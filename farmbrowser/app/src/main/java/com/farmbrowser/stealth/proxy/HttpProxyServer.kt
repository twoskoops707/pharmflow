package com.farmbrowser.stealth.proxy

import android.util.Log
import java.io.*
import java.net.*
import java.util.concurrent.*
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Local HTTP CONNECT proxy server.
 * Listens on 127.0.0.1 and tunnels all CONNECT traffic through a SOCKS5 upstream.
 * This lets Android WebView (which only speaks HTTP proxy) route through Tor SOCKS5.
 *
 * Also supports plain HTTP proxy upstream (pass-through mode).
 */
object HttpProxyServer {
    private const val TAG = "HttpProxyServer"
    private const val LOCAL_HOST = "127.0.0.1"
    const val LOCAL_PORT = 8199

    private var serverSocket: ServerSocket? = null
    private var pool: ExecutorService? = null
    @Volatile var running = false
        private set
    private val starting = AtomicBoolean(false)

    fun start() {
        if (running) return
        if (!starting.compareAndSet(false, true)) return
        try {
            serverSocket = ServerSocket()
            serverSocket!!.reuseAddress = true
            serverSocket!!.bind(InetSocketAddress(LOCAL_HOST, LOCAL_PORT), 50)
            pool = Executors.newCachedThreadPool { r ->
                Thread(r, "farm-proxy-${System.nanoTime()}").apply { isDaemon = true }
            }
            running = true
            Thread({ acceptLoop() }, "farm-proxy-accept").apply { isDaemon = true; start() }
            Log.i(TAG, "HTTP proxy started on $LOCAL_HOST:$LOCAL_PORT")
        } catch (e: Exception) {
            Log.e(TAG, "Failed to start proxy: ${e.message}")
            running = false
        } finally {
            starting.set(false)
        }
    }

    fun stop() {
        running = false
        try { serverSocket?.close() } catch (_: Exception) {}
        pool?.shutdownNow()
        pool = null
        serverSocket = null
        Log.i(TAG, "HTTP proxy stopped")
    }

    private fun acceptLoop() {
        while (running) {
            try {
                val client = serverSocket?.accept() ?: break
                pool?.submit { handleClient(client) }
            } catch (_: SocketException) { break }
            catch (e: Exception) { Log.e(TAG, "Accept error: ${e.message}") }
        }
    }

    private fun handleClient(client: Socket) {
        try {
            client.soTimeout = 60_000
            val input = BufferedInputStream(client.getInputStream(), 8192)
            val output = BufferedOutputStream(client.getOutputStream(), 8192)

            val requestLine = readLine(input) ?: return
            val parts = requestLine.split(" ")
            if (parts.size < 3) return

            val method = parts[0].uppercase()
            val target = parts[1]

            // Read all headers
            val headers = mutableListOf<String>()
            while (true) {
                val line = readLine(input) ?: break
                if (line.isEmpty()) break
                headers.add(line)
            }

            when (method) {
                "CONNECT" -> handleConnect(target, input, output, client)
                "GET", "POST", "PUT", "DELETE", "HEAD", "OPTIONS", "PATCH" -> {
                    handleDirectRequest(method, target, headers, input, output, client)
                }
                else -> {
                    output.write("HTTP/1.1 501 Not Implemented\r\n\r\n".toByteArray())
                    output.flush()
                }
            }
        } catch (e: Exception) {
            Log.d(TAG, "Client error: ${e.message}")
        } finally {
            try { client.close() } catch (_: Exception) {}
        }
    }

    private fun handleConnect(target: String, input: InputStream, output: OutputStream, client: Socket) {
        val (host, port) = parseHostPort(target, 443)
        val upstream = connectUpstream(host, port) ?: run {
            output.write("HTTP/1.1 502 Bad Gateway\r\n\r\n".toByteArray())
            output.flush()
            return
        }
        output.write("HTTP/1.1 200 Connection Established\r\n\r\n".toByteArray())
        output.flush()
        relay(client, upstream, clientInput = input)
    }

    private fun handleDirectRequest(
        method: String, url: String, headers: List<String>,
        input: InputStream, output: OutputStream, client: Socket
    ) {
        val uri = try { URI(url) } catch (_: Exception) { null }
        if (uri == null) {
            output.write("HTTP/1.1 400 Bad Request\r\n\r\n".toByteArray())
            output.flush()
            return
        }
        val host = uri.host ?: ""
        val port = if (uri.port > 0) uri.port else if (uri.scheme == "https") 443 else 80

        val upstream = connectUpstream(host, port) ?: run {
            output.write("HTTP/1.1 502 Bad Gateway\r\n\r\n".toByteArray())
            output.flush()
            return
        }

        try {
            val path = uri.rawPath ?: "/"
            val query = uri.rawQuery
            val fullPath = if (query != null) "$path?$query" else path

            val req = StringBuilder()
            req.append("$method $fullPath HTTP/1.1\r\n")
            req.append("Host: $host:$port\r\n")
            for (h in headers) {
                val lower = h.lowercase()
                if (!lower.startsWith("proxy-") && !lower.startsWith("host:")) {
                    req.append(h).append("\r\n")
                }
            }
            req.append("\r\n")

            val upstreamOut = BufferedOutputStream(upstream.getOutputStream(), 8192)
            upstreamOut.write(req.toString().toByteArray())
            upstreamOut.flush()

            // Pass the BufferedInputStream so relay reads buffered body bytes too
            relay(client, upstream, clientInput = input)
        } catch (e: Exception) {
            try { upstream.close() } catch (_: Exception) {}
        }
    }

    private fun connectUpstream(host: String, port: Int): Socket? {
        return when (ProxyConfig.type) {
            ProxyConfig.Type.SOCKS5 -> connectViaSocks5(host, port)
            ProxyConfig.Type.HTTP -> connectViaHttpProxy(host, port)
            ProxyConfig.Type.NONE -> connectDirect(host, port)
        }
    }

    private fun connectViaSocks5(host: String, port: Int): Socket? {
        try {
            val proxyHost = ProxyConfig.host
            val proxyPort = ProxyConfig.port
            if (proxyHost.isBlank() || proxyPort <= 0) return connectDirect(host, port)

            val sock = Socket()
            sock.connect(InetSocketAddress(proxyHost, proxyPort), 10_000)
            sock.soTimeout = 60_000
            val out = sock.getOutputStream()
            val inp = sock.getInputStream()

            val useAuth = ProxyConfig.username.isNotBlank()

            // SOCKS5 greeting: advertise no-auth + user/pass when credentials are configured
            if (useAuth) {
                out.write(byteArrayOf(0x05, 0x02, 0x00, 0x02))
            } else {
                out.write(byteArrayOf(0x05, 0x01, 0x00))
            }
            out.flush()
            val greeting = ByteArray(2)
            readFully(inp, greeting)
            if (greeting[0] != 0x05.toByte()) { sock.close(); return null }

            // Server-selected method
            val selectedMethod = greeting[1].toInt() and 0xFF
            when (selectedMethod) {
                0x00 -> { /* no auth required */ }
                0x02 -> {
                    // RFC 1929 username/password sub-negotiation
                    if (!useAuth) { sock.close(); return null }
                    val userBytes = ProxyConfig.username.toByteArray()
                    val passBytes = ProxyConfig.password.toByteArray()
                    val authMsg = ByteArray(3 + userBytes.size + 1 + passBytes.size)
                    authMsg[0] = 0x01 // VER
                    authMsg[1] = userBytes.size.toByte()
                    System.arraycopy(userBytes, 0, authMsg, 2, userBytes.size)
                    authMsg[2 + userBytes.size] = passBytes.size.toByte()
                    System.arraycopy(passBytes, 0, authMsg, 3 + userBytes.size, passBytes.size)
                    out.write(authMsg)
                    out.flush()
                    val authResult = ByteArray(2)
                    readFully(inp, authResult)
                    if (authResult[1] != 0x00.toByte()) { sock.close(); return null }
                }
                else -> {
                    // 0xFF = no acceptable methods, or unknown method
                    Log.e(TAG, "SOCKS5 server rejected all methods: $selectedMethod")
                    sock.close()
                    return null
                }
            }

            // SOCKS5 CONNECT request
            val hostBytes = host.toByteArray()
            val connectReq = ByteArray(4 + 1 + hostBytes.size + 2)
            connectReq[0] = 0x05 // VER
            connectReq[1] = 0x01 // CMD: CONNECT
            connectReq[2] = 0x00 // RSV
            connectReq[3] = 0x03 // ATYP: DOMAIN
            connectReq[4] = hostBytes.size.toByte()
            System.arraycopy(hostBytes, 0, connectReq, 5, hostBytes.size)
            connectReq[5 + hostBytes.size] = (port shr 8).toByte()
            connectReq[6 + hostBytes.size] = (port and 0xFF).toByte()
            out.write(connectReq)
            out.flush()

            val resp = ByteArray(10)
            readFully(inp, resp)
            if (resp[1] != 0x00.toByte()) {
                Log.e(TAG, "SOCKS5 CONNECT failed: ${resp[1]}")
                sock.close(); return null
            }
            return sock
        } catch (e: Exception) {
            Log.e(TAG, "SOCKS5 connect error: ${e.message}")
            return null
        }
    }

    private fun connectViaHttpProxy(host: String, port: Int): Socket? {
        try {
            val proxyHost = ProxyConfig.host
            val proxyPort = ProxyConfig.port
            if (proxyHost.isBlank() || proxyPort <= 0) return connectDirect(host, port)

            val sock = Socket()
            sock.connect(InetSocketAddress(proxyHost, proxyPort), 10_000)
            sock.soTimeout = 60_000
            val out = sock.getOutputStream()
            val inp = sock.getInputStream()

            val connectReq = "CONNECT $host:$port HTTP/1.1\r\nHost: $host:$port\r\n"
            val authReq = if (ProxyConfig.username.isNotBlank()) {
                val creds = java.util.Base64.getEncoder().encodeToString(
                    "${ProxyConfig.username}:${ProxyConfig.password}".toByteArray()
                )
                "Proxy-Authorization: Basic $creds\r\n"
            } else ""

            out.write("$connectReq${authReq}\r\n".toByteArray())
            out.flush()

            val status = readLine(inp) ?: run { sock.close(); return null }
            if (!status.contains("200")) {
                Log.e(TAG, "HTTP proxy CONNECT failed: $status")
                sock.close(); return null
            }
            // Skip remaining headers
            while (true) {
                val line = readLine(inp) ?: break
                if (line.isEmpty()) break
            }
            return sock
        } catch (e: Exception) {
            Log.e(TAG, "HTTP proxy connect error: ${e.message}")
            return null
        }
    }

    private fun connectDirect(host: String, port: Int): Socket? {
        return try {
            val sock = Socket()
            sock.connect(InetSocketAddress(host, port), 10_000)
            sock.soTimeout = 60_000
            sock
        } catch (e: Exception) {
            Log.e(TAG, "Direct connect failed: ${e.message}")
            null
        }
    }

    private fun relay(client: Socket, upstream: Socket, clientInput: InputStream? = null) {
        val latch = java.util.concurrent.CountDownLatch(2)

        // Use the pre-buffered stream if provided, so bytes already read into
        // BufferedInputStream's internal buffer aren't silently lost.
        val clientStream = clientInput ?: client.getInputStream()

        fun copyOne(inp: InputStream, outp: OutputStream, srcClosed: () -> Boolean, dstClosed: () -> Boolean, label: String) {
            try {
                val buf = ByteArray(65536)
                while (!srcClosed() && !dstClosed()) {
                    val n = inp.read(buf)
                    if (n == -1) break
                    if (n == 0) continue
                    outp.write(buf, 0, n)
                    outp.flush()
                }
            } catch (e: java.net.SocketException) {
                Log.d(TAG, "$label relay ended: ${e.message}")
            } catch (e: IOException) {
                Log.d(TAG, "$label relay ended: ${e.message}")
            } catch (e: Exception) {
                Log.d(TAG, "$label relay error: ${e.message}")
            } finally {
                latch.countDown()
            }
        }

        // Thread 1: client -> upstream (uses the pre-buffered input stream)
        Thread({
            copyOne(clientStream, upstream.getOutputStream(),
                { client.isClosed }, { upstream.isClosed }, "c->u")
        }, "proxy-c2u").apply {
            isDaemon = true
            start()
        }
        // Thread 2: upstream -> client
        Thread({
            copyOne(upstream.getInputStream(), client.getOutputStream(),
                { upstream.isClosed }, { client.isClosed }, "u->c")
        }, "proxy-u2c").apply {
            isDaemon = true
            start()
        }

        // Wait for both directions to finish (or timeout)
        try {
            latch.await(300, java.util.concurrent.TimeUnit.SECONDS)
        } catch (_: InterruptedException) {}

        // Clean shutdown: close both sockets to unblock the other thread
        try { client.close() } catch (_: Exception) {}
        try { upstream.close() } catch (_: Exception) {}
    }

    private fun parseHostPort(target: String, defaultPort: Int): Pair<String, Int> {
        val colonIdx = target.lastIndexOf(':')
        if (colonIdx > 0) {
            val host = target.substring(0, colonIdx)
            val port = target.substring(colonIdx + 1).toIntOrNull() ?: defaultPort
            return Pair(host, port)
        }
        return Pair(target, defaultPort)
    }

    private fun readLine(input: InputStream): String? {
        val sb = StringBuilder()
        var prev = -1
        while (true) {
            val b = input.read()
            if (b == -1) return if (sb.isEmpty()) null else sb.toString()
            if (b == '\n'.code && prev == '\r'.code) {
                return sb.toString()
            }
            if (b != '\r'.code) {
                sb.append(b.toChar())
            }
            prev = b
        }
    }

    private fun readFully(input: InputStream, buf: ByteArray) {
        var offset = 0
        while (offset < buf.size) {
            val n = input.read(buf, offset, buf.size - offset)
            if (n <= 0) throw IOException("Unexpected EOF")
            offset += n
        }
    }

    /**
     * Test if the local proxy is reachable.
     */
    fun testConnection(): Boolean {
        return try {
            val sock = Socket()
            sock.connect(InetSocketAddress("127.0.0.1", LOCAL_PORT), 3000)
            sock.close()
            true
        } catch (_: Exception) { false }
    }

    /**
     * Test if the upstream proxy is reachable through the local tunnel.
     */
    fun testUpstream(): Boolean {
        return try {
            val url = URL("http://icanhazip.com")
            val conn = url.openConnection(java.net.Proxy(
                java.net.Proxy.Type.HTTP,
                InetSocketAddress("127.0.0.1", LOCAL_PORT)
            )) as HttpURLConnection
            conn.connectTimeout = 10000
            conn.readTimeout = 10000
            conn.setRequestProperty("User-Agent", "FarmBrowser/1.0")
            val code = conn.responseCode
            conn.disconnect()
            code == 200
        } catch (_: Exception) { false }
    }
}

package com.farmbrowser.stealth.proxy

import android.content.Context
import android.content.Intent
import android.os.Build
import android.provider.Settings
import android.util.Log
import java.net.InetSocketAddress
import java.net.Socket

/**
 * Central proxy manager.
 * - Auto-detects host Tor proxy via system http_proxy or ADB reverse port.
 * - Starts/stops local HTTP tunnel for SOCKS5 backends.
 * - Provides the correct proxy URL for WebView configuration.
 */
object ProxyManager {
    private const val TAG = "ProxyManager"

    /**
     * Known PharmFlow Tor HTTP tunnel ports (host side, exposed via adb reverse).
     * Phone 0 = 8118, Phone 1 = 8119, etc. (HTTP_TUNNEL_BASE + phone_idx)
     */
    private const val PHARMFLOW_HTTP_BASE = 8118

    /**
     * Known PharmFlow Tor SOCKS ports (host side).
     * Phone 0 = 9050, Phone 1 = 9051, etc. (BASE_PORT + phone_idx)
     */
    private const val PHARMFLOW_SOCKS_BASE = 9050

    /**
     * Common local ports where Tor HTTP tunnel may be exposed via adb reverse.
     */
    private val CANDIDATE_PORTS = listOf(8118, 8119, 8120, 9050, 9051, 9150, 8199)

    @Volatile
    var activeMode: ProxyMode = ProxyMode.DIRECT
        private set

    enum class ProxyMode { DIRECT, TOR_SOCKS, TOR_HTTP, CUSTOM }

    /**
     * Initialize proxy from system settings and auto-detect Tor.
     */
    fun initFromSystem(context: Context): ProxyMode {
        // 1. Check if user has configured a custom proxy
        if (ProxyConfig.isActive) {
            return if (ProxyConfig.type == ProxyConfig.Type.SOCKS5) {
                ensureLocalTunnel()
                activeMode = ProxyMode.TOR_SOCKS
                ProxyMode.TOR_SOCKS
            } else {
                activeMode = ProxyMode.CUSTOM
                ProxyMode.CUSTOM
            }
        }

        // 2. Try Android system proxy
        val systemProxy = getSystemHttpProxy(context)
        if (systemProxy != null) {
            val (host, port) = systemProxy
            if (port > 0 && host.isNotBlank()) {
                Log.i(TAG, "Detected system proxy: $host:$port")
                ProxyConfig.host = host
                ProxyConfig.port = port
                ProxyConfig.type = ProxyConfig.Type.HTTP
                ProxyConfig.enabled = true
                activeMode = ProxyMode.TOR_HTTP
                return ProxyMode.TOR_HTTP
            }
        }

        // 3. Auto-detect Tor via common ports (adb reverse)
        if (ProxyConfig.autoDetectTor) {
            val detected = detectTorProxy()
            if (detected != null) {
                val (host, port, isSocks) = detected
                Log.i(TAG, "Auto-detected Tor proxy: $host:$port (socks=$isSocks)")
                ProxyConfig.host = host
                ProxyConfig.port = port
                ProxyConfig.type = if (isSocks) ProxyConfig.Type.SOCKS5 else ProxyConfig.Type.HTTP
                ProxyConfig.enabled = true
                if (isSocks) {
                    ensureLocalTunnel()
                    activeMode = ProxyMode.TOR_SOCKS
                    return ProxyMode.TOR_SOCKS
                } else {
                    activeMode = ProxyMode.TOR_HTTP
                    return ProxyMode.TOR_HTTP
                }
            }
        }

        activeMode = ProxyMode.DIRECT
        return ProxyMode.DIRECT
    }

    /**
     * Read Android system global http_proxy setting.
     */
    private fun getSystemHttpProxy(context: Context): Pair<String, Int>? {
        try {
            // Try global http_proxy
            val proxy = Settings.Global.getString(context.contentResolver, "http_proxy")
            if (!proxy.isNullOrBlank() && proxy != ":0" && proxy != "null") {
                val parts = proxy.split(":")
                if (parts.size == 2) {
                    val host = parts[0].trim()
                    val port = parts[1].trim().toIntOrNull() ?: 0
                    if (host.isNotBlank() && port > 0) return Pair(host, port)
                }
            }
        } catch (_: Exception) {}

        try {
            // Try split settings
            val host = Settings.Global.getString(context.contentResolver, "global_http_proxy_host")
            val port = Settings.Global.getString(context.contentResolver, "global_http_proxy_port")
            if (!host.isNullOrBlank() && host != "null") {
                val p = port?.toIntOrNull() ?: 0
                if (p > 0) return Pair(host.trim(), p)
            }
        } catch (_: Exception) {}

        return null
    }

    /**
     * Probe common Tor ports to see if one is reachable.
     */
    private fun detectTorProxy(): Triple<String, Int, Boolean>? {
        for (port in CANDIDATE_PORTS) {
            if (isPortOpen("127.0.0.1", port, 500)) {
                // SOCKS ports are 9050+, HTTP tunnel ports are 8118+
                val isSocks = port in 9000..9999
                return Triple("127.0.0.1", port, isSocks)
            }
        }
        return null
    }

    private fun isPortOpen(host: String, port: Int, timeoutMs: Int): Boolean {
        return try {
            Socket().use { it.connect(InetSocketAddress(host, port), timeoutMs); true }
        } catch (_: Exception) { false }
    }

    /**
     * Start the local HTTP-to-SOCKS5 tunnel if we're using a SOCKS5 upstream.
     */
    fun ensureLocalTunnel() {
        if (!HttpProxyServer.running && ProxyConfig.type == ProxyConfig.Type.SOCKS5) {
            HttpProxyServer.start()
        }
    }

    /**
     * Stop the local tunnel.
     */
    fun stopTunnel() {
        HttpProxyServer.stop()
    }

    /**
     * Get the HTTP proxy URL that WebView should use.
     * - For HTTP upstream: returns the upstream directly.
     * - For SOCKS5 upstream: returns the local HTTP tunnel.
     * - For direct: returns null.
     */
    fun getWebViewProxyUrl(): String? {
        return when (activeMode) {
            ProxyMode.DIRECT -> null
            ProxyMode.TOR_HTTP, ProxyMode.CUSTOM -> ProxyConfig.httpProxyUrl()
            ProxyMode.TOR_SOCKS -> {
                // WebView needs HTTP proxy; use local tunnel
                ensureLocalTunnel()
                "http://127.0.0.1:${HttpProxyServer.LOCAL_PORT}"
            }
        }
    }

    /**
     * Force-set proxy from ADB (used by PharmFlow automation).
     * PharmFlow does: settings put global http_proxy host:port
     */
    fun applyFromAdbProxy(context: Context, host: String, port: Int, isSocks: Boolean = false) {
        ProxyConfig.host = host
        ProxyConfig.port = port
        ProxyConfig.type = if (isSocks) ProxyConfig.Type.SOCKS5 else ProxyConfig.Type.HTTP
        ProxyConfig.enabled = true
        if (isSocks) {
            ensureLocalTunnel()
            activeMode = ProxyMode.TOR_SOCKS
        } else {
            activeMode = ProxyMode.TOR_HTTP
        }
        Log.i(TAG, "Proxy set from ADB: $host:$port (socks=$isSocks)")
    }

    /**
     * Clear all proxy settings.
     */
    fun clearProxy(context: Context) {
        ProxyConfig.enabled = false
        ProxyConfig.host = ""
        ProxyConfig.port = 0
        ProxyConfig.type = ProxyConfig.Type.NONE
        stopTunnel()
        activeMode = ProxyMode.DIRECT
        // Clear system proxy too
        try {
            Settings.Global.putString(context.contentResolver, "http_proxy", ":0")
            Settings.Global.putString(context.contentResolver, "global_http_proxy_host", "")
            Settings.Global.putString(context.contentResolver, "global_http_proxy_port", "")
        } catch (_: Exception) {}
    }

    /**
     * Full status report for debugging.
     */
    fun statusReport(): Map<String, String> {
        return mapOf(
            "mode" to activeMode.name,
            "enabled" to ProxyConfig.enabled.toString(),
            "type" to ProxyConfig.type.name,
            "host" to ProxyConfig.host,
            "port" to ProxyConfig.port.toString(),
            "http_tunnel_running" to HttpProxyServer.running.toString(),
            "http_tunnel_port" to HttpProxyServer.LOCAL_PORT.toString(),
            "webview_proxy" to (getWebViewProxyUrl() ?: "none"),
        )
    }
}

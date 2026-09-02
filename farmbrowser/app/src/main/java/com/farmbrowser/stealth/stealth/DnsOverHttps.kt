package com.farmbrowser.stealth.stealth

import android.util.Base64
import android.util.Log
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.File
import java.net.InetAddress
import java.net.UnknownHostException
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.TimeUnit

/**
 * DNS-over-HTTPS (DoH) to prevent DNS leaks through Tor.
 *
 * When traffic routes through Tor, regular DNS queries can bypass the tunnel
 * and go directly to the system resolver, leaking visited domains.  DoH
 * encrypts DNS queries inside HTTPS so they travel through the same Tor tunnel.
 *
 * This implements RFC 8484 (wireformat DNS-over-HTTPS) using raw OkHttp,
 * avoiding the separate okhttp3-doh dependency.
 *
 * Flow:
 *   1. Build DNS wire-format query for A record
 *   2. Base64url-encode and send to DoH provider as ?dns= query param
 *   3. Parse the response to extract IP addresses
 *   4. Cache results in-memory for fast repeat lookups
 */
object DnsOverHttps {

    private const val TAG = "DnsOverHttps"

    /** DoH provider URLs (RFC 8484). */
    private val DOH_PROVIDERS = listOf(
        "https://cloudflare-dns.com/dns-query",
        "https://dns.quad9.net/dns-query",
        "https://dns.google/dns-query",
    )

    @Volatile
    private var initialized = false

    /** The working DoH provider URL (set after first successful resolution). */
    @Volatile
    private var activeProvider: String? = null

    private var client: OkHttpClient? = null

    // In-memory DNS cache
    private val cache = ConcurrentHashMap<String, List<InetAddress>>()
    private val failedHosts = ConcurrentHashMap<String, Long>()
    private const val CACHE_TTL_MS = 5 * 60 * 1000L

    fun init(cacheDir: File) {
        if (initialized) return

        client = OkHttpClient.Builder()
            .cache(okhttp3.Cache(File(cacheDir, "doh_cache"), 10L * 1024 * 1024))
            .connectTimeout(5, TimeUnit.SECONDS)
            .readTimeout(5, TimeUnit.SECONDS)
            .build()

        // Probe providers to find one that works
        Thread({
            for (provider in DOH_PROVIDERS) {
                try {
                    val result = dohLookup(provider, "example.com")
                    if (result.isNotEmpty()) {
                        activeProvider = provider
                        Log.i(TAG, "DoH initialized with provider: $provider")
                        initialized = true
                        return@Thread
                    }
                } catch (_: Exception) {}
            }
            Log.w(TAG, "All DoH providers failed — DNS leaks possible")
            initialized = true
        }, "doh-init").start()
    }

    /**
     * Resolve a hostname via DoH.
     * Returns list of InetAddress or null (caller should fall back to system DNS).
     */
    fun resolve(hostname: String): List<InetAddress>? {
        val host = hostname.trim().lowercase()
        if (host.isEmpty() || host == "localhost" || host == "127.0.0.1" || host == "::1") {
            return null
        }

        // Check cache
        cache[host]?.let { return it }

        // Check recent failure
        failedHosts[host]?.let { ts ->
            if (System.currentTimeMillis() - ts < CACHE_TTL_MS) return null
        }

        // Resolve via DoH
        val provider = activeProvider ?: return null
        try {
            val addresses = dohLookup(provider, host)
            if (addresses.isNotEmpty()) {
                cache[host] = addresses
                Log.d(TAG, "DoH resolved $host → ${addresses[0].hostAddress}")
                return addresses
            }
        } catch (e: Exception) {
            Log.d(TAG, "DoH failed for $host: ${e.message}")
            failedHosts[host] = System.currentTimeMillis()
        }

        return null
    }

    fun clearCache() {
        cache.clear()
        failedHosts.clear()
    }

    fun isAvailable(): Boolean = activeProvider != null

    fun statusInfo(): Map<String, String> = mapOf(
        "enabled" to isAvailable().toString(),
        "provider" to (activeProvider ?: "none"),
        "cached" to cache.size.toString(),
    )

    // ── Internal DoH implementation ──────────────────────────────────

    /**
     * Build a DNS wireformat A-record query and send it to the DoH provider.
     */
    private fun dohLookup(provider: String, hostname: String): List<InetAddress> {
        val httpClient = client ?: throw IllegalStateException("DoH not initialized")
        val dnsPacket = buildDnsQuery(hostname)
        val dnsB64 = Base64.encodeToString(dnsPacket, Base64.URL_SAFE or Base64.NO_WRAP or Base64.NO_PADDING)

        val url = "$provider?dns=$dnsB64"
        val request = Request.Builder()
            .url(url)
            .header("Accept", "application/dns-message")
            .header("User-Agent", "FarmBrowser/1.0")
            .get()
            .build()

        val response = httpClient.newCall(request).execute()
        if (!response.isSuccessful) {
            throw Exception("DoH HTTP ${response.code}")
        }

        val body = response.body?.bytes() ?: throw Exception("Empty DoH response")
        return parseDnsResponse(body)
    }

    /**
     * Build a DNS wireformat query for A record (type 1).
     * Format: Header(12B) + Question(Name + Type(2) + Class(2))
     */
    private fun buildDnsQuery(hostname: String): ByteArray {
        val output = mutableListOf<Byte>()

        // ── Header (12 bytes) ──
        val txnId = (Math.random() * 65535).toInt()
        output.addAll(listOf(
            ((txnId shr 8) and 0xFF).toByte(),
            (txnId and 0xFF).toByte(),  // Transaction ID
            0x01, 0x00,  // Flags: standard query, recursion desired
            0x00, 0x01,  // Questions: 1
            0x00, 0x00,  // Answer RRs: 0
            0x00, 0x00,  // Authority RRs: 0
            0x00, 0x00,  // Additional RRs: 0
        ))

        // ── Question: domain name in DNS format ──
        for (label in hostname.split(".")) {
            output.add(label.length.toByte())
            for (c in label.toByteArray()) output.add(c)
        }
        output.add(0x00)  // Root label (end of name)

        // Type A (1), Class IN (1)
        output.addAll(listOf(0x00, 0x01, 0x00, 0x01))

        return output.toByteArray()
    }

    /**
     * Parse DNS wireformat response, extracting A-record IP addresses.
     */
    private fun parseDnsResponse(data: ByteArray): List<InetAddress> {
        if (data.size < 12) throw Exception("DNS response too short")

        val answerCount = ((data[6].toInt() and 0xFF) shl 8) or (data[7].toInt() and 0xFF)

        // Skip header (12 bytes) + question section
        var offset = 12
        // Skip question name
        while (offset < data.size && data[offset] != 0.toByte()) {
            val labelLen = data[offset].toInt() and 0xFF
            offset += 1 + labelLen
        }
        offset += 5  // null byte + type(2) + class(2)

        // Parse answer section
        val addresses = mutableListOf<InetAddress>()
        for (i in 0 until answerCount) {
            if (offset + 12 > data.size) break

            // Skip name (could be pointer)
            if ((data[offset].toInt() and 0xC0) == 0xC0) {
                offset += 2  // pointer
            } else {
                while (offset < data.size && data[offset] != 0.toByte()) {
                    offset += 1 + (data[offset].toInt() and 0xFF)
                }
                offset += 1  // null terminator
            }

            val type = ((data[offset].toInt() and 0xFF) shl 8) or (data[offset + 1].toInt() and 0xFF)
            val rdLength = ((data[offset + 8].toInt() and 0xFF) shl 8) or (data[offset + 9].toInt() and 0xFF)
            offset += 10

            if (type == 1 && rdLength == 4 && offset + 4 <= data.size) {
                // A record
                val ip = InetAddress.getByAddress(data.sliceArray(offset until offset + 4))
                addresses.add(ip)
            }
            offset += rdLength
        }

        return addresses
    }
}

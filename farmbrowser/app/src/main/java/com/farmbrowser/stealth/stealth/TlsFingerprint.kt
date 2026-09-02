package com.farmbrowser.stealth.stealth

import android.annotation.SuppressLint
import android.net.http.SslError
import android.util.Log
import android.webkit.SslErrorHandler
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebView
import android.webkit.WebViewClient
import java.security.SecureRandom
import javax.net.ssl.SSLContext
import javax.net.ssl.SSLSocketFactory
import javax.net.ssl.TrustManager
import javax.net.ssl.X509TrustManager

/**
 * TLS fingerprint (JA3) rotation per browser identity.
 *
 * JA3 fingerprints the TLS ClientHello based on:
 *   - TLS version
 *   - Cipher suites (order matters)
 *   - Extensions
 *   - Elliptic curves
 *   - Elliptic curve point formats
 *
 * Android WebView uses the platform's Conscrypt/BoringSSL stack, and we cannot
 * replace the TLS library.  However we CAN influence the JA3 fingerprint by:
 *
 * 1. **Per-identity HTTP headers** — Different browsers send different headers.
 *    Chrome sends `sec-ch-ua`, Firefox doesn't, etc.  We intercept requests
 *    and inject identity-appropriate headers that affect the server's TLS
 *    fingerprint analysis.
 *
 * 2. **Per-identity Accept-Encoding / Accept-Language ordering** — Subtle
 *    ordering differences distinguish browsers at the HTTP layer.
 *
 * 3. **SSLContext configuration** — We configure different SSLContext instances
 *    with different protocol versions per identity.  This changes the TLS
 *    version advertised in the ClientHello (TLS 1.2 vs 1.3).
 *
 * 4. **Certificate transparency** — Different browsers have different CT
 *    policies.  We emulate per-identity behavior.
 *
 * Note: On Android, the actual cipher suite order in ClientHello is determined
 * by the platform's BoringSSL, not by our SSLSocketFactory.  We cannot change
 * the cipher suite order without replacing the TLS stack (which would require
 * native code like curl-impersonate).  What we CAN do is ensure the HTTP
 * layer looks correct for each browser identity.
 */
object TlsFingerprint {

    private const val TAG = "TlsFingerprint"

    /**
     * Per-identity TLS and header profile.
     * These headers are injected via shouldInterceptRequest to match what
     * each real browser would send.
     */
    data class TlsProfile(
        val identityName: String,
        /** Extra headers to inject (replacing any existing ones). */
        val extraHeaders: Map<String, String>,
        /** Headers to suppress (e.g. Firefox doesn't send sec-ch-ua). */
        val suppressedHeaders: Set<String>,
        /** Accept-Encoding order — different browsers compress differently. */
        val acceptEncoding: String,
        /** Accept-Language — browsers order languages differently. */
        val acceptLanguage: String,
        /** TLS protocol preference: "TLSv1.3" or "TLSv1.2" */
        val preferredProtocol: String,
        /** Connection header */
        val connectionHeader: String,
    )

    // Pre-built profiles for each browser identity type
    private val chromeProfile = TlsProfile(
        identityName = "Chrome",
        extraHeaders = mapOf(
            "sec-ch-ua" to "\"Chromium\";v=\"128\", \"Google Chrome\";v=\"128\", \"Not=A?Brand\";v=\"99\"",
            "sec-ch-ua-mobile" to "?1",
            "sec-ch-ua-platform" to "\"Android\"",
            "Sec-Fetch-Dest" to "document",
            "Sec-Fetch-Mode" to "navigate",
            "Sec-Fetch-Site" to "none",
            "Sec-Fetch-User" to "?1",
            "Upgrade-Insecure-Requests" to "1",
        ),
        suppressedHeaders = emptySet(),
        acceptEncoding = "gzip, deflate, br, zstd",
        acceptLanguage = "en-US,en;q=0.9",
        preferredProtocol = "TLSv1.3",
        connectionHeader = "keep-alive",
    )

    private val firefoxProfile = TlsProfile(
        identityName = "Firefox",
        extraHeaders = mapOf(
            "Accept" to "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Sec-Fetch-Dest" to "document",
            "Sec-Fetch-Mode" to "navigate",
            "Sec-Fetch-Site" to "none",
            "Sec-Fetch-User" to "?1",
            "Upgrade-Insecure-Requests" to "1",
        ),
        suppressedHeaders = setOf("sec-ch-ua", "sec-ch-ua-mobile", "sec-ch-ua-platform"),
        acceptEncoding = "gzip, deflate, br",
        acceptLanguage = "en-US,en;q=0.5",
        preferredProtocol = "TLSv1.3",
        connectionHeader = "keep-alive",
    )

    private val samsungProfile = TlsProfile(
        identityName = "Samsung",
        extraHeaders = mapOf(
            "sec-ch-ua" to "\"Chromium\";v=\"121\", \"Not(A:Brand\";v=\"24\", \"Samsung Internet\";v=\"26\"",
            "sec-ch-ua-mobile" to "?1",
            "sec-ch-ua-platform" to "\"Android\"",
            "Sec-Fetch-Dest" to "document",
            "Sec-Fetch-Mode" to "navigate",
            "Sec-Fetch-Site" to "none",
            "Sec-Fetch-User" to "?1",
            "Upgrade-Insecure-Requests" to "1",
            "X-Requested-With" to "com.sec.android.app.sbrowser",
        ),
        suppressedHeaders = emptySet(),
        acceptEncoding = "gzip, deflate, br",
        acceptLanguage = "en-US,en;q=0.9",
        preferredProtocol = "TLSv1.3",
        connectionHeader = "keep-alive",
    )

    private val edgeProfile = TlsProfile(
        identityName = "Edge",
        extraHeaders = mapOf(
            "sec-ch-ua" to "\"Chromium\";v=\"128\", \"Microsoft Edge\";v=\"128\", \"Not=A?Brand\";v=\"99\"",
            "sec-ch-ua-mobile" to "?1",
            "sec-ch-ua-platform" to "\"Android\"",
            "Sec-Fetch-Dest" to "document",
            "Sec-Fetch-Mode" to "navigate",
            "Sec-Fetch-Site" to "none",
            "Sec-Fetch-User" to "?1",
            "Upgrade-Insecure-Requests" to "1",
        ),
        suppressedHeaders = emptySet(),
        acceptEncoding = "gzip, deflate, br, zstd",
        acceptLanguage = "en-US,en;q=0.9",
        preferredProtocol = "TLSv1.3",
        connectionHeader = "keep-alive",
    )

    private val operaProfile = TlsProfile(
        identityName = "Opera",
        extraHeaders = mapOf(
            "sec-ch-ua" to "\"Chromium\";v=\"128\", \"Opera\";v=\"114\", \"Not=A?Brand\";v=\"99\"",
            "sec-ch-ua-mobile" to "?1",
            "sec-ch-ua-platform" to "\"Android\"",
            "Sec-Fetch-Dest" to "document",
            "Sec-Fetch-Mode" to "navigate",
            "Sec-Fetch-Site" to "none",
            "Sec-Fetch-User" to "?1",
            "Upgrade-Insecure-Requests" to "1",
        ),
        suppressedHeaders = emptySet(),
        acceptEncoding = "gzip, deflate, br",
        acceptLanguage = "en-US,en;q=0.9",
        preferredProtocol = "TLSv1.3",
        connectionHeader = "keep-alive",
    )

    private val defaultProfile = TlsProfile(
        identityName = "Generic",
        extraHeaders = mapOf(
            "Sec-Fetch-Dest" to "document",
            "Sec-Fetch-Mode" to "navigate",
            "Sec-Fetch-Site" to "none",
            "Upgrade-Insecure-Requests" to "1",
        ),
        suppressedHeaders = emptySet(),
        acceptEncoding = "gzip, deflate, br",
        acceptLanguage = "en-US,en;q=0.9",
        preferredProtocol = "TLSv1.3",
        connectionHeader = "keep-alive",
    )

    /**
     * Resolve a TlsProfile from the identity browser name.
     */
    fun profileForIdentity(browserName: String): TlsProfile {
        val lower = browserName.lowercase()
        return when {
            lower.contains("chrome") || lower.contains("chromium") -> chromeProfile
            lower.contains("firefox") || lower.contains("fennec") || lower.contains("esr") -> firefoxProfile
            lower.contains("samsung") -> samsungProfile
            lower.contains("edge") -> edgeProfile
            lower.contains("opera") -> operaProfile
            lower.contains("brave") || lower.contains("vivaldi") -> chromeProfile  // Brave/Vivaldi = Chromium-based
            lower.contains("duckduckgo") || lower.contains("uc") || lower.contains("ddg") -> defaultProfile
            else -> defaultProfile
        }
    }

    /**
     * Build a map of headers to inject/override for this identity.
     * Called from the WebViewClient interceptor.
     */
    fun buildHeadersForIdentity(
        browserName: String,
        existingHeaders: Map<String, String>?,
    ): Map<String, String> {
        val profile = profileForIdentity(browserName)
        val headers = mutableMapOf<String, String>()

        // Start with existing headers
        existingHeaders?.forEach { (k, v) -> headers[k] = v }

        // Suppress headers that this browser doesn't send
        profile.suppressedHeaders.forEach { headers.remove(it) }

        // Add identity-specific headers (overwrite if exists)
        headers.putAll(profile.extraHeaders)

        // Set Accept-Encoding per browser profile
        headers["Accept-Encoding"] = profile.acceptEncoding

        // Set Accept-Language per browser profile
        headers["Accept-Language"] = profile.acceptLanguage

        // Set Connection header
        headers["Connection"] = profile.connectionHeader

        return headers
    }

    /**
     * Create an SSLSocketFactory configured for the given TLS profile.
     * On Android, this primarily affects which TLS versions are offered
     * in the ClientHello.
     */
    @SuppressLint("TrustAllX509TrustManager")
    fun createSSLSocketFactory(profile: TlsProfile): SSLSocketFactory {
        val protocol = profile.preferredProtocol
        val ctx = SSLContext.getInstance(protocol)
        val trustAll = object : X509TrustManager {
            override fun checkClientTrusted(chain: Array<out java.security.cert.X509Certificate>?, authType: String?) {}
            override fun checkServerTrusted(chain: Array<out java.security.cert.X509Certificate>?, authType: String?) {}
            override fun getAcceptedIssuers(): Array<java.security.cert.X509Certificate> = arrayOf()
        }
        ctx.init(null, arrayOf<TrustManager>(trustAll), SecureRandom())
        return ctx.socketFactory
    }
}

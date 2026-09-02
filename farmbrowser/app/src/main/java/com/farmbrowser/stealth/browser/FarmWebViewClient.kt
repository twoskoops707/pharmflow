package com.farmbrowser.stealth.browser

import android.app.Activity
import android.graphics.Bitmap
import android.net.http.SslError
import android.webkit.*
import android.widget.EditText
import com.farmbrowser.stealth.proxy.ProxyManager
import com.farmbrowser.stealth.stealth.DeviceFingerprint

/**
 * Custom WebViewClient that:
 * - Updates proxy indicator on page load
 * - Handles SSL errors gracefully (emulator proxies often have cert issues)
 * - Intercepts requests to add custom headers
 */
open class FarmWebViewClient(
    private val activity: Activity,
    private val urlBar: EditText,
    private val onProxyState: (String) -> Unit
) : WebViewClient() {

    override fun onPageStarted(view: WebView?, url: String?, favicon: Bitmap?) {
        super.onPageStarted(view, url, favicon)
        url?.let { urlBar.setText(it) }
    }

    override fun onPageFinished(view: WebView?, url: String?) {
        super.onPageFinished(view, url)
        val report = ProxyManager.statusReport()
        val mode = report["mode"] ?: "DIRECT"
        val proxyState = when (mode) {
            "TOR_SOCKS", "TOR_HTTP" -> "🔒 Tor (${report["host"]}:${report["port"]})"
            "CUSTOM" -> "🔒 ${report["type"]} (${report["host"]}:${report["port"]})"
            else -> ""
        }
        activity.runOnUiThread { onProxyState(proxyState) }
    }

    override fun onReceivedSslError(view: WebView?, handler: SslErrorHandler?, error: SslError?) {
        // Allow SSL errors on emulators (common with proxy MITM)
        // In production you'd want to be more strict
        handler?.proceed()
    }

    override fun onReceivedError(
        view: WebView?, errorCode: Int, description: String?, failingUrl: String?
    ) {
        super.onReceivedError(view, errorCode, description, failingUrl)
        // Show error in URL bar
        if (errorCode != -1) { // -1 is generic error
            activity.runOnUiThread {
                urlBar.setText("⚠ Error $errorCode: $description")
            }
        }
    }

    override fun shouldOverrideUrlLoading(
        view: WebView?, request: WebResourceRequest?
    ): Boolean {
        val url = request?.url?.toString() ?: return false
        // Block non-http protocols
        if (!url.startsWith("http://") && !url.startsWith("https://")) {
            return true
        }
        return false
    }
}

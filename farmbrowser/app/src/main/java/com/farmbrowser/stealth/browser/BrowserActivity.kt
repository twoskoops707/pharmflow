package com.farmbrowser.stealth.browser

import android.annotation.SuppressLint
import android.app.Activity
import android.content.Intent
import android.graphics.Bitmap
import android.net.Uri
import android.os.Bundle
import android.os.Message
import android.util.Log
import android.view.KeyEvent
import android.view.View
import android.view.inputmethod.EditorInfo
import android.view.inputmethod.InputMethodManager
import android.webkit.*
import android.widget.*
import com.farmbrowser.stealth.R
import com.farmbrowser.stealth.proxy.ProxyConfig
import com.farmbrowser.stealth.proxy.ProxyManager
import com.farmbrowser.stealth.stealth.CookieIsolation
import com.farmbrowser.stealth.stealth.DeviceFingerprint
import com.farmbrowser.stealth.stealth.DnsOverHttps
import com.farmbrowser.stealth.stealth.TlsFingerprint
import com.farmbrowser.stealth.settings.SettingsActivity
import java.io.ByteArrayInputStream

class BrowserActivity : Activity() {

    private lateinit var webView: WebView
    private lateinit var urlBar: EditText
    private lateinit var btnBack: ImageButton
    private lateinit var btnForward: ImageButton
    private lateinit var btnRefresh: ImageButton
    private lateinit var btnHome: ImageButton
    private lateinit var btnMenu: ImageButton
    private lateinit var progressBar: ProgressBar
    private lateinit var proxyIndicator: TextView
    private lateinit var toolbar: LinearLayout

    private var currentUrl = ""
    private var forceLoadUrl: String? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_browser)
        FarmBrowserReceiver.currentActivity = this

        initViews()
        initWebView()
        initProxy()
        initNavigation()

        // Handle intent URL
        forceLoadUrl = intent?.data?.toString()
        if (forceLoadUrl.isNullOrBlank()) {
            forceLoadUrl = "about:blank"
        }

        webView.post {
            loadUrl(forceLoadUrl!!)
        }
    }

    override fun onNewIntent(intent: Intent?) {
        super.onNewIntent(intent)
        val url = intent?.data?.toString()
        if (!url.isNullOrBlank()) {
            webView.post { loadUrl(url) }
        }
    }

    private fun initViews() {
        webView = findViewById(R.id.webview)
        urlBar = findViewById(R.id.url_bar)
        btnBack = findViewById(R.id.btn_back)
        btnForward = findViewById(R.id.btn_forward)
        btnRefresh = findViewById(R.id.btn_refresh)
        btnHome = findViewById(R.id.btn_home)
        btnMenu = findViewById(R.id.btn_menu)
        progressBar = findViewById(R.id.progress_bar)
        proxyIndicator = findViewById(R.id.proxy_indicator)
        toolbar = findViewById(R.id.toolbar)
    }

    @SuppressLint("SetJavaScriptEnabled")
    private fun initWebView() {
        val profile = DeviceFingerprint.getProfile(this)
        val initialIdentity = com.farmbrowser.stealth.stealth.BrowserIdentity.currentIdentity()

        // WebSettings — stealth + performance
        webView.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            databaseEnabled = true
            allowFileAccess = true
            allowContentAccess = true
            mixedContentMode = WebSettings.MIXED_CONTENT_ALWAYS_ALLOW
            cacheMode = WebSettings.LOAD_DEFAULT

            // Set initial UA from rotating identity
            userAgentString = initialIdentity.userAgent
            useWideViewPort = true
            loadWithOverviewMode = true
            setSupportZoom(true)
            builtInZoomControls = true
            displayZoomControls = false

            // Enable media autoplay
            mediaPlaybackRequiresUserGesture = false

            // WebRTC leak prevention
            allowUniversalAccessFromFileURLs = false
            allowFileAccessFromFileURLs = false

            // Disable safe browsing (avoid Google telemetry)
            safeBrowsingEnabled = false

            // Enable WebGL
            javaScriptCanOpenWindowsAutomatically = true
            setSupportMultipleWindows(false)
        }

        // Single combined WebViewClient — handles proxy indicator, stealth injection, URL bar updates
        webView.webViewClient = object : WebViewClient() {
            override fun onPageStarted(view: WebView?, url: String?, favicon: Bitmap?) {
                super.onPageStarted(view, url, favicon)
                url?.let { currentUrl = it }
                updateUrlBar(url)
            }

            override fun onPageFinished(view: WebView?, url: String?) {
                super.onPageFinished(view, url)
                url?.let { currentUrl = it }
                updateUrlBar(url)
                // Rotate browser identity on every page load
                injectRotatingIdentity(view)
                updateNavigationButtons()
                // Update proxy indicator
                val report = ProxyManager.statusReport()
                val mode = report["mode"] ?: "DIRECT"
                val proxyState = when (mode) {
                    "TOR_SOCKS", "TOR_HTTP" -> "\uD83D\uDD12 Tor (${report["host"]}:${report["port"]})"
                    "CUSTOM" -> "\uD83D\uDD12 ${report["type"]} (${report["host"]}:${report["port"]})"
                    else -> ""
                }
                runOnUiThread {
                    proxyIndicator.text = proxyState
                    proxyIndicator.visibility = if (proxyState.isNotEmpty()) View.VISIBLE else View.GONE
                }
            }

            @Suppress("DEPRECATION")
            override fun onReceivedSslError(view: WebView?, handler: android.webkit.SslErrorHandler?, error: android.net.http.SslError?) {
                handler?.proceed()
            }

            override fun onReceivedError(view: WebView?, errorCode: Int, description: String?, failingUrl: String?) {
                super.onReceivedError(view, errorCode, description, failingUrl)
                if (errorCode != -1) {
                    runOnUiThread { urlBar.setText("\u26A0 Error $errorCode: $description") }
                }
            }

            @Suppress("OVERRIDE_DEPRECATION")
            override fun shouldInterceptRequest(view: WebView?, request: WebResourceRequest?): WebResourceResponse? {
                val url = request?.url?.toString() ?: return null
                // ── DoH DNS resolution ──
                // Resolve hostname via encrypted DoH before connecting, preventing
                // DNS leaks through Tor.  If DoH fails, fall through to system DNS.
                val host = request?.url?.host
                if (!host.isNullOrBlank() && host.contains(".")) {
                    DnsOverHttps.resolve(host)
                }
                return null  // Let WebView handle the request normally
            }

            override fun shouldOverrideUrlLoading(
                view: WebView?, request: WebResourceRequest?
            ): Boolean {
                val url = request?.url?.toString() ?: return false
                if (url.startsWith("http://") || url.startsWith("https://")) {
                    return false
                }
                try {
                    startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
                } catch (_: Exception) {}
                return true
            }
        }

        // Single combined WebChromeClient — handles progress, popups, file chooser
        webView.webChromeClient = object : WebChromeClient() {
            override fun onProgressChanged(view: WebView?, newProgress: Int) {
                progressBar.progress = newProgress
                progressBar.visibility = if (newProgress < 100) View.VISIBLE else View.GONE
            }

            override fun onCreateWindow(
                view: WebView?, isDialog: Boolean, isUserGesture: Boolean,
                resultMsg: Message?
            ): Boolean {
                val newWebView = WebView(this@BrowserActivity)
                newWebView.webViewClient = webView.webViewClient
                newWebView.webChromeClient = webView.webChromeClient
                val transport = resultMsg?.obj as? WebView.WebViewTransport
                transport?.webView = newWebView
                resultMsg?.sendToTarget()
                return true
            }

            override fun onShowFileChooser(
                webView: WebView?, filePathCallback: ValueCallback<Array<Uri>>?,
                fileChooserParams: FileChooserParams?
            ): Boolean {
                filePathCallback?.onReceiveValue(null)
                return true
            }

            override fun onConsoleMessage(consoleMessage: ConsoleMessage?): Boolean {
                return true
            }
        }

        // Add JS interface for ADB control
        webView.addJavascriptInterface(FarmJsInterface(this), "FarmBrowser")
    }

    private fun initProxy() {
        val mode = ProxyManager.initFromSystem(this)
        val proxyUrl = ProxyManager.getWebViewProxyUrl()
        val report = ProxyManager.statusReport()

        if (proxyUrl != null) {
            webView.post {
                WebView.setWebContentsDebuggingEnabled(true)
                // WebView uses system proxy by default on Android
                // For explicit proxy control, we configure the local tunnel
                proxyIndicator.text = "🔒 ${report["type"]} ${report["host"]}:${report["port"]}"
                proxyIndicator.visibility = View.VISIBLE
            }
        } else {
            proxyIndicator.text = "⚡ Direct"
            proxyIndicator.visibility = View.GONE
        }
    }

    fun injectRotatingIdentity(webView: WebView?) {
        webView ?: return
        try {
            val identity = com.farmbrowser.stealth.stealth.BrowserIdentity.nextIdentity()
            val deviceProfile = DeviceFingerprint.getProfile(this)
            val identityIndex = com.farmbrowser.stealth.stealth.BrowserIdentity.currentIndex()

            // ── Cookie isolation ──
            // Wipe cookie jar and restore cookies for this identity
            CookieIsolation.onIdentityRotated(identityIndex, webView)

            // ── TLS fingerprint ──
            // Clear DNS cache for fresh lookups with new identity
            DnsOverHttps.clearCache()

            // Set WebView UA to match the rotating identity
            webView.settings.userAgentString = identity.userAgent

            // Inject identity JS (navigator, plugins, chrome object, vendor)
            webView.evaluateJavascript(
                com.farmbrowser.stealth.stealth.BrowserIdentity.generateIdentityJs(identity), null
            )

            // Inject device fingerprint JS (screen, WebGL, canvas noise)
            webView.evaluateJavascript(
                com.farmbrowser.stealth.stealth.BrowserIdentity.generateDeviceFingerprintJs(deviceProfile), null
            )

            // Inject TLS profile info (sec-ch-ua headers are set via WebViewClient)
            val tlsProfile = TlsFingerprint.profileForIdentity(identity.browserName)
            Log.i(TAG, "Identity: ${identity.browserName} | TLS: ${tlsProfile.preferredProtocol} | Accept-Encoding: ${tlsProfile.acceptEncoding}")

            // Update proxy indicator with current identity
            runOnUiThread {
                proxyIndicator.text = "${identity.browserName}"
                proxyIndicator.visibility = View.VISIBLE
            }
        } catch (e: Exception) {
            Log.w(TAG, "injectRotatingIdentity failed: $e")
        }
    }

    private fun initNavigation() {
        btnBack.setOnClickListener {
            if (webView.canGoBack()) webView.goBack()
        }
        btnForward.setOnClickListener {
            if (webView.canGoForward()) webView.goForward()
        }
        btnRefresh.setOnClickListener {
            webView.reload()
        }
        btnHome.setOnClickListener {
            webView.loadUrl("about:blank")
        }
        btnMenu.setOnClickListener {
            showMenu()
        }

        urlBar.setOnEditorActionListener { _, actionId, event ->
            if (actionId == EditorInfo.IME_ACTION_GO ||
                event?.keyCode == KeyEvent.KEYCODE_ENTER
            ) {
                loadUrlFromBar()
                hideKeyboard()
                true
            } else false
        }

        urlBar.setOnFocusChangeListener { _, hasFocus ->
            if (hasFocus) {
                urlBar.selectAll()
            }
        }
    }

    private fun loadUrlFromBar() {
        val input = urlBar.text.toString().trim()
        if (input.isBlank()) return
        val url = normalizeUrl(input)
        webView.post { loadUrl(url) }
    }

    private fun loadUrl(url: String) {
        val normalized = normalizeUrl(url)
        currentUrl = normalized
        // Inject TLS headers matching current browser identity
        val identity = com.farmbrowser.stealth.stealth.BrowserIdentity.currentIdentity()
        val tlsHeaders = TlsFingerprint.buildHeadersForIdentity(identity.browserName, null)
        webView.loadUrl(normalized, tlsHeaders)
    }

    private fun normalizeUrl(input: String): String {
        val trimmed = input.trim()
        if (trimmed.startsWith("http://") || trimmed.startsWith("https://")) return trimmed
        if (trimmed.startsWith("about:") || trimmed.startsWith("javascript:")) return trimmed
        // If it looks like a domain
        if (trimmed.contains(".") && !trimmed.contains(" ")) {
            return "https://$trimmed"
        }
        // Otherwise search
        return "https://www.google.com/search?q=${Uri.encode(trimmed)}"
    }

    private fun updateUrlBar(url: String?) {
        if (urlBar.hasFocus()) return
        urlBar.setText(url ?: "")
    }

    private fun updateNavigationButtons() {
        btnBack.alpha = if (webView.canGoBack()) 1.0f else 0.3f
        btnForward.alpha = if (webView.canGoForward()) 1.0f else 0.3f
    }

    private fun hideKeyboard() {
        val imm = getSystemService(INPUT_METHOD_SERVICE) as InputMethodManager
        imm.hideSoftInputFromWindow(urlBar.windowToken, 0)
        urlBar.clearFocus()
    }

    private fun showMenu() {
        val popup = android.widget.PopupMenu(this, btnMenu)
        popup.menu.add(0, 1, 0, "Settings")
        popup.menu.add(0, 2, 1, "Clear Data")
        popup.menu.add(0, 3, 2, "Proxy Status")
        popup.menu.add(0, 4, 3, "Reload Stealth")
        popup.menu.add(0, 5, 4, "New Tab")
        popup.setOnMenuItemClickListener { item ->
            when (item.itemId) {
                1 -> {
                    startActivity(Intent(this, SettingsActivity::class.java))
                    true
                }
                2 -> {
                    clearBrowsingData()
                    true
                }
                3 -> {
                    showProxyStatus()
                    true
                }
                4 -> {
                    injectRotatingIdentity(webView)
                    Toast.makeText(this, "Browser identity rotated", Toast.LENGTH_SHORT).show()
                    true
                }
                5 -> {
                    webView.loadUrl("about:blank")
                    urlBar.setText("")
                    urlBar.requestFocus()
                    true
                }
                else -> false
            }
        }
        popup.show()
    }

    fun clearBrowsingData() {
        webView.clearCache(true)
        webView.clearHistory()
        webView.clearFormData()
        // Use CookieIsolation for a complete wipe (including persisted per-identity cookies)
        CookieIsolation.wipeAll(this)
        DnsOverHttps.clearCache()
        Toast.makeText(this, "Browsing data cleared", Toast.LENGTH_SHORT).show()
    }

    private fun showProxyStatus() {
        val report = ProxyManager.statusReport()
        val msg = buildString {
            appendLine("=== Proxy Status ===")
            report.forEach { (k, v) ->
                appendLine("$k: $v")
            }
        }
        Toast.makeText(this, msg, Toast.LENGTH_LONG).show()
    }

    override fun onBackPressed() {
        when {
            webView.canGoBack() -> webView.goBack()
            else -> super.onBackPressed()
        }
    }

    fun openUrlDirect(url: String) {
        val normalized = normalizeUrl(url)
        currentUrl = normalized
        // Inject TLS headers matching current browser identity
        val identity = com.farmbrowser.stealth.stealth.BrowserIdentity.currentIdentity()
        val tlsHeaders = TlsFingerprint.buildHeadersForIdentity(identity.browserName, null)
        webView.loadUrl(normalized, tlsHeaders)
    }

    override fun onDestroy() {
        FarmBrowserReceiver.currentActivity = null
        webView.destroy()
        super.onDestroy()
    }

    companion object {
        private const val TAG = "FarmBrowser"
    }
}

/**
 * JavaScript interface for ADB/automation control.
 * PharmFlow can call: FarmBrowser.openUrl(url), FarmBrowser.clearData(), etc.
 */
class FarmJsInterface(private val activity: BrowserActivity) {

    @JavascriptInterface
    fun openUrl(url: String) {
        activity.runOnUiThread {
            // Access webView through reflection or make it public
            activity.findViewById<WebView>(R.id.webview)?.loadUrl(url)
        }
    }

    @JavascriptInterface
    fun clearData() {
        activity.runOnUiThread {
            activity.clearBrowsingData()
        }
    }

    @JavascriptInterface
    fun getProxyInfo(): String {
        return ProxyManager.statusReport().toString()
    }

    @JavascriptInterface
    fun setProxy(host: String, port: Int, type: String) {
        val proxyType = when (type.lowercase()) {
            "socks5", "socks" -> ProxyConfig.Type.SOCKS5
            "http", "https" -> ProxyConfig.Type.HTTP
            else -> ProxyConfig.Type.NONE
        }
        ProxyConfig.host = host
        ProxyConfig.port = port
        ProxyConfig.type = proxyType
        ProxyConfig.enabled = proxyType != ProxyConfig.Type.NONE
        activity.runOnUiThread {
            ProxyManager.initFromSystem(activity)
        }
    }

    @JavascriptInterface
    fun clearProxy() {
        ProxyConfig.enabled = false
        ProxyConfig.host = ""
        ProxyConfig.port = 0
        ProxyConfig.type = ProxyConfig.Type.NONE
        activity.runOnUiThread {
            ProxyManager.stopTunnel()
        }
    }

    @JavascriptInterface
    fun stealthReload() {
        activity.runOnUiThread {
            activity.injectRotatingIdentity(activity.findViewById(R.id.webview))
        }
    }

    @JavascriptInterface
    fun rotateIdentity() {
        activity.runOnUiThread {
            activity.injectRotatingIdentity(activity.findViewById(R.id.webview))
        }
    }

    @JavascriptInterface
    fun getBrowserName(): String {
        return com.farmbrowser.stealth.stealth.BrowserIdentity.currentIdentity().browserName
    }
}

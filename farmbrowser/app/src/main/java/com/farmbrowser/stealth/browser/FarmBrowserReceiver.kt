package com.farmbrowser.stealth.browser

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log
import android.webkit.CookieManager
import android.webkit.WebView
import com.farmbrowser.stealth.proxy.ProxyConfig
import com.farmbrowser.stealth.proxy.ProxyManager
import com.farmbrowser.stealth.stealth.BrowserIdentity
import com.farmbrowser.stealth.stealth.CookieIsolation
import com.farmbrowser.stealth.stealth.DeviceFingerprint
import com.farmbrowser.stealth.stealth.DnsOverHttps

/**
 * BroadcastReceiver for ADB-driven control from CPharm automation.
 *
 * All actions use: adb shell am broadcast -a com.farmbrowser.stealth.CONTROL
 *
 * Actions (intent extra "action"):
 *   open_url      — extra "url" (String)
 *   set_proxy     — extra "host" (String), "port" (Int), "type" (String: socks5/http/none)
 *   clear_proxy   — no extras
 *   rotate_identity — no extras
 *   stealth_reload  — no extras
 *   clear_data   — no extras
 *   status       — returns result with proxy info + current identity
 *   dump         — full state dump: identity, proxy, device, page title, URL, cookies
 *   set_ua       — extra "ua" (String) — set a specific user-agent string
 *   set_identity — extra "index" (Int) — set starting identity for this session (no lock)
 *   set_profile  — extra "index" (Int) — switch device fingerprint profile
 *   navigate     — extra "url" (String) — navigate to URL
 */
class FarmBrowserReceiver : BroadcastReceiver() {

    companion object {
        const val TAG = "FarmBrowserReceiver"
        const val ACTION = "com.farmbrowser.stealth.CONTROL"

        // Actions
        const val ACT_OPEN_URL = "open_url"
        const val ACT_SET_PROXY = "set_proxy"
        const val ACT_CLEAR_PROXY = "clear_proxy"
        const val ACT_ROTATE_IDENTITY = "rotate_identity"
        const val ACT_STEALTH_RELOAD = "stealth_reload"
        const val ACT_CLEAR_DATA = "clear_data"
        const val ACT_STATUS = "status"
        const val ACT_SET_UA = "set_ua"
        const val ACT_SET_PROFILE = "set_profile"
        const val ACT_NAVIGATE = "navigate"
        const val ACT_SET_IDENTITY = "set_identity"
        const val ACT_DUMP = "dump"

        @Volatile
        var currentActivity: BrowserActivity? = null
    }

    override fun onReceive(context: Context, intent: Intent?) {
        if (intent?.action != ACTION) return

        val action = intent.getStringExtra("action") ?: ""
        Log.i(TAG, "Received action: $action")

        val activity = currentActivity
        if (activity == null) {
            Log.w(TAG, "No active BrowserActivity -- launching one")
            val launch = Intent(context, BrowserActivity::class.java).apply {
                flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
            }
            val url = intent.getStringExtra("url")
            if (!url.isNullOrBlank()) {
                launch.data = android.net.Uri.parse(url)
            }
            context.startActivity(launch)
            return
        }

        when (action) {
            ACT_OPEN_URL -> {
                val url = intent.getStringExtra("url") ?: ""
                if (url.isNotBlank()) {
                    activity.runOnUiThread { activity.openUrlDirect(url) }
                    resultCode = android.app.Activity.RESULT_OK
                } else {
                    resultCode = android.app.Activity.RESULT_CANCELED
                    resultData = "missing url extra"
                }
            }

            ACT_SET_PROXY -> {
                val host = intent.getStringExtra("host") ?: ""
                val port = intent.getIntExtra("port", 0)
                val type = intent.getStringExtra("type") ?: "none"
                val proxyType = when (type.lowercase()) {
                    "socks5", "socks" -> ProxyConfig.Type.SOCKS5
                    "http", "https" -> ProxyConfig.Type.HTTP
                    else -> ProxyConfig.Type.NONE
                }
                ProxyConfig.host = host
                ProxyConfig.port = port
                ProxyConfig.type = proxyType
                ProxyConfig.enabled = proxyType != ProxyConfig.Type.NONE
                activity.runOnUiThread { ProxyManager.initFromSystem(activity) }
                Log.i(TAG, "Proxy set: $type $host:$port (enabled=${ProxyConfig.enabled})")
                resultData = "proxy_set:$type:$host:$port"
                resultCode = android.app.Activity.RESULT_OK
            }

            ACT_CLEAR_PROXY -> {
                ProxyConfig.enabled = false
                ProxyConfig.host = ""
                ProxyConfig.port = 0
                ProxyConfig.type = ProxyConfig.Type.NONE
                activity.runOnUiThread { ProxyManager.stopTunnel() }
                Log.i(TAG, "Proxy cleared")
                resultData = "proxy_cleared"
                resultCode = android.app.Activity.RESULT_OK
            }

            ACT_ROTATE_IDENTITY -> {
                // Full stealth reset: advance identity + wipe cookies + clear DNS + clear data
                val identity = BrowserIdentity.nextIdentity()
                val idx = BrowserIdentity.currentIndex()
                activity.runOnUiThread {
                    val wv = activity.findViewById<WebView>(com.farmbrowser.stealth.R.id.webview)
                    if (wv != null) {
                        CookieIsolation.onIdentityRotated(idx, wv)
                        wv.clearCache(true)
                        wv.clearHistory()
                        wv.clearFormData()
                    }
                    DnsOverHttps.clearCache()
                }
                Log.i(TAG, "Full stealth reset: ${identity.browserName} | cookies wiped | DNS cleared")
                resultData = "identity:${identity.browserName}"
                resultCode = android.app.Activity.RESULT_OK
            }

            ACT_SET_IDENTITY -> {
                val idx = intent.getIntExtra("index", -1)
                if (idx >= 0) {
                    BrowserIdentity.forceIndex(idx)
                    val identity = BrowserIdentity.currentIdentity()
                    Log.i(TAG, "Identity forced to [$idx]: ${identity.browserName}")
                    resultData = "identity:${identity.browserName}"
                    resultCode = android.app.Activity.RESULT_OK
                } else {
                    resultCode = android.app.Activity.RESULT_CANCELED
                    resultData = "missing index extra"
                }
            }



            ACT_STEALTH_RELOAD -> {
                activity.runOnUiThread {
                    activity.injectRotatingIdentity(
                        activity.findViewById<WebView>(com.farmbrowser.stealth.R.id.webview)
                    )
                }
                resultData = "stealth_reloaded"
                resultCode = android.app.Activity.RESULT_OK
            }

            ACT_CLEAR_DATA -> {
                activity.runOnUiThread { activity.clearBrowsingData() }
                resultData = "data_cleared"
                resultCode = android.app.Activity.RESULT_OK
            }

            ACT_STATUS -> {
                val json = buildStatusJson(activity)
                resultData = json
                resultCode = android.app.Activity.RESULT_OK
            }

            ACT_DUMP -> {
                val json = buildFullDump(activity)
                resultData = json
                resultCode = android.app.Activity.RESULT_OK
            }

            ACT_SET_UA -> {
                val ua = intent.getStringExtra("ua") ?: ""
                if (ua.isNotBlank()) {
                    activity.runOnUiThread {
                        val wv = activity.findViewById<WebView>(com.farmbrowser.stealth.R.id.webview)
                        wv.settings.userAgentString = ua
                    }
                    resultData = "ua_set"
                    resultCode = android.app.Activity.RESULT_OK
                } else {
                    resultCode = android.app.Activity.RESULT_CANCELED
                    resultData = "missing ua extra"
                }
            }

            ACT_SET_PROFILE -> {
                val idx = intent.getIntExtra("index", -1)
                if (idx >= 0) {
                    DeviceFingerprint.setProfileIndex(idx)
                    resultData = "profile:$idx"
                    resultCode = android.app.Activity.RESULT_OK
                } else {
                    resultCode = android.app.Activity.RESULT_CANCELED
                    resultData = "missing index extra"
                }
            }

            ACT_NAVIGATE -> {
                val url = intent.getStringExtra("url") ?: ""
                if (url.isNotBlank()) {
                    activity.runOnUiThread { activity.openUrlDirect(url) }
                    resultData = "navigated:$url"
                    resultCode = android.app.Activity.RESULT_OK
                } else {
                    resultCode = android.app.Activity.RESULT_CANCELED
                    resultData = "missing url extra"
                }
            }

            else -> {
                resultData = "unknown_action:$action"
                resultCode = android.app.Activity.RESULT_CANCELED
            }
        }
    }

    private fun buildStatusJson(activity: BrowserActivity): String {
        val report = ProxyManager.statusReport()
        val identity = BrowserIdentity.currentIdentity()
        val profile = DeviceFingerprint.getProfile(activity)
        return buildString {
            append("{")
            append("\"proxy_mode\":\"${esc(report["mode"])}\",")
            append("\"proxy_host\":\"${esc(report["host"])}\",")
            append("\"proxy_port\":\"${esc(report["port"])}\",")
            append("\"proxy_type\":\"${esc(report["type"])}\",")
            append("\"identity\":\"${esc(identity.browserName)}\",")
            append("\"device\":\"${esc(profile.manufacturer)} ${esc(profile.model)}\",")
            append("\"package\":\"com.farmbrowser.stealth.debug\"")
            append("}")
        }
    }

    private fun buildFullDump(activity: BrowserActivity): String {
        val report = ProxyManager.statusReport()
        val identity = BrowserIdentity.currentIdentity()
        val profile = DeviceFingerprint.getProfile(activity)
        val cm = CookieManager.getInstance()

        // Read page title and URL from UI thread
        var pageTitle = ""
        var pageUrl = ""
        var historySize = 0
        var canGoBack = false
        var canGoForward = false
        activity.runOnUiThread {
            val wv = activity.findViewById<WebView>(com.farmbrowser.stealth.R.id.webview)
            if (wv != null) {
                pageTitle = wv.title ?: ""
                pageUrl = wv.url ?: ""
                canGoBack = wv.canGoBack()
                canGoForward = wv.canGoForward()
                try { historySize = wv.copyBackForwardList().size } catch (_: Exception) {}
            }
        }
        // Brief sleep to let UI thread complete (broadcast runs off main thread)
        Thread.sleep(50)

        val cookieCount = try {
            val raw = cm.getCookie("https://") ?: ""
            raw.split(";").count { it.trim().isNotEmpty() }
        } catch (_: Exception) { 0 }

        return buildString {
            append("{")
            append("\"timestamp\":${System.currentTimeMillis()},")
            append("\"identity\":\"${esc(identity.browserName)}\",")
            append("\"user_agent\":\"${esc(identity.userAgent)}\",")
            append("\"proxy_mode\":\"${esc(report["mode"])}\",")
            append("\"proxy_host\":\"${esc(report["host"])}\",")
            append("\"proxy_port\":\"${esc(report["port"])}\",")
            append("\"proxy_type\":\"${esc(report["type"])}\",")
            append("\"device_brand\":\"${esc(profile.brand)}\",")
            append("\"device_manufacturer\":\"${esc(profile.manufacturer)}\",")
            append("\"device_model\":\"${esc(profile.model)}\",")
            append("\"device_key\":\"${esc(profile.key)}\",")
            append("\"android_version\":\"${esc(profile.androidRelease)}\",")
            append("\"screen_w\":${profile.screenW},")
            append("\"screen_h\":${profile.screenH},")
            append("\"dpi\":${profile.dpi},")
            append("\"gpu\":\"${esc(profile.gpuRenderer)}\",")
            append("\"page_title\":\"${esc(pageTitle)}\",")
            append("\"page_url\":\"${esc(pageUrl)}\",")
            append("\"can_go_back\":$canGoBack,")
            append("\"can_go_forward\":$canGoForward,")
            append("\"history_size\":$historySize,")
            append("\"cookie_count\":$cookieCount,")
            append("\"identity_index\":${BrowserIdentity.currentIndex()},")
            append("\"package\":\"com.farmbrowser.stealth.debug\"")
            append("}")
        }
    }

    /** Escape a value for safe JSON embedding. */
    private fun esc(value: Any?): String {
        return (value?.toString() ?: "")
            .replace("\\", "\\\\")
            .replace("\"", "\\\"")
            .replace("\n", "\\n")
            .replace("\r", "\\r")
            .replace("\t", "\\t")
    }
}

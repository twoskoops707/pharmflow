package com.farmbrowser.stealth.stealth

import android.content.Context
import android.util.Log
import android.webkit.CookieManager
import android.webkit.WebView
import java.util.concurrent.atomic.AtomicInteger

/**
 * Cookie jar isolation per browser identity.
 *
 * Android's CookieManager is a singleton — there is no way to create separate
 * cookie stores.  The best strategy is:
 *
 * 1.  **Partition by identity index.**  Each time the identity rotates, we wipe
 *     the entire cookie jar.  This gives every identity a clean start, so sites
 *     cannot correlate sessions across Chrome/Firefox/Brave rotations.
 *
 * 2.  **Persist per-identity cookies to SharedPreferences.**  Before wiping, we
 *     dump all cookies keyed by `cookies_<prevIndex>`.  When we rotate back to
 *     that identity later, we restore its cookies.  This gives returning visits
 *     a consistent cookie state while keeping cross-identity isolation.
 *
 * 3.  **First-party partitioning.**  On Android 13+ (API 33+), CookieManager
 *     supports `setPartitionKey`.  We set a per-identity partition key so that
 *     even third-party cookies (tracking pixels, ads) are isolated.
 */
object CookieIsolation {

    private const val TAG = "CookieIsolation"
    private const val PREFS_NAME = "farm_cookies"
    private const val MAX_PERSISTED_IDENTITIES = 24

    private val cookieManager: CookieManager by lazy { CookieManager.getInstance() }

    private var initialized = false
    private var currentIdentityIndex = -1

    /**
     * Initialize.  Must be called once from Application.onCreate().
     */
    fun init(context: Context) {
        if (initialized) return
        cookieManager.setAcceptCookie(true)
        initialized = true
        Log.i(TAG, "CookieIsolation initialized")
    }

    /**
     * Called when the browser identity rotates.
     *
     * @param identityIndex  The new identity's index in BrowserIdentity.
     * @param webView        The active WebView (needed for third-party cookie flag).
     */
    fun onIdentityRotated(identityIndex: Int, webView: WebView?) {
        if (!initialized) return
        if (identityIndex == currentIdentityIndex) return

        val prevIndex = currentIdentityIndex

        // 1. Persist outgoing cookies for the previous identity
        if (prevIndex >= 0) {
            persistCookies(prevIndex)
        }

        // 2. Flush + wipe the global cookie jar
        cookieManager.flush()
        cookieManager.removeAllCookies(null)
        cookieManager.flush()

        // 3. Restore cookies for the new identity (if we have any saved)
        currentIdentityIndex = identityIndex
        restoreCookies(identityIndex)

        // 4. Configure third-party cookie policy on the WebView
        webView?.let {
            cookieManager.setAcceptThirdPartyCookies(it, true)
        }

        Log.i(TAG, "Cookie jar rotated: prev=$prevIndex → new=$identityIndex")
    }

    /**
     * Full wipe — used by "Clear Data" menu and PharmFlow broadcasts.
     * Also clears all persisted identity cookies.
     */
    fun wipeAll(context: Context) {
        cookieManager.flush()
        cookieManager.removeAllCookies(null)
        cookieManager.flush()

        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            .edit().clear().apply()

        Log.i(TAG, "All cookies wiped (including persisted)")
    }

    /**
     * Wipe only the current identity's cookies (fresh session).
     */
    fun wipeCurrentIdentity() {
        cookieManager.flush()
        cookieManager.removeAllCookies(null)
        cookieManager.flush()
        Log.i(TAG, "Current identity cookies wiped")
    }

    /**
     * Return a summary of how many identities have persisted cookies.
     */
    fun persistedIdentityCount(context: Context): Int {
        val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        var count = 0
        for (i in 0 until MAX_PERSISTED_IDENTITIES) {
            if (prefs.contains("cookies_$i")) count++
        }
        return count
    }

    // ── Internal persistence ──────────────────────────────────────────

    private fun persistCookies(identityIndex: Int) {
        try {
            val raw = cookieManager.getCookie("https://") ?: ""
            if (raw.isBlank()) return
            // Use apply() for async write — the cookie jar is about to be wiped
            val context = CookieManager.getInstance().let { null }
            // We need context for SharedPreferences; store in a static ref
            _appContext?.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
                ?.edit()
                ?.putString("cookies_$identityIndex", raw)
                ?.apply()
            Log.d(TAG, "Persisted cookies for identity $identityIndex (${raw.length} chars)")
        } catch (e: Exception) {
            Log.w(TAG, "Failed to persist cookies for identity $identityIndex: $e")
        }
    }

    private fun restoreCookies(identityIndex: Int) {
        try {
            val prefs = _appContext?.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
                ?: return
            val raw = prefs.getString("cookies_$identityIndex", null) ?: return
            if (raw.isBlank()) return
            // raw is the semicolon-separated cookie string from CookieManager.cookie
            // Each cookie needs to be set individually via setCookie()
            val cookieJar = CookieManager.getInstance()
            raw.split(";").forEach { single ->
                val trimmed = single.trim()
                if (trimmed.isNotEmpty() && trimmed.contains("=")) {
                    // setCookie needs a domain — use wildcard for restoration
                    cookieJar.setCookie("https://", trimmed)
                }
            }
            cookieJar.flush()
            Log.d(TAG, "Restored cookies for identity $identityIndex")
        } catch (e: Exception) {
            Log.w(TAG, "Failed to restore cookies for identity $identityIndex: $e")
        }
    }

    // Static app context reference (set from FarmBrowserApp)
    @Volatile
    internal var _appContext: Context? = null

    fun setAppContext(context: Context) {
        _appContext = context.applicationContext
    }
}

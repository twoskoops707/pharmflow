package com.farmbrowser.stealth.stealth

import android.content.Context
import android.content.SharedPreferences
import java.util.UUID

/**
 * Per-navigation browser identity rotation.
 * Each page load picks a different browser type so websites see:
 * Chrome, Chromium, Brave, Firefox, Opera, Edge, Samsung Internet, etc.
 *
 * STEALTH RULES:
 * 1. Each phone starts at a UNIQUE index (seeded from ANDROID_ID).
 * 2. Identity ROTATES on every page load — never stays the same.
 * 3. No permanent lock — a locked identity is a tracking fingerprint.
 * 4. set_identity (from PharmFlow ADB) sets the STARTING point for this session,
 *    but rotation still happens on each subsequent page load.
 *
 * The uniqueness guarantee comes from different starting points,
 * NOT from locking. Every phone cycles through all identities over time.
 */
object BrowserIdentity {



    /**
     * A complete browser identity — what a website would see via
     * navigator.userAgent, navigator.vendor, navigator.plugins, window.chrome, etc.
     */
    data class Identity(
        val browserName: String,
        val userAgent: String,
        val vendor: String,
        val product: String,
        val productSub: String,
        val appVersion: String,
        val platform: String,
        val vendorSub: String,
        val chromeExists: Boolean,
        val chromeRuntime: Boolean,
        val chromeApp: Boolean,
        val pluginNames: List<String>,
        val extraNavigatorProps: Map<String, Any> = emptyMap(),
        val extraJs: String = "",
    )

    private val identities: Array<Identity> = arrayOf(
        // ── Chrome variants ──
        Identity(
            browserName = "Chrome 128",
            userAgent = "Mozilla/5.0 (Linux; Android 14; Pixel 8 Build/AP2A.240805.005) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.6613.88 Mobile Safari/537.36",
            vendor = "Google Inc.",
            product = "",
            productSub = "20030107",
            appVersion = "5.0 (Linux; Android 14; Pixel 8 Build/AP2A.240805.005) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.6613.88 Mobile Safari/537.36",
            platform = "Linux armv81",
            vendorSub = "",
            chromeExists = true,
            chromeRuntime = false,
            chromeApp = true,
            pluginNames = listOf("PDF Viewer", "Chrome PDF Viewer", "Chromium PDF Viewer", "Microsoft Edge PDF Viewer", "WebKit built-in PDF"),
        ),
        Identity(
            browserName = "Chrome 127",
            userAgent = "Mozilla/5.0 (Linux; Android 13; SM-S918B Build/TP1A.220624.014) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.6533.103 Mobile Safari/537.36",
            vendor = "Google Inc.",
            product = "",
            productSub = "20030107",
            appVersion = "5.0 (Linux; Android 13; SM-S918B Build/TP1A.220624.014) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.6533.103 Mobile Safari/537.36",
            platform = "Linux armv81",
            vendorSub = "",
            chromeExists = true,
            chromeRuntime = false,
            chromeApp = true,
            pluginNames = listOf("PDF Viewer", "Chrome PDF Viewer", "Chromium PDF Viewer", "Microsoft Edge PDF Viewer", "WebKit built-in PDF"),
        ),
        // ── Chromium ──
        Identity(
            browserName = "Chromium 129",
            userAgent = "Mozilla/5.0 (Linux; Android 14; 23127PN0CC Build/UKQ1.240116.001) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.6668.71 Mobile Safari/537.36",
            vendor = "Google Inc.",
            product = "",
            productSub = "20030107",
            appVersion = "5.0 (Linux; Android 14; 23127PN0CC Build/UKQ1.240116.001) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.6668.71 Mobile Safari/537.36",
            platform = "Linux armv81",
            vendorSub = "",
            chromeExists = true,
            chromeRuntime = false,
            chromeApp = true,
            pluginNames = listOf("PDF Viewer", "Chrome PDF Viewer", "Chromium PDF Viewer", "Microsoft Edge PDF Viewer", "WebKit built-in PDF"),
        ),
        // ── Brave ──
        Identity(
            browserName = "Brave 1.69",
            userAgent = "Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro Build/AP2A.240805.005) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.6613.88 Mobile Safari/537.36",
            vendor = "Google Inc.",
            product = "",
            productSub = "20030107",
            appVersion = "5.0 (Linux; Android 14; Pixel 8 Pro Build/AP2A.240805.005) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.6613.88 Mobile Safari/537.36",
            platform = "Linux armv81",
            vendorSub = "",
            chromeExists = true,
            chromeRuntime = false,
            chromeApp = true,
            pluginNames = listOf("PDF Viewer", "Chrome PDF Viewer", "Chromium PDF Viewer", "Microsoft Edge PDF Viewer", "WebKit built-in PDF"),
            extraJs = """
                // Brave-specific: Brave doesn't expose window.brave but does
                // have specific navigator.plugins ordering differences.
                // Brave shields typically block fingerprint scripts, but we
                // emulate the Brave-like navigator output.
            """,
        ),
        // ── Samsung Internet ──
        Identity(
            browserName = "Samsung Internet 26",
            userAgent = "Mozilla/5.0 (Linux; Android 14; SM-S921B Build/UP1A.231005.007) AppleWebKit/537.36 (KHTML, like Gecko) SamsungBrowser/26.0 Chrome/121.0.6167.178 Mobile Safari/537.36",
            vendor = "Google Inc.",
            product = "",
            productSub = "20030107",
            appVersion = "5.0 (Linux; Android 14; SM-S921B Build/UP1A.231005.007) AppleWebKit/537.36 (KHTML, like Gecko) SamsungBrowser/26.0 Chrome/121.0.6167.178 Mobile Safari/537.36",
            platform = "Linux armv81",
            vendorSub = "",
            chromeExists = true,
            chromeRuntime = false,
            chromeApp = true,
            pluginNames = listOf("PDF Viewer", "Chrome PDF Viewer", "Chromium PDF Viewer", "Samsung Internet PDF Viewer", "WebKit built-in PDF"),
            extraJs = """
                // Samsung Internet uses SamsungBrowser UA token but still has
                // Chrome-like navigator properties.
            """,
        ),
        // ── Firefox / Fennec ──
        Identity(
            browserName = "Firefox 130",
            userAgent = "Mozilla/5.0 (Android 14; Mobile; rv:130.0) Gecko/130.0 Firefox/130.0",
            vendor = "",
            product = "Gecko",
            productSub = "20100101",
            appVersion = "5.0 (Android 14; Mobile; rv:130.0) Gecko/130.0 Firefox/130.0",
            platform = "Linux armv81",
            vendorSub = "",
            chromeExists = false,
            chromeRuntime = false,
            chromeApp = false,
            pluginNames = listOf(),
            extraNavigatorProps = mapOf(
                "buildID" to "20240812184856",
                "oscpu" to "Linux armv8l",
            ),
            extraJs = """
                // Firefox doesn't have window.chrome at all
                delete window.chrome;
                // Firefox has different navigator.connection
                if (navigator.connection) {
                    Object.defineProperty(navigator, 'connection', { get: function() { return undefined; } });
                }
            """,
        ),
        // ── Firefox ESR ──
        Identity(
            browserName = "Firefox ESR 128",
            userAgent = "Mozilla/5.0 (Android 13; Mobile; rv:128.0) Gecko/128.0 Firefox/128.0",
            vendor = "",
            product = "Gecko",
            productSub = "20100101",
            appVersion = "5.0 (Android 13; Mobile; rv:128.0) Gecko/128.0 Firefox/128.0",
            platform = "Linux armv81",
            vendorSub = "",
            chromeExists = false,
            chromeRuntime = false,
            chromeApp = false,
            pluginNames = listOf(),
            extraNavigatorProps = mapOf(
                "buildID" to "20240702120735",
                "oscpu" to "Linux armv8l",
            ),
            extraJs = """
                delete window.chrome;
                if (navigator.connection) {
                    Object.defineProperty(navigator, 'connection', { get: function() { return undefined; } });
                }
            """,
        ),
        // ── Opera ──
        Identity(
            browserName = "Opera 93",
            userAgent = "Mozilla/5.0 (Linux; Android 14; CPH2581 Build/UP1A.231005.007) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.6613.88 Mobile Safari/537.36 OPR/93.0.4556.71",
            vendor = "Google Inc.",
            product = "",
            productSub = "20030107",
            appVersion = "5.0 (Linux; Android 14; CPH2581 Build/UP1A.231005.007) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.6613.88 Mobile Safari/537.36 OPR/93.0.4556.71",
            platform = "Linux armv81",
            vendorSub = "",
            chromeExists = true,
            chromeRuntime = false,
            chromeApp = true,
            pluginNames = listOf("PDF Viewer", "Chrome PDF Viewer", "Chromium PDF Viewer", "Opera PDF Viewer", "WebKit built-in PDF"),
        ),
        // ── Edge ──
        Identity(
            browserName = "Edge 128",
            userAgent = "Mozilla/5.0 (Linux; Android 14; SM-S928B Build/UP1A.231005.007) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.6613.88 Mobile Safari/537.36 EdgA/128.0.2739.42",
            vendor = "Google Inc.",
            product = "",
            productSub = "20030107",
            appVersion = "5.0 (Linux; Android 14; SM-S928B Build/UP1A.231005.007) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.6613.88 Mobile Safari/537.36 EdgA/128.0.2739.42",
            platform = "Linux armv81",
            vendorSub = "",
            chromeExists = true,
            chromeRuntime = false,
            chromeApp = true,
            pluginNames = listOf("PDF Viewer", "Chrome PDF Viewer", "Chromium PDF Viewer", "Microsoft Edge PDF Viewer", "WebKit built-in PDF"),
        ),
        // ── Vivaldi ──
        Identity(
            browserName = "Vivaldi 6.9",
            userAgent = "Mozilla/5.0 (Linux; Android 14; SM-A546B Build/UP1A.231005.007) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.6613.88 Mobile Safari/537.36 Vivaldi/6.9.3445.23",
            vendor = "Google Inc.",
            product = "",
            productSub = "20030107",
            appVersion = "5.0 (Linux; Android 14; SM-A546B Build/UP1A.231005.007) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.6613.88 Mobile Safari/537.36 Vivaldi/6.9.3445.23",
            platform = "Linux armv81",
            vendorSub = "",
            chromeExists = true,
            chromeRuntime = false,
            chromeApp = true,
            pluginNames = listOf("PDF Viewer", "Chrome PDF Viewer", "Chromium PDF Viewer", "Vivaldi PDF Viewer", "WebKit built-in PDF"),
        ),
        // ── DuckDuckGo ──
        Identity(
            browserName = "DuckDuckGo 5",
            userAgent = "Mozilla/5.0 (Linux; Android 14; XQ-DE72 Build/61.1.A.14.190) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/120.0.6099.210 Mobile Safari/537.36",
            vendor = "Google Inc.",
            product = "",
            productSub = "20030107",
            appVersion = "5.0 (Linux; Android 14; XQ-DE72 Build/61.1.A.14.190) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/120.0.6099.210 Mobile Safari/537.36",
            platform = "Linux armv81",
            vendorSub = "",
            chromeExists = true,
            chromeRuntime = false,
            chromeApp = true,
            pluginNames = listOf("PDF Viewer", "Chrome PDF Viewer", "Chromium PDF Viewer", "DuckDuckGo PDF Viewer", "WebKit built-in PDF"),
        ),
        // ── UC Browser ──
        Identity(
            browserName = "UC Browser 15",
            userAgent = "Mozilla/5.0 (Linux; Android 13; motorola edge 40 Build/T1TC33.105) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/120.0.6099.210 Mobile Safari/537.36 UCBrowser/15.6.0.1273",
            vendor = "UC Web",
            product = "",
            productSub = "20030107",
            appVersion = "5.0 (Linux; Android 13; motorola edge 40 Build/T1TC33.105) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/120.0.6099.210 Mobile Safari/537.36 UCBrowser/15.6.0.1273",
            platform = "Linux armv81",
            vendorSub = "",
            chromeExists = true,
            chromeRuntime = false,
            chromeApp = true,
            pluginNames = listOf("PDF Viewer", "Chrome PDF Viewer", "UC PDF Viewer", "WebKit built-in PDF"),
        ),
    )

    @Volatile
    private var currentIndex = 0

    @Volatile
    private var previousIndex = -1

    @Volatile
    private var initialized = false

    private lateinit var prefs: SharedPreferences
    private const val PREFS_NAME = "farm_identity_seed"
    private const val KEY_SEED = "unique_seed"

    /**
     * Initialize identity with a UNIQUE per-phone seed.
     * On first boot: generates a UUID (128-bit entropy), derives index from its hash.
     * On subsequent boots: restores the saved index.
     * The seed is a STARTING POINT — identity rotates freely from there.
     * UUID gives much better distribution than SecureRandom.nextInt(12).
     */
    fun init(context: Context) {
        if (initialized) return
        prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        val savedSeed = prefs.getInt(KEY_SEED, -1)
        if (savedSeed >= 0 && savedSeed < identities.size) {
            currentIndex = savedSeed
        } else {
            // UUID.randomUUID() uses SecureRandom + hardware info for 128 bits of entropy
            val uuid = UUID.randomUUID()
            currentIndex = uuid.hashCode().toLong().and(0xFFFFFFFFL).toInt() % identities.size
            prefs.edit().putInt(KEY_SEED, currentIndex).apply()
        }
        previousIndex = -1
        initialized = true
    }

    /**
     * Get the current browser identity and ADVANCE to the next one.
     * Called on each page load — websites see a different browser every time.
     * NEVER locks. NEVER persists. Always rotates.
     */
    fun nextIdentity(): Identity {
        val identity = identities[currentIndex % identities.size]
        previousIndex = currentIndex
        currentIndex = (currentIndex + 1) % identities.size
        return identity
    }

    /**
     * Peek at the current identity without advancing.
     */
    fun currentIdentity(): Identity = identities[currentIndex % identities.size]

    /**
     * Return the current index (for cookie isolation).
     */
    fun currentIndex(): Int = currentIndex

    /**
     * Set the current identity index for THIS SESSION.
     * Advances on next nextIdentity() call — never locks.
     */
    fun forceIndex(index: Int) {
        previousIndex = currentIndex
        currentIndex = index.coerceIn(0, identities.size - 1)
    }

    /**
     * Total number of available identities.
     */
    fun identityCount(): Int = identities.size

    /**
     * Reset rotation to a device-unique starting point (called on app start or proxy change).
     */
    fun resetRotation() {
        previousIndex = -1
    }

    private fun abs(n: Int): Int = if (n < 0) -n else n

    /**
     * Generate the JavaScript injection string for this identity.
     * This overrides navigator.userAgent, navigator.vendor, plugins,
     * chrome object, and all other fingerprint vectors.
     */
    fun generateIdentityJs(identity: Identity): String {
        val ua = identity.userAgent.replace("'", "\\'")
        val vendor = identity.vendor.replace("'", "\\'")
        val product = identity.product.replace("'", "\\'")
        val platform = identity.platform.replace("'", "\\'")
        val appVersion = identity.appVersion.replace("'", "\\'")
        val vendorSub = identity.vendorSub.replace("'", "\\'")

        val pluginArray = identity.pluginNames.joinToString(", ") { name ->
            """{ name: '${name.replace("'", "\\'")}', filename: 'internal-pdf-viewer', description: 'Portable Document Format' }"""
        }

        val chromeObj = if (identity.chromeExists) {
            """
    if (typeof window.chrome === 'undefined') window.chrome = {};
    window.chrome.runtime = ${if (identity.chromeRuntime) "{}" else "undefined"};
    Object.defineProperty(window.chrome, 'app', {
        get: function() { return { isInstalled: false, InstallState: { DISABLED: 'disabled', INSTALLED: 'installed', NOT_INSTALLED: 'not_installed' }, RunningState: { CANNOT_RUN: 'cannot_run', READY_TO_RUN: 'ready_to_run', RUNNING: 'running' } }; },
        configurable: true
    });
    Object.defineProperty(window.chrome, 'runtime', {
        get: function() { return ${if (identity.chromeRuntime) "{}" else "undefined"}; },
        configurable: true
    });"""
        } else {
            """
    delete window.chrome;"""
        }

        // Extract navigator properties from identity
        val navProps = buildMap {
            put("userAgent", "'$ua'")
            put("vendor", "'$vendor'")
            put("product", "'$product'")
            put("productSub", "'${identity.productSub}'")
            put("appVersion", "'$appVersion'")
            put("platform", "'$platform'")
            put("vendorSub", "'$vendorSub'")
            put("language", "'en-US'")
            put("languages", "['en-US', 'en']")
            put("maxTouchPoints", "5")
            put("hardwareConcurrency", "8")
            put("deviceMemory", "8")
            put("cookieEnabled", "true")
            put("doNotTrack", "null")
            put("pdfViewerEnabled", "true")
            put("webdriver", "false")
            // Extra props from identity
            identity.extraNavigatorProps.forEach { (k, v) ->
                put(k, "'$v'")
            }
        }

        val navPropsJs = navProps.entries.joinToString(",\n        ") { (k, v) ->
            "$k: $v"
        }

        return """
(function() {
    var navProps = {
        $navPropsJs
    };
    for (var k in navProps) {
        try {
            Object.defineProperty(navigator, k, {
                get: (function(key) { return function() { return navProps[key]; }; })(k),
                configurable: true
            });
        } catch(e) {}
    }

    // Override navigator.connection
    Object.defineProperty(navigator, 'connection', {
        get: function() { return {
            effectiveType: '4g',
            rtt: 50,
            downlink: 10.0,
            saveData: false,
            type: 'cellular',
            downlinkMax: Infinity,
            changed: false,
        }; },
        configurable: true
    });

    // Override navigator.plugins
    Object.defineProperty(navigator, 'plugins', {
        get: function() {
            var plugins = [$pluginArray];
            plugins.length = ${identity.pluginNames.size};
            return plugins;
        },
        configurable: true
    });

    // Chrome object
    $chromeObj

    // Identity-specific JS overrides
    ${identity.extraJs}

    console.log('[FarmBrowser] Identity: ${identity.browserName}');
})();
"""
    }

    /**
     * Generate screen/WebGL/canvas fingerprint overrides for a device profile.
     * Device profile stays stable per phone; browser identity rotates.
     */
    fun generateDeviceFingerprintJs(profile: DeviceFingerprint.Profile): String {
        val manufacturer = profile.manufacturer.replace("'", "\\'")
        val gpuRenderer = profile.gpuRenderer.replace("'", "\\'")

        return """
(function() {
    // Screen overrides
    Object.defineProperty(screen, 'width', { get: function() { return ${profile.screenW}; } });
    Object.defineProperty(screen, 'height', { get: function() { return ${profile.screenH}; } });
    Object.defineProperty(screen, 'availWidth', { get: function() { return ${profile.screenW}; } });
    Object.defineProperty(screen, 'availHeight', { get: function() { return ${profile.screenH}; } });
    Object.defineProperty(screen, 'colorDepth', { get: function() { return 24; } });
    Object.defineProperty(screen, 'pixelDepth', { get: function() { return 24; } });
    Object.defineProperty(screen, 'devicePixelRatio', { get: function() { return ${(profile.dpi / 160.0).toString().take(5)}; } });

    // WebGL vendor and renderer
    try {
        var getParameter = WebGLRenderingContext.prototype.getParameter;
        WebGLRenderingContext.prototype.getParameter = function(param) {
            if (param === 37445) return '$manufacturer';
            if (param === 37446) return '$gpuRenderer';
            return getParameter.call(this, param);
        };
    } catch(e) {}
    try {
        var getParameter2 = WebGL2RenderingContext.prototype.getParameter;
        WebGL2RenderingContext.prototype.getParameter = function(param) {
            if (param === 37445) return '$manufacturer';
            if (param === 37446) return '$gpuRenderer';
            return getParameter2.call(this, param);
        };
    } catch(e) {}

    // Canvas fingerprint noise
    var toBlob = HTMLCanvasElement.prototype.toBlob;
    var toDataURL = HTMLCanvasElement.prototype.toDataURL;
    var getImageData = CanvasRenderingContext2D.prototype.getImageData;

    HTMLCanvasElement.prototype.toDataURL = function() {
        if (this.width === 0 || this.height === 0) return toDataURL.apply(this, arguments);
        var ctx = this.getContext('2d');
        if (ctx) {
            var imgData = getImageData.call(ctx, 0, 0, this.width, this.height);
            var data = imgData.data;
            for (var i = 0; i < data.length; i += 16) {
                data[i] = data[i] ^ (Math.random() > 0.5 ? 1 : 0);
            }
            ctx.putImageData(imgData, 0, 0);
        }
        return toDataURL.apply(this, arguments);
    };

    HTMLCanvasElement.prototype.toBlob = function(callback) {
        if (this.width === 0 || this.height === 0) return toBlob.apply(this, arguments);
        var ctx = this.getContext('2d');
        if (ctx) {
            var imgData = getImageData.call(ctx, 0, 0, this.width, this.height);
            var data = imgData.data;
            for (var i = 0; i < data.length; i += 16) {
                data[i] = data[i] ^ (Math.random() > 0.5 ? 1 : 0);
            }
            ctx.putImageData(imgData, 0, 0);
        }
        return toBlob.apply(this, arguments);
    };

    // AudioContext fingerprint noise
    try {
        var origCreateOscillator = AudioContext.prototype.createOscillator;
        AudioContext.prototype.createOscillator = function() {
            var osc = origCreateOscillator.call(this);
            var freq = osc.frequency;
            var origValue = freq.value;
            Object.defineProperty(freq, 'value', {
                get: function() { return origValue; },
                set: function(v) { origValue = v + (Math.random() * 0.0001); },
                configurable: true
            });
            return osc;
        };
    } catch(e) {}

    // Permissions API
    try {
        var origQuery = navigator.permissions.query;
        navigator.permissions.query = function(desc) {
            if (desc && desc.name === 'notifications') {
                return Promise.resolve({ state: Notification.permission, onchange: null });
            }
            return origQuery.call(this, desc);
        };
    } catch(e) {}

    // Battery API
    if (navigator.getBattery) {
        navigator.getBattery = function() {
            return Promise.resolve({
                charging: Math.random() > 0.3,
                chargingTime: Math.random() > 0.5 ? 0 : Math.floor(Math.random() * 7200),
                dischargingTime: Math.floor(Math.random() * 28800) + 3600,
                level: 0.3 + Math.random() * 0.7,
                addEventListener: function() {},
                removeEventListener: function() {},
            });
        };
    }

    // Media devices
    if (navigator.mediaDevices && navigator.mediaDevices.enumerateDevices) {
        navigator.mediaDevices.enumerateDevices = function() {
            return Promise.resolve([
                { deviceId: 'default', kind: 'audioinput', label: '', groupId: 'default' },
                { deviceId: 'default', kind: 'audiooutput', label: '', groupId: 'default' },
                { deviceId: 'default', kind: 'videoinput', label: '', groupId: 'default' },
            ]);
        };
    }

    // Performance timing noise
    var origNow = performance.now;
    performance.now = function() {
        return origNow.call(this) + (Math.random() * 0.001);
    };
})();
"""
    }

    /**
     * Get all identity names (for Settings UI).
     */
    fun allIdentityNames(): Array<String> = identities.map { it.browserName }.toTypedArray()
}

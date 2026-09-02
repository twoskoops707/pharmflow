package com.farmbrowser.stealth.stealth

import android.content.Context
import android.os.Build
import android.util.Log
import java.security.SecureRandom

/**
 * Randomized device fingerprint profiles.
 * Each profile mimics a real retail phone (brand, model, Android version, build ID, UA).
 * Profiles are assigned per-emulator and stored persistently.
 */
object DeviceFingerprint {
    private const val TAG = "DeviceFingerprint"
    private const val PREFS = "farm_fp"

    data class Profile(
        val key: String,
        val brand: String,
        val manufacturer: String,
        val model: String,
        val device: String,
        val androidRelease: String,
        val sdkInt: Int,
        val buildId: String,
        val userAgent: String,
        val screenW: Int,
        val screenH: Int,
        val dpi: Int,
        val gpuRenderer: String,
        val hardware: String,
    )

    private val profiles = arrayOf(
        Profile(
            key = "pixel_8",
            brand = "google", manufacturer = "Google", model = "Pixel 8",
            device = "shiba", androidRelease = "14", sdkInt = 34,
            buildId = "AP2A.240805.005",
            userAgent = "Mozilla/5.0 (Linux; Android 14; Pixel 8 Build/AP2A.240805.005) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/128.0.6613.88 Mobile Safari/537.36",
            screenW = 412, screenH = 915, dpi = 420,
            gpuRenderer = "Adreno (TM) 730",
            hardware = "shiba",
        ),
        Profile(
            key = "pixel_7a",
            brand = "google", manufacturer = "Google", model = "Pixel 7a",
            device = "lynx", androidRelease = "14", sdkInt = 34,
            buildId = "AP2A.240805.005",
            userAgent = "Mozilla/5.0 (Linux; Android 14; Pixel 7a Build/AP2A.240805.005) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/128.0.6613.88 Mobile Safari/537.36",
            screenW = 412, screenH = 915, dpi = 420,
            gpuRenderer = "Adreno (TM) 642L",
            hardware = "lynx",
        ),
        Profile(
            key = "pixel_8_pro",
            brand = "google", manufacturer = "Google", model = "Pixel 8 Pro",
            device = "husky", androidRelease = "14", sdkInt = 34,
            buildId = "AP2A.240805.005",
            userAgent = "Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro Build/AP2A.240805.005) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/128.0.6613.88 Mobile Safari/537.36",
            screenW = 430, screenH = 965, dpi = 489,
            gpuRenderer = "Adreno (TM) 750",
            hardware = "husky",
        ),
        Profile(
            key = "sm_s921b",
            brand = "samsung", manufacturer = "samsung", model = "SM-S921B",
            device = "e3q", androidRelease = "14", sdkInt = 34,
            buildId = "UP1A.231005.007",
            userAgent = "Mozilla/5.0 (Linux; Android 14; SM-S921B Build/UP1A.231005.007) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/128.0.6613.88 Mobile Safari/537.36",
            screenW = 360, screenH = 780, dpi = 480,
            gpuRenderer = "Adreno (TM) 750",
            hardware = "qcom",
        ),
        Profile(
            key = "sm_s928b",
            brand = "samsung", manufacturer = "samsung", model = "SM-S928B",
            device = "e3q", androidRelease = "14", sdkInt = 34,
            buildId = "UP1A.231005.007",
            userAgent = "Mozilla/5.0 (Linux; Android 14; SM-S928B Build/UP1A.231005.007) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/128.0.6613.88 Mobile Safari/537.36",
            screenW = 384, screenH = 854, dpi = 505,
            gpuRenderer = "Adreno (TM) 750",
            hardware = "qcom",
        ),
        Profile(
            key = "oneplus_12",
            brand = "OnePlus", manufacturer = "OnePlus", model = "CPH2581",
            device = "ikju", androidRelease = "14", sdkInt = 34,
            buildId = "UP1A.231005.007",
            userAgent = "Mozilla/5.0 (Linux; Android 14; CPH2581 Build/UP1A.231005.007) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/128.0.6613.88 Mobile Safari/537.36",
            screenW = 412, screenH = 915, dpi = 450,
            gpuRenderer = "Adreno (TM) 750",
            hardware = "qcom",
        ),
        Profile(
            key = "xiaomi_14",
            brand = "Xiaomi", manufacturer = "Xiaomi", model = "23127PN0CC",
            device = "houji", androidRelease = "14", sdkInt = 34,
            buildId = "UKQ1.240116.001",
            userAgent = "Mozilla/5.0 (Linux; Android 14; 23127PN0CC Build/UKQ1.240116.001) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/128.0.6613.88 Mobile Safari/537.36",
            screenW = 393, screenH = 851, dpi = 460,
            gpuRenderer = "Adreno (TM) 750",
            hardware = "qcom",
        ),
        Profile(
            key = "sm_a546b",
            brand = "samsung", manufacturer = "samsung", model = "SM-A546B",
            device = "a54x", androidRelease = "14", sdkInt = 34,
            buildId = "UP1A.231005.007",
            userAgent = "Mozilla/5.0 (Linux; Android 14; SM-A546B Build/UP1A.231005.007) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/128.0.6613.88 Mobile Safari/537.36",
            screenW = 360, screenH = 800, dpi = 403,
            gpuRenderer = "Adreno (TM) 710",
            hardware = "s5e8834",
        ),
        Profile(
            key = "sony_xperia5v",
            brand = "Sony", manufacturer = "Sony", model = "XQ-DE72",
            device = "XQ-DE72", androidRelease = "13", sdkInt = 33,
            buildId = "61.1.A.14.190",
            userAgent = "Mozilla/5.0 (Linux; Android 13; XQ-DE72 Build/61.1.A.14.190) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/120.0.6099.210 Mobile Safari/537.36",
            screenW = 360, screenH = 810, dpi = 449,
            gpuRenderer = "Adreno (TM) 660",
            hardware = "qcom",
        ),
        Profile(
            key = "moto_edge_40",
            brand = "motorola", manufacturer = "motorola", model = "motorola edge 40",
            device = "dmong", androidRelease = "13", sdkInt = 33,
            buildId = "T1TC33.105",
            userAgent = "Mozilla/5.0 (Linux; Android 13; motorola edge 40 Build/T1TC33.105) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/120.0.6099.210 Mobile Safari/537.36",
            screenW = 360, screenH = 800, dpi = 400,
            gpuRenderer = "Adreno (TM) 644",
            hardware = "qcom",
        ),
    )

    private lateinit var prefs: android.content.SharedPreferences
    private var activeProfile: Profile? = null
    private val random = SecureRandom()

    fun init(context: Context) {
        prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
    }

    /**
     * Get or assign a stable profile for this device.
     * Uses the device's serial or android_id as the seed for stable assignment.
     */
    fun getProfile(context: Context): Profile {
        if (activeProfile != null) return activeProfile!!

        val savedIdx = prefs.getInt("profile_idx", -1)
        if (savedIdx in profiles.indices) {
            activeProfile = profiles[savedIdx]
            return activeProfile!!
        }

        // Assign based on a hash of the device's android_id for stability
        val androidId = try {
            android.provider.Settings.Secure.getString(
                context.contentResolver, android.provider.Settings.Secure.ANDROID_ID
            ) ?: ""
        } catch (_: Exception) { "" }

        val idx = if (androidId.isNotBlank()) {
            Math.abs(androidId.hashCode()) % profiles.size
        } else {
            random.nextInt(profiles.size)
        }
        prefs.edit().putInt("profile_idx", idx).apply()
        activeProfile = profiles[idx]
        return activeProfile!!
    }

    /**
     * Get all available profiles.
     */
    fun allProfiles(): Array<Profile> = profiles

    /**
     * Force a specific profile index.
     */
    fun setProfile(context: Context, index: Int) {
        if (index in profiles.indices) {
            prefs.edit().putInt("profile_idx", index).apply()
            activeProfile = profiles[index]
        }
    }

    /**
     * Set profile index without Context — uses already-initialized prefs.
     */
    fun setProfileIndex(index: Int) {
        if (index in profiles.indices) {
            if (::prefs.isInitialized) {
                prefs.edit().putInt("profile_idx", index).apply()
            }
            activeProfile = profiles[index]
        }
    }

    /**
     * JS code to override navigator properties with profile data.
     */
    fun navigatorOverrides(profile: Profile): String {
        val chromeVersion = Regex("Chrome/([\\d.]+)").find(profile.userAgent)
            ?.groupValues?.get(1) ?: "128.0.6613.88"
        val majorVersion = chromeVersion.split(".").firstOrNull() ?: "128"
        val platformVersion = profile.androidRelease

        return """
(function() {
    var navProps = {
        userAgent: '${profile.userAgent.replace("'", "\\'")}',
        platform: 'Linux armv81',
        appVersion: '${profile.userAgent.replace("'", "\\'").substringAfter("Mozilla/5.0 ")}',
        product: 'Gecko',
        productSub: '20030107',
        vendor: 'Google Inc.',
        vendorSub: '',
        language: 'en-US',
        languages: ['en-US', 'en'],
        maxTouchPoints: 5,
        hardwareConcurrency: 8,
        deviceMemory: 8,
        cookieEnabled: true,
        doNotTrack: null,
        pdfViewerEnabled: true,
        webdriver: false,
    };
    for (var k in navProps) {
        try {
            Object.defineProperty(navigator, k, {
                get: function() { return navProps[k]; },
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
            var plugins = [
                { name: 'PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
                { name: 'Chrome PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
                { name: 'Chromium PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
                { name: 'Microsoft Edge PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
                { name: 'WebKit built-in PDF', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
            ];
            plugins.length = 5;
            return plugins;
        },
        configurable: true
    });

    // Override chrome object
    if (typeof window.chrome === 'undefined') {
        window.chrome = {};
    }
    window.chrome.runtime = undefined;
    Object.defineProperty(window.chrome, 'app', {
        get: function() { return { isInstalled: false, InstallState: { DISABLED: 'disabled', INSTALLED: 'installed', NOT_INSTALLED: 'not_installed' }, RunningState: { CANNOT_RUN: 'cannot_run', READY_TO_RUN: 'ready_to_run', RUNNING: 'running' } }; },
        configurable: true
    });
    Object.defineProperty(window.chrome, 'runtime', {
        get: function() { return undefined; },
        configurable: true
    });
})();
"""
    }

    /**
     * JS code to override screen, WebGL, canvas, and other fingerprint vectors.
     */
    fun fingerprintOverrides(profile: Profile): String {
        return """
(function() {
    // Screen overrides
    Object.defineProperty(screen, 'width', { get: function() { return ${profile.screenW}; } });
    Object.defineProperty(screen, 'height', { get: function() { return ${profile.screenH}; } });
    Object.defineProperty(screen, 'availWidth', { get: function() { return ${profile.screenW}; } });
    Object.defineProperty(screen, 'availHeight', { get: function() { return ${profile.screenH}; } });
    Object.defineProperty(screen, 'colorDepth', { get: function() { return 24; } });
    Object.defineProperty(screen, 'pixelDepth', { get: function() { return 24; } });
    Object.defineProperty(screen, 'devicePixelRatio', { get: function() { return 2.625; } });

    // WebGL vendor and renderer
    var getParameter = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function(param) {
        if (param === 37445) return '${profile.manufacturer.replace("'", "\\'")}';
        if (param === 37446) return '${profile.gpuRenderer.replace("'", "\\'")}';
        return getParameter.call(this, param);
    };
    var getParameter2 = WebGL2RenderingContext.prototype.getParameter;
    WebGL2RenderingContext.prototype.getParameter = function(param) {
        if (param === 37445) return '${profile.manufacturer.replace("'", "\\'")}';
        if (param === 37446) return '${profile.gpuRenderer.replace("'", "\\'")}';
        return getParameter2.call(this, param);
    };

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
            // Subtle per-pixel noise (1 bit max)
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
    var origCreateOscillator = AudioContext.prototype.createOscillator;
    if (origCreateOscillator) {
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
    }

    // Permissions API spoof
    var origQuery = navigator.permissions.query;
    navigator.permissions.query = function(desc) {
        if (desc && desc.name === 'notifications') {
            return Promise.resolve({ state: Notification.permission, onchange: null });
        }
        return origQuery.call(this, desc);
    };

    // Timezone consistency
    Intl.DateTimeFormat = (function(orig) {
        return function() {
            var args = Array.prototype.slice.call(arguments);
            return new orig(args[0], args[1]);
        };
    })(Intl.DateTimeFormat);

    // Battery API spoof
    if (navigator.getBattery) {
        navigator.getBattery = function() {
            return Promise.resolve({
                charging: Math.random() > 0.3,
                chargingTime: Math.random() > 0.5 ? 0 : Math.floor(Math.random() * 7200),
                dischargingTime: Math.floor(Math.random() * 28800) + 3600,
                level: 0.3 + Math.random() * 0.7,
                addEventListener: function() {},
                removeEventListener: function() {},
                onchargingchange: null,
                onchargingtimechange: null,
                ondischargingtimechange: null,
                onlevelchange: null,
            });
        };
    }

    // Speech synthesis voices (prevent enumeration fingerprinting)
    if (window.speechSynthesis && window.speechSynthesis.getVoices) {
        var origGetVoices = window.speechSynthesis.getVoices;
        window.speechSynthesis.getVoices = function() {
            return [];
        };
    }

    // Media devices enumeration (prevent fingerprinting via device count)
    if (navigator.mediaDevices && navigator.mediaDevices.enumerateDevices) {
        var origEnum = navigator.mediaDevices.enumerateDevices;
        navigator.mediaDevices.enumerateDevices = function() {
            return Promise.resolve([
                { deviceId: 'default', kind: 'audioinput', label: '', groupId: 'default' },
                { deviceId: 'default', kind: 'audiooutput', label: '', groupId: 'default' },
                { deviceId: 'default', kind: 'videoinput', label: '', groupId: 'default' },
            ]);
        };
    }

    // Storage API consistency
    Object.defineProperty(localStorage, 'length', {
        get: function() { return Object.keys(localStorage).length; }
    });

    // Performance timing noise (sub-ms jitter only)
    var origNow = performance.now;
    performance.now = function() {
        return origNow.call(this) + (Math.random() * 0.001);
    };

    console.log('[FarmBrowser] Stealth fingerprints applied');
})();
"""
    }

    /**
     * User-Agent header override for network requests.
     */
    fun userAgentHeader(profile: Profile): String = profile.userAgent

    /**
     * Accept-Language header.
     */
    fun acceptLanguage(): String = "en-US,en;q=0.9"
}

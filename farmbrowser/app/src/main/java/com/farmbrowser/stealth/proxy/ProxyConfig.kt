package com.farmbrowser.stealth.proxy

import android.content.Context
import android.content.SharedPreferences

/**
 * Persistent proxy configuration.
 * Stores proxy type, host, port, and optional credentials.
 * Supports: NONE, HTTP, HTTPS, SOCKS5
 */
object ProxyConfig {
    private const val PREFS = "farm_proxy_cfg"

    enum class Type { NONE, HTTP, SOCKS5 }

    private lateinit var prefs: SharedPreferences

    fun init(ctx: Context) {
        prefs = ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
    }

    var type: Type
        get() = try { Type.valueOf(prefs.getString("type", "NONE")!!) } catch (_: Exception) { Type.NONE }
        set(v) { prefs.edit().putString("type", v.name).apply() }

    var host: String
        get() = prefs.getString("host", "") ?: ""
        set(v) { prefs.edit().putString("host", v).apply() }

    var port: Int
        get() = prefs.getInt("port", 0)
        set(v) { prefs.edit().putInt("port", v).apply() }

    var username: String
        get() = prefs.getString("user", "") ?: ""
        set(v) { prefs.edit().putString("user", v).apply() }

    var password: String
        get() = prefs.getString("pass", "") ?: ""
        set(v) { prefs.edit().putString("pass", v).apply() }

    var enabled: Boolean
        get() = prefs.getBoolean("enabled", false)
        set(v) { prefs.edit().putBoolean("enabled", v).apply() }

    var autoDetectTor: Boolean
        get() = prefs.getBoolean("auto_detect_tor", true)
        set(v) { prefs.edit().putBoolean("auto_detect_tor", v).apply() }

    val isActive: Boolean get() = enabled && type != Type.NONE && host.isNotBlank() && port > 0

    fun httpProxyUrl(): String? {
        if (!isActive) return null
        return "http://$host:$port"
    }

    fun socksUrl(): String? {
        if (!isActive || type != Type.SOCKS5) return null
        return "socks5://$host:$port"
    }

    fun summary(): String {
        if (!isActive) return "Direct (no proxy)"
        val auth = if (username.isNotBlank()) " [auth]" else ""
        return "${type.name} $host:$port$auth"
    }
}

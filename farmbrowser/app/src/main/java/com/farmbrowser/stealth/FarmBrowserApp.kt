package com.farmbrowser.stealth

import android.app.Application
import android.app.NotificationChannel
import android.app.NotificationManager
import android.os.Build
import com.farmbrowser.stealth.proxy.ProxyConfig
import com.farmbrowser.stealth.stealth.CookieIsolation
import com.farmbrowser.stealth.stealth.DeviceFingerprint
import com.farmbrowser.stealth.stealth.BrowserIdentity
import com.farmbrowser.stealth.stealth.DnsOverHttps

class FarmBrowserApp : Application() {

    override fun onCreate() {
        super.onCreate()
        instance = this
        createNotificationChannels()
        ProxyConfig.init(this)
        DeviceFingerprint.init(this)
        CookieIsolation.setAppContext(this)
        CookieIsolation.init(this)
        BrowserIdentity.init(this)
        DnsOverHttps.init(cacheDir)
    }

    private fun createNotificationChannels() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val manager = getSystemService(NotificationManager::class.java)
            val channel = NotificationChannel(
                CHANNEL_PROXY,
                "Proxy Service",
                NotificationManager.IMPORTANCE_LOW
            ).apply {
                description = "Local proxy tunnel status"
                setShowBadge(false)
            }
            manager.createNotificationChannel(channel)
        }
    }

    companion object {
        const val CHANNEL_PROXY = "farm_proxy"
        lateinit var instance: FarmBrowserApp
            private set
    }
}

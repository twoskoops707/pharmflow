package com.farmbrowser.stealth.proxy

import android.app.Notification
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.IBinder
import com.farmbrowser.stealth.FarmBrowserApp
import com.farmbrowser.stealth.R
import com.farmbrowser.stealth.browser.BrowserActivity

/**
 * Foreground service that keeps the local HTTP-to-SOCKS5 tunnel running
 * even when the browser activity is in the background.
 */
class LocalProxyService : Service() {

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        startForeground(NOTIFICATION_ID, createNotification())
        HttpProxyServer.start()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_START -> {
                HttpProxyServer.start()
                updateNotification("Proxy tunnel active")
            }
            ACTION_STOP -> {
                HttpProxyServer.stop()
                stopForeground(STOP_FOREGROUND_REMOVE)
                stopSelf()
            }
            ACTION_UPDATE -> {
                val host = intent.getStringExtra(EXTRA_HOST) ?: ""
                val port = intent.getIntExtra(EXTRA_PORT, 0)
                val type = intent.getStringExtra(EXTRA_TYPE) ?: "HTTP"
                if (host.isNotBlank() && port > 0) {
                    ProxyConfig.host = host
                    ProxyConfig.port = port
                    ProxyConfig.type = if (type == "SOCKS5") ProxyConfig.Type.SOCKS5 else ProxyConfig.Type.HTTP
                    ProxyConfig.enabled = true
                    HttpProxyServer.start()
                    updateNotification("Proxy: $type $host:$port")
                }
            }
        }
        return START_STICKY
    }

    override fun onDestroy() {
        HttpProxyServer.stop()
        super.onDestroy()
    }

    private fun createNotification(): Notification {
        val pendingIntent = PendingIntent.getActivity(
            this, 0,
            Intent(this, BrowserActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )

        val builder = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            Notification.Builder(this, FarmBrowserApp.CHANNEL_PROXY)
        } else {
            @Suppress("DEPRECATION")
            Notification.Builder(this)
        }

        return builder
            .setContentTitle("FarmBrowser Proxy")
            .setContentText("Proxy tunnel active")
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setContentIntent(pendingIntent)
            .setOngoing(true)
            .build()
    }

    private fun updateNotification(text: String) {
        val builder = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            Notification.Builder(this, FarmBrowserApp.CHANNEL_PROXY)
        } else {
            @Suppress("DEPRECATION")
            Notification.Builder(this)
        }
        val updated = builder
            .setContentTitle("FarmBrowser Proxy")
            .setContentText(text)
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setOngoing(true)
            .build()
        val nm = getSystemService(NOTIFICATION_SERVICE) as android.app.NotificationManager
        nm.notify(NOTIFICATION_ID, updated)
    }

    companion object {
        const val NOTIFICATION_ID = 7701
        const val ACTION_START = "com.farmbrowser.stealth.proxy.START"
        const val ACTION_STOP = "com.farmbrowser.stealth.proxy.STOP"
        const val ACTION_UPDATE = "com.farmbrowser.stealth.proxy.UPDATE"
        const val EXTRA_HOST = "host"
        const val EXTRA_PORT = "port"
        const val EXTRA_TYPE = "type"

        fun start(context: Context, host: String, port: Int, type: String) {
            val intent = Intent(context, LocalProxyService::class.java).apply {
                action = ACTION_UPDATE
                putExtra(EXTRA_HOST, host)
                putExtra(EXTRA_PORT, port)
                putExtra(EXTRA_TYPE, type)
            }
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                context.startForegroundService(intent)
            } else {
                context.startService(intent)
            }
        }

        fun stop(context: Context) {
            val intent = Intent(context, LocalProxyService::class.java).apply {
                action = ACTION_STOP
            }
            context.startService(intent)
        }
    }
}

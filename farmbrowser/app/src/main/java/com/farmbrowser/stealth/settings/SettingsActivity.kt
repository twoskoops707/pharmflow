package com.farmbrowser.stealth.settings

import android.app.Activity
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.View
import android.widget.*
import com.farmbrowser.stealth.R
import com.farmbrowser.stealth.proxy.HttpProxyServer
import com.farmbrowser.stealth.proxy.ProxyConfig
import com.farmbrowser.stealth.proxy.ProxyManager
import com.farmbrowser.stealth.stealth.DeviceFingerprint
import java.util.concurrent.Executors

class SettingsActivity : Activity() {

    private lateinit var proxyEnabled: CheckBox
    private lateinit var proxyTypeSpinner: Spinner
    private lateinit var proxyHost: EditText
    private lateinit var proxyPort: EditText
    private lateinit var proxyUser: EditText
    private lateinit var proxyPass: EditText
    private lateinit var autoDetectTor: CheckBox
    private lateinit var btnApply: Button
    private lateinit var btnClear: Button
    private lateinit var proxyStatus: TextView
    private lateinit var profileSpinner: Spinner
    private lateinit var profileInfo: TextView
    private lateinit var btnTestProxy: Button

    private val handler = Handler(Looper.getMainLooper())
    private val executor = Executors.newSingleThreadExecutor()

    private val proxyTypes = arrayOf("HTTP", "SOCKS5 (Tor)")

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_settings)

        initViews()
        loadCurrentConfig()
        setupListeners()
    }

    private fun initViews() {
        proxyEnabled = findViewById(R.id.proxy_enabled)
        proxyTypeSpinner = findViewById(R.id.proxy_type)
        proxyHost = findViewById(R.id.proxy_host)
        proxyPort = findViewById(R.id.proxy_port)
        proxyUser = findViewById(R.id.proxy_user)
        proxyPass = findViewById(R.id.proxy_pass)
        autoDetectTor = findViewById(R.id.auto_detect_tor)
        btnApply = findViewById(R.id.btn_apply_proxy)
        btnClear = findViewById(R.id.btn_clear_proxy)
        proxyStatus = findViewById(R.id.proxy_status)
        profileSpinner = findViewById(R.id.profile_spinner)
        profileInfo = findViewById(R.id.profile_info)
        btnTestProxy = findViewById(R.id.btn_test_proxy)

        // Proxy type spinner
        proxyTypeSpinner.adapter = ArrayAdapter(
            this, android.R.layout.simple_spinner_dropdown_item, proxyTypes
        )

        // Profile spinner
        val profiles = DeviceFingerprint.allProfiles()
        val profileNames = profiles.map { "${it.brand} ${it.model}" }.toTypedArray()
        profileSpinner.adapter = ArrayAdapter(
            this, android.R.layout.simple_spinner_dropdown_item, profileNames
        )
    }

    private fun loadCurrentConfig() {
        proxyEnabled.isChecked = ProxyConfig.enabled
        proxyTypeSpinner.setSelection(
            when (ProxyConfig.type) {
                ProxyConfig.Type.SOCKS5 -> 1
                else -> 0
            }
        )
        proxyHost.setText(ProxyConfig.host)
        proxyPort.setText(if (ProxyConfig.port > 0) ProxyConfig.port.toString() else "")
        proxyUser.setText(ProxyConfig.username)
        proxyPass.setText(ProxyConfig.password)
        autoDetectTor.isChecked = ProxyConfig.autoDetectTor

        val profile = DeviceFingerprint.getProfile(this)
        val profileIdx = DeviceFingerprint.allProfiles().indexOfFirst { it.key == profile.key }
        if (profileIdx >= 0) profileSpinner.setSelection(profileIdx)
        updateProfileInfo(profile)

        updateProxyStatus()
    }

    private fun setupListeners() {
        btnApply.setOnClickListener { applyProxyConfig() }
        btnClear.setOnClickListener { clearProxyConfig() }
        btnTestProxy.setOnClickListener { testProxy() }

        profileSpinner.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
            override fun onItemSelected(parent: AdapterView<*>?, view: View?, pos: Int, id: Long) {
                val profiles = DeviceFingerprint.allProfiles()
                if (pos in profiles.indices) {
                    updateProfileInfo(profiles[pos])
                    // Save profile selection
                    DeviceFingerprint.setProfile(this@SettingsActivity, pos)
                }
            }
            override fun onNothingSelected(parent: AdapterView<*>?) {}
        }
    }

    private fun applyProxyConfig() {
        val type = when (proxyTypeSpinner.selectedItemPosition) {
            1 -> ProxyConfig.Type.SOCKS5
            else -> ProxyConfig.Type.HTTP
        }
        val host = proxyHost.text.toString().trim()
        val portStr = proxyPort.text.toString().trim()
        val port = portStr.toIntOrNull() ?: 0

        if (host.isBlank() || port <= 0) {
            proxyStatus.text = "ERROR: Host and port are required"
            return
        }

        ProxyConfig.enabled = proxyEnabled.isChecked
        ProxyConfig.type = type
        ProxyConfig.host = host
        ProxyConfig.port = port
        ProxyConfig.username = proxyUser.text.toString().trim()
        ProxyConfig.password = proxyPass.text.toString().trim()
        ProxyConfig.autoDetectTor = autoDetectTor.isChecked

        if (type == ProxyConfig.Type.SOCKS5) {
            ProxyManager.ensureLocalTunnel()
        }

        updateProxyStatus()
        Toast.makeText(this, "Proxy configuration saved", Toast.LENGTH_SHORT).show()
    }

    private fun clearProxyConfig() {
        ProxyManager.clearProxy(this)
        proxyEnabled.isChecked = false
        proxyTypeSpinner.setSelection(0)
        proxyHost.setText("")
        proxyPort.setText("")
        proxyUser.setText("")
        proxyPass.setText("")
        updateProxyStatus()
        Toast.makeText(this, "Proxy cleared", Toast.LENGTH_SHORT).show()
    }

    private fun testProxy() {
        btnTestProxy.isEnabled = false
        proxyStatus.text = "Testing proxy connection..."

        executor.execute {
            val isLocalRunning = HttpProxyServer.testConnection()
            val isUpstreamOk = if (ProxyConfig.isActive) HttpProxyServer.testUpstream() else false

            handler.post {
                val msg = buildString {
                    appendLine("=== Proxy Test Results ===")
                    appendLine("Local tunnel: ${if (isLocalRunning) "✓ Running" else "✗ Not running"}")
                    if (ProxyConfig.isActive) {
                        appendLine("Upstream: ${if (isUpstreamOk) "✓ Reachable" else "✗ Unreachable"}")
                        appendLine("Type: ${ProxyConfig.type.name}")
                        appendLine("Target: ${ProxyConfig.host}:${ProxyConfig.port}")
                    } else {
                        appendLine("No proxy configured")
                    }
                    appendLine("Mode: ${ProxyManager.activeMode.name}")
                }
                proxyStatus.text = msg
                btnTestProxy.isEnabled = true
            }
        }
    }

    private fun updateProxyStatus() {
        val report = ProxyManager.statusReport()
        val status = buildString {
            append("Mode: ${report["mode"]}\n")
            append("Type: ${report["type"]}\n")
            append("Host: ${report["host"]}:${report["port"]}\n")
            append("Tunnel: ${report["http_tunnel_running"]}\n")
            append("WebView: ${report["webview_proxy"]}")
        }
        proxyStatus.text = status
    }

    private fun updateProfileInfo(profile: DeviceFingerprint.Profile) {
        profileInfo.text = buildString {
            appendLine("Brand: ${profile.brand}")
            appendLine("Model: ${profile.model}")
            appendLine("Android: ${profile.androidRelease} (SDK ${profile.sdkInt})")
            appendLine("Build: ${profile.buildId}")
            appendLine("GPU: ${profile.gpuRenderer}")
            appendLine("Screen: ${profile.screenW}x${profile.screenH} @${profile.dpi}dpi")
            appendLine("UA: ${profile.userAgent.take(80)}...")
        }
    }
}

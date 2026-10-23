package com.pharmflow.scorecard

import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.widget.EditText
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import com.google.android.material.button.MaterialButton
import kotlin.concurrent.thread

class MainActivity : AppCompatActivity() {

    private val prefsName = "pharmflow_scorecard"

    private lateinit var laptopUrl: EditText
    private lateinit var statusDot: TextView
    private lateinit var statusTitle: TextView
    private lateinit var statusPhones: TextView
    private lateinit var messageLine: TextView

    private var baseUrl: String = ""
    private var connected = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        laptopUrl = findViewById(R.id.laptopUrl)
        statusDot = findViewById(R.id.statusDot)
        statusTitle = findViewById(R.id.statusTitle)
        statusPhones = findViewById(R.id.statusPhones)
        messageLine = findViewById(R.id.messageLine)

        loadPrefs()
        wireButtons()
        refreshStatusQuiet()
    }

    override fun onResume() {
        super.onResume()
        if (baseUrl.isNotEmpty()) {
            refreshStatusQuiet()
        }
    }

    private fun loadPrefs() {
        val p = getSharedPreferences(prefsName, Context.MODE_PRIVATE)
        laptopUrl.setText(p.getString("farm_url", ""))
        baseUrl = FarmApi.normalizeBaseUrl(laptopUrl.text.toString())
    }

    private fun saveUrl(url: String) {
        getSharedPreferences(prefsName, Context.MODE_PRIVATE)
            .edit()
            .putString("farm_url", url)
            .apply()
    }

    private fun wireButtons() {
        findViewById<MaterialButton>(R.id.btnConnect).setOnClickListener { connect() }
        findViewById<MaterialButton>(R.id.btnFindPhones).setOnClickListener { findPhones() }
        findViewById<MaterialButton>(R.id.btnGo).setOnClickListener { runFarm() }
        findViewById<MaterialButton>(R.id.btnStop).setOnClickListener { stopFarm() }
        findViewById<MaterialButton>(R.id.btnTor).setOnClickListener { torOn() }
        findViewById<MaterialButton>(R.id.btnNewFaces).setOnClickListener { newFaces() }
        findViewById<MaterialButton>(R.id.btnMoney).setOnClickListener {
            startActivity(Intent(this, ScorecardActivity::class.java))
        }
    }

    private fun requireUrl(): String? {
        baseUrl = FarmApi.normalizeBaseUrl(laptopUrl.text.toString())
        if (baseUrl.isEmpty()) {
            showMessage(getString(R.string.need_wifi))
            setConnected(false, 0, 0)
            return null
        }
        saveUrl(laptopUrl.text.toString().trim())
        return baseUrl
    }

    private fun connect() {
        val url = requireUrl() ?: return
        showMessage(getString(R.string.working_on_it))
        thread {
            try {
                val ip = FarmApi.get(url, "/api/ip")
                val phones = FarmApi.get(url, "/api/phones")
                val snap = FarmApi.parsePhones(phones)
                runOnUiThread {
                    connected = true
                    val dash = ip.optString("dashboard_url", url)
                    setConnected(true, snap.online, snap.total)
                    showMessage(getString(R.string.connected) + " " + dash)
                }
            } catch (e: Exception) {
                runOnUiThread {
                    connected = false
                    setConnected(false, 0, 0)
                    showMessage("${getString(R.string.not_connected)}: ${e.message}")
                }
            }
        }
    }

    private fun refreshStatusQuiet() {
        val url = requireUrl() ?: return
        thread {
            try {
                val phones = FarmApi.get(url, "/api/phones")
                val snap = FarmApi.parsePhones(phones)
                runOnUiThread {
                    connected = true
                    setConnected(true, snap.online, snap.total)
                }
            } catch (_: Exception) {
                runOnUiThread { setConnected(false, 0, 0) }
            }
        }
    }

    private fun findPhones() {
        val url = requireUrl() ?: return
        showMessage(getString(R.string.working_on_it))
        thread {
            try {
                FarmApi.postEmpty(url, "/api/devices/refresh")
                val phones = FarmApi.get(url, "/api/phones")
                val snap = FarmApi.parsePhones(phones)
                runOnUiThread {
                    setConnected(true, snap.online, snap.total)
                    showMessage(getString(R.string.phones_found, snap.total))
                }
            } catch (e: Exception) {
                runOnUiThread { showMessage(e.message ?: "Error") }
            }
        }
    }

    private fun runFarm() {
        val url = requireUrl() ?: return
        showMessage(getString(R.string.working_on_it))
        thread {
            try {
                val res = FarmApi.postEmpty(url, "/api/groups/run")
                val err = res.optString("error", "")
                if (err.isNotEmpty() && !res.optBoolean("ok", true)) {
                    runOnUiThread { showMessage(err) }
                    return@thread
                }
                runOnUiThread {
                    showMessage(getString(R.string.farm_running))
                    statusTitle.text = getString(R.string.farm_running)
                }
            } catch (e: Exception) {
                runOnUiThread { showMessage(e.message ?: "Could not start") }
            }
        }
    }

    private fun stopFarm() {
        val url = requireUrl() ?: return
        showMessage(getString(R.string.working_on_it))
        thread {
            try {
                FarmApi.postEmpty(url, "/api/groups/stop")
                FarmApi.postEmpty(url, "/api/stop_all")
                runOnUiThread {
                    showMessage(getString(R.string.all_stopped))
                    statusTitle.text = getString(R.string.all_stopped)
                }
            } catch (e: Exception) {
                runOnUiThread { showMessage(e.message ?: "Could not stop") }
            }
        }
    }

    private fun torOn() {
        val url = requireUrl() ?: return
        showMessage(getString(R.string.working_on_it))
        thread {
            try {
                FarmApi.postEmpty(url, "/api/proxy/setup")
                runOnUiThread { showMessage("Tor is ON") }
            } catch (e: Exception) {
                runOnUiThread { showMessage(e.message ?: "Tor failed") }
            }
        }
    }

    private fun newFaces() {
        val url = requireUrl() ?: return
        showMessage(getString(R.string.working_on_it))
        thread {
            try {
                FarmApi.postEmpty(url, "/api/identity/reset_all")
                runOnUiThread { showMessage("New faces ready") }
            } catch (e: Exception) {
                runOnUiThread { showMessage(e.message ?: "Reset failed") }
            }
        }
    }

    private fun setConnected(on: Boolean, online: Int, total: Int) {
        connected = on
        statusDot.setTextColor(
            if (on) getColor(R.color.status_on) else getColor(R.color.status_off)
        )
        statusTitle.text = if (on) getString(R.string.connected) else getString(R.string.not_connected)
        statusPhones.text = when {
            on && online > 0 -> getString(R.string.phones_working, online)
            on && total > 0 -> getString(R.string.phones_found, total)
            on -> getString(R.string.tap_connect_first)
            else -> getString(R.string.tap_connect_first)
        }
    }

    private fun showMessage(msg: String) {
        messageLine.text = msg
    }
}

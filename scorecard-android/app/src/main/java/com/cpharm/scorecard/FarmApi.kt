package com.cpharm.scorecard

import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

object FarmApi {

    fun normalizeBaseUrl(raw: String): String {
        var u = raw.trim().removeSuffix("/")
        if (u.isEmpty()) return ""
        if (!u.startsWith("http://") && !u.startsWith("https://")) {
            u = "http://$u"
        }
        return u
    }

    fun get(baseUrl: String, path: String): JSONObject {
        val text = httpRequest(baseUrl + path, "GET", null)
        return JSONObject(text)
    }

    fun post(baseUrl: String, path: String, body: JSONObject? = null): JSONObject {
        val text = httpRequest(baseUrl + path, "POST", body?.toString())
        return if (text.isBlank()) JSONObject() else JSONObject(text)
    }

    fun postEmpty(baseUrl: String, path: String): JSONObject = post(baseUrl, path, null)

    data class PhoneSnapshot(
        val online: Int,
        val total: Int,
        val runningNames: List<String>,
    )

    fun parsePhones(json: JSONObject): PhoneSnapshot {
        val arr = json.optJSONArray("phones") ?: JSONArray()
        var online = 0
        val names = mutableListOf<String>()
        for (i in 0 until arr.length()) {
            val p = arr.optJSONObject(i) ?: continue
            val running = p.optBoolean("running", false)
            val status = p.optString("status", "")
            val isOn = running || status == "device"
            if (isOn) {
                online++
                names.add(p.optString("name", p.optString("serial", "phone")))
            }
        }
        return PhoneSnapshot(online = online, total = arr.length(), runningNames = names)
    }

    private fun httpRequest(url: String, method: String, jsonBody: String?): String {
        val conn = (URL(url).openConnection() as HttpURLConnection).apply {
            connectTimeout = 10000
            readTimeout = 15000
            requestMethod = method
            if (jsonBody != null) {
                doOutput = true
                setRequestProperty("Content-Type", "application/json; charset=utf-8")
            }
        }
        if (jsonBody != null) {
            conn.outputStream.use { it.write(jsonBody.toByteArray(Charsets.UTF_8)) }
        }
        val stream = if (conn.responseCode >= 400) conn.errorStream else conn.inputStream
        val text = stream?.bufferedReader()?.use { it.readText() } ?: ""
        conn.disconnect()
        if (conn.responseCode >= 400) {
            throw IOException("HTTP ${conn.responseCode}: ${text.take(200)}")
        }
        return text
    }

    class IOException(message: String) : Exception(message)
}

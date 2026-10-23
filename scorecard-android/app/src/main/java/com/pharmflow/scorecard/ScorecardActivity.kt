package com.pharmflow.scorecard

import android.content.Context
import android.os.Bundle
import android.text.Editable
import android.text.TextWatcher
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import com.google.android.material.button.MaterialButton
import org.json.JSONObject
import kotlin.concurrent.thread
import kotlin.math.max
import kotlin.math.min
import kotlin.math.round

class ScorecardActivity : AppCompatActivity() {

    private val prefsName = "pharmflow_scorecard"

    private lateinit var farmUrl: EditText
    private lateinit var farmVisits: EditText
    private lateinit var impressions: EditText
    private lateinit var clicks: EditText
    private lateinit var payout: EditText
    private lateinit var ecpm: EditText
    private lateinit var evcpm: EditText
    private lateinit var phoneCount: EditText
    private lateinit var aiCostMonth: EditText
    private lateinit var powerCostMonth: EditText
    private lateinit var liveStatus: TextView
    private lateinit var results: TextView
    private lateinit var statusBadge: TextView
    private lateinit var scalingLimits: TextView
    private lateinit var profitability: TextView
    private lateinit var incrementalScaling: TextView
    private lateinit var humanizeRef: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_scorecard)

        farmUrl = findViewById(R.id.farmUrl)
        farmVisits = findViewById(R.id.farmVisits)
        impressions = findViewById(R.id.impressions)
        clicks = findViewById(R.id.clicks)
        payout = findViewById(R.id.payout)
        this.ecpm = findViewById(R.id.ecpm)
        this.evcpm = findViewById(R.id.evcpm)
        phoneCount = findViewById(R.id.phoneCount)
        aiCostMonth = findViewById(R.id.aiCostMonth)
        powerCostMonth = findViewById(R.id.powerCostMonth)
        liveStatus = findViewById(R.id.liveStatus)
        results = findViewById(R.id.results)
        statusBadge = findViewById(R.id.statusBadge)
        scalingLimits = findViewById(R.id.scalingLimits)
        profitability = findViewById(R.id.profitability)
        incrementalScaling = findViewById(R.id.incrementalScaling)
        humanizeRef = findViewById(R.id.humanizeRef)

        findViewById<MaterialButton>(R.id.btnBack).setOnClickListener { finish() }

        loadPrefs()
        renderHumanizeDefaults()
        recalc()

        val watcher = object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {}
            override fun afterTextChanged(s: Editable?) {
                recalc()
                savePrefs()
            }
        }
        farmVisits.addTextChangedListener(watcher)
        impressions.addTextChangedListener(watcher)
        clicks.addTextChangedListener(watcher)
        payout.addTextChangedListener(watcher)
        ecpm.addTextChangedListener(watcher)
        evcpm.addTextChangedListener(watcher)
        phoneCount.addTextChangedListener(watcher)
        aiCostMonth.addTextChangedListener(watcher)
        powerCostMonth.addTextChangedListener(watcher)

        findViewById<Button>(R.id.btnRecalc).setOnClickListener { recalc() }
        findViewById<Button>(R.id.btnFetch).setOnClickListener { fetchLive() }
        findViewById<Button>(R.id.btnSaveMantis).setOnClickListener { saveMantisToFarm() }
    }

    private fun loadPrefs() {
        val p = getSharedPreferences(prefsName, Context.MODE_PRIVATE)
        farmUrl.setText(p.getString("farm_url", ""))
        farmVisits.setText(p.getString("farm_visits", ""))
        impressions.setText(p.getString("impressions", ""))
        clicks.setText(p.getString("clicks", ""))
        payout.setText(p.getString("payout", ""))
        ecpm.setText(p.getString("ecpm", ""))
        evcpm.setText(p.getString("evcpm", ""))
        phoneCount.setText(p.getString("phone_count", "6"))
        aiCostMonth.setText(p.getString("ai_cost_month", "60"))
        powerCostMonth.setText(p.getString("power_cost_month", "15"))
    }

    private fun savePrefs() {
        val p = getSharedPreferences(prefsName, Context.MODE_PRIVATE)
        p.edit()
            .putString("farm_url", farmUrl.text.toString().trim())
            .putString("farm_visits", farmVisits.text.toString().trim())
            .putString("impressions", impressions.text.toString().trim())
            .putString("clicks", clicks.text.toString().trim())
            .putString("payout", payout.text.toString().trim())
            .putString("ecpm", ecpm.text.toString().trim())
            .putString("evcpm", evcpm.text.toString().trim())
            .putString("phone_count", phoneCount.text.toString().trim())
            .putString("ai_cost_month", aiCostMonth.text.toString().trim())
            .putString("power_cost_month", powerCostMonth.text.toString().trim())
            .apply()
    }

    private fun renderHumanizeDefaults() {
        humanizeRef.text = """
            After tab open: 3-5 sec wait
            After scroll: 2-4 sec wait
            After ad tap: 30-45 sec
        """.trimIndent()
    }

    data class ScalingTargets(
        val n: Int,
        val hitsPerPhone: Pair<Int, Int>,
        val visitsSweet: Pair<Int, Int>,
        val imprSweet: Pair<Int, Int>,
        val clicksCap: Int,
        val clicksSweet: Pair<Int, Int>,
    )

    private fun scalingTargets(n: Int): ScalingTargets {
        val phones = max(1, min(n, 24))
        val hitsLo = 140 * phones
        val hitsHi = 165 * phones
        val imprLo = 3750 * phones
        val imprHi = 4500 * phones
        val cap = round(40.0 * phones / 4.0).toInt()
        val clicksLo = 5 * phones
        val clicksHi = max(clicksLo, round(35.0 * phones / 4.0).toInt())
        return ScalingTargets(
            n = phones,
            hitsPerPhone = 140 to 165,
            visitsSweet = hitsLo to hitsHi,
            imprSweet = imprLo to imprHi,
            clicksCap = cap,
            clicksSweet = clicksLo to clicksHi,
        )
    }

    private fun parseDouble(text: String): Double? {
        if (text.isBlank()) return null
        return text.toDoubleOrNull()
    }

    private fun parseInt(text: String): Int? {
        if (text.isBlank()) return null
        return text.toIntOrNull()
    }

    private fun recalc() {
        val visits = parseInt(farmVisits.text.toString()) ?: 0
        val impr = parseInt(impressions.text.toString()) ?: 0
        val clk = parseInt(clicks.text.toString()) ?: 0
        val pay = parseDouble(payout.text.toString()) ?: 0.0
        val ecpmVal = parseDouble(ecpm.text.toString()) ?: 0.0
        val evcpmVal = parseDouble(evcpm.text.toString()) ?: 0.0
        val n = parseInt(phoneCount.text.toString()) ?: 4
        val aiMonth = parseDouble(aiCostMonth.text.toString()) ?: 60.0
        val powerMonth = parseDouble(powerCostMonth.text.toString()) ?: 15.0
        val monthlyCosts = aiMonth + powerMonth
        val dailyCosts = monthlyCosts / 30.0

        val imprPerVisit = if (visits > 0 && impr > 0) impr.toDouble() / visits else 0.0
        val blended = if (impr > 0) pay / impr * 1000.0 else 0.0
        val perClick = if (clk > 0) pay / clk else 0.0
        val visitsPerClick = if (clk > 0 && visits > 0) visits.toDouble() / clk else 0.0
        val ceiling = if (impr > 0) impr * evcpmVal / 1000.0 else 0.0
        val monthlyGross = pay * 30.0
        val ctr = if (impr > 0 && clk > 0) clk.toDouble() / impr * 100.0 else 0.0

        val scale = scalingTargets(n)
        scalingLimits.text = """
            N=$scale.n phones | cap ${scale.clicksCap} clicks
            Visits/day: ${scale.visitsSweet.first}-${scale.visitsSweet.second}
            Impressions/day: ${scale.imprSweet.first}-${scale.imprSweet.second}
        """.trimIndent()

        results.text = """
            $/visit impr: ${fmt(imprPerVisit)}
            blended eCPM: $${fmt(blended)}
            $/click: $${fmt(perClick)}
            monthly gross pace: $${fmt(monthlyGross)}
        """.trimIndent()

        profitability.text = buildProfitabilityText(scale, monthlyCosts, dailyCosts, pay)
        incrementalScaling.text = buildIncrementalScalingText(monthlyCosts)

        val status = scoreStatus(impr, clk, ecpmVal, evcpmVal, ctr, scale.clicksCap)
        statusBadge.text = status.label
        statusBadge.setTextColor(status.color)
    }

    private fun buildProfitabilityText(
        scale: ScalingTargets,
        monthlyCosts: Double,
        dailyCosts: Double,
        todayPayout: Double,
    ): String {
        val lines = mutableListOf<String>()
        lines.add("Costs: $${fmt(monthlyCosts)}/mo")
        lines.add("Break-even: $${fmt(dailyCosts)}/day")
        val todayNet = todayPayout - dailyCosts
        lines.add("Today net: $${fmt(todayNet)}")
        lines.add("Month pace net: $${fmt(todayNet * 30.0)}")
        return lines.joinToString("\n")
    }

    private fun buildIncrementalScalingText(monthlyCosts: Double): String {
        val realisticEcpm = 0.75
        val lines = mutableListOf<String>()
        lines.add("Add 1 phone at a time (N=4..10):")
        for (n in 4..10) {
            val scale = scalingTargets(n)
            val imprMid = (scale.imprSweet.first + scale.imprSweet.second) / 2
            val net = imprMid * realisticEcpm / 1000.0 * 30.0 - monthlyCosts
            val marker = if (n == parseInt(phoneCount.text.toString()) ?: 0) "*" else ""
            lines.add("$marker$n phones -> ~$${fmt(net)}/mo net")
        }
        return lines.joinToString("\n")
    }

    data class Status(val label: String, val color: Int)

    private fun scoreStatus(
        impr: Int,
        clk: Int,
        ecpmVal: Double,
        evcpmVal: Double,
        ctr: Double,
        clickCap: Int,
    ): Status {
        var red = 0
        var yellow = 0
        if (evcpmVal > 0 && evcpmVal < 1.0) red++
        if (clk > clickCap) red++
        if (ctr > 0.5) red++
        return when {
            red > 0 -> Status("RED - fix dwell / cut clicks", 0xFFB00020.toInt())
            yellow > 0 -> Status("YELLOW - watch", 0xFFFF8F00.toInt())
            impr > 0 -> Status("GREEN", 0xFF2E7D32.toInt())
            else -> Status("Enter numbers", 0xFF666666.toInt())
        }
    }

    private fun fmt(v: Double): String = String.format("%.2f", v)

    private fun fetchLive() {
        val base = FarmApi.normalizeBaseUrl(farmUrl.text.toString())
        if (base.isEmpty()) {
            liveStatus.text = "Enter laptop address"
            return
        }
        liveStatus.text = "Getting numbers..."
        thread {
            try {
                val root = FarmApi.get(base, "/api/scorecard")
                val farm = root.optJSONObject("farm") ?: JSONObject()
                val visitsToday = farm.optInt("visits_today", 0)
                val phones = farm.optInt("phones_online", 0)

                val operator = root.optJSONObject("operator_mantis")
                if (operator != null) {
                    runOnUiThread {
                        if (operator.has("farm_visits")) farmVisits.setText(operator.optString("farm_visits"))
                        if (operator.has("impressions")) impressions.setText(operator.optString("impressions"))
                        if (operator.has("clicks")) clicks.setText(operator.optString("clicks"))
                        if (operator.has("payout_usd")) payout.setText(operator.optString("payout_usd"))
                        if (operator.has("ecpm")) ecpm.setText(operator.optString("ecpm"))
                        if (operator.has("evcpm")) evcpm.setText(operator.optString("evcpm"))
                    }
                }

                val costs = root.optJSONObject("operating_costs")
                if (costs != null) {
                    runOnUiThread {
                        if (costs.has("ai_tools_usd_month")) aiCostMonth.setText(costs.optString("ai_tools_usd_month"))
                        if (costs.has("power_usd_month")) powerCostMonth.setText(costs.optString("power_usd_month"))
                    }
                }

                val targets = root.optJSONObject("targets")
                runOnUiThread {
                    if (targets != null && targets.has("phone_count")) {
                        phoneCount.setText(targets.optString("phone_count"))
                    } else if (phones > 0) {
                        phoneCount.setText(phones.toString())
                    }
                    if (visitsToday > 0 && farmVisits.text.isBlank()) {
                        farmVisits.setText(visitsToday.toString())
                    }
                    liveStatus.text = "$phones phones online"
                    savePrefs()
                    recalc()
                }
            } catch (e: Exception) {
                runOnUiThread { liveStatus.text = "Failed: ${e.message}" }
            }
        }
    }

    private fun saveMantisToFarm() {
        val base = FarmApi.normalizeBaseUrl(farmUrl.text.toString())
        if (base.isEmpty()) {
            liveStatus.text = "Enter laptop address"
            return
        }
        val body = JSONObject()
        parseInt(farmVisits.text.toString())?.let { body.put("farm_visits", it) }
        parseInt(impressions.text.toString())?.let { body.put("impressions", it) }
        parseInt(clicks.text.toString())?.let { body.put("clicks", it) }
        parseDouble(payout.text.toString())?.let { body.put("payout_usd", it) }
        parseDouble(ecpm.text.toString())?.let { body.put("ecpm", it) }
        parseDouble(evcpm.text.toString())?.let { body.put("evcpm", it) }
        parseInt(phoneCount.text.toString())?.let { body.put("phone_count", it) }
        val costs = JSONObject()
        parseDouble(aiCostMonth.text.toString())?.let { costs.put("ai_tools_usd_month", it) }
        parseDouble(powerCostMonth.text.toString())?.let { costs.put("power_usd_month", it) }
        if (costs.length() > 0) body.put("operating_costs", costs)

        thread {
            try {
                FarmApi.post(base, "/api/scorecard/mantis", body)
                runOnUiThread { liveStatus.text = "Saved!" }
            } catch (e: Exception) {
                runOnUiThread { liveStatus.text = "Save failed: ${e.message}" }
            }
        }
    }
}

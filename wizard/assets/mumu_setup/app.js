(function () {
  "use strict";

  const logEl = document.getElementById("log");
  const btnGo = document.getElementById("btn-go");
  const btnChrome = document.getElementById("btn-chrome");
  const btnPharmFlow = document.getElementById("btn-pharmflow");
  const btnRefresh = document.getElementById("btn-refresh");
  const checklistEl = document.getElementById("checklist");
  const statusLed = document.getElementById("status-led");
  const statusText = document.getElementById("status-text");
  const phonesEmpty = document.getElementById("phones-empty");
  const phoneChips = document.getElementById("phone-chips");
  const alertPharmFlow = document.getElementById("alert-pharmflow");
  const stepEls = Array.from(document.querySelectorAll(".step"));

  let busy = false;
  let pyApi = null;
  const GO_LABEL_DEFAULT = "GO — Set up my phones";
  const GO_LABEL_REBOOT = "GO — continue after phone reboot";

  function applyGoLabel(label) {
    const text = label || GO_LABEL_DEFAULT;
    if (!busy) {
      btnGo.textContent = text;
    }
    btnGo.dataset.labelDefault = text;
  }

  function api() {
    return pyApi || (window.pywebview && window.pywebview.api);
  }

  function waitForApi(maxMs) {
    return new Promise(function (resolve) {
      const start = Date.now();
      (function tick() {
        const a = window.pywebview && window.pywebview.api;
        if (a) {
          pyApi = a;
          resolve(a);
          return;
        }
        if (Date.now() - start > maxMs) {
          resolve(null);
          return;
        }
        setTimeout(tick, 40);
      })();
    });
  }

  function setBusy(on) {
    busy = on;
    btnGo.disabled = on;
    btnChrome.disabled = on;
    btnPharmFlow.disabled = on;
    btnRefresh.disabled = on;
    statusLed.classList.toggle("live", on);
    statusText.textContent = on ? "Working…" : "Ready";
    btnGo.innerHTML = on
      ? '<span class="spinner"></span>Working…'
      : (btnGo.dataset.labelDefault || GO_LABEL_DEFAULT);
  }

  function setStep(indexOrObj, state) {
    let index = indexOrObj;
    let st = state;
    if (typeof indexOrObj === "object" && indexOrObj !== null) {
      index = indexOrObj.index;
      st = indexOrObj.state;
    }
    stepEls.forEach(function (el, i) {
      el.classList.remove("active", "done", "error");
      if (st === "error" && i === index) {
        el.classList.add("error");
      } else if (i < index) {
        el.classList.add("done");
      } else if (i === index && st === "active") {
        el.classList.add("active");
      } else if (i === index && st === "done") {
        el.classList.add("done");
      }
    });
  }

  function classifyLine(text) {
    const t = text.trim();
    if (!t) return "";
    if (/IMPORTANT|Warning|fail|Could not/i.test(t)) return "log-line-warn";
    if (/Saved:|look good|installed|ready|Found \d/i.test(t)) return "log-line-ok";
    if (/Step|Hiding|Saving/i.test(t)) return "log-line-accent";
    return "";
  }

  function appendLog(text) {
    if (!text) return;
    String(text).split("\n").forEach(function (line) {
      const span = document.createElement("span");
      const cls = classifyLine(line);
      if (cls) span.className = cls;
      span.textContent = line + "\n";
      logEl.appendChild(span);
    });
    logEl.scrollTop = logEl.scrollHeight;
    if (/Found \d+ phone/i.test(text)) setStep(0, "done");
    if (/Hiding emulator|Installing browser|Chromium/i.test(text)) setStep(1, "active");
    if (/Saving tap/i.test(text)) {
      setStep(1, "done");
      setStep(2, "active");
    }
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function setPhones(serials) {
    phoneChips.innerHTML = "";
    if (!serials || !serials.length) {
      phonesEmpty.hidden = false;
      phoneChips.hidden = true;
      return;
    }
    phonesEmpty.hidden = true;
    phoneChips.hidden = false;
    serials.forEach(function (s, i) {
      const chip = document.createElement("span");
      chip.className = "chip";
      chip.style.animationDelay = i * 0.06 + "s";
      chip.innerHTML =
        '<span class="chip-dot"></span><span>' + escapeHtml(s) + "</span>";
      phoneChips.appendChild(chip);
    });
  }

  function statusIcon(status) {
    if (status === "pass") return "✓";
    if (status === "fail") return "!";
    if (status === "warn") return "?";
    return "•";
  }

  function actionLabel(action) {
    if (action === "download_mumu") return "Get MuMu";
    if (action === "download_pharmflow") return "Get PharmFlow";
    if (action === "install_adb") return "Fix";
    if (action === "refresh") return "Refresh";
    if (action === "fix_tablet") return "Fix Pad→Phone";
    if (action === "install_chromium") return "Install Chromium";
    if (action === "download_chromium") return "Download APK";
    if (action === "audit_fingerprint") return "Audit";
    if (action === "apply_fingerprint") return "Apply";
    return "Fix";
  }

  function renderChecklist(items) {
    checklistEl.innerHTML = "";
    (items || []).forEach(function (item) {
      const li = document.createElement("li");
      li.className = "check-item " + (item.status || "manual");

      const dot = document.createElement("div");
      dot.className = "check-dot";
      dot.textContent = statusIcon(item.status);
      li.appendChild(dot);

      const body = document.createElement("div");
      body.className = "check-body";
      const h = document.createElement("h3");
      h.textContent = item.title || "";
      body.appendChild(h);
      const p = document.createElement("p");
      p.textContent = item.help || "";
      body.appendChild(p);
      if (item.phones && item.phones.length) {
        const extra = document.createElement("p");
        extra.textContent = "Seen: " + item.phones.join(", ");
        extra.style.color = "#3ecf8e";
        extra.style.marginTop = "4px";
        body.appendChild(extra);
      }
      li.appendChild(body);

      if (item.action) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "btn-fix";
        btn.textContent = actionLabel(item.action);
        btn.addEventListener("click", function () {
          runAction(item.action);
        });
        li.appendChild(btn);
      }

      checklistEl.appendChild(li);
    });
  }

  async function refreshChecklist() {
    const a = api();
    if (!a) return;
    try {
      const state = await a.get_state();
      if (state && state.checklist) {
        renderChecklist(state.checklist);
      }
      const phonesItem = (state.checklist || []).find(function (x) {
        return x.id === "phones";
      });
      if (phonesItem && phonesItem.phones) {
        setPhones(phonesItem.phones);
      }
      // Unified PharmFlow.exe runs phone setup in-process, so the app is
      // always available — nothing to download or open externally.
      if (state && state.go_label) {
        applyGoLabel(state.go_label);
      }
      if (state && state.awaiting_cold_boot) {
        showPharmFlowAlert(
          "MuMu settings changed — STOP each phone, START again, then click GO."
        );
      }
    } catch (e) {
      appendLog("Refresh failed: " + e);
    }
  }

  async function runAction(action) {
    const a = api();
    if (!a || busy) return;
    try {
      const res = await a.run_action(action);
      if (res && res.log) appendLog(res.log);
      if (res && res.message) appendLog(res.message);
      if (res && res.checklist) renderChecklist(res.checklist);
      if (res && res.phones) setPhones(res.phones);
    } catch (e) {
      appendLog("Action failed: " + e);
    }
  }

  function onChromiumComplete(payload) {
    setBusy(false);
    const ok = payload && payload.ok;
    const msg = (payload && payload.message) || "";
    if (msg) appendLog("\n" + msg);
    statusText.textContent = ok ? "Chromium ready" : "Check log";
    if (ok) setStep(1, "done");
    refreshChecklist();
  }

  function onComplete(payload) {
    setBusy(false);
    const ready = payload && payload.ready === true;
    const msg = (payload && payload.message) || "";
    if (msg) appendLog("\n" + msg);
    if (payload && payload.go_label) {
      applyGoLabel(payload.go_label);
    }
    if (ready) {
      setStep(2, "done");
      statusText.textContent = "Setup finished";
      refreshChecklist();
    } else {
      setStep(1, "error");
      statusText.textContent = "Not done";
      showPharmFlowAlert(msg || "Setup did not finish. Read the log.");
      refreshChecklist();
    }
  }

  function showPharmFlowAlert(text) {
    if (!text) {
      alertPharmFlow.classList.remove("show");
      alertPharmFlow.textContent = "";
      return;
    }
    alertPharmFlow.textContent = text;
    alertPharmFlow.classList.add("show");
  }

  async function init() {
    pyApi = await waitForApi(8000);
    if (!pyApi) {
      appendLog("Could not connect to setup backend.");
      return;
    }

    await refreshChecklist();

    try {
      const state = await pyApi.get_state();
      if (state && state.startup_cleanup) {
        const sc = state.startup_cleanup;
        const n = (sc.killed || []).length;
        if (n > 0) {
          appendLog(
            (sc.first_time
              ? "First-time setup — closed " + n + " stale process(es) (MuMu/adb/PharmFlow).\n"
              : "Closed " + n + " stale PharmFlow/adb process(es).\n") +
              "Open MuMu Player and start phones before GO.\n"
          );
        } else if (sc.skipped && sc.skipped.indexOf("env") < 0 && sc.skipped.indexOf("platform") < 0) {
          appendLog("Startup cleanup: no stale processes found.\n");
        }
      }
    } catch (_e) {
      /* optional */
    }

    btnRefresh.addEventListener("click", refreshChecklist);

    btnGo.addEventListener("click", async function () {
      if (busy) return;
      logEl.textContent = "";
      setStep(0, "active");
      setBusy(true);
      showPharmFlowAlert("");
      try {
        const res = await pyApi.run_setup();
        if (res && res.error === "busy") setBusy(false);
      } catch (e) {
        appendLog("Setup error: " + e);
        setBusy(false);
      }
    });

    btnChrome.addEventListener("click", async function () {
      if (busy) return;
      setBusy(true);
      setStep(1, "active");
      appendLog("\n— Install Chromium on all phones —\n");
      try {
        const res = await pyApi.install_chromium();
        if (res && res.error === "busy") setBusy(false);
      } catch (e) {
        appendLog("Install Chromium error: " + e);
        setBusy(false);
      }
    });

    btnPharmFlow.addEventListener("click", async function () {
      if (busy) return;
      try {
        const res = await pyApi.launch_pharmflow_only();
        if (res && !res.ok) {
          appendLog("\n" + (res.message || "Could not open PharmFlow."));
          showPharmFlowAlert(res.message || "PharmFlow.exe missing.");
        } else if (res && res.ok) {
          appendLog("\n" + (res.message || "A second PharmFlow copy was not opened."));
        }
      } catch (e) {
        appendLog("Launch error: " + e);
      }
    });
  }

  window.PharmFlowSetup = {
    appendLog: appendLog,
    setPhones: setPhones,
    setStep: setStep,
    onComplete: onComplete,
    onChromiumComplete: onChromiumComplete,
    setBusy: setBusy,
    setChecklist: renderChecklist,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();

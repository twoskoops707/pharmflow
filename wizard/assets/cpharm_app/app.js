(function () {
  "use strict";

  const STEP_IDS = [
    "start",
    "install",
    "android",
    "phones",
    "boot",
    "map",
    "steps",
    "builder",
    "teams",
    "go",
  ];

  const views = Array.from(document.querySelectorAll(".view"));
  const stepNav = document.getElementById("step-nav");

  let pyApi = null;
  let wizardSteps = [];
  let currentView = "start";
  let stepComplete = {};
  let setupBusy = false;
  let installBusy = false;
  let setupAutoRefreshTimer = null;
  let setupStatusLockUntilMs = 0;

  const setupLog = document.getElementById("setup-log");
  const setupLed = document.getElementById("setup-led");
  const setupStatus = document.getElementById("setup-status");
  const setupHint = document.getElementById("setup-hint");
  const checklistEl = document.getElementById("checklist");
  const phonesEmpty = document.getElementById("phones-empty");
  const phoneChips = document.getElementById("phone-chips");
  const btnGo = document.getElementById("btn-go");

  const installLog = document.getElementById("install-log");
  const installLed = document.getElementById("install-led");
  const installStatus = document.getElementById("install-status");
  const prereqList = document.getElementById("prereq-list");

  const goLog = document.getElementById("go-log");
  const bootLog = document.getElementById("boot-log");
  const runLed = document.getElementById("run-led");
  const runStatus = document.getElementById("run-status");

  function api() {
    return pyApi || (window.pywebview && window.pywebview.api);
  }

  function waitForApi(maxMs) {
    return new Promise(function (resolve) {
      const start = Date.now();
      function ready(a) {
        if (a && typeof a.get_wizard_steps === "function") {
          pyApi = a;
          resolve(a);
          return true;
        }
        return false;
      }
      function tick() {
        const a = window.pywebview && window.pywebview.api;
        if (ready(a)) return;
        if (Date.now() - start > maxMs) {
          resolve(null);
          return;
        }
        setTimeout(tick, 40);
      }
      if (window.pywebview) {
        window.addEventListener(
          "pywebviewready",
          function () {
            const a = window.pywebview && window.pywebview.api;
            ready(a);
          },
          { once: true }
        );
      }
      tick();
    });
  }

  function showBackendError(msg) {
    const el = document.getElementById("backend-error");
    if (!el) return;
    el.textContent = msg;
    el.hidden = false;
    el.classList.add("visible");
  }

  function requireApi(action) {
    const a = api();
    if (!a) {
      const msg = "PharmFlow backend not connected — close and reopen PharmFlow.exe.";
      showBackendError(msg);
      showToast(msg);
      return null;
    }
    return a;
  }

  async function callApi(action, fn) {
    const a = requireApi(action);
    if (!a) return null;
    try {
      return await fn(a);
    } catch (e) {
      const detail = e && (e.message || String(e));
      const msg = action + " failed: " + detail;
      showBackendError(msg);
      showToast(msg);
      throw e;
    }
  }

  function showToast(msg) {
    const el = document.getElementById("app-toast");
    if (!el) return;
    el.textContent = msg;
    el.hidden = false;
    clearTimeout(showToast._t);
    showToast._t = setTimeout(function () {
      el.hidden = true;
    }, 4200);
  }

  function startSetupAutoRefresh() {
    if (setupAutoRefreshTimer) return;
    setupAutoRefreshTimer = setInterval(function () {
      if (currentView !== "phones" || setupBusy) return;
      refreshSetup();
    }, 5000);
  }

  function stopSetupAutoRefresh() {
    if (!setupAutoRefreshTimer) return;
    clearInterval(setupAutoRefreshTimer);
    setupAutoRefreshTimer = null;
  }

  function appendLog(el, text, cls) {
    if (!el || text == null) return;
    String(text).split("\n").forEach(function (line) {
      if (!line && line !== "") return;
      const span = document.createElement("span");
      if (cls) span.className = cls;
      span.textContent = line + "\n";
      el.appendChild(span);
    });
    el.scrollTop = el.scrollHeight;
  }

  function classifySetupLine(text) {
    const t = String(text).trim();
    if (!t) return "";
    if (/IMPORTANT|Warning|fail|Could not/i.test(t)) return "log-line-warn";
    if (/Saved:|look good|installed|ready|Found \d/i.test(t)) return "log-line-ok";
    if (/Step|Hiding|Saving/i.test(t)) return "log-line-accent";
    return "";
  }

  function setBusy(led, status, on, busyText) {
    if (led) led.classList.toggle("live", on);
    if (status) {
      if (on) {
        status.textContent = busyText || "Working…";
      } else if (status === setupStatus && !status.dataset.hold) {
        status.textContent = "Ready — complete the checklist, then set up phones";
      } else if (!status.dataset.hold) {
        status.textContent = "Ready";
      }
    }
  }

  function setSetupHint(text) {
    if (!setupHint) return;
    if (!text) {
      setupHint.hidden = true;
      setupHint.textContent = "";
      return;
    }
    setupHint.hidden = false;
    setupHint.textContent = text;
  }

  function setSetupStatus(text, lockMs) {
    if (!setupStatus) return;
    setupStatus.textContent = text;
    if (lockMs && lockMs > 0) {
      setupStatusLockUntilMs = Date.now() + lockMs;
    }
  }

  function setSetupPhase() {
    /* Legacy no-op — backend may still emit setStep; instructions are static in HTML. */
  }

  function renderStepNav() {
    if (!stepNav) return;
    stepNav.innerHTML = "";
    const steps = wizardSteps.length
      ? wizardSteps
      : STEP_IDS.map(function (id, i) {
          return { id: id, index: i, name: id, subtitle: "" };
        });

    let lastPhase = null;
    steps.forEach(function (step, i) {
      if (step.phase && step.phase !== lastPhase) {
        const phase = document.createElement("div");
        phase.className = "step-nav-phase";
        phase.textContent = step.phase;
        stepNav.appendChild(phase);
        lastPhase = step.phase;
      }

      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "step-nav-item";
      btn.dataset.view = step.id;
      if (stepComplete[step.id]) btn.classList.add("done");
      if (step.id === currentView) btn.classList.add("active");

      const num = document.createElement("span");
      num.className = "step-num";
      num.textContent = String(i + 1);
      btn.appendChild(num);

      const body = document.createElement("span");
      const title = document.createElement("span");
      title.className = "step-title";
      title.textContent = step.name || step.id;
      body.appendChild(title);
      if (step.subtitle) {
        const desc = document.createElement("span");
        desc.className = "step-desc";
        desc.textContent = step.subtitle;
        body.appendChild(desc);
      }
      btn.appendChild(body);

      btn.addEventListener("click", function () {
        showView(step.id, { animate: true });
      });
      stepNav.appendChild(btn);
    });
  }

  function updateNavActive() {
    if (!stepNav) return;
    stepNav.querySelectorAll(".step-nav-item").forEach(function (btn) {
      const id = btn.dataset.view;
      btn.classList.toggle("active", id === currentView);
      btn.classList.toggle("done", !!stepComplete[id]);
    });
  }

  const VIEW_ENTER = {
    install: refreshPrereqs,
    android: refreshAndroid,
    phones: refreshSetup,
    boot: refreshBoot,
    map: refreshMap,
    steps: refreshSteps,
    teams: refreshTeams,
    go: refreshGo,
  };

  function nextStepId(fromId) {
    const idx = STEP_IDS.indexOf(fromId);
    if (idx < 0 || idx >= STEP_IDS.length - 1) return null;
    return STEP_IDS[idx + 1];
  }

  function showView(name, opts) {
    opts = opts || {};
    if (STEP_IDS.indexOf(name) < 0) name = "start";
    currentView = name;
    if (name === "phones") startSetupAutoRefresh();
    else stopSetupAutoRefresh();

    views.forEach(function (v) {
      const on = v.dataset.view === name;
      v.classList.toggle("active", on);
      if (on && opts.animate) {
        v.classList.remove("flow-in");
        void v.offsetWidth;
        v.classList.add("flow-in");
      }
    });

    updateNavActive();

    const enter = VIEW_ENTER[name];
    if (enter) enter();

    const a = api();
    if (a && a.navigate_wizard_page) {
      const idx = STEP_IDS.indexOf(name);
      if (idx >= 0) {
        Promise.resolve(a.navigate_wizard_page(idx)).catch(function () {
          /* hidden tk sync is best-effort */
        });
      }
    }
  }

  function actionLabel(action) {
    const map = {
      download_mumu: "Get MuMu",
      download_cpharm: "Get PharmFlow",
      install_adb: "Fix",
      refresh: "Refresh",
      fix_tablet: "Fix Pad→Phone",
      install_chromium: "Install Chromium",
      download_chromium: "Download APK",
      audit_fingerprint: "Audit",
      apply_fingerprint: "Apply",
    };
    return map[action] || "Fix";
  }

  function renderChecklist(items) {
    if (!checklistEl) return;
    checklistEl.innerHTML = "";
    (items || []).forEach(function (item) {
      const li = document.createElement("li");
      li.className = "check-item " + (item.status || "manual");
      const dot = document.createElement("div");
      dot.className = "check-dot";
      dot.textContent =
        item.status === "pass" ? "✓" : item.status === "fail" ? "!" : item.status === "warn" ? "?" : "•";
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
        extra.style.color = "#3ecfb0";
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
          runSetupAction(item.action);
        });
        li.appendChild(btn);
      }
      checklistEl.appendChild(li);
    });
  }

  function setPhones(serials) {
    if (!phoneChips || !phonesEmpty) return;
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
      chip.innerHTML = '<span class="chip-dot"></span><span>' + String(s) + "</span>";
      phoneChips.appendChild(chip);
    });
  }

  function applyGoLabel(label) {
    if (!btnGo) return;
      const text = label || "Set up my phones";
    if (!setupBusy) btnGo.textContent = text;
    btnGo.dataset.labelDefault = text;
  }

  async function refreshSetup() {
    ensureAdvanced("phones");
    try {
      const state = await callApi("Refresh checks", function (a) {
        return a.get_setup_state();
      });
      if (!state) return;
      if (state && state.checklist) renderChecklist(state.checklist);
      const phonesItem = (state.checklist || []).find(function (x) {
        return x.id === "phones";
      });
      if (phonesItem && phonesItem.phones) setPhones(phonesItem.phones);
      if (state && state.go_label) applyGoLabel(state.go_label);
      if (state && state.awaiting_cold_boot) {
        setSetupHint(
          "Restart needed: stop the phones, start them again, then click Set up my phones."
        );
        if (setupStatus) {
          setupStatus.textContent = "Restart phones, then set up again";
          setupStatus.dataset.hold = "1";
        }
      } else {
        setSetupHint("");
        if (setupStatus) {
          delete setupStatus.dataset.hold;
          if (!setupBusy && Date.now() >= setupStatusLockUntilMs) {
            setupStatus.textContent = "Ready — click Set up my phones";
          }
        }
      }
      if (state && (state.ready || state.setup_already_done)) stepComplete.phones = true;
      updateNavActive();
    } catch (e) {
      appendLog(setupLog, "Check failed: " + e);
    }
  }

  async function refreshJourney() {
    const a = api();
    if (!a || !a.get_journey_state) return;
    try {
      const j = await a.get_journey_state();
      if (j && j.steps) {
        j.steps.forEach(function (s) {
          if (!s.id || !s.complete) return;
          if (["start", "install", "android", "phones"].indexOf(s.id) >= 0) {
            stepComplete[s.id] = true;
          }
        });
        updateNavActive();
      }
      if (j && j.recommended_view && currentView === "start") {
        /* keep start unless URL specified */
      }
    } catch (_e) {
      /* optional */
    }
  }

  async function runSetupAction(action) {
    const a = api();
    if (!a || setupBusy) return;
    try {
      const res = await a.run_setup_action(action);
      if (res && res.log) appendLog(setupLog, res.log, classifySetupLine(res.log));
      if (res && res.message) appendLog(setupLog, res.message);
      if (res && res.checklist) renderChecklist(res.checklist);
      if (res && res.phones) setPhones(res.phones);
    } catch (e) {
      appendLog(setupLog, "Action failed: " + e);
    }
  }

  /* ── Machine + emulator inventory (Android step, ARM64-aware) ── */
  async function refreshMachineCaps() {
    const el = document.getElementById("machine-caps");
    if (!el) return;
    const a = api();
    if (!a || typeof a.get_machine_capabilities !== "function") {
      el.innerHTML =
        '<p class="panel-note">Inventory needs the PharmFlow backend — close and reopen PharmFlow.exe.</p>';
      return;
    }
    try {
      const m = await a.get_machine_capabilities();
      if (el) el.innerHTML = machineCapsHtml(m);
    } catch (_e) {
      el.innerHTML = '<p class="panel-note">Inventory scan failed — click Check again.</p>';
    }
  }

  function machineCapsHtml(m) {
    if (!m || m.ok === false) {
      return '<p class="panel-note">Scan failed — click Check again.</p>';
    }
    const arch = escHtml(m.arch_label || "—");
    const archNote =
      m.arch === "arm64"
        ? "native build — redroid runs arm64-v8a; MuMu / Studio AVDs are adopted as-is"
        : "standard x64 build";
    const rd = m.redroid || { up: 0, total: 0 };
    const mumu = m.mumu || { instances: 0, online: 0 };
    const avd = Number(m.avd_online) || 0;
    const usb = Number(m.usb_online) || 0;
    const tcp = Number(m.tcp_online) || 0;
    const phones = m.phones || [];
    let html = "";
    html +=
      '<div class="mc-line"><span class="mc-k">CPU</span><span><span class="mc-dot ok"></span><strong>' +
      arch +
      "</strong> · " +
      archNote +
      "</span></div>";
    html +=
      '<div class="mc-line"><span class="mc-k">Docker</span><span><span class="mc-dot ' +
      (m.docker ? "ok" : "bad") +
      '"></span>' +
      (m.docker
        ? "engine up · <strong>" + rd.up + "/" + rd.total + "</strong> redroid containers up (arm64-v8a)"
        : "engine down — start Docker Desktop for redroid phones") +
      "</span></div>";
    html +=
      '<div class="mc-line"><span class="mc-k">MuMu</span><span><span class="mc-dot ' +
      (mumu.instances ? "ok" : "off") +
      '"></span>' +
      (mumu.instances
        ? mumu.instances + " instance(s), <strong>" + mumu.online + "</strong> online"
        : "none found on this machine") +
      "</span></div>";
    html +=
      '<div class="mc-line"><span class="mc-k">Studio AVD</span><span><span class="mc-dot ' +
      (avd ? "ok" : "off") +
      '"></span>' +
      (avd ? avd + " online" : "none online") +
      "</span></div>";
    html +=
      '<div class="mc-line"><span class="mc-k">Real USB</span><span><span class="mc-dot ' +
      (usb ? "ok" : "off") +
      '"></span>' +
      (usb ? usb + " online" : "none") +
      "</span></div>";
    if (tcp > 0) {
      html +=
        '<div class="mc-line"><span class="mc-k">Other ADB</span><span><span class="mc-dot ok"></span>' +
        tcp +
        " online over ADB TCP</span></div>";
    }
    html +=
      '<div class="mc-line"><span class="mc-k">On ADB</span><span><span class="mc-dot ' +
      (phones.length ? "ok" : "off") +
      '"></span><strong>' +
      phones.length +
      "</strong> phone(s) the farm can adopt" +
      (phones.length ? " — start one below, or go to the Test step to spin up a spare" : " — start an emulator or plug a phone") +
      "</span></div>";
    if (phones.length) {
      html +=
        '<div class="mc-line" style="align-items:flex-start"><span class="mc-k">Live</span><span class="mc-phones">' +
        phones
          .map(function (p) {
            return (
              '<span class="chip"><span class="mc-dot ' +
              (p.online ? "ok" : "off") +
              '"></span>' +
              escHtml(p.kind || "phone") +
              " · " +
              escHtml(p.serial) +
              "</span>"
            );
          })
          .join("") +
        "</span></div>";
    }
    return html;
  }

  async function refreshPrereqs() {
    try {
      const rows = await callApi("Refresh", function (a) {
        if (typeof a.get_prereq_status !== "function") {
          throw new Error("PharmFlow is still starting. Wait a moment and try again.");
        }
        return a.get_prereq_status();
      });
      if (!rows) return;
      prereqList.innerHTML = "";
      const allOk = rows && rows.length && rows.every(function (r) {
        return r.ok;
      });
      if (allOk) stepComplete.install = true;
      (rows || []).forEach(function (r) {
        const li = document.createElement("li");
        li.className = "prereq-item " + (r.ok ? "ok" : "pending");
        li.innerHTML =
          '<span class="check-dot">' +
          (r.ok ? "✓" : "…") +
          '</span><span class="check-body"><h3>' +
          r.label +
          '</h3></span><span class="prereq-status">' +
          (r.ok ? "Ready" : "Not yet") +
          "</span>";
        prereqList.appendChild(li);
      });
      updateNavActive();
    } catch (e) {
      appendLog(installLog, "Check failed: " + e);
    }
  }

  async function refreshAndroid() {
    const a = api();
    if (!a) return;
    const statusEl = document.getElementById("android-status");
    const detailEl = document.getElementById("android-detail");
    const labelEl = document.getElementById("android-status-label");
    const ledEl = document.getElementById("android-led");
    try {
      const st = await a.get_android_status();
      const ready = Boolean(st.ready);
      const statusText = st.status || (ready ? "Android tools ready" : "SDK not found");
      if (statusEl) statusEl.textContent = statusText;
      if (labelEl) labelEl.textContent = statusText;
      if (detailEl) detailEl.textContent = st.detail || st.sdk_path || "";
      if (ledEl) ledEl.classList.toggle("on", ready);
      if (ready) stepComplete.android = true;
      updateNavActive();
      refreshMachineCaps();
    } catch (e) {
      if (statusEl) statusEl.textContent = "Could not read status: " + e;
      if (labelEl) labelEl.textContent = "Status unavailable";
    }
  }

  function renderGroupsList(detail) {
    const list = document.getElementById("groups-list");
    if (!list) return;
    list.innerHTML = "";
    const groups = (detail && detail.groups) || [];
    if (!groups.length) {
      const li = document.createElement("li");
      li.className = "groups-list-empty";
      li.textContent = "No groups yet. Click Manage groups.";
      list.appendChild(li);
      return;
    }
    groups.forEach(function (g) {
      const li = document.createElement("li");
      const connected = g.phone_count || 0;
      const configured = g.configured_count || connected;
      let extra = "";
      if (configured > connected) {
        extra = " (" + configured + " saved in config, " + connected + " connected now)";
      }
      li.innerHTML =
        "<strong>" +
        (g.name || "Group") +
        "</strong> — " +
        connected +
        " phone" +
        (connected === 1 ? "" : "s") +
        extra;
      list.appendChild(li);
    });
  }

  function groupsSummaryText(detail) {
    if (!detail || !detail.group_count) {
      return "No groups yet.";
    }
    const connected = detail.connected_phones || 0;
    const assigned = detail.phone_count || 0;
    let text =
      detail.group_count +
      " group" +
      (detail.group_count === 1 ? "" : "s") +
      ", " +
      assigned +
      " phone" +
      (assigned === 1 ? "" : "s") +
      " in groups";
    if (connected > 0 && connected !== assigned) {
      text += " (" + connected + " connected now)";
    } else if (connected > 0) {
      text += " (" + connected + " connected)";
    }
    return text;
  }

  async function pollDashboardReady(maxMs) {
    const start = Date.now();
    while (Date.now() - start < maxMs) {
      const a = api();
      if (a && a.is_dashboard_ready) {
        try {
          const st = await a.is_dashboard_ready();
          if (st && st.ready) return true;
        } catch (_e) {
          /* retry */
        }
      }
      await new Promise(function (r) {
        setTimeout(r, 2000);
      });
    }
    return false;
  }

  async function openDashboardWhenReady() {
    const ready = await pollDashboardReady(90000);
    const a = requireApi("Dashboard");
    if (!a) return;
    if (ready) {
      await a.open_dashboard();
      showToast("Dashboard opened in your browser");
    } else {
      showToast("Service still starting. Click Open dashboard in a moment.");
    }
  }

  async function refreshBoot() {
    ensureAdvanced("boot");
    const a = api();
    if (!a || !a.get_site_settings) return;
    const input = document.getElementById("site-url-input");
    const hint = document.getElementById("site-url-hint");
    const testBtn = document.getElementById("btn-test-url");
    try {
      const s = await a.get_site_settings();
      if (input && s.url) input.value = s.url;
      if (hint) {
        hint.textContent = s.host
          ? "Current site: " + s.host + ". Used for Test and default sequences."
          : "Enter your site URL above, then click Save.";
      }
      if (testBtn) {
        testBtn.textContent = s.host ? "Open " + s.host + " on phones" : "Open site on phones";
      }
    } catch (_e) {
      /* optional */
    }
  }

  async function refreshMap() {
    ensureAdvanced("map");
    wireMapStep();
    const a = api();
    if (!a || !a.get_site_settings) return;
    const input = document.getElementById("map-url-input");
    try {
      const s = await a.get_site_settings();
      if (input && s.url && !input.value.trim()) input.value = s.url;
    } catch (_e) {
      /* optional */
    }
  }

  function escHtml(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function renderMapResults(mapData) {
    const el = document.getElementById("map-results");
    if (!el) return;
    if (!mapData || !mapData.pages || !mapData.pages.length) {
      el.innerHTML = "";
      return;
    }
    let html =
      '<div class="map-summary">' +
      "<span><strong>" + mapData.pages_scanned + "</strong> pages</span>" +
      "<span><strong>" + mapData.total_internal_links + "</strong> internal links</span>" +
      "<span><strong>" + mapData.total_forms + "</strong> " + (mapData.total_forms === 1 ? "form" : "forms") + "</span>" +
      "<span class=\"map-slow\">scanned in " + (mapData.duration_ms / 1000).toFixed(1) + "s</span>" +
      "</div>";
    html += '<div class="map-page-grid">';
    (mapData.pages || []).forEach(function (pg) {
      const forms = (pg.forms || [])
        .map(function (f) {
          const inputs = (f.inputs || [])
            .map(function (i) {
              return "<code>" + escHtml(i.name || i.type || "input") + "</code>";
            })
            .join(" ");
          return (
            "<li><strong>" + escHtml(f.method) + "</strong> " + escHtml(f.action) +
            (inputs ? '<div class="map-inputs">' + inputs + "</div>" : "") +
            "</li>"
          );
        })
        .join("");
      const buttons = (pg.buttons || [])
        .slice(0, 8)
        .map(function (b) {
          return "<code>" + escHtml(b) + "</code>";
        })
        .join(" ");
      const links = (pg.links || [])
        .slice(0, 8)
        .map(function (l) {
          return (
            '<li><a href="' + escHtml(l.url) + '" target="_blank" rel="noopener">' +
            escHtml(l.text || l.url) +
            "</a></li>"
          );
        })
        .join("");
      html +=
        '<div class="map-page">' +
        '<h3 class="map-page-title">' + escHtml(pg.title || pg.url) + "</h3>" +
        '<p class="map-page-url">' + escHtml(pg.url) + "</p>" +
        (pg.headings && pg.headings.length
          ? '<div class="map-block"><span class="map-block-label">Headings</span><ul class="map-chips">' +
            pg.headings
              .slice(0, 6)
              .map(function (h) {
                return "<li><code>" + escHtml(h.level) + "</code> " + escHtml(h.text) + "</li>";
              })
              .join("") +
            "</ul></div>"
          : "") +
        (forms
          ? '<div class="map-block"><span class="map-block-label">Forms</span><ul>' + forms + "</ul></div>"
          : "") +
        (buttons
          ? '<div class="map-block"><span class="map-block-label">Buttons</span><div class="map-chips">' + buttons + "</div></div>"
          : "") +
        (links
          ? '<div class="map-block"><span class="map-block-label">Internal links</span><ul class="map-links">' + links + "</ul></div>"
          : "") +
        "</div>";
    });
    html += "</div>";
    el.innerHTML = html;
  }

  function wireMapStep() {
    if (document.getElementById("btn-map-scan") && document.getElementById("btn-map-scan").dataset.wired) return;
    const mapLog = document.getElementById("map-log");
    const mapStatus = document.getElementById("map-status");
    const mapLed = document.getElementById("map-led");
    const mapStatusLabel = document.getElementById("map-status-label");
    const urlInput = document.getElementById("map-url-input");

    function status(text, led) {
      if (mapStatus) mapStatus.textContent = text;
      if (mapLed) mapLed.className = "status-led " + (led || "");
      if (mapStatusLabel) mapStatusLabel.textContent = text;
    }
    function logLine(text) {
      if (mapLog) appendLog(mapLog, text);
    }

    const btnScan = document.getElementById("btn-map-scan");
    if (btnScan && !btnScan.dataset.wired) {
      btnScan.dataset.wired = "1";
      btnScan.addEventListener("click", async function () {
        const url = urlInput && urlInput.value ? urlInput.value.trim() : "";
        if (!url) {
          showToast("Enter a site URL first");
          return;
        }
        try {
          status("Scanning " + url + "…", "busy");
          logLine("Scanning " + url + " (read-only, up to 20 pages)…");
          const res = await callApi("Scan site", function (a) {
            return a.scan_site(url);
          });
          if (!res || !res.ok) {
            status(res && res.error ? res.error : "Scan failed", "bad");
            logLine(res && res.error ? res.error : "Scan failed");
            return;
          }
          renderMapResults(res);
          status(res.pages_scanned + " page(s) mapped, " + res.total_forms + (res.total_forms === 1 ? " form" : " forms") + " found", "ok");
          logLine("Mapped " + res.pages_scanned + " page(s) on " + res.host + " in " + (res.duration_ms / 1000).toFixed(1) + "s");
          if (res.errors && res.errors.length) {
            logLine(res.errors.length + " page(s) unreachable — " + res.errors[0].url + " (" + res.errors[0].error + ")");
          }
          const gen = document.getElementById("btn-map-generate");
          if (gen) gen.disabled = false;
        } catch (_e) {
          status("Scan failed", "bad");
        }
      });
    }

    const btnGen = document.getElementById("btn-map-generate");
    if (btnGen && !btnGen.dataset.wired) {
      btnGen.dataset.wired = "1";
      btnGen.disabled = true;
      btnGen.addEventListener("click", async function () {
        const url = urlInput && urlInput.value ? urlInput.value.trim() : "";
        if (!url) {
          showToast("Enter a site URL first");
          return;
        }
        try {
          status("Generating starter sequence…", "busy");
          const res = await callApi("Generate sequence", function (a) {
            return a.apply_site_sequence(url);
          });
          if (!res || !res.ok) {
            status(res && res.error ? res.error : "Generate failed", "bad");
            logLine(res && res.error ? res.error : "Generate failed");
            return;
          }
          status("Saved starter sequence (" + res.steps + " steps) — refine it in Steps/Builder", "ok");
          logLine("Saved " + res.steps + "-step starter sequence to " + res.path);
          logLine(res.note || "");
          showToast("Starter sequence is now your default — refine in Steps");
        } catch (_e) {
          status("Generate failed", "bad");
        }
      });
    }
  }

  async function refreshSteps() {
    ensureAdvanced("steps");
    const a = api();
    if (!a) return;
    const el = document.getElementById("steps-summary");
    try {
      const info = await a.get_automation_info();
      if (el) {
        el.textContent = info.has_steps
          ? info.count + " step(s) in default sequence."
          : "No default steps yet.";
      }
      if (info.has_steps) stepComplete.steps = true;
      updateNavActive();
    } catch (e) {
      if (el) el.textContent = "Could not load: " + e;
    }
  }

  async function refreshTeams() {
    ensureAdvanced("teams");
    const a = api();
    if (!a) return;
    const el = document.getElementById("teams-summary");
    try {
      const s = await (a.get_groups_detail ? a.get_groups_detail() : a.get_groups_summary());
      if (el) el.textContent = groupsSummaryText(s);
      renderGroupsList(s);
      if (s.group_count > 0) stepComplete.teams = true;
      updateNavActive();
    } catch (e) {
      if (el) el.textContent = "Could not load: " + e;
    }
  }

  async function refreshGo() {
    ensureAdvanced("go");
    const a = api();
    if (!a) return;
    const el = document.getElementById("launch-summary");
    try {
      await a.save_browse_mode("scramble");
      const s = await a.get_launch_summary();
      if (el) el.textContent = s.summary || "Start the service, then run all groups.";
    } catch (e) {
      if (el) el.textContent = "Ready to launch.";
    }
  }

  /* ── Farm settings — Advanced panels (per step) ──────── */
  let advPayload = null;

  async function advLoad(force) {
    if (advPayload && !force) return advPayload;
    const a = api();
    if (!a || typeof a.get_farm_settings !== "function") return null;
    try {
      advPayload = await a.get_farm_settings();
    } catch (_e) {
      advPayload = null;
    }
    return advPayload;
  }

  function advEntry(step, key) {
    const p = advPayload;
    if (!p || !p.catalog) return null;
    return (p.catalog || []).find(function (e) {
      return e.step === step && e.key === key;
    });
  }

  function advControlFor(entry, value) {
    const kind = entry.kind || "text";
    const val = String(value == null ? "" : value);
    const isOn = ["1", "true", "yes", "on"].indexOf(val.toLowerCase()) >= 0;
    if (kind === "toggle") {
      const lab = document.createElement("label");
      lab.className = "adv-toggle";
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.dataset.key = entry.key;
      cb.checked = isOn;
      lab.appendChild(cb);
      const sw = document.createElement("span");
      sw.className = "adv-toggle-ui";
      lab.appendChild(sw);
      const tx = document.createElement("span");
      tx.className = "adv-toggle-text";
      tx.textContent = isOn ? "On" : "Off";
      lab.appendChild(tx);
      cb.addEventListener("change", function () {
        tx.textContent = cb.checked ? "On" : "Off";
      });
      return lab;
    }
    if (kind === "select") {
      const sel = document.createElement("select");
      sel.className = "adv-select";
      sel.dataset.key = entry.key;
      (entry.options || []).forEach(function (opt) {
        const o = document.createElement("option");
        o.value = opt;
        o.textContent = opt;
        if (opt === val) o.selected = true;
        sel.appendChild(o);
      });
      if (!val) sel.value = (entry.options || [])[0] || "";
      return sel;
    }
    const input = document.createElement("input");
    input.dataset.key = entry.key;
    if (kind === "int" || kind === "float") {
      input.type = "number";
      input.step = kind === "float" ? "any" : "1";
      input.min = "0";
      input.value = val;
    } else {
      input.type = "text";
      input.value = val;
      input.placeholder = entry.kind === "csv" ? "e.g. 148,102,97,52" : "";
    }
    input.className = "adv-input";
    return input;
  }

  async function ensureAdvanced(step) {
    const host = document.querySelector("#view-" + step + " .view-body");
    if (!host) return;
    const title = ((advPayload && advPayload.step_titles) || {})[step] || step;
    let box = document.getElementById("adv-farm-" + step);
    if (!box) {
      const a = api();
      if (!a || typeof a.get_farm_settings !== "function") return;
      box = document.createElement("div");
      box.className = "adv-farm";
      box.id = "adv-farm-" + step;
      box.innerHTML =
        '<details class="adv-details">' +
        "<summary>Advanced · " +
        escHtml(title) +
        " controls</summary>" +
        '<p class="adv-note">Power settings for this step. Changes are saved and applied at the next farm start.</p>' +
        '<div class="adv-grid" id="adv-grid-' +
        step +
        '"></div>' +
        '<div class="adv-actions-row">' +
        '<button type="button" class="btn-mini" data-act="save">Save settings</button>' +
        '<button type="button" class="btn-ghost" data-act="reset">Reset to farm defaults</button>' +
        '<span class="adv-status" id="adv-status-' +
        step +
        '"></span>' +
        "</div>" +
        "</details>";
      host.appendChild(box);
      box.querySelector("button[data-act=save]").addEventListener("click", function () {
        advSave(step, title);
      });
      box.querySelector("button[data-act=reset]").addEventListener("click", function () {
        advReset(step, title);
      });
    }
    const payload = await advLoad();
    if (!payload || !payload.ok) return;
    const sum = box.querySelector("summary");
    if (sum && payload.step_titles && payload.step_titles[step]) {
      const want = "Advanced · " + payload.step_titles[step] + " controls";
      if (sum.textContent !== want) sum.textContent = want;
    }
    const grid = document.getElementById("adv-grid-" + step);
    if (!grid) return;
    if (grid.dataset.rendered === step) {
      advFill(step, payload);
      return;
    }
    grid.innerHTML = "";
    (payload.catalog || [])
      .filter(function (e) {
        return e.step === step;
      })
      .forEach(function (entry) {
        const cell = document.createElement("label");
        cell.className = "adv-cell";
        const head = document.createElement("span");
        head.className = "adv-cell-head";
        const t = document.createElement("span");
        t.className = "adv-label";
        t.textContent = entry.label || entry.key;
        head.appendChild(t);
        const chip = document.createElement("span");
        chip.className = "adv-chip";
        chip.textContent = "custom";
        chip.hidden = true;
        chip.dataset.chip = entry.key;
        head.appendChild(chip);
        cell.appendChild(head);
        const val = ((payload.values || {})[entry.key] || {}).value;
        const src = ((payload.values || {})[entry.key] || {}).source;
        cell.appendChild(advControlFor(entry, val));
        const hint = document.createElement("span");
        hint.className = "adv-hint";
        hint.textContent = entry.hint || "";
        cell.appendChild(hint);
        chip.hidden = src !== "saved";
        grid.appendChild(cell);
      });
    grid.dataset.rendered = step;
    advFill(step, payload);
  }

  function advFill(step, payload) {
    const grid = document.getElementById("adv-grid-" + step);
    if (!grid || !payload) return;
    grid.querySelectorAll("[data-key]").forEach(function (ctl) {
      const val = ((payload.values || {})[ctl.dataset.key] || {}).value;
      if (val === undefined || val === null) return;
      if (ctl.type === "checkbox") {
        ctl.checked = ["1", "true", "yes", "on"].indexOf(String(val).toLowerCase()) >= 0;
      } else if (ctl.tagName === "SELECT") {
        if (ctl.options.length) ctl.value = String(val);
      } else {
        ctl.value = String(val);
      }
    });
    grid.querySelectorAll("[data-chip]").forEach(function (chip) {
      const src = ((payload.values || {})[chip.dataset.chip] || {}).source;
      chip.hidden = src !== "saved";
    });
  }

  function advStatus(step, text, kind) {
    const el = document.getElementById("adv-status-" + step);
    if (el) {
      el.textContent = text || "";
      el.className = "adv-status" + (kind === "err" ? " err" : kind === "ok" ? " ok" : "");
    }
  }

  async function advSave(step, title) {
    const grid = document.getElementById("adv-grid-" + step);
    const a = api();
    if (!grid || !a || typeof a.save_farm_settings !== "function") return;
    const updates = {};
    grid.querySelectorAll("[data-key]").forEach(function (ctl) {
      updates[ctl.dataset.key] =
        ctl.type === "checkbox" ? (ctl.checked ? "1" : "0") : ctl.value;
    });
    advStatus(step, "Saving…");
    try {
      const res = await a.save_farm_settings(updates);
      if (!res || !res.ok) {
        const errs = (res && res.errors) || ["save failed"];
        advStatus(step, errs.join(" · "), "err");
        return;
      }
      await advLoad(true);
      advFill(step, advPayload);
      advStatus(step, "✓ Saved — applies at the next farm start", "ok");
    } catch (e) {
      advStatus(step, "Save error: " + e, "err");
    }
  }

  async function advReset(step, title) {
    const a = api();
    if (!a || typeof a.reset_farm_settings !== "function") return;
    advStatus(step, "Resetting…");
    try {
      const res = await a.reset_farm_settings(step);
      if (!res || !res.ok) {
        advStatus(step, "Reset failed", "err");
        return;
      }
      await advLoad(true);
      advFill(step, advPayload);
      advStatus(step, "✓ Back to farm defaults", "ok");
    } catch (e) {
      advStatus(step, "Reset error: " + e, "err");
    }
  }

  /* ── HUD telemetry strip ─────────────────────────────── */
  function setHudText(id, text) {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
  }

  function fmtMoney(v) {
    const n = Number(v || 0);
    return "$" + n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  async function refreshHud() {
    const a = api();
    const lamp = document.getElementById("hud-farm-lamp");
    try {
      if (!a || typeof a.get_farm_hud !== "function") {
        setHudText("hud-farm", "—");
        setHudText("hud-phones", "—");
        setHudText("hud-today", "—");
        setHudText("hud-clicks", "—");
        setHudText("hud-impr", "—");
        setHudText("hud-ecpm", "—");
        if (lamp) lamp.className = "hud-lamp";
        return;
      }
      const h = await a.get_farm_hud();
      if (!h) return;
      const running = !!(h.running || h.external);
      setHudText("hud-farm", running ? "RUN" : "OFF");
      if (lamp) lamp.className = "hud-lamp" + (running ? " run" : " err");
      setHudText("hud-phones", String(h.phones_online || 0));
      setHudText("hud-today", fmtMoney(h.revenue_today_usd));
      setHudText("hud-clicks", String(h.clicks || 0));
      setHudText("hud-impr", String(h.impressions || 0));
      setHudText("hud-ecpm", "$" + (Number(h.ecpm) || 0).toFixed(2));
    } catch (_e) {
      setHudText("hud-farm", "—");
    } finally {
      setHudText(
        "hud-sync",
        new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })
      );
    }
  }

  function startHudPoll() {
    if (startHudPoll._t) return;
    refreshHud();
    startHudPoll._t = setInterval(refreshHud, 15000);
  }

  window.CPharmSetup = {
    appendLog: function (t) {
      appendLog(setupLog, t, classifySetupLine(t));
      if (setupStatus && setupBusy) {
        const line = String(t).trim();
        if (/Found \d+ phone/i.test(line)) setupStatus.textContent = "Found phones — installing Chromium…";
        else if (/Installing Chromium|Sideloading Chromium/i.test(line)) setupStatus.textContent = "Installing Chromium…";
        else if (/Hiding emulator|browser disguise/i.test(line)) setupStatus.textContent = "Hiding emulator look…";
        else if (/Saving tap|Phone Setup complete/i.test(line)) setupStatus.textContent = "Saving settings…";
      }
    },
    setPhones: setPhones,
    setChecklist: renderChecklist,
    setStep: setSetupPhase,
    setBusy: function (on) {
      setupBusy = on;
      setBusy(setupLed, setupStatus, on, "Setting up phones…");
      if (btnGo) {
        btnGo.disabled = on;
        btnGo.innerHTML = on
          ? '<span class="spinner"></span>Setting up phones…'
          : btnGo.dataset.labelDefault || "Set up my phones";
      }
      const chromeBtn = document.getElementById("btn-chromium");
      if (chromeBtn) chromeBtn.disabled = on;
      const browserBtn = document.getElementById("btn-install-browser");
      const browserSel = document.getElementById("browser-select");
      const phoneSel = document.getElementById("phone-select");
      if (browserBtn) browserBtn.disabled = on;
      if (browserSel) browserSel.disabled = on;
      if (phoneSel) phoneSel.disabled = on;
      if (!on && setupStatus && !setupStatus.dataset.hold) {
        if (Date.now() >= setupStatusLockUntilMs) {
          setupStatus.textContent = "Ready — click Set up my phones";
        }
      }
    },
    onComplete: function (payload) {
      window.CPharmSetup.setBusy(false);
      const ready = payload && (payload.ready === true || payload.ok === true);
      const msg = (payload && payload.message) || "";
      if (msg) appendLog(setupLog, "\n" + msg);
      if (payload && payload.go_label) applyGoLabel(payload.go_label);
      if (ready) {
        setSetupHint("");
        if (setupStatus) {
          delete setupStatus.dataset.hold;
          setSetupStatus("Done. Next: Test, Steps, Groups, then Run.", 12000);
        }
        stepComplete.phones = true;
        updateNavActive();
        showToast("Phones are ready. Go to Test.");
      } else {
        setSetupHint(
          "Something still needs fixing. Read the log. Often you just restart the phones and run setup again."
        );
        if (setupStatus) {
          setupStatus.dataset.hold = "1";
          setSetupStatus("Not done yet. Follow the log.", 12000);
        }
      }
      refreshSetup();
    },
    onChromiumComplete: function (payload) {
      window.CPharmSetup.setBusy(false);
      const msg = (payload && payload.message) || "";
      if (msg) appendLog(setupLog, "\n" + msg);
      if (setupStatus) {
        setSetupStatus(
          payload && payload.ok ? "Chromium installed" : "Chromium install failed. See log.",
          8000
        );
      }
      refreshSetup();
    },
    onBrowserComplete: function (payload) {
      window.CPharmSetup.setBusy(false);
      const msg = (payload && payload.message) || "";
      if (msg) appendLog(setupLog, "\n" + msg);
      const results = (payload && payload.results) || [];
      results.forEach(function (r) {
        appendLog(
          setupLog,
          "  " + r.serial + (r.ok ? " OK" : " FAIL: " + (r.note || "")),
          r.ok ? "log-line-ok" : "log-line-err"
        );
      });
      if (setupStatus) {
        setSetupStatus(
          payload && payload.ok ? "Browser installed" : "Browser install failed. See log.",
          8000
        );
      }
      refreshSetup();
    },
  };

  window.CPharmApp = {
    showView: function (name) {
      showView(name, { animate: true });
    },
    appendLog: function (channel, text) {
      if (channel === "install") appendLog(installLog, text);
      else if (channel === "go") appendLog(goLog, text);
      else if (channel === "boot") appendLog(bootLog, text);
      else appendLog(setupLog, text, classifySetupLine(text));
    },
  };

  window.CPharmDragon = {
    showView: function (name) {
      showView(name, { animate: true });
    },
    goToChapter: function (index) {
      const id = STEP_IDS[index] || "start";
      showView(id, { animate: true });
    },
  };

  /* ── Floating help tooltips (data-help) ─────────────────
     One fixed overlay element at the end of <body>, driven by hover /
     focus. It is never a child of a panel or scroll container, so it can
     never be clipped or end up behind another "window" in the deck. ---- */
  const deckTip = document.createElement("div");
  deckTip.className = "deck-tooltip";
  deckTip.setAttribute("role", "tooltip");
  document.body.appendChild(deckTip);

  let tipSrc = null;

  function showTip(el) {
    tipSrc = el;
    deckTip.textContent = el.getAttribute("data-help") || "";
    positionTip(el);
    requestAnimationFrame(function () {
      if (tipSrc === el) deckTip.classList.add("on");
    });
  }

  function hideTip() {
    tipSrc = null;
    deckTip.classList.remove("on");
  }

  function positionTip(el) {
    const r = el.getBoundingClientRect();
    if (!r || (!r.width && !r.height)) return;
    const pad = 9;
    const vw = document.documentElement.clientWidth;
    const vh = document.documentElement.clientHeight;
    let top = r.top - deckTip.offsetHeight - pad;
    if (top < 6) top = r.bottom + pad; // flip below when no room above
    let left = r.left + r.width / 2 - deckTip.offsetWidth / 2;
    left = Math.max(6, Math.min(left, vw - deckTip.offsetWidth - 6));
    deckTip.style.left = Math.round(left) + "px";
    deckTip.style.top = Math.round(Math.max(6, Math.min(top, vh - deckTip.offsetHeight - 6))) + "px";
  }

  document.addEventListener("mouseover", function (e) {
    const el = e.target && e.target.closest ? e.target.closest("[data-help]") : null;
    if (el) showTip(el);
  });
  document.addEventListener("mouseout", function (e) {
    const el = e.target && e.target.closest ? e.target.closest("[data-help]") : null;
    if (el && el === tipSrc) hideTip();
  });
  document.addEventListener("focusin", function (e) {
    const el = e.target && e.target.closest ? e.target.closest("[data-help]") : null;
    if (el) showTip(el);
  });
  document.addEventListener("focusout", function () {
    hideTip();
  });
  document.addEventListener(
    "scroll",
    function () {
      if (tipSrc) positionTip(tipSrc);
    },
    true
  );
  window.addEventListener("resize", function () {
    if (tipSrc) positionTip(tipSrc);
  });

  async function init() {
    wireStaticNav();

    pyApi = await waitForApi(20000);
    if (!pyApi) {
      showBackendError("Could not connect to PharmFlow backend. Close and reopen PharmFlow.exe.");
      showToast("Backend not connected — restart PharmFlow.exe");
      wizardSteps = STEP_IDS.map(function (id, i) {
        return { id: id, index: i, name: id, subtitle: "" };
      });
      renderStepNav();
      showView("start");
      wireActionButtons();
      startHudPoll();
      return;
    }

    try {
      wizardSteps = (await pyApi.get_wizard_steps()) || [];
    } catch (e) {
      wizardSteps = [];
      showBackendError("Wizard load failed: " + e);
    }
    renderStepNav();
    startHudPoll();

    const startView = new URLSearchParams(window.location.search).get("view") || "start";
    if (startView === "setup") {
      showView("phones");
    } else {
      showView(STEP_IDS.indexOf(startView) >= 0 ? startView : "start");
    }

    await refreshJourney();
    wireActionButtons();
  }

  function wireActionButtons() {
    const refreshSetupBtn = document.getElementById("btn-refresh-setup");
    if (refreshSetupBtn && !refreshSetupBtn.dataset.wired) {
      refreshSetupBtn.dataset.wired = "1";
      refreshSetupBtn.addEventListener("click", refreshSetup);
    }

    const refreshPrereqBtn = document.getElementById("btn-refresh-prereq");
    if (refreshPrereqBtn && !refreshPrereqBtn.dataset.wired) {
      refreshPrereqBtn.dataset.wired = "1";
      refreshPrereqBtn.addEventListener("click", refreshPrereqs);
    }

    if (btnGo && !btnGo.dataset.wired) {
      btnGo.dataset.wired = "1";
      btnGo.addEventListener("click", async function () {
        if (setupBusy) return;
        const a = requireApi("Set up phones");
        if (!a) return;
        setupLog.textContent = "";
        window.CPharmSetup.setBusy(true);
        try {
          const res = await a.run_setup();
          if (res && res.error === "busy") window.CPharmSetup.setBusy(false);
        } catch (e) {
          appendLog(setupLog, "Setup error: " + e);
          window.CPharmSetup.setBusy(false);
        }
      });
    }

    const browserSelect = document.getElementById("browser-select");
    const phoneSelect = document.getElementById("phone-select");
    const btnInstallBrowser = document.getElementById("btn-install-browser");
    if (browserSelect && btnInstallBrowser && !browserSelect.dataset.wired) {
      browserSelect.dataset.wired = "1";

      function fillPhoneOptions(phones) {
        if (!phoneSelect) return;
        const keep = phoneSelect.value;
        phoneSelect.innerHTML = "";
        const allOpt = document.createElement("option");
        allOpt.value = "all";
        allOpt.textContent = "All phones";
        phoneSelect.appendChild(allOpt);
        (phones || []).forEach(function (p) {
          const option = document.createElement("option");
          option.value = p.serial;
          option.textContent = p.label || p.serial;
          phoneSelect.appendChild(option);
        });
        phoneSelect.value = keep || "all";
      }

      try {
        const optApi = requireApi("Install");
        if (optApi && optApi.browser_apk_options) {
          Promise.resolve(optApi.browser_apk_options())
            .then(function (opts) {
              (opts || []).forEach(function (o) {
                const option = document.createElement("option");
                option.value = o.id;
                option.textContent =
                  o.label +
                  (o.installed ? " ✓ installed" : "") +
                  (o.size_mb ? " — " + o.size_mb + " MB" : "");
                browserSelect.appendChild(option);
              });
              if (optApi.live_phone_options) {
                Promise.resolve(optApi.live_phone_options()).then(fillPhoneOptions).catch(function () {
                  fillPhoneOptions([]);
                });
              }
            })
            .catch(function () {
              /* options are best-effort */
            });
        }
      } catch (e) {
        /* best-effort */
      }

      btnInstallBrowser.addEventListener("click", async function () {
        if (setupBusy) return;
        const api = requireApi("Install browser");
        if (!api || !api.install_browser) return;
        const id = browserSelect.value;
        if (!id) {
          appendLog(setupLog, "Pick a browser from the list first.");
          return;
        }
        // Refresh live phones right before installing so the target is current.
        if (api.live_phone_options) {
          try {
            fillPhoneOptions(await Promise.resolve(api.live_phone_options()));
          } catch (e) {
            fillPhoneOptions([]);
          }
        }
        const serial = phoneSelect ? phoneSelect.value : "all";
        if (!serial) {
          appendLog(setupLog, "Pick a phone from the list first (or All phones).");
          return;
        }
        const label = browserSelect.selectedOptions.length
          ? browserSelect.selectedOptions[0].textContent
          : id;
        const targetText =
          serial === "all"
            ? "all phones"
            : phoneSelect && phoneSelect.selectedOptions.length
            ? phoneSelect.selectedOptions[0].textContent
            : serial;
        window.CPharmSetup.setBusy(true);
        appendLog(
          setupLog,
          "\n— Installing browser: " + label + " on " + targetText + " —\n"
        );
        try {
          const res = await api.install_browser(id, serial);
          if (res && res.error === "busy") {
            window.CPharmSetup.setBusy(false);
            return;
          }
          // Result summary arrives async via onBrowserComplete when the thread
          // finishes; this call only starts the install.
        } catch (e) {
          appendLog(setupLog, "Browser install error: " + e);
          window.CPharmSetup.setBusy(false);
        }
      });
    }

    const btnInstallAll = document.getElementById("btn-install-all");
    if (btnInstallAll && !btnInstallAll.dataset.wired) {
      btnInstallAll.dataset.wired = "1";
      btnInstallAll.addEventListener("click", async function () {
        if (installBusy) return;
        const a = requireApi("Install");
        if (!a) return;
        installBusy = true;
        setBusy(installLed, installStatus, true, "Working…");
        if (installLog) installLog.textContent = "";
        appendLog(installLog, "Starting install…\n");
        try {
          const res = await callApi("Install", function (api) {
            return api.run_install_all();
          });
          if (res && res.already_installed) {
            appendLog(installLog, "Everything is already installed — you're ready to go. ✅\n");
            showToast("Everything is already installed ✅");
            stepComplete.install = true;
            updateNavActive();
          } else if (res && res.busy) {
            appendLog(installLog, "An install is already running — watch the log above.\n");
            showToast("Install already running");
          } else {
            appendLog(installLog, "Install started — watch the log.\n");
            showToast("Installing tools. Watch the log.");
            const poll = setInterval(async function () {
              await refreshPrereqs();
              if (stepComplete.install) clearInterval(poll);
            }, 4000);
            setTimeout(function () {
              clearInterval(poll);
            }, 300000);
          }
        } catch (_e) {
          appendLog(installLog, "Install could not start. See the error message above.\n");
          showToast("Install could not start — see log");
        } finally {
          installBusy = false;
          setBusy(installLed, installStatus, false);
        }
      });
    }

    const btnAndroid = document.getElementById("btn-android-install");
    if (btnAndroid && !btnAndroid.dataset.wired) {
      btnAndroid.dataset.wired = "1";
      btnAndroid.addEventListener("click", async function () {
        const androidLog = document.getElementById("android-log");
        const androidLed = document.getElementById("android-led");
        const androidLabel = document.getElementById("android-status-label");
        if (androidLog) androidLog.textContent = "";
        if (androidLed) androidLed.classList.remove("on");
        if (androidLabel) androidLabel.textContent = "Installing…";
        try {
          const res = await callApi("Android install", function (a) {
            return a.run_android_install();
          });
          if (androidLog && res && res.log) appendLog(androidLog, res.log);
          if (androidLog && res && res.message) appendLog(androidLog, res.message);
          showToast("Installing Android SDK…");
          await refreshAndroid();
        } catch (e) {
          if (androidLog) appendLog(androidLog, "Android install failed: " + e);
          if (androidLabel) androidLabel.textContent = "Install failed";
        }
      });
    }

    const btnRefreshCaps = document.getElementById("btn-refresh-caps");
    if (btnRefreshCaps && !btnRefreshCaps.dataset.wired) {
      btnRefreshCaps.dataset.wired = "1";
      btnRefreshCaps.addEventListener("click", refreshMachineCaps);
    }

    const btnSpin = document.getElementById("btn-spin-test-phone");
    if (btnSpin && !btnSpin.dataset.wired) {
      btnSpin.dataset.wired = "1";
      btnSpin.addEventListener("click", async function () {
        try {
          const res = await callApi("Spin up test phone", function (a) {
            return a.spin_up_test_phone();
          });
          const msg = (res && res.message) || "Spinning up one test phone…";
          showToast(msg);
          if (bootLog) appendLog(bootLog, msg);
        } catch (_e) {
          /* banner shown */
        }
      });
    }

    // Home quick-start buttons (view-start).
    const btnStartHome = document.getElementById("btn-start-farm-home");
    if (btnStartHome && !btnStartHome.dataset.wired) {
      btnStartHome.dataset.wired = "1";
      btnStartHome.addEventListener("click", async function () {
        try {
          const res = await callApi("Start farm", function (a) {
            return a.start_farm();
          });
          if (res && res.error) {
            showBackendError(res.error);
            return;
          }
          showToast(res && res.started ? "Farm started — watch the dashboard" : "Farm start triggered");
        } catch (_e) {
          /* banner shown */
        }
      });
    }

    const btnDashHome = document.getElementById("btn-open-dash-home");
    if (btnDashHome && !btnDashHome.dataset.wired) {
      btnDashHome.dataset.wired = "1";
      btnDashHome.addEventListener("click", async function () {
        try {
          const res = await callApi("Dashboard", function (a) {
            return a.open_dashboard();
          });
          if (res && res.error) showBackendError(res.error);
        } catch (_e) {
          /* banner shown */
        }
      });
    }

    const btnSpinHome = document.getElementById("btn-spin-test-phone-home");
    if (btnSpinHome && !btnSpinHome.dataset.wired) {
      btnSpinHome.dataset.wired = "1";
      btnSpinHome.addEventListener("click", async function () {
        try {
          const res = await callApi("Spin up test phone", function (a) {
            return a.spin_up_test_phone();
          });
          if (res && res.started && !res.busy) {
            showToast("Spinning up a test phone — progress streams on the Test step");
            showView("boot", { animate: true });
          } else if (res && res.message) {
            showToast(res.message);
            showView("boot", { animate: true });
          }
        } catch (_e) {
          /* banner shown */
        }
      });
    }

    const btnTest = document.getElementById("btn-test-url");
    if (btnTest && !btnTest.dataset.wired) {
      btnTest.dataset.wired = "1";
      btnTest.addEventListener("click", async function () {
        const input = document.getElementById("site-url-input");
        const url = input && input.value ? input.value.trim() : "";
        try {
          if (url && api() && api().save_site_url) {
            await callApi("Save site", function (a) {
              return a.save_site_url(url);
            });
          }
          const res = await callApi("Test URL", function (a) {
            return a.run_test_url(url || "");
          });
          if (res && res.error) {
            showBackendError(res.error);
            if (bootLog) appendLog(bootLog, res.error);
            return;
          }
          const host = url ? url.replace(/^https?:\/\//, "").split("/")[0] : "site";
          showToast("Opened " + host + " on the phones — check the phone screens");
          if (bootLog && res && res.note) appendLog(bootLog, res.note);
        } catch (_e) {
          /* banner shown */
        }
      });
    }

    const btnSaveSite = document.getElementById("btn-save-site-url");
    if (btnSaveSite && !btnSaveSite.dataset.wired) {
      btnSaveSite.dataset.wired = "1";
      btnSaveSite.addEventListener("click", async function () {
        const input = document.getElementById("site-url-input");
        const url = input && input.value ? input.value.trim() : "";
        if (!url) {
          showToast("Enter a site URL first");
          return;
        }
        try {
          const res = await callApi("Save site", function (a) {
            return a.save_site_url(url);
          });
          if (res) {
            showToast("Saved " + (res.host || url));
            await refreshBoot();
          }
        } catch (_e) {
          /* banner shown */
        }
      });
    }

    const btnEditSeq = document.getElementById("btn-edit-sequence");
    if (btnEditSeq && !btnEditSeq.dataset.wired) {
      btnEditSeq.dataset.wired = "1";
      btnEditSeq.addEventListener("click", async function () {
        try {
          showToast("Opening editor...");
          const res = await callApi("Edit sequence", function (a) {
            return a.run_edit_default_sequence();
          });
          if (res && res.error) {
            showBackendError(res.error);
            return;
          }
          if (res && res.ok !== false) {
            showToast("Editor window opened — it may appear in front of this app");
            await refreshSteps();
          }
        } catch (_e) {
          /* banner shown */
        }
      });
    }
    const btnOpenBuilder = document.getElementById("btn-open-builder");
    if (btnOpenBuilder && !btnOpenBuilder.dataset.wired) {
      btnOpenBuilder.dataset.wired = "1";
      btnOpenBuilder.addEventListener("click", async function () {
        try {
          const res = await callApi("Sequence builder", function (a) {
            return a.open_sequence_builder();
          });
          if (res && res.error) {
            showBackendError(res.error);
            return;
          }
          showToast("Builder window opened");
        } catch (_e) {
          /* banner shown */
        }
      });
    }
    const btnLoadSeq = document.getElementById("btn-load-sequence");
    if (btnLoadSeq && !btnLoadSeq.dataset.wired) {
      btnLoadSeq.dataset.wired = "1";
      btnLoadSeq.addEventListener("click", async function () {
        try {
          const a = requireApi("Load sequence");
          if (!a) return;
          let path = null;
          if (a.pick_sequence_json) {
            const pick = await a.pick_sequence_json(false);
            if (pick && pick.cancelled) return;
            if (pick && pick.error) {
              showBackendError(pick.error);
              return;
            }
            path = pick && pick.path;
          }
          const res = path && a.load_sequence_from_path
            ? await a.load_sequence_from_path(path)
            : await a.run_load_default_sequence();
          if (res && res.cancelled) return;
          if (res && res.error) {
            showBackendError(res.error);
            return;
          }
          if (res && res.ok) {
            showToast("Loaded " + (res.count || 0) + " step(s)");
            await refreshSteps();
          }
        } catch (_e) {
          /* banner shown */
        }
      });
    }
    const btnSaveSeq = document.getElementById("btn-save-sequence");
    if (btnSaveSeq && !btnSaveSeq.dataset.wired) {
      btnSaveSeq.dataset.wired = "1";
      btnSaveSeq.addEventListener("click", async function () {
        try {
          const a = requireApi("Save sequence");
          if (!a) return;
          let path = null;
          if (a.pick_sequence_json) {
            const pick = await a.pick_sequence_json(true);
            if (pick && pick.cancelled) return;
            if (pick && pick.error) {
              showBackendError(pick.error);
              return;
            }
            path = pick && pick.path;
          }
          const res = path && a.save_sequence_to_path
            ? await a.save_sequence_to_path(path)
            : await a.run_save_default_sequence();
          if (res && res.cancelled) return;
          if (res && res.error) {
            showBackendError(res.error);
            return;
          }
          if (res && res.ok) showToast("Sequence saved");
        } catch (_e) {
          /* banner shown */
        }
      });
    }

    const btnManageGroups = document.getElementById("btn-manage-groups");
    if (btnManageGroups && !btnManageGroups.dataset.wired) {
      btnManageGroups.dataset.wired = "1";
      btnManageGroups.addEventListener("click", async function () {
        try {
          const res = await callApi("Manage groups", function (a) {
            return a.open_groups_manager();
          });
          if (res && res.error) {
            showBackendError(res.error);
            return;
          }
          showToast("Groups window opened");
        } catch (_e) {
          /* banner shown */
        }
      });
    }

    const btnAddGroup = document.getElementById("btn-add-group");
    if (btnAddGroup && !btnAddGroup.dataset.wired) {
      btnAddGroup.dataset.wired = "1";
      btnAddGroup.addEventListener("click", async function () {
        try {
          const res = await callApi("Add group", function (a) {
            return a.run_add_group();
          });
          if (res) {
            const sumEl = document.getElementById("teams-summary");
            if (sumEl) sumEl.textContent = groupsSummaryText(res);
            renderGroupsList(res);
            showToast("Group added");
          }
        } catch (_e) {
          /* banner shown */
        }
      });
    }
    const btnHumanize = document.getElementById("btn-humanize");
    if (btnHumanize && !btnHumanize.dataset.wired) {
      btnHumanize.dataset.wired = "1";
      btnHumanize.addEventListener("click", async function () {
        try {
          const res = await callApi("Natural timing", function (a) {
            return a.run_humanize_all_sequences();
          });
          if (res && res.message) showToast(res.message);
          else showToast("Natural timing applied");
          await refreshTeams();
        } catch (_e) {
          /* banner shown */
        }
      });
    }
    const btnDashTeams = document.getElementById("btn-open-dash-teams");
    if (btnDashTeams && !btnDashTeams.dataset.wired) {
      btnDashTeams.dataset.wired = "1";
      btnDashTeams.addEventListener("click", async function () {
        try {
          const res = await callApi("Dashboard", function (a) {
            return a.open_dashboard();
          });
          if (res && res.error) {
            showBackendError(res.error);
            return;
          }
          if (res && res.ok) showToast("Dashboard opened in browser");
        } catch (_e) {
          /* banner shown */
        }
      });
    }

    const btnServer = document.getElementById("btn-start-server");
    if (btnServer && !btnServer.dataset.wired) {
      btnServer.dataset.wired = "1";
      btnServer.addEventListener("click", async function () {
        const a = requireApi("Start service");
        if (!a) return;
        setBusy(runLed, runStatus, true);
        try {
          const res = a.start_server_and_open_dashboard
            ? await a.start_server_and_open_dashboard()
            : await a.start_server();
          if (res && res.error) {
            showBackendError(res.error);
            return;
          }
          showToast("Run window opened");
          await openDashboardWhenReady();
        } catch (e) {
          showBackendError(String(e));
        } finally {
          setBusy(runLed, runStatus, false);
        }
      });
    }

    const btnRun = document.getElementById("btn-run-groups");
    if (btnRun && !btnRun.dataset.wired) {
      btnRun.dataset.wired = "1";
      btnRun.addEventListener("click", async function () {
        const a = requireApi("Run groups");
        if (!a) return;
        setBusy(runLed, runStatus, true);
        try {
          const res = await a.run_all_groups();
          if (res && res.error) {
            showBackendError(res.error);
            return;
          }
          showToast("Run window opened");
          stepComplete.go = true;
          updateNavActive();
        } catch (e) {
          showBackendError(String(e));
        } finally {
          setBusy(runLed, runStatus, false);
        }
      });
    }

    const btnAuto = document.getElementById("btn-start-automation");
    if (btnAuto && !btnAuto.dataset.wired) {
      btnAuto.dataset.wired = "1";
      btnAuto.addEventListener("click", async function () {
        const a = requireApi("Start automation");
        if (!a) return;
        setBusy(runLed, runStatus, true);
        try {
          const res = await a.start_automation_one_click();
          if (res && res.error) {
            showBackendError(res.error);
            return;
          }
          showToast("Run window opened — automation starting");
          stepComplete.go = true;
          updateNavActive();
        } catch (e) {
          showBackendError(String(e));
        } finally {
          setBusy(runLed, runStatus, false);
        }
      });
    }

    const fixNet = document.getElementById("btn-fix-net");
    if (fixNet && !fixNet.dataset.wired) {
      fixNet.dataset.wired = "1";
      fixNet.addEventListener("click", async function () {
        try {
          const res = await callApi("Fix internet", function (a) {
            return a.fix_phone_internet();
          });
          if (res) showToast("Internet restored on " + (res.n || 0) + " phone(s)");
        } catch (_e) {
          /* banner shown */
        }
      });
    }

    const openDash = document.getElementById("btn-open-dash");
    if (openDash && !openDash.dataset.wired) {
      openDash.dataset.wired = "1";
      openDash.addEventListener("click", async function () {
        try {
          const res = await callApi("Dashboard", function (a) {
            return a.open_dashboard();
          });
          if (res && res.error) {
            showBackendError(res.error);
            return;
          }
          if (res && res.ok) showToast("Dashboard opened in browser");
        } catch (_e) {
          /* banner shown */
        }
      });
    }

    const btnCloudSetup = document.getElementById("btn-cloud-setup");
    if (btnCloudSetup && !btnCloudSetup.dataset.wired) {
      btnCloudSetup.dataset.wired = "1";
      btnCloudSetup.addEventListener("click", async function () {
        try {
          const host = window.prompt("Cloud instance IP (e.g. 100.x.x.x):", "");
          if (host == null || !host.trim()) return;
          const countStr = window.prompt("Number of instances:", "8");
          const count = parseInt(countStr || "8", 10);
          if (!count || count < 1) {
            showToast("Enter a valid instance count (1-16)");
            return;
          }
          const a = requireApi("Cloud setup");
          if (!a || !a.cloud_phone_setup) {
            showBackendError("Cloud setup is not available in this build");
            return;
          }
          const res = await a.cloud_phone_setup(host.trim(), Math.min(count, 16));
          if (res && res.error) {
            showBackendError(res.error);
            return;
          }
          showToast("Cloud setup started — watch the Run log");
          showView("go");
        } catch (_e) {
          /* banner shown */
        }
      });
    }

    const btnCloudStatus = document.getElementById("btn-cloud-status");
    if (btnCloudStatus && !btnCloudStatus.dataset.wired) {
      btnCloudStatus.dataset.wired = "1";
      btnCloudStatus.addEventListener("click", async function () {
        try {
          const host = window.prompt("Filter by cloud IP (leave blank for all):", "");
          if (host == null) return;
          const a = requireApi("Cloud status");
          if (!a || !a.cloud_phone_status) {
            showBackendError("Cloud status is not available in this build");
            return;
          }
          const res = await a.cloud_phone_status(host.trim());
          if (res && res.error) {
            showBackendError(res.error);
            return;
          }
          showToast("Cloud status — watch the Run log");
          showView("go");
        } catch (_e) {
          /* banner shown */
        }
      });
    }

    const btnAgentStatus = document.getElementById("btn-agent-status");
    if (btnAgentStatus && !btnAgentStatus.dataset.wired) {
      btnAgentStatus.dataset.wired = "1";
      btnAgentStatus.addEventListener("click", async function () {
        try {
          const a = requireApi("Agent status");
          if (!a || !a.agent_status) {
            showBackendError("Agent status is not available in this build");
            return;
          }
          const res = await a.agent_status();
          if (res && res.error) {
            showBackendError(res.error);
            return;
          }
          showToast("Agent check started — watch the Run log");
          showView("go");
        } catch (_e) {
          /* banner shown */
        }
      });
    }

    const btnAgentSettings = document.getElementById("btn-cloud-agent-settings");
    if (btnAgentSettings && !btnAgentSettings.dataset.wired) {
      btnAgentSettings.dataset.wired = "1";
      btnAgentSettings.addEventListener("click", async function () {
        try {
          const a = requireApi("Agent settings");
          if (!a || !a.cloud_agent_config) {
            showBackendError("Agent settings are not available in this build");
            return;
          }
          const cfg = await a.cloud_agent_config();
          const base = window.prompt(
            "API base URL (OpenAI-compatible):",
            (cfg && cfg.base) || "https://api.openai.com/v1"
          );
          let model = null;
          if (base !== null) {
            model = window.prompt("Model id:", (cfg && cfg.model) || "gpt-4o");
          }
          if (model === null) return;
          const hint = cfg && cfg.configured
            ? "Already configured (leave blank to keep current key)"
            : "Enter your API key (stored in cloud_agent.json on this PC)";
          const key = window.prompt(hint, "");
          if (key === null) return;
          if (!a.save_cloud_agent_config) {
            showBackendError("Saving agent settings is not available in this build");
            return;
          }
          const res = await a.save_cloud_agent_config(base || "", model || "", key || "");
          if (res && res.error) {
            showBackendError(res.error);
            return;
          }
          showToast("Agent settings saved");
        } catch (_e) {
          /* banner shown */
        }
      });
    }

    const btnCloudRun = document.getElementById("btn-cloud-agent");
    if (btnCloudRun && !btnCloudRun.dataset.wired) {
      btnCloudRun.dataset.wired = "1";
      btnCloudRun.addEventListener("click", async function () {
        try {
          const a = requireApi("Cloud agent");
          if (!a || !a.run_cloud_agent) {
            showBackendError("Cloud agent is not available in this build");
            return;
          }
          let cfg = {};
          try {
            if (a.cloud_agent_config) cfg = (await a.cloud_agent_config()) || {};
          } catch (_e) { /* ignore */ }
          if (!cfg.configured) {
            showToast("Configure the agent first via Agent settings…");
            return;
          }
          const goal = window.prompt(
            "What should the cloud agent do? (it may read docker/adb/logs and report; enable --apply in settings for shell actions)",
            ""
          );
          if (goal === null || !goal.trim()) return;
          const allowApply = window.confirm("Allow the agent to run local shell commands (--apply)? Only yes if you trust the model/provider.\n\nNo = read-only inspection only.");
          const res = await a.run_cloud_agent(goal.trim(), allowApply, "", "", 14);
          if (res && res.error) {
            showBackendError(res.error);
            return;
          }
          showToast("Cloud agent started — watch the Run log");
          showView("go");
        } catch (_e) {
          /* banner shown */
        }
      });
    }
  }

  function wireStaticNav() {
    document.querySelectorAll(".btn-next-step").forEach(function (btn) {
      if (btn.dataset.wired) return;
      btn.dataset.wired = "1";
      btn.addEventListener("click", function () {
        const next = btn.dataset.next;
        if (next) showView(next, { animate: true });
      });
    });
    document.querySelectorAll(".btn-prev-step, .btn-prev-inline").forEach(function (btn) {
      if (btn.dataset.wired) return;
      btn.dataset.wired = "1";
      btn.addEventListener("click", function () {
        const prev = btn.dataset.prev;
        if (prev) showView(prev, { animate: true });
      });
    });
  }

  // ── Help modal (opened from File → Help or the __pharmflowOpenHelp hook) ──
  const helpOverlay = document.getElementById("help-overlay");

  function openHelp() {
    if (!helpOverlay) return;
    helpOverlay.hidden = false;
    helpOverlay.style.display = "flex"; // inline wins over any stylesheet
    const closeBtn = document.getElementById("help-close");
    if (closeBtn) closeBtn.focus();
  }

  function closeHelp() {
    if (!helpOverlay) return;
    helpOverlay.hidden = true;
    helpOverlay.style.display = "none";
  }

  if (helpOverlay) {
    const closeBtn = document.getElementById("help-close");
    if (closeBtn) closeBtn.addEventListener("click", closeHelp);
    helpOverlay.addEventListener("click", function (e) {
      if (e.target === helpOverlay) closeHelp();
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && !helpOverlay.hidden) {
        closeHelp();
        e.stopPropagation();
      }
    });
  }

  // Global hook so the native window menu (File → Help) can open the modal.
  window.__pharmflowOpenHelp = openHelp;
  window.__pharmflowCloseHelp = closeHelp;

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();

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

  let activeActionButton = null;
  let actionActivity = null;

  function ensureActionActivity() {
    if (actionActivity) return actionActivity;
    actionActivity = document.createElement("div");
    actionActivity.className = "action-activity";
    actionActivity.setAttribute("role", "status");
    actionActivity.setAttribute("aria-live", "polite");
    actionActivity.hidden = true;
    document.body.appendChild(actionActivity);
    return actionActivity;
  }

  function beginAction(button, label) {
    if (!button) return;
    if (!button.dataset.actionOriginal) button.dataset.actionOriginal = button.textContent;
    activeActionButton = button;
    button.disabled = true;
    button.setAttribute("aria-busy", "true");
    button.classList.add("action-pending");
    button.textContent = label || "Working…";
    const activity = ensureActionActivity();
    activity.hidden = false;
    activity.innerHTML = '<span class="spinner"></span><span>' + escHtml(label || "Working…") + "</span>";
  }

  function finishAction() {
    const button = activeActionButton;
    if (button) {
      button.disabled = false;
      button.removeAttribute("aria-busy");
      button.classList.remove("action-pending");
      if (button.dataset.actionOriginal) {
        if (button.id === "btn-start-farm-home" && button.dataset.mode === "running") {
          button.textContent = "Farm running — open dashboard";
        } else {
          button.textContent = button.dataset.actionOriginal;
        }
        delete button.dataset.actionOriginal;
      }
    }
    activeActionButton = null;
    if (actionActivity) actionActivity.hidden = true;
  }

  let dashConnected = false;

  function markDashConnected() {
    if (dashConnected) return;
    dashConnected = true;
    const el = document.getElementById("backend-error");
    if (el) {
      el.hidden = true;
      el.classList.remove("visible");
    }
  }

  function showBackendError(msg) {
    finishAction();
    const el = document.getElementById("backend-error");
    if (!el) return;
    const text = String(msg || "Action failed");
    // The HUD being up only disproves "backend not connected". It does not
    // mean Start farm / boot / groups succeeded — those errors must stay visible.
    const connectionMissing = /backend not connected|full app/i.test(text);
    if (dashConnected && connectionMissing) {
      el.hidden = true;
      el.classList.remove("visible");
      return;
    }
    el.textContent = text;
    el.hidden = false;
    el.classList.add("visible");
  }

  function requireApi(action) {
    const a = api();
    if (!a) {
      const msg = dashConnected
        ? "This needs the full app — farm data is live in the HUD via the dashboard."
        : "PharmFlow backend not connected — close and reopen PharmFlow.exe.";
      showBackendError(msg);
      showToast(msg);
      return null;
    }
    return a;
  }

  async function callApi(action, fn) {
    const a = requireApi(action);
    if (!a) {
      // Never let callers fall through to a success toast when there is no
      // backend — throw so every try/catch handler reports the failure instead
      // of claiming the action ran.
      throw new Error("backend not connected");
    }
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

  function showToast(msg, keepAction) {
    if (!keepAction) finishAction();
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

  function logClass(cls) {
    if (cls === "err") return "log-line-err";
    if (cls === "warn") return "log-line-warn";
    if (cls === "ok") return "log-line-ok";
    return cls || "";
  }

  function appendLog(el, text, cls) {
    if (!el || text == null) return;
    const raw = String(text);
    const perLine = raw.indexOf("\n") !== -1;
    const passed = logClass(cls);
    raw.split("\n").forEach(function (line) {
      if (!line && line !== "") return;
      const span = document.createElement("span");
      const lineCls = perLine
        ? (classifySetupLine(line) || passed)
        : (passed || classifySetupLine(line));
      if (lineCls) span.className = lineCls;
      span.textContent = line + "\n";
      el.appendChild(span);
    });
    el.scrollTop = el.scrollHeight;
  }

  function classifySetupLine(text) {
    const t = String(text).trim();
    if (!t) return "";
    if (/IMPORTANT|Warning|\bfail|Could not|not ready|not installed|not found|did not|was not|\berror\b|\bFound 0\b/i.test(t)) {
      return "log-line-warn";
    }
    if (/\bSaved:|\blook good\b|\binstalled\b|\bready\b|\bFound [1-9]\d*/i.test(t)) return "log-line-ok";
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

    // App views live outside the numbered wizard pipeline.
    const appDivider = document.createElement("div");
    appDivider.className = "step-nav-phase";
    appDivider.textContent = "Monitor";
    stepNav.appendChild(appDivider);

    const healthBtn = document.createElement("button");
    healthBtn.type = "button";
    healthBtn.className = "step-nav-item";
    healthBtn.dataset.view = "health";
    if (healthBtn.dataset.view === currentView) healthBtn.classList.add("active");
    const healthNum = document.createElement("span");
    healthNum.className = "step-num";
    healthNum.textContent = "✦";
    healthBtn.appendChild(healthNum);
    const healthBody = document.createElement("span");
    const healthTitle = document.createElement("span");
    healthTitle.className = "step-title";
    healthTitle.textContent = "Farm health";
    healthBody.appendChild(healthTitle);
    const healthDesc = document.createElement("span");
    healthDesc.className = "step-desc";
    healthDesc.textContent = "Session quality";
    healthBody.appendChild(healthDesc);
    healthBtn.appendChild(healthBody);
    healthBtn.addEventListener("click", function () {
      showView("health", { animate: true });
    });
    stepNav.appendChild(healthBtn);
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
    builder: refreshBuilder,
    teams: refreshTeams,
    go: refreshGo,
    health: refreshHealth,
  };

  /* ── In-deck sequence builder (cursor_* bridge) ───────── */
  let builderSelectedIndex = -1;
  let builderMutationBusy = false;
  let groupMutationBusy = false;
  let bootAllBusy = false;
  let runActionBusy = false;

  const BUILDER_STEP_TYPES = [
    "open_url",
    "launch_app",
    "tap",
    "wait",
    "swipe",
    "keyevent",
    "close_app",
    "type_text",
    "clear_cookies",
    "rotate_identity",
  ];

  const BUILDER_FIELD_SCHEMA = {
    open_url: [
      { key: "url", label: "Website URL", type: "text", def: "https://getdabflow.app" },
      { key: "post_wait_secs", label: "After-open wait (sec)", type: "text", def: "" },
    ],
    launch_app: [
      { key: "package", label: "Package name", type: "text", def: "com.example.app" },
      { key: "post_wait_secs", label: "After-open wait (sec)", type: "text", def: "" },
    ],
    tap: [
      { key: "x", label: "X", type: "number", def: "540" },
      { key: "y", label: "Y", type: "number", def: "1280" },
      { key: "retries", label: "Retries", type: "number", def: "2" },
      { key: "jitter", label: "Jitter ±px", type: "number", def: "24" },
      { key: "pre_wait_ms", label: "Pre-wait ms", type: "number", def: "0" },
    ],
    wait: [{ key: "seconds", label: "Seconds", type: "number", def: "5" }],
    swipe: [
      { key: "x1", label: "Start X", type: "number", def: "540" },
      { key: "y1", label: "Start Y", type: "number", def: "1600" },
      { key: "x2", label: "End X", type: "number", def: "540" },
      { key: "y2", label: "End Y", type: "number", def: "400" },
      { key: "ms", label: "Speed ms", type: "number", def: "600" },
    ],
    keyevent: [{ key: "key", label: "Key", type: "text", def: "BACK" }],
    close_app: [{ key: "package", label: "Package (optional)", type: "text", def: "" }],
    type_text: [{ key: "text", label: "Text", type: "text", def: "hello world" }],
    clear_cookies: [],
    rotate_identity: [],
  };

  function stepSummaryLine(step) {
    if (!step || typeof step !== "object") return "(invalid)";
    const t = step.type || "?";
    const bits = [t];
    if (t === "open_url" && step.url) bits.push(String(step.url).slice(0, 48));
    else if (t === "launch_app" && step.package) bits.push(String(step.package));
    else if (t === "tap") bits.push((step.x != null ? step.x : "?") + "," + (step.y != null ? step.y : "?"));
    else if (t === "wait" && step.seconds != null) bits.push(String(step.seconds) + "s");
    else if (t === "swipe")
      bits.push(
        (step.x1 != null ? step.x1 : "?") +
          "," +
          (step.y1 != null ? step.y1 : "?") +
          "→" +
          (step.x2 != null ? step.x2 : "?") +
          "," +
          (step.y2 != null ? step.y2 : "?")
      );
    else if (t === "keyevent" && step.key) bits.push(String(step.key));
    else if (t === "close_app" && step.package) bits.push(String(step.package));
    else if (t === "type_text" && step.text) bits.push(JSON.stringify(String(step.text).slice(0, 32)));
    if (step.post_wait_secs != null && step.post_wait_secs !== "") bits.push("+" + step.post_wait_secs + "s");
    return bits.join(" · ");
  }

  function ensureStepsPreview() {
    return document.getElementById("steps-preview");
  }

  function renderStepsPreview(steps) {
    const el = ensureStepsPreview();
    if (!el) return;
    el.innerHTML = "";
    if (!steps || !steps.length) {
      const li = document.createElement("li");
      li.className = "groups-list-empty";
      li.textContent = "No steps yet — open Builder to add some.";
      el.appendChild(li);
      return;
    }
    steps.forEach(function (step, i) {
      const li = document.createElement("li");
      li.textContent = i + 1 + ". " + stepSummaryLine(step);
      el.appendChild(li);
    });
  }

  function setBuilderUpdateVisible(on) {
    const btn = document.getElementById("btn-builder-update");
    if (!btn) return;
    btn.hidden = !on;
    btn.disabled = !on;
  }

  function ensureBuilderDom() {
    const list = document.getElementById("builder-step-list");
    const typeSel = document.getElementById("builder-step-type");
    const fields = document.getElementById("builder-step-fields");
    const btnAdd = document.getElementById("btn-builder-add");
    const btnUpdate = document.getElementById("btn-builder-update");
    if (!list || !typeSel || !fields || !btnAdd || !btnUpdate) return null;
    return { list: list, typeSel: typeSel, fields: fields, btnAdd: btnAdd, btnUpdate: btnUpdate };
  }

  function rebuildBuilderFields(type, values) {
    const fields = document.getElementById("builder-step-fields");
    if (!fields) return;
    values = values || {};
    fields.innerHTML = "";
    const schema = BUILDER_FIELD_SCHEMA[type] || [];
    if (!schema.length) {
      const note = document.createElement("p");
      note.className = "panel-note";
      note.textContent =
        type === "clear_cookies"
          ? "Clears browser cookies — no extra fields."
          : type === "rotate_identity"
          ? "Rotates identity — no extra fields."
          : "No fields for this step type.";
      fields.appendChild(note);
      return;
    }
    schema.forEach(function (f) {
      const row = document.createElement("div");
      row.className = "site-url-row";
      row.style.marginTop = "6px";
      const lab = document.createElement("label");
      lab.className = "browser-picker-label";
      lab.htmlFor = "builder-field-" + f.key;
      lab.textContent = f.label;
      lab.style.minWidth = "120px";
      const input = document.createElement("input");
      input.id = "builder-field-" + f.key;
      input.className = "site-url-input";
      input.dataset.key = f.key;
      input.type = f.type === "number" ? "number" : "text";
      if (f.type === "number") input.step = "any";
      const raw = values[f.key];
      input.value = raw != null && raw !== "" ? String(raw) : f.def != null ? String(f.def) : "";
      row.appendChild(lab);
      row.appendChild(input);
      fields.appendChild(row);
    });
  }

  function collectBuilderStep() {
    const typeSel = document.getElementById("builder-step-type");
    const type = (typeSel && typeSel.value) || "wait";
    const step = { type: type };
    const fields = document.getElementById("builder-step-fields");
    if (!fields) return step;
    fields.querySelectorAll("[data-key]").forEach(function (input) {
      const key = input.dataset.key;
      const v = String(input.value || "").trim();
      if (v === "") return;
      if (key === "post_wait_secs") {
        const n = parseFloat(v);
        if (!Number.isNaN(n) && n >= 0) step[key] = n;
        return;
      }
      if (key === "pre_wait_ms" || key === "seconds") {
        const n = parseFloat(v);
        step[key] = Number.isNaN(n) ? v : n;
        return;
      }
      if (input.type === "number") {
        const n = parseInt(v, 10);
        step[key] = Number.isNaN(n) ? v : n;
        return;
      }
      step[key] = v;
    });
    return step;
  }

  function fillBuilderFormFromStep(step) {
    const typeSel = document.getElementById("builder-step-type");
    if (!typeSel || !step) return;
    const t = step.type || "wait";
    if (BUILDER_STEP_TYPES.indexOf(t) >= 0) typeSel.value = t;
    else typeSel.value = "wait";
    rebuildBuilderFields(typeSel.value, step);
  }

  function renderBuilderStepList(steps) {
    const list = document.getElementById("builder-step-list");
    if (!list) return;
    list.innerHTML = "";
    if (!steps || !steps.length) {
      const li = document.createElement("li");
      li.className = "groups-list-empty";
      li.textContent = "No steps yet — pick a type and click Add step.";
      list.appendChild(li);
      setBuilderUpdateVisible(false);
      return;
    }
    steps.forEach(function (step, i) {
      const li = document.createElement("li");
      li.className = "step-row" + (i === builderSelectedIndex ? " active" : "");
      li.dataset.index = String(i);
      const line = document.createElement("span");
      line.className = "step-row-label";
      line.innerHTML =
        '<span class="step-row-type">#' +
        (i + 1) +
        "</span>" +
        escHtml(stepSummaryLine(step));
      const actions = document.createElement("span");
      actions.className = "step-row-actions";
      [
        { act: "up", label: "Up" },
        { act: "down", label: "Down" },
        { act: "edit", label: "Edit" },
        { act: "del", label: "Delete" },
      ].forEach(function (b) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.textContent = b.label;
        btn.dataset.builderAct = b.act;
        btn.dataset.index = String(i);
        btn.setAttribute(
          "data-help",
          b.act === "up"
            ? "Move this step earlier in the sequence."
            : b.act === "down"
            ? "Move this step later in the sequence."
            : b.act === "edit"
            ? "Load this step into the form so you can change it."
            : "Delete this step from the default sequence."
        );
        actions.appendChild(btn);
      });
      li.appendChild(line);
      li.appendChild(actions);
      list.appendChild(li);
    });
    setBuilderUpdateVisible(builderSelectedIndex >= 0);
  }

  async function refreshBuilder() {
    ensureAdvanced("builder");
    const dom = ensureBuilderDom();
    wireBuilderControls();
    if (!dom) return;
    const a = api();
    if (!a || typeof a.cursor_get_sequence !== "function") {
      renderBuilderStepList([]);
      showToast("Sequence bridge not ready yet");
      return;
    }
    try {
      const res = await a.cursor_get_sequence();
      if (!res || res.ok === false) {
        renderBuilderStepList([]);
        showBackendError((res && res.error) || "Could not load sequence");
        return;
      }
      const steps = res.steps || [];
      if (builderSelectedIndex >= steps.length) builderSelectedIndex = -1;
      renderBuilderStepList(steps);
      if (!dom.typeSel.dataset.fieldsInit) {
        rebuildBuilderFields(dom.typeSel.value || "open_url", {});
        dom.typeSel.dataset.fieldsInit = "1";
      }
      if (steps.length) stepComplete.builder = true;
      updateNavActive();
    } catch (e) {
      renderBuilderStepList([]);
      showToast("Could not load sequence: " + e);
    }
  }

  function wireBuilderControls() {
    const typeSel = document.getElementById("builder-step-type");
    if (typeSel && !typeSel.dataset.wired) {
      typeSel.dataset.wired = "1";
      if (!typeSel.options.length) {
        BUILDER_STEP_TYPES.forEach(function (t) {
          const o = document.createElement("option");
          o.value = t;
          o.textContent = t;
          typeSel.appendChild(o);
        });
      }
      typeSel.addEventListener("change", function () {
        rebuildBuilderFields(typeSel.value, {});
      });
    }

    const btnAdd = document.getElementById("btn-builder-add");
    if (btnAdd && !btnAdd.dataset.wired) {
      btnAdd.dataset.wired = "1";
      btnAdd.addEventListener("click", async function () {
        if (builderMutationBusy) return;
        const a = requireApi("Add step");
        if (!a || typeof a.cursor_add_step !== "function") {
          showToast("Add step not available");
          return;
        }
        builderMutationBusy = true;
        btnAdd.disabled = true;
        try {
          const step = collectBuilderStep();
          const res = await a.cursor_add_step(step);
          if (!res || res.error || res.ok !== true || res.saved !== true) {
            showBackendError((res && (res.error || res.message)) || "Add step failed");
            return;
          }
          builderSelectedIndex = -1;
          showToast("Step added");
          await refreshBuilder();
          await refreshSteps();
        } catch (_e) {
          /* banner shown */
        } finally {
          builderMutationBusy = false;
          btnAdd.disabled = false;
        }
      });
    }

    const btnUpdate = document.getElementById("btn-builder-update");
    if (btnUpdate && !btnUpdate.dataset.wired) {
      btnUpdate.dataset.wired = "1";
      btnUpdate.addEventListener("click", async function () {
        if (builderMutationBusy) return;
        if (builderSelectedIndex < 0) {
          showToast("Select a step with Edit first");
          return;
        }
        const a = requireApi("Update step");
        if (!a || typeof a.cursor_update_step !== "function") {
          showToast("Update step not available");
          return;
        }
        builderMutationBusy = true;
        btnUpdate.disabled = true;
        try {
          const step = collectBuilderStep();
          const res = await a.cursor_update_step(builderSelectedIndex, step);
          if (!res || res.error || res.ok !== true || res.saved !== true) {
            showBackendError((res && (res.error || res.message)) || "Update step failed");
            return;
          }
          showToast("Step updated");
          await refreshBuilder();
          await refreshSteps();
        } catch (_e) {
          /* banner shown */
        } finally {
          builderMutationBusy = false;
          setBuilderUpdateVisible(builderSelectedIndex >= 0);
        }
      });
    }

    const btnClear = document.getElementById("btn-builder-clear-sel");
    if (btnClear && !btnClear.dataset.wired) {
      btnClear.dataset.wired = "1";
      btnClear.addEventListener("click", function () {
        builderSelectedIndex = -1;
        setBuilderUpdateVisible(false);
        const typeSel2 = document.getElementById("builder-step-type");
        rebuildBuilderFields((typeSel2 && typeSel2.value) || "open_url", {});
        refreshBuilder();
      });
    }

    const list = document.getElementById("builder-step-list");
    if (list && !list.dataset.wired) {
      list.dataset.wired = "1";
      list.addEventListener("click", async function (ev) {
        const btn = ev.target && ev.target.closest ? ev.target.closest("[data-builder-act]") : null;
        if (!btn) return;
        if (builderMutationBusy && btn.dataset.builderAct !== "edit") return;
        const act = btn.dataset.builderAct;
        const idx = parseInt(btn.dataset.index, 10);
        if (Number.isNaN(idx)) return;
        const a = requireApi("Builder");
        if (!a) return;
        try {
          if (act === "edit") {
            if (typeof a.cursor_get_sequence !== "function") return;
            const res = await a.cursor_get_sequence();
            if (!res || res.ok === false) {
              showBackendError((res && res.error) || "Could not load that step");
              return;
            }
            const steps = res.steps || [];
            const step = steps[idx];
            if (!step) return;
            builderSelectedIndex = idx;
            fillBuilderFormFromStep(step);
            renderBuilderStepList(steps);
            showToast("Editing step #" + (idx + 1));
            return;
          }
          builderMutationBusy = true;
          if (act === "del") {
            if (typeof a.cursor_remove_step !== "function") {
              showToast("Remove step not available");
              return;
            }
            const res = await a.cursor_remove_step(idx);
            if (!res || res.error || res.ok !== true || res.saved !== true) {
              showBackendError((res && (res.error || res.message)) || "Remove step failed");
              return;
            }
            if (builderSelectedIndex === idx) builderSelectedIndex = -1;
            else if (builderSelectedIndex > idx) builderSelectedIndex -= 1;
            showToast("Step removed");
            await refreshBuilder();
            await refreshSteps();
            return;
          }
          if (act === "up" || act === "down") {
            if (typeof a.cursor_move_step !== "function") {
              showToast("Move step not available");
              return;
            }
            const dir = act === "up" ? -1 : 1;
            const res = await a.cursor_move_step(idx, dir);
            if (!res || res.error || res.ok !== true || res.saved !== true) {
              showBackendError((res && (res.error || res.message)) || "Move step failed");
              return;
            }
            if (builderSelectedIndex === idx) builderSelectedIndex = idx + dir;
            else if (builderSelectedIndex === idx + dir) builderSelectedIndex = idx;
            await refreshBuilder();
            await refreshSteps();
          }
        } catch (_e) {
          /* banner shown */
        } finally {
          if (act !== "edit") builderMutationBusy = false;
        }
      });
    }
  }

  function nextStepId(fromId) {
    const idx = STEP_IDS.indexOf(fromId);
    if (idx < 0 || idx >= STEP_IDS.length - 1) return null;
    return STEP_IDS[idx + 1];
  }

  function showView(name, opts) {
    opts = opts || {};
    if (STEP_IDS.indexOf(name) < 0 && name !== "health") name = "start";
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
      download_pharmflow: "Get PharmFlow",
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

  async function refreshSetup(options) {
    options = options || {};
    ensureAdvanced("phones");
    if (options.announce) {
      appendLog(setupLog, "[check] Checking ADB phones, browser, Tor, and setup state…", "log-line-accent");
    }
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
      const livePhones = phonesItem && phonesItem.phones ? phonesItem.phones.length : 0;
      if (
        livePhones > 0 &&
        state &&
        (state.ready || state.setup_already_done) &&
        !state.awaiting_cold_boot
      ) {
        stepComplete.phones = true;
      } else if (!livePhones) {
        stepComplete.phones = false;
      }
      if (options.announce) {
        const count = phonesItem && phonesItem.phones ? phonesItem.phones.length : 0;
        const fails = (state.checklist || []).filter(function (item) {
          return item && item.status === "fail";
        });
        if (fails.length) {
          const titles = fails.map(function (item) {
            return item.title || item.id || "check";
          }).join("; ");
          appendLog(setupLog, "[check] Failed: " + titles, "log-line-warn");
          showBackendError(titles);
        } else if (!count) {
          appendLog(setupLog, "[check] Finished — no phones answering ADB.", "log-line-warn");
          showToast("Checks finished — no phones answering ADB");
        } else {
          appendLog(setupLog, "[check] Finished — " + count + " phone(s) answering ADB.", "log-line-ok");
          showToast("Checks finished — " + count + " phone(s)");
        }
      }
      updateNavActive();
    } catch (e) {
      if (options.announce) appendLog(setupLog, "[check] Failed: " + e, "log-line-warn");
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
          if (!s.id) return;
          if (s.id === "phones") {
            stepComplete.phones = s.complete === true;
            return;
          }
          if (!s.complete) return;
          if (["start", "install", "android"].indexOf(s.id) >= 0) {
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
    appendLog(setupLog, "[action] " + action + " started…", "log-line-accent");
    try {
      const res = await a.run_setup_action(action);
      if (res && res.log) appendLog(setupLog, res.log, classifySetupLine(res.log));
      if (res && res.message) appendLog(setupLog, res.message);
      if (res && res.checklist) renderChecklist(res.checklist);
      if (res && res.phones) setPhones(res.phones);
      if (!res || res.error || res.ok !== true || !res.message) {
        const fail = (res && (res.error || res.message)) || "no result";
        appendLog(setupLog, "[action] " + action + " failed: " + fail, "log-line-warn");
        showBackendError(fail);
      } else {
        appendLog(setupLog, "[action] " + res.message, "log-line-ok");
        showToast(res.message);
      }
    } catch (e) {
      appendLog(setupLog, "Action failed: " + e, "log-line-warn");
    }
  }

  /* ── Machine + emulator inventory (Android step, ARM64-aware) ── */
  async function refreshMachineCaps(options) {
    options = options || {};
    const el = document.getElementById("machine-caps");
    if (!el) return;
    const androidLog = document.getElementById("android-log");
    const androidLabel = document.getElementById("android-status-label");
    if (options.announce && androidLog) appendLog(androidLog, "[inventory] Check again started — scanning CPU, Docker, MuMu, AVD, USB, and ADB…", "log-line-accent");
    if (options.announce && androidLabel) androidLabel.textContent = "Checking machine…";
    const a = api();
    if (!a || typeof a.get_machine_capabilities !== "function") {
      el.innerHTML =
        '<p class="panel-note">Inventory needs the PharmFlow backend — close and reopen PharmFlow.exe.</p>';
      return;
    }
    try {
      const m = await a.get_machine_capabilities();
      if (m && m.ok === false) {
        if (el) el.innerHTML = machineCapsHtml(m);
        const fail = (m && m.error) || "Inventory scan failed";
        if (options.announce && androidLog) appendLog(androidLog, "[inventory] Failed: " + fail, "log-line-warn");
        if (androidLabel) androidLabel.textContent = "Inventory failed";
        showBackendError(fail);
        return;
      }
      if (el) el.innerHTML = machineCapsHtml(m);
      if (options.announce && androidLog) {
        const n = m && m.phones_online != null ? m.phones_online : 0;
        appendLog(androidLog, "[inventory] Complete — " + n + " phone(s) answering ADB.", "log-line-ok");
        if (androidLabel) androidLabel.textContent = "Inventory ready";
        showToast("Machine inventory refreshed");
      }
    } catch (e) {
      el.innerHTML = '<p class="panel-note">Inventory scan failed — click Check again.</p>';
      if (options.announce && androidLog) appendLog(androidLog, "[inventory] Failed: " + e, "log-line-warn");
      if (androidLabel) androidLabel.textContent = "Inventory failed";
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
      ((Number(m.phones_online) || 0) > 0 ? "ok" : "off") +
      '"></span><strong>' +
      (Number(m.phones_online) || 0) +
      "</strong> phone(s) answering ADB" +
      (phones.length ? " — chips below are what ADB listed" : " — start an emulator or plug a phone") +
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
    dbg("click: refreshPrereqs");
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
      if (!st || typeof st !== "object") {
        if (statusEl) statusEl.textContent = "Status unavailable";
        if (labelEl) labelEl.textContent = "Status unavailable";
        return;
      }
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
      li.textContent = "No groups yet. Click Add group.";
      list.appendChild(li);
      return;
    }
    const canRemove = groups.length > 1;
    groups.forEach(function (g, gi) {
      const li = document.createElement("li");
      li.className = "group-row";
      li.dataset.index = String(gi);
      const connected = g.phone_count || 0;
      const configured = g.configured_count || connected;
      let extra = "";
      if (configured > connected) {
        extra = " (" + configured + " saved, " + connected + " connected)";
      }

      const line = document.createElement("span");
      line.className = "group-line";
      line.style.display = "flex";
      line.style.alignItems = "center";
      line.style.gap = "8px";

      const nameInput = document.createElement("input");
      nameInput.type = "text";
      nameInput.className = "group-name-input";
      nameInput.value = g.name || "Group";
      nameInput.dataset.groupName = String(gi);
      nameInput.setAttribute("aria-label", "Group name");

      const meta = document.createElement("span");
      meta.className = "panel-note";
      meta.style.margin = "0";
      meta.style.whiteSpace = "nowrap";
      meta.textContent =
        connected + " phone" + (connected === 1 ? "" : "s") + extra;

      line.appendChild(nameInput);
      line.appendChild(meta);

      const actions = document.createElement("span");
      actions.style.display = "flex";
      actions.style.gap = "4px";
      actions.style.flexShrink = "0";

      const saveBtn = document.createElement("button");
      saveBtn.type = "button";
      saveBtn.className = "btn-mini";
      saveBtn.textContent = "Save";
      saveBtn.dataset.renameGroup = String(gi);
      saveBtn.setAttribute("data-help", "Rename this group in the saved config.");
      actions.appendChild(saveBtn);

      if (canRemove) {
        const removeBtn = document.createElement("button");
        removeBtn.type = "button";
        removeBtn.className = "btn-mini btn-remove-group";
        removeBtn.textContent = "Remove";
        removeBtn.dataset.removeGroup = String(gi);
        removeBtn.setAttribute(
          "data-help",
          "Remove this group from the saved config. Phones are not touched."
        );
        actions.appendChild(removeBtn);
      }

      li.appendChild(line);
      li.appendChild(actions);
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

  async function pollFarmStart(maxMs) {
    const start = Date.now();
    const a = api();
    while (a && Date.now() - start < maxMs) {
      try {
        const st = a.farm_status ? await a.farm_status() : await a.get_farm_hud();
        if (st && st.ok === false && !st.starting) {
          const error = st.error || "Farm startup failed — read the Run log";
          if (runStatus) runStatus.textContent = "Farm startup failed — read the Run log";
          appendLog(goLog, "[farm] " + error, "log-line-warn");
          showToast(error);
          return false;
        }
        if (st && st.running && !st.starting) {
          applyHomeFarmState(true);
          const dashUp = st.dashboard_ready === true;
          if (runStatus) {
            runStatus.textContent = dashUp
              ? "Farm running"
              : "Farm worker running — dashboard not up";
          }
          appendLog(
            goLog,
            dashUp
              ? "[farm] Farm worker is running. Operator dashboard is answering."
              : "[farm] Farm worker is running. Operator dashboard is not answering on 127.0.0.1:8091.",
            dashUp ? "log-line-ok" : "log-line-warn"
          );
          showToast(
            dashUp
              ? "Farm worker is running"
              : "Farm worker is running — dashboard is not up"
          );
          return true;
        }
      } catch (_e) {
        /* startup can briefly race the status endpoint */
      }
      await new Promise(function (resolve) { setTimeout(resolve, 2000); });
    }
    if (runStatus) runStatus.textContent = "Still starting — read the Run log";
    appendLog(goLog, "[farm] No running status yet. The farm may still be starting — read the Run log.", "log-line-warn");
    showToast("Farm has not reported running yet — read the Run log");
    return false;
  }

  async function pollServiceStart(maxMs) {
    const start = Date.now();
    while (Date.now() - start < maxMs) {
      const a = api();
      if (!a || !a.is_dashboard_ready) break;
      try {
        const st = await a.is_dashboard_ready();
        if (st && st.ok === false && !st.starting) return st;
        if (st && st.ready && !st.starting) return st;
      } catch (_e) {
        /* retry until the worker records a result */
      }
      await new Promise(function (r) { setTimeout(r, 2000); });
    }
    return { ok: false, error: "Service has not answered yet — read the Run log" };
  }

  async function pollNamedStatus(methodName, missing) {
    while (true) {
      const a = api();
      if (!a || typeof a[methodName] !== "function") {
        return { ok: false, error: missing };
      }
      try {
        const st = await a[methodName]();
        if (!st || !st.starting) return st || { ok: false, error: missing };
      } catch (e) {
        return { ok: false, error: String(e) };
      }
      await new Promise(function (r) { setTimeout(r, 2000); });
    }
  }

  async function pollBootAll() {
    while (true) {
      const a = api();
      if (!a || !a.boot_all_status) {
        return { ok: false, error: "Boot status is not available in this build" };
      }
      try {
        const st = await a.boot_all_status();
        if (!st || !st.starting) return st || { ok: false, error: "Boot failed" };
      } catch (e) {
        return { ok: false, error: String(e) };
      }
      await new Promise(function (r) { setTimeout(r, 2000); });
    }
  }

  async function startBootAll(btn) {
    if (bootAllBusy) return;
    const a = requireApi("Boot all phones");
    if (!a) return;
    if (typeof a.boot_all_phones !== "function") {
      showToast("Boot-all not ready yet — waiting on bridge");
      return;
    }
    bootAllBusy = true;
    btn.disabled = true;
    try {
      const res = await a.boot_all_phones();
      if (res && (res.error || res.ok === false)) {
        showBackendError((res && res.error) || "Boot failed");
        if (bootLog) appendLog(bootLog, (res && res.error) || "Boot failed");
        return;
      }
      if (res && res.already_booting) {
        const msg = res.message || "Boot already running — watch the Test log";
        showToast(msg);
        if (bootLog) appendLog(bootLog, msg);
        showView("boot", { animate: true });
        // Keep polling — do not bail; prior click left a live worker.
      } else {
        showToast("Booting phones — watch the Test log", true);
        showView("boot", { animate: true });
      }
      const st = await pollBootAll();
      const detail = (st && (st.error || st.message || st.warning)) || "Boot failed";
      if (!st || (st.ok === false && st.error)) {
        showBackendError(st.error || detail);
        if (bootLog) appendLog(bootLog, st.error || detail);
        return;
      }
      if (st && st.partial && st.warning) {
        showToast(st.warning);
      } else {
        showToast(detail, true);
      }
      if (bootLog) appendLog(bootLog, detail);
    } catch (_e) {
      /* banner shown */
    } finally {
      bootAllBusy = false;
      btn.disabled = false;
    }
  }

  async function pollGroupsRun() {
    while (true) {
      const a = api();
      if (!a || !a.groups_run_status) {
        return { ok: false, error: "Groups status is not available in this build" };
      }
      try {
        const st = await a.groups_run_status();
        if (!st || !st.starting) return st || { ok: false, error: "Run groups failed" };
      } catch (e) {
        return { ok: false, error: String(e) };
      }
      await new Promise(function (r) { setTimeout(r, 2000); });
    }
  }

  async function openDashboardWhenReady() {
    const a = requireApi("Dashboard");
    if (!a) return;
    const st = a.is_dashboard_ready ? await a.is_dashboard_ready() : null;
    if (st && st.ok === false && st.error) {
      showBackendError(st.error);
      return;
    }
    if (st && st.ready) {
      if (st.dashboard_opened) {
        showToast("Control dashboard opened in your browser");
        return;
      }
      const opened = await a.open_dashboard();
      if (!opened || opened.error || opened.ok === false || opened.opened === false) {
        showBackendError((opened && opened.error) || "Control dashboard did not open in the browser");
        return;
      }
      showToast("Control dashboard opened in your browser");
      return;
    }
    const ready = await pollDashboardReady(180000);
    if (ready) {
      const opened = await a.open_dashboard();
      if (!opened || opened.error || opened.ok === false || opened.opened === false) {
        showBackendError((opened && opened.error) || "Control dashboard did not open in the browser");
        return;
      }
      showToast("Control dashboard opened in your browser");
    } else {
      showBackendError("Service has not answered yet — read the Run log");
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
      if (!s || typeof s !== "object" || s.ok === false) {
        if (hint) hint.textContent = "Enter your site URL above, then click Save.";
        return;
      }
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
      if (!s || typeof s !== "object" || s.ok === false) return;
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
    const allScreens = [];
    const seenScreen = {};
    (mapData.pages || []).forEach(function (pg) {
      (pg.screens || []).forEach(function (name) {
        const key = String(name || "").toLowerCase();
        if (!key || seenScreen[key]) return;
        seenScreen[key] = true;
        allScreens.push(key);
      });
    });
    let html =
      '<div class="map-summary">' +
      "<span><strong>" + mapData.pages_scanned + "</strong> pages</span>" +
      "<span><strong>" + mapData.total_internal_links + "</strong> internal links</span>" +
      "<span><strong>" + mapData.total_forms + "</strong> " + (mapData.total_forms === 1 ? "form" : "forms") + "</span>" +
      (allScreens.length
        ? "<span><strong>" + allScreens.length + "</strong> in-app screen" + (allScreens.length === 1 ? "" : "s") + "</span>"
        : "") +
      "<span class=\"map-slow\">scanned in " +
      (Number(mapData.duration_ms) > 0
        ? (Number(mapData.duration_ms) / 1000).toFixed(1) + "s"
        : "—") +
      "</span>" +
      "</div>";
    if (allScreens.length) {
      html +=
        '<div class="map-block map-screens-summary"><span class="map-block-label">In-app screens</span><div class="map-chips">' +
        allScreens
          .map(function (s) {
            return "<code>" + escHtml(s) + "</code>";
          })
          .join(" ") +
        "</div></div>";
    }
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
      const screens = (pg.screens || [])
        .map(function (s) {
          return "<code>" + escHtml(s) + "</code>";
        })
        .join(" ");
      const readAs = pg.read_as ? '<span class="map-read-as">' + escHtml(pg.read_as) + "</span>" : "";
      html +=
        '<div class="map-page">' +
        '<h3 class="map-page-title">' + escHtml(pg.title || pg.url) + "</h3>" +
        '<p class="map-page-url">' + escHtml(pg.url) + (readAs ? " " + readAs : "") + "</p>" +
        (screens
          ? '<div class="map-block"><span class="map-block-label">Screens</span><div class="map-chips">' + screens + "</div></div>"
          : "") +
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
          logLine("Scanning " + url + " (read-only, every same-host page)…");
          const started = await callApi("Scan site", function (a) {
            return a.scan_site(url);
          });
          if (!started || started.error || started.ok === false) {
            status(started && started.error ? started.error : "Scan failed", "bad");
            logLine(started && started.error ? started.error : "Scan failed");
            return;
          }
          if (started.busy && !started.started) {
            status(started.message || "A site map is already running", "busy");
            showToast(started.message || "A site map is already running");
            return;
          }
          const res = await pollNamedStatus(
            "scan_site_status",
            "Site map status is not available in this build"
          );
          if (!res || !res.ok) {
            status(res && res.error ? res.error : "Scan failed", "bad");
            logLine(res && res.error ? res.error : "Scan failed");
            return;
          }
          renderMapResults(res);
          const screenCount = (function () {
            const seen = {};
            let n = 0;
            (res.pages || []).forEach(function (pg) {
              (pg.screens || []).forEach(function (name) {
                const key = String(name || "").toLowerCase();
                if (!key || seen[key]) return;
                seen[key] = true;
                n += 1;
              });
            });
            return n;
          })();
          status(
            res.pages_scanned +
              " page(s) mapped" +
              (screenCount ? ", " + screenCount + " in-app screen" + (screenCount === 1 ? "" : "s") : "") +
              ", " +
              res.total_forms +
              (res.total_forms === 1 ? " form" : " forms") +
              " found",
            "ok"
          );
          logLine(
            "Mapped " +
              res.pages_scanned +
              " page(s) on " +
              res.host +
              (screenCount ? " (" + screenCount + " in-app screens)" : "") +
              (Number(res.duration_ms) > 0
                ? " in " + (Number(res.duration_ms) / 1000).toFixed(1) + "s"
                : "")
          );
          if (res.errors && res.errors.length) {
            logLine(res.errors.length + " page(s) unreachable — " + res.errors[0].url + " (" + res.errors[0].error + ")");
          }
          showToast(
            "Mapped " +
              res.pages_scanned +
              " page(s)" +
              (res.truncated ? "; stopped early with " + (res.remaining_urls || 0) + " still queued" : "") +
              (res.errors && res.errors.length ? "; " + res.errors.length + " unreachable" : "")
          );
          if (res.truncated) {
            logLine(
              "Scan stopped early — " +
                (res.remaining_urls || 0) +
                " same-host URL(s) were still queued."
            );
          }
          const gen = document.getElementById("btn-map-generate");
          if (gen) gen.disabled = false;
        } catch (e) {
          status("Scan failed", "bad");
          logLine("Scan failed: " + e);
          showToast("Site map scan failed");
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
          if (!res || !res.ok || res.saved !== true || !(res.steps > 0)) {
            status(res && res.error ? res.error : "Generate failed", "bad");
            logLine(res && res.error ? res.error : "Generate failed");
            return;
          }
          status("Saved starter sequence (" + res.steps + " steps) — refine it in Steps/Builder", "ok");
          logLine("Saved " + res.steps + "-step starter sequence to " + res.path);
          logLine(res.note || "");
          showToast("Starter sequence is now your default — refine in Steps");
          stepComplete.map = true;
          updateNavActive();
          await refreshSteps();
          await refreshBuilder();
        } catch (e) {
          status("Generate failed", "bad");
          logLine("Generate failed: " + e);
          showToast("Starter sequence generation failed");
        }
      });
    }
  }

  function earnField(id) {
    const el = document.getElementById(id);
    return el && el.value ? String(el.value).trim() : "";
  }

  function earnParamsFromForm() {
    return {
      phones: earnField("earn-phones"),
      visits_per_phone: earnField("earn-visits"),
      target_usd: earnField("earn-usd"),
      ecpm: earnField("earn-ecpm"),
      impressions_per_visit: earnField("earn-ipv"),
      path2_share: earnField("earn-path2"),
      ads_allowed: (document.getElementById("earn-ads") || {}).value === "on",
      visits_per_paid_action: earnField("earn-ratio"),
    };
  }

  function fillEarnForm(plan) {
    if (!plan || plan.saved !== true) return;
    const set = function (id, value) {
      const el = document.getElementById(id);
      if (el && value != null && value !== "") el.value = String(value);
    };
    set("earn-phones", plan.phones);
    set("earn-visits", plan.visits_per_phone);
    set("earn-usd", plan.target_usd);
    set("earn-ecpm", plan.ecpm);
    set("earn-ipv", plan.impressions_per_visit);
    set("earn-path2", plan.path2_share);
    set("earn-ratio", plan.visits_per_paid_action);
    const ads = document.getElementById("earn-ads");
    if (ads) ads.value = plan.ads_allowed ? "on" : "off";
  }

  function earnStatusText(plan) {
    if (!plan || plan.ok === false) return (plan && plan.error) || "Mix was not computed.";
    const visits = Array.isArray(plan.visits_by_phone) ? plan.visits_by_phone.join(",") : String(plan.visits_per_phone);
    const ads = Array.isArray(plan.path3_by_phone) ? plan.path3_by_phone.join(",") : String(plan.path3_per_phone);
    let text =
      "Per phone visits: " + visits + ". Path 3: " + ads + ". " +
      "Means ~" + plan.path1_per_phone + " Path 1, " +
      plan.path2_per_phone + " Path 2, " + plan.path3_per_phone + " Path 3. " +
      (plan.note || "");
    if (plan.settings_warning) text += " Warning: " + plan.settings_warning;
    if (plan.groups && plan.groups.updated) {
      text += " Updated hits/day on " + plan.groups.updated + " phone(s) in Groups.";
    }
    return text;
  }

  async function refreshEarnPlan() {
    const status = document.getElementById("earn-plan-status");
    if (!status) return;
    const a = api();
    if (!a || typeof a.get_earn_plan !== "function") return;
    try {
      const plan = await a.get_earn_plan();
      fillEarnForm(plan);
      if (plan && plan.saved === true) status.textContent = earnStatusText(plan);
    } catch (e) {
      status.textContent = "Could not read the saved mix: " + e;
    }
  }

  async function refreshSteps() {
    ensureAdvanced("steps");
    ensureStepsPreview();
    const a = api();
    if (!a) return;
    const el = document.getElementById("steps-summary");
    try {
      let count = 0;
      let hasSteps = false;
      if (typeof a.get_automation_info === "function") {
        const info = await a.get_automation_info();
        hasSteps = !!(info && info.has_steps);
        count = (info && info.count) || 0;
      }
      if (typeof a.cursor_get_sequence === "function") {
        const seq = await a.cursor_get_sequence();
        const steps = (seq && seq.steps) || [];
        count = (seq && seq.count != null) ? seq.count : steps.length;
        hasSteps = count > 0;
        renderStepsPreview(steps);
      } else {
        renderStepsPreview([]);
      }
      if (el) {
        el.textContent = hasSteps
          ? count + " step(s) in default sequence."
          : "No default steps yet.";
      }
      if (hasSteps) stepComplete.steps = true;
      updateNavActive();
      await refreshEarnPlan();
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
      if (!s || typeof s !== "object") {
        if (el) el.textContent = "Could not load groups.";
        renderGroupsList({ groups: [] });
        return;
      }
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
      const s = await a.get_launch_summary();
      if (!s || s.ok === false) {
        if (el) el.textContent = (s && s.error) || "Could not load the run summary.";
        return;
      }
      if (el) {
        el.textContent =
          s.summary || "Start the service, then run all groups.";
      }
    } catch (e) {
      if (el) el.textContent = "Could not load the run summary: " + e;
    }
  }

  /* ── Farm health view ────────────────────────────────── */
  function pct(v) {
    if (v == null) return "—";
    return (v * 100).toFixed(1) + "%";
  }

  function renderHealth(data) {
    const summaryEl = document.getElementById("health-summary");
    const tableEl = document.getElementById("health-table");
    const noteEl = document.getElementById("health-note");
    const led = document.getElementById("health-led");
    if (!summaryEl) return;
    if (!data || data.ok === false) {
      summaryEl.innerHTML =
        '<p class="panel-note">Health unavailable: ' +
        (data && data.error ? String(data.error) : "farm logs not found") +
        "</p>";
      if (tableEl) tableEl.innerHTML = "";
      if (led) led.classList.remove("led-ok");
      if (noteEl) noteEl.textContent = "Health data unavailable.";
      return;
    }
    if (led) led.classList.toggle("led-ok", !!data.farm_alive);
    const s = data.summary || {};
    const p = data.paying || {};
    const po = data.payout || {};
    const cards = [
      ["Farm", data.farm_alive ? "LIVE" : "idle", data.farm_alive ? "#3ecfb0" : "#f2a65a"],
      ["Steps (1h)", s.steps == null ? "—" : String(s.steps), "#c8d3d8"],
      ["Dump timeouts", String(s.dump_timeouts == null ? 0 : s.dump_timeouts), s.dump_timeouts ? "#ff7a70" : "#3ecfb0"],
      ["Timeout rate", pct(s.timeout_rate), s.timeout_rate && s.timeout_rate > 0.2 ? "#ff7a70" : "#3ecfb0"],
      ["Fallback taps", String(s.fallback_taps == null ? 0 : s.fallback_taps), s.fallback_taps ? "#f2a65a" : "#3ecfb0"],
      ["Fallback rate", pct(s.fallback_rate), s.fallback_rate && s.fallback_rate > 0.2 ? "#f2a65a" : "#3ecfb0"],
      ["Paying fills", p.paying == null ? "—" : String(p.paying), p.paying ? "#3ecfb0" : "#ff7a70"],
      ["Payout", po.payout_usd == null ? "—" : "$" + Number(po.payout_usd).toFixed(2), po.payout_usd ? "#3ecfb0" : "#c8d3d8"],
      ["Clicks / impr", po.clicks == null ? "—" : po.clicks + " / " + po.impressions, "#c8d3d8"],
    ];
    summaryEl.innerHTML =
      '<div class="health-cards">' +
      cards
        .map(function (c) {
          return (
            '<div class="health-card"><span class="health-card-label">' +
            c[0] +
            '</span><span class="health-card-value" style="color:' +
            c[2] +
            '">' +
            c[1] +
            "</span></div>"
          );
        })
        .join("") +
      "</div>";

    const phones = data.phones || [];
    if (tableEl) {
      if (!phones.length) {
        const steps = s.steps == null ? 0 : Number(s.steps);
        tableEl.innerHTML = steps > 0
          ? '<p class="panel-note">No dump timeouts or fallback taps in the last hour. Step lines are not listed here unless a timeout or fallback was on that phone.</p>'
          : '<p class="panel-note">No session steps in the last hour. An empty window is not a clean farm.</p>';
      } else {
        const rows = phones
          .map(function (r) {
            return (
              "<tr><td>" +
              escHtml(r.name ? r.name : r.serial) +
              "</td><td>" +
              escHtml(r.serial) +
              "</td><td>" +
              (r.steps || 0) +
              "</td><td>" +
              (r.timeouts || 0) +
              "</td><td>" +
              pct(r.timeout_rate) +
              "</td><td>" +
              (r.fallbacks || 0) +
              "</td><td>" +
              pct(r.fallback_rate) +
              "</td></tr>"
            );
          })
          .join("");
        tableEl.innerHTML =
          '<table class="health-table"><thead><tr><th>Phone</th><th>Serial</th><th>Steps</th><th>Timeouts</th><th>Timeout %</th><th>Fallbacks</th><th>Fallback %</th></tr></thead><tbody>' +
          rows +
          "</tbody></table>";
      }
    }
    const age =
      data.log_age_s == null ? "" : " · log " + data.log_age_s + "s old";
    const round =
      p.round == null ? "" : " · paying round " + p.round + (p.newnym ? " · newnym " + p.newnym : "");
    const worker = data.farm_alive
      ? "A farm worker process is running."
      : "No farm worker process is running. A fresh log is not a live farm.";
    if (noteEl) noteEl.textContent =
      worker + " Last hour of " + (data.log_path ? data.log_path.split(/[\\/]/).pop() : "farm log") + age + round + ".";
  }

  async function refreshHealth() {
    const a = api();
    if (!a || typeof a.get_farm_health !== "function") return;
    try {
      const data = await a.get_farm_health();
      renderHealth(data);
    } catch (_e) {
      renderHealth({ ok: false, error: "backend call failed" });
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
    const entries = (payload.catalog || []).filter(function (e) {
      return e.step === step;
    });
    if (!entries.length) {
      box.hidden = true;
      return;
    }
    box.hidden = false;
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

  // Home quick-start reflects live farm state (called from the HUD poll).
  function applyHomeFarmState(running) {
    const btn = document.getElementById("btn-start-farm-home");
    if (!btn) return;
    const mode = running ? "running" : "start";
    if (btn.dataset.mode === mode) return;
    btn.dataset.mode = mode;
    btn.textContent = running ? "Farm running — open dashboard" : "Start farm";
    const stop = document.getElementById("btn-stop-farm-home");
    if (stop) stop.hidden = !running;
  }

  function fmtMoney(v) {
    const n = Number(v || 0);
    return "$" + n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  const DASH_STATUS_URL = "http://127.0.0.1:8091/api/status";

  function farmWorkerUp(s) {
    if (!s || typeof s !== "object") return false;
    const rows = Array.isArray(s.processes) ? s.processes : [];
    for (let i = 0; i < rows.length; i++) {
      const cmd = String((rows[i] && rows[i].cmd) || "");
      if (
        cmd.indexOf("run_farm_354") >= 0 ||
        cmd.indexOf("run_farm_cycles") >= 0 ||
        cmd.indexOf("pharmflow_unison_supervisor") >= 0
      ) {
        return true;
      }
    }
    return String(s.farm_owner || "").indexOf("python") === 0;
  }

  function fmtSyncTime(v) {
    if (!v) return "";
    const d = new Date(v);
    if (isNaN(d.getTime())) return "";
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  }

  // No pywebview bridge (static preview): poll the farm dashboard API so the
  // HUD shows live numbers instead of dashes. Read-only GET, short timeout.
  async function refreshHudFromDashboard() {
    const lamp = document.getElementById("hud-farm-lamp");
    try {
      const ctrl = new AbortController();
      const t = setTimeout(function () {
        ctrl.abort();
      }, 5000);
      const res = await fetch(DASH_STATUS_URL, { cache: "no-store", signal: ctrl.signal });
      clearTimeout(t);
      if (!res.ok) throw new Error("status " + res.status);
      const s = await res.json();
      const m = (s && s.mantis_today) || {};
      const running = farmWorkerUp(s);
      setHudText("hud-farm", running ? "RUN" : "OFF");
      if (lamp) lamp.className = "hud-lamp" + (running ? " run" : " err");
      applyHomeFarmState(running);
      const phones = Array.isArray(s && s.phone_rows) ? s.phone_rows.length : 0;
      setHudText("hud-phones", String(phones || 0));
      const payout = Number(m.payout_usd);
      setHudText("hud-today", fmtMoney(isFinite(payout) ? payout : 0));
      setHudText("hud-clicks", String(Number(m.clicks) || 0));
      setHudText("hud-impr", String(Number(m.impressions) || 0));
      setHudText("hud-ecpm", "$" + (Number(m.ecpm) || 0).toFixed(2));
      return true;
    } catch (_e) {
      setHudText("hud-farm", "—");
      setHudText("hud-phones", "—");
      setHudText("hud-today", "—");
      setHudText("hud-clicks", "—");
      setHudText("hud-impr", "—");
      setHudText("hud-ecpm", "—");
      if (lamp) lamp.className = "hud-lamp";
      return false;
    }
  }

  async function refreshHud() {
    const a = api();
    const lamp = document.getElementById("hud-farm-lamp");
    try {
      if (!a || typeof a.get_farm_hud !== "function") {
        const ok = await refreshHudFromDashboard();
        if (ok) markDashConnected();
        return;
      }
      const h = await a.get_farm_hud();
      if (!h) return;
      if (h.money_ok === false) {
        const ok = await refreshHudFromDashboard();
        if (ok) {
          markDashConnected();
          return;
        }
      }
      const running = !!h.running;
      setHudText("hud-farm", running ? "RUN" : "OFF");
      if (lamp) lamp.className = "hud-lamp" + (running ? " run" : " err");
      applyHomeFarmState(running);
      setHudText("hud-phones", String(h.phones_online || 0));
      if (h.money_ok === false) {
        setHudText("hud-today", "—");
        setHudText("hud-clicks", "—");
        setHudText("hud-impr", "—");
        setHudText("hud-ecpm", "—");
      } else {
        setHudText("hud-today", fmtMoney(h.revenue_today_usd));
        setHudText("hud-clicks", String(h.clicks || 0));
        setHudText("hud-impr", String(h.impressions || 0));
        setHudText("hud-ecpm", "$" + (Number(h.ecpm) || 0).toFixed(2));
      }
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

  window.PharmFlowSetup = {
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
      window.PharmFlowSetup.setBusy(false);
      const ready = payload && payload.ready === true;
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
        showToast(msg || "Phone setup finished.");
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
      window.PharmFlowSetup.setBusy(false);
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
      window.PharmFlowSetup.setBusy(false);
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

  window.PharmFlowApp = {
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

  window.PharmFlowDragon = {
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
    if (!el || el !== tipSrc) return;
    const to = e.relatedTarget;
    if (to && typeof el.contains === "function" && el.contains(to)) return;
    hideTip();
  });
  document.addEventListener("focusin", function (e) {
    const el = e.target && e.target.closest ? e.target.closest("[data-help]") : null;
    if (el) showTip(el);
  });
  document.addEventListener("focusout", function (e) {
    const to = e.relatedTarget;
    if (to && tipSrc && typeof tipSrc.contains === "function" && tipSrc.contains(to)) return;
    if (to && to.closest && to.closest("[data-help]")) return;
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
    dbg("init: waitForApi done pyApi=" + !!pyApi + " apiFn=" + typeof api());
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
    dbg("init: wireActionButtons done");
  }

  function dbg(msg) {
    try {
      const a = api();
      if (a && typeof a.debug_log === "function") a.debug_log("" + msg);
    } catch (_e) {}
    if (window.console && console.log) console.log("DECK: " + msg);
  }

  function wireActionButtons() {
    const refreshSetupBtn = document.getElementById("btn-refresh-setup");
    if (refreshSetupBtn && !refreshSetupBtn.dataset.wired) {
      refreshSetupBtn.dataset.wired = "1";
      refreshSetupBtn.addEventListener("click", function () { refreshSetup({ announce: true }); });
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
        window.PharmFlowSetup.setBusy(true);
        try {
          const res = await a.run_setup();
          if (res && res.already_running) {
            appendLog(setupLog, res.message || "A phone setup/install is already running.");
            return;
          }
          // Only async start leaves busy=true until onComplete; any failure must clear it.
          if (!res || res.error || res.ok === false || !res.started) {
            window.PharmFlowSetup.setBusy(false);
            if (res && (res.error || res.ok === false) && res.error !== "busy") {
              showBackendError(res.error || "Set up phones failed");
              appendLog(setupLog, res.error || "Set up phones failed");
            }
          }
        } catch (e) {
          appendLog(setupLog, "Setup error: " + e);
          window.PharmFlowSetup.setBusy(false);
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
            appendLog(setupLog, "Could not list live phones: " + e);
            showBackendError("Could not list live phones: " + e);
            return;
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
        window.PharmFlowSetup.setBusy(true);
        appendLog(
          setupLog,
          "\n— Installing browser: " + label + " on " + targetText + " —\n"
        );
        try {
          const res = await api.install_browser(id, serial);
          if (res && res.already_running) {
            appendLog(setupLog, res.message || "A phone setup/install is already running.");
            return;
          }
          if (!res || res.error || res.ok === false) {
            window.PharmFlowSetup.setBusy(false);
            if (res && res.error) {
              showBackendError(res.error);
              appendLog(setupLog, res.error);
            }
            return;
          }
          // Result summary arrives async via onBrowserComplete when the thread
          // finishes; this call only starts the install.
        } catch (e) {
          appendLog(setupLog, "Browser install error: " + e);
          window.PharmFlowSetup.setBusy(false);
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
          if (res && (res.error || res.ok === false)) {
            appendLog(installLog, (res.error || "Install failed") + "\n", "err");
            showBackendError(res.error || "Install failed");
          } else if (res && res.already_installed) {
            appendLog(installLog, "Install checklist is already complete. Android tools are the next step.\n");
            showToast("Install checklist is already complete — Android tools are next");
            stepComplete.install = true;
            updateNavActive();
          } else if (res && res.busy) {
            appendLog(installLog, "An install is already running — watch the log above.\n");
            showToast("Install already running");
          } else if (res && res.started && res.window_ready) {
            appendLog(installLog, (res.message || "Opened the install wizard — watch that window.") + "\n");
            showToast(res.message || "Opened the install wizard — watch that window");
          } else if (res && res.started) {
            appendLog(installLog, (res.message || "Install process started. The window is not up yet.") + "\n");
            showToast(res.message || "Install process started. The window is not up yet.");
          }
          if (res && res.started) {
            const poll = setInterval(async function () {
              await refreshPrereqs();
              if (stepComplete.install) clearInterval(poll);
            }, 4000);
            setTimeout(function () {
              clearInterval(poll);
            }, 300000);
          }
          if (!(res && (res.error || res.ok === false || res.already_installed || res.busy || res.started))) {
            appendLog(installLog, "Install did not start.\n", "err");
            showBackendError((res && res.message) || "Install did not start");
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
        if (btnAndroid.dataset.busy === "1") return;
        const androidLog = document.getElementById("android-log");
        const androidLed = document.getElementById("android-led");
        const androidLabel = document.getElementById("android-status-label");
        if (androidLog) androidLog.textContent = "";
        if (androidLed) androidLed.classList.remove("on");
        if (androidLabel) androidLabel.textContent = "Installing…";
        btnAndroid.dataset.busy = "1";
        btnAndroid.disabled = true;
        try {
          const res = await callApi("Android install", function (a) {
            return a.run_android_install();
          });
          if (androidLog && res && res.log) appendLog(androidLog, res.log);
          if (androidLog && res && res.message) appendLog(androidLog, res.message);
          if (res && (res.error || res.ok === false)) {
            showBackendError(res.error || "Android install failed");
            if (androidLabel) androidLabel.textContent = "Install failed";
            showToast(res.error || "Android install failed");
          } else if (res && res.already_installed) {
            if (androidLabel) androidLabel.textContent = "Ready";
            showToast(res.message || "Android SDK already found");
            await refreshAndroid();
          } else if (res && res.started && res.window_ready) {
            showToast(res.message || "Opened the Android tools wizard — watch that window");
          } else if (res && res.started) {
            showToast(res.message || "Android tools process started. The window is not up yet.");
            await refreshAndroid();
          } else {
            showBackendError((res && res.message) || "Android install did not start");
            if (androidLabel) androidLabel.textContent = "Install failed";
          }
        } catch (e) {
          if (androidLog) appendLog(androidLog, "Android install failed: " + e);
          if (androidLabel) androidLabel.textContent = "Install failed";
        } finally {
          btnAndroid.dataset.busy = "0";
          btnAndroid.disabled = false;
        }
      });
    }

    const btnRefreshCaps = document.getElementById("btn-refresh-caps");
    if (btnRefreshCaps && !btnRefreshCaps.dataset.wired) {
      btnRefreshCaps.dataset.wired = "1";
      btnRefreshCaps.addEventListener("click", function () { refreshMachineCaps({ announce: true }); });
    }

    async function startTestPhoneSpin() {
      const res = await callApi("Spin up test phone", function (a) {
        return a.spin_up_test_phone();
      });
      if (res && (res.error || res.ok === false)) {
        showBackendError((res && res.error) || "Test phone spin-up failed");
        return;
      }
      if (res && res.busy) {
        const msg = res.message || "A test phone is already coming up";
        showToast(msg);
        if (bootLog) appendLog(bootLog, msg, "warn");
        return;
      }
      if (!(res && res.started)) {
        const msg = (res && res.message) || "Test phone spin-up did not start";
        showToast(msg);
        if (bootLog) appendLog(bootLog, msg, "warn");
        return;
      }
      const startMsg = res.message || "Spinning up one test phone — watch the Test log";
      showToast(startMsg, true);
      if (bootLog) appendLog(bootLog, startMsg);
      const st = await pollNamedStatus(
        "test_phone_status",
        "Test phone status is not available in this build"
      );
      if (!st || st.error || st.ok === false) {
        const err = (st && (st.error || st.message)) || "Test phone spin-up failed";
        showBackendError(err);
        if (bootLog) appendLog(bootLog, err, "err");
        return;
      }
      const done = st.message || "Test phone is ready";
      showToast(done);
      if (bootLog) appendLog(bootLog, done);
    }

    const btnSpin = document.getElementById("btn-spin-test-phone");
    if (btnSpin && !btnSpin.dataset.wired) {
      btnSpin.dataset.wired = "1";
      btnSpin.addEventListener("click", async function () {
        try {
          await startTestPhoneSpin();
        } catch (_e) {
          /* banner shown */
        }
      });
    }

    const btnBootAll = document.getElementById("btn-boot-all");
    if (btnBootAll && !btnBootAll.dataset.wired) {
      btnBootAll.dataset.wired = "1";
      btnBootAll.addEventListener("click", function () {
        startBootAll(btnBootAll);
      });
    }

    const btnBootAllHome = document.getElementById("btn-boot-all-home");
    if (btnBootAllHome && !btnBootAllHome.dataset.wired) {
      btnBootAllHome.dataset.wired = "1";
      btnBootAllHome.addEventListener("click", function () {
        startBootAll(btnBootAllHome);
      });
    }

    // Long-running actions opt into beginAction at their own handler so menu,
    // navigation, help, and toggle buttons are never globally disabled.

    // Home quick-start: Start farm / Farm running → dashboard / Stop farm.
    const btnStartHome = document.getElementById("btn-start-farm-home");
    const btnStopHome = document.getElementById("btn-stop-farm-home");

    async function openFarmDash() {
      try {
        const res = await callApi("Farm dashboard", function (a) {
          if (!a.open_farm_dashboard) {
            return {
              ok: false,
              opened: false,
              error: "Farm dashboard open is not available in this build.",
            };
          }
          return a.open_farm_dashboard();
        });
        if (!res || res.error || res.ok === false || res.opened !== true) {
          showBackendError((res && res.error) || "Farm dashboard did not open in the browser");
          return;
        }
        if (!res.dashboard || String(res.dashboard).indexOf(":8091") === -1) {
          showBackendError(
            "That did not open the farm dashboard at 127.0.0.1:8091. Use Open control dashboard for the wizard server."
          );
          return;
        }
        showToast("Farm dashboard opened in your browser");
      } catch (_e) {
        /* banner shown */
      }
    }

    async function openControlDash() {
      try {
        const res = await callApi("Control dashboard", function (a) {
          return a.open_dashboard();
        });
        if (!res || res.error || res.ok === false || res.opened !== true) {
          showBackendError((res && res.error) || "Control dashboard did not open in the browser");
          return;
        }
        showToast("Control dashboard opened in your browser");
      } catch (_e) {
        /* banner shown */
      }
    }

    if (btnStartHome && !btnStartHome.dataset.wired) {
      btnStartHome.dataset.wired = "1";
      btnStartHome.addEventListener("click", async function () {
        if (btnStartHome.dataset.mode === "running") {
          openFarmDash();
          return;
        }
        try {
          beginAction(btnStartHome, "Starting farm…");
          appendLog(goLog, "[farm] Start requested — preparing the farm stack…", "log-line-accent");
          showView("go", { animate: true });
          const res = await callApi("Start farm", function (a) {
            return a.start_farm();
          });
          if (res && res.running && res.dashboard_ready === true) {
            applyHomeFarmState(true);
            openFarmDash();
            return;
          }
          if (res && (res.error || res.ok === false)) {
            showBackendError((res && res.error) || "Start farm failed");
            return;
          }
          if (res && res.starting) {
            appendLog(goLog, "[farm] " + (res.message || "Farm startup is running in the background.\n"), "log-line-accent");
            if (runStatus) runStatus.textContent = "Starting farm… watch the Run log";
            showToast("Farm startup is running — watch the Run log", true);
            pollFarmStart(180000);
          } else if (res && res.started && res.running && res.dashboard_ready === true) {
            applyHomeFarmState(true);
            showToast("Farm worker is running");
          } else {
            showBackendError((res && (res.error || res.message)) || "Farm start did not begin — read the Run log");
          }
        } catch (_e) {
          /* banner shown */
        }
      });
    }

    if (btnStopHome && !btnStopHome.dataset.wired) {
      btnStopHome.dataset.wired = "1";
      btnStopHome.addEventListener("click", async function () {
        try {
          const res = await callApi("Stop farm", function (a) {
            return a.stop_farm();
          });
          if (res && (res.error || res.ok === false || res.running)) {
            showBackendError((res && res.error) || "Stop farm failed");
            if (res && res.running) applyHomeFarmState(true);
            return;
          }
          applyHomeFarmState(false);
          showToast((res && res.message) || (res && res.stopped ? "Farm stopped" : "Farm is already stopped"));
        } catch (_e) {
          /* banner shown */
        }
      });
    }

    const btnDashHome = document.getElementById("btn-open-dash-home");
    if (btnDashHome && !btnDashHome.dataset.wired) {
      btnDashHome.dataset.wired = "1";
      btnDashHome.addEventListener("click", openFarmDash);
    }

    const btnHealthHome = document.getElementById("btn-health-home");
    if (btnHealthHome && !btnHealthHome.dataset.wired) {
      btnHealthHome.dataset.wired = "1";
      btnHealthHome.addEventListener("click", function () {
        showView("health", { animate: true });
        refreshHealth();
      });
    }

    const btnHealthRefresh = document.getElementById("btn-health-refresh");
    if (btnHealthRefresh && !btnHealthRefresh.dataset.wired) {
      btnHealthRefresh.dataset.wired = "1";
      btnHealthRefresh.addEventListener("click", refreshHealth);
    }

    const btnSpinHome = document.getElementById("btn-spin-test-phone-home");
    if (btnSpinHome && !btnSpinHome.dataset.wired) {
      btnSpinHome.dataset.wired = "1";
      btnSpinHome.addEventListener("click", async function () {
        try {
          showView("boot", { animate: true });
          await startTestPhoneSpin();
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
            const saved = await callApi("Save site", function (a) {
              return a.save_site_url(url);
            });
            if (!saved || saved.error || saved.ok === false) {
              showBackendError((saved && saved.error) || "Could not save the site URL");
              return;
            }
          }
          const res = await callApi("Test URL", function (a) {
            return a.run_test_url(url || "");
          });
          if (res && (res.error || res.ok === false)) {
            showBackendError((res && res.error) || "Test URL failed");
            if (bootLog) appendLog(bootLog, (res && res.error) || "Test URL failed");
            return;
          }
          const host = url ? url.replace(/^https?:\/\//, "").split("/")[0] : "site";
          const opened = res && typeof res.opened === "number" ? res.opened : 0;
          if (!opened) {
            showBackendError("No phone opened the site");
            return;
          }
          showToast("Opened " + host + " on " + opened + " phone(s) — check the phone screens");
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
          if (!res || res.error || res.ok === false) {
            showBackendError((res && res.error) || "Save site failed");
            showToast((res && res.error) || "Could not save site URL");
            return;
          }
          if (res.saved !== true) {
            showBackendError("Site URL was not saved");
            return;
          }
          showToast("Saved " + (res.host || url));
          await refreshBoot();
        } catch (_e) {
          /* banner shown */
        }
      });
    }

    const btnEarnPreview = document.getElementById("btn-earn-preview");
    if (btnEarnPreview && !btnEarnPreview.dataset.wired) {
      btnEarnPreview.dataset.wired = "1";
      btnEarnPreview.addEventListener("click", async function () {
        const status = document.getElementById("earn-plan-status");
        try {
          const res = await callApi("Preview mix", function (a) {
            return a.preview_earn_plan(earnParamsFromForm());
          });
          if (!res || res.ok === false) {
            if (status) status.textContent = (res && res.error) || "Mix was not computed.";
            showToast((res && res.error) || "Mix was not computed");
            return;
          }
          if (status) status.textContent = earnStatusText(res);
          showToast("Preview only — Save mix to use these counts");
        } catch (_e) {
          /* banner shown */
        }
      });
    }
    const btnEarnSave = document.getElementById("btn-earn-save");
    if (btnEarnSave && !btnEarnSave.dataset.wired) {
      btnEarnSave.dataset.wired = "1";
      btnEarnSave.addEventListener("click", async function () {
        const status = document.getElementById("earn-plan-status");
        try {
          const res = await callApi("Save mix", function (a) {
            return a.save_earn_plan(earnParamsFromForm());
          });
          if (!res || res.ok === false || res.saved !== true) {
            if (status) status.textContent = (res && res.error) || "Mix was not saved.";
            showToast((res && res.error) || "Mix was not saved");
            return;
          }
          fillEarnForm(res);
          if (status) status.textContent = earnStatusText(res);
          const groupsMsg =
            res.groups && res.groups.updated
              ? " Updated " + res.groups.updated + " phone hit(s)/day in Groups."
              : "";
          showToast(
            (res.settings_warning ? "Mix saved with a warning. " : "Saved mix. ") +
              "Start farm uses PATHS/ads from this plan." +
              groupsMsg
          );
        } catch (_e) {
          /* banner shown */
        }
      });
    }

    const btnEditSeq = document.getElementById("btn-edit-sequence");
    if (btnEditSeq && !btnEditSeq.dataset.wired) {
      btnEditSeq.dataset.wired = "1";
      btnEditSeq.addEventListener("click", function () {
        showView("builder", { animate: true });
        refreshBuilder();
      });
    }
    const btnOpenBuilder = document.getElementById("btn-open-builder");
    if (btnOpenBuilder && !btnOpenBuilder.dataset.wired) {
      btnOpenBuilder.dataset.wired = "1";
      btnOpenBuilder.addEventListener("click", function () {
        showView("builder", { animate: true });
        refreshBuilder();
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
            if (pick && pick.error) {
              showBackendError(pick.error);
              return;
            }
            if (pick && pick.cancelled) return;
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
          if (res && res.ok && (res.count || 0) > 0) {
            showToast("Loaded " + res.count + " step(s)");
            await refreshSteps();
            await refreshBuilder();
          } else {
            showBackendError((res && res.message) || "Load sequence failed");
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
            if (pick && pick.error) {
              showBackendError(pick.error);
              return;
            }
            if (pick && pick.cancelled) return;
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
          if (res && res.ok && res.saved === true && (res.count || 0) > 0) showToast("Sequence saved");
          else showBackendError((res && (res.error || res.message)) || "Save sequence failed");
        } catch (e) {
          showBackendError((e && e.message) || "Save sequence failed");
        }
      });
    }

    const btnManageGroups = document.getElementById("btn-manage-groups");
    if (btnManageGroups && !btnManageGroups.dataset.wired) {
      btnManageGroups.dataset.wired = "1";
      btnManageGroups.addEventListener("click", function () {
        showView("teams", { animate: true });
        refreshTeams();
      });
    }

    const btnAddGroup = document.getElementById("btn-add-group");
    if (btnAddGroup && !btnAddGroup.dataset.wired) {
      btnAddGroup.dataset.wired = "1";
      btnAddGroup.addEventListener("click", async function () {
        if (groupMutationBusy) return;
        groupMutationBusy = true;
        btnAddGroup.disabled = true;
        try {
          const res = await callApi("Add group", function (a) {
            if (typeof a.cursor_add_group === "function") return a.cursor_add_group();
            return a.run_add_group();
          });
          if (!res || res.error || res.ok !== true || res.saved !== true) {
            showBackendError((res && (res.error || res.message)) || "Add group failed");
            return;
          }
          if (res) {
            const sumEl = document.getElementById("teams-summary");
            if (sumEl) sumEl.textContent = groupsSummaryText(res);
            renderGroupsList(res);
            showToast("Group added");
            stepComplete.teams = true;
            updateNavActive();
          }
        } catch (_e) {
          /* banner shown */
        } finally {
          groupMutationBusy = false;
          btnAddGroup.disabled = false;
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
          if (!res || res.error || res.ok !== true || res.saved !== true || !(res.count > 0)) {
            showBackendError((res && (res.error || res.message)) || "Natural timing failed");
            return;
          }
          showToast(res.message || ("Natural timing applied to " + res.count + " sequence(s)"));
          await refreshTeams();
        } catch (_e) {
          /* banner shown */
        }
      });
    }
    const btnDashTeams = document.getElementById("btn-open-dash-teams");
    if (btnDashTeams && !btnDashTeams.dataset.wired) {
      btnDashTeams.dataset.wired = "1";
      btnDashTeams.addEventListener("click", openFarmDash);
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
          if (res && (res.error || res.ok === false)) {
            showBackendError((res && res.error) || "Start service failed");
            return;
          }
          if (res && res.starting) {
            showToast("Starting service — watch the Run log", true);
            if (runStatus) runStatus.textContent = "Starting service…";
            const st = await pollServiceStart(180000);
            if (!st || st.error || st.ok === false || !st.ready) {
              showBackendError((st && st.error) || "Start service failed");
              return;
            }
            if (st.dashboard_opened) {
              showToast("Service started — control dashboard opened");
              return;
            }
            showToast("Service is up — opening the control dashboard");
            await openDashboardWhenReady();
            return;
          }
          if (res && res.ready) {
            showToast("Service started");
            await openDashboardWhenReady();
            return;
          }
          showBackendError((res && (res.error || res.message)) || "Start service did not begin — read the Run log");
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
        if (runActionBusy) return;
        const a = requireApi("Run groups");
        if (!a) return;
        runActionBusy = true;
        btnRun.disabled = true;
        setBusy(runLed, runStatus, true);
        try {
          const res = await a.run_all_groups();
          if (res && (res.error || res.ok === false)) {
            showBackendError((res && res.error) || "Run groups failed");
            return;
          }
          if (res && res.starting) {
            showToast("Running groups — watch the Run log", true);
            if (runStatus) runStatus.textContent = "Running groups…";
            const st = await pollGroupsRun();
            if (!st || st.error || st.ok === false || !st.started) {
              showBackendError((st && st.error) || "Run groups failed");
              return;
            }
            showToast((st && st.message) || "Groups accepted — watch the Run log");
            return;
          }
          showBackendError((res && (res.error || res.message)) || "Run groups did not start — read the Run log");
        } catch (e) {
          showBackendError(String(e));
        } finally {
          runActionBusy = false;
          btnRun.disabled = false;
          setBusy(runLed, runStatus, false);
        }
      });
    }

    // Groups list: rename (Save) + Remove via cursor_* (no Tk window).
    const groupsList = document.getElementById("groups-list");
    if (groupsList && !groupsList.dataset.removeWired) {
      groupsList.dataset.removeWired = "1";
      groupsList.addEventListener("click", async function (ev) {
        const renameBtn = ev.target.closest("[data-rename-group]");
        if (renameBtn) {
          const idx = parseInt(renameBtn.getAttribute("data-rename-group"), 10);
          if (Number.isNaN(idx)) return;
          const row = renameBtn.closest("li");
          const input = row && row.querySelector("[data-group-name]");
          const name = input ? String(input.value || "").trim() : "";
          const a = api();
          if (!a || typeof a.cursor_rename_group !== "function") {
            showBackendError("Rename group unavailable — update the app.");
            return;
          }
          try {
            const res = await a.cursor_rename_group(idx, name);
            if (!res || res.error || res.ok !== true || res.saved !== true) {
              showBackendError((res && (res.error || res.message)) || "Rename group failed");
              return;
            }
            const sumEl = document.getElementById("teams-summary");
            if (sumEl) sumEl.textContent = groupsSummaryText(res);
            renderGroupsList(res);
            showToast("Group renamed");
          } catch (_e) {
            /* banner shown */
          }
          return;
        }
        const btn = ev.target.closest("[data-remove-group]");
        if (!btn) return;
        const idx = parseInt(btn.getAttribute("data-remove-group"), 10);
        if (Number.isNaN(idx)) return;
        const a = api();
        const removeFn =
          a && typeof a.cursor_remove_group === "function"
            ? a.cursor_remove_group.bind(a)
            : a && typeof a.remove_group === "function"
            ? a.remove_group.bind(a)
            : null;
        if (!removeFn) {
          showBackendError("Remove group unavailable — update the app.");
          return;
        }
        try {
          const res = await removeFn(idx);
          if (!res || res.error || res.ok !== true || res.saved !== true) {
            showBackendError((res && (res.error || res.message)) || "Remove group failed");
            return;
          }
          const sumEl = document.getElementById("teams-summary");
          if (sumEl) sumEl.textContent = groupsSummaryText(res);
          renderGroupsList(res);
          showToast("Group removed" + (res && res.removed ? ": " + res.removed : ""));
        } catch (_e) {
          /* banner shown */
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
          if (res && (res.error || res.ok === false)) {
            showBackendError((res && res.error) || "Start automation failed");
            return;
          }
          if (res && res.starting) {
            showToast("Starting automation — watch the Run log", true);
            if (runStatus) runStatus.textContent = "Starting automation…";
            const st = await pollGroupsRun();
            if (!st || st.error || st.ok === false || !st.started) {
              showBackendError((st && st.error) || "Start automation failed");
              return;
            }
            showToast((st && st.message) || "Automation accepted — watch the Run log");
            return;
          }
          showBackendError((res && (res.error || res.message)) || "Start automation did not begin — read the Run log");
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
          if (!res) return;
          if (res.error || res.ok === false) {
            showBackendError(res.error || "Fix internet failed");
            showToast(res.error || "Could not restore phone internet");
            return;
          }
          if (!res.message) {
            showBackendError("Fix internet did not confirm a phone exit");
            return;
          }
          showToast(res.message);
        } catch (_e) {
          /* banner shown */
        }
      });
    }

    const openDash = document.getElementById("btn-open-dash");
    if (openDash && !openDash.dataset.wired) {
      openDash.dataset.wired = "1";
      openDash.addEventListener("click", openControlDash);
    }

    const btnCloudSetup = document.getElementById("btn-cloud-setup");
    if (btnCloudSetup && !btnCloudSetup.dataset.wired) {
      btnCloudSetup.dataset.wired = "1";
      btnCloudSetup.addEventListener("click", async function () {
        try {
          const host = window.prompt("Cloud instance IP (e.g. 100.x.x.x):", "");
          if (host == null || !host.trim()) return;
          const countStr = window.prompt("Number of instances:", "");
          const count = parseInt(countStr || "", 10);
          if (!count || count < 1) {
            showToast("Enter a valid instance count");
            return;
          }
          const a = requireApi("Cloud setup");
          if (!a || !a.cloud_phone_setup) {
            showBackendError("Cloud setup is not available in this build");
            return;
          }
          const res = await a.cloud_phone_setup(host.trim(), count);
          if (!res || res.error || res.ok === false) {
            showBackendError((res && res.error) || "Cloud setup failed");
            return;
          }
          showView("go");
          if (res.already_running) {
            showToast(res.message || "A cloud command is already running — watch the Run log");
            return;
          }
          showToast((res && res.message) || "Cloud setup started — watch the Run log", true);
          const st = await pollNamedStatus("cloud_command_status", "Cloud status is not available in this build");
          if (!st || st.error || st.ok === false) {
            showBackendError((st && (st.error || st.message)) || "Cloud setup failed");
            return;
          }
          showToast(st.message || "Cloud setup finished");
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
          if (!res || res.error || res.ok === false) {
            showBackendError((res && res.error) || "Cloud status failed");
            return;
          }
          showView("go");
          if (res.already_running) {
            showToast(res.message || "A cloud command is already running — watch the Run log");
            return;
          }
          showToast("Cloud status started — watch the Run log", true);
          const st = await pollNamedStatus("cloud_command_status", "Cloud status is not available in this build");
          if (!st || st.error || st.ok === false) {
            showBackendError((st && (st.error || st.message)) || "Cloud status failed");
            return;
          }
          showToast(st.message || "Cloud status finished");
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
          showView("go");
          if (!res || res.error || res.ok === false || !res.message) {
            showBackendError((res && (res.error || res.message)) || "Agent status returned no result");
            return;
          }
          showToast(res.message);
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
          if (!res || res.error || res.ok === false) {
            showBackendError((res && res.error) || "Agent settings were not saved");
            return;
          }
          if (res.saved !== true) {
            showBackendError("Agent settings were not saved on disk");
            return;
          }
          if (!res.configured) {
            showToast("Settings written, but no API key is stored — the agent is not ready");
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
          const res = await a.run_cloud_agent(goal.trim(), allowApply);
          if (!res || res.error || res.ok === false) {
            showBackendError((res && res.error) || "Cloud agent failed");
            return;
          }
          showView("go");
          if (res.already_running) {
            showToast(res.message || "Cloud agent is already running — watch the Run log");
            return;
          }
          showToast((res && res.message) || "Cloud agent started — watch the Run log", true);
          const st = await pollNamedStatus("cloud_agent_status", "Cloud agent status is not available in this build");
          if (!st || st.error || st.ok === false) {
            showBackendError((st && (st.error || st.message)) || "Cloud agent failed");
            return;
          }
          showToast(st.message || "Cloud agent finished");
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

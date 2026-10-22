(() => {
  "use strict";

  const state = {
    snapshot: null,
    catalog: null,
    publicConfig: null,
    activeView: "overview",
    token: localStorage.getItem("plumbox_token") || "",
    unlocked: false,
    websocket: null,
    historyHours: 24,
    historyRows: [],
    overviewHistory: [],
    overviewHistoryRevision: 0,
    alarmRows: [],
    fuelToday: null,
    overviewExtrasLoading: false,
    overviewExtrasLoadedAt: 0,
    sparks: {},
    pendingWrite: null,
    parameterDrafts: new Map(),
    hiddenSeries: new Set(),
    lastSnapshotAt: 0,
    lastWebsocketAt: 0,
    authExpired: false,
    authCheckInFlight: null,
    authCheckedAt: 0,
    pinExpiresAt: 0,
    role: "readonly",
    snapshotFetchInFlight: null,
    initialized: false,
    uiReady: false,
    bootstrapAttempt: 0,
    recoveryInFlight: null,
    websocketReconnectTimer: null,
  };
  try {
    JSON.parse(localStorage.getItem("plumbox_hidden_series") || "[]").forEach((key) => state.hiddenSeries.add(key));
  } catch { /* uszkodzony zapis — startujemy z pełną legendą */ }

  const $ = (id) => document.getElementById(id);
  const content = $("content");

  // Kolory wykresów pochodzą ze zmiennych CSS motywu (dark/light mają osobne,
  // zwalidowane palety). Fallback = paleta dark, gdyby zmiennej brakowało.
  const cssColor = (name, fallback) =>
    (getComputedStyle(document.documentElement).getPropertyValue(name) || "").trim() || fallback;
  const chartSeries = () => [
    ["heating_temp", cssColor("--chart-s1", "#e8563a"), "Kocioł"],
    ["return_temp", cssColor("--chart-s2", "#22a06b"), "Powrót"],
    ["water_heater_temp", cssColor("--chart-s3", "#4a8fe8"), "CWU"],
    ["mixer_temp", cssColor("--chart-s4", "#bb8b16"), "Mieszacz"],
  ];

  const overviewChartSeries = () => chartSeries().filter(([key]) => key !== "return_temp");

  const appBase = new URL(location.href);
  if (!appBase.pathname.endsWith("/")) appBase.pathname += "/";
  appBase.search = "";
  appBase.hash = "";

  const titles = {
    communication: "KOMUNIKACJA I MQTT",
    users: "UŻYTKOWNICY",
    account: "MOJE KONTO",
    overview: "PODGLĄD KOTŁA",
    installation: "SCHEMAT INSTALACJI",
    heating: "CO I KOCIOŁ",
    water_heater: "CIEPŁA WODA UŻYTKOWA",
    summer: "LATO / ZIMA",
    mixer: "MIESZACZ",
    fuel_calibration: "PRACA",
    boiler_powers: "MOCE 100/50/30%",
    hysteresis: "H1 / H2 I HISTEREZA",
    airflow: "KOREKTY NADMUCHU",
    kindling: "ROZPALANIE I STABILIZACJA",
    supervision: "NADZÓR",
    burning_off: "WYGASZANIE",
    cleaning: "CZYSZCZENIE",
    protections: "ZABEZPIECZENIA",
    alarms: "ALARMY",
    history: "HISTORIA TEMPERATUR",
    statistics: "STATYSTYKI CYKLI",
    notifications: "ALERTY NA TELEFON",
    all: "WSZYSTKIE PARAMETRY",
    system: "STAN SYSTEMU",
    audit: "DZIENNIK ZMIAN",
  };

  const filteredViews = {
    fuel_calibration: ["min_fan_power", "max_fuel_flow", "fuel_calorific_value", "fuel_detection_time"],
    boiler_powers: ["boiler_power_100", "boiler_power_50", "boiler_power_30"],
    hysteresis: ["h1_hysteresis", "h2_hysteresis", "heating_hysteresis"],
    airflow: ["airflow_correction_100", "airflow_correction_50", "airflow_correction_30"],
  };
  const liveParameterViews = new Set([
    "heating", "water_heater", "summer", "mixer", "kindling", "supervision",
    "burning_off", "cleaning", "protections", ...Object.keys(filteredViews),
  ]);
  // V3 Native. Ustawienie false przywraca niezmieniony wariant iframe.
  const USE_NATIVE_SYSTEM_V3 = true;

  function clearControlAccess({ forgetToken = false } = {}) {
    state.unlocked = false;
    state.pinExpiresAt = 0;
    state.pendingWrite = null;
    if (forgetToken) {
      state.token = "";
      localStorage.removeItem("plumbox_token");
    }
    $("confirmDialog")?.close();
    document.querySelectorAll(".parameter-card input, .parameter-card select, .parameter-card button").forEach((node) => { node.disabled = true; });
    updateLockButton();
  }

  function requireRelogin() {
    if (state.authExpired) return;
    state.authExpired = true;
    clearControlAccess({ forgetToken: true });
    $("unlockDialog")?.close();
    if (state.websocketReconnectTimer) clearTimeout(state.websocketReconnectTimer);
    state.websocketReconnectTimer = null;
    const socket = state.websocket;
    state.websocket = null;
    try { socket?.close(); } catch { /* zamykane WebView */ }
    $("loginAgainLink").href = new URL("login", appBase).href;
    $("sessionExpiredDialog").addEventListener("cancel", (event) => event.preventDefault(), { once: true });
    $("sessionExpiredDialog").showModal();
  }

  async function api(path, options = {}) {
    if (state.authExpired) throw Object.assign(new Error("Sesja wygasła. Zaloguj się ponownie."), { code: "auth_required" });
    const { timeoutMs = options.method && options.method !== "GET" ? 30000 : 8000, ...requestOptions } = options;
    const controller = new AbortController();
    const upstream = requestOptions.signal;
    const abort = () => controller.abort();
    if (upstream?.aborted) abort();
    else upstream?.addEventListener("abort", abort, { once: true });
    const timeout = setTimeout(abort, timeoutMs);
    try {
      const headers = new Headers(requestOptions.headers || {});
      if (state.token) headers.set("X-Plumbox-Token", state.token);
      if (requestOptions.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
      const response = await fetch(new URL(path.replace(/^\//, ""), appBase), { ...requestOptions, headers, signal: controller.signal });
      if (response.ok && !response.headers.get("content-type")?.includes("application/json")) {
        if (response.redirected) requireRelogin();
        throw new Error("Serwer nie zwrócił danych panelu. Ponawiam połączenie.");
      }
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        if (response.status === 401) {
          if (payload.code === "auth_required" || payload.detail === "Zaloguj się do PlumBox.") requireRelogin();
          else if (path !== "/api/auth/unlock") clearControlAccess({ forgetToken: true });
        }
        throw Object.assign(new Error(payload.detail || `Błąd HTTP ${response.status}`), { status: response.status, code: payload.code });
      }
      return payload;
    } catch (error) {
      if (error.name === "AbortError") {
        const write = requestOptions.method && requestOptions.method !== "GET";
        throw new Error(write ? "Nie otrzymano potwierdzenia operacji. Sprawdź odczyt przed ponownym zapisem." : "Przekroczono czas połączenia. Spróbuj ponownie.");
      }
      throw error;
    } finally {
      clearTimeout(timeout);
      upstream?.removeEventListener("abort", abort);
    }
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function fmt(value, decimals = 1) {
    if (value === null || value === undefined || value === "") return "—";
    if (typeof value === "number") {
      if (Number.isInteger(value)) return String(value);
      return value.toFixed(decimals).replace(".", ",");
    }
    return String(value);
  }

  function finiteNumber(value) {
    if (value === null || value === undefined || value === "") return null;
    const number = Number(value);
    return Number.isFinite(number) ? number : null;
  }

  function booleanValue(value) {
    if (value === null || value === undefined) return null;
    if (value === true || value === false) return value;
    if (value === 1 || value === 0) return value === 1;
    const normalized = String(value).trim().toLowerCase();
    if (["1", "true", "on"].includes(normalized)) return true;
    if (["0", "false", "off"].includes(normalized)) return false;
    return null;
  }

  function isEnabledValue(value) {
    return booleanValue(value) === true;
  }

  function optionLabel(parameter, value) {
    const key = String(typeof value === "number" && Number.isInteger(value) ? value : value);
    return parameter?.options?.[key] ?? null;
  }

  function parameterValueLabel(parameter, value = undefined) {
    if (!parameter) return "—";
    const actual = value === undefined ? parameter.value : value;

    // ecomax_control jest poleceniem start/stop, ale jego wartość logiczna nie
    // opisuje fazy procesu. Na kafelku bieżącego stanu pokazujemy więc stan
    // sterownika (np. ROZPALANIE/WYGASZANIE), zachowując bool dla opisu komendy.
    if (parameter.name === "ecomax_control" && value === undefined) {
      const controllerPhase = val("state_label", null);
      if (controllerPhase !== null && controllerPhase !== undefined && controllerPhase !== "") {
        return String(controllerPhase);
      }
    }

    if (parameter.kind === "select") {
      return optionLabel(parameter, actual)
        || (value === undefined ? parameter.selected_label : null)
        || fmt(actual, 2);
    }

    if (parameter.kind === "switch") {
      const enabled = booleanValue(actual);
      if (enabled === null) return "Brak rozpoznania";
      return enabled
        ? (parameter.on_label || "Włączony")
        : (parameter.off_label || "Wyłączony");
    }

    const formatted = fmt(actual, 2);
    return parameter.unit ? `${formatted} ${parameter.unit}` : formatted;
  }

  function parameterRangeLabel(parameter) {
    if (parameter.kind === "select") {
      const labels = Object.values(parameter.options || {});
      return labels.length ? `Dostępne: ${labels.join(" / ")}` : "Wybór trybu";
    }

    if (parameter.kind === "switch") {
      return `Dostępne: ${parameter.off_label || "Wyłączony"} / ${parameter.on_label || "Włączony"}`;
    }

    return `Zakres: ${fmt(parameter.min, 2)} – ${fmt(parameter.max, 2)} ${parameter.unit || ""} • krok ${parameter.step}`;
  }

  function val(key, fallback = "—") {
    const value = state.snapshot?.values?.[key];
    return value === null || value === undefined ? fallback : value;
  }

  function clamp(value, min = 0, max = 100) {
    return Math.max(min, Math.min(max, Number(value) || 0));
  }

  function formatDate(value) {
    if (!value) return "—";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return date.toLocaleString("pl-PL");
  }

  function toast(message, type = "") {
    const node = document.createElement("div");
    node.className = `toast ${type}`;
    node.textContent = message;
    $("toastContainer").appendChild(node);
    setTimeout(() => node.remove(), 4200);
  }

  function updateClock() {
    const now = new Date();
    $("clockTime").textContent = now.toLocaleTimeString("pl-PL");
    $("clockDate").textContent = now.toLocaleDateString("pl-PL");
  }

  // Trzy motywy jako przełącznik segmentowy; OLED korzysta z ciemnozielonej palety.
  const THEME_ORDER = ["dark", "light", "oled"];
  const THEME_COLORS = { dark: "#0b1017", light: "#eef1f6", oled: "#07110f" };

  function updateThemeSwitch() {
    const theme = document.documentElement.dataset.theme || "dark";
    document.querySelectorAll("[data-theme-set]").forEach((button) => {
      button.classList.toggle("active", button.dataset.themeSet === theme);
    });
    const colorMeta = document.querySelector('meta[name="theme-color"]');
    if (colorMeta) colorMeta.setAttribute("content", THEME_COLORS[theme] || THEME_COLORS.dark);
  }

  function applyTheme(theme) {
    const normalized = THEME_ORDER.includes(theme) ? theme : "dark";
    document.documentElement.dataset.theme = normalized;
    localStorage.setItem("plumbox_theme", normalized);
    updateThemeSwitch();
    // Wykresy canvas i sparkline'y mają kolory motywu wpisane przy rysowaniu,
    // więc po przełączeniu trzeba je narysować ponownie.
    if (state.snapshot) render();
  }

  function initTheme() {
    const saved = localStorage.getItem("plumbox_theme");
    const preferred = window.matchMedia?.("(prefers-color-scheme: light)")?.matches ? "light" : "dark";
    applyTheme(saved || preferred);
  }

  function setConnectionUi() {
    const connected = Boolean(state.snapshot?.connected);
    const simulated = Boolean(state.snapshot?.simulation);
    const badge = $("connectionBadge");
    badge.classList.toggle("offline", !connected);
    badge.querySelector("strong").textContent = connected ? (simulated ? "SYMULACJA" : "ONLINE") : "OFFLINE";
    $("offlineBanner").classList.toggle("hidden", connected);

    const hardware = state.snapshot?.hardware_profile || {};
    const modelBadge = $("modelSourceBadge");
    const modelStatus = connected ? (hardware.status || "inactive") : "offline";
    const modelName = String(hardware.product_id) === "2" ? "860P4-LZ" : `ID ${hardware.product_id ?? "—"}`;
    const shortLabels = {
      verified: `MODEL: ${modelName}`,
      fixed_fallback: "MODEL: FIXED",
      foreign: `MODEL: ${modelName}`,
      inactive: "MODEL: NIEZNANY",
      simulation: "MODEL: SYMULATOR",
      offline: "MODEL: —",
    };
    modelBadge.className = `model-source-pill ${modelStatus}`;
    modelBadge.querySelector("strong").textContent = shortLabels[modelStatus] || "MODEL: NIEZNANY";
    modelBadge.title = hardware.label || "Źródło identyfikacji modelu";


  }

  function updateLockButton() {
    const label = state.unlocked ? "Sterowanie odblokowane" : "Odblokuj sterowanie";
    for (const id of ["lockButton", "topLockButton"]) {
      const button = $(id);
      if (!button) continue;
      if (id === "topLockButton") {
        const shackle = state.unlocked ? "M8 10V7a4 4 0 0 1 8 0" : "M8 10V7a4 4 0 0 1 8 0v3";
        button.innerHTML = `<svg class="admin-lock-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><rect x="5" y="10" width="14" height="11" rx="2"/><path d="${shackle}"/></svg><span>${state.role === "admin" ? "Admin" : "PIN"}</span>`;
      } else {
        button.textContent = `${state.unlocked ? "🔓" : "🔒"} ${label}`;
      }
      button.classList.toggle("unlocked", state.unlocked);
      button.setAttribute("aria-label", state.unlocked ? "Zablokuj sterowanie" : "Odblokuj sterowanie PIN-em");
      button.setAttribute("aria-pressed", String(state.unlocked));
      button.title = state.role === "admin" ? `${label} — administrator` : label;
      button.disabled = state.authExpired || state.role === "readonly";
    }
  }

  async function checkAuth() {
    if (state.authCheckInFlight) return state.authCheckInFlight;
    state.authCheckInFlight = (async () => {
      try {
        const result = await api("/api/auth/status");
        state.role = result.role || "readonly";
        state.authCheckedAt = Date.now();
        state.pinExpiresAt = result.expires_at ? Date.parse(result.expires_at) : 0;
        state.unlocked = Boolean(result.unlocked) || (state.publicConfig?.pin_required === false && ["admin", "user"].includes(state.role));
        if (!state.unlocked) clearControlAccess({ forgetToken: true });
        updateLockButton();
        return true;
      } catch (error) {
        // Zmiana sieci nie unieważnia poprawnego PIN-u na serwerze.
        // Ukryj aktywne sterowanie, ale zachowaj token do ponownej walidacji.
        clearControlAccess();
        return false;
      }
    })().finally(() => { state.authCheckInFlight = null; });
    return state.authCheckInFlight;
  }

  function showUnlock() {
    if (state.authExpired) { $("sessionExpiredDialog").showModal(); return; }
    if (state.role === "readonly") { toast("To konto ma dostęp tylko do odczytu.", "error"); return; }
    $("unlockError").textContent = "";
    $("pinInput").value = "";
    $("unlockDialog").showModal();
    setTimeout(() => $("pinInput").focus(), 80);
  }

  async function unlock(pin) {
    const result = await api("/api/auth/unlock", { method: "POST", body: JSON.stringify({ pin }) });
    state.token = result.token;
    state.unlocked = true;
    state.pinExpiresAt = Date.parse(result.expires_at);
    state.authCheckedAt = Date.now();
    localStorage.setItem("plumbox_token", result.token);
    updateLockButton();
    toast("Sterowanie odblokowane.", "success");
  }

  async function lock() {
    try { await api("/api/auth/lock", { method: "POST" }); } catch {}
    state.token = "";
    state.unlocked = false;
    localStorage.removeItem("plumbox_token");
    updateLockButton();
    toast("Sterowanie zablokowane.");
    render();
  }

  function pushSpark(key, value) {
    const numeric = finiteNumber(value);
    if (numeric === null) return;
    if (!state.sparks[key]) state.sparks[key] = [];
    state.sparks[key].push(numeric);
    if (state.sparks[key].length > 34) state.sparks[key].shift();
  }

  function updateSparks() {
    ["heating_temp", "return_temp", "water_heater_temp", "mixer_temp", "feeder_temp", "fan_power", "optical_temp", "boiler_power", "boiler_load", "fuel_consumption", "fuel_level"].forEach((key) => {
      if (key === "mixer_temp") pushSpark(key, state.snapshot?.mixers?.["0"]?.values?.current_temp);
      else pushSpark(key, val(key, null));
    });
  }

  function currentTemperatureHistoryRow() {
    if (!state.snapshot) return null;
    const mixer = state.snapshot?.mixers?.["0"]?.values || {};
    const row = {
      ts: state.snapshot.timestamp || new Date().toISOString(),
      heating_temp: finiteNumber(val("heating_temp", null)),
      return_temp: finiteNumber(val("return_temp", null)),
      water_heater_temp: finiteNumber(val("water_heater_temp", null)),
      mixer_temp: finiteNumber(mixer.current_temp),
    };
    return [row.heating_temp, row.return_temp, row.water_heater_temp, row.mixer_temp]
      .some((value) => value !== null) ? row : null;
  }

  function appendOverviewTemperatureSample() {
    const row = currentTemperatureHistoryRow();
    if (!row) return false;
    const rows = state.overviewHistory;
    const last = rows.length ? rows[rows.length - 1] : null;
    const keys = ["heating_temp", "return_temp", "water_heater_temp", "mixer_temp"];
    if (last && keys.every((key) => finiteNumber(last[key]) === row[key])) return false;
    rows.push(row);
    if (rows.length > 400) rows.splice(0, rows.length - 400);
    state.overviewHistoryRevision += 1;
    return true;
  }

  function sparkline(key, color, height = 50) {
    const data = state.sparks[key] || [];
    if (data.length < 2) return `<div class="sparkline sparkline-empty">Brak historii</div>`;
    const width = 180;
    const min = Math.min(...data);
    const max = Math.max(...data);
    const range = Math.max(1, max - min);
    const points = data.map((number, index) => {
      const x = index * width / Math.max(1, data.length - 1);
      const y = height - ((number - min) / range) * (height - 7) - 3;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(" ");
    const id = `${key}-${Math.random().toString(36).slice(2, 7)}`;
    return `<svg class="sparkline" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" aria-hidden="true"><defs><linearGradient id="${id}" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="${color}" stop-opacity=".28"/><stop offset="1" stop-color="${color}" stop-opacity="0"/></linearGradient></defs><polygon points="0,${height} ${points} ${width},${height}" fill="url(#${id})"></polygon><polyline points="${points}" fill="none" stroke="${color}" stroke-width="1.7" vector-effect="non-scaling-stroke"></polyline></svg>`;
  }

  function progress(value) {
    return `<div class="progress"><span style="width:${clamp(value)}%"></span></div>`;
  }

  function parameterByName(name, scope = "ecomax", index = 0) {
    if (scope === "ecomax") return state.snapshot?.parameters?.[name] || null;
    return state.snapshot?.mixers?.[String(index)]?.parameters?.[name] || null;
  }

  function parameterValue(name, fallback = "—", scope = "ecomax", index = 0) {
    return parameterByName(name, scope, index)?.value ?? fallback;
  }

  function parameterInputId(parameter) {
    return `${parameter.scope}-${parameter.index}-${parameter.name}`.replaceAll("_", "-");
  }

  function draftParameterNumber(name, fallback = 0) {
    const parameter = parameterByName(name);
    if (!parameter) return Number(fallback) || 0;

    const input = $(`input-${parameterInputId(parameter)}`);
    const source = input ? input.value : parameter.value;
    const number = Number(source);

    return Number.isFinite(number) ? number : (Number(fallback) || 0);
  }

  function effectiveHeatingTarget() {
    const liveTarget = finiteNumber(val("heating_target", null));
    if (liveTarget !== null) return liveTarget;
    return finiteNumber(parameterValue("heating_target_temp", null));
  }

  function hysteresisSummaryHtml() {
    const target = effectiveHeatingTarget();
    if (target === null) {
      return `<section class="hysteresis-summary" id="hysteresisSummary"><div class="warning-strip">Brak temperatury zadanej kotła. PlumBox nie wylicza progów H1/H2 z niepełnych danych.</div></section>`;
    }
    const h2 = draftParameterNumber("h2_hysteresis");
    const h1 = draftParameterNumber("h1_hysteresis");
    const restartHysteresis = draftParameterNumber("heating_hysteresis");

    const h2Threshold = target - h2;
    const h1Threshold = target - h1;
    const restartThreshold = target - restartHysteresis;

    const powerMax = parameterValue("boiler_power_100", "—");
    const powerMid = parameterValue("boiler_power_50", "—");
    const powerMin = parameterValue("boiler_power_30", "—");
    const currentTemp = finiteNumber(val("heating_temp", null));

    const threeLevels = h1 < h2;
    const middleRange = threeLevels
      ? `${fmt(h2Threshold)}–${fmt(h1Threshold)}°C`
      : "zakres pomijany";

    const currentText = currentTemp !== null
      ? `${fmt(currentTemp)}°C`
      : "brak odczytu";

    return `
      <section class="hysteresis-summary" id="hysteresisSummary">
        <div class="hysteresis-summary-head">
          <div>
            <span class="hysteresis-kicker">PRZELICZONE PROGI TEMPERATURY</span>
            <h3>Temperatura zadana kotła: ${escapeHtml(fmt(target))}°C</h3>
            <p>Aktualna temperatura kotła: <strong>${escapeHtml(currentText)}</strong>. Progi są liczone automatycznie jako temperatura zadana minus wartość H1, H2 lub histerezy kotła.</p>
          </div>
          <div class="target-badge"><span>ZADANA</span><strong>${escapeHtml(fmt(target))}°C</strong></div>
        </div>

        <div class="hysteresis-threshold-grid">
          <article class="threshold-card max">
            <span class="threshold-label">MOC MAX</span>
            <strong>${escapeHtml(fmt(powerMax))} kW</strong>
            <div>Praca poniżej <b>${escapeHtml(fmt(h2Threshold))}°C</b></div>
            <small>H2 = ${escapeHtml(fmt(h2))}°C</small>
          </article>

          <article class="threshold-card mid">
            <span class="threshold-label">MOC ŚREDNIA</span>
            <strong>${escapeHtml(fmt(powerMid))} kW</strong>
            <div>${threeLevels ? `Zakres <b>${escapeHtml(middleRange)}</b>` : "<b>Zakres mocy pośredniej jest pomijany</b>"}</div>
            <small>Próg H2: ${escapeHtml(fmt(h2Threshold))}°C</small>
          </article>

          <article class="threshold-card min">
            <span class="threshold-label">MOC MIN</span>
            <strong>${escapeHtml(fmt(powerMin))} kW</strong>
            <div>Od <b>${escapeHtml(fmt(h1Threshold))}°C</b> do temperatury zadanej</div>
            <small>H1 = ${escapeHtml(fmt(h1))}°C</small>
          </article>

          <article class="threshold-card restart">
            <span class="threshold-label">PONOWNY START</span>
            <strong>${escapeHtml(fmt(restartThreshold))}°C</strong>
            <div>Kocioł dostanie sygnał startu po spadku poniżej tego progu</div>
            <small>Histereza kotła = ${escapeHtml(fmt(restartHysteresis))}°C</small>
          </article>
        </div>

        <div class="hysteresis-scale">
          <div class="scale-row">
            <span class="scale-caption">Moc MAX</span>
            <div class="scale-bar max" style="flex:${Math.max(1, h2Threshold)}"></div>
            <span class="scale-value">${escapeHtml(fmt(h2Threshold))}°C</span>
          </div>
          <div class="scale-row">
            <span class="scale-caption">Moc średnia</span>
            <div class="scale-bar mid ${threeLevels ? "" : "disabled"}" style="flex:${Math.max(1, h2 - h1)}"></div>
            <span class="scale-value">${threeLevels ? escapeHtml(middleRange) : "pominięta"}</span>
          </div>
          <div class="scale-row">
            <span class="scale-caption">Moc MIN</span>
            <div class="scale-bar min" style="flex:${Math.max(1, h1)}"></div>
            <span class="scale-value">${escapeHtml(fmt(h1Threshold))}–${escapeHtml(fmt(target))}°C</span>
          </div>
        </div>

        ${threeLevels
          ? ""
          : `<div class="warning-strip critical hysteresis-warning">H1 jest większe lub równe H2. W takim ustawieniu sterownik może pominąć poziom mocy pośredniej i przechodzić bezpośrednio między mocą MAX i MIN.</div>`}

        <div class="hysteresis-mode-note">
          H1 i H2 sterują progami modulacji w trybie Standardowym. W trybie Fuzzy Logic regulator dobiera moc automatycznie.
        </div>
      </section>`;
  }

  function refreshHysteresisSummary() {
    if (state.activeView !== "hysteresis") return;
    const current = $("hysteresisSummary");
    if (!current) return;

    const wrapper = document.createElement("div");
    wrapper.innerHTML = hysteresisSummaryHtml().trim();
    const replacement = wrapper.firstElementChild;

    if (replacement) current.replaceWith(replacement);
  }

  function allParameters() {
    const parameters = [];
    Object.values(state.snapshot?.parameters || {}).forEach((item) => parameters.push(item));
    Object.entries(state.snapshot?.mixers || {}).forEach(([index, mixer]) => {
      Object.values(mixer.parameters || {}).forEach((item) => parameters.push({ ...item, index: Number(index) }));
    });
    return parameters;
  }

  function userFirst(parameters) {
    return [...parameters].sort((left, right) => {
      const leftOrder = left.access === "user" ? 0 : 1;
      const rightOrder = right.access === "user" ? 0 : 1;
      return leftOrder - rightOrder;
    });
  }

  function deviceLine(icon, label, active) {
    // Bez kolumny odczytu — temperatury są już w kaflach wyżej, tu tylko stan.
    const stateClass = active === null ? "state-unknown" : active ? "state-on" : "state-off";
    const stateText = active === null ? "BRAK DANYCH" : active ? "WŁĄCZONA" : "WYŁĄCZONA";
    return `<div class="device-line ${stateClass}"><span class="device-state-icon" aria-hidden="true">${icon}</span><span>${escapeHtml(label)}</span><strong class="state-pill">${stateText}</strong></div>`;
  }

  function serviceLine(name, label, unit = "", scope = "ecomax", index = 0) {
    const parameter = parameterByName(name, scope, index);
    const id = `${scope}-${index}-${name}`.replaceAll("_", "-");
    return `<div class="service-line"><span>${escapeHtml(label)}</span><strong>${escapeHtml(fmt(parameter?.value, 2))}${unit ? ` ${escapeHtml(unit)}` : ""}</strong><button class="service-edit" data-quick-parameter="${escapeHtml(id)}" data-param-scope="${scope}" data-param-index="${index}" data-param-name="${name}" title="Edytuj">✎</button></div>`;
  }

  function gaugeCard(title, value, unit, max, icon = "✥") {
    const pct = clamp((Number(value) / Math.max(1, max)) * 100);
    return `<article class="card rail-card gauge-card"><div class="card-heading"><span class="accent">${icon}</span>${escapeHtml(title)}</div><div class="gauge-wrap"><div class="gauge-ring" style="--pct:${pct}"></div><div class="gauge-value">${escapeHtml(fmt(value, 1))}${unit}</div></div><div class="gauge-scale"><span>0</span><span>${escapeHtml(max)}${unit}</span></div></article>`;
  }

  function chartLegendHtml(series = chartSeries()) {
    const items = series.map(([key, color, label]) =>
      `<button type="button" class="legend-item ${state.hiddenSeries.has(key) ? "off" : ""}" data-series-toggle="${key}" title="Kliknij, aby ukryć/pokazać serię"><i style="--legend-color:${color}"></i>${label}</button>`
    ).join("");
    return `<div class="chart-legend" aria-label="Legenda wykresu — kliknięcie przełącza serię">${items}</div>`;
  }

  function firstSnapshotValue(names, fallback = null) {
    for (const name of names) {
      const value = state.snapshot?.values?.[name];
      if (value !== null && value !== undefined) return value;
    }
    return fallback;
  }

  function schemePumpClass(value) {
    return value === null ? " unknown" : "";
  }

  function schemeBurnerState(mode, lighter, connected) {
    if (!connected) return { phase: "offline", label: "Brak łączności" };
    const phase = String(mode).trim().toLocaleLowerCase("pl");
    if (lighter === true || phase === "rozpalanie") return { phase: "igniting", label: "Rozpalanie" };
    if (["praca", "nadzór"].includes(phase)) return { phase: "burning", label: String(mode) };
    if (phase === "wygaszanie") return { phase: "extinguishing", label: "Wygaszanie" };
    return { phase: "idle", label: String(mode || "Brak odczytu") };
  }

  function installationSchemeHtml() {
    const mixer = state.snapshot?.mixers?.["0"]?.values || {};
    const mode = String(val("state_label", "Nieznany"));
    const heating = finiteNumber(val("heating_temp", null));
    const heatingTarget = finiteNumber(val("heating_target", null))
      ?? finiteNumber(parameterValue("heating_target_temp", null));
    const cwuTemp = finiteNumber(val("water_heater_temp", null));
    const cwuTarget = finiteNumber(val("water_heater_target", null))
      ?? finiteNumber(parameterValue("water_heater_target_temp", null));
    const mixerTemp = finiteNumber(mixer.current_temp);
    const mixerTarget = finiteNumber(mixer.target_temp)
      ?? finiteNumber(parameterValue("mixer_target_temp", null, "mixer", 0));
    const feederTemp = finiteNumber(val("feeder_temp", null));
    const outsideTemp = finiteNumber(firstSnapshotValue(["outside_temp", "external_temp", "weather_temp"]));

    // Animacje pokazują wyłącznie stany odebrane ze sterownika. Brak flagi
    // nie jest zastępowany domysłem na podstawie nazwy fazy pracy.
    const boilerPump = booleanValue(val("heating_pump", null));
    const cwuPump = booleanValue(val("water_heater_pump", null));
    const coPump = booleanValue(mixer.pump ?? null);
    const feeder = booleanValue(val("feeder", null));
    const lighter = booleanValue(val("lighter", null));
    const burner = schemeBurnerState(mode, lighter, Boolean(state.snapshot?.connected));
    const thermostat = booleanValue(firstSnapshotValue(["thermostat", "thermostat_state", "room_thermostat"]));
    const activeFlows = [
      coPump === true ? "CO" : null,
      cwuPump === true ? "CWU" : null,
      boilerPump === true ? "ochrona powrotu" : null,
    ].filter(Boolean);
    const unknownPumps = [boilerPump, cwuPump, coPump].some((value) => value === null);
    const classes = [
      "installation-scheme",
      `burner-${burner.phase}`,
      coPump === true ? "co-active" : "",
      cwuPump === true ? "cwu-active" : "",
      boilerPump === true ? "boiler-active" : "",
      feeder === true ? "feeder-active" : "",
      activeFlows.length ? "has-active-flow" : "",
    ].filter(Boolean).join(" ");
    const flowText = activeFlows.length
      ? `Pracujące pompy: ${activeFlows.join(", ")}.`
      : "Sterownik nie sygnalizuje pracy pomp.";
    const qualityText = unknownPumps
      ? " Brak pełnego odczytu stanów pomp — brakujące animacje pozostają zatrzymane."
      : " Animacja wynika ze stanów pomp; nie jest pomiarem przepływu.";
    const thermostatText = thermostat === null ? "BRAK ODCZYTU" : thermostat ? "WŁĄCZONY" : "WYŁĄCZONY";

    return `<section class="${classes}" data-installation-scheme>
      <div class="scheme-header">
        <div>
          <span class="scheme-eyebrow">SCHEMAT HYDRAULICZNY · UKŁAD DEKLAROWANY</span>
          <h2>Dwa obiegi kotła i ochrona powrotu</h2>
          <p>Schemat według konfiguracji instalacji użytkownika. CO i CWU mają osobne zasilania oraz powroty.</p>
        </div>
        <div class="scheme-legend" aria-label="Legenda schematu">
          <span><i class="hot"></i>Zasilanie</span>
          <span><i class="cold"></i>Powrót</span>
          <span><i class="active"></i>Pompa pracuje</span>
        </div>
      </div>

      <div class="scheme-status-strip">
        <i class="scheme-status-dot" aria-hidden="true"></i>
        <strong>${escapeHtml(mode).toUpperCase()}</strong>
        <span>${escapeHtml(flowText + qualityText)}</span>
      </div>

      <div class="scheme-canvas">
        <div class="scheme-plant">
          <div class="scheme-weather">ZEWN. <b>${escapeHtml(fmt(outsideTemp))}°C</b></div>
          <div class="scheme-thermostat"><span>TERMOSTAT</span><b>${escapeHtml(thermostatText)}</b></div>

          <div class="scheme-boiler scheme-boiler-photo">
            <img class="scheme-boiler-image" src="assets/sf11130.jpg" width="500" height="500" alt="Kocioł na pellet HKS Lazar SmartFire SF 11/130" decoding="async">
            <div class="scheme-boiler-data">
            <div class="scheme-controller" role="status"><i aria-hidden="true"></i><span>${escapeHtml(burner.label).toUpperCase()}</span></div>
            <div class="scheme-boiler-readout"><span>TEMPERATURA KOTŁA</span><b>${escapeHtml(fmt(heating))}<small>°C</small></b><span>zadana ${escapeHtml(fmt(heatingTarget))}°C</span></div>
            <div class="scheme-burner-window" title="Symboliczny stan palnika według danych sterownika" aria-hidden="true"><i class="scheme-flame"></i><i class="scheme-ember"></i></div>
            <div class="scheme-burner-readout"><span>PALNIK</span><strong>${escapeHtml(burner.label)}</strong><small>Temp. podajnika <b>${escapeHtml(fmt(feederTemp))}°C</b></small><span class="scheme-feed-status${feeder === true ? " active" : ""}"><i aria-hidden="true"></i>${feeder === null ? "Podawanie: brak odczytu" : feeder ? "Podawanie pelletu" : "Podajnik zatrzymany"}</span></div>
            </div>
          </div>

          <div class="scheme-hydraulics">
          <div class="scheme-port scheme-port-co-supply"><i></i><span>ZASILANIE CO</span></div>
          <div class="scheme-port scheme-port-co-return"><i></i><span>POWRÓT CO</span></div>
          <div class="scheme-cwu-label scheme-cwu-label-supply">ZASILANIE CWU</div>
          <div class="scheme-cwu-label scheme-cwu-label-return">POWRÓT CWU</div>

          <div class="scheme-pipe scheme-boiler-feed horizontal red"><i></i></div>
          <div class="scheme-pipe scheme-co-supply-h co-flow horizontal red"><i></i></div>
          <div class="scheme-pipe scheme-co-supply-v co-flow vertical red"><i></i></div>
          <div class="scheme-pipe scheme-co-return-v co-flow vertical blue"><i></i></div>
          <div class="scheme-pipe scheme-co-return-h co-flow horizontal blue"><i></i></div>
          <div class="scheme-pipe scheme-protect-return horizontal blue"><i></i></div>
          <div class="scheme-pipe scheme-atv-branch protect-flow vertical orange"><i></i></div>

          <div class="scheme-separator"><span>SPRZĘGŁO</span></div>
          <div class="scheme-atv">ATV</div>
          <div class="scheme-mixer"><b>MIX</b></div>
          <div class="scheme-pump scheme-pump-co${schemePumpClass(coPump)}"><i></i><span></span><small>POMPA CO</small></div>
          <div class="scheme-pump scheme-pump-boiler${schemePumpClass(boilerPump)}"><i></i><span></span><small>POMPA KOTŁOWA</small></div>
          <div class="scheme-radiator"><span>OBIEG GRZEJNIKOWY</span><div><i></i><i></i><i></i><i></i><i></i><i></i><i></i></div></div>

          <div class="scheme-temp scheme-temp-co"><b>${escapeHtml(fmt(mixerTemp))}°C</b><span>zadana ${escapeHtml(fmt(mixerTarget))}°C</span></div>

          <div class="scheme-pipe scheme-cwu-feed cwu-flow horizontal red"><i></i></div>
          <div class="scheme-pipe scheme-cwu-feed-v cwu-flow vertical red"><i></i></div>
          <div class="scheme-pipe scheme-cwu-return-link cwu-flow horizontal blue"><i></i></div>
          <div class="scheme-pipe scheme-cwu-return-v cwu-flow vertical blue"><i></i></div>
          <div class="scheme-pipe scheme-cwu-supply cwu-flow horizontal red"><i></i></div>
          <div class="scheme-pipe scheme-cwu-return cwu-flow horizontal blue"><i></i></div>
          <div class="scheme-pump scheme-pump-cwu${schemePumpClass(cwuPump)}"><i></i><span></span><small>POMPA CWU</small></div>
          <div class="scheme-tank">
            <span class="scheme-tap"><b></b><em></em><i></i></span>
            <div class="scheme-coil"><i></i><i></i><i></i></div>
            <small>ZASOBNIK CWU</small>
          </div>
          <div class="scheme-temp scheme-temp-cwu"><b>${escapeHtml(fmt(cwuTemp))}°C</b><span>zadana ${escapeHtml(fmt(cwuTarget))}°C</span></div>

          </div>
          <div class="scheme-flow-note"><i></i><span>${escapeHtml(flowText)}</span></div>
        </div>
      </div>
    </section>`;
  }

  function fitInstallationScheme() {
    const canvas = content.querySelector(".scheme-canvas");
    const plant = canvas?.querySelector(".scheme-plant");
    if (!canvas || !plant) return;
    const scale = Math.min(1, Math.max(.2, canvas.clientWidth / 1360));
    plant.style.setProperty("--scheme-scale", scale.toFixed(4));
    const height = `${Math.ceil(610 * scale)}px`;
    if (canvas.style.height !== height) canvas.style.height = height;
  }

  function captureInstallationScroll() {
    const positions = [];
    const seen = new Set();
    const remember = (element) => {
      if (!element || seen.has(element)) return;
      seen.add(element);
      positions.push({ element, top: element.scrollTop, left: element.scrollLeft });
    };
    remember(document.scrollingElement);
    let element = content;
    while (element) {
      if (element.scrollHeight > element.clientHeight || element.scrollWidth > element.clientWidth) {
        remember(element);
      }
      element = element.parentElement;
    }
    return positions;
  }

  function restoreInstallationScroll(positions) {
    positions.forEach(({ element, top, left }) => {
      if (element.scrollTop !== top) element.scrollTop = top;
      if (element.scrollLeft !== left) element.scrollLeft = left;
    });
  }

  function overviewHtml() {
    const mixer = state.snapshot?.mixers?.["0"]?.values || {};
    const heating = finiteNumber(val("heating_temp", null));
    const target = finiteNumber(val("heating_target", null)) ?? finiteNumber(parameterValue("heating_target_temp", null));
    const boilerLoad = finiteNumber(val("boiler_load", null));
    const cwu = finiteNumber(val("water_heater_temp", null));
    const cwuTarget = finiteNumber(val("water_heater_target", null)) ?? finiteNumber(parameterValue("water_heater_target_temp", null));
    const mixerTemp = finiteNumber(mixer.current_temp);
    const mixerTarget = finiteNumber(mixer.target_temp) ?? finiteNumber(parameterValue("mixer_target_temp", null, "mixer", 0));
    const fuelLevel = finiteNumber(val("fuel_level", null));
    const mode = val("state_label", "Nieznany");
    const currentAlerts = Array.isArray(state.snapshot?.alerts) ? state.snapshot.alerts : [];
    const activeSnapshotAlerts = currentAlerts.filter((alarm) => alarm?.active).length;
    const pendingAlerts = finiteNumber(val("pending_alerts", null));
    const alarmSignal = booleanValue(val("alarm", null));
    let activeAlarmCount = pendingAlerts === null ? null : Math.max(0, pendingAlerts);
    if (activeSnapshotAlerts > 0) activeAlarmCount = Math.max(activeAlarmCount ?? 0, activeSnapshotAlerts);
    if (activeAlarmCount === null && alarmSignal !== null) activeAlarmCount = alarmSignal ? 1 : 0;
    const hasActiveAlarm = activeAlarmCount !== null && activeAlarmCount > 0;
    return `<div class="dashboard-shell">
      <div class="dashboard-main">
        <div class="top-cards">
          <article class="card hero-card"><div class="hero-label">TEMPERATURA KOTŁA</div><div class="hero-temp">${escapeHtml(fmt(heating))}<small>°C</small></div><div class="hero-meta"><span>Temperatura zadana: <strong>${escapeHtml(fmt(target))}°C</strong></span><span>Tryb pracy: <strong class="mode">${escapeHtml(mode).toUpperCase()}</strong></span></div></article>
          <article class="card metric-card"><div class="metric-top"><span>⚿</span>PODAJNIK</div><div class="metric-value orange">${escapeHtml(fmt(val("feeder_temp")))}<small>°C</small></div>${sparkline("feeder_temp", cssColor("--viz-amber", "#d99b2b"), 30)}</article>
          <article class="card metric-card"><div class="metric-top"><span>⌁</span>OBCIĄŻENIE</div><div class="metric-value green">${escapeHtml(fmt(boilerLoad, 0))}<small>%</small></div><div class="status-metric-note">Wartość przekazana przez sterownik</div>${sparkline("boiler_load", cssColor("--viz-green", "#34c98e"), 30)}</article>
        </div>

        <div class="metric-row">
          <article class="card metric-card"><div class="metric-top"><span>✥</span>WENTYLATOR</div><div class="metric-value blue">${escapeHtml(fmt(val("fan_power"), 0))}<small>%</small></div>${sparkline("fan_power", cssColor("--viz-blue", "#4a8fe8"), 30)}</article>
          <article class="card metric-card"><div class="metric-top"><span>⌘</span>MIESZACZ</div><div class="metric-value blue">${escapeHtml(fmt(mixerTemp))}<small>°C</small></div><div class="status-metric-note">Zadana: ${escapeHtml(fmt(mixerTarget))}°C</div>${sparkline("mixer_temp", cssColor("--chart-s4", "#bb8b16"), 30)}</article>
          <article class="card metric-card"><div class="metric-top"><span>💧</span>CWU</div><div class="metric-value blue">${escapeHtml(fmt(cwu))}<small>°C</small></div><div class="status-metric-note">Zadana: ${escapeHtml(fmt(cwuTarget))}°C</div>${sparkline("water_heater_temp", cssColor("--chart-s3", "#4a8fe8"), 30)}</article>
        </div>

        <div class="metric-row metric-row-compact">
          <article class="card metric-card"><div class="metric-top"><span>▧</span>POZIOM PALIWA</div><div class="metric-value green">${escapeHtml(fmt(fuelLevel, 0))}<small>%</small></div>${sparkline("fuel_level", cssColor("--viz-green", "#34c98e"), 30)}</article>
          <button type="button" class="card metric-card metric-action-card${hasActiveAlarm ? " alarm-active" : ""}" data-open-view="alarms"><div class="metric-top"><span>${hasActiveAlarm ? "⚠" : "✓"}</span>ALARMY AKTYWNE</div><div class="metric-value ${hasActiveAlarm ? "red" : "green"}">${escapeHtml(fmt(activeAlarmCount, 0))}</div><div class="status-metric-note">Kliknij, aby otworzyć alarmy</div></button>
        </div>

        <div class="middle-row">
          <article class="card device-panel"><div class="panel-title">URZĄDZENIA / STAN</div><div class="device-table">
            ${deviceLine("♨", "Pompa kotłowa", booleanValue(val("heating_pump", null)))}
            ${deviceLine("💧", "Pompa CWU", booleanValue(val("water_heater_pump", null)))}
            ${deviceLine("◉", "Pompa CO za mieszaczem", booleanValue(mixer.pump))}
            ${deviceLine("⚿", "Podajnik", booleanValue(val("feeder", null)))}
            ${deviceLine("♨", "Zapalarka", booleanValue(val("lighter", null)))}
            ${deviceLine("✥", "Wentylator", booleanValue(val("fan", null)))}
          </div></article>


        </div>

        <div class="bottom-row bottom-row-full">
          <article class="card history-card"><div class="panel-title">HISTORIA TEMPERATUR</div>${chartLegendHtml(overviewChartSeries())}<div class="history-wrap"><canvas id="overviewHistoryCanvas"></canvas></div></article>
        </div>
      </div>

    </div>

    <article class="card remote-card"><div class="remote-content"><div class="remote-node"><div class="remote-icon">⌂</div><strong>SIEĆ LOKALNA</strong><small>Adres przydziela instalacja</small></div><div class="remote-node"><div class="remote-icon"><img src="assets/icon.svg" alt=""></div><strong>PlumBox</strong><small>Lokalna bramka</small></div><div class="remote-node"><div class="remote-icon">◎</div><strong>PANEL WWW</strong><small>Przeglądarka w sieci lokalnej</small></div><div class="remote-node"><div class="remote-icon">⬡</div><strong>VPN</strong><small>Tylko po skonfigurowaniu</small></div><div class="remote-node"><div class="remote-icon">▣</div><strong>DOSTĘP ZDALNY</strong><small>Zależy od instalacji</small></div></div></article>`;
  }

  function parametersForSection(section) {
    return userFirst(allParameters().filter((parameter) => parameter.section === section));
  }

  function editorHtml(parameter) {
    const id = `${parameter.scope}-${parameter.index}-${parameter.name}`.replaceAll("_", "-");
    const allowed = state.unlocked && ["admin", "user"].includes(state.role) && ((parameter.name !== "ecomax_control" && parameter.risk === "safe") || state.role === "admin");
    const disabled = allowed ? "" : "disabled";
    let draft = state.parameterDrafts.get(id);
    if (draft !== undefined && draft !== "" && Number(draft) === Number(parameter.value)) {
      state.parameterDrafts.delete(id);
      draft = undefined;
    }
    const editorValue = draft !== undefined ? draft : parameter.value;
    if (parameter.kind === "switch") {
      const on = isEnabledValue(parameter.value);
      return `<div class="switch-editor"><button class="off ${!on ? "active" : ""}" ${disabled} data-switch-parameter="${escapeHtml(id)}" data-switch-value="false">${escapeHtml(parameter.off_action_label || "Wyłącz")}</button><button class="${on ? "active" : ""}" ${disabled} data-switch-parameter="${escapeHtml(id)}" data-switch-value="true">${escapeHtml(parameter.on_action_label || "Włącz")}</button></div>`;
    }
    if (parameter.kind === "select") {
      const selectedValue = draft !== undefined ? draft : parameter.native_value;
      const options = Object.entries(parameter.options || {}).map(([option, label]) => `<option value="${escapeHtml(option)}" ${(String(selectedValue) === String(option) || String(editorValue) === String(option)) ? "selected" : ""}>${escapeHtml(label)}</option>`).join("");
      return `<div class="select-editor"><select id="input-${escapeHtml(id)}" ${disabled}>${options}</select></div><div class="parameter-actions"><button class="save-button" ${disabled} data-save-parameter="${escapeHtml(id)}">Zapisz do sterownika</button></div>`;
    }
    return `<div class="number-editor"><button ${disabled} data-step-parameter="${escapeHtml(id)}" data-direction="-1">−</button><input id="input-${escapeHtml(id)}" type="number" value="${escapeHtml(editorValue)}" min="${escapeHtml(parameter.min)}" max="${escapeHtml(parameter.max)}" step="${escapeHtml(parameter.step || 1)}" ${disabled}><button ${disabled} data-step-parameter="${escapeHtml(id)}" data-direction="1">+</button></div><div class="parameter-actions"><button class="save-button" ${disabled} data-save-parameter="${escapeHtml(id)}">Zapisz do sterownika</button></div>`;
  }

  function parameterCard(parameter) {
    const badge = parameter.risk === "critical" ? "Krytyczny" : parameter.access === "user" ? "Użytkowy" : "Serwis";
    const badgeClass = parameter.risk === "critical" ? "critical" : parameter.access === "user" ? "safe" : "advanced";
    return `<article class="parameter-card" data-risk="${escapeHtml(parameter.risk)}" data-access="${escapeHtml(parameter.access || "service")}" data-param-scope="${escapeHtml(parameter.scope)}" data-param-index="${escapeHtml(parameter.index)}" data-param-name="${escapeHtml(parameter.name)}"><div class="parameter-top"><div class="parameter-title">${escapeHtml(parameter.label)}</div><span class="risk-tag ${escapeHtml(badgeClass)}">${badge}</span></div><div class="parameter-current">${escapeHtml(parameterValueLabel(parameter))}</div><div class="range-note">${escapeHtml(parameterRangeLabel(parameter))}</div>${editorHtml(parameter)}</article>`;
  }

  function sectionHtml(section, parameters = null, intro = "") {
    const items = parameters || parametersForSection(section);
    const sectionMeta = state.catalog?.sections?.find((item) => item.id === section);
    const advanced = ["kindling", "supervision", "burning_off", "cleaning", "protections"].includes(section);
    if (!items.length) return `<div class="empty-state">Sterownik nie udostępnił parametrów tej sekcji.</div>`;
    return `<div class="section-head"><h2>${escapeHtml(sectionMeta?.label || titles[state.activeView] || section)}</h2><p>${items.length} parametrów wykrytych bezpośrednio w regulatorze.</p></div>${intro}${advanced ? `<div class="warning-strip ${section === "protections" ? "critical" : ""}">Zmiany w tej sekcji wpływają na proces spalania lub zabezpieczenia. Porównaj bieżące wartości z panelem kotła.</div>` : ""}${!state.unlocked ? `<div class="warning-strip">Sterowanie jest zablokowane. Podaj PIN, aby zapisywać wartości.</div>` : ""}<div class="parameters-grid">${items.map(parameterCard).join("")}</div>`;
  }

  function filteredHtml(view) {
    const wanted = new Set(filteredViews[view] || []);
    const byName = new Map(allParameters().filter((item) => wanted.has(item.name)).map((item) => [item.name, item]));
    const items = (filteredViews[view] || []).map((name) => byName.get(name)).filter(Boolean);
    const intro = view === "hysteresis" ? hysteresisSummaryHtml() : "";
    return sectionHtml(view, items, intro);
  }

  function viewForParameter(parameter) {
    const name = parameter?.name;
    if (filteredViews.fuel_calibration.includes(name)) return "fuel_calibration";
    if (filteredViews.boiler_powers.includes(name)) return "boiler_powers";
    if (filteredViews.hysteresis.includes(name)) return "hysteresis";
    if (filteredViews.airflow.includes(name)) return "airflow";
    return parameter?.section || "all";
  }

  function summaryCard(label, value, unit = "") {
    return `<div class="summary-card"><span>${escapeHtml(label)}</span><strong>${escapeHtml(fmt(value))}${unit ? ` ${escapeHtml(unit)}` : ""}</strong></div>`;
  }

  async function alarmsHtml() {
    try { state.alarmRows = (await api("/api/alarms?limit=300")).rows || []; } catch { state.alarmRows = []; }
    const current = state.snapshot?.alerts || [];
    const alarmFlag = booleanValue(val("alarm", null));
    const pending = finiteNumber(val("pending_alerts", null));
    const active = current.some((alarm) => alarm.active) || alarmFlag === true || (pending !== null && pending > 0)
      ? true
      : alarmFlag === false && pending !== null ? false : null;
    const rows = [...current, ...state.alarmRows].map((alarm) => `<tr><td>${escapeHtml(alarm.code)}</td><td>${escapeHtml(alarm.name)}</td><td>${escapeHtml(formatDate(alarm.from || alarm.started_at))}</td><td>${escapeHtml(formatDate(alarm.to || alarm.ended_at))}</td><td>${alarm.active ? "Aktywny" : "Zakończony"}</td></tr>`).join("");
    return `<div class="summary-grid">${summaryCard("Stan alarmów", active === null ? "BRAK DANYCH" : active ? "ALARM" : "Brak")}${summaryCard("Oczekujące", pending)}</div><section class="panel"><h3>Historia alarmów</h3><div class="table-wrap"><table><thead><tr><th>Kod</th><th>Opis</th><th>Początek</th><th>Koniec</th><th>Stan</th></tr></thead><tbody>${rows || `<tr><td colspan="5">Brak zarejestrowanych alarmów.</td></tr>`}</tbody></table></div></section>`;
  }

  async function historyHtml() {
    try { state.historyRows = (await api(`/api/history?hours=${state.historyHours}&limit=10000`)).rows || []; } catch { state.historyRows = []; }
    setTimeout(drawMainHistoryChart, 0);
    return `<section class="panel"><div class="section-head"><h2>Historia temperatur</h2><p>Dane zapisane lokalnie przez PlumBox.</p></div><div class="chart-toolbar">${[6,24,48,168,720].map((hours) => `<button data-history-hours="${hours}" class="${state.historyHours === hours ? "active" : ""}">${hours < 24 ? `${hours} h` : `${hours / 24} dni`}</button>`).join("")}</div>${chartLegendHtml()}<div class="chart-wrap"><canvas id="historyChart"></canvas></div></section>`;
  }

  function allHtml(search = "") {
    const query = search.trim().toLowerCase();
    const rows = allParameters().filter((item) => !query || `${item.label} ${item.name} ${item.section}`.toLowerCase().includes(query));
    return `<div class="search-row"><input id="parameterSearch" type="search" placeholder="Szukaj w pełnej liście diagnostycznej…" value="${escapeHtml(search)}"></div><div class="table-wrap"><table><thead><tr><th>Sekcja</th><th>Nazwa</th><th>Klucz</th><th>Wartość</th><th>Zakres</th><th>Urządzenie</th></tr></thead><tbody>${rows.map((item) => `<tr><td>${escapeHtml(item.section)}</td><td>${escapeHtml(item.label)}</td><td><code>${escapeHtml(item.name)}</code></td><td><strong>${escapeHtml(parameterValueLabel(item))}</strong></td><td>${escapeHtml(parameterRangeLabel(item))}</td><td>${item.scope === "mixer" ? `Mieszacz ${item.index + 1}` : "ecoMAX"}</td></tr>`).join("") || `<tr><td colspan="6">Brak wyników.</td></tr>`}</tbody></table></div>`;
  }

  function systemItem(label, value) {
    return `<div class="system-item"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`;
  }

  function auditValueLabel(parameterName, value) {
    const parameter = allParameters().find((item) => item.name === parameterName);
    return parameter ? parameterValueLabel(parameter, value) : fmt(value, 2);
  }

  function auditResultHtml(row) {
    if (row.success) return `<span class="audit-result ok">OK</span>`;
    const message = String(row.message || "Brak potwierdzenia zapisu.");
    const pending = message.startsWith("Brak potwierdzenia zapisu");
    return `<span class="audit-result ${pending ? "unconfirmed" : "error"}">${escapeHtml(message)}</span>`;
  }

  async function systemHtml(showAudit = false) {
    let auditRows = [];
    if (state.unlocked && showAudit) {
      try { auditRows = (await api("/api/audit?limit=200")).rows || []; } catch {}
    }
    if (showAudit) return `<section class="panel"><h3>Dziennik zmian</h3>${state.unlocked ? `<div class="table-wrap"><table><thead><tr><th>Czas</th><th>Wykonawca</th><th>Parametr</th><th>Poprzednio</th><th>Żądano</th><th>Wynik</th></tr></thead><tbody>${auditRows.map((row) => `<tr><td>${escapeHtml(formatDate(row.ts))}</td><td>${escapeHtml(row.actor || (row.source === "internal_or_mqtt" ? "MQTT / system" : "Brak danych"))}</td><td>${escapeHtml(row.parameter)}</td><td>${escapeHtml(auditValueLabel(row.parameter, row.old_value))}</td><td>${escapeHtml(auditValueLabel(row.parameter, row.requested_value))}</td><td>${auditResultHtml(row)}</td></tr>`).join("") || `<tr><td colspan="6">Brak zapisów.</td></tr>`}</tbody></table></div>` : `<div class="empty-state">Odblokuj sterowanie, aby zobaczyć dziennik zmian.</div>`}</section>`;
    const modules = val("modules", {});
    const stats = state.snapshot?.statistics || {};
    const stat = (name) => stats?.[name]?.value ?? stats?.[name] ?? "—";
    const hardware = state.snapshot?.hardware_profile || {};
    return `<div class="two-column"><section class="panel"><h3>Połączenie</h3><div class="system-list">${systemItem("Stan", state.snapshot?.connected ? "Połączony" : "Rozłączony")}${systemItem("Tryb", state.snapshot?.simulation ? "Symulacja" : state.publicConfig?.connection_type || "—")}${systemItem("Identyfikacja modelu", hardware.label || "Brak danych")}${systemItem("Skala RPM", hardware.enabled ? "Aktywna" : "Nieaktywna")}${systemItem("Źródło profilu", hardware.source || "—")}${systemItem("Ostatnia aktualizacja", formatDate(state.snapshot?.timestamp))}${systemItem("Błąd", state.snapshot?.connection_error || "Brak")}${systemItem("Odebrane ramki", stat("received_frames"))}${systemItem("Wysłane ramki", stat("sent_frames"))}</div></section><section class="panel"><h3>Moduły</h3><div class="system-list">${systemItem("Moduł A", modules?.module_a || "—")}${systemItem("Panel", modules?.panel || "—")}${systemItem("MQTT", state.publicConfig?.mqtt_enabled ? "Włączone" : "Wyłączone")}${systemItem("Historia", state.publicConfig?.history_enabled ? "Włączona" : "Wyłączona")}</div></section></div>`;
  }

  function findParameterCard(id) {
    return [...document.querySelectorAll(".parameter-card")].find((card) => `${card.dataset.paramScope}-${card.dataset.paramIndex}-${card.dataset.paramName}`.replaceAll("_", "-") === id);
  }

  function findQuickParameter(id) {
    const button = document.querySelector(`[data-quick-parameter="${CSS.escape(id)}"]`);
    if (!button) return null;
    return allParameters().find((item) => item.scope === button.dataset.paramScope && item.index === Number(button.dataset.paramIndex) && item.name === button.dataset.paramName) || null;
  }

  function prepareWrite(id, forcedValue = undefined, quick = false) {
    if (state.pinExpiresAt && Date.now() >= state.pinExpiresAt) clearControlAccess({ forgetToken: true });
    if (!state.unlocked) { showUnlock(); return; }
    if (quick) {
      const parameter = findQuickParameter(id);
      if (!parameter) { toast("Parametr nie został jeszcze udostępniony przez sterownik.", "error"); return; }
      switchView(viewForParameter(parameter));
      setTimeout(() => {
        const cardId = `${parameter.scope}-${parameter.index}-${parameter.name}`.replaceAll("_", "-");
        findParameterCard(cardId)?.scrollIntoView({ behavior: "smooth", block: "center" });
      }, 100);
      return;
    }
    const card = findParameterCard(id);
    if (!card) return;
    const parameter = allParameters().find((item) => item.scope === card.dataset.paramScope && item.index === Number(card.dataset.paramIndex) && item.name === card.dataset.paramName);
    if (!parameter) return;
    let nextValue = forcedValue;
    if (nextValue === undefined) {
      const input = $(`input-${id}`);
      if (!input) return;
      nextValue = Number(input.value);
    }
    const write = { parameter, value: nextValue };
    // Włączenie/wyłączenie kotła zawsze wymaga potwierdzenia — przypadkowe
    // kliknięcie po odblokowaniu PIN nie może zatrzymać ani uruchomić kotła.
    const alwaysConfirm = parameter.name === "ecomax_control";
    if (parameter.risk === "safe" && !alwaysConfirm) { executeWrite(write, false); return; }
    state.pendingWrite = write;
    $("confirmTitle").textContent = alwaysConfirm
      ? "Zmiana stanu kotła"
      : parameter.risk === "critical" ? "Zmiana progu bezpieczeństwa" : "Zmiana ustawienia serwisowego";
    $("confirmText").textContent = `${parameter.label}: ${parameterValueLabel(parameter)} → ${parameterValueLabel(parameter, nextValue)}.`;
    $("confirmCheckbox").checked = false;
    $("confirmButton").disabled = true;
    $("confirmDialog").showModal();
  }

  async function executeWrite(write, confirmed) {
    try {
      if (!await checkAuth()) { if (!state.authExpired) toast("Sprawdź połączenie i odblokuj sterowanie.", "error"); return; }
      if (!state.unlocked) { showUnlock(); await render(); return; }
      const result = await api("/api/set", { method: "POST", body: JSON.stringify({ scope: write.parameter.scope, index: write.parameter.index, name: write.parameter.name, value: write.value, confirmed }) });
      const toastKind = result.status === "unconfirmed" ? "warning" : result.success ? "success" : "error";
      toast(result.message || "Wartość zapisana.", toastKind);
      if (result.success) {
        const id = `${write.parameter.scope}-${write.parameter.index}-${write.parameter.name}`.replaceAll("_", "-");
        state.parameterDrafts.delete(id);
      }
      await fetchSnapshot();
      if (state.activeView === "audit") render();
    } catch (error) { toast(error.message, "error"); }
  }

  function bindContentEvents() {
    // Karty mogą zostać dodane później przez morphChildNodes(). Delegacja na
    // stałym kontenerze sprawia, że nowe przyciski i pola działają od razu.
    if (content.dataset.eventsBound === "true") return;
    content.dataset.eventsBound = "true";

    const rememberDraft = (input) => {
      state.parameterDrafts.set(input.id.replace(/^input-/, ""), input.value);
      refreshHysteresisSummary();
    };

    content.addEventListener("click", (event) => {
      const target = event.target instanceof Element ? event.target : event.target?.parentElement;
      if (!target) return;

      const stepButton = target.closest("[data-step-parameter]");
      if (stepButton && content.contains(stepButton)) {
        const input = $(`input-${stepButton.dataset.stepParameter}`);
        if (input) {
          const step = Number(input.step || 1) || 1;
          const next = Number(input.value || 0) + step * Number(stepButton.dataset.direction || 1);
          // Krok 0.2 dawał 6.3999999999999995 (arytmetyka zmiennoprzecinkowa IEEE 754);
          // zaokrąglamy do liczby miejsc dziesiętnych kroku.
          const decimals = Math.min(6, (String(step).split(".")[1] || "").length);
          input.value = String(Number(next.toFixed(decimals)));
          state.parameterDrafts.set(stepButton.dataset.stepParameter, input.value);
          refreshHysteresisSummary();
        }
        return;
      }

      const saveButton = target.closest("[data-save-parameter]");
      if (saveButton && content.contains(saveButton)) {
        prepareWrite(saveButton.dataset.saveParameter);
        return;
      }
      const switchButton = target.closest("[data-switch-parameter]");
      if (switchButton && content.contains(switchButton)) {
        prepareWrite(switchButton.dataset.switchParameter, switchButton.dataset.switchValue === "true");
        return;
      }
      const quickButton = target.closest("[data-quick-parameter]");
      if (quickButton && content.contains(quickButton)) {
        prepareWrite(quickButton.dataset.quickParameter, undefined, true);
        return;
      }
      const viewButton = target.closest("[data-open-view]");
      if (viewButton && content.contains(viewButton)) {
        switchView(viewButton.dataset.openView);
        return;
      }
      const hoursButton = target.closest("[data-history-hours]");
      if (hoursButton && content.contains(hoursButton)) {
        state.historyHours = Number(hoursButton.dataset.historyHours);
        render();
        return;
      }
      const seriesButton = target.closest("[data-series-toggle]");
      if (seriesButton && content.contains(seriesButton)) {
        const key = seriesButton.dataset.seriesToggle;
        if (state.hiddenSeries.has(key)) state.hiddenSeries.delete(key); else state.hiddenSeries.add(key);
        localStorage.setItem("plumbox_hidden_series", JSON.stringify([...state.hiddenSeries]));
        document.querySelectorAll(`[data-series-toggle="${CSS.escape(key)}"]`).forEach((item) => item.classList.toggle("off", state.hiddenSeries.has(key)));
        const overviewCanvas = $("overviewHistoryCanvas");
        if (overviewCanvas?.__chartArgs) paintLineChart(overviewCanvas, null);
        const historyCanvas = $("historyChart");
        if (historyCanvas?.__chartArgs) paintLineChart(historyCanvas, null);
      }
    });

    content.addEventListener("input", (event) => {
      const input = event.target;
      if (input instanceof HTMLInputElement && input.matches(".parameter-card input[type='number']")) {
        rememberDraft(input);
      }
      if (input instanceof HTMLInputElement && input.id === "parameterSearch") {
        const query = input.value;
        content.innerHTML = allHtml(query);
        $("parameterSearch")?.focus();
      }
    });

    content.addEventListener("change", (event) => {
      const input = event.target;
      if (input instanceof HTMLInputElement && input.matches(".parameter-card input[type='number']")) {
        rememberDraft(input);
      } else if (input instanceof HTMLSelectElement && input.matches(".parameter-card select")) {
        state.parameterDrafts.set(input.id.replace(/^input-/, ""), input.value);
      }
    });
  }

  async function loadOverviewExtras() {
    const age = Date.now() - state.overviewExtrasLoadedAt;
    if (state.overviewExtrasLoading || age < 15000) {
      drawOverviewHistoryChart();
      renderOverviewAlarms();
      return;
    }
    state.overviewExtrasLoading = true;
    const [history, alarms, summary] = await Promise.all([
      api("/api/history?hours=24&limit=400").catch(() => ({ rows: [] })),
      api("/api/alarms?limit=5").catch(() => ({ rows: [] })),
      api("/api/summary").catch(() => ({ fuel_today_kg: null })),
    ]);
    state.overviewHistory = history.rows || [];
    appendOverviewTemperatureSample();
    state.alarmRows = alarms.rows || [];
    state.fuelToday = finiteNumber(summary.fuel_today_kg);
    state.overviewExtrasLoading = false;
    state.overviewExtrasLoadedAt = Date.now();
    const fuelTarget = $("fuelTodayValue");
    if (fuelTarget) fuelTarget.textContent = fmt(state.fuelToday, 1);
    drawOverviewHistoryChart();
    renderOverviewAlarms();
  }

  function renderOverviewAlarms() {
    const target = $("overviewAlarmList");
    if (!target) return;
    const current = state.snapshot?.alerts || [];
    const rows = [...current, ...state.alarmRows].slice(0, 3);
    const html = rows.length ? rows.map((alarm, index) => {
      const date = new Date(alarm.from || alarm.started_at || Date.now());
      const time = Number.isNaN(date.getTime()) ? "—" : date.toLocaleString("pl-PL");
      const icon = index === 0 ? "⚠" : index === 1 ? "△" : "ℹ";
      return `<div class="alarm-item"><div class="alarm-icon">${icon}</div><div><strong>${escapeHtml(alarm.name || `Alarm ${alarm.code}`)}</strong><span>${escapeHtml(time)}</span></div><div class="alarm-duration">${alarm.active ? "AKTYWNY" : "Zakończony"}</div></div>`;
    }).join("") : `<div class="alarm-item"><div class="alarm-icon">✓</div><div><strong>Brak alarmów</strong><span>Sterownik nie zgłasza aktywnych zdarzeń.</span></div><div></div></div>
`;
    // Podmiana listy tylko przy realnej zmianie treści — bez tego lista
    // migała przy każdym odświeżeniu Podglądu.
    if (target.__lastHtml === html) return;
    target.__lastHtml = html;
    target.innerHTML = html;
  }

  function drawOverviewHistoryChart(force = false) {
    const canvas = $("overviewHistoryCanvas");
    if (!canvas) return;
    // Wykres rysujemy tylko dla nowych danych (albo po resize/zmianie motywu);
    // przerysowywanie tych samych danych co sekundę powodowało miganie.
    const stamp = String(state.overviewExtrasLoadedAt) + "|" + String(state.overviewHistoryRevision)
      + "|" + (document.documentElement.dataset.theme || "dark");
    if (!force && canvas.dataset.drawnFor === stamp) return;
    canvas.dataset.drawnFor = stamp;
    drawLineChart(canvas, state.overviewHistory, overviewChartSeries(), true);
  }

  function drawMainHistoryChart() {
    const canvas = $("historyChart");
    if (!canvas) return;
    drawLineChart(canvas, state.historyRows, chartSeries(), false);
  }

  function drawLineChart(canvas, rows, series, compact) {
    // Serie ukryte kliknięciem w legendę nie są rysowane ani pokazywane w tooltipie.
    canvas.__chartArgs = { rows, series, compact };
    paintLineChart(canvas, null);
    if (!canvas.__hoverBound) { canvas.__hoverBound = true; bindChartHover(canvas); }
  }

  function paintLineChart(canvas, hoverIndex, hoverKey = null) {
    const { rows, series, compact } = canvas.__chartArgs;
    const visible = series.filter(([key]) => !state.hiddenSeries.has(key));
    const rect = canvas.getBoundingClientRect();
    const ratio = window.devicePixelRatio || 1;
    canvas.width = Math.max(300, Math.round(rect.width * ratio));
    canvas.height = Math.max(160, Math.round(rect.height * ratio));
    const ctx = canvas.getContext("2d");
    ctx.setTransform(ratio,0,0,ratio,0,0);
    const width = rect.width, height = rect.height;
    const pad = compact ? { left:38,right:8,top:28,bottom:22 } : { left:48,right:12,top:30,bottom:30 };
    const plotW = width - pad.left - pad.right, plotH = height - pad.top - pad.bottom;
    canvas.__layout = null;
    ctx.clearRect(0,0,width,height);
    ctx.strokeStyle = cssColor("--chart-grid", "rgba(255,255,255,.08)");
    ctx.fillStyle = cssColor("--chart-ink", "#89949d");
    ctx.font = compact ? "600 11px system-ui" : "600 12px system-ui";
    const values = [];
    visible.forEach(([key]) => rows.forEach((row) => { const number = finiteNumber(row[key]); if (number !== null) values.push(number); }));
    if (values.length < 2) { ctx.fillText("Brak danych", pad.left + 10, pad.top + 20); return; }
    const min = Math.floor((Math.min(...values) - 5) / 10) * 10;
    const max = Math.ceil((Math.max(...values) + 5) / 10) * 10;
    const range = Math.max(1,max-min);
    canvas.__layout = { pad, plotW, plotH, min, range };
    ctx.fillText("°C", 3, 14);
    for (let i=0;i<=3;i++) { const y=pad.top+plotH*i/3; ctx.beginPath(); ctx.moveTo(pad.left,y); ctx.lineTo(width-pad.right,y); ctx.stroke(); ctx.fillText(String(Math.round(max-range*i/3)),3,y+4); }
    // Przy najeździe wyróżniamy tylko serię najbliższą kursorowi:
    // pozostałe są przygaszone, kropka i dymek dotyczą jednej linii.
    visible.forEach(([key,color]) => { ctx.globalAlpha = hoverKey && key !== hoverKey ? 0.25 : 1; ctx.strokeStyle=color; ctx.lineWidth=(hoverKey === key ? 1 : 0) + (compact?2:2.5); ctx.beginPath(); let started=false; rows.forEach((row,index)=>{ const number=finiteNumber(row[key]); if(number===null)return; const x=pad.left+plotW*index/Math.max(1,rows.length-1); const y=pad.top+plotH-((number-min)/range)*plotH; if(!started){ctx.moveTo(x,y);started=true;}else ctx.lineTo(x,y);}); ctx.stroke(); });
    ctx.globalAlpha = 1;
    if (hoverIndex !== null && hoverIndex >= 0 && hoverIndex < rows.length) {
      const x = pad.left + plotW * hoverIndex / Math.max(1, rows.length - 1);
      ctx.strokeStyle = cssColor("--chart-ink", "#89949d");
      ctx.lineWidth = 1;
      ctx.setLineDash([4, 4]);
      ctx.beginPath(); ctx.moveTo(x, pad.top); ctx.lineTo(x, pad.top + plotH); ctx.stroke();
      ctx.setLineDash([]);
      visible.forEach(([key, color]) => {
        if (hoverKey && key !== hoverKey) return;
        const number = finiteNumber(rows[hoverIndex][key]);
        if (number === null) return;
        const y = pad.top + plotH - ((number - min) / range) * plotH;
        ctx.beginPath(); ctx.arc(x, y, 4.5, 0, Math.PI * 2);
        ctx.fillStyle = color; ctx.fill();
        ctx.strokeStyle = cssColor("--bg", "#0b1017"); ctx.lineWidth = 2; ctx.stroke();
      });
    }
  }

  // Warstwa najazdu: pionowa linia + kropki na seriach + dymek z wartościami
  // najbliższej próbki. Dymek żyje obok canvasa i nie jest ruszany przez morph.
  function bindChartHover(canvas) {
    const wrap = canvas.parentElement;
    // position:relative kontenera jest w CSS (.history-wrap/.chart-wrap) —
    // styl inline zdejmowałby morph przy każdej aktualizacji Podglądu
    // i dymek pozycjonowałby się względem całej strony (poza ekranem).
    const tip = document.createElement("div");
    tip.className = "chart-tooltip hidden";
    wrap.appendChild(tip);
    const indexFromEvent = (event) => {
      const layout = canvas.__layout, args = canvas.__chartArgs;
      if (!layout || !args || args.rows.length < 2) return null;
      const rect = canvas.getBoundingClientRect();
      const x = event.clientX - rect.left;
      return clamp(Math.round((x - layout.pad.left) / Math.max(1, layout.plotW) * (args.rows.length - 1)), 0, args.rows.length - 1);
    };
    canvas.addEventListener("pointermove", (event) => {
      const index = indexFromEvent(event);
      if (index === null) return;
      const layout = canvas.__layout;
      const { rows, series } = canvas.__chartArgs;
      const visible = series.filter(([key]) => !state.hiddenSeries.has(key));
      const row = rows[index];
      const rect = canvas.getBoundingClientRect();
      const cursorY = event.clientY - rect.top;
      // Wybieramy serię najbliższą kursorowi w pionie — tylko ją wyróżniamy.
      let hovered = null, bestDistance = Infinity;
      visible.forEach(([key, color, label]) => {
        const number = finiteNumber(row[key]);
        if (number === null) return;
        const y = layout.pad.top + layout.plotH - ((number - layout.min) / layout.range) * layout.plotH;
        const distance = Math.abs(y - cursorY);
        if (distance < bestDistance) { bestDistance = distance; hovered = { key, color, label, number, y }; }
      });
      paintLineChart(canvas, index, hovered?.key ?? null);
      if (!hovered) { tip.classList.add("hidden"); return; }
      tip.innerHTML = `<div class="tip-time">${escapeHtml(formatDate(row.ts))}</div>` +
        `<div class="tip-row"><i style="--legend-color:${hovered.color}"></i>${escapeHtml(hovered.label)}<strong>${escapeHtml(fmt(hovered.number, 1))}°C</strong></div>`;
      tip.classList.remove("hidden");
      const x = event.clientX - rect.left;
      const flip = x + tip.offsetWidth + 24 > rect.width;
      tip.style.left = (flip ? Math.max(4, x - tip.offsetWidth - 14) : x + 14) + "px";
      tip.style.top = Math.round(clamp(hovered.y - tip.offsetHeight - 12, 4, rect.height - 60)) + "px";
    });
    canvas.addEventListener("pointerleave", () => {
      tip.classList.add("hidden");
      if (canvas.__chartArgs) paintLineChart(canvas, null);
    });
  }

  // Ciche uzgadnianie DOM: zamiast wymiany innerHTML (miganie całego ekranu)
  // porównujemy istniejące drzewo z nowo wygenerowanym HTML i nadpisujemy
  // wyłącznie różniące się teksty oraz atrybuty. Canvas jest pomijany
  // (rysuje go drawLineChart), a lista alarmów ma własny cykl odświeżania.
  function morphNode(live, fresh) {
    if (live.tagName !== fresh.tagName) { live.replaceWith(fresh); return; }
    if (live.tagName === "CANVAS") return;
    for (const attribute of [...live.attributes]) {
      const schemeLayoutStyle = attribute.name === "style"
        && live.classList
        && (live.classList.contains("scheme-canvas") || live.classList.contains("scheme-plant"));
      // Wysokość płótna i skala instalacji są obliczane z szerokości okna.
      // Nie wolno usuwać ich podczas każdej ramki WebSocket: chwilowe
      // zapadnięcie schematu uruchamia scroll anchoring i cofa stronę w górę.
      if (!fresh.hasAttribute(attribute.name) && !schemeLayoutStyle) live.removeAttribute(attribute.name);
    }
    for (const attribute of [...fresh.attributes]) {
      if (live.getAttribute(attribute.name) !== attribute.value) live.setAttribute(attribute.name, attribute.value);
    }
    // Sam atrybut value/selected nie aktualizuje zawsze bieżącej właściwości
    // kontrolki po wcześniejszej interakcji użytkownika. Nie nadpisujemy tylko
    // pola aktualnie edytowanego; pozostałe mają pokazać świeży odczyt kotła.
    if (live.tagName === "INPUT" && document.activeElement !== live && live.value !== fresh.value) {
      live.value = fresh.value;
    }
    if (live.tagName === "SELECT" && document.activeElement !== live && live.value !== fresh.value) {
      live.value = fresh.value;
    }
    if (live.id === "overviewAlarmList") return;
    // Kontenery wykresów mają dodatkowy element dymka (tooltip) spoza szablonu.
    if (live.classList && (live.classList.contains("history-wrap") || live.classList.contains("chart-wrap"))) return;
    morphChildNodes(live, fresh);
  }

  function morphChildNodes(live, fresh) {
    const freshNodes = [...fresh.childNodes];
    freshNodes.forEach((freshNode, index) => {
      const liveNode = live.childNodes[index];
      if (!liveNode) { live.appendChild(freshNode); return; }
      if (liveNode.nodeType === Node.TEXT_NODE && freshNode.nodeType === Node.TEXT_NODE) {
        if (liveNode.nodeValue !== freshNode.nodeValue) liveNode.nodeValue = freshNode.nodeValue;
      } else if (liveNode.nodeType === Node.ELEMENT_NODE && freshNode.nodeType === Node.ELEMENT_NODE) {
        morphNode(liveNode, freshNode);
      } else {
        liveNode.replaceWith(freshNode);
      }
    });
    while (live.childNodes.length > freshNodes.length) live.lastChild.remove();
  }

  function morphChildren(live, html) {
    const template = document.createElement("template");
    template.innerHTML = html;
    morphChildNodes(live, template.content);
  }

  const selectedAttr = (value, expected) => String(value) === expected ? " selected" : "";
  const checkedAttr = (value) => value ? " checked" : "";

  function communicationNativeHtml(data) {
    const passwordHint = data.mqtt_password_configured ? "pozostaw puste, aby zachować obecne" : "hasło brokera";
    return `<div class="native-admin" data-native-admin="communication">
      <div class="native-notice hidden" role="status"></div>
      <form id="nativeCommunicationForm">
        <section class="panel native-admin-section"><h3>Połączenie ecoMAX</h3>
          <div class="native-form-grid">
            <label class="native-field native-field-wide"><span>Tryb</span><select name="connection_type"><option value="simulation"${selectedAttr(data.connection_type,"simulation")}>Symulacja</option><option value="tcp"${selectedAttr(data.connection_type,"tcp")}>RS485 przez TCP</option><option value="serial"${selectedAttr(data.connection_type,"serial")}>USB-RS485</option></select></label>
            <label class="native-field"><span>Host TCP</span><input name="host" value="${escapeHtml(data.host)}"></label>
            <label class="native-field"><span>Port TCP</span><input name="port" type="number" min="1" max="65535" value="${escapeHtml(data.port)}"></label>
            <label class="native-field"><span>Port USB</span><input name="serial_device" value="${escapeHtml(data.serial_device)}"></label>
            <label class="native-field"><span>Baudrate</span><input name="baudrate" type="number" min="1" value="${escapeHtml(data.baudrate)}"></label>
          </div>
        </section>
        <section class="panel native-admin-section"><h3>Profil odczytów</h3>
          <label class="native-field"><span>Profil sterownika</span><select name="profile_mode"><option value="fixed_ecomax860p4"${selectedAttr(data.profile_mode,"fixed_ecomax860p4")}>Stały profil ecoMAX 860P4</option><option value="auto_detect"${selectedAttr(data.profile_mode,"auto_detect")}>Auto-detect</option></select></label>
        </section>
        <section class="panel native-admin-section"><h3>MQTT / Home Assistant</h3>
          <label class="native-check"><input name="mqtt_enabled" type="checkbox"${checkedAttr(data.mqtt_enabled)}><span>Włącz MQTT</span></label>
          <div class="native-form-grid">
            <label class="native-field"><span>Host brokera</span><input name="mqtt_host" value="${escapeHtml(data.mqtt_host)}"></label>
            <label class="native-field"><span>Port</span><input name="mqtt_port" type="number" min="1" max="65535" value="${escapeHtml(data.mqtt_port)}"></label>
            <label class="native-field"><span>Użytkownik</span><input name="mqtt_username" value="${escapeHtml(data.mqtt_username)}" autocomplete="username"></label>
            <label class="native-field"><span>Hasło</span><input name="mqtt_password" type="password" value="" placeholder="${escapeHtml(passwordHint)}" autocomplete="new-password"></label>
             <label class="native-field"><span>Base topic</span><input name="mqtt_base_topic" value="${escapeHtml(data.mqtt_base_topic)}"></label>
             <label class="native-check native-check-bottom"><input name="mqtt_discovery" type="checkbox"${checkedAttr(data.mqtt_discovery)}><span>Home Assistant Discovery</span></label>
            </div>
            <div class="native-form-grid">
              <label class="native-check"><input name="mqtt_commands_enabled" type="checkbox"${checkedAttr(data.mqtt_commands_enabled)}><span>Encje sterujące MQTT</span></label>
              <label class="native-check"><input name="mqtt_allow_advanced_commands" type="checkbox"${checkedAttr(data.mqtt_allow_advanced_commands)}><span>Parametry serwisowe (advanced)</span></label>
              <label class="native-check"><input name="mqtt_allow_critical_commands" type="checkbox"${checkedAttr(data.mqtt_allow_critical_commands)}><span>Parametry krytyczne</span></label>
              <label class="native-check"><input name="mqtt_allow_power_commands" type="checkbox"${checkedAttr(data.mqtt_allow_power_commands)}><span>Uruchamianie/zatrzymywanie kotła</span></label>
            </div>
            <p class="native-help">Polecenia MQTT nie używają interaktywnego PIN-u. Zabezpiecz broker osobnym kontem i ACL. PlumBox nadal wykonuje walidację, readback oraz audyt.</p>
          </section>
        <div class="native-actions"><button class="primary-button" type="submit">Zapisz konfigurację</button><span>Po zapisie uruchom ponownie usługę lub dodatek PlumBox.</span></div>
      </form>
    </div>`;
  }

  function usersNativeHtml(data) {
    const rows = (data.users || []).map((user) => `<tr>
      <td><strong>${escapeHtml(user.username)}</strong></td><td>${escapeHtml(user.display_name || "—")}</td><td>${escapeHtml(user.role || "—")}</td><td>${user.enabled ? "Tak" : "Nie"}</td>
      <td class="native-table-actions"><button class="danger-button" type="button" data-delete-user="${escapeHtml(user.username)}">Usuń</button></td>
    </tr>`).join("");
    return `<div class="native-admin" data-native-admin="users">
      <div class="native-notice hidden" role="status"></div>
      <section class="panel native-admin-section"><h3>Użytkownicy PlumBox</h3><div class="table-wrap"><table><thead><tr><th>Login</th><th>Nazwa</th><th>Rola</th><th>Aktywny</th><th></th></tr></thead><tbody>${rows || '<tr><td colspan="5">Brak użytkowników.</td></tr>'}</tbody></table></div></section>
      <div class="two-column native-admin-columns">
        <section class="panel native-admin-section"><h3>Dodaj użytkownika</h3><form id="nativeAddUserForm" class="native-form-stack">
          <label class="native-field"><span>Login</span><input name="username" required maxlength="64"></label>
          <label class="native-field"><span>Nazwa</span><input name="display_name"></label>
          <label class="native-field"><span>Hasło (min. 8 znaków)</span><input name="password" type="password" minlength="8" required autocomplete="new-password"></label>
          <label class="native-field"><span>Rola</span><select name="role"><option value="user">user</option><option value="readonly">readonly</option><option value="admin">admin</option></select></label>
          <button class="primary-button" type="submit">Dodaj</button>
        </form></section>
        <section class="panel native-admin-section"><h3>Zmień hasło użytkownika</h3><form id="nativeUserPasswordForm" class="native-form-stack">
          <label class="native-field"><span>Login</span><input name="username" required maxlength="64"></label>
          <label class="native-field"><span>Nowe hasło (min. 8 znaków)</span><input name="password" type="password" minlength="8" required autocomplete="new-password"></label>
          <button class="primary-button" type="submit">Zmień hasło</button>
        </form></section>
      </div>
    </div>`;
  }

  function accountNativeHtml(data) {
    const user = data.user || {};
    return `<div class="native-admin" data-native-admin="account">
      <div class="native-notice hidden" role="status"></div>
      <section class="panel native-admin-section"><h3>Moje konto</h3>
        <p class="native-account-summary">Zalogowano jako <strong>${escapeHtml(user.username || "—")}</strong> · rola: <strong>${escapeHtml(user.role || "—")}</strong></p>
        <form id="nativeAccountPasswordForm" class="native-form-stack native-account-form">
          <label class="native-field"><span>Obecne hasło</span><input name="old_password" type="password" required autocomplete="current-password"></label>
          <label class="native-field"><span>Nowe hasło (min. 8 znaków)</span><input name="new_password" type="password" minlength="8" required autocomplete="new-password"></label>
          <label class="native-field"><span>Powtórz nowe hasło</span><input name="repeat_password" type="password" minlength="8" required autocomplete="new-password"></label>
          <button class="primary-button" type="submit">Zmień hasło</button>
        </form>
        <p class="native-help">Po zmianie pozostałe zalogowane przeglądarki tego konta zostaną wylogowane.</p>
      </section>
    </div>`;
  }

  function setNativeNotice(root, message, error = false) {
    const notice = root?.querySelector(".native-notice");
    if (!notice) return;
    notice.textContent = message || "";
    notice.classList.toggle("hidden", !message);
    notice.classList.toggle("error", Boolean(error));
  }

  function numberFromForm(form, name) {
    const value = Number(new FormData(form).get(name));
    return Number.isFinite(value) ? value : 0;
  }

  function bindNativeAdminEvents(view) {
    const root = content.querySelector(`[data-native-admin="${view}"]`);
    if (!root) return;
    if (view === "communication") {
      const form = root.querySelector("#nativeCommunicationForm");
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const data = new FormData(form);
        const button = event.submitter;
        if (button) button.disabled = true;
        try {
          const result = await api("/api/native-admin/communication", {method:"PUT", body:JSON.stringify({
            connection_type:data.get("connection_type"), host:data.get("host"), port:numberFromForm(form,"port"), serial_device:data.get("serial_device"), baudrate:numberFromForm(form,"baudrate"), profile_mode:data.get("profile_mode"),
             mqtt_enabled:form.elements.mqtt_enabled.checked, mqtt_host:data.get("mqtt_host"), mqtt_port:numberFromForm(form,"mqtt_port"), mqtt_username:data.get("mqtt_username"), mqtt_password:data.get("mqtt_password"), mqtt_base_topic:data.get("mqtt_base_topic"), mqtt_discovery:form.elements.mqtt_discovery.checked,
             mqtt_commands_enabled:form.elements.mqtt_commands_enabled.checked, mqtt_allow_advanced_commands:form.elements.mqtt_allow_advanced_commands.checked, mqtt_allow_critical_commands:form.elements.mqtt_allow_critical_commands.checked, mqtt_allow_power_commands:form.elements.mqtt_allow_power_commands.checked,
            })});
          form.elements.mqtt_password.value = "";
          setNativeNotice(root, result.message);
          toast(result.message);
        } catch (error) { setNativeNotice(root, error.message, true); }
        finally { if (button) button.disabled = false; }
      });
    }
    if (view === "users") {
      root.querySelector("#nativeAddUserForm").addEventListener("submit", async (event) => {
        event.preventDefault(); const data = new FormData(event.currentTarget);
        try { const result = await api("/api/native-admin/users", {method:"POST",body:JSON.stringify(Object.fromEntries(data))}); toast(result.message); await loadNativeSystemView("users", true); }
        catch (error) { setNativeNotice(root, error.message, true); }
      });
      root.querySelector("#nativeUserPasswordForm").addEventListener("submit", async (event) => {
        event.preventDefault(); const data = new FormData(event.currentTarget); const username = String(data.get("username") || "");
        try { const result = await api(`/api/native-admin/users/${encodeURIComponent(username)}/password`, {method:"PUT",body:JSON.stringify({password:data.get("password")})}); event.currentTarget.reset(); setNativeNotice(root,result.message); toast(result.message); }
        catch (error) { setNativeNotice(root, error.message, true); }
      });
      root.querySelectorAll("[data-delete-user]").forEach((button) => button.addEventListener("click", async () => {
        const username = button.dataset.deleteUser;
        if (!confirm(`Usunąć użytkownika ${username}?`)) return;
        try { const result = await api(`/api/native-admin/users/${encodeURIComponent(username)}`, {method:"DELETE"}); toast(result.message); await loadNativeSystemView("users", true); }
        catch (error) { setNativeNotice(root, error.message, true); }
      }));
    }
    if (view === "account") {
      root.querySelector("#nativeAccountPasswordForm").addEventListener("submit", async (event) => {
        event.preventDefault(); const form = event.currentTarget; const data = new FormData(form);
        try { const result = await api("/api/native-admin/account/password", {method:"PUT",body:JSON.stringify(Object.fromEntries(data))}); form.reset(); setNativeNotice(root,result.message); toast(result.message); }
        catch (error) { setNativeNotice(root, error.message, true); }
      });
    }
  }

  async function loadNativeSystemView(view, force = false) {
    if (!force && content.querySelector(`[data-native-admin="${view}"]`)) return;
    content.innerHTML = `<div class="loading-card">Ładowanie…</div>`;
    try {
      const data = await api(`/api/native-admin/${view}`);
      if (state.activeView !== view) return;
      content.innerHTML = view === "communication" ? communicationNativeHtml(data) : view === "users" ? usersNativeHtml(data) : accountNativeHtml(data);
      bindNativeAdminEvents(view);
    } catch (error) {
      if (state.activeView === view) content.innerHTML = `<div class="empty-state">${escapeHtml(error.message)}</div>`;
    }
  }

  function refreshActiveSnapshotView() {
    if (state.activeView === "overview") {
      render();
      return;
    }
    if (state.activeView === "installation") {
      render();
      return;
    }
    if (!liveParameterViews.has(state.activeView)) return;
    // Mieszacz potrafi chwilowo zniknąć z pojedynczej ramki PyPlumIO podczas
    // odświeżenia/reconnectu. Jeżeli karty są już widoczne, nie zastępujemy ich
    // pustym komunikatem; następna pełna ramka zaktualizuje wartości. Stan
    // połączenia w nagłówku nadal jednoznacznie pokazuje ONLINE/OFFLINE.
    if (
      state.activeView === "mixer"
      && content.querySelector(".parameter-card")
      && parametersForSection("mixer").length === 0
    ) return;
    const html = filteredViews[state.activeView]
      ? filteredHtml(state.activeView)
      : sectionHtml(state.activeView);
    if (content.childNodes.length) morphChildren(content, html);
    else {
      content.innerHTML = html;
      bindContentEvents();
    }
  }

  async function render() {
    if (!state.snapshot) { content.innerHTML = `<div class="loading-card">Oczekiwanie na dane…</div>`; return; }
    setConnectionUi();
    $("viewTitle").textContent = titles[state.activeView] || "PLUMBOX";
    if (state.activeView === "overview") {
      const html = overviewHtml();
      if (content.querySelector(".dashboard-shell")) {
        // Struktura już istnieje: aktualizujemy w tle bez wymiany drzewa,
        // dzięki czemu ekran nie miga, a słuchacze zdarzeń zostają.
        morphChildren(content, html);
      } else {
        content.innerHTML = html;
        bindContentEvents();
      }
      setTimeout(loadOverviewExtras, 0);
      return;
    }
    if (state.activeView === "installation") {
      const scrollPositions = captureInstallationScroll();
      const html = installationSchemeHtml();
      if (content.querySelector("[data-installation-scheme]")) morphChildren(content, html);
      else content.innerHTML = html;
      fitInstallationScheme();
      restoreInstallationScroll(scrollPositions);
      requestAnimationFrame(() => {
        fitInstallationScheme();
        restoreInstallationScroll(scrollPositions);
      });
    }
    else if (["heating","water_heater","summer","mixer","kindling","supervision","burning_off","cleaning","protections"].includes(state.activeView)) content.innerHTML = sectionHtml(state.activeView);
    else if (filteredViews[state.activeView]) content.innerHTML = filteredHtml(state.activeView);
    else if (state.activeView === "alarms") content.innerHTML = await alarmsHtml();
    else if (state.activeView === "history") content.innerHTML = await historyHtml();
    else if (state.activeView === "statistics") {
      const html = await window.PlumBoxBoilerViews.statistics({api,escapeHtml,formatDate});
      if (state.activeView !== "statistics") return;
      content.innerHTML = html;
    }
    else if (state.activeView === "notifications") {
      if (content.querySelector("[data-boiler-notifications]")) return;
      try {
        const html = await window.PlumBoxBoilerViews.notifications({api,escapeHtml,formatDate});
        if (state.activeView !== "notifications") return;
        content.innerHTML = html;
        window.PlumBoxBoilerViews.bind({api,toast,render:() => {content.innerHTML=""; return render();}});
      } catch(error) { content.innerHTML = '<div class="empty-state">' + escapeHtml(error.message) + '</div>'; }
    }
    else if (state.activeView === "all") content.innerHTML = allHtml();
    else if (state.activeView === "system") content.innerHTML = await systemHtml(false);
    else if (state.activeView === "audit") content.innerHTML = await systemHtml(true);
    else if (["communication", "users", "account"].includes(state.activeView)) {
      if (USE_NATIVE_SYSTEM_V3) {
        await loadNativeSystemView(state.activeView);
      } else {
        // Zachowany fallback GPTSOL10: zmiana USE_NATIVE_SYSTEM_V3 na false
        // przywraca kompletne, stare strony administracyjne w iframe.
        const existing = content.querySelector(`iframe.embed-frame[data-embed="${state.activeView}"]`);
        if (existing) {
          applyEmbedTheme(existing);
        } else {
          content.innerHTML = `<iframe class="embed-frame" data-embed="${escapeHtml(state.activeView)}" src="${state.activeView}" title="${escapeHtml(titles[state.activeView] || "")}"></iframe>`;
          const frame = content.querySelector("iframe.embed-frame");
          frame.addEventListener("load", () => applyEmbedTheme(frame));
        }
      }
    }
    bindContentEvents();
  }

  function applyEmbedTheme(frame) {
    try {
      const doc = frame.contentDocument;
      if (doc?.documentElement) doc.documentElement.dataset.theme = document.documentElement.dataset.theme || "dark";
    } catch { /* inna domena — nie dotyczy stron PlumBox */ }
  }

  function switchView(view) {
    state.activeView = view;
    document.querySelectorAll("[data-view]").forEach((button) => button.classList.toggle("active", button.dataset.view === view));
    $("sidebar").classList.remove("open");
    window.scrollTo({ top:0, behavior:"smooth" });
    render();
  }

  async function fetchSnapshot() {
    if (state.snapshotFetchInFlight) return state.snapshotFetchInFlight;
    state.snapshotFetchInFlight = (async () => {
      try {
        state.snapshot = await api("/api/snapshot");
        state.lastSnapshotAt = Date.now();
        updateSparks();
        await render();
      } catch (error) { toast(error.message,"error"); }
      finally { state.snapshotFetchInFlight = null; }
    })();
    return state.snapshotFetchInFlight;
  }

  function connectWebSocket() {
    if (state.authExpired) return;
    const current = state.websocket;
    if (current && (current.readyState === WebSocket.OPEN || current.readyState === WebSocket.CONNECTING)) return;
    if (state.websocketReconnectTimer) {
      clearTimeout(state.websocketReconnectTimer);
      state.websocketReconnectTimer = null;
    }
    const socketUrl = new URL("ws", appBase);
    socketUrl.protocol = location.protocol === "https:" ? "wss:" : "ws:";
    const socket = new WebSocket(socketUrl);
    state.websocket = socket;
    state.lastWebsocketAt = Date.now();
    socket.addEventListener("open", () => socket.send("hello"));
    socket.addEventListener("message", (event) => {
      if (state.websocket !== socket || state.authExpired) return;
      try {
        state.snapshot = JSON.parse(event.data);
        state.lastWebsocketAt = Date.now();
        state.lastSnapshotAt = Date.now();
        updateSparks();
        appendOverviewTemperatureSample();
        setConnectionUi();
        // Podgląd aktualizuje się przy każdej ramce, ale przez ciche
        // uzgadnianie DOM (morph) — zmieniają się tylko teksty i atrybuty,
        // które faktycznie się różnią, więc nic nie miga.
        refreshActiveSnapshotView();
      } catch {}
    });
    socket.addEventListener("close", (event) => {
      if (state.websocket !== socket) return;
      state.websocket = null;
      if (event.code === 1008) checkAuth();
      if (state.authExpired) return;
      if (state.websocketReconnectTimer) clearTimeout(state.websocketReconnectTimer);
      state.websocketReconnectTimer = setTimeout(() => {
        state.websocketReconnectTimer = null;
        connectWebSocket();
      },3000);
    });
    socket.addEventListener("error", () => socket.close());
  }

  function restartWebSocket() {
    const previous = state.websocket;
    state.websocket = null;
    if (state.websocketReconnectTimer) {
      clearTimeout(state.websocketReconnectTimer);
      state.websocketReconnectTimer = null;
    }
    if (previous && (previous.readyState === WebSocket.OPEN || previous.readyState === WebSocket.CONNECTING)) {
      try { previous.close(); } catch { /* WebView może właśnie usuwać stare gniazdo */ }
    }
    connectWebSocket();
  }

  const wait = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

  async function loadInitialDataWithRetry() {
    const retryDelays = [0,500,1000,2000,4000,8000];
    while (!state.initialized && !state.authExpired) {
      const delay = retryDelays[Math.min(state.bootstrapAttempt, retryDelays.length - 1)];
      if (delay) await wait(delay);
      state.bootstrapAttempt += 1;
      if (state.bootstrapAttempt > 1) {
        content.innerHTML = `<div class="empty-state">Ponawiam połączenie z PlumBox…<br><small>Próba ${state.bootstrapAttempt}</small></div>`;
      }
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(),8000);
      try {
        const [catalog,publicConfig,snapshot] = await Promise.all([
          api("/api/catalog", { signal:controller.signal }),
          api("/api/config/public", { signal:controller.signal }),
          api("/api/snapshot", { signal:controller.signal }),
        ]);
        state.catalog = catalog;
        state.publicConfig = publicConfig;
        state.snapshot = snapshot;
        state.initialized = true;
      } catch (error) {
        if (state.authExpired) return false;
        controller.abort();
        if (state.bootstrapAttempt === 1) {
          const message = error?.name === "AbortError" ? "Przekroczono czas połączenia" : error.message;
          content.innerHTML = `<div class="empty-state">${escapeHtml(message)}<br><small>Ponawiam automatycznie…</small></div>`;
        }
      } finally {
        clearTimeout(timeout);
      }
    }
  }

  async function recoverAfterAppResume() {
    if (!state.uiReady || state.authExpired || document.visibilityState === "hidden") return;
    if (state.recoveryInFlight) return state.recoveryInFlight;
    state.recoveryInFlight = (async () => {
      // Świeży HTTP nie jest dowodem aktywności kanału WebSocket.
      const websocketUnavailable = !state.websocket || state.websocket.readyState !== WebSocket.OPEN;
      const websocketStale = Date.now() - state.lastWebsocketAt > 6000;
      if (websocketUnavailable || websocketStale) restartWebSocket();
      await Promise.all([fetchSnapshot(), checkAuth()]);
      if (!state.authExpired) await render();
    })().finally(() => { state.recoveryInFlight = null; });
    return state.recoveryInFlight;
  }

  function installAppResumeRecovery() {
    const recover = () => { recoverAfterAppResume(); };
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible") recover();
    });
    window.addEventListener("pageshow", recover);
    window.addEventListener("focus", recover);
    window.addEventListener("online", recover);
  }

  async function init() {
    initTheme();
    updateClock(); setInterval(updateClock,1000);
    installAppResumeRecovery();
    if ("serviceWorker" in navigator) navigator.serviceWorker.register("service-worker.js").catch(() => {});
    await loadInitialDataWithRetry();
    if (state.authExpired || !state.initialized) return;
    state.lastSnapshotAt = Date.now();
    updateSparks(); appendOverviewTemperatureSample(); await checkAuth(); await render(); connectWebSocket();
    // Tylko elementy z data-view przełączają widok SPA; linki <a class="nav-item">
    // (Komunikacja, Użytkownicy, Konto, Wyloguj) nawigują normalnie.
    document.querySelectorAll(".nav-item[data-view],.mobile-nav-item[data-view]").forEach((button) => button.addEventListener("click", () => switchView(button.dataset.view)));
    document.querySelector('.mobile-nav-item[data-action="menu"]').addEventListener("click", () => $("sidebar").classList.add("open"));
    $("menuButton").addEventListener("click", () => $("sidebar").classList.toggle("open"));
    document.addEventListener("pointerdown", (event) => {
      const sidebar = $("sidebar");
      if (!sidebar.classList.contains("open") || window.innerWidth > 1024) return;
      const target = event.target instanceof Element ? event.target : event.target?.parentElement;
      if (!target || sidebar.contains(target) || $("menuButton").contains(target) || target.closest('.mobile-nav-item[data-action="menu"]')) return;
      sidebar.classList.remove("open");
    });
    document.querySelectorAll("[data-theme-set]").forEach((button) => button.addEventListener("click", () => applyTheme(button.dataset.themeSet)));
    for (const id of ["lockButton", "topLockButton"]) {
      $(id).addEventListener("click", async () => {
        if (!await checkAuth()) return;
        if (state.unlocked) await lock(); else showUnlock();
      });
    }
    $("unlockCancelButton").addEventListener("click", () => $("unlockDialog").close());
    // Jedynym przyciskiem submit jest „Odblokuj", więc Enter w polu PIN
    // uruchamia dokładnie tę samą ścieżkę co kliknięcie przycisku.
    $("unlockForm").addEventListener("submit", async (event) => { event.preventDefault(); try { await unlock($("pinInput").value); $("unlockDialog").close(); render(); } catch (error) { $("unlockError").textContent = error.message; } });
    $("confirmCheckbox").addEventListener("change", (event) => $("confirmButton").disabled = !event.target.checked);
    const resetConfirmState = () => { state.pendingWrite = null; $("confirmCheckbox").checked = false; $("confirmButton").disabled = true; };
    $("confirmCancelButton").addEventListener("click", () => { resetConfirmState(); $("confirmDialog").close(); });
    $("confirmDialog").addEventListener("close", resetConfirmState);
    $("confirmForm").addEventListener("submit", async (event) => { event.preventDefault(); if (!$("confirmCheckbox").checked || !state.pendingWrite) return; const write = state.pendingWrite; state.pendingWrite = null; $("confirmDialog").close(); await executeWrite(write, true); });
    window.addEventListener("resize", () => {
      if (state.activeView === "overview") drawOverviewHistoryChart(true);
      if (state.activeView === "history") drawMainHistoryChart();
      if (state.activeView === "installation") fitInstallationScheme();
    });
    setInterval(() => {
      if (state.authExpired || document.visibilityState === "hidden") return;
      if (state.pinExpiresAt && Date.now() >= state.pinExpiresAt) {
        clearControlAccess({ forgetToken: true });
        render();
      }
      const websocketStale = Date.now() - state.lastWebsocketAt > 6000;
      if (state.websocket?.readyState !== WebSocket.OPEN || websocketStale) {
        if (websocketStale) restartWebSocket();
        fetchSnapshot();
      }
      if (state.activeView === "statistics") render().catch(() => {});
      if (Date.now() - state.authCheckedAt > 30000) {
        const previousAccess = `${state.role}:${state.unlocked}`;
        checkAuth().then(() => { if (!state.authExpired && previousAccess !== `${state.role}:${state.unlocked}`) render(); });
      }
    },5000);
    state.uiReady = true;
  }

  init();
})();

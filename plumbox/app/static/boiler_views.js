/* Statystyki i powiadomienia: niezależna warstwa widoku PlumBox. */
(() => {
  "use strict";
  let notificationData = null;
  function duration(seconds) {
    if (seconds === null || seconds === undefined) return "—";
    const n = Math.max(0, Math.floor(Number(seconds) || 0));
    return Math.floor(n / 3600) + " h " + Math.floor(n % 3600 / 60) + " min " + n % 60 + " s";
  }
  async function statistics({api, escapeHtml:esc, formatDate:date}) {
    const data = await api("/api/boiler/cycles");
    const c = data.current;
    const last = data.last;
    const card = (label, value) => '<div class="summary-card"><span>' + esc(label) + '</span><strong>' + esc(value) + '</strong></div>';
    let note = data.error || (data.simulation
      ? "W symulacji nie zapisujemy cykli kotła ani nie wysyłamy alarmów."
      : !data.fresh ? "Brak świeżego odczytu. Licznik nie uzupełnia przerwy zgadywanymi danymi."
      : "Cykl trwa od rozpoczęcia rozpalania do wyłączenia albo postoju po wygaszaniu. Samo wygaszanie nie zatrzymuje licznika.");
    return '<section class="panel"><h2>Statystyki cykli kotła</h2><p>' + esc(note) + '</p></section>' +
      '<div class="summary-grid">' +
      card("Bieżący cykl", c ? c.started_at ? duration(c.duration_seconds) : "Początek nieznany" : "Brak aktywnego cyklu") +
      card("Rozpoczęcie", c ? date(c.started_at || c.observed_since) : "—") +
      card("Ostatni cykl", last ? duration(last.duration_seconds) : "—") +
      card("Potwierdzone rozpalenia dzisiaj", data.starts_today) +
      card("Potwierdzone rozpalenia w miesiącu", data.starts_month) +
      card("Zaobserwowany czas cykli dzisiaj", duration(data.observed_today_seconds)) +
      card("Zaobserwowany czas cykli w miesiącu", duration(data.observed_month_seconds)) +
      '</div>' +
      (c && (!c.started_at || c.has_gap) ? '<div class="warning-strip">Bieżący cykl ma nieznany początek lub lukę w odczytach. Zaobserwowany czas: ' + esc(duration(c.observed_seconds)) + '.</div>' : '') +
      '';
  }
  async function notifications({api, escapeHtml:esc, formatDate:date}) {
    const data = await api("/api/boiler/notifications");
    notificationData = data;
    const cfg = data.settings;
    const check = (name, label) => '<label class="native-check"><input type="checkbox" name="' + name + '"' + (cfg[name] ? ' checked' : '') + '> ' + esc(label) + '</label>';
    const selected = cfg.targets || (cfg.target ? [cfg.target] : []);
    const choices = [...new Set([...data.targets, ...selected])];
    const options = choices.map(target => '<label class="native-check"><input type="checkbox" name="targets" value="' + esc(target) + '"' + (selected.includes(target) ? ' checked' : '') + '> ' + esc(target.replace(/^mobile_app_/, "") + (data.targets.includes(target) ? "" : " — niedostępny")) + '</label>').join("");
    const statuses = {pending:"Oczekuje",sent:"Przyjęte przez HA",failed:"Błąd",cancelled:"Anulowane"};
    const rows = data.recent.map(row => '<tr><td>' + esc(date(row.ts)) + '</td><td>' + esc(row.message) + '</td><td>' + esc(statuses[row.status] || row.status) + '</td><td>' + esc(row.error || "—") + '</td></tr>').join("");
    return '<div class="native-admin" data-boiler-notifications><section class="panel"><h2>Powiadomienia na telefon</h2><p>Zaznacz jeden lub kilka telefonów z aplikacją Home Assistant. Powiadomienia działają w tle, także po zamknięciu panelu PlumBox.</p>' +
      (data.error ? '<div class="warning-strip">' + esc(data.error) + '</div>' : '') +
      '<form id="boilerNotificationsForm" class="native-form-stack">' +
      check("enabled","Włącz powiadomienia") +
      '<fieldset class="panel" style="min-width:0;margin:0"><legend>Telefony — wybierz odbiorców</legend><div class="native-form-grid">' + (options || '<p>Brak telefonów zarejestrowanych w Home Assistant.</p>') + '</div></fieldset>' +
      '<div class="native-form-grid">' + check("start","Rozpoczęcie rozpalania") + check("extinguishing","Rozpoczęcie wygaszania") + check("finished","Zakończenie cyklu") + check("alarms","Alarmy zgłoszone przez sterownik") + '</div>' +
      check("communication", "Utrata i odzyskanie łączności z kotłem") +
      '<label class="native-field">Brak aktualnych odczytów przez [s]<input name="communication_delay_seconds" type="number" min="30" max="1800" step="1" value="' + esc(cfg.communication_delay_seconds ?? 120) + '"></label>' +
      check("quiet_hours_enabled", "Godziny ciszy dla informacji o cyklu") +
      '<div class="native-form-grid"><label class="native-field">Cisza od<input name="quiet_hours_start" type="time" value="' + esc(cfg.quiet_hours_start || "22:00") + '"></label><label class="native-field">Cisza do<input name="quiet_hours_end" type="time" value="' + esc(cfg.quiet_hours_end || "07:00") + '"></label></div>' +
      '<p>Godziny ciszy dotyczą rozpalania, wygaszania i zakończenia cyklu. Alarmy, temperatura i łączność są zgłaszane całą dobę. Strefa czasu: Europe/Warsaw.</p>' +
      '<label class="native-field">Próg ostrzegawczy temperatury podajnika [°C]<input name="temperature_threshold" type="number" min="0.1" max="500" step="0.1" placeholder="Puste = bez własnego progu" value="' + esc(cfg.temperature_threshold === null ? "" : cfg.temperature_threshold) + '"></label>' +
      '<p>Własny próg służy do ostrzegania. Alarmy sterownika są odczytywane niezależnie; próg nie zmienia ustawień kotła.</p>' +
      '<div class="native-form-grid"><label class="native-field">Przekroczenie przez [s]<input name="threshold_hold_seconds" type="number" min="0" max="300" step="1" value="' + esc(cfg.threshold_hold_seconds) + '"></label><label class="native-field">Spadek temperatury do ponownego uzbrojenia [°C]<input name="temperature_hysteresis" type="number" min="0.1" max="50" step="0.1" value="' + esc(cfg.temperature_hysteresis) + '"></label></div>' +
      '<div class="native-actions"><button type="submit" class="primary-button">Zapisz ustawienia</button><button type="button" id="boilerNotificationTest" class="secondary-button"' + (!selected.length || !data.available ? ' disabled' : '') + '>Wyślij test na wybrane telefony</button></div>' +
      '<p id="boilerNotificationNotice" role="status"></p></form></section>' +
      '<section class="panel"><h3>Ostatnie powiadomienia</h3><div class="table-wrap"><table><thead><tr><th>Czas</th><th>Treść</th><th>Wysyłka</th><th>Informacja</th></tr></thead><tbody>' + (rows || '<tr><td colspan="4">Brak wysłanych powiadomień.</td></tr>') + '</tbody></table></div></section></div>';
  }
  function bind({api, toast, render}) {
    const form = document.getElementById("boilerNotificationsForm");
    if (!form || form.dataset.bound) return;
    form.dataset.bound = "true";
    form.addEventListener("submit", async event => {
      event.preventDefault();
      const data = new FormData(form);
      const settings = {};
      ["enabled","start","extinguishing","finished","alarms","communication","quiet_hours_enabled"].forEach(k => { settings[k] = data.has(k); });
      settings.targets = data.getAll("targets").map(String);
      settings.communication_delay_seconds = Number(data.get("communication_delay_seconds"));
      settings.quiet_hours_start = String(data.get("quiet_hours_start"));
      settings.quiet_hours_end = String(data.get("quiet_hours_end"));
      settings.temperature_threshold = data.get("temperature_threshold") === "" ? null : Number(data.get("temperature_threshold"));
      settings.threshold_hold_seconds = Number(data.get("threshold_hold_seconds"));
      settings.temperature_hysteresis = Number(data.get("temperature_hysteresis"));
      const button = form.querySelector('[type="submit"]');
      button.disabled = true;
      try {
        const result = await api("/api/boiler/notifications", {method:"PUT",body:JSON.stringify(settings)});
        toast(result.message,"success"); await render();
      } catch (error) { document.getElementById("boilerNotificationNotice").textContent=error.message; }
      finally { button.disabled=false; }
    });
    document.getElementById("boilerNotificationTest").addEventListener("click", async event => {
      event.currentTarget.disabled=true;
      try { const result=await api("/api/boiler/notifications/test",{method:"POST"}); toast(result.message,"success"); }
      catch(error) { toast(error.message,"error"); }
      finally { const button=document.getElementById("boilerNotificationTest"); if(button)button.disabled=!notificationData?.available; }
    });
  }
  window.PlumBoxBoilerViews={statistics,notifications,bind,duration};
})();

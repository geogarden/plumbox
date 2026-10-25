/* Boiler-work plan adapted to PlumBox from geogarden/ecomax-esp32-gateway.
   The controller owns the schedule; no browser/HA timer turns the boiler on/off. */
((root) => {
  "use strict";
  const days = ["Poniedziałek", "Wtorek", "Środa", "Czwartek", "Piątek", "Sobota", "Niedziela"];
  const shortDays = ["Pn", "Wt", "Śr", "Cz", "Pt", "So", "Nd"];
  const clock = slot => `${String(Math.floor(slot / 2)).padStart(2, "0")}:${slot % 2 ? "30" : "00"}`;
  const copy = value => JSON.parse(JSON.stringify(value));
  const validWeek = week => Array.isArray(week) && week.length === 7 && week.every(day => Array.isArray(day) && day.length === 48 && day.every(slot => typeof slot === "boolean"));
  function paintRange(week, day, from, to, on) {
    if (!validWeek(week) || !Number.isInteger(day) || day < 0 || day > 6 || !Number.isInteger(from) || !Number.isInteger(to) || from < 0 || to > 48 || from >= to || typeof on !== "boolean") throw new Error("Wybierz prawidłowy przedział co 30 minut.");
    const result = copy(week);
    for (let slot = from; slot < to; slot++) result[day][slot] = on;
    return result;
  }
  function ranges(row) {
    const result = [];
    for (let slot = 0; slot < 48; slot++) if (row[slot]) {
      const start = slot;
      while (slot + 1 < 48 && row[slot + 1]) slot++;
      result.push(`${clock(start)}–${clock(slot + 1)}`);
    }
    return result.join(", ") || "brak";
  }
  if (typeof module !== "undefined" && module.exports) { module.exports = {validWeek, paintRange, ranges, clock}; return; }
  let ctx, element, base = null, draft = null, busy = false, conflict = false, uncertain = false, readAt = 0, lastAttempt = 0, generation = 0;
  const q = id => element?.querySelector(`#${id}`);
  const active = () => ctx?.isActive() && element?.isConnected;
  const dirty = () => draft && base && (JSON.stringify(draft.week) !== JSON.stringify(base.week) || draft.enabled !== base.enabled);
  const fresh = () => base?.available && Date.now() - readAt < 65000 && ctx.access().connected;
  function message(text, error = false) {
    const node = q("workScheduleStatus");
    if (node) { node.textContent = text; node.classList.toggle("schedule-error", error); }
  }
  function update() {
    if (!active()) return;
    const access = ctx.access(), admin = access.role === "admin";
    const editable = fresh() && admin && !busy && !conflict && !uncertain;
    element.querySelectorAll("[data-schedule-edit]").forEach(input => { input.disabled = !editable; });
    q("workScheduleSave").disabled = !editable || !dirty();
    q("workScheduleCancel").disabled = busy || !dirty();
    q("workScheduleRead").disabled = busy;
    q("workScheduleSave").textContent = access.unlocked ? "Zapisz harmonogram" : "Odblokuj PIN i zapisz";
    q("workScheduleAccess").textContent = !access.connected ? "Brak połączenia ze sterownikiem." : !admin ? "Podgląd. Zapis wymaga konta administratora." : !access.unlocked ? "Zapis wymaga odblokowania sterowania PIN-em." : "Zapis do sterownika wymaga potwierdzenia.";
    q("workScheduleEnabled").checked = !!draft?.enabled;
    q("workScheduleGrid").classList.toggle("schedule-stale", !fresh());
    if (!base && !busy) return;
    if (uncertain) message("Zapis niepotwierdzony. Odczytaj plan ponownie przed kolejną zmianą.", true);
    else if (conflict) message("Plan zmieniono poza formularzem. Odczytaj ponownie lub anuluj zmiany.", true);
    else if (!busy && base && !fresh()) message("Brak aktualnego odczytu. Odczytaj harmonogram ponownie.", true);
    else if (!busy && dirty()) message("Niezapisane zmiany");
  }
  function draw() {
    if (!active()) return;
    const container = q("workScheduleGrid"); container.replaceChildren();
    for (let d = 0; d < 7; d++) {
      const row = document.createElement("div"); row.className = "schedule-week-row";
      row.classList.toggle("schedule-selected-day", d === Number(q("workScheduleDay").value));
      const label = document.createElement("span"); label.className = "schedule-day"; label.textContent = shortDays[d];
      const strip = document.createElement("div"); strip.className = "schedule-slots"; strip.setAttribute("role", "img");
      const slots = draft?.week?.[d];
      strip.setAttribute("aria-label", slots ? `${days[d]}: praca dozwolona ${ranges(slots)}` : `${days[d]}: brak odczytu`);
      for (let s = 0; s < 48; s++) { const cell = document.createElement("span"); cell.className = `schedule-slot${slots ? slots[s] ? " schedule-on" : " schedule-off" : " schedule-unknown"}`; cell.setAttribute("aria-hidden", "true"); strip.append(cell); }
      row.append(label, strip); container.append(row);
    }
    const selected = Number(q("workScheduleDay").value);
    q("workScheduleIntervals").textContent = draft ? `${days[selected]} — praca dozwolona: ${ranges(draft.week[selected])}` : "";
    update();
  }
  async function read(force = false, discard = false) {
    if (!active() || busy) return;
    const ticket = generation; busy = true; lastAttempt = Date.now(); update(); message("Odczytywanie harmonogramu…");
    try {
      const data = await ctx.api(`/api/work-schedule${force ? "?refresh=true" : ""}`);
      if (ticket !== generation || !active()) return;
      if (!data.available || !validWeek(data.week) || typeof data.enabled !== "boolean" || !/^[a-f0-9]{64}$/.test(data.revision || "")) throw new Error(data.message || "Brak prawidłowego harmonogramu.");
      if (!discard && dirty() && data.revision !== base.revision) conflict = true;
      else if (discard || !dirty()) { base = data; draft = copy(data); conflict = false; uncertain = false; }
      readAt = Date.now();
      q("workScheduleReadAt").textContent = `Odczyt ze sterownika: ${new Date(data.read_at * 1000).toLocaleTimeString("pl-PL")}`;
      message(dirty() ? "Niezapisane zmiany" : "Odczytano harmonogram ze sterownika.");
    } catch (error) { if (ticket === generation && active()) { readAt = 0; message(error.message, true); } }
    finally { if (ticket === generation) { busy = false; draw(); } }
  }
  function html() {
    const options = (start, end, selected) => Array.from({length: end - start + 1}, (_, i) => `<option value="${i + start}"${i + start === selected ? " selected" : ""}>${clock(i + start)}</option>`).join("");
    return `<section class="schedule-page" data-work-schedule><div class="schedule-heading"><h2>Tygodniowy plan pracy kotła</h2><button type="button" class="secondary-button" id="workScheduleRead">Odczytaj ponownie</button></div>
      <div class="schedule-panel"><div class="schedule-plan-state"><label class="schedule-enabled"><input type="checkbox" id="workScheduleEnabled" data-schedule-edit> Harmonogram włączony</label><span id="workScheduleReadAt"></span></div>
      <div class="schedule-legend"><span><i class="schedule-swatch schedule-on"></i>Praca dozwolona</span><span><i class="schedule-swatch schedule-off"></i>Przerwa</span><span>1 pole = 30 minut</span></div>
      <div class="schedule-axis" aria-hidden="true"><span>00:00</span><span>06:00</span><span>12:00</span><span>18:00</span><span>24:00</span></div><div id="workScheduleGrid"></div>
      <div class="schedule-editor"><label>Dzień<select id="workScheduleDay">${days.map((day, i) => `<option value="${i}">${day}</option>`).join("")}</select></label><label>Od<select id="workScheduleFrom" data-schedule-edit>${options(0, 47, 12)}</select></label><label>Do<select id="workScheduleTo" data-schedule-edit>${options(1, 48, 44)}</select></label><label>Stan<select id="workScheduleState" data-schedule-edit><option value="1">Praca dozwolona</option><option value="0">Przerwa</option></select></label><button type="button" class="secondary-button" id="workScheduleApply" data-schedule-edit>Ustaw przedział</button></div>
      <div class="schedule-intervals" id="workScheduleIntervals"></div><div class="schedule-actions"><span id="workScheduleStatus" role="status"></span><button type="button" class="secondary-button" id="workScheduleCancel">Anuluj zmiany</button><button type="button" class="primary-button" id="workScheduleSave">Zapisz harmonogram</button></div></div>
      <p class="schedule-help">Praca dozwolona oznacza możliwość grzania przy zapotrzebowaniu, a nie ciągłe palenie. Przerwa może również ograniczać grzanie CWU. Po wyłączeniu harmonogramu godziny planu nie ograniczają pracy kotła. Zabezpieczenia sterownika pozostają aktywne.</p><p class="schedule-help" id="workScheduleAccess"></p></section>`;
  }
  async function mount(context) {
    ctx = context;
    if (context.content.querySelector("[data-work-schedule]") === element && element?.isConnected) { update(); return; }
    generation++; busy = false; base = draft = null; conflict = uncertain = false; readAt = 0;
    context.content.innerHTML = html(); element = context.content.querySelector("[data-work-schedule]");
    q("workScheduleDay").onchange = draw;
    q("workScheduleEnabled").onchange = event => { if (draft) draft.enabled = event.target.checked; update(); };
    q("workScheduleApply").onclick = () => {
      if (!fresh() || !draft) return;
      try { draft.week = paintRange(draft.week, Number(q("workScheduleDay").value), Number(q("workScheduleFrom").value), Number(q("workScheduleTo").value), q("workScheduleState").value === "1"); draw(); }
      catch (error) { message(error.message, true); }
    };
    q("workScheduleCancel").onclick = () => { draft = base ? copy(base) : null; conflict = false; message("Anulowano zmiany w formularzu."); draw(); if (!uncertain) read(true, true); };
    q("workScheduleRead").onclick = () => { if (dirty() && !window.confirm("Odrzucić niezapisane zmiany i odczytać plan ze sterownika?")) return; read(true, true); };
    q("workScheduleSave").onclick = async () => {
      if (!await ctx.checkAuth()) return;
      if (!ctx.access().unlocked) { ctx.unlock(); return; }
      if (!fresh() || busy || conflict || uncertain || !dirty()) return;
      ctx.confirm({week: copy(draft.week), enabled: draft.enabled, revision: base.revision});
    };
    draw(); await read();
  }
  async function save(payload, confirmed) {
    if (!confirmed || busy || !active()) return;
    if (!await ctx.checkAuth() || !ctx.access().unlocked) { ctx.unlock(); return; }
    if (!fresh() || conflict || uncertain) { update(); return; }
    const ticket = generation;
    busy = true; update(); message("Zapisywanie i sprawdzanie odczytu…");
    try {
      const result = await ctx.api("/api/work-schedule", {method: "PUT", body: JSON.stringify({...payload, confirmed: true})});
      if (ticket !== generation || !active()) return;
      if (result.success && result.readback_confirmed && result.schedule?.available && validWeek(result.schedule.week)) {
        base = result.schedule; draft = copy(base); readAt = Date.now(); conflict = uncertain = false;
        q("workScheduleReadAt").textContent = `Odczyt ze sterownika: ${new Date(base.read_at * 1000).toLocaleTimeString("pl-PL")}`;
      } else uncertain = true;
      message(result.message || "Zapis niepotwierdzony.", !result.success);
      ctx.toast(result.message || "Zapis niepotwierdzony.", result.success ? "success" : "warning");
    } catch (error) { if (ticket === generation && active()) { uncertain = true; message(error.message, true); ctx.toast(error.message, "error"); } }
    finally { if (ticket === generation) { busy = false; if (active()) draw(); } }
  }
  function canLeave() {
    if (busy) { ctx.toast("Poczekaj na zakończenie odczytu lub zapisu harmonogramu.", "warning"); return false; }
    return !dirty() || window.confirm("Opuścić harmonogram i odrzucić niezapisane zmiany?");
  }
  setInterval(() => { if (active()) { update(); if (!busy && !uncertain && Date.now() - lastAttempt > 30000) read(true); } }, 5000);
  root.PlumBoxWorkSchedule = {mount, save, canLeave};
})(typeof window === "undefined" ? globalThis : window);

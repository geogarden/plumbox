"""Server-rendered administration pages using Ingress-safe relative URLs."""

from __future__ import annotations

import html
from typing import Any


# Strony administracyjne są osadzane w panelu (iframe) — tło przezroczyste,
# tokeny zgodne z motywem FABLE UI; jasny wariant wg preferencji systemowej.
STYLE = """
:root{color-scheme:dark;--bg:#0b1017;--surface:#121a26;--s2:#172233;--line:rgba(148,163,184,.16);--line-soft:rgba(148,163,184,.09);
--text:#eef2f7;--strong:#fff;--muted:#92a0b3;--accent:#ff8b2d;--accent-ink:#14100a;--ok:#34c98e;--err:#ef5350}
/* Motyw narzuca panel przez data-theme na <html> ramki; media query jest
   tylko fallbackiem przy otwarciu strony bezpośrednio, poza panelem.
   Tlo jest nieprzezroczyste, bo przy niezgodnym color-scheme przegladarka
   maluje pod ramka bialy podklad i przezroczystosc nie dziala. */
:root[data-theme="light"]{color-scheme:light;--bg:#eef1f6;--surface:#fff;--s2:#f4f6fa;--line:rgba(15,23,42,.14);--line-soft:rgba(15,23,42,.07);
--text:#1a2430;--strong:#0c141d;--muted:#5b6875;--accent:#e06d00;--accent-ink:#fff;--ok:#0f8a5f;--err:#cf3d3a}
:root[data-theme="oled"]{color-scheme:dark;--bg:#07110f;--surface:#0c1916;--s2:#10211d;--line:rgba(143,167,160,.22);--line-soft:rgba(143,167,160,.12);
--text:#eff8f4;--strong:#fff;--muted:#8fa7a0;--accent:#47e6a4;--accent-ink:#052016;--ok:#47e6a4;--err:#ff6b6b}
@media(prefers-color-scheme:light){:root:not([data-theme="dark"]):not([data-theme="oled"]){color-scheme:light;--bg:#eef1f6;--surface:#fff;--s2:#f4f6fa;
--line:rgba(15,23,42,.14);--line-soft:rgba(15,23,42,.07);--text:#1a2430;--strong:#0c141d;--muted:#5b6875;
--accent:#e06d00;--accent-ink:#fff;--ok:#0f8a5f;--err:#cf3d3a}}
*{box-sizing:border-box}
html,body{min-height:100%}
body{margin:0;padding:4px 2px 24px;background:var(--bg);color:var(--text);
font-family:"Inter","Segoe UI Variable Text","Segoe UI",system-ui,sans-serif;font-size:14px;line-height:1.5}
a{color:var(--accent);font-weight:600}
h1{margin:4px 0 14px;font-size:19px;color:var(--strong)}h2{margin:22px 0 10px;font-size:14px;letter-spacing:.05em;color:var(--strong)}
.card{max-width:980px;margin:0;padding:18px;border:1px solid var(--line-soft);border-radius:16px;background:var(--surface)}
table{width:100%;border-collapse:collapse;margin:14px 0;font-size:13px}
td,th{border-bottom:1px solid var(--line-soft);padding:9px;text-align:left}
th{font-size:10.5px;font-weight:800;letter-spacing:.09em;text-transform:uppercase;color:var(--muted)}
input,select,button{padding:10px 12px;border-radius:10px;border:1px solid var(--line);background:var(--s2);color:var(--strong);font:inherit}
input:focus,select:focus{outline:none;border-color:var(--accent)}
button{cursor:pointer;background:var(--accent);color:var(--accent-ink);border:0;font-weight:800;transition:filter .15s}
button:hover{filter:brightness(1.08)}
.grid{display:grid;grid-template-columns:repeat(4,1fr) auto;gap:8px}
.ok,.err{padding:10px 14px;border-radius:10px;font-weight:600;font-size:13px}
.ok{color:var(--ok);background:color-mix(in srgb,var(--ok) 12%,transparent);border:1px solid color-mix(in srgb,var(--ok) 40%,transparent)}
.err{color:var(--err);background:color-mix(in srgb,var(--err) 10%,transparent);border:1px solid color-mix(in srgb,var(--err) 40%,transparent)}
label{display:block;margin:12px 0 5px;color:var(--muted);font-size:12px;font-weight:700}
.form-control{width:100%}.two{display:grid;grid-template-columns:1fr 1fr;gap:10px}small{color:var(--muted)}
@media(max-width:700px){.grid,.two{grid-template-columns:1fr}body{padding:2px 0 16px}}
"""


def _notice(message: str | None, error: str | None) -> str:
    success = f"<div class='ok'>{html.escape(message)}</div>" if message else ""
    failure = f"<div class='err'>{html.escape(error)}</div>" if error else ""
    return success + failure


def _shell(title: str, navigation: str, content: str) -> str:
    # Nawigacja jest opcjonalna: strony osadzone w panelu (iframe) nie powinny
    # linkować do dashboardu, bo załadowałyby całą aplikację wewnątrz ramki.
    nav_html = f"<p>{navigation}</p>" if navigation else ""
    return f"""<!doctype html><html lang='pl'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{html.escape(title)}</title><style>{STYLE}</style></head><body><main class='card'>{nav_html}{content}</main></body></html>"""


def render_users_page(users: list[dict[str, Any]], message: str | None = None, error: str | None = None) -> str:
    rows = "".join(
        f"<tr><td>{html.escape(u['username'])}</td><td>{html.escape(u.get('display_name') or '')}</td><td>{html.escape(u.get('role') or '')}</td><td>{'tak' if u.get('enabled') else 'nie'}</td><td><form method='post' action='users/delete' onsubmit='return confirm(\"Usunąć użytkownika?\")'><input type='hidden' name='username' value='{html.escape(u['username'])}'><button>Usuń</button></form></td></tr>"
        for u in users
    )
    body = f"""<h1>Użytkownicy PlumBox</h1>{_notice(message, error)}
<table><thead><tr><th>Login</th><th>Nazwa</th><th>Rola</th><th>Aktywny</th><th></th></tr></thead><tbody>{rows}</tbody></table>
<h2>Dodaj użytkownika</h2><form class='grid' method='post' action='users'><input name='username' placeholder='login'><input name='display_name' placeholder='nazwa'><input name='password' type='password' placeholder='hasło min. 8 znaków'><select name='role'><option value='user'>user</option><option value='readonly'>readonly</option><option value='admin'>admin</option></select><button>Dodaj</button></form>
<h2>Zmień hasło</h2><form class='grid' method='post' action='users/password'><input name='username' placeholder='login'><input name='password' type='password' placeholder='nowe hasło min. 8 znaków'><span></span><span></span><button>Zmień</button></form>"""
    return _shell("Użytkownicy PlumBox", "", body)


def render_account_page(user: dict[str, Any], message: str | None = None, error: str | None = None) -> str:
    username = html.escape(str(user.get("username", "")))
    role = html.escape(str(user.get("role", "")))
    body = f"""<h1>Moje konto</h1>{_notice(message, error)}
<p>Zalogowano jako <strong>{username}</strong> (rola: {role}).</p>
<h2>Zmiana hasła</h2>
<form method='post' action='account'>
<label>Obecne hasło</label><input class='form-control' name='old_password' type='password' autocomplete='current-password' required>
<label>Nowe hasło (min. 8 znaków)</label><input class='form-control' name='new_password' type='password' autocomplete='new-password' minlength='8' required>
<label>Powtórz nowe hasło</label><input class='form-control' name='repeat_password' type='password' autocomplete='new-password' minlength='8' required>
<br><br><button>Zmień hasło</button>
</form>
<small>Po zmianie pozostałe zalogowane przeglądarki tego konta zostaną wylogowane.</small>"""
    return _shell("Moje konto — PlumBox", "", body)


def render_communication_page(cfg: dict[str, Any], message: str | None = None, error: str | None = None) -> str:
    conn, mqtt, profile = cfg.get("connection", {}), cfg.get("mqtt", {}), cfg.get("profile", {})
    # Hasła brokera nie wstawiamy do value formularza — trafiałoby do źródła
    # strony przy każdym GET. Puste pole oznacza „zachowaj obecne hasło".
    password_hint = "pozostaw puste, aby nie zmieniać" if mqtt.get("password") else ""
    esc = lambda value: html.escape(str(value))
    sel = lambda value, expected: "selected" if str(value) == expected else ""
    chk = lambda value: "checked" if bool(value) else ""
    body = f"""<h1>Komunikacja i MQTT</h1>{_notice(message, error)}<form method='post' action='communication'>
<h2>Połączenie ecoMAX</h2><label>Tryb</label><select class='form-control' name='connection_type'><option value='simulation' {sel(conn.get('type'),'simulation')}>symulacja</option><option value='tcp' {sel(conn.get('type'),'tcp')}>RS485 przez TCP</option><option value='serial' {sel(conn.get('type'),'serial')}>USB-RS485</option></select>
<div class='two'><div><label>Host TCP</label><input class='form-control' name='host' value='{esc(conn.get('host','192.168.1.50'))}'></div><div><label>Port TCP</label><input class='form-control' name='port' value='{esc(conn.get('port',8899))}'></div><div><label>Port USB</label><input class='form-control' name='serial_device' value='{esc(conn.get('serial_device','/dev/ttyUSB0'))}'></div><div><label>Baudrate</label><input class='form-control' name='baudrate' value='{esc(conn.get('baudrate',115200))}'></div></div>
<h2>Profil odczytów</h2><select class='form-control' name='profile_mode'><option value='fixed_ecomax860p4' {sel(profile.get('mode'),'fixed_ecomax860p4')}>Stały profil ecoMAX 860P4</option><option value='auto_detect' {sel(profile.get('mode'),'auto_detect')}>Auto-detect</option></select>
<h2>MQTT / Home Assistant</h2><label><input type='checkbox' name='mqtt_enabled' value='1' {chk(mqtt.get('enabled'))}> Włącz MQTT</label><div class='two'><div><label>Host brokera</label><input class='form-control' name='mqtt_host' value='{esc(mqtt.get('host','127.0.0.1'))}'></div><div><label>Port</label><input class='form-control' name='mqtt_port' value='{esc(mqtt.get('port',1883))}'></div><div><label>Użytkownik</label><input class='form-control' name='mqtt_username' value='{esc(mqtt.get('username',''))}'></div><div><label>Hasło</label><input class='form-control' name='mqtt_password' type='password' value='' placeholder='{password_hint}' autocomplete='new-password'><small>Hasło nie jest odsyłane do przeglądarki; puste pole zachowuje obecne.</small></div><div><label>Base topic</label><input class='form-control' name='mqtt_base_topic' value='{esc(mqtt.get('base_topic','plumbox'))}'></div><div><label><input type='checkbox' name='mqtt_discovery' value='1' {chk(mqtt.get('home_assistant_discovery',True))}> HA Discovery</label></div></div>
<h2>Sterowanie przez MQTT</h2>
<label><input type='checkbox' name='mqtt_commands_enabled' value='1' {chk(mqtt.get('commands_enabled',True))}> Wystaw encje sterujące i odbieraj polecenia</label>
<label><input type='checkbox' name='mqtt_allow_advanced_commands' value='1' {chk(mqtt.get('allow_advanced_commands',True))}> Zezwól na parametry serwisowe (advanced)</label>
<label><input type='checkbox' name='mqtt_allow_critical_commands' value='1' {chk(mqtt.get('allow_critical_commands',False))}> Zezwól na parametry krytyczne</label>
<label><input type='checkbox' name='mqtt_allow_power_commands' value='1' {chk(mqtt.get('allow_power_commands',True))}> Zezwól na uruchamianie i zatrzymywanie kotła</label>
<small>Polecenia MQTT omijają interaktywny PIN. Użyj osobnego konta brokera i restrykcyjnego ACL. Zmiany są nadal walidowane, potwierdzane readbackiem i zapisywane w audycie.</small><br><br>
<button>Zapisz konfigurację</button><br><small>Po zapisie uruchom ponownie usługę lub dodatek PlumBox.</small></form>"""
    return _shell("Komunikacja PlumBox", "", body)

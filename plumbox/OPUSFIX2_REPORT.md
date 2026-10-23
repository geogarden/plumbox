# PlumBox OPUSFIX2

Poprawki naniesione po dodatkowej analizie Opusa. Dashboard, zakładki, CSS, logo i QR nie były ruszane.

## Zmiany względem OPUSFIX

1. Poprawione nazwy parametrów profilu P4:
   - `fan_power_100/50/30` → `airflow_power_100/50/30`,
   - `fuel_feeder_efficiency` → `max_fuel_flow` i `feeder_calibration`.
2. Ujednolicony reconnect: `reconnect_on_failure=False` w połączeniu TCP/serial. Reconnect wykonuje tylko pętla PlumBox `_run()`.
3. Usunięty sztuczny `await asyncio.sleep(0.4)` po zapisie parametru. `device.set(...)` czeka na potwierdzenie.
4. `scripts/test_connection.py` używa tego samego trybu TCP bez reconnectu wewnętrznego.

## Bez zmian

- dashboard v10 READABLE,
- układ zakładek,
- `app/static/index.html`, `styles.css`, `app.js`, `icon.svg`, `qr-plumbox.png`, manifest i service-worker,
- blokada zapisu parametrów `advanced/critical`,
- poprawka `connection.connected.is_set()`.

## Tryb paczki

`AUTO_DETECT / HA Add-on`

## Nadal do testu na żywym kotle

- realne nazwy sensorów P4 z `/api/snapshot`,
- ewentualne odblokowanie wybranych parametrów advanced po potwierdzeniu skali i zakresów.

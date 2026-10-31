# Dokumentacja PlumBox

## Proces aplikacji

PlumBox uruchamia `uvicorn app.main:app` na porcie 8080. Dashboard, API, strony administracyjne i WebSocket są obsługiwane przez tę samą aplikację FastAPI. W aktualnej wersji nie istnieje osobny proces ani trasa `/bridge/...`.

## Trasy

- panel: względny adres bazowy dodatku lub `http://HOST:8080/`,
- API: względne `api/...`,
- WebSocket: względne `ws`,
- administracja: `communication`, `users`, `change-password`,
- stan sterownika: `api/snapshot`,
- podsumowanie dobowe: `api/summary`.

Adresy względne są celowe, aby panel działał zarówno bezpośrednio, jak i pod prefiksem Home Assistant Ingress.

## Dane trwałe Home Assistant

- `/data/config.yaml` — konfiguracja,
- `/data/users.yaml` — użytkownicy,
- `/data/plumbox.db` — historia i audyt,
- `/data/initial_admin_password.txt` — jednorazowe hasło, jeżeli je wygenerowano,
- `/data/initial_pin.txt` — jednorazowy PIN, jeżeli go wygenerowano.

## Stan weryfikacji

Testy lokalne i symulator nie potwierdzają komunikacji z fizycznym ecoMAX. Dodatek ma `stage: experimental`. Parametry `advanced` i `critical` pozostają tylko do odczytu.

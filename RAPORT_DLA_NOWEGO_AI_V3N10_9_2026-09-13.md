# Raport dla nowego AI — PlumBox V3N10.9

Data: 2026-09-13

## Baza i zakres

V3N10.9 utworzono jako nowe wydanie z V3N10.8. Poprzedniej wersji nie modyfikowano. Zakres obejmuje wyłącznie odporność frontendu uruchamianego jako panel ingress w aplikacji Home Assistant na Androidzie.

## Potwierdzona przyczyna

Dotychczas `init()` pobierał równolegle `/api/catalog`, `/api/config/public` i `/api/snapshot`. Błąd dowolnego żądania wykonywał `return`, przez co panel pozostawał nieuruchomiony. Ponowne wejście zwykle działało, bo WebView, sieć i sesja ingress były już gotowe.

## Wprowadzone zmiany

1. Startowe żądania są ponawiane z opóźnieniami 0,5 / 1 / 2 / 4 / 8 sekund; kolejne próby odbywają się co 8 sekund.
2. Każda próba ma limit czasu 8 sekund dzięki `AbortController`.
3. Podczas oczekiwania panel pokazuje komunikat o automatycznym ponawianiu.
4. `visibilitychange`, `pageshow`, `focus` i `online` wywołują odzyskanie połączenia po wznowieniu aplikacji HA.
5. Odzyskanie pobiera świeży snapshot oraz odbudowuje WebSocket, jeśli jest zamknięty albo nie dostarcza danych.
6. WebSocket ma blokadę przed równoległymi instancjami i jeden śledzony timer reconnect.
7. Rewizję cache statycznego podniesiono z `gptsol-34` do `gptsol-35`.

## Elementy nietknięte funkcjonalnie

- `plum_service.py` i transport PyPlumIO,
- reconnect TCP z mostem,
- `mqtt.py` i komendy MQTT,
- mapowania oraz skale product ID 211,
- baza danych i retencja,
- autoryzacja, użytkownicy i PIN,
- schemat instalacji i wygląd dashboardu.

Porównanie SHA-256 ze źródłem V3N10.8 potwierdziło bajtową identyczność plików `plum_service.py`, `mqtt.py`, `mappings.py`, `serializer.py`, `controller_profile.py`, `database.py`, `security.py`, `users.py`, `simulator.py`, `main.py` i `deps.py`.

## Weryfikacja programowa

- składnia `app.js` i `service-worker.js`: poprawna (`node --check`),
- cztery testy regresyjne V3N10.9: zaliczone,
- cztery testy schematu instalacji: zaliczone,
- cały pakiet: 139 testów zaliczonych,
- jeden historycznie znany test `test_release_builder_syncs_every_runtime_app_file` nie działa w samym pakiecie, ponieważ oczekuje nieobecnego modułu repozytoryjnego `tools`; nie jest to regresja runtime.

Testy programowe nie symulują cyklu życia Android WebView ani sesji ingress. Ostateczne potwierdzenie wymaga próby w aplikacji Home Assistant na telefonie.

## Test na telefonie

Po instalacji sprawdzić panel PlumBox w aplikacji HA:

1. po dłuższym uśpieniu telefonu,
2. bezpośrednio po przejściu z LTE na Wi-Fi,
3. po pozostawieniu HA w tle przez kilka minut,
4. tuż po restarcie dodatku lub Home Assistanta.

Oczekiwane: panel może krótko pokazać `Ponawiam połączenie z PlumBox…`, ale otworzy się sam bez wychodzenia i ponownego wybierania zakładki.

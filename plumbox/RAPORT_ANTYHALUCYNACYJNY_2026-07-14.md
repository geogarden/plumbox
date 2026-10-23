# Raport antyhalucynacyjny PlumBox — 2026-07-14

## Cel

Ponowny przegląd miał znaleźć miejsca, w których panel lub dokumentacja mogły przedstawiać wartość wyliczoną, domyślną albo symulowaną tak, jakby pochodziła z fizycznego ecoMAX. Zakres objął źródło robocze, frontend, API, profile MQTT/Home Assistant, metadane dodatku oraz cztery paczki wydania.

Nie było dostępu do prawdziwego ecoMAX, RS485/TCP użytkownika, Home Assistant ani brokera MQTT. Z tego powodu nie dopisywano nowych znaczeń rejestrów i nie odblokowano zapisów `advanced/critical`.

## Wprowadzone poprawki

1. **Usunięto sztuczne wykresy z produkcyjnego dashboardu.** `app/static/app.js` nie generuje już sinusoid przy braku historii. Sparkline pokazuje „Brak historii”, a wykres temperatur „Brak danych”.
2. **Brak odczytu nie staje się zerem.** Temperatury, moc, paliwo i urządzenia używają jawnego stanu braku danych. Nieznany stan urządzenia pokazuje „BRAK DANYCH”, a nie „WYŁĄCZONA”.
3. **Naprawiono kartę „Pellet dzisiaj”.** Nie używa już `fuel_burned` ani chwilowego `fuel_consumption` jako dobowej masy. Endpoint `GET /api/summary` całkuje zapisane kg/h od lokalnej północy. Pojedynczy pomiar jest ważny maksymalnie 300 sekund; dłuższa luka nie jest uzupełniana.
4. **Usunięto ocenę jakości spalania z obciążenia.** Etykiety „DOBRE/WYSOKIE/NISKIE” nie miały potwierdzonego modelu. Karta pokazuje teraz wyłącznie rzeczywisty `boiler_load` jako „Obciążenie”.
5. **Zneutralizowano `optical_temp`.** Bez potwierdzenia modelu pole nazywa się „Czujnik optyczny” i nie ma ręcznie przypisanej jednostki `%` ani etykiety „Płomień”.
6. **Usunięto niepotwierdzone stany 12 i 23.** Znane kody 0–11 pozostają zgodne z `pyplumio.const.DeviceState`. Inny kod jest pokazywany jako `Stan X`.
7. **Usunięto ręczne skale i jednostki parametrów procesu.** Z `PARAMETER_META` zniknęły `display_scale`, `display_offset`, `step_override` i `unit_override`, które nie miały śladu źródłowego. Interfejs używa wartości, zakresu, kroku i jednostki zwróconych przez PyPlumIO.
8. **Poprawiono jednostki profilu MQTT/HA.** Dla wykrytych parametrów profil przenosi jednostkę z serializowanego snapshotu. Znane wartości procesowe mogą używać potwierdzonego `SENSOR_META`; nieznane pola nie dostają jednostki zgadywanej z nazwy. `device_class: power` dostają tylko rzeczywiste `W/kW`.
9. **Nieznane alarmy zachowują identyfikator biblioteki.** Jeżeli PyPlumIO zwróci nieprzetłumaczony element enum, UI otrzyma np. `Alarm 57 (NAZWA_ENUM)`, bez wymyślonego polskiego opisu.
10. **Naprawiono czyste rozłączenie.** Zakończenie aktywnej sesji bez wyjątku jest zgłaszane pętli reconnectu, która publikuje stan offline i czyści `_device`/`_connection`.
11. **Service worker nie zatrzymuje starego panelu.** Zmieniono wersję cache i strategię statyk na network-first z cache jako fallback.
12. **Usunięto nieprawdziwe założenia instalacyjne z dashboardu.** Panel nie twierdzi już, że działa na Orange Pi Zero 3, pod adresem `plumbox.local`, ani że WireGuard/Tailscale są skonfigurowane. Te elementy zależą od instalacji.
13. **Metadane Home Assistant są uczciwie eksperymentalne.** Usunięto fikcyjny URL `example.local`, a `stage` zmieniono ze `stable` na `experimental`.
14. **Uaktualniono samodzielny podgląd HTML.** Nadal jest jawną symulacją, lecz korzysta z aktualnego CSS/JS i nie zawiera starych transformacji metadanych.

## Walidacja lokalna

- `python -m pytest -q`: **42 passed** po poprawkach z audytu Fable,
- `python -m compileall -q app tests`: zaliczone,
- nowe testy obejmują dobową integrację paliwa, brak syntetycznych wykresów, fallback kodów stanu, jednostki profilu, nieznany alarm, service worker i czyste rozłączenie,
- testy wykonano bez fizycznego sterownika, prawdziwego brokera i instancji Home Assistant.

## Czego nadal nie wolno uznać za potwierdzone

- znaczenie i jednostka `optical_temp` dla konkretnego firmware,
- wartości opcji ręcznie opisanych trybów `water_heater_work_mode`, `summer_mode` i `work_mode` na urządzeniu użytkownika,
- semantyka oraz bezpieczeństwo realnego zapisu nawet parametrów oznaczonych `safe`, dopóki nie przejdą kontrolowanej próby na kotle,
- jednostki i skale pól, których PyPlumIO nie opisze w snapshotcie,
- działanie TCP/serial, reconnectu, MQTT Discovery i Ingress na instalacji użytkownika,
- budowa obrazów HA dla wszystkich architektur oraz właściwy, przypięty digest `BUILD_FROM`,
- rzeczywisty adres sieciowy, działanie mDNS, QR i dostęp VPN.

## Zalecana weryfikacja sprzętowa

1. Uruchomić najpierw `simulation`, potem profil FIXED tylko do odczytu.
2. Zapisać zanonimizowany `/api/snapshot`, `/api/profile` i listę alarmów.
3. Porównać temperatury, stan kotła, pompy, wentylator i mieszacz z panelem ecoMAX.
4. Potwierdzić przejścia `Praca → Wygaszanie → Postój/Czuwanie` na rzeczywistym cyklu.
5. Sprawdzić kontrolowane rozłączenie i powrót TCP/serial.
6. Dopiero potem wykonać pojedynczy, odwracalny zapis `safe`, porównując wartość przed i po na panelu sterownika.

Nie zmieniać blokady `advanced/critical` na podstawie samego symulatora.

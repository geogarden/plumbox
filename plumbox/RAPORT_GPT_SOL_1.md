# PlumBox 2.8.0 GPT SOL 1 — raport wykonania

Data: 2026-07-13  
Baza: `plumbox-claude-fix` / OPUSFIX5 CLAUDEFIX  
Zasada: poprawiono tylko zachowania możliwe do potwierdzenia przez analizę kodu i testy bez sterownika. Nie odblokowano zapisów advanced/critical.

## Aktualizacja 2026-07-14

Wykonano dodatkowy audyt antyhalucynacyjny opisany w `RAPORT_ANTYHALUCYNACYJNY_2026-07-14.md`. Usunięto sztuczne wykresy i zera zastępujące brak danych, błędną dobową interpretację `fuel_burned`, ocenę jakości spalania z obciążenia, niepotwierdzone kody stanów 12/23 oraz ręczne skale/jednostki bez źródła. Dodano integrację dobowego kg/h z limitowaniem luk, poprawiono jednostki profilu MQTT/HA, obsługę nieznanych alarmów i czyste rozłączenie. Metadane dodatku HA mają obecnie `stage: experimental`.

Następnie wdrożono potwierdzone poprawki z niezależnego audytu Fable, opisane szczegółowo w `RAPORT_POPRAWEK_FABLE_2026-07-14.md`: prawidłowe przekierowania z głębokich tras, zachowanie PIN-u przy `apply_options_on_start`, brak heurystycznych jednostek, limity prób uwierzytelnienia, ponowną kontrolę sesji WebSocket, defensywny zapis stanu SQLite i ograniczenie zapisów `last_login_at`.

## Stan 11 punktów z audytu

1. **Dockerfile dodatku HA — poprawione.** Usunięto końcowy znak kontynuacji w `ENV`. Dodano standardowy `ARG BUILD_FROM`, zachowując domyślny obraz HA.
2. **Role i autoryzacja sterowania — poprawione.** `readonly` nie może odblokować PIN ani wykonywać zapisów. `user` może wykonywać wyłącznie bezpieczne zapisy po PIN. Zasilanie sterownika i audyt wymagają `admin`. Token PIN jest związany z nazwą i rolą zalogowanego konta; zmiana hasła, usunięcie konta i wylogowanie unieważniają właściwe sesje.
3. **Home Assistant Ingress — poprawione po stronie aplikacji.** Zasoby, API, formularze, WebSocket, manifest i service worker używają ścieżek względnych. Service worker odświeża jawnie wskazane statyki w trybie network-first i nie przechwytuje API ani stron administracyjnych.
4. **Backup i restore — poprawione.** Kopia obejmuje całe `/etc/plumbox`, w tym użytkowników. Restore sprawdza ścieżki archiwum przed rozpakowaniem i odtwarza ograniczone uprawnienia.
5. **Awaria audytu po zapisie — poprawione.** Wynik fizycznego/symulowanego zapisu nie jest maskowany przez błąd bazy audytu. Odpowiedź zawiera `audit_saved`.
6. **Stare referencje po utracie połączenia — poprawione.** `_device` i `_connection` są zerowane w `finally`; zapis dodatkowo sprawdza aktywny stan połączenia.
7. **MQTT — poprawione logicznie i testami jednostkowymi.** Stan połączenia ustawia callback brokera, działa reconnect z backoff i LWT. Usuwane są stare retained topics stanu i Discovery. Sygnatura Discovery obejmuje pełne dane encji. Błędy publikacji są logowane.
8. **Błędny `device_class: power` dla procentów — poprawione.** Klasa `power` jest nadawana tylko jednostkom W/kW; `%` jej nie otrzymuje.
9. **Testy i paczki — poprawione.** `scripts/test_connection.py` nie uruchamia połączenia przy imporcie. Paczki zawierają `tests`, `pytest.ini` i `requirements-dev.txt`. Smoke test loguje się przed odczytem chronionego snapshotu.
10. **Wersjonowanie — ujednolicone.** Kod aplikacji, Dockerfile i manifest dodatku używają `2.8.0-gptsol1`; pakiety Python mają wersję `2.8.0`, a interfejs pokazuje GPT SOL 1.
11. **Prawdziwy sterownik — celowo nierozstrzygnięte.** Bez dostępu do ecoMAX 860P4, magistrali RS485/TCP i brokera użytkownika nie da się uczciwie potwierdzić skalowania, nazw pól, zapisu ani zachowania przy realnych zerwaniach. Dlatego advanced/critical nadal są tylko do odczytu, a test połączenia pozostaje narzędziem uruchamianym ręcznie.

## Dodatkowe utwardzenie

- Dodatek HA bez podanego PIN-u generuje losowy ośmiocyfrowy PIN i zapisuje go w chronionym `/data/initial_pin.txt`; plik jest usuwany po pierwszym poprawnym odblokowaniu.
- Przy kolejnych restartach pusty `initial_pin` zachowuje istniejący `pin_hash`, również przy `apply_options_on_start: true`.
- Logowanie i odblokowanie PIN mają limit 5 nieudanych prób na 5 minut; WebSocket sprawdza ważność sesji przed każdą publikacją.
- Plik z wygenerowanym hasłem administratora jest usuwany po pierwszym poprawnym logowaniu admina.
- Zapis konfiguracji z panelu jest atomowy i waliduje typ połączenia, profil, porty, baudrate oraz MQTT base topic.
- Domyślny PIN w modelu konfiguracji usunięto. Instalator Orange Pi nadal wymaga ustawienia PIN-u interaktywnie.

## Weryfikacja lokalna

- `python -m compileall`: zaliczone dla aplikacji, inicjalizatora, skryptów i testów.
- `pytest`: **42 passed** w źródle po aktualizacji 2026-07-14.
- Testy obejmują także brak sztucznych pomiarów, integrację dobowego paliwa, jednostki profilu, fallback stanów i alarmów, service worker, czyste rozłączenie oraz regresje wskazane przez Fable.

## Zawartość `wydania`

- `PlumBox_HA_AUTO_DETECT_2.8.0_GPTSOL1`
- `PlumBox_HA_FIXED_ECOMAX860P4_2.8.0_GPTSOL1`
- `PlumBox_OrangePi_AUTO_DETECT_2.8.0_GPTSOL1`
- `PlumBox_OrangePi_FIXED_ECOMAX860P4_2.8.0_GPTSOL1`

Wariant FIXED jest właściwym pierwszym kandydatem dla wskazanego ecoMAX 860P4, ale pierwsze uruchomienie na sprzęcie powinno odbyć się w trybie odczytu. Wariant AUTO_DETECT nie zakłada z góry kompletnego zestawu pól.

## Czego nie wykonano i dlaczego

- Nie wykonano zapisu na prawdziwym kotle ani testu awarii realnego TCP/RS485 — brak sprzętu.
- Nie potwierdzono brokera MQTT i Discovery w konkretnej instancji Home Assistant — brak danych dostępowych i środowiska użytkownika.
- Nie przypięto `BUILD_FROM` do konkretnego digestu — właściwy obraz zależy od architektury i systemu budowania dodatku HA; zgadywanie digestu byłoby ryzykowne.
- Nie odblokowano parametrów spalania, nadmuchu i innych `advanced/critical`.

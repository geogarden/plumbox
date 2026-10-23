# START TUTAJ — przekazanie projektu PlumBox dla nowego AI

## 1. Cel dokumentu

Ten plik jest kompletnym przekazaniem kontekstu dla kolejnego AI lub programisty, który otrzyma folder `2026-07-13 GPT SOL PlumBox` bez historii rozmowy.

Projekt jest poprawioną wersją PlumBox opartą na najnowszej w chwili rozpoczęcia prac bazie:

`E:\AI\plumbox\opus fix5\plumbox-claude-fix`

Baza była wcześniej oznaczona jako OPUSFIX5 CLAUDEFIX. Nie należy wracać do starszych folderów OPUSFIX bez wyraźnej decyzji użytkownika.

Nowa wersja została oznaczona:

- aplikacja i dodatek HA: `2.8.0-gptsol1`,
- pakiet Python Orange Pi: `2.8.0`,
- nazwa wydania: `GPT SOL 1`,
- data utworzenia: `2026-07-13`.

### Aktualizacja antyhalucynacyjna 2026-07-14

Przed dalszą pracą przeczytać `RAPORT_ANTYHALUCYNACYJNY_2026-07-14.md`. Produkcyjny dashboard nie generuje już zastępczych sinusoid ani zer przy braku pomiaru, „Pellet dzisiaj” jest liczony z zapisanej historii kg/h, a niepotwierdzone kody stanów, skale i znaczenie `optical_temp` zostały usunięte. Dodatek HA ma status `experimental`.

Najważniejsza reguła dla kolejnego AI: brak danych ma pozostać brakiem danych. Nie wolno poprawiać wyglądu przez dopisywanie wartości, jednostek, stanów albo znaczeń, których nie zwrócił sterownik lub nie potwierdza używana wersja PyPlumIO.

### Aktualizacja po audycie Fable 2026-07-14

Przeczytać również `RAPORT_POPRAWEK_FABLE_2026-07-14.md`. Naprawiono 404 po zmianie hasła/usunięciu użytkownika i pętlę logowania na głębokich trasach, zachowano istniejący PIN przy pustym `initial_pin`, usunięto heurystyczne jednostki `auto_detect`, dodano limity prób logowania/PIN, ponowną autoryzację WebSocket, defensywny zapis stanu do SQLite oraz rzadszy zapis `last_login_at`. Zmian nie rozszerzano na mapy sprzętowe ani niepotwierdzone parametry.

## 2. Najważniejsza zasada bezpieczeństwa

Nie wolno uznawać obsługi prawdziwego sterownika za potwierdzoną tylko dlatego, że testy symulatora przechodzą.

Podczas tych prac nie było dostępu do:

- fizycznego ecoMAX 860P4,
- magistrali RS485 ani konwertera RS485–TCP użytkownika,
- brokera MQTT użytkownika,
- uruchomionej instancji Home Assistant użytkownika,
- rzeczywistych ramek, snapshotów i potwierdzeń zapisu z kotła.

Z tego powodu parametry oznaczone `advanced` i `critical` pozostały tylko do odczytu. Nie odblokowywać ich bez sprawdzenia nazwy pola, skali, zakresu, jednostki, wartości natywnej i zachowania konkretnej wersji PyPlumIO na prawdziwym sterowniku.

## 3. Co znajduje się w folderze

### Katalog główny

Katalog główny jest źródłem roboczym i głównym miejscem dalszego rozwoju. Zawiera między innymi:

- `app/` — aplikację FastAPI, logowanie, API, obsługę sterownika, MQTT i frontend,
- `config/` — przykładową konfigurację instalacji Orange Pi,
- `scripts/` — instalację, aktualizację, backup, restore, smoke test i diagnostykę,
- `tests/` — testy bazowe i regresyjne GPT SOL,
- `Dockerfile`, `addon_init.py`, `run.sh`, `config.yaml` — pliki dodatku Home Assistant,
- `requirements.txt` — zależności uruchomieniowe,
- `requirements-dev.txt` — zależności testowe,
- `pytest.ini` — ograniczenie zbierania testów do `tests/`,
- `RAPORT_GPT_SOL_1.md` — krótsze podsumowanie wykonanych 11 punktów,
- `RAPORT_ANTYHALUCYNACYJNY_2026-07-14.md` — najnowszy audyt i lista zmian eliminujących dane pozorne,
- `RAPORT_POPRAWEK_FABLE_2026-07-14.md` — przyczynowo-skutkowy opis poprawek wdrożonych po niezależnym audycie Fable,
- `INSTRUKCJA_INSTALACJI_ORANGE_PI.md` — kompletna instalacja, aktualizacja, backup i diagnostyka Orange Pi,
- `INSTRUKCJA_INSTALACJI_HOME_ASSISTANT.md` — lokalna instalacja aplikacji/dodatku przez `/addons`, konfiguracja i diagnostyka HA,
- `START_TUTAJ_DLA_NOWEGO_AI.md` — niniejszy dokument,
- `wydania/` — cztery gotowe warianty i archiwa ZIP.

Katalog zawiera kopię metadanych Git z bazy CLAUDEFIX. Zmiany GPT SOL są obecnie zmianami roboczymi względem tej bazy, a nie osobnym zatwierdzonym commitem. Nowe AI powinno najpierw uruchomić `git status --short` i `git diff --stat`, a nie zakładać czystego repozytorium.

### Gotowe warianty w `wydania/`

1. `PlumBox_HA_AUTO_DETECT_2.8.0_GPTSOL1`
   - repozytorium/dodatek Home Assistant,
   - profil startowy `auto_detect`,
   - właściwy dla nieznanego lub innego modelu, ale wymaga oceny wykrytych pól.

2. `PlumBox_HA_FIXED_ECOMAX860P4_2.8.0_GPTSOL1`
   - repozytorium/dodatek Home Assistant,
   - profil startowy `fixed_ecomax860p4`,
   - pierwszy kandydat dla wskazanego przez użytkownika ecoMAX 860P4.

3. `PlumBox_OrangePi_AUTO_DETECT_2.8.0_GPTSOL1`
   - instalacja Orange Pi/Debian/Ubuntu/Armbian,
   - profil startowy `auto_detect`.

4. `PlumBox_OrangePi_FIXED_ECOMAX860P4_2.8.0_GPTSOL1`
   - instalacja Orange Pi/Debian/Ubuntu/Armbian,
   - profil startowy `fixed_ecomax860p4`.

Obok katalogów są cztery ZIP-y i `SHA256SUMS.txt`. ZIP-y są migawkami wydania. Nie należy edytować ZIP-a bezpośrednio. Najpierw zmienić źródło, uruchomić testy, przenieść zmianę do odpowiednich wariantów, a następnie przebudować archiwa i sumy.

## 4. Stan początkowy i problemy wykryte w audycie CLAUDEFIX

Przed zmianami wykonano przegląd źródła oraz czterech najnowszych paczek CLAUDEFIX. Ustalono:

- źródłowe testy CLAUDEFIX przechodziły: 17 testów,
- wszystkie pliki Python w czterech paczkach dało się skompilować,
- w środowisku testowym nie było `paho-mqtt`, więc MQTT nie był faktycznie testowany z brokerem,
- paczki końcowe nie zawierały pełnego zestawu testów i konfiguracji deweloperskiej,
- Orange Pi mógł błędnie zebrać `scripts/test_connection.py` jako test i uruchomić połączenie podczas importu.

Jedenaście głównych punktów raportu wejściowego:

1. końcowy `\` w `ENV` Dockerfile dodatku HA,
2. nieskuteczny model ról — `readonly`/`user` mogły uzyskać zbyt szerokie sterowanie,
3. bezwzględne adresy URL psujące pracę pod prefiksem HA Ingress,
4. backup bez użytkowników i restore z niepełnymi uprawnieniami,
5. błąd zapisu audytu mógł zamaskować wykonany zapis urządzenia,
6. pozostawienie `_device` po błędzie połączenia,
7. problemy ze stanem, reconnectem i retained topics MQTT,
8. błędne `device_class: power` dla wartości procentowych,
9. wadliwe pakowanie testów i smoke test bez logowania,
10. niespójne wersje w plikach,
11. brak możliwości potwierdzenia działania na prawdziwym sprzęcie.

## 5. Dokładny zakres wykonanych zmian

### 5.1 Role, sesje i PIN sterowania

Pliki główne:

- `app/security.py`,
- `app/deps.py`,
- `app/routers/api.py`,
- `app/routers/pages.py`,
- `app/routers/users.py`,
- `app/users.py`.

Wykonano:

- sesja odblokowania PIN przechowuje teraz `username`, `role` i czas wygaśnięcia,
- token PIN musi należeć do aktualnie zalogowanego użytkownika,
- zmiana roli między utworzeniem tokenu a użyciem powoduje odmowę,
- `readonly` nie może odblokować sterowania,
- `user` może zapisywać wyłącznie bezpieczne parametry po PIN,
- `admin` może wykonywać bezpieczne zapisy i sterować zasilaniem regulatora po PIN,
- odczyt audytu jest ograniczony do administratora,
- wylogowanie unieważnia tokeny sterowania tego użytkownika,
- zmiana hasła lub usunięcie użytkownika unieważnia jego sesje WWW i PIN,
- logowanie i PIN są ograniczone do 5 nieudanych prób w ciągu 5 minut dla danego klienta/konta,
- otwarty WebSocket przed każdą publikacją ponownie sprawdza ważność sesji,
- `last_login_at` jest zapisywany najwyżej raz na godzinę dla danego użytkownika,
- plik z początkowym hasłem administratora jest usuwany po pierwszym poprawnym logowaniu administratora,
- plik z automatycznie wygenerowanym PIN-em dodatku HA jest usuwany po pierwszym poprawnym odblokowaniu.

Macierz uprawnień po zmianie:

| Operacja | readonly | user | admin |
|---|---:|---:|---:|
| Podgląd dashboardu i snapshotu | tak | tak | tak |
| Odblokowanie PIN | nie | tak | tak |
| Zapis `risk=safe` | nie | tak | tak |
| Zapis `advanced/critical` | nie | nie | nie |
| Włączenie/wyłączenie regulatora | nie | nie | tak |
| Dziennik audytu | nie | nie | tak |
| Użytkownicy i konfiguracja | nie | nie | tak |

Sesje są przechowywane w pamięci procesu. Restart aplikacji je unieważnia. Nie implementowano trwałych sesji rozproszonych.

### 5.2 Ochrona zapisów sterownika i reconnect

Pliki główne:

- `app/plum_service.py`,
- `app/serializer.py`,
- `app/routers/api.py`.

Wykonano:

- `_device` i `_connection` są czyszczone w `finally` po wyjściu z sesji PyPlumIO,
- zapis sprawdza, czy referencja urządzenia istnieje i czy połączenie jest aktywne,
- brak aktywnego połączenia daje jednoznaczny błąd 503 w API,
- awaria bazy audytu nie zmienia sukcesu urządzenia w pozorną porażkę,
- odpowiedź zapisu zawiera `audit_saved: true/false`,
- parametry `advanced/critical` mają `writable: false` już w serializowanym modelu UI,
- niezależnie od konfiguracji usługa nadal blokuje realny zapis `advanced/critical` jako drugą warstwę ochronną.

Usunięto ręczne przeliczniki i nadpisania jednostek bez udokumentowanego źródła. Wartość, zakres, krok i jednostka mają pochodzić z PyPlumIO. Nazw i znaczeń niepotwierdzonych przez bibliotekę lub sprzęt nie zastępowano nowymi domysłami.

### 5.3 Home Assistant Ingress i frontend

Pliki główne:

- `app/main.py`,
- `app/routers/pages.py`,
- `app/admin_pages.py`,
- `app/static/index.html`,
- `app/static/login.html`,
- `app/static/app.js`,
- `app/static/manifest.webmanifest`,
- `app/static/service-worker.js`.

Wykonano:

- zasoby statyczne używają adresów względnych,
- wywołania API są wyliczane względem bazowego adresu panelu,
- WebSocket jest wyliczany względem adresu panelu i obsługuje `ws:`/`wss:`,
- formularze administracyjne i linki są względne,
- odpowiedzi `Location` z lokalnymi ścieżkami są normalizowane do postaci względnej,
- głębokość trasy jest uwzględniana, więc `/users/delete` wraca do `/users`, a niezalogowany klient do `/login`,
- service worker jest dostępny pod `/service-worker.js`, co pozwala uzyskać właściwy zakres,
- service worker pobiera jawnie wskazane zasoby statyczne w strategii network-first i używa cache tylko awaryjnie,
- service worker nie przechwytuje API ani stron administratora,
- manifest ma względny `start_url` i ikonę,
- UI pokazuje wersję `2.8.0 GPT SOL 1`.

To zostało sprawdzone testami treści i tras FastAPI. Nie wykonano pełnego testu w prawdziwym HA Ingress.

### 5.4 Dockerfile i inicjalizacja dodatku HA

Pliki główne:

- `Dockerfile`,
- `addon_init.py`,
- `config.yaml`,
- `run.sh`,
- `app/config.py`.

Wykonano:

- usunięto błędny końcowy znak `\` w `ENV`,
- dodano `ARG BUILD_FROM` i `FROM ${BUILD_FROM}` z dotychczasowym obrazem jako wartością domyślną,
- zaktualizowano wersję dodatku,
- usunięto domyślny PIN `1234` z modelu konfiguracji,
- jeżeli użytkownik nie poda PIN-u przy pierwszym tworzeniu konfiguracji HA, generowany jest losowy ośmiocyfrowy PIN,
- jeżeli konfiguracja już istnieje, pusty `initial_pin` zachowuje dotychczasowy `pin_hash`, także przy `apply_options_on_start: true`,
- wygenerowany PIN trafia do `/data/initial_pin.txt` z uprawnieniami `0600`,
- nie wpisuje się jawnego PIN-u do logu,
- `run.sh` przekazuje ścieżkę pliku początkowego PIN-u aplikacji.

Nie przypięto bazowego obrazu HA do digestu. Nie zgadywać digestu — należy dobrać go do wspieranych architektur i aktualnego procesu budowania Home Assistant.

### 5.5 Konfiguracja administracyjna

Pliki główne:

- `app/config.py`,
- `app/routers/admin.py`,
- `app/admin_pages.py`.

Wykonano:

- zapis YAML jest atomowy: plik tymczasowy, `fsync`, zachowanie trybu i `os.replace`,
- walidowane są typy połączenia `simulation/tcp/serial`,
- walidowane są profile `fixed_ecomax860p4/auto_detect`,
- porty muszą należeć do zakresu 1–65535,
- baudrate musi być dodatni,
- MQTT base topic nie może być pusty ani zawierać wildcardów `+` lub `#`.

### 5.6 MQTT i Home Assistant Discovery

Plik główny: `app/mqtt.py`.

Wykonano:

- `_connected` jest ustawiane przez callback połączenia z brokerem, a nie tuż po wywołaniu `connect`,
- zastosowano `connect_async`, pętlę Paho i reconnect delay 1–60 sekund,
- ustawiono retained Last Will `offline`,
- przy kontrolowanym zatrzymaniu publikowane jest `offline`,
- sprawdzany jest kod wyniku `publish`,
- przechowywany jest zestaw opublikowanych tematów stanu,
- tematy, które zniknęły z nowego snapshotu, są czyszczone pustym retained payloadem,
- analogicznie czyszczone są nieaktualne tematy Home Assistant Discovery,
- sygnatura Discovery obejmuje pełną treść encji i nazwę profilu, a nie tylko ścieżkę/domenę/jednostkę,
- błędy publikacji są logowane i nie zatrzymują głównej pętli sterownika.

Test MQTT używa kontrolowanego klienta zastępczego i potwierdza czyszczenie retained topics. Nie wykonano integracji z prawdziwym Mosquitto ani Home Assistant.

### 5.7 Profile i klasy urządzeń

Plik główny: `app/controller_profile.py`.

Wykonano:

- `device_class: power` jest nadawane tylko jednostkom `W` i `kW`,
- sama obecność słowa `power` w kluczu nie wystarcza,
- wartości procentowe nie dostają klasy mocy.

### 5.8 Backup i restore

Pliki główne:

- `scripts/backup.sh`,
- `scripts/restore.sh`.

Wykonano:

- backup obejmuje całe `/etc/plumbox`, a więc także `users.yaml` i pliki inicjalizacyjne,
- obejmuje też `/var/lib/plumbox` i `/opt/plumbox`,
- ścieżki są zapisywane względem `/`,
- restore przed rozpakowaniem odrzuca ścieżki absolutne, `../` i elementy spoza trzech dozwolonych katalogów,
- po przywróceniu ustawiane są właściciele i ograniczone uprawnienia,
- `users.yaml` i początkowe dane administratora otrzymują bardziej restrykcyjne tryby.

Skrypty przeszły `bash -n`. Nie wykonano rzeczywistego restore na testowym systemie Linux z systemd.

### 5.9 Testy, smoke test i pakowanie

Pliki główne:

- `scripts/test_connection.py`,
- `scripts/smoke_test.sh`,
- `tests/test_smoke.py`,
- `tests/test_gptsol_regressions.py`,
- `pytest.ini`,
- `requirements-dev.txt`.

Wykonano:

- `scripts/test_connection.py` ma osłonę `if __name__ == "__main__"`,
- `pytest.ini` ogranicza zbieranie do katalogu `tests`,
- smoke test tworzy konto administratora, uruchamia aplikację, loguje się z cookie i dopiero potem pobiera chroniony snapshot,
- testy i zależności deweloperskie są dołączone do paczek,
- test Dockerfile obsługuje układ HA (`Dockerfile`) i Orange Pi (`docker/Dockerfile`).

Nowe testy regresyjne obejmują:

- odmowę PIN i audytu dla `readonly`,
- bezpieczny zapis dla `user`,
- odmowę sterowania zasilaniem dla `user`,
- związanie tokenu PIN z tożsamością cookie,
- zachowanie sukcesu zapisu przy awarii audytu,
- wyczyszczenie `_device` i `_connection` po błędzie połączenia,
- czyszczenie starego retained topic MQTT,
- brak root-bound URL w runtime frontendu,
- brak końcowej kontynuacji `ENV` w Dockerfile.
- poprawne przekierowania z głębokich tras i brak pętli logowania,
- limity prób logowania oraz PIN-u,
- zachowanie istniejącego hash PIN-u po restarcie dodatku,
- brak jednostek zgadywanych z nazwy nieznanego pola,
- defensywną normalizację stanu SQLite,
- odcięcie WebSocket po unieważnieniu sesji,
- ograniczenie zapisów `last_login_at`.

### 5.10 Wersjonowanie i wydania

Zaktualizowano:

- `app/__init__.py` → `2.8.0-gptsol1`,
- etykietę Dockerfile → `2.8.0-gptsol1`,
- manifest HA → `2.8.0-gptsol1`,
- `pyproject.toml` w Orange Pi → `2.8.0`,
- tekst wersji w interfejsie i instalatorze.

Cztery drzewa wydania zostały utworzone na bazie odpowiadających im paczek CLAUDEFIX, a następnie otrzymały poprawiony kod, testy i dokumentację GPT SOL. Warianty FIXED mają wymuszony profil `fixed_ecomax860p4`; AUTO mają `auto_detect`.

## 6. Wyniki weryfikacji

Ostatnia weryfikacja lokalna: 2026-07-14, Python 3.10.1, PyPlumIO 0.6.8.

Wyniki po audycie antyhalucynacyjnym:

- katalog źródłowy: **42 testy zaliczone**,
- HA AUTO: **42 testy zaliczone**,
- HA FIXED: **42 testy zaliczone**,
- Orange Pi AUTO: **45 testów zaliczonych, 1 pominięty**,
- Orange Pi FIXED: **45 testów zaliczonych, 1 pominięty**,
- `compileall` dla `app` i `tests`: zaliczony,
- walidacja YAML, zgodności drzew wydania, zawartości ZIP i separatorów ścieżek: wykonywana przy przebudowie paczek,
- brak testu fizycznego sterownika, kontenera HA, systemd, brokera MQTT i rzeczywistego Ingress.

Orange Pi ma cztery dodatkowe testy pakietu natywnego (`test_mappings.py` i `test_security.py`), ale pomija jeden test `addon_init.py`, ponieważ ten plik istnieje wyłącznie w dodatku HA. Dawne testy przeliczników w `test_mappings.py` zostały odwrócone: pilnują teraz przekazywania wartości natywnej bez wymyślonej skali.

## 7. Sumy kontrolne gotowych ZIP-ów

Obowiązującym źródłem jest `wydania/SHA256SUMS.txt`. Nie wpisuje się sum ZIP-ów do dokumentu znajdującego się wewnątrz tych samych ZIP-ów, ponieważ powodowałoby to samoodniesienie i natychmiastową utratę aktualności po przebudowie archiwum.

## 8. Jak przenieść projekt

### Pełne przekazanie do kolejnego AI

Najbezpieczniej przenieść cały folder:

`2026-07-13 GPT SOL PlumBox`

Dzięki temu nowe AI otrzyma:

- źródło robocze,
- diff względem CLAUDEFIX,
- testy,
- raporty,
- cztery warianty,
- ZIP-y i sumy.

Po przeniesieniu należy wskazać nowemu AI ten dokument jako pierwszy plik do przeczytania.

### Przekazanie wyłącznie instalatorowi/użytkownikowi

Można przekazać tylko właściwy ZIP z `wydania/` oraz `SHA256SUMS.txt`. Nie jest to jednak wystarczające do wygodnego dalszego rozwoju wszystkich wariantów.

### Wybór wariantu

- ecoMAX 860P4 użytkownika: zacząć od wariantu FIXED, ale pierwsze uruchomienie prowadzić w trybie odczytu,
- inny/niepewny sterownik PLUM: zacząć od AUTO_DETECT i zapisać pełny snapshot do analizy,
- Home Assistant: wybrać HA,
- osobny Orange Pi/Armbian/Debian: wybrać Orange Pi.

## 9. Jak odtworzyć testy na nowej maszynie

Przykładowy przebieg dla czystego środowiska Python 3.10+:

```bash
python -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/python -m compileall -q app addon_init.py scripts tests
.venv/bin/python -m pytest -q
bash -n scripts/*.sh
```

Na Windows aktywator i ścieżka interpretera będą miały postać `.venv\Scripts\python.exe`. `bash -n` wymaga Git Bash lub środowiska Linux/WSL.

Smoke test jest przeznaczony dla Linux:

```bash
./scripts/smoke_test.sh
```

Test prawdziwego połączenia uruchamiać świadomie, po odłączeniu innego mastera od tej samej magistrali:

```bash
python scripts/test_connection.py --host ADRES_IP --port 8899 --timeout 60
```

Sterownik ecoMAX powinien mieć tylko jednego aktywnego klienta/mastera. Równoległy Home Assistant lub inna bramka może zaburzyć wynik.

## 10. Zalecany plan pierwszej weryfikacji sprzętowej

1. Utworzyć backup istniejącej konfiguracji użytkownika.
2. Uruchomić wariant FIXED dla ecoMAX 860P4 bez wykonywania zapisów.
3. Potwierdzić stabilność TCP/serial i zebrać pełny snapshot.
4. Porównać wykryte pola z `PARAMETER_META`, jednostkami i profilem.
5. Sprawdzić odczyty temperatur, stan regulatora, mieszacze i alarmy.
6. Zasymulować kontrolowane rozłączenie TCP/USB i potwierdzić reconnect oraz odmowę zapisu podczas przerwy.
7. Podłączyć testowy broker MQTT; sprawdzić LWT, reconnect i usuwanie retained topics.
8. Sprawdzić HA Ingress przez rzeczywisty panel dodatku, w tym logowanie, statyki, WebSocket i service worker.
9. Wykonać jeden odwracalny zapis `risk=safe` o małej zmianie, obserwując wartość przed i po.
10. Sprawdzić rekord audytu i odczyt po ponownym połączeniu.
11. Nie testować `advanced/critical`, dopóki nie powstanie osobna tabela potwierdzonych nazw, skal i bezpiecznych procedur cofnięcia.

Wyniki sprzętowe powinny być zapisane w nowym, datowanym raporcie, wraz z modelem, wersją firmware, wersją PyPlumIO, typem łącza i surowym snapshotem z usuniętymi sekretami.

## 11. Rzeczy świadomie niewykonane

- brak fizycznego testu ecoMAX,
- brak testu rzeczywistego zapisu do kotła,
- brak prawdziwego testu MQTT/Mosquitto,
- brak instalacji i uruchomienia dodatku w prawdziwym Home Assistant,
- brak budowy obrazów dla wszystkich architektur HA,
- brak pełnego testu backup/restore na systemie z systemd,
- brak migracji do `httpx2`,
- brak trwałego magazynu sesji,
- brak odblokowania `advanced/critical`,
- brak gwarancji działania QR, mDNS i adresu lokalnego w konkretnej sieci; dashboard opisuje je obecnie jako zależne od instalacji.

Nie przedstawiać powyższych elementów jako ukończonych.

## 12. Potencjalne następne usprawnienia — dopiero po osobnej decyzji

Te punkty nie należały do zatwierdzonego zakresu i nie zostały zaimplementowane:

- test integracyjny z tymczasowym brokerem Mosquitto,
- test E2E dodatku HA pod rzeczywistym prefiksem Ingress,
- tokeny CSRF dla stron administracyjnych, jeżeli model wdrożenia tego wymaga,
- trwały lub współdzielony magazyn sesji,
- automatyczny test restore w maszynie/kontenerze systemd,
- retencja dziennika audytu i zakończonych alarmów, jeśli baza zacznie rosnąć,
- CI budujące i testujące cztery warianty,
- skrypt generujący warianty i ZIP-y z jednego źródła, aby uniknąć ręcznego nakładania plików.

Nowe AI nie powinno wdrażać tych punktów automatycznie bez potwierdzenia użytkownika, zwłaszcza jeśli zmieniają model bezpieczeństwa lub format danych.

## 13. Zasady dalszej edycji

1. Bazować na tym folderze, nie na starszych OPUSFIX.
2. Najpierw zmieniać katalog główny jako źródło robocze.
3. Nie nadpisywać bez potrzeby istniejących plików użytkownika `config.yaml`, `users.yaml` i bazy danych podczas aktualizacji.
4. Nie usuwać blokady `advanced/critical` bez dowodów sprzętowych.
5. Po każdej zmianie uruchomić kompilację i testy.
6. Sprawdzić obydwa profile oraz HA/Orange Pi, jeśli zmiana dotyczy wspólnego kodu.
7. Przenieść poprawione pliki do czterech drzew `wydania/`.
8. Usunąć wyłącznie cache testów z wydania, nie testy.
9. Przebudować ZIP-y i `SHA256SUMS.txt`.
10. Zaktualizować raport o to, co faktycznie przetestowano.

## 14. Gotowy prompt dla nowego AI

Poniższy tekst można wkleić nowemu AI razem z folderem:

```text
Pracujesz nad projektem PlumBox. Najpierw przeczytaj w całości plik
START_TUTAJ_DLA_NOWEGO_AI.md, następnie RAPORT_GPT_SOL_1.md oraz sprawdź
git status --short i git diff --stat.

Aktualną bazą jest folder 2026-07-13 GPT SOL PlumBox oparty na OPUSFIX5
CLAUDEFIX. Nie wracaj do starszych folderów. Katalog główny jest źródłem
roboczym, a wydania/ zawiera cztery migawki HA/Orange Pi oraz AUTO/FIXED.

Nie zakładaj, że działanie na fizycznym ecoMAX, MQTT lub HA Ingress zostało
potwierdzone. Parametry advanced/critical muszą pozostać tylko do odczytu,
dopóki nie otrzymasz dowodów z rzeczywistego sterownika. Nie zgaduj nazw,
skal ani rejestrów. Przed zmianą przedstaw diagnozę i zakres, zachowaj dane
użytkownika, po zmianie uruchom testy i opisz dokładnie, co było testowane.
```

## 15. Skrócona decyzja dla następnego opiekuna

Kod jest przygotowany do dalszych testów i bezpieczniejszy od CLAUDEFIX w zakresie ról, sesji, Ingress, reconnectu, MQTT, backupu i pakowania. Nie jest jeszcze certyfikowany na prawdziwym kotle. Najbliższym właściwym krokiem nie jest dodawanie kolejnych funkcji, tylko kontrolowany test FIXED ecoMAX 860P4 w trybie odczytu oraz zapis wyników.

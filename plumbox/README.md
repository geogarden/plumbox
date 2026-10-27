# PlumBox dla Home Assistant

Lokalny panel sterownika PLUM ecoMAX 860P4-LZ i kotła Lazar SmartFire SF 11/130.

## Instalacja z repozytorium

1. W Home Assistant otwórz **Ustawienia → Aplikacje / Dodatki → Sklep**.
2. W menu **⋮ → Repozytoria** dodaj:

   `https://github.com/geogarden/plumbox`

3. W sekcji **PlumBox — ecoMAX / Lazar** wybierz **PlumBox** i zainstaluj.
4. Skonfiguruj połączenie ze sterownikiem oraz MQTT. Nowa instalacja domyślnie używa symulacji.
5. Uruchom dodatek i otwórz jego panel.

Przy instalacji Home Assistant buduje obraz z dołączonego Dockerfile. Budowanie może potrwać kilka minut.

## Przejście z lokalnego dodatku

Home Assistant rozpoznaje lokalny dodatek i dodatek z repozytorium jako dwie osobne instalacje. Samo dodanie repozytorium nie przełącza źródła istniejącego dodatku.

Przed migracją wykonaj kopię zapasową lokalnego PlumBox i zachowaj jego konfigurację. Nie odinstalowuj lokalnego dodatku przed zakończeniem migracji i sprawdzeniem nowego.

Dane trwałe wewnątrz kontenera starego dodatku:

- `/data/config.yaml` — konfiguracja połączenia, MQTT i PIN-u,
- `/data/users.yaml` — konta użytkowników,
- `/data/plumbox.db` — historia i audyt,
- `/data/initial_admin_password.txt` oraz `/data/initial_pin.txt` — wygenerowane dane pierwszego logowania, jeśli istnieją.

Kopiowanie bazy należy wykonywać przy zatrzymanym dodatku, aby zachować jej spójność. Jeśli potrzebujesz zachować historię i konta, przenieś dane do katalogu danych nowej instalacji przed jej docelowym uruchomieniem. Kopia dodatku lokalnego nie jest automatycznie odtwarzana pod identyfikatorem nowego dodatku.

Przy uruchamianiu wersji z repozytorium zatrzymaj lokalny PlumBox, żeby oba procesy nie łączyły się jednocześnie z kotłem i nie zajmowały tego samego portu. Po sprawdzeniu odczytów, MQTT i logowania można usunąć starą instalację.

## Aktualizacje

Po opublikowaniu nowego numeru wersji w `plumbox/config.yaml` odśwież sklep dodatków i otwórz zainstalowany **PlumBox**. Home Assistant powinien udostępnić przycisk **Aktualizuj**. Aktualizacje tej samej instalacji zachowują jej katalog danych.

Kod znajduje się w folderze [plumbox](plumbox/). [Dokumentacja aplikacji](plumbox/DOCS.md) · [Historia zmian](plumbox/CHANGELOG.md).

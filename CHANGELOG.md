# Changelog

## 2.8.0-gptsol10-v3native10.22

- dolna krawędź kolumny odczytów jest wyrównana z dołem kotła,
- zdjęcie kotła jest przesunięte do króćców zasilania i powrotu,
- usunięto odcinki rur po lewej stronie kółek przyłączeniowych.

## 2.8.0-gptsol10-v3native10.21

- usunięto komin oraz podpis modelu pod zdjęciem kotła,
- odczyty po lewej są podniesione i układane w kolumnie bez stałych odstępów pionowych, aby dolny kafelek nie był ucinany przy zawijaniu tekstu.

## 2.8.0-gptsol10-v3native10.20

- stan pracy, temperatura kotła, wskazanie palnika i temperatura podajnika są w osobnej kolumnie po lewej stronie zdjęcia,
- animacja palnika jest przeniesiona do kolumny odczytów, a zdjęcie kotła pozostaje odsłonięte,
- schemat hydrauliczny ma dodatkowe miejsce na odczyty i nadal skaluje się do szerokości ekranu.

## 2.8.0-gptsol10-v3native10.19

- schemat instalacji pokazuje zdjęcie HKS Lazar SmartFire SF 11/130 zamiast rysunku kotła,
- temperatura kotła, temperatura podajnika i stan palnika mają odczyty dopasowane do zdjęcia,
- rozpalanie, praca i wygaszanie mają osobne animacje wynikające z odczytanego stanu sterownika; brak łączności zatrzymuje animację płomienia,
- zdjęcie jest dołączone lokalnie i dostępne w pamięci podręcznej panelu,
- domyślna konfiguracja dodatku korzysta z istniejącego generowania PIN-u i hasła zamiast wpisanych jawnie danych początkowych.

## 2.8.0-gptsol10-v3native10.8

- wykres temperatur na stronie głównej dostaje bieżące próbki ze snapshotów WebSocket i nie czeka na zapis historii w SQLite,
- kafelek sterowania kotłem pokazuje bieżącą fazę regulatora (`state_label`), np. „Wygaszanie”, zamiast utożsamiać ją z logiczną wartością polecenia start/stop,
- przyciski start/stop oraz ich wartość wysyłana do sterownika pozostają bez zmian.
- dla profilu ecoMAX860P4/product ID 211 kod stanu 6 jest prezentowany jako „Test płomienia”; w pozostałych profilach pozostaje ogólnym „Czuwanie”.

## 2.8.0-gptsol10-v3native10.7

- zapis parametru nie może już zostać uznany za potwierdzony wyłącznie na podstawie starej wartości z cache; wymagana jest zgodna wartość po wzroście licznika odebranych ramek,
- włączenie i wyłączenie regulatora otrzymało tę samą ostrożną weryfikację,
- komunikaty rozróżniają przyjęcie polecenia przez transport od świeżego potwierdzenia wartości,
- nieznane stany logiczne nie są prezentowane jako „wyłączone”,
- animacje schematu opisano jako wynik stanów pomp, a nie fizyczny pomiar przepływu,
- przelicznik korekt nadmuchu ±100 działa tylko dla potwierdzonego profilu product ID 211 lub jawnego wariantu FIXED bez odczytanego ID.

# 2.8.0-gptsol10-v3native10.1 — 2026-07-30

- usunięto skok przewijania schematu przy cyklicznym odświeżaniu danych,
- zachowano obliczoną wysokość i skalę schematu podczas morphowania DOM,
- zwiększono kontrast i rozmiar dolnego komunikatu o przepływie,
- dashboard, rdzeń, MQTT i mapowania pozostają bez zmian względem V3N10.

## 2.8.0-gptsol10-v3native10 — 2026-07-29

- dodano natywną zakładkę „Schemat instalacji” na podstawie zaakceptowanego projektu B2,
- schemat pokazuje dwa osobne obiegi CO i CWU, sprzęgło hydrauliczne, zawór ATV oraz pompę kotłową,
- temperatury, stan kotła, płomień i stany urządzeń pochodzą z bieżącego snapshotu,
- animacje pomp, przepływów i podajnika działają tylko po otrzymaniu odpowiedniej flagi ze sterownika,
- wygląd dashboardu oraz pozostałe widoki V3N9 pozostają bez zmian,
- cache zasobów podniesiono do `gptsol-27`.

## 2.8.0-gptsol10-v3native9 — 2026-07-29

- parametry wyboru słownego mają pełnoszeroką listę oraz osobny pełnoszeroki przycisk „Zapisz do sterownika”,
- zachowano dotychczasowy atrybut `data-save-parameter`, delegację zdarzeń i całą ścieżkę zapisu,
- nazwy małych kafelków dashboardu zwiększono z 10,5 do 12 px,
- wartości małych kafelków zwiększono z 23 do 27 px, a jednostki z 12,5 do 13,5 px,
- pozycje lewego menu zwiększono z 13,5 do 14 px,
- dużą temperaturę kotła ograniczono do 60 px oraz dodano bezpieczny odstęp pod przecinkiem,
- etykieta panelu wskazuje `V3N9`, a cache zasobów ma numer `gptsol-26`,
- nie zmieniono komunikacji ecoMAX, reconnectu V3N8, MQTT, mapowań, RPM, readbacku, autoryzacji ani fallbacku iframe.

## 2.8.0-gptsol10-v3native8 — 2026-07-28

- włączono TCP keepalive natychmiast po zestawieniu transportu, jeszcze przed oczekiwaniem na urządzenie ecoMAX,
- transport TCP jest przechwytywany przed procedurą PyPlumIO i zamykany awaryjnie także wtedy, gdy biblioteka wyczyści już własny obiekt writer,
- brak prywatnego uchwytu gniazda lub opcji keepalive nie przerywa pracy — zdarzenie jest raportowane diagnostycznie,
- kolejne nieudane negocjacje połączenia są zliczane, a od trzeciej próby komunikat wskazuje możliwe zawieszone połączenie TCP/mostek,
- udane pobranie urządzenia zeruje licznik nieudanych negocjacji,
- rozszerzono testy MQTT o pełny katalog bieżących parametrów ecoMAX i mieszaczy, ustawienia serwisowe oraz osobną zgodę dla parametrów krytycznych,
- potwierdzono, że MQTT publikuje i steruje wszystkimi zapisywalnymi parametrami faktycznie dostępnymi w snapshotcie, także spoza skróconego profilu FIXED,
- etykieta panelu wskazuje `V3N8`, a cache zasobów ma numer `gptsol-25`,
- nie zmieniono mapowań ecoMAX, skali RPM, readbacku, polityki zapisów ani fallbacku iframe.

## 2.8.0-gptsol10-v3native7 — 2026-07-27

- rozbudowano MQTT z kanału odczytowego do dwukierunkowego sterowania Home Assistant,
- zapisywalne parametry są wystawiane przez Home Assistant Discovery jako `number`, `select` lub `switch`,
- dodano przełącznik uruchomienia/zatrzymania kotła oraz listę trybu CWU,
- MQTT obejmuje wszystkie parametry faktycznie obecne w snapshotcie, także niewymienione na skróconej liście profilu FIXED,
- polecenia MQTT używają wspólnej ścieżki zapisu PlumBoxa: konwersji jednostek, walidacji, blokady, readbacku i audytu,
- polecenia zachowane przez brokera (`retain`) są odrzucane, aby restart nie uruchomił starego zapisu,
- wyniki zapisów są publikowane w `plumbox/result/...`,
- krytyczne parametry pozostają domyślnie tylko do odczytu; ich sterowanie wymaga jawnego zezwolenia,
- dodano konfigurację uprawnień MQTT w panelu oraz opcjach dodatku Home Assistant,
- etykieta panelu wskazuje `V3N7`, a cache zasobów ma numer `gptsol-24`,
- nie zmieniono mapowań ecoMAX, skal RPM, retry ramek ani protokołu komunikacyjnego.

## 2.8.0-gptsol10-v3native6 — 2026-07-26

- każda ścieżka zamknięcia dialogu potwierdzenia, w tym klawisz `Esc`, czyści oczekujący zapis,
- zamknięcie dialogu resetuje checkbox i ponownie blokuje przycisk „Potwierdź”,
- przycisk „Anuluj” nadal czyści stan natychmiast, przed zamknięciem dialogu,
- dodano test regresyjny wspólnego czyszczenia stanu dialogu,
- nazwy czterech istniejących ustawień rozpalania dopasowano do panelu kotła bez zmiany kluczy, wartości i jednostek,
- dashboard rozróżnia „Pompę kotłową” oraz „Pompę CO za mieszaczem”,
- krótka etykieta panelu wskazuje `V3N6`, a cache zasobów ma numer `gptsol-23`,
- nie dodano brakujących parametrów i nie zmieniono protokołu ecoMAX, RPM, retry, readbacku, ról administratora ani fallbacku iframe.

## 2.8.0-gptsol10-v3native5 — 2026-07-26

- rozszerzono wykrywanie mojibake o prefiksy `U+00C3` i `U+00C5`, zapewniając pokrycie polskich znaków dla cp1250 i cp1252,
- przycisk „Anuluj” w dialogu potwierdzenia jest zwykłym przyciskiem, a „Potwierdź” jedynym submit,
- dodano testy pokrycia kodowania i symetrycznej obsługi dialogu potwierdzenia,
- krótka etykieta panelu wskazuje `V3N5`, a cache zasobów ma numer `gptsol-21`,
- nie zmieniono rdzenia ecoMAX, mapowań, RPM, retry, readbacku ani fallbacku iframe.

## 2.8.0-gptsol10-v3native4 — 2026-07-26

- Enter w polu PIN odblokowuje sterowanie tak samo jak przycisk „Odblokuj”,
- dotknięcie poza rozwiniętym menu mobilnym zamyka panel boczny,
- rozszerzono strażnik kodowania na całą klasę podejrzanych sekwencji oraz dokumentację i manifesty,
- test wersji sprawdza format i spójność bez literału zależnego od konkretnego wydania,
- dodano kontrolę kompletności delegacji wszystkich wyzwalaczy kart,
- skrócona etykieta w panelu rozróżnia linię `V3N4`,
- podniesiono cache zasobów do `gptsol-20`,
- nie zmieniono rdzenia ecoMAX, mapowań, RPM, retry, readbacku ani fallbacku iframe.

## 2.8.0-gptsol10-v3native3 — 2026-07-26

- naprawiono zapis konfiguracji, gdy sekcje `connection`, `profile` lub `mqtt` są puste (`null` w YAML),
- obsługa kart doładowanych podczas odświeżania używa delegacji zdarzeń, więc nowe kontrolki pozostają aktywne,
- usunięto BOM i potwierdzone mojibake z metadanych dodatku oraz modułu wersji,
- ujednolicono nazwę V3 Native, przykład timeoutu i cache zasobów (`gptsol-19`),
- nie zmieniono mapowań, skal RPM, komunikacji ecoMAX, retry, readbacku ani fallbacku iframe.

## 2.8.0-gptsol10-v3native2 — 2026-07-25

- skrócono nazwę dodatku Home Assistant do `PlumBox V3 Native`,
- poprawiono centrowanie mobilnego przycisku menu także po przełączeniu go na `inline-flex`,
- przebudowano mobilny nagłówek tak, aby status połączenia mieścił się bez przewijania,
- podniesiono cache zasobów do `gptsol-18`,
- zachowano profil FIXED, logikę ecoMAX, API zapisów i awaryjny wariant iframe.

## 2.8.0-gptsol10 — 2026-07-22

- motyw OLED otrzymał ciemnozieloną paletę panelu: tło `#07110f`, zielony
  akcent `#47e6a4`, ciemnozielone powierzchnie i dopasowane kolory wykresów,
- nazwa przycisku pozostała neutralna: `OLED`,
- klasyczny dashboard GPTSOL10 uporządkowano bez zmiany menu: duża temperatura
  kotła pozostaje na górze, a małe kafelki mają kolejność odpowiadającą pracy
  kotła i instalacji,
- przywrócono pierwotne zachowanie responsywne: na szerokim ekranie cztery
  pierwsze kafelki stoją obok temperatury kotła, a na węższym przechodzą pod nią,
- odczyt czujnika optycznego jest opisany jako `Płomień` i prezentowany w `%`,
- powtórzony kafelek stanu kotła zastąpiono liczbą aktywnych alarmów z przejściem
  do zakładki alarmów, a wykres temperatur rozszerzono na całą szerokość,
- osadzone strony systemowe otrzymały tę samą zieloną paletę OLED co dashboard,
- linie kotła i powrotu na wykresach OLED mają teraz wyraźnie różne kolory,
- zasoby interfejsu podniesiono do `gptsol-15`, aby wymusić pobranie nowego
  układu bez ingerencji w komunikację, odczyty i zapisy sterownika.

## 2.8.0-gptsol — 2026-07-18

- bieżące wartości parametrów odświeżają się bez wychodzenia z aktywnej zakładki,
- brak natychmiastowego ACK jest weryfikowany odczytem zwrotnym i pokazywany jako stan niepotwierdzony, nie jako pewne odrzucenie,
- watchdog snapshotów odzyskuje dane przy pozornie otwartym, lecz nieaktywnym WebSocket,
- zawieszony klient WebSocket nie zatrzymuje pętli odczytu,
- aktywne urządzenia i wybrana nawigacja mają czytelne, animowane ikony z obsługą ograniczenia ruchu.

## 2.5.0-tcp

- Dopisano i opisano pełny tryb RS485 przez TCP dla dodatku Home Assistant.
- Dodano instrukcję pracy równoległej z istniejącym dodatkiem Plum ecoMAX: instalacja obok jest OK, ale aktywny odczyt powinien być jeden.
- Potwierdzono obsługę pól `connection_type: tcp`, `tcp_host` i `tcp_port` w opcjach dodatku oraz w panelu **Komunikacja i MQTT**.


## 2.4.0-ha

- Pierwsza pełna wersja jako Home Assistant Add-on.
- Dashboard v10 zachowany bez przebudowy.
- Dodane Ingress.
- Dodany proxy `/bridge` dla zakładki Komunikacja i MQTT.
- Dodane wewnętrzne przeładowanie konfiguracji bez `systemd`.
- Dane trwałe przeniesione do `/data`.
## 2.8.0-gptsol-2 — 2026-07-18

- odświeżanie kontrolek mieszacza synchronizuje również bieżące właściwości pól,
- nowy identyfikator zasobów i pamięci przeglądarki wymusza załadowanie hotfixu,
- jednostki i nazwy Rozpalania/Wygaszania dopasowano do zdjęć panelu PellasX:
  prędkości wentylatora w rpm, czasy w sekundach/minutach i progi w procentach,
- wartości rpm pozostają natywne — bez zgadywanego przelicznika.
## 2.8.0-gptsol-3 — 2026-07-18

- pełne nazwy i jednostki parametrów dopasowano do ecoNET 3.0.023 dla
  ecoMAX 860P4-PE/PellasX na podstawie zrzutów użytkownika,
- rozdzielono przedmuch przed rozpalaniem od przedmuchu po jego zakończeniu,
- nadmuchy rozpalania, wygaszania i czyszczenia pokazują `obr/min`,
- `52 godz.` opisano zgodnie z potwierdzeniem sprzętowym jako czas do
  automatycznego czyszczenia kotła,
- poprawiono odwrócone opisy kodów trybu pompy CWU: z priorytetem/bez priorytetu,
- kompilacja i cache zasobów podniesione do `gptsol-3`.
## 2.8.0-gptsol-4 — 2026-07-18

- naprawiono proces budowania: wszystkie pliki `app/` są teraz synchronizowane
  do sześciu wariantów, zamiast ręcznej listy pomijającej mapowania i serializer,
- walidator porównuje źródła z każdym gotowym drzewem wydania,
- sekcja Mieszacz zachowuje widoczne karty podczas chwilowo pustej ramki,
- nowy identyfikator zasobów `gptsol-4` odcina wadliwy cache `gptsol-3`.

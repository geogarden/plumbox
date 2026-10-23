# PlumBox V2 / V3N10.11 — 14.10.2026

Bieżąca korekta: modelowa nazwa fazy 6 to **Czyszczenie**, zgodnie z porównaniem użytkownika z ecoNET i wyświetlaczem podczas startu kotła. Następna faza Rozpalanie zachowuje dotychczasową nazwę. Ogólna nazwa kodu 6 dla pozostałych profili nie została zmieniona.

Silnik TCP/RS485, reconnect, komendy, readback, MQTT i przeliczniki pozostają bajtowo identyczne z V3N10.10. W mappings.py zmieniono wyłącznie tę etykietę i opis jej źródła.

Aktualne pliki instalacyjne występują tylko w DO_WGRANIA; nie ma dodatkowych ZIP-ów dublujących źródła. Poprzednia V3N10.10 jest zachowana w 01_PRODUKCJA jako rollback. Nie zmieniono źródeł ani ustawień na działającym Home Assistant.

Dla obecnego kotła wybierz wariant HA FIXED i zaktualizuj istniejący folder dodatku plumbox jego zawartością. Zachowaj dane dodatku; aktualizacja źródeł wymaga odświeżenia sklepu i przebudowy/aktualizacji dodatku. Nazwy faz należy sprawdzić na rzeczywistym kotle po wdrożeniu.

---

## Zachowana dokumentacja poprzedniej wersji

# PlumBox V2 / V3N10.10 — 30.09.2026

To jest nowy wariant wydania V2. Baza: V3N10.9. Silnik, MQTT, mapowania i zależności silnika są bajtowo identyczne z bazą.

Kłódka **Admin** jest w nagłówku panelu; korzysta z istniejącego PIN-u i uprawnień konta. Panel odróżnia zmianę sieci, wygaśnięcie PIN-u i utratę logowania. Komendy zapisu nie są ponawiane automatycznie.

Dokumentacja całego projektu: `00_START_TUTAJ.md`, `INSTRUKCJA_WDROZENIA_PLUMBOX_V2.md` i `PODSUMOWANIE_POPRAWEK_V2.md` w głównym katalogu PLUMBOX V2.
W pakiecie HA aktualizuj istniejący dodatek `plumbox`, zachowując jego dane. W standalone używaj skryptów install/update; backup zatrzymuje usługę na czas tworzenia spójnej kopii.

Starsze raporty i instrukcje w tym pakiecie są zachowaną historią. Bieżące testy: walidacja sześciu wariantów, regresja Python i osiem wykonywalnych testów JavaScript dla każdego wariantu. Test na fizycznym kotle i rzeczywistym iOS HA pozostaje do wykonania.

---

## Zachowana dokumentacja wcześniejszej bazy

# PlumBox 2.8.0 GPT SOL 1

Lokalny panel i bramka dla regulatorów PLUM, przygotowana w dwóch wariantach instalacyjnych: Orange Pi/Debian/Armbian oraz lokalna aplikacja Home Assistant.

## Najważniejsze funkcje

- panel WWW z historią temperatur, alarmami i audytem zmian,
- TCP, USB-RS485/serial oraz jawny tryb `simulation`,
- profile `fixed_ecomax860p4` i `auto_detect`,
- MQTT oraz Home Assistant Discovery,
- konta `readonly`, `user`, `admin` i osobny PIN sterowania,
- zapisy `advanced/critical` zablokowane do czasu testów sprzętowych,
- brak generowania zastępczych pomiarów w produkcyjnym dashboardzie,
- dobowe zużycie pelletu liczone z zapisanych odczytów kg/h.

## Ważny status

Kod przeszedł testy lokalne i symulator, ale nie został potwierdzony na fizycznym ecoMAX użytkownika, prawdziwym RS485/TCP, brokerze MQTT ani Home Assistant. Wariant HA ma status `experimental`. Brak odczytu jest pokazywany jako brak danych; nie należy dopisywać domyślnych jednostek, stanów ani znaczeń bez dowodu.

## Start

- Orange Pi: `INSTRUKCJA_INSTALACJI_ORANGE_PI.md`,
- Home Assistant: `INSTRUKCJA_INSTALACJI_HOME_ASSISTANT.md`,
- kolejny AI/programista: `START_TUTAJ_DLA_NOWEGO_AI.md`,
- najnowszy audyt: `RAPORT_ANTYHALUCYNACYJNY_2026-07-14.md`,
- gotowe paczki: `wydania/`.

Pierwszy start wykonać w `simulation`. Na sprzęcie najpierw sprawdzić wyłącznie odczyty i porównać je z panelem regulatora.

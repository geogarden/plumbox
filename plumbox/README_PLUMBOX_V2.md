# PlumBox V2 / V3N10.11 — 14.10.2026

Bieżąca korekta: modelowa nazwa fazy 6 to **Czyszczenie**, zgodnie z porównaniem użytkownika z ecoNET i wyświetlaczem podczas startu kotła. Następna faza Rozpalanie zachowuje dotychczasową nazwę. Ogólna nazwa kodu 6 dla pozostałych profili nie została zmieniona.

Silnik TCP/RS485, reconnect, komendy, readback, MQTT i przeliczniki pozostają bajtowo identyczne z V3N10.10. W mappings.py zmieniono wyłącznie tę etykietę i opis jej źródła.

Aktualne pliki instalacyjne występują tylko w DO_WGRANIA; nie ma dodatkowych ZIP-ów dublujących źródła. Poprzednia V3N10.10 jest zachowana w 01_PRODUKCJA jako rollback. Nie zmieniono źródeł ani ustawień na działającym Home Assistant.

Dla obecnego kotła wybierz wariant HA FIXED i zaktualizuj istniejący folder dodatku plumbox jego zawartością. Zachowaj dane dodatku; aktualizacja źródeł wymaga odświeżenia sklepu i przebudowy/aktualizacji dodatku. Nazwy faz należy sprawdzić na rzeczywistym kotle po wdrożeniu.

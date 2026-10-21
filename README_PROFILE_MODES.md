# PlumBox v10 READABLE — AUTO-DETECT odczytów sterownika

Baza dashboardu: przesłana paczka `PlumBox_FULL_v10_FINAL_OrangePi_Debian(1).zip` z późniejszym powiększeniem małych opisów.

Ta paczka nie przebudowuje dashboardu. Różnica dotyczy profilu odczytów i Home Assistant Discovery.

## Tryb tej paczki

`profile.mode: auto_detect`

- `fixed_ecomax860p4` — stabilna wersja pod diagnostykę Mateusza / ecoMAX 860P4. Znane pola mają polskie nazwy i jednostki. Dodatkowe pola nadal lecą w `/api/snapshot`, MQTT `state` i `raw`.
- `auto_detect` — PlumBox tworzy listę encji z tego, co sterownik naprawdę zwrócił: wartości, parametry, mieszacze i alarmy. Home Assistant Discovery publikuje tylko wykryte encje.

## Przydatne endpointy

- `/api/snapshot` — pełny snapshot.
- `/api/profile` — aktualny profil sterownika.
- `/api/discovered` — wykryte encje dla HA/MQTT.
- `/communication` — zmiana TCP/USB/MQTT oraz przełączenie trybu profilu.

## MQTT

- `plumbox/state` — pełny snapshot.
- `plumbox/profile` — profil sterownika.
- `plumbox/raw/...` — wszystkie proste pola rozbite na tematy.
- `plumbox/entity/...` — ujednolicone tematy używane przez Home Assistant Discovery.

## Bezpieczeństwo zapisu

Auto-detect nie odblokowuje automatycznie zapisu nieznanych parametrów. Zapis nadal przechodzi przez PIN i mapowanie bezpieczeństwa.

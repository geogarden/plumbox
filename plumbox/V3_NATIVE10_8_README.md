# PlumBox V3N10.8

Wydanie naprawia dwie regresje prezentacji zgłoszone podczas testu V3N10.7.

## Poprawki

- wykres temperatur na Podglądzie jest uzupełniany bezpośrednio z kolejnych snapshotów WebSocket; historia SQLite nadal pozostaje źródłem danych archiwalnych,
- kafelek `ecomax_control` pokazuje bieżącą fazę procesu ze `state_label`, np. `Wygaszanie`, `Rozpalanie`, `Praca` lub `Postój`,
- w potwierdzonym profilu ecoMAX860P4/product ID 211 ogólny kod PyPlumIO `STANDBY=6` jest podpisany zgodnie z panelem kotła jako `Test płomienia`,
- przyciski przełącznika nadal wysyłają wyłącznie bool start/stop — faza procesu nie jest używana jako komenda.

Nie zmieniono komunikacji ecoMAX, MQTT, bazy danych ani zabezpieczeń zapisu. Jedyna zmiana mapowania jest ograniczona do etykiety stanu 6 w potwierdzonym profilu sprzętowym.

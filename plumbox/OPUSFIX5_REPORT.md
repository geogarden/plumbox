# OPUSFIX5

Zmiana względem OPUSFIX4:
- przywrócono przebudowanie `snapshot["profile"]` natychmiast po zapisie parametru w trybie symulacji;
- brak zmian w dashboardzie, CSS, JS, logo i QR;
- zachowane poprawki OPUSFIX2/3/4: PyPlumIO, reconnect, safe_writes_only, /ws auth, uprawnienia, YAML hardening, usunięcie bridge.py w HA.

Cel poprawki: usunięcie około sekundowego migotania profilu po zapisie parametru w symulatorze. Nie wpływa na odczyt/zapis z realnego kotła.

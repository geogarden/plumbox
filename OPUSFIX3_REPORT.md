# PlumBox OPUSFIX3

Poprawki względem OPUSFIX2:

- Orange Pi: `/etc/plumbox` ustawione jako `root:plumbox` z `chmod 775`, żeby aplikacja mogła atomowo zapisywać `users.yaml`.
- Orange Pi: `/etc/plumbox/config.yaml` i `users.yaml` ustawione na `660`, żeby działała strona `Komunikacja i MQTT` oraz zarządzanie użytkownikami.
- Login: zapis `last_login_at` nie powoduje już błędu 500, jeżeli ktoś ręcznie zepsuje uprawnienia pliku użytkowników.
- WebSocket `/ws`: wymaga aktywnej sesji logowania przed `accept()`, więc pełny snapshot nie jest wysyłany niezalogowanym klientom.
- HA Add-on: usunięto martwy moduł `extensions/communication_mqtt/bridge.py` i związane wpisy z Dockerfile; konfigurację obsługuje właściwa aplikacja PlumBox.
- Konfiguracja YAML: nieznane klucze w sekcjach są ignorowane zamiast wywracać start aplikacji; dodano `security.login_session_hours`.
- Docker Compose: `/etc/plumbox` jest montowany jako zapisywalny katalog, żeby zachować `users.yaml` i umożliwić zapis konfiguracji.

Dashboard/statyczne pliki v10 READABLE nie były zmieniane.

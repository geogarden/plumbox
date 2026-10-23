# PlumBox V3N10.9

Wydanie utworzone osobno na bazie V3N10.8. Naprawia uruchamianie panelu PlumBox w aplikacji Home Assistant na Androidzie, gdy WebView lub ingress nie odpowie przy pierwszej próbie.

Zmiana dotyczy wyłącznie frontendu:

- ponawianie trzech zapytań startowych z narastającym opóźnieniem,
- limit 8 sekund dla pojedynczej próby startowej,
- odświeżenie snapshotu po powrocie aplikacji HA z tła,
- odbudowa nieaktywnego albo starego WebSocketu,
- ochrona przed wieloma równoległymi WebSocketami i timerami reconnect,
- podniesienie cache statycznego do `gptsol-35`.

Rdzeń komunikacji ecoMAX, MQTT, mapowania, baza, autoryzacja i schemat instalacji pozostają bez zmian względem V3N10.8.

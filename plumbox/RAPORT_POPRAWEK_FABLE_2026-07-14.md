# PlumBox GPT SOL 1 — raport poprawek po audycie Fable

Data: 2026-07-14  
Zakres: poprawki możliwe do potwierdzenia analizą kodu i testami lokalnymi.  
Zasada: bez zmian map rejestrów, skal sprzętowych, parametrów `advanced/critical` i bez deklarowania zgodności z fizycznym ecoMAX.

## Wynik

Uwagi z audytu Fable zostały sprawdzone, a potwierdzone błędy i bezpieczne do usunięcia ryzyka poprawiono. Kod źródłowy po zmianach przechodzi 42 testy. Testy na prawdziwym kotle, HA Ingress i brokerze MQTT nadal nie zostały wykonane.

## 1. Przekierowania po operacjach użytkownika

**Przyczyna:** middleware usuwał początkowy `/` z lokalnego nagłówka `Location`. Adres `users?...` zwrócony po żądaniu `/users/delete` lub `/users/password` był rozwiązywany przez przeglądarkę jako `/users/users?...`.

**Zmiana:** dodano centralne wyliczanie względnego adresu na podstawie głębokości ścieżki żądania. Przekierowanie z dowolnej trasy rozwiązuje się teraz do właściwej lokalnej ścieżki również pod prefiksem HA Ingress. Parametry zapytań są kodowane przez `urllib.parse.urlencode`, a nie przez funkcję do escapowania HTML.

**Test:** operacje zmiany hasła i usunięcia użytkownika z głębokich tras kończą się na `/users`, nie na `/users/users`.

## 2. Pętla logowania na głębokich trasach

**Przyczyna:** stałe `./login` jest poprawne przy trasie jednopoziomowej, ale z `/users/delete` wskazuje `/users/login`.

**Zmiana:** ten sam mechanizm relatywizacji wylicza prawidłową drogę do `/login` dla każdej głębokości.

**Test:** niezalogowane żądanie głębokiej ścieżki prowadzi do `/login` i nie tworzy pętli.

## 3. Zachowanie PIN-u dodatku HA

**Przyczyna:** `apply_options_on_start: true` z pustym `initial_pin` generowało nowy PIN przy każdym restarcie.

**Zmiana:** inicjalizator odczytuje istniejący `pin_hash`. Pusty `initial_pin` zachowuje poprzedni hash; losowy PIN powstaje wyłącznie przy pierwszym uruchomieniu, gdy nie istnieje ani PIN, ani hash. Jeżeli `apply_options_on_start` nadpisuje konfigurację połączenia, profilu lub MQTT, log zawiera jawne ostrzeżenie.

**Ważne:** `apply_options_on_start: true` nadal celowo stosuje opcje Supervisora do konfiguracji. Nie usunięto tego zachowania, bo jest potrzebne do świadomego przełączenia symulacja/TCP/serial. Po jednorazowym zastosowaniu opcji zalecane jest ponowne ustawienie `false`.

## 4. Jednostki w `auto_detect`

**Przyczyna:** nieznane pola dostawały jednostkę na podstawie fragmentu nazwy, np. `temp` albo `power`.

**Zmiana:** usunięto heurystyki nazw. Jednostka jest publikowana tylko wtedy, gdy pochodzi z potwierdzonego `SENSOR_META` albo z metadanych parametru zwróconych w snapshotcie PyPlumIO. Dla pozostałych pól wynosi `null`; w konsekwencji nie jest też zgadywany `device_class`.

**Test:** nieznane klucze zawierające `temperature` i `power` nie otrzymują wymyślonej jednostki.

## 5. Defensywny zapis stanu do SQLite

**Ryzyko:** typ stanu zwrócony przez bibliotekę może nie być bezpośrednio obsługiwany przez SQLite.

**Zmiana:** przed zapisem stan jest normalizowany do liczby całkowitej albo `NULL`. Obsługiwane są liczby, słowniki serializowanego enum i obiekty z polem `.value`; wartości niekonwertowalne nie zrywają pętli połączenia.

**Test:** zwykły `Enum` i wartość niekonwertowalna są obsługiwane bez błędu bindowania SQLite.

## 6. Limit prób logowania i PIN-u

**Zmiana:** dodano pamięciowy, bezpieczny wątkowo limit 5 nieudanych prób w ciągu 5 minut. Szósta próba zwraca HTTP 429 z `Retry-After`. Poprawne uwierzytelnienie zeruje licznik. Logowanie jest limitowane według adresu klienta i nazwy konta, a PIN według adresu klienta i aktualnie zalogowanego konta.

**Ograniczenie:** limity są przechowywane w pamięci procesu i zerują się przy restarcie. To świadoma, mała ochrona dla pojedynczej instancji, nie rozproszony mechanizm bezpieczeństwa.

## 7. Ponowna autoryzacja WebSocket

**Przyczyna:** sesja była sprawdzana tylko podczas zestawienia połączenia.

**Zmiana:** hub zapamiętuje token sesji i przed każdą publikacją snapshotu sprawdza, czy sesja nadal istnieje i nie wygasła. Unieważnione połączenie jest zamykane kodem 1008.

**Test:** usunięcie sesji powoduje zamknięcie WebSocket i brak kolejnej publikacji.

## 8. Ograniczenie zapisów `last_login_at`

**Zmiana:** udane logowanie nie zapisuje ponownie `users.yaml`, jeżeli ostatni zapis nastąpił mniej niż godzinę wcześniej. Zmniejsza to liczbę zapisów na kartę SD, zachowując informacyjną wartość pola.

**Test:** świeży `last_login_at` nie powoduje zapisu pliku użytkowników.

## 9. Drobne korekty

- poprawiono mylący komentarz dotyczący trasy service workera,
- usunięto ternary z identycznymi gałęziami w JavaScript,
- komunikaty w URL są kodowane jako parametry zapytania, nie jako HTML.

## Elementy świadomie niezmienione

- `BUILD_FROM` nie został przypięty do zgadywanego digestu; wymaga potwierdzenia obrazu i architektur w prawdziwym procesie budowania HA,
- port 8080 pozostał dostępny jako opcja instalacyjna; nie należy wystawiać go do Internetu, a nowe limity prób tylko zmniejszają ryzyko, nie zastępują zapory i bezpiecznej sieci,
- mapy ecoMAX, jednostki nieopisane przez bibliotekę i blokada `advanced/critical` nie zostały zmienione,
- nie wykonano testów sprzętowych, testu realnego Ingress, Mosquitto ani budowy obrazu HA.

## Testy regresji dodane po audycie

1. przekierowanie po zmianie hasła,
2. przekierowanie po usunięciu użytkownika,
3. logowanie z głębokiej ścieżki,
4. limit prób logowania,
5. limit prób PIN-u,
6. zachowanie istniejącego `pin_hash`,
7. brak heurystycznych jednostek,
8. normalizacja stanu SQLite,
9. zamknięcie WebSocket po unieważnieniu sesji,
10. brak zbędnego zapisu `last_login_at`.

## Wniosek dla kolejnego audytora

Audyt Fable wykrył realny błąd przekierowania i kilka spójnych ryzyk. Zmiany mają pokrycie regresyjne, ale wynik lokalny nie stanowi potwierdzenia zachowania na fizycznym kotle ani wewnątrz prawdziwego Home Assistant. Następny audyt powinien zacząć od tego pliku, `START_TUTAJ_DLA_NOWEGO_AI.md`, pełnego diffu i ponownego uruchomienia testów.

## Końcowa walidacja lokalna

- źródło robocze: 42 testy zaliczone,
- HA AUTO_DETECT: 42 testy zaliczone,
- HA FIXED_ECOMAX860P4: 42 testy zaliczone,
- Orange Pi AUTO_DETECT: 45 testów zaliczonych, 1 pominięty test inicjalizatora HA,
- Orange Pi FIXED_ECOMAX860P4: 45 testów zaliczonych, 1 pominięty test inicjalizatora HA,
- `compileall`: zaliczony dla źródła i czterech drzew wydania.

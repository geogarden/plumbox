# Raport dla nowego AI — PlumBox V3N10.8

Data: 2026-09-12

## Baza

V3N10.8 utworzono jako osobne wydanie na bazie V3N10.7. V3N10.7 oraz V3N10.6 pozostają nietkniętymi punktami powrotu.

## Objaw i przyczyna 1 — nieruchomy wykres Podglądu

Kafelki korzystały bezpośrednio ze snapshotu WebSocket i aktualizowały się poprawnie. Duży wykres korzystał wyłącznie z `/api/history`, czyli próbek zapisanych okresowo w SQLite. Powodowało to opóźnienie widoczne szczególnie wtedy, gdy bieżące temperatury zmieniały się częściej niż interwał historii.

Poprawka w `app/static/app.js`:

- każdy snapshot tworzy bieżący wiersz czterech temperatur,
- wiersz jest dopisywany tylko po zmianie co najmniej jednej wartości,
- bufor Podglądu jest ograniczony do 400 pozycji,
- rewizja danych wymusza przerysowanie canvasu,
- po odświeżeniu danych archiwalnych dopisywana jest również najnowsza próbka bieżąca.

Nie zwiększa to liczby zapisów do SQLite i nie obciąża bazy Home Assistanta.

## Objaw i przyczyna 2 — po zatrzymaniu nadal „Kocioł uruchomiony”

`ecomax_control` opisuje polecenie start/stop, a nie aktualną fazę procesu. Podczas wygaszania jego bool może nadal nie odpowiadać oczekiwanemu opisowi operatora.

Poprawka:

- bieżąca wartość na kafelku `ecomax_control` jest prezentowana z `state_label`,
- opis polecenia w dialogu i wartości przycisków nadal korzystają z bool,
- dzięki temu `Wygaszanie` może pojawić się na otwartej zakładce CO po kolejnym snapshotcie, bez przechodzenia na Podgląd.

## Zakres nietknięty

- `plum_service.py`, PyPlumIO i reconnect,
- skale parametrów product ID 211,
- MQTT,
- baza i retencja,
- autoryzacja, PIN i role,
- schemat instalacji.

## Etykieta „Test płomienia”

Test na fizycznym kotle wykazał sekwencję: panel kotła pokazuje `Test płomienia`, podczas gdy PlumBox na podstawie ogólnego enumu PyPlumIO pokazywał `Czuwanie`; następnie oba przechodziły do rozpalania. Oznacza to kod `DeviceState.STANDBY=6` widziany przez PyPlumIO w tej fazie.

Etykietę kodu 6 nadpisano na `Test płomienia` wyłącznie wtedy, gdy aktywny jest potwierdzony profil ecoMAX860P4/product ID 211 (w tym jawny fallback FIXED bez odebranego ID). Dla obcego lub nierozpoznanego sterownika kod 6 nadal oznacza ogólne `Czuwanie`.

## Test sprzętowy

Po instalacji zatrzymać pracujący kocioł z zakładki CO. Oczekiwane:

1. komunikat zapisu zgodny z wynikiem,
2. kafelek przechodzi na `Wygaszanie` po odebraniu takiej fazy ze sterownika,
3. wykres na Podglądzie reaguje na kolejne zmiany temperatur bez otwierania zakładki Historia.

Kod nie wymusza fazy `Wygaszanie` lokalnie — pokazuje ją dopiero, gdy nadejdzie ze sterownika.

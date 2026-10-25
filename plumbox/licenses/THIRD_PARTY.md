# Oprogramowanie zewnętrzne

PlumBox korzysta z projektu PyPlumIO oraz zależności Pythona wymienionych w `requirements.txt`. Warunki licencyjne zainstalowanych pakietów można sprawdzić poleceniem:

```bash
/opt/plumbox/.venv/bin/pip show pyplumio fastapi uvicorn PyYAML
```

## Zdjęcie kotła

Plik `app/static/sf11130.jpg` to zdjęcie kotła HKS Lazar SF 11/130 dostarczone przez użytkownika. Plik zapisano bez modyfikacji.

## Harmonogram pracy kotła

Widok i znaczenie planu „Praca kotła” zaadaptowano z projektu
https://github.com/geogarden/ecomax-esp32-gateway (main a21f66a1b75cb7f2b1788a832ffdb49ad2fef4e1).
PlumBox korzysta z natywnego kodowania PyPlumIO 0.6.8; kod firmware ESP nie jest uruchamiany w dodatku.
Informacja licencyjna projektu źródłowego: [ecomax-esp32-gateway-MIT.txt](ecomax-esp32-gateway-MIT.txt).


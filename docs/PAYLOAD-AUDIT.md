# Audyt pakietu karty SD

## Zakres

Sprawdzono wszystkie 131 plików w `sdcard/ports/` (144 916 557 bajtów przed porządkami), rozmiary, odwołania runtime oraz duplikaty SHA-256. Bez uruchamiania gry na konsoli.

## Wynik

Po porządkach: **91 plików, 136 145 771 bajtów (129,84 MiB)**. Oszczędność: **8 770 786 bajtów (8,36 MiB)**, około 6,05% poprzedniego rozmiaru. Obejmuje usunięcie cache oraz zmniejszenie skryptów.

Weryfikacja: pełny zestaw Windows — 668 testów, 117 pominiętych platformowo; bez błędów. Dodatkowo Linux/WSL — 74 syntetyczne testy shell, bez błędów. Hashe i rozmiary wszystkich czterech artefaktów runtime zgodne z manifestem. Test na fizycznym R36S pozostaje do wykonania.

## Usunięte

- Trzy alternatywne launchery: GPU, Performance GDI, Performance OpenGL.
- Eksperymentalny `compat/box86-a35/`: 7 837 281 bajtów. Główny launcher domyślnie używał stock Box86, nie A35.
- Eksperymentalny `compat/gles2-renderer/`: 518 026 bajtów.
- Powiązane selektory, konfiguracja OpenGL, narzędzia budowania, pakowania i testy wycofanych wariantów.
- Cache `scripts/__pycache__/`: 384 245 bajtów. Testy uruchamiane z `python -B`, aby nie odtwarzać cache w pakiecie.

Pozostaje jeden launcher i dotychczasowa konfiguracja produkcyjna GDI. Nazwy w menu: `640x480`, `800x600`, `1024x768`, `1068x600`. Wewnętrzny token `native` zachowano dla zgodności zapisanych ustawień i protokołu menu; nie jest etykietą użytkownika.

## Duże pliki pozostawione celowo

| Plik w `projectdiablo2/` | Bajty | Uzasadnienie |
|---|---:|---|
| `runtime/weston_pkg_0.2.squashfs` | 55 398 400 | Compositor Weston; montowany podczas startu. |
| `runtime/wine-8.0-x86.tar.xz` | 31 185 272 | Instalacja/weryfikacja Wine. |
| `runtime/box86` | 27 311 020 | Sprawdzony emulator produkcyjny. |
| `runtime/vc_redist.x86.exe` | 13 889 072 | Inicjalizacja bibliotek VC++ w prefiksie Wine. |
| `compat/alsa-native/strace-6.1.tar.xz` | 2 351 272 | Źródła towarzyszące dystrybuowanemu strace; zgodność licencyjna i odtwarzalność. |
| `compat/alsa-native/strace.aarch64` | 1 453 376 | Obsługiwana diagnostyka audio. |
| `compat/alsa-legacy-armhf/alsa-lib-1.2.8.tar.bz2` | 1 091 475 | Źródła LGPL dla biblioteki zgodności audio. |

Główny launcher weryfikuje wszystkie cztery artefakty `runtime/` przy każdym uruchomieniu. Usunięcie archiwów lub instalatora po pierwszej instalacji zablokowałoby kolejne starty.

Pozostałe biblioteki i narzędzia audio, wejścia, FPS oraz diagnostyki mają odwołania w zachowanej funkcjonalności. Nie usuwano ich tylko dlatego, że domyślny start ich nie wybiera. Zachowano licencje i patche źródłowe. Nie znaleziono duplikatów binariów; powtarzają się jedynie niewielkie licencje komponentów. Nie znaleziono danych gry, zapisów, prefiksów Wine, logów ani przypadkowych dużych archiwów deweloperskich.

## Możliwe dalsze odchudzenie — wymaga osobnego testowania

Stock `runtime/box86` zawiera 19 806 478 bajtów sekcji debug/symboli. Usunięcie symboli może zmniejszyć binarium, ale zmienia jego hash: wymaga nowego artefaktu, aktualizacji manifestów i testu na R36S. Tego audytu nie użyto do modyfikacji sprawdzonego runtime.

Archiwum Wine zawiera około 56 MB nieskompresowanych bibliotek statycznych i narzędzi deweloperskich. Przepakowanie wymaga osobnej walidacji instalacji, zależności i hashy; nie jest bezpiecznym usunięciem pojedynczego pliku z obecnego pakietu. Nie przycinano nieprzeanalizowanego wnętrza Weston squashfs.

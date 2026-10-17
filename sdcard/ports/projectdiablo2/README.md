# Project Diablo 2 na R36S / dArkOSen — wersja 0.1.18

## Diagnostics-1 — aktualny etap: pomiar zamiast nowych flag

[Instrukcja nowych testów A–F i eksportu logów](<DIAGNOSTICS-1.md>). Dotychczasowe Forward512/FastFlags nie poprawiły FPS, KMS/Auto nadal były czarne, CALLRET nie doszedł do gry. Nowa paczka dodaje lekki licznik bez HUD, dokładne etapy setupu, metryki CPU/RAM/swap/PSI oraz rozdzielone próby SDL → GLX/Crusty → Wine/DirectDraw. Zwykły launcher nie włącza nowego licznika. Nie ogłaszamy przyspieszenia ani działającego OpenGL bez próby na R36S. Starszy opis tuning-1 poniżej pozostaje historyczny.

## Pakiet tuning-1 — sześć nowych testów po czarnym ekranie OpenGL

Wypakuj aktualizację `projectdiablo2-tuning-1.zip` do istniejącego `ports` z nadpisaniem, bez kasowania gry/config/prefixu. Pakiet nie wymienia Wine/Box86 ani danych gry. Zwykły launcher nadal działa jak wcześniej. Każdy nowy test: **800×600, BIGBLOCK=1, FPS ON, bez menu portu**, diagnostyka co 5 s. Wybranie wpisu od razu uruchamia grę. Aby wyłączyć nakładkę, zmień w danym wpisie `${PD2_FPS:-1}` na `${PD2_FPS:-0}`; porównuj zawsze te same ustawienia licznika.

| Test w Ports | Zmiana względem punktu odniesienia |
|---|---|
| **Test 1 GDI Baseline** | Punkt odniesienia: FORWARD=128, CALLRET=0, SAFEFLAGS=1. |
| **Test 2 GDI Forward512** | Tylko FORWARD=512: większy zakres szukania dalszych bloków dynarec. |
| **Test 3 GDI CallRet RISK** | Tylko CALLRET=1. Może być niezgodne z kodem samomodyfikującym się. |
| **Test 4 GDI FastFlags RISK** | Tylko SAFEFLAGS=0. Może powodować także ciche błędy działania. |
| **Test 5 OpenGL KMS** | SDL Crusty otrzymuje kmsdrm zamiast x11; wymaga działającego ARM32 KMS. |
| **Test 6 OpenGL Auto** | Jak Test 5, ale bez narzucania SDL_VIDEODRIVER; SDL sam wybiera backend. |

**Najpierw 1 → 2 → 5 → 6. Testy 3/4 są opcjonalne i ryzykowne: backup zapisów/prefixu, wyłącznie nieważna postać.** Nie łączymy CALLRET i FastFlags ani nie narzucamy ich zwykłemu wpisowi. Nie zmieniamy globalnego governor, częstotliwości, uprawnień urządzeń ani precyzji x87. Nie gwarantujemy większej liczby FPS.

W obu nowych testach GL dodatkowo ustawiono upstreamowe XDG_SESSION_TYPE=x11 (to nie wymusza backendu SDL) i SDL_VIDEO_EGL_DRIVER na sprawdzoną bibliotekę ARM32 EGL. Zmiany dotyczą tylko Wine/Box/Crusty, nie natywnego mappera/Pythona ani AArch64 Westona. Oba testy GL mają te same pozostałe ustawienia, więc ich porównanie izoluje backend SDL. Względem starego Performance OpenGL zmienia się więcej niż jedna rzecz: także BIGBLOCK/FPS, kontrola bibliotek i środowisko EGL.

Przed startem GL sprawdzane są ARM32 SDL/EGL/GLES/GBM/DRM: wpisy `graphics_probe` z `arch=armhf`. `ready` oznacza znalezienie poprawnej architektury biblioteki i odrzucenie proxy, **nie utworzenie kontekstu GPU**. `client_drm_access` sprawdza jedynie otwarcie card0 przez użytkownika gry; nie potwierdza DRM master ani możliwości wyświetlania. Nie uruchamiamy Wine jako root.

Logi podają `tuning_profile` i — gdy firmware udostępnia — `cpu_freq_khz`, `cpu_max_freq_khz`, `gpu_freq_hz`, `gpu_max_freq_hz`, temperaturę i wolny RAM. Maksimum jest limitem raportowanym przez sysfs, nie gwarantowanym zegarem fizycznym. Sam zegar nie jest pomiarem obciążenia ani dowodem bottlenecku. Brak odczytu oznacza pominięte pole, nie zero. Log nie zawiera nazw postaci ani surowego trace.

Dla każdego wariantu: ta sama postać/lokacja/players, 30 s rozgrzewki, 60 s postoju i 60 s walki, potem kilka minut po rozgrzaniu. Zapisz FPS i czy działają obraz, pad, dźwięk, ekwipunek/stash. Prześlij log i nazwę testu. Jeśli GL nadal jest czarny, nie zmieniaj sterownika ani nie kasuj prefixu. `xwayland_software_fallback` sam nie dowodzi renderowania gry na CPU — bezpośrednia ścieżka Crusty jest osobna.

Powrót bez odinstalowania: wybierz zwykły wpis. Pełny rollback kodu: nadpisz zachowaną paczką 0.1.18 i usuń tylko sześć nowych wpisów Test z Ports (nadpisanie ZIP ich nie usuwa), nie katalog gry. Pomocniki pozostawione po rollbacku nie są wywoływane przez stary kod.

Źródła: [WestonPack — tryby ArkOS/Mali, headless i SDL/Crusty](https://github.com/binarycounter/Westonpack/wiki), [Box86 — znaczenie i ryzyka opcji](https://github.com/ptitSeb/box86/blob/fa59e74/docs/USAGE.md). To wiedza o stosie i podobnych urządzeniach, nie benchmark tej gry. Testy lokalne nie zastępują pomiaru na R36S.

## Historia: 0.1.18 — eksperymentalne profile Performance

Aktualizacja dodaje dwa osobne wpisy w Ports; zwykły `Project Diablo 2.sh` zachowuje dotychczasowe działanie. Nie obiecujemy wzrostu z 10–15 do 25/30 FPS bez pomiaru na R36S.

- **Project Diablo 2 - Performance GDI.sh** — dotychczasowa ścieżka GDI, domyślnie 800×600, FPS OFF i eksperymentalne większe bloki Box86 (`BIGBLOCK=2`). Zacznij od tego wariantu.
- **Project Diablo 2 - Performance OpenGL.sh** — te same ustawienia CPU i pełny profil OpenGL (także odpowiedni Weston/Crusty), najprostsze skalowanie Nearest neighbor. Może odciążyć prezentację obrazu, ale może też być wolniejszy, dawać czarny ekran lub problemy z kursorem/kolorami. Nie jest to gwarancja użycia GPU ani przeniesienie całego silnika na GPU.

W obu wariantach menu nadal pozwala zmienić rozdzielczość i włączyć FPS. Do gry zalecane **800X600 / FPS OFF**; licznik kopiuje powierzchnię na każdej klatce i ma narzut. Ustawienia renderera Performance są wyłącznie sesyjne, tworzone z szablonu portu i nie zapisują się do użytkownikowego INI. Pozostałe ustawienia gry nadal zapisują się normalnie. Działający dźwięk, pad, runtime Wine/Box86, dane i save’y nie są wymieniane/resetowane.

`BIGBLOCK=2` zamiast dotychczasowego `1` jest eksperymentem: możliwe większe zużycie pamięci i niestabilność przy samomodyfikującym się kodzie. W razie crashy wróć do zwykłego launchera. Aby testować sam backend bez tej zmiany, w wybranym launcherze Performance zmień `${PD2_BIGBLOCK:-2}` na `${PD2_BIGBLOCK:-1}`. Nie włączamy ryzykownych `SAFEFLAGS=0`, `CALLRET=1`, wyrównanych mutexów ani obniżonej precyzji x87. Dynarec już wcześniej był domyślnie włączony; nie przedstawiamy tego jako nowej optymalizacji.

### Instalacja i powrót

1. Zamknij grę, wykonaj własny backup zapisów.
2. Wypakuj ZIP 0.1.18 do **tego samego katalogu ports** z nadpisaniem. Nie usuwaj folderu gry, konfiguracji, prefixu ani runtime. Aktualizacja nie zawiera danych gry.
3. Uruchom **Performance GDI**, potem **Performance OpenGL**. Zwykły wpis jest szybkim powrotem bez edycji ustawień.
4. Pełny rollback kodu: wypakuj zachowany ZIP 0.1.17. Nowe dwa wpisy Performance pozostaną po zwykłym nadpisaniu — usuń wtedy tylko te dwa launchery, nie folder gry.

### Porównanie na R36S

Dla zwykłego wpisu oraz obu Performance wybierz **800X600 i FPS ON**. Ta sama nieważna postać, ta sama lokacja, liczba graczy 1: 30 s rozgrzewki, potem 60 s postoju i 60 s podobnej walki. Zapisz zakres FPS i stabilność; sprawdź ekwipunek, stash, mysz, analogi i audio. Następnie zagraj kilka minut z FPS OFF i sprawdź temperaturę/stabilność po rozgrzaniu. Dla izolacji zmiany renderera powtórz oba Performance z BIGBLOCK=1.

Jeśli obecna konfiguracja gry nie jest już niska: w opcjach wyłącz perspektywę i mieszane cienie, ustaw niską jakość oświetlenia; nie zmieniaj innych pól JSON w ciemno. Szablon portu już ma te wartości. 640×480 to tylko wyjście na ekran, nie wewnętrzna rozdzielczość gry. Nie dodano ryzykownego patcha 640×480 UI. Nie obniżaj `maxgameticks` — zmienia tempo gry, nie rozwiązuje braku FPS. Limit prezentacji pozostaje 30, a nie wymuszona liczba klatek.

Bezpieczny log ma `performance_profile=off/gdi/opengl` i `dynarec_bigblock=1/2`; wybrany profil nie dowodzi sprzętowej akceleracji. Przy problemach prześlij log i zdjęcie. Nie wprowadzamy OC, globalnego governor ani zmian sterowników.

Źródła opcji: [Box86](https://github.com/ptitSeb/box86/blob/fa59e74/docs/USAGE.md), [cnc-ddraw 7.1](https://github.com/FunkyFr3sh/cnc-ddraw/blob/v7.1.0.0/src/config.c).

Poniższa sekcja opisuje podstawowy launcher i historię 0.1.17.

## Główny launcher gry — Project Diablo 2.sh

W wersji **0.1.17** jedynym plikiem startowym w katalogu `ports/` jest `Project Diablo 2.sh`.
Launcher uruchamia stylizowane, klimatyczne menu Diablo II (`PROJECT DIABLO II / LORD OF DESTRUCTION - R36S`):

- **RESOLUTION:** na starcie jawnie pokazuje **800X600** (albo inną rzeczywistą wartość rozwiązaną przez główny launcher). Pierwsza pozycja nadal dziedziczy ustawienie launchera, bez jego nadpisywania; kolejne pozwalają wybrać NATIVE 1068X600, 800X600 i 1024X768. Pełny napis mieści się w obecnej czcionce.
- **FPS COUNTER:** domyślnie **OFF**. Po wybraniu **ON** licznik pojawia się automatycznie w lewym górnym rogu obrazu gry, bez skrótu ani komend do czatu. Mierzy klatki renderera, nie częstotliwość logiki gry ani odświeżanie ekranu. Najpierw pokazuje `FPS: --`, a po zebraniu pierwszej próbki wyświetla wynik liczbowy. OFF pozostawia oryginalny, niezmieniony renderer.
- **Stabilny obraz:** zachowano składanie klatki poza ekranem i pojedyncze kopiowanie gotowego obrazu; menu nie jest ciągle czyszczone ani odrysowywane w spoczynku.
- **ENTER SANCTUARY / LAUNCH:** natychmiastowe uruchomienie gry z wybranymi opcjami.
- **EXIT TO SYSTEM:** powrót do PortMastera / systemu.
- **Działające audio ALSA:** zmodyfikowana, działająca ścieżka ALSA ARM32 z routingiem rk817 jest aktywna domyślnie w tle, bez konieczności konfiguracji i bez wyświetlania okna testu tonu audio (`pd2-audio-probe.exe`). Uruchamiana jest wyłącznie gra `Game.exe`.

**Krzyżak/strzałki**: wiersz i zmiana wartości. **A/Start/Enter**: potwierdź. **B/Select/Esc**: anuluj i wróć do Ports. Puść przyciski po wejściu.

Od 0.1.17 nie jest uruchamiany pomocnik klawiatury FPS ani dodatkowy pulpit Wine. Opcjonalny wariant cnc-ddraw z nakładką FPS jest uwierzytelniany i wybierany tylko w ulotnym katalogu sesji przed startem gry. Oryginalna biblioteka, dane i zapisy nie są modyfikowane. Gdy przygotowanie nakładki się nie powiedzie, gra korzysta z oryginalnego renderera, a bezpieczny log zawiera `fps_counter=unavailable`.

Licznik nie wymaga odczekiwania 10 s ani **Select+R3/F10**. Nie wpisuje `/fps`, nie przechwytuje pada ani klawiatury. Wariant 1024×768 ma około 64% więcej pikseli niż 800×600. Efekt i wydajność nowej nakładki wymagają potwierdzenia na fizycznym R36S.

Tryb **Test zawsze pokazuje menu i czeka na wybór** przed startem gry. Menu jest teraz klientem protokołu X11 napisanym w Pythonie (bez SDL, Xlib, pygame, Qt i dodatkowych pakietów), używa gotowej prywatnej sesji Xwayland/Weston. Potwierdza wyświetlenie okna przed obsługą wyboru. Puść przycisk użyty do wejścia z Ports, następnie wybierz opcje i naciśnij **A/Start/Enter** na URUCHOM. **Nie ma automatycznego uruchamiania gry, limitu czasu ani pomijania menu po błędzie.** Anulowanie wraca bez gry; błąd zatrzymuje Test i zapisuje stały kod diagnostyczny. Domyślne RES/FPS nadal dziedziczą ustawienia głównego launchera. Obraz i pad wymagają potwierdzenia na R36S.

## Test audio bez resetowania prefixu

`Project Diablo 2.sh` domyślnie włącza działające audio z lokalną biblioteką ALSA ARM32 i routingiem rk817 w tle. Opcje testowe audio i próbkowanie tonu zostały usunięte z menu — gra uruchamia się bezpośrednio z aktywnym dźwiękiem. Wyszarzone Sound Settings może oznaczać brak działającego urządzenia audio w Wine — nie potwierdza celowego wyłączenia dźwięku. Sukces ustawienia rejestru i dostęp do węzła ALSA nie dowodzą słyszalnego dźwięku.

AUDIO TEST ON zapisuje dodatkowo: `audio_driver` (`loaded` oznacza aktywność kanału ALSA, nie potwierdzenie sprawności odtwarzania — próby z WINEDEBUG=+alsa, log wyłącznie w RAM z limitem rozmiaru, nie na karcie; przy porażce niesie zamknięte `detail`: `no_log`/`silent`/`libasound`/`load_error`/`alsa_error`/`unknown`/`capture_error`/`capture_timeout`), `audio_control` (dostęp do /dev/snd/controlC*) oraz `audio_fallback`. Gdy pierwsza trasa rk817 nie zagra, fallback jest jawnie logowany jako `attempted` i próba jest ponawiana na domyślnej trasie systemowej; przy sukcesie pojawia się `skipped`. Odczyt jest wyłącznie diagnostyczny — bez zmian miksera, uprawnień i plików systemowych.

Rewizja jest oznaczona zdarzeniem `audio_diagnostics: legacy_v7`. AUDIO TEST ON (także DEFAULT w launcherze Test) wybiera lokalną bibliotekę ARM32 alsa-lib 1.2.8 z tradycyjnym ABI time32/SYNC_PTR (132 B, żądanie `0xC0844123`, zamiast odrzucanego `0xC0884123`). Biblioteka jest uwierzytelniana SHA-256, kopiowana do prywatnej pamięci RAM i dodawana na początek ścieżek ARM32 po zatrzymaniu Wine. Używają jej natywne testy ARM32 i Wine/Box86 w tej sesji; test AArch64 zachowuje bibliotekę 64-bitową. `audio_library: legacy_armhf` potwierdza wybór; `unavailable` oznacza pozostawienie wcześniejszych ścieżek. Główny launcher oraz jawne AUDIO TEST OFF zachowują dotychczasową ścieżkę. Biblioteki systemowe, kernel i mikser nie są modyfikowane.

`audio_syscall_library` z `arch: armhf` i `status: legacy_armhf` potwierdza zaobserwowane otwarcie lokalnej biblioteki pod strace, bez eksportowania jej ścieżki. Źródła i licencja są dołączone w `compat/alsa-legacy-armhf/alsa-lib-1.2.8.tar.bz2` oraz `licenses/LICENSE-alsa-lib.txt`. Ta binarka wymaga ARM32 glibc co najmniej 2.29; ewentualny błąd ładowania pokaże test natywny. Użytkownik potwierdził działający dźwięk na R36S, ale zgłasza duże lagi.

Obie próby (rk817 i ewentualny fallback default) przechwytują `+alsa`. Kolektor zapisuje do 262144 B w RAM i opróżnia resztę strumienia. Wynik jest odczytywany po zatrzymaniu Wine i zakończeniu kolektora; dodatkowy limit oczekiwania na kolektor wynosi 3 s. `capture_timeout` i `capture_error` oznaczają problem diagnostyki, a nie potwierdzoną awarię winealsa. `silent` wymaga obecności markera. Sam dostęp do węzłów ALSA nie potwierdza działającego odtwarzania.

Przed każdą próbą Wine wykonywany jest bezpośrednio mały program ARM32 (bez Box86), z tym samym użytkownikiem, przestrzenią nazw, `ALSA_CONFIG_PATH` i ścieżkami bibliotek ARM32. Ładuje dynamicznie `libasound.so.2` i wykonuje `snd_pcm_open` dla odtwarzania w trybie nonblocking, kolejno dla `default` oraz jednoznacznie wykrytego `plughw`. Udane otwarcia są zamykane bez ustawiania parametrów i bez zapisu dźwięku. Limit uruchomienia wynosi 8 s. Binarka jest uwierzytelniana SHA-256 i wykonywana z prywatnej kopii w RAM.

- `audio_native_armhf: ready` oznacza, że program załadował bibliotekę i zwrócił poprawny raport — nie że otwarcia się udały. Inne statusy obejmują `timeout`, `failed`, `missing`, `tampered`, `library_missing`, `symbol_missing`, `unsupported`.
- `audio_native_default` i `audio_native_plughw`: `ready` oznacza udane otwarcie PCM; przy błędzie występuje klasa i `alsa_rc`. `not_run` dla plughw oznacza brak jednoznacznego wyboru karty/urządzenia.
- Gdy natywny ARM32 też zwróci `-25`, problem daje się odtworzyć bez Box86. Gdy ARM32 otwiera PCM, a Wine nie — zawęża to problem do ścieżki Wine/Box86 lub różnic sposobu użycia ALSA. Udane otwarcie nadal nie dowodzi słyszalnego odtwarzania.

Ta sama próba wykonywana jest także jako natywny AArch64, z bibliotekami 64-bitowymi i bez preloadu ARM32: `audio_native_aarch64`, `audio_native64_default`, `audio_native64_plughw`. Wyniki bazowe są zbierane bez śledzenia. Osobne, dodatkowe uruchomienie każdej architektury pod strace 6.1 śledzi tylko `open`, `openat`, `ioctl`, `close`. Tracer AArch64 dostaje środowisko 64-bitowe; ścieżki ARM32 są przekazywane wyłącznie dziecku. Każde uruchomienie ma limit 8 s, więc cały zestaw może potrwać dłużej niż poprzednia diagnostyka.

- `audio_syscall_trace`: pole `arch` (`armhf`/`aarch64`) i status `complete`, `limited`, `not_observed`, `denied`, `unavailable`, `timeout`, `missing` lub `tampered`. Odmowa ptrace nie oznacza awarii audio i nie blokuje gry.
- `audio_syscall_open`: kategoria żądanej ścieżki `node` (`pcm`/`control`), wynik `syscall_rc`, a po sukcesie także `fd`. `device_kind` i numery `device_major`/`device_minor` opisują rzeczywisty cel deskryptora, jeśli strace go rozpoznał.
- `audio_syscall_ioctl`: `arch`, `node`, `fd`, liczbowy `request`, `syscall_rc` (np. `-25`) oraz dostępne dane urządzenia. `node: unknown` oznacza brak pewnego przypisania deskryptora. Nie jest zgadywane poprzednie urządzenie po zamknięciu/reużyciu fd.

Surowy ślad jest zbierany wyłącznie w ograniczonym buforze RAM (256 KiB, z drenażem nadmiaru); do logu trafia maksymalnie 64 różnych obserwacji na ślad. Pełne ścieżki, PID, adresy pamięci i treść buforów nie są eksportowane. Źródła niezmodyfikowanego strace są dołączone w `compat/alsa-native/strace-6.1.tar.xz`, informacje licencyjne w `licenses/LICENSE-strace.txt`.

Diagnostyka enumeracji Wine 8.0 (po każdym raporcie probe):

- `audio_alsa_capture`: `complete` / `limited` (osiągnięto limit zapisu) / `unavailable`.
- `audio_alsa_default` i `audio_alsa_plughw`: zaobserwowana próba otwarcia lub klasy błędów.
- `audio_alsa_control`, `audio_alsa_cards`, `audio_alsa_devices`: ostrzeżenia dostępu do control, enumeracji kart i urządzeń.
- `audio_alsa_stream` i `audio_alsa_params`: błędy otwarcia PCM dla strumienia i odczytu/ustawienia parametrów sprzętowych.
- `audio_alsa_endpoint`: `render_seen` / `capture_only` / `not_observed` — ślad utworzenia nazwy endpointu przez winealsa, nie dowód zarejestrowania go jako aktywnego w Windows.

Klasy błędów: `busy`, `denied`, `missing`, `invalid`, `unsupported`, `other_error`. Rozpoznany liczbowy kod ALSA trafia dodatkowo do `alsa_rc` (ujemna liczba całkowita 32-bitowa). Różne kody tego samego etapu i tej samej klasy pozostają osobnymi zdarzeniami. Brak rozpoznanego kodu nie jest zastępowany zerem. `not_observed` oznacza brak rozpoznanego komunikatu, nigdy potwierdzony brak kart. Ostrzeżenia mogą dotyczyć także wejścia audio; interpretuj je razem z wynikiem probe. Numery kart, nazwy urządzeń i swobodny tekst komunikatów pozostają wyłącznie w RAM.

Najpierw sprawdź FPS ON + AUDIO TEST OFF, potem FPS OFF + AUDIO TEST ON. Sprawdź dźwięk i Sound Settings; jeśli nadal są wyszarzone, prześlij ostatni log z katalogu logs portu (statusy audio_backend/audio_route/audio_device/audio_control/audio_driver/audio_fallback). Nie resetuj prefixu ani nie kasuj konfiguracji.

W głównym folderze `ports` ma pozostać wyłącznie `Project Diablo 2.sh`. Po aktualizacji istniejącej karty usuń wyłącznie stare launchery: `Project Diablo 2 - Native Controller.sh`, `Project Diablo 2 - Controller Test.sh`, `Project Diablo 2 - Native 800x600.sh`, `Project Diablo 2 - Native 1024x768.sh` i `Project Diablo 2 - Audio Test.sh`. Samo wypakowanie ZIP nie usuwa starych plików. Nie usuwaj folderu `projectdiablo2` ani jego skryptów pomocniczych.

Mapowanie pada z 0.1.13 pozostaje bez zmian. Dodatkowe warianty obrazu są dostępne wyłącznie w menu Test; starsze instrukcje poniżej są historyczne.

## Historia: poprawka 0.1.13 — Select, Start, L3, R3 i Menu

Zdjęcie i log testu 0.1.12 potwierdziły wszystkie 17 naciśnięć/zwolnień fizycznych. W XInput brakowało dokładnie Select, Start, L3, R3 i Menu. Przyczyną tych braków były nieprawidłowe lub brakujące przypisania w mapperze; to nie brak fizycznych zdarzeń.

| Przycisk | Potwierdzony kod fizyczny | Docelowy przycisk Xbox |
|---|---|---|
| Select | `0x2c0` | Back |
| Start | `0x2c1` | Start |
| L3 | `0x2c2` | Left Thumb |
| R3 | `0x2c3` | Right Thumb |
| Menu/FN | `0x2c4` | Guide |

Poprawiono tylko te pięć wejść. A/B/X/Y, L1/R1, L2/R2, krzyżak, analogi, program testowy i runtime pozostają bez zmian. **Rezultat poprawki w XInput wymaga ponownego testu na R36S.** Nie dodano systemowego skrótu Start+Select.

## Test przycisków — każdy przycisk osobno

Controller Test z 0.1.12 pozostaje bez zmian i prowadzi kolejno przez **A, B, Y, X, Start, Select, Menu, L1, L2, L3, R1, R2, R3, Up, Down, Left, Right**. Sam test nie uczy ani nie zapisuje nowych przypisań. Wersja 0.1.13 wprowadza pięć jawnych korekt mappera opisanych powyżej.

1. Zamknij port, zrób backup zapisów i wypakuj bieżący ZIP 0.1.17 do tego samego `ports` z nadpisaniem. Nie kasuj danych gry, zapisów, konfiguracji ani prefixu.
2. Uruchom **Project Diablo 2 - Controller Test**. Najpierw puść wszystkie przyciski.
3. Czytaj wiersz **STEP**: na każdy z 17 przycisków masz **6 sekund**. Naciśnij i puść **wyłącznie wskazany przycisk**; nie wciskaj wszystkich naraz. Program sam przechodzi do następnego kroku.
4. **L3/R3 to kliknięcie lewego/prawego analoga**, nie wychylenie. Jeśli analog fizycznie się nie klika, nie wciskaj go na siłę i zgłoś to. **Menu** oznacza osobny przycisk Menu/FN, nie Start/Select. Up/Down/Left/Right sprawdzaj krzyżakiem, nie analogiem.
5. Po 102 sekundach pojawi się **SUMMARY** na około **20 sekund**. Zrób wtedy wyraźne zdjęcie całej tabeli; test zamknie się automatycznie po około **122 sekundach**. Prześlij zdjęcie i ostatni bezpieczny log. Jeśli naciśnięto kilka przycisków w jednym kroku, uruchom test ponownie.

Każdy wiersz ma niezależne kolumny:

- **Physical** — czy fizyczny pad wysłał naciśnięcie i zwolnienie podczas danego kroku; wykrywa też kody jeszcze nieobsługiwane przez mapper bez zgadywania ich przypisania.
- **XInput** — czy oczekiwany przycisk Windows rzeczywiście został naciśnięty i zwolniony w tym samym kroku. Physical=passed i XInput=not_seen wskazuje na brak lub inne przypisanie po drodze, nie automatycznie uszkodzony guzik.

Wyniki: **passed** = naciśnięty i puszczony; **pressed** = wykryte naciśnięcie bez zwolnienia; **not_seen** = nie wykryto świeżego naciśnięcia w tym kroku; **multiple** = kilka fizycznych klawiszy lub utracone zdarzenia, wynik niejednoznaczny; **unavailable** = brak danych. **unsupported** przy Menu oznacza brak rozszerzenia XInput Guide (ordinal 100), nie dowód niedziałającego Menu. Fizyczna kolumna pozostaje użyteczna niezależnie od tego rozszerzenia.

Kod szesnastkowy przy wyniku jest wyłącznie wskazówką na ekranie/testowym tmpfs do rozpoznania nieznanego przypisania. Bezpieczny log przechowuje tylko zamknięte wyniki dla nazwanych przycisków (`physical_button_*`, `xinput_button_*`), bez kodów i strumienia zdarzeń. Przy fallbacku do gptokeyb fizyczna kolumna może być unavailable. W grze nadal nie ma systemowego skrótu Start+Select w dołączonym mapperze; wychodź przez menu gry. **Poprawione mapowanie 0.1.13 wymaga ponownego potwierdzenia na R36S.**

Poniższe instrukcje 45-sekundowego testu dotyczą starszych wersji.

## Sterowanie 0.1.11 — wbudowany mapper evdev→uinput (poprawka Controller Test)

W teście użytkownika 0.1.10 było `XINPUT1_4.dll: ready`, `Connected now: 1/4` i `Movement: left yes`, lecz buttons/right/triggers pozostały `no` mimo naciskania przycisków i poruszania kontrolerem. Potwierdza to wykrycie urządzenia i zmianę lewego analoga, nie pełną sprawność XInput. **Przyczyna nie jest ustalona:** mapowanie SDL/gamecontrollerdb w ścieżce gptokeyb jest hipotezą, nie dowiedzioną ani jedyną przyczyną.

0.1.11 dodaje dołączony mapper [xbox_mapper.py](<scripts/xbox_mapper.py>) (Python, biblioteka standardowa): omija SDL, czyta evdev `GO-Super Gamepad` (`484b:1100`) i tworzy wirtualny `Microsoft X-Box 360 pad` (`045e:028e` v`0104`) przez `/dev/uinput`. Dalsza ścieżka winebus→Wine XInput pozostaje bez zmian, ale kompletność wejścia z nowego mappera wymaga testu.

Zamierzone mapowanie `standard` (kod i zgodność z fizycznym układem wymagają testu sprzętowego; poniżej kody evdev, nie nazwy Linux `KEY_F1`):

| Przycisk pada | XInput |
|---|---|
| A (`0x131`) / B (`0x130`) / X (`0x133`) / Y (`0x134`) | A / B / X / Y |
| L1 (`0x136`) / R1 (`0x137`) | LB / RB |
| L2 (`0x138`) / R2 (`0x139`) — cyfrowe | osie Z/RZ → LT/RT: puszczone 0, naciśnięte 255 |
| Select (`0x13a`) / Start (`0x13b`) | Back / Start |
| D-pad (`0x220–0x223`) | cyfrowy hat |
| FN (`0x2c0`) | Guide (MODE) |
| lewy / prawy analog | lewy / prawy stick (przełączany do pełnego zakresu, strefa martwa ±8000 z ±32767) |

Jeśli dołączony mapper nie wystartuje (np. odmowa `/dev/uinput`), port zapisuje `controller_mapper=fallback` i ponawia start gptokeyb z PortMaster (zachowanie 0.1.10). Kontrola (probe), test 45 s i sprzątanie są bez zmian; zwykły wpis **Project Diablo 2** (mapper klawiatura/mysz) nie jest dotknięty.

### Historyczna instrukcja testu 45 s — bieżący test 17 przycisków opisano wyżej

1. Zamknij port, zrób backup zapisów i rozpakuj ZIP aktualizacji do tego samego `ports` z nadpisaniem. Nie kasuj `gamedata`, runtime, config, prefixu ani save’ów.
2. Uruchom **Project Diablo 2 - Controller Test** (okno XInput jak w 0.1.10).
3. Przez **45 sekund** naciskaj i puszczaj **każdy przycisk osobno**: A, B, X, Y, L1, R1, L2, R2, Select, Start i FN; sprawdź osobno cztery kierunki D-pada, oba analogi w obu osiach i oba triggery. Oczekiwane, jeszcze niepotwierdzone wyniki: `XINPUT1_4.dll: ready`, `Connected now: 1/4`, `Seen: device yes / buttons yes`, `Movement: left yes / right yes` oraz zmiany LT/RT 0↔255. Sprawdź także zgodność każdego fizycznego przycisku z tabelą, brak zablokowanych wejść i powrót analogów do spoczynku.
4. Sfotografuj okno, poczekaj na automatyczny powrót do Ports i prześlij zdjęcie oraz ostatni bezpieczny log z `projectdiablo2/logs`. `controller_mapper=ready` + `mapper_layout=standard` oznacza gotowość mappera, **nie zaliczenie testu przycisków ani fizycznego layoutu**; `controller_mapper=fallback` oznacza użycie gptokeyb.
5. Dopiero po potwierdzeniu wejść uruchom **Project Diablo 2 - Native Controller** i sprawdź menu, ruch, loot i czary na nieważnej postaci; zakończ grę przez jej menu.

**Pending hardware — oczekuje na test R36S:** kod mappera, fizyczny layout, kompletność XInput, zachowanie w PD2, fallback po nieudanym starcie oraz sprzątanie i ponowny start nie są tu oznaczone jako zaliczone. Wbudowany mapper **nie realizuje Start+Select jako systemowego skrótu wyjścia**. Controller Test kończy się automatycznie po 45 s, a z gry należy wychodzić przez menu; historyczne instrukcje skrótu gptokeyb nie dotyczą tego mappera.

Nowe bezpieczne zdarzenia `session_probe` (faza `launch`):

| check | status | Znaczenie |
|---|---|---|
| `controller_mapper` | `ready` | Wbudowany mapper działa: wirtualny Xbox tworzony bezpośrednio ze strumienia evdev pada. |
| `controller_mapper` | `missing` | Nie znaleziono obsługiwanego fizycznego pada GO-Super. |
| `controller_mapper` | `denied` | Odmowa dostÄ™pu do pada lub `/dev/uinput`. |
| `controller_mapper` | `invalid` | Nierozpoznany układ pada lub błąd odczytu. |
| `controller_mapper` | `fallback` | Wbudowany mapper nie wystartował; port używa gptokeyb. |
| `mapper_layout` | `standard` | Wybrany układ kodów GO-Super; fizyczna zgodność wymaga testu. |

Bez globalnych zmian uprawnień, Wine jako root, nowych sterowników ani wymiany runtime. Program probe i mechanizm flag winebus pozostają bez zmian. **Powrót:** po pełnym zamknięciu sesji nadpisz port zachowanym [ZIP-em 0.1.10](<../../../dist/projectdiablo2-port-update-0.1.10-rollback.zip>), zachowując dane, runtime, konfigurację, prefix i zapisy. SHA-256: `05c067f7a4025791a99fc286d1089814cb9caf77c33bd04869d4d2481d03e355`.

## Historia: sterowanie 0.1.10 — rzeczywisty test Windows XInput

Raport z konsoli potwierdza `GO-Super Gamepad` (`484b:1100`), cztery osie, GUID SDL `1900bb3e4b4800000011000000010000`, dostęp O_RDWR oraz rozpoznanie kontrolera przez SDL. Użytkownik uruchamiał PD2 z działającym padem przez LineageOS/Winlator na tej konsoli. Obecna diagnostyka bada ścieżkę Linux/Wine/Box86, nie zakłada braku obsługi w grze.

### Co zmienia test

Native Controller i Controller Test nadal tworzą wirtualnego Xboxa przez gptokeyb przed pierwszym procesem Wine. Następnie jawnie wybierają backend evdev/udev prywatnego Wine: `HKLM\System\CurrentControlSet\Services\winebus`, DWORD `Enable SDL=0`, `DisableInput=0`, `DisableUdevd=1`. Ostatnia opcja wybiera monitor inotify bez polegania na daemonie udev w przestrzeni montowań. Restart prefixowego wineserver jest wymagany, bo flagi są odczytywane przy starcie winebus. Wyłączenie SDL jest celowe — dołączone Wine nie ma tego backendu; możliwy brak fallbacku pozostaje hipotezą do sprawdzenia, nie potwierdzoną przyczyną awarii.

Przed zmianą zachowywane są wyłącznie trzy poprzednie DWORD-y lub informacja o ich braku. Po zakończeniu gry/testu port przywraca je, restartuje wineserver i usuwa marker dopiero po sukcesie. Jeśli sprzątanie przerwano, kolejne uruchomienie (również zwykłego mappera) ponawia restore. Brak działającego wineservera po przerwaniu jest traktowany jako stan już zatrzymany tylko dla udokumentowanego kodu `-k`; timeout lub inny błąd pozostawia marker i zatrzymuje start. Nie edytuj ani nie usuwaj ręcznie markera `pd2-winebus-restore.reg` w prywatnym prefixie. Nie kasuj prefixu; przed powrotem do starszego kodu uruchom i zamknij zwykły wpis 0.1.10, żeby dokończyć ewentualny restore. Bez globalnych zmian uprawnień, Wine jako root, nowych sterowników lub wymiany runtime.

### Historyczna instrukcja testu 45 s — bieżący test 17 przycisków opisano wyżej

1. Zamknij port, zrób backup zapisów i rozpakuj ZIP aktualizacji do tego samego `ports` z nadpisaniem. Nie kasuj `gamedata`, runtime, config, prefixu ani save’ów.
2. Uruchom **Project Diablo 2 - Controller Test**. To teraz własny program Windows x86, odpytujący dokładnie `XINPUT1_4.dll / XInputGetState` dla slotów 0–3. Nie uruchamia PD2, `joy.cpl`, dodatkowego mappera myszy ani klawiatury. Program jest sprawdzany rozmiarem i SHA-256 przed uruchomieniem.
3. Przez **45 sekund** porusz oboma analogami, D-padem i naciśnij A/B/L1/R1/L2/R2. Powinno być `XINPUT1_4.dll: ready` oraz `Connected now: 1/4` (lub więcej). Wartości slotu powinny się zmieniać; `Seen: device yes / buttons yes`, `Movement: left yes / right yes` dowodzą dojścia wejścia do Windows XInput. Początkowe niezerowe wartości nie są uznawane za zmianę.
4. Sfotografuj okno. Poczekaj na automatyczny powrót do Ports; test nie wymaga myszy. Prześlij ostatni log z `projectdiablo2/logs`. Zapisuje wyłącznie enumy, nie surowe przyciski/osie ani zdjęcie. Jeśli panel nie otworzy się, również prześlij log — nie zmieniaj uprawnień i nie resetuj prefixu.
5. Jeśli urządzenie jest podłączone i wejście się zmienia, uruchom **Project Diablo 2 - Native Controller** i sprawdź ruch/loot/czary na nieważnej postaci. Jeśli XInput działa, a gra nadal nie, rozdzielimy wtedy problem konfiguracji/pollingu gry od wykrywania przez Wine.

Znaczenie bezpiecznych zdarzeń `session_probe`:

| check | status | Znaczenie |
|---|---|---|
| `virtual_gamepad` | `ready` | Nowy wirtualny Xbox istnieje i jest dostępny w Linux; jeszcze nie dowód XInput. |
| `winebus_backend` | `udev` / `restored` | Wybrano backend i zrestartowano Wine / przywrócono stare flagi. |
| `xinput_api` | `ready` / `library_missing` / `entry_missing` | Załadowano bibliotekę i funkcję / brak biblioteki / brak eksportu. |
| `xinput_devices` | `ready` / `missing` / `error` | Co najmniej raz połączony slot / brak slotów / błąd API. |
| `xinput_buttons`, `xinput_axes` | `changed` / `unchanged` / `unavailable` | Rzeczywista zmiana od początkowej próbki / brak zmiany / nie było urządzenia. |

Podsumowanie powstaje w ulotnym katalogu sesji, jest walidowane zamkniętym schematem i przekazywane do bezpiecznego logu. Surowe wartości widać tylko w oknie. **Testy PC z syntetyczną DLL nie są testem Wine/ARM ani dowodem działania na R36S.** Zwykły wpis **Project Diablo 2** pozostaje powrotem do mappera z L1=Alt. Select+Start awaryjnie zamyka wyłącznie tę sesję; w teście lepiej poczekać 45 s, aby otrzymać pełny raport. Obraz, dane, zapisy i runtime pozostają bez zmian.

## Historia: sterowanie 0.1.9 — wirtualny Xbox 360 przez udev

Test użytkownika nie potwierdził sterowania w grze. Ruch kursora i A w dawnym panelu były osobnym mapperem nawigacyjnym, nie dowodem działania Wine/XInput. Poniższe kroki opisują starą wersję, nie bieżący test.

Wersja 0.1.8 nie obsłużyła natywnego pada w teście użytkownika. Dołączone Wine 8 ma backend udev, ale **nie ma wkompilowanego backendu SDL kontrolerów**. W 0.1.9 wpis **Project Diablo 2 - Native Controller** uruchamia `gptokeyb xbox360`: fizyczny pad R36S → mapowanie SDL PortMaster → wirtualny Xbox 360 → Wine/udev → PD2. Nie emuluje WASD ani kliknięć w rozgrywce. Nie wymienia Wine/Box86, nie instaluje sterowników i nie zmienia uprawnień urządzeń.

### Jak sprawdziÄ‡ na R36S

1. Zrób własny backup zapisów, zamknij port i rozpakuj ZIP aktualizacji do tego samego `ports` z nadpisaniem plików portu. Nie usuwaj prefixu, konfiguracji ani danych gry. W razie potrzeby odśwież listę Ports. Wymagany gptokeyb PortMaster z obsługą `xbox360` oraz istniejący dostęp użytkownika do uinput i zdarzeń kontrolera.
2. Najpierw uruchom **Project Diablo 2 - Controller Test**. Ten wpis otwiera panel Wine `joy.cpl` w tym samym środowisku/prefixie co PD2, **nie uruchamia gry**. Osobny mapper działa tylko w panelu: prawy analog porusza myszą, A klika, B = Esc, Start = Enter, R2 spowalnia kursor. Nie jest uruchamiany podczas rozgrywki.
3. Sprawdź, czy lista zawiera **Microsoft X-Box 360 pad** (lub odpowiednik nazwy pada Xbox w Wine). Wybierz go, otwórz właściwości/Test i porusz analogami oraz naciskaj przyciski; jeśli panel udostępnia zakładkę XInput, sprawdź ją również. Sama obecność na liście HID/DirectInput nie dowodzi działania XInput. W panelu prawy analog jednocześnie porusza kursorem — to celowa pomoc diagnostyczna, nie sterowanie gry.
4. Zamknij test, następnie uruchom **Project Diablo 2 - Native Controller**. Na nieważnej postaci sprawdź ruch, L1 przy leżącym loocie i kierunek czaru po zmianie kierunku ruchu. Mapowanie umiejętności jest natywnym mapowaniem PD2, nie tabelą mappera poniżej.
5. Jeżeli port wraca do menu przed otwarciem panelu albo lista jest pusta, prześlij log ostatniej sesji i zdjęcie panelu. W logu `session_probe / virtual_gamepad` oznacza: `ready` — NOWE wirtualne urządzenie Xbox istnieje w Linuksie i użytkownik może je otworzyć do odczytu/zapisu; `missing` — nie powstało w ciągu 5 s; `denied` — odmowa dostępu; `invalid` / `unavailable` — błąd preflight. **`ready` nie dowodzi enumeracji w Wine ani działania XInput.** Nie naprawiaj tego przez `chmod 666` ani uruchamianie Wine jako root.

Wirtualny Xbox powstaje przed pierwszym procesem Wine; port czeka maksymalnie 5 s na nowe urządzenie i nie startuje gry, jeśli sprawdzenie się nie powiedzie. Probe nie odczytuje przycisków ani zdarzeń wejścia; zapisuje wyłącznie anonimowy status. Urządzenie znika po zakończeniu sesji mapującego procesu.

**Powrót:** uruchom zwykłe **Project Diablo 2** (mapper, L1=Alt); nie trzeba zmieniać JSON ani usuwać prefixu. **Select+Start** to awaryjne zamknięcie wyłącznie tej sesji, z ryzykiem utraty niezapisanego postępu. Tryby natywne nadal używają sesyjnych flag ruchu z 0.1.8; oryginalne flagi trwałego JSON są zachowane podczas synchronizacji. Obraz i save’y nie są zmieniane tą poprawką. **Rzeczywiste działanie wirtualnego pada w Wine/PD2 wymaga potwierdzenia na R36S.**

Mechanizm pochodzi z [gptokeyb](https://github.com/PortsMaster/gptokeyb#use); [kod urządzenia Xbox](https://github.com/PortsMaster/gptokeyb/blob/main/src/xbox360.cpp). Podobny problem Box86/Wine opisano w [#809](https://github.com/ptitSeb/box86/issues/809); nie jest to dowód identycznej przyczyny na R36S.

## Historia: sterowanie 0.1.8 — dwa oddzielne wpisy w Ports

* **Project Diablo 2 - Native Controller**: eksperymentalny natywny pad PD2. Sesyjnie `controller_movement=true`, `wasd_movement=false`; mapper nie generuje WASD, kliknięć ani ruchu kursora. Sterowaniem, lootem i kierunkiem czarów zarządza gra. Nie zmieniamy globalnej konfiguracji Wine, sterowników ani uprawnień urządzeń. Natywne wykrycie pada przez Wine/PD2 **wymaga testu na R36S**, nie wynika z działania mappera SDL. `swap_ab` dotyczy tylko mappera, nie natywnego pada.
* **Project Diablo 2**: znany mapper klawiatura/mysz i łatwy powrót, bez edycji JSON. **L1 = przytrzymaj Alt, aby pokazać nazwy lootu** (zastępuje dotychczasowe F1). W tym trybie czary nadal celują w kursor — to nie jest natywne celowanie.

Rozpakuj aktualizację do tego samego `ports`, nadpisując pliki portu; zachowaj dane, konfigurację, prefix i save’y. Odśwież listę Ports, jeśli drugi wpis nie jest widoczny. Zrób backup zapisów i testuj nieważną postać. Uruchom Native Controller, sprawdź reakcję menu, ruch, L1 przy leżącym przedmiocie i kierunek czaru po zmianie kierunku ruchu. Brak reakcji oznacza nieudany test natywnego wejścia, nie powód do kasowania prefixu. **Select+Start** zachowuje awaryjne wyjście tej sesji; może utracić niezapisany postęp. Jeśli również ono nie reaguje, użyj zwykłego wyjścia firmware. Następny start zwykłym wpisem wraca do mappera. Pozostałe ustawienia obrazu i zapisów pozostają takie jak w 0.1.7.

Flagi ruchu są nadpisane tylko w kopii roboczej na czas sesji; synchronizacja zachowuje pierwotne wartości tych dwóch kluczy w trwałym JSON, a pozostałe zmiany gry zapisuje normalnie. Log `movement_mode` pokazuje wybrany tryb, **nie potwierdza wykrycia urządzenia przez XInput**.

## Obraz 0.1.7 — eksperymentalne pełne 4:3 (800×600)

W 0.1.6 potwierdzono zapisy i menu, ale rozgrywka pokazuje panoramiczny obraz z pasami i nie ma w niej wyboru żadnej rozdzielczości. Analiza bajtowa zaimportowanej biblioteki `SGD2FreeRes.dll` dowodzi, że ta ograniczona kompilacja PD2 **zawsze tworzy w grze 1068×600** (stały wektor rozdzielczości oraz parser wymuszający te stałe); klucze `Ingame Resolutions`/`Ingame Resolution Mode` z `SGD2FreeResolution.json` są w niej nieoperatywne, więc edycja tego pliku obrazu nie naprawi.

Za zgodą użytkownika 0.1.7 tworzy **lokalną, przypiętą hashami kopię** tej biblioteki z dokładnie dwiema zmianami po cztery bajty (szerokość 1068 → 800 w dwóch stałych) w prywatnym stanie urządzenia, a w katalogu roboczym sesji podłącza kopię zamiast oryginału. **Pierwotne dane gry, zapisy i prefix nie są zmieniane**; ZIP aktualizacji **nie zawiera** biblioteki. Przy każdym starcie w trybie 800×600 port ponownie weryfikuje oryginał rozmiarem i SHA-256; nieznaną lub zmienioną bibliotekę odrzuca przed uruchomieniem gry (zamknięty kod błędu, bez treści pliku). Kopię buduje tylko z rozpoznanej wersji; nie jest to ogólny patcher DLL.

Obraz: **gra 800×600 → cnc-ddraw 7.1.0.0 → 640×480**, pełne 4:3 bez pasów. **Nie wykonano prawdziwego testu gry/Wine/ARM dla tego wariantu: interfejs 800×600 może być obcięty lub nakładać się, a pozycja kliknięć może wymagać korekty.** Przed aktualizacją wykonaj własny backup zapisów i testuj wyłącznie na nowej, nieważnej postaci: ekwipunek, stash, handel, umiejętności, pas mikstur i zgodność kliknięć.

**Powrót do obrazu 1068×600 z pasami bez resetu:** w `config/settings.json` ustaw `"game_resolution": "native"` (pozostałe klucze zostaw) i zamknij port przed uruchomieniem. Nie wymaga to kasowania cache ani resetu prefixu; oryginalna biblioteka pozostaje nietknięta. Pełny powrót kodu: [ZIP 0.1.6](<../../../dist/projectdiablo2-port-update-0.1.6-rollback.zip>).

## Historia: zapisy 0.1.6 — potwierdzone

Użytkownik potwierdził prawidłowe skalowanie w 0.1.5 oraz działanie obu analogów, A/B i X/Y. Po wgraniu 0.1.6 potwierdził, że **zapisy są widoczne i menu działa prawidłowo**; nie ustalono, która z poniższych zmian była przyczyną poprawy.

0.1.6 **nie zmienia obrazu, wrappera ani mapowania kontrolera**. Ujednolica wskazanie zapisów: ponownie ustawia rejestrowe `Save Path` na `S:\` również w istniejącym prefixie i jednorazowo ustawia tylko `classic_game_settings.other.save_path` aktywnego JSON na `S:\`. Poprzednie bajty zmienionego JSON zachowuje w `config/backups/ProjectDiablo.json.save-path-v1.bak`; nie nadpisuje flag WASD/kontrolera ani innych ustawień. Marker `config/.save-path-v1.json` oznacza zakończoną migrację. Późniejszych zmian tego pola nie poprawia bez końca — pokaże je diagnostyka. Same save’y nie są kopiowane, otwierane, konwertowane ani przenoszone przez aktualizator.

Gra startuje na tym samym pulpicie `PD2Native,640x480`, ale z jawnym katalogiem Windows ustawionym przez `start.exe /d ... /exec ...`. Nie twierdzimy, że Explorer zmieniał katalog — kod Wine 8 tego nie dowodzi; teraz nie polegamy na dziedziczeniu katalogu.

Widoczność zapisów została potwierdzona przez użytkownika po tej aktualizacji.

## Historia: aktualizacja obrazu 0.1.5

Zdjęcie użytkownika potwierdza dojście do menu PD2, lecz z uciętym obrazem. Ta wersja zachowuje rozdzielczość gry **1024×768**, ale używa osobnego cnc-ddraw **7.1.0.0**, aby zmniejszyć ją do **640×480** przed Wine/Xwayland/Weston. Pulpit Wine i Crusty są teraz 640×480. Nie zakładamy już, że większa wirtualna rozdzielczość Crusty sama skaluje obraz na ekranie R36S.

Przy pierwszym starcie aktualizacji ustawienia obrazu obu profili przechodzą jednorazową migrację z backupem. Gra, oryginalny DirectDraw, zapisy i prefix nie są usuwane ani podmieniane. Nowa biblioteka jest osobnym dodatkiem w [compat](<compat/cnc-ddraw/manifest.json>), wybieranym tylko w katalogu roboczym sesji. **To poprawka eksperymentalna: testy PC nie potwierdzają działania nowego wrappera z PD2 na R36S.** Najpierw sprawdź GDI, całe menu i pozycję kliknięć na testowej postaci.

### Historia wcześniejszych poprawek (0.1.0–0.1.4)

**To nie jest natywny port ARM ani zatwierdzony port PortMaster.** Jest to prywatny launcher: Box86 ARM32 → Wine 8.0 x86 → PD2 `Game.exe -ddraw`, z WestonPack/Xwayland. Pierwszy test użytkownika na R36S zakończył się powrotem do EmulationStation przed fazą Wine/gry. Wersja 0.1.1 poprawia nieobsługiwane `seatd -s`, izoluje domyślne gniazdo w prywatnym `/run` i dodaje dokładne etapy do bezpiecznego logu. Drugi test (0.1.1) przeszedł seatd, ale zatrzymał się na awarii Westona. Wersja 0.1.2 poprawia potwierdzone blokowanie odmontowania przez cwd, weryfikuje prawdziwe SDL/EGL i ich architekturę, dopuszcza nazwy bibliotek z upstream, izoluje SDL od własnego nieskonfigurowanego DISPLAY/Wayland i uruchamia sam compositor jako root zgodnie z WestonPack (Wine/Box86/Windows gra pozostają zwykłym użytkownikiem). Log otrzymuje tylko enumy prób bibliotek i etapów Westona, nie surowe trace/ścieżki. Trzeci log (0.1.2) potwierdza gotowe EGL/GL/wyjście i moduł Xwayland, lecz zatrzymuje się na `x11_probe_failed`, przed Wine. Wersja 0.1.4 dodaje prywatny plik Xauthority z sesyjnym cookie MIT-MAGIC-COOKIE-1 dla rootowego Xwayland oraz lokalny test prawdziwej odpowiedzi protokołu X11 jako użytkownik gry, osobno dla gniazda plikowego i abstrakcyjnego, zamiast zależnego od Xlib narzędzia `xdpyinfo`. Rozróżnia uprawnienia, odmowę, timeout, autoryzację i błędną odpowiedź oraz start/awarię leniwie uruchamianego Xwayland. Wyłącznie prywatne root-owned gniazdo X0 otrzymuje grupę użytkownika i tryb 0660; runtime kompozytora pozostaje 0700. Nie zmienia gniazd hosta. Log 0.1.3 dowodzi odrzucenia pustego uwierzytelnienia przez działający Xwayland; 0.1.4 przekazuje prywatne cookie i wymaga kolejnego testu sprzętowego. Zgodność aktualnej wersji PD2, obrazu, dźwięku i FPS nadal trzeba sprawdzić na urządzeniu. Aktualizuj wyłącznie ZIP-em portu; nie kopiuj ponownie gry ani runtime i nie resetuj prefixu. Wynik z innego handhelda nie dowodzi zgodności R36S.

## 1. Pierwsza instalacja — dane tylko raz

1. Zaktualizuj PortMaster na dArkOSen. Wymagany system aarch64 z obsługą ARMHF, narzędziami Python 3, sudo, mount/squashfs, unshare, runuser, timeout, flock oraz dostępem do DRM/uinput. Firmware powinno już zawierać SDL2/ALSA/udev/freetype ARMHF. Port nie instaluje pakietów systemowych ani binfmt.
2. Wyłącz grę i wykonaj własny backup istniejących postaci. Kopia przygotowana na PC **nie importuje zapisów ani kont z Windows**.
3. Skopiuj **zawartość katalogu `sdcard/ports` z przygotowanej paczki** do katalogu `ports` na partycji z ROM-ami (EASYROMS; `/roms/ports` albo `/roms2/ports`). Ma powstać [launcher](<../Project%20Diablo%202.sh>) oraz sąsiadujący katalog `projectdiablo2`. Nie kopiuj katalogów narzędzi, testów, cache ani `.state` z PC. Nie twórz dodatkowej kopii `Live` ani ZIP-a zawierającego grę.
4. Dane `gamedata/Diablo II` zostały już skopiowane jednorazowo z legalnej instalacji Diablo II + LoD + PD2. Nie przenoś ich do innego folderu. Nie publikuj danych gry ani klucza instalacyjnego.
5. Z menu **Ports**, jako zwykły użytkownik firmware (zwykle `ark`), wybierz Project Diablo 2. Nie uruchamiaj launchera jako root. Na exFAT uprawnienia wykonania zapewnia montowanie firmware; na ext4 nadaj launcherowi prawo wykonywania, jeśli menu go nie uruchamia.
6. Pierwszy start rozpakowuje runtime do prywatnego systemowego katalogu Linux, tworzy prefix win32 i instaluje podpisany VC++ x86. Może potrwać kilka minut. **Nie odcinaj zasilania.** Kolejne uruchomienia nie instalują go ponownie.
7. Wybierz **Single Player**, utwórz nową postać i przetestuj nową grę przed kopiowaniem cennych zapisów. Nie używaj Battle.net, launchera .NET, aktualizatora PD2 ani PlugY.

Zostaw dodatkowo przynajmniej około 1 GB wolnego miejsca w systemie Linux na runtime/prefix oraz zapas miejsca na SD na zapisy. Prefix wymaga Linux/ext4 i symlinków: **nie przenoś go na FAT/exFAT**. Runtime jest częścią pierwszej instalacji; nie wymaga kolejnego pobierania na konsoli.

## 2. Gdzie sÄ… dane i ustawienia

| Element | Miejsce na urzÄ…dzeniu |
|---|---|
| Jedyna kopia EXE/DLL/MPQ i klucza | `ports/projectdiablo2/gamedata/Diablo II` |
| Aktywne ustawienia | `ports/projectdiablo2/config` |
| Postacie, stash i mapy | `ports/projectdiablo2/saves` — w Wine dysk `S:` |
| Ograniczona diagnostyka | `ports/projectdiablo2/logs` |
| Prefix i rozpakowany runtime | `$HOME/.local/share/pd2-r36s` |

Podczas gry dane są podłączone **tylko do odczytu**. Katalog roboczy zawiera symlinki do tej samej kopii danych, nie drugi zestaw MPQ. Silnikowe pliki diagnostyczne w katalogu roboczym trafiają do ograniczonego tmpfs 16 MiB i znikają po sesji. Tylko sześć małych, sprawdzonych plików konfiguracji jest synchronizowanych z powrotem; jedna poprzednia wersja trafia do `config/backups`. Zapisy na `S:` są trwałe i nie zależą od tmpfs.

Prefix jest prywatnym stanem Wine — może zawierać rejestr i tymczasowe dane instalatora. Nie jest przeznaczony do udostępniania. Nie zmieniaj katalogów ani ustawień, kiedy gra jest uruchomiona.

## 3. Obraz i wydajność

Domyślnie od 0.1.7: gra **800×600** (lokalna kopia biblioteki SGD; patyz wyżej), pulpit Wine / Crusty / wyjście **640×480** (ekran R36S 4:3), renderer **GDI**, limit renderowania **30 FPS**, bez shaderów. cnc-ddraw 7.1.0.0 wykonuje downscaling w trybie borderless: `windowed=true`, `fullscreen=true`, `maintas=true`, `adjmouse=true`, `inject_resolution=1024x768`. `maintas` zachowuje proporcje, więc pełne 4:3 wypełnia ekran, a oryginalna biblioteka (~16:9, 1068×600) daje pasy. `adjmouse` zapewnia przeliczenie pozycji kursora przy skalowaniu. W tej kompilacji PD2 wewnętrzne menu rozdzielczości nie działa, a `SGD2FreeResolution.json` nie zmienia rozgrywki — wyborem obrazu steruje `game_resolution` w `config/settings.json`. Zgodność wariantu 800×600 i wydajność wymagają testu sprzętowego. Limit nie jest obietnicą 30 FPS i nie zmienia ticków symulacji Diablo II. Bez Vulkan, DXVK i D2GL.

Po pierwszym starcie w `config/settings.json` można ustawić:

```json
{
  "schema_version": 1,
  "profile": "gdi",
  "swap_ab": false,
  "game_resolution": "800x600",
  "metrics": false
}
```

* `game_resolution: "800x600"` — domyślnie w 0.1.7; pełne 4:3 z lokalną, przypiętą kopią biblioteki SGD.
* `game_resolution: "native"` — oryginalna biblioteka z danych gry; obraz 1068×600 z pasami. Powrót bez kasowania cache ani resetu prefixu. Istniejący plik ustawień nie jest nadpisywany — klucz dodaje się ręcznie lub zostaje domyślne `800x600`.
* `profile: "opengl"` — alternatywny eksperymentalny GL4ES/Crusty GLX + headless Weston; sprawdź dopiero po GDI. Ciemny ekran nie dowodzi błędu danych gry. Powrót do `gdi` nie kasuje prefixu ani zapisów.
* `swap_ab: true` — odwraca funkcje A/B, jeśli mapowanie firmware jest odwrotne niż oczekujesz. Nie zmienia firmware.
* `metrics: true` — dopisuje co 5 sekund wyłącznie liczby: dostępną RAM, wolne miejsce i temperaturę, gdy system ją udostępnia. Pojedynczy pomiar startowy jest wykonywany również przy `false`.

Szablony [GDI](<defaults/ddraw-gdi.ini>) i [OpenGL](<defaults/ddraw-opengl.ini>) są kopiowane przy tworzeniu konfiguracji. **Wyjątek 0.1.5:** jednorazowa migracja zmienia tylko wskazane klucze obrazu w sekcji `[ddraw]` obu aktywnych profili, zachowując pozostałe ustawienia, komentarze i sekcje oraz poprzednie bajty w backupie. Kolejne starty nie przywracają tych wartości na siłę. Zwykły wpis sesyjnie konfiguruje `wasd_movement=true` i `controller_movement=false`, a Native Controller odwrotnie; nie włącza równocześnie dwóch sposobów ruchu.

## 4. Sterowanie

Nazwy przycisków dotyczą mapowania SDL/PortMaster; dArkOSen może już zamieniać A/B. Fn/R3 pozostają hotkeyami firmware.

**Poniższa tabela dotyczy zwykłego wpisu (mapper), nie wpisu Native Controller.** To emulacja klawiatury i myszy, nie pełny natywny tryb kontrolera PD2. Krzyżak jest przypisany do mikstur, nie do przeskakiwania kursorem między przyciskami menu. B wywołuje prawy klik, więc zaklęcia celują w położenie myszy; ukrycie kursora nie przełączy ich na kierunek analoga. Od 0.1.8 osobny wpis Native Controller rozdziela ten eksperyment od mappera; jego zgodność z Wine i PD2 nadal wymaga osobnego testu sprzętowego.

| Przycisk | Funkcja |
|---|---|
| Lewy analog | WASD, ruch postaci |
| Prawy analog | Kursor myszy |
| A / B | Lewy / prawy przycisk myszy |
| X / Y | Ekwipunek / mapa |
| D-pad góra, prawo, dół, lewo | Mikstury 1, 2, 3, 4 |
| L1 / R1 | Alt (nazwy lootu, przytrzymaj) / umiejętność F2 |
| L2 / R2 | Shift (stój/atak) / wolniejszy kursor |
| Start | Enter |
| Select+B | Escape, menu; **zapisz i wyjdź z menu gry** |
| Select+X / Select+Y | Statystyki / drzewko umiejętności |
| Select+A | Alt, nazwy przedmiotów |
| Select+L1 / Select+R1 | F3 / F4 |
| Select+L2 / Select+R2 | Portal T / przełącz bieg R |
| Start+Select | Wyjście awaryjne tylko tej sesji; ostatnie niezapisane zmiany mogą przepaść |

**Wpisywanie nazwy postaci:** kliknij pole nazwy, naciśnij **Start+D-pad dół**. Góra/dół zmienia literę, prawo przechodzi do następnej, lewo kasuje poprzednią; L1/R1 skacze o 13 liter. Start lub A potwierdza, Select anuluje. Sprawdź działanie na nowej postaci. [Mapowanie podstawowe](<defaults/controls.gptk>) / [A-B zamienione](<defaults/controls-swap.gptk>).

## 5. Aktualizacje — bez gry i zapisów

Zamknij grę. ZIP `projectdiablo2-port-update.zip` rozpakuj **do tego samego katalogu `ports`**, ze zgodą na nadpisanie plików portu. Nie kasuj starego katalogu i nie zastępuj go pustym folderem.

ZIP zawiera launcher, skrypty, domyślne szablony, metadata, instrukcję, licencje oraz **osobny MIT wrapper cnc-ddraw 7.1.0.0**. Nie jest już paczką wyłącznie tekstowego kodu. **Nie zawiera gamedata, klucza, aktywnego config, saves, logs, prefixu, cache ani dużego runtime Wine/Box86/Weston/VC++.** Te runtime pozostają z pierwszej instalacji. Oryginalny `ddraw.dll` w danych PD2 nie jest nadpisywany. Nie kopiuj gry ponownie.

Możesz nadpisywać port tyle razy, ile potrzeba; aktywne dane i ustawienia nie są częścią ZIP-a. Przed aktualizacją zawsze zachowaj własny backup zapisów. Jednorazowa migracja 0.1.5 zapisuje poprzednie zmieniane pliki do `config/backups/<nazwa>.display-640-v1.bak` i kończy się markerem `config/.display-640-v1.json`; te backupy nie są nadpisywane przy kolejnych startach ani przez zwykły backup synchronizacji.

**Powrót, jeśli nowy wrapper nie uruchamia gry:** zamknij port, nadpisz go zachowanym ZIP-em 0.1.4, a następnie przywróć wcześniejsze profile z backupów `.display-640-v1.bak`, jeśli powstały. Stary launcher ponownie wybierze oryginalną bibliotekę z danych PD2 i pulpit 1024×768 (może wrócić znane obcinanie). Osobny plik w `compat` może pozostać — starszy kod go nie używa. Nie usuwaj gry ani prefixu. Przy późniejszym ponownym przejściu na 0.1.5 zachowaj marker pod nazwą backupu, aby migracja mogła wykonać się ponownie. Samo skasowanie nowego DLL bez przywrócenia starego kodu zatrzyma start na walidacji, a nie bezpiecznie przełączy wrapper.

**Powrót z 0.1.6:** po zamknięciu portu nadpisz kod zachowanym ZIP-em 0.1.5. Skalowanie pozostanie takie samo. Jeśli chcesz cofnąć również zmianę wskazania zapisów w JSON, przywróć jego backup `.save-path-v1.bak` (jeżeli powstał), nie przenoś samych postaci. Zmiana rejestru dotyczy tylko wskazania istniejącego `S:`, nie zawartości zapisów. Przy ponownej próbie migracji zachowaj marker `.save-path-v1.json` pod inną nazwą; nie kasuj backupu.

**Powrót z 0.1.7 (obraz):** najprościej w `config/settings.json` po zamknięciu portu ustaw `"game_resolution": "native"` — port ponownie podłączy oryginalną bibliotekę (1068×600 z pasami) bez resetu prefixu ani kasowania cache. Pełny powrót kodu: nadpisz port zachowanym [ZIP-em 0.1.6](<../../../dist/projectdiablo2-port-update-0.1.6-rollback.zip>). Lokalna kopia biblioteki w `.local/share/pd2-r36s` może pozostać — starszy kod jej nie używa.

## 6. Bezpieczne logi i co przesłać do diagnozy

Od 0.1.6 `session_probe` podaje tylko:
* `saves_directory`: dostępność i liczbę zwykłych plików `.d2s` bezpośrednio w trwałym folderze (maksymalnie 4096 przejrzanych wpisów). Nie czyta zawartości postaci ani nie loguje ich nazw.
* `save_mapping`: czy `S:` wskazuje właściwy trwały folder; nie loguje ścieżki.
* `game_config`: czy kopia konfiguracji w katalogu roboczym jest czytelnym JSON.
* `save_path`: `canonical` / `missing` / `other` / `unknown`, bez rzeczywistej wartości innej ścieżki.
* `movement_mode`: `emulated` / `native` / `mixed` / `disabled` / `unknown` na podstawie dwóch flag konfiguracji. To nie jest test działania pada ani odczytu konfiguracji przez samą grę.
* Od 0.1.11 dodatkowo: `controller_mapper` (`ready` / `missing` / `denied` / `invalid` / `fallback`) — stan wbudowanego mappera evdev→uinput w trybie natywnym, oraz `mapper_layout` (`standard`) — wybór układu kodów GO-Super, nie potwierdzenie fizycznego layoutu. Zdarzenia nie zawierają żadnych wartości przycisków ani osi.

`count>0`, `save_mapping=ready`, `game_config=ready`, `save_path=canonical` potwierdzają przygotowanie plików po stronie wrappera, ale nie dowodzą, że silnik gry zaakceptował postacie. Wtedy potrzebna jest dalsza diagnoza zamiast kopiowania/konwersji save’ów na ślepo.

Logi JSONL zapisują jedynie zamkniętą listę faz, kategorii błędów, kodów zakończenia, nazw brakujących bibliotek i liczbowych pomiarów. Od 0.1.4 zdarzenia `x11_probe` zawierają test `identity/socket/filesystem/abstract`, status, czas w ms oraz dla gniazda wyłącznie bity uprawnień i kategorię właściciela `root/user/other` — bez UID/nazwy użytkownika, ścieżki, wartości cookie ani odpowiedzi serwera. Cookie MIT jest losowe, tymczasowe, prywatne dla sesji i nie trafia do logu/eksportu. `connect_timeout` oznacza timeout łączenia, `reply_timeout` brak pełnej odpowiedzi X11, `denied/refused/missing` błąd transportu, `setup_rejected` ogólną odmowę inicjalizacji (nie dowodzi błędu hasła), `auth_rejected` odrzucenie z odpowiedzią wskazującą autoryzację, `auth_required` żądanie dalszej autoryzacji, `ready` pełną odpowiedź Setup. Stan gniazda `ready` oznacza tylko obecność pliku socket; gotowość serwera potwierdza dopiero test transportu. Błędy startu/exec/font Xwayland i nieszkodliwe fallbacki są oddzielnymi zamkniętymi kategoriami. Nieznany stdout/stderr jest **pomijany**, nie zapisywany jako tekst. Nie ma dumpów środowiska, pamięci ani linii poleceń; trace Box86/Wine i core dumps są wyłączone. Limit: **10 sesji po maks. 2 MiB**. Logger dalej opróżnia potok po osiągnięciu limitu lub błędzie zapisu. Dane nie są automatycznie wysyłane.

Po zamkniÄ™ciu gry z terminala konsoli, bÄ™dÄ…c w katalogu `ports/projectdiablo2`:

```bash
python3 scripts/safe_log.py export --dir logs --manifest runtime-manifest.json
```

Powstanie `logs/diagnostic-export.zip`, zawierający ponownie zwalidowane logi z anonimowymi nazwami i tylko projekcję wersji runtime. **Udostępniaj tylko ten eksport**, nie cały folder, surowe pliki D2, konfigurację Windows, prefix, klucz czy zapisy. Podaj osobno: profil GDI/OpenGL, czy było menu, obraz/dźwięk, działanie pada i moment awarii. Bez loginów, haseł i klucza gry.

Typowe kategorie:

* `missing_library`: brakuje podanej biblioteki ARMHF; korzystaj z zaleceń dla swojej wersji firmware/PortMaster, nie instaluj losowych pakietów z internetu.
* `missing_drm_device`, `missing_uinput`, `namespace_unavailable`: niezgodność zasobów systemu/uprawnień lub brak funkcji kernela. Port nie tworzy globalnych urządzeń i nie naprawia systemu automatycznie.
* `display_conflict`: istnieje inny X11; wyjdź z innego portu albo zrestartuj konsolę. Nie zabijaj wszystkich procesów Wine/Weston.
* `compositor_failed`, `compositor_timeout`: ścieżka obrazu nie wystartowała; zachowaj GDI podczas diagnozy i przekaż eksport.
* `x11_probe_failed`, `x11_socket_failed`: Wine jeszcze nie ruszyło; przekaż log z wersją 0.1.4 oraz zdarzeniami `x11_probe`. Nie resetuj prefixu ani nie kopiuj gry.
* `prefix_incomplete`: poprzednia inicjalizacja została przerwana. Nie kasuj gry/zapisów. Po pełnym zamknięciu sesji zachowaj backup i zmień nazwę **wyłącznie** prywatnego `wineprefix` na folder backupu; nowy prefix będzie utworzony przy kolejnym starcie. Przy przerwanym rozpakowaniu zachowaj podobnie podkatalog `runtime-*/extracting` pod nową nazwą. Nie usuwaj całego `.local/share/pd2-r36s` i nie wykonuj masowych resetów.
* `invalid_layout`, `unsupported_runtime`: sprawdź poprawny układ pierwszej instalacji, kompletność runtime i wolne miejsce. Aktualizacja bez danych nie zastępuje pierwszej instalacji.

## 7. Lista testów na R36S

1. Menu i nowa postaÄ‡; nazwa przez interaktywny input.
2. Ruch WASD, celowanie, kliknięcia, mikstury, ekwipunek i umiejętności.
3. Pełne menu (także dolne przyciski), cztery krawędzie obrazu, kliknięcia zgodne z kursorem, ekwipunek i pasek interfejsu: pełne 4:3 — gra 800×600 zmniejszona do ekranu 640×480, bez pasów. Czytelność interfejsu (brak obcięcia/nakładania się), dźwięk i wydajność przez około 10 minut.
4. Zapis i normalny powrót do Ports; ponowny start i odczyt postaci.
5. W zwykłym wpisie klawiatura/mysz, dopiero na testowej postaci: Start+Select i powrót do menu. Wbudowany mapper natywny 0.1.11 nie realizuje tego skrótu systemowego — wyjdź przez menu gry; Controller Test kończy się po 45 s. Nie odłączaj zasilania jako testu.
6. Nadpisanie kodem portu, zachowanie konfiguracji i ponowny odczyt zapisu.
7. Wyeksportuj diagnostykę; jeśli GDI nie działa, osobno sprawdź OpenGL.

## Źródła i licencje

[Firmware dArkOSen-R36S](<https://github.com/djparentx/dArkOSen-R36S>) · [PortMaster](<https://github.com/PortsMaster/PortMaster-New/tree/main/ports>) · [PD2 — wybór Game.exe/-ddraw](<https://raw.githubusercontent.com/Project-Diablo-2/PD2Launcher/master/PD2Shared/Helpers/LaunchGameHelpers.cs>) · [gptokeyb](<https://github.com/PortsMaster/gptokeyb>) · [Wine Builds](<https://github.com/Kron4ek/Wine-Builds>) · [WestonPack](<https://github.com/binarycounter/Westonpack/wiki>).

[Manifest runtime](<runtime-manifest.json>) · [Informacje o licencjach](<licenses/THIRD-PARTY-NOTICES.md>). Paczka jest prywatnym eksperymentem, nie gotową publikacją w katalogu PortMaster.

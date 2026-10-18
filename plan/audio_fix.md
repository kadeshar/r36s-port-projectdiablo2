# Audio fix — kolejne kroki po testach Buffer / Dmix

## 1. Cel i instrukcja dla następnego agenta

**Status: problem otwarty.** Użytkownik po obu próbach nadal słyszy echo/powtarzanie oraz rwanie dźwięku, bez zauważalnej poprawy. Nie uznawać spadku liczby EPIPE za naprawę jakości audio.

Ten dokument zastępuje poprzednią kolejność prac. Dotychczasowe naprawy przekazania SDL, ponownego wykorzystania slotów observera, recovery DirectSound i dodanie tras pozostają w kodzie; nie wykonywać ich ponownie bez wykazanej regresji. Historyczne zielone testy hosta nie potwierdzają jakości na R36S.

**Kolejność:** P0 identyfikacja rzeczywistej trasy → P0 wiarygodny pomiar → krótki test sprzętowy → izolacja producenta/echo → jedna poprawka wynikająca z dowodów → porównanie i długi test. Nie przygotowywać kolejnych launcherów „większy bufor” bez potwierdzenia, co rzeczywiście się zmienia.

Zakres tej aktualizacji: wyłącznie plan. Implementację i testy sprzętowe wykonuje następny agent/użytkownik. Bez urządzenia wynik prac oznaczać „gotowe do testu sprzętowego”, nie „audio naprawione”.

## 2. Co wynika z nowych logów

### 2.1. Źródła

Załączniki są read-only; nie modyfikować oryginałów. Przy delegowaniu przekazać zapisane ścieżki. Dla regresji najlepiej utworzyć małe syntetyczne fixture o tej samej strukturze, bez kopiowania całych logów do payloadu.

- [Buffer: sesja 20261018T152000Z / 35679](<C:/Users/kadeshar/.dsh/attachments/v1/files/0c/0c2223f90493920f383ab75cab7784f4d595e191411f188309ca4b0790f1abc9/pd2-session-20261018T152000Z-35679.jsonl>), SHA-256 `0c2223f90493920f383ab75cab7784f4d595e191411f188309ca4b0790f1abc9`.
- [Dmix: sesja 20261018T152521Z / 39827](<C:/Users/kadeshar/.dsh/attachments/v1/files/57/5718ae2b946f9dceef11ce6c3bef9b3d04767701f369085fd6360bc5c8dfa555/pd2-session-20261018T152521Z-39827.jsonl>), SHA-256 `5718ae2b946f9dceef11ce6c3bef9b3d04767701f369085fd6360bc5c8dfa555`.

### 2.2. Potwierdzone obserwacje

| Pole | Buffer | Dmix |
|---|---|---|
| Wersje raportowane | port 0.1.18, Wine 8.0 | port 0.1.18, Wine 8.0 |
| Wariant / żądana trasa | buffer / buffer160 | dmix / dmix160 |
| SDL / DirectSound | dummy / off | dummy / off |
| Długotrwały PCM | source=1, stream=11 | source=1, stream=21 |
| Rate / kanały / access | 48000 / 2 / 3 (RW_INTERLEAVED) | 48000 / 2 / 3 (RW_INTERLEAVED) |
| Okres obserwowanego PCM | 480 ramek = 10 ms | 960 ramek = 20 ms |
| Bufor obserwowanego PCM | 1920 ramek = 40 ms | 3840 ramek = 80 ms |
| Okno pierwszego–ostatniego snapshotu tego strumienia | 101.302 s | 125.547 s |
| Przyrost `epipe_results` w oknie | 481 | 0 |
| Przyrost `recover_epipe_calls` / `recover_successes` | 908 / 908 | 1 / 1 |
| Końcowe `eagain_results` | 0 | 508 |
| Pokrycie | brak raportowanej utraty | `lost_updates=1`, `data_lost`, `partial_coverage` |

Wspólne: GDI, stock renderer/Box86, BigBlock=2, render 800×600, trasa raportowana jako rk817, zakończenia `rc=0`. SDL dummy tym razem rzeczywiście dociera do runtime. `dsound_profile=off` oznacza brak wymuszania profilu, **nie** wyłączony DirectSound ani potwierdzenie identycznego rejestru między próbami.

### 2.3. Granice interpretacji

1. Nazwy `buffer160`/`dmix160` i `audio_route=rk817` potwierdzają wybór konfiguracji/dostępność urządzenia, nie wykorzystanie jej przez końcowy PCM gry. Obserwowane 40/80 ms dotyczą uchwytu ALSA widzianego przez observer. W dmix bufor klienta i slave sprzętowego mogą się różnić. Nie stwierdzać jeszcze, że sprzęt nie dostał 160 ms.
2. Buffer nadal ma liczne zwroty `-EPIPE`. Nie dodawać 481 i 908: recover może otrzymywać `-EPIPE` także po nieobserwowanych wywołaniach; liczniki nie są liczbą niezależnych słyszalnych przerw.
3. Dmix nie raportuje EPIPE w obserwowanych wynikach, ale ma recover z EPIPE i niepełny pomiar. `EAGAIN` oznacza m.in. chwilowy brak miejsca w trybie nonblocking, nie automatycznie underrun. Potrzebne poprawne retry/poll oraz rozpoznanie wywołania, które zwróciło błąd.
4. Obie sesje zawierają tylko jeden systemowy `metrics`, przed grą. Brak podstaw do korelacji z CPU, swapem, temperaturą, I/O i klatkami. Temperatura startowa różna: 54.583°C / 62.500°C; nie jest to dowód throttlingu.
5. `playback_observed` nie gwarantuje pełnego pokrycia gry: obecny kolektor może nadać status już za kilka ramek zamkniętego probe. W tych logach istnieją jednak także długotrwałe aktywne strumienie.
6. Nie ma nagrania ani znacznika objawu. „Echo” może oznaczać EAX/reverb, ponowne odtworzenie starego fragmentu, opóźnione efekty albo dwa źródła. To odrębne hipotezy, nie rozpoznanie.

**Decyzja:** nie powtarzać niezmienionych Buffer/Dmix i nie zwiększać w ciemno `HelBuflen`. Najpierw udowodnić trasę i rozdzielić błąd ALSA od dostarczania już uszkodzonego/powtarzanego materiału.

## 3. P0 — potwierdzić konfigurację rzeczywiście otwartą przez Wine

### 3.1. Zweryfikować generator i wyeliminować pozorny test Buffer

Punkty wejścia: [audio_config.py](<../sdcard/ports/projectdiablo2/scripts/audio_config.py>), [run-game.sh](<../sdcard/ports/projectdiablo2/scripts/run-game.sh>), [Buffer](<../sdcard/ports/Project Diablo 2 - Audio Buffer.sh>), [Dmix](<../sdcard/ports/Project Diablo 2 - Audio Dmix.sh>).

**Konkretny problem kodu:** generator Buffer wpisuje `period_time` i `buffer_time` do `pcm_slave`, którego używa `type plug`. W lokalnych źródłach ALSA 1.2.8 [pcm_plug.c](<../.state/audio-metrics-build/alsa-lib-1.2.8/src/pcm/pcm_plug.c#L1293-L1298>) przekazuje do `snd_pcm_slave_conf` tylko format/channels/rate; [pcm.c](<../.state/audio-metrics-build/alsa-lib-1.2.8/src/pcm/pcm.c#L7780-L7887>) odrzuca nieznane pola. To przesłanka odrzucenia `default`, nie dowód z logu, jaką alternatywę wybrało Wine. Lokalny katalog builda może nie istnieć u kolejnego agenta — wówczas odtworzyć przypięte źródła.

- [ ] Sprawdzić dokładnie źródła/binary ALSA używane na SD, opcje kompilacji i hash. Odtworzyć `snd_pcm_open("default")` z wygenerowanym Buffer przez **tę samą ARMHF time32 ALSA**, w tym samym środowisku. Zarejestrować kod wyniku i bezpieczny enum błędu; otwarcie to dopiero test składni, potem wymagane `hw_params` i odtwarzanie.
- [ ] Nie „naprawiać” przez przeniesienie tych samych pól do innego nieobsługiwanego miejsca. Jeżeli konfiguracja jest odrzucana, usunąć obietnicę 160 ms i oznaczyć wariant jako nieobsługiwany do czasu rzeczywistego sterowania negocjacją.
- [ ] Testy generatora rozszerzyć poza porównanie stringów: test rzeczywistego parsowania/open na docelowej ALSA, potem odtwarzania i odczytu parametrów. Hostowy test tekstu nie wykrywa fallbacku Wine.

### 3.2. Dodać dowód endpointu i topologii PCM

- [ ] Prześledzić launcher → sudo/env → Weston → run-game → wrapper observera → proces Wine otwierający PCM. Potwierdzić `ALSA_CONFIG_PATH` i załadowaną bibliotekę u tego procesu, nie tylko w rodzicu. Publicznie logować zgodność/hash/enum, nie pełny environ/maps/cmdline.
- [ ] W observerze dodać allowlistowane kategorie otwieranego PCM (`default`, `hw`, `plughw`, `dmix`, `other`), typ pluginu, kierunek playback/capture, tryb nonblocking, źródło i generację strumienia. Nie publikować arbitralnych nazw urządzeń.
- [ ] W kontrolowanym probe odczytać topologię przez API ALSA/dump do prywatnego bufora, następnie zanonimizować. Nie wykonywać dump/logowania na wątku audio. Rozróżnić uchwyt klienta, plugin i sprzęt; nie sumować tych samych ramek przez warstwy.
- [ ] W czasie gry próbkować właściwe `/proc/asound/card*/pcm*p/sub*/hw_params`, `sw_params`, `status`: format, rate, kanały, period/buffer, avail_min, start/stop threshold, stan i dostępne hw_ptr/appl_ptr. Numer urządzenia ustalać przez trasę i właściciela. Brak uprawnień/pól = `unavailable`, nie zero.
- [ ] Sprawdzić wybór endpointu w dokładnie używanym Wine 8.0: enumeracja/default, zapisany wybór aplikacji, fallback po błędzie otwarcia. Zapisać przypięty commit i odpowiednie funkcje. Krótki trace wyłącznie osobno; nie uruchamiać stale `+all` ani strace podczas testów jakości.
- [ ] Zestawiać trzy oddzielne rekordy: **requested profile**, **effective client PCM**, **effective hardware PCM**. W eksperymencie rozbieżność/nieznany routing oznaczyć `mismatch`/`unverified`; nie raportować udanej próby 160 ms.
- [ ] Identyfikator builda obejmuje skrypty i bibliotekę observera. Sam `port_version=0.1.18` nie odróżnia kolejnych zmian. Potwierdzić kopiowanie bieżącego payloadu na SD.

### 3.3. Dmix: IPC i zachowanie pod obciążeniem

- [ ] Obecny generator ma stały `ipc_key 592834`, `ipc_key_add_uid false`, `ipc_perm 0660`. Zaprojektować prywatny klucz sesji wspólny dla wszystkich jej procesów, z wykrywaniem kolizji i bez współdzielenia między użytkownikami. Nie generować innego klucza dla każdego open.
- [ ] Zweryfikować zwykłego użytkownika, ARMHF/time32, format i sprzętowy buffer/period, start/stop/restart oraz restart po awarii. Nigdy nie usuwać obcego IPC i nie zabijać obcych właścicieli PCM.
- [ ] Zmierzyć koszt dmix i opóźnienie. Większy bufor bez właściwego zapełniania/threshold nie zapewnia proporcjonalnego zapasu.

**Brama P0-A:** krótka sesja techniczna pokazuje, co otwiera gra, jaka konfiguracja jest użyta oraz jakie parametry ma klient i sprzęt. Przy fallbacku najpierw naprawić wybór trasy. Dopiero wtedy porównywać bufory.

## 4. P0/P1 — pomiar odpowiadający na pytanie „kiedy i co się rwie?”

Pliki: [audio_metrics_core.h](<../tools/audio_metrics_core.h>), [audio_metrics.py](<../sdcard/ports/projectdiablo2/scripts/audio_metrics.py>), [safe_log.py](<../sdcard/ports/projectdiablo2/scripts/safe_log.py>), [metrics.py](<../sdcard/ports/projectdiablo2/scripts/metrics.py>).

- [ ] Doprecyzować `lost_updates=1` w Dmix. Obecny kod inkrementuje globalny licznik procesu po nieudanym trylock (także w flush) oraz przy reuse dirty retired slot. Nie jest to liczba straconych ramek ani dokładnie jeden utracony write; nie sumować wartości między strumieniami. Rozdzielić contention podczas samego odczytu/flush, pominięcie aktualizacji open/params/result, recycling i straty transportu osobnymi bounded licznikami. Nie ukrywać utraty ani nie usuwać `partial_coverage`, żeby uzyskać zielony wynik.
- [ ] `playback_observed` może pozostać statusem „jakiekolwiek próbki”; dodać osobne potwierdzenie długotrwałego aktywnego playback (np. przyrost w ≥3 snapshotach przez ≥2 s). Zamknięty probe nie może spełniać bramy jakości gry.
- [ ] Rozdzielić błędy write, mmap, avail/status, recover oraz prepare. Rejestrować powód wejścia do recover i jego wynik. Nie utożsamiać `recover_successes` z naprawionymi niezależnymi XRUN.
- [ ] Dodać agregaty czasu: odstęp między udanymi zapisami, czas wywołania, największy odstęp i histogram; osobno czekanie poll i retry EAGAIN. Stała pamięć, nieblokujący transport, bez JSON/alokacji/I/O na callbacku. Uwzględnić mmap, częściowe zapisy i zawijanie liczników.
- [ ] Nie wyznaczać przerw z odstępu ~1 s między snapshotami — to częstotliwość raportowania, nie wywołań audio. Zapas porównywać z rzeczywistym delay/fill, nie zawsze z pełną pojemnością bufora.
- [ ] Włączyć `PD2_METRICS=1` wyłącznie w diagnostyce i sprawdzić przekazanie przez granice procesów. W [run-game.sh](<../sdcard/ports/projectdiablo2/scripts/run-game.sh#L614-L621>) sampler jest warunkowy; samo `PD2_AUDIO_METRICS=1` nie włącza zasobów systemowych. Ustalić realną grę zamiast wrappera Python; brak podwójnego liczenia dzieci.
- [ ] Co 1–2 s: CPU procesów/wątków w ograniczonym zakresie, częstotliwości/temperatura, RAM, delty swap-in/out i major faults, dostępne I/O. FPS/frame-time przez istniejący pomiar; jeśli nie działa, jawnie brak danych. Nie zakładać, że `fps_counter=renderer` oznacza zapisane próbki FPS.
- [ ] Znacznik objawu z monotonic czasem i kategorią: powtórzenie fragmentu, pogłos, przerwa, trzask, opóźnienie. Opcjonalny skrót niekolidujący ze sterowaniem albo notatka użytkownika od początku oznaczonego odcinka.
- [ ] Raport offline grupuje po `(session, source, stream/generation)`; liczy delty i faktyczne okno pokrycia. Oddziela probe/start/stop od menu/miasta/walki. Nie sumuje snapshotów kumulacyjnych, warstw ALSA ani EPIPE+recover. Ujemne delty = reset/nieprawidłowość, nie bezwarunkowe zero.
- [ ] Jedna krótka próba observer on/off przy identycznej konfiguracji ocenia wpływ pomiaru. Telemetria też może pogarszać deadline; brak observera oznacza wtedy brak liczników, nie zero błędów.

**Brama P0-B:** log obejmuje całą próbę, rozpoznaje utratę danych, zawiera parametry klienta/sprzętu i próbki zasobów w czasie gry. Jeśli pełne pokrycie chwilowo niemożliwe, dopuścić odsłuch/probe z oznaczeniem ograniczeń, lecz nie wnioskować „zero XRUN”.

## 5. P1 — oddzielić echo od underrunów i zlokalizować warstwę błędu

### 5.1. Powtarzalny scenariusz gry

- [ ] Utrzymać GDI, tę samą rozdzielczość, stock Box86, lokację, postać, głośność i trasę. EAX/Environmental Effects wyłączone i potwierdzone w grze; logi tego nie dowodzą. Backup ustawień przed próbami, restore także po przerwaniu.
- [ ] Nagrać opcjonalnie telefonem 30–60 s z oznaczonym zdarzeniem i czasem próby. Bez wprowadzania capture ALSA podczas gry. Nie publikować prywatnych danych/głosu bez zgody.
- [ ] Przeprowadzić osobno: muzyka+efekty, muzyka off, efekty off; mowa jako odrębna obserwacja. Wyciszenie służy izolacji, nie jest docelową naprawą.
- [ ] Sprawdzić liczbę instancji gry/Wine i właścicieli PCM. Poszukać drugiego źródła tylko na podstawie procesów/uchwytów; nie zabijać wszystkich Wine globalnym `killall`.
- [ ] Jeden kontrolowany odsłuch głośnik kontra słuchawki, bez jednoczesnego wyjścia. Objaw tylko na jednym torze kieruje do kodeka/miksera/sprzętu; bez dowodu nie zmieniać globalnych ustawień miksera.

### 5.2. Zbudować prawdziwe długotrwałe probe

Istniejący [audio_native.py](<../sdcard/ports/projectdiablo2/scripts/audio_native.py>) jest diagnostyką PCM-open. Istniejący [audio_probe.c](<../tools/audio_probe.c>) odtwarza 1.5 s przez waveOut; DirectSound jest tylko tworzony i zwalniany. **Żaden z tych wyników nie zastępuje kilkuminutowego testu miksera DirectSound.** Rozszerzyć istniejące narzędzia, nie tworzyć drugiego systemu diagnostyki.

- [ ] Native ARMHF/time32: 120 s kontrolowanego sygnału z cichymi, rozpoznawalnymi impulsami/sekwencją, ciągłe zasilanie PCM, obsługa short write/EAGAIN/EPIPE, deadline, timeout i cleanup. Najpierw ta sama trasa co gra; AArch64/system ALSA tylko dodatkowa kontrola z wyraźnie inną biblioteką.
- [ ] Win32 waveOut: ciągły refill wielu buforów przez ten sam Wine/Box86 przez 120 s.
- [ ] Win32 DirectSound: rzeczywiste secondary buffer playback i cykliczny refill, pomiar play/write cursors; osobny test małej liczby i większej liczby jednoczesnych głosów, 3D/EAX off. Statyczna zapętlona sinusoida sama nie sprawdzi deadline producenta.
- [ ] W każdej warstwie najpierw idle, potem ograniczone, powtarzalne obciążenie CPU. Nie uruchamiać drugiego odtwarzacza na ekskluzywnym `hw` równolegle z grą. Kontrola temperatury, limit czasu i natychmiastowe przerwanie; bez root/real-time.
- [ ] Raportować odstępy sekwencji, powtórzenia, opóźnienie i błędy; zachować bezpieczną amplitudę. Artefakty ARM/Win32 odtwarzalne, z manifestem/hash i licencjami.

### 5.3. Drzewo decyzji

| Wynik | Następny eksperyment / poprawka |
|---|---|
| Native psuje audio bez obciążenia | Trasa/ABI/sterownik/kodek; sprawdzić time32/ENOTTY i hw/sw params, nie stroić DirectSound |
| Native poprawny, waveOut nie | Winealsa/Box86: endpoint, negocjacja, poll/timery, obsługa częściowych zapisów |
| waveOut poprawny, DirectSound refill nie | Mikser/cursors/timer DirectSound; przejrzeć dokładne źródła Wine i narzut głosów |
| Probe poprawne, dopiero gra źle | Ustawienia gry/EAX, liczba głosów, powtarzany bufor producenta, I/O i obciążenie renderowania |
| Przerwy udanych zapisów przekraczają realny zapas, XRUN rośnie | Zapas bufora oraz deadline/scheduling; zmieniać pojedynczy parametr |
| EAGAIN, brak postępu/retry lub busy-spin | Zweryfikować Winealsa poll/retry i zachowanie dmix; EAGAIN nie liczyć jako XRUN |
| Klient działa regularnie, a powtarzane fragmenty trafiają już do ALSA | DirectSound/gra; większy bufor ALSA tego nie usunie |
| Zacięcia skorelowane z faults/swap/I/O/długimi klatkami | Usunąć źródło stall; nie maskować dowolnie dużą latencją |

Jeśli pozostaje podejrzenie replay starego bufora: najpierw znaczniki kontrolowanej sekwencji w probe; dopiero potem opcjonalny, krótki opt-in tap PCM w RAM poza wątkiem audio, z limitem pamięci, bez automatycznej publikacji/zapisu materiału gry. Porównać powtórzenie przed ALSA z nagraniem wyjścia. Sam hash identycznej ciszy lub muzycznej pętli nie dowodzi błędu.

## 6. P2 — wdrożyć jedną poprawkę wskazaną pomiarami

### A. Potwierdzony problem negocjacji/bufora

- [ ] Najpierw poznać dozwolone RK817 format/rate/period/buffer. Przy stałych 48 kHz i formacie sprawdzić rzeczywiście uzyskane 80, następnie 160 ms; nie wymuszać wartości poza możliwościami sterownika. Osobno stroić threshold/avail_min, bez mieszania zmian.
- [ ] Dla raw `hw` sterowanie przez zweryfikowane API negocjacji klienta/Winealsa, nie nieobsługiwane pola `plug`. Dmix może ustawiać slave, ale wymaga dowodu hardware params.
- [ ] Jeśli potrzebny patch Wine: przypiąć źródła/toolchain, zmienić tylko negocjację lub wykazany błąd, przygotować osobny opt-in artefakt i rollback. Bez globalnej podmiany runtime.
- [ ] 44100 vs 48000 dopiero osobny test kosztu konwersji; aktualne logi pokazują 48000. Nie zakładać, że wpis rejestru wymusi rate urządzenia.

### B. Potwierdzony problem producenta/DirectSound/CPU

- [ ] Zweryfikować w dokładnym Wine 8.0 odczytywane klucze, jednostki i domyślne wartości. `HelBuflen` nie jest buforem ALSA; 8192 nie jest zwiększeniem względem 65536. Nie przypisywać `MaxHardwareChannels` udowodnionej redukcji miksowanych głosów/CPU bez kodu i pomiaru.
- [ ] Zmianę HelBuflen wykonać dopiero po izolacji DirectSound, z readback/backup/restore przez [audio_dsound.py](<../sdcard/ports/projectdiablo2/scripts/audio_dsound.py>). Zmienić jeden parametr, nie pakiet `ver2` jako kilka niewiadomych.
- [ ] Przy przeciążeniu: osobny eksperyment limitu renderowania lub niższej rozdzielczości, z potwierdzeniem rzeczywistego efektu na CPU/frame-time. GDI pozostaje; nie włączać headless/noop ani kilku optymalizacji Box86 jednocześnie.
- [ ] Priorytet/affinity wątku audio dopiero po danych o opóźnieniach schedulera; bez globalnego chrt/SCHED_FIFO, bez głodzenia Westona i input. Nie obiecywać poprawy przez sam governor.
- [ ] Przy I/O/RAM nie kopiować całej gry do RAM 1 GB, nie wyłączać swap, nie wykonywać okresowego drop_caches. Zmienić konkretną wykazaną przyczynę stall.

**Brama P2:** poprawka usuwa zaobserwowany mechanizm i daje słyszalną poprawę w tej samej scenie. Spadek EPIPE bez poprawy echa nie kończy zadania.

## 7. Testy lokalne i regresje wymagane przed przekazaniem

- [ ] Routing: baseline bez zmian; odrzucona składnia Buffer; konfiguracja nieotwarta przez grę; fallback endpointu; brak pliku; busy/denied; brak uprawnień do proc; różne client/hardware params; kolizja IPC.
- [ ] Shell: mock sudo czyści odziedziczone `PD2_*`; wariant/trasa/SDL/metrics dochodzą jawnie do procesu docelowego. Test błędnych wartości przed mutacją oraz cleanup po awarii.
- [ ] Observer: zamknięty probe nie spełnia sustained playback; utrata pojedynczej aktualizacji; równoległe strumienie; reuse slotu/adresu; >8 open/close; pełna kolejka; brak kolektora; fork/exec; write/mmap; częściowe zapisy; EAGAIN/retry; start/stop versus steady-state.
- [ ] Raport: fixture odpowiadające Buffer (481 wyników EPIPE i 908 recover, bez sumowania) i Dmix (0 EPIPE, recover, EAGAIN, partial coverage); różne okresy/okna czasowe, reset licznika i brak danych systemowych.
- [ ] Nowe pola zgodne w bibliotece, wire ABI, parserze i allowliście; test prywatności. Przebudować observer tylko jeśli zmieniony, zachować ARMHF/time32 i zaktualizować wszystkie piny/manifest/notices. Nie podmieniać stock legacy ALSA ani omijać hash.

Polecenia z katalogu repo w Linux/WSL; wyniki i pominięcia zapisać w raporcie:

```bash
python3 -m unittest discover -s tests -p 'test_audio_*.py'
python3 tests/test_shell.py
python3 tools/audio_metrics_tests.py
python3 -m unittest discover -s tests -p 'test_*.py'
bash -n 'sdcard/ports/Project Diablo 2.sh'
bash -n 'sdcard/ports/Project Diablo 2 - Audio Buffer.sh'
bash -n 'sdcard/ports/Project Diablo 2 - Audio Dmix.sh'
bash -n sdcard/ports/projectdiablo2/scripts/run-game.sh
bash -n sdcard/ports/projectdiablo2/scripts/weston-session.sh
git diff --check
```

Dodatkowo właściwy test builda C/ABI według [audio_metrics_build.py](<../tools/audio_metrics_build.py>) i testów narzędzia, jeśli zmieniono bibliotekę. Nie przedstawiać historycznego `695 OK` jako nowego przebiegu. Brak R36S nie blokuje napisania testów/artefaktów, ale blokuje potwierdzenie jakości.

## 8. Następny test użytkownika i warunki akceptacji

### Pierwsza dostawa — tylko po P0

1. Jeden osobny launcher diagnostyczny/menu, bez ręcznej edycji rejestru/ALSA przez użytkownika. Najpierw zweryfikowany baseline, potem jeden zweryfikowany wariant; nie pełna macierz wszystkich hipotez.
2. Instrukcja w [AUDIO-FIX-1.md](<../docs/AUDIO-FIX-1.md>): build ID, dokładnie co skopiować, oczekiwane statusy i gdzie zebrać log; baseline/rollback. Zachować dane gry, save i ustawienia.
3. Próba techniczna 2 min: potwierdzenie endpointu, obu poziomów PCM, pokrycia oraz metryk. Gdy konfiguracja nieskuteczna, przerwać dalsze porównania i zwrócić log.
4. Dopiero potem odsłuch: 30–60 s menu, 60 s miasta, 120 s tej samej walki; oznaczyć przejścia i momenty objawu. Zapisać muzyka/efekty/mowa, echo/przerwy/opóźnienie, wyjście audio oraz EAX off.
5. Zwycięski kandydat: trzy przeplatane próby na wariant, z kontrolą rozgrzania, i jedna sesja 15–20 min z przejściami lokacji. Próg regresji ustalić przed testem (np. ≤5% pogorszenia mediany FPS, z uwzględnieniem rozrzutu/frame-time).

Raport porównawczy: build, wariant żądany/efektywny, scena, długość i pokrycie, client/hardware buffer+period, delty błędów według API, max gap, CPU/FPS/RAM/swap/temperatura, zdarzenia słuchowe i opóźnienie. Pola niedostępne oznaczać wprost.

**Akceptacja:** brak słyszalnych powtórzeń/przerw w powtarzalnych scenach; brak nowych XRUN podczas ustalonego odtwarzania przy wiarygodnym pomiarze; akceptowalna latencja, brak regresji obrazu/sterowania i brak blokady audio po wyjściu/restartach. Jeśli odsłuch przeczy licznikom, zadanie nadal otwarte.

## 9. Dystrybucja, ograniczenia i przekazanie

- Wszystkie zmiany runtime bezpośrednio w [payloadzie SD](<../sdcard/ports/>). **Nie budować `dist/`, ZIP ani uruchamiać `build-update`.** Poprzednie polecenia planu dotyczące archiwów są wycofane.
- Dokumentacja użytkowa wyłącznie w [docs](<../docs/>); ten plan pozostaje tutaj na życzenie użytkownika. Zaktualizować [release-files.json](<../release-files.json>) i walidację tylko dla potrzebnych artefaktów, bez danych gry/logów prywatnych.
- [Główny launcher](<../sdcard/ports/Project Diablo 2.sh>) zachowuje stabilne domyślne zachowanie. Wspólna diagnostyka może być poprawiana warunkowo; eksperymenty tylko opt-in. Awans do produkcji dopiero po sprzętowej akceptacji.
- `BOX86_DYNAREC_SAFEFLAGS=1`, bez `CALLRET=1`. Wine/gra jako zwykły użytkownik. GDI i DRM Weston bez headless/noop. Bez globalnego miksera, globalnego ALSA config i cudzych zasobów IPC.
- Zastałe zmiany robocze zachować; nie resetować repo i nie cofać cudzej pracy.
- Po wynikach zaktualizować [MEMORY.md](<../MEMORY.md>) i skorygować niepotwierdzone twierdzenia audio w [AGENTS.md](<../AGENTS.md>); nie przepisywać hipotez jako faktów.

**Raport następnego agenta:** zmienione pliki/build ID, dokładne wyniki testów, zweryfikowana topologia, tabela pomiarów, hipotezy potwierdzone/odrzucone/otwarte, rollback i dokładnie jeden kolejny test dla użytkownika. Przy braku sprzętu jawnie wskazać, które bramy pozostają niespełnione.

# AGENTS.md — Project Diablo 2 Port na konsolę R36S

Niniejszy dokument stanowi kompendium wiedzy architektonicznej, technicznej i operacyjnej dla agentów AI oraz deweloperów pracujących nad portem gry **Project Diablo 2 (Diablo II: Lord of Destruction)** na konsolę retro **R36S**.

---

## 1. Specyfikacja sprzętowa urządzenia docelowego (R36S)

Konsola R36S to budżetowy handheld oparty na platformie Rockchip RK3326. Wszystkie decyzje inżynieryjne muszą uwzględniać następujące ograniczenia:

| Komponent | Specyfikacja | Wpływ na architekturę |
|---|---|---|
| **SoC** | Rockchip RK3326 | Układ 64-bitowy z 2018 roku |
| **CPU** | 4x ARM Cortex-A35 @ 1.30 GHz | Rdzenie energooszczędne ARMv8-A (in-order execution, brak predykcji spekulacyjnej o dużej głębokości, małe cache L1/L2). Każdy cykl CPU jest na wagę złota. |
| **GPU** | ARM Mali-G31 MP2 (Bifrost v1) | Obsługa OpenGL ES 2.0 / 3.0, Vulkan 1.0. **Brak sprzętowego desktopowego OpenGL (GLX)** w 32-bitowym userlandzie. |
| **RAM** | 1024 MB LPDDR3 (współdzielony) | Ekstremalnie ciasny budżet pamięci. Pomiędzy systemem, Westonem, Xwaylandem i Wine zostaje ok. 500–600 MB na grę. Swapowanie na wolną kartę microSD zabija płynność. |
| **Ekran** | 3.5" IPS LCD, 640×480 (4:3) | Interfejs MIPI DSI, bufor klatek sterowany przez `/dev/dri/card0` (Direct Rendering Manager). |
| **Audio** | Rockchip RK817 (I2S Codec) | Węzły ALSA: `/dev/snd/pcmC0D0p` oraz `/dev/snd/controlC0`. Wymaga zgodności z 64-bitowym sterownikiem jądra. |
| **Wejścia** | Gamepad zintegrowany (evdev) | 2 analogi, D-Pad, A/B/X/Y, L1/R1, L2/R2, Select, Start, L3, R3, Menu. Kody sprzętowe: Select `0x2C0`, Start `0x2C1`, L3 `0x2C2`, R3 `0x2C3`, Menu `0x2C4`. |
| **OS / Kernel** | ArkOS / Linux 4.4.189+ aarch64 | Jądro 64-bitowe, przestrzeń użytkownika hybrydowa (biblioteki systemowe AArch64 oraz multiarch ARMHF 32-bit). Środowisko uruchomieniowe PortMaster. |

---

## 2. Architektura oprogramowania (Stos uruchomieniowy)

Gra jest 32-bitową aplikacją Windows x86. Nie ma możliwości skompilowania jej natywnie na ARM (zamknięty kod źródłowy Blizzard / PD2). Cały stos opiera się na wydajnej emulacji w przestrzeni użytkownika Linux:

```
[ Gra: Game.exe -ddraw (Win32 x86) ]
          │
          ▼
[ DirectDraw Wrapper: cnc-ddraw (ddraw.dll x86) ]
          │
          ▼
[ Wine 8.0 x86 (WoW64 / Win32 API) ]
          │
          ▼
[ Box86 (JIT Dynarec x86 -> ARMHF 32-bit) ]
          │
    ┌─────┴─────────────────────────┐
    ▼                               ▼
[ Grafika ]                     [ Audio ]
Wine X11 Window                 winealsa.drv
    │                               │
Xwayland (DISPLAY=:0)           compat/alsa-legacy-armhf
    │                           (libasound.so.2 time32)
Weston (wp_weston kiosk)            │
(-B drm card0 --renderer=gl)    /dev/snd/pcmC0D0p (rk817)
    │
Mali-G31 GPU / KMS DRM
    │
[ Matryca LCD 640x480 ]
```

---

## 3. Podsystem graficzny i reguły wyświetlania

### A. Dlaczego profil GDI jest oficjalnym trybem produkcyjnym?
- W trybie **GDI** ([`Project Diablo 2.sh`](file:///C:/AI%20fast/R36S/github/sdcard/ports/Project%20Diablo%202.sh)):
  1. `weston-session.sh` startuje kompozytor z flagami:
     `-B drm --drm-device card0 --renderer=gl`
     oraz preinstalowaną biblioteką `crusty_gbm`.
  2. Kompozytor Weston przejmuje rolę **DRM Master** na `/dev/dri/card0` i używa 64-bitowego sterownika GPU Mali do wyświetlania obrazu na LCD.
  3. Gra i `cnc-ddraw` rysują klatkę programowo do bufora DIB (GDI), który przez X11/Xwayland trafia do Westona. Weston sprzętowo skaluje bufor do 640×480 i wyświetla na matrycy.
  4. **Ten tryb ZAWSZE gwarantuje stabilny obraz.**

### B. Krytyczny błąd: Czarny ekran przy profilu OpenGL
- **Co się działo:** Po wybraniu profilu `opengl` gra uruchamiała się, grało audio, ale ekran był czarny.
- **Przyczyna w kodzie:** W `weston-session.sh` profil `opengl` wymuszał:
  `weston_args=(-B headless --renderer=noop);preload=;backendlib=`
  Tryb `headless` z rendererem `noop` **nie otwiera wyjścia DRM i porzuca wszystkie ramki**.
- **Wniosek architektoniczny:** Na konsoli R36S kompozytor Weston **nigdy nie może działać w trybie headless/noop**, chyba że istnieje weryfikowalny natywny renderer KMS scanout. Ponieważ ArkOS nie posiada 32-bitowych sterowników GLX dla Mali, standardowy profil OpenGL z cnc-ddraw nie może wyświetlać obrazu bez aktywnego kompozytora DRM.

### C. Zaawansowany wariant GPU (GLES2)
- W folderze `compat/gles2-renderer/` znajduje się eksperymentalny build `ddraw.dll` zoptymalizowany pod kątem shaderów GLES2 / GLSL 1.10 (uruchamiany przez [`Project Diablo 2 - GPU.sh`](file:///C:/AI%20fast/R36S/github/sdcard/ports/Project%20Diablo%202%20-%20GPU.sh)).
- Przenosi on konwersję palety kolorów 8-bit na GPU, odciążając CPU z ręcznego przeliczania barw dla każdej klatki.

---

## 4. Podsystem dźwięku (ALSA / DirectSound)

### A. Problem jądra 64-bit vs biblioteka 32-bit (Błąd ENOTTY)
- Sterownik audio jądra RK3326 oczekuje 32-bitowego `time_t` w strukturze `snd_pcm_sync_ptr` dla 32-bitowych procesów (`ioctl 0xC0844123`).
- Nowoczesne dystrybucyjne wersje `libasound.so.2` kompilowane są z 64-bitowym `time_t` (time64, `ioctl 0xC0884123`), co jądro odrzucało błędem `-25 ENOTTY`.
- **Rozwiązanie:** W `compat/alsa-legacy-armhf/libasound.so.2` dostarczana jest wersja `alsa-lib 1.2.8` skompilowana bez flag time64, preładowana w locie do RAM (`$PD2_WORK/.alsa-legacy-armhf`).

### B. Problem zacinania dźwięku (Audio Stutter / Underruns) i jego rozwiązanie
- Workaround kierował wyjście ALSA bezpośrednio do surowego urządzenia sprzętowego:
  `slave.pcm "hw:CARD=rk817...,DEV=0"`
- Surowe `hw:` ma mały bufor sprzętowy (~20 ms). Podczas obciążenia emulacji Box86 bufor opróżniał się, powodując trzaski i rwanie dźwięku.
- **Kluczowe poprawki wdrożone w `run-game.sh`:**
  1. `export SDL_AUDIODRIVER=dummy` — uniemożliwia bibliotekom SDL2 blokowanie węzła ALSA przed Wine.
  2. Strojenie rejestru Wine DirectSound:
     - `HelBuflen = 8192` (bufor emulacji DirectSound powiększony do ~90 ms zapasu).
     - `MaxHardwareChannels = 16` (ograniczenie liczby miksowanych kanałów z 32/64 do 16, oszczędzające do 40% mocy CPU).
     - `DefaultSampleRate = 44100` (dopasowanie częstotliwości próbkowania, brak programowego resamplingu w locie).
  3. W samej grze opcja **Environmental Effects (EAX 3D)** musi pozostać **WYŁĄCZONA**.

---

## 5. Optymalizacja wydajności CPU (Box86 Dynarec)

Procesor Cortex-A35 jest wąskim gardłem. Aby uzyskać płynną rozgrywkę w Diablo II (zamiast początkowych 10–15 FPS), launcher produkcyjny ustawia:

```bash
export BOX86_DYNAREC=1
export BOX86_DYNAREC_BIGBLOCK=2     # Duże bloki podstawowe translacji JIT
export BOX86_DYNAREC_FORWARD=256    # Głębokie skanowanie skoków w przód
export BOX86_DYNAREC_FASTROUND=1    # Sprzętowe instrukcje zaokrąglania ARM
export BOX86_DYNAREC_FASTNAN=1      # Szybka obsługa IEEE NaN
export BOX86_DYNAREC_SAFEFLAGS=1    # Bezpieczne flagi procesora (nie wyłączać dla Diablo!)
export BOX86_DYNAREC_STRONGMEM=0    # Luźny model pamięci (brak niepotrzebnych barier)
export BOX86_DYNAREC_X87DOUBLE=0    # Użycie sprzętowego NEON zamiast emulacji 80-bit x87
```

Dodatkowo przed uruchomieniem gry obniżany jest współczynnik swapowania:
```bash
sysctl -w vm.swappiness=10
sync; echo 3 > /proc/sys/vm/drop_caches
```
Zapobiega to dławieniu systemu przez zrzucanie stron pamięci RAM na kartę microSD.

---

## 6. Struktura plików w repozytorium

```
github/
├── AGENTS.md                  # Niniejszy dokument
├── MEMORY.md                  # Chronologiczna historia debugowania i testów
├── README.md                  # Główny opis projektu
├── runtime-manifest.json      # Przypięte hashe i rozmiary pobieranych runtime'ów
├── runtime-lock.json          # Integralność plików binarnych
├── release-files.json         # Wykaz plików dystrybucyjnych
├── sdcard/
│   └── ports/
│       ├── Project Diablo 2.sh              # GŁÓWNY LAUNCHER PRODUKCYJNY (GDI + Dynarec)
│       ├── Project Diablo 2 - Performance GDI.sh
│       ├── Project Diablo 2 - GPU.sh        # Alternatywny launcher GLES2 shader
│       ├── Project Diablo 2 - Performance OpenGL.sh
│       └── projectdiablo2/
│           ├── port.json                    # Metadane PortMaster
│           ├── gameinfo.xml                 # Opis i grafika EmulationStation
│           ├── scripts/                     # Skrypty orkiestracji (Bash, Python)
│           │   ├── run-game.sh              # Przygotowanie Wine, rejestru i start gry
│           │   ├── weston-session.sh        # Kompozytor Wayland/Weston
│           │   ├── layout.py                # Walidacja ścieżek, prefiksu i INI
│           │   ├── audio_config.py          # Konfiguracja routingu ALSA
│           │   └── ...
│           ├── compat/                      # Binaria i biblioteki pomocnicze
│           │   ├── alsa-legacy-armhf/       # libasound.so.2 (time32)
│           │   ├── box86-a35/               # Box86 zoptymalizowany pod Cortex-A35
│           │   ├── cnc-ddraw/               # ddraw.dll z usuniętym glGetTexImage
│           │   ├── gles2-renderer/          # ddraw.dll z paletą na GPU
│           │   └── ...
│           └── defaults/                    # Pliki konfiguracyjne gry i padów
├── tools/                                   # Narzędzia kompilacji i pakowania
│   ├── prepare.py                           # Budowanie paczek aktualizacji
│   ├── build_cnc_ddraw_ogl.py               # Kompilacja ddraw.dll (MSVC)
│   ├── build_box86_a35.py                   # Kompilacja Box86 A35
│   └── ...
└── tests/                                   # Zestaw 53 testów regresji i logiki
```

---

## 7. Instrukcje operacyjne dla deweloperów i agentów

### Uruchomienie testów lokalnych:
```bash
# Testy konfiguracji i ścieżek:
python tests/test_layout.py

# Testy launchera i menu:
python tests/test_opengl_entry_fix.py

# Testy profilu GPU:
python tests/test_gpu_runtime.py
```

### Zbudowanie paczki aktualizacyjnej:
```bash
python tools/prepare.py build-update
```
Wynikowy plik ZIP tworzony jest w katalogu `dist/projectdiablo2-port-update.zip`.

### Zasady nienaruszalności kodu:
1. **Nie zmieniaj `SAFEFLAGS=1` na `0` ani nie włączaj `CALLRET=1` w Box86** — Diablo II zawiera samomodyfikujący się kod (JIT wewnątrz silnika gry); agresywne flagi Box86 powodują natychmiastowe crashe podczas rzucania czarów.
2. **Nigdy nie instaluj Wine jako root** i nie uruchamiaj gier z uprawnieniami roota — Westonpack wymaga separacji przestrzeni nazw użytkownika (`runuser`).
3. **Plik `Project Diablo 2.sh` musi zawsze pozostać sprawdzoną wersją produkcyjną.** Eksperymenty należy wdrażać wyłącznie w osobnych plikach launcherów.

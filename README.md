# Project Diablo 2 — R36S Port (ArkOS / PortMaster)

Prywatny, zoptymalizowany port gry **Project Diablo 2 (Diablo II: Lord of Destruction)** przygotowany dla konsoli przenośnej **R36S** (SoC Rockchip RK3326, 4x Cortex-A35, 1 GB RAM, ArkOS).

Projekt łączy środowisko **PortMaster**, kompozytor **Westonpack Wayland/X11**, translator instrukcji **Box86 JIT Dynarec**, warstwę **Wine 8.0 x86** oraz zmodyfikowany wrapper DirectDraw **cnc-ddraw**.

---

## 🚀 Główne cechy wydania produkcyjnego

- **Stabilny obraz na ekranie LCD 640×480:** Kompozytor Weston zoptymalizowany pod kątem DRM/KMS z akceleracją Mali-G31 GPU i bezpiecznym renderowaniem GDI / DirectDraw.
- **Czysty dźwięk bez zacinania:** Dedykowana biblioteka ALSA time32 (`compat/alsa-legacy-armhf/libasound.so.2`) eliminująca błąd `ENOTTY` na 64-bitowym jądrze oraz powiększony bufor DirectSound (`HelBuflen=8192`, limit kanałów do 16) eliminujący underruny ALSA.
- **Optymalizacja wydajności CPU (Box86 Cortex-A35):** Włączone zaawansowane flagi kompilacji JIT (`BIGBLOCK=2`, `FORWARD=256`, `FASTROUND=1`, `FASTNAN=1`, `X87DOUBLE=0`).
- **Ochrona pamięci RAM:** Obniżony współczynnik swapowania (`vm.swappiness=10`) i zwalnianie buforów systemowych zapobiegające zrzucaniu pamięci gry na wolną kartę microSD.
- **Pełne sterowanie kontrolerem:** Zintegrowany translator wirtualnego kontrolera Xbox 360 z obsługą wszystkich 17 przycisków i analogów R36S (w tym L3, R3, Select, Start i FN/Menu).
- **Klimatyczne menu startowe:** Stylizowane menu w klimacie Diablo II z wyborem rozdzielczości (domyślnie 800×600 skalowane sprzętowo do 640×480) i licznika FPS.
- **Eksperymentalny profil GPU (GLES2):** Osobny launcher [`Project Diablo 2 - GPU.sh`](file:///C:/AI%20fast/R36S/github/sdcard/ports/Project%20Diablo%202%20-%20GPU.sh) z dedykowanym shaderem palety 8-bit na GPU Mali.

---

## 📂 Struktura repozytorium

- **[`AGENTS.md`](file:///C:/AI%20fast/R36S/github/AGENTS.md):** Kompendium wiedzy technicznej dla agentów AI i deweloperów (specyfikacja SoC RK3326, architektura stosu, zasady nienaruszalności kodu).
- **[`MEMORY.md`](file:///C:/AI%20fast/R36S/github/MEMORY.md):** Pełna chronologiczna pamięć procesu badawczego i rozwiązywania problemów (brak dźwięku, czarny ekran, underruny audio, optymalizacja FPS).
- **[`sdcard/ports/`](file:///C:/AI%20fast/R36S/github/sdcard/ports/):** Pliki przeznaczone do skopiowania na kartę SD konsoli:
  - `Project Diablo 2.sh` — **Oficjalny launcher produkcyjny** (przetestowany na konsoli).
  - `Project Diablo 2 - GPU.sh` — Alternatywny wariant ze sprzętowym shaderem GLES2.
  - `Project Diablo 2 - Performance GDI.sh` — Bezpośredni start GDI z pominięciem menu.
  - `projectdiablo2/` — Całe środowisko skryptowe, biblioteki kompatybilności i konfiguracje.
- **[`tools/`](file:///C:/AI%20fast/R36S/github/tools/):** Skrypty budowania, kompilatory bibliotek (MSVC/GCC), narzędzia diagnostyczne i generator paczek aktualizacyjnych (`prepare.py`).
- **[`tests/`](file:///C:/AI%20fast/R36S/github/tests/):** Oczyszczony zestaw 53 testów jednostkowych i integracyjnych (bez zbędnych plików tymczasowych).

---

## 🛠️ Instalacja na konsoli R36S

### Wymagane pliki gry:
Port wymaga oryginalnych plików gry **Diablo II: Lord of Destruction** (wersja 1.13c lub 1.14) z zainstalowanym modem **Project Diablo 2**.

### Krok po kroku:
1. Skopiuj zawartość folderu `sdcard/ports/` do katalogu `ports/` na karcie SD konsoli (partycja `EASYROMS` lub druga karta SD):
   ```
   roms/ports/
   ├── Project Diablo 2.sh
   ├── Project Diablo 2 - GPU.sh
   ├── Project Diablo 2 - Performance GDI.sh
   └── projectdiablo2/
   ```
2. Umieść pliki gry Diablo II oraz folder `ProjectD2` w katalogu:
   ```
   ports/projectdiablo2/gamedata/Diablo II/
   ```
   *(upewnij się, że w środku znajdują się `Game.exe`, pliki `.mpq` oraz podfolder `ProjectD2`).*
3. Włóż kartę do konsoli R36S, uruchom konsolę i wejdź do menu **Ports** w EmulationStation.
4. Wybierz **Project Diablo 2**.

---

## 🎮 Sterowanie (R36S Gamepad)

| Przycisk R36S | Działanie w Diablo II / PD2 |
|---|---|
| **Lewy Analog** | Ruch kursorem myszy / postać |
| **Prawy Analog** | Swobodne przesuwanie kursora |
| **A** | Lewy przycisk myszy (atak podstawowy / podnoszenie przedmiotu) |
| **X** | Prawy przycisk myszy (czar / atak dodatkowy) |
| **B** | Zamknięcie okien / Anuluj / ESC |
| **Y** | Bieg / Chód (Toggle Run) |
| **D-Pad Lewo / Prawo** | Przełączanie pasów mikstur (1, 2, 3, 4) |
| **D-Pad Góra / Dół** | Ekwipunek (I) / Karta postaci (C) |
| **L1 / R1** | Przypisane czary funkcyjne (F1, F2...) / Przełączanie kart |
| **L2 / R2** | Pokazywanie przedmiotów na ziemi (ALT) / Mapa (TAB) |
| **Start** | Menu główne gry (ESC) / Zatwierdzenie |
| **Select** | Przełączanie minimapy / Dodatkowe menu |
| **L3 / R3** | Szybkie leczenie / Pomocnik FPS |
| **FN / Menu** | Klawisz specjalny portu |

---

## 💡 Porady wydajnościowe w samej grze

1. **Efekty dźwiękowe 3D (Environmental Effects):**
   - W menu gry wejdź w: **Options -> Sound Options**.
   - Upewnij się, że opcja **Environmental Effects jest ODZNACZONA (wyłączona)**. Emulacja efektów EAX 3D na procesorach ARM powoduje gwałtowny spadek płynności.
2. **Rozdzielczość:**
   - Domyślna rozdzielczość 800×600 zapewnia najlepszy kompromis pomiędzy czytelnością interfejsu Project Diablo 2 a wydajnością sprzętowego skalera Mali na ekranie 640×480.

---

## 📜 Licencje i podziękowania

Projekt korzysta z komponentów Open Source:
- **Westonpack** (Wayland / Xwayland) — MIT License
- **Box86** autorstwa Sébastien Chevalier (ptitSeb) — MIT License
- **Wine** — LGPL v2.1+
- **cnc-ddraw** autorstwa FunkyFr3sh — GNU General Public License v3.0
- **ALSA Library (alsa-lib)** — LGPL v2.1

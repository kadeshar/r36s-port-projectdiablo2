# GPU Runtime 1 — R36S / dArkOSen

To nowy wariant renderera, nie następna macierz ustawień. Nie jest jeszcze potwierdzony na R36S i nie gwarantuje 20 FPS.

## Instalacja i uruchomienie

1. Wypakuj zawartość aktualizacji do istniejącego `ports`, nadpisując pliki portu. Nie usuwaj prefixu, konfiguracji, gry ani zapisów.
2. Zrób kopię zapisów; pierwszą sesję wybierz na nieważnej postaci. Nieodwracalny błąd GPU kończy proces gry jak awaria, więc niezapisany postęp może przepaść. Uruchom **Project Diablo 2 - GPU**. Nie uruchamiaj ponownie A–F. Pierwszy start nadal wykonuje bezpieczne przygotowanie Wine; może potrwać kilka minut.
3. Zagraj normalnie w znanym miejscu z dźwiękiem, także chwilę podczas walki. Wyjdź normalnie do Ports i uruchom GPU ponownie bez resetowania konsoli.
4. Jeśli GPU nie wystartuje, wróć do dotychczasowego głównego launchera / Performance GDI. Nie kasuj prefixu. Błąd GPU nie przełącza już gry po cichu na niewidoczne GDI.

Nie ma HUD FPS. Pomiary zapisują się automatycznie w bezpiecznym logu; licznik prezentacji nie jest licznikiem symulacji ani gwarancją fizycznego wyświetlenia klatki.

## Co zmieniono

- Oddzielna biblioteka cnc-ddraw z backendem GL2/GLSL 1.10 przez GL4ES → GLES2/KMS. Bez GL3/core, multipass, ignorowania błędów i cichego fallbacku.
- Dla obrazu 8-bit indeksy i paleta są przetwarzane na GPU. Aktualizacja samej palety nie wymaga konwersji pełnej powierzchni na CPU. Obsługiwane są także RGB565, RGB555 i BGRA32.
- Krótka syntetyczna walidacja shaderów/tekstur przy inicjalizacji. Bez odczytów obrazu gry i bez wymuszonych 30 odrysowań niezmienionej powierzchni.
- Dźwięk pozostaje ALSA time32/rk817. Prywatna biblioteka z tego samego źródła dodaje ograniczone liczniki rzeczywistych operacji PCM, bez nagrywania dźwięku i bez globalnych zmian ALSA/buforów/priorytetów.
- CPU gry jest zakresem zweryfikowanych procesów Wine, również po zmianie rodzica. `verified_subset` nie oznacza kompletnego pomiaru; `partial/unavailable` nie oznacza zerowego obciążenia.

## Box86 A35 jest niezależny

GPU domyślnie pozostawia dotychczasowy Box86, aby nie mieszać wpływu emulatora i renderera. Opcjonalny build z tego samego commita, dostrojony do Cortex-A35 bez założenia CRC/crypto, wybiera się dla pojedynczej sesji:

```bash
PD2_BOX_VARIANT=a35 bash "Project Diablo 2 - GPU.sh"
```

Można też wybrać A35 z istniejącym launcherem GDI. Nie ma dodatkowego launchera testowego. Wartości `stock|a35` i `stock|gles2` są zamkniętą listą, nie ścieżkami do bibliotek. Nie zmieniono Wine ani systemowych sterowników. A35 nie jest obietnicą wzrostu FPS; ma znane ograniczenie upstream konwersji time64, opisane w [README wariantu A35](<compat/box86-a35/README.md>). Jest przeznaczony wyłącznie dla przypiętego runtime'u Wine.

## Eksport

W katalogu portu:

```bash
python3 scripts/safe_log.py export --dir logs --manifest runtime-manifest.json
```

Skopiuj `logs/diagnostic-export.zip` na PC przed kolejnym eksportem. Zachowywanych jest 10 sesji. Wystarczy log ze zwykłego uruchomienia GPU i informacja: czy był obraz, płynność w znanej scenie, czy dźwięk rwał i czy drugi start zadziałał.

## Jak czytać wynik

`renderer_gl2` pokazuje rzeczywiste etapy, bpp, rozmiar powierzchni silnika i rozmiar wyjścia. `render_status:first_present` z `backend:opengl` oznacza udane API SwapBuffers, nie dowód widoczności na LCD. Zmiana wymiarów okna nie obniża automatycznie rozdzielczości gry. Używana jest dotychczasowa wybrana rozdzielczość; porównania wymagają tej samej sceny i ustawień.

`audio_pcm` to liczniki publicznych wywołań ALSA w procesach finalnego uruchomienia Wine. Parametry dotyczą klienta PCM, niekoniecznie sprzętu za `plug`. `recover_epipe_calls` nie jest liczbą unikalnych przerw dźwięku. Brak strumienia (`no_stream`) oznacza brak obserwacji, nie poprawne audio. Nie dodano sztucznego opóźnienia, aby maskować rwanie.

W poprzednich logach profil OpenGL wracał do GDI. Nowa paczka naprawia tę konkretną ścieżkę, ale dopiero konsola potwierdzi zgodność sterownika i rzeczywistą wydajność.

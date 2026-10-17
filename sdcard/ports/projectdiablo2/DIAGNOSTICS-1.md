# Diagnostics-1 — PD2 / R36S

To jest **paczka pomiarowa, nie obietnica wzrostu FPS ani naprawy OpenGL**. Dotychczasowe Forward512/FastFlags nie poprawiły 10–15 FPS, KMS/Auto pozostały czarne, CALLRET nie doszedł do gry. Nie dokładamy kolejnego zestawu losowych flag ani nowego runtime.

## Instalacja

Wypakuj `projectdiablo2-diagnostics-2.zip` (lub `projectdiablo2-diagnostics-1.zip`) **do istniejącego katalogu ports**, z nadpisaniem plików portu. ZIP zawiera pliki startowe obok katalogu `projectdiablo2`, bez dodatkowego poziomu `sdcard`. Zachowaj grę, klucz, config, prefix i zapisy; nie importuj gry ponownie. Zalecany backup zapisów i nieważna postać testowa. Stare paczki pozostają dostępne do wycofania aktualizacji.

W paczce Diagnostics-2:
- **Odblokowanie OpenGL (cnc-ddraw)**: usunięto destrukcyjne autotesty `glGetTexImage` w `render_ogl.c`, które w GL4ES na Mali powodowały cichy natychmiastowy powrót do programowego GDI.
- **Ograniczenie swapowania**: adapter sesji tymczasowo obniża `vm.swappiness=10` i przywraca go przy wyjściu, redukując opóźnienia spowodowane zrzucaniem pamięci gry na wolną kartę microSD.

## Co uruchomić

Wpisy A/B/F uruchamiają grę bez menu portu, w 800×600, BIGBLOCK=1, bez nakładki FPS. Testy C/D/E wyświetlają tylko syntetyczne kolory — nie uruchamiają silnika PD2.

| Wpis w Ports, po prefiksie „Project Diablo 2 -” | Cel |
|---|---|
| Diag A GDI Stock | Oryginalny cnc-ddraw bez HUD, punkt odniesienia odczuwalnej płynności. |
| Diag B GDI Measure | Ten sam GDI, osobny lekki renderer: liczenie prezentacji w logu, bez HUD i kopiowania powierzchni. |
| Diag C SDL RGB | Natywne ARM32 SDL/GLES2 na rzeczywistych bibliotekach, bez GL4ES/Crusty i bez Wine. |
| Diag D GLX RGB | Natywne ARM32 GLX przez GL4ES/Crusty, nadal bez Wine. |
| Diag E Wine RGB | Syntetyczny Windows DirectDraw przez Wine i cnc-ddraw/OpenGL. |
| Diag F OpenGL Measure | Dopiero jeśli C/D/E pokazują kolory: gra OpenGL + lekki licznik. |

C/D/E powinny pokazać kolejno **czerwony, zielony, niebieski**, po około 2 s, a potem wrócić do Ports. Sam proces graficzny ma deadline 15 s + maks. 2 s na wymuszone zakończenie; start całej sesji i przygotowanie prefixu mogą trwać dłużej. Przy C/D nie startuje Wine ani mapper. E korzysta z istniejącego prefixu i odzyskiwania audio/Winebus; nie jest testem świeżego prefixu.

### Pierwsza runda

1. Uruchom **B**, wybierz tę samą nieważną postać i lokację. 30 s rozgrzewki, 60 s postoju i 60 s podobnej walki, liczba graczy 1. Wyjdź przez menu gry. Na ekranie **nie będzie licznika** — wynik trafia do logu.
2. Powtórz z **A**, oceniaj płynność i reakcję sterowania. A celowo nie daje nowego licznika FPS; nie porównuj jego braku próbek z zerowym FPS. Dla sprawdzenia kosztu starego HUD można dodatkowo powtórzyć istniejący **Test 1 GDI Baseline**, bez zmiany sceny i po rozgrzewce.
3. Uruchom **C**, **D**, **E**. Zapisz osobno, które kolory faktycznie widziałeś, a które testy były czarne/nie wróciły automatycznie. Jeśli C jest czarny, zgłoś wynik przed długimi próbami F.
4. Jeśli C/D/E pokazują RGB, uruchom **F**. Jeśli gra pozostaje czarna, odczekaj około 35 s na wpis diagnostyczny, a następnie wyjdź zwykłym dostępnym sposobem; sam brak prezentacji **nie zabija gry** i nie zapisuje postaci za Ciebie.
5. Sprawdź **pięć kolejnych startów B bez restartu konsoli**, w tym bezpośredni start po próbach grafiki. Zaznacz wynik każdego startu, obraz, dźwięk, sterowanie i normalny powrót do Ports. To test odzyskiwania, nie benchmark. Nie kasuj prefixu pomiędzy próbami.

Na razie nie uruchamiaj ponownie ryzykownych CALLRET/FastFlags na wartościowych zapisach. Najpierw chcemy ustalić wąskie gardło i najwcześniejszą niesprawną warstwę grafiki.

## Co wysłać

Wyślij bezpieczny eksport logów plus krótką listę: A/B odczuwalna płynność, C/D/E widoczne kolory lub czerń, F obraz/dźwięk, pięć startów B: OK/błąd. Nie wysyłaj gry, klucza, prefixu ani zapisów.

Eksport z katalogu portu:

```sh
python3 scripts/safe_log.py export --dir logs --manifest runtime-manifest.json
```

Powstaje `logs/diagnostic-export.zip`. Zachowywanych jest maksymalnie 10 sesji — po pierwszej rundzie wyeksportuj logi **przed** kolejnymi powtórkami; skopiuj eksport na komputer przed następnym eksportem. Opisz kolejność prób, ponieważ log zawiera tylko zamknięte statusy trybów, nie nazwy postaci/scen.

## Jak odczytujemy wyniki

- `setup_stage`: nazwany etap przygotowania; `status=failed` lokalizuje awarię. Setup, odzyskiwanie rejestru i zamknięcie Wine używają zachowawczych flag: BIGBLOCK=1, SAFEFLAGS=1, CALLRET=0. FORWARD512/CALLRET/FastFlags obejmują dopiero proces gry, nie przygotowanie prefixu.
- `render_status=window_ready`: backend wszedł do renderera z prawidłowym uchwytem okna (OpenGL po aktywacji kontekstu). **Nie dowodzi widocznego okna.**
- `render_status=first_present`: pierwsze poprawne wywołanie API prezentacji; nadal nie dowodzi fizycznego obrazu na matrycy.
- `render_sample`: liczba udanych prezentacji oraz rzeczywisty okres QPC. FPS próbki = `1000 * frames / duration_ms`. To nie licznik logiki gry ani odświeżania matrycy. Nie wyliczamy z tego percentyli pojedynczych czasów klatek.
- `no_presentation`: po 30 s nie odebrano pierwszej udanej prezentacji. Gra nie jest automatycznie przerywana. `capture_limit` oznacza koniec ograniczonej rejestracji, nie awarię gry. Dane renderera mają limit 256 KiB na proces, bez kopiowania pikseli i bez wymuszania odświeżeń; koszt pomiaru na konsoli nadal wymaga A/B.
- `graphics_layer`: start → biblioteka → kontekst → frame1/2/3 → done albo error. `frame` oznacza, że wywołanie prezentacji/wypełnienia wróciło; przy SDL/GLX API swap nie zwraca potwierdzenia widoczności. `renderer=gpu` to wyłącznie klasyfikacja ciągu GL, **nie dowód sprzętowej akceleracji**. Do rozstrzygnięcia potrzebujemy Twojej obserwacji RGB.
- Metryki co 5 s: system CPU, RAM/swap, swap-in/out, major faults, PSI gdy kernel udostępnia; także CPU/RSS/swap/faults zatwierdzonych poddrzew procesów. `game_*` obejmuje uruchomiony proces Wine/gry i dowiedzionych potomków; `mapper_*` mapper; `compositor_*` łącznie Weston i jego potomków, w tym Xwayland, jeżeli zachowana jest relacja rodzic–potomek. **Xwayland nie jest osobno rozbity**, odłączone/reparentowane procesy Wine nie są dopisywane na podstawie nazw. Puste pole oznacza niedostępne/niepewne, nie zero. Sampler kończy się po wyjściu lub ponownym użyciu PID kotwicy.
- `*_cpu_pct_x100`: 10000 = 100% jednego rdzenia dla procesu/poddrzewa; wynik procesu może przekroczyć 10000. System CPU ma skalę 0..10000 dla całego CPU. Systemowe liczniki fault/swap/PSI total są narastające — porównujemy ich przyrosty. Sumy procesowe obejmują tylko aktualne poddrzewo, więc mogą zmaleć po wyjściu procesu; procent CPU jest wtedy pomijany do ustabilizowania składu. Częstotliwość CPU/GPU nie jest miarą obciążenia; nie deklarujemy GPU utilization, którego firmware może nie udostępniać.

## Granice i następny krok

Sprawdzone na hoście: budowa x86/MSVC i ARMHF, integralność bibliotek, schematy i limity, selektor tylko w ulotnym katalogu, izolacja trybów na atrapach oraz testy odzyskiwania. **Nie przetestowano fizycznie R36S, sterownika Mali, RGB ani pięciu kolejnych realnych startów.**

Nie podmieniono Wine/Box86, systemowych sterowników, governora ani taktowania. Standardowy launcher domyślnie nie włącza nowej instrumentacji; lepsze etapy i ostrożniejsze przygotowanie prefixu dotyczą też zwykłych startów. Po danych z konsoli: ten sam commit Box86 z celem Cortex-A35 obok istniejącego runtime; dopiero osobno nowszy Box86. WoW64/Box64 lub świeży prefix pozostają kolejnymi, warunkowymi eksperymentami, nie częścią tej paczki.

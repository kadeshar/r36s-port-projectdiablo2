# Natywne 640×480 w launcherze R36S — plan wdrożenia

## 1. Cel i status

Dodać wybór **640×480 — natywna rozdzielczość ekranu**, z rzeczywistym renderowaniem gry w 640×480, bez zmniejszania klatki 800×600. Zachować dotychczasowe tryby i bezpieczny powrót do 800×600.

**Status: Wdrożono etapy A, B, C, D.**
- Etap A: Zweryfikowano autentyczną bibliotekę gry SGD2 (`177242c2...`), potwierdzono disassembly 4 offsetów immediates, wyliczono docelowy SHA-256 (`b582f3018b75ff1010ce811924f146d7bd8b67b5693c2f338f782695b1b14cec`) dla minimalnego 8-bajtowego diffu.
- Etap B: Wdrożono w `layout.py` (`SGD2_640_SHA256`, `SGD2_640_PATCHES`, `GAME_RESOLUTIONS`, `sgd2_640_bytes`, `sgd2_640_file`, obsługa w `prepare()`).
- Etap C: Zaktualizowano `start_menu.py`, `menu_x11.py`, `weston-session.sh`, `run-game.sh`, `safe_log.py`.
- Etap D: Rozszerzono testy automatyczne (`test_resolution_patch.py`, `test_start_menu.py`, `test_menu_x11.py`, `test_audio_result.py`, `test_shell.py`); cała suita 713 testów przechodzi pomyślnie (0 błędów).
- Etap E: Do wykonania na fizycznej konsoli R36S z wgranym payloadem `sdcard/ports/`.

### Definicja sukcesu

- Menu launchera pozwala świadomie wybrać 640×480.
- Gra tworzy powierzchnię renderowania 640×480, także po wejściu do rozgrywki i otwarciu paneli.
- Obraz dociera do ekranu 640×480 w relacji 1:1: bez przycinania, letterboxingu i pośredniego renderowania 800×600.
- Wszystkie istotne panele PD2 i pola interakcji mieszczą się na ekranie.
- Wyjście i ponowne uruchomienie w 800×600 przywracają dotychczasowe działanie.
- Nie zmienia się domyślnego 800×600 w ramach pierwszego wdrożenia. Użytkownik prosi o możliwość wyboru, nie automatyczną migrację.

## 2. Zweryfikowany stan obecny

| Warstwa | Ustalenie | Dowód |
|---|---|---|
| Wybór gry | Dopuszczalne `800x600`, `1024x768`, `native`; brak 640×480. Domyślnie 800×600. | [layout.py](<../sdcard/ports/projectdiablo2/scripts/layout.py#L42>), [ustalanie wyboru](<../sdcard/ports/projectdiablo2/scripts/layout.py#L607-L620>) |
| Znaczenie `native` | Oryginalna biblioteka PD2, dla przypiętej wersji 1068×600. **Nie** natywna rozdzielczość LCD. | [start_menu.py](<../sdcard/ports/projectdiablo2/scripts/start_menu.py#L15-L16>), [historia analizy](<../docs/PORT-README.md#L270-L278>) |
| Ograniczenie PD2 | Przypięty build SGD2 wymusza 1068×600 w wektorze rozdzielczości i parserze. Port stosuje prywatne pochodne DLL dla 800×600 oraz 1024×768. | [stałe i poprawki](<../sdcard/ports/projectdiablo2/scripts/layout.py#L23-L41>) |
| Wyjście | Rozmiar wyjściowy już wynosi 640×480; `inject_resolution` jest odrębnym ustawieniem. | [DISPLAY_KEYS](<../sdcard/ports/projectdiablo2/scripts/layout.py#L43-L49>) |
| Skalowanie | Historia portu opisuje 800×600 → cnc-ddraw → 640×480. Nie należy przypisywać całego kosztu wyłącznie Westonowi. | [opis toru obrazu](<../docs/PORT-README.md#L270-L276>) |
| Menu | Cztery warianty rozdzielczości, w tym `default`; cztery wiersze interfejsu. Renderer ma również sztywną walidację czterech wariantów. | [model menu](<../sdcard/ports/projectdiablo2/scripts/start_menu.py#L15-L60>), [renderer](<../sdcard/ports/projectdiablo2/scripts/menu_x11.py#L347-L398>) |
| Protokół | Menu zwraca dwa tokeny `resolution fps`; shell stosuje zamkniętą listę kombinacji. | [weston-session.sh](<../sdcard/ports/projectdiablo2/scripts/weston-session.sh#L257-L284>) |
| Konfiguracja SGD2 | Szablon ma menu 1024×768, listę 1024×768/800×600 i `Use 800 Interface Bar? = true`. | [SGD2FreeResolution.json](<../sdcard/ports/projectdiablo2/defaults/SGD2FreeResolution.json>) |
| Bezpieczeństwo poprawek | Sprawdzane są rozmiar, SHA-256 oryginału, stare bajty oraz SHA-256 wyniku; oryginał pozostaje nienaruszony. | [walidacja i cache](<../sdcard/ports/projectdiablo2/scripts/layout.py#L124-L189>) |
| Regresje | Istnieją testy traktujące `640x480` jako nieprawidłowe ustawienie. | [test_resolution_patch.py](<../tests/test_resolution_patch.py#L217-L223>), [override](<../tests/test_resolution_patch.py#L434-L439>) |

Ważne rozróżnienie: ekran, pulpit Wine i okno launchera 640×480 **nie dowodzą** renderowania gry w 640×480. Także zdarzenie `render_resolution` w [run-game.sh](<../sdcard/ports/projectdiablo2/scripts/run-game.sh#L370-L373>) raportuje wybór, a nie pomiar powierzchni.

## 3. Ograniczenia Project Diablo 2 — wynik weryfikacji

### 3.1. Potwierdzone dla wersji przypiętej w porcie

1. Zmiana samej listy `Ingame Resolutions` nie odblokowuje rozgrywki w innym rozmiarze. Wbudowane wymuszenie opisano w [historii portu](<../docs/PORT-README.md#L270-L274>) i odwzorowano w [implementacji](<../sdcard/ports/projectdiablo2/scripts/layout.py#L23-L41>).
2. Oryginał objęty poprawkami ma rozmiar **307200 bajtów** i SHA-256:

   ```text
   177242c2afd2df9da93ca1591c4189c6ca014e4ce5e6971e7b26912a146579cf
   ```

3. Istniejąca poprawka 800×600 zmienia szerokość; wariant 640×480 wymaga również zmiany wysokości. Zadziałanie 800×600 nie dowodzi poprawności 640×480.
4. Szablon wymusza pasek interfejsu 800. Przy szerokości 640 wymaga to osobnego sprawdzenia geometrii i dostępności zasobów. Nie wystarczy uznać `Use 800 Interface Bar? = false` za gotowe rozwiązanie.
5. Port zachowuje wymagane moduły PD2, w tym SGD2 i display-fix: [lista importowanych zależności](<../tools/prepare.py#L30-L35>). Usunięcie SGD2, wyłączenie dodatku lub powrót do trybu podstawowego Diablo II nie jest równoważnym rozwiązaniem.

### 3.2. Publiczne źródła i granice ich przydatności

- [PD2 FAQ — rozdzielczość](https://wiki.projectdiablo2.com/wiki/FAQ#What_resolution_does_PD2_use?): od sezonu 7 PD2 zawiera D2GL; opis wyższych rozdzielczości i tekstu w rozdzielczości natywnej dotyczy tego renderera. **Nie potwierdza** działania 640×480 w naszym torze `-ddraw` + cnc-ddraw.
- [PD2 Customization — ddraw.ini](https://wiki.projectdiablo2.com/wiki/Customization#ddraw.ini): `width`/`height` opisano jako „Stretch to custom resolution”. To rozmiar prezentacji, nie dowód zmiany wewnętrznej rozdzielczości gry.
- [README oficjalnego repozytorium PD2 BH](https://github.com/Project-Diablo-2/BH/blob/master/README.md): zmienione/debugowe BH przeznaczone jest tylko do singleplayer; autorzy ostrzegają przed multiplayer. Nie jest to bezpośrednia reguła dla każdej poprawki SGD2, ale nie daje podstaw do deklarowania zgodności zmodyfikowanego klienta z serwerami.

**Wniosek:** nie znaleziono w sprawdzonych źródłach gwarancji obsługi pełnego PD2 w 640×480 ani dowodu uniwersalnego minimum 800×600. Rzeczywiste ograniczenie potwierdzone w tym porcie to wymuszenie 1068×600 w konkretnym buildzie biblioteki. Minimum użytecznego interfejsu PD2 trzeba ustalić eksperymentalnie dla tego samego zestawu DLL/MPQ.

Wyszukiwarka zewnętrzna zwróciła HTTP 402; powyższe źródła pobrano bezpośrednio. Zakres weryfikacji nie obejmuje pełnego przeglądu wszystkich wersji/sezonów PD2. Wszystkie próby poniżej: **offline/singleplayer**, na kopii postaci testowej.

### 3.3. Ryzyka wymagające pomiaru, nie założeń

- Rozszerzony ekwipunek, skrzynia, kupiec, kostka i panele PD2 mogą mieć geometrię wymagającą więcej niż 640×480.
- Osobne ścieżki 640/800 w silniku mogą wybierać inne zasoby HUD i inne współrzędne kliknięć.
- BH, moduły PD2 lub display-fix mogą nadpisywać wymiary albo zakładać wysokość 600.
- Menu główne może używać innej rozdzielczości niż gra; działający ekran tytułowy nie wystarcza.
- Mniejsze pole widzenia jest naturalną konsekwencją mniejszego obszaru renderowania; nie wolno „naprawiać” go przez render większej sceny i ponowne skalowanie.

## 4. Etap A — udowodnić wykonalność przed dodaniem pozycji menu

### A1. Utrwalić punkt odniesienia

1. Zanotować commit portu, wersję/sezon PD2, hashe rzeczywistych modułów i istotnych MPQ, profil renderera, wersję Wine/Box86 i ustawienia wejścia.
2. Zabezpieczyć konfigurację i zapisy. Testować na osobnej postaci offline.
3. Na R36S wykonać bazowy pomiar 800×600: menu, miasto, walka, skrzynia, ekwipunek.
4. Zweryfikować oryginalny rozmiar/hash SGD2. Dla innej wersji przerwać ścieżkę poprawki i przygotować osobną analizę, bez wyszukiwania/zamiany dowolnych stałych.

### A2. Zbadać poprawkę 640×480

Punktem wyjścia jest wariant 1024×768 w [layout.py](<../sdcard/ports/projectdiablo2/scripts/layout.py#L32-L41>). Poniższa tabela to **kandydat badawczy, nie zatwierdzona poprawka**:

| Offset plikowy | Znaczenie według aktualnego kodu | Oryginał LE | Kandydat LE |
|---|---|---|---|
| `0x3ca1` | wysokość wektora | `58 02 00 00` = 600 | `e0 01 00 00` = 480 |
| `0x3caa` | szerokość wektora | `2c 04 00 00` = 1068 | `80 02 00 00` = 640 |
| `0xc6ab` | szerokość wymuszana przez parser | `2c 04 00 00` = 1068 | `80 02 00 00` = 640 |
| `0xc6b5` | wysokość wymuszana przez parser | `58 02 00 00` = 600 | `e0 01 00 00` = 480 |

Kolejność:

1. Na prawdziwym, zweryfikowanym oryginale odczytać instrukcje i przepływ sterowania wokół tych offsetów. Potwierdzić immediaty, odróżnić offset pliku od RVA.
2. Sprawdzić dalsze clampy/minima, rozgałęzienia trybu 640/800 oraz sposób ustalania rozmiaru HUD, buforów i paneli. Nie wykonywać globalnej zamiany liczb 800/600.
3. Wygenerować prywatną pochodną z oryginału, nigdy z cache 800/1024. Wyliczyć rzeczywisty SHA-256 wyniku i zapisać oczekiwany minimalny diff bajtowy.
4. Zidentyfikować, które klucze SGD2 faktycznie wpływają na menu i HUD. Testować kontrolowane warianty paska 800 tylko w kopii sesyjnej.
5. Potwierdzić, że nadal ładowany jest pełny PD2; nie akceptować uruchomienia bazowego LoD jako sukcesu.

### A3. Zmierzyć prawdziwy rozmiar renderowania

Dodać ograniczoną instrumentację testowego wrappera: argumenty `SetDisplayMode`, rozmiary powierzchni primary/backbuffer oraz rozmiar bufora przekazywanego do prezentacji GDI. Jeśli silnik rysuje do dodatkowej powierzchni offscreen, objąć pomiarem również ją. Rejestrować tylko zmianę trybu/rozmiaru, nie każdą klatkę.

Sprawdzić osobno: ekran tytułowy → wybór postaci → gra → otwarcie panelu → powrót do menu. Ustalić skalę Xwayland/Westona i rozmiar końcowego okna. Zrzut samego LCD 640×480 nie wystarcza.

**Bramka A:** kontynuować tylko po potwierdzeniu powierzchni 640×480 i używalnego UI. Gdy potrzebne są dodatkowe poprawki zasobów/interfejsu, oszacować je jako osobny zakres. Nie publikować trybu, który ucina pola skrzyni lub maskuje 800×600 pod etykietą 640×480.

## 5. Etap B — przygotowanie sesji i bezpieczna poprawka

### B1. Nowy wariant w przygotowaniu środowiska

W [layout.py](<../sdcard/ports/projectdiablo2/scripts/layout.py>):

- Dodać literalny token `640x480` do `GAME_RESOLUTIONS`, pozostawiając `native` bez zmiany znaczenia.
- Po bramce A dodać `SGD2_640_PATCHES`, wyliczony `SGD2_640_SHA256`, `sgd2_640_bytes()` i `sgd2_640_file()`.
- Wykorzystać istniejące `_sgd2_patch()`/`_sgd2_file()`; proponowany cache: `compat/sgd2-640x480-v1` w prywatnym stanie użytkownika.
- Zachować weryfikację oryginału przy każdym uruchomieniu, także przy istniejącym cache; walidować cache, preimage, wynik i ścieżki bez symlinków.
- Zmieniać wyłącznie cel linku biblioteki w roboczym `ProjectD2`. Nie edytować danych importowanych.
- Nie wpisywać fikcyjnego hasha wyniku; bez prawdziwego artefaktu poprawka nie jest gotowa.

### B2. Konfiguracja sesyjna, bez skutków ubocznych

- Dla 640×480 generować spójny wariant roboczy SGD2: rozdzielczość menu/lista/wybór/HUD wyłącznie według wyników A2. Sam JSON nadal nie zastępuje poprawki DLL.
- Wyjście wrappera pozostaje `width=640`, `height=480`; dla nowego wariantu ustawić właściwe `inject_resolution=640x480`. Nie przedstawiać `inject_resolution` jako wymuszenia rozdzielczości silnika.
- Uwzględnić sekcje specyficzne dla gry w INI, które mogą nadpisać klucze globalne. Pozostawić działające ustawienia myszy i sprawdzić ich zachowanie dla skali 1:1.
- Obecna korekta `inject_resolution` występuje przy `volatile_work` oraz `performance != off`: [generowanie kopii](<../sdcard/ports/projectdiablo2/scripts/layout.py#L667-L689>). Nowa funkcja ma jawnie obsłużyć zwykłe przygotowanie i etap sesyjny; nie polegać przypadkiem tylko na profilu performance.
- Oryginalny launcher wykonuje przygotowanie przed menu, potem przekazuje rozdzielczość przez środowisko: [Project Diablo 2.sh](<../sdcard/ports/Project%20Diablo%202.sh#L151-L166>). Sprawdzić, że ponowne przygotowanie po wyborze nie wraca do wcześniejszego wariantu.
- Dla `volatile_work=False` nie zapisywać nakładek przez link do trwałej konfiguracji. Jeśli nowy tryb wymaga kopii roboczej, tworzyć ją jawnie tylko dla tego wariantu.
- Rozszerzyć [sync_config()](<../sdcard/ports/projectdiablo2/scripts/layout.py#L724-L771>): nie utrwalać narzuconych kluczy rozdzielczości/HUD. Zachować niezwiązane zmiany użytkownika oraz dotychczasową ochronę ustawień kontrolera.
- Wybór w menu pozostaje sesyjny. Ręcznie zapisane `game_resolution=640x480` można obsłużyć po walidacji; nie dodawać automatycznego zapisywania wyboru bez osobnej decyzji.

### B3. Błędy i odzyskiwanie

Nieznana wersja, błędny hash, uszkodzony cache lub niespójna konfiguracja → przerwanie startu z bezpiecznym kodem błędu i czytelnym komunikatem. Bez cichego przełączania na 800×600 i bez usuwania danych/prefixu. Użytkownik może jawnie wybrać 800×600; oryginalne `native` pozostaje istniejącą ścieżką bez poprawki.

## 6. Etap C — menu launchera i przepływ wartości

| Plik | Planowana zmiana |
|---|---|
| [start_menu.py](<../sdcard/ports/projectdiablo2/scripts/start_menu.py>) | Dodać piąty wariant `640x480`, obsługę dziedziczenia i etykiety. Zachować `default` jako dziedziczenie, nie alias 640×480. |
| [menu_x11.py](<../sdcard/ports/projectdiablo2/scripts/menu_x11.py>) | Zastąpić `menu.resolution not in range(4)` walidacją względem liczby wariantów. `menu.row` nadal ma cztery wiersze — nie zwiększać go do pięciu. Ujednolicić etykiety zwykłe i dziedziczone. |
| [weston-session.sh](<../sdcard/ports/projectdiablo2/scripts/weston-session.sh>) | Dopuścić dokładnie `640x480 default`, `640x480 0`, `640x480 1`; zachować brak `eval`, anulowanie i odmowę startu przy błędnym protokole. |
| [run-game.sh](<../sdcard/ports/projectdiablo2/scripts/run-game.sh>) | Rozszerzyć allowlistę i diagnostykę wyboru; potwierdzić przekazanie tokenu do przygotowania roboczej gry. Pulpit Wine nadal 640×480. |
| [safe_log.py](<../sdcard/ports/projectdiablo2/scripts/safe_log.py>) | Dopuścić nowy status `render_resolution`; dodać osobny ograniczony schemat pomiaru powierzchni, jeśli instrumentacja trafia do produktu. |

Proponowane krótkie etykiety pasujące do aktualnego fontu: `LCD 640X480`, `800X600`, `1024X768`, `PD2 1068X600`. Techniczny token `native` nadal oznacza ostatni wariant. Dzięki temu „native” nie opisuje dwóch różnych rozdzielczości. Ewentualny dopisek eksperymentalności umieścić w osobnym wierszu, bez obcinania etykiety.

[Produkcyjny launcher](<../sdcard/ports/Project%20Diablo%202.sh>) nie wymaga obecnie edycji: przekazuje już `PD2_GAME_RESOLUTION`. Jeśli analiza ujawni konieczność jego zmiany, uzyskać osobną zgodę zgodnie z [AGENTS.md](<../AGENTS.md#L203-L209>). Wspólne skrypty muszą zachować dotychczasowe działanie dla wszystkich starych tokenów; eksperyment nie może zmieniać domyślnego środowiska.

## 7. Etap D — testy automatyczne

### Biblioteka i konfiguracja

Rozszerzyć [test_resolution_patch.py](<../tests/test_resolution_patch.py>) i [test_layout.py](<../tests/test_layout.py>):

- Poprawny wariant 640×480; zgodne wymiary obu miejsc inicjalizacji/wymuszenia; dokładny diff i niemodyfikowanie źródła.
- Odrzucenie innego rozmiaru, źródłowego hasha, preimage, hasha wyniku; uszkodzonego cache, pozostałości `.new`, duplikatów nazw i symlinków.
- Istniejący cache nigdy nie omija walidacji oryginału.
- `640x480` przestaje być przypadkiem negatywnym; pozostają negatywne `640X480`, `640x480 `, puste i nieprawidłowe typy oraz nieobsługiwane rozmiary.
- Roundtrip `800x600 → 640x480 → 1024x768 → native → 800x600`, oba tryby pracy, bez zmiany danych gry i zapisów.
- Nakładki konfiguracji nie utrwalają się przy synchronizacji, błędzie startu ani następnym uruchomieniu. Niezwiązane ustawienia nadal synchronizują się poprawnie.
- Domyślne i starsze ustawienia nadal wybierają 800×600. Nadpisanie sesyjne nie modyfikuje trwałego wyboru.

Fixture syntetyczne sprawdzają kontrakt mechanizmu, **nie** działanie prawdziwego PD2 ani prawdziwy hash nowej pochodnej. Weryfikację rzeczywistego artefaktu wykonywać lokalnie, bez dołączania własnościowych DLL do testów/repozytorium.

### Menu, shell, logi

Rozszerzyć [test_start_menu.py](<../tests/test_start_menu.py>), [test_menu_x11.py](<../tests/test_menu_x11.py>), [test_opengl_entry_fix.py](<../tests/test_opengl_entry_fix.py>), [test_safe_log.py](<../tests/test_safe_log.py>) i [test_display.py](<../tests/test_display.py>):

- Pięć wariantów rozdzielczości, cztery wiersze; nawigacja w obu kierunkach, zawijanie, Enter/Start, anulowanie, ekspozycja/przerysowanie X11.
- Dziedziczenie zapisanej wartości 640×480 i zachowanie `default` bez niejawnego zapisu.
- Każda dozwolona kombinacja z FPS; odrzucenie dodatkowych tokenów, nowej linii, payloadu shell i błędnego kodu wyjścia.
- Najdłuższa etykieta mieści się na ekranie 640×480.
- Nowe logi przechodzą filtr, nie ujawniają ścieżek prywatnych, danych postaci ani wejścia użytkownika.
- Brak zmian wymagających headless/noop, nowego renderera, innych flag Box86 czy zmian audio.

Przykładowy zestaw po implementacji:

```bash
python -m unittest discover -s tests -p "test_resolution_patch.py"
python -m unittest discover -s tests -p "test_layout.py"
python -m unittest discover -s tests -p "test_start_menu.py"
python -m unittest discover -s tests -p "test_menu_x11.py"
python -m unittest discover -s tests -p "test_opengl_entry_fix.py"
python -m unittest discover -s tests -p "test_safe_log.py"
python -m unittest discover -s tests -p "test_display.py"
python -m unittest discover -s tests -p "test_gpu_runtime.py"
python -m unittest discover -s tests -p "test_shell.py"
```

Testy wymagające Linux/symlinków uruchomić również w odpowiednim środowisku; pominięcia na Windows nie są pełną walidacją. Dla tego dokumentu nie wykonano tych testów — kod nie został zmieniony.

## 8. Etap E — obowiązkowa walidacja na R36S

### Macierz funkcjonalna

| Obszar | Kryterium odbioru |
|---|---|
| Start/menu/postać | Widoczne wszystkie przyciski, brak zmiany do większej powierzchni, poprawny kursor |
| Świat gry | Cztery brzegi obrazu, brak przycięcia lub rozciągania; brak powrotu do 800/1068 po zmianie lokacji |
| HUD | Kule życia/many, pas, umiejętności, doświadczenie, przyciski PD2 bez nakładania i ucięcia |
| Ekwipunek i skrzynia PD2 | Dostępne wszystkie sloty i zakładki; przenoszenie przedmiotów trafia we właściwe pola |
| Kupiec, kostka, najemnik | Pełne panele i przyciski, poprawne hitboxy |
| Statystyki/umiejętności/questy | Pełne panele, możliwość zamknięcia, brak zasłoniętych kontrolek |
| Tooltipy i loot filter | Czytelność i możliwość obejrzenia opisów przy brzegach; brak nowych krytycznych ucięć |
| Sterowanie | Natywny kontroler i mapper; kursor, kliknięcia, cele czarów, analogi, loot |
| Stabilność | Co najmniej 30 minut gry, przejścia lokacji, walka, zapis/odczyt i powrót do launchera |
| Regresja | Ponowny start 800×600, 1024×768 i oryginalnego `native`; brak zmiany konfiguracji i zapisów przez wybór rozdzielczości |

Pierwszy odbiór na produkcyjnym GDI. Eksperymentalny GPU/GLES2 sprawdzić osobno; jego wynik nie zastępuje odbioru GDI. Nie włączać OpenGL/headless w celu „naprawienia” rozdzielczości.

### Pomiar korzyści

800×600 = 480000 pikseli; 640×480 = 307200 pikseli: **36% mniej pikseli klatki źródłowej**. Dotyczy potencjalnie rasteryzacji, konwersji palety i kopiowania. Nie oznacza 36% mniej całkowitego CPU ani gwarantowanego wzrostu FPS. Symulacja, Box86, audio i część kosztu kompozytora pozostają; samo skalowanie może nie być głównym wąskim gardłem.

Procedura A/B: minimum trzy porównywalne przebiegi na wariant, naprzemiennie 800/640, po rozgrzewce. Ten sam zapis/lokacja, trasa, scena walki, renderer, limit FPS, filtry, audio, taktowanie i sposób pomiaru. Zanotować temperaturę i throttling. Przy scenach niedeterministycznych opisać różnice i rozrzut.

Rejestrować medianę FPS, p95/p99 czasu klatki, obciążenie procesu gry i kompozytora, RSS oraz zacięcia audio. Przy limicie 30 FPS korzyścią może być niższe CPU i mniej długich klatek zamiast wyższego FPS. Koszt instrumentacji kontrolować identycznie w obu wariantach. Dołączyć zrzuty tego samego HUD w obu trybach oraz pomiar rzeczywistych powierzchni.

**Bramka E:** brak błędów geometrii/interakcji, potwierdzone 1:1, działający rollback i brak istotnej regresji stabilności/wydajności. Wynik wydajności opublikować jako pomiar, nie obietnicę.

## 9. Wdrożenie, rollback, kolejność prac

1. **A — wykonalność:** analiza prawdziwej biblioteki, kandydat 640, pomiar powierzchni, pierwszy audyt UI. Wynik go/no-go przed obietnicą nowej opcji.
2. **B — mechanizm:** przypięta poprawka, prywatny cache, kopie sesyjne, ochrona synchronizacji, testy konfiguracji.
3. **C — obsługa wyboru:** model menu, renderer, protokół shella, walidatory i logi; stare wartości bez zmian.
4. **D/E — odbiór:** testy automatyczne, rzeczywista konsola, pełna macierz UI, A/B i przełączenia wsteczne.
5. **Publikacja:** udostępnić opcję dopiero po odbiorze; zachować domyślne 800×600. Uzupełnić [PORT-README.md](<../docs/PORT-README.md>) o znaczenie LCD 640 i PD2 1068, wspieraną wersję gry, ograniczenie offline i wyniki.
6. Pliki wykonawcze utrzymywać bezpośrednio w `sdcard/ports/`; bez ZIP/dist i bez dystrybucji oryginalnych lub zmodyfikowanych własnościowych bibliotek gry. Użytkownik generuje pochodną lokalnie z własnego, zgodnego oryginału.

Rollback użytkowy: wyjść z gry → wybrać 800×600 → uruchomić ponownie. Nie kasować prefixu, zapisów ani oryginałów. Cache 640 może pozostać nieużywany. Jeśli ktoś ręcznie utrwalił 640 w ustawieniach, przed powrotem do starszego kodu przywrócić obsługiwany token 800×600; starszy walidator odrzuci 640.

Jeżeli 640×480 nie mieści pełnego UI PD2: zatrzymać publikację, udokumentować konkretny panel/moduł i wymagane minimum. Zaproponować osobny plan adaptacji UI albo pozostawić 800×600 i optymalizować sprawdzony tor prezentacji. **Nie nazywać skalowanego 800×600 trybem natywnym 640×480.**

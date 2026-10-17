/* User-triggered built-in /fps toggle, NOT a wrapper frame counter.
 * Use ONLY inside a running game with chat/other text fields closed, never menus.
 * No startup typing, hooks, global injection, configuration, or file/log output.
 * FPS_NATIVE_TEST compiles only synthetic core tests; it never polls real input.
 */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <tlhelp32.h>

#define FPS_MASK 0x00a0u /* Select (0020) + R3 (0080), never Guide */
typedef struct { int armed; } FpsEdge;

static int fps_edge(FpsEdge *edge, unsigned bits, unsigned mask, int eligible)
{
    if (!eligible) { edge->armed = 0; return 0; }
    if (!(bits & mask)) { edge->armed = 1; return 0; }
    if ((bits & mask) == mask && edge->armed) {
        edge->armed = 0;
        return 1;
    }
    return 0;
}

static int fps_game_name(const WCHAR *path)
{
    const WCHAR *base = path, *p = path;
    static const WCHAR expected[] = L"game.exe";
    unsigned i;
    if (!path || !*path) return 0;
    for (; *p; ++p) if (*p == L'\\' || *p == L'/') base = p + 1;
    for (i = 0; expected[i]; ++i) {
        WCHAR c = base[i];
        if (!c) return 0;
        if (c >= L'A' && c <= L'Z') c += L'a' - L'A';
        if (c != expected[i]) return 0;
    }
    return base[i] == 0;
}

static int fps_target(int foreground, int visible, DWORD pid, DWORD tracked,
                      const WCHAR *image)
{
    return foreground && visible && pid && tracked == pid && fps_game_name(image);
}

typedef int (*FpsSend)(void *, UINT, WPARAM, LPARAM);
/* Revalidate the exact HWND/PID before EVERY bounded message; stop on failure.
 * Explicit WM_CHAR models TranslateMessage without using a global input queue.
 */
static int fps_type(FpsSend send, void *context)
{
    static const char text[] = "/fps";
    unsigned i;
    if (!send(context, WM_KEYDOWN, VK_RETURN, 0x001c0001L) ||
        !send(context, WM_CHAR, '\r', 0x001c0001L) ||
        !send(context, WM_KEYUP, VK_RETURN, (LPARAM)0xc01c0001UL)) return 0;
    for (i = 0; text[i]; ++i)
        if (!send(context, WM_CHAR, (WPARAM)text[i], 1)) return 0;
    return send(context, WM_KEYDOWN, VK_RETURN, 0x001c0001L) &&
           send(context, WM_CHAR, '\r', 0x001c0001L) &&
           send(context, WM_KEYUP, VK_RETURN, (LPARAM)0xc01c0001UL);
}

#ifndef FPS_NATIVE_TEST
/* Public XInputGetState ABI only; dynamic import keeps XInput optional. */
typedef struct { WORD buttons; BYTE lt, rt; SHORT lx, ly, rx, ry; } FpsPad;
typedef struct { DWORD packet; FpsPad pad; } FpsState;
typedef DWORD (WINAPI *FpsGetState)(DWORD, FpsState *);
typedef struct { HWND window; DWORD pid; HANDLE process; } FpsWindow;

static int fps_image(HANDLE process, WCHAR *image)
{
    DWORD size = 32768;
    return QueryFullProcessImageNameW(process, 0, image, &size) &&
           size < 32768 && fps_game_name(image);
}

static int fps_valid(FpsWindow *target)
{
    WCHAR image[32768];
    DWORD pid = 0;
    if (!target->process || WaitForSingleObject(target->process, 0) != WAIT_TIMEOUT)
        return 0;
    GetWindowThreadProcessId(target->window, &pid);
    if (!fps_image(target->process, image)) return 0;
    return fps_target(GetForegroundWindow() == target->window,
                      IsWindowVisible(target->window), pid, target->pid, image);
}

static int fps_send(void *context, UINT message, WPARAM key, LPARAM data)
{
    FpsWindow *target = (FpsWindow *)context;
    DWORD_PTR result;
    if (!fps_valid(target)) return 0;
    return SendMessageTimeoutW(target->window, message, key, data,
        SMTO_ABORTIFHUNG | SMTO_BLOCK, 100, &result) != 0;
}

static HANDLE fps_find_game(DWORD *pid)
{
    HANDLE snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    PROCESSENTRY32W entry;
    HANDLE found = NULL;
    if (snapshot == INVALID_HANDLE_VALUE) return NULL;
    entry.dwSize = sizeof(entry);
    if (Process32FirstW(snapshot, &entry)) do {
        if (fps_game_name(entry.szExeFile)) {
            WCHAR image[32768];
            HANDLE process = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE,
                                         FALSE, entry.th32ProcessID);
            if (process && fps_image(process, image) &&
                WaitForSingleObject(process, 0) == WAIT_TIMEOUT) {
                *pid = entry.th32ProcessID;
                found = process;
                break;
            }
            if (process) CloseHandle(process);
        }
    } while (Process32NextW(snapshot, &entry));
    CloseHandle(snapshot);
    return found;
}

int WINAPI WinMain(HINSTANCE instance, HINSTANCE previous, LPSTR command, int show)
{
    HMODULE library = LoadLibraryA("xinput1_4.dll");
    FpsGetState get_state = library ? (FpsGetState)(void *)GetProcAddress(library, "XInputGetState") : NULL;
    FpsEdge pad_edges[4] = {{0}, {0}, {0}, {0}}, keyboard = {0};
    FpsWindow target = {0};
    DWORD start = GetTickCount();
    (void)instance; (void)previous; (void)command; (void)show;
    while (!(target.process = fps_find_game(&target.pid))) {
        if ((DWORD)(GetTickCount() - start) >= 120000) goto done;
        Sleep(250);
    }
    while (WaitForSingleObject(target.process, 0) == WAIT_TIMEOUT) {
        unsigned i;
        int trigger = 0, valid;
        target.window = GetForegroundWindow();
        valid = fps_valid(&target);
        /* F10 is inspected only for the foreground game, never other apps. */
        trigger |= fps_edge(&keyboard, valid && (GetAsyncKeyState(VK_F10) & 0x8000) ? 1 : 0, 1, valid);
        for (i = 0; i < 4; ++i) {
            FpsState state = {0};
            int connected = get_state && get_state(i, &state) == ERROR_SUCCESS;
            trigger |= fps_edge(&pad_edges[i], connected ? state.pad.buttons : 0,
                                FPS_MASK, valid && connected);
        }
        if (trigger) (void)fps_type(fps_send, &target);
        Sleep(25);
    }
    CloseHandle(target.process);
done:
    if (library) FreeLibrary(library);
    return 0;
}
#else
/* In-process synthetic tests. No production main, process scan or input APIs. */
#include <assert.h>
typedef struct { unsigned count, fail; UINT messages[10]; WPARAM keys[10]; } FpsFake;
static int fps_fake_send(void *context, UINT message, WPARAM key, LPARAM data)
{
    FpsFake *fake = (FpsFake *)context;
    (void)data;
    if (fake->fail && fake->count + 1 == fake->fail) return 0;
    assert(fake->count < 10);
    fake->messages[fake->count] = message;
    fake->keys[fake->count++] = key;
    return 1;
}
int main(void)
{
    FpsEdge edge = {0};
    FpsFake fake = {0};
    unsigned n;
    assert(!fps_edge(&edge, FPS_MASK, FPS_MASK, 1)); /* held at startup */
    assert(!fps_edge(&edge, 0, FPS_MASK, 1));
    assert(!fps_edge(&edge, 0x20, FPS_MASK, 1));
    assert(fps_edge(&edge, FPS_MASK, FPS_MASK, 1));
    assert(!fps_edge(&edge, FPS_MASK, FPS_MASK, 1));
    assert(!fps_edge(&edge, 0x20, FPS_MASK, 1));
    assert(!fps_edge(&edge, FPS_MASK, FPS_MASK, 1)); /* both must release */
    assert(!fps_edge(&edge, 0, FPS_MASK, 1));
    assert(!fps_edge(&edge, 0, FPS_MASK, 0));
    assert(!fps_edge(&edge, FPS_MASK, FPS_MASK, 1)); /* foreground rearm */
    assert(!fps_edge(&edge, 0, FPS_MASK, 1));
    assert(fps_edge(&edge, FPS_MASK | 1, FPS_MASK, 1));
    edge.armed = 0;
    assert(!fps_edge(&edge, 1, 1, 1));
    assert(!fps_edge(&edge, 0, 1, 1));
    assert(fps_edge(&edge, 1, 1, 1));
    assert(!fps_edge(&edge, 1, 1, 1));
    assert(fps_target(1, 1, 42, 42, L"C:\\foo\\GaMe.ExE"));
    assert(!fps_target(0, 1, 42, 42, L"Game.exe"));
    assert(!fps_target(1, 0, 42, 42, L"Game.exe"));
    assert(!fps_target(1, 1, 0, 0, L"Game.exe"));
    assert(!fps_target(1, 1, 43, 42, L"Game.exe"));
    assert(!fps_target(1, 1, 42, 42, L"Game.exe.bak"));
    assert(!fps_game_name(L"NotGame.exe"));
    assert(!fps_game_name(L""));
    assert(fps_type(fps_fake_send, &fake));
    assert(fake.count == 10);
    assert(fake.messages[0] == WM_KEYDOWN && fake.keys[0] == VK_RETURN);
    assert(fake.messages[1] == WM_CHAR && fake.keys[1] == '\r');
    assert(fake.messages[2] == WM_KEYUP && fake.keys[2] == VK_RETURN);
    for (n = 0; n < 4; ++n) {
        assert(fake.messages[3+n] == WM_CHAR);
        assert(fake.keys[3+n] == (WPARAM)"/fps"[n]);
    }
    assert(fake.messages[7] == WM_KEYDOWN && fake.keys[7] == VK_RETURN);
    assert(fake.messages[8] == WM_CHAR && fake.keys[8] == '\r');
    assert(fake.messages[9] == WM_KEYUP && fake.keys[9] == VK_RETURN);
    for (n = 1; n <= 10; ++n) {
        FpsFake failed = {0}; failed.fail = n;
        assert(!fps_type(fps_fake_send, &failed));
        assert(failed.count == n-1);
    }
    return 0;
}
#endif

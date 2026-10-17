/* Standalone Win32 x86 GUI probe. No xinput import library is needed.
 * Only fixed enums are persisted; physical key codes exist in the UI only. */
#include <windows.h>
#include <stdio.h>
#include <string.h>

#define TIMER_ID 1
#define CONTROL_COUNT 17
#ifndef DURATION_MS
#define DURATION_MS 122000UL
#endif
#ifndef RESULT_PATH
#define RESULT_PATH "C:\\Diablo II\\ProjectD2\\pd2-xinput-result.json"
#endif
#ifndef XINPUT_DLL
#define XINPUT_DLL "xinput1_4.dll"
#endif

typedef struct {
    WORD wButtons;
    BYTE bLeftTrigger, bRightTrigger;
    SHORT sThumbLX, sThumbLY, sThumbRX, sThumbRY;
} XI_GAMEPAD;
typedef struct { DWORD dwPacketNumber; XI_GAMEPAD Gamepad; } XI_STATE;
typedef DWORD (WINAPI *GET_STATE)(DWORD, XI_STATE *);
typedef struct {
    XI_STATE live;
    XI_GAMEPAD baseline;
    BOOL connected, initialized;
    BOOL step_initialized, armed, pressed;
} SLOT;
static const char *keys[CONTROL_COUNT] = {
    "a", "b", "y", "x", "start", "select", "menu", "l1", "l2", "l3",
    "r1", "r2", "r3", "up", "down", "left", "right"
};
static const char *labels[CONTROL_COUNT] = {
    "A", "B", "Y", "X", "Start", "Select", "Menu", "L1", "L2", "L3",
    "R1", "R2", "R3", "Up", "Down", "Left", "Right"
};
static const WORD masks[CONTROL_COUNT] = {
    0x1000, 0x2000, 0x8000, 0x4000, 0x0010, 0x0020, 0x0400,
    0x0100, 0, 0x0040, 0x0200, 0, 0x0080, 1, 2, 4, 8
};
static HMODULE library;
static GET_STATE get_state, standard_get_state;
static BOOL guide_supported;
static SLOT slots[4];
static const char *api = "library_missing";
static DWORD started, step_ms;
static int current_step = -2;
static unsigned connected_now;
static BOOL seen_device, seen_error, seen_buttons;
static BOOL seen_left, seen_right, seen_triggers, finished;
static BOOL step_device[CONTROL_COUNT];
static unsigned control_stage[CONTROL_COUNT];
static unsigned physical_stage[CONTROL_COUNT], physical_code[CONTROL_COUNT];
static BOOL physical_available;
static char request_path[MAX_PATH], physical_path[MAX_PATH];
static int result_code = 1;
static HFONT font;

static void sibling_path(char *out, const char *name) {
    const char *p, *last = NULL;
    size_t prefix;
    for (p = RESULT_PATH; *p; ++p) if (*p == '/' || *p == '\\') last = p;
    prefix = last ? (size_t)(last - RESULT_PATH + 1) : 0;
    if (prefix + strlen(name) >= MAX_PATH) { out[0] = 0; return; }
    memcpy(out, RESULT_PATH, prefix);
    memcpy(out + prefix, name, strlen(name) + 1);
}
static void publish_step(int index) {
    HANDLE file;
    char text[16];
    DWORD count, written;
    unsigned i;
    current_step = index;
    for (i = 0; i < 4; ++i) {
        slots[i].step_initialized = slots[i].armed = slots[i].pressed = FALSE;
    }
    count = (DWORD)snprintf(text, sizeof(text), "%d\n", index);
    file = CreateFileA(request_path, GENERIC_WRITE,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, NULL,
        CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (file != INVALID_HANDLE_VALUE) {
        WriteFile(file, text, count, &written, NULL);
        CloseHandle(file);
    }
}
/* Bounded decimal parser: neither sscanf nor unbounded string scans on input. */
static BOOL number(const char **cursor, const char *end, unsigned max, unsigned *out) {
    const char *p = *cursor;
    unsigned n = 0;
    if (p == end || *p < '0' || *p > '9') return FALSE;
    do {
        unsigned digit = (unsigned)(*p++ - '0');
        if (n > max / 10 || (n == max / 10 && digit > max % 10)) return FALSE;
        n = n * 10 + digit;
    } while (p < end && *p >= '0' && *p <= '9');
    *cursor = p; *out = n;
    return TRUE;
}
static BOOL separator(const char **p, const char *end, char ch) {
    if (*p == end || **p != ch) return FALSE;
    ++*p;
    return TRUE;
}
static void read_physical(void) {
    char data[1025];
    unsigned stages[CONTROL_COUNT], codes[CONTROL_COUNT], i, index;
    DWORD size, got;
    const char *p, *end;
    HANDLE file;
    physical_available = FALSE;
    file = CreateFileA(physical_path, GENERIC_READ,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, NULL,
        OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
    if (file == INVALID_HANDLE_VALUE) return;
    size = GetFileSize(file, NULL);
    if (size > 1024 || size < 11 || !ReadFile(file, data, sizeof(data), &got, NULL)) {
        CloseHandle(file); return;
    }
    CloseHandle(file);
    if (got != size || memcmp(data, "PD2BUTTON1\n", 11)) return;
    p = data + 11; end = data + got;
    for (i = 0; i < CONTROL_COUNT; ++i) {
        if (!number(&p, end, 16, &index) || index != i ||
            !separator(&p, end, ' ') || !number(&p, end, 3, &stages[i]) ||
            !separator(&p, end, ' ') || !number(&p, end, 767, &codes[i]) ||
            !separator(&p, end, '\n')) return;
    }
    if (p != end) return;
    memcpy(physical_stage, stages, sizeof(stages));
    memcpy(physical_code, codes, sizeof(codes));
    physical_available = TRUE;
}
static BOOL moved(int value, int baseline) {
    int delta = value - baseline;
    return delta > 4000 || delta < -4000;
}
static BOOL down(const XI_GAMEPAD *pad, int index) {
    if (index == 8) return pad->bLeftTrigger >= 31;
    if (index == 11) return pad->bRightTrigger >= 31;
    return (pad->wButtons & masks[index]) != 0;
}
static void poll_slots(void) {
    unsigned i;
    connected_now = 0;
    if (!get_state) return;
    for (i = 0; i < 4; ++i) {
        XI_STATE state;
        DWORD rc = get_state(i, &state);
        SLOT *slot = &slots[i];
        BOOL held;
        /* Some Wine builds export ordinal 100 but do not implement it. */
        if (guide_supported && (rc == ERROR_CALL_NOT_IMPLEMENTED || rc == ERROR_NOT_SUPPORTED)) {
            guide_supported = FALSE;
            if (standard_get_state) {
                get_state = standard_get_state;
                rc = get_state(i, &state);
            }
        }
        slot->connected = rc == ERROR_SUCCESS;
        if (rc != ERROR_SUCCESS) {
            if (rc != ERROR_DEVICE_NOT_CONNECTED) seen_error = TRUE;
            /* A lost connection is never evidence of release. Rebaseline on return. */
            slot->step_initialized = slot->armed = slot->pressed = FALSE;
            continue;
        }
        ++connected_now;
        seen_device = TRUE;
        slot->live = state;
        if (!slot->initialized) {
            slot->baseline = state.Gamepad;
            slot->initialized = TRUE;
        }
        if (state.Gamepad.wButtons != slot->baseline.wButtons) seen_buttons = TRUE;
        if (moved(state.Gamepad.sThumbLX, slot->baseline.sThumbLX) ||
            moved(state.Gamepad.sThumbLY, slot->baseline.sThumbLY)) seen_left = TRUE;
        if (moved(state.Gamepad.sThumbRX, slot->baseline.sThumbRX) ||
            moved(state.Gamepad.sThumbRY, slot->baseline.sThumbRY)) seen_right = TRUE;
        if (moved((int)state.Gamepad.bLeftTrigger * 128,
                  (int)slot->baseline.bLeftTrigger * 128) ||
            moved((int)state.Gamepad.bRightTrigger * 128,
                  (int)slot->baseline.bRightTrigger * 128)) seen_triggers = TRUE;
        if (current_step < 0) continue;
        step_device[current_step] = TRUE;
        if (current_step == 6 && !guide_supported) continue;
        held = down(&state.Gamepad, current_step);
        if (!slot->step_initialized) {
            slot->step_initialized = TRUE;
            slot->armed = !held;
        } else if (!held) {
            if (slot->pressed) control_stage[current_step] = 2;
            slot->armed = TRUE;
            slot->pressed = FALSE;
        } else if (slot->armed) {
            slot->pressed = TRUE;
            if (!control_stage[current_step]) control_stage[current_step] = 1;
        }
    }
}
static const char *control_result(unsigned i) {
    if (!step_device[i]) return "unavailable";
    if (i == 6 && !guide_supported) return "unsupported";
    return control_stage[i] == 2 ? "passed" : control_stage[i] == 1 ? "pressed" : "not_seen";
}
static const char *physical_result(unsigned i) {
    static const char *values[] = {"not_seen", "pressed", "passed", "multiple"};
    return physical_available ? values[physical_stage[i]] : "unavailable";
}
static int write_summary(void) {
    char json[4096];
    DWORD written;
    BOOL ok;
    unsigned i;
    int count;
    const char *devices = seen_device ? "ready" : (!get_state || seen_error ? "error" : "missing");
    const char *buttons = !seen_device ? "unavailable" : (seen_buttons ? "changed" : "unchanged");
    const char *axes = !seen_device ? "unavailable" :
        (seen_left || seen_right || seen_triggers ? "changed" : "unchanged");
    HANDLE file;
    count = snprintf(json, sizeof(json),
        "{\"schema_version\":2,\"api\":\"%s\",\"devices\":\"%s\","
        "\"buttons\":\"%s\",\"axes\":\"%s\",\"controls\":{", api, devices, buttons, axes);
    for (i = 0; i < CONTROL_COUNT; ++i)
        count += snprintf(json + count, sizeof(json) - count, "%s\"%s\":\"%s\"",
            i ? "," : "", keys[i], control_result(i));
    count += snprintf(json + count, sizeof(json) - count, "},\"physical_controls\":{");
    for (i = 0; i < CONTROL_COUNT; ++i)
        count += snprintf(json + count, sizeof(json) - count, "%s\"%s\":\"%s\"",
            i ? "," : "", keys[i], physical_result(i));
    count += snprintf(json + count, sizeof(json) - count, "}}\n");
    if (count < 0 || (unsigned)count >= sizeof(json)) return 1;
    file = CreateFileA(RESULT_PATH, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS,
                       FILE_ATTRIBUTE_NORMAL, NULL);
    if (file == INVALID_HANDLE_VALUE) return 1;
    ok = WriteFile(file, json, (DWORD)count, &written, NULL);
    if (!ok || written != (DWORD)count) { CloseHandle(file); return 1; }
    ok = FlushFileBuffers(file);
    if (!CloseHandle(file)) ok = FALSE;
    return ok ? 0 : 1;
}
static void finish(HWND window) {
    if (finished) return;
    finished = TRUE;
    KillTimer(window, TIMER_ID);
    publish_step(-1);
    read_physical();
    result_code = write_summary();
    DestroyWindow(window);
}
static void line(HDC dc, int x, int y, const char *text) {
    TextOutA(dc, x, y, text, lstrlenA(text));
}
static void paint(HWND window) {
    PAINTSTRUCT ps;
    HDC dc = BeginPaint(window, &ps);
    HGDIOBJ old = SelectObject(dc, font);
    char text[160], code[16];
    DWORD elapsed = GetTickCount() - started;
    unsigned remaining = elapsed >= DURATION_MS ? 0 :
        (unsigned)((DURATION_MS - elapsed + 999) / 1000);
    unsigned i;
    SetBkMode(dc, TRANSPARENT);
    snprintf(text, sizeof(text), "PD2 guided buttons - %us remaining", remaining);
    line(dc, 10, 8, text);
    snprintf(text, sizeof(text), "API %s / Guide %s / connected %u/4", api,
        guide_supported ? "ordinal100" : "unsupported", connected_now);
    line(dc, 10, 28, text);
    if (current_step >= 0) {
        DWORD deadline = (DWORD)(current_step + 1) * step_ms;
        unsigned left = elapsed >= deadline ? 0 : (unsigned)((deadline - elapsed + 999) / 1000);
        snprintf(text, sizeof(text), "STEP %d/17: Press and RELEASE %s (%us)",
            current_step + 1, labels[current_step], left);
    } else snprintf(text, sizeof(text), "SUMMARY - all 17 steps complete; auto-exit in %us", remaining);
    line(dc, 10, 52, text);
    line(dc, 10, 74, "Release held keys first. Physical / XInput results:");
    line(dc, 10, 98, "Key  Physical      XInput");
    line(dc, 310, 98, "Key  Physical      XInput");
    for (i = 0; i < CONTROL_COUNT; ++i) {
        int x = i < 9 ? 10 : 310;
        int y = 120 + (int)(i < 9 ? i : i - 9) * 24;
        code[0] = 0;
        if (physical_available && physical_stage[i])
            snprintf(code, sizeof(code), " %03X", physical_code[i]);
        snprintf(text, sizeof(text), "%-6s %-11s %-11s%s", labels[i],
            physical_result(i), control_result(i), code);
        line(dc, x, y, text);
    }
    line(dc, 10, 344, "not_seen=no press; pressed=no release; passed=press+release");
    line(dc, 10, 362, "unsupported=no API; unavailable=no data; multiple=ambiguous");
    line(dc, 10, 380, "Hex=physical code (UI only). Only fixed enums are saved.");
    SelectObject(dc, old);
    EndPaint(window, &ps);
}
static void tick(void) {
    DWORD elapsed = GetTickCount() - started;
    int index = elapsed / step_ms >= CONTROL_COUNT ? -1 : (int)(elapsed / step_ms);
    if (index != current_step) publish_step(index);
    poll_slots();
    read_physical();
}
static LRESULT CALLBACK window_proc(HWND window, UINT message, WPARAM wp, LPARAM lp) {
    switch (message) {
    case WM_TIMER:
        if (wp == TIMER_ID && !finished) {
            if (GetTickCount() - started >= DURATION_MS) finish(window);
            else { tick(); InvalidateRect(window, NULL, TRUE); }
        }
        return 0;
    case WM_PAINT: paint(window); return 0;
    case WM_CLOSE: finish(window); return 0;
    case WM_DESTROY: PostQuitMessage(result_code); return 0;
    }
    return DefWindowProcA(window, message, wp, lp);
}
int WINAPI WinMain(HINSTANCE instance, HINSTANCE previous, LPSTR command, int show) {
    WNDCLASSA cls;
    HWND window;
    MSG message;
    DWORD summary_ms = DURATION_MS / 6;
    UINT interval;
    int rc;
    (void)previous; (void)command;
    if (summary_ms > 20000) summary_ms = 20000;
    step_ms = (DURATION_MS - summary_ms) / CONTROL_COUNT;
    if (!step_ms) step_ms = 1;
    interval = (UINT)(step_ms / 6);
    if (!interval) interval = 1;
    if (interval > 50) interval = 50;
    sibling_path(request_path, "pd2-button-step.txt");
    sibling_path(physical_path, "pd2-button-physical.txt");
    library = LoadLibraryA(XINPUT_DLL);
    if (library) {
        standard_get_state = (GET_STATE)GetProcAddress(library, "XInputGetState");
        get_state = (GET_STATE)GetProcAddress(library, (LPCSTR)100);
        guide_supported = get_state != NULL;
        if (!get_state) get_state = standard_get_state;
        api = get_state ? "ready" : "entry_missing";
    }
    ZeroMemory(&cls, sizeof(cls));
    cls.lpfnWndProc = window_proc;
    cls.hInstance = instance;
    cls.lpszClassName = "PD2XInputProbe";
    cls.hCursor = LoadCursor(NULL, IDC_ARROW);
    cls.hbrBackground = (HBRUSH)(COLOR_WINDOW + 1);
    font = CreateFontA(14, 0, 0, 0, FW_NORMAL, FALSE, FALSE, FALSE, ANSI_CHARSET,
        OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS, DEFAULT_QUALITY,
        FIXED_PITCH | FF_MODERN, "Consolas");
    if (!font) font = (HFONT)GetStockObject(ANSI_FIXED_FONT);
    started = GetTickCount();
    if (!RegisterClassA(&cls)) {
        if (library) FreeLibrary(library);
        return 1;
    }
    window = CreateWindowExA(0, cls.lpszClassName, "PD2 native XInput probe",
        WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU | WS_MINIMIZEBOX,
        5, 10, 620, 450, NULL, NULL, instance, NULL);
    if (window) {
        started = GetTickCount(); /* Startup cost must not skip the first prompt. */
        tick();
        ShowWindow(window, show);
        UpdateWindow(window);
        if (!SetTimer(window, TIMER_ID, interval, NULL)) {
            publish_step(-1);
            finished = TRUE;
            result_code = 1;
            DestroyWindow(window);
        }
        while ((rc = GetMessageA(&message, NULL, 0, 0)) > 0) {
            TranslateMessage(&message);
            DispatchMessageA(&message);
        }
        if (rc == -1) {
            publish_step(-1);
            if (!finished) DestroyWindow(window);
            result_code = 1;
        }
    } else result_code = 1;
    if (library) FreeLibrary(library);
    UnregisterClassA(cls.lpszClassName, instance);
    if (font != GetStockObject(ANSI_FIXED_FONT)) DeleteObject(font);
    return result_code;
}

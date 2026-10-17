/* Synthetic x86 fixture only. Never loads XInput or reads host controllers. */
#include <windows.h>
#include <string.h>
#include <stdlib.h>

typedef struct {
    WORD wButtons;
    BYTE bLeftTrigger, bRightTrigger;
    SHORT sThumbLX, sThumbLY, sThumbRX, sThumbRY;
} STUB_GAMEPAD;
typedef struct { DWORD dwPacketNumber; STUB_GAMEPAD Gamepad; } STUB_STATE;

/* Guided fixtures follow only the probe's public numeric step handshake. */
static DWORD guided(DWORD index, STUB_STATE *state, const char *mode) {
    static int previous = -2;
    static unsigned samples;
    static const WORD masks[17] = {0x1000, 0x2000, 0x8000, 0x4000,
        0x0010, 0x0020, 0x0400, 0x0100, 0, 0x0040, 0x0200, 0,
        0x0080, 1, 2, 4, 8};
    char path[MAX_PATH], text[32];
    DWORD got;
    HANDLE file;
    int step;
    BOOL held;
    GetEnvironmentVariableA("PD2_XINPUT_STEP_PATH", path, sizeof(path));
    file = CreateFileA(path, GENERIC_READ,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, NULL,
        OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
    if (file == INVALID_HANDLE_VALUE) return ERROR_DEVICE_NOT_CONNECTED;
    if (!ReadFile(file, text, sizeof(text) - 1, &got, NULL)) got = 0;
    CloseHandle(file);
    text[got] = 0;
    step = atoi(text);
    if (step != previous) { previous = step; samples = 0; }
    if (index != (strcmp(mode, "guided_slot3") == 0 ? 3UL : 0UL))
        return ERROR_DEVICE_NOT_CONNECTED;
    ++samples;
    ZeroMemory(state, sizeof(*state));
    if (step < 0 || step > 16) return ERROR_SUCCESS;
    held = samples == 2;
    if (strcmp(mode, "guided_press") == 0) held = samples >= 2;
    if (strcmp(mode, "guided_held") == 0) held = TRUE;
    if (strcmp(mode, "guided_rearm") == 0) held = samples == 1 || samples == 3;
    if (strcmp(mode, "guided_disconnect") == 0) {
        if (samples >= 4) return ERROR_DEVICE_NOT_CONNECTED;
        held = samples >= 2;
    }
    if (strcmp(mode, "guided_reconnect") == 0) {
        if (samples == 3) return ERROR_DEVICE_NOT_CONNECTED;
        held = samples == 2;
    }
    if (held) {
        if (step == 8) state->Gamepad.bLeftTrigger = 31;
        else if (step == 11) state->Gamepad.bRightTrigger = 31;
        else state->Gamepad.wButtons = masks[step];
    }
    if (strcmp(mode, "guided_below") == 0 && (step == 8 || step == 11)) {
        state->Gamepad.bLeftTrigger = state->Gamepad.bRightTrigger = 30;
    }
    return ERROR_SUCCESS;
}

/* The .def files export exact undecorated names for the stdcall ABI. */
DWORD WINAPI StubGetState(DWORD index, STUB_STATE *state) {
    static DWORD calls;
    char mode[32];
    STUB_GAMEPAD *pad;
    GetEnvironmentVariableA("PD2_XINPUT_TEST_CASE", mode, sizeof(mode));
    if (index > 3) return ERROR_BAD_ARGUMENTS;
    if (strncmp(mode, "guided_", 7) == 0) return guided(index, state, mode);
    if (index != 0 || strcmp(mode, "missing") == 0)
        return ERROR_DEVICE_NOT_CONNECTED;
    if (strcmp(mode, "error") == 0) return ERROR_GEN_FAILURE;
    ++calls;
    if (strcmp(mode, "disconnect") == 0 && calls > 2)
        return ERROR_DEVICE_NOT_CONNECTED;
    ZeroMemory(state, sizeof(*state));
    state->dwPacketNumber = calls;
    pad = &state->Gamepad;
    pad->wButtons = 0x1000;
    pad->bLeftTrigger = 40;
    pad->bRightTrigger = 50;
    pad->sThumbLX = -12000;
    pad->sThumbLY = 8000;
    pad->sThumbRX = 16000;
    pad->sThumbRY = -9000;
    if (calls > 1 && strcmp(mode, "static") != 0) {
        if (strcmp(mode, "changing") == 0 || strcmp(mode, "buttons") == 0 ||
            strcmp(mode, "disconnect") == 0) pad->wButtons = 0x2000;
        if (strcmp(mode, "changing") == 0 || strcmp(mode, "left") == 0 ||
            strcmp(mode, "disconnect") == 0) pad->sThumbLX += 5000;
        if (strcmp(mode, "right") == 0) pad->sThumbRY += 5000;
        if (strcmp(mode, "triggers") == 0) pad->bRightTrigger += 40;
        if (strcmp(mode, "threshold") == 0) {
            pad->sThumbLX += 4000;
            pad->sThumbRY -= 4000;
            pad->bLeftTrigger += 31;
        }
    }
    return ERROR_SUCCESS;
}
DWORD WINAPI StubGetStateEx(DWORD index, STUB_STATE *state) {
    char mode[32];
    GetEnvironmentVariableA("PD2_XINPUT_TEST_CASE", mode, sizeof(mode));
    if (strcmp(mode, "guided_notimpl") == 0) return ERROR_CALL_NOT_IMPLEMENTED;
    if (strcmp(mode, "guided_notsupported") == 0) return ERROR_NOT_SUPPORTED;
    if (strcmp(mode, "guided_ex_disconnected") == 0) return ERROR_DEVICE_NOT_CONNECTED;
    return StubGetState(index, state);
}

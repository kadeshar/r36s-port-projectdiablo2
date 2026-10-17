/* Own bounded Windows x86 diagnostic. No game files or settings are modified.
 * An explicit Audio Test entry plays a quiet 1.5-second tone; no mic/capture.
 */
#define COBJMACROS
#include <windows.h>
#include <mmsystem.h>
#include <dsound.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifndef RESULT_PATH
#define RESULT_PATH "C:\\Diablo II\\ProjectD2\\pd2-audio-result.json"
#endif
#define RATE 48000
#define FRAMES 72000
#define SAMPLES (FRAMES * 2)
static const char *opened = "error", *written = "not_run", *tone = "not_run";
static const char *directsound = "not_run";
static unsigned devices;
static DWORD started;
static BOOL tested, finished;
static int result_code = 1;

static const char *mm_status(MMRESULT rc) {
    switch (rc) {
    case MMSYSERR_NOERROR: return "ready";
    case MMSYSERR_NODRIVER: case MMSYSERR_BADDEVICEID: return "missing";
    case MMSYSERR_ALLOCATED: return "busy";
    case MMSYSERR_NOTSUPPORTED: case WAVERR_BADFORMAT: return "unsupported";
    default: return "error";
    }
}
static const char *ds_status(HRESULT rc) {
    if (SUCCEEDED(rc)) return "ready";
    if (rc == DSERR_NODRIVER) return "missing";
    if (rc == DSERR_ALLOCATED) return "busy";
    if (rc == DSERR_UNSUPPORTED) return "unsupported";
    if (rc == E_ACCESSDENIED) return "denied";
    return "error";
}
static void fill_tone(short *samples) {
    unsigned i;
    for (i = 0; i < FRAMES; ++i) {
        /* Gentle attack/release; ~4.6% full scale, not a system-volume change. */
        double envelope = 1.0;
        short value;
        if (i < 2400) envelope = i / 2400.0;
        if (i >= FRAMES - 2400) envelope = (FRAMES - 1 - i) / 2400.0;
        value = (short)(1500.0 * envelope * sin(6.283185307179586 * 440.0 * i / RATE));
        samples[i * 2] = samples[i * 2 + 1] = value;
    }
}
static void run_test(void) {
    HWAVEOUT output = NULL;
    HANDLE completed = NULL;
    WAVEFORMATEX format;
    WAVEHDR header;
    MMRESULT rc;
    short *samples = NULL;
    LPDIRECTSOUND ds = NULL;
    devices = waveOutGetNumDevs();
    if (devices > 256) devices = 256;
    directsound = ds_status(DirectSoundCreate(NULL, &ds, NULL));
    if (ds) IDirectSound_Release(ds);
    completed = CreateEventA(NULL, FALSE, FALSE, NULL);
    if (!completed) return;
    ZeroMemory(&format, sizeof(format));
    format.wFormatTag = WAVE_FORMAT_PCM;
    format.nChannels = 2;
    format.nSamplesPerSec = RATE;
    format.wBitsPerSample = 16;
    format.nBlockAlign = 4;
    format.nAvgBytesPerSec = RATE * 4;
    rc = waveOutOpen(&output, WAVE_MAPPER, &format, (DWORD_PTR)completed, 0, CALLBACK_EVENT);
    opened = mm_status(rc);
    if (rc != MMSYSERR_NOERROR) { CloseHandle(completed); return; }
    samples = (short *)malloc(SAMPLES * sizeof(short));
    if (!samples) { written = "error"; goto cleanup; }
    fill_tone(samples);
    ZeroMemory(&header, sizeof(header));
    header.lpData = (LPSTR)samples;
    header.dwBufferLength = SAMPLES * sizeof(short);
    rc = waveOutPrepareHeader(output, &header, sizeof(header));
    if (rc != MMSYSERR_NOERROR) { written = "error"; goto cleanup; }
    ResetEvent(completed);  /* Do not mistake WOM_OPEN for WOM_DONE. */
    rc = waveOutWrite(output, &header, sizeof(header));
    written = rc == MMSYSERR_NOERROR ? "ready" : "error";
    if (rc == MMSYSERR_NOERROR) {
        DWORD until = GetTickCount() + 4000;
        while (!(header.dwFlags & WHDR_DONE) && (LONG)(until - GetTickCount()) > 0)
            WaitForSingleObject(completed, 100);
        tone = (header.dwFlags & WHDR_DONE) ? "completed" : "error";
    }
    waveOutReset(output);
    waveOutUnprepareHeader(output, &header, sizeof(header));
cleanup:
    waveOutClose(output);
    CloseHandle(completed);
    free(samples);
}
static int summary(void) {
    char json[512];
    DWORD length, count = 0;
    HANDLE file;
    int size = snprintf(json, sizeof(json),
        "{\"schema_version\":1,\"devices\":%u,\"open\":\"%s\",\"write\":\"%s\","
        "\"tone\":\"%s\",\"directsound\":\"%s\"}\n",
        devices, opened, written, tone, directsound);
    if (size < 0 || size >= (int)sizeof(json)) return 1;
    length = (DWORD)size;
    file = CreateFileA(RESULT_PATH, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS,
                       FILE_ATTRIBUTE_NORMAL, NULL);
    if (file == INVALID_HANDLE_VALUE) return 1;
    if (!WriteFile(file, json, length, &count, NULL) || count != length || !FlushFileBuffers(file)) {
        CloseHandle(file); return 1;
    }
    return CloseHandle(file) ? 0 : 1;
}
static void finish(HWND window) {
    if (finished) return;
    finished = TRUE;
    KillTimer(window, 1);
    result_code = summary();
    DestroyWindow(window);
}
static void text(HDC dc, int y, const char *value) { TextOutA(dc, 14, y, value, (int)strlen(value)); }
static LRESULT CALLBACK proc(HWND window, UINT message, WPARAM wp, LPARAM lp) {
    switch (message) {
    case WM_TIMER:
        if (wp != 1 || finished) return 0;
        if (!tested) { tested = TRUE; run_test(); }
        if (GetTickCount() - started >= 10000) finish(window);
        else InvalidateRect(window, NULL, TRUE);
        return 0;
    case WM_PAINT: {
        PAINTSTRUCT ps;
        HDC dc = BeginPaint(window, &ps);
        HGDIOBJ old = SelectObject(dc, GetStockObject(ANSI_FIXED_FONT));
        char line[160];
        SetBkMode(dc, TRANSPARENT);
        text(dc, 14, "PD2 Audio Test - quiet 1.5-second tone, auto-close in 10s");
        snprintf(line, sizeof(line), "Output endpoints: %u / DirectSound: %s", devices, directsound);
        text(dc, 52, line);
        snprintf(line, sizeof(line), "WaveOut open: %s / write: %s / tone: %s", opened, written, tone);
        text(dc, 78, line);
        text(dc, 120, "A completed buffer proves API playback, NOT audible speakers.");
        text(dc, 146, "Please report: heard tone YES/NO; speaker or headphones.");
        text(dc, 184, "No microphone, mixer changes, raw device names or input logs.");
        text(dc, 210, "Take a photo and send the last safe port log.");
        SelectObject(dc, old);
        EndPaint(window, &ps);
        return 0;
    }
    case WM_CLOSE: finish(window); return 0;
    case WM_DESTROY: PostQuitMessage(0); return 0;
    }
    return DefWindowProcA(window, message, wp, lp);
}
static int self_test(void) {
    short *samples = (short *)malloc(SAMPLES * sizeof(short));
    unsigned i;
    BOOL varied = FALSE;
    if (!samples) return 1;
    fill_tone(samples);
    for (i = 0; i < FRAMES; ++i) {
        if (samples[i * 2] != samples[i * 2 + 1] || abs(samples[i * 2]) > 1500) { free(samples); return 2; }
        if (samples[i * 2] != 0) varied = TRUE;
    }
    if (!varied || samples[0] || samples[SAMPLES - 1]) { free(samples); return 3; }
    free(samples);
    if (strcmp(mm_status(MMSYSERR_ALLOCATED), "busy") ||
        strcmp(mm_status(WAVERR_BADFORMAT), "unsupported") ||
        strcmp(ds_status(DSERR_NODRIVER), "missing") ||
        strcmp(ds_status(E_ACCESSDENIED), "denied")) return 4;
    return 0;  /* This path never opens any audio device. */
}
int WINAPI WinMain(HINSTANCE instance, HINSTANCE previous, LPSTR command, int show) {
    WNDCLASSA cls;
    HWND window;
    MSG message;
    int rc;
    (void)previous;
    if (!strcmp(command, "--self-test")) return self_test();
    ZeroMemory(&cls, sizeof(cls));
    cls.lpfnWndProc = proc;
    cls.hInstance = instance;
    cls.hCursor = LoadCursor(NULL, IDC_ARROW);
    cls.hbrBackground = (HBRUSH)(COLOR_WINDOW + 1);
    cls.lpszClassName = "PD2AudioProbe";
    if (!RegisterClassA(&cls)) return 1;
    started = GetTickCount();
    window = CreateWindowExA(0, cls.lpszClassName, "PD2 Audio Test",
        WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU, 5, 20, 620, 300,
        NULL, NULL, instance, NULL);
    if (!window) return 1;
    ShowWindow(window, show);
    UpdateWindow(window);
    if (!SetTimer(window, 1, 100, NULL)) { DestroyWindow(window); return 1; }
    while ((rc = GetMessageA(&message, NULL, 0, 0)) > 0) {
        TranslateMessage(&message); DispatchMessageA(&message);
    }
    UnregisterClassA(cls.lpszClassName, instance);
    return rc == -1 ? 1 : result_code;
}

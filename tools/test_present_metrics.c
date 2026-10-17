/* SPDX-License-Identifier: MIT */
#ifdef _WIN32
#define PD2_PRESENT_IMPLEMENTATION
#else
#define PD2_PRESENT_CORE_ONLY
#endif
#include "present_metrics.h"
#include <assert.h>
#include <string.h>
int main(void)
{
    pd2_metrics m;
    char line[PD2_PRESENT_LINE];
    unsigned n;
    assert(pd2_metrics_first_present(1, 640, 480, line, sizeof(line)));
    assert(!strcmp(line, "{\"event\":3,\"backend\":1,\"frames\":1,\"duration_ms\":0,\"width\":640,\"height\":480}\n"));
    assert(!pd2_metrics_first_present(3, 640, 480, line, sizeof(line)));
    assert(!pd2_metrics_first_present(1, 0, 480, line, sizeof(line)));
    assert(!pd2_metrics_first_present(1, 640, 480, line, 1));
    assert(pd2_metrics_status(2, 640, 480, line, sizeof(line)));
    assert(!strcmp(line, "{\"event\":2,\"backend\":2,\"frames\":0,\"duration_ms\":0,\"width\":640,\"height\":480}\n"));
    assert(!pd2_metrics_status(0, 640, 480, line, sizeof(line)));
    assert(!pd2_metrics_status(1, 0, 480, line, sizeof(line)));
    assert(!pd2_metrics_status(1, 640, 480, line, 1));
    pd2_metrics_init(&m, 100, 1000, 1);
    assert(!pd2_metrics_frame(&m, 100, 1, 640, 480, line, sizeof(line)));
    assert(!pd2_metrics_frame(&m, 1099, 0, 640, 480, line, sizeof(line)));
    n = pd2_metrics_frame(&m, 1100, 1, 640, 480, line, sizeof(line));
    assert(n == strlen(line));
    assert(!strcmp(line, "{\"event\":1,\"backend\":1,\"frames\":2,\"duration_ms\":1000,\"width\":640,\"height\":480}\n"));
    assert(!pd2_metrics_frame(&m, 2099, 0, 640, 480, line, sizeof(line)));
    assert(pd2_metrics_frame(&m, 2600, 0, 640, 480, line, sizeof(line)));
    assert(strstr(line, "\"frames\":0,\"duration_ms\":1500"));
    assert(!pd2_metrics_frame(&m, 2000, 1, 640, 480, line, sizeof(line)));
    assert(!pd2_metrics_frame(&m, 3600, 1, 0, 480, line, sizeof(line)));
    pd2_metrics_init(&m, 0, 3579545, 2);
    assert(pd2_metrics_frame(&m, 5369317, 1, 800, 600, line, sizeof(line)));
    assert(strstr(line, "\"backend\":2,\"frames\":1,\"duration_ms\":1499"));
    pd2_metrics_init(&m, 0, 0, 1);
    assert(!pd2_metrics_frame(&m, 1000, 1, 640, 480, line, sizeof(line)));
    pd2_metrics_init(&m, 0, 1000000001, 1);
    assert(!pd2_metrics_frame(&m, UINT64_MAX, 1, 640, 480, line, sizeof(line)));
    pd2_metrics_init(&m, 0, 1000, 3);
    assert(!pd2_metrics_frame(&m, 1000, 1, 640, 480, line, sizeof(line)));
    pd2_metrics_init(&m, 0, 1000, 1);
    assert(!pd2_metrics_frame(&m, 1000, 1, 640, 480, line, 2));
    assert(!pd2_metrics_frame(&m, UINT64_MAX, 1, 640, 480, line, sizeof(line)));
    /* Budget can never cross limit: exercise the writer's subtraction guard. */
    {
        unsigned total = 0, records = 0;
        pd2_metrics_init(&m, 0, 1000, 2);
        for (;;) {
            n = pd2_metrics_frame(&m, (uint64_t)(records + 1) * 1000, 1, 640, 480, line, sizeof(line));
            assert(n && n < PD2_PRESENT_LINE);
            if (n > PD2_PRESENT_LIMIT - total) break;
            total += n;
            ++records;
        }
        assert(total <= PD2_PRESENT_LIMIT && PD2_PRESENT_LIMIT - total < n);
    }
#ifdef _WIN32
    /* No window or rendering required: exercise the real fixed-file writer. */
    pd2_present_start(1, 640, 480);
    assert(pd2_present_file != INVALID_HANDLE_VALUE);
    assert(pd2_present_bytes > 0);
    pd2_present_frame(1, 0, 640, 480);
    assert(pd2_present_seen == 0); /* Failed API calls cannot claim first present. */
    pd2_present_frame(1, 1, 640, 480);
    assert(pd2_present_seen == (1u << 1));
    pd2_present_start(1, 640, 480);
    assert(pd2_present_seen == (1u << 1)); /* Restart never resets process marker. */
    pd2_present_frame(1, 1, 640, 480);
    assert(pd2_present_seen == (1u << 1));
    pd2_present_start(2, 800, 600); /* Backend transition never resets budget. */
    pd2_present_frame(2, 1, 800, 600);
    assert(pd2_present_seen == ((1u << 1) | (1u << 2)));
    assert(pd2_present_bytes > 100);
    n = pd2_metrics_status(2, 800, 600, line, sizeof(line));
    while (!pd2_present_disabled) pd2_present_write(line, n);
    assert(pd2_present_bytes <= PD2_PRESENT_LIMIT);
    assert(PD2_PRESENT_LIMIT - pd2_present_bytes < n);
    assert(pd2_present_file == INVALID_HANDLE_VALUE);
    {
        FILE *stream = fopen("pd2-present.jsonl", "rb");
        unsigned first_records = 0;
        assert(stream);
        while (fgets(line, sizeof(line), stream)) {
            if (strstr(line, "\"event\":3")) {
                ++first_records;
                assert(strstr(line, "\"frames\":1,\"duration_ms\":0"));
            }
        }
        assert(!ferror(stream));
        fclose(stream);
        assert(first_records == 2); /* Exactly once for each backend, despite restart. */
    }
    {
        WIN32_FILE_ATTRIBUTE_DATA info;
        unsigned total = pd2_present_bytes;
        pd2_present_start(1, 640, 480);
        pd2_present_frame(1, 1, 640, 480);
        assert(pd2_present_bytes == total);
        assert(GetFileAttributesExW(L"pd2-present.jsonl", GetFileExInfoStandard, &info));
        assert(!info.nFileSizeHigh && info.nFileSizeLow == total);
        /* Simulate a new process; CREATE_NEW must refuse any existing file. */
        pd2_present_disabled = 0;
        pd2_present_start(1, 640, 480);
        assert(pd2_present_disabled);
        assert(pd2_present_file == INVALID_HANDLE_VALUE);
        assert(GetFileAttributesExW(L"pd2-present.jsonl", GetFileExInfoStandard, &info));
        assert(info.nFileSizeLow == total);
    }
#endif
    puts("present metrics native tests passed");
    return 0;
}

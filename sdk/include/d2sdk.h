#ifndef D2SDK_H
#define D2SDK_H
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif

typedef struct D2Device D2Device;
enum { D2_OK=0, D2_TIMEOUT=1, D2_INVALID=-1, D2_PERMISSION=-2, D2_ERROR=-3 };
enum { D2_IR=1, D2_DEPTH=3 };
enum { D2_DEPTH_MM=100, D2_DEPTH_100UM=101, D2_GRAY16=203 };
enum {
    D2_TIMESTAMP_UNVERIFIED=1, D2_TIMESTAMP_NONINCREASING=2,
    D2_COUNTER_NONINCREASING=4, D2_COUNTER_GAP=8, D2_IDENTICAL_CONTENT=16,
    D2_FIRST_EIGHT_DEPTH_SAMPLES_INVALID=32, D2_NATIVE_GRID_DIFFERS=64,
    D2_SOFTWARE_FILTER_DISABLED=128
};
typedef struct {
    int sensor, format;
    int width, height;          /* Actual output buffer coordinates. */
    int requested_width, requested_height;
    int reported_fps;           /* Driver declaration, not a measured/guaranteed rate. */
    int experimental;           /* High-resolution modes have unverified timing. */
} D2Mode;
typedef struct {
    const void *data;           /* Borrowed until next read of the same sensor or close. */
    size_t bytes;
    int sensor, format, width, height, stride;
    int requested_width, requested_height, reported_fps, mirroring;
    int frame_index;
    uint64_t sdk_timestamp_us;  /* May be device- or host-derived. Never used as exposure proof. */
    uint64_t host_received_ns;  /* CLOCK_MONOTONIC delivery time; not exposure time. */
    uint32_t flags;
} D2Frame;

/* One context per isolated process; calls from one thread. No service/config writes. */
int d2_open(D2Device **out);
void d2_close(D2Device *device);
const char *d2_error(const D2Device *device);
/* experimental!=0 includes HD5 and USB3-only HD30. IR60 is never offered. */
int d2_modes(D2Device *device, int sensor, int experimental, D2Mode *out, int capacity);
/* Configure before any start; dimensions use the actual output grid. */
int d2_configure(D2Device *device, int sensor, int format, int width, int height, int reported_fps);
int d2_start(D2Device *device);
int d2_read(D2Device *device, int timeout_ms, D2Frame *out);
/* Native factory 30-float structure; no assumed output-grid/IR/RGB registration. */
int d2_camera_parameters(D2Device *device, float out[30]);

#ifdef __cplusplus
}
#endif
#endif

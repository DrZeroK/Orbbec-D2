#ifndef D2_FRAME_INTERNAL_H
#define D2_FRAME_INTERNAL_H
#include "d2sdk.h"
#include <OniCAPI.h>
#include <algorithm>
#include <cstring>
#include <stdexcept>
#include <vector>

namespace d2_internal {
struct State {
    std::vector<uint8_t> pixels;
    bool seen=false;
    uint64_t timestamp=0;
    int index=0;
};
inline D2Frame copy_frame(const OniFrame &src, const D2Mode &mode, int mirror,
                          uint64_t host, State &state) {
    const int bpp=(src.videoMode.pixelFormat==ONI_PIXEL_FORMAT_GRAY16 || src.videoMode.pixelFormat==ONI_PIXEL_FORMAT_DEPTH_1_MM
        || src.videoMode.pixelFormat==ONI_PIXEL_FORMAT_DEPTH_100_UM) ? 2 : 0;
    if (!bpp || !src.data || src.sensorType!=mode.sensor || src.videoMode.pixelFormat!=mode.format
        || src.width!=mode.width || src.height!=mode.height || src.width<=0 || src.height<=0
        || src.videoMode.resolutionX!=src.width || src.videoMode.resolutionY!=src.height
        || src.width>4096 || src.height>4096 || src.stride<src.width*bpp || src.stride>32768
        || src.dataSize<0 || size_t(src.dataSize)<size_t(src.height)*src.stride
        || src.dataSize>64*1024*1024 || src.croppingEnabled || src.cropOriginX || src.cropOriginY || src.frameIndex<=0)
        throw std::runtime_error("unexpected D2 frame layout/crop/index");
    std::vector<uint8_t> pixels(size_t(src.width)*src.height*bpp);
    for (int y=0;y<src.height;++y)
        std::memcpy(pixels.data()+size_t(y)*src.width*bpp,
            static_cast<const uint8_t*>(src.data)+size_t(y)*src.stride,size_t(src.width)*bpp);
    uint32_t flags=D2_TIMESTAMP_UNVERIFIED;
    if (mode.sensor==D2_DEPTH) {
        // This driver overwrites the first 16 output bytes with original input bytes.
        std::fill_n(pixels.begin(),std::min(size_t(16),pixels.size()),0);
        flags|=D2_FIRST_EIGHT_DEPTH_SAMPLES_INVALID;
    }
    if (mode.width!=mode.requested_width || mode.height!=mode.requested_height)
        flags|=D2_NATIVE_GRID_DIFFERS;
    if(mode.sensor==D2_DEPTH&&mode.width==1280&&mode.height==800&&mode.reported_fps==30)
        flags|=D2_SOFTWARE_FILTER_DISABLED;
    if (state.seen) {
        if (src.timestamp<=state.timestamp) flags|=D2_TIMESTAMP_NONINCREASING;
        if (src.frameIndex<=state.index) flags|=D2_COUNTER_NONINCREASING;
        if (int64_t(src.frameIndex)>int64_t(state.index)+1) flags|=D2_COUNTER_GAP;
        if (pixels==state.pixels) flags|=D2_IDENTICAL_CONTENT;
    }
    state.pixels.swap(pixels);
    state.seen=true; state.timestamp=src.timestamp; state.index=src.frameIndex;
    D2Frame result{};
    result.data=state.pixels.data(); result.bytes=state.pixels.size();
    result.sensor=mode.sensor; result.format=mode.format;
    result.width=src.width; result.height=src.height; result.stride=src.width*bpp;
    result.requested_width=mode.requested_width; result.requested_height=mode.requested_height;
    result.reported_fps=src.videoMode.fps; result.mirroring=mirror;
    result.frame_index=src.frameIndex; result.sdk_timestamp_us=src.timestamp;
    result.host_received_ns=host; result.flags=flags;
    return result;
}
}
#endif

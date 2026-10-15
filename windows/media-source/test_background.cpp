#ifndef NOMINMAX
#define NOMINMAX
#endif
#include "D2Capture.h"
#include <atomic>
#include <thread>
#include <vector>
#include <cstdio>
#include <algorithm>
#include <cassert>
#include <string>

constexpr DWORD Pixels = 640 * 400;

struct PairReading {
    D2Capture::FrameInfo ambient, active;
    LONGLONG outputTime;
    double ambientMean, activeMean, backgroundMean;
};
struct RawReading {
    D2Capture::FrameInfo frame;
    LONGLONG qpc;
    int requestedState, getterState, inferredPreviousState;
    bool continuous;
    double mean;
};
struct Result {
    std::atomic<bool> done{false};
    std::atomic<UINT32> published{0};
    HRESULT status = E_FAIL;
    HRESULT restorationStatus = E_FAIL;
    int initialEmitter = -1, restoredEmitter = -1;
    UINT32 rawFrames = 0, rejectedPairs = 0, resyncs = 0, positiveSignalPairs = 0;
    LONGLONG firstRawTime = 0, lastRawTime = 0;
    std::vector<PairReading> readings;
    std::vector<RawReading> rawReadings;
    std::vector<BYTE> lastBackground;
};

double Mean(const std::vector<BYTE>& pixels) {
    unsigned long long sum = 0;
    for (BYTE pixel : pixels) sum += pixel;
    return static_cast<double>(sum) / pixels.size();
}
BYTE Subtract(BYTE active, BYTE ambient) {
    return static_cast<BYTE>(active > ambient ? active - ambient : 0);
}

HRESULT RunWorker(Result& result, UINT32 requestedPairs, bool stress, bool settled) {
    D2Capture capture;
    std::vector<BYTE> ambient(Pixels), active(Pixels), background(Pixels);
    HRESULT hr = capture.Start();
    if (FAILED(hr)) return hr;
    struct StopGuard { D2Capture* capture; ~StopGuard() { capture->Stop(); } } cleanup{&capture};
    hr = capture.GetEmitterState(&result.initialEmitter);
    if (FAILED(hr)) return hr;
    D2Capture::FrameInfo previous{};
    bool havePrevious = false;
    bool synchronized = false;
    bool gapInjected = false;
    unsigned randomState = 731u;
    int previousCommand = -1;
    auto read = [&](bool commandOn, std::vector<BYTE>& image, D2Capture::FrameInfo& info, LONGLONG& qpc, bool& continuous) -> HRESULT {
        if (stress) { randomState = randomState * 1664525u + 1013904223u; Sleep(randomState % 21); }
        HRESULT readHr = capture.SetEmitter(commandOn);
        if (FAILED(readHr)) return readHr;
        int currentState = -1;
        readHr = capture.GetEmitterState(&currentState);
        if (FAILED(readHr)) return readHr;
        if (currentState != static_cast<int>(commandOn)) return HRESULT_FROM_WIN32(ERROR_INVALID_DATA);
        readHr = capture.Read(image.data(), Pixels, &qpc, &info);
        if (FAILED(readHr)) return readHr;
        continuous = !havePrevious ||
            (info.index == previous.index + 1 && info.deviceTimestamp > previous.deviceTimestamp &&
             info.deviceTimestamp - previous.deviceTimestamp >= 20000 &&
             info.deviceTimestamp - previous.deviceTimestamp <= 50000);
        result.rawReadings.push_back({info, qpc, static_cast<int>(commandOn), currentState,
            continuous && havePrevious ? previousCommand : -1, continuous, Mean(image)});
        previousCommand = static_cast<int>(commandOn);
        previous = info;
        havePrevious = true;
        if (result.rawFrames++ == 0) result.firstRawTime = qpc;
        result.lastRawTime = qpc;
        return S_OK;
    };
    while (result.readings.size() < requestedPairs && result.rawFrames < requestedPairs * 4 + 120) {
        D2Capture::FrameInfo offInfo{}, onInfo{};
        LONGLONG offQpc = 0, onQpc = 0;
        bool continuous = false;
        if (!synchronized) {
            ++result.resyncs;
            // Hold OFF for two acquired frames before inferring the verified one-frame lag.
            hr = read(false, ambient, offInfo, offQpc, continuous);
            if (FAILED(hr)) return hr;
            hr = read(false, ambient, offInfo, offQpc, continuous);
            if (FAILED(hr)) return hr;
            if (!continuous) continue;
            synchronized = true;
        }
        if (stress && !gapInjected && result.readings.size() >= requestedPairs / 2) {
            Sleep(120);
            gapInjected = true;
        }
        double ambientMean = 0, activeMean = 0;
        if (settled) {
            hr = read(true, active, onInfo, onQpc, continuous); // discard transition frame
            if (FAILED(hr)) return hr;
            if (!continuous) { synchronized = false; ++result.rejectedPairs; continue; }
            hr = read(true, active, onInfo, onQpc, continuous);
            if (FAILED(hr)) return hr;
            if (!continuous) { synchronized = false; ++result.rejectedPairs; continue; }
            activeMean = result.rawReadings.back().mean;
            hr = read(false, ambient, offInfo, offQpc, continuous); // discard transition frame
            if (FAILED(hr)) return hr;
            if (!continuous) { synchronized = false; ++result.rejectedPairs; continue; }
            hr = read(false, ambient, offInfo, offQpc, continuous);
            if (FAILED(hr)) return hr;
            if (!continuous) { synchronized = false; ++result.rejectedPairs; continue; }
            ambientMean = result.rawReadings.back().mean;
        } else {
            // The returned frame is inferred to have the previous command's illumination.
            hr = read(true, ambient, offInfo, offQpc, continuous);
            if (FAILED(hr)) return hr;
            if (!continuous) { synchronized = false; ++result.rejectedPairs; continue; }
            ambientMean = result.rawReadings.back().mean;
            hr = read(false, active, onInfo, onQpc, continuous);
            if (FAILED(hr)) return hr;
            if (!continuous) { synchronized = false; ++result.rejectedPairs; continue; }
            activeMean = result.rawReadings.back().mean;
        }
        for (DWORD index = 0; index < Pixels; ++index) background[index] = Subtract(active[index], ambient[index]);
        PairReading reading{offInfo, onInfo, settled ? offQpc : onQpc, ambientMean, activeMean, Mean(background)};
        if (reading.activeMean > reading.ambientMean) ++result.positiveSignalPairs;
        result.readings.push_back(reading);
        result.lastBackground = background;
        result.published.store(static_cast<UINT32>(result.readings.size()), std::memory_order_release);
    }
    hr = capture.Stop();
    if (FAILED(hr)) return hr;
    return result.readings.size() == requestedPairs ? S_OK : HRESULT_FROM_WIN32(ERROR_TIMEOUT);
}

HRESULT Save(const Result& result, const std::wstring& prefix, bool settled) {
    FILE* csv = nullptr;
    if (_wfopen_s(&csv, (prefix + L".csv").c_str(), L"wb") || !csv) return HRESULT_FROM_WIN32(ERROR_OPEN_FAILED);
    bool okay = std::fprintf(csv, "pair,role_mapping,ambient_index,ambient_device_us,active_index,active_device_us,output_qpc100ns,ambient_mean,active_mean,bgs_mean\n") > 0;
    for (size_t index = 0; index < result.readings.size() && okay; ++index) {
        const auto& reading = result.readings[index];
        okay = std::fprintf(csv, "%zu,%s,%d,%llu,%d,%llu,%lld,%.6f,%.6f,%.6f\n",
            index + 1, settled ? "transition_frame_discarded" : "inferred_one_frame_lag", reading.ambient.index, reading.ambient.deviceTimestamp, reading.active.index,
            reading.active.deviceTimestamp, reading.outputTime, reading.ambientMean, reading.activeMean, reading.backgroundMean) > 0;
    }
    if (std::fclose(csv)) okay = false;
    if (!okay) return E_FAIL;
    FILE* raw = nullptr;
    if (_wfopen_s(&raw, (prefix + L"_raw.csv").c_str(), L"wb") || !raw) return HRESULT_FROM_WIN32(ERROR_OPEN_FAILED);
    okay = std::fprintf(raw, "frame_index,device_us,qpc100ns,requested_current_state,getter_current_state,inferred_prior_command_illumination,continuous,mean\n") > 0;
    for (const auto& reading : result.rawReadings) {
        if (!okay) break;
        okay = std::fprintf(raw, "%d,%llu,%lld,%d,%d,%d,%d,%.6f\n", reading.frame.index,
            reading.frame.deviceTimestamp, reading.qpc, reading.requestedState, reading.getterState,
            reading.inferredPreviousState, reading.continuous ? 1 : 0, reading.mean) > 0;
    }
    if (std::fclose(raw)) okay = false;
    if (!okay) return E_FAIL;
    if (!result.lastBackground.empty()) {
        FILE* image = nullptr;
        if (_wfopen_s(&image, (prefix + L".pgm").c_str(), L"wb") || !image) return HRESULT_FROM_WIN32(ERROR_OPEN_FAILED);
        okay = std::fprintf(image, "P5\n640 400\n255\n") > 0 &&
            std::fwrite(result.lastBackground.data(), 1, result.lastBackground.size(), image) == result.lastBackground.size();
        if (std::fclose(image)) okay = false;
        if (!okay) return E_FAIL;
    }
    return S_OK;
}

int wmain(int argc, wchar_t** argv) {
    UINT32 pairs = argc > 1 ? static_cast<UINT32>(_wtoi(argv[1])) : 300;
    if (pairs < 31 || pairs > 1000) return 2;
    bool stress = argc > 3 && wcscmp(argv[3], L"stress") == 0;
    bool settled = argc > 3 && wcscmp(argv[3], L"settled") == 0;
    assert(Subtract(20, 5) == 15 && Subtract(5, 20) == 0 && Subtract(255, 0) == 255);
    Result result;
    std::thread worker([&] {
        try { result.status = RunWorker(result, pairs, stress, settled); }
        catch (...) { result.status = E_FAIL; }
        D2Capture verification;
        result.restorationStatus = verification.Start();
        if (SUCCEEDED(result.restorationStatus)) result.restorationStatus = verification.GetEmitterState(&result.restoredEmitter);
        HRESULT stopHr = verification.Stop();
        if (FAILED(stopHr) && SUCCEEDED(result.restorationStatus)) result.restorationStatus = stopHr;
        if (SUCCEEDED(result.restorationStatus) && result.initialEmitter != result.restoredEmitter) result.restorationStatus = HRESULT_FROM_WIN32(ERROR_INVALID_DATA);
        if (FAILED(result.restorationStatus) && SUCCEEDED(result.status)) result.status = result.restorationStatus;
        result.done.store(true, std::memory_order_release);
    });
    UINT32 consumerSeen = 0, consumerDropped = 0;
    while (!result.done.load(std::memory_order_acquire)) {
        Sleep(120); // Consumer is deliberately slow; capture/control stays on the worker.
        UINT32 current = result.published.load(std::memory_order_acquire);
        if (current > consumerSeen + 1) consumerDropped += current - consumerSeen - 1;
        consumerSeen = current;
    }
    worker.join();
    double rawFps = result.rawFrames > 1 ? (result.rawFrames - 1) * 10000000.0 / (result.lastRawTime - result.firstRawTime) : 0;
    double fps = 0, lowest30IntervalFps = 0, largestGapMs = 0;
    if (result.readings.size() > 1) {
        fps = (result.readings.size() - 1) * 10000000.0 / (result.readings.back().outputTime - result.readings.front().outputTime);
        lowest30IntervalFps = fps;
        for (size_t index = 1; index < result.readings.size(); ++index) {
            largestGapMs = std::max(largestGapMs, (result.readings[index].outputTime - result.readings[index - 1].outputTime) / 10000.0);
            if (index >= 30) lowest30IntervalFps = std::min(lowest30IntervalFps,
                300000000.0 / (result.readings[index].outputTime - result.readings[index - 30].outputTime));
        }
    }
    std::printf("role_mapping=%s; no exposure metadata or Hello capability is claimed.\n",
        settled ? "transition_frame_discarded" : "inferred_one_frame_lag");
    std::printf("mode=%s\n", stress ? "random_0_20ms_control_delay_and_one_120ms_producer_gap" :
        settled ? "four_reads_two_toggles_per_output" : "continuous_worker_baseline");
    std::printf("initial_emitter=%d restored_emitter_after_stop_and_new_start=%d restoration_hr=0x%08lx\n",
        result.initialEmitter, result.restoredEmitter, static_cast<unsigned long>(result.restorationStatus));
    std::printf("raw_frames=%u raw_fps=%.6f bgs_pairs=%zu bgs_fps=%.6f minimum_30_interval_fps=%.6f largest_output_gap_ms=%.3f\n",
        result.rawFrames, rawFps, result.readings.size(), fps, lowest30IntervalFps, largestGapMs);
    std::printf("rejected_pairs=%u resyncs=%u positive_signal_pairs=%u consumer120ms_dropped_outputs=%u measured_15fps_lower_bound_met=%s\n",
        result.rejectedPairs, result.resyncs, result.positiveSignalPairs, consumerDropped, lowest30IntervalFps >= 15.0 ? "yes" : "no");
    HRESULT saveHr = Save(result, argc > 2 ? argv[2] : L"background_result", settled);
    if (FAILED(saveHr) && SUCCEEDED(result.status)) result.status = saveHr;
    std::printf("capture_pipeline_result=0x%08lx\n", static_cast<unsigned long>(result.status));
    std::printf("quality_route_verified=no; inferred pair roles are not validated exposure metadata.\n");
    return SUCCEEDED(result.status) ? 0 : 1;
}

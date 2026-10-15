#include "D2Capture.h"
#include <iostream>
#include <vector>
#include <numeric>
#include <chrono>
#include <algorithm>
#include <iomanip>

int main(int argc, char** argv) {
    bool delayed = argc == 2 && std::string(argv[1]) == "--lighting-delayed";
    bool stateTest = argc == 2 && std::string(argv[1]) == "--lighting-state";
    bool lighting = delayed || stateTest || (argc == 2 && std::string(argv[1]) == "--lighting");
    D2Capture capture;
    HRESULT hr = capture.Start();
    if (FAILED(hr)) { std::cerr << "Start HRESULT 0x" << std::hex << hr << '\n'; return 1; }
    std::vector<BYTE> pixels(640 * 400);
    LONGLONG previous = -1, timestamp = 0;
    auto started = std::chrono::steady_clock::now();
    std::cout << "frame,emitter_requested,mean_l8,p90_l8,qpc100ns,control_ms,sdk_frame,sdk_timestamp_us\n";
    for (int n = 0; n < (lighting ? 120 : 60); ++n) {
        bool enabled = stateTest ? (n / 30) % 2 == 0 : n % 2 == 0;
        if (delayed && n > 0 && n % 30 == 0) Sleep(120);
        auto controlStart = std::chrono::steady_clock::now();
        if (lighting && FAILED(hr = capture.SetEmitter(enabled))) {
            std::cerr << "Emitter unsupported HRESULT 0x" << std::hex << hr << '\n';
            return 2;
        }
        double controlMs = std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-controlStart).count();
        D2Capture::FrameInfo info{};
        hr = capture.Read(pixels.data(), static_cast<DWORD>(pixels.size()), &timestamp, &info);
        if (FAILED(hr) || timestamp <= previous) { std::cerr << "Read failed / invalid timestamp\n"; return 3; }
        previous = timestamp;
        if (stateTest && n % 30 == 29) {
            int state = -1;
            if (FAILED(capture.GetEmitterState(&state))) return 5;
            std::cerr << "requested=" << enabled << " public_state=" << state << '\n';
            if (state != static_cast<int>(enabled)) return 6;
        }
        double mean = std::accumulate(pixels.begin(), pixels.end(), 0.0) / pixels.size();
        auto sorted = pixels;
        std::nth_element(sorted.begin(), sorted.begin()+sorted.size()*9/10, sorted.end());
        std::cout << n << ',' << (lighting ? (enabled ? 1 : 0) : -1) << ',' << mean << ','
                  << static_cast<int>(sorted[sorted.size()*9/10]) << ',' << timestamp << ',' << controlMs << ',' << info.index << ',' << info.deviceTimestamp << '\n';
    }
    hr = capture.Stop();
    if (FAILED(hr)) { std::cerr << "Emitter restore/readback failed\n"; return 4; }
    std::cerr << "elapsed_s=" << std::chrono::duration<double>(std::chrono::steady_clock::now()-started).count() << '\n';
    return 0;
}

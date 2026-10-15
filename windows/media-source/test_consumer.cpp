#include "D2MediaSource.h"
#include <mfapi.h>
#include <mferror.h>
#include <ks.h>
#include <ksmedia.h>
#include <ksproxy.h>
#include <wrl.h>
#include <cstdio>
#include <vector>
#include <algorithm>

using Microsoft::WRL::ComPtr;
using Factory = HRESULT (__stdcall*)(REFIID, void**);

#define CHECK_HR(expr) do { HRESULT testHr = (expr); if (FAILED(testHr)) { std::fprintf(stderr, "%s failed: 0x%08lx\n", #expr, static_cast<unsigned long>(testHr)); return testHr; } } while (0)
#define CHECK_TRUE(expr) do { if (!(expr)) { std::fprintf(stderr, "check failed: %s\n", #expr); return E_FAIL; } } while (0)

HRESULT WaitEvent(IMFMediaEventGenerator* generator, MediaEventType expected, IMFMediaEvent** output = nullptr) {
    ULONGLONG deadline = GetTickCount64() + 10000;
    while (GetTickCount64() < deadline) {
        ComPtr<IMFMediaEvent> event;
        HRESULT hr = generator->GetEvent(MF_EVENT_FLAG_NO_WAIT, &event);
        if (hr == MF_E_NO_EVENTS_AVAILABLE) { Sleep(2); continue; }
        CHECK_HR(hr);
        HRESULT status = E_FAIL;
        CHECK_HR(event->GetStatus(&status));
        CHECK_HR(status);
        MediaEventType type = MEUnknown;
        CHECK_HR(event->GetType(&type));
        if (type == expected) return output ? event.CopyTo(output) : S_OK;
        std::fprintf(stderr, "unexpected event: %d, expected: %d\n", type, expected);
        return E_UNEXPECTED;
    }
    return HRESULT_FROM_WIN32(WAIT_TIMEOUT);
}

HRESULT CheckBusySource(Factory factory) {
    ComPtr<IMFMediaSource> second;
    CHECK_HR(factory(__uuidof(IMFMediaSource), reinterpret_cast<void**>(second.GetAddressOf())));
    struct ShutdownGuard {
        IMFMediaSource* source;
        ~ShutdownGuard() { source->Shutdown(); }
    } cleanup{second.Get()};
    ComPtr<IMFPresentationDescriptor> descriptor;
    CHECK_HR(second->CreatePresentationDescriptor(&descriptor));
    PROPVARIANT position = {};
    position.vt = VT_EMPTY;
    HRESULT startHr = second->Start(descriptor.Get(), nullptr, &position);
    std::printf("second_source_start=0x%08lx expected_busy=0x%08lx\n",
        static_cast<unsigned long>(startHr), static_cast<unsigned long>(HRESULT_FROM_WIN32(ERROR_BUSY)));
    CHECK_TRUE(startHr == HRESULT_FROM_WIN32(ERROR_BUSY));
    CHECK_HR(second->Shutdown());
    return S_OK;
}

HRESULT RunTest(IMFMediaSource* source, Factory factory, UINT32 frames, const wchar_t* outputPath) {
    ComPtr<IMarshal> sourceMarshal;
    CHECK_HR(source->QueryInterface(IID_PPV_ARGS(&sourceMarshal)));
    ComPtr<IMFSampleAllocatorControl> allocatorControl;
    CHECK_HR(source->QueryInterface(IID_PPV_ARGS(&allocatorControl)));
    DWORD inputId = ~0u;
    MFSampleAllocatorUsage allocation = MFSampleAllocatorUsage_DoesNotAllocate;
    CHECK_HR(allocatorControl->GetAllocatorUsage(0, &inputId, &allocation));
    CHECK_TRUE(allocation == MFSampleAllocatorUsage_UsesCustomAllocator);
    CHECK_TRUE(allocatorControl->GetAllocatorUsage(1, &inputId, &allocation) == MF_E_INVALIDSTREAMNUMBER);
    CHECK_TRUE(allocatorControl->GetAllocatorUsage(0, nullptr, &allocation) == E_POINTER);
    std::printf("source IMarshal and explicit custom sample allocation: passed\n");
    ComPtr<IMFMediaSourceEx> sourceEx;
    CHECK_HR(source->QueryInterface(IID_PPV_ARGS(&sourceEx)));
    ComPtr<IMFAttributes> attributes;
    CHECK_HR(sourceEx->GetStreamAttributes(0, &attributes));
    UINT32 frameType = 0;
    CHECK_HR(attributes->GetUINT32(MF_DEVICESTREAM_ATTRIBUTE_FRAMESOURCE_TYPES, &frameType));
    CHECK_TRUE(frameType == MFFrameSourceTypes_Infrared);
    UINT64 capability = ~0ull;
    CHECK_TRUE(attributes->GetUINT64(MF_DEVICESTREAM_ATTRIBUTE_FACEAUTH_CAPABILITY, &capability) == MF_E_ATTRIBUTENOTFOUND);
    ComPtr<IKsControl> control;
    CHECK_HR(source->QueryInterface(IID_PPV_ARGS(&control)));
    KSPROPERTY property = {KSPROPERTYSETID_ExtendedCameraControl, KSPROPERTY_CAMERACONTROL_EXTENDED_FACEAUTH_MODE, KSPROPERTY_TYPE_GET};
    ULONG returned = ~0u;
    CHECK_TRUE(control->KsProperty(&property, sizeof(property), nullptr, 0, &returned) == HRESULT_FROM_WIN32(ERROR_SET_NOT_FOUND));
    CHECK_TRUE(returned == 0);
    std::printf("IR attributes correct; unverified Hello mode explicitly unavailable.\n");

    std::vector<BYTE> lastFrame;
    for (unsigned cycle = 0; cycle < 2; ++cycle) {
        ComPtr<IMFPresentationDescriptor> descriptor;
        CHECK_HR(source->CreatePresentationDescriptor(&descriptor));
        PROPVARIANT position = {};
        position.vt = VT_EMPTY;
        LONGLONG startTime = MFGetSystemTime();
        CHECK_HR(source->Start(descriptor.Get(), nullptr, &position));
        ComPtr<IMFMediaEvent> streamEvent;
        CHECK_HR(WaitEvent(source, cycle == 0 ? MENewStream : MEUpdatedStream, &streamEvent));
        PROPVARIANT streamValue = {};
        CHECK_HR(streamEvent->GetValue(&streamValue));
        ComPtr<IMFMediaStream2> stream;
        HRESULT streamHr = streamValue.vt == VT_UNKNOWN && streamValue.punkVal ? streamValue.punkVal->QueryInterface(IID_PPV_ARGS(&stream)) : E_UNEXPECTED;
        PropVariantClear(&streamValue);
        CHECK_HR(streamHr);
        ComPtr<IMarshal> streamMarshal;
        CHECK_HR(stream->QueryInterface(IID_PPV_ARGS(&streamMarshal)));
        CHECK_HR(WaitEvent(source, MESourceStarted));
        CHECK_HR(WaitEvent(stream.Get(), MEStreamStarted));
        MF_STREAM_STATE state = MF_STREAM_STATE_STOPPED;
        CHECK_HR(stream->GetStreamState(&state));
        CHECK_TRUE(state == MF_STREAM_STATE_RUNNING);
        UINT32 count = cycle == 0 ? frames : 5;
        LONGLONG previous = -1, first = -1;
        ULONGLONG started = GetTickCount64();
        for (UINT32 index = 0; index < count; ++index) {
            CHECK_HR(stream->RequestSample(nullptr));
            ComPtr<IMFMediaEvent> sampleEvent;
            CHECK_HR(WaitEvent(stream.Get(), MEMediaSample, &sampleEvent));
            PROPVARIANT sampleValue = {};
            CHECK_HR(sampleEvent->GetValue(&sampleValue));
            ComPtr<IMFSample> sample;
            HRESULT sampleHr = sampleValue.vt == VT_UNKNOWN && sampleValue.punkVal ? sampleValue.punkVal->QueryInterface(IID_PPV_ARGS(&sample)) : E_UNEXPECTED;
            PropVariantClear(&sampleValue);
            CHECK_HR(sampleHr);
            LONGLONG time = 0, duration = 0;
            CHECK_HR(sample->GetSampleTime(&time));
            CHECK_HR(sample->GetSampleDuration(&duration));
            CHECK_TRUE(time > previous && duration == 333333);
            previous = time;
            if (first < 0) first = time;
            CHECK_TRUE(llabs(MFGetSystemTime() - time) < 20000000);
            ComPtr<IMFMediaBuffer> buffer;
            CHECK_HR(sample->ConvertToContiguousBuffer(&buffer));
            BYTE* bytes = nullptr;
            DWORD length = 0;
            CHECK_HR(buffer->Lock(&bytes, nullptr, &length));
            if (length != 640 * 400) { buffer->Unlock(); return E_FAIL; }
            lastFrame.assign(bytes, bytes + length);
            CHECK_HR(buffer->Unlock());
            if (index == 0) {
                double firstFrameMs = (MFGetSystemTime() - startTime) / 10000.0;
                std::printf("cycle=%u start_to_first_frame_ms=%.3f hello_under_500ms=%s\n",
                    cycle, firstFrameMs, firstFrameMs < 500.0 ? "yes" : "no");
                if (cycle == 0) CHECK_HR(CheckBusySource(factory));
            }
            if (cycle == 0 && index == 1) std::printf("first_source_survived_second_source_shutdown=yes\n");
            if (index == 0 || index + 1 == count) {
                auto range = std::minmax_element(lastFrame.begin(), lastFrame.end());
                std::printf("cycle=%u frame=%u bytes=%lu range=%u..%u qpc100ns=%lld\n", cycle, index + 1, length, *range.first, *range.second, time);
            }
        }
        std::printf("cycle=%u frames=%u elapsed_ms=%llu timestamp_fps=%.3f\n", cycle, count, GetTickCount64() - started, (count - 1) * 10000000.0 / (previous - first));
        CHECK_HR(source->Stop());
        CHECK_HR(WaitEvent(source, MESourceStopped));
        CHECK_HR(WaitEvent(stream.Get(), MEStreamStopped));
        CHECK_HR(stream->GetStreamState(&state));
        CHECK_TRUE(state == MF_STREAM_STATE_STOPPED);
        CHECK_TRUE(stream->RequestSample(nullptr) == MF_E_INVALIDREQUEST);
    }
    if (outputPath) {
        FILE* file = nullptr;
        if (_wfopen_s(&file, outputPath, L"wb") != 0 || !file) return HRESULT_FROM_WIN32(ERROR_OPEN_FAILED);
        bool okay = std::fprintf(file, "P5\n640 400\n255\n") > 0 && std::fwrite(lastFrame.data(), 1, lastFrame.size(), file) == lastFrame.size();
        if (std::fclose(file) != 0) okay = false;
        CHECK_TRUE(okay);
    }
    CHECK_HR(source->Shutdown());
    DWORD characteristics = 0;
    CHECK_TRUE(source->GetCharacteristics(&characteristics) == MF_E_SHUTDOWN);
    return S_OK;
}

int wmain(int argc, wchar_t** argv) {
    UINT32 frames = argc > 2 ? static_cast<UINT32>(_wtoi(argv[2])) : 90;
    if (argc < 2 || frames < 2 || frames > 1000) { std::fprintf(stderr, "Usage: test_consumer.exe D2MediaSource.dll [frames=90] [output.pgm]\n"); return 2; }
    HRESULT hr = CoInitializeEx(nullptr, COINIT_MULTITHREADED);
    if (FAILED(hr)) return 3;
    hr = MFStartup(MF_VERSION);
    HMODULE module = nullptr;
    Factory factory = nullptr;
    ComPtr<IMFMediaSource> source;
    if (SUCCEEDED(hr)) {
        DWORD needed = GetFullPathNameW(argv[1], 0, nullptr, nullptr);
        if (!needed) hr = HRESULT_FROM_WIN32(GetLastError());
        else {
            std::vector<wchar_t> absolutePath(needed);
            DWORD copied = GetFullPathNameW(argv[1], needed, absolutePath.data(), nullptr);
            if (!copied) hr = HRESULT_FROM_WIN32(GetLastError());
            else if (copied >= needed) hr = HRESULT_FROM_WIN32(ERROR_INSUFFICIENT_BUFFER);
            else {
                module = LoadLibraryExW(absolutePath.data(), nullptr, LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_DEFAULT_DIRS);
                if (!module) hr = HRESULT_FROM_WIN32(GetLastError());
            }
        }
    }
    if (SUCCEEDED(hr)) {
        factory = reinterpret_cast<Factory>(GetProcAddress(module, "CreateD2MediaSource"));
        hr = factory ? factory(__uuidof(IMFMediaSource), reinterpret_cast<void**>(source.GetAddressOf())) : E_NOINTERFACE;
    }
    if (SUCCEEDED(hr)) hr = RunTest(source.Get(), factory, frames, argc > 3 ? argv[3] : nullptr);
    if (source) { source->Shutdown(); source.Reset(); }
    if (module) {
        auto canUnload = reinterpret_cast<HRESULT (__stdcall*)()>(GetProcAddress(module, "DllCanUnloadNow"));
        bool unloadable = canUnload && canUnload() == S_OK;
        std::printf("COM objects released=%s\n", unloadable ? "yes" : "no");
        if (unloadable) FreeLibrary(module);
        else if (SUCCEEDED(hr)) hr = E_UNEXPECTED;
    }
    MFShutdown();
    CoUninitialize();
    std::printf("result=0x%08lx\n", static_cast<unsigned long>(hr));
    return SUCCEEDED(hr) ? 0 : 1;
}

#include <windows.h>
#include <mfapi.h>
#include <mfidl.h>
#include <mferror.h>
#include <mfreadwrite.h>
#include <wrl.h>
#include <cstdio>

using Microsoft::WRL::ComPtr;
using Factory = HRESULT (__stdcall*)(REFIID, void**);

HRESULT ReadSource(IMFMediaSource* source) {
    ComPtr<IMFSourceReader> reader;
    HRESULT hr = MFCreateSourceReaderFromMediaSource(source, nullptr, &reader);
    std::printf("direct source reader create=0x%08lx\n", static_cast<unsigned long>(hr));
    if (FAILED(hr)) return hr;
    for (UINT32 index = 0; index < 30; ++index) {
        ComPtr<IMFSample> sample;
        DWORD stream = 0, flags = 0;
        LONGLONG time = 0;
        hr = reader->ReadSample(MF_SOURCE_READER_FIRST_VIDEO_STREAM, 0, &stream, &flags, &time, &sample);
        std::printf("direct source reader frame=%u hr=0x%08lx stream=%lu flags=0x%lx sample=%d time=%lld\n",
            index + 1, static_cast<unsigned long>(hr), stream, flags, sample ? 1 : 0, time);
        if (FAILED(hr)) return hr;
        if (!sample) return E_FAIL;
        DWORD bytes = 0;
        hr = sample->GetTotalLength(&bytes);
        if (FAILED(hr)) return hr;
        if (bytes != 640 * 400) return E_FAIL;
    }
    return S_OK;
}

int wmain(int argc, wchar_t** argv) {
    if (argc != 2) return 2;
    HRESULT hr = CoInitializeEx(nullptr, COINIT_MULTITHREADED);
    if (FAILED(hr)) return 3;
    hr = MFStartup(MF_VERSION);
    HMODULE module = SUCCEEDED(hr) ? LoadLibraryW(argv[1]) : nullptr;
    if (SUCCEEDED(hr) && !module) hr = HRESULT_FROM_WIN32(GetLastError());
    ComPtr<IMFMediaSource> source;
    if (SUCCEEDED(hr)) {
        auto factory = reinterpret_cast<Factory>(GetProcAddress(module, "CreateD2MediaSource"));
        hr = factory ? factory(__uuidof(IMFMediaSource), reinterpret_cast<void**>(source.GetAddressOf())) : E_NOINTERFACE;
    }
    if (SUCCEEDED(hr)) hr = ReadSource(source.Get());
    if (source) { source->Shutdown(); source.Reset(); }
    if (module) {
        auto canUnload = reinterpret_cast<HRESULT (__stdcall*)()>(GetProcAddress(module, "DllCanUnloadNow"));
        if (canUnload && canUnload() == S_OK) FreeLibrary(module);
        else if (SUCCEEDED(hr)) hr = E_UNEXPECTED;
    }
    MFShutdown();
    CoUninitialize();
    std::printf("direct_source_reader_result=0x%08lx\n", static_cast<unsigned long>(hr));
    return SUCCEEDED(hr) ? 0 : 1;
}

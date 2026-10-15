#include <windows.h>
#include <mfapi.h>
#include <mfidl.h>
#include <mfvirtualcamera.h>
#include <ks.h>
#include <ksmedia.h>
#include <wrl.h>
#include <cstdio>
#include <mfreadwrite.h>
#include <string>

HRESULT ReadRegisteredCamera() {
    Microsoft::WRL::ComPtr<IMFAttributes> attributes;
    HRESULT hr = MFCreateAttributes(&attributes, 2);
    if (FAILED(hr)) return hr;
    hr = attributes->SetGUID(MF_DEVSOURCE_ATTRIBUTE_SOURCE_TYPE, MF_DEVSOURCE_ATTRIBUTE_SOURCE_TYPE_VIDCAP_GUID);
    if (FAILED(hr)) return hr;
    hr = attributes->SetGUID(MF_DEVSOURCE_ATTRIBUTE_SOURCE_TYPE_VIDCAP_CATEGORY, KSCATEGORY_SENSOR_CAMERA);
    if (FAILED(hr)) return hr;
    IMFActivate** devices = nullptr;
    UINT32 count = 0;
    hr = MFEnumDeviceSources(attributes.Get(), &devices, &count);
    if (FAILED(hr)) return hr;
    Microsoft::WRL::ComPtr<IMFMediaSource> source;
    for (UINT32 i = 0; i < count; ++i) {
        WCHAR* name = nullptr;
        UINT32 length = 0;
        if (SUCCEEDED(devices[i]->GetAllocatedString(MF_DEVSOURCE_ATTRIBUTE_FRIENDLY_NAME, &name, &length))) {
            if (std::wstring(name).find(L"D2 Infrared Research Source") != std::wstring::npos)
                { hr = devices[i]->ActivateObject(IID_PPV_ARGS(&source)); std::printf("sensor activate=0x%08lx\n", static_cast<unsigned long>(hr)); }
            CoTaskMemFree(name);
        }
        devices[i]->Release();
    }
    CoTaskMemFree(devices);
    if (!source) return HRESULT_FROM_WIN32(ERROR_NOT_FOUND);
    Microsoft::WRL::ComPtr<IMFSourceReader> reader;
    hr = MFCreateSourceReaderFromMediaSource(source.Get(), nullptr, &reader);
    std::printf("sensor source reader create=0x%08lx\n", static_cast<unsigned long>(hr));
    if (SUCCEEDED(hr)) {
        bool received = false;
        ULONGLONG deadline = GetTickCount64() + 10000;
        for (int attempt = 0; attempt < 100 && GetTickCount64() < deadline; ++attempt) {
            Microsoft::WRL::ComPtr<IMFSample> sample;
            DWORD flags = 0;
            hr = reader->ReadSample(MF_SOURCE_READER_FIRST_VIDEO_STREAM, 0, nullptr, &flags, nullptr, &sample);
            std::printf("sensor source reader read=0x%08lx flags=0x%lx sample=%d\n", static_cast<unsigned long>(hr), flags, sample ? 1 : 0);
            if (FAILED(hr) || (flags & (MF_SOURCE_READERF_ERROR | MF_SOURCE_READERF_ENDOFSTREAM))) break;
            if (!sample) continue; // Live Frame Server may emit STREAMTICK before the first sample.
            DWORD bytes = 0;
            hr = sample->GetTotalLength(&bytes);
            std::printf("registered sensor camera sample bytes=%lu flags=0x%lx\n", bytes, flags);
            if (SUCCEEDED(hr) && bytes != 640 * 400) hr = E_FAIL;
            received = SUCCEEDED(hr);
            break;
        }
        if (!received && SUCCEEDED(hr)) hr = HRESULT_FROM_WIN32(WAIT_TIMEOUT);
    }
    reader.Reset();
    source->Shutdown();
    return hr;
}

// Requires prior trusted COM/package registration; this tool does not register a DLL.
int wmain(int argc, wchar_t** argv) {
    const wchar_t* sourceId = argc > 1 ? argv[1] : L"{265E13EF-0B32-4E1D-8A91-CFD17143D89C}";
    UINT32 seconds = argc > 2 ? static_cast<UINT32>(_wtoi(argv[2])) : 30;
    if (seconds < 1 || seconds > 600) return 2;
    HRESULT hr = CoInitializeEx(nullptr, COINIT_MULTITHREADED);
    if (FAILED(hr)) return 3;
    hr = MFStartup(MF_VERSION);
    Microsoft::WRL::ComPtr<IMFVirtualCamera> camera;
    const GUID categories[] = {KSCATEGORY_VIDEO_CAMERA, KSCATEGORY_SENSOR_CAMERA};
    if (SUCCEEDED(hr)) hr = MFCreateVirtualCamera(MFVirtualCameraType_SoftwareCameraSource,
        MFVirtualCameraLifetime_Session, MFVirtualCameraAccess_CurrentUser,
        L"D2 Infrared Research Source", sourceId, categories, ARRAYSIZE(categories), &camera);
    if (SUCCEEDED(hr)) hr = camera->Start(nullptr);
    std::printf("virtual camera start=0x%08lx; no Hello capability is advertised.\n", static_cast<unsigned long>(hr));
    if (SUCCEEDED(hr)) {
        HRESULT captureHr = ReadRegisteredCamera();
        std::printf("registered camera capture=0x%08lx\n", static_cast<unsigned long>(captureHr));
        Sleep(seconds * 1000);
        HRESULT removeHr = camera->Remove();
        std::printf("virtual camera remove=0x%08lx\n", static_cast<unsigned long>(removeHr));
        if (FAILED(removeHr)) hr = removeHr;
        else if (FAILED(captureHr)) hr = captureHr;
    }
    if (camera) camera->Shutdown();
    camera.Reset();
    MFShutdown();
    CoUninitialize();
    return SUCCEEDED(hr) ? 0 : 1;
}

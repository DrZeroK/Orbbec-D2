#include "D2MediaSource.h"
#include <mfapi.h>
#include <mferror.h>
#include <wrl.h>
#include <cstdio>

using Microsoft::WRL::ComPtr;
using GetClassObject = HRESULT (__stdcall*)(REFCLSID, REFIID, void**);
#define CHECK(expr) do { HRESULT hr = (expr); if (FAILED(hr)) { std::fprintf(stderr, "%s = 0x%08lx\n", #expr, static_cast<unsigned long>(hr)); return hr; } } while (0)
#define EXPECT(expr) do { if (!(expr)) { std::fprintf(stderr, "failed: %s\n", #expr); return E_FAIL; } } while (0)

HRESULT Test(HMODULE module) {
    auto getClass = reinterpret_cast<GetClassObject>(GetProcAddress(module, "DllGetClassObject"));
    EXPECT(getClass != nullptr);
    ComPtr<IClassFactory> factory;
    CHECK(getClass(CLSID_D2MediaSource, __uuidof(IClassFactory), reinterpret_cast<void**>(factory.GetAddressOf())));
    ComPtr<IMFActivate> activate;
    CHECK(factory->CreateInstance(nullptr, __uuidof(IMFActivate), reinterpret_cast<void**>(activate.GetAddressOf())));
    ComPtr<IMFAttributes> attributes;
    ComPtr<IMarshal> marshal;
    CHECK(activate.As(&attributes));
    CHECK(activate.As(&marshal));
    CHECK(attributes->SetString(MF_DEVSOURCE_ATTRIBUTE_FRIENDLY_NAME, L"D2 activation test"));
    ComPtr<IMFMediaSourceEx> source;
    CHECK(activate->ActivateObject(__uuidof(IMFMediaSourceEx), reinterpret_cast<void**>(source.GetAddressOf())));
    struct Cleanup { IMFMediaSource* source; ~Cleanup() { source->Shutdown(); } } cleanup{source.Get()};
    ComPtr<IMFMediaSource> secondReference;
    CHECK(activate->ActivateObject(__uuidof(IMFMediaSource), reinterpret_cast<void**>(secondReference.GetAddressOf())));
    ComPtr<IUnknown> firstIdentity, secondIdentity;
    CHECK(source.As(&firstIdentity));
    CHECK(secondReference.As(&secondIdentity));
    EXPECT(firstIdentity.Get() == secondIdentity.Get());
    ComPtr<IMFAttributes> sourceAttributes;
    CHECK(source->GetSourceAttributes(&sourceAttributes));
    WCHAR name[64]{};
    CHECK(sourceAttributes->GetString(MF_DEVSOURCE_ATTRIBUTE_FRIENDLY_NAME, name, ARRAYSIZE(name), nullptr));
    EXPECT(wcscmp(name, L"D2 activation test") == 0);
    ComPtr<IMFAttributes> streamAttributes;
    CHECK(source->GetStreamAttributes(0, &streamAttributes));
    UINT64 capability = 0;
    EXPECT(streamAttributes->GetUINT64(MF_DEVICESTREAM_ATTRIBUTE_FACEAUTH_CAPABILITY, &capability) == MF_E_ATTRIBUTENOTFOUND);
    EXPECT(activate->ShutdownObject() == E_NOTIMPL);
    EXPECT(activate->DetachObject() == E_NOTIMPL);
    attributes.Reset();
    marshal.Reset();
    activate.Reset();
    DWORD characteristics = 0;
    CHECK(source->GetCharacteristics(&characteristics));
    EXPECT((characteristics & MFMEDIASOURCE_IS_LIVE) != 0);
    std::printf("IMFActivate, IMFAttributes, IMarshal, cached identity, copied attributes, no Hello capability, source alive after activator release: passed\n");
    return S_OK;
}

int wmain(int argc, wchar_t** argv) {
    if (argc != 2) return 2;
    HRESULT hr = CoInitializeEx(nullptr, COINIT_MULTITHREADED);
    if (FAILED(hr)) return 3;
    hr = MFStartup(MF_VERSION);
    HMODULE module = SUCCEEDED(hr) ? LoadLibraryW(argv[1]) : nullptr;
    if (SUCCEEDED(hr) && !module) hr = HRESULT_FROM_WIN32(GetLastError());
    if (SUCCEEDED(hr)) hr = Test(module);
    if (module) {
        auto canUnload = reinterpret_cast<HRESULT (__stdcall*)()>(GetProcAddress(module, "DllCanUnloadNow"));
        if (canUnload && canUnload() == S_OK) FreeLibrary(module);
        else if (SUCCEEDED(hr)) hr = E_UNEXPECTED;
    }
    MFShutdown();
    CoUninitialize();
    std::printf("activation_result=0x%08lx\n", static_cast<unsigned long>(hr));
    return SUCCEEDED(hr) ? 0 : 1;
}

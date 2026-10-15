#include "D2MediaSource.h"
#include <mfapi.h>
#include <wrl.h>
#include <mutex>

using namespace Microsoft::WRL;

class D2Activate final : public RuntimeClass<RuntimeClassFlags<ClassicCom>,
    ChainInterfaces<IMFActivate, IMFAttributes>, FtmBase> {
public:
    D2Activate() { InterlockedIncrement(&D2ModuleObjects); }
    ~D2Activate() {
        // A successfully returned source belongs to its caller, which shuts it down.
        if (m_source && !m_handedOut) m_source->Shutdown();
        InterlockedDecrement(&D2ModuleObjects);
    }
    HRESULT Initialize() { return MFCreateAttributes(&m_attributes, 4); }

    STDMETHODIMP ActivateObject(REFIID iid, void** result) override {
        if (!result) return E_POINTER;
        *result = nullptr;
        std::lock_guard<std::mutex> lock(m_mutex);
        if (!m_source) {
            HRESULT hr = CreateD2MediaSource(__uuidof(IMFMediaSourceEx), reinterpret_cast<void**>(m_source.GetAddressOf()));
            if (FAILED(hr)) return hr;
            ComPtr<IMFAttributes> sourceAttributes;
            hr = m_source->GetSourceAttributes(&sourceAttributes);
            if (SUCCEEDED(hr)) hr = m_attributes->CopyAllItems(sourceAttributes.Get());
            if (FAILED(hr)) { m_source->Shutdown(); m_source.Reset(); return hr; }
        }
        HRESULT hr = m_source.CopyTo(iid, result);
        if (SUCCEEDED(hr)) m_handedOut = true;
        return hr;
    }
    // Frame Server custom-source IMFActivate does not support these operations.
    STDMETHODIMP ShutdownObject() override { return E_NOTIMPL; }
    STDMETHODIMP DetachObject() override { return E_NOTIMPL; }

    STDMETHODIMP GetItem(REFGUID key, PROPVARIANT* item) override { return m_attributes->GetItem(key, item); }
    STDMETHODIMP GetItemType(REFGUID key, MF_ATTRIBUTE_TYPE* type) override { return m_attributes->GetItemType(key, type); }
    STDMETHODIMP CompareItem(REFGUID key, REFPROPVARIANT item, BOOL* equal) override { return m_attributes->CompareItem(key, item, equal); }
    STDMETHODIMP Compare(IMFAttributes* theirs, MF_ATTRIBUTES_MATCH_TYPE type, BOOL* equal) override { return m_attributes->Compare(theirs, type, equal); }
    STDMETHODIMP GetUINT32(REFGUID key, UINT32* item) override { return m_attributes->GetUINT32(key, item); }
    STDMETHODIMP GetUINT64(REFGUID key, UINT64* item) override { return m_attributes->GetUINT64(key, item); }
    STDMETHODIMP GetDouble(REFGUID key, double* item) override { return m_attributes->GetDouble(key, item); }
    STDMETHODIMP GetGUID(REFGUID key, GUID* item) override { return m_attributes->GetGUID(key, item); }
    STDMETHODIMP GetStringLength(REFGUID key, UINT32* length) override { return m_attributes->GetStringLength(key, length); }
    STDMETHODIMP GetString(REFGUID key, LPWSTR text, UINT32 capacity, UINT32* length) override { return m_attributes->GetString(key, text, capacity, length); }
    STDMETHODIMP GetAllocatedString(REFGUID key, LPWSTR* text, UINT32* length) override { return m_attributes->GetAllocatedString(key, text, length); }
    STDMETHODIMP GetBlobSize(REFGUID key, UINT32* length) override { return m_attributes->GetBlobSize(key, length); }
    STDMETHODIMP GetBlob(REFGUID key, UINT8* bytes, UINT32 capacity, UINT32* length) override { return m_attributes->GetBlob(key, bytes, capacity, length); }
    STDMETHODIMP GetAllocatedBlob(REFGUID key, UINT8** bytes, UINT32* length) override { return m_attributes->GetAllocatedBlob(key, bytes, length); }
    STDMETHODIMP GetUnknown(REFGUID key, REFIID iid, void** object) override { return m_attributes->GetUnknown(key, iid, object); }
    STDMETHODIMP SetItem(REFGUID key, REFPROPVARIANT item) override { return m_attributes->SetItem(key, item); }
    STDMETHODIMP DeleteItem(REFGUID key) override { return m_attributes->DeleteItem(key); }
    STDMETHODIMP DeleteAllItems() override { return m_attributes->DeleteAllItems(); }
    STDMETHODIMP SetUINT32(REFGUID key, UINT32 item) override { return m_attributes->SetUINT32(key, item); }
    STDMETHODIMP SetUINT64(REFGUID key, UINT64 item) override { return m_attributes->SetUINT64(key, item); }
    STDMETHODIMP SetDouble(REFGUID key, double item) override { return m_attributes->SetDouble(key, item); }
    STDMETHODIMP SetGUID(REFGUID key, REFGUID item) override { return m_attributes->SetGUID(key, item); }
    STDMETHODIMP SetString(REFGUID key, LPCWSTR text) override { return m_attributes->SetString(key, text); }
    STDMETHODIMP SetBlob(REFGUID key, const UINT8* bytes, UINT32 length) override { return m_attributes->SetBlob(key, bytes, length); }
    STDMETHODIMP SetUnknown(REFGUID key, IUnknown* object) override { return m_attributes->SetUnknown(key, object); }
    STDMETHODIMP LockStore() override { return m_attributes->LockStore(); }
    STDMETHODIMP UnlockStore() override { return m_attributes->UnlockStore(); }
    STDMETHODIMP GetCount(UINT32* count) override { return m_attributes->GetCount(count); }
    STDMETHODIMP GetItemByIndex(UINT32 index, GUID* key, PROPVARIANT* item) override { return m_attributes->GetItemByIndex(index, key, item); }
    STDMETHODIMP CopyAllItems(IMFAttributes* destination) override { return m_attributes->CopyAllItems(destination); }
private:
    std::mutex m_mutex;
    ComPtr<IMFAttributes> m_attributes;
    ComPtr<IMFMediaSourceEx> m_source;
    bool m_handedOut = false;
};

class D2ClassFactory final : public RuntimeClass<RuntimeClassFlags<ClassicCom>, IClassFactory> {
public:
    D2ClassFactory() { InterlockedIncrement(&D2ModuleObjects); }
    ~D2ClassFactory() { InterlockedDecrement(&D2ModuleObjects); }
    STDMETHODIMP CreateInstance(IUnknown* outer, REFIID iid, void** result) override {
        if (!result) return E_POINTER;
        *result = nullptr;
        if (outer) return CLASS_E_NOAGGREGATION;
        auto activate = Make<D2Activate>();
        if (!activate) return E_OUTOFMEMORY;
        HRESULT hr = activate->Initialize();
        return SUCCEEDED(hr) ? activate.CopyTo(iid, result) : hr;
    }
    STDMETHODIMP LockServer(BOOL lock) override {
        if (lock) InterlockedIncrement(&D2ModuleLocks);
        else InterlockedDecrement(&D2ModuleLocks);
        return S_OK;
    }
};

extern "C" HRESULT __stdcall DllGetClassObject(REFCLSID clsid, REFIID iid, void** result) {
    if (!result) return E_POINTER;
    *result = nullptr;
    if (clsid != CLSID_D2MediaSource) return CLASS_E_CLASSNOTAVAILABLE;
    auto factory = Make<D2ClassFactory>();
    return factory ? factory.CopyTo(iid, result) : E_OUTOFMEMORY;
}

extern "C" HRESULT __stdcall DllCanUnloadNow() {
    return InterlockedCompareExchange(&D2ModuleObjects, 0, 0) == 0 &&
        InterlockedCompareExchange(&D2ModuleLocks, 0, 0) == 0 ? S_OK : S_FALSE;
}

BOOL WINAPI DllMain(HINSTANCE, DWORD, void*) { return TRUE; }

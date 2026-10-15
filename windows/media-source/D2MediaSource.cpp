#include "D2MediaSource.h"
#include "D2Capture.h"
#include <mfapi.h>
#include <mferror.h>
#include <ks.h>
#include <ksmedia.h>
#include <ksproxy.h>
#include <wrl.h>
#include <mutex>
#include <new>

using Microsoft::WRL::ComPtr;
using Microsoft::WRL::RuntimeClass;
using Microsoft::WRL::RuntimeClassFlags;
using Microsoft::WRL::ClassicCom;
using Microsoft::WRL::ChainInterfaces;
using Microsoft::WRL::Make;
using Microsoft::WRL::FtmBase;

#define D2_RETURN_IF_FAILED(expr) do { HRESULT d2_hr = (expr); if (FAILED(d2_hr)) return d2_hr; } while (0)

long D2ModuleObjects = 0;
long D2ModuleLocks = 0;

namespace {
constexpr UINT32 Width = 640, Height = 400, Fps = 30;
constexpr DWORD FrameBytes = Width * Height;

HRESULT MakeIrType(IMFMediaType** output) {
    if (!output) return E_POINTER;
    *output = nullptr;
    ComPtr<IMFMediaType> type;
    D2_RETURN_IF_FAILED(MFCreateMediaType(&type));
    D2_RETURN_IF_FAILED(type->SetGUID(MF_MT_MAJOR_TYPE, MFMediaType_Video));
    D2_RETURN_IF_FAILED(type->SetGUID(MF_MT_SUBTYPE, MFVideoFormat_L8));
    D2_RETURN_IF_FAILED(type->SetUINT32(MF_MT_INTERLACE_MODE, MFVideoInterlace_Progressive));
    D2_RETURN_IF_FAILED(type->SetUINT32(MF_MT_ALL_SAMPLES_INDEPENDENT, TRUE));
    D2_RETURN_IF_FAILED(type->SetUINT32(MF_MT_FIXED_SIZE_SAMPLES, TRUE));
    D2_RETURN_IF_FAILED(type->SetUINT32(MF_MT_SAMPLE_SIZE, FrameBytes));
    D2_RETURN_IF_FAILED(type->SetUINT32(MF_MT_DEFAULT_STRIDE, Width));
    D2_RETURN_IF_FAILED(MFSetAttributeSize(type.Get(), MF_MT_FRAME_SIZE, Width, Height));
    D2_RETURN_IF_FAILED(MFSetAttributeRatio(type.Get(), MF_MT_FRAME_RATE, Fps, 1));
    D2_RETURN_IF_FAILED(MFSetAttributeRatio(type.Get(), MF_MT_PIXEL_ASPECT_RATIO, 1, 1));
    return type.CopyTo(output);
}

HRESULT SetIrAttributes(IMFAttributes* attributes) {
    D2_RETURN_IF_FAILED(attributes->SetGUID(MF_DEVICESTREAM_STREAM_CATEGORY, PINNAME_VIDEO_CAPTURE));
    D2_RETURN_IF_FAILED(attributes->SetUINT32(MF_DEVICESTREAM_STREAM_ID, 0));
    D2_RETURN_IF_FAILED(attributes->SetUINT32(MF_DEVICESTREAM_FRAMESERVER_SHARED, 1));
    return attributes->SetUINT32(MF_DEVICESTREAM_ATTRIBUTE_FRAMESOURCE_TYPES, MFFrameSourceTypes_Infrared);
}

class D2Stream final : public RuntimeClass<RuntimeClassFlags<ClassicCom>,
    ChainInterfaces<IMFMediaStream2, IMFMediaStream, IMFMediaEventGenerator>, FtmBase> {
public:
    D2Stream() { InterlockedIncrement(&D2ModuleObjects); }
    ~D2Stream() { m_capture.Stop(); InterlockedDecrement(&D2ModuleObjects); }

    HRESULT Initialize(IMFMediaSource* source) {
        m_source = source;
        D2_RETURN_IF_FAILED(MFCreateEventQueue(&m_events));
        ComPtr<IMFMediaType> type;
        D2_RETURN_IF_FAILED(MakeIrType(&type));
        IMFMediaType* types[] = {type.Get()};
        D2_RETURN_IF_FAILED(MFCreateStreamDescriptor(0, 1, types, &m_descriptor));
        ComPtr<IMFMediaTypeHandler> handler;
        D2_RETURN_IF_FAILED(m_descriptor->GetMediaTypeHandler(&handler));
        D2_RETURN_IF_FAILED(handler->SetCurrentMediaType(type.Get()));
        D2_RETURN_IF_FAILED(SetIrAttributes(m_descriptor.Get()));
        D2_RETURN_IF_FAILED(MFCreateAttributes(&m_attributes, 4));
        return SetIrAttributes(m_attributes.Get());
    }

    HRESULT GetAttributes(IMFAttributes** attributes) {
        if (!attributes) return E_POINTER;
        std::lock_guard<std::mutex> lock(m_mutex);
        if (m_shutdown) return MF_E_SHUTDOWN;
        return m_attributes.CopyTo(attributes);
    }

    HRESULT StartCapture() {
        std::lock_guard<std::mutex> lock(m_mutex);
        if (m_shutdown) return MF_E_SHUTDOWN;
        if (m_state == MF_STREAM_STATE_RUNNING) return S_OK;
        D2_RETURN_IF_FAILED(m_capture.Start());
        m_state = MF_STREAM_STATE_RUNNING;
        return m_events->QueueEventParamVar(MEStreamStarted, GUID_NULL, S_OK, nullptr);
    }

    HRESULT StopCapture() {
        std::lock_guard<std::mutex> lock(m_mutex);
        if (m_shutdown) return MF_E_SHUTDOWN;
        HRESULT stopHr = m_capture.Stop();
        m_state = MF_STREAM_STATE_STOPPED;
        D2_RETURN_IF_FAILED(stopHr);
        return m_events->QueueEventParamVar(MEStreamStopped, GUID_NULL, S_OK, nullptr);
    }

    void ShutdownStream() {
        std::lock_guard<std::mutex> lock(m_mutex);
        if (m_shutdown) return;
        m_shutdown = true;
        m_capture.Stop();
        m_state = MF_STREAM_STATE_STOPPED;
        if (m_events) m_events->Shutdown();
        m_source.Reset();
    }

    STDMETHODIMP BeginGetEvent(IMFAsyncCallback* callback, IUnknown* state) override {
        ComPtr<IMFMediaEventQueue> events;
        D2_RETURN_IF_FAILED(GetQueue(events));
        return events->BeginGetEvent(callback, state);
    }
    STDMETHODIMP EndGetEvent(IMFAsyncResult* result, IMFMediaEvent** event) override {
        ComPtr<IMFMediaEventQueue> events;
        D2_RETURN_IF_FAILED(GetQueue(events));
        return events->EndGetEvent(result, event);
    }
    STDMETHODIMP GetEvent(DWORD flags, IMFMediaEvent** event) override {
        ComPtr<IMFMediaEventQueue> events;
        D2_RETURN_IF_FAILED(GetQueue(events));
        return events->GetEvent(flags, event);
    }
    STDMETHODIMP QueueEvent(MediaEventType type, REFGUID extended, HRESULT status, const PROPVARIANT* payload) override {
        ComPtr<IMFMediaEventQueue> events;
        D2_RETURN_IF_FAILED(GetQueue(events));
        return events->QueueEventParamVar(type, extended, status, payload);
    }
    STDMETHODIMP GetMediaSource(IMFMediaSource** source) override {
        if (!source) return E_POINTER;
        *source = nullptr;
        std::lock_guard<std::mutex> lock(m_mutex);
        if (m_shutdown) return MF_E_SHUTDOWN;
        return m_source.CopyTo(source);
    }
    STDMETHODIMP GetStreamDescriptor(IMFStreamDescriptor** descriptor) override {
        if (!descriptor) return E_POINTER;
        *descriptor = nullptr;
        std::lock_guard<std::mutex> lock(m_mutex);
        if (m_shutdown) return MF_E_SHUTDOWN;
        return m_descriptor.CopyTo(descriptor);
    }
    STDMETHODIMP RequestSample(IUnknown* token) override {
        std::lock_guard<std::mutex> lock(m_mutex);
        if (m_shutdown) return MF_E_SHUTDOWN;
        if (m_state != MF_STREAM_STATE_RUNNING) return MF_E_INVALIDREQUEST;
        ComPtr<IMFSample> sample;
        ComPtr<IMFMediaBuffer> buffer;
        D2_RETURN_IF_FAILED(MFCreateSample(&sample));
        D2_RETURN_IF_FAILED(MFCreateMemoryBuffer(FrameBytes, &buffer));
        BYTE* bytes = nullptr;
        D2_RETURN_IF_FAILED(buffer->Lock(&bytes, nullptr, nullptr));
        LONGLONG time = 0;
        HRESULT captureHr = m_capture.Read(bytes, FrameBytes, &time);
        HRESULT unlockHr = buffer->Unlock();
        if (FAILED(captureHr)) {
            m_events->QueueEventParamVar(MEError, GUID_NULL, captureHr, nullptr);
            return captureHr;
        }
        D2_RETURN_IF_FAILED(unlockHr);
        D2_RETURN_IF_FAILED(buffer->SetCurrentLength(FrameBytes));
        D2_RETURN_IF_FAILED(sample->AddBuffer(buffer.Get()));
        D2_RETURN_IF_FAILED(sample->SetSampleTime(time));
        D2_RETURN_IF_FAILED(sample->SetSampleDuration(10000000 / Fps));
        if (token) D2_RETURN_IF_FAILED(sample->SetUnknown(MFSampleExtension_Token, token));
        return m_events->QueueEventParamUnk(MEMediaSample, GUID_NULL, S_OK, sample.Get());
    }
    STDMETHODIMP SetStreamState(MF_STREAM_STATE state) override {
        if (state == MF_STREAM_STATE_RUNNING) return StartCapture();
        if (state == MF_STREAM_STATE_STOPPED) return StopCapture();
        return MF_E_INVALID_STATE_TRANSITION;
    }
    STDMETHODIMP GetStreamState(MF_STREAM_STATE* state) override {
        if (!state) return E_POINTER;
        std::lock_guard<std::mutex> lock(m_mutex);
        if (m_shutdown) return MF_E_SHUTDOWN;
        *state = m_state;
        return S_OK;
    }
private:
    HRESULT GetQueue(ComPtr<IMFMediaEventQueue>& events) {
        std::lock_guard<std::mutex> lock(m_mutex);
        if (m_shutdown) return MF_E_SHUTDOWN;
        events = m_events;
        return S_OK;
    }
    std::mutex m_mutex;
    bool m_shutdown = false;
    MF_STREAM_STATE m_state = MF_STREAM_STATE_STOPPED;
    ComPtr<IMFMediaSource> m_source;
    ComPtr<IMFMediaEventQueue> m_events;
    ComPtr<IMFStreamDescriptor> m_descriptor;
    ComPtr<IMFAttributes> m_attributes;
    D2Capture m_capture;
};

class D2Source final : public RuntimeClass<RuntimeClassFlags<ClassicCom>,
    ChainInterfaces<IMFMediaSourceEx, IMFMediaSource, IMFMediaEventGenerator>, IMFGetService, IKsControl, IMFSampleAllocatorControl, FtmBase> {
public:
    D2Source() { InterlockedIncrement(&D2ModuleObjects); }
    ~D2Source() { InterlockedDecrement(&D2ModuleObjects); }

    HRESULT Initialize() {
        D2_RETURN_IF_FAILED(MFCreateEventQueue(&m_events));
        D2_RETURN_IF_FAILED(MFCreateAttributes(&m_attributes, 1));
        ComPtr<IMFSensorProfileCollection> profiles;
        ComPtr<IMFSensorProfile> profile;
        D2_RETURN_IF_FAILED(MFCreateSensorProfileCollection(&profiles));
        D2_RETURN_IF_FAILED(MFCreateSensorProfile(KSCAMERAPROFILE_Legacy, 0, nullptr, &profile));
        D2_RETURN_IF_FAILED(profile->AddProfileFilter(0, L"((RES==640,400;FRT==30,1;SUT==L8))"));
        D2_RETURN_IF_FAILED(profiles->AddProfile(profile.Get()));
        D2_RETURN_IF_FAILED(m_attributes->SetUnknown(MF_DEVICEMFT_SENSORPROFILE_COLLECTION, profiles.Get()));
        m_stream = Make<D2Stream>();
        if (!m_stream) return E_OUTOFMEMORY;
        HRESULT hr = m_stream->Initialize(this);
        if (FAILED(hr)) { m_stream->ShutdownStream(); return hr; }
        ComPtr<IMFStreamDescriptor> descriptor;
        hr = m_stream->GetStreamDescriptor(&descriptor);
        if (SUCCEEDED(hr)) {
            IMFStreamDescriptor* descriptors[] = {descriptor.Get()};
            hr = MFCreatePresentationDescriptor(1, descriptors, &m_descriptor);
        }
        if (SUCCEEDED(hr)) hr = m_descriptor->SelectStream(0);
        if (FAILED(hr)) m_stream->ShutdownStream();
        return hr;
    }
    STDMETHODIMP BeginGetEvent(IMFAsyncCallback* callback, IUnknown* state) override {
        ComPtr<IMFMediaEventQueue> events;
        D2_RETURN_IF_FAILED(GetQueue(events));
        return events->BeginGetEvent(callback, state);
    }
    STDMETHODIMP EndGetEvent(IMFAsyncResult* result, IMFMediaEvent** event) override {
        ComPtr<IMFMediaEventQueue> events;
        D2_RETURN_IF_FAILED(GetQueue(events));
        return events->EndGetEvent(result, event);
    }
    STDMETHODIMP GetEvent(DWORD flags, IMFMediaEvent** event) override {
        ComPtr<IMFMediaEventQueue> events;
        D2_RETURN_IF_FAILED(GetQueue(events));
        return events->GetEvent(flags, event);
    }
    STDMETHODIMP QueueEvent(MediaEventType type, REFGUID extended, HRESULT status, const PROPVARIANT* payload) override {
        ComPtr<IMFMediaEventQueue> events;
        D2_RETURN_IF_FAILED(GetQueue(events));
        return events->QueueEventParamVar(type, extended, status, payload);
    }
    STDMETHODIMP GetCharacteristics(DWORD* characteristics) override {
        if (!characteristics) return E_POINTER;
        std::lock_guard<std::mutex> lock(m_mutex);
        if (m_shutdown) return MF_E_SHUTDOWN;
        *characteristics = MFMEDIASOURCE_IS_LIVE;
        return S_OK;
    }
    STDMETHODIMP CreatePresentationDescriptor(IMFPresentationDescriptor** descriptor) override {
        if (!descriptor) return E_POINTER;
        *descriptor = nullptr;
        std::lock_guard<std::mutex> lock(m_mutex);
        if (m_shutdown) return MF_E_SHUTDOWN;
        return m_descriptor->Clone(descriptor);
    }
    STDMETHODIMP Start(IMFPresentationDescriptor* descriptor, const GUID* timeFormat, const PROPVARIANT* position) override {
        if (!descriptor || !position) return E_POINTER;
        if (timeFormat && *timeFormat != GUID_NULL) return MF_E_UNSUPPORTED_TIME_FORMAT;
        if (position->vt != VT_EMPTY && (position->vt != VT_I8 || position->hVal.QuadPart != 0)) return MF_E_INVALIDREQUEST;
        std::lock_guard<std::mutex> lock(m_mutex);
        if (m_shutdown) return MF_E_SHUTDOWN;
        D2_RETURN_IF_FAILED(ValidateDescriptor(descriptor));
        D2_RETURN_IF_FAILED(m_stream->StartCapture());
        D2_RETURN_IF_FAILED(m_events->QueueEventParamUnk(m_announced ? MEUpdatedStream : MENewStream, GUID_NULL, S_OK, static_cast<IMFMediaStream2*>(m_stream.Get())));
        m_announced = true;
        m_started = true;
        return m_events->QueueEventParamVar(MESourceStarted, GUID_NULL, S_OK, position);
    }
    STDMETHODIMP Stop() override {
        std::lock_guard<std::mutex> lock(m_mutex);
        if (m_shutdown) return MF_E_SHUTDOWN;
        D2_RETURN_IF_FAILED(m_stream->StopCapture());
        m_started = false;
        return m_events->QueueEventParamVar(MESourceStopped, GUID_NULL, S_OK, nullptr);
    }
    STDMETHODIMP Pause() override {
        std::lock_guard<std::mutex> lock(m_mutex);
        return m_shutdown ? MF_E_SHUTDOWN : MF_E_INVALID_STATE_TRANSITION;
    }
    STDMETHODIMP Shutdown() override {
        std::lock_guard<std::mutex> lock(m_mutex);
        if (m_shutdown) return MF_E_SHUTDOWN;
        m_shutdown = true;
        m_started = false;
        if (m_stream) m_stream->ShutdownStream();
        if (m_events) m_events->Shutdown();
        return S_OK;
    }
    STDMETHODIMP GetSourceAttributes(IMFAttributes** attributes) override {
        if (!attributes) return E_POINTER;
        *attributes = nullptr;
        std::lock_guard<std::mutex> lock(m_mutex);
        if (m_shutdown) return MF_E_SHUTDOWN;
        return m_attributes.CopyTo(attributes);
    }
    STDMETHODIMP GetStreamAttributes(DWORD id, IMFAttributes** attributes) override {
        if (!attributes) return E_POINTER;
        *attributes = nullptr;
        std::lock_guard<std::mutex> lock(m_mutex);
        if (m_shutdown) return MF_E_SHUTDOWN;
        if (id != 0) return MF_E_INVALIDSTREAMNUMBER;
        return m_stream->GetAttributes(attributes);
    }
    STDMETHODIMP SetD3DManager(IUnknown*) override {
        std::lock_guard<std::mutex> lock(m_mutex);
        return m_shutdown ? MF_E_SHUTDOWN : S_OK;
    }
    STDMETHODIMP GetService(REFGUID, REFIID, void** result) override {
        if (!result) return E_POINTER;
        *result = nullptr;
        std::lock_guard<std::mutex> lock(m_mutex);
        return m_shutdown ? MF_E_SHUTDOWN : MF_E_UNSUPPORTED_SERVICE;
    }
    STDMETHODIMP GetAllocatorUsage(DWORD outputId, DWORD* inputId, MFSampleAllocatorUsage* usage) override {
        if (!inputId || !usage) return E_POINTER;
        std::lock_guard<std::mutex> lock(m_mutex);
        if (m_shutdown) return MF_E_SHUTDOWN;
        if (outputId != 0) return MF_E_INVALIDSTREAMNUMBER;
        *inputId = 0;
        *usage = MFSampleAllocatorUsage_UsesCustomAllocator;
        return S_OK;
    }
    STDMETHODIMP SetDefaultAllocator(DWORD outputId, IUnknown* allocator) override {
        std::lock_guard<std::mutex> lock(m_mutex);
        if (m_shutdown) return MF_E_SHUTDOWN;
        if (outputId != 0) return MF_E_INVALIDSTREAMNUMBER;
        if (!allocator) return E_POINTER;
        // The advertised custom allocation path uses MFCreateMemoryBuffer, not this allocator.
        return MF_E_INVALIDREQUEST;
    }
    STDMETHODIMP KsProperty(PKSPROPERTY property, ULONG propertyBytes, void*, ULONG, ULONG* returned) override {
        if (!property || !returned) return E_POINTER;
        *returned = 0;
        if (propertyBytes < sizeof(KSPROPERTY)) return E_INVALIDARG;
        std::lock_guard<std::mutex> lock(m_mutex);
        if (m_shutdown) return MF_E_SHUTDOWN;
        // shortcut: publish no Hello mode until synchronized real illumination is verified.
        return HRESULT_FROM_WIN32(ERROR_SET_NOT_FOUND);
    }
    STDMETHODIMP KsMethod(PKSMETHOD, ULONG, void*, ULONG, ULONG* returned) override {
        if (!returned) return E_POINTER;
        *returned = 0;
        return HRESULT_FROM_WIN32(ERROR_SET_NOT_FOUND);
    }
    STDMETHODIMP KsEvent(PKSEVENT, ULONG, void*, ULONG, ULONG* returned) override {
        if (returned) *returned = 0;
        return HRESULT_FROM_WIN32(ERROR_SET_NOT_FOUND);
    }
private:
    HRESULT GetQueue(ComPtr<IMFMediaEventQueue>& events) {
        std::lock_guard<std::mutex> lock(m_mutex);
        if (m_shutdown) return MF_E_SHUTDOWN;
        events = m_events;
        return S_OK;
    }
    HRESULT ValidateDescriptor(IMFPresentationDescriptor* descriptor) {
        DWORD count = 0;
        D2_RETURN_IF_FAILED(descriptor->GetStreamDescriptorCount(&count));
        if (count != 1) return MF_E_INVALIDREQUEST;
        BOOL selected = FALSE;
        ComPtr<IMFStreamDescriptor> stream;
        D2_RETURN_IF_FAILED(descriptor->GetStreamDescriptorByIndex(0, &selected, &stream));
        DWORD id = ~0u;
        D2_RETURN_IF_FAILED(stream->GetStreamIdentifier(&id));
        if (!selected || id != 0) return MF_E_INVALIDREQUEST;
        ComPtr<IMFMediaTypeHandler> handler;
        ComPtr<IMFMediaType> type;
        D2_RETURN_IF_FAILED(stream->GetMediaTypeHandler(&handler));
        D2_RETURN_IF_FAILED(handler->GetCurrentMediaType(&type));
        GUID major = GUID_NULL, subtype = GUID_NULL;
        UINT32 width = 0, height = 0, numerator = 0, denominator = 0;
        D2_RETURN_IF_FAILED(type->GetGUID(MF_MT_MAJOR_TYPE, &major));
        D2_RETURN_IF_FAILED(type->GetGUID(MF_MT_SUBTYPE, &subtype));
        D2_RETURN_IF_FAILED(MFGetAttributeSize(type.Get(), MF_MT_FRAME_SIZE, &width, &height));
        D2_RETURN_IF_FAILED(MFGetAttributeRatio(type.Get(), MF_MT_FRAME_RATE, &numerator, &denominator));
        if (major != MFMediaType_Video || subtype != MFVideoFormat_L8 || width != Width || height != Height || numerator != Fps || denominator != 1) return MF_E_INVALIDMEDIATYPE;
        return S_OK;
    }
    std::mutex m_mutex;
    bool m_shutdown = false, m_started = false, m_announced = false;
    ComPtr<IMFMediaEventQueue> m_events;
    ComPtr<IMFAttributes> m_attributes;
    ComPtr<IMFPresentationDescriptor> m_descriptor;
    ComPtr<D2Stream> m_stream;
};
}

extern "C" HRESULT __stdcall CreateD2MediaSource(REFIID iid, void** result) {
    if (!result) return E_POINTER;
    *result = nullptr;
    auto source = Make<D2Source>();
    if (!source) return E_OUTOFMEMORY;
    HRESULT hr = source->Initialize();
    if (SUCCEEDED(hr)) hr = source.CopyTo(iid, result);
    if (FAILED(hr)) source->Shutdown();
    return hr;
}

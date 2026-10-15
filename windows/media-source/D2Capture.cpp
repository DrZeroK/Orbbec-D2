#include "D2Capture.h"
#include "OniCAPI.h"
#include <bcrypt.h>
#include <mferror.h>
#include <filesystem>
#include <fstream>
#include <vector>
#include <cstring>
#include <new>
#include <atomic>
#include <cstdio>

static_assert(sizeof(OniDeviceInfo) == 1028 && sizeof(OniFrame) == 80);

namespace {
void ModuleAnchor() {}
std::atomic_flag CaptureLease = ATOMIC_FLAG_INIT;
HRESULT VerifyDriver(const std::filesystem::path& file) {
    std::ifstream stream(file, std::ios::binary);
    if (!stream) return HRESULT_FROM_WIN32(ERROR_FILE_NOT_FOUND);
    std::vector<BYTE> data((std::istreambuf_iterator<char>(stream)), {});
    if (data.empty() || data.size() > 32 * 1024 * 1024) return E_FAIL;
    BCRYPT_ALG_HANDLE algorithm = nullptr;
    if (BCryptOpenAlgorithmProvider(&algorithm, BCRYPT_SHA256_ALGORITHM, nullptr, 0) < 0) return E_FAIL;
    BYTE digest[32]{};
    auto status = BCryptHash(algorithm, nullptr, 0, data.data(), static_cast<ULONG>(data.size()), digest, sizeof(digest));
    BCryptCloseAlgorithmProvider(algorithm, 0);
    static const BYTE expected[] = {0xbd,0x08,0xe8,0x73,0x78,0xeb,0xa3,0x34,0x2f,0x89,0x2c,0x5d,0x9c,0xf0,0x0a,0xf1,
        0xdf,0xbf,0x67,0x4e,0xf4,0x6c,0xec,0x38,0x12,0xeb,0xec,0x0d,0x66,0x9d,0x12,0x45};
    return status >= 0 && std::memcmp(digest, expected, 32) == 0 ? S_OK : HRESULT_FROM_WIN32(ERROR_INVALID_DATA);
}
HRESULT Status(OniStatus value) { return value == ONI_STATUS_OK ? S_OK : E_FAIL; }
HRESULT PatchEmitterReply(HMODULE driver, bool enable, bool* changed = nullptr) {
    auto instruction = reinterpret_cast<BYTE*>(driver) + 0x2d9fc;
    const BYTE expected[] = {static_cast<BYTE>(enable ? 0x83 : 0x80), 0x38, 0x01, 0x0f, 0x94, 0xc3};
    if (std::memcmp(instruction, expected, sizeof(expected))) return HRESULT_FROM_WIN32(ERROR_INVALID_DATA);
    DWORD protection = 0, ignored = 0;
    if (!VirtualProtect(instruction, 1, PAGE_EXECUTE_READWRITE, &protection)) return HRESULT_FROM_WIN32(GetLastError());
    // D2 replies 0x6400/0x6401; this pinned SDK incorrectly compares the whole DWORD to 1.
    instruction[0] = enable ? 0x80 : 0x83;
    if (changed) *changed = true;
    FlushInstructionCache(GetCurrentProcess(), instruction, 1);
    if (!VirtualProtect(instruction, 1, protection, &ignored)) return HRESULT_FROM_WIN32(GetLastError());
    return S_OK;
}
}

struct D2Capture::State {
    HMODULE crt1 = nullptr, crt2 = nullptr, library = nullptr, driver = nullptr;
    OniDeviceHandle device = nullptr;
    OniStreamHandle stream = nullptr;
    bool initialized = false, started = false;
    bool emitterChanged = false;
    bool tableChanged = false;
    bool getterPatched = false;
    int initialEmitter = -1;
#define D2_API(name) decltype(&name) name##_ = nullptr
    D2_API(oniInitialize); D2_API(oniShutdown); D2_API(oniGetDeviceList); D2_API(oniReleaseDeviceList);
    D2_API(oniDeviceOpen); D2_API(oniDeviceClose); D2_API(oniDeviceCreateStream);
    D2_API(oniDeviceGetProperty); D2_API(oniDeviceSetProperty);
    D2_API(oniStreamSetProperty); D2_API(oniStreamStart); D2_API(oniStreamStop); D2_API(oniStreamDestroy);
    D2_API(oniWaitForAnyStream); D2_API(oniStreamReadFrame); D2_API(oniFrameRelease);
#undef D2_API
};

HRESULT D2Capture::Start() {
    if (state_) return HRESULT_FROM_WIN32(ERROR_BUSY);
    if (CaptureLease.test_and_set()) return HRESULT_FROM_WIN32(ERROR_BUSY);
    state_ = new (std::nothrow) State;
    if (!state_) { CaptureLease.clear(); return E_OUTOFMEMORY; }
    HRESULT result = E_FAIL;
    auto setup = [&]() -> HRESULT {
        HMODULE self = nullptr;
        if (!GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                               reinterpret_cast<LPCWSTR>(&ModuleAnchor), &self)) return HRESULT_FROM_WIN32(GetLastError());
        WCHAR path[32768]{};
        DWORD length = GetModuleFileNameW(self, path, _countof(path));
        if (!length || length >= _countof(path)) return E_FAIL;
        auto root = std::filesystem::path(path).parent_path() / L"openni_runtime";
        auto driverPath = root / L"OpenNI2/Drivers/orbbec.dll";
        HRESULT hr = VerifyDriver(driverPath);
        if (FAILED(hr)) return hr;
        // shortcut: reuse this PC's installed VC2013 CRT; package licensed CRT before distributing.
        wchar_t systemDirectory[MAX_PATH]{};
        if (!GetSystemDirectoryW(systemDirectory, MAX_PATH)) throw std::runtime_error("GetSystemDirectory failed");
        auto office = std::filesystem::path(systemDirectory);
        state_->crt1 = LoadLibraryExW((office/L"msvcr120.dll").c_str(), nullptr, LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR|LOAD_LIBRARY_SEARCH_SYSTEM32);
        state_->crt2 = LoadLibraryExW((office/L"msvcp120.dll").c_str(), nullptr, LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR|LOAD_LIBRARY_SEARCH_SYSTEM32);
        if (!state_->crt1 || !state_->crt2) return HRESULT_FROM_WIN32(GetLastError());
        state_->library = LoadLibraryExW((root/L"OpenNI2.dll").c_str(), nullptr, LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR|LOAD_LIBRARY_SEARCH_SYSTEM32);
        state_->driver = LoadLibraryExW(driverPath.c_str(), nullptr, LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR|LOAD_LIBRARY_SEARCH_SYSTEM32);
        if (!state_->library || !state_->driver) return HRESULT_FROM_WIN32(GetLastError());
#define D2_LOAD(name) state_->name##_ = reinterpret_cast<decltype(state_->name##_)>(GetProcAddress(state_->library, #name)); if (!state_->name##_) return E_NOINTERFACE
        D2_LOAD(oniInitialize); D2_LOAD(oniShutdown); D2_LOAD(oniGetDeviceList); D2_LOAD(oniReleaseDeviceList);
        D2_LOAD(oniDeviceOpen); D2_LOAD(oniDeviceClose); D2_LOAD(oniDeviceCreateStream);
        D2_LOAD(oniDeviceGetProperty); D2_LOAD(oniDeviceSetProperty);
        D2_LOAD(oniStreamSetProperty); D2_LOAD(oniStreamStart); D2_LOAD(oniStreamStop); D2_LOAD(oniStreamDestroy);
        D2_LOAD(oniWaitForAnyStream); D2_LOAD(oniStreamReadFrame); D2_LOAD(oniFrameRelease);
#undef D2_LOAD
        auto pair = reinterpret_cast<USHORT*>(reinterpret_cast<BYTE*>(state_->driver) + 0x9f590);
        if (pair[0] != 0x2bc5 || pair[1] != 0x0300) return HRESULT_FROM_WIN32(ERROR_INVALID_DATA);
        pair[1] = 0x060d;
        state_->tableChanged = true;
        hr = Status(state_->oniInitialize_(2003));
        if (FAILED(hr)) return hr;
        state_->initialized = true;
        OniDeviceInfo* devices = nullptr;
        int count = 0;
        hr = Status(state_->oniGetDeviceList_(&devices, &count));
        if (FAILED(hr)) return hr;
        if (count < 0 || count > 100 || (count && !devices)) {
            if (devices) state_->oniReleaseDeviceList_(devices);
            return HRESULT_FROM_WIN32(ERROR_INVALID_DATA);
        }
        int matches = 0;
        for (int i = 0; i < count; ++i) {
            if (devices[i].usbVendorId == 0x2bc5 && devices[i].usbProductId == 0x060d) {
                ++matches;
                if (matches == 1) hr = Status(state_->oniDeviceOpen_(devices[i].uri, &state_->device));
            }
        }
        state_->oniReleaseDeviceList_(devices);
        if (matches != 1 || FAILED(hr)) return HRESULT_FROM_WIN32(ERROR_DEVICE_NOT_CONNECTED);
        hr = Status(state_->oniDeviceCreateStream_(state_->device, ONI_SENSOR_IR, &state_->stream));
        if (FAILED(hr)) return hr;
        OniVideoMode mode = {ONI_PIXEL_FORMAT_GRAY16, 640, 400, 30};
        hr = Status(state_->oniStreamSetProperty_(state_->stream, 3, &mode, sizeof(mode)));
        if (FAILED(hr)) return hr;
        hr = Status(state_->oniStreamStart_(state_->stream));
        if (SUCCEEDED(hr)) state_->started = true;
        return hr;
    };
    try { result = setup(); } catch (...) { result = E_FAIL; }
    if (FAILED(result)) Stop();
    return result;
}

HRESULT D2Capture::Read(BYTE* l8, DWORD bytes, LONGLONG* qpc100ns, FrameInfo* info) {
    if (!l8 || !qpc100ns) return E_POINTER;
    if (bytes != 640 * 400) return E_INVALIDARG;
    if (!state_ || !state_->started) return MF_E_NOT_INITIALIZED;
    int ready = 0;
    HRESULT hr = Status(state_->oniWaitForAnyStream_(&state_->stream, 1, &ready, 1000));
    if (FAILED(hr)) return hr;
    OniFrame* frame = nullptr;
    hr = Status(state_->oniStreamReadFrame_(state_->stream, &frame));
    if (FAILED(hr)) return hr;
    if (!frame) return E_FAIL;
    if (frame->sensorType != ONI_SENSOR_IR || frame->videoMode.pixelFormat != ONI_PIXEL_FORMAT_GRAY16 ||
        frame->width != 640 || frame->height != 400 || !frame->data || frame->stride < 1280 ||
        frame->stride % 2 || frame->stride > 32768 || frame->dataSize < frame->stride * 400) {
        state_->oniFrameRelease_(frame);
        return HRESULT_FROM_WIN32(ERROR_INVALID_DATA);
    }
    for (int y = 0; y < 400; ++y) {
        auto row = reinterpret_cast<const USHORT*>(reinterpret_cast<const BYTE*>(frame->data) + y * frame->stride);
        for (int x = 0; x < 640; ++x) l8[y * 640 + x] = static_cast<BYTE>((row[x] > 1023 ? 1023 : row[x]) >> 2);
    }
    LARGE_INTEGER counter{}, frequency{};
    QueryPerformanceCounter(&counter);
    QueryPerformanceFrequency(&frequency);
    *qpc100ns = counter.QuadPart / frequency.QuadPart * 10000000 + counter.QuadPart % frequency.QuadPart * 10000000 / frequency.QuadPart;
    if (info) *info = {frame->frameIndex, frame->timestamp};
    state_->oniFrameRelease_(frame);
    return S_OK;
}

HRESULT D2Capture::SetEmitter(bool enabled) {
    if (!state_ || !state_->device) return E_FAIL;
    if (!state_->emitterChanged) {
        int original = -1;
        HRESULT stateHr = GetEmitterState(&original);
        if (FAILED(stateHr)) return stateHr;
        if (original != 0 && original != 1) return HRESULT_FROM_WIN32(ERROR_INVALID_DATA);
        state_->initialEmitter = original;
    }
    ULONGLONG value = enabled ? 1 : 0;
    state_->emitterChanged = true;
    HRESULT hr = Status(state_->oniDeviceSetProperty_(state_->device, 0x1080e007, &value, sizeof(value)));
    return hr;
}

HRESULT D2Capture::GetEmitterState(int* enabled) {
    if (!enabled) return E_POINTER;
    if (!state_ || !state_->device) return E_FAIL;
    if (!state_->getterPatched) {
        HRESULT patchHr = PatchEmitterReply(state_->driver, true, &state_->getterPatched);
        if (FAILED(patchHr)) return patchHr;
    }
    int size = sizeof(*enabled);
    return Status(state_->oniDeviceGetProperty_(state_->device, 0x1080ffbf, enabled, &size));
}

HRESULT D2Capture::Stop() {
    if (!state_) return S_OK;
    HRESULT restored = S_OK;
    if (state_->device && state_->emitterChanged && state_->initialEmitter >= 0 && state_->oniDeviceSetProperty_) {
        ULONGLONG original = static_cast<ULONGLONG>(state_->initialEmitter);
        restored = Status(state_->oniDeviceSetProperty_(state_->device, 0x1080e007, &original, sizeof(original)));
        int actual = -1, size = sizeof(actual);
        HRESULT readback = E_FAIL;
        for (int attempt = 0; attempt < 6; ++attempt) {
            size = sizeof(actual);
            readback = Status(state_->oniDeviceGetProperty_(state_->device, 0x1080ffbf, &actual, &size));
            if (SUCCEEDED(readback) && actual == state_->initialEmitter) break;
            Sleep(20);
        }
        if (FAILED(readback) || actual != state_->initialEmitter) restored = E_FAIL;
        if (FAILED(restored)) std::fprintf(stderr, "D2 restore expected=%d actual=%d readback=0x%08lx\n", state_->initialEmitter, actual, static_cast<unsigned long>(readback));
    }
    if (state_->stream && state_->oniStreamStop_ && state_->started) state_->oniStreamStop_(state_->stream);
    if (state_->stream && state_->oniStreamDestroy_) state_->oniStreamDestroy_(state_->stream);
    if (state_->device && state_->oniDeviceClose_) state_->oniDeviceClose_(state_->device);
    if (state_->initialized && state_->oniShutdown_) state_->oniShutdown_();
    if (state_->getterPatched && FAILED(PatchEmitterReply(state_->driver, false))) restored = E_FAIL;
    if (state_->driver && state_->tableChanged) {
        auto pair = reinterpret_cast<USHORT*>(reinterpret_cast<BYTE*>(state_->driver) + 0x9f590);
        if (pair[0] == 0x2bc5 && pair[1] == 0x060d) pair[1] = 0x0300;
    }
    for (auto module : {state_->driver, state_->library, state_->crt2, state_->crt1}) if (module) FreeLibrary(module);
    delete state_;
    state_ = nullptr;
    CaptureLease.clear();
    return restored;
}

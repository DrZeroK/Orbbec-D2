#pragma once
#include <windows.h>

// The SDK remains behind the user-mode source; no kernel USB replacement.
class D2Capture {
public:
    struct FrameInfo { int index; ULONGLONG deviceTimestamp; };
    ~D2Capture() { Stop(); }
    HRESULT Start();
    HRESULT Read(BYTE* l8, DWORD bytes, LONGLONG* qpc100ns, FrameInfo* info = nullptr);
    HRESULT Stop();
    HRESULT SetEmitter(bool enabled);
    HRESULT GetEmitterState(int* enabled);
private:
    struct State;
    State* state_ = nullptr;
};

#pragma once
#include <windows.h>
#include <mfidl.h>

// This source advertises real IR capture only. Hello illumination is unverified.
inline constexpr GUID CLSID_D2MediaSource =
{0x265e13ef, 0x0b32, 0x4e1d, {0x8a, 0x91, 0xcf, 0xd1, 0x71, 0x43, 0xd8, 0x9c}};

extern "C" HRESULT __stdcall CreateD2MediaSource(REFIID iid, void** result);
extern long D2ModuleObjects;
extern long D2ModuleLocks;

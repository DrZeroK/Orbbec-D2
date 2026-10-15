// UMDF 2 interface registration only. Requires WDK; not installed by the probe.
#include <windows.h>
#include <wdf.h>

static const GUID D2VideoCameraCategory = {0xe5323777,0xf976,0x4f5b,{0x9b,0x55,0xb9,0x46,0x99,0xc4,0x6e,0x44}};
static const GUID D2SensorCameraCategory = {0x24e552d7,0x6523,0x47f7,{0xa6,0x47,0xd3,0x46,0x5b,0xf1,0xf5,0xca}};
DRIVER_INITIALIZE DriverEntry;
EVT_WDF_DRIVER_DEVICE_ADD D2StubDeviceAdd;

NTSTATUS DriverEntry(PDRIVER_OBJECT object, PUNICODE_STRING path) {
    WDF_DRIVER_CONFIG config;
    WDF_DRIVER_CONFIG_INIT(&config, D2StubDeviceAdd);
    return WdfDriverCreate(object, path, WDF_NO_OBJECT_ATTRIBUTES, &config, WDF_NO_HANDLE);
}

NTSTATUS D2StubDeviceAdd(WDFDRIVER driver, PWDFDEVICE_INIT init) {
    WDFDEVICE device;
    UNICODE_STRING reference;
    NTSTATUS status;
    UNREFERENCED_PARAMETER(driver);
    RtlInitUnicodeString(&reference, L"D2InfraredSource");
    status = WdfDeviceCreate(&init, WDF_NO_OBJECT_ATTRIBUTES, &device);
    if (!NT_SUCCESS(status)) return status;
    status = WdfDeviceCreateDeviceInterface(device, &D2VideoCameraCategory, &reference);
    if (!NT_SUCCESS(status)) return status;
    return WdfDeviceCreateDeviceInterface(device, &D2SensorCameraCategory, &reference);
}

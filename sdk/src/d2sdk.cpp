#include "d2sdk.h"
#include "frame.h"
#include "mode.h"
#include <OniCProperties.h>
#include <array>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <new>
#include <string>
#include <unistd.h>

static_assert(sizeof(OniFrame)==80 && offsetof(OniFrame,timestamp)==24,"unsupported OpenNI frame ABI");
static_assert(sizeof(OniDeviceInfo)==1028,"unsupported OpenNI device ABI");

struct D2Device {
    OniDeviceHandle device=nullptr;
    std::vector<OniStreamHandle> streams;
    std::vector<D2Mode> modes;
    std::vector<int> mirrors;
    std::array<d2_internal::State,4> states;
    bool initialized=false, started=false, usb3=false;
    std::string error;
};
static std::atomic<bool> occupied{false};
static thread_local std::string last_error;
static int fail(D2Device *d,const std::string &why,int code=D2_ERROR) {
    last_error=why; if(d) d->error=why; return code;
}
static std::string read_text(const std::filesystem::path &p) {
    std::ifstream in(p); std::string value; if(!(in>>value)) throw std::runtime_error("USB identity disappeared"); return value;
}
static bool check_usb() {
    int matches=0;
    bool usb3=false;
    for (const auto &entry:std::filesystem::directory_iterator("/sys/bus/usb/devices")) {
        auto p=entry.path();
        if(!std::filesystem::exists(p/"idVendor") || !std::filesystem::exists(p/"idProduct")) continue;
        if(read_text(p/"idVendor")!="2bc5" || read_text(p/"idProduct")!="060d") continue;
        ++matches;
        const int bus=std::stoi(read_text(p/"busnum")), node=std::stoi(read_text(p/"devnum"));
        if(bus<1 || bus>999 || node<1 || node>999) throw std::runtime_error("invalid D2 USB identity");
        char path[64]; std::snprintf(path,sizeof(path),"/dev/bus/usb/%03d/%03d",bus,node);
        if(access(path,R_OK|W_OK)!=0) throw std::runtime_error("D2 USB node needs read/write permission; camera not opened");
        usb3=std::stod(read_text(p/"speed"))>=5000;
    }
    if(matches!=1) throw std::runtime_error("expected exactly one D2 2bc5:060d");
    return usb3;
}

extern "C" int d2_open(D2Device **out) {
    if(!out) return fail(nullptr,"null output",D2_INVALID);
    *out=nullptr;
    if(occupied.exchange(true)) return fail(nullptr,"one D2 context per process",D2_INVALID);
    D2Device *d=nullptr;
    try {
        d=new D2Device;
        d->streams.reserve(2); d->modes.reserve(2); d->mirrors.reserve(2);
        d->usb3=check_usb();
        if(oniInitialize(2003)!=ONI_STATUS_OK) throw std::runtime_error("OpenNI initialize failed");
        d->initialized=true;
        OniDeviceInfo *devices=nullptr; int count=0;
        if(oniGetDeviceList(&devices,&count)!=ONI_STATUS_OK) throw std::runtime_error("OpenNI enumeration failed");
        std::string uri; int matches=0;
        if(count>=0 && count<=100) for(int i=0;i<count;++i)
            if(devices[i].usbVendorId==0x2bc5 && devices[i].usbProductId==0x060d) {uri=devices[i].uri; ++matches;}
        oniReleaseDeviceList(devices);
        if(matches!=1) throw std::runtime_error("native D2 enumeration failed; use packaged driver");
        if(oniDeviceOpen(uri.c_str(),&d->device)!=ONI_STATUS_OK) throw std::runtime_error("D2 open failed");
        char name[256]{}; int size=sizeof(name);
        if(oniDeviceGetProperty(d->device,0x1080ff7a,name,&size)!=ONI_STATUS_OK
            || std::string(name,strnlen(name,sizeof(name)))!="Mx6000 TornadoD2")
            throw std::runtime_error("unverified camera model");
        *out=d; return D2_OK;
    } catch(const std::exception &e) {
        const std::string why=e.what(); d2_close(d); occupied=false;
        return fail(nullptr,why,why.find("permission")!=std::string::npos?D2_PERMISSION:D2_ERROR);
    }
}
extern "C" void d2_close(D2Device *d) {
    if(!d) return;
    for(auto stream:d->streams) {oniStreamStop(stream); oniStreamDestroy(stream);}
    if(d->device) oniDeviceClose(d->device);
    if(d->initialized) oniShutdown();
    delete d; occupied=false;
}
extern "C" const char *d2_error(const D2Device *d) {return d?d->error.c_str():last_error.c_str();}

extern "C" int d2_modes(D2Device *d,int sensor,int experimental,D2Mode *out,int capacity) {
    if(!d || (sensor!=D2_DEPTH && sensor!=D2_IR) || capacity<0 || (!out && capacity))
        return fail(d,"invalid mode query",D2_INVALID);
    const auto *info=oniDeviceGetSensorInfo(d->device,static_cast<OniSensorType>(sensor));
    if(!info || info->numSupportedVideoModes<0 || info->numSupportedVideoModes>1000)
        return fail(d,"invalid sensor modes");
    int count=0;
    for(int i=0;i<info->numSupportedVideoModes;++i) {
        const auto &raw=info->pSupportedVideoModes[i];
        for(const auto& mode:d2_internal::modes_for(sensor,raw,d->usb3,experimental!=0)){
            if(count<capacity) out[count]=mode;
            ++count;
        }
    }
    return count;
}
extern "C" int d2_configure(D2Device *d,int sensor,int format,int width,int height,int fps) {
    if(!d || d->started) return fail(d,"configure before start",D2_INVALID);
    for(const auto &m:d->modes) if(m.sensor==sensor) return fail(d,"sensor already configured",D2_INVALID);
    D2Mode modes[8]{}; const int count=d2_modes(d,sensor,1,modes,8);
    if(count<0 || count>8) return fail(d,"invalid modes");
    for(int i=0;i<count;++i) {
        auto mode=modes[i];
        if(mode.format!=format || mode.width!=width || mode.height!=height || mode.reported_fps!=fps) continue;
        for(const auto& previous:d->modes)
            if(!d2_internal::streams_compatible(previous,mode))
                return fail(d,"HD streams must be used alone; use standard modes for depth+IR",D2_INVALID);
        OniStreamHandle stream=nullptr;
        if(oniDeviceCreateStream(d->device,static_cast<OniSensorType>(sensor),&stream)!=ONI_STATUS_OK)
            return fail(d,"create stream failed");
        OniVideoMode raw{static_cast<OniPixelFormat>(format),mode.requested_width,mode.requested_height,fps};
        int mirror=0, size=sizeof(mirror);
        if(oniStreamSetProperty(stream,ONI_STREAM_PROPERTY_VIDEO_MODE,&raw,sizeof(raw))!=ONI_STATUS_OK
            || oniStreamSetProperty(stream,ONI_STREAM_PROPERTY_MIRRORING,&mirror,sizeof(mirror))!=ONI_STATUS_OK
            || oniStreamGetProperty(stream,ONI_STREAM_PROPERTY_MIRRORING,&mirror,&size)!=ONI_STATUS_OK || mirror!=0) {
            oniStreamDestroy(stream); return fail(d,"mode or mirror configuration failed");
        }
        if(sensor==D2_DEPTH&&width==1280&&height==800&&fps==30){
            uint64_t filter=0;int bytes=sizeof(filter);
            // The bundled CPU filter otherwise reduces HD30 to about 14.5fps on X5.
            if(oniStreamSetProperty(stream,0x2080ff43,&filter,sizeof(filter))!=ONI_STATUS_OK
                ||oniStreamGetProperty(stream,0x2080ff43,&filter,&bytes)!=ONI_STATUS_OK
                ||bytes!=sizeof(filter)||filter!=0){
                oniStreamDestroy(stream);return fail(d,"HD30 software-filter configuration failed");
            }
        }
        d->streams.push_back(stream); d->modes.push_back(mode); d->mirrors.push_back(mirror);
        return D2_OK;
    }
    return fail(d,"mode not verified for this adapter",D2_INVALID);
}
extern "C" int d2_start(D2Device *d) {
    if(!d || d->started || d->streams.empty()) return fail(d,"invalid start",D2_INVALID);
    for(auto stream:d->streams) if(oniStreamStart(stream)!=ONI_STATUS_OK) {
        for(auto prior:d->streams) oniStreamStop(prior);
        return fail(d,"start stream failed");
    }
    d->started=true; return D2_OK;
}
extern "C" int d2_read(D2Device *d,int timeout,D2Frame *out) {
    if(!d || !out || !d->started || timeout<1 || timeout>5000) return fail(d,"invalid read",D2_INVALID);
    *out={}; int index=-1;
    const auto rc=oniWaitForAnyStream(d->streams.data(),int(d->streams.size()),&index,timeout);
    if(rc==ONI_STATUS_TIME_OUT) return fail(d,"frame wait timed out",D2_TIMEOUT);
    if(rc!=ONI_STATUS_OK || index<0 || size_t(index)>=d->streams.size()) return fail(d,"wait failed");
    OniFrame *frame=nullptr;
    if(oniStreamReadFrame(d->streams[index],&frame)!=ONI_STATUS_OK || !frame) return fail(d,"read frame failed");
    const auto received=std::chrono::steady_clock::now().time_since_epoch();
    const auto ns=std::chrono::duration_cast<std::chrono::nanoseconds>(received).count();
    try {*out=d2_internal::copy_frame(*frame,d->modes[index],d->mirrors[index],uint64_t(ns),d->states[d->modes[index].sensor]);}
    catch(const std::exception &e) {oniFrameRelease(frame); return fail(d,e.what());}
    oniFrameRelease(frame); return D2_OK;
}
extern "C" int d2_camera_parameters(D2Device *d,float out[30]) {
    if(!d || !out) return fail(d,"invalid calibration output",D2_INVALID);
    float values[30]{}; int size=sizeof(values);
    if(oniDeviceGetProperty(d->device,14,values,&size)!=ONI_STATUS_OK || size!=sizeof(values))
        return fail(d,"camera parameter read failed");
    for(float v:values) if(!std::isfinite(v)) return fail(d,"invalid calibration number");
    if(values[0]<=0 || values[1]<=0 || values[4]<=0 || values[5]<=0) return fail(d,"invalid calibration focal length");
    std::copy(values,values+30,out); return D2_OK;
}

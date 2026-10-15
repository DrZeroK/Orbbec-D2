#include "d2sdk.h"
#include <OniCAPI.h>
#include <array>
#include <chrono>
#include <cstdlib>
#include <iostream>
#include <string>

int main(int argc,char **argv) {
    if(argc==2 && std::string(argv[1])=="--native-enumerate") {
        if(oniInitialize(2003)!=ONI_STATUS_OK) return 2;
        OniDeviceInfo *devices=nullptr; int count=0, matches=0;
        const auto rc=oniGetDeviceList(&devices,&count);
        if(rc==ONI_STATUS_OK && count>=0 && count<=100) for(int i=0;i<count;++i)
            if(devices[i].usbVendorId==0x2bc5 && devices[i].usbProductId==0x060d) ++matches;
        oniReleaseDeviceList(devices); oniShutdown();
        std::cout<<"{\"native_d2_count\":"<<matches<<",\"python_memory_patch\":false}\n";
        return rc==ONI_STATUS_OK && matches==1?0:3;
    }
    const int seconds=argc>1?std::atoi(argv[1]):10;
    const std::string kind=argc>2?argv[2]:"dual";
    if(seconds<1 || seconds>180 || (kind!="dual" && kind!="depth" && kind!="depth100" && kind!="ir" && kind!="hd" && kind!="hd30" && kind!="irhd30" && kind!="hddual30")) return 2;
    D2Device *d=nullptr;
    if(d2_open(&d)!=D2_OK) {std::cerr<<d2_error(nullptr)<<"\n"; return 3;}
    auto fail=[&] {std::cerr<<d2_error(d)<<"\n"; d2_close(d); return 4;};
    float calibration[30]{};
    if(d2_camera_parameters(d,calibration)!=D2_OK) return fail();
    std::cout<<"{\"calibration_floats\":30,\"registration_verified\":false}\n";
    for(int sensor:{D2_DEPTH,D2_IR}) {
        D2Mode modes[8]{}; const int n=d2_modes(d,sensor,1,modes,8);
        if(n<0 || n>8) return fail();
        for(int i=0;i<n;++i) std::cout<<"{\"sensor\":"<<sensor<<",\"mode\":["<<modes[i].format<<","<<modes[i].width<<","<<modes[i].height<<","<<modes[i].reported_fps<<"],\"experimental\":"<<modes[i].experimental<<"}\n";
    }
    const bool hd=kind=="hd"||kind=="hd30"||kind=="hddual30";
    if(kind!="ir" && kind!="irhd30" && d2_configure(d,D2_DEPTH,kind=="depth100"?D2_DEPTH_100UM:D2_DEPTH_MM,hd?1280:640,hd?800:400,kind=="hd"?5:30)!=D2_OK) return fail();
    if((kind=="ir" || kind=="dual" || kind=="irhd30" || kind=="hddual30") && d2_configure(d,D2_IR,D2_GRAY16,kind=="irhd30"||kind=="hddual30"?1280:640,kind=="irhd30"||kind=="hddual30"?800:400,30)!=D2_OK) return fail();
    if(d2_start(d)!=D2_OK) return fail();
    struct Stats {int count=0, bad_clock=0, bad_counter=0,gaps=0,duplicate=0; uint64_t first=0,last=0;};
    std::array<Stats,4> stats{};
    const auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(seconds);
    while(std::chrono::steady_clock::now()<deadline) {
        D2Frame frame{}; const int rc=d2_read(d,3000,&frame);
        if(rc!=D2_OK) return fail();
        auto &s=stats[frame.sensor];
        if(!s.count) {
            s.first=frame.host_received_ns;
            std::cout<<"{\"first_frame_sensor\":"<<frame.sensor<<",\"shape\":["<<frame.width<<","<<frame.height<<"],\"requested_grid\":["<<frame.requested_width<<","<<frame.requested_height<<"],\"flags\":"<<frame.flags<<"}\n";
        }
        ++s.count;s.last=frame.host_received_ns;
        s.bad_clock+=bool(frame.flags&D2_TIMESTAMP_NONINCREASING);
        s.bad_counter+=bool(frame.flags&D2_COUNTER_NONINCREASING);
        s.gaps+=bool(frame.flags&D2_COUNTER_GAP);
        s.duplicate+=bool(frame.flags&D2_IDENTICAL_CONTENT);
        if(frame.sensor==D2_DEPTH) for(int i=0;i<8;++i)
            if(static_cast<const uint16_t*>(frame.data)[i]!=0) {d2_close(d);return 5;}
    }
    for(int sensor:{D2_DEPTH,D2_IR}) {
        auto s=stats[sensor]; if(!s.count) continue;
        const double fps=s.count>1?double(s.count-1)*1e9/double(s.last-s.first):0;
        std::cout<<"{\"summary_sensor\":"<<sensor<<",\"frames\":"<<s.count<<",\"host_fps\":"<<fps<<",\"bad_clock\":"<<s.bad_clock<<",\"bad_counter\":"<<s.bad_counter<<",\"gap_events\":"<<s.gaps<<",\"duplicate\":"<<s.duplicate<<",\"exposure_sync_verified\":false}\n";
    }
    d2_close(d);return 0;
}

#include "frame.h"
#include "mode.h"
#include <cassert>
#include <iostream>
#include <functional>

int main() {
    using namespace d2_internal;
    OniVideoMode hd{ONI_PIXEL_FORMAT_DEPTH_1_MM,800,1280,5};
    auto usb2=modes_for(D2_DEPTH,hd,false,true),usb3=modes_for(D2_DEPTH,hd,true,true);
    assert(usb2.size()==1&&usb2[0].reported_fps==5);
    assert(usb3.size()==2&&usb3[1].reported_fps==30&&usb3[1].experimental==1);
    assert(usb3[1].width==1280&&usb3[1].height==800&&usb3[1].requested_width==800);
    assert(modes_for(D2_DEPTH,hd,true,false).empty());
    assert(modes_for(D2_IR,{ONI_PIXEL_FORMAT_GRAY16,640,400,60},true,true).empty());
    assert(modes_for(D2_IR,{ONI_PIXEL_FORMAT_GRAY16,1280,800,5},true,true).size()==2);
    auto standard_depth=modes_for(D2_DEPTH,{ONI_PIXEL_FORMAT_DEPTH_1_MM,400,640,30},true,false)[0];
    auto standard_ir=modes_for(D2_IR,{ONI_PIXEL_FORMAT_GRAY16,640,400,30},true,false)[0];
    assert(streams_compatible(standard_depth,standard_ir));
    assert(!streams_compatible(usb3[1],standard_ir)&&!streams_compatible(standard_ir,usb3[1]));
    assert(!streams_compatible(standard_depth,standard_depth));
    D2Mode mode{D2_DEPTH,D2_DEPTH_MM,10,2,2,10,30,0};
    std::vector<uint16_t> pixels(24,1000);
    OniFrame raw{}; raw.data=pixels.data(); raw.dataSize=int(pixels.size()*2);
    raw.sensorType=ONI_SENSOR_DEPTH; raw.videoMode.pixelFormat=ONI_PIXEL_FORMAT_DEPTH_1_MM;
    raw.width=10; raw.height=2; raw.stride=24; raw.frameIndex=1; raw.timestamp=0;
    raw.videoMode.resolutionX=10; raw.videoMode.resolutionY=2;
    State state;
    auto result=copy_frame(raw,mode,0,12345,state);
    assert(result.width==10 && result.height==2 && result.stride==20 && result.bytes==40);
    auto data=static_cast<const uint16_t*>(result.data);
    for(int i=0;i<8;++i) assert(data[i]==0);
    assert(data[8]==1000 && data[10]==1000);
    assert(result.sdk_timestamp_us==0 && result.host_received_ns==12345);
    assert((result.flags&D2_TIMESTAMP_UNVERIFIED) && !(result.flags&D2_TIMESTAMP_NONINCREASING));
    raw.frameIndex=3;
    result=copy_frame(raw,mode,0,99999,state);
    assert((result.flags&D2_TIMESTAMP_NONINCREASING) && (result.flags&D2_COUNTER_GAP));
    assert(result.flags&D2_IDENTICAL_CONTENT);
    raw.frameIndex=2; raw.timestamp=100;
    pixels[9]=1200;
    result=copy_frame(raw,mode,0,100000,state);
    assert((result.flags&D2_COUNTER_NONINCREASING) && !(result.flags&D2_IDENTICAL_CONTENT));
    auto rejected=[&](const std::function<void()> &change) {
        auto original=raw;
        change(); bool caught=false;
        try {copy_frame(raw,mode,0,1,state);} catch(const std::runtime_error&) {caught=true;}
        assert(caught); raw=original;
    };
    rejected([&]{raw.data=nullptr;});
    rejected([&]{raw.dataSize=4;});
    rejected([&]{raw.stride=2;});
    rejected([&]{raw.width=11;});
    rejected([&]{raw.croppingEnabled=1;});
    rejected([&]{raw.frameIndex=0;});
    rejected([&]{raw.videoMode.resolutionX=2;});
    OniFrame hd_frame{};std::vector<uint16_t> hd_pixels(1280*800,700);
    hd_frame.data=hd_pixels.data();hd_frame.dataSize=int(hd_pixels.size()*2);
    hd_frame.sensorType=ONI_SENSOR_DEPTH;hd_frame.width=1280;hd_frame.height=800;hd_frame.stride=2560;
    hd_frame.videoMode={ONI_PIXEL_FORMAT_DEPTH_1_MM,1280,800,30};hd_frame.frameIndex=1;
    State hd_state;auto hd_result=copy_frame(hd_frame,usb3[1],0,1,hd_state);
    assert(hd_result.flags&D2_SOFTWARE_FILTER_DISABLED);
    assert(!(result.flags&D2_SOFTWARE_FILTER_DISABLED));
    std::cout<<"PASS: USB2/USB3 modes, padding, depth mask, raw clock provenance, counter/clock/content flags, malformed frames\n";
}

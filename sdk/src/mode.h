#ifndef D2_MODE_INTERNAL_H
#define D2_MODE_INTERNAL_H
#include "d2sdk.h"
#include <OniCAPI.h>
#include <vector>
namespace d2_internal {
inline bool streams_compatible(const D2Mode& a,const D2Mode& b){
    return a.sensor!=b.sensor&&a.width<=640&&a.height<=400&&b.width<=640&&b.height<=400;
}
inline std::vector<D2Mode> modes_for(int sensor,const OniVideoMode& raw,bool usb3,bool experimental){
    const bool depth=sensor==D2_DEPTH&&(raw.pixelFormat==ONI_PIXEL_FORMAT_DEPTH_1_MM||raw.pixelFormat==ONI_PIXEL_FORMAT_DEPTH_100_UM);
    const bool ir=sensor==D2_IR&&raw.pixelFormat==ONI_PIXEL_FORMAT_GRAY16;
    const bool standard=raw.fps==30&&((depth&&raw.resolutionX==400&&raw.resolutionY==640)||(ir&&raw.resolutionX==640&&raw.resolutionY==400));
    const bool hd=experimental&&raw.fps==5&&((depth&&raw.resolutionX==800&&raw.resolutionY==1280)||(ir&&raw.resolutionX==1280&&raw.resolutionY==800));
    if(!standard&&!hd)return {};
    D2Mode m{sensor,int(raw.pixelFormat),depth?raw.resolutionY:raw.resolutionX,depth?raw.resolutionX:raw.resolutionY,raw.resolutionX,raw.resolutionY,raw.fps,hd?1:0};
    std::vector<D2Mode> out{m};
    // This D2 firmware accepts HD30 on USB3 although its preset table lists only 5.
    if(hd&&usb3){m.reported_fps=30;out.push_back(m);}
    return out;
}
}
#endif

// Isolated diagnostic: only documented stream settings; no persistent device writes.
#include <OniCAPI.h>
#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <sys/resource.h>
#include <vector>

struct Camera {
    OniDeviceHandle device=nullptr;
    OniStreamHandle stream=nullptr;
    uint32_t saved_exposure=0;bool restore_exposure=false;
    ~Camera(){
        if(stream){oniStreamStop(stream);oniStreamDestroy(stream);}
        if(restore_exposure){
            int rc=oniDeviceSetProperty(device,12,&saved_exposure,sizeof(saved_exposure));
            uint32_t value=0;int size=sizeof(value);int read=oniDeviceGetProperty(device,12,&value,&size);
            std::cout<<"{\"restore_exposure_rc\":"<<rc<<",\"read_rc\":"<<read<<",\"restored\":"<<value<<",\"expected\":"<<saved_exposure<<"}"<<std::endl;
        }
        if(device)oniDeviceClose(device);oniShutdown();
    }
};
static bool ok(int rc,const char *label){
    std::cout<<"{\"step\":\""<<label<<"\",\"rc\":"<<rc<<"}"<<std::endl;
    if(rc)std::cerr<<oniGetExtendedError()<<std::endl;
    return rc==0;
}
static void properties(OniStreamHandle s){
    for(int id:{0x10800001,0x2080ff43,0x2080ff45,0x2080ff46}){
        uint64_t value=0;int size=sizeof(value);int rc=oniStreamGetProperty(s,id,&value,&size);
        std::cout<<"{\"property\":"<<id<<",\"rc\":"<<rc<<",\"size\":"<<size<<",\"value\":"<<value<<"}"<<std::endl;
    }
    OniVideoMode m{};int size=sizeof(m);int rc=oniStreamGetProperty(s,ONI_STREAM_PROPERTY_VIDEO_MODE,&m,&size);
    std::cout<<"{\"mode_rc\":"<<rc<<",\"mode\":["<<m.pixelFormat<<","<<m.resolutionX<<","<<m.resolutionY<<","<<m.fps<<"]}"<<std::endl;
}
static void firmware_parameters(OniDeviceHandle d,const char *stage){
    for(uint16_t id:{0x12,0x13,0x14,0x19,0x1a,0x1b}){
        uint16_t pair[2]{id,0};int size=sizeof(pair);
        int rc=oniDeviceGetProperty(d,0x1080e001,pair,&size);
        std::cout<<"{\"firmware_stage\":\""<<stage<<"\",\"param\":"<<id<<",\"value\":"<<pair[1]<<",\"rc\":"<<rc<<",\"size\":"<<size<<"}"<<std::endl;
    }
}
int main(int argc,char **argv){
    if(argc!=5&&argc!=6)return 2;
    const int sensor=std::atoi(argv[1]),hd=std::atoi(argv[2]),fps=std::atoi(argv[3]),seconds=std::atoi(argv[4]);
    if((sensor!=1&&sensor!=3)||(hd!=0&&hd!=1)||(fps!=5&&fps!=30)||seconds<1||seconds>120)return 2;
    Camera c;if(!ok(oniInitialize(2003),"init"))return 3;
    OniDeviceInfo *list=nullptr;int count=0;
    if(!ok(oniGetDeviceList(&list,&count),"enumerate"))return 3;
    std::string uri;
    if(count>=0&&count<100)for(int i=0;i<count;++i)if(list[i].usbVendorId==0x2bc5&&list[i].usbProductId==0x060d)uri=list[i].uri;
    oniReleaseDeviceList(list);if(uri.empty())return 3;
    if(!ok(oniDeviceOpen(uri.c_str(),&c.device),"open")||!ok(oniDeviceCreateStream(c.device,OniSensorType(sensor),&c.stream),"create"))return 3;
    if(argc==6){
        const uint32_t exposure=std::atoi(argv[5]);
        if(exposure!=1000)return 2;
        int size=sizeof(c.saved_exposure);
        if(!ok(oniDeviceGetProperty(c.device,12,&c.saved_exposure,&size),"save_exposure")||size!=4)return 4;
        c.restore_exposure=true;
        if(!ok(oniDeviceSetProperty(c.device,12,&exposure,sizeof(exposure)),"set_exposure"))return 4;
        uint32_t value=0;size=sizeof(value);
        if(!ok(oniDeviceGetProperty(c.device,12,&value,&size),"read_exposure")||value!=exposure)return 4;
        std::cout<<"{\"exposure\":"<<value<<",\"saved\":"<<c.saved_exposure<<"}"<<std::endl;
    }
    const int w=hd?800:400,h=hd?1280:640;
    OniVideoMode mode{sensor==3?ONI_PIXEL_FORMAT_DEPTH_1_MM:ONI_PIXEL_FORMAT_GRAY16,sensor==3?w:h,sensor==3?h:w,fps};
    properties(c.stream);
    firmware_parameters(c.device,"before_mode");
    if(!ok(oniStreamSetProperty(c.stream,ONI_STREAM_PROPERTY_VIDEO_MODE,&mode,sizeof(mode)),"set_mode"))return 4;
    int mirror=0;if(!ok(oniStreamSetProperty(c.stream,ONI_STREAM_PROPERTY_MIRRORING,&mirror,sizeof(mirror)),"mirror"))return 4;
    properties(c.stream);
    if(!ok(oniStreamStart(c.stream),"start"))return 4;
    firmware_parameters(c.device,"started");
    using Clock=std::chrono::steady_clock;const auto start=Clock::now();auto first=start,last=start;
    uint64_t first_ts=0,last_ts=0;int n=0,gaps=0,regress=0,repeat=0,badclock=0,previndex=0;
    std::vector<uint8_t> previous;double valid_sum=0,min_gap=10,max_gap=0;
    while(Clock::now()-start<std::chrono::seconds(seconds)){
        int ready=-1;if(!ok(oniWaitForAnyStream(&c.stream,1,&ready,3000),"wait")||ready!=0)return 5;
        OniFrame *f=nullptr;if(!ok(oniStreamReadFrame(c.stream,&f),"read")||!f)return 5;
        auto now=Clock::now();
        const bool valid=f->data&&f->dataSize>0&&f->dataSize<=8*1024*1024&&f->width==h&&f->height==w&&f->stride>=h*2&&f->dataSize>=f->stride*w;
        if(!valid){oniFrameRelease(f);return 6;}
        if(!n){first=now;first_ts=f->timestamp;std::cout<<"{\"actual\":["<<f->width<<","<<f->height<<"],\"bytes\":"<<f->dataSize<<"}"<<std::endl;}
        else{double dt=std::chrono::duration<double>(now-last).count();if(dt<min_gap)min_gap=dt;if(dt>max_gap)max_gap=dt;
            gaps+=f->frameIndex>previndex?f->frameIndex-previndex-1:0;regress+=f->frameIndex<=previndex;badclock+=f->timestamp<=last_ts;}
        const auto *bytes=static_cast<const uint8_t*>(f->data);
        repeat+=previous.size()==size_t(f->dataSize)&&std::memcmp(previous.data()+16,bytes+16,f->dataSize-16)==0;
        previous.assign(bytes,bytes+f->dataSize);
        int nonzero=0;for(int y=0;y<w;++y){const auto *row=reinterpret_cast<const uint16_t*>(bytes+y*f->stride);for(int x=0;x<h;++x)if(row[x])++nonzero;}
        valid_sum+=double(nonzero)/(w*h);last=now;last_ts=f->timestamp;previndex=f->frameIndex;++n;oniFrameRelease(f);
    }
    rusage usage{};getrusage(RUSAGE_SELF,&usage);
    const double elapsed=std::chrono::duration<double>(last-first).count();
    std::cout<<"{\"summary\":true,\"frames\":"<<n<<",\"host_fps\":"<<(n>1?(n-1)/elapsed:0)
        <<",\"sdk_span_us\":"<<(last_ts-first_ts)<<",\"bad_clock\":"<<badclock<<",\"index_gaps\":"<<gaps<<",\"index_regress\":"<<regress
        <<",\"identical\":"<<repeat<<",\"mean_nonzero\":"<<(n?valid_sum/n:0)<<",\"host_gap\":["<<min_gap<<","<<max_gap<<"]"
        <<",\"cpu_user\":"<<(usage.ru_utime.tv_sec+usage.ru_utime.tv_usec/1e6)<<",\"cpu_system\":"<<(usage.ru_stime.tv_sec+usage.ru_stime.tv_usec/1e6)<<"}"<<std::endl;
    return n>1?0:5;
}

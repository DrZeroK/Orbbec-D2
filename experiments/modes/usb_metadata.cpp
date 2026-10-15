// Observe only this test process's completed USB transfers; never retain pixels.
#include <linux/usbdevice_fs.h>
#include <sys/ioctl.h>
#include <dlfcn.h>
#include <cstdarg>
#include <cstdio>
#include <cstdlib>
#include <ctime>
#include <fcntl.h>
#include <unistd.h>
static int output=-1;
__attribute__((constructor)) static void start(){
    const char *path=std::getenv("D2_USB_META");
    if(path)output=open(path,O_WRONLY|O_CREAT|O_EXCL|O_CLOEXEC,0600);
}
extern "C" int ioctl(int fd,unsigned long request,...) noexcept {
    using Function=int(*)(int,unsigned long,...);
    static auto original=reinterpret_cast<Function>(dlsym(RTLD_NEXT,"ioctl"));
    va_list args;va_start(args,request);void *arg=va_arg(args,void*);va_end(args);
    int result=original(fd,request,arg);
    if(output>=0 && result==0 && (request==USBDEVFS_REAPURB || request==USBDEVFS_REAPURBNDELAY) && arg){
        const auto *urb=*static_cast<usbdevfs_urb**>(arg);
        if(urb && urb->type==USBDEVFS_URB_TYPE_BULK && (urb->endpoint==0x81||urb->endpoint==0x82)){
            timespec now{};clock_gettime(CLOCK_MONOTONIC,&now);
            char line[128];int n=std::snprintf(line,sizeof(line),"%lld.%09ld,%u,%d,%d\n",static_cast<long long>(now.tv_sec),now.tv_nsec,urb->endpoint,urb->actual_length,urb->status);
            if(n>0 && n<int(sizeof(line)))write(output,line,n);
        }
    }
    return result;
}
__attribute__((destructor)) static void finish(){if(output>=0)close(output);}

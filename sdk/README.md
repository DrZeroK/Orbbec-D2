# D2 SDK · Linux ARM64 原生适配

适用于本项目实机 `Mx6000 TornadoD2 / RA3016 / firmware 5.8.23 / USB 2bc5:060d`。固定上游为 OpenNI 2.3.0.86 beta6 ARM64；源码模块版本0.2.0。采用独立版本目录，不覆盖系统运行库。

## 做了什么

- 专用`liborbbec.so`在原始文件偏移`0xf9dc2`将枚举PID `0300`替换为`060d`，只改变2字节；原始完整SHA256及45项表先验证。标准OpenNI客户端可直接发现D2，不需要Python内存补丁。这是D2专用副本，不再支持被替换的旧PID0300。
- `libd2sdk.so`提供小型C ABI。传入实际输出尺寸640×400时，底层深度请求400×640；返回两套尺寸，不把请求坐标冒充输出坐标。
- 复制并紧凑排列帧缓冲区，深度输出前8个样本置为无效零。原厂帧不被修改。由驱动旋转后覆盖原始16字节导致的无效样本不能恢复。
- 直接读取120字节原生标定，不依赖会返回假阴性的属性支持查询。返回原厂30个float，不猜测它们与旋转后图像、红外或UVC彩色的配准关系。
- 保留原始`sdk_timestamp_us`，另给`host_received_ns`。SDK时钟域始终标为未验证；相等/倒退时间戳、帧号问题与相邻完全相同图像另列flags，不伪造设备时钟。主机接收时间不是曝光时间。
- 稳定模式列标准毫米／0.1毫米深度和GRAY16红外640×400@30声明。experimental查询包含高清5fps，以及仅在USB连接速率≥5000M时提供的高清30fps；不把通用驱动的IR60枚举当D2官网承诺。SDK声明fps不是本机实测fps。
- USB3高清30fps深度流关闭该流的软件滤波并回读确认，帧flags设置`D2_SOFTWARE_FILTER_DISABLED`。X5默认软件滤波的高清实测约14.5fps，关闭后约30fps；标准模式仍使用原滤波配置。此差异需在测距/人脸实物验收中评估。
- 高清流限单路使用。实测高清深度＋高清IR同时启用会在原驱动中超时并触发底层USB异常，适配层在配置第二路前拒绝所有涉及高清的双流组合。深度＋IR联合使用采用已验收的标准模式。

上游闭源核心和固件未重写。早期USB2高清约7.25fps；本机改为USB3后直接请求高清30fps已实测约30.16fps，因此不能把USB2结论推广到USB3。固件模式表仍列高清5fps，新适配层明确标注USB3实验模式，不修改固件或枚举原始表。没有启用几何配准、曝光硬同步或活体判定。RGB仍走独立UVC接口。

## 构建

先在电脑或X5生成一个全新的包目录。`--upstream`必须是原版`Include/`及`libs/`的父目录；`--platform-headers`用同版本官方SDK的通用头补齐该ARM压缩包遗漏的OniPlatform/OniVersion/Linux头，不使用Windows二进制。已有包目录会拒绝覆盖。

```bash
python3 package.py --upstream /path/to/original/sdk \
  --platform-headers /path/to/matching/official/Include \
  --output /path/to/new/d2-package
cmake -S . -B /path/to/new/build -DD2_PACKAGE=/path/to/new/d2-package -DCMAKE_BUILD_TYPE=Release
cmake --build /path/to/new/build -j2
ctest --test-dir /path/to/new/build --output-on-failure
```

模块只使用系统编译器和上游OpenNI。`package.py`保留原运行库并生成SHA256清单，输出`lib/`、`include/`；原生构建再加入`lib/libd2sdk.so`、`bin/d2_probe`。上游原有头文件的版权和许可注释保留。打包脚本不安装软件、不改udev、不重启服务。

## 独立探针

先确认相机无人占用，并与项目的`wheelchair-face-camera.lock`协调；不要与正式人脸采集争用。普通用户没有USB写权限时，适配器会在打开原生设备前明确拒绝，避免旧SDK的权限失败崩溃。现有环境仅在有外层timeout的独立测试子进程中使用sudo，不把整个UI提权。

```bash
timeout 15s /path/to/d2-package/bin/d2_probe --native-enumerate
timeout 25s /path/to/d2-package/bin/d2_probe 10 dual
timeout 25s /path/to/d2-package/bin/d2_probe 10 depth
timeout 25s /path/to/d2-package/bin/d2_probe 10 ir
timeout 25s /path/to/d2-package/bin/d2_probe 10 hd
timeout 25s /path/to/d2-package/bin/d2_probe 10 hd30
```

探针仅输出数值统计，不保存图像或做人脸识别。`--native-enumerate`直接调用原OpenNI C API来验证磁盘驱动适配；其他命令验证新增C ABI。返回flags必须由上层检查；此库不会据“收到帧”就给出身份、防伪或安全避障结论。

Python调用示例在`examples/capture.py`，仅用标准库ctypes加载原生`libd2sdk.so`，无需原来的内存修补加载器：`python3 examples/capture.py /path/to/d2-package 10`。这只是采集示例，不包含自动鉴权、人脸或防伪逻辑。

## C接口

见`include/d2sdk.h`。单进程单context、单调用线程；先`d2_open`、查询模式／标定、`d2_configure`、`d2_start`，再循环`d2_read`，最后`d2_close`。不保存或上传图像。返回data由SDK持有，直到同sensor下一次read或close失效；调用方需要长期持有时自行复制。

`D2_FIRST_EIGHT_DEPTH_SAMPLES_INVALID`和`D2_NATIVE_GRID_DIFFERS`是正常D2输出说明。`D2_TIMESTAMP_UNVERIFIED`始终存在；`D2_TIMESTAMP_NONINCREASING`、`D2_COUNTER_NONINCREASING`、`D2_COUNTER_GAP`、`D2_IDENTICAL_CONTENT`需由调用方根据用途拒绝或报告，不可绕过正式鉴权/PIN逻辑。`D2_SOFTWARE_FILTER_DISABLED`表示USB3高清30fps深度采用未滤波输出。此SDK不提供未经实物验收的深度到IR或RGB坐标转换。

公开逆向说明见仓库docs/reverse-engineering，实测摘要见evidence与docs/performance.md。厂商二进制不随源码再分发，使用者须自行取得；构建工具不会自动部署或重启服务。

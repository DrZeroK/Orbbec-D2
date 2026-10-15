> 历史研究记录（2026-10-13～15）。描述当轮状态；最终状态以仓库根 README 为准。工作区路径已脱敏，未公开的原始归档项见资料清单。

# D2 高清约7fps：离线参数与传输追踪

日期2026-10-15。只读ARM64原厂库，SHA256 `24e43298e83d74bb3ce8dcf3ca28979e6334603f9d0534542aa5891cc6764e4b`；未操作相机、未改SDK或服务。新会话证据见 `hd_transport_8f4c2d1a_evidence.json`，前轮后处理证据在 `driver_rea_evidence.json`。Ghidra地址比ELF符号值增加0x100000。

## 可以确定的路径

1. `SetVideoMode` 0x1311b8 在选择输入格式时按宽高匹配，不在该循环比较fps；随后把实际传入fps写入属性0x1080ff20并批量配置。证据 `ev_9d415c9496283760aa6535b64cc4c5c91389f2424a4f0f75cf7e84ba344b259a`。`XnSensorDepthStream::BatchConfig` 0x1709b0直接转helper，后者在停止态调用模块属性配置。证据 `ev_793d8d1159e62116969de33becef1e1a553a15b8b3d97895810ba5f5d642f7b6`、`ev_0d905a659d92c1c913e2fdb4e90f92ce8f1caff86952b1bccd7db2096f5313ac`。因此公开OniVideoMode请求HD30是否会被接受，值得隔离实测，无须先改枚举fps或绕过模式校验。

2. 深度SetFPS 0x16d850走BeforeSettingFirmwareParam、FrameStream本地值更新、AfterSettingFirmwareParam；启动时ConfigureStreamImpl也明确ConfigureFirmware(FPS)。证据 `ev_d890dc4ce7847ef8a05d8365ce83a2a842aafd5b0fbd92851f748c61cdfff16c`、`ev_17c76324616b8ea1b2b8481210d0bfd5a93f0ce410e86d6b9c267155039792a5`。它并非仅修改对外枚举数字。映射函数0x16d520将深度格式/分辨率/fps对应至固件对象；FirmwareParams构造和Init给出命名与固件索引。证据 `ev_562398d9dca4ae641bb8c04723f49cd2e8fd3044ee3795a1507fe26ff0c95f27`、`ev_30a5af47f7e07b55a2bd8eb0a19f80d5503713eb6dfb896c5e10e5b30ae43131`、`ev_b22eb71c0eb5ae4ffdb6b40508a6055e8abb33ef6a1a2b0adc9549990ff63a09`。

3. 对PID060d/061f/0613，`XnSensorDepthStream::SetInputFormat` 0x16d8c8无条件强制InputFormat=2（10bit），同时设置0x3ff上限及另一参数4，再走正常固件参数配置。证据 `ev_db72ed443edcc260d963dbd53158fc9eba8370cfa7b7ab5f46eb3aa1c60e34d8`。故扫描Depth InputFormat=0/3/4不会提供另一条受支持的D2路径，不应二进制绕过此保护。

4. USB打开函数0x14d528先按固件支持的alternative interface设置，再打开depth81、IR82（旧设备分支另有回退）。不会创造设备描述符不存在的ISO或USB3能力。证据 `ev_163cdb5febfc0fd162eec5a1cead224fdc462eb8b02c7377db9489585ec8205b`。独立运行方已报告该实物只有USB2 BULK81/82，所以不建议ISO/USB3试错。

5. Linux读线程0x186c10使用异步libusb transfers，但对完成buffer的协议/图像处理回调在读线程内同步调用，回调返回后才resubmit该transfer。没有观察到按请求FPS主动sleep或节流。证据 `ev_0d04e748c808a196c180d6dbf2f8b2816a0690d8690282ae3f12ed92adfbba2c`。CPU后处理可能减少可排队buffer，但尚不能把它当作本机7fps根因。

6. 帧号并非原始设备曝光计数：MarkWriteBufferAsStable 0x1298f8将内部计数加1并写到OniFrame.frameIndex。证据 `ev_863350893138cf30cabe1937fe477fa49b64149873c5d397b83d4bd7fedafbaa`。“无frameIndex缺口”只表示应用未漏读已完成输出帧，不能排除USB损坏帧被驱动丢弃。

## 可只读核对的固件状态

Sensor构造0x145d88注册general属性0x1080e001 `FirmwareParam`。GetFirmwareParamCallback检查buffer恰为4字节，再将其前uint16当索引、后uint16当返回值，调用XnHostProtocolGetParam。Get路径不写状态。证据 `ev_4bec2a2a1d25c7e15bc0acc9044ff6a648ec3f4b557c290b609ac7e840c293b7`、`ev_4ac09e4435543891b38bf9f324e929db5090282ea830aac98792eec583f29177`。

最小对照：以`{uint16_t param,value}`、size=4调用`oniDeviceGetProperty`，仅读以下已确认项，分别在标准30和HD5 start前/后记录：

| 索引 | 含义 |
|---|---|
| 0x12 | DepthFormat |
| 0x13 | DepthResolution |
| 0x14 | DepthFPS |
| 0x19 | IRFormat |
| 0x1a | IRResolution |
| 0x1b | IRFPS |

这能区分“SDK缓存写5但设备未接受/重解释”与“设备参数也是5而物理输出约7.25”的情况。返回值仍不能单独证明曝光频率。禁止对该general属性调用Set作为试错手段。

## SoftFilter排除实验与边界

原始ini确实启用`[Depth] SoftFilter=2`。Init 0x16f4b8读取该项，证据 `ev_ab4a64a2e065760e3c26321dfdfcc343cfec0b9f064babc9de716f6f2a500cdf`；0x167e00先无条件复制源buffer，再依据SoftFilter调用filter，继续相同转换、旋转和帧完成。SoftFilter=0没有early-return或漏填帧的明显静态分支。前轮证据 `ev_ff1fec84ed521bb6176c6f2b069e71f7fbc895443e521e85547467034cd72144`。

因此可在全新隔离副本仅改SoftFilter=0作为host负载排除实验，保留原副本与全部其他参数。官方本地`OpenNI_0400_API.md`也警告软件滤波可影响接收。若无帧，需看corrupt/packet-loss/USB transfer日志及实际加载路径，不应直接宣称SoftFilter0导致D2固有漏帧，更不能据未成功实验宣布已提速。

现有历史modes.csv显示IR高清三个输出格式都约7.23–7.27fps，深度约6.90fps；IR不走深度SoftFilter。因此公共传感器模式/传输节奏假设比单纯深度滤波根因更强，但仍是待验证假设。运行方本轮已报告HD约7.25666fps、CPU约35%单核，更削弱纯CPU饱和解释；该运行证据应以主代理保存的原始日志为准。

## 最小可验证假设与实验顺序

1. **输入模式5被设备映射到固定高清读出节奏**：先做上述六项只读回读，同时比较HD IR单路与HD depth单路、启用SDK丢包日志。若两路独立都约7.25且无底层包错误、CPU未满，说明约束在主机算法之前的可能性较高。
2. **host滤波有增量开销但不是共同7fps根因**：隔离SoftFilter0与2，仅比较fps/CPU/corrupt日志。保留两份配置，不修改共享SDK。
3. **官网HD30可用但旧固件枚举只列5**：正常OpenNI SetVideoMode(深度800x1280、fps30)可作为明确标注的实验，记录返回码、start后设备FPS回读、实际尺寸、host吞吐和包错误。若拒绝即停止；不能修改支持表强行接受，不能通过改reported_fps作成功证据。

尚未证明究竟是固件、CMOS读出、USB吞吐还是SDK包解析限速。未发现固件内部代码，无法解释5为何稳定输出约7.25。不得猜写CMOS寄存器、blanking、laser/APC、硬同步或固件参数；不得刷新固件或改正式服务。禁用滤波会改变深度噪声特性，任何提速都须重新做几何/噪声验收，不能直接上线。

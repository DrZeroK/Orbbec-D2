> 公开整理更正：微软样例实际随附MS-PL，不是MIT；见根THIRD_PARTY_NOTICES.md。本记录不意味着Hello登录已完成。

> 历史研究记录（2026-10-13～15）。描述当轮状态；最终状态以仓库根 README 为准。工作区路径已脱敏，未公开的原始归档项见资料清单。

# D2 Windows Hello 适配研究

2026-10-14～15，设备为 Mx6000 TornadoD2，深度 USB 2BC5:060D、RGB 2BC5:0505，Windows 11 Pro build 26300。

**公开官方渠道没有找到匹配这台 D2 的 Windows Hello 驱动。已自行编写真实红外适配组件，并经 Windows 相机服务读取实际图像；当前仍未实现 Windows Hello 注册或登录。** 基础红外取流、系统相机源加载、Hello 认证是三个不同的验收步骤，不能互相替代。

## 官方驱动检索

| 渠道 | 结果 |
| --- | --- |
| [D2 官方页](https://www.orbbec.com.cn/index/product/info.html?cate=38&id=31) | 介绍人脸数据采集和活体检测应用，未声明 Windows Hello 支持 |
| [OpenNI 官方下载](https://www.orbbec.com/developers/openni-sdk/) | 4.3.0.22 USB 传输驱动；本机 060D 使用 obdrv4.sys、Orbbec 专有类，未注册 Windows 相机接口 |
| [微软 Update Catalog](https://www.catalog.update.microsoft.com/Search.aspx?q=orbbec) | 查到 5 个历史奥比包，最高 4.3.0.7，面向 HP Sprout/3D Capture Module；无 060D/0505 匹配记录 |
| 微软历史 CAB 内容 | 已下载、只读解包，CAT 签名有效；只列 0400/0405/0300/0406/0301，同样为 USB 传输驱动，未安装 |
| [官方 Sample-HelloOrbbec](https://github.com/orbbec/OrbbecSDK/blob/main/examples/cpp/Sample-HelloOrbbec/README.md) | 普通 SDK 初始化和枚举示例，与 Windows Hello 登录无关 |

原厂 GitHub 公共仓库及部分完整树已检索；未认证 API 限流影响了部分后续树查询，不声称遍历了所有历史包或私有 OEM 软件。完整 URL、网页、源文件、INF、包哈希与查询失败记录见 official_sources/findings.json（原始归档项）。

## 已实现的代码与二进制

源代码和运行方法：driver/README.md（原始归档项）。

- D2Capture.cpp（原始归档项）：原生 C++ 调用官方 OpenNI，核验原 DLL SHA-256、限定进程内枚举修复，只读真实 D2 红外图像；10 位 GRAY16 固定映射到 L8，未用录制/合成画面代替相机。使用进程级独占租约，停止时清理 SDK 并恢复枚举表。
- D2MediaSource.cpp（原始归档项）：Media Foundation COM Custom Media Source，IMFMediaSourceEx、IMFMediaStream2、IKsControl、事件及 Start/Stop/Shutdown。输出 L8 640×400@30；样本时间戳是读完时的 QPC，不冒称传感器曝光时刻。
- D2MediaSource.dll（原始归档项）：已生成的 x64 用户态适配 DLL，**不是已签名、可正式安装的 Hello 驱动包**。
- test_consumer.cpp（原始归档项）：无需管理员或系统注册即可直接消费真实相机源，验证帧、事件、停止、重启、并发拒绝与引用释放。
- `driver/stub/`：UMDF 2 相机接口注册源码与 INF 草案；没有 WDK 构建结果、完整发行包及微软签名，不能当成可安装驱动。

原始微软 SimpleMediaSource 参考示例另存 `architecture/official_sample/`，固定 commit `2dc3fd3a0cc84a2933f2194e7ec0871584979071`，29 个文件 Git blob SHA-1 校验通过，保留 MIT 许可。当前用户态实现只使用已安装的 VS BuildTools 和 Windows SDK，不依赖 WIL、NuGet 或内核驱动。

## 实机验证

| 测试 | 结果 |
| --- | --- |
| 真实红外 Media Foundation 样本 | 第一轮 90 帧、第二轮重启 5 帧，640×400，每帧 256000 字节，非恒定/非零图像 |
| 稳定输出帧率 | 最终复测第一轮约 30.173 fps，重启后约 30.257 fps |
| Start 到首帧 | 最终复测 388.635 ms；重启后 326.997 ms。这仅是直接消费者测试，未代替 FrameServer/HLK 延迟验收 |
| 并发源 | 第二个源 Start 返回 ERROR_BUSY，关闭第二个源后第一个仍能正常读帧 |
| 停止/关闭 | 停止后拒绝样本；Shutdown 状态与 COM 引用释放检查通过 |
| COM 激活器 | IMFActivate、IMFAttributes、IMarshal、缓存对象身份、属性传递通过；释放激活器后相机源仍可使用 |
| 直接 MFSourceReader | 30 张真实 IR 图像，每张 256000 字节，通过 |
| Windows 相机服务 | 临时 Sensor Camera 创建、激活、MFSourceReader 读取实际 256000 字节图像全部成功；随后 Remove 成功 |
| Hello 属性 | 当前不发布 FACEAUTH_CAPABILITY/FaceAuth Profile；相关模式请求明确拒绝，避免把未验证能力报给认证系统 |

证据：consumer_final_20261015.log（原始归档项）、activation_final_20261015.log（原始归档项）、source_reader_final_20261015.log（原始归档项）、system_source_machine_probe.log（原始归档项）。

管理员只读检查确认：Hello.Face.20134 组件为 Installed（DISM PackageFeatureState=4），安全启动开启，无已连接 Biometric 设备；WbioSrvc 当前停止、手动启动。并未启动服务、安装驱动或变更启动安全设置。证据：hello_admin_status.json（原始归档项）。仅凭没有 Biometric 类设备不能单独判断摄像头兼容性，实际相机接口和配置仍须单独核验。

## 照明同步的实际阻塞点

Windows Hello 的 [FACEAUTH_MODE 接口](https://learn.microsoft.com/en-us/windows-hardware/drivers/stream/ksproperty-cameracontrol-extended-faceauth-mode) 要求真实逐帧 IR 明暗交替并提供相应信息，或者输出实际扣除环境 IR 的图像。普通红外图像、深度图或随意设置能力标志不能满足这个要求。

已用公开 OpenNI 属性进行有限测试：

1. 泛光状态、泛光强度和 depth/IR mode 的 GET，在 1/2/4/8/16/64 字节查询中均返回 4（BAD_PARAMETER）。这只能证明当前 SDK 调用未成功；不能据此断言模组绝对没有相关硬件。SDK 的“支持属性”标志在这些接口上也不能等同于可用。
2. 临时 0/1 切换实际影响红外图像：稳定场景亮帧平均约 7.06 L8、暗帧约 0.027，稳定部分约 30.116 fps，控制调用小于 0.95 ms。逆向与运行跟踪确认 SET opcode=42、GET opcode=134，固件稳定 GET 原始值为 OFF `0x6400`、ON `0x6401`。原 SDK 在 RVA `0x2D9FC` 用整个 DWORD 与 1 比较，导致稳态读错；适配组件在固定哈希、校验指令后，仅进程内将比较改为低 BYTE。高位的具体含义尚未知。测试 ON/OFF/ON/OFF 四段各 30 帧，公开 getter 均与请求相符；结束后恢复并回读通过。最新代码在首个写命令前读取修复后的真实原状态，并在命令尝试前标记待恢复；Stop 撤销指令修复。磁盘 DLL 未修改。
3. 稳定读流时亮度对应上一次请求。但每 30 次调用插入 120 ms 延迟后，SDK frameIndex 跳 3–4 帧，样本 31、61、91 的亮度与简单上一请求映射不符。仅凭读取次数或奇偶帧推断照明，会写出错误信息。

证据：lighting_alternation_summary.json（原始归档项）、lighting_delayed_summary.json（原始归档项）、emitter_analysis.json（原始归档项）、emitter_state_wire_trace.jsonl（原始归档项）、lighting_state_fixed.stderr.log（原始归档项）。该实验说明发射器可控，但当前 getter 表示控制状态，并非曝光时帧信息。后续需研究真实协议帧标记或可验证的同步控制，并对丢帧/重启恢复作验收；简单固定“一帧延迟”补丁不够。

泛光属性已进一步只读追踪：SDK 的 subcommand support 查询对 opcode `0x96` 的 subcommand 0/1 均返回 `0x307F9`。仅诊断进程中跳过这一读取前置检查后，真实 GET `0x96` 获得成功 ACK、但有效回复为 0 words，仍不够构成状态值。因此不能把当前 SDK 的 advertised 标志当成泛光已可用，也不能据此证明模组物理上没有泛光。未发送未知泛光写命令。证据：flood_firmware_trace.jsonl（原始归档项）、flood_read_gate_bypass_trace.jsonl（原始归档项）。

### 连续采集与背景扣除实测

test_background.cpp（原始归档项） 已实现独立连续采集线程、实际 ON/OFF 控制、相邻图像逐像素 `max(active-ambient,0)`、时间戳/编号断续检查、丢帧后丢弃配对与重新等待、120 ms 慢消费者，以及原状态恢复验证。输出真实差图和每个原始帧的当前请求、当前 getter、推断照明及平均亮度。它是受限硬件实验，不发布 Hello 能力。

| 150 对图像的实验 | 原始 fps | 差图 fps / 30 间隔最低 fps | 结果 |
| --- | --- | --- | --- |
| 连续工作线程、简单一帧延迟配对 | 30.1623 | 15.0842 / 15.0683 | 150/150 对 active 均值大于 ambient；慢消费者丢 70 个输出，采集未受拖慢；只证明此固定时序场景 |
| 随机 0～20 ms 控制延时，加一次 120 ms 采集延时 | 29.8575 | 14.7807 / 13.6843 | 仅 90/150 对正信号；包含编号连续却明暗反相、两帧均亮/均暗。检测到 1 次丢对并重新等待，仍无法检测所有错配 |
| 每相位丢弃一张过渡图，四次读取产生一张差图 | 30.1584 | 7.5391 / 7.5367 | 150/150 对正信号，0 丢对；帧率不足 15 |

三组实际照明初态均为 ON，Stop 后另开相机再读仍为 ON，恢复验证成功；初态 OFF 尚未覆盖。压力实验的采集结束码 0 只表示运行/保存成功，不能解释为质量或 Hello 验收通过。稳定基线的 15 fps 已被压力试验揭示的相位不确定性限制，不能据此发布 BGS/FaceAuth。

证据：background_findings.json（原始归档项） 汇总原始证据的 SHA-256 和连续帧反相案例；基础日志（原始归档项）、压力日志（原始归档项）、等待过渡帧日志（原始归档项） 及同目录 CSV、原始逐帧 CSV 和 PGM 图像全部保留。

### 硬件交错模式与原始帧信息

官方 `PS1080.h` 的 `OBDepthIrMode=3` 描述散斑 IR/纯 IR 交错，是硬件同步路线的候选。对当前设备只读跟踪确认：SET opcode=159、GET=160，GET160 返回成功 ACK，但 payload=0 words；SDK 因缺少 4 字节模式值返回 `0x10001`。因此无法读取/保存原模式，没有发送 SET159，也没有把其他型号的协议猜测写入固件。

公开 `OniFrame` 没有曝光时照明状态；已识别的 12 字节原始包头包含 magic、packet type、packet sequence、size、timestamp，没有发现可可靠标注 ON/OFF 的字段。SDK frameIndex 为主机 buffer manager 计数，IR 时间戳在某些状态下也来自主机，二者均不能冒充曝光编号。部分 IR 处理分支存在额外 8 行等布局，其含义尚未解码，故不能断言原始流绝无隐藏信息。

证据：ir_metadata_analysis.json（原始归档项）、GET160 运行记录（原始归档项）。完整 REA 证据包 ir_metadata_analysis_evidence.json（原始归档项） 保留地址和证据 ID，包含包解析 `0x18001FBF0`、IR EOF `0x180033490`、模式 GET `0x1800301C0`、SET `0x1800300E0`。后续突破需要厂商可用的同步协议、固件/SDK 或明确的曝光照明字段；目前实验不够支撑正式登录。

## 系统集成与正式登录的要求

[微软 Custom Media Source 文档](https://learn.microsoft.com/en-us/windows-hardware/drivers/stream/frame-server-custom-media-source) 明确支持在专有驱动上增加相机源与 stub 的架构，也说明其受信安装包要求。其 Hello 路线要求 IR 至少 340×340@15，以及正确的 FaceAuth DDI/Profile；D2 的 640×400@30 尺寸和帧率符合数值门槛，尚不能推出认证兼容。

临时相机使用 CurrentUser、Session 范围；COM 源需在机器级临时注册，用户级 COM 注册未被系统相机服务正确发现。先后修正 COM 激活器生命周期、跨线程封送与自有样本分配；最后还修正探针把正常 STREAMTICK（时钟事件、暂时无图像）误判为失败的问题。最新机器级试验已创建并激活 Sensor Camera，MFSourceReader 实际读到 256000 字节图像，HRESULT 全部为 S_OK，Remove 成功。机器级与用户级专用 CLSID 均已检查不存在。未持续安装相机，成功读取仍不能代替 Hello 注册/锁屏测试；失败历史日志原样保留。

正式驱动还需满足 [相机 Hello bring-up/HLK 要求](https://learn.microsoft.com/en-us/windows-hardware/drivers/stream/windows-hello-camera-driver-bring-up-guide) 和 [驱动签名要求](https://learn.microsoft.com/en-us/windows-hardware/drivers/dashboard/code-signing-reqs)。编译成功或管理员权限不能生成微软认证与签名。当前尚无可供正式安装的完整、已认证驱动包。

微软的 [ESS 文档](https://learn.microsoft.com/en-us/windows-hardware/design/device-experiences/windows-hello-enhanced-sign-in-security) 另涉及隔离的硬件通路；普通外接 SDK 桥接不能据此承诺 ESS 支持。没有修改 ESS、Secure Boot、测试签名模式、PIN 或账户凭据。

最初 Windows REA server 没有可用原生分析引擎，记录在 rea_session_status.json（原始归档项）；随后通过已配置的 Linux REA/Ghidra 12.1.4 对同一哈希 DLL 完成分析，并结合独立进程 Frida 实际运行跟踪核对控制请求与回复。完整发射器证据包为 emitter_analysis_evidence.json（原始归档项）。主要证据 ID：GET `ev_2a6b533ab0669aba9cf44b7e07fb40040a9e128970e7ebe3cb311ee0aba6ab47`；SET `ev_6df3554cc7133d4116d0d4d217db7ce28c410a1181231b32d16c7093e8a71d30`；共享请求发送器 `ev_1a20f6e1807134a2eb15f66250bbe22b1707e10327811e50e46c90a87ff81d2c`。静态逆向只证明代码行为，实际回复与亮度来自运行记录。

当前没有声称这台 D2 已可用于 Hello。Windows 相机服务读取红外的链路已打通；剩余工作是可靠照明同步或真实背景扣除、FaceAuth DDI/Profile、登录所需的持久设备注册与必要的 RGB/IR 组合、认证驱动包及实机登录验收。未知项不能通过伪造能力标志或冒充设备签名解决。

最终复查记录：final_verification_20261015.json（原始归档项）。90+5 帧直接相机源、激活器及 30 帧 SourceReader 再次通过；深度重新接收 30 帧并包含有效像素，当前场景中心无有效深度，未新增尺量验收。原 SDK 及构建目录 SDK 哈希仍一致，临时 HKLM/HKCU CLSID 不存在，工作区 `wh check` 为 PASS。所有 REA 分析会话已关闭，未留下持续取流实验。

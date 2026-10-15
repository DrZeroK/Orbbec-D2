> 历史研究记录（2026-10-13～15）。描述当轮状态；最终状态以仓库根 README 为准。工作区路径已脱敏，未公开的原始归档项见资料清单。

# D2 SDK 驱动与开发资料

资料日期：2026-10-13。优先路线是核对实物和固件后尝试厂家匹配的 **OpenNI2 SDK**。当前证据足以确认官方文档曾为 D2 给出配置示例，尚不足以承诺任一通用安装包能适配所有 D2 版本。

## 软件路线选择

| 路线 | 已核对内容 | 对 D2 的结论 |
| --- | --- | --- |
| 厂家／卖家随设备提供的包 | 需对应实物型号、固件和平台 | 首选，应索要可复现的取流示例 |
| Orbbec OpenNI2 SDK | 官方 Android 文档有 D2 深度和 IR 示例；C++ 文档提到 D2 打包格式；有 Linux ARM64 发布包 | 有明确历史开发线索，适配当前实物仍需验证 |
| Orbbec SDK v1 | 兼容部分旧 OpenNI 协议设备；公开设备列表未列 D2 | 不能仅凭“支持 OpenNI”认定 D2 支持 |
| Orbbec SDK v2／Viewer v2 | 官方说明不再支持旧 OpenNI 协议设备；公开列表未列 D2 | 不作为默认 D2 开发路线 |
| OrbbecSDK ROS2 main 分支 | 旧协议设备路线，文档支持 Humble；设备表未列 D2 | 只能作为候选封装，先确认底层 SDK 识别 |
| OrbbecSDK ROS2 v2-main 分支 | 面向 SDK v2；默认分支 | 不因默认分支较新就直接用于 D2 |
| ros2_astra_camera | 旧 OpenNI ROS 2 驱动参考，README 示例采用 Galactic | 不能把 Astra 启动文件改名就当作 D2／Humble 适配完成 |

来源：[OpenNI SDK](https://github.com/orbbec/OpenNI_SDK)、[SDK v1](https://github.com/orbbec/OrbbecSDK)、[SDK v2](https://github.com/orbbec/OrbbecSDK_v2)、[ROS2 main](https://github.com/orbbec/OrbbecSDK_ROS2/tree/main)、[ROS2 v2-main](https://github.com/orbbec/OrbbecSDK_ROS2/tree/v2-main)、[ros2_astra_camera](https://github.com/orbbec/ros2_astra_camera)。各 README 已保存离线快照。

注意名称：**OpenNI 2.3.x** 与 **Orbbec SDK v2.x** 是不同产品线，版本前缀都有“2”不表示可互换。D2C 表示深度到彩色的对齐，也不是 D2 摄像头型号。

## 中文手册中的 D2 证据

| 手册 | 页码 | 相关内容及用法 |
| --- | --- | --- |
| `官方原始资料/OpenNI_中文Android接口规范_v3.1.pdf` | 12／35 | D2 示例先枚举模式，再选择宽 400、高 640 和 `DEPTH_1_MM` |
| 同上 | 13／35 | D2 IR 示例写宽 640、高 400 和 `GRAY16`；与深度宽高顺序不同，必须按实物枚举结果检查 |
| `官方原始资料/OpenNI_中文C++接口规范_v1.0.2.pdf` | 38／44 | 深度输入打包格式注释指 D2 使用 10-bit，即 `InputFormat=2`；紧邻通用示例仍写 `InputFormat=3`，不能照抄整个模板 |

手册由[官方 OpenNI 仓库 Chinese 目录](https://github.com/orbbec/OpenNI_SDK/tree/a640cb3724f323dc83d410d0550b5d504894db8a/Doc/Chinese)取得；上述关键页已提取并核对。英文版相关内容见[官方 API](https://github.com/orbbec/OpenNI_SDK/blob/a640cb3724f323dc83d410d0550b5d504894db8a/Doc/English/0400_API.md)。

这些内容主要来自历史接口说明。尤其 Android 文档中的具体调用方式不应直接复制到 Linux C++。`InputFormat` 是固件到 SDK 的数据打包配置，**不是**应用层深度像素的物理单位，也不意味着输出只有 10 bit 的测距精度。

## 已下载的 SDK

官方发布入口：[OpenNI v2.3.0.86-beat6](https://github.com/orbbec/OpenNI_SDK/releases/tag/v2.3.0.86-beat6)。注意官方 tag 拼成 `beat6`，资产文件名使用 `beta6`。包名中的 `20221011` 与 GitHub 上的发布／上传日期是不同概念，不应称为“2026 新 SDK”。

| 本地文件简写 | 用途 | 核对结果 |
| --- | --- | --- |
| `...beta6_arm64.zip` | Linux ARM64 候选 | 外层 ZIP CRC 通过；内部仅有 `066797_OpenNI_2.3.0.86_202210111155_4c8f5aa4_beta6_a311d.rar`，属于需要进一步核对的平台包 |
| `...beta6_windows_x64.zip` | Windows 首轮取流验证 | ZIP CRC 通过；包含 OpenNI 库、样例与运行时内容 |
| `openni-device-windows-driver-4.3.0.22.zip` | Windows 旧协议传感器驱动 | ZIP CRC 通过；内有 `SensorDriver_V4.3.0.22.exe`；下载 SHA-256 与发布页标注一致 |

ARM64 内层为 RAR5。本机 Windows `tar` 尝试列目录返回 `Header CRC error`，因此**本次未验证该内层包的可解压性及运行库**；这不能单凭一次工具错误判定厂商包已损坏。接入前用支持 RAR5 的工具检验；若仍失败，应向厂家索取直接的 Linux ARM64 SDK。

Windows 包所带 `samples/samples/ThirdParty/OpenNI2/arm/Arm64/` 中，`libOpenNI2.so` 和 `liborbbec.so` 的头部均为 ELF64、AArch64（机器号 183）。这只是归档内容核对，既未执行这些库，也未证明它们与 X5 系统 ABI、D2 固件兼容。不要跨包混拷不同版本的库和插件。

## 最小取流验证顺序

1. **登记设备**：型号标签、USB VID/PID、SN、固件、连接速度、SDK 完整版本。
2. **枚举而不是猜模式**：查看设备包含哪些传感器，再读取各流支持的宽、高、帧率和像素格式。
3. **先取深度单流**：使用 SDK 自带示例；初始候选是枚举中存在的 400×640 @ 30 fps。记录真实帧率、时间戳、无效值比例和报错。
4. **检查尺度**：面对已知距离的平面，用原始深度数据核对单位。`DEPTH_1_MM` 和 `DEPTH_100_UM` 不可用同一换算常数。
5. **再取 RGB 与 IR**：确认是否走同一 SDK 接口、是否有独立 UVC 通路、哪些流能并开。RGB 单独能显示不证明深度可用。
6. **检查对齐及点云**：读取匹配当前模式的内参、畸变和 RGB／深度外参；先查询配准能力，再启用支持的配准方式。
7. **最后接 ROS 2**：原生 SDK 长时间取流稳定后，才验证 ROS 驱动、话题和 TF。

OpenNI 的设备、流、帧、坐标转换及错误处理可查[官方代码样例](https://github.com/orbbec/OpenNI_SDK/blob/a640cb3724f323dc83d410d0550b5d504894db8a/Doc/English/0200_Code%20samples.md)及[知识说明](https://github.com/orbbec/OpenNI_SDK/blob/a640cb3724f323dc83d410d0550b5d504894db8a/Doc/English/0300_SDK%20knowledge%20base.md)。验证时应保留 SDK 返回错误码，不用黑画面或全零图静默代替错误。

## Linux 与 RGB 通路

官方 OpenNI 安装说明列出 Linux x86、ARM、ARM64 平台，运行时需要配套的 `libOpenNI2.so`、`OpenNI2/Drivers/liborbbec.so` 及配置文件。该说明不能代替 D2 型号支持表，也不能证明 Ubuntu 22.04／RDK X5 已通过验证。[官方安装说明](https://github.com/orbbec/OpenNI_SDK/blob/a640cb3724f323dc83d410d0550b5d504894db8a/Doc/English/0100_Installation.md)

官方 FAQ 说明，旧 OpenNI SDK 对使用 UVC 的彩色通路需借助 OpenCV／libuvc 等另行获取。D2 的彩色通路是否如此，须查实物描述符和厂家说明；D2 Pro 的 UVC 特性不能自动套给 D2。[官方 FAQ](https://github.com/orbbec/OpenNI_SDK/blob/a640cb3724f323dc83d410d0550b5d504894db8a/Doc/English/0500_Product%20Support.md)

上游安装文档包含 `sudo apt`、运行安装脚本、修改 USB 权限和较宽松的 `chmod` 示例。本工程板端有单独的部署规则，不应原样批量执行；资料下载也不构成板端安装授权。

## 常见现象的检查方向

| 现象 | 优先检查 |
| --- | --- |
| 只有彩色，没有深度 | 型号及固件支持、深度设备是否枚举、Windows 传感器驱动、Linux USB 权限、匹配的 OpenNI 插件 |
| SDK 找不到设备 | USB 数据线与实际连接速度、设备占用、VID/PID、库架构、SDK／固件组合 |
| 深度花屏或数值异常 | 枚举得到的模式、输入打包格式、输出单位、行步长；核对 D2 的 10-bit 打包说明 |
| 深度图转向或镜像不对 | 原始宽高、SDK 镜像设置、物理安装方向；不要仅改 UI 画面掩盖坐标错误 |
| 目标 RGB 位置对应错误距离 | RGB 与深度内外参、分辨率、裁剪／缩放、D2C 对齐、帧时间差 |
| 插入后其他传感器掉线 | USB 共用链路带宽、HUB 供电、线材、热插拔及系统 USB 日志 |
| ROS 启动了但没有有效点云 | 先确认原生深度有效，再核对编码、单位、CameraInfo、TF 和话题名 |

此表是排错顺序，不是对当前设备故障的诊断。

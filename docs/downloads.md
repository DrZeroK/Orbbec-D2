# 官方下载与依赖

官方 OpenNI 发布页：[v2.3.0.86-beat6](https://github.com/orbbec/OpenNI_SDK/releases/tag/v2.3.0.86-beat6)。tag 的 beat6 是上游原拼写，资产名使用 beta6。下载清单和本地计算 SHA-256 见 [upstream-downloads.json](../evidence/upstream-downloads.json)。只有 Windows 驱动 ZIP 的哈希另与发布页对照；其他值用于锁定本次所用文件，不是独立厂商签名。

| 文件 | 用途 |
|---|---|
| OpenNI_2.3.0.86_202210111950_4c8f5aa4_beta6_windows_x64.zip | Windows SDK、运行库、头文件 |
| OpenNI_2.3.0.86_202210111155_4c8f5aa4_beta6_arm64.zip | Linux ARM64；ZIP 内还有 A311D 命名的 RAR |
| openni-device-windows-driver-4.3.0.22.zip | Windows 旧协议设备驱动，安装可能需要管理员权限 |

ARM64 内层 RAR 请使用支持 RAR5 的工具解压。得到含 Include/ 和 libs/ 的 sdk/ 后作为 package.py 的 --upstream。该 ARM 包缺少部分通用平台头，可从同版本 Windows SDK 的 Include/ 取 OniPlatform.h、OniVersion.h、Linux-Arm/、Linux-x86/，传给 --platform-headers；不会使用 Windows 二进制。不要混用版本。

Windows 需要 64 位 Python 和 Visual C++ 2013 x64 运行库（msvcr120.dll、msvcp120.dll）；请从微软正规渠道安装，不从随机 DLL 网站下载。探针默认查系统 System32，也可通过 D2_VC120_DIR 指定合法安装目录；该目录不应由不可信用户写入。

厂商 SDK、驱动、PDF、固件及完整官网快照未随库再分发；先阅读其许可。打包器仅在本地生成专用运行目录，不授予将补丁后厂商二进制再次分发的权利。模型通过 models/download_models.py 显式下载到指定新目录，校验固定提交、大小和 SHA-256。

官方中文文档：[固定提交目录](https://github.com/orbbec/OpenNI_SDK/tree/a640cb3724f323dc83d410d0550b5d504894db8a/Doc/Chinese)。Android v3.1 第12–13页包含 D2 深度/IR模式，C++ v1.0.2 第38页提到 D2 InputFormat=2（10-bit 打包）；它不是输出深度单位。

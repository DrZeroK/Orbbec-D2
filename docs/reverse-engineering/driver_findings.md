> 历史研究记录（2026-10-13～15）。描述当轮状态；最终状态以仓库根 README 为准。工作区路径已脱敏，未公开的原始归档项见资料清单。

# D2 ARM64 驱动只读分析 · 2026-10-15

目标：`测试/D2_X5_20261015/offline_sdk/OpenNI_2.3.0.86_202210111155_4c8f5aa4_beta6_a311d/sdk/libs/OpenNI2/Drivers/liborbbec.so`

SHA-256：`24e43298e83d74bb3ce8dcf3ca28979e6334603f9d0534542aa5891cc6764e4b`。
使用 Linux REA / Ghidra 12.1.4 离线分析，未连接相机、未改正式服务、未改原库。完整证据见同目录 `driver_rea_evidence.json`。
地址采用 Ghidra 加载地址，较 ELF 符号值增加 `0x100000`，不是文件偏移。

## 已回答：D2 图像宽高与首8样本

`XnDepthProcessor::OnEndOfFrame` 地址 `0x167e00`（ELF 符号 `0x67e00`），证据 `ev_ff1fec84ed521bb6176c6f2b069e71f7fbc895443e521e85547467034cd72144`。

- 对 PID `0x060d` / `0x061f` 保存输入图像前 `0x10` 字节。
- 深度转换完成后调用 `Channel2Rotate90`，交换 `OniFrame.width/height`、`videoMode.resolutionX/Y`，重新计算 stride。
- 随后将此前保存的原始 `0x10` 字节重新覆盖输出图像头部。因此输出前8个 uint16 样本不是正常完成转换的深度；适配器应在自己持有的副本中将其标记为无效（零），保留官方帧原始数据供诊断。
- 这些字节的语义仍未解码，不能把“协议头”当成已经确认的事实，也不能恢复被覆盖位置的正常深度。
- `Channel2Rotate90` 地址 `0x151590`，证据 `ev_419cb46e59f02dc5f6b2618d507469bc1fa02e65ecb2fcd5fa39d5b671710ae0`；调用 `Channel2TransposeLeft` 并反向遍历源行。
- `XnIRProcessor::OnEndOfFrame` 地址 `0x16b198`，证据 `ev_2d3ef0134b7d52ce500eea22d45a0232621e7d52e233fb39a5f8626a5d5d369c`；此函数未对 D2 执行上述深度旋转。不能把深度与 IR 的像素坐标直接视为一致。

## 已回答：SDK timestamp 的时钟来源不统一

`XnIRProcessor::CreateTimestampFromDevice` 地址 `0x16b800`，证据 `ev_44695056a01864c1f11679ebdea0adf7abc55a1c4b7de0394ba5c8899ecfbca2`；`XnUncompressedIRProcessor` 同名函数地址 `0x13d680`，证据 `ev_02c7f81ef88ee4f44689ee760613911212c98f53dd3ebe598d855095cd743197`。

- 在一个传感器状态值不等于2时，直接返回主机高精度计时器减首次值，忽略传入设备 timestamp。
- 状态等于2时才调用基类的设备时钟换算。
- 基类帧完成函数 `0x151088` 还能依据 HostTimestamps 属性改用已保存的 host 时间。证据 `ev_369e0860f8537c65240798d41cb9b48a551338a314d6d9d3b4c7ff2be0f67a87`。
- 建议适配层使用 `sdk_timestamp_us` 名称，并单独返回 `host_monotonic_us`；没有实际运行状态证据时，SDK timestamp 的时钟域应标记未知，不能直接相减声称 RGB/IR/depth 已同步。

基类 `XnDataProcessor::CreateTimestampFromDevice` 位于 `0x1778b0`，证据 `ev_1793ed769f8fd8247207bc6434ac2dfdc255acbdb4e019cb43a5252d236b92c6`。它使用 float 换算并处理32位回绕、超时重同步；相等/倒退的输入存在被走回绕分支的可能。但本次没有原始 USB 包与计时频率证据，不能据此保证修复异常，更不能通过改返回值伪造设备时间单调性。

## 部分回答：模式帧率

`XnHostProtocalReinitializeSupportedDepthModes` 地址 `0x154730`，证据 `ev_0463a07793c510e29f93e8ccd7bc02e787faccaa840cd0642ed16705ba0299da`；IR 对应函数地址 `0x1550f8`，证据 `ev_883ec4eef95850c3f0f1d916d8323ef1125d5b56a6fe4547568cbb6a8d38877b`。

- 两个函数都没有为 PID `0x060d` 重建硬编码模式表，而是直接返回；其他产品有不同的硬编码表。
- `XnOniDevice::FillSupportedVideoModes` 地址 `0x135b18`，证据 `ev_548269f560550642d3740faae947412bb5c91de9e368f40ded566c3aef87ab16`，直接从底层模式表复制 fps、转换分辨率并去重。列表中的 fps 是枚举值，不能证明实际吞吐。
- 修改这里的 fps 数字只会修改声明，不会提高设备或 USB 实际帧率。没有找到有证据支撑的、能把高清深度恢复到30fps的单点二进制补丁。
- 还需在隔离实验环境检查传输格式、USB 带宽、相机固件、帧包完整性及 CPU 后处理占用。不能把未实测配置标记为稳定模式。

## 适配范围建议

保留独立副本中的枚举修补；对外统一实际输出尺寸；深度前8样本无效化；严格区分 SDK 时间戳与 host 到达时间；保留原生标定与坐标约定。不要自动旋转 IR、猜测 RGB 配准、硬改 fps 或伪造 timestamp。

未做任何相机运行验证或原始 USB 协议抓取；本报告不能证明新适配层的帧率、几何精度或时间同步已验收。

> 历史研究记录（2026-10-13～15）。描述当轮状态；最终状态以仓库根 README 为准。工作区路径已脱敏，未公开的原始归档项见资料清单。

# D2 FPS下发、USB队列、公开曝光路径补查

2026-10-15；原厂ARM64库SHA256 `24e43298e83d74bb3ce8dcf3ca28979e6334603f9d0534542aa5891cc6764e4b`。只读离线分析，未操作相机、未改正式服务。完整证据见同名`_evidence.json`；前轮SetParam和映射证据在`hd_transport_8f4c2d1a_evidence.json`。Ghidra地址=ELF符号值+0x100000。

## FPS下发没有找到D2专用no-op

- `XnSensorFirmwareParams::CheckFirmwareParam` 0x139c68只检查属性映射和固件枚举版本min/max，无PID判断。证据 `ev_019f6fe6dd2648ef68efb26ee845eb7565378ffe77b17fb8be92b33179ce1e50`。
- `AddFirmwareParam` 0x139498保存明确的parameter ID与版本范围、设置回调。DepthFPS在前轮Init中注册为0x14、min/max均0，故不会因D2而被版本检查静默忽略。证据 `ev_f6c869e5a248c6e5d1efb9c0b4a33fe68e8020fb4888e557ec31ae98cf57f7a4`。
- `SetFirmwareParam` 0x13a6f8若处于批量事务会暂存，否则调用SetFirmwareParamImpl；未见D2判断或fps换算。证据 `ev_e4a290a8f92184f3ad7d59a39a292dddf7a81b6d7cc49c236177fcb4919d297b`。
- 前轮`XnHostProtocolSetParam`0x1587c8按普通parameter/value发命令，20不在任何特殊处理分支中；成功立即返回0，不回读验证。`SetFirmwareParamImpl`据成功码更新缓存。因此日志“DepthFPS(20)=30 successful”只证明协议应答成功，不证明固件采用了该物理帧率。
- 没有固件代码/厂商匹配版本，尚不能解释DepthFPS getter始终0或HD物理约7.25。禁止据此猜写别的ID或CMOS寄存器。

## USB队列与读块没有INI旋钮

`XnDeviceSensorOpenInputThreads`0x16c588，证据 `ev_908462669dc6d699321a7165c102901865f95bddeb28844676487d5c914d5d77`：

- BULK模式chunk硬编码为endpoint maxPacketSize * 0xa0。
- 本机maxPacketSize512时等于81920字节，与运行方观察完全一致。
- Depth/IR各16个buffer；misc5个；BULK timeout1000ms。
- 这些赋值没有读INI分支，不能通过增加未存在的INI key安全调整。

`XnSensor::InitReading`0x142998打开端点、获取算法参数、可选开启数值dump、调用上述OpenInputThreads；`SetReadData`0x143fa8只调用InitReading并更新ReadData状态，没有fps节流逻辑。证据 `ev_ef1f0be89c977ee145f5f9ef00a4f95b0e54b85d8a10c9085a5e396c1356f756`、`ev_9fabd339402cd18e7d181af31cdc2e95601183882b0b9cff2874b2048ea619eb`。

运行方报告标准depth约9.75MB/s、HDdepth约9.39MB/s、HDIR约9.35MB/s，正常URB均81920字节、15个取消发生于关闭。结合已确认16buffer队列，未发现SDK主动按FPS限流或排队不足的静态证据。这个约9.4MB/s的平台更像设备输出/传输路径约束，但**不能等同于USB2物理带宽已饱和**，更不能据此承诺修改SDK可恢复38.4MB/s的HD10bit30。

## 公开exposure12路径

头文件`OniProperties.h`明确`OBEXTENSION_ID_IR_EXP=12`。`XnOniDevice::setProperty`0x135298对当前CMOS类型分支检查dataSize=4，再调用ObSetIRExp；host通路为：

`公开property12 -> ObSetIRExp -> 内部property0x1080ff96 -> XnSensor::SetIrExp -> XnHostProtocolSetIrExp`。

证据 `ev_92b2ab36fc87d4f4116ef35d759ee0e787dacce790ba393321a0e8003cdeb41a`、`ev_a784747be6ca60c8066c8fe706c3548689b3708c10dc406c0dce3deb55721ff6`、`ev_613104e561235ce907bd6b93ba79670a62b1a7d5b7e1e8a7f411271597e1657d`。

`XnHostProtocolSetIrExp`0x15cd10发8字节payload，其中配置选择值0xf1000004及曝光uint32，再普通Execute。证据 `ev_b4e1dadab8b2231ad0d026c4a6cd4b76daa4508adfd689f0badd910bbbdff6cd`。此host调用链没有Flash、Save或固件升级调用。但没有设备固件实现，不能保证此设置跨断电的volatile语义。

若有必要做最小曝光排除实验，应仅使用公开property12的4字节int设置：记录当前值3000、写1000、立刻回读、仅数值采样、finally写回原3000并回读确认；失败时报告恢复状态。不改gain/laser/APC/AE/寄存器，不调用私有host protocol。该实验只检查曝光是否影响帧率，不建立曝光单位、正确画质或安全认证结论。

所有运行数值均由主代理提供，具体有效范围以其保存的原始日志为准；本报告未新增运行结果。未找到可证明恢复HD30的SDK单点补丁。

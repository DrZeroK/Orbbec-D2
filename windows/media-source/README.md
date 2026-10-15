# D2 实验性 Windows 红外相机源

本目录实现真实 D2 IR 取流到 Media Foundation COM Custom Media Source。当前发布一条 L8 640×400@30 红外流，**没有声明 Windows Hello 能力**。

先在 x64 Native Tools Command Prompt 设置 OPENNI_INCLUDE（官方 Include 目录）和 OPENNI_RUNTIME（含 OpenNI2.dll 的 Win64 库目录）；再运行 `build.cmd` 编译原生 D2Capture 与 COM 源、独立测试消费者。用户态代码依赖 Visual C++、Windows SDK、官方 OpenNI 头文件／运行库和 VC++ 2013 x64 运行库；没有 WIL、NuGet 或内核驱动构建依赖。微软参考来源见仓库 evidence/microsoft-sample-provenance.json；实际许可为目录内 MS-PL（旧研究记录的 MIT 说法已更正）。

消费者可直接加载 DLL，不用注册或管理员权限：

```powershell
.\build.cmd
.\build\test_consumer.exe .\build\D2MediaSource.dll 90 .\build\last_ir.pgm
```

消费者检查真实样本字节数、IR 属性、QPC 时间戳、Start/Stop/Shutdown、停止后拒绝样本、第二次启动和所有 COM 引用释放；Hello 属性应缺失，FaceAuth 控制应返回不支持。图像用本地 PGM 文件保存，程序不会发送凭据或实现替代登录。

`virtual_camera_probe.cpp` 是 Windows 11 临时系统发现与取图探针：仅 CurrentUser + Session 相机，结束后 Remove/Shutdown。`probe_system_source.ps1 -Machine` 在管理员权限下临时注册专用 COM CLSID，finally 中自动撤销，不覆盖已有键。原工作区历史实测 Windows 相机服务已成功激活本源，MFSourceReader 读到实际 256000 字节 IR 图像；Remove 成功，HKLM/HKCU 临时 CLSID 均已核验不存在。见 `build/system_source_machine_probe.log`。成功取图仍不代表 Windows Hello 可以登录。

`stub/` 提供 UMDF 2 设备接口注册源码与 INF 草案；编译它需要 WDK，安装它需要管理员权限和合适签名。此草案没有打包全部 OpenNI/CRT 运行库、相机移除后的接口生命周期、正式签名或 HLK 报告，所以不作为可安装发行包。

照明控制使用固定哈希 SDK 的真实控制接口；GET 稳态回复 `0x6400/0x6401` 的 SDK 判断错误仅在本进程内修正。首个写命令前保存真实原状态，Stop 恢复并回读，撤销指令修复。当前 getter 表示控制状态，不能作为曝光时逐帧 metadata。

`test_background.cpp` 提供真实照明切换和背景差图实验：

```powershell
.\build\test_background.exe 150 .\build\background_new
.\build\test_background.exe 150 .\build\background_stress_new stress
.\build\test_background.exe 150 .\build\background_settled_new settled
```

基线 15.084 fps，但随机延时压力测试出现编号连续的明暗错配；每相位丢弃过渡帧后为 7.539 fps。两条当前路线分别缺少可靠配对或达不到 Hello 15 fps。测试成功结束只表示真实采集和保存完成，不能作为 Hello 质量验收。原始日志、逐帧/配对 CSV、实际差图均在 `build/background_*_20261015.*`。

后续实际适配 Hello 还需验证真实同步照明或背景相减、最低有效帧率与启动延迟，增加 FaceAuth DDI 和 Profile，核验持久 PnP 设备、必要的 RGB/IR 分组以及签名/系统策略要求。

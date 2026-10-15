# Windows Hello 研究：做到哪里

**未实现 Windows Hello 登录，不提供已签名、已认证的 Hello 驱动。** 自研 D2Capture 和 Media Foundation COM 源已经在原 Windows 实机读到640×400的真实IR；临时机器级 COM 注册后，系统相机服务也实际取得256000字节图像。临时 CLSID 随探针退出撤销；这不能替代账户注册和锁屏登录验收。

源码与测试在 [windows/media-source](../windows/media-source/)。该目录的参考许可实际为 **Microsoft Public License（MS-PL）**，不是原历史说明所称的 MIT，公开整理已更正；遵循目录内许可。UMDF stub/INF 是未完成草案，缺 WDK 构建、完整运行依赖、签名、HLK 与设备生命周期验收，不要安装到日常系统。

照明 ON/OFF 可控制，但 getter 不是曝光时逐帧 metadata。背景相减实验：简单连续配对150对约15.084fps；随机0–20ms控制延迟及一次120ms采集延迟后仅90/150对正信号；丢过渡帧后150/150对正信号，但只有7.539fps。稳定场景成功不足以证明可靠同步和防伪。

没有发送未知交错模式写命令。GET160返回成功ACK但无预期payload，原模式无法可靠保存，故没有写SET159。SDK frameIndex是主机计数，SDK时间戳也不能当作已验证曝光编号。

继续工作需要可靠同步照明或背景扣除、正确 FaceAuth DDI/Profile、合适 PnP 注册和RGB/IR组合，以及微软签名／系统安全要求；不能靠伪造能力标志达成兼容。未关闭 Secure Boot、ESS，未启用测试签名，未更改账户凭据。

官方参考：[Custom Media Source](https://learn.microsoft.com/en-us/windows-hardware/drivers/stream/frame-server-custom-media-source)、[Hello bring-up](https://learn.microsoft.com/en-us/windows-hardware/drivers/stream/windows-hello-camera-driver-bring-up-guide)、[签名要求](https://learn.microsoft.com/en-us/windows-hardware/drivers/dashboard/code-signing-reqs)。

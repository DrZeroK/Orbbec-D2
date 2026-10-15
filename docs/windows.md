# Windows x64：深度测距与红外

样机经官方 Windows 传感器驱动安装后，USB 设备正常而 OpenNI 枚举仍为零。精确版本 orbbec.dll 内有 TornadoD2 路径，但枚举表遗漏 PID060d。探针仅在当前进程把表首项 2bc5:0300 改成 2bc5:060d，不刷固件、不修改磁盘 DLL，也不改变相机 USB 身份。此进程不再支持被替换的 PID0300。

## 使用

1. 从官方发布页下载 Windows x64 ZIP，放到仓库 downloads/；文件名见下载说明。需要时安装官方传感器驱动，之后重新检查设备管理器。安装驱动需你自己确认系统管理员提示。
2. 在虚拟环境安装根目录 requirements.txt。USB 数据线直连主机，确保相机未被其他程序占用。
3. 从仓库根目录运行：

    python windows/openni/probe_openni.py --d2
    python windows/openni/probe_depth.py --d2 --frames 90
    python windows/openni/probe_depth.py --d2 --ir --preview --frames 1800
    python windows/openni/probe_depth.py --d2 --high-resolution --preview --frames 1800

D2_OPENNI_ZIP 可指定 ZIP 完整路径；D2_OPENNI_RUNTIME 可指定解压输出目录（默认 windows/openni/openni_runtime）。脚本从归档提取 Win64-Release/sdk/libs；若已有文件与归档不同会拒绝覆盖。--d2 需要 DLL 的 SHA-256 精确匹配 bd08e87378eba3342f892c5d9cf00af1dfbf674ef46cec3812ebec0d669d1245，未知版本立即停止。完整 ZIP 也须按下载清单核对。

深度输出单位为 mm；IR 为原始强度，不是距离。结果目录只写 measurements.json；显式加 --save-frame 才保存最后一帧 NPY，注意它可能包含个人信息。预览退出关闭窗口即可。USB2 高清实际帧率可能远低于请求值；不要据请求参数判断达标。

## 原理与测距边界

标准深度请求400×640，IR640×400；以返回帧尺寸和 stride 为准。中心21×21区域取有效像素中位数，无效、越量程应单独显示。早期尺量57cm和100cm进行了对照，不构成全量程精度认证。

MF 相机源在 windows/media-source，另见 Windows Hello 研究说明；它不是可安装的正式 Hello 驱动。

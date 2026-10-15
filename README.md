# Orbbec D2 · 资料、OpenNI2 适配与应用实验

让闲置的奥比中光／蚂里奥 **D2 单目结构光相机**重新用于深度测距、红外取流和本地应用开发。本仓库整理了 Windows x64、Linux ARM64 / RDK X5 的排查结果、自研适配源码、测试和资料索引。

**这是社区研究项目，与奥比中光无隶属关系。D2 ≠ D2 Pro；OpenNI2 ≠ Orbbec SDK v2。** 样机是 MX6000 / Mx6000 TornadoD2、固件 5.8.23、深度 USB `2bc5:060d`、彩色 UVC `2bc5:0505`。其他硬件版本须重新验证。

[![奥比中光 D2 官方产品图（官网外链）](https://www.orbbec.com.cn/uploads/20211107/4476252a81340ec42a40de474f4f9ffb.jpg)](https://www.orbbec.com.cn/index/product/info.html?cate=38&id=31) · [官方产品页与参数](https://www.orbbec.com.cn/index/product/info.html?cate=38&id=31)

图片版权归奥比中光及相关权利人；依据官网法律声明，本仓库提供官方原图入口，不复制托管或将图片置于 MIT 许可下。

## 先看结论

| 功能 | 状态 | 入口 |
|---|---|---|
| Windows 深度测距、IR 预览 | 样机已实测；精确哈希限定的进程内枚举修复 | [Windows 指南](docs/windows.md) |
| Linux ARM64 深度＋IR | 标准双流约 30 fps；自研 C ABI / Python 示例 | [SDK 构建与使用](sdk/README.md) |
| USB3 高清深度或高清 IR | 样机单流约 30.16 fps；实验模式 | [性能与限制](docs/performance.md) |
| RGB 彩色取流 | Linux UVC 实测可用；帧率受曝光、格式和场景影响 | [X5 应用参考](integrations/x5-ui/README.md) |
| RGB 人脸＋PIN 应用解锁 | 已在 X5 实际解锁；只用彩色摄像头 | [集成源码](integrations/x5-ui/) |
| 深度＋IR 防伪 | **实验，未完成几何／时序／真人连续验收，不用于正式解锁** | [实验说明](experiments/ir-face/README.md) |
| Windows Hello | 能经系统相机服务读取 IR；**尚不能 Hello 登录** | [研究边界](docs/windows-hello.md) |
| Orbbec SDK v2 / ROS 2 | 未桥接 SDK v2；没有本仓库已验证的 D2 ROS 2 驱动 | [路线比较](docs/sdk-and-ros.md) |

深度/IR 是原始数据能力，不等于附送活体算法、支付认证或 Windows Hello 驱动。RGB 人脸识别可能被照片和视频冒用；**始终保留 PIN**。这里的锁屏是应用锁，不是操作系统登录或经过认证的身份安全产品。

## 官网标称参数

下表按 [D2 官方产品页](https://www.orbbec.com.cn/index/product/info.html?cate=38&id=31) 的数值和宽高顺序整理，2026-10-16 再核对。官方标称值与本仓库实测分开记录，未宣称全部达标。

| 参数 | 标称值 |
|---|---|
| 技术 / 基线 | 单目 3D 结构光 / 55 mm |
| 深度距离 | 0.3–1.3 m |
| 深度分辨率 | 800×1280 @30 fps；400×640 @30 fps |
| 彩色分辨率 | 1536×2048 @15 fps；696×928、768×1024、480×640、240×320 @30 fps |
| 精度 | 0.3 m：±0.3 mm；1 m：±3 mm |
| 深度 FOV | H45° / V68° / D78°（±3%） |
| 彩色 FOV | H58.5° / V72° / D86.5°（±5%） |
| 功耗 / 数据接口 | ≤2.2 W / USB 2.0、USB 3.0 |
| 供电接口 | TYPE-C |
| 官网列出的系统 | Android、Windows 7、Windows 10 |
| 使用环境 | 室内、室外（80000 Lux @1 m） |
| 工作温度 | −20～50 °C |
| 尺寸 | 107.00×27.60×21.00 mm |
| 安全 | Class 1；简介另提及 RoHS |

官网采用竖向规格；样机 OpenNI 的请求尺寸、原生输出和安装方向并不相同，不能只交换宽高再沿用旧内参。0.1 mm 输出单位不代表 0.1 mm 测距精度。深度无效值为零，超量程或无回波不等于没有障碍物。完整解释见[历史规格研究](docs/research-notes/01_产品参数与型号辨识.md)。

## 从哪里开始

1. **只要彩色画面**：先使用 UVC / OpenCV，按 VID:PID 确认设备，避免写死 `/dev/video0`。
2. **需要深度／IR**：从[官方 OpenNI 发布页](https://github.com/orbbec/OpenNI_SDK/releases/tag/v2.3.0.86-beat6)下载匹配包；先读 [下载、许可与哈希](docs/downloads.md)。
3. **Windows**：依 [Windows 指南](docs/windows.md)运行 `probe_depth.py --d2 --frames 90`；预览不会保存照片，测量统计会写入新结果目录。
4. **Linux ARM64 / X5**：以官方原包生成独立 D2 运行目录，再构建 `sdk/`；默认先跑标准双流，不要并开两路高清。
5. **人脸识别**：先读 [RGB＋PIN 集成说明](integrations/x5-ui/README.md)。本仓库提供原工程组件与最小接线示例，不是一键覆盖整机 UI 的安装包。

### Linux ARM64 最小示例

需要 Python 3.10+、CMake 3.16+、C++17 编译器，以及自行取得的匹配官方 OpenNI SDK。构建只创建新目录，不覆盖系统 SDK。

```bash
python3 sdk/package.py --upstream /path/to/original/sdk \
  --platform-headers /path/to/matching/official/Include --output /path/to/new/d2-package
cmake -S sdk -B build/sdk -DD2_PACKAGE=/path/to/new/d2-package -DCMAKE_BUILD_TYPE=Release
cmake --build build/sdk -j2
ctest --test-dir build/sdk --output-on-failure
timeout 25s /path/to/new/d2-package/bin/d2_probe 10 dual
python3 sdk/examples/capture.py /path/to/new/d2-package 10
```

ARM64 归档可能缺通用平台头；需从同版本官方包补齐，详见 SDK README。厂商库哈希不符时适配器会拒绝，**不要将偏移套用于未知版本**。设备无 USB 读写权限时先处理权限；不要把整个 UI 以 root 运行。

## 目录

| 目录 | 内容 |
|---|---|
| [sdk/](sdk/) | v0.2.0 ARM64 原生适配源码、C ABI、打包器、CTest、Python 示例 |
| [windows/](windows/) | Win64 枚举／测距、MF COM 红外源、消费者测试和 UMDF 草案 |
| [linux/](linux/) | 早期进程内补丁加载器，保留排查参考 |
| [integrations/x5-ui/](integrations/x5-ui/) | 已验收 RGB 人脸、PIN、实时预览及防伪几何组件、合成测试 |
| [experiments/](experiments/) | 历史 IR 人脸分支、高清／帧率／USB 诊断 |
| [tools/calibration/](tools/calibration/) | 出厂参数解码、标定、时序、棋盘 PDF 与测试 |
| [models/](models/) | YuNet / SFace 官方下载清单、哈希与许可证；不含模型权重 |
| [docs/](docs/) | 使用说明、官方来源、历史研究记录和已知问题 |
| [evidence/](evidence/) | 脱敏数值结果与此次公开检查；不含照片或模板 |

[资料清单与公开范围](docs/source-inventory.md)解释哪些归档已经合并、哪些只保留官方链接，以及哪些涉及隐私或许可而未上传。公开源码来源和 SHA-256 见 [provenance.json](evidence/provenance.json)。

## 验证

```bash
python -m venv .venv
# 在自己的虚拟环境安装；X5 已有系统 OpenCV 时可复用其匹配环境。
python -m pip install -r requirements.txt
python tools/check_publication.py
python -m unittest discover -s sdk/tests -v
PYTHONPATH=integrations/x5-ui python -m unittest discover -s integrations/x5-ui/tests -v
PYTHONPATH=tools/calibration python -m unittest discover -s tools/calibration -p 'test_*.py' -v
python tools/calibration/timing_probe.py --self-test
```

Windows 的 `PYTHONPATH` 请用 PowerShell `$env:PYTHONPATH='integrations/x5-ui'` 设置。Linux 专有的相机工作进程测试在其他平台会跳过。测试使用合成图、假相机和临时目录，不能替代实机验收。原 X5 完整 UI 359 项通过属于当时整机工程的回归记录，并非本独立仓库包含 359 项。

本次整理在 WSL 下 **65 项独立 Python 测试全部通过**，另通过时序7项／出厂参数解码4项自检、C++帧合约，以及Windows红外源和6个消费者／探针的源码编译。未重新做实机取流或Hello／防伪验收；详见 [公开检查记录](evidence/publication-checks.json)。

## 已知问题与参与

参见 [已知限制](docs/known-issues.md)、[贡献指南](CONTRIBUTING.md)和[安全边界](SECURITY.md)。报告问题时提供型号、固件、USB VID:PID／速率、系统架构、官方库 SHA-256、命令与脱敏日志；不要提交照片、人脸特征、PIN 或密钥。

本项目自研源码采用 [MIT](LICENSE)。微软参考代码、模型和厂商 SDK 各自适用原许可证，见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。本项目不刷固件，不调整激光安全参数，也不提供认证或精度保证。

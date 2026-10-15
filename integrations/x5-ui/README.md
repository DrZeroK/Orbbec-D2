# X5 / Linux：RGB 人脸识别、PIN 与预览组件

这里使用已验收的 **RGB-only** 发行快照，不包含后来其他工作对UI的未部署改动。原X5用户实际彩色解锁成功；PIN保留。没有调用D2深度或IR。

| 文件 | 作用 |
|---|---|
| face_engine.py | YuNet/SFace、私有模板、受限子进程、按2bc5:0505选择UVC |
| face_rgb_stream.py | 优先借用原scene-daemon的RGB帧；没有该Unix socket时直接V4L2采集 |
| face_preview.py | 录入期间经内存socket发送JPEG；退出或过期后清空 |
| screen_auth.py | PIN PBKDF2、限速、接口门控、并发epoch、失败保留PIN |
| qml/LockOverlay.qml | 原轮椅UI锁屏组件，依赖原工程提供的属性与控件 |
| d2_camera.py / face_pad.py | 仅供深度IR研究引用；RGB录入/验证不会加载它们 |

## 组件使用

Linux环境，使用根requirements。按models清单下载模型到你选择的目录；FaceEngine(data_dir, models_dir)可显式传入，不必使用默认wheelchair路径。data_dir应为仅本机账户可写的私有目录。

    from face_engine import FaceEngine
    engine = FaceEngine('/path/to/private/data', '/path/to/models')
    print(engine.status())
    # 仅在用户同意且通过本机PIN验证后调用：
    # engine.enroll()
    # engine.verify()

将本目录加PYTHONPATH。上面的status不录入人脸；不要在共享终端打印enroll/verify返回的特征。模板本机0600，不自动采照片。验证超时、相机异常或模板损坏要回到PIN，不应自动放行。模型阈值是研究参数，未量化误识率。

## 接入自己的aiohttp应用

screen_auth.install(app, monitor_key, is_device=..., same_origin=...)注册/api/screen-auth/*。app[monitor_key]须提供带root（私有数据目录）的对象；install会将screen_auth挂到该对象。两个回调由宿主应用可信地判断本机界面和同源，不能照搬为总返回True。

在所有敏感API处理前调用auth.gate(request)，若非None就直接返回该拒绝响应；宿主已有远程权限校验仍须保留。PIN设置和录入界面不得暴露给网络来访者。QML片段需按你自己的宿主UI接线，本库没有完整server.py、轮椅UI或服务部署脚本。

## 测试与边界

tests/可独立执行。upstream-tests/test_screen_auth.py保留原工程15项HTTP流程测试和1项损坏PIN测试，需要原工程server.create_app/MONITOR_KEY，不计入独立测试通过数；不能仅复制该文件运行。原X5的359项整套UI回归通过记录见evidence摘要。

RGB画面可被照片或视频冒用；连续帧或更高相似度不构成活体。应用锁不能替代操作系统账户保护。

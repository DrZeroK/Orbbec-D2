# 深度＋IR身份与几何防伪实验（未验收）

此目录保存最终切回RGB之前的IR人脸分支，不是默认解锁版本。共同依赖来自integrations/x5-ui。不要用它替换已经可用的RGB/PIN登录。

IR预处理、旋转、YuNet检测、SFace身份和深度鼻部局部几何检查均有合成回归；但真实IR录入、连续识别和防伪验收未完成。用户曾报告录入成功，随后更正仍无法录入，最终明确选择仅彩色识别；仓库最终状态以RGB实际解锁为准。

配对检查包括SDK时间差、主机到达年龄、帧号/哈希异常，后台持续排空过期帧；这些不能证明曝光同步。相机样机出厂参数有有限棋盘对照，完整全视场对齐与曝光时序仍未确认。照片/视频未检出IR人脸也不能证明整体防伪能力。

实验d2_camera.py和合成factory_activation_fixture.json中的D2_SAMPLE_SERIAL是脱敏占位；没有真实激活文件。不能把样机K/D和raw参数复制到另一台设备，也不能仅修改verified=true绕过验收。自编libd2sdk.so需要重新验证并审阅固定哈希清单。

几何合成用例在integrations/x5-ui/tests/test_face_pad.py；IR专有测试在本目录tests/。要测试IR分支，把本目录放在PYTHONPATH首位，再放integrations/x5-ui，避免误导入RGB模块。仅跑合成测试不会采集或录入真人。

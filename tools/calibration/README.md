# 出厂参数、标定与时序工具

**正常RGB解锁不需要此目录。** 如果只想取深度/IR，先使用sdk/d2_probe；它能读取120字节原厂30个float，不依赖特定相机的硬编码内参。坐标含义与旋转后的流还需核对。

- ir_calibration.py、test_ir_calibration.py：纯计算／合成标定，训练视角和留出验证分离，不会自动宣称完整对齐通过。
- read_factory.py：已知属性3（序列号）、14（120字节参数）只读探针；保留原测试约束，路径、UID和样机绑定已脱敏，**编辑并审阅前不能直接用于其他机器**。--self-test不访问相机。通用读取请优先用sdk/d2_probe。
- verify_factory.py、board_boundary.py、checker_diagnostics.py：数值核验与边界分析。
- capture_checker.py、capture_boundary.py、detector_compare.py、corner_floor.py、board_preview.py：原隔离实机采集脚本。脱敏的/home/USER路径、UID1000锁和实验目录需按本机配置；没有自动化部署入口。
- timing_probe.py --self-test：验证统计逻辑；实际--run仍是原X5隔离采样流程，不能在缺乏排他访问与权限核对时照跑。SDK timestamp和host receive time不等于曝光同步。
- D2_A4_20mm_8x11_inner_corners.pdf：自行生成的A4棋盘，8×11内角点、20mm格、100mm尺。按100%打印后**必须实测横纵尺寸**；原实物打印缩成96%，当时改按19.2mm格记录，不能将该历史尺寸用在新板上。

本仓库不带本机出厂激活文件。过去有限近60cm/远80cm棋盘核验的重投影RMS约0.26–0.38px，不能代替覆盖全视场/多姿态/实物距离原点的完整验收。之后手工标定已取消，所有未完成项目保持未验证。

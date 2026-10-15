# 高清、UVC与USB历史诊断

保留raw_probe.cpp、usb_metadata.cpp、matrix.py、rgb_worker.py等模式矩阵和协议元数据工具。它们使用当时隔离环境的路径、SDK哈希、UID和进程协调规则，公开时仅脱敏；**不是通用一键安装或运行脚本**。先按自己的环境审阅，读根docs/performance.md。

不要并行打开两路高清；不要与正在人脸采集的应用争用相机。实验可能临时改变曝光/软件滤波，需确保退出恢复。优先用已有sdk探针和标准模式，避免重做会触发USB异常的历史组合。

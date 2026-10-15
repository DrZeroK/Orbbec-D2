# SDK v2 与 ROS 2 路线

本项目依赖官方历史 **OpenNI2 2.3.0.86 beta6** 的核心和Orbbec插件，加自研D2适配层。sdk/ 的 v0.2.0 是本项目模块版本，不是 Orbbec SDK v2，也不是重写闭源核心。

| 路线 | 对本样机的状态 |
|---|---|
| OpenNI2 + D2兼容补丁 | 已取深度/IR；当前使用 |
| Orbbec SDK v1 | 官方支持表未列D2；没有得到本样机可用结论 |
| Orbbec SDK v2 | 未做桥接，未验证原生支持 |
| OrbbecSDK_ROS2 main | 旧SDK路线，可作ROS2消息和启动组织参考；没有D2适配验收 |
| OrbbecSDK_ROS2 v2-main | SDKv2路线，不会自动让OpenNI D2兼容 |

外层数据桥接最多复用部分上层接口，不能补出新硬件协议、固件能力、曝光同步、几何标定或官方支持资格。当前优先保留已工作的OpenNI2链路。

若后续发布ROS2驱动，应以真实测量的CameraInfo、正确 optical frame、毫米到米换算和无效值语义为基础，分别发布IR/深度/RGB并标明时间域；不要只改Astra设备名字。

官方入口：[OpenNI](https://github.com/orbbec/OpenNI_SDK)、[SDK v2](https://github.com/orbbec/OrbbecSDK_v2)、[ROS2 main](https://github.com/orbbec/OrbbecSDK_ROS2/tree/main)、[ROS2 v2-main](https://github.com/orbbec/OrbbecSDK_ROS2/tree/v2-main)。支持列表会变化，提交问题前再核对上游。

> 历史研究记录（2026-10-13～15）。描述当轮状态；最终状态以仓库根 README 为准。工作区路径已脱敏，未公开的原始归档项见资料清单。

# D2原生INI解析器兼容性纠正 · 2026-10-15

只读目标仍为原厂ARM64 `liborbbec.so`，SHA256 `24e43298e83d74bb3ce8dcf3ca28979e6334603f9d0534542aa5891cc6764e4b`。本次未操作相机、未改运行库或服务。证据保存于同目录 `ini_parser_43c98b7e_evidence.json`。地址采用Ghidra基址（ELF符号值加0x100000）。

## 已确认的配置失效根因

`FindEntry`地址0x185e88，证据 `ev_d99c4c50748ac285fcffc70be27bf407769c630dd2bde5ec2b9a84842adbee76`：

- 行首空格/制表符会跳过。
- section通过strcmp精确匹配，区分大小写。
- key从首字符逐字节复制直到等号，再与请求key做strcmp。**不去除等号之前的键尾空格**。
- 取value时从等号后一字节开始复制，直到行末；不做通用INI规范化。

`xnOSReadIntFromINI`地址0x1864f0，证据 `ev_070f52ab9658f2301542aa78c6c07bc00fc95922d6e2a5ccd4bf7a6a9067478b`，匹配成功后调用strtol(value,NULL,10)。因此：

| 文本 | 请求Depth/SoftFilter的结果 |
|---|---|
| `[Depth]` + `SoftFilter=2` | 可匹配并读2 |
| `[Depth]` + `SoftFilter = 2` | key实际为`SoftFilter `，匹配失败，返回0x2000f |
| `[Depth]` + `SoftFilter= 2` | key可匹配，strtol允许值前空格，读2 |
| `[Depth]` + `softfilter=2` | 大小写不匹配 |

`xnOSReadStringFromINI`地址0x1862f8也共用FindEntry，证据 `ev_bb80a1693947dc1a9fb14322dd88907c124fbca59ce88553419fc8dc0c8e293b`。这不局限于SoftFilter，configparser默认输出`key = value`会令这类键全部失效。

`XnDepthStream`构造地址0x127d18创建`SoftFilter`属性，ID确为0x2080ff43，默认值为1。证据 `ev_9239aa393e7911ae77fd6f86de86d4a79ef40ea491f8a9d65f2e0b52b94a0f22`。因此运行方报告INI名义SoftFilter2而getter读1，与配置未解析、保留默认值的解释一致；不需要怀疑该属性ID。

## 对既有实验的影响

本地`测试/D2_FPS_20261015/sdk_fps_experiment.py`的configure()使用`cfg.optionxform=str`，已保留键大小写，但调用`cfg.write(out)`没有禁用等号周围空格。因此旧nofilter失败不能证明真实SoftFilter0不工作，旧矩阵涉及这类重写后的设置对照也不能证明配置已生效。

最小修复是在临时实验副本中使用`cfg.write(out, space_around_delimiters=False)`且保持`optionxform=str`，或仅精确替换原始配置行。应在采集前回读实际属性并记录值，不能只记录磁盘INI。

无相机自检可直接调用导出的xnOSReadIntFromINI，在不同临时INI文本上比较返回码和读值；不需要oniInitialize、USB或任何固件操作。

## 固件FPS索引限制

前轮证据证明0x14是这份SDK预期的DepthFPS索引：FirmwareParams构造命名、Init的AddFirmwareParam(0x14)、DepthStream::MapPropertiesToFirmware三处一致。0x13对应DepthResolution；运行方读回26与HD请求分辨率枚举一致。但这不能证明FW5.8.23对DepthFPS getter返回值有真实语义。DepthFormat=0、DepthFPS=0不能解释成物理0fps，也不足以推断应该写另一个地址。只允许使用已确认Get接口记录对照，不能猜写寄存器或固件参数。

尚未做实际解析函数运行测试或相机重测；静态结果明确证明键尾空格不兼容，但新配置下帧率仍以运行方日志为准。

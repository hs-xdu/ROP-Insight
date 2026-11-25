# P2-D Vessel 原实验接入与验收

## 1. 范围和依据

用户明确要求暂缓 P2-C，优先实施 P2-D，并指定在 `E:\ROP_Experiments` 搜索原实验资料。血管分割独立运行，不依赖 Ridge；后续分类若实际依赖 Ridge，仍须补齐，不能把暂缓视为完成。

本段复用既有权重和原实验环境，通过独立进程运行，界面环境不安装科学计算依赖。现有图层/线程机制继续使用；不接入分类、量化，不调用 VascX 最新默认模型，不改动原实验文件。

## 2. 已定位的原实验资料

资料基目录：`E:\ROP_Experiments\icrop3_vascular_quant_v1\A1_Bayesian_ReferenceRefresh_20261102_191829`。

| 类型 | 相对于基目录的路径或记录 |
| --- | --- |
| 原权重 | shared_assets/models/vessels_july24.pt |
| 权重 SHA-256 | bdabae77502648acd1c176bff6d5e3c8295da60f18f2f84fe1bcd6181d2b2ca4 |
| 原环境 | a1_vascular_severity/runtime_t02/.venv/Scripts/python.exe |
| 推理流程 | a1_vascular_severity/reference_refresh_experiment/image_pipeline.py |
| 初始原生流程 | a1_vascular_severity/t02_infer.py |
| 内嵌模型配置基准 | a1_vascular_severity/outputs/t02_pilot26_v1/audit/vessels_model_config.json |
| 参考结果 | a1_vascular_severity/outputs/a1_reference_refresh_comparison_v1/new_inference |

已验证原环境可运行：Python 3.12、PyTorch 2.6.0+cu124、retinalysis-inference 1.0.0、retinalysis-fundusprep 1.3.0、NumPy 2.5.4；GPU 为 RTX 4080 SUPER。权重与环境均从外部路径只读引用，不复制进 Git。

官方当前 [模型仓库](https://github.com/Eyened/retinalysis-vascx-models) 与 [推理库](https://github.com/Eyened/retinalysis-inference) 仅用于核对来源；本项目以本地原实验实现为准，不能把当前线上 main 当作原环境的等价物。模型用于本项目的学术研究；引用与使用范围沿用原工件说明。

## 3. 实现与数据流程

1. 主程序注册 `vascx_native`，配置指定原环境解释器、设备、权重路径、模型版本和期望 SHA-256；Ridge、分类禁用，Vessel 依赖列表为空。
2. 工作线程把当前图像保存为独立的临时 PNG 快照，使用参数列表启动固定 backend 脚本，不经 shell 执行。原环境保持只读：禁用 pyc，设置离线模式，缓存写入本次输出目录，清除界面 PYTHONPATH/PYTHONHOME 污染。
3. 后端校验权重哈希，沿用 seed 20261029、bounds.crop(1024)、RGB 和 contrast_enhanced_5；以与原脚本一致的文件路径方式送入 preprocess_item/make_batch/predict_batch/postprocess_batch，batch_size=1、tile_batch_size=2。
4. 采用原生后处理生成 1024×1024 二值 Mask；保留概率与内嵌配置，不另加阈值。使用同一裁剪变换的最近邻逆映射得到原图 Mask，再转换为平台的 0/1 bytes。
5. 平台显示 Vessel 单独 Mask 和叠加图，不生成 Ridge 或分类结果。记录权重、输入快照与像素哈希、backend 哈希、包版本、设备、bounds、变换、原生及对齐结果哈希。
6. 输出保存于 Qt 本地应用数据目录下 `vascx_runs/<运行标识>/`，包含日志、预处理图、原生 Mask/概率和对齐 Mask。临时原图快照在任务结束或失败后删除。结果不上传，日志和结果目录由用户按需保留。
7. 取消时只停止本任务创建的子进程，等待其退出；不终止 QThread 或其他实验进程。超过 600 秒明确报超时，设备失败不静默切换 CPU。CPU 配置可选，但本次真实对照只验证 CUDA。

## 4. 自动化与真实对照

单元测试覆盖配置路径与哈希字段、原环境/权重缺失、子进程协议、奇数宽度 PNG 解码、输入快照清理、子进程取消和失败提示，并运行既有回归。

已在一个固定原实验参考样本上完成真实推理对照：

| 检查 | 结果 |
| --- | --- |
| 预处理 RGB | 逐像素一致 |
| 原生 Mask | 1024×1024，差异像素 0 |
| 原生血管概率 | 最大绝对差异 0.0 |
| 逆映射 Mask | 原图尺寸 428×571，差异像素 0 |
| 内嵌模型配置 | 与原实验记录一致 |

本地详细数据保存在项目忽略目录 `.runtime/real-vessel/`，患者图片、文件名及原始参考数据不写入提交。这是单样本工程一致性验证，不代表全体图像的一致性或分割准确率。平台端真实进程到图层的联调结论以交付记录补充。

平台真实链路亦已通过：界面导入 → 工作线程 → 原实验解释器子进程 → Vessel 0/1 Mask → 图层展示；未提供 Ridge 与分类输出。另实际启动并取消了一个本任务的原环境子进程，确认控制器取消终态、子进程退出和输入快照清理。使用临时工作区验证输出位置，实际用户启动后输出位于本机应用数据目录。仅启用的模块参与运行成功判定，主动禁用 Ridge/分类不会使成功的 Vessel 误报“部分完成”。当前自动化回归为 80 passed，pip check 通过。

## 5. 启动与人工验收

本机已生成 `configs/vascx.local.json`，因含本机绝对路径而被 Git 忽略。项目目录中启动：

```powershell
.\run-vessel.ps1
```

也可使用：

```powershell
.\.venv\Scripts\python.exe -m rop_insight --config configs/vascx.local.json
```

其他机器需先将 `configs/vascx.example.json` 复制为 `.local.json`，填写原实验 Python 与权重路径；不要直接把示例中的占位路径用于运行。普通 `run.ps1` 仍启动未配置模型的基础平台。

- [ ] 导入测试图并开始分析，界面保持响应，完成后 Vessel 状态成功，Ridge 与分类为跳过/未提供。
- [ ] 选择 Vessel Mask 或叠加显示，检查血管与原图对应、缩放拖动及透明度正常。
- [ ] 换图、清除、取消和关闭操作不残留旧图结果或子进程。
- [ ] 原环境或权重路径错误时有提示，日志可定位具体原因。

用户已在本次对话明确确认 P2-D 验收完成并要求推进 E，作为本阶段人工验收结论。前述步骤保留用于复现；本阶段通过不代表整个 V0.2 完成。

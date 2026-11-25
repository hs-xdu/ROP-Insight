# P2-E A6 深圳分类接入与验收

## 1. 用户确认的范围

用户选择 A6、深圳权重，并明确采用“先支持导入已有 Ridge Mask”。本阶段不恢复自动 Ridge 分割、不改用其他分类模型、不重新训练；Ridge 来源明确标为用户导入。用户必须确认 Mask 与原图内容对应，软件只检查尺寸和二值编码，不能证明两者来自同一病例。

## 2. 固定工件与接口

- 原项目：`E:\ROP_Experiments\a567_rgb_qkv_seed42_20261112_v1`。
- 权重：`runs/shenzhen_v2/A6/seed_42/best.pt`，SHA-256 为 `46d32c4991e304b0a4058bf013847635695e884e7c435552869effe20d241f45`。
- 复用原 `models.py` 的 RGBExtension 与快照中的 StagingModel，固定两份源文件哈希；构造时不下载 ImageNet 权重，严格加载最终 state_dict。
- 原环境：`C:\Python\PythonProjects2025\ROP_Paper_Materials\heatmap_study\.venv\Scripts\python.exe`，PyTorch 2.6.0+cu124。
- 与原 ROPDataset 一致：512×512，RGB 双线性缩放及 ImageNet 标准化；Mask 用最近邻，前景规范为 1；输入顺序 RGB、Ridge、Vessel。
- 原 FP32 推理，cuDNN benchmark=False、deterministic=True、cuDNN TF32=True、matmul TF32=False；一次 softmax，标签顺序 Normal、Stage1、Stage2、Stage3。

配置快照见 `configs/a6.example.json`；本机已生成被 Git 忽略的 `configs/a6.local.json`。分类仅在 ridge、vessel 两个上游成功后执行。缺少导入 Mask 时禁止完整分析；不自动补零，不把合成输入作为生产预测。

## 3. 实现与结果生命周期

主窗口增加“导入已有 Ridge Mask”，支持原图同尺寸的不透明灰度二值 PNG，值只能为 0、1 或 255；导入失败保留此前有效输入，导入成功可查看 Ridge 图层。

Mask 作为当前 image_id 的独立输入快照，开始运行时复制，导入新 Mask 会取消旧任务并使旧 run_id 失效。换图或清除原图移除 Mask 与分类结果；取消选择原图或原图加载失败不改变当前上下文。

注册 imported_ridge 和 a6_shenzhen 两个适配器；扩展现有隔离进程执行机制供 A6 使用，保留 VascX 的取消、日志、超时和临时原图清理行为。结果包含原 logits、概率、类别映射、权重/代码哈希、设备与输入哈希，界面只做展示舍入。

## 4. 验证记录

使用原实验的一个固定测试样本及保存的 RGB/Ridge/Vessel 输入进行真实 A6 参考对照，预测类别一致，概率最大绝对差异为 `3.5762786865234375e-07`，小于 `1e-6`。这是单样本工程一致性检查，不代替全测试集复验或临床效果验证。其历史测试成绩见 [候选说明](P2_E_MODEL_SELECTION.md)。

参考对照使用原实验保存的 Vessel；平台联调则重新执行 VascX。重新分割的输入不应直接当作历史输入概率的逐位复现，需区分输入来源。自动测试新增二值规范、透明/彩色/错误尺寸拒绝、来源标记、输入依赖、换图失效及 A6 请求校验，并重跑全部回归。

平台原图导入 → 用户 Ridge → 真实 VascX → 真实 A6 → 概率面板的完整联调已通过，三个模块均成功；全量 93 项测试及 pip check 通过。参考样本、概率与详细本地记录位于 Git 忽略目录 `.runtime/a6-reference/` 和 `.runtime/a6-gui/`，不提交病例图与逐图记录。

## 5. 启动与用户验收

在项目目录执行：

```powershell
.\run-classifier.ps1
```

脚本受限时：

```powershell
.\.venv\Scripts\python.exe -m rop_insight --config configs/a6.local.json
```

1. 导入眼底图像。
2. 导入与该原图对应的 Ridge Mask，检查 Ridge 图层对齐；缺少它时应显示导入提示且不能开始完整分析。
3. 点击开始分析，等待真实 Vessel 分割及 A6 分类完成。
4. 查看预测类别、四类概率和两种图层；Ridge 状态标为用户导入。
5. 换图后应要求重新提供 Ridge；尝试错误尺寸、彩色图、取消和关闭，检查错误提示与旧结果隔离。

代码已实现，实际操作待用户确认；自动 Ridge 分割仍暂缓，不将此模式描述为完全自动诊断系统。

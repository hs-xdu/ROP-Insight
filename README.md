# ROP-Insight

P5 已实现：分析结束后点击“预览辅助分析报告”，查看简要/详细报告并“导出PDF报告”。输出PDF、精确JSON、文字及来源清单，使用与验证见 [P5说明](docs/P5.md)。P6匿名病例信息、P7历史分析记录与报告复核已实现，操作和验收见 [P6/P7说明](docs/P6_P7.md)。范围见 [开发设计](docs/DESIGN_V2.md)，依赖和验收见 [阶段路线图](docs/IMPLEMENTATION_ROADMAP.md)。

完整研究平台入口：`.\run-platform.ps1`。导入原图和已有 Ridge Mask，开始分析，结束后可“导出分析结果”，生成独立目录中的 JSON、二值 Mask PNG 和原图坐标叠加图。

启动、自检、配置与复现见 [运行手册](docs/RUNBOOK.md)；导出字段见 [P4-A](docs/P4_A.md)，系统自审与剩余限制见 [P4-B](docs/P4_B_VALIDATION.md)，论文材料见 [索引](docs/THESIS_MATERIALS.md)。当前为手动 Ridge 的研究原型，自动 Ridge 仍暂缓。

P3-B 评分与辅助分类入口：`.\run-scoring.ps1`。导入原图及 Ridge 后开始分析，向下滚动左侧结果，可分别查看连续评分/95% 后验区间、RBF-SVM 类别及 A6 概率。原冻结 SVM 使用含 T1 的 11 项特征，说明与验收见 [P3-B 记录](docs/P3_B.md)。

结构量化入口：`run-quantification.ps1`。导入原图及 Ridge Mask 后，运行真实血管分割、A6 分类和原实验十项量化；说明与验收见 [P3-A 记录](docs/P3_A.md)。

已按用户选择接入 A6 深圳权重，采用用户导入 Ridge Mask＋真实 VascX Vessel 的分类流程：

```powershell
.\run-classifier.ps1
```

先导入原图，再导入对应的二值 Ridge PNG，最后开始分析。步骤与限制见 [A6 接入说明](docs/P2_E_A6.md)。

P2-D 已接入本机原实验 VascX 权重与独立 CUDA 环境。运行真实血管分割：

```powershell
.\run-vessel.ps1
```

导入图像并点击“开始分析”，成功后在左侧选择 Vessel Mask 或叠加显示。配置与验收见 [P2-D 说明](docs/P2_D_SPEC.md)。自动 Ridge 按用户要求暂缓，完整平台采用导入 Ridge 后运行 A6。

P2-A 已经用户确认验收。P2-B 增加 Mask 图层、透明度和概率面板，使用以下合成数据窗口检查展示效果：

```powershell
.\.venv\Scripts\python.exe tests/manual_p2_b.py
```

步骤见 [P2-B 实施说明](docs/P2_B_SPEC.md)。这些测试窗口只使用合成数据；真实 Vessel 使用上面的专用启动入口。

P2-A 已实现后台任务基础。普通 run.ps1 未指定模型配置，显示“分析模块未配置”；后台响应、取消和安全关闭可用测试专用窗口验收：

```powershell
.\.venv\Scripts\python.exe tests/manual_p2_a.py
```

详见 [P2-A 验收记录](docs/P2_A_VALIDATION.md)。该脚本只运行工程任务，不输出诊断结果。

支持用 `python -m rop_insight --config 配置文件.json` 指定分析配置。配置顶层为 `schema_version: 1` 和 `modules` 列表；每项使用 `module_id`、`enabled`、`adapter_id`、`device`、`dependencies` 等字段。生产注册表包含 vascx_native；配置只能选择显式注册的适配器，不能从 JSON 动态导入任意模块。错误日志位于 Qt 的本地应用数据目录下 `ROP-Insight/logs/analysis.log`，失败提示不显示完整堆栈。

Windows 本地眼底图像查看软件，采用 Python 3.12 + PyQt6。支持单张 JPG、JPEG、PNG 导入、重选、清除、等比例适应窗口、滚轮及按钮缩放、鼠标拖动，以及文件信息和加载状态展示。

## 安装与运行

在项目目录打开 PowerShell：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\run.ps1
```

也可以安装为本地包并启动：

```powershell
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
.\.venv\Scripts\python.exe -m rop_insight
```

点击“导入图像”或按 Ctrl+O 选择文件。放大后按住鼠标左键拖动查看局部；“适应窗口”恢复完整图像显示。适应模式随窗口大小变化，手动缩放后保留观察比例。取消选择不改变当前图像，加载失败保留上一张图像并显示错误提示。

首版同步读取，每张图像默认不超过 4,000 万像素，Qt 解码分配上限为 256 MB。可在 `ImageLoader` 的构造参数中调整；超限、损坏和扩展名伪装文件会被拒绝。读取和缩放均不写回源文件。目前不包含病例管理或批处理。

## 测试

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
```

自动化测试使用临时合成图片，不需要患者图像。无显示环境可设置 `QT_QPA_PLATFORM=offscreen`；Windows 桌面仍需检查实际布局和操作手感。

需求见 [MVP 文档](docs/MVP.md)，实现方案见 [技术方案](docs/TECHNICAL_PLAN.md)。

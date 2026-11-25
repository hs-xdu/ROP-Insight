# ROP-Insight

P2-A 已经用户确认验收。P2-B 增加 Mask 图层、透明度和概率面板，使用以下合成数据窗口检查展示效果：

```powershell
.\.venv\Scripts\python.exe tests/manual_p2_b.py
```

步骤见 [P2-B 实施说明](docs/P2_B_SPEC.md)。正常启动不包含合成输出，也尚未接入真实模型。

P2-A 已实现后台任务基础，真实模型尚未接入。正常启动显示“分析模块未配置”；后台响应、取消和安全关闭可用测试专用窗口验收：

```powershell
.\.venv\Scripts\python.exe tests/manual_p2_a.py
```

详见 [P2-A 验收记录](docs/P2_A_VALIDATION.md)。该脚本只运行工程任务，不输出诊断结果。

支持用 `python -m rop_insight --config 配置文件.json` 指定分析配置。配置顶层为 `schema_version: 1` 和 `modules` 列表；每项使用 `module_id`、`enabled`、`adapter_id`、`device`、`dependencies` 等字段。此阶段生产注册表为空，只能禁用或留空模型项；不能通过 JSON 加载任意 Python 代码。错误日志位于 Qt 的本地应用数据目录下 `ROP-Insight/logs/analysis.log`，失败提示不显示完整堆栈。

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

首版同步读取，每张图像默认不超过 4,000 万像素，Qt 解码分配上限为 256 MB。可在 `ImageLoader` 的构造参数中调整；超限、损坏和扩展名伪装文件会被拒绝。读取和缩放均不写回源文件。本阶段不包含 AI 推理、病例管理或批处理。

## 测试

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
```

自动化测试使用临时合成图片，不需要患者图像。无显示环境可设置 `QT_QPA_PLATFORM=offscreen`；Windows 桌面仍需检查实际布局和操作手感。

需求见 [MVP 文档](docs/MVP.md)，实现方案见 [技术方案](docs/TECHNICAL_PLAN.md)。

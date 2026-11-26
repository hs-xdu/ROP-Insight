# ROP-Insight

**v0.2.0 · 研究预发布**。Python 3.12 + PyQt6 的 Windows 本地 ROP 眼底图像分析工作台。

当前支持单图查看、导入已有 Ridge、VascX Vessel 分割、A6 深圳四分类、11项特征及连续评分/95%后验区间、冻结 RBF-SVM 辅助分类、固定模板报告，以及精简病例保存与历史恢复。自动 Ridge 仍暂缓；此版本不代表完整 V1.0 验收或临床有效性验证。

## 在已配置的本机启动

```powershell
cd "E:\8 大论文\ROP_System"
.\run-platform.ps1
```

1. 可先点击“病例与资料库”，选择本地资料文件夹并创建/选择匿名病例；不选病例也能临时分析。
2. 导入原图和对应的二值 Ridge PNG，点击“开始分析”。
3. 完成后点击“保存分析记录”；先预览报告再保存，可同时保存或补充 PDF。
4. 点击“历史分析记录”搜索病例，查看已保存图像/图层/结果及原报告；历史查看不重新推理。

## 从 GitHub 下载后运行

本次发布是**源码版本，不是 Windows 安装包**。源码不包含模型权重、算法专用环境、患者图像、病例库或本机配置。

先创建 GUI 环境并安装项目：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
```

仅检查图像查看界面可运行 `.\run.ps1`。完整分析还需按 [运行手册](docs/RUNBOOK.md) 配置模型、独立推理环境及 `configs/p3b.local.json`，随后运行 `.\run-platform.ps1`。其他单模块启动脚本仍保留用于验证和排错。

## 使用与开发资料

- [运行手册](docs/RUNBOOK.md)：配置、自检、复现和故障排查。
- [P6 使用与验收](docs/P6_SIMPLE_VALIDATION.md)、[P7 使用与验收](docs/P7_SIMPLE_VALIDATION.md)：病例保存、历史查询和恢复。
- [当前精简设计](docs/P6_P7_SIMPLIFIED.md)、[技术方案](docs/TECHNICAL_PLAN.md)、[开发路线图](docs/IMPLEMENTATION_ROADMAP.md)。
- [v0.2.0 更新说明](docs/releases/v0.2.0.md)、[存档与清理记录](docs/releases/ARCHIVE_20261126.md)。
- [论文材料索引](docs/THESIS_MATERIALS.md)、[历史文档档案](docs/archive/README.md)。历史资料保留开发证据，不作为当前操作指南。

## 测试

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
```

测试使用临时目录和合成图像。GPU、权重和原实验依赖通过各模块独立环境配置；不因下载新版本而自动安装或改写原实验环境。开发遵循 AGENTS.md，每段改动保留测试及 Git commit。

历史阶段证据集中在 [开发档案](docs/archive/README.md)，本次清理记录见 [发布整理记录](docs/releases/ARCHIVE_20261126.md)。

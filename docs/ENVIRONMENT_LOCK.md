# 环境与工件记录

2026-11-25 在本机只读自检并执行真实参考推理。以本地 `.runtime/p4-validation/environment.json` 的实际导入记录、配置内 SHA-256 和各后端结果为依据，不通过升级研究环境“修复”差异。

| 角色 | 实际运行版本/条件 |
| --- | --- |
| GUI | Python 3.12.3、PyQt6 6.10.2、Qt 6.10.0；requirements.txt/requirements-dev.txt |
| VascX/量化/SVM 原环境 | Python 3.12.3、PyTorch 2.6.0+cu124、torchvision 0.21.0+cu124、NumPy 2.5.4、pandas 2.3.3、SciPy 1.18.1、scikit-learn 1.9.1 |
| A6 原环境 | Python 3.12.3、实际导入 PyTorch 2.6.0+cu124、torchvision 0.21.0+cu124、NumPy 2.5.2 |
| 执行设备 | Vessel/A6 配置 cuda:0；量化/SVM CPU；不会静默回退 |

A6 环境中 PyTorch 的发行元数据报告 `2.14.0+cpu`，实际导入为 `2.6.0+cu124` 且 CUDA 可用。自检将该差异列入 `metadata_mismatches`，现有参考推理通过。不应将 pip freeze 的这一记录直接用于新机器重建；环境重建及清理重复元数据需要在独立环境另行核对并重新通过数值对照，当前未修改该研究环境。

权重与源码清单见 `configs/p3b.example.json`，本机实际路径仅在 Git 忽略的 p3b.local.json。原算法对应说明见 [VascX](P2_D_SPEC.md)、[A6](P2_E_A6.md)、[量化](P3_A.md)、[评分/SVM](P3_B.md)。这些工件通过原模型哈希和原代码哈希约束，不将大型权重放进 Git。

导出结果记录实际后端包版本、确定性开关、原生几何、模型版本与哈希；软件身份采用运行开始时的 Git commit/dirty。开发中生成的验证证据如 dirty=true，应保留该事实；不可改写成最终提交的干净运行。最终提交后可按运行手册重新复验，得到对应 commit 的新证据。

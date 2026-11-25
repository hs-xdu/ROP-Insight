# P3-A 结构量化接入与审查验证

## 1. 实现范围与启动

已接入原实验的 Ridge 四项、血管五项和 S_median，共十项量化输出；不训练新模型，不执行 P3-B 的 RBF-SVM，也不把连续评分解释成临床分期。自动 Ridge 仍暂缓，沿用用户导入的二值 Mask。

```powershell
.\run-quantification.ps1
```

本机配置为 `configs/p3.local.json`；可迁移模板为 `configs/p3.example.json`。先导入原图，再导入对应 Ridge Mask，开始分析；向下滚动左侧“结果与图层”查看指标、单位及计算网格。普通分类和血管启动入口保持原行为。

## 2. 原实验依据与坐标约束

在指定实验归档中定位到原血管分析及后验工件，继续追溯其论文材料，最终代码位于 `C:\Python\PythonProjects2025\ROP_Paper_Materials\features_quant`：

- `phase2_features/ridge_annot_metrics.py` 与 `ridge_metrics.py`：四项 Ridge 指标。
- `phase2_features/automorph_metrics.py`：FD、VD、最大局部密度变化。保留部分占据盒计数及按行窗口序列相邻密度差，不改成其他常见公式。
- `fusion_stage34/prepare.py`：原生 native_features 与 extract 调用；T3/B3 复用已验证血管段筛选、端点裁剪、长度权重及图结构规则。
- `phase1_preprocess/preprocess_512.py` 与 `common/spatial.py`：原 FOV 与共享裁剪、填充、缩放。
- `E:\ROP_Experiments\icrop3_vascular_quant_v1\A1_Bayesian_ReferenceRefresh_20261102_191829` 下的 `selected_model/full26.json`、后验 NPZ 及 `a1_vascular_severity` 代码：评分参数、原生血管工具与骨架长度实现。

原图、导入 Ridge 与逆映射 Vessel 经同一变换进入 512 网格，计算 Ridge 四项和 FD/VD/局部密度变化。T3/B3 和 S_median 继续使用原生 1024 网格。使用原 VascX 工件的原生 Mask，不把逆映射后的显示图再缩放成原生 Mask。

S_median 复用冻结后验及其原标准化参数，不重新拟合；血管段不足或输入特征非有限时遵循原 QC 规则，返回不可用。空 Ridge 的四项保持原实现的缺失语义；有效空血管的面积密度可为 0，但 FD/T3/评分不可定义时不补零。当前 text exclusion 与原深圳流程一致为零，含覆盖文字的其他输入需人工审查，不能声称已经处理文字遮挡。

## 3. 代码审查与执行隔离

继续使用原 `runtime_t02` 环境的独立进程，GUI 不安装科学计算依赖。源文件与后验配置均固定哈希，后验 NPZ 由原函数校验。直接复用原函数体；为避免研究脚本顶层的历史输出路径和文件操作，按 AST 提取已指定函数定义而不执行脚本入口及其他顶层代码。骨架辅助函数同样取自原定义，原文件不被改写。

审查时修复了脚本同目录 `vascx.py` 与原生 vascx 包重名的导入问题。量化与分类只依赖 Ridge/Vessel，彼此不依赖，一方失败不阻止另一方。新运行、换图和清除沿用 run_id 隔离及面板重置机制。不可用指标提供 null、单位、网格与原因；源函数异常则模块明确失败，不保留上一图的指标。

## 4. 验证证据与限制

- 一个 Ridge 非空参考样本：十项指标与原缓存逐项差异均为 0。
- 一个原 Ridge 为空参考样本：血管五项及 S_median 与原缓存差异为 0，Ridge 四项保持不可用。
- 空血管真实函数测试：FD、T3、S_median 不可用，VD 为 0；没有把所有不可用项替换为 0。
- 自动化覆盖原函数提取不执行顶层副作用、缺少原生工件时拒绝运行、单位/数值/不可用原因显示及重置，并回归现有平台功能。
- 平台真实联调中 Ridge、Vessel、A6 与量化四个模块全部成功；结果字段缺失或缺失值没有原因时会被拒绝。全量 97 项测试通过，pip check 通过。

本地对照记录位于被 Git 忽略的 `.runtime/p3-reference/`、`.runtime/p3-reference-nonempty/` 和 `.runtime/p3-empty-vessel/`。不提交患者图、逐图身份和原实验数据；有限样本只验证工程复现，不代表全数据集复验或临床有效性。

## 5. 人工验收

- [ ] 导入原图及 Ridge，开始分析，Vessel、分类、量化分别显示状态。
- [ ] 检查十项指标、单位和网格，确认 Ridge 来源为用户导入。
- [ ] 空或退化 Mask 的指标不可用时能看到原因，不误认为零分或正常诊断。
- [ ] 换图/清除后旧指标消失；分析中取消、关闭和错误提示正常。

P3-A 代码及自动化验证完成后仍待用户实际操作确认；不提前进入 P3-B，不标记 V0.3 完成。

# P3-B 连续评分与结构辅助分类

## 启动和功能

在项目目录执行 `.\run-scoring.ps1`。先导入原图，再导入与原图对齐的二值 Ridge PNG，点击“开始分析”。左侧结果区向下滚动可查看连续评分、95% 后验区间、RBF-SVM 辅助分类和 A6 四分类概率，三者独立展示，不融合。

本机配置 `configs/p3b.local.json` 不进入 Git。其他机器参考 `configs/p3b.example.json` 填写原实验代码、环境和权重路径。不提交患者图像或模型权重，不修改原研究环境。

## 冻结算法

用户已确认按原模型将 SVM 输入从规划的 10 项修正为 11 项，增加 T1。P3-A 原十项量化显示保留。SVM 固定顺序：

1. fractal_dimension
2. vessel_area_density_fov
3. sliding_window_max_density_gradient
4. T1
5. T3
6. B3
7. ridge_area_ratio_fov
8. ridge_solidity
9. ridge_outer_vessel_density
10. ridge_max_radius_ratio
11. S_median

使用原 `features_quant/fusion_stage34/V6_R4_S1_methods_20261104/results_v2/RBF_SVM.joblib`，SHA-256 为 `d474cc1394c30d410de36eac0307393eb28e71f4f28297c6659542f176abc7eb`。参数 C=10、gamma=0.01、class_weight=balanced。直接使用冻结 Pipeline 的训练期中位数填补和 StandardScaler，不调用 fit。

字段缺失报错；原算法不可定义的 Ridge 特征以 null 传递，由已训练的填补器处理。评分不通过质量规则时暂停 SVM，不补零继续预测。加载 joblib 前核验模型、最终特征清单、实验汇总和环境记录的哈希。Python 3.12.3、NumPy 2.5.4、pandas 2.3.3、SciPy 1.18.1、scikit-learn 1.9.1 与原记录一致才运行。

原 sklearn 的 probability 默认值为 `deprecated`，不代表启用校准。本适配器只使用 predict，不输出概率或把决策值归一化为概率。

连续评分复用原 full26 后验，输入顺序 L3、B3、T1、T3，使用原 mean/std 及固定 w/b 样本计算 2.5%、50%、97.5% 分位数。要求至少 5 条有效血管段且输入有限。评分及区间均为原后验相对尺度，不映射临床分期。

## 接口与任务隔离

- `quantification.values.score`：status、reason、median、lower、upper、ci95_width、valid_segments、posterior_sha256。
- `quantification.values.feature_values`：按名称提供原十项指标与 T1，缺失为 null。
- `auxiliary.values.auxiliary_classification`：独立类别、固定特征顺序、原始向量、变换后向量、缺失值规则；未校准概率为 null。
- 辅助分类另记录模型版本、模型/来源哈希、环境版本及本地工件目录，不填充 `AnalysisOutput.classification`；该字段继续承载 A6 概率。
- 沿用独立子进程、取消、超时和 run_id 隔离。量化失败使依赖它的 SVM 跳过，不阻止独立的 A6。换图/清除后旧结果消失。

## 审查验证

- 全量 111 项测试通过，pip check 通过；覆盖错序/缺项、冻结缺失值处理、评分区间合法性、质量失败、特征与显示一致性、拒绝伪概率、独立展示与重置。
- 518 条原训练特征，其中 163 条含缺失值：适配层逐条输出与直接调用冻结 Pipeline 对照，分类 518/518 一致，预处理最大差异为 0。仅验证工程复现，不是独立数据集性能验证，没有重训。
- 一个原 Ridge 非空参考样本：S_median 和 95% 区间宽度与原缓存差异均为 0；区间端点由相同后验重放得到。
- 真实工件检查：评分质量不通过时辅助分类不可用；错误模型哈希在加载前拒绝。
- Qt 真实联调：用户导入 Ridge、VascX、A6、量化、SVM 五模块均成功；评分/SVM/A6 分别展示，换图后旧结果清除。
- 本地证据位于 Git 忽略的 `.runtime/p3b-reference/`：comparison.json、gui-validation.json 及截图。不提交原图、研究数据和模型权重。

## 人工验收

- [ ] 使用新入口启动，导入原图及 Ridge，五模块运行成功。
- [ ] 滚动左侧结果，分别检查评分/后验区间、SVM 类别和 A6 概率。
- [ ] 检查换图、清除、取消及错误提示；旧结果不残留，按钮栏宽度稳定。
- [ ] 不可用评分有原因，SVM 不显示百分比，不与 A6 合成结论。

P3-B 代码、自动化及真实联调完成，人工验收待用户确认；V0.3 总体验收未提前标记完成。自动 Ridge 分割仍暂缓。

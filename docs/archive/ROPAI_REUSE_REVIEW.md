> 历史档案：仅作开发与论文追溯；当前运行和功能以 [运行手册](../RUNBOOK.md) 为准。

当前P6/P7执行范围已改为 [精简计划](../P6_P7_SIMPLIFIED.md)；本文仅保留旧源码盘点，不构成新的开发授权。

# ropai 代码借鉴评估与阶段实施依据

本页保留P5实施前的只读盘点和来源记录。随后用户已授权完成P5，当前已实现模板适配、预览和PDF，见 [P5实施记录](../P5.md)；下文“尚未迁移/实现任务”描述的是当时的检查状态，P6/P7仍未实施。

## 1. 已确认的范围

用户提供本地源码 `C:\Python\PythonProjects2025\ropai`，并确认保留当前 ROP-Insight，仅借鉴相关代码，不迁入旧平台整体。本轮为只读源码盘点和规划补充，未执行旧服务、连接数据库、读取患者结果/图像、运行旧分类器或修改 ropai 文件；没有开始 P5—P7 功能实现。

用户随后补充报告源码 `C:\Python\PythonProjects2025\ROP_DeviceAgnostic_Features\deploy_rop_report_web`，已只读核对其报告模板、分档规则、提取入口和界面；模板已定位，尚未迁移。该目录同样未被修改或启动服务，详细评估见第6节。

检查覆盖 `ROP_Classifier_App` 的说明及聚合逻辑、`ropaiweb` 的接口/worker/血管分析桥接代码、`ropaih5` 的结果页面与相关脚本。以下是本地静态代码发现，不等于旧系统运行验收。

## 2. 可借鉴模块与边界

| 目标 | 已定位代码 | 可借鉴内容 | 在 ROP-Insight 中的处理 |
| --- | --- | --- | --- |
| P5 报告内容组织 | `ropaih5/index.html` 的 renderResult 及 vascular-results 段 | 类别映射、血管指标名称/单位、有限值/不可用展示、评分区间和研究尺度说明；动态内容使用 textContent | 借鉴字段与固定语句，改为当前 A6、11项特征及独立SVM的报告数据/模板；不整体复用HTML页面 |
| P5 结果汇总 | `ropaiweb/worker_ropai.py` 的 process_pic | 分类结果与逐图血管分析的结构化组织 | 直接读取当前 AnalysisRun/P4 JSON，不调用旧worker或重新推理 |
| P6 病例关联 | `ropaiweb/main.py` 的 upload_pic_batch | 病例记录、图像组ID、图像文件关联的业务关系 | 改为匿名研究病例编号、眼别、检查日期和备注；临床字段与模型输入隔离，使用本地元数据 |
| P7 历史查看 | `ropaiweb/main.py` 的 get_patient_list、get_patient_by_id、get_ret_by_pic_id | 分页、按编号查询、运行状态和既有结果查看 | 用当前导出目录/JSON实现本地列表和报告重开，不迁移SQL、数据库或HTTP服务 |
| 运行隔离参考 | `ropaiweb/vascular_bridge.py`、vascular_analyze.py | 独立科学环境、质量规则、不可用状态和固定后验语义 | 当前平台已有已验证实现，保留现有算法，只参考字段语义，不替换函数或环境 |

在 ropai 中定位到的是结果卡片和查询接口，也未将可选函数包装段视为已完成的历史页面。独立文字模板已在用户补充的 deploy_rop_report_web 中定位，输出为 Markdown/TXT；已检查源码尚未定位PDF生成实现。P5将借鉴该模板结构，适配当前输出和缺失规则，PDF仍由当前PyQt6实现，不依赖旧平台运行。

## 3. 不能直接照搬的差异

- **分类模型不同：** 旧 ROP_Classifier_App 使用 Dual/Mask4ch ResNet50，预处理及类别顺序不同；当前仍使用已确认的 A6 深圳 RGB/Ridge/Vessel 模型。不会为了复用报告而切换权重或输入流程。
- **多图聚合不同：** 旧 aggregate_eye 的 majority 模式 confidence 是投票比例，mean_prob 是跨图平均；都不能直接当作当前 A6 单图概率。P5不新增多图聚合，也不把投票比例写入报告为模型校准概率。
- **隐私字段不同：** 旧表单/API要求姓名、年龄、性别、身高和体重；P6不迁入这些必填要求，采用匿名研究编号，病例信息不进入分类模型。
- **历史聚合需改造：** 旧列表使用病例级聚合及 ANY_VALUE/GROUP_CONCAT 组织关联，不能直接用作多眼、多日期、多次运行的精确报告关系。新系统按 case_id/image_id/run_id/report_id 保留独立关联，不合并不同运行的指标。
- **缺省值不同：** 旧分类卡片对未给出的 confidence 以0初始化；新报告必须明确“未提供/不可用”，不能把缺失结果写成0%或正常。
- **平台依赖不同：** 旧 FastAPI、Web表单、MySQL、上传URL、数据库连接配置和轮询worker不进入新系统；不复制服务器配置、连接凭据、患者数据、图片、日志或旧权重。

## 4. 分阶段执行顺序

沿用 P5→P6→P7 的优先级和范围，不因存在旧代码就一次性迁入全部功能。

### P5 优先：先内容与模板，再预览/PDF

第一步定义当前分析快照到报告数据的映射，以已找到的 template.py 简化/详细报告结构为参考，补齐 A6、真实导入Ridge、T1、11项特征、评分区间、SVM、版本与限制。不迁入旧经验分档，验证完整、部分失败、不可用及不同运行不混用，文字只按固定规则生成。

第二步实现 PyQt6 报告预览与PDF，预览/PDF共用报告数据；核对中文、分页、数值和既有JSON一致性、文件失败与防覆盖。P5不依赖旧数据库或P6病例信息，不迁入模板中未经当前模型支持的临床结论。

### P6 建议：本地匿名病例字段与关联

借鉴旧病例与图像关联流程，独立实现匿名编号、眼别、检查日期、备注及版本。覆盖同病例多眼、多次分析、换图清空、保存失败及旧报告不被修改；不迁移旧病例数据库，不改变模型输入。

### P7 可选：本地历史列表与来源复核

借鉴旧查询/分页交互，扫描用户选择的当前成果目录，读取JSON及报告关联，支持病例检索、重开PDF和来源核对。兼容无病例/PDF的旧P4成果，覆盖目录迁移、损坏数据、文件缺失和目录外路径；不连接旧数据库，不重算历史输出。

## 5. 已检查源码身份

相对路径均基于上述 ropai 根目录。哈希只用于说明本轮检查的源码版本，不将旧代码当作当前模型工件或运行依赖；后续实际借用函数时应记录具体来源及相应测试。

| 相对源码路径 | SHA-256 |
| --- | --- |
| ropaih5/index.html | 16a2417342c22f032e855a942165e9ca73d45bd209a82a0e3ffd12d2ddcef3bd |
| ropaiweb/main.py | e86b641411970f0f9824c8114d8bd3ebc698e8bc238431581571f1450a22d6d5 |
| ropaiweb/worker_ropai.py | 4e8071092d83e481cbac382eba04258399b4c3e21e89dce3ae0cea42aa5fc5f0 |
| ropaiweb/vascular_bridge.py | a0c53cf1f089c43262d3ca2ebeb795b7a3af895558bea0c65364caef91683668 |
| ropaiweb/vascular_analyze.py | 81841e569c485441198a49a233f84b492752d652623ac2e7b7d4b6bfbfdc2a6c |
| ROP_Classifier_App/rop_app/aggregate.py | df42d041ccdc592eee994ef0c7c97dc005fe5cea3db93e4c1ea14025484b6491 |

完整功能范围见 [第二版设计](../DESIGN_V2.md)，实施与验收顺序见 [路线图](../IMPLEMENTATION_ROADMAP.md)，技术选型见 [技术方案](../TECHNICAL_PLAN.md)。本评估不宣称PDF、匿名病例或本地历史功能已经迁移完成。

## 6. 补充报告源码的评估

### 6.1 已定位的实际实现

相对路径基于用户补充的 deploy_rop_report_web 目录：

| 相对源码路径 | 已有能力 |
| --- | --- |
| report/template.py | render_simple_impression 生成简化报告；render_report_md 生成详细Markdown；md_to_txt 转为纯文本 |
| report/feature_bins.py | 12项血管 + 10项嵴代理的固定经验分档，源码说明为“经验区间，非诊断阈值” |
| report/extract_one.py | 旧图像→分割→特征→报告流水线，保存简化/详细MD/TXT及血管叠加预览 |
| report/app_gradio.py | Gradio预览与文件下载入口，不是当前PyQt6界面 |

可借鉴固定模板、简化/详细层次、项目名称/单位展示、说明章节和纯文本转换。当前P5只从已完成分析快照生成报告，不调用旧 extract_one_image 重做分割/量化，不安装Gradio/conda/旧VascX或修改当前原实验环境。独立PDF实现尚未在这份检查范围中定位，PDF预览/排版/导出仍是新平台P5实现任务。

### 6.2 字段与规则适配

22项旧分档字段与当前11项模型特征仅有3个同名：fractal_dimension、vessel_area_density_fov、sliding_window_max_density_gradient。同名不证明算法与尺度等价；旧提取入口注明特征在原图分辨率提取，当前协议则区分512与原生1024网格，不能套用旧经验阈值。

当前 T1、T3、B3、Ridge面积比例/实心度/外环血管密度/最大径向位置、S_median 没有相应的旧分档项。尤其不能将旧 median_tortuosity 或 Top5迂曲指标当作当前 T1/T3，也不能将基于血管化前沿的“嵴代理”当作用户导入真实Ridge的四项特征。

旧模板还不包含当前 A6四类概率、冻结SVM或当前后验评分的完整字段，因此不直接将当前11项数值传入旧 render_simple_impression。它的缺省分支可能将缺失输入写成中等/常见范围，新适配器必须先检查状态，缺失只写不可用及原因；同时覆盖 None、NaN、Infinity，不继承旧格式化仅判NaN的行为。

模板中的经验分档、“plus样改变”“分区倾向”及“综合印象”等旧规则不直接迁入。P5先按当前结果作事实性表述，不新增诊断、风险阈值或未经验证的解释；将来若确需这些解释，需另行提供阈值来源、尺度适用性及对应验证。保留模板的研究用途说明，补齐当前手动Ridge、部分失败、独立分类和版本追溯说明。

### 6.3 补充源码身份

| 相对源码路径 | SHA-256 |
| --- | --- |
| report/template.py | 87c7bcc5816808041d68abb4487151cfd5faf804b3c17ec43d25afd624ab54cd |
| report/feature_bins.py | eb9c5d1f17da1576a9d60b099bab878c8b0c4789da7384c367b31e9f3a13fe2d |
| report/extract_one.py | 1485b507de63518d7df048f1760b4c2d37e89f67dfda8630bfb7e6e27912a920 |
| report/app_gradio.py | 6be5fe5dde5e4b19705b164b6fc5ac3a2577f0090caf2ed5615bc60ada0f529c |

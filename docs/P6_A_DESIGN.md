# ROP-Insight P6-A 详细设计（待批准）

更新：本计划已获人工批准，P6-A已完成数据库与病例仓储实现；实际接口、测试、差异和范围见 [P6-A验收记录](P6_A_VALIDATION.md)。下文保留原审核设计基线，关于“未实施/待批准”的表述属于批准前的记录。P6-B尚未获准，不在本轮开发范围。
日期：2026-11-26。对应 [P6实施计划](P6_IMPLEMENTATION_PLAN.md)。本文件仅为设计，以下表结构、接口、SQL事务边界与测试均未实施；没有创建数据库或迁移脚本。

## 1. P6-A目标、交付与边界

目标：用标准库sqlite3建立五表v1基础、病例身份与版本读写、明确的事务/唯一性/幂等规则，为P6-B图像托管及P6-C运行持久化提供稳定关联。

A交付：models/managed_data.py、services/database.py、services/data_repository.py、migrations/001_initial.sql（包资源路径在开发时确定）、test_database.py、test_case_repository.py及实施/测试记录。默认不改requirements、程序启动配置或算法。应用界面集成在E；A只提供可独立验收的服务接口。

五表在A定义并初始化，images/analysis_runs/artifacts暂只建立约束，不提供可绕过文件校验的ready写入接口。A不复制原图、不接自动保存、不生成报告、不迁移旧成果、不开发备份恢复或孤立目录修复。数据库只在显式初始化用户选择的新仓库时创建；导入模块、打开现有临时分析界面不会自动建库。

## 2. 通用字段与校验规则

- ID：规范小写UUID文本。Case、Image、Artifact由管理层生成；run_id沿用既有独立分析ID。revision_id与旧JSON版本ID保留显式映射，不把研究编号当UUID。
- 时间：TEXT，统一UTC带时区ISO 8601；日期TEXT为YYYY-MM-DD，允许NULL；界面展示可本地化。服务层使用datetime/date严格检查，不只靠字符串格式。
- 哈希：64位小写十六进制SHA256。区分原文件SHA、解码RGB像素SHA、JSON文件SHA与P5来源快照SHA；不能互相代用。
- 路径：仓库相对路径，统一正斜线，禁止空段、绝对路径、盘符、URL、`.`/`..`及解析越界；实际文件还须检查链接/重解析点。原始文件名仅保存名称，不参与路径拼接。
- 编号：trim后1—64个ASCII字母/数字/下划线/连字符，首位字母或数字。case_code_key为小写规范键；大小写不敏感判重。不对所有权做哈希自动合并。
- 备注：可空文本，最多2000字符，保留换行/制表符，拒绝其他无效控制字符。空日期统一NULL，未知结果统一缺失/不可用，不能用0或Normal替代。
- 文本必填、枚举、非负大小/尺寸、唯一性、外键由SQLite约束兜底；UUID、合法日历日期、Unicode控制字符、JSON结构和路径语义由服务层严格校验。

## 3. 数据字典（v1）

下列PK=主键、FK=外键、UQ=唯一、NN=非空。除标明可空外均为NN。查询索引字段只是JSON的可重建投影，不成为第二份完整结果。

### 3.1 cases：病例身份

| 字段 | 类型/约束 | 含义 |
| --- | --- | --- |
| case_id | TEXT PK | 稳定内部病例UUID |
| case_code | TEXT | 当前匿名研究编号显示值 |
| case_code_key | TEXT UQ | 编号规范键，不因归档释放唯一性 |
| current_revision_id | TEXT | 当前病例资料版本；同病例复合FK |
| created_at / updated_at | TEXT | 创建/更新时间 |
| archived_at | TEXT，可空 | 预留归档；A不提供归档操作 |

Case不保存作为事实使用的眼别、检查日期。姓名、身份证、出生日期等不在模型内。case_code重复索引用于唯一查询；历史编号保存在病例版本，修改编号不会重写历史。

### 3.2 case_revisions：不可变病例版本

| 字段 | 类型/约束 | 含义 |
| --- | --- | --- |
| revision_id | TEXT PK | 版本UUID |
| case_id | TEXT FK → cases | 所属病例 |
| previous_revision_id | TEXT，可空 | 首版NULL；否则必须是同病例已有前版 |
| case_code / case_code_key | TEXT | 该版本的研究编号快照；不全局唯一 |
| notes | TEXT | 病例备注，默认空字符串 |
| default_eye | TEXT，可空 | 仅图像表单预填值：left/right/unspecified |
| default_exam_date | TEXT，可空 | 仅图像表单预填值，不是历史检查事实 |
| created_at | TEXT | 该版本生成时间 |

UQ(case_id, revision_id)支持复合FK。FK(case_id, previous_revision_id)引用同表(case_id, revision_id)，防止跨病例版本链；CHECK前版不能等于自身。服务层只允许追加到当前版本，前版已存在，不接受任意图结构；修改/删除版本不在A接口内，数据库追加不可变触发器阻止UPDATE/DELETE。后续若开发删除能力，需单独审核保留/删除策略，不能绕过此约束。

cases的FK(case_id,current_revision_id)引用本表(case_id,revision_id)，DEFERRABLE INITIALLY DEFERRED，支持同一事务插入首个病例及版本；提交前必须满足。服务层核对当前cases编号等于当前revision编号。

### 3.3 images：图像与检查事实

| 字段 | 类型/约束 | 含义 |
| --- | --- | --- |
| image_id | TEXT PK | 持久化图像UUID，不等于每次加载的会话ID |
| case_id | TEXT FK → cases | 所属病例 |
| case_revision_id | TEXT | 登记时的病例版本；同病例复合FK |
| eye | TEXT | left/right/unspecified；本图像权威眼别 |
| exam_date | TEXT，可空 | 本图像检查日期 |
| original_filename | TEXT | 原始文件名，不含目录 |
| managed_relpath | TEXT，可空 | 原图托管位置；ready必填且UQ |
| width / height | INTEGER，可空 | pending时可空，ready时必须正数 |
| format | TEXT，可空 | ready为PNG或JPEG |
| file_sha256 / rgb_pixel_sha256 | TEXT，可空 | ready必须齐全 |
| imported_at | TEXT | 导入时间 |
| save_state / integrity_state | TEXT | 保存及完整性状态 |
| operation_id | TEXT UQ | 幂等保存操作标识 |
| failure_code / failure_message | TEXT，可空 | 保存失败原因，脱敏摘要 |
| last_verified_at | TEXT，可空 | 最近完整性检查时间 |

UQ(image_id,case_id)支持Run复合FK；索引(case_id,exam_date)、file_sha256（非唯一）。不对哈希建全局唯一约束，避免误合并病例/眼别。登记成功后的图像身份、病例归属、眼别和日期不可由Case编辑级联修改；修正新增Image关联记录。A不暴露Image写入服务。

### 3.4 analysis_runs：分析时冻结关联与保存状态

| 字段 | 类型/约束 | 含义 |
| --- | --- | --- |
| run_id | TEXT PK | 沿用AnalysisController创建的Run ID |
| case_id / image_id | TEXT | 冻结病例及持久化图像身份 |
| case_revision_id | TEXT | 开始分析时选定的病例版本，可晚于图像登记版本但必须同病例 |
| source_image_id | TEXT | 原AnalysisRun/ExportSnapshot中的运行时image_id |
| eye_snapshot / exam_date_snapshot | TEXT，日期可空 | 从Image复制，禁止用Case默认值覆盖 |
| association_snapshot_json | TEXT | 冻结编号、病例版本、图像身份/检查信息和输入哈希的小型快照，不保存预测正文 |
| started_at / finished_at | TEXT，结束可空 | 实际执行起止时间 |
| analysis_status | TEXT | running/success/partial_success/failed/cancelled |
| module_states_json | TEXT | 模块状态/是否启用/是否实际执行的查询摘要；完整记录在JSON |
| analysis_error_code / analysis_error_message | TEXT，可空 | 分析错误，与保存错误分开 |
| result_relpath / result_sha256 | TEXT，可空 | 成功/部分成功指向P4结果；失败/取消指向管理用最小终态JSON |
| result_kind | TEXT，可空 | p4_bundle或terminal_record，防止格式冒充 |
| run_manifest_relpath / run_manifest_sha256 | TEXT，可空 | 受管理清单，登记实际存在和未生成的工件 |
| source_snapshot_sha256 | TEXT，可空 | 可用时记录P5规范分析来源摘要，不要求失败记录伪造此值 |
| a6_stage | TEXT，可空 | 有效A6结果才投影Normal/Stage 1/Stage 2/Stage 3；SVM不混入 |
| save_state / integrity_state | TEXT | 保存和完整性状态 |
| operation_id | TEXT UQ | 该运行终态发布的幂等标识 |
| save_error_code / save_error_message | TEXT，可空 | 文件或数据库保存失败 |
| recovery_state | TEXT | none/review_required；异常退出待核对 |
| last_verified_at | TEXT，可空 | 最近核对时间 |

FK(image_id,case_id)→images(image_id,case_id)，FK(case_id,case_revision_id)→case_revisions(case_id,revision_id)，UQ(run_id,image_id)供工件复合引用。索引(case_id,started_at)、(image_id,started_at)、analysis_status、a6_stage；按检查日期查询经images索引或Run日期快照。

Run开始时身份/配置已冻结，运行期间只追加实际状态；终态发布后不更新分析结果或冻结关联，后续仅允许完整性、保存重试及未来归档等管理字段按约定改变。未结束运行不能ready。异常退出保留最后已知analysis_status并设置review_required，界面须显示“中断待核对”，不能继续显示为活跃任务，也不凭空推断已成功/已取消。

### 3.5 artifacts：受管理文件与报告关联

| 字段 | 类型/约束 | 含义 |
| --- | --- | --- |
| artifact_id | TEXT PK | 工件UUID |
| image_id | TEXT FK → images | 原图或工件所属图像 |
| run_id | TEXT，可空 | 图像原文件为空；运行工件必填 |
| report_id | TEXT，可空 | 报告组标识；有值时run_id必填 |
| artifact_kind | TEXT | original_image、input_ridge、ridge_mask、vessel_mask、overlay、result_json、run_manifest、report_json/pdf/text/html/manifest、case_snapshot等显式白名单 |
| source_kind | TEXT | imported/generated/legacy_import，记录Ridge真实来源 |
| relpath | TEXT UQ，可空 | 待生成时可空，ready必填 |
| sha256 / byte_size | TEXT/INTEGER，可空 | ready必填；大小非负 |
| schema_version / template_version | TEXT，可空 | JSON/P5版本标识，不复制报告正文 |
| save_state / integrity_state | TEXT | 工件发布和校验状态 |
| operation_id | TEXT | 可多工件共享的报告/文件发布操作UUID |
| failure_code / failure_message | TEXT，可空 | 独立工件保存失败，不污染Run分析状态 |
| created_at / last_verified_at | TEXT，检查可空 | 创建及检查时间 |

FK(run_id,image_id)→analysis_runs(run_id,image_id)防止跨图工件。一个Run允许多report_id；report_id不是artifacts单列UQ。对report_id非空的(report_id,artifact_kind)建唯一索引，每组每种报告文件唯一；服务层在同事务中检查report_id不能跨Run。输入/输出Mask按来源分类，未生成文件不伪造artifact；manifest说明缺失原因。

所有FK默认ON DELETE RESTRICT；不使用级联删除或ON UPDATE CASCADE改变历史归属。A不开放物理删除接口。

## 4. 数据库连接、初始化与事务边界

连接配置：foreign_keys=ON（每个连接核对）、busy_timeout=5000ms、journal_mode=DELETE、synchronous=FULL。初期单后台写入队列；读连接按线程独立创建，不跨线程共享connection，不关闭线程检查。SQL参数绑定，显式BEGIN/COMMIT/ROLLBACK，不用executescript隐式提交破坏外层原子性。

### A-T1：新仓库初始化

只在显式新建空仓库时执行。创建同目录临时数据库，事务创建五表、索引、不可变版本约束及user_version=1；检查foreign_key_check/quick_check，通过后关闭连接并以不覆盖方式发布catalog.sqlite3。已有数据库不能被初始化逻辑覆盖；初始化失败不显示成功，不发布半初始化正式库。此处临时库发布只服务数据库初始化，不开发通用文件托管引擎。

打开既有库先检查user_version和结构。未知高版本或异常结构拒绝写入并明确错误，不能通过重建表静默修复。迁移框架定义显式逐版事务与回滚；A只交付新库v1，不实际迁移用户旧数据。完整备份恢复和修复在F。

### A-T2：创建Case及首版

输入为一次请求冻结的case_id、revision_id、时间和规范字段。BEGIN IMMEDIATE → 检查幂等/编号冲突 → 插入Case及首版revision → 核对当前指针及编号 → COMMIT。循环FK延迟到提交检查。任一步失败全部回滚；不能留下无首版病例或无所属病例版本。

相同case_id/revision_id及相同请求内容重试，返回已存在记录，不重复追加；同ID不同内容为IDEMPOTENCY_CONFLICT。编号被另一病例占用为CASE_CODE_CONFLICT。ID及请求时间由调用方保留到请求完成，重试不能重新生成UUID伪装成新建。

### A-T3：修改Case/追加版本

输入包含expected_revision_id和冻结的新revision_id。BEGIN IMMEDIATE → 若新revision已存在则先检查是否为相同请求重试 → 核对当前版本等于expected → 插入新版本，previous=expected → 更新Case编号/updated_at/current_revision_id，WHERE case_id=? AND current_revision_id=? → 断言恰好一行 → COMMIT。版本冲突返回STALE_REVISION，调用方重新读取后处理，不能静默覆盖。

Case编号唯一检查及版本追加处于同事务。失败回滚新版本和当前指针；不得更新images、analysis_runs或已有JSON。备注或默认值修改也必须追加版本。无内容变化返回当前版本，不制造空版本。

### A-T4：一致读取

get_case/get_revision/list_cases采用只读短事务；跨Case当前指针与revision的组合读取使用同一一致快照。按规范编号查询，历史版本使用UUID读取；分页稳定排序created_at、case_id。返回冻结数据对象或独立副本，不暴露可修改数据库连接。

### 后续文件事务契约（A定义，B/C实现）

B/C/D执行“登记pending/operation → 事务外写文件/校验 → 原子发布 → 短事务登记所有工件与ready”。数据库CHECK要求ready具备必要路径、哈希及终态字段；跨行工件齐全/实际文件哈希一致由统一发布服务验证后同事务提交。禁止普通repository公开任意set_ready入口。A不通过插入虚假文件记录冒充文件保存验收。

published但DB提交失败必须保持非ready并报告；重试使用同一operation_id并比对业务身份、最终路径、结果摘要和文件哈希。文件缺失/损坏或终态摘要冲突拒绝幂等成功。前期仅检测和阻断有效读取；完整孤立目录修复、备份恢复在F，不下放为“忽略错误继续成功”。

## 5. P6-A拟提供接口

- initialize_new_store(root)、open_store(root)：显式新建与版本检查。
- create_case(request)：原子创建身份及首版，重复请求幂等。
- update_case(case_id,expected_revision_id,request)：乐观并发控制及追加版本。
- get_case(case_id)、find_case_by_code(code)、get_case_revision(revision_id)、list_cases(filter,limit,cursor)。
- health_check()：数据库结构/版本/外键检查；A不宣称检查尚未托管的文件。

request区分身份/版本字段与default_eye/default_exam_date，服务返回稳定UUID。未来Image构造必须显式复制预填值；Run构造必须从Image读取真实眼别/日期。接口不接受模型预测作为病例字段，也不调用推理或P5生成服务。

错误区分VALIDATION_ERROR、CASE_CODE_CONFLICT、STALE_REVISION、IDEMPOTENCY_CONFLICT、STORE_BUSY、STORE_IO_ERROR、SCHEMA_UNSUPPORTED、STORE_CORRUPT。调用失败不伪装空查询结果；日志记录细节，用户提示使用适当摘要。事务回滚失败时关闭连接并拒绝继续写入，不复用未知状态连接。

## 6. P6-A测试设计与验收

后续使用pytest、标准库sqlite3和临时目录，不安装依赖，不触及真实数据库或原实验环境。数据库测试不启动模型；以受控屏障制造并发，不依赖长sleep。所有以下测试均为计划，尚未编写/执行。

| 编号 | 测试场景 | 预期 |
| --- | --- | --- |
| A01 | 显式初始化、重复初始化、打开后重连 | 五表/索引/版本正确；已有库不覆盖；外键每连接启用 |
| A02 | 初始化DDL/发布失败注入 | 不发布半库，错误清晰，可安全重试 |
| A03 | 创建Case、重开读取、编号查询/分页 | UUID稳定、首版完整、时间及值正确 |
| A04 | 编号空/非法/超长，大小写/首尾空白重复 | 拒绝非法；规范重复不能新建第二病例 |
| A05 | 修改编号/备注/默认值与无变化请求 | 追加完整链或返回原版；旧版保持不变 |
| A06 | 相同请求重复创建/更新、同ID不同内容 | 幂等不多写；内容冲突明确失败 |
| A07 | 插入版本后、更新Case前/提交时故障 | Case与revision一起回滚，指针不悬空 |
| A08 | 两连接修改同一expected版本 | 一次成功、一次STALE_REVISION；无丢失更新 |
| A09 | 两连接创建相同规范编号、锁超时 | 唯一性兜底；STORE_BUSY可重试，不产生半记录 |
| A10 | 跨病例前版/当前版本/图像Run关联、删除被引用父项 | FK或服务拒绝；foreign_key_check无异常 |
| A11 | 非法枚举/日期/UUID/哈希/备注，直接SQL修改旧版本 | 服务与DB分层拒绝；旧版本不可覆盖 |
| A12 | Case默认眼别/日期/编号/备注更新 | 用测试夹具建立的历史Image及Run快照逐字段不变；不创建实际工件或标ready |
| A13 | 未结束Run标ready、缺路径/哈希的ready工件 | DB必要条件拒绝；A无任意ready公开接口 |
| A14 | 未知高schema、坏库/无权限、迁移事务模拟中断 | 拒绝写入；不降级、不重建、不吞异常 |
| A15 | SQL特殊字符、返回对象被调用方修改、跨线程使用 | 参数绑定安全；数据库原值不变；连接不跨线程 |
| A16 | 原有P1—P5及轻量P6/P7回归 | 所有现有测试通过；临时分析不会隐式创建仓库 |

A12只使用直接受控数据库夹具证明Case更新不写历史行，不声称托管/自动保存已经实现；B/C将用实际文件和任务验证同一不变量。A13通过约束测试验证必要条件，完整文件校验和跨行发布验收必须在B/C补齐。

拟运行命令（获准开发后）：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_database.py tests/test_case_repository.py -q
.\.venv\Scripts\python.exe -m pytest -q
```

验收交付必须列实际通过数、失败注入位置及回滚结果，检查仓库中的真实数据库/影像未进入Git。不以“计划覆盖”代替“实际通过”。A完成后提供数据字典与接口实施差异、测试记录和对应commit；未经下一段授权，不顺带开发B。

## 7. 本轮文档验证及待审核点

本轮只检查两份计划的本地链接、五表/字段归属、三条审核意见、阶段边界和测试条目，并检查Git差异范围；不运行会生成缓存或输出文件的应用测试，不创建数据库，不修改或提交Git版本。

待审核：五表字段及约束、编号大小写不敏感唯一规则、版本事务、P6-A不开放文件ready写入、B/C前置一致性底线，以及失败/取消最小终态契约。等待人工明确批准P6-A后实施。

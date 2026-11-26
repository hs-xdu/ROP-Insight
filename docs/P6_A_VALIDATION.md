# P6-A 实施与验收报告

日期：2026-11-26。基线提交：`9e82d49`。对应 [已批准实施计划](P6_IMPLEMENTATION_PLAN.md) 与 [详细设计](P6_A_DESIGN.md)。本阶段仅数据库基础及病例版本服务，不包含图像托管、自动终态保存、报告接入或新界面。

## 1. 实际文件清单及Diff审查

| 类型 | 文件 | 内容 |
| --- | --- | --- |
| 新增 | src/rop_insight/models/managed_data.py | 冻结请求/病例/版本对象，UUID、UTC时间、编号、备注、日期、路径和哈希校验；StoreError |
| 新增 | src/rop_insight/migrations/__init__.py | 迁移资源包；导入不创建数据库 |
| 新增 | src/rop_insight/migrations/001_initial.sql | 五表、复合/延迟FK、索引、ready必要条件、不可变版本触发器、user_version=1 |
| 新增 | src/rop_insight/services/database.py | 显式空目录初始化、不覆盖发布、严格结构核对、每线程独立连接/事务、健康检查及错误转换 |
| 新增 | src/rop_insight/services/data_repository.py | 病例新建/追加版本/查询/分页/幂等/并发控制；无Image/Run/工件保存接口 |
| 新增 | tests/test_database.py | 模式/循环外键/状态/故障注入/连接/临时界面回归 |
| 新增 | tests/test_case_repository.py | 病例校验、版本、幂等、真实双连接并发、历史快照不变、分页及输入安全 |
| 新增纳入版本 | docs/P6_IMPLEMENTATION_PLAN.md、docs/P6_A_DESIGN.md | 前两轮审核文档，原先未提交；本轮加入批准状态说明并一并纳入版本 |
| 新增 | docs/P6_A_VALIDATION.md | 本验收、技术决策及设计差异记录 |
| 修改 | pyproject.toml | 仅增加setuptools.package-data以分发迁移SQL；依赖和程序入口不变 |

审查结论：未修改既有UI、AnalysisController/Worker、模型/算法、P4/P5契约、轻量病例/历史模块、启动脚本及原实验环境。没有加入托管文件发布、Run自动保存、备份恢复、孤立目录修复或P7新增界面。测试中的数据库都在临时目录；构建产物位于Git忽略的build/.runtime等目录，不提交真实库或影像。

## 2. 五表最终实现

| 表 | 身份/关系 | 关键约束 |
| --- | --- | --- |
| cases | 内部case_id、匿名编号/小写规范键、当前revision、创建/更新时间 | UUID主键；规范编号全仓库唯一；(case_id,current_revision_id)复合FK延迟到提交检查 |
| case_revisions | 同病例版本链、编号/备注及可选预填默认值 | 前版必须属同一病例；前版不能为自身；UPDATE/DELETE触发器阻止覆盖历史 |
| images | 持久化图像ID、病例/版本、眼别、检查日期、文件元数据 | 同病例复合FK；路径/哈希/尺寸/枚举约束；ready需原图路径、格式、双哈希及正尺寸 |
| analysis_runs | Run ID、持久化及运行时图像ID、病例版本、冻结眼别/日期、结果及状态 | 图像和病例必须匹配；JSON对象约束；终态与保存状态分离；ready需结束时间、结果与管理清单路径/哈希 |
| artifacts | 所属图像、可选Run/报告、工件类型、相对路径与文件哈希 | 复合FK避免跨图工件；相对路径唯一；报告组+工件类型唯一；ready需路径、哈希和非负大小 |

完整字段以SQL和详细设计为准，未增删已批准的五个实体。编号trim后沿用ASCII格式，小写规范键判重；不同Case不能占用同一当前编号，历史编号保留在版本。Case仅保存身份，默认眼别/日期保存在版本且仅为预填；Image拥有实际检查事实，Run拥有冻结快照。

ready是数据库必要条件，不是文件存在性证明：

- success/partial_success必须使用p4_bundle结果契约。
- failed/cancelled允许terminal_record最小结果，也允许确有P4包时使用p4_bundle。
- 所有ready Run需实际终态、结束时间、结果JSON和run_manifest路径/哈希；不要求所有Mask、报告、A6类别或source_snapshot_sha256齐全。
- ready Image/Artifact有各自必要字段。数据库不能独立验证文件存在及跨行清单完整，后续B/C统一发布服务负责；A没有公开set_ready/保存Run/保存工件接口，不声称已实现文件验收。
- 完整性状态独立，后续有效读取必须同时满足ready及valid；已保存但后来缺失/损坏可标记，不抹去原分析状态。

## 3. 最终接口及事务

`initialize_new_store(root)`：仅显式新建空目录；同目录临时SQLite文件，显式事务执行初版DDL和版本设置，结构/quick_check/foreign_key_check通过后关闭连接，再无覆盖发布。失败不留下正式半库；竞争创建的目标不会被覆盖。

`open_store(root)` / `DataStore.health_check()`：不隐式创建，核对user_version、表/索引/触发器完整模式、SQLite完整性、外键和当前病例/版本编号一致性。返回database=ok、files=not_checked，避免把数据库检查冒充文件检查；未知版本或异常结构拒绝写入。

`CaseRepository`：create_case、update_case、get_case、find_case_by_code、get_case_revision、list_cases、health_check。分页按(created_at,case_id)，调用方使用上一页末项作为游标。读取返回冻结对象，未找到返回None；异常不伪装为“未找到”。

- 创建：BEGIN IMMEDIATE → 幂等/编号核对 → 插入Case → 插入首版 → 读取核对 → COMMIT。Case当前版本的延迟循环FK在COMMIT前必须满足。
- 更新：先核对新revision请求是否已执行，之后核对expected_revision_id → 无变化直接返回 → 追加前版链 → CAS更新当前指针/编号 → COMMIT。编号冲突或提交失败同时撤销版本和指针。
- 幂等：同UUID/版本/冻结时间及内容重试返回对应历史快照，不因当前已经有新版本而再次写入；同ID不同内容明确冲突。
- 并发：每次调用在所属线程创建连接，BEGIN IMMEDIATE序列化写入；expected_revision实现乐观并发。A是无GUI服务库，未启动后台写入队列或修改应用线程；B/E接入时按计划在后台调用。
- 每连接启用并检查外键、busy_timeout=5000ms、DELETE日志和FULL同步；显式事务，不使用executescript隐式提交。异常回滚，回滚失败强制关闭连接并报告IO错误；不复用未知状态连接。

错误码包括VALIDATION_ERROR、CASE_CODE_CONFLICT、STALE_REVISION、IDEMPOTENCY_CONFLICT、STORE_BUSY、STORE_IO_ERROR、SCHEMA_UNSUPPORTED、STORE_CORRUPT。底层异常保留cause，调用者可记录具体诊断。

## 4. 实际测试与故障注入

专项命令：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_database.py tests/test_case_repository.py -q
```

实际结果：84 passed，无跳过。测试均使用临时数据；现有窗口不自动创建SQLite也有明确回归测试。

| 注入/验证 | 实际结果 |
| --- | --- |
| 创建Case后未插入首版，提交触发延迟FK失败 | 插入阶段可见待满足FK，COMMIT失败后Case回滚；补齐首版的事务可以成功 |
| 首版插入前/后抛异常、版本追加后及CAS前抛异常 | 无孤立Case/revision；旧版本及当前指针完整保留 |
| 追加版本后注入另一无效延迟指针，使提交失败 | 本次新版本和指针一起回滚，旧记录可读 |
| DDL错误、初始化提交失败、发布权限错误 | 不发布正式半库；本次临时库清理，可重试 |
| 发布目标竞争出现 | 已有目标字节不变，初始化明确失败 |
| 两真实连接同时更新同一expected版本 | 仅一个成功，另一个STALE_REVISION，无丢失更新 |
| 两真实连接同时创建同一规范编号 | 仅一个成功，另一个CASE_CODE_CONFLICT；无半记录 |
| 锁占用/短超时、query_only拒写 | STORE_BUSY/STORE_IO_ERROR，原记录不受影响 |
| 限制SQLite max_page_count触发真实SQLITE_FULL | 转换保存错误；Case与revision数量一致，无孤立版本，健康检查仍通过 |
| 回滚方法本身失败 | 连接仍被关闭，未提交行不残留，新的独立连接可读 |
| 未知版本、异常表结构/索引、坏库、外部禁用FK写入孤立指针 | 拒绝打开或健康检查报错，不自动修复/降级 |
| 跨病例版本/跨图Run与工件、修改/删除历史版本 | FK或不可变触发器拒绝 |
| 四类终态ready及缺字段/运行中ready | 合法终态通过；缺少必要字段拒绝，失败/取消不要求P4全包 |
| 修改病例编号/默认检查信息/备注 | 历史Image与Run测试夹具逐字段不变；没有进行文件托管 |

全量回归：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

实际结果：291 passed（已有207＋P6-A新增84），无跳过。最终命令在全部改动后复验，P4/P5报告生成和旧轻量P6/P7用例保持通过。本轮未做模型训练或修改算法。

构建核对：项目venv缺少setuptools，直接pip离线构建失败；没有安装或更新依赖。改用已存在的独立Python 3.12构建运行时离线生成wheel，检查001_initial.sql与源文件字节一致，再用项目Python在隔离进程中从wheel直接导入并初始化临时库、创建/读取病例，全部通过。构建运行时仅用于打包，不替代项目测试环境；正式安装包部署仍不在本阶段。

## 5. 与详细设计的差异/细化

没有改变数据实体或事务设计的实质性偏离，未扩大阶段范围。实现细化如下：

1. SQL位于rop_insight.migrations包；pyproject仅补包资源声明，保证wheel中资源可用。没有增加依赖或运行配置。
2. UTC时间规范为含微秒的+00:00 ISO格式；新版本时间不早于当前版本。调用方保留请求时间以支持严格幂等。
3. 报告文字工件区分summary/detail两类，保留P5实际两份文字输出；不改变P5字段或新增报告内容。
4. Windows用不覆盖rename发布初始库；POSIX仅为辅助兼容，使用不覆盖硬链接发布临时库。不引入通用原图/结果文件托管。
5. A只实现新库v1及严格模式检查；不交付跨版本生产库升级、备份恢复或孤立目录修复。初版DDL执行和user_version设置在同事务，相关失败回滚已测；未来真正升级另按F的备份前置要求实施。
6. 原先审核文档未进入Git，本次与实现一并保存；文首标明已批准及实施记录，保留历史设计基线以用于论文过程追踪。

## 6. Git记录与停止点

基线9e82d49；本次提交主题：`feat: implement P6-A SQLite schema and versioned case repository`。实现、审核文档、测试和本记录纳入同一阶段提交，具体短哈希见交付回复及git log；不把提交自身哈希预写进其内容。

已完成P6-A工程实现与本机测试，待人工验收。P6-B未启动：没有给当前图像托管原文件，没有为现有Run自动落库，没有重构P5或新增历史界面。等待明确批准后才能继续。

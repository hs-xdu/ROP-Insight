# P6-B 原图与输入Ridge托管

已完成工程实现和本机自审，待用户人工验收。基线：`1f50703`；范围见 [实施约定](P6_B_SPEC.md)。不接入Run自动保存或正式病例界面，不修改数据库结构、模型、算法或P4/P5数据契约。

## 简单运行与验收

正式平台仍用：

```powershell
cd "E:\8 大论文\ROP_System"
.\run-platform.ps1
```

本次功能用独立验收窗口查看：

```powershell
cd "E:\8 大论文\ROP_System"
.\.venv\Scripts\python.exe tests\manual_p6_b.py
```

依次点击三个按钮：

1. **托管原图和输入Ridge**：提示托管完成，数据库状态ready/valid。
2. **移走源文件，从仓库重新打开**：仍显示原图及粉色Ridge叠加，说明读取的是托管副本。
3. **损坏演示副本，验证阻止打开**：图像区清空并提示损坏副本未打开，这是预期结果。

只使用自动生成的合成图像，每次启动创建独立`.runtime/p6-b-demo/<随机目录>/`，不操作用户图像、不运行模型。预期损坏错误写入演示目录acceptance.log。正式平台的病例/托管操作界面留到P6-E，原有功能保持原用法。

## 本次实现

- 明确病例UUID/资料版本与Image关联；眼别、日期是Image事实，不随病例默认值或编号修改而变化。
- 原图原字节复制并读回校验文件SHA256、解码RGB像素SHA256、尺寸和格式。支持PNG/JPG/JPEG、中文原文件名，源路径不保存进清单。
- 可选输入Ridge保存原文件和规范化0/255二值副本，复用原load_ridge检查二值、大小、对齐及归一化像素，不修改算法。
- 文件保存到images/<image_id>/，仅相对路径；移动整个仓库后可重开。原图不会因重复保存同一个请求而复制多份；同哈希不会跨病例自动合并。
- pending/saving/ready/write_failed与unchecked/valid/missing/corrupt分开。复制与哈希不占长SQLite事务；文件发布并校验后，原图/清单工件与Image ready状态在同一事务提交。
- 幂等核对图像、操作ID及全部冻结内容（含Ridge），相同请求重试复用；不同内容报冲突。源文件移动/删除后，已经托管的图像仍可校验和读取。
- 发布后数据库登记失败，保留已发布文件和未完成记录，阻止当作有效数据；同一请求重试时先重新验证，再补登记，源文件已不在也可完成。不同来源、不明临时目录、缺请求证据不自动修复。
- 读取时核对SQLite工件、清单、文件哈希、像素与身份，缺失/损坏阻止打开并更新完整性状态；权限或存储错误标为unchecked。原图/Ridge在检查后发生变化也再次核对；没有声明的Ridge不会被读取。
- 单文件上限256MiB，解码上限4000万像素；使用已有QThread控制器进行后台导入和取消。关闭独立验收窗口会取消/等待，不提前销毁运行线程。

## Ridge与五表兼容说明

P6-A的input_ridge工件要求关联Run；B不伪造尚未存在的Run、不改变schema。待分析Ridge由image_manifest.json完整关联与哈希校验，作为图像导入输入准备；artifacts仅登记original_image和image_manifest，两者同事务发布。C实施时再按实际Run冻结输入来源。这里不是把Ridge称为分割模型输出。

主要接口：ImageImportRequest.capture、ManagedImageStore.import_image/get_image/inspect_image/open_image/open_ridge/find_duplicates/incomplete_images、ImageImportController.start_request/cancel。get_image和重复提示只返回元数据；实际使用必须经过inspect/open校验。

## 测试与自审

专项：`python -m pytest tests/test_managed_store.py tests/test_p6_b_acceptance.py -q`：**53项通过**。

全量：`python -m pytest -q`：**344项通过**（既有291＋新增53），无跳过。

涵盖PNG/JPEG、Ridge可选、中文名、源文件删除及仓库移动、病例修改隔离、幂等/冲突、原文件变更、尺寸/像素伪造、复制/发布/工件插入/提交故障、发布后重试、取消/并发锁、路径穿越与Windows junction、文件缺失/篡改、异常临时目录不误删、后台线程和安全关闭、三步窗口实际操作。新窗口逐步截图已检查，私有验收输出在`.runtime/p6-b-validation/`，不提交数据库、图片或截图。

自审补强：只清理本次创建的已知临时文件；不递归删除未知内容；发布后和打开时二次校验；拒绝未声明Ridge；取消检查不会误标文件损坏。继续复用P6-A五表，不修改旧迁移或版本号。

## 文件、限制与停止点

新增models/managed_image.py、services/managed_store.py、services/image_import_controller.py、tests/manual_p6_b.py、test_managed_store.py、test_p6_b_acceptance.py及本阶段文档；更新README、RUNBOOK及计划状态。无依赖或运行配置改动，未修改现有主窗口或原实验环境。

仓库写入用排他操作锁串行化；异常进程退出可能留下锁/请求/临时目录，前期明确阻断并提供incomplete_images，不自动删除锁或修复不明目录。完整恢复、备份、孤立目录处理仍在F；不是数字签名或并发恶意修改防护系统。同一图像在B登记的输入清单不可原地换Ridge，C再提供按Run的独立输入管理。

已完成并提交P6-B后停止，等待用户验收与P6-C授权。提交主题：`feat: add P6-B managed image and Ridge input storage`，具体哈希见交付回复与git log。

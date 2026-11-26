# 运行与交付说明

## 本机启动

在项目目录打开 PowerShell，执行：

```powershell
.\run-platform.ps1
```

新入口以脚本目录解析路径，也可从其他工作目录调用。本机沿用 `configs/p3b.local.json`：手动 Ridge、真实 VascX、A6 深圳、第五章量化、连续评分及 11 项特征的冻结 SVM。旧 `run-scoring.ps1` 等阶段入口仍可使用。普通 `run.ps1` 是未配置模型的查看器。

操作顺序：导入 JPG/JPEG/PNG → 导入同尺寸二值 Ridge PNG（不透明灰度，0/1/255）→ 开始分析 → 左侧向下滚动查看量化、评分和两套独立分类 → 导出分析结果。没有 Ridge 时不能启动完整模型流程。失败原因显示于模块状态，日志在 Qt 本地应用数据目录的 `ROP-Insight/logs/analysis.log`，子进程工件保留在本地应用数据目录，可能包含眼底图像；不应作为普通软件文件对外分享。

P5另提供“预览辅助分析报告”：任务结束后打开简要/详细报告，在报告窗口选择“导出PDF报告”，生成独立报告目录中的PDF、精确JSON、文字和来源清单。无需重新推理或填写病例信息；详细用法及固定模板规则见 [P5说明](P5.md)。复验命令添加 `--report` 可检查P5预览、后台PDF及P4来源一致性。

## 新机器源码运行

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
Copy-Item configs\p3b.example.json configs\p3b.local.json
```

编辑 local 配置的路径，准备与 [环境记录](ENVIRONMENT_LOCK.md) 一致的独立算法环境和已授权模型资料。不要向 GUI 环境安装所有算法依赖，不要仅更改哈希来绕过一致性检查。必须匹配既有代码、模型、配置和参考输出；迁移后重新运行自检及真实参考验证。已有环境无需重建。未提供权重下载、自动安装研究环境或已验证的安装包。

## 只读自检和测试

```powershell
.\.venv\Scripts\python.exe -m rop_insight.services.runtime_check --config configs\p3b.local.json --probe
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pip check
```

自检只读取配置、源文件、权重和环境，校验 SHA-256、包导入及指定 CUDA 是否可用；`--probe` 会在研究解释器内读取元数据并实际导入主要库，不安装包、不推理。输出包含元数据与导入版本差异。退出码 0 表示所执行的检查通过，不代表真实推理或临床验证已通过。输出文件可用 `--output 路径`，父目录需已存在。

自检发现 CUDA 不可用时检查配置指定的解释器/驱动，程序不会自动改用 CPU。缺权重、代码哈希变化或 SVM 环境版本不一致时恢复原工件；不得使用不同算法输出代替。导出写入失败时选择可写目录、检查空间，原结果仍可重试。

## 真实参考复验

使用已授权的图像、对应 Ridge 和原实验缓存，输出写入本地私有目录：

```powershell
.\.venv\Scripts\python.exe scripts\validate_system.py --config configs\p3b.local.json --image "E:\reference\image.png" --ridge "E:\reference\ridge.png" --reference "E:\reference\expected_features.json" --output ".runtime\my-validation"
```

`--reference` 可省略，但省略后不代表通过原数值对照。它应为原特征提取缓存的平铺 JSON；比较使用相对容差 1e-6、绝对容差 1e-8，并逐项记录实际差异。现有参考样本十项差异均为 0。

脚本记录五模块、截图、导出、缩放独立性、清除行为、响应与资源观察；超过 `--timeout`（默认 600 秒）取消。`--expect-partial` 用于有意设置 A6 缺权重而保留量化/SVM 的验收配置。验证输出目录可能包含眼底影像和研究输出，默认位于 Git 忽略的 `.runtime`。参考特征的一致性不等于全数据集性能或临床有效性。

## 交付边界

当前为 Windows 本地、单图、用户提供 Ridge 的研究原型。自动 Ridge、批处理、患者数据库、云服务和正式安装包不在本轮已验证成果内。自动 Ridge 暂缓使第二版总体验收第 2 项尚不完整；V1.0 尚未宣告全部验收通过。用户仍可检查实际操作手感、目标设备和新病例上的表现，所有预测应保留研究用途属性。

## P6/P7 病例资料与历史复核

使用原入口 `.\run-platform.ps1`，左侧向下滚动可见“匿名病例信息”和“历史分析记录”。导入图像后自动生成新的匿名编号；点击病例信息编辑编号、眼别、可选日期、备注，“保存并关联”后选择本地位置。取消或保存失败不改变当前资料。换图会生成新编号；同一研究病例的另一只眼或另次检查请手动填写相同研究编号。

分析结束后，导出分析结果或PDF报告到自己选择的成果目录；导出会附带病例资料版本，PDF预览包含相同病例快照。已保存报告不会随病例修改变化，再次预览/导出产生新报告。单独保存病例JSON不代表已保存分析或报告。

“历史分析记录”无需先导入图像。选择具体成果目录，等待后台扫描；输入病例编号筛选，选择记录查看模型版本、原图/像素哈希及原JSON。点击“重开已有 PDF”或“查看已有文字报告”读取原文件，不重新运行模型。仅P4分析的旧记录显示“未关联病例/报告未生成”。需核对原图时手动选文件，后台比较SHA256，不更改关联。刷新可在移动整个导出目录后重建列表。

扫描只到8层，最多10000目录/5000记录；单JSON≤4MiB、JSON总量≤64MiB、单文件哈希≤256MiB。请选择专用成果文件夹，不能选磁盘根目录或链接目录。取消/失败保留上次成功列表，校验异常记录不可重开关联文件。哈希表示记录内一致性，不是数字签名；本地历史复核不代表医学审签。详见 [P6/P7说明](P6_P7.md)。

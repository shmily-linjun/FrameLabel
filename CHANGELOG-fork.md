# CHANGELOG-fork.md

本文件记录本 fork 相对上游 [X-AnyLabeling](https://github.com/CVHub520/X-AnyLabeling) 4.3.2 的改动。

版本规则：`4.3.2+fork.N`（N = 1, 2, 3 …，PEP 440 本地版本写法，语义等价于「4.3.2 fork N」）。
采用 `+` 形式是 PEP 440 唯一合法写法；`4.3.2-fork.1` 等写法会被 `packaging.version` 判为非法，
进而影响 `python -m build` 与 `update_checker` 的版本比较。

## 4.3.2+fork.60 — 2026-11-26

### 1. 背景与需求

用户对“原生文件对话框”提出四点：①为何不用 Qt 的 `QFileDialog`、当前
`DontUseNativeDialog` 是什么；②`QFileDialog`/`getExistingDirectory`/
`getOpenFileName`/`getSaveFileName` 在 Linux/macOS 是否可用；③若可用，把所有文件/文件夹
对话框统一换成 Qt 静态 API（这才是 fork.42 的本意）；④对话框是否散落、是否需要集中。

### 2. 结论与实现

- **语义澄清**：`DontUseNativeDialog=False`（默认）= 系统原生对话框；`True` = Qt 自绘。
  两者都是 Qt 的 `QFileDialog` API，差别只在“谁来画”。fork.59 之前
  `FileDialogPreview` 用 `True`（为了嵌入预览面板），其余调用点默认原生。
- **跨平台**：四个静态 API 在 Linux/macOS 可用；Linux 由平台主题/portal 决定原生或回退
  自绘，macOS 使用原生面板。限制是原生对话框**不能嵌入自定义控件**。
- **统一替换（本批）**：
  - 新增 `anylabeling/views/file_dialogs.py`：`choose_directory`/`choose_open_file`/
    `choose_open_files`/`choose_save_file`，一律调用 Qt 静态 API、不设置
    `DontUseNativeDialog`、返回值归一化。
  - `file_session.open_file` 去掉 `FileDialogPreview` 子类，改用 `choose_open_file`；
  - `file_session.save_file_dialog` 去掉“构造实例 + 再调用静态方法”的死配置，改用
    `choose_save_file`（原实例上的 `setDefaultSuffix`/`setAcceptMode` 本来就不会生效）；
  - 自动标注“加载自定义模型配置”去掉 `QFileDialog` 实例，改用 `choose_open_file`；
  - **删除** `widgets/file_dialog_preview.py` 及其导出与测试（预览面板与非原生对话框绑定，
    与“全部原生”互斥；如需预览，只能作为显式例外单独设计）。
- **集中评估**：全仓库约 90 处对话框调用，其中绝大多数已经是 Qt 静态 API；真正需要改的
  只有上述 3 处实例/子类。结论：**政策集中、调用点分阶段迁移**——新 helper 统一
  native 政策与返回值，其余约 80 处保持静态调用不动，避免一次性大范围重写带来的回归；
  后续按模块机械替换即可。
- i18n：新增 1 条文案（`Select model configuration` → 选择模型配置），四语言 `.qm`
  各 2752 条，zh/en 0 未翻译。

### 3. 涉及文件

- 新增 `anylabeling/views/file_dialogs.py`、`tests/test_widgets/test_file_dialogs.py`
- 修改 `anylabeling/views/labeling/file_session.py`、
  `anylabeling/views/labeling/widgets/auto_labeling/auto_labeling.py`、
  `anylabeling/views/labeling/widgets/__init__.py`、翻译资源
- 删除 `anylabeling/views/labeling/widgets/file_dialog_preview.py`、
  `tests/test_widgets/test_file_dialog_preview.py`
- 文档/版本：`app_info.py`、`CHANGELOG-fork.md`、`docs/dev/CODE_STRUCTURE_REPORT.md`、
  `docs/dev/工业机器视觉数据平台-设计书-v1.6.md`、`docs/开始.md`

### 4. 行为、接口与兼容性

- “打开文件”对话框改为系统原生，**不再显示图片/JSON 预览面板**（原生限制）；
- “保存标注”对话框行为不变（此前实例配置未生效，返回值逻辑一致）；
- 自动标注自定义模型配置选择改为原生；
- 其余文件/文件夹对话框保持原样（本来就调用 Qt 静态 API，默认原生）。

### 5. 验证

- `tests/test_widgets/test_file_dialogs.py` **6 passed**（四个助手均为 native、取消返回空、
  打开/保存走 helper）；
- `tests/test_widgets + test_dataset_db + test_utils + test_identity + test_i18n`：
  **388 passed / 1 failed（既有计时抖动）/ 108 subtests**；
- `tests/test_i18n` 17 passed；四语言 `.qm` 各 2752 条，zh/en 0 未翻译。
- **未执行**：真实桌面点击“打开文件/保存”（本机无 GUI 会话），原生行为需在用户桌面确认。

### 6. 已知限制

- 原生对话框的 `DontResolveSymlinks`/`ShowDirsOnly` 等选项在部分平台会被忽略（Qt 文档行为）；
- 预览面板功能随本批移除，如需恢复只能走非原生例外；
- 约 80 处调用点尚未迁移到 helper（行为已经是原生，仅政策未集中）；
- 推送仍受本机网络/凭据阻塞；本地 `main` 领先远端 13 个提交。

## 4.3.2+fork.59 — 2026-11-25

### 1. 背景与问题

用户点击 `文件 → 打开文件` 时软件崩溃：

```
File ".../file_dialog_preview.py", line 49, in __init__
    self.layout().addLayout(box, 1, 3, 1, 1)
AttributeError: 'NoneType' object has no attribute 'addLayout'
```

### 2. 原因

fork.42（`ce05c0d`，原生文件对话框）把 `FileDialogPreview` 的
`DontUseNativeDialog` 从 `True` 改成了 `False`，于是 Windows 使用系统原生对话框；
原生对话框没有 Qt 的 `layout()`，而该类正是靠往 `layout()` 里加预览面板实现
“选中文件旁显示图片/JSON 预览”的，构造时即崩溃。

### 3. 修复

- `FileDialogPreview` 恢复 `DontUseNativeDialog = True`（该对话框必须用 Qt 自己的
  控件树才能加预览面板）；
- 增加防御：`layout()` 为 `None` 时只记录警告并跳过预览面板，不再抛异常（避免
  未来平台/主题差异导致同类崩溃）；
- 新增回归测试 `tests/test_widgets/test_file_dialog_preview.py`：
  - 构造后 `DontUseNativeDialog` 为真、`layout()` 非空、预览初始隐藏；
  - 用最小宿主调用 `FileSession.open_file()`（`exec` 被替换为取消），确认构造路径不再崩溃。
- 版本：`4.3.2+fork.58` → `4.3.2+fork.59`。

### 4. 涉及文件

- `anylabeling/views/labeling/widgets/file_dialog_preview.py`
- `tests/test_widgets/test_file_dialog_preview.py`（新增）
- `anylabeling/app_info.py`、`CHANGELOG-fork.md`、`docs/dev/CODE_STRUCTURE_REPORT.md`

### 5. 行为与兼容性

- “打开文件”对话框恢复“图片/JSON 预览”面板；其余原生文件对话框（保存、选择目录、
  移动文件等）不受影响，仍是 fork.42 的原生行为；
- 无接口/数据格式变化。

### 6. 验证

- `tests/test_widgets/test_file_dialog_preview.py` **2 passed**；
  `tests/test_widgets + test_dataset_db + test_utils + test_identity + test_i18n`：
  **383 passed / 1 failed（既有计时抖动）/ 108 subtests**。
- 未执行：真实桌面点击“文件 → 打开文件”（本机无 GUI 会话），但构造路径已被用例覆盖。

### 7. 已知限制

- 该对话框为非原生，视觉风格与应用内 Qt 对话框一致，不再跟随 Windows 原生文件框主题
  （预览功能所需，属预期）；
- 推送仍受本机网络/凭据阻塞；本地 `main` 领先远端 12 个提交。

## 4.3.2+fork.58 — 2026-11-25

### 1. 背景与需求

用户提出三项改进：

1. 数据集中心已有 TabWidget，汇总表也应放进去；“类别/标签”表格补“占比”列；
2. “标签过滤”tab 名称改为“类别”，与主界面右侧栏一致；
3. 右侧“图像属性”页“标签库”改为**不变动**（已用于当前图片的标签不再从库中消失），
   理由：右键搜索需要完整词表、减少代码复杂度、实现“图像属性”页与批量标签窗口的无差异复用。

### 2. 分析结论（第 3 项）

用户判断成立，且比“隐藏已用标签”更科学：

- 标签库在本项目里承担**词表 + 搜索入口**双重职责（右键/Ctrl+单击按标签过滤图片）。
  移除已用标签会让该标签在库中消失，无法再按它搜索——这是功能缺陷而不是简化；
- “隐藏已用”需要在每次标签变更时重算 missing 集合、同步计数与空状态，分支更多；
  显示完整词表后列表稳定，`_missing_entries()` 删除，渲染分支收敛；
- 批量标签窗口只是“选标签”的同一控件，词表稳定后无需为两个宿主维护不同语义。
- 唯一需要在意的点（重复添加）用“弱化标记 + 双击已存在标签提示”解决，不改变列表内容。

### 3. 主要实现

- **数据集中心概览**：`QTabWidget` 三页——概览（指标/数值/占比）、类别（类别/图片/对象/
  图片占比/对象占比）、标签（标签/图片/图片占比）；汇总表移入 tab 并默认选中“概览”；
  tab 顺序固定，类别/标签的占比按图片总数、对象总数计算，空库显示“-”。
- **tab 名称**：`DatasetCenterWindow` 的 `Classes` 译文由“标签过滤”修正为“类别”
  （此前是翻译记忆按源文复用了自动标注页的错误译文）。
- **标签库**（`TagLibraryWidget`）：始终显示完整词表；已用于当前图片的标签弱化显示并在
  tooltip 追加“已在此图片中。”；双击已存在标签不再写入，改为状态栏提示
  “该标签已在此图片中。”；计数显示词表总数；空词表文案改为“当前文件列表中没有标签。”；
  新增 `status_message` 信号并在工作区接到状态栏。
- i18n：新增/修正 7 条文案，四语言 `.qm` 各 2753 条，zh/en 0 未翻译。

### 4. 涉及文件

- `anylabeling/views/dataset_center.py`
- `anylabeling/views/labeling/widgets/tag_library.py`、`widgets/workspace.py`
- `tests/test_widgets/test_tag_library_widget.py`、`test_dataset_center.py`、
  `tests/test_i18n/test_translations.py`（文案期望）
- 翻译资源、`app_info.py`、`CHANGELOG-fork.md`、`docs/dev/CODE_STRUCTURE_REPORT.md`、
  `docs/dev/工业机器视觉数据平台-设计书-v1.6.md`、`docs/开始.md`

### 5. 行为、接口与兼容性

- 数据集中心概览：信息组织变化（汇总表在 tab 内），列增加；不改变数据统计口径。
- 标签库：列表内容稳定；已用标签变为可点击/可搜索但弱化；双击已用标签无写入；
  批量标签窗口复用同一控件，行为一致。
- 无数据格式/DB schema 变化。

### 6. 验证

- `tests/test_widgets/test_tag_library_widget.py` **9 passed**（新增“已用标签仍在列表/
  可搜索”“双击已用标签无操作”）；`tests/test_widgets/test_dataset_center.py` **5 passed**
  （三 tab、列数断言）。
- `tests/test_widgets + test_dataset_db + test_utils + test_identity + test_i18n`：
  **382 passed / 1 failed（既有计时抖动）/ 108 subtests**。
- 离屏中文核对：tab 为“概览/类别/标签”，表头“图片占比/对象占比”；
  标签库条目 `['aaa','bbb']`、计数 `(2)`。
- 四语言 `.qm` 各 2753 条，zh/en 0 未翻译。
- **未执行**：真实桌面查看三 tab 排版与标签库弱化效果（本机无 GUI 会话）。

### 7. 已知限制

- 标签库弱化色使用 `text_secondary`，主题切换后需重新 `set_entries()` 才更新颜色；
- 概览表仍一次加载全部类别/标签；
- 推送仍受本机凭据/网络阻塞；本地 `main` 领先远端 11 个提交。

## 4.3.2+fork.57 — 2026-11-25

### 1. 背景与需求

用户反馈 fork.56 的“当前数据集”chip 位于标题栏右侧不合理，应放在**标题栏中间**；
其他功能保持。

### 2. 主要实现

- `TitleBar` 新增 `add_center_widget()`：chip 作为标题栏子控件（不进入水平布局），
  按窗口宽度居中；窗口缩放时重新定位。
- 窄窗口保护：居中位置被夹在“菜单栏右边缘”与“右侧控件（操作员 chip/窗口按钮）左边缘”
  之间；右侧控件通过 `_right_widgets` 跟踪，避免与操作员 chip 重叠。
- `FramelessWindow.add_center_widget()` 对外暴露；`MainWindow._install_dataset_chip()`
  在无边框模式下改用它（原生模式仍在工具栏）。
- 测试：`test_center_widget_sits_in_the_middle`（TitleBar 级）与
  `test_dataset_chip_is_centered_in_the_title_bar`（真实 MainWindow、1600px 宽度，
  断言 chip 中心与标题栏中心偏差 ≤ 1/6 宽度且不越过最小化按钮）。
- 版本：`4.3.2+fork.56` → `4.3.2+fork.57`。

### 3. 涉及文件

- `anylabeling/widgets/frameless/title_bar.py`、`anylabeling/widgets/frameless/window.py`
- `anylabeling/views/mainwindow.py`
- `tests/test_widgets/test_frameless_window.py`、`tests/test_widgets/test_mainwindow_state.py`
- `anylabeling/app_info.py`、`CHANGELOG-fork.md`、`docs/dev/CODE_STRUCTURE_REPORT.md`、
  `docs/dev/工业机器视觉数据平台-设计书-v1.6.md`、`docs/开始.md`

### 4. 行为与兼容性

- chip 仍显示/切换/打开中心/关闭数据集，行为不变，仅位置改变；
- 原生边框模式不变（chip 在工具栏）；
- 标题栏其余控件（菜单、操作员 chip、窗口按钮）布局不变；窄窗口下 chip 会被夹紧而不是覆盖控件。

### 5. 验证

- `tests/test_widgets/test_frameless_window.py` **20 passed**（含居中用例）；
  `tests/test_widgets/test_mainwindow_state.py` **5 passed**（含 MainWindow 居中用例）；
  `tests/test_widgets + test_dataset_db + test_utils + test_identity + test_i18n`
  **381 passed / 108 subtests**。
- **未执行**：真实桌面查看 chip 居中后的视觉效果（本机无 GUI 会话）。

### 6. 已知限制

- 居中为“窗口中心”，标题栏左侧的图标/标题/菜单较宽时 chip 会被夹向右侧（防止重叠）；
- 推送仍受本机凭据/网络阻塞；本地 `main` 领先远端 10 个提交。

## 4.3.2+fork.56 — 2026-11-25

### 1. 背景与需求

用户同意“标题栏 chip”方案，要求实现：在窗口标题栏显示当前数据集，并提供
打开数据集中心 / 切换数据集 / 关闭数据集的快捷操作。

### 2. 主要实现

- 新增 `DatasetChip`（`views/labeling/widgets/dataset_chip.py`，`QToolButton`）：
  - 文本：有数据集时“数据集：<名称>”（名称优先取注册表显示名，其次 `dataset.name`，
    最后目录名；过长省略）；无数据集时“未打开数据集”；
  - 菜单懒构建（`aboutToShow`）：当前数据集信息行、“数据集中心…”、“切换数据集”
    （列出注册表 active 项，排除当前项，最多 20 条）、“关闭数据集”（无数据集时置灰）；
  - 信号：`open_center_requested`、`open_dataset_requested(root)`、`close_dataset_requested`。
- `LabelingWidget` 新增 `dataset_changed` 信号与 `close_dataset()`；`FileSession` 在
  打开/关闭数据集时发射信号，并新增 `close_dataset()`（确认未保存修改→重置状态→清空
  文件表→关闭数据库→状态栏提示“数据集已关闭”）。
- `MainWindow` 安装 chip：无边框模式放入自定义标题栏（`add_title_widget(key="dataset")`），
  原生边框模式放入工具栏；连接三个信号到标注窗口的方法，`dataset_changed` 驱动
  `_update_dataset_chip()` 刷新显示。
- i18n：新增 10 条文案（No dataset/Dataset: %s/Current: %s/Switch dataset/Close dataset/
  No other datasets/Dataset closed 等），已补中文；四语言 `.qm` 各 2748 条，zh/en 0 未翻译。

### 3. 涉及文件

- `anylabeling/views/labeling/widgets/dataset_chip.py`（新增）
- `anylabeling/views/mainwindow.py`、`views/labeling/label_widget.py`、
  `views/labeling/file_session.py`
- `tests/test_widgets/test_dataset_chip.py`（新增 3 个用例）
- 翻译资源、`app_info.py`、`CHANGELOG-fork.md`、`docs/dev/CODE_STRUCTURE_REPORT.md`、
  `docs/dev/工业机器视觉数据平台-设计书-v1.6.md`、`docs/开始.md`

### 4. 行为与兼容性

- 标题栏/工具栏新增 chip，不改变原有菜单与工具栏动作；
- 无数据集时 chip 显示“未打开数据集”，关闭动作置灰；打开/切换/关闭均复用现有
  `import_image_folder`/`close_dataset` 路径；
- 关闭数据集不影响注册表记录（数据集仍列在中心，状态 active）。

### 5. 验证

- `tests/test_widgets/test_dataset_chip.py` **3 passed**；`tests/test_widgets` **91 passed /
  1 failed（既有计时抖动）**；`tests/test_dataset_db + test_widgets + test_utils +
  test_identity + test_i18n` 通过（除既有抖动外）。
- 离屏中文核对：chip 文本“数据集：演示数据集”、tooltip“当前数据集：…”、菜单
  “当前：… / 数据集中心… / 切换数据集 / 关闭数据集”。
- 四语言 `.qm` 各 2748 条，zh/en 0 未翻译。
- **未执行**：真实桌面查看标题栏 chip 位置与点击行为（本机无 GUI 会话）。

### 6. 已知限制

- “切换数据集”最多列 20 条，更多请打开数据集中心；
- 原生边框模式下 chip 在工具栏而非菜单栏右侧（避免与操作员 chip 争用角落）；
- 推送仍受本机凭据/网络阻塞；本地 `main` 领先远端 9 个提交。

## 4.3.2+fork.55 — 2026-11-25

### 1. 背景与需求

用户对数据集中心提出四项改进：

1. 缺少快捷入口，考虑在工具栏添加“数据集中心”按钮；
2. 统计总览不便于查看，建议改为表格；
3. “打开文件”按钮更名为“打开数据集”；
4. 合并时目标数据集用下拉选择很好，但同名数据集无法区分，建议显示“名称（路径）”。

### 2. 主要实现

- **工具栏入口**：`dataset_center` 动作加入工具栏（`actions/tool` 首位，`layers` 图标），
  并保留 `文件 → 数据集中心…` 菜单入口；工具栏设置列表可单独隐藏/显示。
  未采用“仅标题栏 chip”方案：工具栏是当前主界面唯一常驻快捷区，标题栏 chip 作为后续增强
  （需要同时显示“当前数据集”状态，设计方案 §4.7 已预留）。
- **概览表格**：右侧概览由纯文本改为表格——
  - 汇总表三列：指标 / 数值 / 占比（图片、回收站、训练、验证、测试、未划分、对象、类别、标签种类）；
  - 下方 `QTabWidget` 分“类别”（类别/图片/对象）与“标签”（标签/图片）两页，全部只读、行选择；
  - 数据集名称与路径显示在概览上方的提示行。
- **按钮更名**：`Open` → `Open Dataset`（中文“打开数据集”），菜单/工具栏文案不变（“数据集中心…”）。
- **合并目标路径**：目标下拉文本改为 `显示名 (数据库路径)`，同名数据集可区分；
  来源列表仍用显示名（来源在中心里已由用户多选确定）。
- i18n：新增 13 条文案（Open Dataset/Metric/Value/Share/Category/Objects/Tag/Recycle bin/
  Train/Val/Test/None/Tag kinds），已补中文；四语言 `.qm` 各 2737 条，zh/en 0 未翻译。

### 3. 涉及文件

- `anylabeling/views/labeling/actions/builder.py`（工具栏动作）
- `anylabeling/views/dataset_center.py`（概览表格、按钮文案）
- `anylabeling/views/dataset_center_merge.py`（目标下拉显示路径）
- `tests/test_widgets/test_dataset_center.py`（表格断言 + 同名目标用例）
- 翻译资源、`app_info.py`、`CHANGELOG-fork.md`、`docs/dev/CODE_STRUCTURE_REPORT.md`、
  `docs/dev/工业机器视觉数据平台-设计书-v1.6.md`、`docs/开始.md`

### 4. 行为与兼容性

- 工具栏多一个按钮；可通过工具栏设置隐藏，不影响原有动作。
- 概览从文字改为表格，信息量增加（全部类别/标签可滚动查看），不再只显示 Top 10/15。
- “打开数据集”文案仅改显示；合并目标文本变化不影响选择值（仍存 `RegistryEntry`）。
- 无接口/数据格式变化。

### 5. 验证

- `tests/test_dataset_db + test_widgets + test_utils + test_identity + test_i18n`：
  **376 passed / 108 subtests**（新增同名目标下拉用例、表格断言）；
  `test_image_tags_widget` 12 passed；`tests/test_i18n` 17 passed。
- 四语言 `.qm` 各 2737 条，zh/en 0 未翻译。
- **未执行**：真实桌面查看工具栏图标与表格排版（本机无 GUI 会话）。

### 6. 已知限制

- 概览表格目前一次加载全部类别/标签（万级标签时建议后续分页）；
- “当前数据集”标题栏 chip 未实现（已登记为后续增强）；
- 推送仍受本机凭据/网络阻塞；本地 `main` 领先远端 8 个提交。

## 4.3.2+fork.54 — 2026-11-25

### 1. 背景与问题

用户反馈数据集中心三个问题：

1. 打开一个文件夹后，数据集中心没有记录——但打开目录时若没有 `xanylabeling.db` 会创建，
   因此中心“至少应包含当前数据集”；
2. 打开已有 `xanylabeling.db` 的文件夹时仍提示“该文件夹必须包含已存在的 xanylabeling.db
   数据集数据库。无法打开数据库：…”；
3. 刚启动后打开以前编辑过的数据集时，“图像属性”页“图片标签”下方出现空白占位，编辑标签后消失。

### 2. 原因与修复

- **中心为空**：fork.53 只在中心里“添加文件夹…”时登记；打开目录的流程没有登记。
  fork.54 在 `DatasetCenterWindow.refresh()` 前调用 `_register_current_dataset()`：
  校验当前 `dataset_root/xanylabeling.db` 并 `add_from_folder()` 自动登记（失败只记日志，
  不影响列表）。
- **有库仍报“无法打开”**：`RegistryStore.check_dataset()` 用 `DatasetDatabase.open(read_only=True)`
  （SQLite `mode=ro` URI）。WAL 数据库正被编辑窗口/其他进程写入时，只读 URI 可能失败，
  于是被误判为“无法打开”。新增 `DatasetDatabase.open_for_reading()`：先只读打开，失败回退
  普通连接；注册表校验、概览读取、合并源/目标读取全部改用它；错误信息带上数据库路径。
- **标签区域留白**：`ImageTagsWidget._render()` 在“图像属性”页隐藏时首次渲染，视口宽度
  尚未确定（按 80px 兜底），流式布局把芯片折成多行并按最大行数预留高度，导致下方空白；
  编辑标签触发重渲染后才收缩。fork.54 在 `showEvent` 中延迟刷新高度，并在视口宽度未知时
  跳过计算（等布局完成后的 resize/show 再算）。

### 3. 涉及文件

- `anylabeling/services/dataset/connection.py`（`open_for_reading`）
- `anylabeling/services/dataset/registry.py`（校验回退 + 错误带路径）
- `anylabeling/services/dataset/merge.py`（源/目标读取用回退）
- `anylabeling/views/dataset_center.py`（当前数据集自动登记）
- `anylabeling/views/labeling/widgets/image_tags_widget.py`（show 时刷新高度）
- `tests/test_widgets/test_dataset_center.py`（自动登记用例）
- `anylabeling/app_info.py`、`CHANGELOG-fork.md`、`docs/dev/CODE_STRUCTURE_REPORT.md`、
  `docs/dev/工业机器视觉数据平台-设计书-v1.6.md`、`docs/开始.md`

### 4. 行为与兼容性

- 打开目录后打开数据集中心即可看到当前数据集；重复打开不会重复登记。
- 已有数据库即使正被窗口打开，也能被中心校验/概览/作为合并源读取。
- 标签区域高度在切到“图像属性”页时即正确，不再依赖“编辑一次”。

### 5. 验证

- `tests/test_dataset_db + test_widgets + test_utils + test_identity + test_i18n`：
  **374 passed / 1 failed（既有计时抖动）/ 108 subtests**；新增
  `test_registers_the_dataset_open_in_the_window` 通过；`test_image_tags_widget` 12 passed。
- 四语言 `.ts/.qm` 未新增文案（本批无新用户可见字符串）。
- **未执行**：真实桌面复验三个问题（本机无 GUI 会话）。

### 6. 已知限制

- 若当前数据集被外部移动/删除，中心仍显示为 `missing`（设计如此），需“重新定位”。
- 标签高度修复基于“隐藏页首次渲染宽度未知”的判断；如仍出现留白，需要用户提供复现步骤。
- 推送仍受本机凭据/网络阻塞；本地 `main` 领先远端 7 个提交。

## 4.3.2+fork.53 — 2026-11-25

### 1. 背景与需求

用户确认数据集中心方案（设计书 §4.7）：P0（数据集中心：概览统计、注释、切换、重命名、删除、移除记录）
与 P1（数据集合并）同批实现，并要求把 app 级数据库从 `operators.db` 改名（因为现在同时存账号与数据集注册表）。

### 2. 主要实现

- **数据库更名**：`%APPDATA%/X-AnyLabeling/operators/operators.db` → `platform/platform.db`；
  `session.py` 的 `default_database_path()` 指向新位置，首次访问 `OperatorService.store` 时
  `migrate_legacy_database()` 依次尝试旧 app 目录与 pre-fork.5 工作目录并复制（不删除源文件）。
- **共享 app schema**：新增 `anylabeling/services/app_state.py`（`APP_SCHEMA_VERSION = "2"`，
  `operator` + `meta` + `dataset_registry` + `dataset_registry_event`），由 `OperatorStore` 与
  `RegistryStore` 共用；幂等 `CREATE TABLE IF NOT EXISTS`，旧库原地升级。
- **RegistryStore**（`services/dataset/registry.py`，无 Qt）：`add/add_from_folder/list/get/get_by_path/
  rename/touch/mark_missing/relocate/mark_deleted/remove_record/events/check_dataset`；状态
  `active|missing|deleted`，事件表记录 `add/rename/open/merge_source/merge_target/delete/
  delete_aborted/mark_missing/relocate/remove_record`。
- **Repository 扩展**：`overview()`（图片/回收站/对象/类别/标签种类、split 计数、每类图片/对象数、
  标签词表，全 SQL 聚合）与 `update_dataset_metadata(name/description)`（长度校验 + `updated_at`）。
- **数据集中心窗口**（`views/dataset_center.py`）：独立非模态窗口，列表 + 概览 + 注释编辑器；支持
  添加文件夹、刷新、打开、重命名、重新定位、合并、删除、移除记录、搜索；打开时校验并自动把
  失效项置 `missing`；删除需二次登录（`OperatorStore.authenticate`）+ 先备份（`VACUUM INTO`）+
  写注册表事件 + 应用日志；删除模式分“仅数据库/数据库和图片”。
- **合并服务**（`services/dataset/merge.py`，无 Qt）：`plan_merge()` dry-run 与
  `merge_datasets()`；图片复制到 `<目标>/imported/<源slug>-<session>/`；类别同名归并 + 可选
  跨名映射；对象 `uuid` 重建、`group_id`/几何/属性保留；`split` 默认保留源；疑似重复（同名+大小+
  mtime）只提示；合并前备份目标；写 `import_session(source_format='dataset-merge')` 溯源；
  分批事务 + 每图 SAVEPOINT，单图失败不中断；支持 `cancel_check`。
- **合并向导**（`views/dataset_center_merge.py`）：目标选择（已有数据集/新建）、类别映射表、
  split/空类别/疑似重复选项、预检报告、后台线程执行 + 进度、结果与错误摘要；新建目标后自动
  注册并可在完成后直接打开。
- **菜单接入**：`文件 → 数据集中心…`（`builder.py`/`menus.py`），`LabelingWidget.open_dataset_center`
  转 `FileSession`，窗口单实例并复用打开数据集回调。
- **i18n**：新增 98 条文案（`DatasetCenterWindow`/`MergeDialog`/`_SecondLoginDialog`/菜单），
  `.ts/.qm` 四语言重建；`fill_identity()` 修复 `pylupdate6` 自闭合 `<translation/>` 无法被 TM 填充
  的缺陷；四个 `.qm` 各 2730 条，zh/en 0 未翻译。

### 3. 涉及模块

- 新增：`anylabeling/services/app_state.py`、`anylabeling/services/dataset/registry.py`、
  `anylabeling/services/dataset/merge.py`、`anylabeling/views/dataset_center.py`、
  `anylabeling/views/dataset_center_merge.py`、`tests/test_dataset_db/test_registry.py`、
  `tests/test_dataset_db/test_merge.py`、`tests/test_widgets/test_dataset_center.py`
- 修改：`identity/session.py`、`identity/store.py`、`identity/__init__.py`、
  `dataset/repository.py`、`labeling/actions/builder.py`、`labeling/actions/menus.py`、
  `labeling/file_session.py`、`labeling/label_widget.py`、`scripts/translation_scan.py`、
  `scripts/generate_languages.py`、`tests/test_identity/test_operator_store.py`、
  `tests/test_i18n/test_translations.py`、翻译资源、`app_info.py`、`CHANGELOG-fork.md`、
  `docs/dev/CODE_STRUCTURE_REPORT.md`、`docs/dev/工业机器视觉数据平台-设计书-v1.6.md`、`docs/开始.md`

### 4. 行为、接口与兼容性影响

- 旧 `operators.db` 在首次访问账号/注册表时自动复制到新位置，账号不丢；旧文件保留。
- 数据集中心是新增窗口，不影响原有标注/上传/导出流程；`DatasetRepository` 仅新增方法。
- 合并会**复制**图片并在目标库写入新行，源库只读；类别同名归并（schema 唯一约束），
  跨名映射只由用户显式指定。
- 删除数据集需要二次登录并先备份；外部删除会在下次刷新时标记 `missing`，不会抛异常。

### 5. 实际验证内容

- `tests/test_dataset_db + test_widgets + test_utils + test_identity + test_i18n`：
  **374 passed / 108 subtests**（含 registry 4、overview 1、merge 4、数据集中心 3）。
- `tests/test_labeling`：**256 passed / 10 failed**，失败与 fork.49 记录的既有测试债一致
  （4 文件表 DB 模式、3 `SimpleNamespace` 桩、3 上传属性），本批未触碰这些用例。
- 离屏翻译核对：`数据集中心`/`添加文件夹…`/`图片：%d（回收站：%d）`/`划分：训练 …`/
  `确认密码`/`合并数据集`/`开始合并`/`数据集中心…` 均为中文。
- 生成器幂等性：重跑 `generate_languages.py --no-resources` 后译文零增减（仅 `<location line>` 变化）。
- 四语言 `.qm` 各 2730 条（zh/en 0 未翻译；ja/ko 未翻译数增加，运行时回退英文）。
- **未执行**：真实桌面人工点击“数据集中心”与合并向导（本机无 GUI 会话）。

### 6. 已知限制

- 合并暂无内容哈希去重（`image_file.sha256` 仍延期），疑似重复仅提示。
- 数据集中心不支持多窗口打开（U12 已登记）；注册表随 `platform.db`，若用户删除该库则列表丢失
  （数据集文件仍在，可重新“添加文件夹”）。
- ja/ko 仍有未翻译文案。
- 推送仍受本机凭据/网络阻塞；本地 `main` 已领先远端 6 个提交。

## 文档：新增设计书 §4.7 数据集管理与合并契约（2026-11-25，不升 fork 版本）

纯文档变更，不改变代码结构、接口或行为，故不升 fork 版本号。

- 设计书 `工业机器视觉数据平台-设计书-v1.6.md` 正文升至 **v1.27**，新增 §4.7：
  - 数据集中心定位为**独立窗口**（非右侧 tab），管理已知数据集：概览统计、切换/新窗口打开、数据集注释、合并、移除记录；
  - 数据集身份 = `dataset.uuid` + 数据库绝对路径，**名称/目录名不参与身份判定**（不同路径同名目录是不同数据集，不做同名自动合并）；
  - 概览统计口径：split 四类计数、tag 种类与每 tag 图片数（`tag_counts()`）、类别对象/图片数（`category_counts()`/`v_category_split_stats`），只读连接 + SQL 聚合；
  - 数据集注释复用已有 `dataset.description` 列（无需迁移），新增 `update_dataset_metadata()` 写入口；
  - 合并为**并集语义**：`rel_path` 跨库不可比 → 默认命名空间复制（`imported/<源>-<session>/…`）；`ux_category_name` 决定同名类别只能归并为一行（**schema 约束，非可选项**），可选的是不同名类别的显式映射；对象 `uuid` 直接并集、`group_id` 为图内分组无需重编号；split 默认保留源；溯源写 `import_session(source_format='dataset-merge')`；
  - 与项目的关系：本期不引入 `project` 实体、不做项目创建，中心窗口预留分组位；项目作为二期独立设计；
  - 记录 D1–D5 决策点（注释归属、轻量项目、合并默认方式、split 策略、P0 是否含删除）。
- 2026-11-25 第二轮（正文 v1.27）：用户确认「合并采用复制」「合并需类别映射提醒」「本期只做数据集中心（项目仅评估）」；§4.7 增补决策记录 R1–R3、未决事项 U1–U11（落盘路径、split、P0 删除、注释登录、合并目标形态、合并登录、空类别/软删、去重提示、多窗口、注册表位置、P0 列表操作）与实现假设清单（统计口径、注释长度、预检/批次/备份/失败处理、映射方向、溯源、归属）。
- 2026-11-25 第三轮（正文 v1.28）：用户拍板 U1–U9、U11（R4–R13）——命名空间复制、split 保留源、P0 含删除（二次登录确认 + 备份 + 审计日志）、注释需登录、合并到新数据集（R8=C）、合并需登录、空类别/无标注导入且回收站跳过、疑似重复仅提示、本期单窗口打开、P0/P1 列表操作范围；§4.7 新增“删除与外部缺失处理”（`active|missing|deleted` 状态、重新定位、事件表）与 U10 注册表评估（建议扩展 `operators.db`：新增 `dataset_registry` + `dataset_registry_event`，`meta.schema_version` 升 2，不新建 user 表）。
- `docs/开始.md`：T11 范围按 R4–R13 更新；设计书版本引用更新为 v1.28。
- `docs/dev/CODE_STRUCTURE_REPORT.md`：未改代码结构，仅更新版本元数据与核对日期。

## 4.3.2+fork.52 — 2026-11-25

### 1. 背景与原因

用户反馈 fork.51 之后“图像属性”页仍残留英文：`Tag Library`、`Search tags…`、
`No other tags in the current file list.`。

排查结论是**代码结构问题**，不是漏译或 `.ts` 缺条目：

- `TagLibraryWidget.__init__(self, translate, …)` 接收注入的翻译函数并执行
  `self._tr = translate`；调用点分别传 `host.tr`（`workspace.py:560`）和
  `self.tr`（`tags_dialog.py`）。
- `BatchTagsDialog.__init__(…, translate=None)` 同样接受注入，
  `file_list/controller.py` 传入 `translate=host.tr`。
- `pylupdate6` 只按“类体内的字面量调用”把文案登记到**类名**上下文（`TagLibraryWidget`/
  `BatchTagsDialog`），而运行时 `host.tr` 的上下文是 **`LabelingWidget`**。两者永远
  对不上，因此这些文案无论 `.ts` 里有没有译文都会显示英文；fork.51 把它们的译文放在
  `TagLibraryWidget`/`BatchTagsDialog` 下，自然不生效。

### 2. 主要实现与关键细节

- **移除翻译函数注入**，让控件使用自身的 `self.tr`（上下文 = 类名，与抽取一致）：
  - `TagLibraryWidget(parent=None)`：删除 `translate` 参数与 `lambda` 兜底，
    所有 `self._tr(...)` 改为 `self.tr(...)`；调用点改为 `TagLibraryWidget()` /
    `TagLibraryWidget(self)`。
  - `BatchTagsDialog(image_count, library_tags=(), parent=None)`：删除 `translate`
    参数与 `self._tr` 赋值；调用点改为 `BatchTagsDialog(len(paths), library_tags, host)`。
  - 测试替身同步去掉 `translate` 形参；`test_tag_library_widget` 改用
    `TagLibraryWidget()`。
- **新增回归测试** `test_image_attributes_tag_library_is_translated`：安装 `zh_CN.qm`
  后校验标签库标题/搜索占位/收起提示/空状态，以及批量标签对话框标题与三种模式文案。
- 重新生成 `.ts`：仅 `<location>` 行号变化，四语言译文**零增减、零改动**（证明上下文
  已与抽取一致，不再依赖 fork.51 的“猜上下文”）。
- 版本：`4.3.2+fork.51` → `4.3.2+fork.52`。

### 3. 涉及模块与文件

- 修改：`anylabeling/views/labeling/widgets/tag_library.py`、
  `anylabeling/views/labeling/file_list/tags_dialog.py`、
  `anylabeling/views/labeling/widgets/workspace.py`、
  `anylabeling/views/labeling/file_list/controller.py`、
  `anylabeling/resources/translations/*.ts`、`*.qm`、
  `tests/test_i18n/test_translations.py`、`tests/test_widgets/test_tag_library_widget.py`、
  `tests/test_labeling/test_file_table.py`、`anylabeling/app_info.py`、
  `CHANGELOG-fork.md`、`docs/dev/CODE_STRUCTURE_REPORT.md`、
  `docs/dev/工业机器视觉数据平台-设计书-v1.6.md`、`docs/开始.md`

### 4. 行为、接口与兼容性影响

- 用户可见：中文界面下“图像属性”页标签库（标题、搜索框、收起/展开、空状态、悬停提示）
  与“批量设置图片标签”对话框恢复中文。
- 内部接口：`TagLibraryWidget`、`BatchTagsDialog` 不再接受 `translate` 参数；仓库内
  调用点与测试已同步，无外部调用者（`translate=` 全仓库检索为 0）。
- 不改变数据格式、DB schema 或 `.ts` 条数与译文。

### 5. 实际验证内容

- 离屏运行时核对（`zh_CN.qm`）：`TagLibraryWidget` 标题“标签库”、占位“搜索标签…”、
  收起提示“收起标签库”、空状态“当前文件列表中没有其他标签。”；
  `BatchTagsDialog` 标题“批量设置图片标签”、模式“添加到现有标签/替换指定标签/删除所有图片标签”。
- `tests/test_i18n` **17 passed**；`tests/test_i18n + tests/test_widgets + tests/test_utils +
  tests/test_dataset_db` **342 passed / 105 subtests**；`tests/test_widgets/test_tag_library_widget.py`
  **4 passed**；`tests/test_labeling/test_file_table.py` **41 passed / 4 failed**，4 条失败为
  结构报告记录的既有文件表 DB 模式测试债（本批未改这些用例）。
- 生成器幂等性：重跑 `generate_languages.py --no-resources` 后译文零变化，仅
  `<location line>` 随源码行号更新。
- 四语言 `.qm` 各 2632 条（`en_US`/`zh_CN` 0 未翻译，`ja_JP`/`ko_KR` 各 139 条未翻译）。
- **未执行**：真实桌面人工验收（本机无 GUI 会话）；用户副本需同步本次提交后生效。

### 6. 已知限制与后续事项

- `ja_JP`/`ko_KR` 仍有 139 条未翻译（fork.49 遗留 130 条 + fork.51 新发现 9 条）。
- 推送仍受本机凭据/网络阻塞（见 fork.49 记录）；本地 `main` 已领先远端 3 个提交。
- 控件与对话框的翻译规范已写入设计书 §4.6：**不得注入翻译函数**，一律用自身
  `self.tr`；确需跨上下文时由调用方用自己的 `tr` 包装后再传入文本（而不是传入函数）。

## 4.3.2+fork.51 — 2026-11-25

### 1. 背景与原因

用户反馈“软件设为中文时，主界面右侧 QTabWidget 的内容全是英文”。

对比 fork.48（`5c049c1^`）与 fork.50 的 `zh_CN.ts` 后确认这是 fork.49 翻译重建引入的回归：

- **丢失 172 条** `(上下文, 源文)` 译文：`auto_labeling_form` 47、`LabelingWidget` 41（多数是已删除文案，属正常废弃）、`LabelManagerPanel` 33、`TrashDialog` 14、`LabelModifyDialog` 10、`PasswordResetDialog` 9、`StatisticsTable` 8 等；
- **5 条被错误替换**：跨上下文按源文回退导致 `Classes` 从“类别”变成“标签过滤”、`Next`/`Previous` 从“下一张/上一张”变成“下一步/上一步”、`None` 从“无”变成“空”、“No images loaded”措辞变化。

根因：`pylupdate6` 只会抽取**类体内、字面量参数**的 `*.tr()`。项目里还有多种运行时有效但抽取不到的写法：

| 写法 | 位置 |
|---|---|
| `self._tr("…")`（内部 `translate(TRANSLATION_CONTEXT, text)`） | `LabelManagerPanel`、`TrashDialog` |
| `self.tr(常量)` / `for label in 常量元组: self.tr(label)` | `StatisticsTable`（表头 `COLUMN_HEADERS`） |
| `_translate("auto_labeling_form", "…")`（pyuic6 生成） | `widgets/auto_labeling/auto_labeling_ui.py` |
| `QT_TRANSLATE_NOOP(SETTINGS_TRANSLATION_CONTEXT, "…")` | `settings/schema.py` |

fork.49 的 `pylupdate6 --no-obsolete` 把这些消息当成废弃条目删掉，而 fork.49 的补充抽取只认字面量，于是整块译文中断；右侧栏“类别”“统计”等页面因此全英文。

### 2. 主要实现与关键细节

- **`scripts/translation_scan.py` 支持动态写法**：
  - `_translate("ctx", "text")` / `translate(...)` / `QT_TRANSLATE_NOOP(ctx, text)`；
  - `self._tr("text")`：上下文取模块级 `TRANSLATION_CONTEXT`（或 `*_TRANSLATION_CONTEXT`），委托调用（`host.label_manager_widget._tr(...)`）跳过，由属主模块登记；
  - 参数可以是模块级字符串常量、同文件/跨文件的唯一同名常量、`+` 拼接；
  - `for label in 常量元组:` 展开每个元素（序列常量允许引用同模块字符串常量）。
- **`StatisticsTable` 表头改为字面量**：新增 `_header_labels()`，用 `self.tr("Class")/("Train")/("Val")/("Test")/("Unassigned")/("Total")` 直接书写（`pylupdate6` 原生可抽取），避免翻译共享常量；新增“表头数量与 `COLUMN_HEADERS` 一致”的测试。
- **译文恢复**：按 fork.48 的 `(上下文, 源文)` 精确恢复被丢弃/被改坏的译文（`Classes`→“类别”等 5 条已还原），再补齐新增条目；`zh_CN.ts` 现有 2632 条消息、0 未翻译；另补 11 条此前从未翻译的文案（设置页“类别排序/校验类别/滚轮导航模式…”与类别页锁定提示）。
- **测试**：
  - `test_right_sidebar_widgets_are_translated`：安装 `zh_CN.qm` 后校验五个 tab 标题、“类别”页表格表头、统计表表头/可访问名、回收站与设置页文案；
  - `test_scanner_resolves_dynamic_translation_patterns`：用临时包覆盖 `_tr`、`_translate`、`QT_TRANSLATE_NOOP`、常量参数、常量循环五种写法，断言扫描结果完整且 0 未解析。
- 版本：`4.3.2+fork.50` → `4.3.2+fork.51`。

### 3. 涉及模块与文件

- 修改：`scripts/translation_scan.py`、`anylabeling/views/labeling/widgets/statistics_table.py`、`anylabeling/resources/translations/*.ts`、`*.qm`、`tests/test_i18n/test_translations.py`、`tests/test_widgets/test_statistics_table.py`、`anylabeling/app_info.py`、`CHANGELOG-fork.md`、`docs/dev/CODE_STRUCTURE_REPORT.md`、`docs/dev/工业机器视觉数据平台-设计书-v1.6.md`、`docs/开始.md`

### 4. 行为、接口与兼容性影响

- 用户可见：中文界面下右侧栏（对象/类别/图像属性/描述/统计）恢复中文，回收站、自动标注面板、设置页相关文案同步恢复；无接口或数据格式变化。
- `StatisticsTable._header_labels()` 为新增内部方法，外部行为不变（表头文字与顺序不变）。

### 5. 实际验证内容

- `tests/test_i18n` **16 passed**（含右侧栏运行时回归与动态写法扫描用例）；`tests/test_utils + tests/test_widgets + tests/test_dataset_db + tests/test_i18n` **340 passed / 1 failed / 105 subtests**，唯一失败是已记录的 `test_brightness_contrast_updates_are_throttled` 计时抖动。
- 离屏运行时核对（安装 `zh_CN.qm`）：tab 标题 对象/类别/图像属性/描述/统计；统计表头 类别/训练/验证/测试/未划分/合计；类别页表头 类别/删除/可见/锁定/颜色；`TrashDialog`“回收站/恢复”；`auto_labeling_form`“Box threshold”→“框置信度”；`SettingsDialog`“Edit Image Tags”→“编辑图片标签”。
- 生成器幂等性：重新运行 `scripts/generate_languages.py --no-resources` 后四语言 `.ts` **0 行变化**（证明新增动态条目不会再被丢弃）。
- 四语言 `.qm` 重编各 **2632 条**：`en_US`/`zh_CN` 0 未翻译；`ja_JP`/`ko_KR` 各 139 条未翻译（fork.49 遗留 130 条 + 本批新发现 9 条），回退英文。
- **未执行**：真实桌面点击右侧栏各页的人工验收（本机无 GUI 会话）；用户副本需同步本次提交后生效。

### 6. 已知限制与后续事项

- `ja_JP`/`ko_KR` 仍有 139 条未翻译；如需完整四语言需补译。
- 动态写法的抽取依赖 `scripts/translation_scan.py` 的常量解析：今后若新增更复杂的计算式（如 `dict[...]` 表达式、运行时拼装），需扩展 scanner 或改写字面量，否则仍会在重建时丢失；测试已覆盖现有五种写法。
- 推送仍受本机凭据/网络阻塞（见 fork.49 记录），本批提交只落在本地。

## 4.3.2+fork.50 — 2026-11-25

### 1. 背景与原因

fork.49 发布后，用户点“上传 → YOLO Seg”直接崩溃：

```text
File "...\utils\upload.py", line 1028, in _class_source_text
    return host.tr("Classes: %d from %s") % (count, source.path)
TypeError: %d format: a real number is required, not str
```

根因是 fork.49 新补的 zh_CN 译文把占位符顺序写反了：
`Classes: %d from %s` 被译成 `类别：来自 %s 的 %d 个`。代码用 Python `%` 按位置套参数
（`(count, path)`），于是第一个 `%s` 吃到整数、第二个 `%d` 吃到字符串，抛 `TypeError`。
换句话说：**译文能显示，但一旦参与格式化就会崩**；fork.49 的 i18n 守卫只检查“条目存在、
非空、`.qm` 与 `.ts` 一致”，没有检查占位符。

### 2. 主要实现与关键细节

- 修正 zh_CN 译文：`类别：%d 个，来自 %s`（占位符顺序与类型与源文一致），重编 `zh_CN.qm`。
- `tests/test_i18n` 新增两条守卫：
  - `test_placeholder_order_matches_source[en_US/zh_CN/ja_JP/ko_KR]`：逐条比较源文与译文的
    有序 `%` 说明符（跳过 `%%`），顺序或类型不一致即失败；覆盖全部 2493 条消息；
  - `test_classes_hint_template_accepts_its_arguments`：加载 `zh_CN.qm` 后真实格式化
    `Classes: %d from %s`，直接复现用户崩溃路径。
- `tests/test_utils/test_upload.py` 新增 `test_class_source_text_formats_in_chinese`：
  安装 zh_CN 翻译后调用 `_class_source_text()`（DB 类别与文件类别两种来源），确认不再抛异常。
- 用旧译文复跑新守卫，确认能复现 `TypeError: %d format: a real number is required, not str`
  并使两条用例失败；恢复修复后全绿（先证明守卫有效，再证明修复有效）。

### 3. 涉及模块与文件

- 修改：`anylabeling/resources/translations/zh_CN.ts`、`zh_CN.qm`、`tests/test_i18n/test_translations.py`、`tests/test_utils/test_upload.py`、`anylabeling/app_info.py`、`CHANGELOG-fork.md`、`docs/dev/CODE_STRUCTURE_REPORT.md`、`docs/dev/工业机器视觉数据平台-设计书-v1.6.md`、`docs/开始.md`
- 未修改运行时代码（`upload.py` 逻辑本身正确，问题在译文）。

### 4. 行为、接口与兼容性影响

- 修复后“上传 → YOLO Seg/检测/旋转框”可正常打开选项对话框并显示“类别：N 个，来自 …”。
- 不改变任何接口或数据格式；仅修正一个译文条目并新增测试。
- 版本：4.3.2+fork.49 → 4.3.2+fork.50（缺陷修复属用户可观察行为变化）。

### 5. 实际验证内容

- `tests/test_i18n` **14 passed**（含四语言占位符检查与崩溃回归）；`tests/test_utils/test_upload.py` **9 passed**（含中文格式化回归）；两者合计 **23 passed**。
- 反向验证：临时恢复旧译文后，`test_placeholder_order_matches_source[zh_CN]` 与
  `test_classes_hint_template_accepts_its_arguments` 均失败，错误正是用户看到的
  `TypeError: %d format: a real number is required, not str`；恢复后全绿。
- 四语言 `.qm` 重编各 2493 条（`en_US`/`zh_CN` 0 未翻译，`ja_JP`/`ko_KR` 各 130 条未翻译，状态与 fork.49 相同，本批未改）。
- **未执行**：真实桌面点击“上传 → YOLO Seg”的完整交互（本机无 GUI 会话）；用户侧副本 `D:\cbg\code\X-AnyLabeling-main` 需要同步本次提交后才会生效。

### 6. 已知限制与后续事项

- 仍有一类风险：若后续人工新增/修改译文时打乱占位符，测试会拦住；但 `pylupdate6` 自动复用旧译文时也可能带出错误，因此每次都须跑 `tests/test_i18n`。
- `ja_JP`/`ko_KR` 的 130 条未翻译文案仍未补（与 fork.49 相同）。
- 推送仍受本机凭据/网络阻塞（见 fork.49 记录），本批提交同样只落在本地。

## 4.3.2+fork.49 — 2026-11-25

### 1. 背景与原因

用户反馈“工具标题栏 → 上传 → YOLO Seg”有三个问题：

1. 强制要求 `classes.txt` 不合理；导出早已在 DB 模式直接使用“类别”页顺序（fork.38），上传没有跟上；
2. `Upload Options` 窗口没有中文翻译；核对后发现这不是单个窗口的问题；
3. 图片在 `.../images/train`、标注在 `.../labels/train` 时，在对话框里填标注目录仍然解析不到 YOLO Seg 标注。

排查结论（均有实测）：

- **翻译丢失的根因**：这些对话框/提示写在**模块级自由函数**里，用 `self.tr()`；`pylupdate6` 只抽取**类体内**的 `*.tr()`，对自由函数里的调用一条也不提取（对 `utils/upload.py` 单独跑 `pylupdate6` 产出空 `.ts`），所以字符串从未进入 `.ts/.qm`。运行时 `host.tr()` 本身有效（PyQt 按对象类名查上下文），坏的是抽取环节；全项目有 800+ 处这类调用，涉及上传、导出、裁剪、可视化、视频、批量处理、菜单/工具栏与若干代理模块。
- **解析不到的根因有两层**：
  - 当前 fork 打开文件夹必建库（fork.39），界面/文件表/画布只读 `xanylabeling.db`；但“上传”只写 JSON sidecar，因此 DB 模式下**所有**格式的上传都是“成功但看不见”，不只是 seg；
  - `LabelConverter.yolo_to_custom()` 用 `split(" ")` + 直接 `int(float)`，遇到 Tab、重复空格、空行、`0.0` 类号或类号越界就直接抛异常，且第一处失败中断整批，只弹一句英文错误，不说是哪个文件哪一行；默认标注目录取 `dirname(dirname(image))`，不会推断 `labels/<split>`。

### 2. 主要实现与关键细节

- **YOLO 四格式上传（hbb/obb/seg/pose）**
  - 类别来源按优先级：DB `category.sort_index` 顺序 → 最近的 `classes.txt`/`obj.names`/`names.txt` → 最近的 `data.yaml` 的 `names`（数字键排序）→ 兜底文件选择框（取消即退出）。pose 仍需关键点 YAML。
  - 自动推断标注目录：把路径里的 `images` 段替换为 `labels`，保留 split；用户填 `labels` 时自动下钻同名 split 子目录；目录不存在直接报错退出。
  - 对话框新增“类别来源”提示与“保留已有标注”选项。
  - 解析改为任意空白切分、跳过空行、逐行校验；新增 `YoloAnnotationError`，消息形如 `a.txt:2: class index 3 is out of range for 1 class names (…/classes.txt)`；单文件失败只计入错误列表，不中断整批。
  - 结束后统一汇总“已上传/跳过（无同名 .txt）/跳过（不在数据集）/失败 + 前 5 条错误”，失败写入日志。
- **DB 模式写库**：新增 Qt-free `services/dataset/annotation_import.py`（`store_annotation`/`store_annotations`/`build_annotation`/`relative_to_root`），把转换结果按 `rel_path` 找 `image_id`，`preserve_existing` 时先 `load_annotation` 再追加，最后走 `repository.save_annotation()`；不在库中的图片记 skipped，根外路径记 failed。`LabelConverter` 的 `yolo_to_custom`/`yolo_obb_to_custom`/`yolo_pose_to_custom` 新增 `write=True` 参数（`write=False` 返回 payload 不落盘），默认行为不变。
- **其他上传格式**：DB 模式下统一由 `_reject_dataset_mode_upload()` 明确拒绝并提示（COCO/VOC/DOTA/MOT/MGDD/Mask/ODVG/PPOCR/VLM-R1），避免继续“成功但不可见”；JSON 模式行为不变。
- **对话框基类化**：新增 `widgets/base_dialog.py::BaseDialog`（路径行、复选、按钮、样式、`validate()`）与 `widgets/upload_dialogs.py`（`UploadFolderDialog`、`UploadCategorySection`、`UploadConfirmDialog`、`UploadProgressDialog`）；`upload.py` 的 5 个 `Upload Options` 对话框、9 个覆盖确认框、9 个进度框全部改用它们，原重复布局代码删除。
- **翻译流水线**
  - 新增 `scripts/translation_scan.py`：AST 扫描全部常量可翻译字符串，按运行时上下文归类（类体内 `self.tr` → 类名；显式 `QCoreApplication.translate("Ctx", …)` → Ctx；其余用模块级 `TR_CONTEXT`），并把 `pylupdate6` 抽不到的消息补进 `.ts`；另有 `translation_memory()`/`fill_translations()` 按源文复用旧译文，避免代码换类后译文丢失。
  - `scripts/generate_languages.py` 改为：只把含翻译调用的源文件交给 `pylupdate6`（避免 Windows 命令行超长）、按语言执行补充抽取 + 译文回填，再 `lrelease`；新增 `--no-resources`（与 `compile_languages.py` 一致），发布前才重建 `resources.py`；`pylupdate6`/`pyuic6`/`lrelease` 找不到时回退到当前环境 `Scripts` 目录。
  - 27 个模块补 `TR_CONTEXT = "LabelingWidget"`；`pointcloud/camera.py`、`widgets/operator_dialog.py`、`utils/qt.py` 的非 `self` 接收者改为显式 `translate("Context", …)`。
  - `.ts/.qm` 重建：各 **2493 条**；`en_US`、`zh_CN` 0 未翻译（新文案与“代码换类后”的旧文案均已回填），`ja_JP`、`ko_KR` 各 130 条 fork.49 新文案未翻译（回退英文）。
  - 新增守卫测试 `tests/test_i18n/test_translations.py`：上下文必须可解析、四语言条目齐全、`en_US`/`zh_CN` 必须翻译、`.qm` 抽样与 `.ts` 一致、上传对话框文案实测中文。

### 3. 涉及模块与文件

- 新增：`anylabeling/services/dataset/annotation_import.py`、`anylabeling/views/labeling/utils/yolo_import.py`、`anylabeling/views/labeling/widgets/base_dialog.py`、`anylabeling/views/labeling/widgets/upload_dialogs.py`、`scripts/translation_scan.py`、`tests/test_i18n/test_translations.py`、`tests/test_utils/test_yolo_import.py`、`tests/test_dataset_db/test_annotation_import.py`
- 修改（运行时）：`utils/upload.py`、`utils/export.py`、`utils/crop.py`、`utils/video.py`、`utils/visualization.py`、`utils/batch.py`、`utils/shape.py`、`utils/async_exif.py`、`utils/qt.py`、`label_converter.py`、`label_widget.py`、`label_filters.py`、`label_loop.py`、`annotation_editor.py`、`appearance.py`、`auto_labeling_handoff.py`、`file_session.py`、`object_editor.py`、`relations.py`、`right_sidebar.py`、`shape_commands.py`、`special_workspaces.py`、`status.py`、`settings/runtime_applier.py`、`actions/{builder,menus,toolbar}.py`、`file_list/controller.py`、`operator/gate.py`、`pointcloud/camera.py`、`widgets/{attributes_panel,workspace,operator_dialog}.py`、`services/dataset/__init__.py`、`resources/translations/*.ts`、`resources/translations/*.qm`
- 修改（测试/脚本/文档）：`tests/test_utils/test_upload.py`、`tests/test_utils/test_label_converter.py`、`scripts/generate_languages.py`、`docs/dev/CODE_STRUCTURE_REPORT.md`、`docs/dev/工业机器视觉数据平台-设计书-v1.6.md`、`docs/user/zh_cn/user_guide.md`、`docs/开始.md`、`anylabeling/app_info.py`、`CHANGELOG-fork.md`

### 4. 行为、接口与兼容性影响

- **用户可见行为**：YOLO 检测/分割/旋转框/姿态上传不再要求 `classes.txt`（DB 模式用“类别”页顺序，JSON 模式自动探测）；标注目录自动填 `labels/<split>`；解析失败会逐条列出文件与行号；DB 模式下上传确实写入数据集并刷新文件表/统计/画布；其他格式在 DB 模式改为明确拒绝。
- **接口变化**：`LabelConverter.yolo_*_to_custom(..., write=True)` 新增可选参数并返回 payload；`LabelConverter(..., classes_source=None)` 新增可选参数（用于错误消息）；新增 `store_annotation()/store_annotations()`；`upload_yolo_annotation()` 的签名与菜单入口不变。
- **数据格式/存储**：不改变 XLABEL JSON 与 DB schema；DB 模式下上传不再产生 JSON sidecar（之前会留下永远不会被读取的 JSON）。
- **兼容性**：JSON 模式（未建库/`auto_db=False` 的测试与迁移工具）保持原行为；`preserve_existing` 在 JSON 模式仍合并旧 JSON；旧 `.ts` 条目在重新生成时按源文回填，不丢既有译文。

### 5. 实际验证内容

- `tests/test_utils/test_label_converter.py::TestLabelConverterYoloImport` 9 passed；`tests/test_utils/test_yolo_import.py` 17 passed；`tests/test_dataset_db/test_annotation_import.py` 7 passed；`tests/test_utils/test_upload.py` 7 passed；`tests/test_i18n/test_translations.py` 9 passed。
- 回归：`tests/test_utils tests/test_dataset_db tests/test_i18n` **249 passed / 0 failed / 103 subtests**；`tests/test_widgets tests/test_config tests/test_settings tests/test_identity` **155 passed / 1 skipped / 14 subtests**；`tests/test_labeling` **256 passed / 10 failed / 51 subtests**，10 条失败与 HEAD 基线记录逐条相同（测试债，本批未改）。
- 离屏冒烟：两种 import 顺序下 `upload.py`/`upload_dialogs.py` 均可导入；`UploadFolderDialog`/`UploadProgressDialog`/`UploadConfirmDialog`/`UploadCategorySection` 可构建；`validate()` 返回预期提示；加载 `zh_CN.qm` 后上传对话框与 `LabelingWidget` 上下文抽查均返回中文。
- `pyside6-lrelease` 重编四语言 `.qm` 各 2493 条。
- **未执行**：真实桌面上的文件框/确认框/进度条交互、真实数据集批量上传验收、`black`/`flake8`（本机未安装，按规则未自行安装）、不带 `--no-resources` 的 `resources.py` 重建（按 fork.36 约定留到发布前）。

### 6. 已知限制与后续事项

- `ja_JP`、`ko_KR` 有 130 条 fork.49 新文案未翻译，运行时回退英文；需要时按 `scripts/generate_languages.py` 流程补译。
- DB 模式目前只有 YOLO 四格式能上传；COCO/VOC/DOTA/MOT/MMGD/Mask/ODVG/PPOCR/VLM-R1 的写库适配未做（登记为 T10）。
- 上传后不写 `editor/modified_at`（外部数据不是当前操作员所写）；`"none"` 语义与 fork.4 契约一致，未新增归属逻辑。
- `black` 未运行，个别新增长行（如 `translate("CameraConfigurationDialog", "…")`）可能不符合 79 列格式，下一次格式化会统一处理。
- 上传流程假设同一目录内所有图片都已在当前数据集中；之后新增到磁盘但未入库的图片会被记为“跳过（不在数据集）”，不会自动入库。

## 4.3.2+fork.48 — 2026-11-24

### 1. 背景与原因

用户反馈 CPU/GPU 环境里没有 `onnxruntime` / `onnxruntime-gpu`，认为环境没有配置完。
实际情况是：`conda env create` 在 `Obtaining file:///D:/cbg` 阶段就失败，pip
尚未开始安装依赖，所以失败环境里没有 ORT；不是 extras 没写。

同时为了让依赖在 YAML 中直接可见，补充显式包名。

### 2. 主要实现与关键细节

- `environment-cpu.yml` 的 pip 段显式增加：
  - `onnx`
  - `onnxruntime`
- `environment-gpu.yml` 的 pip 段显式增加：
  - `onnx`
  - `onnxruntime-gpu`
- 版本约束仍由 `pyproject.toml` 的 `[cpu]` / `[gpu]` extra 决定，避免切换
  `gpu-cu11` / `gpu-cu13` 时重复 pin 冲突。
- `docs/dev/打包环境-conda.md` 说明：失败环境没有 ORT 是 pip 未开始安装，
  不是清单漏写；先解决 YAML 路径再重建。
- 版本：4.3.2+fork.47 → 4.3.2+fork.48。

### 3. 涉及模块与文件

- 修改：`environment-cpu.yml`、`environment-gpu.yml`、`docs/dev/打包环境-conda.md`、`docs/dev/CODE_STRUCTURE_REPORT.md`、`docs/开始.md`、`anylabeling/app_info.py`
- 未修改运行时代码。

### 4. 行为、接口与兼容性影响

- 成功创建环境后，CPU 环境有 `onnxruntime`，GPU 环境有 `onnxruntime-gpu`；
- 仍需使用仓库根 YAML（或 `scripts/setup_conda_env.ps1`）解决 `-e .` 路径；
- 版本：fork.47 → fork.48。

### 5. 实际验证内容

- 两份 YAML 用 PyYAML 解析通过，pip 段包含 `onnx` + 对应 ORT 包名；
- 未在干净机器实际创建环境；运行时代码未变，沿用 fork.44 回归结果。

### 6. 已知限制与后续事项

- 失败环境不会因为显式 ORT 行而自动装上 ORT；必须重建成功；
- GPU 的 CUDA/cuDNN 仍由系统提供；
- `gpu` extra 默认 CUDA 12，CUDA 11/13 需切换 extra。

---

## 4.3.2+fork.47 — 2026-11-24

### 1. 背景与原因

fork.46 的排错说明把 conda 的 pip 工作目录写成了“终端当前目录”，不准确。用户从
`C:\Windows\system32` 执行、YAML 仍在 `D:\cbg` 时，pip 仍解析到
`file:///D:/cbg`：

```text
ERROR: file:///D:/cbg does not appear to be a Python project
```

实际原因是 **Conda 会把 pip 子进程的 cwd 设为 environment.yml 所在目录**，不是
终端 cwd。只把 YAML 复制到 `D:\cbg`，即使 `cd` 到仓库根也会失败。

### 2. 主要实现与关键细节

- 修正两份 `environment-*.yml` 顶部说明：
  - YAML 必须与 `pyproject.toml` 同目录；
  - 不要只复制 YAML；使用仓库根里的绝对路径：
    `conda env create -f D:\path\to\repo\environment-gpu.yml`。
- 修正 `scripts/setup_conda_env.ps1` 的说明：脚本通过传入仓库根 YAML 解决路径，
  而不是依赖 `Push-Location` 改变 conda 的 pip cwd。
- 修正 `docs/dev/打包环境-conda.md` 的“最常见错误”专节，给出
  `Test-Path D:\...\pyproject.toml` 和绝对路径命令。
- 版本：4.3.2+fork.46 → 4.3.2+fork.47。

### 3. 涉及模块与文件

- 修改：`environment-cpu.yml`、`environment-gpu.yml`、`scripts/setup_conda_env.ps1`、`docs/dev/打包环境-conda.md`、`docs/dev/CODE_STRUCTURE_REPORT.md`、`docs/开始.md`、`anylabeling/app_info.py`
- 未修改运行时代码。

### 4. 行为、接口与兼容性影响

- 使用仓库根 YAML 时，从任意终端目录执行 `conda env create -f <repo>\environment-gpu.yml` 都能正确把 `-e .` 解析到仓库；
- 仍不能使用复制到仓库外的 YAML；
- 版本：fork.46 → fork.47。

### 5. 实际验证内容

- `scripts/setup_conda_env.ps1 -Device gpu -DryRun` 通过，输出仓库根 YAML 绝对路径；
- 两份 YAML 用 PyYAML 解析通过；
- 未在干净机器实际创建环境；运行时代码未变，沿用 fork.44 回归结果。

### 6. 已知限制与后续事项

- 如果用户只有 YAML、没有仓库源码，必须先克隆/复制完整仓库；
- 环境文件仍不安装 CUDA/cuDNN/Inno Setup。

---

## 4.3.2+fork.46 — 2026-11-23

### 1. 背景与原因

用户在新电脑 `D:\cbg` 执行 `conda env create -f environment-gpu.yml` 失败：

```text
ERROR: file:///D:/cbg does not appear to be a Python project:
neither 'setup.py' nor 'pyproject.toml' found.
```

原因是 `-e .` 由 conda 的 pip 子进程按**当前工作目录**解析，而不是按 YAML 文件所在目录；`D:\cbg` 不是仓库根。

### 2. 主要实现与关键细节

- 新增 `scripts/setup_conda_env.ps1`：
  - 自动定位仓库根（脚本父目录）；
  - `Push-Location` 到仓库根后再执行 `conda env create -f environment-<device>.yml`；
  - 支持 `-Device cpu|gpu`、`-Recreate`（清理失败/半成品环境）、`-DryRun`（只打印命令）；
  - 检测环境已存在并提示用 `-Recreate`，不再产生二次失败。
- 两份 `environment-*.yml` 顶部加醒目警告，说明必须从仓库根执行及失败报错特征。
- `docs/dev/打包环境-conda.md` 增加“最常见的错误：不在仓库根目录执行”专节，给出 `Get-Location`/`Test-Path pyproject.toml`、删除半成品环境、脚本一键创建步骤。
- 版本：4.3.2+fork.45 → 4.3.2+fork.46。

### 3. 涉及模块与文件

- 新增：`scripts/setup_conda_env.ps1`
- 修改：`environment-cpu.yml`、`environment-gpu.yml`、`docs/dev/打包环境-conda.md`、`docs/dev/CODE_STRUCTURE_REPORT.md`、`anylabeling/app_info.py`
- 未修改运行时代码。

### 4. 行为、接口与兼容性影响

- 在仓库根目录执行：
  ```powershell
  powershell -ExecutionPolicy Bypass -File scripts\setup_conda_env.ps1 -Device gpu
  ```
  会自动切到仓库根，避免 `-e .` 指向错误目录；
- 已存在或半成品环境用 `-Recreate` 重建；
- 环境文件直接执行的行为不变，仍要求当前目录是仓库根；
- 版本：fork.45 → fork.46。

### 5. 实际验证内容

- `scripts/setup_conda_env.ps1 -Device gpu -DryRun` 通过，输出正确仓库根、环境名、YAML 路径和最终命令；
- 两份 YAML 继续用 PyYAML 解析通过；
- 未在干净机器实际创建环境，未实际打包；
- 运行时代码未变，沿用 fork.44 回归结果（551 passed / 10 failed / 156 subtests）。

### 6. 已知限制与后续事项

- 脚本是 Windows PowerShell 5.1+；Linux/macOS 仍需在仓库根手动执行；
- 脚本不安装 NVIDIA 驱动、CUDA/cuDNN、Inno Setup；
- 若 conda 不在 PATH，脚本会提示先打开 Anaconda Prompt；
- `-Recreate` 会删除同名环境，执行前需确认环境名。

---

## 4.3.2+fork.45 — 2026-11-23

### 1. 背景与原因

用户需要把项目编译为可单独运行的 exe，并在另一台电脑上快速配置 CPU/GPU 两套 Conda 环境。

### 2. 主要实现与关键细节

- 新增根目录 [`environment-cpu.yml`](environment-cpu.yml)：
  - `python=3.12`、`pip>=24.1`、`setuptools>=77`、`wheel`；
  - pip 安装 `-e .[cpu,dev]`，包含 CPU ONNX Runtime、PyInstaller、PySide6/pyside6-lrelease、pytest。
- 新增根目录 [`environment-gpu.yml`](environment-gpu.yml)：
  - 同样的 Python/打包工具；
  - pip 安装 `-e .[gpu,dev]`，默认 CUDA 12.x + cuDNN 9.x；
  - 注释说明切换 `gpu-cu13` / `gpu-cu11` 的方式，以及 CUDA/cuDNN 需在系统安装。
- 新增 [`docs/dev/打包环境-conda.md`](docs/dev/打包环境-conda.md)：创建、验证、构建、更新、GPU 排错、单文件 exe/安装包区别。
- `packaging/README.md` 与 `docs/user/zh_cn/get_started.md` 增加环境文件入口。
- 版本：4.3.2+fork.44 → 4.3.2+fork.45。

### 3. 涉及模块与文件

- 新增：`environment-cpu.yml`、`environment-gpu.yml`、`docs/dev/打包环境-conda.md`
- 修改：`packaging/README.md`、`docs/user/zh_cn/get_started.md`、`docs/开始.md`、`docs/dev/CODE_STRUCTURE_REPORT.md`、`anylabeling/app_info.py`
- 未修改运行时代码。

### 4. 行为、接口与兼容性影响

- 新电脑在仓库根目录执行 `conda env create -f environment-cpu.yml`（或 `environment-gpu.yml`）即可创建打包环境；
- CPU 环境只有 CPU ONNX Runtime，GPU 环境只有 `onnxruntime-gpu`，两者不要混装；
- GPU 环境仍依赖系统 NVIDIA 驱动、CUDA 12.x Runtime、cuDNN 9.x 和 `PATH`；GPU exe 不是完全绿色包；
- 版本：fork.44 → fork.45。

### 5. 实际验证内容

- 两份 YAML 用 PyYAML 解析通过，确认 `name`/`channels`/`dependencies`/`pip` 结构及 extras；
- 未在干净机器执行 `conda env create`，未安装依赖，未实际 PyInstaller 打包；
- 运行时代码未变，沿用 fork.44 的回归结果（**551 passed / 10 failed / 156 subtests**，10 条为基线已知失败）。

### 6. 已知限制与后续事项

- `-e .` 要求从仓库根目录执行；换源码目录后需重新 `pip install -e`；
- 环境文件只保留下界、不锁死所有版本；发布前建议 `pip freeze` 留档；
- Conda 文件不安装 CUDA/cuDNN，也不安装 Inno Setup；GPU 构建前需按文档准备；
- CUDA 12 是默认 GPU 目标，CUDA 11/13 需修改 extra 并重建环境；
- GPU 单文件 exe 仍需目标机 CUDA/cuDNN 运行库；只追求绿色运行优先 CPU 版。

---

## 4.3.2+fork.44 — 2026-11-23

### 1. 背景与原因

用户反馈 YOLO 分割导出不符合设计要求：

1. 数据集已划分 `train/val/test/none`，导出目录必须按四个划分区分；
2. 没有生成官方训练方法需要的 `.yaml` 配置文件。

### 2. 主要实现与关键细节

- **YOLO 检测/分割/旋转框导出改为划分目录**：
  - `<export_root>/images/{train,val,test,none}/...`
  - `<export_root>/labels/{train,val,test,none}/...`
  - 即使某个划分没有图片，也创建对应空目录；
  - 保留图片在源目录下的相对子目录（嵌套目录不会丢失）。
- **split 来源**：
  - DB 模式以 `image_file.split` 为权威，`DatasetRepository.find_image()` 查询；
  - JSON 模式读取标注 `split`，缺失/非法归 `none`；
  - `none` 单独导出，不参与训练。
- **生成 `data.yaml`**：
  - `path` 为导出根目录绝对路径；
  - `train: images/train`、`val: images/val`、`test: images/test`；
  - `nc` 与 `names`（按“类别”页 `category.sort_index` 顺序）；
  - `none` 不写入训练键，文件末尾注释说明。
- **默认导出根目录**：图片目录同级 `yolo_dataset`（避免旧 `labels` 平铺造成 `labels/labels`）。
- **UI**：导出对话框增加说明“图片与标签写入 train/val/test/none 子目录并生成 data.yaml”。
- **范围**：`hbb`/`obb`/`seg` 使用新契约；`pose` 仍使用关键点 YAML 和旧目录结构，未套用。
- 翻译：新增导出说明 1 条；四语言 `.qm` 各 2326 条。
- 版本：4.3.2+fork.43 → 4.3.2+fork.44。

### 3. 涉及模块与文件

- 修改：`anylabeling/views/labeling/utils/export.py`、`resources/translations/*`、`app_info.py`
- 测试：`tests/test_utils/test_export.py`（划分目录、data.yaml、DB split 优先、嵌套目录）
- 文档：本文件、`docs/dev/工业机器视觉数据平台-设计书-v1.6.md`（正文 v1.21）、`docs/dev/CODE_STRUCTURE_REPORT.md`、`docs/开始.md`、`docs/user/zh_cn/user_guide.md`

### 4. 行为、接口与兼容性影响

- **用户可观察**：检测/分割/旋转框导出的目录从平铺 `labels/*.txt` 变为 `images/<split>` + `labels/<split>`，根目录多出 `data.yaml`；默认根目录改为 `yolo_dataset`。
- **接口**：`_get_yolo_export_files(..., split_by_image=None)`；`_yolo_split_for_image()`；`_write_yolo_data_yaml()`；`YOLO_SPLITS`。
- **数据**：不修改数据库；split 从 DB 读取，不写回。
- **兼容性**：旧平铺目录不再生成，属于破坏性变更；`pose` 暂不受影响。

### 5. 实际验证内容

- `test_yolo_seg_export_uses_split_directories_and_data_yaml`：train/val/none 三张图分别落到对应目录，四个空目录存在，`data.yaml` 的 `names`/`path`/`train`/`val`/`test` 正确。
- `test_yolo_split_prefers_database_over_json`：DB 返回 `val`、JSON 为 `train` 时使用 `val`。
- `test_yolo_export_preserves_nested_directories`：hbb/obb/seg 新布局，pose 旧布局。
- `tests/test_utils`：**172 passed**；其余非 pointcloud 组：**295 passed / 0 failed / 105 subtests**；`test_labeling` 沿用 **256 passed / 10 failed / 51 subtests**；合计 **551 passed / 10 failed / 156 subtests**，10 条与 HEAD 基线相同。
- 四语言 `.qm` 各 **2326 条 / 0 unfinished**；`resources.py` 无 diff。
- **未执行**：真实 Ultralytics 训练读取生成的 `data.yaml`、真实 DB 大数据集导出、桌面观感、打包与全量回归。

### 6. 已知限制与后续事项

- 旧平铺布局不再生成；如需兼容旧结构，需要后续加显式开关，而不是静默双写。
- `none` 不进入 `data.yaml` 的训练键，只作为独立目录保留；训练前需要人工确认是否忽略。
- `pose` 未套用本契约；若后续统一，需要补 `kpt_shape` 和关键点 YAML。
- `data.yaml` 的 `path` 是绝对路径；移动导出目录后需要改路径。
- 数据集划分仍以 DB 为准；JSON 模式的 `split` 只做兜底。

---

## 4.3.2+fork.43 — 2026-11-23

### 1. 背景与原因

用户要求在标题/菜单栏“工具”（当前 Ultralytics 所在菜单）中增加：

- 训练结果分析
- SAM
- RF-DETR
- Efficient

并明确“暂时不实现功能，先添加菜单”，同时把四项加入设计书作为后续功能。

### 2. 主要实现与关键细节

- 在 `actions/builder.py` 增加四个 QAction：
  - `training_analysis`：Training Result Analysis；
  - `sam_tool`：SAM；
  - `rf_detr_tool`：RF-DETR；
  - `efficient_tool`：Efficient。
- 四个动作均使用 `planned_feature()`：点击只在状态栏提示“%s is planned but not implemented yet.”，不启动任何训练/模型逻辑。
- 图标：`chart-column`、`circle-selection`、`component`、`cpu-ai`；tooltip 写明 Planned。
- 在 `actions/menus.py` 的 Train 菜单中，Ultralytics 后加分隔线，再列四个占位项。
- 翻译：新增菜单/提示 6 条；四语言 `.qm` 各 2325 条。
- 设计书 §6.6.1–§6.6.4 新增四项规划：
  - 训练结果分析：只读解析 Ultralytics run（args/results/weights/曲线/混淆矩阵），按类别定位错误样本、对比 run、回链数据集；
  - SAM：统一 SAM/SAM2 提示分割工作台，复用现有适配器与 CPU 串行锁/BFC 策略；
  - RF-DETR：检测模型族接入自动标注/训练包/结果回导，首期不在桌面端训练；
  - Efficient：EfficientViT/EfficientDet 等轻量模型族，面向 CPU/低显存。
- 版本：4.3.2+fork.42 → 4.3.2+fork.43。

### 3. 涉及模块与文件

- 修改：`anylabeling/views/labeling/actions/builder.py`、`actions/menus.py`、`resources/translations/*`、`app_info.py`
- 测试：`tests/test_labeling/test_file_table.py`（四个 action 存在）
- 文档：本文件、`docs/dev/工业机器视觉数据平台-设计书-v1.6.md`（正文 v1.20）、`docs/dev/CODE_STRUCTURE_REPORT.md`、`docs/开始.md`

### 4. 行为、接口与兼容性影响

- **用户可观察**：Train 菜单在 Ultralytics 后新增四个菜单项；点击显示“规划功能，暂未实现”，不会触发训练/推理。
- **接口**：`actions.training_analysis`/`sam_tool`/`rf_detr_tool`/`efficient_tool`。
- **数据**：无变化。
- **版本**：fork.42 → fork.43。

### 5. 实际验证内容

- `test_train_menu_has_planned_tool_entries`：四个 action 均已注册，Ultralytics 仍存在。
- 四语言 `.qm` 各 **2325 条 / 0 unfinished**；`resources.py` 无 diff。
- 最终回归：`test_labeling` **256 passed / 10 failed / 51 subtests**（失败集合与基线相同）；其余沿用 fork.42 的 **291 passed / 1 failed / 105 subtests**；合计 **547 passed / 11 failed / 156 subtests**。
- **未执行**：真实菜单点选观感、占位提示翻译逐语言检查、打包与全量回归。

### 6. 已知限制与后续事项

- 四个菜单项目前完全无功能，只是占位；点击不会打开任何窗口。
- “训练结果分析”优先做只读分析；SAM/RF-DETR/Efficient 需要模型管理、训练包格式和自动标注适配，属于后续独立批次。
- 菜单放在与 Ultralytics 相同的 Train 菜单，而不是 Tool 菜单；如果用户希望放在 Tool 菜单，需要再确认（避免同一动作出现在两个菜单）。

---

## 4.3.2+fork.42 — 2026-11-23

### 1. 背景与原因

用户反馈 4 项：

1. “移动到文件夹”用了 Qt 自绘的 “Look in” 对话框，不能在顶部直接输入路径；希望全部文件/文件夹选择都用 Windows 原生对话框；
2. 该操作用的是文件选择窗口，应改为文件夹选择；
3. 只允许移动到数据集根目录内不合理；移出数据集可后悔/重新导入，风险低，应允许；
4. 已记录每张图的 `editor`/时间，但无法按“张三/李四”筛选或查看。

### 2. 主要实现与关键细节

- **全部文件/文件夹选择改用原生对话框**：
  - 移除标注、导出、上传、点云、PPOCR、可视化等模块所有显式
    `QtWidgets.QFileDialog.Option.DontUseNativeDialog`；
  - `file_dialog_preview.py` 把该选项显式设为 `False`（原生），自定义预览不再拦截；
  - `file_session.py` 保存对话框保留 `DontUseNativeDialog, False`，同样是原生；
  - 原生窗口支持顶部地址栏输入/粘贴路径。
- **移动改为文件夹选择**：
  - `getExistingDirectory(..., options=ShowDirsOnly)`，只列文件夹，不再显示文件；
  - 目标可用任意目录。
- **允许移出数据集**：
  - 目标在数据集根内：移动图片+同名 JSON，`DatasetRepository.move_image()` 更新 `rel_path`/`file_name`；
  - 目标在根外：先弹“移出数据集”确认，移动文件后 `delete_image()` 软删 DB 行并从文件表移除；文件/JSON 保留在新目录，可重新导入；
  - 失败回滚文件并保留原行；多选按行倒序处理，避免删行导致索引错位。
- **编辑人筛选/查看（不新增列）**：
  - 搜索语法新增 `editor::张三`（也支持 `author::张三`，精确、不区分大小写）；
  - DB 走 `image_summaries(editor=...)` 的 `f.editor` 过滤；JSON 走 `_LabelData.editor`；
  - 文件表不新增列；文件名 tooltip 增加“编辑人：%s”；
  - `FileMeta` 增加 `editor` 字段，DB 行从 `image_summaries` 的 `editor` 读取，JSON 从 `author`/`editor` 读取。
- 翻译：新增“移出数据集/确认/编辑人”等 4 条；更新搜索语法 tooltip；`.qm` 各 2319 条。
- 版本：4.3.2+fork.41 → 4.3.2+fork.42。

### 3. 涉及模块与文件

- 修改：`anylabeling/views/labeling/file_list/controller.py`、`file_session.py`、`right_sidebar.py`、`widgets/workspace.py`、`widgets/label_manager.py`、`utils/export.py`、`utils/upload.py`、`utils/crop.py`、`utils/visualization.py`、`widgets/file_dialog_preview.py`、`widgets/ppocr_dialog.py`、`widgets/pointcloud_dialog.py`、`pointcloud/*`、`services/dataset/repository.py`、`utils/file_search.py`、`utils/file_meta.py`、`resources/translations/*`、`app_info.py`
- 测试：`tests/test_labeling/test_file_table.py`（移出数据集）、`tests/test_dataset_db/test_repository.py`（editor 过滤）、`tests/test_dataset_db/test_ui_adapter.py`（6 元过滤器）、`tests/test_utils/test_file_search.py`（editor 搜索）、`tests/test_pointcloud/test_ui_details.py`（原生对话框断言）
- 文档：本文件、`docs/dev/CODE_STRUCTURE_REPORT.md`、`docs/dev/工业机器视觉数据平台-设计书-v1.6.md`（正文 v1.19）、`docs/dev/数据库设计-讨论稿.md`、`docs/开始.md`、`docs/user/zh_cn/user_guide.md`

### 4. 行为、接口与兼容性影响

- **用户可观察**：文件/文件夹选择为 Windows 原生窗口，可直接输入路径；移动使用文件夹选择；可移出数据集（确认后从列表/DB 活跃记录移除）；搜索框可用 `editor::张三`，文件名悬停显示编辑人。
- **接口**：新增 `image_summaries(editor=...)`；`_simple_database_filters()` 返回 6 元组（追加 editor）；`FileMeta.editor`；`parse_category_names` 等不受影响。
- **数据**：移出数据集是软删除，文件保留在新目录；可重新导入恢复。无 schema 变更。
- **版本**：fork.41 → fork.42。

### 5. 实际验证内容

- `test_move_to_folder_updates_db_and_file_table`：根内移动，图片+JSON+DB+文件表同步。
- `test_move_outside_dataset_removes_row`：移出根外，文件保留、文件表行移除、DB 活跃行消失。
- `test_image_summaries_sql_filters`：`editor="张三"` / `"李四"` 过滤；`test_editor_search_matches_attribution`：`editor::张三` / `author::李四`。
- `test_simple_database_filters_parses_tags`：6 元组含 editor。
- `test_file_and_folder_choosers_use_native_dialogs`：点云打开文件/文件夹不再带 `DontUseNativeDialog`。
- 最终回归：`test_labeling` **255 passed / 10 failed / 51 subtests**；其余（不含 pointcloud）**291 passed / 1 failed / 105 subtests**；合计 **546 passed / 11 failed / 156 subtests**。10 条与 HEAD 基线逐条相同，第 11 条为已知 `test_brightness_contrast_updates_are_throttled` 时序抖动。
- `tests/test_pointcloud` 整组在本沙箱运行到约 54% 时进程异常退出（`0xC0000409`），单条原生对话框用例通过；该组未纳入最终统计。
- 四语言 `.qm` 各 **2319 条 / 0 unfinished**；`resources.py` 无 diff。
- **未执行**：真实桌面所有原生对话框逐项点选、根外移动后重新导入恢复、编辑人筛选在真实 DB 的 UI 观感、打包与全量回归。

### 6. 已知限制与后续事项

- 原生 Windows 对话框不继承应用深色主题；`file_dialog_preview.py` 的自定义预览在原生模式下不可见。
- 移出数据集为软删除，回收站仍保留 DB 行；重新导入会按新路径重建记录，不自动恢复原 `rel_path`。
- 编辑人筛选是精确匹配；同一人有多种写法（`张三`/`zhangsan`）时需分别搜索；文件表只在 tooltip 显示，不新增列。
- 多选移出时同名冲突逐项失败，不自动改名。
- 点云整组测试崩溃与本次改动无直接证据，但未完成基线对比；若后续复现需单独排障。

---

## 4.3.2+fork.41 — 2026-11-23

### 1. 背景与原因

用户反馈 2 项：

1. 类别“批量导入”的表头覆盖按钮会与表头重合，方案不可用；
2. fork.40 的文件表右键菜单没有“移动到文件夹…”（此前只给了方案，未实现）。

### 2. 主要实现与关键细节

- **类别批量导入入口改到右侧标签栏右上角**：
  - 删除 `LabelManagerPanel` 内覆盖 `QHeaderView` 的按钮与 `eventFilter`；
  - 在 `workspace.py` 创建 `host.category_import_button`，用
    `right_tabs.setCornerWidget(..., Qt.Corner.TopRightCorner)` 放到 Classes
    标签栏右上角；
  - `RightSidebarTabs._on_right_tab_changed()` 只在 Classes 页显示该按钮；
  - 按钮仍调用 `LabelManagerPanel.import_categories()`，`set_editing_enabled()`
    同步禁用/启用。
- **文件表“移动到文件夹…”**：
  - 右键菜单在“设置标签…”之后新增“移动到文件夹…”（folder-tree 图标）；
  - 仅允许选择当前数据集根目录内的文件夹；目标同名文件存在时中止；
  - 逐项移动图片 + 同名 JSON（`output_dir` 路径相同时 JSON 不移动）；
  - DB 模式调用新增 `DatasetRepository.move_image()` 更新
    `rel_path`/`file_name`/`ext`；移动文件或 DB 更新失败时回滚文件，保留原行；
  - 成功后更新文件表路径、`fn_to_index`、`_import_times`、标签库路径、缩略图；
    当前图片会重新加载；失败项在状态栏报告。
  - 移动前如当前图片有未保存修改，先走 `may_continue()`；并要求登录
    `_ensure_operator()`。
- 翻译：新增“移动到文件夹…”等 5 条；`.qm` 各 2315 条。
- 版本：4.3.2+fork.40 → 4.3.2+fork.41。

### 3. 涉及模块与文件

- 修改：`anylabeling/views/labeling/widgets/workspace.py`、`right_sidebar.py`、`widgets/label_manager.py`、`file_list/controller.py`、`services/dataset/repository.py`、`resources/translations/*`、`app_info.py`
- 测试：`tests/test_labeling/test_file_table.py`（按钮显示/隐藏、移动图片+JSON+DB）
- 文档：本文件、`docs/dev/CODE_STRUCTURE_REPORT.md`、`docs/dev/工业机器视觉数据平台-设计书-v1.6.md`（正文 v1.18）、`docs/dev/数据库设计-讨论稿.md`、`docs/开始.md`、`docs/user/zh_cn/user_guide.md`

### 4. 行为、接口与兼容性影响

- **用户可观察**：Classes 页标签栏右上角出现导入图标（切到其他页隐藏），不再遮挡表头；文件表右键出现“移动到文件夹…”，移动后图片/JSON/DB/文件表同步。
- **接口**：`FileListController.move_rows_to_folder()`/`_move_one_file()`/`_update_row_path()`；`DatasetRepository.move_image()`；`host.category_import_button`。
- **数据**：`rel_path`/`file_name` 更新；无 schema 变更；移动只允许数据集根内，避免产生外部悬空行。
- **版本**：fork.40 → fork.41。

### 5. 实际验证内容

- `test_category_import_button_is_shown_on_classes_tab`：Classes 页可见、切到 Objects 隐藏。
- `test_move_to_folder_updates_db_and_file_table`：图片+JSON 移动到 `moved/`，文件表路径更新，DB 新 `rel_path` 可查、旧路径消失。
- 最终回归同集合分两组：`test_labeling` **254 passed / 10 failed / 51 subtests**；其余 **290 passed / 1 failed / 105 subtests**；合计 **544 passed / 11 failed / 156 subtests**，10 条与 HEAD 基线逐条相同，第 11 条为已知 `test_brightness_contrast_updates_are_throttled` 时序抖动。
- 四语言 `.qm` 各 **2315 条 / 0 unfinished**；`resources.py` 无 diff。
- **未执行**：真实桌面右键移动/标签栏按钮位置观感、多文件移动冲突、跨卷移动、打包与全量回归。

### 6. 已知限制与后续事项

- 移动只允许数据集根目录内；移动到数据集外仍需“移出数据集/移除记录”的独立动作，未实现。
- 多选移动中同名冲突逐项失败，不做自动改名。
- JSON 模式移动可跨目录；文件表保留新路径，但重新打开当前文件夹时，移出该文件夹的图片不会自动出现。
- 标签栏右上角按钮是 QTabWidget corner widget；若同时隐藏多个 tab，位置随标签栏宽度变化。
- 移动 API 未写 `editor/modified_at`（文件组织操作，不属于标注内容修改）。

---

## 4.3.2+fork.40 — 2026-11-23

### 1. 背景与原因

用户反馈 5 项：

1. “类别”页批量导入按表头右上角按钮做，先看效果；
2. 已有登录后，类别“锁定”是否还有必要；
3. 标签库搜索在标题栏后高度太低、搜索框变形，且计数 `(x)` 应紧挨标题；
4. 批量标签对话框的标签库不能随窗口拉伸，仍被折叠；
5. SAM ONNX 在有内存时仍报 1 GiB BFC 分配失败，切模型后恢复。

### 2. 主要实现与关键细节

- **类别批量导入**：
  - `LabelManagerPanel` 在 `QTableWidget.horizontalHeader()` 上放 22×22 `QToolButton`（`clipboard-paste` 图标），通过 `eventFilter` 定位到表头右上角；不新增行。
  - 点击弹多行输入框；`parse_category_names()` 按中文/英文逗号、空白、换行分隔，去重保序。
  - DB 模式 `ensure_category()` 追加；导入后刷新类别页。非 DB 数据集提示“仅适用于数据集文件夹”。
  - DB 模式类别页改为显示**全部类别**（含 0 对象）；空类别可改名/删除：新增 `DatasetRepository.rename_category()`/`delete_category()`/`category_object_count()`，`_rewrite_database()` 对 0 对象类别走类别级操作，范围改名/删除后清理已变空的旧类别。
  - 导出 `_dataset_category_names()` 也包含 0 对象类别，保持“界面顺序 = 导出顺序”。
- **标签库标题栏**：
  - 标题/计数改回紧邻；搜索框放在 stretch 之后、折叠按钮之前；
  - 搜索框高度 20 → 24px，宽度 52–180px，不再被压扁；
  - 仍保持 `minimumSizeHint` 宽 0，避免抬高侧栏最小宽度。
- **批量标签对话框拉伸**：
  - `TagLibraryWidget` 从固定/最大高度改为可扩展，`layout.addWidget(..., 1)`；
  - 对话框启用 size grip；标签列表最小 60px，随窗口高度增长。
- **SAM ONNX BFC arena**：
  - `sam_onnx.py` 为 encoder/decoder 共用 `SessionOptions`，设置
    `enable_cpu_mem_arena=False`、`enable_mem_pattern=False`；
  - 不再预申请/扩展 1 GiB BFC 块，避免“物理内存尚有余量但连续块分配失败”；
  - 保留 fork.20 的 CPU 串行锁与 encoder 释放后重建策略。
- 翻译：新增类别导入 7 条；四语言 `.qm` 各 2310 条。
- 版本：4.3.2+fork.39 → 4.3.2+fork.40。

### 3. 涉及模块与文件

- 修改：`anylabeling/views/labeling/widgets/label_manager.py`、`anylabeling/views/labeling/utils/category_names.py`（新增）、`anylabeling/services/dataset/repository.py`、`anylabeling/views/labeling/widgets/tag_library.py`、`anylabeling/views/labeling/file_list/tags_dialog.py`、`anylabeling/services/auto_labeling/sam_onnx.py`、`resources/translations/*`、`app_info.py`
- 测试：`tests/test_labeling/test_label_manager.py`、`tests/test_utils/test_category_names.py`（新增）、`tests/test_dataset_db/test_repository.py`、`tests/test_labeling/test_file_table.py`
- 文档：本文件、`docs/dev/CODE_STRUCTURE_REPORT.md`、`docs/dev/工业机器视觉数据平台-设计书-v1.6.md`（正文 v1.17）、`docs/dev/数据库设计-讨论稿.md`、`docs/开始.md`、`docs/user/zh_cn/user_guide.md`

### 4. 行为、接口与兼容性影响

- **用户可观察**：类别页可批量导入并显示空类别；空类别可改名/删除；标签库搜索高度/计数布局修复；批量标签对话框标签库可随窗口拉伸；SAM 不再因 BFC 1 GiB 块失败（在内存确实不足时仍会失败，但不再误报竞技场错误）。
- **接口**：`DatasetRepository.rename_category()`/`delete_category()`/`category_object_count()`；`parse_category_names()`；`LabelManagerPanel.import_categories()`。
- **数据**：`category` 表无 schema 变更；空类别为 `is_deleted=0` 正常行，删除为软删除；导出包含空类别。
- **版本**：fork.39 → fork.40。

### 5. 实际验证内容

- `test_label_manager.py`：**全部通过**，新增“批量导入追加类别”和“空类别也显示”用例。
- `test_category_names.py`：2 条解析用例通过。
- `test_repository.py`：新增“空类别改名/删除、已使用类别不可删”用例通过。
- 标签库/侧栏：搜索在标题栏、高度 24、计数紧邻标题；侧栏最小宽度两条回归通过。
- 批量标签对话框：标签库直接复用、随窗口增长（离屏手工验证）。
- `.qm` 四语言各 **2310 条 / 0 unfinished**；`resources.py` 无 diff。
- 最终回归（同集合分两组）：`test_labeling` **252 passed / 10 failed / 51 subtests**；其余 **290 passed / 1 failed / 105 subtests**；合计 **542 passed / 11 failed / 156 subtests**，10 条与 HEAD 基线逐条相同，第 11 条为已知 `test_brightness_contrast_updates_are_throttled` 时序抖动。
- **未执行**：真实桌面批量导入/空类别改名删除、表头按钮实际位置观感、SAM 真实模型 OOM 复测、打包与全量回归。

### 6. 已知限制与后续事项

- 表头按钮是 `QHeaderView` 子控件，覆盖在最右列表头上；窗口很窄时可能遮挡 `Color` 表头文字，需要按实际观感调位置/图标。
- 批量导入按精确名称去重；大小写不同视为不同类别。
- 0 对象类别的删除是软删除，目前没有“恢复已删除空类别”的 UI。
- SAM 关闭 arena 会略增分配开销；若实际提交内存确实不足，仍可能 OOM，需要关闭其它模型/增大页面文件。
- 类别“锁定”评估见本轮回复：登录与锁定职责不同，暂建议保留。

---

## 4.3.2+fork.39 — 2026-11-23

### 1. 背景与原因

用户反馈/要求：

1. 不应再区分 DB/JSON 两套操作逻辑：打开文件夹时没有 DB 就创建 DB，之后全部走 DB；
2. “类别”页的批量导入按钮不应占用一整行；
3. 外部删除/移走图片后，不需要复杂校验；打开该行时只弹“清除出列表/跳过”；
4. 评估把标签库搜索栏移到标题栏；代码量小/逻辑简单就移动；
5. 批量设置图片标签对话框应复用“标签库”的点选方式，并收紧 label/combobox/lineedit 间距。

### 2. 主要实现与关键细节

- **打开文件夹强制建库（正常 UI 路径）**：
  - `import_image_folder()` 对所有带图片目录先 `_ensure_dataset_for_folder()`，不区分是否搜索/是否已有 DB；
  - 建库失败直接返回，不再静默回退到 JSON 读写；
  - 移除单文件打开路径里的 `auto_db=False`；
  - `_ensure_dataset_for_folder()` 改为三态：`True` 可用、`False` 硬失败、`None` 无图片；
  - `auto_db=False` 仅保留给测试/迁移工具，正常 UI 不再使用。JSON 读写分支仍存在，但只服务于旧项目导入/兼容测试，完整删除属于 P4。
- **缺失文件简化处理**：
  - `load_file()` 发现 `QFile.exists()` 为假时，若该路径在文件表中，弹“文件不存在”对话框，只有 **从列表移除** / **跳过** 两个动作；
  - 移除：`FileListController.remove_missing_path()` 删除文件表行，并把 DB 行软删除（`repository.delete_image`），随后加载下一张；
  - 跳过：`skip_missing_path()` 保留记录，选中下一张；
  - 不扫描全盘、不做移动匹配、不自动改其他 `rel_path`。
- **标签库搜索栏移入标题栏**：
  - `TagLibraryWidget` 标题行改为“标题 + 计数 + 搜索框 + 折叠”，删除 body 里的独立搜索行；
  - 搜索框 `52–180px`、高 20px；`minimumSizeHint()` 覆盖为宽度 0、`sizeHint()` 宽度 160，避免把右侧栏最小宽度重新抬高；
  - 逻辑不变，只是布局移动；代码量约 25 行，不复杂。
- **批量标签对话框复用标签库**：
  - `BatchTagsDialog` 嵌入同一个 `TagLibraryWidget`（搜索、双击标签加入输入框），删除“从标签库添加…”下拉；
  - 去掉 `QStackedWidget`，改为同层 group 显隐，消除 stack 最大页高度造成的空白；
  - 主布局 spacing 8、页内 spacing 4；标签列表高度 44–96px；
  - 三种模式不变；替换模式的“要替换的标签”仍是可编辑下拉（它是替换源，不是“添加标签”）。
- 翻译：新增“文件不存在/丢失/移除或跳过/Skip”4 条；`.qm` 各 2303 条。
- 版本：4.3.2+fork.38 → 4.3.2+fork.39。

### 3. 涉及模块与文件

- 修改：`anylabeling/views/labeling/file_session.py`、`file_list/controller.py`、`file_list/tags_dialog.py`、`widgets/tag_library.py`、`resources/translations/*`、`anylabeling/app_info.py`
- 测试：`tests/test_labeling/test_file_table.py`（自动建库、缺失文件移除）、`tests/test_widgets/test_tag_library_widget.py`、`tests/test_labeling/test_label_manager.py`
- 文档：本文件、`docs/dev/CODE_STRUCTURE_REPORT.md`、`docs/dev/工业机器视觉数据平台-设计书-v1.6.md`（正文 v1.16）、`docs/dev/数据库设计-讨论稿.md`、`docs/开始.md`、`docs/user/zh_cn/user_guide.md`

### 4. 行为、接口与兼容性影响

- **用户可观察**：打开任意图片文件夹都会自动建库；建库失败明确报错；外部删除图片时只问“移除/跳过”；标签库搜索在标题栏；批量标签对话框直接点标签库。
- **接口**：`_ensure_dataset_for_folder()` 三态；`remove_missing_path()`/`skip_missing_path()`；`TagLibraryWidget.sizeHint()/minimumSizeHint()`。
- **数据**：无 schema 变更；缺失图片“从列表移除”会将 DB 行软删除；不做自动重定位。
- **版本**：fork.38 → fork.39。

### 5. 实际验证内容

- `test_folder_open_always_creates_database`：无库目录首次打开生成 `xanylabeling.db`。
- `test_missing_file_can_be_removed_from_db_list`：删除磁盘图片后 `remove_missing_path()` 从文件表/DB 活跃行移除。
- 标签库/批量对话框用例：搜索仍在标题栏、双击标签加入、布局可用。
- 侧栏最小宽度两条回归：标签库搜索移动后仍可拖窄（修复 `sizeHint` 抬高最小宽度）。
- 四语言 `.qm` 各 **2303 条 / 0 unfinished**；`resources.py` 无 diff。
- 最终回归（同集合分两组）：`tests/test_labeling` **251 passed / 10 failed / 51 subtests**，`tests/test_widgets` + `tests/test_dataset_db` + `tests/test_config` + `tests/test_utils` **286 passed / 1 failed / 105 subtests**；合计 **537 passed / 11 failed / 156 subtests**。10 条失败与 HEAD 基线逐条相同；第 11 条是已知时序抖动 `test_brightness_contrast_updates_are_throttled`，基线本次未触发。

### 6. 已知限制与后续事项

- 正常 UI 已强制 DB，但 JSON 读写函数仍保留给旧项目导入、CLI/兼容测试；彻底删除是 P4，不能靠本批完成。
- 缺失文件“从列表移除”是软删除，回收站仍会保留该行；若希望硬删除/从回收站彻底清除，需要单独的清理动作。
- 批量导入类别（“类别”页）尚未实现；建议改为表头右上角 `QToolButton`（`setCornerWidget`），不占行。
- 标签库搜索在标题栏后，窄侧栏下宽度有限（最小 52px）；英文标题较长时会更紧。
- 批量标签的“要替换的标签”仍是下拉；若也要改成标签库单击选择，需要额外的单击/双击区分。

---

## 4.3.2+fork.38 — 2026-11-23

### 1. 背景与原因

用户反馈 2 个已确认的缺陷：

1. 导出项目时仍要求选择 `classes.txt`；而“类别”页已能调整 `category.sort_index`，外部 classes 文件与界面顺序可能不一致；
2. “类别”页底部 `From [ ] To [ ] [Go] [↑] [↓]` 中两个 `QSpinBox` 和 `Go` 按钮过高/过宽，与 24×22 的上下移按钮及界面字体不协调。

另有两项设计问题（批量导入类别、移动图片到其他文件夹）本轮只给出方案，未改代码。

### 2. 主要实现与关键细节

- **DB 模式导出使用“类别”页顺序**：
  - 新增 `export.py::_dataset_category_names(host)`：有 `dataset_repository` 时读取 `category_counts()` 中 `object_count > 0` 的类别，顺序与“类别”页完全一致；异常时返回空列表并保留旧回退。
  - `LabelConverter` 增加 `classes=` 参数，按传入顺序去重，不读文件、不重排。
  - 已接入 YOLO hbb/obb/seg、COCO rectangle/polygon、DOTA、MOT/MOTS/ODVG：DB 模式不再弹 `classes.txt`；纯 JSON 目录仍保留原来的文件选择。YOLO/COCO Pose 仍选择关键点 YAML（其中含类别/关键点定义）。
- **“类别”页范围行紧凑化**：
  - 新增 `get_compact_spinbox_style()` 与 `get_compact_ok_btn_style()`（12px 字体、22px 高、圆角 4px）；
  - `from_input`/`to_input` 固定 48×22，`Go` 高 22、最大宽 48，`From`/`To` 标签字号 12px；与 24×22 的上下移按钮同高；
  - 不改范围语义（仍是图片序号范围），只改尺寸。
- 文档同步：用户手册补充 DB 模式导出类别来源；设计书 v1.15 明确“DB 导出不得再选 classes.txt”。
- 版本：`4.3.2+fork.37` → `4.3.2+fork.38`。

### 3. 涉及模块与文件

- 修改：`anylabeling/views/labeling/utils/export.py`、`anylabeling/views/labeling/label_converter.py`、`anylabeling/views/labeling/widgets/label_manager.py`、`anylabeling/views/labeling/utils/style.py`、`anylabeling/app_info.py`
- 测试：`tests/test_utils/test_label_converter.py`（显式 classes 顺序/去重、DB 类别来源）、`tests/test_labeling/test_label_manager.py`（范围行 22px/按钮宽度）
- 文档：本文件、`docs/dev/CODE_STRUCTURE_REPORT.md`、`docs/dev/工业机器视觉数据平台-设计书-v1.6.md`（正文 v1.15）、`docs/开始.md`、`docs/user/zh_cn/user_guide.md`

### 4. 行为、接口与兼容性影响

- **用户可观察**：DB 数据集导出 YOLO/COCO/DOTA/MOT 不再询问 `classes.txt`，类别编号按“类别”页顺序；JSON 目录行为不变；类别页范围行更紧凑。
- **接口**：`LabelConverter(classes=...)`；`export.py::_dataset_category_names()`；`get_compact_*_style()`。
- **数据/契约**：无 schema 变更；导出只读类别表；“类别”页仍只列有对象的类别。
- **版本**：fork.37 → fork.38。

### 5. 实际验证内容

- `tests/test_utils/test_label_converter.py`：**32 passed / 7 subtests**（新增显式 classes 顺序/去重与 DB 类别来源用例；含原 YOLO/COCO/DOTA/MOT/Pose 用例）。
- `tests/test_labeling/test_label_manager.py::test_range_controls_match_reorder_button_height`：三个控件高度 22、`Go` 宽 ≤48。
- 本轮 `tests/test_labeling` + `tests/test_widgets` + `tests/test_dataset_db` + `tests/test_config` + `tests/test_utils/test_tag_library.py` + `tests/test_utils/test_file_search.py` + `tests/test_utils/test_label_converter.py`：**429 passed / 10 failed / 156 subtests**；10 条失败与 HEAD 基线逐条相同（本次时序抖动 `test_brightness_contrast_updates_are_throttled` 未触发）。
- **未执行**：真实桌面导出对话框（确认不再弹 classes）与真实“类别”页截图、导出文件类别编号逐项核对、打包与全量回归。

### 6. 已知限制与后续事项

- DB 模式导出只包含“类别”页当前可见（`object_count > 0`）的类别；无对象类别不参与编号，也无法在类别页调整顺序。
- 纯 JSON 目录没有持久化类别顺序，仍提示选择 `classes.txt`。
- 批量导入类别（用户问题 2）与移动图片到其他文件夹/手动移动后的 DB 同步（问题 4）尚未实现，方案见本轮回复。
- “类别”页控件使用固定 12px 字号/22px 高；若系统缩放或主题字体变化，需再看实际观感。

---

## 4.3.2+fork.37 — 2026-11-23

### 1. 背景与原因

用户反馈 3 项：

1. “设置图片标签”窗口未与“图像属性 → 标签库”联动；
2. “替换现有标签”当前是“删除所有标签再加入新标签”，不符合“把图片中的 xxx 替换为 yyy”的语义；
3. 由于 2 的调整，combobox 需要新增“批量删除所有标签”选项；
4. 该窗口应更名为“批量设置图片标签”。

第 2 项根因：fork.32 的 `apply_image_tags(replace=True)` 把目标标签列表当作整组覆盖，导致不相关标签被清空。第 1 项属于对话框没有读取标签库词表。

### 2. 主要实现与关键细节

- **三种批量模式**（[batch_tags.py](../../anylabeling/views/labeling/utils/batch_tags.py)）：
  - `add`：追加标签、去重；
  - `replace`：必须提供 `old_tags`，只处理包含旧标签的图片：移除旧标签、追加新标签，**其它标签保留**；不含旧标签的图片保持不变（不会退化成批量添加）；
  - `delete_all`：清空全部图片标签，控制器在执行前二次确认。
- **对话框重构**（[tags_dialog.py](../../anylabeling/views/labeling/file_list/tags_dialog.py)）：
  - 标题改为“批量设置图片标签”（Batch Set Image Tags）；
  - 模式下拉三种；`QStackedWidget` 分别显示“要添加的标签”“要替换的标签 + 替换为”“删除全部”警示；
  - “从标签库添加…”下拉从当前文件夹/数据集词表取标签，追加到输入框，解决“未联动”；
  - 替换模式的旧标签是可选可编辑下拉，新标签支持标签库下拉；提交前校验至少一个标签/旧标签/新标签。
- **控制器**（[controller.py](../../anylabeling/views/labeling/file_list/controller.py)）：
  - 打开对话框前 `_refresh_tag_library()`，把 `_tag_library_entries` 的标签名传入；
  - 读取 `dialog.mode()/tags()/old_tags()`，删除全部先确认，替换缺旧标签不执行；
  - `apply_image_tags(..., mode=..., old_tags=...)`。
- **测试**：`merge_image_tags`/`apply_image_tags` 的 JSON/DB 用例改为 mode/old_tags；新增替换保留其它标签、不含旧标签 unchanged、删除全部、DB 集成替换；对话框测试三种模式与解析。
- 翻译：新增 13 条（标题/三种模式/输入标签/校验/删除确认/标签库下拉），重编 `.qm`。
- 版本：`4.3.2+fork.36` → `4.3.2+fork.37`。

### 3. 涉及模块与文件

- 修改：`anylabeling/views/labeling/utils/batch_tags.py`、`anylabeling/views/labeling/file_list/tags_dialog.py`、`anylabeling/views/labeling/file_list/controller.py`、`anylabeling/resources/translations/*`、`anylabeling/app_info.py`
- 测试：`tests/test_dataset_db/test_batch_tags.py`、`tests/test_labeling/test_file_table.py`
- 文档：本文件、`docs/dev/CODE_STRUCTURE_REPORT.md`、`docs/dev/工业机器视觉数据平台-设计书-v1.6.md`（正文 v1.14）、`docs/dev/数据库设计-讨论稿.md`、`docs/开始.md`、`docs/user/zh_cn/user_guide.md`

### 4. 行为、接口与兼容性影响

- **用户可观察**：批量对话框标题为“批量设置图片标签”；替换指定标签不再清空其它标签；不含旧标签的图片不改变；新增“删除所有图片标签”模式；标签输入可从标签库选择。
- **接口**：`merge_image_tags(existing, tags, mode, old_tags)`；`apply_image_tags(..., mode=..., old_tags=...)`；`BatchTagsDialog.mode()/old_tags()/tags()`；`BatchTagsDialog` 构造增加 `library_tags` 参数。
- **数据/契约**：无 schema 变更；仍是“内容变化才写盘/盖章”，未变化图片跳过；删除全部需确认。
- **版本**：fork.36 → fork.37。

### 5. 实际验证内容

- `tests/test_dataset_db/test_batch_tags.py`：**12 passed**（添加、替换指定标签保留其它标签、不含旧标签 unchanged、删除全部、JSON 归属、DB 合并/替换、坏文件/未知图）。
- `tests/test_labeling/test_file_table.py`：批量替换集成用例在 DB 中验证 `["keep","old"] → ["keep","new"]`、`["old"] → ["new"]`、未选中图片不变；对话框三模式/旧新标签解析通过。
- 本轮 `tests/test_labeling tests/test_widgets tests/test_dataset_db tests/test_config tests/test_utils/test_tag_library.py tests/test_utils/test_file_search.py`：**395 passed / 11 failed / 149 subtests**；失败集合与 HEAD 基线逐条相同（唯一差异仍是时序抖动 `test_brightness_contrast_updates_are_throttled`）。
- 四语言 `.qm` 各 **2299 条 / 0 unfinished**；`resources.py` 仍无 diff（fork.36 的 `--no-resources` 流程）。
- **未执行**：真实桌面三种模式/标签库下拉/删除确认观感、超大批量替换性能、打包与全量回归。

### 6. 已知限制与后续事项

- 替换模式只做“移除旧标签 + 追加新标签”，不是任意多对多映射（例如 a→x 且 b→y 的成对映射）；需要时可按逗号输入多旧/多新标签，统一移除/追加。
- 标签库下拉列出文件夹/数据集全部标签；替换旧标签下拉没有按“选中图片中实际存在的标签”预过滤，选中不存在标签会得到 “unchanged” 结果。
- 删除全部仍会逐图保存（DB 每图一个事务），大批量较慢；后续可做单事务批量接口。
- 发布前仍需运行不带 `--no-resources` 的 `compile_languages.py`，把 2299 条翻译嵌入 `resources.py`。

---

## 4.3.2+fork.36 — 2026-11-23

### 1. 背景与原因

用户反馈/提问 5 项：

1. 查询 `(shape::0,split::none)` 时标签库标签被压缩成“暗…”“导…”等缩略；
2. 标签库来源应继续用文件列表，还是改用文件夹/数据库？
3. 标签的搜索/添加是否存储在数据库，是否有必要用数据库？
4. `resources.py` 按方案二执行；能否与方案一（拆分 qrc）结合，会不会更好？
5. 标签库单击添加容易手滑，是否改成双击添加。

第 1 项的根因：`QListWidget` 的 IconMode 虽然设置了 112px 网格，但每个 item 的 `sizeHint` 仍按文本宽度（约 44px）计算，长标签被 item 自身宽度截断；网格空余没有分配给 chip。第 5 项与“点击即写盘 + 归属”叠加后，误触成本较高，采纳双击。

### 2. 主要实现与关键细节

- **标签库来源改为文件夹/数据集**：
  - JSON 模式在 `import_image_folder()` 无搜索条件时记录 `host._tag_library_all_paths`（文件夹内全部图片）；搜索过滤只重建文件表，不再覆盖该列表；移除行时从列表剔除。
  - DB 模式直接 `DatasetRepository.tag_counts()`（全部活跃图片），不再传当前文件表 `rel_paths`。
  - 因此搜索过滤不会改变标签库词表；`(shape::0,split::none)` 等查询只影响文件表，不影响可添加的标签。
- **标签宽度修复**：
  - `TagLibraryWidget._rebuild()` 按当前匹配标签的最长文本计算 chip 宽度（96–200px），并给每个 item 设置 `sizeHint`；长标签不再被压成 2 个字，超长仍 elide + tooltip 全名。
- **双击添加**：
  - 单击只选中，不写盘；双击（或选中后 `Enter`）才添加并立即保存/盖章；右键/Ctrl+单击仍是 `tags::` 查找。
  - 提示与 tooltip 改为“双击添加……”。
- **resources.py 方案二（源码优先 `.qm`，发布前再嵌入）**：
  - `app.py` 先加载 `anylabeling/resources/translations/<lang>.qm`，失败再回退 `:/languages/...`。
  - `scripts/compile_languages.py` 新增 `--no-resources`：日常只编 `.qm`；不带参数时仍生成 `resources.py`，作为发布/打包步骤。
  - 本批使用 `--no-resources`，并把 `resources.py` 保持为上一版（无生成 diff）；发布前必须运行不带 `--no-resources` 的脚本。
  - **未采用方案一**：在方案二下静态资源几乎不再变化，再拆 qrc 需要多一个生成文件和构建步骤，收益重叠；如后续要做资源模块化可再拆。
- 翻译：标签库提示改为“双击添加……”并新增“Double-click to add.”；重编 `.qm`。
- 版本：`4.3.2+fork.35` → `4.3.2+fork.36`。

### 3. 涉及模块与文件

- 修改：`anylabeling/app.py`、`scripts/compile_languages.py`、`anylabeling/views/labeling/widgets/tag_library.py`、`label_widget.py`、`file_session.py`、`file_list/controller.py`、`resources/translations/*`、`app_info.py`
- 测试：`tests/test_widgets/test_tag_library_widget.py` 改为单击不添加/双击添加/长标签宽度；`tests/test_labeling/test_file_table.py` 改为双击写盘、增加“搜索过滤后词表不缩水”与登录提示用例
- 文档：本文件、`docs/dev/CODE_STRUCTURE_REPORT.md`、`docs/dev/工业机器视觉数据平台-设计书-v1.6.md`（正文 v1.13）、`docs/dev/数据库设计-讨论稿.md`、`docs/开始.md`、`docs/user/zh_cn/user_guide.md`

### 4. 行为、接口与兼容性影响

- **用户可观察**：标签库词表不随文件表搜索缩水；长标签显示完整（超长省略+tooltip）；单击只选中、双击/Enter 才添加；登录提示与 `tags::` 查找不变。
- **接口**：`LabelingWidget._tag_library_all_paths`；`TagLibraryWidget` 的 `itemDoubleClicked` 添加；`compile_languages.py --no-resources`；`app.py` 文件系统 `.qm` 优先。
- **数据/存储**：无 schema 变更。DB 数据集标签存 `image_tag`；纯 JSON 目录标签存 JSON 顶层 `tags`，不需要额外数据库。标签库/`tags::` 的索引是派生缓存，不另建表。
- **版本**：fork.35 → fork.36。

### 5. 实际验证内容

- `test_tag_library_widget.py`：单击不添加、双击添加、Ctrl+单击只查找、长标签 item 宽度 96–200px；离屏预览确认 4 字标签不再显示为“暗…”。
- `test_file_table.py`：双击后 JSON 立即写入 `tags`/`author`/`modified_at`；把文件表缩到 1 行后标签库仍包含其他图片的标签；未登录时库仍 enabled 且调用 `_ensure_operator()`。
- 本轮 `tests/test_labeling tests/test_widgets tests/test_dataset_db tests/test_config tests/test_utils/test_tag_library.py tests/test_utils/test_file_search.py`：**392 passed / 10 failed / 149 subtests**；失败集合与 HEAD 基线**完全相同**，未新增失败。
- 四语言 `.qm` 各 **2286 条 / 0 unfinished**；`resources.py` 本批无 diff（按方案二保留旧嵌入副本）。
- **未执行**：真实桌面双击/长标签观感、打包产物中文件系统 `.qm` 回退路径的真实安装验证、万级目录词表扫描性能、全量回归。

### 6. 已知限制与后续事项

- 发布/打包前必须运行 `python scripts/compile_languages.py`（不带 `--no-resources`），否则安装包内嵌的翻译仍是上一版；源码运行不受影响。
- 未拆分 qrc；静态资源变化时 `resources.py` 仍会整体重写。
- 标签库词表按文件夹/数据集全量维护；文件表搜索只影响列表，不影响词表。移除行会从 JSON 词表剔除该文件，但磁盘 JSON 仍在。
- 双击添加同样会立即保存当前图片的其它未保存修改；这是“点击即写盘”的既有语义。
- `tags::` 仍为精确标签名匹配；非 ASCII 大小写在 SQLite/JSON 两种模式可能略有差异。

---

## 4.3.2+fork.35 — 2026-11-23

### 1. 背景与原因

用户反馈 2 项（另有一项关于生成文件的疑问）：

1. `resources.py` 每次都被修改且行数特别大，想知道原因；
2. 标签库有三个新问题：①搜索框不支持 `tags` 字段；②未登录时点击标签没有登录提示；③鼠标悬停显示“xxx 张图片使用”很好，但点击已被用于添加，想知道如何快速查看哪些图片使用了该标签（即触发 `tags::xxx` 搜索）。

第 2 项的根因：`file_search.py` 没有 `tags` 字段；fork.34 把 `TagLibraryWidget` 放进了 `OperatorGate.apply()` 的禁用列表，未登录时点击被控件直接吞掉（没有走到 `_ensure_operator()`）；标签库只有左键添加一个事件。

### 2. 主要实现与关键细节

- **`tags::` 搜索**：
  - `file_search.py` 的字段集合加入 `tags`，`_LabelData` 缓存 `tags`，新增 `_matches_tags()`：按标签精确匹配、不区分大小写；`tags::a,tags::b` 为 AND，`tags::a|b` 走既有 OR 展开。
  - DB 快路径：`DatasetRepository.image_summaries(tags=...)` 用 `EXISTS (SELECT 1 FROM image_tag ... t.tag = ? COLLATE NOCASE)`；`FileSession._simple_database_filters()` 解析 `tags::` 并返回 5 元组（labels/tags/split/objectless/filename），统一用 `_unescape_filter_value()` 处理转义。复杂布尔式仍走完整求值器。
  - 搜索框 tooltip 与中文手册补充 `tags::xxx`。
- **未登录点击标签库**：
  - 移除 `OperatorGate.apply()` 对 `tag_library_widget` 的 `set_editing_enabled(False)`；标签库保持可点击，点击仍走 `_on_tag_library_tag_clicked()` → `_ensure_operator()`，未登录时弹出登录对话框。图片标签 chips 仍在浏览模式只读。
- **查找使用某标签的图片**：
  - `TagLibraryWidget` 新增 `tag_search_requested` 信号；右键标签菜单“Show images with this tag”，或 `Ctrl+单击` 触发。
  - `LabelingWidget._search_tag_from_library()` 用 `escape_query_value()` 拼出 `tags::标签名`，写入搜索框并调用 `file_search_changed()`；库底提示更新为“单击添加；右键或 Ctrl+单击可查看使用该标签的图片”。
- **`resources.py` 说明（未改代码）**：它是 `scripts/compile_languages.py` 用 Qt RCC 从 `resources.qrc` 生成的资源包，内嵌 252 个图标/图片/4 个 `.qm`；RCC 以每行约 16 字节的十六进制字面量输出，因此文件约 5.2 MB / 11.7 万行。只有资源文件变化（本批是翻译）时才会重新生成；翻译 `.qm` 在文件尾部，`.qm` 变化会移动后续字节串的断行位置，造成数万行 diff。该生成文件不手改；是否“拆分资源/改为运行时加载 `.qm`/发布时再生成”属于流程选择，本批未改。
- 翻译：替换 1 条标签库提示、新增“Show images with this tag”；四语言重编。
- 版本：`4.3.2+fork.34` → `4.3.2+fork.35`。

### 3. 涉及模块与文件

- 修改：`anylabeling/views/labeling/utils/file_search.py`、`anylabeling/views/labeling/file_session.py`、`anylabeling/services/dataset/repository.py`、`anylabeling/views/labeling/widgets/tag_library.py`、`anylabeling/views/labeling/label_widget.py`、`anylabeling/views/labeling/operator/gate.py`、`anylabeling/resources/translations/*`、`resources.py`、`app_info.py`
- 测试：`tests/test_utils/test_file_search.py` 增加 `tags::` 用例；`tests/test_widgets/test_tag_library_widget.py` 增加 Ctrl+单击搜索用例；`tests/test_labeling/test_file_table.py` 增加未登录可点击/登录提示与 `tags::` 搜索框写入断言；`tests/test_dataset_db/test_repository.py` 增加 `image_summaries(tags=...)` 断言
- 文档：本文件、`docs/dev/CODE_STRUCTURE_REPORT.md`、`docs/dev/工业机器视觉数据平台-设计书-v1.6.md`（正文 v1.12，§4.5）、`docs/开始.md`（T3）、`docs/user/zh_cn/user_guide.md`

### 4. 行为、接口与兼容性影响

- **用户可观察**：搜索框支持 `tags::xxx`；未登录点击标签库会弹登录；右键标签或 `Ctrl+单击` 直接筛出使用该标签的图片。
- **接口**：`file_search` 新增 `tags` 字段；`image_summaries(tags=None)`；`TagLibraryWidget.tag_search_requested`；`LabelingWidget._search_tag_from_library()`。
- **数据/契约**：无 schema 变更；标签匹配精确、不区分大小写；DB `COLLATE NOCASE` 对非 ASCII 大小写的处理与 Python `.lower()` 略有差异。
- **版本**：fork.34 → fork.35。

### 5. 实际验证内容

- `tests/test_utils/test_file_search.py`：`tags::` 大小写/AND/NOT/缺失文件用例通过；`test_dataset_db/test_repository.py::test_image_summaries_sql_filters` 增加 `tags` 快路径断言并通过。
- `tests/test_widgets/test_tag_library_widget.py`：Ctrl+单击只发 `tag_search_requested`、不添加；`test_labeling/test_file_table.py`：未登录时标签库仍 enabled、点击调用 `_ensure_operator()`，以及 `_search_tag_from_library("defect")` 写入 `tags::defect`、逗号被转义。
- 本轮 `tests/test_labeling tests/test_widgets tests/test_dataset_db tests/test_config tests/test_utils/test_tag_library.py tests/test_utils/test_file_search.py`：**389 passed / 10 failed / 149 subtests**；失败集合与 HEAD 基线**完全相同**（本次运行时序抖动 `test_brightness_contrast_updates_are_throttled` 通过，故从 11 降到 10，未引入新失败）。
- `scripts/compile_languages.py`：四语言 `.qm` 各 **2285 条 / 0 unfinished**；新字符串四语言抽查通过。
- **未执行**：真实桌面右键菜单/`Ctrl+单击`/登录弹窗观感、真实大目录 `tags::` 搜索性能、非 ASCII 大小写标签的 DB/JSON 一致性、打包与全量回归。

### 6. 已知限制与后续事项

- `tags::` 为**精确标签名**匹配，不支持子串/通配符；需要子串时可用普通文件名/其它条件组合，后续可加 `tags~=` 之类语法。
- SQLite `COLLATE NOCASE` 只对 ASCII 大小写不敏感；含非 ASCII 大小写的标签在 DB 与 JSON 模式可能表现不同。
- 右键/Ctrl+单击会覆盖当前搜索框内容并重新加载列表；想保留原查询需先自行记录。
- 标签库仍只添加；查找结果通过文件表呈现，没有独立的“使用该标签的图片”对话框。
- `resources.py` 的生成/提交策略未改；若希望减少 diff，需要在“运行时优先加载文件系统 `.qm` + 发布前统一生成”之间做流程选择（本批仅解释）。

---

## 4.3.2+fork.34 — 2026-11-23

### 1. 背景与原因

用户反馈 2 项：

1. 运行时出现 `Skipping unexpected key in config: column_widths` 告警；
2. “图像属性 → 标志”为空，希望它显示当前文件列表里已经出现过的所有标签/标记（flags/tags），点击即可添加到当前图片；并明确：保留现有“图片标签”功能、只列尚未添加的标签、标签多时需搜索/折叠、点击后立即写盘并盖章归属、只负责添加（移除仍用标签上的 ×）。

第 1 项的根因是 `FileListController.on_column_resized()` 会把用户列宽写进 `file_list.column_widths`，但默认配置模板没有声明该键，且 `update_dict()` 把其中的列索引当成 schema 键逐项校验；第 2 项是 fork.31/32 删除“标志”展示后留下的空白区域。

### 2. 主要实现与关键细节

- **配置告警修复**：
  - `anylabeling/configs/xanylabeling_config.yaml` 的 `file_list` 增加 `column_widths: {}`。
  - `config.update_dict()` 增加 `_FREEFORM_CONFIG_KEYS = {"column_widths"}`：该映射的键是数据（列索引），整体深拷贝合并，不再逐键校验，因此启动时既不告警也不丢列宽。
- **标签库取代“标志”区**：
  - 新增 [TagLibraryWidget](../../anylabeling/views/labeling/widgets/tag_library.py)：标题“标签库 (N)”、搜索框、可滚动标签网格、收起/展开箭头；只显示当前图片尚未添加的标签；点击发 `tag_clicked`（用 `QTimer.singleShot(0)` 延后，避免在 `itemClicked` 中删除条目）。
  - 新增 Qt-free [TagCatalog](../../anylabeling/views/labeling/utils/tag_library.py)：JSON 模式按绝对路径缓存每个标注文件的 `tags`，`load()` 只读新增路径、删除消失路径，`update()/remove()` 支持保存/批量写后的增量维护。
  - `DatasetRepository.tag_counts(rel_paths=None)`：按 `image_tag` 统计活跃图片的标签用量；`rel_paths` 限定当前文件表行（900 个一批），`None` 表示整个数据集。
  - `LabelingWidget` 新增 `_refresh_tag_library()`/`_refresh_tag_library_if_visible()`/`_invalidate_tag_library()`/`_on_tags_persisted()`/`_on_batch_tags_persisted()`；`_on_tag_library_tag_clicked()` 先 `_ensure_operator()`，加 tag 后调用 `_save_file()` **立即保存**，保存路径经归属门禁写 `author`/`modified_at`；成功后标签从库中消失，失败显示“新标签保存失败”。
  - `FileSession._save_file()` 改为返回 `True/False`，供点击即写盘判断成功/失败；`AnnotationEditor.save_labels()` 成功后通知 `_on_tags_persisted()`；批量标签完成后通知 `_on_batch_tags_persisted(result.tags_by_path)`。
  - 工作区装配：`attributes_panel` 不再添加 `Flags` 标签与 `flag_widget`，改为 `TagLibraryWidget`；`flag_widget` 仍保留并 `hide()`（分类对话框、归属签名继续使用图片级 `flags`），旧 `flags` 数据不变但不再有独立复选框 UI。
  - `OperatorGate.apply()` 同步启用/禁用标签库；`RightSidebarTabs` 在切到“图像属性”页时刷新；导入/移除文件行、保存、批量标签都会失效/更新缓存。
- **翻译**：`LabelingWidget` 上下文新增 10 条（标签库标题、搜索、收起/展开、提示、计数、空状态、保存失败、添加成功）；重编 `.qm`、重建 `resources.py`。
- 版本：`4.3.2+fork.33` → `4.3.2+fork.34`。

### 3. 涉及模块与文件

- 修改：`anylabeling/config.py`、`anylabeling/configs/xanylabeling_config.yaml`、`anylabeling/services/dataset/repository.py`、`anylabeling/views/labeling/label_widget.py`、`annotation_editor.py`、`file_session.py`、`file_list/controller.py`、`operator/gate.py`、`right_sidebar.py`、`widgets/workspace.py`、`widgets/__init__.py`、`translations/*`、`resources.py`、`app_info.py`
- 新增：`anylabeling/views/labeling/utils/tag_library.py`、`anylabeling/views/labeling/widgets/tag_library.py`
- 测试：新增 `tests/test_utils/test_tag_library.py`（3）、`tests/test_widgets/test_tag_library_widget.py`（4）；`tests/test_dataset_db/test_repository.py` 增加 `tag_counts` 用例；`tests/test_config/test_normalization.py` 增加 `column_widths` 用例；`tests/test_labeling/test_file_table.py` 增加“点击标签立即写盘并盖章”用例
- 文档：本文件、`docs/dev/CODE_STRUCTURE_REPORT.md`、`docs/dev/工业机器视觉数据平台-设计书-v1.6.md`（正文 v1.11，§4.5）、`docs/dev/数据库设计-讨论稿.md`、`docs/开始.md`（T3）、`docs/user/zh_cn/user_guide.md`

### 4. 行为、接口与兼容性影响

- **用户可观察**：启动不再出现 `column_widths` 告警；“图像属性”页下方显示标签库，搜索/收起，点击标签立即保存并添加到当前图片，标签从库中消失；移除仍用上方 chips 的 ×。
- **接口**：新增 `TagCatalog`、`TagLibraryWidget`、`DatasetRepository.tag_counts(rel_paths=None)`；`FileSession._save_file()` 返回 bool；`update_dict()` 对 `column_widths` 整体合并。
- **数据/契约**：无 schema 变更；标签仍写 JSON `tags` 或 DB `image_tag`，立即保存按归属契约写 `author`/`modified_at`；图片级 `flags` 数据保留，但界面不再提供复选框编辑（分类对话框仍可维护）。
- **版本**：fork.33 → fork.34。

### 5. 实际验证内容

- `tests/test_utils/test_tag_library.py`：**3 passed**（计数/排序、增量 update/remove、缺失与坏文件）；`tests/test_widgets/test_tag_library_widget.py`：**4 passed**（只列未添加、搜索、点击延后发信号、折叠）。
- `tests/test_dataset_db/test_repository.py::test_tag_counts_exclude_soft_deleted_images`：通过（软删过滤 + `rel_paths` 限定）；`tests/test_config/test_normalization.py`：**5 passed**（默认配置声明 `column_widths`、动态键合并无告警）。
- `tests/test_labeling/test_file_table.py::test_tag_library_click_adds_tag_and_writes_attribution`：通过（点击后 JSON 立即写入 `tags`/`author`/`modified_at`，库中条目消失）。该用例把数据放在 `temporary/` 而非 pytest `tmp_path`，因为本机 DSH 沙箱下 `tmp_path` 的 owner-only DACL 会让 `LabelFile.save()` 的 `mkstemp` 失败（既有测试债）。
- 与 HEAD 导出树（`temporary/fork31/baseline`，HEAD `f31a952`）同环境对比 `tests/test_labeling tests/test_widgets tests/test_dataset_db tests/test_config tests/test_utils/test_tag_library.py`：当前 **361 passed / 11 failed / 53 subtests**，基线 **321 passed / 10 failed**；失败集合唯一差异仍是已记录的时序抖动 `test_brightness_contrast_updates_are_throttled`；本批新增 10 个用例全部通过。
- `scripts/compile_languages.py`：四语言 `.qm` 各 **2284 条 / 0 unfinished**，`resources.py` 重建；四语言抽查 10 个新字符串通过。
- `python -m py_compile` 修改与新增文件：通过。
- **未执行**：真实桌面标签库观感/点击/输入法、千图/万图 JSON 首次扫描耗时、真实 DB 7553 图 `tag_counts` 冒烟、隐藏图片级 flags UI 对分类工作流的真实回归、打包与全量回归。

### 6. 已知限制与后续事项

- 标签库只收集图片标签 `tags`，不把图片级 `flags` 的布尔值混入（两者是不同字段）；原“标志”复选框 UI 已隐藏，`flags` 仍按旧契约保存，分类对话框仍可维护。
- JSON 模式首次打开“图像属性”页会同步扫描当前文件表内所有标注文件（有缓存后仅增量）；万级目录首次可能卡顿约数秒，后续可改为后台线程。
- 标签库只负责添加；删除仍用图片标签 chips 的 ×，且删除后不会立刻重新扫描全局词表（下次失效/重扫时恢复）。
- 点击即保存会同时保存当前图片其它未保存的修改（与手动保存语义一致）；保存失败时标签已进入内存但会提示失败，用户可再次保存。
- `rel_paths` 限定按当前文件表行计算；DB 模式下列表若被搜索过滤，标签库也随可见行变化。
- 版本 fork.33 → fork.34。

---

## 4.3.2+fork.33 — 2026-11-23

### 1. 背景与原因

用户提出 3 项：

1. 文件表“对象”列数字前的圆圈是 `checked` 状态的遗留物，要求确认并去除；
2. “图像属性 → 标志”没有内容，希望展示已有 `tags` 供点击快速添加（用户明确要求先讨论，本批未改代码）；
3. 图一的对象编辑对话框需要命名（用户拟名“对象编辑”），并修复“只有一个类别时，点击下方类别名不会填入上方输入框、需要手动再输入”的问题。

第 1 项是 fork.30 移除 `checked::` 搜索后残留的视觉装饰；第 3 项的根因是类别列表只连接了 `currentItemChanged`，而单击已经是 current item 的项不会触发该信号（单类别列表天然如此）。

### 2. 主要实现与关键细节

- **去掉对象列审核圆点**：
  - `FileListController.build_row_cells()` 不再给“对象”列 `setIcon()`，`apply_row_state()` 只更新数量文本与排序键；`apply_row_state(row, checked, shape_count)` 改为 `apply_row_state(row, shape_count)`，`refresh_row()` 与 `StatusController._set_file_item_checked()` 同步。
  - 删除 `status_icons`、`create_file_status_icon()`、`FILE_CHECKED_COLOR`/`FILE_FAILED_COLOR`/`FILE_UNCHECKED_COLOR` 及 `file_list/__init__.py` 的导出；删除对应的圆点图标单测。
  - `checked` 数据契约不变：JSON 顶层 `checked`、文件表行内 checkState/UserRole、`Ctrl+Alt+U/K/J`、“检查状态”菜单与文件名 tooltip 仍保留，只是文件表不画圆点。
- **对象编辑对话框**：
  - `LabelDialog` 设置窗口标题 `Object Edit`（中/日/韩：对象编辑/オブジェクト編集/객체 편집）。
  - 新增 `label_clicked()` 并连接 `label_list.itemClicked`：被点击的类别项即使已经是 current item（单类别列表），也会填入“对象类别”输入框并交回焦点；`currentItemChanged` 继续处理键盘/编程选择。
- **第 2 项（标签库）**：本批只在回复中表述理解并列出待确认点，未改代码、未动 `flags` 契约。
- 版本：`4.3.2+fork.32` → `4.3.2+fork.33`。

### 3. 涉及模块与文件

- 修改：`anylabeling/views/labeling/file_list/controller.py`、`file_list/table.py`、`file_list/constants.py`、`file_list/__init__.py`、`anylabeling/views/labeling/status.py`、`anylabeling/views/labeling/widgets/label_dialog.py`、`anylabeling/resources/translations/*`、`anylabeling/resources/resources.py`、`anylabeling/app_info.py`
- 测试：新增 `tests/test_labeling/test_label_dialog.py`（2 条）；`tests/test_labeling/test_label_widget_metrics.py` 删除圆点用例；`test_file_table.py` 既有用例回归
- 文档：本文件、`docs/dev/CODE_STRUCTURE_REPORT.md`、`docs/dev/工业机器视觉数据平台-设计书-v1.6.md`（正文 v1.10，§4.5）、`docs/开始.md`（T3）、`docs/user/zh_cn/user_guide.md`

### 4. 行为、接口与兼容性影响

- **用户可观察**：文件表“对象”列只显示数字，不再有灰色/绿色/红色圆点；对象编辑对话框标题为“对象编辑”；单类别列表单击类别名即可填入输入框。
- **接口**：删除 `create_file_status_icon()`、三个 `FILE_*_COLOR` 常量、`FileListController.status_icons`；`apply_row_state()` 去掉 `checked` 参数；`LabelDialog` 新增 `label_clicked()` 与窗口标题。
- **数据/契约**：无 schema 变更；`checked` 字段与审核动作保持不变，旧 JSON 兼容。
- **版本**：fork.32 → fork.33。

### 5. 实际验证内容

- `tests/test_labeling/test_label_dialog.py`：**2 passed**（窗口标题；单类别单击 `itemClicked` 填充输入框）；`test_kie_linking.py` 7 passed；`test_file_table.py` 新增“对象列无状态图标”用例通过。
- `tests/test_labeling/test_file_table.py` + `test_label_widget_metrics.py`：**40 passed / 5 failed**；5 条失败与 HEAD 基线逐条相同（4 条文件表 DB 模式测试债、1 条 `SimpleNamespace` 桩缺方法）。
- 与 HEAD 导出树（`temporary/fork31/baseline`，HEAD `f31a952`）同环境对比 `tests/test_labeling tests/test_widgets tests/test_dataset_db`：当前 **347 passed / 11 failed / 53 subtests**，基线 **321 passed / 10 failed**；失败集合唯一差异仍是已记录的时序抖动 `test_brightness_contrast_updates_are_throttled`；新增 3 个用例通过、删除 1 个圆点用例。
- `scripts/compile_languages.py`：四语言 `.qm` 各 **2274 条 / 0 unfinished**，`resources.py` 重建；`Object Edit` 四语言抽查通过。
- **未执行**：真实桌面文件表观感（圆点是否完全消失）、真实鼠标单击单类别列表、输入法/高分屏、打包与全量回归。

### 6. 已知限制与后续事项

- 文件表不再显示审核状态；状态只能从画布左下角面板、右键“检查状态”、快捷键与文件名 tooltip 获取。若后续做 `asset.state` 图级审核 UI，应统一设计，不要恢复“对象列圆点”。
- “对象编辑”同时用于新建与编辑，标题不区分入口；若需区分，可按入口设置副标题/不同标题。
- 第 2 项（在“图像属性”页展示已有标签并点击添加）尚未实现，等待用户确认范围与交互（是否与 `flags` 分区、标签库范围、点击是添加还是切换等）。

---

## 4.3.2+fork.32 — 2026-11-23

### 1. 背景与原因

用户反馈 3 项问题：

1. 文件表右键菜单没有批量标签，无法给一批图片赋予相同的 `tags`；
2. 软件刚启动（无数据）时停留在“对象”“统计”等非“类别”标签页，随后导入图片/打开文件夹，切到“类别”页不会更新；
3. “统计”页的 `合计` 行、`合计` 列以及 `(合计, 合计)` 单元格无法点击筛选。

第 1 项是功能缺口；第 2 项是 fork.31 修复的遗漏——切页钩子仍用“tab page 就是面板控件”的同一性判断，而真实页是 `labels_panel` 容器，导致隐藏期间的脏标记在切页时没有被消费；第 3 项是统计表把合计行列硬编码为不可点击。

### 2. 主要实现与关键细节

- **批量图片标签**：
  - 文件表右键新增 `Set Tags…`（[controller.py](../../anylabeling/views/labeling/file_list/controller.py) 的 `set_tags_rows()`），对多选行生效；菜单项图标复用 `tag.svg`。
  - 新增 [BatchTagsDialog](../../anylabeling/views/labeling/file_list/tags_dialog.py)：逗号分隔输入 + “追加到现有标签 / 替换现有标签”两种模式；替换且输入为空时二次确认清空。
  - 新增 Qt-free 的 [batch_tags.py](../../anylabeling/views/labeling/utils/batch_tags.py)：`merge_image_tags()` 负责追加去重/替换；`apply_image_tags()` 走两条写入路径——DB 模式 `repository.find_image() → load_annotation() → save_annotation(editor, modified_at)`，JSON 模式 `read_file_meta() → write_tags()`；未变化的图片不重写、不重复盖章；返回 `updated/unchanged/failed` 与 `tags_by_path`。
  - [file_meta.py](../../anylabeling/views/labeling/utils/file_meta.py) 新增 `write_tags()`：保留其它键、原子替换、缺失时创建可加载的最小标注文件，并按归属契约写入 `author`/`modified_at`。
  - 图片标签属于内容修改，入口点击时通过 `host._ensure_operator()` 要求登录；当前打开的图片若在范围内，`other_data` 与“图像属性”页同步刷新；数量结果写入状态栏。
- **“类别”页切页刷新**：`RightSidebarTabs._on_right_tab_changed()` 改为“同一性 + 祖先链”判断（`page is label_manager_widget or page.isAncestorOf(...)`），与 `LabelManagerPanel._is_visible_page()` 保持一致；启动停在其他页→导入→切到“类别”页会走 `ensure_built()` 重建。
- **统计合计可点击**：`StatisticsFilter` 新增 `all_images` 字段；`filter_for_cell()` 新语义——合计行×划分列 → `split`，类别行×合计列 → `label`，无对象行×合计列 → `objectless`，合计行标签与右下角 → `all_images=True`；`RightSidebarTabs._on_statistics_filter_requested()` 收到 `all_images` 时清空搜索框并刷新列表；`Class`/`Total` 表头仍不可点击。
- **翻译**：`LabelingWidget` 上下文新增 11 条（菜单项、对话框标题/说明/占位符/模式、清空确认、三条状态提示），复用已有的 `OK`/`Cancel`；重编 `.qm`、重建 `resources.py`。
- 版本：`4.3.2+fork.31` → `4.3.2+fork.32`。

### 3. 涉及模块与文件

- 修改：`anylabeling/views/labeling/file_list/controller.py`、`anylabeling/views/labeling/right_sidebar.py`、`anylabeling/views/labeling/utils/file_meta.py`、`anylabeling/views/labeling/utils/dataset_statistics.py`、`anylabeling/views/labeling/widgets/statistics_table.py`、`anylabeling/resources/translations/*`、`anylabeling/resources/resources.py`、`anylabeling/app_info.py`
- 新增：`anylabeling/views/labeling/file_list/tags_dialog.py`、`anylabeling/views/labeling/utils/batch_tags.py`
- 测试：`tests/test_dataset_db/test_batch_tags.py`（新增 8 条）、`tests/test_labeling/test_file_table.py`（新增启动后切页刷新、批量标签写入选行/当前图片同步、统计合计清空/设置搜索 3 条）、`tests/test_utils/test_dataset_statistics.py`、`tests/test_widgets/test_statistics_table.py`（合计语义）
- 文档：本文件、`docs/dev/CODE_STRUCTURE_REPORT.md`、`docs/dev/工业机器视觉数据平台-设计书-v1.6.md`（正文 v1.9，§4.5 扩充）、`docs/开始.md`（T3）、`docs/user/zh_cn/user_guide.md`

### 4. 行为、接口与兼容性影响

- **用户可观察**：文件表右键可批量设置图片标签（追加/替换，空替换需确认）；启动停留在其他标签页、导入后切到“类别”页即为最新；统计页的合计行/合计列/右下角均可点击，右下角清空搜索。
- **接口**：新增 `FileListController.set_tags_rows()`、`BatchTagsDialog`、`merge_image_tags()`、`apply_image_tags()`、`file_meta.write_tags()`；`StatisticsFilter` 新增 `all_images`；`filter_for_cell()` 的返回语义变化（合计不再返回 `None`）。
- **数据/契约**：无 schema 变更；批量标签写 `image_tag` 或标注 JSON 的 `tags`，并按 fork.4 契约盖章 `author`/`modified_at`；JSON 模式对没有标注文件的图片会创建一个只含标签/作者的最小文件。
- **兼容性**：菜单项与对话框文案复用 `LabelingWidget` 翻译上下文；`Set Tags…` 不新增全局 `QAction`，因此不需要登记到 `OPERATOR_REQUIRED_ACTIONS`，但点击时必须调用 `_ensure_operator()`。
- **版本**：fork.31 → fork.32。

### 5. 实际验证内容

- `python -m pytest tests/test_dataset_db/test_batch_tags.py -q`：**8 passed**（追加/替换/清空、盖章、未变化不重写、缺失文件建档、坏 JSON 失败、DB 未知图失败、DB 合并与 `editor`/`modified_at`）。
- `python -m pytest tests/test_utils/test_dataset_statistics.py tests/test_widgets/test_statistics_table.py -q`：**39 passed**（合计行/列/右下角语义与点击载荷）。
- `python -m pytest tests/test_labeling/test_file_table.py -q`：**30 passed / 4 failed**；4 条失败与 HEAD 基线逐条相同（文件表 DB 模式测试债）；新增的“启动后切到类别页会重建”“批量标签写入选行并同步当前图片”“统计合计清空/设置搜索”“批量标签对话框解析”均通过。
- `python -m pytest tests/test_utils/test_file_meta.py tests/test_labeling/test_image_tags.py tests/test_labeling/test_operator_gate.py tests/test_dataset_db -q`：**73 passed**。
- 与 HEAD 导出树（`temporary/fork31/baseline`，HEAD `f31a952`）同环境对比 `tests/test_labeling tests/test_widgets tests/test_dataset_db`：当前树 **345 passed / 11 failed / 53 subtests passed**，基线 **321 passed / 10 failed / 53 subtests passed**；失败集合唯一差异仍是已记录的时序抖动 `test_brightness_contrast_updates_are_throttled`，其余 10 条（4 条文件表 DB 模式测试债、3 条 `SimpleNamespace` 桩缺方法、1 条上传属性、2 条 subtest）与基线逐条相同；fork.31+fork.32 新增的 24 个用例全部通过。
- `python -m py_compile` 修改与新增文件：通过。
- `scripts/compile_languages.py`：四语言 `.qm` 各 **2273 条 / 0 unfinished**，`resources.py` 重建；从 `.qm` 加载并抽查 11 个新字符串，四语言均返回预期译文。
- **未执行**：真实桌面右键/弹窗/输入法观感、大批量（上千图）标签写入耗时、真实数据库 + 真实图片的批量标签冒烟、打包与全量回归。

### 6. 已知限制与后续事项

- DB 模式批量标签对每张图调用一次 `save_annotation()`（独立事务），会重写该图对象/关系行；上千图批量写会较慢，后续可合并为单事务批量接口。
- 批量写入读取的是已保存内容：当前图片未保存的形状不会被并入批量写；标签变化后当前图片只同步标签，不改变其脏标记。
- 批量标签只支持“追加”和“整组替换”，不支持在一次操作中按标签增删；需要精细修改时仍用“图像属性”页。
- 文件表不再有 `标签` 列，批量结果只能通过状态栏数量、当前图片的“图像属性”页或搜索/筛选确认。
- “统计”页右下角会清空用户手动输入的搜索条件（这是“显示全部图片”的语义）；`Class`/`Total` 表头仍不可点击。

---

## 4.3.2+fork.31 — 2026-11-22

### 1. 背景与原因

用户提出 5 项界面/交互问题：

1. “编辑图片标签”按钮所在功能已并入右侧“图像属性”页，标题栏中最小化按钮旁的该按钮应删除；
2. 标题栏右键菜单里的“全屏”应移到标题栏，且进入/退出全屏共用一个按钮；
3. 文件列表不需要“标签”列；
4. 无论登录与否，导入图片或新增/删除/修改类别后，右侧“类别”页都不会实时更新，只有点击 `工具 → 标签管理器` 才刷新；
5. 按文档约定（讨论稿 D7/D18），类别顺序必须可调整，且该顺序是导出类别编号的权威。

前 4 项属于重复入口、信息不完整和隐藏刷新时机的问题；第 5 项落地讨论稿已确认但尚未实现的 `category.sort_index` 排序 UI。

### 2. 主要实现与关键细节

- **标题栏去掉图片标签按钮**：`workspace.build_instruction_bar()` 不再创建 `image_tags_toggle_button`，`window_control_buttons` 只保留右侧栏开关；图片标签入口仍是 `视图 → 图片标签` 与 `Ctrl+Shift+T`。
- **全屏改为标题栏单按钮**：`MainWindow._install_fullscreen_button()` 用 `FramelessWindow.fullscreen_action`（`F11`/视图菜单共用同一个可勾选 `QAction`）作为标题栏 `QToolButton` 的默认动作；`_sync_fullscreen_button()` 在 `fullscreen_changed` 时切换图标（`expand-view`/`restore-view`）、`全屏/退出全屏` 文案与 tooltip。`TitleBar.build_context_menu()` 删除全屏项；原生窗口模式没有自绘标题栏，按钮回退到工具条。
- **文件表改回五列**：`file_list/constants.py` 删除 `FILE_COL_TAGS`（`FILE_COLUMN_COUNT` 6 → 5）；`FileListController` 删除标签列构建与 `set_row_tags()`/`_apply_tags_item()`/`build_tags_item()`/`tags_text()`，表头右键与 `show_tags` 配置项同步删除；`LabelingWidget._on_image_tags_changed()` 与 `AutoLabelingHandoff` 不再写文件表；默认配置删除 `file_list.show_tags`。
- **“类别”页实时刷新**：`LabelManagerPanel.invalidate()` 置脏后，若“类别”页是当前页则启动 120ms 单次定时器合并重建（`_refresh_if_visible()`/`flush_refresh()`），页面隐藏时只置脏、切页时仍由 `ensure_built()` 重建；页面判断改为祖先链（真实布局中面板位于 `labels_panel` 容器内，不是 `QTabWidget` 的直接页面）。重建保留用户已选的 `From`/`To` 范围与当前类别，并在表格单元格编辑中延后重建，避免丢掉正在输入的改名。
- **新增失效点**：`AnnotationEditor.add_label()`（新类别）、`remove_labels()`（对象删空即隐藏类别）、JSON/DB 两条保存路径；`ObjectEditor.edit_label()`/`batch_edit_labels()`；`ShapeCommands.undo_shape_edit()`；`SpecialWorkspaces.shape_manager()`；`utils.upload` 的类别上传与标注上传后刷新；文件表原有增删/排序/清空仍走 `FileListController.invalidate_label_manager()`。
- **类别顺序可调整**：`DatasetRepository.category_counts()` 改为 `ORDER BY c.sort_index, c.name`；新增 `set_category_order(names)`——把可见类别的目标顺序放入全量类别的原有槽位后逐行更新 `sort_index`，未知/重复名返回 `False` 且不写库。`LabelManagerPanel` 底部新增 `↑`/`↓` 按钮与 `move_selected_category()`，仅在编辑态且存在 `dataset_repository` 时可用；无对象类别（`object_count == 0`）不再列出，与 JSON 模式“由剩余对象推导类别集合”的口径一致。
- **翻译**：四语言新增 `Move Up`/`Move Down`/`Category order is stored in the dataset database`/`An error occurred while reordering the categories.`/`Full Screen`/`Exit Full Screen`，删除 `TitleBar` 上下文中已不再使用的全屏两条；重编 `.qm`、重建 `resources.py`。
- 版本：`4.3.2+fork.30` → `4.3.2+fork.31`。

### 3. 涉及模块与文件

- 修改：`anylabeling/views/mainwindow.py`、`anylabeling/widgets/frameless/title_bar.py`、`anylabeling/views/labeling/widgets/workspace.py`、`anylabeling/views/labeling/widgets/label_manager.py`、`anylabeling/views/labeling/file_list/{constants,controller,table,__init__}.py`、`anylabeling/views/labeling/{annotation_editor,object_editor,shape_commands,special_workspaces,label_widget,auto_labeling_handoff}.py`、`anylabeling/views/labeling/utils/upload.py`、`anylabeling/services/dataset/repository.py`、`anylabeling/configs/xanylabeling_config.yaml`、`anylabeling/resources/translations/*`、`anylabeling/resources/resources.py`、`anylabeling/app_info.py`
- 测试：`tests/test_labeling/test_label_manager.py`（实时刷新、祖先链可见性、范围保留、DB 顺序、上移/下移、无 DB 禁用、无对象类别过滤）、`tests/test_labeling/test_file_table.py`（五列表头、无标签列、标题栏无图片标签按钮、全屏单按钮与右键菜单移除、可见“类别”页自动刷新）、`tests/test_labeling/test_image_tags.py`（不再写文件表）、`tests/test_dataset_db/test_repository.py`（`sort_index` 顺序与 `set_category_order()` 拒绝非法输入）
- 文档：本文件、`docs/dev/CODE_STRUCTURE_REPORT.md`、`docs/dev/工业机器视觉数据平台-设计书-v1.6.md`（正文 v1.8，新增 §4.5）、`docs/dev/数据库设计-讨论稿.md`（D18 落地说明与代码基线）、`docs/开始.md`（T3 状态）、`docs/user/zh_cn/user_guide.md`

### 4. 行为、接口与兼容性影响

- **用户可观察**：标题栏不再有图片标签按钮；全屏由标题栏单按钮/`F11`/视图菜单三者共用，按钮提示随状态切换，右键菜单不再有全屏；文件表为五列，图片标签只在“图像属性”页；导入图片、增删改对象/类别、保存后“类别”页自动更新且保留文件范围；类别可上移/下移，顺序写入数据集数据库并成为后续导出顺序。
- **接口**：新增 `DatasetRepository.set_category_order(names)`；`category_counts()` 的顺序由名称改为 `sort_index`；`LabelManagerPanel` 新增 `flush_refresh()`、`move_selected_category()`、`_is_visible_page()`、`_selected_category()`、`_select_category()`、`_update_reorder_buttons()` 及 `move_up_button`/`move_down_button`；删除 `FileListController.set_row_tags()`/`_apply_tags_item()`/`build_tags_item()`/`tags_text()`。
- **配置**：默认 YAML 删除 `file_list.show_tags`；旧用户配置中的该键不再被读取，也不再写回（未知键按既有策略保留）。
- **数据/契约**：无 schema 变更；类别顺序写入既有 `category.sort_index`。同一数据集内类别 `sort_index` 相同时仍按名称排序（旧库/外部写入的兜底），本批的上移/下移会把全量顺序规范化为 0..n-1。
- **兼容性**：纯 JSON 目录没有类别顺序权威，`↑`/`↓` 按钮禁用并说明原因；DB 模式下列表不显示无对象类别（对象被删空后即消失），类别行本身仍保留在库中，后续 `in_class_list`“隐藏类别”能力再区分。
- **版本**：fork.30 → fork.31。

### 5. 实际验证内容

- `python -m pytest tests/test_dataset_db -q`：**20 passed**（新增 `sort_index` 顺序与 `set_category_order()` 用例）。
- `python -m pytest tests/test_label_manager.py -q`：**20 passed**（新增实时刷新/可见性/范围保留/DB 顺序/上移下移/无 DB 禁用/无对象过滤 8 条）。
- `python -m pytest tests/test_file_table.py tests/test_label_manager.py tests/test_image_tags.py tests/test_dataset_db -q`：**82 passed / 4 failed**；4 条失败均为 HEAD 基线同样存在的文件表 DB 模式测试债（`test_file_paths_survive_annotation_status_roles`、`test_import_time_is_persisted_in_sidecar`、`test_split_action_writes_json_and_preserves_existing_keys`、`test_batch_split_applies_to_all_selected_rows`），`test_file_table.py` 新增的五列、标题栏、全屏单按钮与“类别页自动刷新”用例全部通过。
- 与 HEAD 导出树（`temporary/fork31/baseline`，HEAD = `f31a952`）在同一 shim/环境对比 `tests/test_labeling tests/test_widgets tests/test_dataset_db`：当前树 **331 passed / 11 failed / 53 subtests passed**，基线 **321 passed / 10 failed / 53 subtests passed**；失败集合差异只有已记录的时序抖动 `test_brightness_contrast_updates_are_throttled`，其余 10 条失败（4 条文件表 DB 模式测试债、3 条 `SimpleNamespace` 桩缺方法、1 条上传属性、2 条 subtest）在基线逐条相同。新增 12 个用例均通过。
- `python -m py_compile` 修改的 Python 文件：通过。
- `scripts/compile_languages.py`：四语言 `.qm` 各 **2262 条 / 0 unfinished**，`resources.py` 重建（`resources.py` 行尾已归一为 LF）；从 `.qm` 加载并逐条抽查 7 个新字符串，四语言均返回预期译文。
- **未执行**：真实桌面点击标题栏/全屏/类别上移下移的观感、真实 7553 图数据集的实时刷新耗时、JSON 模式大目录的类别页重建耗时、打包与全量回归。

### 6. 已知限制与后续事项

- JSON 模式（无数据集数据库）没有类别顺序权威，`↑`/`↓` 禁用；纯 JSON 目录的类别页重建仍会扫描文件列表内全部 JSON，大目录首次切页或新增类别可能卡顿（DB 模式走 `category_counts()`，不受此影响）。
- “类别”页实时刷新是 120ms 合并 + 可见时才重建；隐藏时只置脏，切页重建。单元格正在编辑时会延后重建，不会丢失输入，但编辑期间的类别变化要等编辑结束后才显示。
- DB 模式列出的类别按“有活动对象”过滤；被删空对象的类别行保留在库中（`is_deleted=0`），`in_class_list`“隐藏类别”与 classes.txt 种子仍是 P3b，不在本批。
- DB 模式以库为权威：关闭自动保存时，新画的类别要等保存后才出现在“类别”页；JSON 模式因合并会话登记表可提前显示，两种模式的时机差异属于实现细节。
- 标题栏全屏按钮图标在启动时按当时主题生成，运行中切换主题不会重绘（与既有侧栏开关行为一致）。
- 类别页批量改名/删除仍直接改写标注 JSON（JSON 模式）且不写 `author`/`modified_at`，与 fork.4 归属契约的缺口未在本批处理。

---

## 4.3.2+fork.30 — 2026-11-21

### 1. 背景与原因

用户要求：①把缩略图懒加载记录到设计书；②把“数万行 model/view 虚拟化”记录到设计书；③既然 DB/软件不再把 `checked` 当审核状态，正则/搜索也不应保留 `checked::`；④解释“逐图 `load_annotation` + SearchQuery”回退，并确认文件名能否用 SQL。

### 2. 主要实现与关键细节

- **设计书 v1.7（正文）**新增 §4.4“文件表、搜索与统计的性能约束”：记录 DB 为权威、缩略图视口懒加载、7553 图实测、数万行必须迁移 model/view 虚拟化、搜索 DSL 下推 SQL、统计反筛不自动打开图片、真实万图验收口径；§3.2 明确图片级 `checked` 已移除。
- **《开始》新增第 10 条**：用户可见功能/交互/性能约束及已确认演进需求必须写入设计书，结构报告只记实现，CHANGELOG 记变更；设计书正文版本递增但文件名可保留历史链接。
- **移除 `checked::`**：从 `file_search.py` 的字段集合、`_LabelData.checked`、`_matches_checked`、解析器/求值器、搜索帮助文案中删除；旧 `checked::x` 不再表达审核状态（按未知条件回退为文件名文本）。搜索测试同步删除 checked 用例。
- **文件名 SQL 快路径**：`_simple_database_filters()` 接受普通文件名子串；`image_summaries(filename=...)` 用 `instr(f.file_name, ?)` 过滤。复杂正则/布尔仍回退。
- 版本：`4.3.2+fork.29` → `4.3.2+fork.30`。

### 3. 涉及模块与文件

- 修改：`docs/dev/工业机器视觉数据平台-设计书-v1.6.md`（正文 v1.7）、`docs/开始.md`、`anylabeling/views/labeling/utils/file_search.py`、`label_widget.py`、`file_session.py`、`anylabeling/services/dataset/repository.py`、`app_info.py`、翻译资源
- 测试：`tests/test_utils/test_file_search.py`（删除 checked 用例）、`tests/test_dataset_db/test_repository.py`/`test_ui_adapter.py`（文件名 SQL 过滤）

### 4. 行为、接口与兼容性影响

- **用户可观察**：搜索帮助不再宣传 `checked::`；`checked::x` 不再返回“已审核/未审核”结果；普通文件名搜索走 SQL。DB 模式搜索更快。
- **数据契约**：DB schema 不变；旧 JSON `checked` 仍可被 `LabelFile` 兼容读取/写出，但不再作为审核事实、不参与 DB 搜索；文件表勾选/审核动作仍是 P4 清理项。
- **接口**：`image_summaries(filename=...)`、`_simple_database_filters` 返回四元组。
- **版本**：fork.29 → fork.30。

### 5. 实际验证内容

- `python -m pytest tests/test_dataset_db -q`：**19 passed**（含文件名 SQL 过滤、`label::bolt,split::train` 快路径）。
- `python -m py_compile` 修改的 `file_search.py`/`file_session.py`/`repository.py`/测试：通过。
- `scripts/compile_languages.py`：四语言 `.qm` 各 **2258 条 / 0 unfinished**。
- **未执行**：`tests/test_utils/test_file_search.py` 全量（本机 tempfile/DACL 限制）、真实 UI 搜索观感、打包与全量回归。

### 6. 已知限制与后续事项

- 文件表/审核动作/JSON 的 `checked` 兼容仍在；P4 删除 JSON 链路时一并清理，当前只保证 DB/搜索不再使用它。
- 普通文件名 SQL 只做 `instr(file_name, ?)`，大小写/路径目录语义与旧“绝对路径子串”略有差异；复杂正则仍回退。
- 数万行虚拟化是设计书 v1.7 记录的演进要求，**本批未实现**；当前仍是 `QTableWidget`。
- 设计书文件名仍为 `-v1.6.md` 以保持历史链接，正文版本为 v1.7，已在文件头说明。

---

## 4.3.2+fork.29 — 2026-11-21

### 1. 背景与原因

用户用 7553 图的 DGLF 数据集反馈：二次打开文件表约 4s；统计页筛选卡顿；并建议搜索栏字段最终应转成数据库查询，而不是继续逐图读数据。

实测（7553 图 DB、离屏 `MainWindow`，不含真实图片解码）：

| 路径 | 优化前 | 优化后 |
|---|---|---|
| `image_summaries()` | 0.07s | 0.07s |
| 文件表 7553 行（缩略图开启） | 约 7.8s | **约 0.84s** |
| `statistics_rows()` / 刷新统计 | 0.09–0.16s | 0.09–0.16s |
| `label::` 搜索（逐图 `load_annotation`） | 约 1.16s | **约 0.53s**（SQL 快路径，且不再自动加载第一张图） |

根因：
- `append_db_row()` 为每一行立即调用 `request_thumbnail()`，7553 行一次排队 7553 个缩略图任务，拖慢首屏；
- DB 搜索虽然读库，但对 `label::`/`split::`/`shape::0` 仍是“每图一次 `load_annotation()` + Python 求值”，统计页点击反筛也走这条慢路径；
- DB 搜索后还自动加载第一张图，大 TIFF 解码会放大卡顿。

### 2. 主要实现与关键细节

- **缩略图懒加载**：`append_row()`/`append_db_row()` 不再逐行请求缩略图；新增 `request_visible_thumbnails()`，只请求视口附近行，滚动/排序/切换缩略图时再补。`ThumbnailLoader` 不再被 7000+ 任务淹没。
- **搜索 SQL 快路径**：`DatasetRepository.image_summaries(labels=..., split=..., objectless=...)` 用 `EXISTS`/`NOT EXISTS` + 索引过滤；`FileSession._simple_database_filters()` 把 `label::x`、`split::train`、`shape::0` 及逗号 AND 组合编译为 SQL。
- **保留完整语法回退**：布尔分组、属性、描述、正则、文件名、`checked::` 等复杂条件仍走现有 `SearchQuery` + 逐图求值，避免语义分叉。
- **筛选不自动打开图片**：DB 搜索 `load=False, select_first=False`，只刷新文件表；用户点击行再加载，避免大图解码拖慢统计反筛。
- **版本**：`4.3.2+fork.28` → `4.3.2+fork.29`。

### 3. 涉及模块与文件

- 修改：`anylabeling/services/dataset/repository.py`、`anylabeling/views/labeling/file_list/controller.py`、`file_session.py`、`label_widget.py`、`app_info.py`
- 测试：`tests/test_dataset_db/test_repository.py`（SQL 过滤）、`test_ui_adapter.py`（`label::bolt,split::train` 快路径）
- 文档：本文件、`docs/dev/CODE_STRUCTURE_REPORT.md`、`docs/开始.md`、`docs/dev/数据库设计-讨论稿.md`（代码基线）

### 4. 行为、接口与兼容性影响

- **用户可观察**：7553 图文件表首屏由约 4–8s 降到约 1s 量级；缩略图只加载可见行，滚动时补；统计页点击 `label::`/`split::`/`shape::0` 反筛约 0.5s，且不再自动打开第一张图。
- **接口**：新增 `image_summaries(labels=,split=,objectless=)`、`request_visible_thumbnails()`、`_simple_database_filters()`；`import_image_folder()` 增加 `select_first` 参数。
- **语义**：简单字段 SQL 与 JSON `SearchQuery` 保持 AND/精确标签语义；复杂查询回退，不改变结果含义。
- **版本**：fork.28 → fork.29。

### 5. 实际验证内容

- `python -m pytest tests/test_dataset_db -q`：**19 passed**（新增 SQL 过滤用例；搜索适配器覆盖 `label::bolt,split::train`）。
- 7553 图 DB 性能冒烟（`temporary/perf/`，无真实图片解码）：
  - `image_summaries` 0.07s；
  - 文件表 7553 行：缩略图全量请求约 7.8s → 懒加载约 **0.84s**；
  - 统计刷新 0.16s；
  - `label::` 搜索约 **0.53s**（原 1.16s），筛选后 `filename=None`，不自动加载图片。
- `python -m compileall` 修改模块通过。
- **未执行**：真实桌面滚动/缩略图观感、7553 张 TIFF 的实际解码耗时、复杂查询回退性能、打包与全量回归。

### 6. 已知限制与后续事项

- 文件表仍是 `QTableWidget`，7553 行的构建约 0.8s；更大规模（数万）应改为 model/view 虚拟化。
- SQL 快路径只覆盖 `label::`/`split::`/`shape::0` 的逗号 AND；属性、描述、正则、文件名、复杂布尔仍逐图求值，后续可继续下推。
- 统计筛选后文件表仍要重建匹配行（3509 行约 0.4s），这是目前 0.5s 的主要成本；可进一步做结果集缓存/增量。
- 缩略图懒加载后，快速滚动到底部时可能需要短暂等待缩略图。

---

## 4.3.2+fork.28 — 2026-11-21

### 1. 背景与原因

用户核对 DGLF 数据集后确认 `image_file` 实为 7553 条；随后提出：`rel_path`/`file_name` 内容相同、DB 模式仍会出现 `.xanylabeling_import_time.json`、关闭应用/浏览器后 `xanylabeling.db-wal`/`-shm` 仍存在。

- `rel_path` 的语义是“相对数据集根”，不是绝对路径；当根目录就是图片目录时，`rel_path == file_name` 是预期结果（`dataset.root_path` + `rel_path` 才是定位信息）。
- `.xanylabeling_import_time.json` 是 JSON 模式 sidecar；DB 模式下 `image_file.imported_at` 才是权威，但旧文件不会自动清理。
- 应用退出路径没有关闭 `DatasetDatabase`，SQLite 未执行 checkpoint/close，导致 `-wal`/`-shm` 残留。

### 2. 主要实现与关键细节

- `LabelingWidget.closeEvent()` 在窗口正常关闭时调用 `FileSession._close_dataset()`；`DatasetDatabase.close()` 先 `PRAGMA wal_checkpoint(TRUNCATE)` 再 close，正常退出后 WAL/SHM 由 SQLite 清理。
- `_open_dataset_for_folder()` 在打开 DB 时删除数据集根下遗留的 `.xanylabeling_import_time.json`（DB 模式不再读取它；删除失败只记 warning）。
- 不改变 `rel_path` 语义，也不把绝对路径写进 DB；绝对路径由“打开目录 + rel_path”在运行时还原，保持项目目录可移动/可复制。
- 版本：`4.3.2+fork.27` → `4.3.2+fork.28`。

### 3. 涉及模块与文件

- 修改：`anylabeling/views/labeling/file_session.py`、`label_widget.py`、`app_info.py`
- 文档：本文件、`docs/dev/CODE_STRUCTURE_REPORT.md`、`docs/开始.md`、`docs/dev/数据库设计-讨论稿.md`（代码基线）

### 4. 行为、接口与兼容性影响

- **用户可观察**：正常关闭窗口后 `-wal`/`-shm` 消失；DB 模式打开目录会清掉根下旧 `.xanylabeling_import_time.json`；DB 仍以 `rel_path`（相对根）+ `file_name` 存储。
- **接口**：`FileSession._close_dataset()` 现在也被窗口关闭调用（原只在切换目录时调用）；无新增公共 API。
- **兼容性**：`rel_path`/`file_name` 语义不变；已有库不受影响；若其他进程（SQLite 浏览器）仍持有连接，WAL/SHM 可能继续存在，这是 SQLite 正常行为。
- **版本**：fork.27 → fork.28（缺陷修复）。

### 5. 实际验证内容

- `python -m pytest tests/test_dataset_db -q`：**18 passed**。
- 离屏 `MainWindow` 冒烟（`temporary/diag/smoke_close.py`）：
  - 目录根为数据集根，图片在 `images/` 下；建库后 `rel_path='images/a.png'`、`file_name='a.png'`（验证两者不同）；
  - 根下预置 `.xanylabeling_import_time.json`，打开 DB 后被删除；
  - 正常 `window.close()` 后 `-wal`、`-shm` 均不存在；`view.dataset_repository is None`；
  - 结果：`close smoke ok`。
- `python -m compileall` 修改模块通过。
- **未执行**：真实桌面关闭、SQLite 浏览器同时打开、异常退出/断电恢复、打包与全量回归。

### 6. 已知限制与后续事项

- 如果关闭应用时仍有 SQLite 浏览器/其他进程持有连接，`-wal`/`-shm` 仍会存在；需关闭所有连接后再检查。
- 异常退出/强杀不会走 `closeEvent`，WAL 可能保留（SQLite 下次打开会自动恢复）；不要手动删除运行中的 WAL。
- `rel_path` 不存绝对路径是设计选择，便于整目录移动/复制；绝对路径由运行时 `dataset_root + rel_path` 还原。
- 若希望一个项目只建一个 DB，需要 T5 的 `.xalp` 项目文件/根目录识别；当前“打开哪个目录就在哪个目录建库”。

---

## 4.3.2+fork.27 — 2026-11-21

### 1. 背景与原因

用户反馈两点：①按约定每个项目/目录应生成替代 JSON 的 `xanylabeling.db`，但实际没有，数据仍在 JSON；②打开过的项目二次打开时文件表仍很慢，似乎没有读数据库。

根因确认：fork.24–fork.26 的 DB 模式只在“目录里已经存在 `xanylabeling.db`”时生效；普通“打开目录”仍只扫描 JSON，自动建库/导入从未实现。用户只有手动走 P3a 的 `Import Project…` 才会生成库，所以数据留在 JSON，二次打开也继续走 JSON 扫描。

### 2. 主要实现与关键细节

- `FileSession._ensure_dataset_for_folder()`：打开目录且无 `xanylabeling.db`、目录内有图片时，自动调用 P0 `import_xlabel_folder()` 建库并导入 X-AnyLabeling JSON；来源 JSON 只读、不移动/不删除。
- `import_image_folder(..., auto_db=True)` 在无库且非搜索请求时先自动建库；建库成功后立即打开 DB。失败时提示并回退 JSON，不阻塞用户。
- 过滤 `.trash/`、`_delete_/`，避免把回收站/旧删除目录重新导入。
- 状态栏显示“正在创建 / 已创建”及库路径；有文件错误时显示错误数。
- 二次打开：`_open_dataset_for_folder()` 检测到库后直接走 P1/P2 的 DB 文件表/搜索/统计，不再扫描 JSON。
- 版本：`4.3.2+fork.26` → `4.3.2+fork.27`（缺陷修复）。

### 3. 涉及模块与文件

- 修改：`anylabeling/views/labeling/file_session.py`、`label_widget.py`、`anylabeling/services/dataset/importer.py`（`_delete_` 跳过）、`app_info.py`
- 翻译：四语言新增 5 条（建库状态/错误），`.qm` 各 **2258 条 / 0 unfinished**
- 文档：本文件、`docs/dev/CODE_STRUCTURE_REPORT.md`、`docs/开始.md`、`docs/dev/数据库设计-讨论稿.md`（代码基线）

### 4. 行为、接口与兼容性影响

- **用户可观察**：首次打开含图片的普通目录会生成 `<目录>/xanylabeling.db`，文件表/单图/搜索/统计走 DB；二次打开直接读库。来源 JSON 保留原位，不再作为运行期权威。
- **接口**：`import_image_folder()` 增加 `auto_db=True` 参数；`LabelingWidget.import_image_folder()` 透传；内部 JSON 删除路径使用 `auto_db=False`。
- **兼容性**：无图片目录不建库、仍回退 JSON；建库失败提示后可继续 JSON；已有库不重复导入。
- **版本**：fork.26 → fork.27。

### 5. 实际验证内容

- `python -m pytest tests/test_dataset_db -q`：**18 passed**。
- 离屏 `MainWindow` 冒烟（`temporary/diag/smoke_auto_db.py`）：
  - 目录只有图片 + JSON，首次 `import_image_folder()` 后生成 `xanylabeling.db`，文件表 2 行、`dataset_repository` 非空、加载 `bolt`；耗时约 **0.09s**；
  - 删除源 JSON 后二次打开，仍从 DB 显示 2 行并加载 `bolt`；耗时约 **0.03s**；
  - 结果：`auto db smoke ok`。
- `python -m compileall` 修改模块通过；四语言 `.qm` 各 2258 条 / 0 unfinished。
- **未执行**：真实桌面目录选择/大目录导入进度、同步/导出/训练、打包、全量回归。

### 6. 已知限制与后续事项

- 首次建库是同步导入，超大目录会阻塞 UI；P3b 需要进度条/分批事务。
- 自动建库目前只解析 X-AnyLabeling 同名 JSON；COCO/YOLO/VOC/LabelMe/LabelImg 的标注不会被迁移，P3b 多格式导入补。
- 若目录已有其他格式标注且用户不希望空库，仍需 P3b 的导入向导选择；当前会建“只有图片、无对象”的库。
- 打开单张 recent 文件（而非目录）不会触发目录建库；需先打开所在目录。

---

## 4.3.2+fork.26 — 2026-11-21

### 1. 背景与原因

P0–P2 已让 DB 目录可打开、可读写、可搜索/统计/改类别，但用户仍没有创建数据库的 UI 入口，也没有删除/恢复。P3 计划包含导入、回收站、同步、导出/训练；本批先落 **P3a：导入项目 + 回收站**，让 DB 模式可被普通用户进入和清理；同步/导出/训练留在 P3b。

### 2. 主要实现与关键细节

- **导入项目**：`文件 → Import Project (X-AnyLabeling)…` 选择目录，调用 P0 `import_xlabel_folder()`；目录已有库时弹“跳过已存在 / 替换已存在 / 取消”，替换前自动 `VACUUM INTO` 备份；完成后显示图片/标注/对象/跳过/错误统计并直接打开数据集。
- **回收站**：DB 模式删除图片或标注统一为“图片与标注同进退”——图片移到 `<dataset>/.trash/<image_id>/`，DB 行 `is_deleted=1`、`deleted_at`；原来源 JSON 不移动。`TrashDialog` 列出回收站，可恢复（移回 `rel_path` 并清 `deleted_at`）、永久删除、清空；恢复前检查原路径冲突。
- **动作入口**：File 菜单新增“Import Project (X-AnyLabeling)…”与“Recycle Bin…”；无库时回收站提示仅数据集模式可用。
- **翻译**：四语言新增 34 条（导入/回收站），重编 `.qm`（各 **2253 条 / 0 unfinished**）并重建 `resources.py`。
- **版本**：`4.3.2+fork.25` → `4.3.2+fork.26`。

### 3. 涉及模块与文件

- 修改：`anylabeling/views/labeling/actions/builder.py`、`actions/menus.py`、`file_session.py`、`label_widget.py`、`app_info.py`
- 新增：`anylabeling/views/labeling/widgets/trash_dialog.py`
- 翻译资源：`anylabeling/resources/translations/{en_US,zh_CN,ja_JP,ko_KR}.{ts,qm}`、`anylabeling/resources/resources.py`
- 文档：本文件、`docs/dev/CODE_STRUCTURE_REPORT.md`、`docs/开始.md`、`docs/dev/数据库设计-讨论稿.md`（代码基线）

### 4. 行为、接口与兼容性影响

- **用户可观察**：无库目录可通过菜单导入为 DB 项目；DB 模式可删除到回收站、恢复/永久删除/清空；JSON 模式仍走原 `_delete_` 目录逻辑。
- **内部接口**：新增 `FileSession.import_project_dialog()/show_trash_dialog()/_trash_current_image()`、`TrashDialog`、`LabelingWidget.import_project_dialog()/show_trash_dialog()`、`actions.import_project/show_trash`。
- **数据契约**：DB schema 不变；回收站文件布局按 D19（`.trash/<image_id>/`）；来源 JSON 不删。
- **版本**：`4.3.2+fork.25` → `4.3.2+fork.26`（用户可观察行为变化）。

### 5. 实际验证内容

- `python -m pytest tests/test_dataset_db -q`：**18 passed**（P3 复用 P0 回收站 repository 用例）。
- 离屏 `MainWindow` 冒烟（`temporary/p3/smoke_p3.py`）：打开 1 图 DB → `FileSession._trash_current_image()` 后 DB 行不可见、图片在 `.trash/1/a.png`、来源 `a.json` 仍在；`TrashDialog` 显示 1 行，`_restore()` 后 DB 行恢复、图片回原路径、`.trash` 文件消失；结果 `p3 smoke ok`。
- `python -m compileall` 修改模块通过；四语言 `.qm` 各 2253 条 / 0 unfinished。
- **未执行**：真实桌面菜单/文件选择/确认框、导入冲突逐项选择、同步/导出/训练、打包、全量回归。

### 6. 已知限制与后续事项

- **本批是 P3a**：只做导入（X-AnyLabeling JSON）与回收站；COCO/YOLO/VOC/LabelMe/LabelImg 导入、同步文件数据、导出/训练仍待 P3b。
- 导入冲突是“整批跳过/整批替换”，不是设计 §10.2 的逐项/批量冲突清单；逐项选择待 P3b。
- 回收站没有“自动清理天数”配置入口；只支持手动清空；删除/恢复不做来源 JSON 处理（设计 D19）。
- 导入后的类别顺序没有从 `classes.txt` 种子化（D18 的 P3b）。
- DB 模式删除/恢复未强制登录门禁（沿用现有删除动作的门禁状态，未额外加 DB 专属限制）。
- pytest `tmp_path` 仍受本机 DSH 沙箱 `mode=0o700` DACL 限制；本批用 `dataset_tmp` 与离屏冒烟。

---

## 4.3.2+fork.25 — 2026-11-20

### 1. 背景与原因

P1 已让 DB 目录可打开、可读写单图，但搜索、统计、类别页仍按 JSON 扫描；DB 模式下搜索框只提示不可用，统计/类别页为空或旧数据。P2 把这三处改成数据库查询，并复用现有搜索语法与统计表模型，避免另造一套 UI。

### 2. 主要实现与关键细节

- **搜索复用现有语法**：`file_search.matches_query_label_data()` 把 DB 的 `ImageAnnotation` 转成 `{shapes, flags, split, description, tags}`，直接走现有 `SearchQuery` 节点求值；`label::`/`split::`/`shape::0`/属性/描述/文件名/布尔组合/`#N` 的行为与 JSON 模式一致。
- **文件表过滤**：`FileSession._load_database_folder(pattern=...)` 先用 `parse_search_query()` 过滤 `image_summaries()` 的行，再生成文件表；DB 搜索 `load=True` 直接打开第一条结果，避免 `load=False` 留下“文件名已变但画布未变”的状态。
- **统计**：`DatasetRepository.statistics_rows()` 按图片聚合活动对象的类别与 `split`；`RightSidebarTabs._refresh_statistics()` 在 DB 模式构造 `FileStatisticsEntry` 并调用 `StatisticsTable.set_entries()`，不再读 JSON。保存/划分后会刷新当前可见统计页。
- **类别页**：`DatasetRepository.category_counts()` 提供数据集级类别与对象数；`LabelManagerPanel._collect_labels()` 在 DB 模式直接读库。`rewrite_categories(image_ids, renames, deletes)` 在事务内按图片范围重命名（合并到目标类别）或软删对象，`LabelManagerPanel._rewrite_database()` 把文件表路径映射为 `image_id` 后调用；范围、重名/空名校验沿用原面板。
- **版本**：`4.3.2+fork.24` → `4.3.2+fork.25`。

### 3. 涉及模块与文件

- 修改：`anylabeling/views/labeling/utils/file_search.py`、`file_session.py`、`label_widget.py`、`right_sidebar.py`、`file_list/controller.py`、`annotation_editor.py`、`widgets/label_manager.py`、`anylabeling/services/dataset/repository.py`、`anylabeling/app_info.py`
- 测试：`tests/test_dataset_db/test_repository.py`、`tests/test_dataset_db/test_ui_adapter.py`
- 文档：本文件、`docs/dev/CODE_STRUCTURE_REPORT.md`、`docs/开始.md`、`docs/dev/数据库设计-讨论稿.md`（代码基线）

### 4. 行为、接口与兼容性影响

- **用户可观察**：DB 模式下搜索可用（含统计表点击反筛）；统计表显示 DB 的类别 × 划分；类别页显示数据集类别并可在登录后按范围改名/删除。JSON 目录行为不变。
- **内部接口**：新增 `matches_query_label_data()`、`FileSession._load_database_folder(pattern=...)`、`DatasetRepository.statistics_rows()/category_counts()/rewrite_categories()`、`LabelManagerPanel._rewrite_database()`。
- **数据契约**：DB schema 不变；类别删除为对象软删（`is_deleted=1`），不做物理删；重命名合并到目标类别。
- **版本**：`4.3.2+fork.24` → `4.3.2+fork.25`（用户可观察行为变化）。

### 5. 实际验证内容

- `python -m pytest tests/test_dataset_db -q`：**18 passed**（新增 DB 搜索过滤、统计/类别计数、类别重命名+软删）。
- 离屏 `MainWindow` 冒烟（`temporary/p2/smoke_p2.py`，2 张图/2 类别）：
  - 统计：`classes=('bolt','nut')`，`bolt` 在 train、`nut` 在 val，`total=2`；
  - 类别页：`['bolt','nut']`，未登录时表禁用，显式启用可编辑；
  - 搜索：`label::bolt` → 1 行且加载 `a.png`；清空 → 2 行；
  - 类别编辑：把 `bolt` 改为 `screw` 后重载 DB，当前图对象标签为 `['screw']`。
  - 结果：`p2 smoke ok`。
- `python -m compileall` 修改模块通过；四语言翻译仍为 2219 条 / 0 unfinished（P2 未新增界面文案）。
- **未执行**：真实桌面点击/快捷键、DB 大目录搜索/统计性能、回收站/导入/同步/导出/训练、打包、全量回归。

### 6. 已知限制与后续事项

- **搜索按图加载**：当前每条候选调用 `load_annotation()`，大库搜索是 O(图片数) 次查询；P3 可改为一次查询对象/批量聚合，或加 FTS/索引。
- **类别批量编辑不写归属**：`rewrite_categories()` 只改 `image_file.updated_at` 与对象 `category_id`/`is_deleted`，不写 `image_file.editor/modified_at`；与 fork.23 类别页直接改 JSON 的既有缺口一致，后续统一走归属盖章。
- **类别页范围**：类别列表是数据集级（D15），但 `From/To` 仍按当前文件表（含搜索过滤）的行号；搜索后范围语义要在 UI 上提示清楚。
- **统计口径**：DB 统计按“图片是否包含该类别”计数，与 JSON 版一致；`checked` 仍未持久化。
- **未接**：回收站、导入/同步、导出/训练、项目文件；P3/P4。

---

## 4.3.2+fork.24 — 2026-11-20

### 1. 背景与原因

T3/P0 已落地 SQLite 存储层，但没有任何 UI 路径使用它。P1 的目标是让“打开一个含 `xanylabeling.db` 的数据集目录”走数据库：文件表从库里列出图片，单图从库里读标注，保存写回库；同时不破坏 JSON 目录的既有行为。

### 2. 主要实现与关键细节

- **目录检测**：`FileSession.import_image_folder()` 先检查 `<目录>/xanylabeling.db`。存在则 `DatasetDatabase.open()` + `DatasetRepository`，设置 `dataset_database`/`dataset_repository`/`dataset_root`，文件表改从 `image_summaries()` 取数；不存在则关闭旧库并回退 JSON 扫描。
- **文件表**：新增 `FileListController.append_db_row(file, FileMeta)` 与 `build_row_cells(..., meta=...)`；行内对象数来自 `annotation_object`，划分来自 `image_file.split`，标签来自 `image_tag`，导入时间来自 `imported_at`。DB 模式下“划分”列直接写 `image_file.split`（不再写 JSON）。
- **单图加载**：`FileSession.load_file()` 增加 DB 分支，把 `ImageAnnotation` 转成 `Shape` 列表和 `DatabaseLabelFile`（轻量 LabelFile 形状，`filename` 用图片路径），复用原有的图像/缩放/画布/缩略图公共尾部；`author`/`modified_at`/`tags`/`split`/`description`/`relations`/未知顶层字段都回到 `other_data`，图片 flags 回到 `label_file.flags`。
- **单图保存**：`AnnotationEditor.save_labels()` 在 DB 模式走 `_save_database_labels()`，按 `dataset_image_id` 调 `DatasetRepository.save_annotation()`；归属仍由 `OperatorGate.prepare_attribution()` 决定，JSON 的 `author`/`modified_at` 写入 DB `editor`/`modified_at`；未知顶层字段进 `extra`。
- **不适用动作**：DB 模式下 `Save As`、删除标注、删除图片、修改输出目录、拖入外部文件均给出状态提示并阻止写 JSON；审核勾选/“上一张/下一张未审核”动作一并禁用（DB schema 无 `checked`）。这些动作要等 P3 的回收站/同步/导出，勾选功能 P4 删除。
- **首行加载修复**：`load_file()` 在“目标行不是当前行”时先清空 `host.filename` 再 `setCurrentRow()`，让选择信号真正加载第一张图；此前首行加载会被“点击当前文件”判断吞掉。
- **翻译**：四语言 `.ts` 在 `LabelingWidget` 上下文新增 14 条 DB 模式提示；`scripts/compile_languages.py` 重编 `.qm`（各 2219 条、0 unfinished）并重建 `resources.py`。
- **版本**：`4.3.2+fork.23` → `4.3.2+fork.24`。

### 3. 涉及模块与文件

- 修改：`anylabeling/views/labeling/file_session.py`、`annotation_editor.py`、`file_list/controller.py`、`label_widget.py`、`anylabeling/services/dataset/repository.py`（`image_summaries()`/`set_split()`）、`anylabeling/app_info.py`
- 测试：`tests/test_dataset_db/test_ui_adapter.py`（新增 2 个适配器用例）、`tests/test_dataset_db/` 其余用例
- 翻译资源：`anylabeling/resources/translations/{en_US,zh_CN,ja_JP,ko_KR}.{ts,qm}`、`anylabeling/resources/resources.py`
- 文档：本文件、`docs/dev/CODE_STRUCTURE_REPORT.md`、`docs/开始.md`、`docs/dev/数据库设计-讨论稿.md`（代码基线）

### 4. 行为、接口与兼容性影响

- **用户可观察**：打开含库目录时文件表来自 DB；首图可正常加载；编辑后 `Ctrl+S` 写回 SQLite；划分列写 DB。JSON 目录仍走原 JSON 读写，行为不变（首行加载修复对 JSON 同样生效）。
- **内部接口**：新增 `FileListController.append_db_row()`、`DatabaseLabelFile`、`FileSession._open_dataset_for_folder()/_load_database_folder()/_prepare_database_file()/_close_dataset()`、`AnnotationEditor._save_database_labels()`、`DatasetRepository.image_summaries()/set_split()`。
- **数据契约**：DB schema 不变（P0 的 v0.13 8 表/86 列/3 视图）；JSON 契约不变。
- **兼容性**：没有 `xanylabeling.db` 的目录仍按 JSON 模式；DB 存在但无图片/损坏时给错误提示，不回退 JSON。
- **版本**：`4.3.2+fork.23` → `4.3.2+fork.24`（用户可观察的存储行为变化）。

### 5. 实际验证内容

- `python -m pytest tests/test_dataset_db -q`：**15 passed**（新增 `test_open_dataset_for_folder_and_file_rows`、`test_save_database_labels_writes_through_repository`、`test_image_summaries_and_split_update`）。
- 离屏 `MainWindow` 冒烟（`temporary/p1/smoke_gui.py`，使用 P0 导入器生成 DB）：
  - DB 目录：`dataset_repository` 非空、文件表 1 行、首图 `DatabaseLabelFile`、`dataset_image_id` 非空、`save_labels()` 写回库后对象数 1、tags `['tag']`；
  - 同一窗口切到无库 JSON 目录：`dataset_repository` 回到 `None`、`label_file` 为 `LabelFile`、读取 1 个对象、`save_labels()` 后 JSON 仍有 1 个对象；
  - 结果：`gui smoke ok` / `json smoke ok`。
- `python -m compileall` 覆盖修改模块：通过。
- 翻译：四语言 `.ts` 各新增 14 条，`pyside6-lrelease` 重编 `.qm` 各 **2219 条 / 0 unfinished**；从 `:/languages/translations/zh_CN.qm` 加载并抽查 `Dataset database: %s`、`Search filters are not available in dataset mode yet.`、`Current image is not registered in the dataset.`，均返回预期中文。
- **未执行**：真实桌面点击/快捷键、DB 大目录性能、搜索/统计/类别页/导出/训练、打包。

### 6. 已知限制与后续事项

- **搜索、统计、类别页、导出、训练仍是 JSON 口径**：DB 模式下搜索框只提示“暂不可用”且不再重建列表；统计/类别页可能为空或停留在旧数据；按计划 P2 接入。
- **checked 审核状态**：DB schema 已无 `checked`，DB 模式下审核动作与“未审核”导航被禁用；文件表勾选框仍由 `meta.exists` 显示（不代表审核状态），P4 删除该列/功能。
- **删除/另存为/拖入/输出目录**：DB 模式下已阻止，提示“暂不可用”；P3 接回收站、同步与导出。
- **创建/导入入口**：P1 只检测已存在的库，没有“无库时自动创建/导入 JSON”的 UI；目前用 P0 的 `import_xlabel_folder()` 或测试夹具建库。P3 接导入向导。
- **测试环境**：`temporary/p1` 与 `tests/test_dataset_db` 使用普通 mode 目录；现有 pytest `tmp_path` 用例在本机 DSH 沙箱下仍会因 `mode=0o700` DACL 卡住，未用其作为 P1 验证依据。

---

## 4.3.2+fork.23 — 2026-11-19

### 1. 背景与原因

用户提出：`工具 → 标签管理器（Alt+L）` 的入口流程偏长，而右侧“类别”tab 功能单一、默认侧栏宽度也够，希望把标签管理器直接放进“类别”tab，同时少一个窗口。评估（见对话记录）指出：原 `LabelModifyDialog` 是**跨文件范围**的批量改名/删除 + 会话级显隐/锁定/颜色，和“类别”tab 的“当前图片类别列表”作用域不同；放进 tab 会失去 `From/To + Go` 的显式提交边界，且首次进入会扫描文件列表内的所有 JSON。用户确认仍选“整体搬入”，并给出简化口径：类别列改为可编辑、去掉 `New Value` 列、`Delete/Visible/Lock/Color` 列宽本来就窄，侧栏可调。本批按此实施，并保留“Go”作为唯一的写盘边界。

### 2. 主要实现与关键细节

- **新增 `widgets/label_manager.py`**：把原 `LabelModifyDialog` 的 UI 与逻辑重写为页内面板 `LabelManagerPanel(QWidget)`，并移入其专用的 `LabelColorButton`。表格改为 5 列：`Category`（可编辑）/ `Delete` / `Visible` / `Lock` / `Color`；底部保留 `From` / `To` / `Go`。
- **类别列可编辑替代 New Value**：双击行内改名，应用时校验空名、重名与非法范围；非法时提示且不写盘。删除行会禁用该行的类别编辑。
- **删除对话框**：移除 `LabelModifyDialog` 及其专用 `LabelColorButton`、`special_workspaces` 中的创建逻辑；`工具 → 标签管理器` / `Alt+L` 改为切到“类别”页、必要重建并聚焦表格。
- **类别 tab 由面板承载**：`workspace.build_workspace()` 用面板替换原来的 `unique_label_list` 页面；`unique_label_list` 不再显示，仍作为“类别 → 颜色/锁定”的会话登记表保留（约 40 处调用不变，避免大面积重构）。
- **新建对象的默认类别**：改为读取面板当前行（`selected_label()`）；未选中时回落到原有登记表选择，保持旧行为。
- **门禁**：`label_manager` 移出 `OPERATOR_REQUIRED_ACTIONS`（动作只负责切页），改由 `OperatorGate.apply()` 调用 `label_manager_widget.set_editing_enabled(allowed)`；浏览模式下整张表只读。
- **刷新**：文件列表增删、排序、清空以及当前图片新增类别时调用 `invalidate()`；切到该页时按需重建（`ensure_built()`），不在启动时扫描。
- **侧栏宽度回归**：五列表格曾把右侧栏最小宽度从 220px 抬到 315px（`sizeHint * 0.8` 的既有算法），面板覆盖 `minimumSizeHint()`/`sizeHint()` 后恢复 220px，表格改为横向滚动。
- **翻译**：新增 `LabelManagerPanel` 上下文 22 条（四语言），删除已废弃的 `LabelModifyDialog` 上下文；`scripts/compile_languages.py` 重编 `.qm`（各 2205 条、0 unfinished）并重建 `resources.py`。

### 3. 涉及模块与文件

- 新增：`anylabeling/views/labeling/widgets/label_manager.py`
- 修改：`widgets/__init__.py`、`widgets/label_dialog.py`（删除两个类与无用导入）、`widgets/workspace.py`、`special_workspaces.py`、`operator/gate.py`、`right_sidebar.py`、`annotation_editor.py`、`file_list/controller.py`、`app_info.py`
- 翻译资源：`resources/translations/{en_US,zh_CN,ja_JP,ko_KR}.{ts,qm}`、`resources/resources.py`
- 测试：`tests/test_labeling/test_label_manager.py`（由 `test_label_manager_locks.py` 更名并扩展为 12 个用例）、`tests/test_labeling/test_file_table.py`（新增类别页集成用例）
- 文档：本文件、`docs/dev/CODE_STRUCTURE_REPORT.md`、`docs/user/zh_cn/user_guide.md`

### 4. 行为、接口与兼容性影响

- **用户可观察**：标签管理器从模态窗口变为“类别”标签页；`Alt+L` / 菜单项切页；类别列可直接改名；`Go` 应用；浏览模式只读；右侧栏仍可拖到 220px。
- **内部接口**：`LabelModifyDialog` 与其 `LabelColorButton` 删除（无其他内部调用方）；新增 `LabelManagerPanel`（`invalidate()`、`ensure_built()`、`rebuild()`、`apply_changes()`、`selected_label()`、`set_editing_enabled()`）与宿主属性 `LabelingWidget.label_manager_widget`。
- **配置**：无新增键；`shortcuts.edit_labels`（`Alt+L`）键名与语义（“打开标签管理器”）保持不变。标注 JSON 契约不变。
- **版本**：`4.3.2+fork.22` → `4.3.2+fork.23`。

### 5. 实际验证内容

- `tests/test_labeling/test_label_manager.py` **12 passed**：表格行/范围、改名只作用于范围、改名作用于范围内全部行、删除只作用于范围、重名拒绝、空名按“不改名”处理、未登录不可应用、锁定只改会话、显式解锁不写盘、删除后禁用编辑、选中类别作为默认类别、invalidate 后重建。
- `tests/test_labeling/test_file_table.py` **27 passed**（新增“类别页托管面板 + Alt+L 切页 + 门禁联动”用例）。
- `tests/test_labeling/test_file_table.py test_label_manager.py test_operator_gate.py test_browse_mode.py` **55 passed**；`test_file_table + test_label_manager` **38 passed**。
- 全量回归（`tests/test_labeling tests/test_settings tests/test_config tests/test_identity tests/test_widgets tests/test_utils`）**539 passed / 1 skipped / 6 failed / 186 subtests**；6 条失败与 `temporary/baseline-fork21/src` 基线一致，均为结构报告 §13.1 记录的“用例未跟上实现”测试债（属性保存、笔刷模式、标题断言、属性上传）。
- 翻译：从 `:/languages/translations/<lang>.qm` 加载并抽查 `LabelManagerPanel` 的 `Category`/`Go`/`Duplicate category: %s` 等，四语言均返回预期译文。
- 离屏 `MainWindow` 冒烟：类别 tab 承载面板、`Alt+L` 切页并重建 2 行、表头/类别正确、未登录时表格与 `Go` 禁用。
- **未执行**：真实桌面交互（行内编辑、`Go` 的实际写盘反馈、高 DPI 观感）、`black`/`flake8`/`pre-commit`（本机未安装）、打包。

### 6. 已知限制与后续事项

- 面板仍沿用旧对话框的做法**直接 `json.dump` 写标注 JSON**：不写 `author`/`modified_at`、不重置 `checked`，与 fork.4 的归属契约不一致。这是既有缺口，本次未顺手修改；若要修，应在写盘前走 `OperatorGate.prepare_attribution()` 并补批量归属测试。
- 首次切到该页会扫描文件列表内所有 JSON；大目录首次进入可能卡顿，之后仅在 `invalidate()` 后重建。未做后台扫描或进度提示。
- 删除类别只删除范围内的对象，不会清理 `_config["labels"]` 或类别编辑框历史之外的类别词表；项目级类别词表管理仍是另一项功能。
- `From/To` 仍按文件列表序号；fork.22 的文件表多选尚未接入该面板（可改为“作用于选中行”，本次未做）。
- `unique_label_list` 仍作为隐藏的会话登记表存在（颜色/锁定数据源），未改为纯数据模型；后续可评估用字典替代这个 QListWidget。

### 7. T3/P0 预埋：数据集 SQLite 存储层（2026-11-20，未发布、不升版）

- **背景**：T3 数据库改造启动，先落不改变现有 UI 行为的存储地基；设计见 `docs/dev/数据库设计-讨论稿.md` v0.13。
- **新增**：`anylabeling/services/dataset/`（`schema.py`、`connection.py`、`codec.py`、`repository.py`、`importer.py`、`errors.py`、`__init__.py`）。8 表 86 列 3 视图；WAL/`foreign_keys`/`application_id`/`user_version`；在线 `VACUUM INTO` 备份；XLABEL JSON↔DB 编解码（几何对象、flags/attributes/kie/extra、tags、relations、`author`→`editor`）；按 uuid upsert、缺失对象软删/恢复、回收站 `deleted_at`；XLABEL 目录导入（skip/replace/error，源文件只读）。
- **测试**：`tests/test_dataset_db/` **12 passed**（schema 同步、建库、导入往返、upsert/恢复、NOCASE、回收站、坏 JSON）。conda Python 3.12.14 / SQLite 3.53.4。
- **行为/兼容性**：现有 JSON 读写链路未改，不新增配置键、不改界面；`LabelingWidget`/`FileSession`/文件表/搜索/统计/导出均未接入。版本保持 `4.3.2+fork.23`，本批只做本地提交、不推送。
- **限制/后续**：P1 才接单图读写与文件列表；P1 起才出现用户可观察的存储行为变化并按规则升版。测试因 DSH 沙箱下 `tmp_path` 的 `mode=0o700` DACL 问题改用 `dataset_tmp`（普通 mode 目录），不是产品行为。

---

## 4.3.2+fork.22 — 2026-11-19

### 1. 背景与原因

用户提出两项需求：

- **文件表不能多选**：无法用 `Ctrl + 鼠标` 多行选择，`Ctrl + A` 也不能全选。核查确认这是“从未实现”，不是回归：文件表自本 fork 首个提交起就是 `SingleSelection`（`git log -S SingleSelection` 只命中根提交与 T8 搬运提交）；而且 `Ctrl + A` 已被窗口级快捷键 `shortcuts.auto_label`（自动标注面板）占用，实测在表格上按 `Ctrl + A` 打开的是自动标注面板，所以只把选择模式改成 `ExtendedSelection` 仍然无法全选。文件表此前也没有任何批量动作，因此“多选”必须同时定义“选区与当前图片的关系”“批量动作”“反馈”三件事。
- **图片标签条与“标志”页重复**：用户认为“在 tabwidget 中有标志的情况下，画布下方那条图片标签栏应去掉，把图片标签放进标志页”。两者其实不是同一种数据（`tags` 是自由文本有序数组，`flags` 是固定词表的布尔字典，数据库设计里也分别对应 `image_tag` 表与 `image_file.flags_json`），但用户明确选择合并，并要求补一个“不切页也能看到标签”的出口。本批按“图像属性”页承载两者、文件表新增 `标签` 列作为出口实施。

### 2. 主要实现与关键细节

#### 2.1 文件表多选与批量动作

- `FileTableWidget` 选择模式改为 `ExtendedSelection`；`mousePressEvent` 记录 Ctrl/Shift 手势（右键仍只打开菜单、不改选区），`keyPressEvent` 对 Ctrl/Shift + 导航键同样置手势标志，`selection_only_gesture()` 暴露给宿主。
- **`Ctrl + A`**：在 `event()` 中接受 `ShortcutOverride`，并在 `keyPressEvent()` 中调用 `selectAll()`。因此只有文件表获得焦点时 `Ctrl + A` 才是全选，窗口级“自动标注”快捷键在其他控件上语义不变。
- `LabelingWidget.file_selection_changed()` 增加三道守卫：`_no_selection_slot` 期间返回；扩展选择手势期间返回（不打开图片）；当前行与已打开文件相同时返回（否则全选/取消选择会整份重载当前文件，丢失未保存状态）。
- 批量动作（右键菜单；右键落在多选范围内时作用于全部选中行，否则只作用于该行）：
  - 设置划分：`set_split_rows()` 逐行 `write_split()` 后 `refresh_row()`、刷新统计，并按条数给出状态消息；单选仍走 `set_split()` 薄封装。
  - 从列表移除：`remove_rows()` 一次确认（多行时提示数量并说明不删除磁盘文件），从后往前删行、重建索引；若当前文件被移除则选中相邻行，否则重新同步选区。
  - 复制文件名/路径：多行时每行一条（换行分隔）。
- `context_target_rows()` 统一决定菜单目标集合。

#### 2.2 图片标签并入“图像属性”页

- `widgets/workspace.py` 新增 `attributes_panel`：`图片标签` 小节标题 + `ImageTagsWidget` + `标志` 小节标题 + `flag_widget`；右侧 tab 的 `flags` 页标题改为 `Image Attributes`（页 key 仍是 `flags`，不迁移配置）。
- 画布下方不再有标签条：`central_layout` 移除该控件；`build_canvas_view()` 仍创建控件（`OperatorGate` 在工作区装配前就会访问它），但不再 `show()`；删除 `_image_tags_visibility` 状态、`toggle_image_tags_visibility()`、`_auto_show_image_tags()`，以及 `LabelingWidget.eventFilter` 中为该条调整右侧栏下边距的分支。
- `show_image_tags` 动作改为一次性跳转：非 checkable，触发 `show_image_tags_editor()`（切到 `flags` 页并聚焦标签控件）；`Ctrl+Shift+T`、`视图 > Image Tags`、标题栏按钮共用该动作；设置页快捷键说明由 `Toggle Image Tags` 改为 `Edit Image Tags`。
- `right_sidebar.ALWAYS_VISIBLE_TABS = ("flags",)`：该页不可隐藏（状态栏提示“该面板不可隐藏”），`_apply_right_tabs_config()` 会丢弃旧配置中隐藏它的项。
- **文件表新增 `标签` 列**（`FILE_COL_TAGS`，共 6 列）：`FileMeta` 增加带默认值的 `tags`（用 `normalize_image_tags` 归一），行构建/刷新显示逗号分隔文本并支持表头显隐与 `file_list.show_tags`；标签编辑后由 `_on_image_tags_changed()` 调 `set_row_tags()` 直接更新单元格（文件尚未保存，不能从磁盘回读），`AutoLabelingHandoff` 写入自动标注 tags 后同样更新该行。

### 3. 涉及模块与文件

- 文件表：`anylabeling/views/labeling/file_list/{table,controller,constants,__init__}.py`、`utils/file_meta.py`
- 视图装配与状态：`widgets/workspace.py`、`right_sidebar.py`、`appearance.py`、`actions/builder.py`、`label_widget.py`
- 标签回写：`file_session.py`、`auto_labeling_handoff.py`
- 配置与设置：`configs/xanylabeling_config.yaml`（`file_list.show_tags`）、`settings/schema.py`
- 翻译资源：`resources/translations/{en_US,zh_CN,ja_JP,ko_KR}.{ts,qm}`、`resources/resources.py`
- 测试：`tests/test_labeling/test_file_table.py`、`tests/test_labeling/test_image_tags.py`
- 文档与版本：本文件、`docs/dev/CODE_STRUCTURE_REPORT.md`、`docs/user/zh_cn/user_guide.md`、`app_info.py`

### 4. 行为、接口与兼容性影响

- **用户可观察**：文件表支持 `Ctrl + 单击`/`Shift + 单击`/`Ctrl + A` 多选，右键菜单多出批量划分、批量移除、批量复制路径；新增 `标签` 列；画布下方标签条移除，标签改在“图像属性”页编辑；`标志` 页改名“图像属性”且不可隐藏；`Ctrl+Shift+T` 由“显示/隐藏标签条”变为“跳到标签编辑区”。标注 JSON 契约不变。
- **配置**：新增 `file_list.show_tags`（缺省 `true`）；`right_tabs.hidden` 中若含 `flags` 会在加载时被忽略；`shortcuts.toggle_image_tags` 键名保留但语义变化（不再切换可见性）。
- **内部接口**：`FileMeta` 新增带默认值的 `tags` 字段；`FileListController` 新增 `selected_paths()`/`context_target_rows()`/`set_split_rows()`/`remove_rows()`/`set_row_tags()`；`FileTableWidget` 新增 `selection_only_gesture()`；`RightSidebarTabs.ALWAYS_VISIBLE_TABS` 常量为新约束。`LabelingWidget.toggle_image_tags_visibility()` 与 `_auto_show_image_tags()` 删除，`show_image_tags_editor()` 取而代之。
- **版本**：`4.3.2+fork.21` → `4.3.2+fork.22`。

### 5. 实际验证内容

- 定向 pytest（本机 conda env，`QT_QPA_PLATFORM=offscreen`）：`tests/test_labeling/test_file_table.py` **26 passed**，其中新增 7 个用例：Ctrl/Shift 单击扩展选区且不换图、Shift+方向键扩展选区且不换图、表格内 `Ctrl+A` 全选且不触发自动标注面板、批量划分写盘、批量移除保留文件并重建索引、`标签` 列随文件/内存编辑更新、“图像属性”页托管标签编辑器且画布区域不再包含它；`test_file_table + test_image_tags + test_utils/test_file_meta` 首轮 **60 passed**。
- 回归：`tests/test_labeling tests/test_settings tests/test_config tests/test_identity tests/test_widgets tests/test_utils` 合计 **529 passed / 1 skipped / 7 failed / 186 subtests passed**。7 条失败与 `temporary/baseline-fork21/src`（HEAD 的只读导出树）逐条一致：6 条为结构报告 §13.1 已记录的“用例未跟上实现”测试债，1 条为已记录的时序抖动 `test_brightness_contrast_updates_are_throttled`。
- 回归中发现并修复的自伤：早期实现用 `QApplication.keyboardModifiers()` 判断手势，被同一进程内前序用例残留的 Ctrl 状态污染，导致 `test_image_switch::test_configured_image_jump_updates_navigation` 失败；改为只依据控件自身的手势标志后，该文件 **4 passed**。
- 翻译：四语言 `.ts` 新增 10 条（`LabelingWidget` 9 条 + `SettingsDialog` 1 条），`scripts/compile_languages.py` 重编 `.qm`（各 2183 条、0 unfinished）并重建 `resources.py`；从 `:/languages/translations/<lang>.qm` 加载并抽查全部新字符串，四语言均返回预期译文。
- **未执行**：真实桌面 GUI 交互（Ctrl+单击、右键批量菜单的观感与高 DPI 表现）、`black`/`flake8`/`pre-commit`（本机未安装）、打包与发布。

### 6. 已知限制与后续事项

- 批量动作只做了一期范围：**删除文件**与**对选中行跑自动标注**未纳入（后者与 `BatchRangeDialog` 的区间语义冲突，需先定规则）。
- 切换图片会清空多选（`sync_selection()` 走 `setCurrentCell`），符合“跳图即重置选区”的约定，未做选择记忆。
- “图像属性”页不可隐藏是硬约束；若将来把标签/标志拆回可隐藏面板，需同步调整 `ALWAYS_VISIBLE_TABS` 与用户手册。
- `标签` 列只是逗号连接的文本（超长省略 + tooltip），搜索语法暂不支持 `tag::`；批量设置检查状态也未纳入。
- 本机 pytest 仍受 DSH Windows 沙箱限制：沙箱内新建目录无法被枚举（`WinError 5`），本轮按用户授权以一次性完全权限运行；未在受限模式复现该限制的绕过方案。

---

## 4.3.2+fork.20 — 2026-11-19

### 1. 背景与原因

用户报告运行时有两条报错：

- **报错 1：`ModuleNotFoundError: No module named 'anylabeling'`**（`label_widget.py` 第一处包内绝对导入）。复现确认这是**启动方式问题**，不是代码缺陷：`label_widget.py` 是包内模块而非入口，直接 `python label_widget.py`（或 IDE 对当前文件按 Run）时 Python 把该文件所在目录而非仓库根加入 `sys.path`，包导入必然失败；在重构前的基线工作树上直接运行同一文件报同样错误（基线行为见 `temporary/sam-diag` 下的验证记录）。正确启动方式是 `python -m anylabeling.app`（仓库根执行）或 VS Code 的 `.vscode/launch.json` → “Debug Python Module”。
- **报错 2：SAM 编码器 ONNX Runtime 内存分配失败**（`BFCArena ... Failed to allocate memory for requested buffer of size 1073741824`）。该 1 GiB 缓冲是 SAM ViT 全局注意力矩阵（4096×4096×16 heads×4B）的一次性连续分配；模型级实测：单次编码峰值 ViT-L float **5.31 GB**、ViT-L quant 4.42 GB、ViT-H quant 4.95 GB；编码结束关闭 session 后内存可完整归还（5.31 → 0.07 GB，无泄漏）。真正的放大器是：`segment_anything` 在 `_ON_NEXT_FILES_CHANGED_MODELS` 中，模型加载后**后台线程预加载后续图片**，而用户又可随时触发交互编码，两个编码器会话并发时实测峰值 **10.55 GB**；用户机器 31.3 GB 内存、其它程序已占约 14 GB、页面文件仅约 1 GB，因此在 1 GiB 连续分配时失败。

### 2. 修改与关键细节

- **新增 `anylabeling/services/auto_labeling/encoder_lock.py`**：`cpu_encoder_lock(providers)` 在 provider 列表**全部**为 `CPUExecutionProvider`/`AzureExecutionProvider` 时返回进程级共享锁（`threading.Lock`，可作为上下文管理器），否则返回 `contextlib.nullcontext()`。锁是进程级而非实例级，因此预加载线程与交互编码、以及不同 SAM 适配器实例之间都会互斥。
- **直接创建 ORT 会话的 SAM 适配器接入锁**：
  - `sam_onnx.py`（`segment_anything` 使用）：`run_encoder()` 的懒加载 + `session.run` + `release_after` 释放整体套锁；
  - `sam_hq.py`：同样的懒加载/运行/释放套锁；
  - `grounding_sam.py`、`sam_med2d.py`、`__base__/sam.py`（EdgeSAM）：在 `__init__` 保存 `self.providers`，并在 `encoder_session.run(...)` 外套锁。
- 预加载机制本身不改：锁只让第二个编码等待，而不是丢弃预加载结果；GPU/加速 provider 行为保持原样（可继续并行预加载）。
- **版本**：`4.3.2+fork.19` → `4.3.2+fork.20`（用户可观察的资源行为变化 + 缺陷修复，按 `docs/开始.md` §八.3 升版）。

### 3. 涉及模块与文件

- 新增：`anylabeling/services/auto_labeling/encoder_lock.py`；
- 修改：`anylabeling/services/auto_labeling/sam_onnx.py`、`sam_hq.py`、`grounding_sam.py`、`sam_med2d.py`、`__base__/sam.py`；
- 测试：新增 `tests/test_models/test_sam_encoder_lock.py`（CPU 共享锁、加速 provider 不串行、并发不重叠、编码后释放 session）；
- 文档：`CHANGELOG-fork.md`、`docs/dev/CODE_STRUCTURE_REPORT.md`、`anylabeling/app_info.py`。

### 4. 行为、接口与兼容性影响

- 用户可观察：CPU 上 SAM 类模型编码改为串行执行；当后台预加载正在编码时，交互标注可能等待一张编码完成（本机 ViT-L 约 10–20 秒），但峰值内存从约 10.5 GB 降到约 5.3 GB，避免 `Failed to allocate memory`；GPU/加速 provider 无变化。
- 代码接口：新增 `cpu_encoder_lock`；`sam_onnx.py`/`sam_hq.py`/`grounding_sam.py`/`sam_med2d.py`/`__base__/sam.py` 的 `SegmentAnythingONNX`/`EdgeSAMONNX` 新增 `providers` 属性（内部使用）；无配置键、QSettings、数据格式、CLI 或模型契约变化。
- 报错 1 不涉及代码改动；正确启动命令见上（`python -m anylabeling.app`），并用 `.vscode/launch.json` 的 “Debug Python Module” 配置。

### 5. 实际验证内容

- 模型级实测（`temporary/sam-diag/`，使用用户机器上 `E:\segment_anything_vit_l-r20230810` 的真实模型）：
  - 旧行为两路并发：10.55 GB 峰值、两路均成功；
  - 加锁后两路并发：**5.42 GB 峰值**，两路串行完成（10.5s + 11.6s = 22.3s），两路均返回 `(1,256,64,64)` 嵌入；
  - session 释放：单次编码后销毁 session，RSS 5.31 GB → 0.07 GB（重复 3 次结果一致，无泄漏）。
- 新增单测 `tests/test_models/test_sam_encoder_lock.py`：4 passed（CPU 共享锁、加速 provider 不串行、两个并发 `run_encoder` 最大并发为 1、`release_after` 后 `encoder_session is None`）。
- `tests/test_models` + `tests/test_auto_labeling`：236 passed；4 failed 均为**基线同样存在**的环境限制用例（Windows 符号链接权限 `WinError 1314`、沙箱 `PermissionError`），已在基线工作树复跑确认相同。
- 离屏 `MainWindow` 冒烟通过；`python -m anylabeling.app version` 输出 `4.3.2+fork.20`。
- **未执行**：真实桌面 GUI 交互、GPU 环境、打包/发布；`black`/`flake8`/`pre-commit` 未安装未执行。

### 6. 已知限制与后续事项

- 本次只覆盖直接创建 ONNX Runtime 会话的 SAM 适配器；`_ON_NEXT_FILES_CHANGED_MODELS` 中其余重编码器（`segment_anything_2`、`grounding_sam2`、`yolov8_sam2`、`efficientvit_sam`、`geco`、`yolov5_sam` 的基类会话等）仍可能并发预加载，如遇到同类 OOM 应按同样方式接入 `cpu_encoder_lock`。
- 页面文件仍只有约 1 GB，属系统设置；代码加锁只把峰值减半，不能替代足够的内存/页面文件。
- 报错 1 属于使用方式问题，文档已说明；如后续希望降低误用，可考虑增加一个显式的开发启动脚本（本次未改）。

### 7. 追加修复（同一 fork.20 批次，未推送）：缓存嵌入不再钉住 ORT arena

用户补充现象：**每用 SAM 标注一张图，进程内存上涨约 4000 MB，切换图片也不回收**，最终 OOM。复核后确认这是真正的根因（串行锁只消除了并发峰值，不能解决累积）：

- ONNX Runtime 的 `InferenceSession.run()` 返回的 numpy 数组是**会话 CPU arena 的视图**（实测 `ndarray.flags.owndata == False`）。应用会把 `image_embedding` 放进 `image_embedding_cache`（LRU，最多 10 个文件），于是**即使 `run_encoder()` 已把 `encoder_session` 置空，只要缓存里还留着一个 4 MB 的视图，整个约 4 GB 的 encoder arena 就不会释放**；后台预加载还会一次缓存后续 7 张图的嵌入，放大到几十 GB。
- 用小型 ONNX 探针复现（`temporary/sam-diag/arena_pin_test.py`）：丢弃输出时销毁 session 后 RSS 0.45 → 0.12 GB；**保留输出视图**销毁 session 后停在 0.39 GB，直到视图被删除才回到 0.12 GB；保留 `np.array(out, copy=True)` 的副本时 3 次运行 RSS 始终 0.12 GB。

修复：

- `sam_onnx.py`（`segment_anything`）：`run_encoder()` 返回前先 `np.array(output[0], copy=True)`，再走原有的 `del output / gc / encoder_session=None` 释放，缓存的是自有内存的 4 MB 数组；
- `sam_hq.py`：同样把 `features[0]` 复制后再释放（`np.stack(features[1:])` 本身已是新内存）；
- 其余保留常驻 encoder session 的 SAM 适配器不在本次范围（它们的 arena 本就随会话常驻，不存在“释放后被视图钉住”的累积问题）。
- 版本仍为 `4.3.2+fork.20`（与第 1–6 节同批、尚未推送，作为同一批次的追加修复记录）。

验证：新增/扩展 `tests/test_models/test_sam_encoder_lock.py` 至 6 个用例（CPU 串行锁、加速 provider 不串行、并发不重叠、`sam_onnx`/`sam_hq` 输出 `owndata` 且不与假 ORT 视图共享内存、连续编码不保留 session），全部通过；小型 ONNX 探针的“保留副本”对照实验 RSS 保持平直。真实 ViT-L 的复测因**当前用户正在运行的旧进程已占用约 8.8 GB 且提交内存接近上限**（commit 可用约 3 GB，单次编码约需 5 GB）而无法在本轮完成，需用户重启应用后验证；修复后的预期是编码峰值仍约 5 GB，但每张图处理后回落到基线，不再逐图累积。

---

## 4.3.2+fork.21 — 2026-11-19

### 1. 背景与原因

用户报告（Win11 双显示器，主屏 1920×1080@100%、副屏 1536×960@200%）：

- 点击最小化后再次打开窗口，窗口跳到**另一台显示器**；最大化/还原按钮同样；
- 恢复后鼠标变成调整窗口大小的“<->”状态。

在本机（同为主屏 100% + 副屏 200%）用真实 Windows 平台实测复现：

- 窗口放在副屏 `(-2704,-680,800,600)`，`showMaximized()` 后落到**主屏** `(0,0,1920,1032)`；
- `WM_NCHITTEST` 中心点被判成 `HTTOPLEFT`/`HTLEFT`（即 Windows 认为光标在边框上，所以显示缩放箭头）；
- 还原后 geometry 变成 `(-2704,-680,1536,960)`（尺寸被污染成整屏工作区，而不是原来的 800×600）。

差分实验定位到两处模块代码：

| 实验 | 最大化结果 | 结论 |
|---|---|---|
| 模块现状 | 主屏，错误 | 复现用户问题 |
| 禁用 `WM_GETMINMAXINFO` 覆写 | 副屏工作区，正确 | **覆写是位置错误的根因** |
| 去掉 `WS_THICKFRAME` | 副屏工作区，正确 | 样式不是根因 |
| 纯 Qt 无边框窗口 | 副屏工作区，正确 | Qt 原生行为已满足 |
| 纯 Qt + `WS_THICKFRAME` | 副屏工作区，正确 | 同上 |

进一步测试 `WM_GETMINMAXINFO` 各字段的坐标语义（副屏 200%）：“只写 `ptMaxSize`（逻辑值）”正确；“写物理值”跳主屏；“只写 `ptMaxTrackSize`”把最大化尺寸减半成 768×480。说明该消息在不同 DPI 上下文下语义不一致、不可靠，而 **Qt/Windows 默认实现已经能最大化到工作区且不盖任务栏**。

### 2. 修改与关键细节

- **移除 `WM_GETMINMAXINFO` 覆写**：删除 `_WM_GETMINMAXINFO` 分支、`_apply_minmax_info()`、`_monitor_rects()`、`_MinMaxInfo`/`_Rect`/`_MonitorInfo` 结构与 `_last_monitor` 跟踪代码；`nativeEvent` 增加注释说明“不要再加回来”及原因。最大化/还原/最小化还原交回 Qt/Windows。
- **`WM_NCHITTEST` 改用物理坐标换算**：新增 `_native_hit_test()`，用 `ScreenToClient` 把 `lParam` 的物理屏幕坐标转成**本窗口客户区物理坐标**，与 `GetClientRect()` 的物理尺寸及 `round(resize_margin * dpr)` 比较；不再把全局物理坐标除以 `devicePixelRatio`（混合 DPI 副屏逻辑原点 ≠ 物理原点/缩放，会把窗口中心算成负坐标）。非 Windows、无原生句柄时返回 `None` 并回落 `(False, 0)`。
- **回归用例**：新增 `test_getminmaxinfo_is_not_overridden`（Windows 下断言 `WM_GETMINMAXINFO` 不被处理，防止以后再加回来）与 `test_native_hit_test_returns_none_without_a_native_handle`（无句柄时不抛异常）。
- **文档**：`docs/dev/无边框窗口模块-讨论稿.md` 升至 v1.6，§6/§11 从“需处理 `WM_GETMINMAXINFO`”改为“不要覆写”，并补充 `ScreenToClient` 换算约束与实测数据。
- **版本**：`4.3.2+fork.20` → `4.3.2+fork.21`。

### 3. 涉及模块与文件

- `anylabeling/widgets/frameless/window.py`（唯一的运行时代码改动，属于可复用模块，宿主持久受益）；
- `tests/test_widgets/test_frameless_window.py`；
- `CHANGELOG-fork.md`、`docs/dev/CODE_STRUCTURE_REPORT.md`、`docs/dev/无边框窗口模块-讨论稿.md`、版本号。

### 4. 行为、接口与兼容性影响

- 版本 `4.3.2+fork.20` → `4.3.2+fork.21`；无 QSettings 键、数据格式、CLI 或公共 API 变化（`_apply_minmax_info`/`_monitor_rects` 为私有方法，删除不影响宿主）。
- 用户可观察：最小化→还原、最大化→还原都留在原来那台显示器，尺寸回到原值；光标不再无故变成缩放箭头；最大化仍贴合工作区、不覆盖任务栏（主屏与 200% 副屏均验证）。
- 其他调用本模块的项目：只要使用 `FramelessWindow`，同样获得修复；不依赖宿主的 `MainWindow` 逻辑。

### 5. 实际验证内容

- 真实 Windows 桌面（本机双屏），`temporary/verify-frameless-multimon/probe.py`：模块窗口在主屏与 200% 副屏分别测试，全部 PASS——
  - 最大化：留在自身屏幕，几何等于该屏 `availableGeometry`（主屏 `(0,0,1920,1032)`、副屏 `(-3072,-836,1536,912)`）；
  - 还原：几何与还原前完全一致（800×600）；
  - 最小化→还原：屏幕与几何均不变；
  - `WM_NCHITTEST`：窗口中心 `HTCLIENT`、左边缘 `HTLEFT`（两屏、两种 DPR 均正确）。
- `temporary/verify-frameless-multimon/app_probe.py`：真实 `MainWindow`（frameless）在 200% 副屏用 `toggle_maximize()`/`minimize()` 走完整链路，PASS（最大化回副屏工作区、还原与最小化还原均回到 `(-2804,-730,1000,700)`、中心 `HTCLIENT`）。
- `python -m unittest tests.test_widgets.test_frameless_window -v`：**19 tests OK**（含两个新增用例）。
- 未执行：Win11 Snap Layouts（`Win+←/→/↑`）实机按键验证；高 DPI 拖动过程中的实时光标跟随（只验证了静态命中结果）；pytest 全量（沙箱仍受限）。

### 6. 已知限制与后续事项

- 移除覆写后，最大化行为完全依赖 Qt/Windows 默认实现；已在主屏 100% 与副屏 200% 实测贴合工作区，其他 DPI 组合建议再抽验一次。
- Win11 Snap Layouts 悬停提示仍按设计稿决策退化（本模块未实现自绘 Snap 面板）。
- 后续若有人重新加入 `WM_GETMINMAXINFO` 覆写，`test_getminmaxinfo_is_not_overridden` 会失败；该用例是本次问题的守门测试。

---

## 4.3.2+fork.19 — 2026-11-19

### 1. 背景与原因

fork.18 后用户报告两件事：

- **SAM/自动标注“完成对象”闪退**：`Traceback ... label_widget.py, line 9321, in finish_auto_labeling_object / item.setText / AttributeError: 'NoneType' object has no attribute 'setText'`。复现确认根因：`new_shapes_from_auto_labeling()` 的“追加”分支只删除了旧占位对象的**对象列表行**，却把占位形状留在 `canvas.shapes` 里；第二次自动标注结果之后，画布上就存在“有形状、没有行”的孤儿 `AUTOLABEL_OBJECT`，`finish_auto_labeling_object()` 默认每个占位都有行，于是 `find_item_by_shape()` 返回 `None` 后直接 `setText`。
- **“设置”“快捷键”按钮无法在 `设置 → 工具栏` 中控制显隐**：这两个按钮以 `QWidgetAction` 追加在 `actions.tool` 末尾且文本为空，`toolbar_entries()` 会跳过空文本动作，因此设置页只列出 43 个工具，两个固定按钮既看不到也关不掉。

### 2. 修改与关键细节

- **修复闪退根因**：`new_shapes_from_auto_labeling()`“追加”分支现在同时清理画布上的旧 `AUTOLABEL_OBJECT` 占位形状（按 `id()` 精确匹配，避免 `Shape.__eq__` 影响），不再产生孤儿；`clear_auto_labeling_marks()` 改为先判空再删行（原来只捕获 `ValueError`，`remove_item(None)` 实为 `TypeError`）。
- **防御性兜底**：新增 `_auto_labeling_list_item(shape)`，在 `finish_auto_labeling_object()` 的两个循环里按需补建对象行；确实建不出来时跳过而不是崩溃。这样历史遗留的孤儿（例如中途中断的标注会话）也能被接管，标签照常写入。
- **设置/快捷键可隐藏**：`_utility_toolbar_entries` 记录 `(key, title, action)`，`toolbar_entries()` 追加 `settings`/`shortcuts` 两项，`populate_mode_actions()` 先按 id 跳过 `actions.tool` 里的这两个动作、再按 key 决定是否插入；隐藏状态写入既有的 `toolbar/hidden_actions`，与普通工具一致。
- **版本**：`4.3.2+fork.18` → `4.3.2+fork.19`。

### 3. 涉及模块与文件

- `anylabeling/views/labeling/label_widget.py`（自动标注占位清理、`_auto_labeling_list_item()`、工具条固定按钮条目）；
- `tests/test_labeling/test_auto_labeling_finish.py`（新增）、`tests/test_labeling/test_file_table.py`（新增固定按钮显隐用例）；
- `CHANGELOG-fork.md`、结构报告、中文用户手册、`docs/开始.md`（登记 T8）、版本号。

### 4. 行为、接口与兼容性影响

- 版本 `4.3.2+fork.18` → `4.3.2+fork.19`；无新增 QSettings 键（沿用 `toolbar/hidden_actions`），无数据格式或 CLI 变化。
- 用户可观察：SAM/自动标注连续出结果后“完成对象”不再闪退；`设置 → 工具栏` 现在列出 45 项，含“设置”“快捷键”，可单独隐藏，`全选` 一并控制。
- 代码接口：`LabelingWidget._auto_labeling_list_item()`、`_utility_toolbar_entries` 新增；`toolbar_entries()` 返回值由 43 项变为 45 项。

### 5. 实际验证内容

- 复现脚本（`temporary/verify-sam-crash/repro.py`，离屏真实 `MainWindow`）：
  - 修复前两次“追加”结果后：画布 2 个占位、其中 1 个无行，`finish_auto_labeling_object()` 在 `label_widget.py:9321` 抛出与用户相同的 `AttributeError`；
  - 修复后：画布 1 个占位且有行，finish 成功，`canvas` 标签为 `['cat']`、列表文本 `['cat']`；
  - 孤儿补贴：手工插入无行占位后 finish 不崩溃，自动补行并写入标签 `cat`。
- 工具条脚本（`temporary/verify-toolbar-utility/probe.py`）：`toolbar_entries()` 45 项且末尾为 `settings`/`shortcuts`；隐藏 `settings` 后工具条 44 项、按钮 `isVisible()` 为 False；同时隐藏两项后 43 项；恢复后 45 项。
- **未执行**：pytest 回归——沙箱仍拒绝 pytest 临时目录，命令无输出退出，`test_auto_labeling_finish.py` 等新增用例需在有权限环境补跑。

### 6. 已知限制与后续事项

- 孤儿兜底只覆盖 `AUTOLABEL_OBJECT`；`AUTOLABEL_ADD/REMOVE` 标记仍按自动标注会话生命周期清理。
- `end_move(copy=True)`（另一处直接改 `canvas.shapes` 的路径）仍假定由调用方补建对象行，本次未改动，已记入结构报告维护提示。
- `label_widget.py` 上帝类问题登记为 `docs/开始.md` T8，分阶段处理；落地情况见下方第 7 节。

### 7. 重构（不升版）：T8 拆分 `label_widget.py` 上帝类

#### 7.1 背景与原因

`label_widget.py` 已达 9507 行，`LabelingWidget` 单类约 9118 行、321 个方法，其中 `__init__` 一个函数就占 2816 行：窗口装配、约 150 个 QAction 定义、菜单、工具栏、画布视图、右侧栏、文件列表、操作员门禁、自动标注交接全部挤在同一文件里。任何小改动都要在一万行上下文中定位，静态检查、测试隔离和多人协作都被拖慢；`docs/开始.md` 已登记为 T8。

#### 7.2 修改与关键细节

本次按职责拆分，全部为**代码搬移 + 显式依赖**，不改变运行时行为：

- **动作表与菜单** → `labeling/actions/`
  - `builder.py`：`build_actions(host)` 创建全部 QAction（原 `__init__` 第 855–2157 行的动作定义、`self.actions = utils.Struct(...)`、数字快捷键注册、`actions.tool` 工具条元组），返回动作登记表；菜单专用动作（`about`/`documentation`/`fill_drawing`/`open_settings`/`save_crop`/`select_lang_*`/`shape_converter`/`sponsor`/`ultralytics_train`/`theme_mode_actions`）一并挂到该表，供菜单构建复用。
  - `menus.py`：`build_menus(host)` 创建顶层菜单与 `utils.add_actions` 装配，使用 `host.actions` 而不是 `__init__` 的局部变量。
  - `LABEL_OPACITY` 迁到 `labeling/constants.py`（动作 lambda 与 `add_label` 等共用）。
- **工作区布局装配** → `labeling/widgets/workspace.py`
  - `build_canvas_view(host)`（画布 + 比较视图 + 滚动区 + 画布调节浮层 + 浏览模式浮层 + 滚动条 + 图像标签条，返回滚动区）、
  - `build_instruction_bar(host)`（指令标签、自动标注面板及其信号、面板显隐按钮、设置/快捷键/更新按钮、显示模式动作）、
  - `build_operator_bar(host)`（操作员 chip、归属标签、会话订阅）、
  - `build_workspace(host, scroll_area, instruction_layout)`（中央布局、右侧标签页/统计/文件面板、两层拆分器与宽度策略）、
  - `restore_session_state(host, ...)`（应用状态、QSettings 恢复、首个文件排队加载、快捷键映射）。
- **文件列表** → `labeling/file_list/`
  - `constants.py`（列号/列宽/行高/排序角色/状态色）、`table.py`（`FileTableWidget`/`FileTableItem`/`FileNameDelegate` + 状态图标）、`controller.py`（`FileListController`：行构建、按列排序、列宽持久化、缩略图、划分设置、右键菜单、选中同步、`fn_to_index`）。
  - `LabelingWidget` 保留 `fn_to_index` 属性与 `sort_file_list_by_column`/`set_file_column_visible`/`set_file_thumbnails_visible`/`set_file_split`/`remove_file_from_list`/`_clear_file_list` 等薄委托，既有调用方与测试入口不变。
- **操作员门禁与归属** → `labeling/operator/gate.py`
  - `OperatorGate`：浏览模式开关（动作启用/禁用、画布只读、标签控件交互、浮层刷新）、登录/登出/编辑前登录守卫、内容签名与 `author`/`modified_at` 盖章判据、`suppress` 与 `baseline` 状态；`OPERATOR_MODE_ACTIONS`/`OPERATOR_REQUIRED_ACTIONS` 随策略迁移，原模块再导出以保留测试与外部引用。
- **自动标注交接** → `labeling/auto_labeling_handoff.py`
  - `AutoLabelingHandoff`：过期结果过滤、替换/追加合并、关系/描述/flags/tags 回写、占位对象清理与“完成对象”补行兜底；`LabelingWidget` 保留同名薄委托（`new_shapes_from_auto_labeling` 等仍是信号目标）。
- **其他搬移**：拆分器 handle → `widgets/splitters.py`；`_measure_text_width`/`_format_label_list_text` → `utils/label_text.py`；`CHECKED_FIELD` → `schema.py`；`LabelingWidget.__init__` 从 2816 行降到 238 行。
- **版本**：纯内部重构，无用户可观察行为、配置键、数据格式、CLI 或模型契约变化，按 `docs/开始.md` §八.3 不升 fork 版本号，仍为 `4.3.2+fork.19`。

#### 7.3 涉及模块与文件

- 新增：`anylabeling/views/labeling/actions/{__init__,builder,menus}.py`、`file_list/{__init__,constants,table,controller}.py`、`operator/{__init__,gate}.py`、`auto_labeling_handoff.py`、`constants.py`、`widgets/workspace.py`、`widgets/splitters.py`、`utils/label_text.py`；
- 修改：`anylabeling/views/labeling/label_widget.py`（9507 → 5727 行，`LabelingWidget` 9118 → 5592 行、321 → 299 个方法）、`anylabeling/views/labeling/schema.py`（`CHECKED_FIELD`）；
- 测试：`tests/test_labeling/test_file_table.py`、`test_label_widget_metrics.py`（改从新模块导入列常量、图标函数）、`test_operator_gate.py`（改为直接驱动 `OperatorGate`）、`test_image_tags.py`、`test_classification_flags.py`（改为直接驱动 `AutoLabelingHandoff`）；
- 文档：`CHANGELOG-fork.md`、`docs/dev/CODE_STRUCTURE_REPORT.md`、`docs/开始.md`（T8 状态）。

#### 7.4 行为、接口与兼容性影响

- 用户可观察：无变化（菜单/工具栏/文件表/右侧栏/浏览模式/保存归属均保持原样；窗口结构快照逐项比对一致）。
- 代码接口：`from anylabeling.views.labeling.label_widget import FileTableWidget/FileTableItem/_create_file_status_icon/_measure_text_width/_format_label_list_text/LABEL_OPACITY` 不再可用，应分别从 `file_list`、`utils.label_text`、`constants` 导入；`OPERATOR_MODE_ACTIONS`/`OPERATOR_REQUIRED_ACTIONS` 仍在 `label_widget` 再导出。`LabelingWidget` 的公开/既有测试方法名保持不变。
- 新增服务类：`FileListController`、`OperatorGate`、`AutoLabelingHandoff`，以及 `actions.builder.build_actions`、`actions.menus.build_menus`、`widgets.workspace.*` 构建函数。

#### 7.5 实际验证内容

- 基线对比：在独立工作树（`git worktree`，HEAD `104ada3`）与重构后分别跑 `tests/test_labeling`，结果均为 **214 passed / 6 failed / 51 subtests passed**，失败集合逐条相同，均为重构前已存在、与本任务无关的用例（详见结构报告 §13）。
- 定向回归：`tests/test_labeling/test_file_table.py`、`test_browse_mode.py`、`test_operator_gate.py`、`test_image_tags.py`、`test_classification_flags.py`、`test_auto_labeling_finish.py`、`test_relations.py`、`test_label_file_author.py` 全部通过（除上述预存在失败）。
- 离屏真实 `MainWindow` 冒烟（`temporary/t8-analysis/smoke.py`）：建窗、导入 3 图文件夹、排序、划分写入、加载含 3 个图形的标注、勾选状态、缩略图开关、列显隐、`populate_mode_actions()` 全链路通过。
- 结构快照对比（`temporary/t8-analysis/snapshot.py`）：对基线树与重构后的窗口各导出一份控件树/动作表/菜单/工具栏/右侧标签/文件表列/拆分器/状态快照，差异仅为 `actions` 上新增的菜单专用动作条目与 canvas 对象地址，其余完全一致。
- 静态检查：自写 `symtable` 脚本核对各模块“函数引用了但模块内未定义”的全局名，`label_widget.py` 与全部新增模块均为 0 问题。
- **未执行**：真实桌面实机交互、打包/发布验证、全量 pytest（见下条环境限制）。
- **环境限制（需记录）**：本机 DSH Windows 沙箱下 pytest 会以 `mode=0o700` 创建 `temporary/runs/...` 临时目录，受限令牌无法列举该目录，表现为 `PermissionError [WinError 5]`/无输出退出（fork.17/18/19 均因此未跑成 pytest）。本次在本地测试运行时通过 `PYTHONPATH` 注入一个仅存在于 `temporary/` 的 `sitecustomize.py`（把 `os.mkdir` 的 mode 放宽为 0o777）绕开该限制，未修改仓库代码与 `tests/conftest.py`；此外部分测试文件在进程退出阶段会让解释器以 `0xC0000409` 结束（基线与重构后同样出现），因此全量套件改为按测试包分批执行并与基线逐包对比。

#### 7.6 已知限制与后续事项

- `LabelingWidget` 仍约 5592 行、299 个方法，剩余职责主要是标注数据编排（`add_label`/`load_shapes`/`save_labels`/`new_shape`）、属性面板（`update_attributes` 348 行）和缩放/导航；这些与画布、列表、标签对话框共享大量状态，本批未强拆，避免把耦合从“类内”变成“跨模块回环”。（第二阶段已继续拆分，见第 8 节。）
- 上帝类判定口径（用户 2026-11-19 明确）：**只有 `Canvas` 这类数千行、上百方法的类才算上帝类；1000–2000 行级类不算**。按此口径，本批未处理项只剩 `Canvas`（6269 行/216 方法）；此前列出的 `PPOCRTableBlockEditor`/`PointCloudDialog`/`VideoClassifierDialog`/`UltralyticsDialog`/`PPOCRDialog`/`ChatbotDialog`/`SettingsDialog`/`LabelConverter`/`ClassifierDialog`/`AutoLabelingWidget` 等 1000–3000 行级类不再按“上帝类”登记，只按普通维护风险对待。
- 拆分后需要维护的契约：`FileListController`/`OperatorGate`/`AutoLabelingHandoff` 的 host 属性表（各模块 docstring 已列出）；`actions.builder` 新增编辑类动作时必须同步 `OperatorGate` 的 `OPERATOR_REQUIRED_ACTIONS`。

### 8. 重构（不升版，T8 第二阶段）：继续拆分 `label_widget.py`

#### 8.1 背景与原因

第 7 节第一阶段把 `label_widget.py` 从 9507 行降到 5727 行，但 `LabelingWidget` 仍有约 5592 行、299 个方法：工具栏策略、属性面板、对象列表编辑、文件生命周期、缩放/导航、外观/状态、关系/过滤、绘制模式、专项窗口入口、引导标注循环、标注数据操作都还在同一个类里。用户 2026-11-19 要求继续拆分，并明确上帝类判定口径（见 7.6）。

#### 8.2 修改与关键细节

沿用第一阶段的“无状态控制器 + 宿主契约 + 同名一行委托”方式，本阶段新增 15 个模块：

| 模块 | 职责 | 行数 |
|---|---|---|
| `labeling/annotation_editor.py` | `new_shape`/`add_label`/`load_labels`/`load_shapes`/`load_flags`/`save_labels`/`remove_labels`/颜色映射 | 344 |
| `labeling/file_session.py` | 打开/上下一张/最近文件/另存/关闭/删除/导入与 `load_file` 加载流程 | 792 |
| `labeling/object_editor.py` | 对象选择、标签重命名/批量编辑、锁定/显隐、全选与过滤提示 | 576 |
| `labeling/canvas_navigation.py` | 缩放/平移状态、滚动条同步、fit、navigator | 421 |
| `labeling/actions/toolbar.py` | 工具栏短标签、显隐偏好、几何刷新、`populate_mode_actions`、右侧栏开关 | 256 |
| `labeling/widgets/attributes_panel.py` | 属性控件构建、取值、保存 | 554 |
| `labeling/status.py` | 标题/状态栏/脏标记/审核状态 | 291 |
| `labeling/appearance.py` | 主题/语言/快捷键/画布提示 | 264 |
| `labeling/label_filters.py` | 类别与分组过滤、显隐 | 243 |
| `labeling/shape_commands.py` | 剪贴板、删除、显隐、分组、合并 | 321 |
| `labeling/draw_modes.py` | 绘制/编辑模式状态机与登录门禁 | 212 |
| `labeling/special_workspaces.py` | 点云/PPOCR/VQA/分类/训练/管理器窗口入口 | 228 |
| `labeling/label_loop.py` | 引导标注循环（含 `_find_next_label_loop_shape` 迁入） | 184 |
| `labeling/relations.py` | 关系列表编辑与关系对话框 | 160 |
| `labeling/right_sidebar.py` | 右侧 tab 显隐与统计点击反筛 | 150 |

同时：`LABEL_COLORMAP` 移入 `labeling/constants.py`；`set_item_locked()` 移到 `widgets/label_list_widget.py`（`label_widget` 保留旧私有名别名）；`CHECKED_FIELD_PATTERN` 移入 `schema.py`。委托保持原签名（含 `set_zoom(value, *, pos=None)` 的关键字参数语义），服务在每次调用时以一行构造（无状态），因此既有的 fake 宿主测试无需改写。

#### 8.3 涉及模块与文件

- 新增：上表 15 个模块（其中 `actions/toolbar.py`、`widgets/attributes_panel.py` 为第一阶段目录的补充）；
- 修改：`anylabeling/views/labeling/label_widget.py`（5727 → 1782 行，`LabelingWidget` 5592 → 1703 行）、`constants.py`、`schema.py`、`widgets/label_list_widget.py`；
- 测试：`test_auto_training/test_dialog.py`、`test_labeling/test_classifier_window_lifecycle.py`、`test_labeling/test_label_widget_attributes.py` 的 `patch()` 目标改到新模块；其余测试未改（委托保持方法名与签名）。

#### 8.4 行为、接口与兼容性影响

- 用户可观察：无变化。窗口结构快照（控件树/动作表/菜单/工具栏/文件表/拆分器）与第一阶段后完全一致，仅 `actions` 上仍多出第一阶段引入的 12 个菜单专用动作属性。
- 代码接口：`label_widget` 仍可导入 `LabelingWidget` 与各委托方法；`_find_next_label_loop_shape`、`_measure_text_width`、`_format_label_list_text`、`OPERATOR_*_ACTIONS`、`_set_label_list_item_lock` 仍在原模块再导出（测试与旧调用可用）。新增 15 个类，宿主契约见各模块 docstring。
- 版本：仍为 `4.3.2+fork.19`，纯内部重构不升版。

#### 8.5 实际验证内容

- 基线工作树（HEAD `104ada3`）与重构后逐包 pytest 对比：失败集合一致（详见结构报告 §16；`tests/test_labeling` 仍为 214 passed / 6 failed，失败均为重构前已存在的测试债）。
- 离屏 `MainWindow` 冒烟脚本全链路通过；窗口结构快照与样式快照比对无新增差异。
- 静态检查：`compileall` 通过；自写 `symtable` 脚本确认各模块无“引用了但未定义/未导入”的全局名，`check_unused` 仅剩有意再导出项。
- **未执行**：真实桌面交互、打包、`black`/`flake8`（环境未安装，按规则未自行安装）。

#### 8.6 已知限制与后续事项

- `label_widget.py` 剩余 1782 行中约 150 个是 2 行委托；真实实现集中在 `__init__`（238 行）、`new_shape`（102）、`closeEvent`（66）、`update_thumbnail_display`（47）、`_update_ui_density`（36）、`update_file_menu`（32）等窗口外壳/事件/缩略图逻辑，继续拆需要处理 Qt 事件覆盖与 UI 密度联动，收益递减。
- 全项目按用户口径仅剩 `Canvas`（6269 行/216 方法）一个上帝类，未在本次处理。
- `black`/`flake8` 未运行，格式与 lint 需在装有 dev 依赖的环境执行 `pre-commit run --all-files`。

---

## 4.3.2+fork.18 — 2026-11-19

### 1. 背景与原因

fork.17 后实测确认三个问题：

- **暗色主题下可用/不可用工具几乎分不清**：禁用态文字用 `text_secondary`（`#aeaeb2`），与背景对比度 7.69:1，仍属"可读正文"；实测同一按钮只有 280/5671 像素不同，图标只从 `#f6f6f6` 淡到 `#d0d0d2`。反过来，提示"未登录"的 chip 用硬编码 `#6b6b6b`（对比度 3.19:1），几乎看不见——该暗的没暗、该亮的没亮。
- **未登录时点击创建/编辑工具毫无反馈**：`setEnabled(False)` 让 Qt 不触发 `triggered`，快捷键同时失效，无提示、无 tooltip 说明。
- **"浏览模式"名不副实**：`_apply_operator_gate()` 只锁按钮，画布仍可编辑。实测未登录时 `canvas.editing()` 为 `True`，`bounded_move_shapes()` 直接把矩形从 `(20,20),(120,120)` 移到 `(80,80),(180,180)`；真正的拦截点只有保存时弹登录，反馈错位。
- **画布右键菜单 29 项中有 13 项是工具模式切换**（11 创建 + 编辑对象 + 编辑笔刷），与工具栏完全重复，占菜单 45% 篇幅。

### 2. 修改与关键细节

- **主题禁用态**：`LIGHT/DARK` 新增 `text_disabled`（`#a1a1a6` / `#6e6e73`，暗色对比度 3.36:1）；`get_dark_palette()` 的 Disabled 文字角色改用该色；应用 QSS 增加 `QToolButton:disabled`，`QMenu::item:disabled` 改为该色；`ToolBar._apply_style()` 增加 `QToolBar QToolButton:disabled`（悬停/背景不再出现）。
- **图标禁用变体**：`utils/qt.py` 新增 `with_disabled_variant()`，按 32% 不透明度生成 `QIcon::Mode.Disabled` 位图，`new_action()` 统一套用；不再依赖 Qt 各平台差异很大的自动灰化。实测按钮文字由 `#f5f5f7` 变为 `#6e6e73`，平均墨色亮度 199.5 → 90.4。
- **登录 chip 可读**：新增主题色 `warning_text`（浅色 `#8A5300`、深色 `#FF9F0A`）——琥珀色在浅色背景上做文字对比度不足；`OperatorBar` 状态文字改为主题色、未登录用 `warning_text` 加粗（原来固定 `#6b6b6b`）；沿用已翻译文案（`Not logged in` / `Annotation mode: %s`），无需重建翻译资源。
- **浏览模式真正只读**：`Canvas` 新增 `set_read_only()/is_read_only()`，只读时拦截拖拽移动、顶点/边拖动、旋转手柄、长方体面拖动、双击加点/改标签、编辑笔刷；保留缩放、平移与选中，便于查看。`_apply_operator_gate()` 按登录状态切换。
- **工具可点并引导登录**：`OPERATOR_REQUIRED_ACTIONS` 拆分为 `OPERATOR_MODE_ACTIONS`（13 个模式类，浏览模式下保持可用）与 `OPERATOR_REQUIRED_ACTIONS`（16 个内容修改类，浏览模式下禁用）。入口统一在 `toggle_draw_mode()`（覆盖工具栏/菜单/数字快捷键/自动标注交接）、`toggle_brush_mode()`、`_enter_edit_mode_from_toolbar()` 用 `_ensure_operator_for_edit()` 拦截：未登录弹登录框，登录成功自动继续，取消则回退并提示 `浏览模式 — 编辑标注需要先登录`。
- **画布内常驻提示**：新增 `browse_mode_badge`（画布视口左上角浮层，警示色描边，可点击登录，登录后隐藏），不再只靠标题栏小字。
- **右键菜单精简**：`actions.menu` 改为 `actions.canvas_menu`，从 29 项减到 16 项——删除 13 个工具模式项，保留筛选×2、检查状态、编辑标签、关系×2、锁定对象、复制坐标、合并选择、复制/粘贴/删除/撤销/撤销上一点/删点，并用分隔线分组。
- **版本**：`4.3.2+fork.17` → `4.3.2+fork.18`。

### 3. 涉及模块与文件

- `anylabeling/views/labeling/utils/theme.py`（`text_disabled`、`warning_text`、Disabled 调色板、菜单/按钮禁用 QSS）；
- `anylabeling/views/labeling/utils/qt.py`（`with_disabled_variant`，`new_action` 套用）；
- `anylabeling/views/labeling/widgets/toolbar.py`（禁用态 QSS）；
- `anylabeling/views/labeling/widgets/operator_bar.py`（主题化状态色）；
- `anylabeling/views/labeling/widgets/canvas.py`（只读状态与手势拦截）；
- `anylabeling/views/labeling/label_widget.py`（动作分组、登录守卫、浏览提示浮层、右键菜单）；
- `tests/test_labeling/test_browse_mode.py`（新增）、`tests/test_labeling/test_operator_gate.py`（更新）；
- 结构报告、中文用户手册、版本号。

### 4. 行为、接口与兼容性影响

- 版本 `4.3.2+fork.17` → `4.3.2+fork.18`；无 QSettings 键、数据格式和 CLI 变化。
- 用户可观察：
  - 暗色下不可用工具明显变暗（文字与图标一起），未登录状态在画布左上角有琥珀色浮层，标题栏 chip 变琥珀色加粗；
  - 未登录点击创建/编辑工具会弹出登录框，登录后直接进入该工具；取消则保持原状并在状态栏说明；
  - 浏览模式画布只读：可缩放、平移、选中查看，但拖不动、改不了；
  - 画布右键菜单从 29 项减为 16 项，不再重复工具栏的工具模式。
- 代码接口：`Canvas.set_read_only()/is_read_only()` 新增；`LabelingWidget.OPERATOR_MODE_ACTIONS` 新增、`OPERATOR_REQUIRED_ACTIONS` 缩窄；`actions.menu` → `actions.canvas_menu`；`LabelingWidget._ensure_operator_for_edit()` 新增。

### 5. 实际验证内容

- 脚本化验证（`temporary/verify-browse/verify.py`，离屏真实 `MainWindow`）：
  - 未登录：`canvas.is_read_only()==True`、13 个模式动作 `isEnabled()==True`、`delete` 为 `False`、浮层可见（370×34，左上角 12,12）、chip 文案与警示色正确；
  - 取消登录：画布保持 `Editing`，状态栏显示"浏览模式 — 编辑标注需要先登录"；
  - 只读拖拽：`bounded_move_shapes()` 返回 `False`，点位不变；
  - 登录成功后：画布进入 `Drawing`、`delete` 恢复、浮层隐藏、拖拽生效；
  - 右键菜单：16 项，13 个模式项全部消失，`Copy Object`/`Paste Object` 保留；
  - 主题：启用文字 `#f5f5f7`（15.63:1）vs 禁用 `#6e6e73`（3.36:1），渲染墨色 199.5 → 90.4；
  - `tests/test_labeling/test_browse_mode.py` 中 6 个不依赖 fixture 的用例逐个执行通过。
- **未执行**：pytest 全量/定向回归——本机沙箱拒绝为 pytest 临时目录提权（命令被拒），因此没有跑成；`tests/test_labeling/test_browse_mode.py` 的 window fixture 用例与其余套件需要在有权限的环境补跑。
- 未执行：真实 Windows 下目视暗色对比、浮层位置与中文文案（翻译 `.qm` 未重建，新增文案均复用已翻译字符串，故不受影响）。

### 6. 已知限制与后续事项

- 浏览模式下仍允许选中对象（便于查看属性），因此 `复制` 等只读操作可用；内容修改类命令禁用。
- 浏览模式下自动标注单图推理仍可触发，写入时由保存守卫要求登录；如需完全禁止，应单独收口。
- 浮层固定在画布左上角，窗口极窄时按视口宽度收窄；与缩放/导航器等浮层同层，未来新增左上角浮层需注意叠放顺序。
- 未重建 `.qm`/`resources.py`：本次未新增界面文案，全部复用已有翻译。

## 4.3.2+fork.17 — 2026-11-18

### 1. 背景与原因

fork.16 把放不下的工具收进自绘弹层，并把 QToolBar 内置“»”改成 28×30 的小箭头。实测后用户明确否定：

- 取消“显示工具标签”后，工具之间出现无法点击的黑色方块；
- “⌵/»”被改小，点击面积反而不如改前；
- 弹层仍是“弹出项目列表”，不是用户要的整条工具栏滚动；顶部停靠横向、左侧停靠纵向都应像可滚动窗格一样访问全部工具。

### 2. 修改与关键细节

- **移除工具栏分隔项**：`populate_mode_actions()` 不再把 `actions.tool` 中的 `None` 分隔符插入工具栏。此前竖向工具栏把分隔符渲染成 26×30 的深色空块，关闭标签后尤其明显；现在工具按钮连续排列。
- **整条工具栏改为可滚动窗格**：`MainWindow._install_toolbar()` 用 `QDockWidget`（`ToolsDock`，隐藏标题栏、禁用浮动/关闭）承载 `ToolBarScrollArea`（`ToolsToolBarScroll`），滚动区内放原有 `ToolsToolBar`；`_apply_toolbar_area()` 按停靠位置切换工具栏方向与滚动条策略：
  - 左侧：`Vertical`，垂直滚动条按需显示，水平滚动条关闭；
  - 顶部：`Horizontal`，水平滚动条按需显示，垂直滚动条关闭。
- **滚动区域尺寸**：`ToolBarScrollArea.sizeHint()/minimumSizeHint()` 只按工具栏自然宽度（左侧）或高度（顶部）加滚动条宽度申请停靠尺寸，避免顶部停靠要求整条工具栏的超宽尺寸、或左侧停靠要求整条工具栏的高度。
- **滚轮**：`ToolBarScrollArea.wheelEvent()` 把滚轮转给当前方向的可滚动条，鼠标停在工具按钮上也能滚动。
- **移除 fork.16 的弹层与自绘箭头**：删除 `_toolbar_more_icon()`、`_install_toolbar_overflow()`、`_show_toolbar_overflow()`，不再断开 Qt 内置 extension 按钮信号，也不再缩成 28×30；空间不足时由滚动条访问全部工具，无需末端按钮。
- **几何同步**：新增 `LabelingWidget.refresh_toolbar_geometry()`，在 `populate_mode_actions()`、`apply_toolbar_preferences()` 和切换停靠方向后调用 `adjustSize()` 并刷新滚动区，保证标签开关、显隐过滤和方向切换后内容尺寸正确。
- **停靠契约**：`ToolsToolBar` 仍是带原 objectName 的 `QToolBar`，但由 `ToolsDock` 承载，`setMovable(False)`、`setFloatable(False)`；左右/顶部切换仍走 `dock_toolbar()` 与视图菜单，持久化键仍是 `window/toolbar_area` 与 `window/toolbar_visible`，`window/toolbar_area_scheme` 仍为 3。

### 3. 涉及模块与文件

- `anylabeling/views/mainwindow.py`（`QDockWidget` + 滚动区安装、方向/滚动条策略、停靠与显隐）；
- `anylabeling/views/labeling/widgets/toolbar.py`（`ToolBarScrollArea` 尺寸、滚轮）；
- `anylabeling/views/labeling/label_widget.py`（分隔符过滤、几何刷新、移除弹层与箭头）；
- `tests/test_widgets/test_mainwindow_state.py`、`tests/test_labeling/test_file_table.py`（停靠断言改为 dock area，新增加滚动/无分隔块回归）；
- 结构报告、中文用户手册与版本号。

### 4. 行为、接口与兼容性影响

- 版本 `4.3.2+fork.16` → `4.3.2+fork.17`；无配置键、数据格式或 CLI 变化。
- 用户可观察：关闭“显示工具标签”后不再出现黑色空块；工具不再被末端小箭头折叠，左侧用垂直滚动条、顶部用水平滚动条访问全部工具；滚轮可滚动工具栏。
- 代码接口：`MainWindow` 不再把 `ToolsToolBar` 直接 `addToolBar()`；需要读取停靠位置的外部代码应使用 `window.findChild(QDockWidget, "ToolsDock")` 与 `dockWidgetArea()`。`window/toolbar_area` 值仍为 `left`/`top`。
- 设置页“工具栏”仍是即时生效，无重置/保存按钮。

### 5. 实际验证内容

- 离屏几何探针（1400×900，`temporary/fork4-toolbar-scroll/probe.py`）：
  - 左侧标签模式：dock 137px 宽，工具栏 119×2467，垂直滚动条 `maximum=1621`，水平 `maximum=0`；图标模式：dock 52px，工具栏 34×1438，垂直 `maximum=592`，水平 `maximum=0`；
  - 顶部标签模式：dock 高 70px，工具栏 4301×53，水平 `maximum=2903`，垂直 `maximum=0`；图标模式：水平 `maximum=220`，垂直 `maximum=0`；
  - 两种方向、两种标签模式均无可见 `qt_toolbar_ext_button`，工具栏动作中无 separator。
- pytest：`tests/test_widgets`、`tests/test_labeling/test_file_table.py`、`tests/test_settings` 共 138 passed、1 skipped、11 subtests passed；新增 `test_toolbar_scrolls_the_whole_tool_set` 通过。
- 未执行：真实 Windows 窗口中的鼠标滚轮/拖动滚动、暗色主题滚动条目视确认、全量 pytest 与打包。

### 6. 已知限制与后续事项

- `QDockWidget` 会占用停靠区并显示分隔线；标题栏已用空 widget 替换，但不同平台边框可能有 1–2px 差异。
- 左侧宽度按最长按钮计算，较长的英文短标签会把工具栏拉宽；顶部标签模式内容总宽较大，需要横向滚动。
- 滚动区的尺寸提示加入 4px 余量，以抵消 QToolBar 样式内边距与滚动条宽度差；更换 Qt 主题/样式后应回归一次。
- 滚轮事件依赖子控件不消费 wheel；如某类工具按钮自行处理滚轮，需要再补事件过滤。
- 未做工具分组或搜索，工具栏很长时仍需滚动查找。

## 4.3.2+fork.16 — 2026-11-18

### 1. 背景与原因

fork.15 后实测发现：取消“显示工具标签”时设置/快捷键仍显示文字；设置页出现两个无名称 checkbox；点击工具栏“»”后 QMenu 因高度超屏被拆成多列并排，画面错乱；暗色主题下“»”几乎看不见。

### 2. 修改与关键细节

- **标签开关覆盖设置/快捷键**：`_apply_toolbar_short_labels()` 根据 `_toolbar_show_labels` 同时切换这两个 QWidgetAction 按钮的 `ToolButtonIconOnly` 与空文本（标签模式下恢复“设置/快捷键”）。
- **无名 checkbox**：`toolbar_entries()` 跳过文本为空的动作（设置/快捷键的 QWidgetAction），设置页不再生成空白项；当前列出 43 个可切换工具。
- **折叠改为可滚动弹层**：断开 QToolBar 内置 extension 按钮的 `clicked/pressed` 连接，改为自绘 `QFrame` 弹层（`Qt.Popup` + `QScrollArea`，240×最多 520），内部按单列列出放不下的工具，超出时用垂直滚动条而不是多列并排；点击项触发动作并关闭弹层。
- **暗色主题可见性**：extension 按钮改为自绘 16px 主题色箭头（水平向下、垂直向右），固定 28×30，并设置 tooltip“更多工具”；不再依赖 Qt 默认箭头颜色。

### 3. 涉及模块与文件

- `anylabeling/views/labeling/label_widget.py`（短标签开关、空项过滤、overflow 弹层、箭头图标）；
- `anylabeling/views/mainwindow.py`（停靠后重新安装 overflow 处理）；
- 文档与版本号。

### 4. 行为、接口与兼容性影响

- 版本 `4.3.2+fork.15` → `4.3.2+fork.16`；无配置键/数据契约变化。
- 用户可观察：关闭标签后设置/快捷键变为纯图标；设置页无空白项；点击“»”弹出单列可滚动列表；暗色下箭头清晰。

### 5. 实际验证内容

- 离屏冒烟：`apply_toolbar_preferences(False, set())` 后设置/快捷键均为 `ToolButtonIconOnly` 且文本为空；`toolbar_entries()` 返回 43 项且无空文本；点击 extension 生成 `QFrame` 弹层（240×520），无可见 `QMenu`（内置菜单已被断开）。
- `tests/test_settings`：48 passed、1 skipped；`tests/test_widgets`：72 passed（另 1 个既有 canvas 节流用例时序敏感失败，单跑通过）；模块单测 17 passed。
- 未执行：真实暗色主题下的箭头/弹层目视确认（逻辑与配色已按主题设置）。

### 6. 已知限制与后续事项

- 弹层为单列滚动，未做搜索框；工具很多时滚动仍较长。
- 断开 QToolBar 内置 extension 连接属于 Qt 内部行为依赖，升级 Qt 后需回归一次。
- 设置页仍为即时生效，无“重置/保存”按钮。

---

## 4.3.2+fork.15 — 2026-11-18

### 1. 背景与原因

fork.14 的工具栏在顶部停靠时仍会被 QToolBar 压缩，四字标签变成“…”或被挤压；左侧也仍靠滚动/溢出隐藏工具。用户要求：带文字的工具不得压缩，放不下的应收进“»/⌵”折叠菜单；并在设置窗口增加“工具栏”页控制各工具显隐与标签开关。

### 2. 修改与关键细节

- **禁止压缩**：每个工具按钮按内容计算并 `setFixedSize`；`ToolBar` 的 QSS `min-width` 在标签模式下为 70px、图标模式下为 26px。放不下的项由 QToolBar 自带的 extension 按钮（“»”）折叠，不再挤压文字。
- **设置页“工具栏”**：`SETTINGS_PRIMARY_ORDER` 增加 `Toolbar`（位于“常规”之后），页面提供：
  - “显示工具标签”开关（关闭后切回纯图标，可显示更多工具）；
  - “全选”；
  - 按工具逐项勾选显示/隐藏（列出全部 45 项，含名称与动作描述 tooltip）；
  - 修改即时生效并写入 `QSettings`：`toolbar/show_labels`、`toolbar/hidden_actions`。
- 工具栏布局在 `LabelingWidget.populate_mode_actions()` 中按隐藏键过滤；隐藏键使用 `actions.tool` 的索引字符串，避免依赖翻译后的名称。
- 设置页没有沿用快捷键页的底部“重置/保存”按钮：本页采用即时生效（与常规/画布页一致的自动保存语义）。

### 3. 涉及模块与文件

- `anylabeling/views/labeling/widgets/toolbar.py`（标签模式 QSS/尺寸）；
- `anylabeling/views/labeling/label_widget.py`（过滤、设置读写、按钮固定尺寸）；
- `anylabeling/views/labeling/settings/schema.py`、`dialog.py`（新页面与渲染）；
- `tests/test_settings/test_schema.py`（主分类顺序）；
- 翻译与文档。

### 4. 行为、接口与兼容性影响

- 版本 `4.3.2+fork.14` → `4.3.2+fork.15`；无数据契约变化。
- 新增 QSettings 键 `toolbar/show_labels`、`toolbar/hidden_actions`（应用级，不随项目）。
- 设置窗口新增“工具栏”页；工具显隐与标签开关立即生效，重启后保持。
- 原有“工具栏停靠到顶部/左侧”与显隐逻辑不变。

### 5. 实际验证内容

- 顶部停靠几何：按钮宽度 78–103px（不再 34px），extension 按钮可见；左侧停靠宽度 119px，标签单行。
- 离屏冒烟：设置页列出 45 个工具项；“显示工具标签”关闭后工具栏切到 `ToolButtonIconOnly`；取消勾选一项后工具栏动作数 51→50。
- `tests/test_settings`：48 passed、1 skipped；`tests/test_widgets`：72 passed（另 1 个既有 canvas 节流用例时序敏感失败，单跑通过）；模块单测 17 passed。
- 未执行：真实鼠标逐个悬停确认；真实点击设置页并重启验证持久化（本会话 QSettings 写入受沙箱限制返回 AccessError，代码路径与读取已验证）。

### 6. 已知限制与后续事项

- 设置页采用即时生效，没有“重置/保存”按钮（与用户草图不同）；如需要可再加“恢复默认（全部显示 + 标签开）”。
- 隐藏项仍保留快捷键与菜单入口，只是不在工具栏出现。
- 英文界面短标签仍可能同名；中文为 4 字截断。

---

## 4.3.2+fork.14 — 2026-11-18

### 1. 背景与原因

fork.13 在真实窗口里仍有三处问题：工具栏短标签在顶部停靠时被压缩成多行且超出四字；`window/toolbar_area_scheme` 已被早期探针写成 2，导致“默认左侧”的一次性迁移没有生效；设置/快捷键两个工具没有文字说明。

### 2. 修改与关键细节

- **强制迁移到左侧**：`window/toolbar_area_scheme` 版本号升到 3，旧配置（包括已被写成 2 的）会再迁移一次到 `left`；迁移后用户手动切换仍正常持久化。
- **短标签与按钮尺寸**：`QToolButton` 使用内容宽度（左侧停靠时约 67px），标签保持一行且不超过四个字符；`QAction.iconText` 承载短标签，`QToolButton` 的 tooltip 保持为完整动作描述（悬停提示不再丢失）。
- **设置/快捷键**：两个 QWidgetAction 按钮改为 `ToolButtonTextUnderIcon`，显示“设置”“快捷键”，固定 56×46，并按当前主题重设图标；它们被移动到工具栏顶部，避免被溢出菜单隐藏。
- 工具按钮的完整名称仍在 tooltip 与菜单中。

### 3. 涉及模块与文件

- `anylabeling/views/labeling/label_widget.py`（短标签、设置/快捷键按钮、工具顺序）；
- `anylabeling/views/mainwindow.py`（迁移版本号）；
- 文档与版本号。

### 4. 行为、接口与兼容性影响

- 版本 `4.3.2+fork.13` → `4.3.2+fork.14`；无配置键/数据契约变化。
- 用户可观察：首次启动强制左侧停靠；按钮文字单行且 ≤4 字；设置/快捷键有文字；悬停仍显示完整说明。

### 5. 实际验证内容

- 离屏冒烟（中文）：工具栏区域为左侧；按钮文本均 ≤4 字；`设置`/`快捷键` 文本与图标齐全；`save` 按钮 tooltip 为“将标签保存到文件”。
- 真实 Windows 截图：左侧工具栏单行显示“向后切换 / 下一张图 / 保存 / 创建矩形 …”，设置与快捷键位于顶部。
- `tests/test_widgets`：72 passed（另 1 个既有 canvas 节流用例时序敏感失败，单跑通过）；模块单测 17 passed。
- 未执行：真实鼠标悬停逐个确认 tooltip（离屏已断言对象属性）。

### 6. 已知限制与后续事项

- 左侧工具栏约 45 项，带文字后一屏仍放不下，超出部分在工具栏末端展开菜单中；如需全部可见需分组/两列/滚动侧栏。
- 英文短标签取首词，仍可能出现同名；中文为 4 字截断。

---

## 4.3.2+fork.13 — 2026-11-18

### 1. 背景与原因

用户反馈：状态栏右下角仍会单独弹出坐标；工具栏没有文字说明、难以理解；文件列表缺少导入入口；工具栏默认停在顶部。按 `docs/开始.md` 的约定，本轮只改界面与交互，不触碰数据契约。

### 2. 修改与关键细节

#### 2.1 去掉右下角重复坐标

- `show_shape` / `show_line_length` / `show_circle_radius` 的状态提示不再带 `X:/Y:` 前缀，只保留尺寸/长度/半径信息；坐标统一由状态栏左侧的 `[x,y|路径]` 显示。
- 状态栏布局调整为“消息标签在左、文档标签紧随其后（占剩余宽度）”，消息不再被推到右下角。

#### 2.2 工具栏文字说明

- 工具栏改为 `ToolButtonTextUnderIcon`，每个按钮显示不超过四个字符的短标签：CJK 文本取前 4 个字符，ASCII 文本取首个单词；`QAction.iconText` 承载短标签，完整名称仍在悬停提示与菜单中。
- `ToolBar` 的 QSS 由固定 `width/height` 改为 `min-width/min-height`，按钮按内容自适应高度。

#### 2.3 文件列表导入

- 文件列表右键菜单新增“单文件导入 / 文件夹导入”（空列表时也可用）。
- 搜索框右侧新增“+”按钮，下拉同样两项；单文件导入追加到当前列表，文件夹导入按目录重建列表。
- 工具栏中的“打开文件夹”按钮移除（“文件”菜单与快捷键仍保留）。

#### 2.4 工具栏默认左侧停靠

- `window/toolbar_area` 默认值改为 `left`，并增加一次性迁移标记 `window/toolbar_area_scheme`：旧配置首次升级时切到左侧，之后用户手动选择的停靠位置继续生效。

### 3. 涉及模块与文件

- `anylabeling/views/mainwindow.py`（默认停靠迁移、状态栏消息顺序）；
- `anylabeling/views/labeling/label_widget.py`（短标签、导入对话框/按钮/右键菜单、坐标提示）；
- `anylabeling/views/labeling/widgets/toolbar.py`（按钮尺寸策略）；
- `tests/test_widgets/test_mainwindow_state.py`（默认停靠断言）；
- 翻译与文档。

### 4. 行为、接口与兼容性影响

- 版本 `4.3.2+fork.12` → `4.3.2+fork.13`；无配置键、数据格式、门禁规则变化。
- 用户可观察：右下角不再重复显示坐标；工具栏按钮带短文字；文件列表可导入；工具栏默认在左侧。
- `window/toolbar_area` 的旧值会被一次性迁移为 `left`；迁移后用户再手动切换仍按选择持久化。

### 5. 实际验证内容

- 真实 Windows 截图：左侧工具栏显示中文短标签（向后切换/下一张图/上一张图/保存/删除文件/创建矩形…），搜索框右侧出现“+”按钮，状态栏左下角为 `[x,y|路径]`。
- 离屏冒烟（中文翻译）：工具栏按钮文本均 ≤4 字；导入菜单两项为“单文件导入/文件夹导入”；`show_shape` 提示为 `H: 10, W: 20`（不含坐标）；工具栏区域为 `LeftToolBarArea`。
- `tests/test_widgets`：**71 passed**（另 1 个既有 canvas 节流用例时序敏感失败，单独运行通过）；模块单测 17 passed。
- 未执行：真实点击“单文件导入/文件夹导入”并选择文件（对话框为模态，自动化会阻塞）；全量测试。

### 6. 已知限制与后续事项

- 左侧工具栏项目较多（约 45 个），带文字后无法在一屏内全部显示，超出部分由 Qt 工具栏末端的展开按钮收纳；如果需要，下一步可做分组、两列或可滚动侧栏。
- 英文界面短标签取首个单词，可能出现同名（如多个 “Create”），完整名称见悬停提示；中文界面为 4 字截断，仍可能有近义截断。
- “单文件导入”与“打开文件”的区别：前者追加到当前列表，后者清空列表并打开单个文件。

---

## 4.3.2+fork.12 — 2026-11-18

### 1. 背景与原因

fork.11 把状态标签放在状态栏右侧、且只显示文件名；用户要求改为**完整路径**并放回**左侧**，同时避免提示文字把它顶掉。

### 2. 修改与关键细节

- 新增 `DocumentStatusBar(QStatusBar)`：文档标签 `[x,y|完整路径]` 作为左侧普通控件；临时消息改写入旁边的独立 `message_label`，不再调用基类的 `showMessage`，因此文档标签始终可见。
- 新增 `_StatusTipFilter`：`QMainWindow` 在 C++ 层处理 `QStatusTipEvent` 时会直接调用原生 `QStatusBar::showMessage()`（绕过 Python 覆写），该过滤器在应用层拦截状态提示并转发到自定义消息标签，避免文档标签被隐藏。
- 状态文本改为 `[x,y|绝对路径]`；未移动鼠标时为 `[-,-|绝对路径]`。
- 移除启动时常驻的应用描述消息（它会和文档信息并排显示、显得拥挤）；版本与描述仍可在“帮助/关于”查看。

### 3. 涉及模块与文件

- `anylabeling/views/mainwindow.py`（`DocumentStatusBar`、状态提示过滤器、状态栏构建）；
- `anylabeling/views/labeling/label_widget.py`（完整路径）；
- 文档与结构报告。

### 4. 行为、接口与兼容性影响

- 版本 `4.3.2+fork.11` → `4.3.2+fork.12`；无配置键、数据格式与门禁规则变化。
- 用户可观察：状态栏左侧显示 `[x,y|完整路径]`；状态提示出现在其右侧且不遮挡；启动时状态栏不再有常驻描述文字。

### 5. 实际验证内容

- 真实 Windows 截图：左下角显示 `[123,456|E:\project\data\...\1_0_0_00271_3375.tif]`，位于状态栏左侧。
- 离屏冒烟：`[-,-|…a.tif]` → 模拟鼠标后 `[12,35|…a.tif]`；`showMessage("tip")` 后文档标签仍可见；发送 `QStatusTipEvent` 后消息进入 `message_label` 且文档标签仍在。
- 模块单测 17 passed；`tests/test_widgets` 72 passed（另 1 个既有时序敏感用例失败，单独运行通过）。
- 用户已实机确认 fork.9 的四边/四角拖拽缩放正常。

### 6. 已知限制与后续事项

- 完整路径较长时会按标签宽度裁切显示（标签不会撑宽窗口），悬停不显示 tooltip；如需省略中间/尾部可再调整。
- x/y 在鼠标移动时实时刷新，未做节流。

---

## 4.3.2+fork.11 — 2026-11-18

### 1. 背景与原因

fork.10 后用户反馈：状态栏的坐标/文件名重叠且有时文件名消失；标题栏左上角没有软件图标；并提醒这些修复应落在可复用无边框窗口模块内，而不是只在主程序里打补丁。

### 2. 修改与关键细节

#### 2.1 状态栏改为 `[x,y|filename]`

- 画布新增 `mouse_position_changed(x, y)` 信号（鼠标离开时发 `-1,-1`）；`LabelingWidget` 记录光标位置并刷新状态。
- 状态栏右侧改为**常驻控件**（`addPermanentWidget`），不再被 `showMessage` 的临时提示隐藏，解决“有时文件名消失”；左侧提示区保持原样，互不重叠。
- 文本格式固定为 `[x,y|文件名]`（未移动鼠标时为 `[-,-|文件名]`）；去掉验收状态、图片尺寸与序号（序号已在文件列表中）。

#### 2.2 标题栏软件图标

- `FramelessWindow` 初始化时读取 `QApplication.windowIcon()`，非空则同步到标题栏左侧图标位；宿主只需按常规设置应用图标。
- 实测截图：图标位于软件名左侧（16×16，垂直居中）。

#### 2.3 模块边界复核（用户第 1 点）

逐项确认 fork.7–fork.10 的无边框相关修复均在 `anylabeling/widgets/frameless/` 内，宿主代码只做参数与内容装配：

| 能力 | 位置 |
|---|---|
| `nativeEvent` 不调用 super（启动崩溃） | `frameless/window.py` |
| `WS_THICKFRAME` + `WM_NCCALCSIZE` 边缘缩放、DPI 换算 | `frameless/window.py` |
| 菜单项垂直内边距（标题栏对齐） | `frameless/theme.py` |
| 标题栏右键“菜单显示”子菜单 | `frameless/title_bar.py` |
| 自绘标题与系统标题分离（`set_display_title`） | `frameless/window.py` |
| 默认沿用应用图标 | `frameless/window.py` |
| 标题栏按钮槽位 / `add_title_widget` | `frameless/window.py`、`title_bar.py` |

宿主侧仅保留与业务相关、本就不属于窗口 chrome 的部分：状态栏内容、侧栏/图片标签开关、菜单项创建。新增 2 个模块级回归用例（显示标题独立于系统标题、默认应用图标生效），模块单测 17 passed。

#### 2.4 关于“验收状态”

核对 `docs/开始.md`、设计书、数据库讨论稿与用户手册：**没有文档要求移除验收状态**，用户手册第 6 章仍把它作为功能记录。因此本次只把验收状态从状态栏文本中去除，功能本身（画布左下角面板与快捷键）保留；如需彻底下线，应作为独立需求走文档与数据契约变更流程。

### 3. 涉及模块与文件

- `anylabeling/widgets/frameless/window.py`（默认图标、显示标题）；
- `anylabeling/views/labeling/widgets/canvas.py`（鼠标位置信号）；
- `anylabeling/views/labeling/label_widget.py`（状态文本、坐标跟踪）；
- `anylabeling/views/mainwindow.py`（常驻状态标签、初始提示）；
- `tests/test_widgets/test_frameless_window.py`、`examples/frameless_demo.py`；
- 文档与结构报告。

### 4. 行为、接口与兼容性影响

- 版本 `4.3.2+fork.10` → `4.3.2+fork.11`；无配置键、数据格式与门禁规则变化。
- 用户可观察：状态栏显示 `[x,y|文件名]`，不再被提示文字覆盖；标题栏左上角出现软件图标。
- 画布新增 `mouse_position_changed` 信号，属新增 API，不影响既有连接。

### 5. 实际验证内容

- 真实 Windows 截图：标题栏图标 16×16 显示在软件名左侧；菜单项高度 28px。
- `MainWindow` 离屏冒烟：状态文本在假文件下为 `[-,-|a.tif]`，模拟鼠标移动后为 `[12,35|a.tif]`；`showMessage` 后状态标签仍可见；标题栏图标未被隐藏。
- 模块单测 **17 passed**（新增显示标题独立、默认图标两例）。
- 未执行：真实桌面交互与全量测试。

### 6. 已知限制与后续事项

- 状态栏文件名只显示基名（不含目录），目录信息仍在任务栏标题与文件列表中；如需完整路径可在后续按需调整。
- x/y 为图像坐标，画布缩放/平移时随之换算；未做节流，高频移动时每秒多次刷新 QLabel。
- fork.9 的边缘缩放仍未经真实鼠标拖拽验证。

---

## 4.3.2+fork.10 — 2026-11-18

### 1. 背景与原因

fork.9 的标题栏把完整图片路径、验收状态、尺寸和序号都画在软件名后面，既挤压菜单、又不美观；用户还纠正了第二个开关的含义：它不是“底部调整面板”，而是“显示/隐藏图片标签”。

### 2. 修改与关键细节

- **标题栏只显示软件名**：`FramelessWindow` 新增 `set_display_title()`，`setWindowTitle()` 仍更新操作系统窗口标题（任务栏/Alt+Tab 保留完整文件信息），但自绘标题栏固定显示 “X-AnyLabeling”。
- **文档信息移入状态栏**：`MainWindow` 状态栏左侧新增可选中的 `document_status_label`；`LabelingWidget` 在 `update_progress_title()` 中同步更新，内容为“绝对路径 + 未保存标记 + 验收状态 + 尺寸 + 序号”。临时提示（如空格平移提示）仍通过 `showMessage` 短暂覆盖，消失后恢复。
- **第二个开关改为图片标签**：标题栏最小化左侧现在是“右侧边栏开关 + 图片标签开关”；图片标签按钮直接使用既有 `show_image_tags` 动作（`setDefaultAction`），勾选状态、图标与快捷键保持一致。该动作已从工具栏移除，仅在“视图”菜单与标题栏保留；原生窗口模式下两个按钮仍回落到工具栏。
- 删除不再使用的“底部调整面板开关”及其偏好、翻译条目。

### 3. 涉及模块与文件

- `anylabeling/views/labeling/label_widget.py`（标题/状态文本拆分、图片标签按钮、移除底部面板开关）；
- `anylabeling/views/mainwindow.py`（`set_display_title`、状态栏文档标签）；
- `anylabeling/widgets/frameless/window.py`（显示标题与系统标题分离）；
- `anylabeling/resources/translations/*`（删除 obsolete 条目并重建）；
- 文档与结构报告。

### 4. 行为、接口与兼容性影响

- 版本 `4.3.2+fork.9` → `4.3.2+fork.10`；无配置键、数据格式与门禁规则变化。
- 用户可观察：标题栏简洁（仅软件名）；状态栏左侧显示当前图片路径/状态/尺寸/序号；标题栏第二个按钮控制图片标签显隐。
- 原生窗口模式下两个按钮回到工具栏，“图片标签”动作的快捷键与菜单项不变。

### 5. 实际验证内容

- 真实 Windows 截图：标题栏仅 “X-AnyLabeling”，菜单与标题同一水平线；两个开关位于最小化左侧；工具栏不再有图片标签按钮。
- `MainWindow` 离屏冒烟：标题栏显示名恒为软件名；`setWindowTitle` 带文件信息时标题栏不变；状态栏在设置假图片后包含 `a.tif` 与 `640x480`；图片标签按钮点击可切换 `image_tags_widget` 可见性；原生模式两个按钮父控件为工具栏。
- `tests/test_widgets/test_frameless_window.py`：15 passed。
- 未执行：真实桌面交互（拖动/缩放/点击开关）与全量测试。

### 6. 已知限制与后续事项

- 状态栏临时消息会短暂覆盖文档信息（Qt `showMessage` 语义），消息结束后恢复。
- 图片标签按钮继承既有动作的图标（panel-down/up），与标题栏自绘侧栏图标风格略有差异；如需统一可再自绘。
- fork.9 的边缘缩放仍未在本会话完成真实鼠标验证，需实机确认。

---

## 4.3.2+fork.9 — 2026-11-18

### 1. 背景与原因

fork.8 可正常启动后，用户在真实桌面上验证无边框窗口，反馈四项问题：边缘无法拖动缩放；右侧边栏/底部调整面板的开关不在标题栏；菜单文字顶到标题栏上沿；标题栏右键菜单没有菜单显隐项。

### 2. 修复与关键细节

#### 2.1 窗口边缘缩放

- 根因：无边框窗口的样式里没有 `WS_THICKFRAME`（实测样式 `0x860b0000`）。`WM_NCHITTEST` 虽然返回 `HTLEFT/HTTOP…`，但 Windows 只为带 sizing frame 的窗口启动缩放循环。
- 修复：`FramelessWindow.showEvent()` 中为无边框窗口补 `WS_THICKFRAME` 并 `SetWindowPos(FRAMECHANGED)`；`nativeEvent()` 增加 `WM_NCCALCSIZE` 处理（`wParam=TRUE` 时返回 0），让客户区重新覆盖整窗，避免出现原生边框。
- 同时修正高 DPI：`WM_NCHITTEST` 的屏幕坐标按 `devicePixelRatio` 换算到逻辑坐标后再 `mapFromGlobal`；最大化/全屏时返回 `HTCLIENT`，避免在边缘误触缩放。

#### 2.2 侧栏与底部面板开关

- 标题栏最小化按钮左侧新增两个自绘图标按钮：右侧边栏开关、底部调整面板开关。图标用 `QPainter` 绘制（面板框 + 填充），无需新增资源，填充表示面板当前可见。
- 侧栏按钮不再放进工具栏的 `QWidgetAction`；原生窗口模式仍会自动回落到工具栏，避免功能丢失。
- 底部面板开关新增偏好 `_adjustment_panel_enabled`：关闭后加载新图片不再自动弹出调整面板，重新开启后恢复。

#### 2.3 菜单垂直对齐

- 菜单项 QSS 垂直内边距 `2px → 6px`，菜单项高度由 20px 增至 28px，在 30px 标题栏内与软件名、窗口按钮同一水平线；标题栏高度不变。

#### 2.4 标题栏右键菜单的菜单显隐

- 标题栏右键菜单新增“菜单显示”子菜单，逐项勾选顶层菜单的显示/隐藏，与“右键菜单栏空白处”的能力一致；隐藏后快捷键仍有效。
- 右键菜单构建抽成 `build_context_menu()`，便于单测。

### 3. 涉及模块与文件

- `anylabeling/widgets/frameless/window.py`（缩放样式与 NCCALCSIZE、DPI）；
- `anylabeling/widgets/frameless/theme.py`（菜单项内边距）；
- `anylabeling/widgets/frameless/title_bar.py`（“菜单显示”子菜单、`build_context_menu()`）；
- `anylabeling/views/labeling/label_widget.py`（面板开关、自绘图标、底部面板偏好）；
- `anylabeling/views/mainwindow.py`（标题栏/工具栏落位）；
- `anylabeling/resources/translations/*`（新增 “Toggle adjustment panel”“Menus”）；
- `tests/test_widgets/test_frameless_window.py`、文档若干。

### 4. 行为、接口与兼容性影响

- 版本 `4.3.2+fork.8` → `4.3.2+fork.9`；无配置键、数据格式与门禁规则变化。
- 用户可观察：窗口四边/四角可拖动缩放；标题栏多两个面板开关；菜单文字与标题垂直居中；标题栏右键可显隐菜单。
- 原生窗口模式（`frameless: false`）下两个面板开关回到工具栏，其余不变。

### 5. 实际验证内容

- 真实 Windows 平台截图核对：菜单项高度 28px、标题栏 30px；两个开关位于最小化按钮左侧（x≈1208/1236，最小化 1266）；侧栏按钮已从工具栏移除。
- `MainWindow` 离屏冒烟：无边框模式下两个开关的父控件为标题栏，原生模式下为工具栏；点击可切换侧栏与调整面板可见性；菜单 11 项正常。
- `tests/test_widgets/test_frameless_window.py`：**15 passed**（新增“标题栏右键菜单含菜单显隐子菜单”用例）。
- 新增中英日韩四个翻译条目并重建资源。
- **未验证**：真实鼠标拖拽缩放。当前会话无法把窗口置前台（`GetForegroundWindow` 不匹配），合成的鼠标拖拽不会命中窗口；需用户在实机确认。

### 6. 已知限制与后续事项

- 缩放方案依赖 `WS_THICKFRAME`；若个别 Windows 主题下仍不可拖拽，可用 `frameless: false` 回退。
- 全屏/最大化时禁用边缘缩放；Win11 Snap Layouts 悬停提示仍按 v0.4 决策退化。
- 标题栏右键的系统菜单仍为简化版（无“移动/大小”）。

---

## 4.3.2+fork.8 — 2026-11-18

### 1. 背景与原因

fork.7 推送后，实际启动即闪退（终端只打印到 `config:get_config`，无 Python 回溯）。复现确认崩溃点为 `FramelessWindow.nativeEvent()`：在 PyQt6（6.12）+ Windows 上，从覆写中调用 `super().nativeEvent(event_type, message)` 会重入该虚函数并导致进程在 `show()` 时崩溃（Windows 退出码 `0xC000041D` / `0xC0000409`，faulthandler 显示 access violation）。

### 2. 修复与关键细节

- `nativeEvent()` 不再调用 `super()`；所有“未处理”路径统一返回 `(False, 0)`（Qt 文档定义的“未处理”结果，等价于 `QWidget::nativeEvent` 默认行为）。
- 同时把 `hasattr(ctypes, "wintypes")` 的前置判断改为函数内 `from ctypes import wintypes`，避免首次调用时因模块尚未导入而跳过原生处理、后续行为不一致。
- 其余逻辑（`WM_NCHITTEST`/`WM_GETMINMAXINFO`、非 Windows 的 `startSystemResize`、菜单/全屏/主题）不变。

### 3. 涉及模块与文件

- 修改：`anylabeling/widgets/frameless/window.py`、`anylabeling/app_info.py`、`tests/test_widgets/test_frameless_window.py`（新增“nativeEvent 不得调用 super”的回归用例）；
- 文档：本文件、`docs/dev/CODE_STRUCTURE_REPORT.md`、`docs/dev/无边框窗口模块-讨论稿.md`、`docs/开始.md`。

### 4. 行为、接口与兼容性影响

- 版本 `4.3.2+fork.7` → `4.3.2+fork.8`；无接口/配置/数据契约变化。
- 修复效果：软件可正常启动；无边框与原生两种模式均可显示窗口。

### 5. 实际验证内容

- 复现脚本（真实 Windows 平台插件）：修复前 `window.show()` 即崩溃；修复后无边框、原生两种模式均完成 `show → showMaximized → 事件循环 → 正常关闭`。
- 直接运行 `python anylabeling/app.py --no-auto-update-check`：进程保持运行（不再是启动即退出），随后手动终止。
- `tests/test_widgets`：加入回归用例后 70 passed（含既有 69 项），2 subtests。
- 未执行：真实桌面上的拖动/缩放/贴边/最大化工区/多屏 DPI 实测（仍需用户验证）；macOS/Wayland；全量测试。

### 6. 已知限制与后续事项

- 本次只修复启动崩溃；fork.7 记录中的平台限制仍然有效。
- 若后续再覆写其他 Qt 虚函数，需避免在 `nativeEvent` 中调用 `super()`；该约束已写入讨论稿 §11。

---

## 4.3.2+fork.7 — 2026-11-18

### 1. 背景与原因

按 `docs/dev/无边框窗口模块-讨论稿.md` v0.4 的冻结设计，连做 M1+M2+M3：新建可复用的无边框窗口模块，并把主窗口接入，合并原生标题栏与菜单栏，回收一条窗口 chrome 的高度；同时补齐全屏、菜单溢出与菜单显隐。

### 2. 主要实现与关键细节

#### 2.1 可复用模块 `anylabeling/widgets/frameless/`

| 文件 | 职责 |
|---|---|
| `window.py` | `FramelessWindow(QMainWindow)`：启动时二选一（自绘/原生）、菜单与标题按钮 API、全屏、Windows 原生命中测试与最大化工区、非 Windows 缩放兜底 |
| `title_bar.py` | `TitleBar` + `TitleButton`：图标、标题（过长省略）、菜单槽位、宿主按钮、窗口按钮、拖动/双击最大化/右键菜单 |
| `window_buttons.py` | 自绘最小化/最大化/还原/关闭按钮（无图标资源依赖，跟随主题色） |
| `menu_bar.py` | `FrameMenuBar`：真实 `QMenuBar`，`add_menu` 任意层级、右键显隐顶层菜单、`menu_visibility_changed` 信号 |
| `hit_test.py` | 纯几何边缘检测与 Windows `HT*` 映射，可单测 |
| `window_state.py` | 模式判断、多屏几何校正、全屏退出恢复模式 |
| `theme.py` | `FramelessTheme`：从宿主主题字典映射颜色/尺寸并生成 QSS |

#### 2.2 主窗口接入（M3）

- `MainWindow` 改为继承 `FramelessWindow`；启动时按 `frameless` 配置（默认 `true`）或环境变量 `XANYLABELING_NATIVE_FRAME=1` 决定形态，**不支持运行中切换**。
- 菜单仍由 `LabelingWidget` 通过 `self.parent.parent.menuBar()` 创建；`FramelessWindow.menuBar()` 返回嵌入标题栏的 `FrameMenuBar`，原生模式返回普通 `QMenuBar`，因此菜单构建代码无需重写。
- 登录芯片：无边框模式放入标题栏按钮区；原生模式仍用菜单栏右上角 corner widget。归属文字继续在状态栏。
- `F11` 全屏动作加入“视图”菜单，首版全屏保留标题栏（按 v0.4 决策）；退出全屏恢复进入前的最大化/普通状态。
- 菜单显隐持久化到 `QSettings` 的 `frameless/menu_visibility`；窗口最大化状态持久化到 `window/maximized`；恢复几何时做多屏可见性校正。
- 菜单溢出交由 Qt 内建的 menubar extension 按钮（“»”）处理，不再自写折叠逻辑。

#### 2.3 主题与翻译

- 启动时把 `get_theme()` 映射为 `FramelessTheme`，浅色/深色都显式着色（浅色模式全局 QSS 为空的问题在模块内解决）；窗口激活/失活时标题文字变灰。
- 四语言新增 `FramelessWindow`、`FrameMenuBar`、`TitleBar`、`WindowButton` 上下文并重建 `.qm` 与 `resources.py`。
- 新增示例 `examples/frameless_demo.py`，可脱离项目直接运行。

### 3. 涉及模块与文件

- 新增：`anylabeling/widgets/__init__.py`、`anylabeling/widgets/frameless/{__init__,theme,hit_test,window_buttons,menu_bar,title_bar,window_state,window}.py`、`examples/frameless_demo.py`、`tests/test_widgets/test_frameless_window.py`；
- 修改：`anylabeling/views/mainwindow.py`、`anylabeling/configs/xanylabeling_config.yaml`、`anylabeling/resources/translations/*.ts|*.qm`、`anylabeling/resources/resources.py`、`anylabeling/app_info.py`；
- 文档：本文件、`docs/dev/CODE_STRUCTURE_REPORT.md`、`docs/dev/无边框窗口模块-讨论稿.md`、`docs/user/zh_cn/user_guide.md`、`docs/开始.md`。

### 4. 行为、接口与兼容性影响

- 版本由 `4.3.2+fork.6` 升至 `4.3.2+fork.7`。
- **用户可观察**：窗口默认无边框，标题栏与菜单栏合并为一条，托盘高度减少；提供 `F11` 全屏；右键菜单栏可隐藏/显示顶层菜单；启动配置可回退原生窗口。
- **配置契约**：新增 `frameless` 配置键（默认 `true`）；新增环境变量 `XANYLABELING_NATIVE_FRAME`；新增 QSettings 键 `window/maximized`、`frameless/menu_visibility`。
- **兼容性**：原生模式仍可用；旧 `window/size`、`window/position`、`window/toolbar_area`、`window/toolbar_visible` 继续有效；未改动标注数据格式、`author`/`modified_at` 契约、门禁规则与业务模块；无新增第三方依赖。

### 5. 实际验证内容

- 新增单元测试：hit-test 边缘与 `HT*` 码、几何校正、主题映射与 QSS、无边框/原生两种结构、标题按钮增删、菜单显隐信号、全屏切换与恢复。
- 离屏冒烟：完整 `MainWindow` 在无边框与原生两种模式下构造成功；菜单 11 项进入嵌入菜单栏；登录芯片分别位于标题栏/菜单栏 corner；`F11` 动作在“视图”菜单；菜单显隐切换正常。
- 定向回归：`tests/test_widgets`、`tests/test_identity` 及标注读写/门禁/tags/审核相关用例合计 **120 passed / 11 subtests passed**；另有一个既有用例 `test_canvas_adjustment...throttled` 在合并运行中偶发失败、单独运行与重跑通过（时序敏感，未发现与本次改动相关）。
- 翻译资源：`lrelease` 生成四个 `.qm`（2159 条，0 未完成）并重建 `resources.py`；资源加载抽查通过。
- 未执行：真实 Windows 桌面的拖动/缩放/贴边/最大化工区/多屏 DPI 实测；macOS 与 Wayland 实机验证；全量测试。

### 6. 已知限制与后续事项

- Windows 原生行为（`WM_NCHITTEST`、`WM_GETMINMAXINFO`）只有静态与离屏验证，**需在真实 Windows 桌面确认**；若异常可用 `frameless: false` 或环境变量回退。
- macOS 默认无边框，但全局菜单栏/交通灯/全屏行为未实机验证；必要时按讨论稿退回原生或透明标题栏。Wayland 下拖动/缩放可能不可用。
- 菜单溢出使用 Qt 内建 extension 按钮，样式与自绘标题栏可能不完全一致。
- 标题栏右键菜单是简化版系统菜单（还原/最大化/最小化/全屏/关闭），不含“移动/大小”。
- 全屏首版保留标题栏，沉浸式自动隐藏未实现。
- 标题栏宿主按钮（登录芯片）沿用原控件，键盘焦点行为未专门调整。

---

## 4.3.2+fork.6 — 2026-11-18

### 1. 背景与原因

fork.4 把操作员会话条放在画布上方，占掉一行画布高度，影响标注/浏览主功能；同时账号库路径依赖 `--work-dir`，一旦换工作目录就会“找不到账号”，与“账号随软件走”的定位矛盾。按用户确认的方案：登录入口移到菜单栏右上角、归属文字移到状态栏；账号库改为与 `work_dir` 无关的固定系统目录。并要求评估无边框窗口方案、产出一份可复用模块的讨论稿。

### 2. 主要实现与关键细节

#### 2.1 登录入口与归属显示改到原生窗口区域

- `OperatorBar` 改为紧凑控件（模式文字 + 登录/注销按钮），新增 `AttributionLabel` 承载“最后修改/未记录”文字。
- `MainWindow` 新增 `_install_operator_chrome()`：把 `OperatorBar` 放进 `menuBar().setCornerWidget(..., TopRightCorner)`，把 `AttributionLabel` 放进 `statusBar().addPermanentWidget(...)`。两者都不再占用画布高度。
- 画布上方不再插入会话条；仅当宿主没有菜单栏（独立嵌入、非 `MainWindow`）时回退为原布局，避免登录入口丢失。
- `OperatorBar` 新增紧凑按钮样式 `get_compact_button_style()`；悬停提示随登录状态变化。
- 新增译文：`OperatorBar/Not logged in`、`AttributionLabel/Author: not recorded`、`AttributionLabel/Last modified: %s`，四语言 `.ts` 与 `.qm` 同步；`resources.py` 由脚本重新生成。

#### 2.2 账号库改为固定系统目录

- 路径改为与 `--work-dir` 无关：Windows `%APPDATA%\X-AnyLabeling\operators\operators.db`；Linux `$XDG_DATA_HOME/X-AnyLabeling/...`（缺省 `~/.local/share`）；macOS `~/Library/Application Support/X-AnyLabeling/...`。
- 旧路径 `<work_dir>/xanylabeling_data/operators/operators.db` 保留为迁移来源：首次使用新路径时若新库不存在而旧库存在，则**复制**（不移动、不删除）到新位置，旧文件留给用户处理。
- `OperatorService` 支持显式 `db_path`（测试与特殊部署），显式路径不触发迁移。

#### 2.3 无边框窗口模块评估

新增讨论稿 `docs/dev/无边框窗口模块-讨论稿.md`：给出可复用模块的 API 草案（一级/二级菜单、标题/图标、标题栏按钮、内容区）、子模块划分、平台差异与降级、以及接入本项目需要改动/重写的模块清单与分阶段工作量。本批不实现无边框窗口。

### 3. 涉及模块与文件

- 代码：`anylabeling/views/labeling/widgets/operator_bar.py`、`label_widget.py`、`views/mainwindow.py`、`views/labeling/utils/style.py`、`services/identity/session.py`、`services/identity/__init__.py`、`app_info.py`；
- 资源：`resources/translations/*.ts`、`*.qm`、`resources/resources.py`；
- 测试：`tests/test_identity/test_operator_store.py`（新增路径与迁移用例）；
- 文档：本文件、`docs/开始.md`、`docs/dev/数据库设计-讨论稿.md`、`docs/dev/工业机器视觉数据平台-设计书-v1.6.md`、`docs/user/zh_cn/user_guide.md`、`docs/dev/CODE_STRUCTURE_REPORT.md`、新增 `docs/dev/无边框窗口模块-讨论稿.md`。

### 4. 行为、接口与兼容性影响

- 版本由 `4.3.2+fork.5` 升至 `4.3.2+fork.6`。
- **用户可观察**：登录入口从画布上方移到菜单栏右上角，归属文字移到状态栏；画布高度增加约一行。
- **存储契约**：账号库路径变化，属于需要迁移的契约变化；旧库自动复制到新位置，不删除旧文件。
- 不改变标注数据格式、`author`/`modified_at` 语义、门禁规则与依赖。
- `resources.py` 行级差异很大仍是生成器输出差异；`.qm` 每次重编可能产生少量非确定字节，属已知现象。

### 5. 实际验证内容

- 离屏构造 `MainWindow`：菜单栏右上角 corner widget 即 `OperatorBar`，状态栏包含 `AttributionLabel`，画布布局中不再有会话条；`OperatorBar.parent()` 为菜单栏。
- 账号库路径：`default_database_path()` 返回 `%APPDATA%\X-AnyLabeling\operators\operators.db`，不受工作目录影响；`legacy_database_path()` 仍指向旧位置。
- 迁移用例：旧库复制到新位置后账号数一致，旧文件保留，二次调用不覆盖。
- 定向 pytest：身份库、归属字段、门禁三组共 30 项通过；离屏 widget 冒烟通过。
- 译文：资源内新增上下文可加载（四语言）。未做 GUI 实机截图与全量测试。

### 6. 已知限制与后续事项

- 菜单栏 corner widget 在极窄窗口下会挤压菜单文字，尚未做自适应收起。
- 旧账号库只复制不删除；迁移只在当前 `work_dir` 下能找到旧库时发生，用户换过工作目录的旧库需手动复制。
- 无边框窗口仅完成评估与讨论稿，未实现。
- 英文用户手册仍冻结，未同步路径与界面位置说明。
- 补充（2026-11-18，纯文档）：`docs/dev/无边框窗口模块-讨论稿.md` 更新至 v0.4——记录 11 项决策与两项收尾决策（**全屏首版保留标题栏**、**macOS 默认无边框但接受实机验证后降级**）；澄清启动时二选一不会出现两组窗口按钮；补菜单溢出“更多 »”与右键菜单显隐、全屏方案、平台默认与工作量（9–14 人日），设计问题已清空。本补充不改变代码、接口与版本号。

---

## 4.3.2+fork.5 — 2026-11-18

### 1. 背景与原因

fork.4 上线后发现登录相关界面仍是英文，用户在中文界面看不到 `登录/注销/忘记口令` 等译文。排查结论：应用从 Qt 资源 `:/languages/translations/<lang>.qm` 加载翻译，而该资源由 `anylabeling/resources/resources.py` 从 `resources.qrc` 编译生成；fork.4 只更新了散装的 `.ts/.qm` 文件，没有重新编译资源包，因此运行时仍使用旧译文。同批处理用户在评审中提出的文档缺口与失效链接。

### 2. 主要实现与关键细节

- **翻译资源重新编译**：执行 `scripts/compile_languages.py`（`pyside6-lrelease` + `pyside6-rcc`），重新生成四个 `.qm` 并重建 `anylabeling/resources/resources.py`，新增的 `OperatorBar`/`OperatorDialog`/`_LoginPage`/`_RegisterPage`/`PasswordResetDialog` 上下文进入内嵌资源。验证方式：从资源路径 `:/languages/translations/zh_CN.qm` 加载 `QTranslator` 并抽查新字符串。
- **用户手册失效链接修复**：`docs/user/zh_cn/user_guide.md` 中 55 处形如 `../../assets/...`、`../../examples/...`、`../../anylabeling/...` 的相对链接实际指向 `docs/` 下，改为 `../../../...`；全文件 270 条本地链接现全部可解析。
- **归属契约写入三份文档**：`docs/开始.md` 新增“十、标注归属与操作员契约”并登记 T6；`docs/dev/数据库设计-讨论稿.md` 新增 §12A“操作员归属与账号库边界”；`docs/dev/工业机器视觉数据平台-设计书-v1.6.md` 新增 §3.4 并记录变更行。核心结论：账号库是应用级、项目库是数据级，两者不共享存储、不做外键。

### 3. 涉及模块与文件

- 资源与翻译：`anylabeling/resources/resources.py`（重新生成）、`anylabeling/resources/translations/*.qm`；
- 版本：`anylabeling/app_info.py`；
- 文档：`CHANGELOG-fork.md`、`docs/开始.md`、`docs/dev/数据库设计-讨论稿.md`、`docs/dev/工业机器视觉数据平台-设计书-v1.6.md`、`docs/user/zh_cn/user_guide.md`、`docs/dev/CODE_STRUCTURE_REPORT.md`。

### 4. 行为、接口与兼容性影响

- 版本由 `4.3.2+fork.4` 升至 `4.3.2+fork.5`；属于缺陷修复（界面译文不生效），不改变数据格式、接口或依赖。
- `resources.py` 由项目脚本重新生成，行级差异很大属生成器/压缩输出差异，不是手工改写；已验证图片与翻译资源路径均可加载。
- 文档链接修复只影响 Markdown 跳转。

### 5. 实际验证内容

- 从 Qt 资源路径加载 `zh_CN/ja_JP/ko_KR` 的 `.qm`，抽查 `OperatorBar.Login`、`OperatorBar.Annotation mode: %s`、`_LoginPage.Forgot password?`、`OperatorDialog` 与 `PasswordResetDialog` 的错误文案，均返回预期译文。
- 文档本地链接检查：三份文档共 270 条本地链接，0 缺失。
- 未重新运行 fork.4 的代码回归（本批未改 Python 业务代码）；未做 GUI 实机截图验证，译文验证基于 `QTranslator` 资源加载结果。

### 6. 已知限制与后续事项

- 登录会话条仍占用画布上方一行，位置是否改为菜单栏/标题栏区域尚未决定；无边框自绘标题栏方案只做了评估，未实施（见 §附录说明）。
- `database design` 讨论稿与设计书只补充了契约说明，项目数据库 schema 仍无操作者列，待 T3 按 T6 落地。
- 英文用户手册仍按规则冻结，未同步链接修复。

---

## 4.3.2+fork.4 — 2026-11-17

### 1. 背景与原因

现场需要回答“这张图片的标注是谁改的”，此前只能靠人工给每张图片添加名字标签，既繁琐又容易遗忘，并且把人员信息混进了业务标签语义。本轮引入**本地操作员账号 + 自动归属记录**：

- 账号只在本地 SQLite 中注册与登录，不依赖任何服务端；
- 打开软件**不强制登录**，因为软件定位是标注/训练/评估解耦，训练和评估不应被登录挡住；
- 编辑标注需要登录（浏览模式/标注模式），软件自动把操作员写入标注文件，不再依赖记忆；
- 归属以一个 `author` 字段记录“最后修改人”，并可加 `modified_at`；完整修订历史留给后续数据库与 revision 审计。

本轮决定（用户确认）：归属存名字而非 id；只有“标注内容/tags 变化”才盖章；先做单值、不建历史；导入数据记为 `none`；首个注册账号为管理员；未登录时工具置灰而不是操作时弹窗；账号只禁用不删除、名字唯一、`none` 保留。

### 2. 主要实现与关键细节

#### 2.1 操作员账号库（新增 `anylabeling/services/identity/`）

- `passwords.py`：PBKDF2-HMAC-SHA256（260000 次迭代、每用户 16 字节随机 salt），只用标准库，不新增依赖；口令长度至少 4 位。
- `store.py`：`OperatorStore` 管理 `operators.db`，表 `operator(name, name_key, password_hash, password_salt, password_iterations, is_admin, disabled, created_at)` 与 `meta(schema_version)`；`name_key` 为 `casefold` 后的唯一键，`none` 大小写不敏感保留；首个注册账号为管理员；提供 `register/authenticate/change_password/set_disabled/list_operators`。
- `session.py`：`OperatorSession` 保存当前操作员并向监听者广播；`OperatorService` 组合 store 与 session；`get_operator_service()` 为进程级唯一访问点，`reset_operator_service()` 供测试替换；`default_database_path()` 固定为 `<work_dir>/xanylabeling_data/operators/operators.db`。
- `attribution.py`：定义 `author`/`modified_at` 契约、`none` 哨兵、`ensure_attribution()`（旧文件与导入数据按未记录补齐）、`stamp_attribution()`、`read_attribution()` 与 `content_signature()`（内容签名，排除 `checked`/`split`/归属字段本身）。

#### 2.2 门禁（浏览模式 / 标注模式）

- `label_widget.py` 新增 `OPERATOR_REQUIRED_ACTIONS` 清单与 `_apply_operator_gate()`：未登录时禁用创建、编辑、删除、复制粘贴、撤销、关系、标签/群组/对象管理器及批量自动标注等会改内容的动作，并关闭图片标签控件交互；登录后恢复。
- 门禁在 `set_clean()`、`toggle_actions()`、`toggle_draw_mode()` 和会话变化后重新应用，避免加载图片或切换绘制模式时把工具重新点亮。
- 浏览、训练、评估、导出、统计、切换 split、导入外部标注不受门禁影响。

#### 2.3 自动归属与写入保护

- `save_labels()`/`save_attributes()` 写盘前调用 `_prepare_attribution()`：仅当内容签名变化且存在操作员时写入 `author`/`modified_at`；签名不变则保留原归属。
- 内容变化但没有操作员时**拒绝写盘**并弹出登录窗口；用户取消则保持 `dirty` 状态，不向文件写入任何伪造归属。`set_dirty()` 已相应处理保存失败分支。
- 批量自动标注写盘（`utils/batch.py` 的 `save_auto_labeling_result()`）按发起运行的操作员盖章；无操作员（程序化调用）写 `none` 而不是沿用旧名字。批量入口 `run_all_images()` 先要求登录。
- `load_file()` 记录加载时的内容签名作为基线，并在会话变化/加载完成时刷新归属显示；`keep_prev` 自动带入上一张图形时抑制盖章，视为非操作员编辑。

#### 2.4 界面与文案

- 新增 `OperatorBar`（画布上方常显会话条）：显示浏览/标注模式、当前操作员、当前图片“最后修改/未记录”，提供登录与注销按钮。
- 新增 `OperatorDialog`（登录/注册双页）与 `PasswordResetDialog`（管理员重置口令）；错误以内联文案提示，不弹额外对话框。
- 关闭软件自动退出登录：会话只在内存，不写入 YAML/QSettings，不保存口令。
- `zh_CN/en_US/ja_JP/ko_KR` 四个 `.ts` 增加 `OperatorBar`、`OperatorDialog`、`_LoginPage`、`_RegisterPage`、`PasswordResetDialog` 上下文并重新编译 `.qm`。

### 3. 涉及模块与文件

- 新增：`anylabeling/services/identity/{__init__,passwords,store,session,attribution}.py`、`anylabeling/views/labeling/widgets/{operator_bar,operator_dialog}.py`；
- 修改：`anylabeling/app_info.py`、`anylabeling/views/labeling/label_widget.py`、`label_file.py`、`utils/batch.py`、`widgets/__init__.py`、四个 `.ts` 与对应 `.qm`；
- 测试：新增 `tests/test_identity/test_operator_store.py`、`tests/test_labeling/test_label_file_author.py`、`tests/test_labeling/test_operator_gate.py`；
- 文档：本文件、`docs/dev/CODE_STRUCTURE_REPORT.md`、`docs/user/zh_cn/user_guide.md`。

### 4. 行为、接口与兼容性影响

- 版本由 `4.3.2+fork.3` 升至 `4.3.2+fork.4`。
- **数据格式**：XLABEL JSON 新增可选顶层字段 `author`、`modified_at`；旧文件缺少字段时按“未记录”处理，无需迁移；字段通过 `other_data` 读写，未改动 `create_xlabel_template`，未知字段仍按原逻辑保留。
- **操作行为**：编辑标注前必须登录；未登录时相关工具栏置灰。这是用户可观察的行为变化。
- **新增本地文件**：`<work_dir>/xanylabeling_data/operators/operators.db`；删除该文件会丢失账号（标注数据不受影响，已有 `author` 仍保留在 JSON 中）。
- **依赖**：仅使用标准库 `sqlite3`、`hashlib`、`hmac`，未新增第三方依赖。
- 未改动训练、导出、模型目录、搜索/统计逻辑；未改动数据库改造（T3）与项目文件（T5）规划。

### 5. 实际验证内容

- 定向 pytest（获授权的一次性环境）：`tests/test_identity`、`test_label_file_author.py`、`test_label_file_load.py`、`test_label_file_save.py`、`test_operator_gate.py`、`test_image_tags.py`、`test_check_status.py`、`test_label_widget_groups.py` 合计 **51 passed / 9 subtests passed**；未运行全量测试。
- 离屏端到端脚本（`QT_QPA_PLATFORM=offscreen`）：构造完整 `LabelingWidget`，验证未登录时创建/编辑/删除/撤销/批量入口与 tags 控件均禁用；注册登录后工具恢复；加载图片后修改 tags，JSON 写入 `author=张三` 与 `modified_at`；仅切换 `checked` 的自保存不改变归属；注销后内容变化被拒绝写盘且文件保持原值、窗口保持 dirty。
- 翻译校验：加载四个 `.qm`，抽查 `OperatorBar`/`_LoginPage`/`OperatorDialog`/`PasswordResetDialog` 新字符串均返回预期译文。
- 代码静态检查：相关模块 `compileall` 通过，`label_widget` 可导入。

### 6. 已知限制与后续事项

- `author` 为单值“最后修改人”，不保留历史；多人先后编辑同一张图只留最后一次。完整历史与唯一权威仍属于 T3 的数据库与二期 revision 审计。
- 点云、PPOCR、VQA、图像分类、视频分类等专项工作区未纳入门禁与归属；自动标注面板的按钮本身未置灰，依赖写入保护兜底。
- 本地账号不构成安全边界：口令哈希只防止直接读取明文，不能防篡改或抵赖。
- `docs/dev/数据库设计-讨论稿.md` 与设计书尚未补充 `author`/操作者字段契约（讨论稿当前 schema 无该列），留待 T1 文档合并时一并处理。→ **fork.5 已补契约说明**（讨论稿 §12A、设计书 §3.4、`开始.md` §10/T6）；项目数据库的操作者列仍待 T3/T6 落地。
- README、发布脚本与 `docs/user/en/user_guide.md` 未同步（英文手册按规则冻结）。

---

## 4.3.2+fork.3 — 2026-11-11

### 1. 背景与原因

本版本处理文档治理和交接准确性问题：用户手册中英文双份同步维护增加 token 与人工成本；
`开始.md` 尚未明确项目约束、当前代码结构和未来设计三类文档的职责；
`docs/dev/CODE_STRUCTURE_REPORT.md` 仍主要反映上游 4.3.2，未覆盖 fork.1/fork.2 的界面和模型目录变化，
且文档移至 `docs/dev` 后相对链接失效。与此同时，需要评估上游 README/CHANGELOG 在私有 fork 中的保留方式，
但本批只形成建议，不直接删改这些上游文档。

### 2. 主要实现与关键细节

#### 2.1 交接文档定位与维护规则（`docs/开始.md`）

- 明确 `开始.md` = 项目约束、`CODE_STRUCTURE_REPORT.md` = 当前代码结构、设计书 = 未来功能；
  默认按该顺序阅读，当前实现仍以代码为最终证据。
- 规定每次代码修改在同一提交批次内按差异更新结构报告，发现不符时同步修正；
  无变化章节不重写，纯文档变化不虚构结构变化。
- 用户手册以后只例行更新 `docs/user/zh_cn/user_guide.md`，冻结 `docs/user/en/user_guide.md` 为历史参考；
  该规则不影响 en_US 界面翻译、`.ts/.qm` 或其他英文材料。
- `CHANGELOG-fork.md`、结构报告、`开始.md` 和设计书等其他既定维护义务继续有效。
- Git 规则进一步区分：行为变更才强制升级 fork 版本；fork 版本提交验证后自动普通 push 到 GitHub，
  纯文档/非行为小改动不强制升版且默认只在本地提交。禁止 force push，推送失败不得伪报云端成功。
- 升版判定细化为用户可观察行为、接口/数据契约、依赖/平台兼容性及迁移需求；文档、测试、格式化、
  文案微调、资源移动和无行为变化的内部重构不升版。判定不看代码行数，一行缺陷修复仍升版，
  大规模无行为重构不升版；难以判定时先询问，避免版本号滥用。
- 新增累积改动默认阈值：排除文档等豁免改动后，自上一个 fork 版本起，独立改动点不少于 3 个
  且涉及不少于 2 个结构模块时递增一次。同一问题的配套修改和跨文件机械性重复修改不重复计数；
  达到阈值后仍只递增一次，不按改动点数量连续跳号。
- 设计书定位同步澄清为“未定稿的方向性草案”：只作大方向指导和重大冲突提醒，不是任务清单、
  需求基线或验收依据；具体任务以用户后续消息为准，避免新接手者按“定稿、待开工”误读并自行实施。

#### 2.2 当前结构报告同步（`docs/dev/CODE_STRUCTURE_REPORT.md`）

- 版本更新为 `4.3.2+fork.3`，分析起点记录为 `main/7718aad`；应用统计保持 427 个非生成 Python 文件、
  648 个唯一类名；新增 `tests/conftest.py` 后，测试目录 Python 文件由 137 增至 138，核心类排名不变。
- 补充工具栏顶部/左侧停靠及显式 QSettings 键、五列文件表、右侧对象/类别/标志/描述/统计 tab、
  split/布尔搜索、统计点击反筛，以及 `model_directory` 的解析、迁移和旧目录兼容扫描。
- 核心类由 16 增至 18，新增 `FileTableWidget` 与 `StatisticsTable`；全部类名引用排名、
  文件扇入/扇出和主要维护提示按当前代码重算。
- 修正文档在 `docs/dev` 下的源码/测试/脚本/图片相对链接；重新渲染模块依赖图和核心类总览图，
  保留可编辑 Mermaid 源码及 SVG/JPG 两种图形格式。随后将四个受跟踪图形文件用 `git mv` 移至
  `docs/dev/code_structure_assets`，报告改为同目录引用；根目录 `code_structure_assets` 中的
  `.xanylabeling_import_time.json` 也按用户要求移至 `docs/dev/`。它仍是运行时元数据，
  保持 Git 忽略，不改变程序对图片目录中同名 sidecar 的读写规则。
- 已知限制同步记录：统计大数据集刷新可能阻塞 UI、模型目录迁移不是全量原子操作。

#### 2.3 上游 README/CHANGELOG 评估

- 结论为不建议直接删除：`pyproject.toml` 使用 `README.md` 作为包说明；`CHANGELOG.md` 保留上游历史，
  且发布说明脚本和应用内“关于”仍引用它。
- 建议后续把 README 改为 fork 入口，链接三份交接文档、中文用户手册和 `CHANGELOG-fork.md`，
  并区分上游历史与 fork 当前功能；`CHANGELOG.md` 只保留上游记录。
- 另发现发布说明脚本尚未适配 `+fork.N` 版本与 fork 变更日志，需要单独设计发布通道，本批未修改脚本。

#### 2.4 pytest 临时目录统一（`tests/conftest.py`、`pyproject.toml`）

- 《开始.md》明确所有一次性测试、调试和验证产物必须预先定向到 `temporary`，不得写入根目录后再移动，
  也不能只凭 `.gitignore` 或 `git status` 判断无残留；权限或工具配置失败时不得擅自回退到系统临时目录。
- 新增测试专用 `pytest_configure`：每次以 PID 和 UUID 建立 `temporary/runs/pytest-<PID>-<UUID>/`，
  pytest 临时 fixture 使用 `fixtures`，直接调用 `tempfile` 的代码和子进程使用 `process`。
  进程内统一设置 `TEMP`、`TMP`、`TMPDIR` 和 `tempfile.tempdir`，不修改全局环境；显式 `--basetemp` 仍优先。
- 不写死共享 `basetemp`，因为 pytest 9.2.0 会删除已有的显式路径；自定义 fixture 根目录的父目录由配置预先创建。
- `cache_dir` 固定为 `temporary/cache/pytest`，供跨运行复用。pytest 原子写缓存时生成的
  `pytest-cache-files-*` 临时目录也随之进入 `temporary/cache`，不再落在仓库根目录。
- 本次只改变测试临时文件和缓存位置，不改变应用运行逻辑、数据契约、依赖或支持平台，不额外递增 fork 版本。

### 3. 涉及模块与文件

- 规则与版本：`docs/开始.md`、`docs/dev/工业机器视觉数据平台-设计书-v1.6.md`、`anylabeling/app_info.py`、`CHANGELOG-fork.md`。
- 当前结构：`docs/dev/CODE_STRUCTURE_REPORT.md`、`docs/dev/code_structure_assets/{module_dependencies,core_classes_overview}.{svg,jpg}`。
- 忽略的文档辅助元数据：`docs/dev/.xanylabeling_import_time.json`（仅移动，不纳入版本控制）。
- 测试支撑：`pyproject.toml`、`tests/conftest.py`；仅改变 pytest 临时目录与缓存位置。
- 核对实现：`views/mainwindow.py`、`views/labeling/label_widget.py`、`utils/file_search.py`、
  `utils/dataset_statistics.py`、`widgets/statistics_table.py`、`services/auto_labeling/{model,model_storage,model_manager}.py`。
- 仅评估未修改：`README.md`、`README_zh-CN.md`、`CHANGELOG.md`、`docs/user/en/user_guide.md`。

### 4. 行为、接口与兼容性影响

- 版本由 `4.3.2+fork.2` 升至 `4.3.2+fork.3`，版本字符串通过 PEP 440 解析。
- 本批不修改搜索、统计、模型下载、训练或 UI 行为逻辑；新增配置只影响 pytest 临时文件和缓存位置，
  其余为版本元数据、文档和图形变化，不改变应用行为、数据契约、依赖或支持平台。
- 英文用户手册从本版本起会有意滞后，阅读时以中文手册和代码为准；英文界面翻译维护不受该规则影响。
- 上游 `README.md`、`README_zh-CN.md`、`CHANGELOG.md` 未删除或改写。

### 5. 实际验证内容

- Markdown 静态检查：`开始.md` 与结构报告共检查 **186 个本地链接，0 个缺失**；
  `4.3.2+fork.3` 经 `packaging.version.Version` 解析成功。
- 本轮静态检查：`tests/conftest.py` AST 解析及 `pyproject.toml` TOML 读取通过；实测应用目录 436 个、
  测试目录 138 个 Python 文件，按原排除口径应用统计仍为 427；《开始.md》、结构报告和本记录共检查
  **191 个本地链接，0 个缺失**；`git diff --check` 通过。
- 当前代码静态统计：应用源码仍为 427 个非生成 Python 文件、648 个唯一类名；新增 stdlib-only 测试配置不影响核心类与依赖排名。
- 两张更新后的总览图均成功生成 SVG/JPG，并通过图片读取检查中文和布局。
- 相关回归（指定 Conda 环境）：`test_file_search.py`、`test_dataset_statistics.py`、`test_model_storage.py`、
  `test_file_table.py`、`test_statistics_table.py` 合计 **85 passed / 114 subtests passed**。
  首次在受限环境运行时因系统临时目录和 pytest 缓存权限出现失败；经用户批准的一次性授权环境重跑全部通过，
  未据此声称全量测试通过。
- 新增临时目录配置后，在同一组 85 项测试上验证默认配置，首轮结果为 **32 passed / 19 failed / 49 errors**；
  失败和错误均表现为临时目录 `PermissionError` 或 fixture 根目录父目录缺失，不是业务断言失败。
  已修正父目录预创建，但权限诊断未发现其可修复的权限类型、未更改权限；未在受限环境中反复重跑，
  因而新配置尚无完整通过结论。测试前后根目录条目无新增，未声称全量测试通过。

### 6. 已知限制与后续事项

- 结构报告按 fork 差异更新，未重新逐行分析所有模型算法、OpenGL/编辑器或第三方代码。
- README fork 化、发布脚本适配 fork 版本与变更日志仍需单独实施和验证。
- 英文用户手册会随功能演进而过时，后续如需恢复双语言维护，应由用户明确决定。
- `temporary/fork3-docs-tests-full` 由用户选择手动清理，最终检查时已不存在；本轮未删除该目录。
- 用户报告已手动清理 `temporary/runs/pytest-36252-cb6f241d20af4150aa97b0bd89dbcede` 及
  `temporary/cache/pytest-cache-files-{bqn8wm0u,nxoxlqvm}`；最终受限检查仍无法枚举这些路径，
  因而不能独立确认目录为空。它们位于 Git 忽略的 `temporary` 下，不纳入提交。
  `temporary/cache/pytest` 是预留给后续运行的可复用缓存目录；本次因权限未成功生成，不列为清理对象。
  最终检查根目录已无 `pytest-cache-files-*`，本轮未执行删除。
- Windows 权限诊断未作出修改，报告为 `E:\dev-GitHub\dsh-acl-recovery\acl-report-c0dd8d7f13444916a7d4d86c7133998c.jsonl`；
  新配置尚待在可正常读写临时目录的环境中复验。用户知悉该限制后明确要求保持 `4.3.2+fork.3`
  并提交、推送本批累积更新；该授权不被解释为测试已经全部通过。

## 4.3.2+fork.2 — 2026-11-11

### 1. 背景与原因

本版本处理 6 项现场反馈：file_list 已有 `split`（划分）信息，但搜索栏不支持按划分筛选；
原搜索只支持单条件，无法表达“类别与划分组合”的查询；自动标注模型固定下载到
`C:\Users\<user>\xanylabeling_data\models`，现场希望可切换目录；界面把 object 的 class
中译成“标签”，与底部图片 tag 混淆；对象/类别两个 tab 仍残留旧的标题栏、显隐/锁定按钮与
逐行复选框/锁图标；同时需要一个按“类别 × 划分”汇总并可直接点击联动筛选的统计表。

### 2. 主要实现与关键细节

#### 2.1 搜索语法：split 关键字与布尔组合（`utils/file_search.py` 重写）

- 新增 `split::` 条件，值接受 `none/train/val/test` 及中文 `未划分/训练/验证/测试`；
  `shape::` 同时支持 `1/0`（有/无对象）。
- 新增布尔语法：`|` = OR、`,` = AND（优先级高于 `|`）、`!` = 前缀取反、`()` 分组，
  可跨 `label`/`split`/`shape` 组合；同字段多值可简写（`label::cat|dog`、`label::cat,dog`）。
- 值内特殊字符用 `\` 转义；`escape_query_value()` 供统计表回填搜索框。
- 兼容保留旧接口与行为：`parse_search_pattern`、`matches_filename`、
  `matches_label_attribute` 签名不变，`#N`、`<regex>`、`checked/review/gid/difficult/`
  `type/score/description/label` 等旧条件继续可用；无法解析的文本退化为文件名子串搜索。
- `label_widget.import_image_folder` 改为统一走 `parse_search_query` +
  `filter_image_files`；搜索框 tooltip 更新为新语法说明。

#### 2.2 设置新增“模型保存目录”并自动迁移（需求 3）

- 新增 config 键 `model_directory`（默认 `null` = `<work_dir>/xanylabeling_data/models`），
  并在“设置 → 常规 → 行为”增加 Directory 控件（输入框 + Browse；清空 = 默认位置）。
- 新增 `services/auto_labeling/model_storage.py`：解析生效目录、默认目录、目录迁移；
  `model.py` 下载/缓存路径与 `model_manager.py` 的模型扫描/删除均改用配置目录，同时兼容
  扫描默认与旧目录（已有模型不会消失）。
- 保存设置时如目录变化，自动把旧目录下的模型条目 move 到新目录；目标同名跳过；失败/权限
  不足时弹窗提示并保留旧文件（不做复杂回滚），可在新目录重新下载。

#### 2.3 右侧 tab 中“类别”措辞与普通列表化（需求 4、5）

- class 概念统一为“类别”（英文源 `Classes`）：右侧 tab `标签` → `类别`；标注弹窗占位符
  `Enter object label` → `Enter class`（中译“输入类别”），`Label description` →
  `Object description`（中译“对象描述”）；“标签”仅保留给图片 tag/标志等既有概念。
- 右侧“对象”与“类别”两个 tab 改为普通 `QListWidget`：移除 PanelHeader 标题栏及其
  显隐/锁定全部按钮、移除逐行复选框与锁形图标/右键锁定交互；保留选择联动、双击编辑、
  类别管理器中的会话级锁定策略（不再在列表中绘制）。
- 设置页字段标题改为走 `tr()`（原实现只翻译描述不翻译标题）；字段译文本就在 .ts 中，因此
  中文设置页标题与描述都中文化（含新增“模型保存目录”）。

#### 2.4 新增“统计/Statistics” tab（需求 6）

- 右侧 tab 新增 `统计`：`QTableWidget` 按“类别 × 训练/验证/测试/未划分/合计”显示当前
  文件列表数据，行含 `（无对象图）` 与 `合计`；合计行按 split 统计文件数、右下为文件总数。
- 点击数值单元格 → 生成 `label::X,split::Y` 搜索并过滤文件列表；点类别名只按类别，点列头
  只按 split，`（无对象图）` → `shape::0`（+ split）；合计行列不可点击。
- 切换到统计 tab、导入/移除文件或修改 split 时刷新；数据聚合逻辑独立为
  `utils/dataset_statistics.py`（可单测，无 Qt 依赖），控件为
  `widgets/statistics_table.py`。

#### 2.5 国际化与文档

- 4 语言 `.ts` 用 `pylupdate6 --no-obsolete` 重生成并补译：本批新增/变更 12 条/语言、
  统计表 `StatisticsTable` context 8 条手工条目、运行期 fallback 2 条；清理 8 条 obsolete；
  重建 `.qm` 与 `resources.py`（0 unfinished）。
- 用户手册 en/zh 更新：搜索语法（split/布尔/示例）、统计 tab、对象/类别 tab 普通列表化与
  锁定说明、设置页“模型保存目录”章节及章节编号。

### 3. 涉及模块与文件

- 搜索：`anylabeling/views/labeling/utils/file_search.py`、`label_widget.py`
- 统计：`anylabeling/views/labeling/utils/dataset_statistics.py`、
  `anylabeling/views/labeling/widgets/statistics_table.py`
- 列表/tab：`anylabeling/views/labeling/widgets/label_list_widget.py`、
  `widgets/unique_label_qlist_widget.py`、`widgets/label_dialog.py`、`label_widget.py`
- 模型目录：`services/auto_labeling/model_storage.py`、`model.py`、`model_manager.py`、
  `views/labeling/settings/{schema,dialog,controller,runtime_applier}.py`、
  `configs/xanylabeling_config.yaml`
- 翻译：`anylabeling/resources/translations/*.ts|.qm`、`resources/resources.py`
- 版本/文档：`anylabeling/app_info.py`、`docs/user/{en,zh_cn}/user_guide.md`、本文件
- 测试：`tests/test_utils/test_file_search.py`、`test_dataset_statistics.py`、
  `tests/test_widgets/test_statistics_table.py`、`tests/test_auto_labeling/test_model_storage.py`、
  `tests/test_settings/*`、`tests/test_labeling/test_file_table.py`、`test_label_locks.py`、
  `test_image_switch.py`、`test_label_widget_metrics.py` 等

### 4. 行为、接口与兼容性影响

- **版本号**：`4.3.2+fork.1` → `4.3.2+fork.2`。
- **搜索**：旧语法全部兼容；新增 `split::`、布尔运算符与 `escape_query_value()` 等 API。
- **配置**：新增 `model_directory`（null=默认）；设置项总数 139→140（General 9→10）。
- **QSettings**：无新增键；模型目录保存在 config 而非 QSettings。
- **tab/界面**：右侧 tab 变为 对象/类别/标志/描述/统计（隐藏集合持久化于
  `right_tabs.hidden`，旧配置中未知 key 会被忽略）；对象/类别 tab 不再有标题栏、显隐/锁定
  全部按钮与逐行复选框/锁图标。
- **设置页标题**：现在会按 .ts 翻译（此前只翻译描述），中文界面字段标题全部中文化。
- **模型目录**：切换目录时旧目录模型自动 move；失败时保留旧文件并提示，不做回滚。
  极老 `anylabeling_data/models` 目录不自动迁移，但仍会被扫描到。

### 5. 实际验证内容

- 单元/集成测试（分批执行，避免一次性大批量运行触发本机页面文件/内存级崩溃）：
  - `tests/test_widgets + tests/test_settings + tests/test_config + tests/test_utils +
    test_model_storage.py`：**283 passed / 1 skipped**，1 条 `canvas_adjustment`
    节流计时失败为本机 offscreen 计时抖动（改动前同样偶发）；
  - `tests/test_labeling` 分批：`file_table/image_switch/label_locks/label_manager_locks/
    label_widget_metrics/check_status/image_tags` 共 **60 passed**（1 条失败为 POSIX `/tmp`
    路径在本机变成 `E:\tmp` 的既有环境断言），`test_relations.py` **21 passed**；
  - `tests/test_utils`（含新搜索/统计用例）**162 passed**；i18n 相关 `pytest` **41 passed**；
  - 注：`tests/test_labeling` 整目录单进程运行在本机会在若干重型用例处触发
    `Fatal Python error: Aborted`（页面文件/内存环境问题，单独/分批运行均通过），
    未声称整目录一次性通过。
- 真实 Windows 平台冒烟：
  - 搜索：split 中英文条件、`label::cat|dog,split::train`、`label::cat,dog`、`!label::cat`、
    括号跨字段组合等 11 组经 UI 输入后文件列表结果全部正确；
  - 统计 tab：构造 4 图数据集，表头/行列计数/合计口径与图二一致；点击单元格回填
    `label::object_0,split::train` 并过滤出正确文件；点击 `（无对象图）` 回填
    `shape::0,split::none`；
  - 普通列表 tab：MainWindow 启动、tab 切换、对象/类别列表添加/选择/双击正常，
    标题栏控件属性确认不存在；
  - i18n：4 语言 QTranslator 探针通过（zh tab `对象/类别/标志/描述/统计`、弹窗
    `输入类别/对象描述`、统计表头 `类别/训练/验证/测试/未划分/合计/（无对象图）`、
    设置页 `模型保存目录/默认位置/浏览`），en_US 组件无中文泄漏。
- 未联网真实下载模型，也未在真实 125%/150% HiDPI 显示器验证。

### 6. 已知限制与后续事项

- 统计表刷新为“切到统计 tab / 导入 / 移除 / 改 split”时同步读取当前文件列表的标注 JSON；
  数万文件规模首次刷新可能卡顿，后续可加防抖或后台线程。
- `statistics_table.py` 与 `runtime_applier.py` 中有少量 `self.tr(变量)` 形式的手工 .ts 条目，
  未来重跑 `pylupdate6 --no-obsolete` 需复用临时补译脚本或改为显式 context。
- 移除对象/类别 tab 的逐行显隐与锁定 UI 后，单对象显隐可通过视图菜单/筛选完成，逐对象
  锁定仍可在画布右键菜单操作；类别管理器的会话级锁定策略保留但不再在列表绘制。
- 模型目录迁移为简单 move，不支持跨卷失败回滚；极老 `anylabeling_data` 目录不自动迁移。
- `docs/dev/CODE_STRUCTURE_REPORT.md` 仍为 4.3.2 基线静态分析快照。

## 4.3.2+fork.1 — 2026-11-10

### 1. 背景与原因

- 本项目是 X-AnyLabeling 4.3.2 的私有 fork，目标是演进为自用工业视觉数据平台；本版本是该
  fork 的第一个可运行、可提交的基线。
- 上游 4.3.2 的界面形态与本项目现场使用习惯冲突：文件列表信息密度低、右侧 dock 占用大量纵向
  空间、工具栏无法按要求停靠，且旧版本遗留的配置/窗口状态会在升级后触发告警甚至启动失败。
- 本版本在保持上游标注/自动标注/训练能力不变的前提下，完成文件列表表格化、右侧栏 tab 化、
  工具栏停靠化，并修复升级兼容性与 Windows 浮动工具栏几何崩溃问题。

### 2. 主要实现与关键细节

#### 2.1 文件列表表格化（`file_list_widget` → `QTableWidget`）

- 文件列表改为 5 列表格：`文件 / 对象 / 导入时间 / 推理 / 划分`；文件名前增加缩略图。
- 去掉每行前的 checkbox，勾选状态由行内状态点/文本表达；行号使用原生 vertical header，
  排序后行号与文件映射保持一致。
- 「导入时间」「推理」「划分」三列可在表头右键菜单中显示/隐藏；5 列均可拖拽调整宽度并持久化到
  `file_list.column_widths`；文件列在未手动调整前自动填满剩余宽度。
- 导入时间持久化到图片目录下的 sidecar `.xanylabeling_import_time.json`（不污染标注 JSON，
  未标注图片也能记录）；sidecar 缺失时回退文件 mtime。
- 行右键「从列表移除」只从列表移除，不删除磁盘文件（带确认弹窗）。
- 缩略图开关、行高（36px / 隐藏缩略图时 20px）持久化。

#### 2.2 右侧栏 dock → tab

- 移除右侧全部 `QDockWidget`（`description_dock`、`label_dock`、`flag_dock`、`shape_dock`、
  `file_dock`），改为 `QTabWidget` 4 个 tab：`对象 / 标签 / 标志 / 描述`。
- tab 可通过 tab 栏右键菜单显示/隐藏（至少保留 1 个），隐藏集合持久化到
  `right_tabs.hidden`；tab 内部重复标题行删除，仅保留「眼睛/锁」小按钮。
- tab 区与文件列表之间使用纵向 `QSplitter`（带拖拽柄）调整比例。

#### 2.3 工具栏停靠化与浮动缺陷修复

- 标注工具栏改为真正的 `QToolBar`，支持停靠顶部/左侧，可从「视图」菜单或工具栏右键菜单切换；
  位置与可见性持久化到 `window/toolbar_area` / `window/toolbar_visible`。
- 禁用浮动（`setFloatable(False)`）：Qt 6 的浮动工具栏路径在 Windows 上会触发
  `QWindowsWindow::setGeometry` 几何爆炸（宽度/高度逐次翻倍，直至 32767），最终
  `createDIB: CreateDIBSection failed` 并使进程异常退出。
- 修复升级后仍会复现该崩溃的根因：旧版通过 `QMainWindow.saveState/restoreState` 保存窗口状态，
  其中标记为 floating 的工具栏会被 Qt 还原为浮动窗口——即使 `setFloatable(False)`
  （`QToolBarPrivate::setWindowState` 不检查该标志）。现在不再读写 `window/state`，启动时丢弃该
  遗留键，工具栏位置改由上述显式键持久化。

#### 2.4 右侧边栏最小宽度

- 旧实现把 `minimumWidth` 设置为侧栏初始宽度（实测 580px），用户无法拖窄。
- 改为独立最小宽度（`max(220, sizeHint * 0.8)`，随 UI scale 缩放），拖拽可到 220px；
  侧栏变窄后文件表格列溢出可横向滚动，不再被最小宽度顶死。

#### 2.5 旧配置键静默迁移

- 旧 `.xanylabelingrc` 中的已删除键（`description_dock`、`file_dock`、`flag_dock`、
  `label_dock`、`shape_dock`、`file_list_checkbox_editable`）在加载时静默丢弃，不再逐条输出
  `Skipping unexpected key in config` WARNING；真正的未知键（拼写错误）仍保留告警。
- 设置项总数 140 → 139（移除 `file_list_checkbox_editable`）。

#### 2.6 国际化与文档

- 新增/变更文案已同步 en_US / zh_CN / ja_JP / ko_KR 翻译并重建 `resources.py`。
- 用户手册（en/zh_cn `user_guide.md`）更新文件列表新表格行为与工具栏停靠说明。

### 3. 涉及模块与文件

- 主界面：`anylabeling/views/mainwindow.py`、`anylabeling/app_info.py`
- 标注视图：`anylabeling/views/labeling/label_widget.py`
- 部件：`anylabeling/views/labeling/widgets/toolbar.py`、`widgets/panel.py`
- 配置：`anylabeling/config.py`、`anylabeling/configs/xanylabeling_config.yaml`、
  `anylabeling/views/labeling/settings/schema.py`、
  `anylabeling/views/labeling/settings/runtime_applier.py`
- 工具与样式：`anylabeling/views/labeling/utils/style.py`、`utils/file_meta.py`、
  `utils/thumbnail.py`、`utils/export.py`、`utils/upload.py`
- 翻译资源：`anylabeling/resources/translations/{en_US,zh_CN,ja_JP,ko_KR}.{ts,qm}`、
  `anylabeling/resources/resources.py`
- 文档：`docs/user/en/user_guide.md`、`docs/user/zh_cn/user_guide.md`、本文件
- 测试：`tests/test_labeling/test_file_table.py`、`tests/test_widgets/test_mainwindow_state.py`、
  `tests/test_widgets/test_toolbar_layout.py`、`tests/test_config/test_normalization.py`、
  `tests/test_settings/test_schema.py`、`tests/test_utils/test_file_meta.py`、
  `tests/test_utils/test_thumbnail.py` 等

### 4. 行为、接口与兼容性影响

- **配置键**：上述 6 个旧键被静默删除，不再写回；升级后首次保存配置即从 `.xanylabelingrc`
  消失。新增 `right_tabs`、`file_list` 配置节。
- **QSettings 键**：不再使用 `window/state`（启动时删除遗留值）；新增
  `window/toolbar_area`（`top`/`left`）与 `window/toolbar_visible`。升级后若原先工具栏在左侧，
  首次启动会回到顶部，之后选择会被记住。
- **版本号**：`__version__` 由 `4.3.2` 改为 `4.3.2+fork.1`（PEP 440 合法本地版本）；
  使用 `packaging.version` 的更新检查与打包元数据均可正常解析。
- **工具栏**：不再支持拖成浮动窗口（Qt 6 在 Windows 上的已知缺陷），仅支持顶部/左侧停靠。
- **默认宽度**：右侧栏初始宽度仍按可见列宽自适应（实测 580px），但可自由拖窄至 220px。

### 5. 实际验证内容

- 单元/集成测试：`tests/test_labeling` + `tests/test_settings` + `tests/test_widgets` +
  `tests/test_config` + `tests/test_utils` 共 410 passed / 6 failed（6 条为本机环境性失败：
  POSIX `/tmp` 路径断言、DSH 沙箱临时目录写权限、离屏计时抖动，与代码改动无关）。
- 升级场景验收（真实 Windows QPA）：用「含 6 个旧配置键的 `.xanylabelingrc` + 含浮动工具栏
  巨大几何的旧 `window/state`」启动主窗口——无旧键 WARNING、无 `setGeometry`/`createDIB`
  输出、工具栏停靠顶部、进程正常退出。
- 缺陷复现对照：修复前同一场景在 `MainWindow` 构造期即 `createDIB: CreateDIBSection failed
  (32767x32767)` 并异常退出（exit 0xC0000409）；修复后通过。
- 右侧栏最小宽度（真实 Windows QPA，dpr=1.0）：1280x800 / 1500x900 / 1920x1009 三种窗口下
  `minimumWidth=220`，拖拽 260→260、220→220、200→被 clamp 在 220；缩窄后文件表格仍可见可横向滚动。
- 新增回归测试均为实际执行：`test_mainwindow_state.py` 4 项、`test_normalization.py` 2 项、
  `test_file_table.py` 侧栏 2 项；并验证把最小宽度临时改回旧行为时对应测试会失败。

### 6. 已知限制与后续事项

- 工具栏浮动窗口不可用（Qt 6 Windows 缺陷）；如确需浮动窗口，需改用 `QDockWidget` 承载，
  外观会带可拖动标题栏，待评估。
- 更新检查仍指向 `CVHub520/X-AnyLabeling` 上游 releases；fork 自用场景可能收到上游更新提示，
  后续可改为读取本 fork 的发布信息。
- `docs/dev/CODE_STRUCTURE_REPORT.md` 是 4.3.2 基线（2026-11-09）的静态分析快照，未随本次
  版本号更新；其版本字段仍描述分析基线。
- 未在真实 HiDPI 显示器（125%/150%）上验证；仅用离屏 `ui_scale=1.375` 路径覆盖了按比例缩放。
- `temporary/` 与 `docs/session.md` 为本地工作文件，已加入 `.gitignore`，不纳入版本库。

# CHANGELOG-fork.md

本文件记录本 fork 相对上游 [X-AnyLabeling](https://github.com/CVHub520/X-AnyLabeling) 4.3.2 的改动。

版本规则：`4.3.2+fork.N`（N = 1, 2, 3 …，PEP 440 本地版本写法，语义等价于「4.3.2 fork N」）。
采用 `+` 形式是 PEP 440 唯一合法写法；`4.3.2-fork.1` 等写法会被 `packaging.version` 判为非法，
进而影响 `python -m build` 与 `update_checker` 的版本比较。

---

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

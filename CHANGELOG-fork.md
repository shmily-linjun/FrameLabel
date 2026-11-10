# CHANGELOG-fork.md

本文件记录本 fork 相对上游 [X-AnyLabeling](https://github.com/CVHub520/X-AnyLabeling) 4.3.2 的改动。

版本规则：`4.3.2+fork.N`（N = 1, 2, 3 …，PEP 440 本地版本写法，语义等价于「4.3.2 fork N」）。
采用 `+` 形式是 PEP 440 唯一合法写法；`4.3.2-fork.1` 等写法会被 `packaging.version` 判为非法，
进而影响 `python -m build` 与 `update_checker` 的版本比较。

---

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

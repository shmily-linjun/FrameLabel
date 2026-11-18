# CHANGELOG-fork.md

本文件记录本 fork 相对上游 [X-AnyLabeling](https://github.com/CVHub520/X-AnyLabeling) 4.3.2 的改动。

版本规则：`4.3.2+fork.N`（N = 1, 2, 3 …，PEP 440 本地版本写法，语义等价于「4.3.2 fork N」）。
采用 `+` 形式是 PEP 440 唯一合法写法；`4.3.2-fork.1` 等写法会被 `packaging.version` 判为非法，
进而影响 `python -m build` 与 `update_checker` 的版本比较。

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

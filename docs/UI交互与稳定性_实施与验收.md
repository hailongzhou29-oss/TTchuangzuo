# TT 创作助手：本轮实施与验收

2026-10-01。源码目录 `J:\精简版本\TTchuangzuo`，Git HEAD 保持 `8915390c303d6f0140ecfb1d1228253f0baf25be`。在现有未提交修改之上继续实施，没有重置、覆盖用户数据、推送、打包、修改授权或发出付费模型请求。

本轮以已读取的《TT创作助手_UI交互与稳定性总规范》为实施依据；之前已取得并查看本地 `创建剧本_拟改布局.png` 的实际图片。范围是共享外壳、控件、剧本页和对应稳定性修复，不推进小说、仿写页面的下一阶段。

## 实施内容与文件

| 文件 | 本轮内容 |
|---|---|
| `app/ui/interaction.py` | 统一主题参数、中文字体、焦点与悬停边界、可中断动效、下拉列表、原生输入法组合状态保护、屏幕边界定位 |
| `app/ui/v2_widgets.py` | 统一卡片/字段样式，单选与多选弹层，标签摘要、图形箭头和发送输入规则 |
| `app/ui/script_settings.py` | 固定基本六项，独立补充入口；表现形式三项与三个详情页签；剧情六个页签按当前内容计高；自定义字段下一整行；响应式列数；局部更新、错误定位与旧设置中文处理 |
| `app/ui/creation_page.py` | 设置/正文切换和各自滚动焦点恢复；草稿合并保存、失败保留输入；界面展开状态单独持久化；先归属父布局再显示控件 |
| `app/ui/v2_window.py` | 导航与顶栏；助手宽度保存、可靠恢复和窄窗子面板；页间返回；统一字体与主题 |
| `app/ui/assistant_panel.py` | 保留模型选择、聊天输入、发送和真实业务连接，发送图标统一 |
| `app/core/script_settings.py` | 保持目录绑定；按载体过滤有效字段；旧“人物一生”映射“人生”；明确保留的旧要求参与实际设置 |
| `tools/gui_bootstrap.pyw`、`tools/launch_gui.pyw`、根目录启动入口、`tools/run_dev.ps1` | 配置解释器启动、无控制台入口及启动失败日志；不绕过机器的脚本执行策略 |
| `tests/test_ui_stability_rules.py`、`tools/ui_stability_acceptance.py`、相关既有验收工具 | 对应回归与真实窗口截图/录屏，隔离临时数据，不调用付费模型 |

其他既有修改继续保留。上表不是整个工作区与 Git HEAD 的完整差异清单；此前业务逻辑、目录、台词记录和测试改动没有被回退。

## 验收结果

实际解释器：`J:\codex\tt_yingxu_build_v2_wan3\venv\Scripts\python.exe`；Python 3.12.9 / PySide6 6.11.1。

以下命令均从源码根目录执行，`python` 指上述解释器。

| 命令/检查 | 状态 | 证据 |
|---|---|---|
| `python -m unittest discover -s tests`（离屏） | **208/208 通过** | `evidence/ui_stability_unit_final.log` |
| `python tools/script_safety_acceptance.py` | **33/33 通过**，固定响应/无费用 | `evidence/script_safety/results.json` |
| `python tools/script_unified_acceptance.py` | **137/137 通过**，离屏/固定响应 | `evidence/script_unified_offscreen_native/results.json` |
| `python tools/ui_stability_acceptance.py` | **96/96 通过**，离屏 | `evidence/ui_stability_offscreen_native/results.json` |
| `python tools/ui_stability_acceptance.py --native-hidden`，分别设置进程级 `QT_SCALE_FACTOR=0.8/1.0/1.2/1.6` | 每组 **88/88 通过**；实际 DPR **1/1.25/1.5/2** | `evidence/ui_stability_native-hidden_*/results.json` |
| `python tools/ui_stability_acceptance.py --visible` | 原始结果 **93/95**；见下方两项复核 | `evidence/ui_stability_visible_native/results.json` |
| pythonw / BAT / 快捷方式无窗口启动探测 | 三种入口探测成功、无附属控制台 | `evidence/ui_stability_*probe.json` |

原生隐藏窗口的四项焦点/悬停检查明确记为**未运行**，没有混入 88 项通过数。四种 DPR 是同一显示器上的进程级缩放测试，未修改系统 DPI，也不代表跨物理显示器验收。

可见运行 PID 13580，Windows 平台，实际 DPR 1.25；只有一轮完整可见验收，之后进行了两个短定点诊断。全部测试窗口已按自身生命周期关闭，没有处理用户未知 Python 进程。

可见原始失败记录保留，未改成全部通过：

1. **窗口数量断言复核已定位。** 系统枚举返回两个无标题窗口，类名分别为 `UAC_InputIndicatorOverlayWnd` 与 `UAC Input Indicator`。定点诊断显示它们在弹层打开前就存在，属于环境输入指示器；Qt 显示事件中唯一无父对象窗口是 MainWindow。不是复现出的字段独立窗口。证据：`evidence/ui_stability_visible_native/native-window-diagnostic.json`。这不解释用户此前未知进程的来源。
2. **真实指针悬停检查仍未确认。** 指针坐标成功移至目标行，但本次原生环境没有向 Qt 投递 Enter/MouseMove/Leave 事件，悬停值仍为 -1。定点日志：`evidence/ui_stability_visible_native/pointer-diagnostic.json`。离屏预览逻辑通过，不能替代真实指针验收，因此保留此项未确认，不能宣称完整交互验收通过。

重启宽度回归最初读到 0，原因是脚本在窗口重布局完成前立即取尺寸；补上事件队列等待后，137 项回归通过，断言阈值没有放宽。输入十次不会触发整表 reflow 或网格重建；20 轮父选项、自定义中文、多选、展开、页签、助手、缩放操作均通过对应数据保持检查。

## 真实截图与录屏

下列均来自**实际运行的 PySide6 窗口**，使用窗口抓取，不是设计图。已查看主要截图的实际像素。

- [正常设置页](evidence/ui_stability_visible_native/01-default-settings.png)
- [自定义身份整行与基本补充](evidence/ui_stability_visible_native/03-custom-identity.png)
- [助手展开/恢复](evidence/ui_stability_visible_native/07-assistant-restored.png)
- [助手收起](evidence/ui_stability_visible_native/08-assistant-collapsed.png)
- [正文页与长文本](evidence/ui_stability_visible_native/09-body-view.png)
- [窄窗口设置页](evidence/ui_stability_visible_native/10-narrow-closed.png)
- [窄窗口助手子面板](evidence/ui_stability_visible_native/11-narrow-overlay.png)
- [实际操作录屏 MP4](evidence/ui_stability_visible_native/实际操作录屏.mp4)

录屏保留 115 个实际采样帧，按采样时间编码，960×600，约 904 KB；编码日志与原始帧目录保留。录的是测试应用自己的窗口，没有录入用户其他窗口。本轮按后续交付范围保留本地证据，没有新增 Library 上传或虚构 Library 文件 ID。

## 启动

本机推荐双击根目录 **`启动TT创作助手.lnk`**，使用已配置的 pythonw 启动源码。快捷方式路径已探测通过。

开发调试：

```powershell
Set-Location 'J:\精简版本\TTchuangzuo'
& 'J:\codex\tt_yingxu_build_v2_wan3\venv\Scripts\python.exe' -m app.main
```

显式无控制台启动：

```powershell
& 'J:\codex\tt_yingxu_build_v2_wan3\venv\Scripts\pythonw.exe' 'J:\精简版本\TTchuangzuo\tools\gui_bootstrap.pyw'
```

启动日志在 `logs/startup.log` / `logs/gui-runtime.log`。BAT 探测成功，但双击 BAT 本身可能短暂显示命令窗口。本机 PowerShell 文件执行策略阻止 `.ps1`，没有绕过；默认 `.pyw` 文件关联所用的 pyw 找不到已安装解释器，因此不推荐仅双击 `.pyw`。

## 剩余边界

- 真实指针悬停尚未完成确认；原生中文输入法候选窗、物理多屏切换、系统高对比模式未实测。组合事件与防误发送是 Qt 合成输入验证。
- 不将自动检查计时当作用户感知的 100 ms 视觉响应达标证明。
- 没有付费模型输出质量、真实语音/视频生成或模型供应商网络验收。
- 本阶段代码与证据可供复核，不等同用户已经验收，也不宣布全项目完成；小说、仿写后续阶段未推进。

## 视觉复核后的定点修复：字段底边裁切

主线程查看真实截图后发现基本方向、表现形式输入框底边被裁切。此前查看截图时没有正确处理这一可见缺陷，本次已按该反馈修复，未重新设计。

复现测量：标签 18 + 间距 6 + 控件 38 = 62 像素，但基本字段包装只有 61、表现形式包装只有 60。`fit_cards()` 使用了内部 `layout().sizeHint()`，漏算 QFrame 的上下边框；固定控件高度不变，压缩后的父包装裁掉底部。

修复仅在 `app/ui/script_settings.py` 的卡片适高逻辑中改为 `card.sizeHint().height()`，使用包含框架边界的整体高度。

`python tools/field_border_acceptance.py --visible`：**36/36 通过**，Windows / DPR 1.25，隔离临时数据。测试覆盖默认基本六项、表现形式三项、自定义详情、窄窗基本项，除父包装包含检查外，还逐项检测实际应用截图中输入框底边中央的绘制像素。已实际查看默认整窗、基本卡片、表现形式卡片和自定义字段截图，边框闭合、文字完整。测试窗口已自行关闭。没有重跑全量矩阵；之前 208/137/96 等结果是此次定点修改前的结果。

- [修复后的设置整窗](evidence/field_borders_visible/01-default-settings-fixed.png)
- [基本方向卡片像素近图](evidence/field_borders_visible/02-basic-card-fixed.png)
- [表现形式卡片像素近图](evidence/field_borders_visible/03-presentation-card-fixed.png)
- [自定义详情](evidence/field_borders_visible/04-custom-field-fixed.png)
- [窄窗口](evidence/field_borders_visible/05-narrow-settings-fixed.png)
- [36 项定点检查原始结果](evidence/field_borders_visible/results.json)

hover 未追加检查、未改逻辑，仍保持未确认。独立 Qt.Popup 不会包含在主窗口 grab 中；旧 `05-menu-states.png` 只有主窗口已选值状态，不是独立菜单或 hover 截图。

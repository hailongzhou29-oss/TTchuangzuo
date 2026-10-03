# 规则、三页设置与 AI 助手：本地开发阶段交付

日期：2026-10-01。源码目录：J:\精简版本\TTchuangzuo。
HEAD：8915390c303d6f0140ecfb1d1228253f0baf25be。保留此前剧本、小说、仿写改动，没有回退源码。
本阶段提供完整可运行的本地闭环；真实供应商质量、生图及原 TT 逐图对齐不作为已通过项。用户已明确允许视觉对齐后续收敛。本次不再扩展功能。

## 已交付功能

- 一级导航为首页、创建剧本、创建小说、仿写内容、设置；隐藏独立资料与规则入口。内部规则、命中选择、历史资料和作品内设定仍可用；规则损坏时允许打开作品并提供重试，生成被明确拦截。
- 设置只保留国内模型、Codex 本地、通用图片API。复用 TT-YingXu 固定提交 8f80b197e66c61f16c19596c0da5fcdc642017ee 的模型搜索、Codex 四卡片及图片表单等 19 个原函数。保存与启用分离，未保存表单不能半新半旧启用；模型列表失败可以手填。
- 新软件独立配置和 Windows DPAPI 密钥库。图片站点按协议与地址区分，模型、尺寸、价格和凭据不串站；清理只作用于本软件。未保存密钥不显示已加密保存。模型、地址、凭据及 CLI 路径变化会失效相关验证。
- 助手连接当前作品和冻结版本：能检查、讨论、读取当前项目文档分页与规则，生成修改或规划候选。原生工具能力未知的模型走受限 JSON 工具桥，不以未知当作平台支持。Codex 继续使用只读隔离会话；模型覆盖留空可使用 CLI 默认模型。
- 修改先显示候选，比较并明确采用后才更新作品。采用核对项目、文档、版本、段落 ID/hash、用户手改和锁定内容；正文、衍生台词记录与采用回执在 SQLite 事务内写入。重复采用不增加版本；撤销保留版本并恢复原稿。候选和撤销入口可在重新打开作品后恢复。
- LangGraph 控制模型与受限工具轮次，SQLite 检查点保存在原项目数据库，没有第二份权威正文。默认最多 3 轮模型、8 次受限工具读取；提交前记录外部轮次，重复提交被拦截，重启不会自动重发收费请求。检查覆盖记录含读取分页与未读取文档，不能把未读内容说成全书已查。
- 当前正文和用户设定优先；正文修改后旧摘要失效，依赖旧正文版本的事实不进入当前有效事实。项目范围隔离。
- 封面提示词可见、可编辑，可从当前正文或创作条件填入主体素材、构图、光线、风格、画幅与标题留位。只有点击生成才提交图片任务，先校验并预览，采用后绑定作品；旧封面不删除。记录提示词、渠道、模型、任务 ID、实际像素及哈希；模拟图片不会登记为真实模型生图成功。原任务查询路径保留。

## 验证结果与命令

运行环境：Python 3.12.9 / PySide6 6.11.1。解释器：J:\codex\tt_yingxu_build_v2_wan3\venv\Scripts\python.exe。

| 命令（在源码根目录，使用上述解释器） | 最新结果 | 证据 |
|---|---|---|
| -m unittest discover -s tests | 239/239 通过 | docs/evidence/agent-full-tests.txt |
| -m unittest discover -s tests -p test_agent_workflow.py | 22/22 通过（全量包含这 22 项） | docs/evidence/agent-targeted-tests.txt |
| tools/rules_builtin_acceptance.py --visible | 7/7 通过 | docs/evidence/rules_builtin/results.json |
| tools/settings_reuse_acceptance.py --visible | 18/18 通过 | docs/evidence/settings_reuse/results.json |
| tools/agent_ui_acceptance.py --visible | 12/12 通过 | docs/evidence/agent_ui/results.json |

设置与助手截图来自 Windows 实际显示窗口，DPR 1.25。模型和图片响应是明确标识的隔离模拟，未调用真实供应商、未产生模型费用、未执行登录。测试使用临时配置和临时测试凭据，未读取生产密钥。全量包含本地 HTTP 协议模拟，不能据此声称真实供应商通过。

失败记录：第一次全量回归出现 43 个 SQLite 临时目录清理错误，原因是检查点连接没有关闭；已改为显式关闭，后续全量 239 项通过。第一次设置异步失败回调参数不匹配，已修复；第一次原生助手测试使用未选中的“这段”，按预期被拦截，改为明确“当前正文”后通过。没有把这些初次失败当成通过。

## 32 项验收矩阵

“已验证”仅指该行列明的本地范围；模拟通过不等于真实模型质量通过。“未验证”明确保留边界。

| 编号 | 状态 | 实际证据或边界 |
|---|---|---|
| A01 | 已验证（本地） | 规则/导航 7 项，五个一级入口；历史参考与选择保留 |
| A02 | 已验证（模拟） | 既有创作路径、前阶段创作验收及全量回归；真实空想法创作质量未测 |
| A03 | 已验证（本地） | 历史正文、资料、规则引用重开；旧封面在新候选时保留 |
| S01 | 未验证，视觉后续收敛 | 固定源码与三页运行已核实；原 TT 国内模型、Codex 四卡片、图片API三张基准图未逐图对照 |
| S02 | 已验证（本地） | DS/千问保存互不覆盖，保存不自动启用 |
| S03 | 已验证（本地） | 文本及图片未保存表单启用被拦截 |
| S04 | 已验证（模拟） | 模型列表失败保留手填；真实接口连接未测 |
| S05 | 已验证（本地） | 两站点参数、价格、测试凭据独立，旧连接快照保留原站；原站后续被编辑/删除等真实查询未测 |
| S06 | 已验证（本地） | 清理隔离产品库，另一测试产品字节不变；未读真实 TT影序凭据 |
| C01 | 已验证（模拟状态） | CLI 未登录时四项分别显示，不宣称生图可用；真实机器登录状态未探测 |
| C02 | 已验证（模拟状态） | 发现 imagegen 不等于实际生图成功，不导入旧 TT 成功标记 |
| C03 | 未验证（真实调用） | 模拟 PNG 解码、预览、采用及记录通过；真实生图未调用 |
| U01 | 已验证（原生窗口） | 连续五次收起/展开、宽度恢复、输入保持、切页返回 |
| U02 | 未完整验证 | 中文文本与页面操作通过；真实中文输入法组合输入/高速连切仍需人工验收 |
| G01 | 已验证（模拟） | “只检查，别续写”不会续写，正文和版本数不变 |
| G02 | 部分验证 | 第三章定位路径保留、结尾保护校验通过；自然语言创作效果与整组第三章用例未做真实模型评价 |
| G03 | 已验证（本地/模拟） | 相同台词第二处按稳定范围与 ID 修改，第一处保留 |
| G04 | 已验证（本地/模拟） | 手改或另一窗口更新后旧候选不可覆盖 |
| G05 | 部分验证 | 跨项目采用被拒绝，异步回包按原 work/store 保存；新界面中的延迟切项目操作尚未完整重测 |
| G06 | 已验证（本地） | 采用/撤销/重复采用；写入异常事务回滚；候选重开可用 |
| G07 | 已验证（本地） | 锁定文字改变时事务拒绝，版本和候选状态不被半写 |
| G08 | 部分验证 | 前阶段仿写原文隔离与结果候选保留通过；真实人物/商品事实创作质量未测 |
| M01 | 部分验证 | 原文修改失效旧摘要，旧依据事实从有效上下文排除；真实模型关系问答未测 |
| M02 | 部分验证 | 分页读取、预算、覆盖记录与未读提示接通；超长全书自动检查完整质量未验收 |
| M03 | 已验证（本地边界） | 工具仅允许当前项目冻结文档，跨项目 ID 拒绝；真实同名人物问答未测 |
| R01 | 部分验证 | 取消不提交/不采用，提交回执、检查点和重复提交保护通过；流式中断后整个 GUI 重启流程未完整人工验收 |
| R02 | 已验证（协议模拟） | 既有图片任务查询和图像工作流单测通过，不自动新生第二单；真实平台异步任务未测 |
| R03 | 已验证（模拟） | 坏 JSON、空正文、越界工具/目标、锁定修改被拦截，原稿不变 |
| R04 | 部分验证 | 升级备份存在，新增候选表及迁移完成标记幂等；强制中断升级过程未做破坏性测试 |
| R05 | 已验证（测试范围） | 测试截图为空白密码输入/虚构模型，交付不含生产凭据；完整个人生产数据审计未进行 |
| V01 | 未完整验证 | 真实 125% 与窄窗口可操作；图片设置在窄宽度使用横/纵滚动；100/150/200%真实显示及所有下拉逐项未测 |
| V02 | 部分验证 | 原生候选生成、采用、撤销、切页、关闭及全量回归通过；无限循环压力与所有耗时关闭组合未测 |

## 实际截图及 Library 确认 ID

| 内容 | 本地路径（docs/evidence/ 下） | library_file_id |
|---|---|---|
| 五个一级页入口 | rules_builtin/01-five-pages.png | libfile_2f0658e2ad848191b35047bb218e572e |
| 国内模型 | settings_reuse/01-domestic.png | libfile_9a83e28188a8819180fced74acf17c18 |
| Codex 四卡片 | settings_reuse/02-codex.png | libfile_12f320ab23b08191a5615342f1eec996 |
| 通用图片API | settings_reuse/03-images.png | libfile_bc6ea125d68c81918630ad2d1a8eea16 |
| 设置窄窗口 | settings_reuse/04-narrow.png | libfile_e876b1bec5a881919702a81d00a9e469 |
| 助手修改候选 | agent_ui/01-candidate-assistant.png | libfile_9d90701de5f48191a18e1aa703c20a28 |
| 采用前比较 | agent_ui/02-compare.png | libfile_7dec7f00fab4819180dcc15c350fbe56 |
| 可编辑封面提示词 | agent_ui/05-cover-prompt.png | libfile_65ffd1d522688191a301a1ac40c52611 |
| 助手窄窗口 | agent_ui/06-narrow-assistant.png | libfile_a5fd7265469c81919a47a18fa61124b8 |

保存返回均确认 succeeded。四张设置图使用原 Library ID 更新到版本 1，其他八图批次内助手图为版本 0。本地对应关系保存于 docs/evidence/agent-library-delivery.json；Windows 扩展元数据写入不支持，因此不声称图像文件自身已写入 Library 标识。这里列出的是应用运行截图，不是设计渲染图。助手截图中的回复与配置均为模拟测试材料。

## 修改文件与依赖

本阶段新增：app/core/settings_controller.py、agent_graph.py、agent_candidates.py；app/ui/tt_settings_page.py、tt_settings_widgets.py；tests/test_agent_workflow.py；tools/upgrade_baseline.py、port_tt_settings.py、rules_builtin_acceptance.py、settings_reuse_acceptance.py、agent_ui_acceptance.py。
本阶段修改：app/__init__.py；app/core/selection.py、creation_flow.py、work_context.py、project_tools.py、tasks.py；app/providers/contracts.py、image_contracts.py、codex_text.py；app/storage/connections.py、project.py；app/ui/assistant_panel.py、cover_panel.py、v2_window.py；requirements.txt、.gitignore。
先前创作页等改动全部保留，不把累计 git diff 当成本阶段全部新写内容。

增加 langgraph==1.0.10、langgraph-checkpoint-sqlite==3.0.1，安装在源码 .deps 中，没有修改共用 venv。41 项传递依赖精确版本见 requirements-agent.lock，许可证 METADATA 记录见 docs/AI依赖与许可证.json。默认强制关闭 LANGSMITH_TRACING 与 LANGCHAIN_TRACING_V2，不向跟踪服务上传作品。

## 数据、启动与剩余事项

升级前恢复点：backups/agent_upgrade_20261001_152411，含当时源文件压缩备份、6 个项目数据库的 SQLite 一致性备份及完成清单；不含模型配置/密钥库，不导出资产。新表、检查点是项目数据库附加记录，正文仍由原 revisions/documents 权威存储。图片站点元数据位于本产品配置目录，凭据仍在独立 DPAPI 库。

源码启动：在源码根目录运行上述 Python 解释器加 -m app.main。已有“启动TT创作助手.lnk”调用无控制台 pythonw 源码入口，可继续使用。新建干净环境可安装 requirements.txt；当前工作区已可直接启动，.deps 已就位。

剩余人工验收：原 TT 三张视觉基准（用户允许后续收敛）、真实供应商模型/图片质量、真实中文输入法与其他物理 DPI、超长作品全覆盖及故障重启组合。原仿写页约 98px 留白和目录混合选择问题按父线程记录留到后续调整。没有真实权限阻塞；未构建安装包、未推送、未自动登录或迁移认证，也不自动推进下一阶段。


# 需求与验收

## 用户、目标和范围

面向内容团队，输入素材ID、每项hard/soft时间、渠道和可选确认，输出有证据的审核与排期草稿以及待处理项。范围为CLI、单Agent、合成资料、SQLite和离线验证。

需求来源：根目录 `小影科技2027校招AI Agent笔试题.md`、`素材审核与发布排期Agent.md`，以及实现阶段整理的工程约束。当前 README 为运行与评审入口；工程约束已映射到下文验收点与 `docs/02`。

## 业务验收映射

| ID | 验收点 | 用例 | 实现/验证 |
| --- | --- | --- | --- |
| A01 | M01无风险、可用时间、保存成功 | normal | tools.py、test_agent.py |
| A02 | M02缺资料先补查，仍缺不排期 | missing_info | read_asset、check_rules、guards.py |
| A03 | M03高风险阻断并保留原因 | rule_risk | 规则及审核/保存护栏 |
| A04 | soft占用18:00建议19:00，存待确认草稿 | slot_conflict | query_slots、改时确认护栏 |
| A05 | hard时间未经授权不自动更改 | slot_conflict_hard | 保存和finish双护栏 |
| A06 | 相同请求重复只一条草稿 | duplicate | 事务与UNIQUE、原ID/行数断言 |
| A07 | 两次保存注入失败，不能称成功 | save_failure | 注入器、尝试上限、保存真实性 |
| A08 | 相同输入只变工具数据，建议变为20:00 | slot_swap | 仍请求18:00；夹具占用18/19 |
| A09 | 低风险可存草稿但保留人工确认 | low_risk | 风险原因及pending一致性 |
| A10 | hard改时只接受精确授权 | hard_confirmed | 另测错误时间、拒绝回答、伪造同意 |
| A11 | 两类预算上限，部分结果与缺口 | pytest | test_budget_partial、边界finish测试 |
| A12 | 防伪保存、防遗漏、防批内冲突及禁词 | pytest | test_guards.py、test_protocol.py |

## 工程硬约束映射

| 要求 | 文件/验证 |
| --- | --- |
| 真实function calling→工具→observation→再决策 | agent.py、llm.py；真实效果待验证 |
| Mock根据observation决策，同协议且明确边界 | MockLLM、README、评估文档 |
| MAX_STEPS默认12、独立工具预算、超限未完成 | agent.py、cli.py、预算测试 |
| OpenAI SDK、三项LLM变量、temperature=0 | llm.py、.env.example、离线接线测试 |
| 六个本地工具、统一envelope、异常回填 | tools.py、schemas.py、工具错误测试 |
| 环境/CLI故障注入、重复序号和计数隔离 | FaultInjector、test_protocol.py |
| Trace六字段、摘要≤200字符、真实next_action | trace.py、test_business_paths |
| reason仅为简短依据，无内部思维过程 | ToolArgs、prompts.py、Trace |
| Pydantic结果、finish失败回填修正 | schemas.py、guards.py、循环修正测试 |
| hard授权、所有改时标记、保存状态真实 | guards.py、test_guards.py |
| 规范化SHA-256、事务、UNIQUE | storage.py、顺序/时区/并发测试 |
| 不提供真实发布、输出禁词检测 | 六工具注册表、递归check_words测试 |
| 可复制安装/单例/测试/批量命令、固定依赖 | README、requirements.txt、scripts |
| src/tests/examples/data/docs完整结构 | 当前仓库及评估文档 |
| 至少两条真实模型路径，禁止造假 | normal+slot_conflict真实调用通过，独立_real输出和Trace，任务8.3完成 |
| AI使用和个人复盘如实记录 | docs/04、05模板 |

## 明确的业务约定

一条素材占同日一个整点小时，时间必须带时区，展示北京时间、存储UTC；替代候选默认只取之后整点。高风险优先于缺资料，缺资料优先于低风险可排期。可信确认只来自请求或预设回答，绑定素材及具体时间/风险代码。改时即使已确认也保留标记，只有未解决事项进入pending_items。

保存状态为saved/duplicate/failed/not_saved；存储异常的failed表示未获成功确认，保留核实待办。执行状态为completed/needs_attention/incomplete_step_limit/incomplete_model_error。部分结果不替未审核素材编造审核状态。

## 复盘跟进验收（2026-10-30）

全量真实业务场景、长批量/规则变化/接口契约扩展已完成，验收与证据见[06-followup-validation.md](06-followup-validation.md)；Codex主要写代码，本人基本上负责测试与执行并在审阅中参与问题定位与纠偏，见[04-ai-usage.md](04-ai-usage.md)。规则失效拒绝、已解决待办拒绝、异常接口结构和可选参数模式均有回归验证，不把离线接口模拟记为多厂商实测。

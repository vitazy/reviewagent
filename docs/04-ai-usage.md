# AI辅助使用与人工参与记录

## 使用方式与实际投入

本项目使用 Codex 辅助需求整理、方案设计、代码实现、测试编写与文档起草。本人选定题目、提出工程约束（先 OpenSpec 再实现、仅保存草稿、必须真实 ReAct），配置真实模型所需的 `.env`，并在交付前亲自复跑与走读验收。

**实际投入：3 小时（本人报告）。**未按阶段细分计时；自动化测试与 AI 代跑时长不计入本人投入。

分工原则：AI 负责大部分实现与初版验证证据；本人负责范围决策、环境配置、结果复核与方案取舍确认。不把 AI 生成或修复的代码记作本人独立编写。

## AI 生成了什么及采用的方案

| 范围 | AI 产物与采用理由 | 对应文件 |
| --- | --- | --- |
| 需求与设计 | 整合三份需求，生成提案、能力规格、设计与任务清单，便于逐条验收 | `openspec/changes/build-material-review-scheduling-agent/` |
| Agent 与模型 | 原生 ReAct、OpenAI 兼容客户端、observation 驱动 Mock、系统提示词与预算 | `agent.py`、`llm.py`、`prompts.py` |
| 业务与持久化 | 六工具、审核规则、合成库、事务与幂等键 | `tools.py`、`storage.py`、`data/review_rules.json`、`scripts/seed_db.py` |
| 结构与护栏 | Pydantic 契约、可信确认、保存前/finish 校验、保存快照 | `schemas.py`、`context.py`、`guards.py` |
| 验证与证据 | 测试、10 个 Mock / 10 个真实场景及兼容模式；初版输出与 Trace | `tests/`、`examples/`、`scripts/run_all_cases.sh` |
| 交付材料 | README 与 docs 初稿（本记录经本人按实际分工修订） | `README.md`、`docs/` |

采用原生循环 + SQLite：需要证明模型按工具结果调整动作，且相同业务请求不重复落库；CLI 即可覆盖本题范围，未引入 UI、部署或多 Agent。

## 本人实际参与

| 事项 | 本人做了什么 | 说明 |
| --- | --- | --- |
| 选题与范围 | 选定「素材审核与发布排期」，明确只存草稿、验收边界与交付目录 | 范围决策由本人完成 |
| 实施约束 | 要求先 OpenSpec 再编码，坚持真实 function calling ReAct，禁止固定分支冒充决策 | AI 按该约束实现 |
| 环境与密钥 | 配置 `.env`（兼容 OPENAI_* / openai provider），管理额度与网络访问 | 密钥不入库；`.env` 已忽略 |
| 代码走读 | 阅读循环、护栏、幂等事务、异常与预算路径，确认能解释主要约束触发条件 | 实现代码仍由 AI 编写；本人未另提独立业务补丁 |
| 亲自复跑 | 按 README 安装依赖，执行 `pytest -q`、Mock 批量、真实 normal / slot_conflict（及必要扩展场景），对照输出、Trace 与草稿状态 | 与 AI 初跑证据一致；以本人复跑结论作为提交依据 |
| 方案取舍 | 接受「模型建议 + 代码护栏」、保存快照、省略候选拒绝等修正，并理解其业务含义 | 修正代码由 AI 落地，本人确认采用 |

业务侧 hard 改时、低风险复核在本题中使用合成资料与预设回答；单测/场景通过不等于生产人工终审。

## 我如何验证

AI 先产出可复现证据；本人在本地再次执行并核对，以下为本人复跑后确认的结果。

| 验证 | 结果 | 证据 |
| --- | --- | --- |
| 离线单测 / 集成 | `pytest -q`：109 passed | [pytest.txt](../examples/pytest.txt)、[tests](../tests/) |
| 全部 Mock 用例 | 10/10 PASS | [Mock 报告](../examples/run_report_mock.json)、[索引](../examples/results.md) |
| 真实正常排期 | approved / saved / completed | [normal](../examples/outputs/normal_real.json)、[Trace](../examples/traces/normal_real.jsonl) |
| 真实 soft 冲突 | 建议替代时段并保存，保留待确认 | [冲突](../examples/outputs/slot_conflict_real.json)、[Trace](../examples/traces/slot_conflict_real.jsonl) |
| 关键边界抽查 | hard 未授权不改时；高风险 / 缺资料不入草稿；duplicate 同库一条；save_failure 不虚报已保存 | [results.md](../examples/results.md)、相关 `_real` / `_mock` 产物 |
| 交付检查 | 产物未写入真实密钥；Mock 与真实结论分开表述 | [评估报告](03-evaluation.md) |

本人复跑核对要点：

1. 依赖可按 `requirements.txt` 安装，CLI 与 `pytest -q` 可离线运行。
2. Mock 批量中 duplicate 返回原 `draft_id` 且同库仅一条；两次保存失败不声称 `saved`。
3. 真实 Trace 中工具顺序随 observation 变化，而非固定脚本。
4. soft 冲突有待确认标记；hard 须精确确认才可改时；改时即使已确认仍保留 `needs_confirmation=true`。
5. 文档不把 Mock 通过写成真实模型效果证明。

题号、GitHub URL 与最终 commit SHA 见 [README 提交信息](../README.md#提交信息)。

## AI 产物中发现并修正的问题（实现归属）

下列定位与代码修改由 Codex 完成；本人通过走读与回归测试理解并确认采用。

| 问题 | 修正 | 验证 |
| --- | --- | --- |
| 保存后继续查槽再预算退出，候选可能偏离已保存内容 | 保留经护栏的保存快照，部分退出据此报告 | `test_budget_after_save_and_further_query_keeps_saved_snapshot` |
| 删除合法候选以 `not_saved` 绕过保存 | finish 发现仍可保存的空闲候选则拒绝 | `test_omitting_candidate_cannot_bypass_save` |
| 仅支持 LLM_* / real，与本人 OPENAI_* 配置不符 | 别名映射；非空 LLM_* 优先 | 配置回归 + 真实路径 |
| SOCKS 代理缺依赖 | 固定 `socksio`，缺依赖明确报错 | 缺依赖回归 + 实际调用 |

跟进轮次另含规则指纹 / 失效拒绝、待办证据匹配、已解决待办拒绝、接口契约与省略 `parallel_tool_calls` 等，见 [06-followup-validation.md](06-followup-validation.md)。跟进实现仍由 AI 完成；本人对结论做了复跑确认。

## 验证结论边界

- Mock 只验证流程，不证明模型决策效果。
- 真实结论限于当前已配置接口与合成场景；离线 HTTP 契约测试不记为多厂商实测。
- 个人贡献以本节表格为准：本人主导范围、配置、走读与复跑验收；主体实现与多数修复代码由 AI 完成。

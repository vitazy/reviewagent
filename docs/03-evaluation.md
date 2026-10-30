# 实际评估

验证日期：2026-10-30（北京时间）。当前完成离线实现、Mock验收及全部10条真实模型业务路径验证；**Mock只验证流程，不证明模型的决策效果**。

## 实际执行

- `pytest -q`：109 passed，默认离线，无模型密钥依赖；[实际终端结果](../examples/pytest.txt)。
- `LLM_PROVIDER=mock bash scripts/run_all_cases.sh`：10/10 PASS，含8个必需用例与2个补充用例。
- OpenSpec严格校验：通过。
- 真实模型：10/10业务场景通过；normal为6步、saved/completed，slot_conflict为5步、saved/needs_attention；另有真实省略并行参数模式通过。
- 独立证据检查：10组Mock与10组真实业务输出通过Pydantic，Trace字段、摘要长度、实际next_action和provider一致；草稿ID与各自SQLite记录一致。
- 配置回归：支持OPENAI变量和openai provider别名，LLM变量优先；缺配置和缺依赖明确报错，不降级Mock。

直接依赖已安装验证：openai 1.109.1、socksio 1.0.0、httpx 0.28.1、pydantic 2.11.7、python-dotenv 1.1.0、pytest 8.3.4。开发运行环境为Python 3.13.5。单元测试中的SDK接线测试使用替身；下列真实证据由已配置接口的实际调用产生。

## 验收点 → 文件 → 状态

下表A01–A10为实际Mock结果；独立真实验证见后面的表格。完整输入/输出/Trace索引见[examples/results.md](../examples/results.md)，机器汇总见[Mock报告](../examples/run_report_mock.json)和[真实报告](../examples/run_report_real.json)。

| ID | 预期 | 实际 | 文件 | 状态 |
| --- | --- | --- | --- | --- |
| A01 | 无风险可用时段保存 | approved / saved / completed；5步 | [normal](../examples/outputs/normal_mock.json) | Mock通过 |
| A02 | 缺资料先补查不保存 | needs_info / not_saved；4步，读取两次 | [missing_info](../examples/traces/missing_info_mock.jsonl) | Mock通过 |
| A03 | 高风险阻断 | blocked / not_saved；3步，风险保留 | [rule_risk](../examples/outputs/rule_risk_mock.json) | Mock通过 |
| A04 | soft18→19且待确认 | approved / saved / needs_attention；5步 | [slot_conflict](../examples/outputs/slot_conflict_mock.json) | Mock通过 |
| A05 | hard未授权不改时 | suggested_time=null / not_saved；确认工具返回pending | [hard](../examples/traces/slot_conflict_hard_mock.jsonl) | Mock通过 |
| A06 | 重复只一条 | duplicate、原draft_id、同库总数1 | [duplicate](../examples/outputs/duplicate_mock.json) | Mock通过 |
| A07 | 两次保存失败不虚报 | failed / draft_id=null；两次失败、草稿0条 | [save_failure](../examples/traces/save_failure_mock.jsonl) | Mock通过 |
| A08 | 同输入变占用后建议20 | 原请求仍18，建议20 / saved | [slot_swap](../examples/outputs/slot_swap_mock.json) | Mock通过 |
| A09 | 低风险保留人工复核 | saved，needs_confirmation=true，风险待办 | [low_risk](../examples/outputs/low_risk_mock.json) | Mock通过 |
| A10 | hard精确确认后改时 | 建议19 / saved / completed；仍保留改时标记 | [hard_confirmed](../examples/outputs/hard_confirmed_mock.json) | Mock通过 |
| A11 | 有界执行、部分事实 | 两类预算、恰好上限finish、保存后接口失败/预算退出均通过 | [test_agent.py](../tests/test_agent.py) | 离线测试通过 |
| A12 | 代码护栏 | 防伪保存、hard授权、嵌套禁词、批内冲突、保存后漂移、跳过保存均拒绝 | [test_guards.py](../tests/test_guards.py) | 离线测试通过 |
| E01 | 真实ReAct循环与SDK配置 | 通用调度、消息回填与真实工具决策已验证 | [agent.py](../src/schedule_agent/agent.py)、[llm.py](../src/schedule_agent/llm.py) | 10条真实路径通过 |
| E02 | 工具异常和故障注入可恢复 | 多种工具失败、注入序号、计数重置、重试上限通过 | [test_protocol.py](../tests/test_protocol.py) | 离线测试通过 |
| E03 | 幂等与事务 | 等价时区/排序/措辞，业务变化，竞争插入及保存前占用变化通过 | [test_guards.py](../tests/test_guards.py) | 离线测试通过 |
| E04 | 指定目录、文档和无密钥模板 | src/tests/examples/data/docs/scripts和固定依赖齐备 | [README](../README.md) | 完成 |
| E05 | 至少两条真实模型路径 | 全部10个业务场景通过 | 独立_real输出/Trace及真实报告 | 真实验证通过 |

## 真实模型独立验证

下列结果为2026-10-30扩展复跑，不将旧记录的步数套用于本轮。完整调用参数及错误修正见Trace。

| 用例 | 实际结果 | 步数 | 证据 |
| --- | --- | --- | --- |
| normal | approved / saved / completed | 6 | [输出](../examples/outputs/normal_real.json)、[Trace](../examples/traces/normal_real.jsonl) |
| missing_info | needs_info / not_saved / needs_attention | 4 | [输出](../examples/outputs/missing_info_real.json)、[Trace](../examples/traces/missing_info_real.jsonl) |
| rule_risk | blocked / not_saved / needs_attention | 3 | [输出](../examples/outputs/rule_risk_real.json)、[Trace](../examples/traces/rule_risk_real.jsonl) |
| slot_conflict | approved / saved / needs_attention | 5 | [输出](../examples/outputs/slot_conflict_real.json)、[Trace](../examples/traces/slot_conflict_real.jsonl) |
| slot_conflict_hard | approved / not_saved / needs_attention | 5 | [输出](../examples/outputs/slot_conflict_hard_real.json)、[Trace](../examples/traces/slot_conflict_hard_real.jsonl) |
| duplicate | approved / duplicate / needs_attention | 6 | [输出](../examples/outputs/duplicate_real.json)、[Trace](../examples/traces/duplicate_real.jsonl) |
| save_failure | approved / failed / needs_attention | 7 | [输出](../examples/outputs/save_failure_real.json)、[Trace](../examples/traces/save_failure_real.jsonl) |
| slot_swap | approved / saved / needs_attention | 5 | [输出](../examples/outputs/slot_swap_real.json)、[Trace](../examples/traces/slot_swap_real.jsonl) |
| low_risk | approved / saved / needs_attention | 7 | [输出](../examples/outputs/low_risk_real.json)、[Trace](../examples/traces/low_risk_real.jsonl) |
| hard_confirmed | approved / saved / completed | 6 | [输出](../examples/outputs/hard_confirmed_real.json)、[Trace](../examples/traces/hard_confirmed_real.jsonl) |

独立场景使用独立合成数据库；slot_conflict→duplicate共享同库并验证原ID和仅一行。当前已覆盖高/低风险、缺字段、hard未确认/精确确认、失败和时段变化。其他厂商及真实内容不在本轮验证结论内。

16项批量、4种规则变化/不可用边界、19项原生SDK离线HTTP契约测试，以及当前真实接口的省略参数模式，见[复盘跟进报告](06-followup-validation.md)和[扩展证据](../examples/followup/results.md)。

## 验证中处理的问题

部分退出最初根据最后查询重新投影候选，存在保存后继续查询导致快照漂移的风险。现保存工具保留经过护栏的结果快照，预算/模型异常退出按该快照报告已完成部分；正常finish仍严格比对当前结果与数据库。对应回归测试为test_budget_after_save_and_further_query_keeps_saved_snapshot。

另补充拒绝“删除合法候选再以not_saved结束”的情况，避免模型跳过保存；对应test_omitting_candidate_cannot_bypass_save。

真实接入时补充OPENAI_BASE_URL/OPENAI_API_KEY和openai别名兼容，以及SOCKS代理依赖；客户端缺依赖现返回配置错误。初次连接受沙箱网络限制，开放网络访问后重新实际运行两条路径，最终记录均为成功运行产生。

## 限制与未完成项

- 原35项及本轮6项跟进任务完成后共41项；业务真实验证覆盖10个既有场景。本人已走读并复跑确认；GitHub提交仍属提交环节。
- function calling与parallel_tool_calls支持因厂商而异；本次真实配置两种参数模式通过，其他厂商兼容性不能用离线模拟代替实测。
- 合成规则、同日整点1小时槽位、单渠道请求，以及预设确认是本题简化；不涉及身份认证和生产审核。
- 草稿不预占真实排期，只保证保存时检查；后续执行需重新查槽。
- 存储异常无法确认提交状态时保留核实待办，不能把它当成已确认成功。注入失败发生于副作用前，可明确证明无新增。
- 禁词为递归字符串检查，不能穷尽所有语义性表述。
- 本人报告实际投入3小时；AI与人工分工、本人走读/复跑见docs/04、05。题号、GitHub URL与最终commit SHA见[README提交信息](../README.md#提交信息)。

本轮扩展首轮有3项检查未通过，修正待办证据匹配、已解决待办及验收调用计数后整套复跑10/10通过；旧输出和Trace保存在examples/history/real。详见跟进报告，不将本轮表述为首次即全部通过。

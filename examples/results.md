# 用例实际结果

由 scripts/run_cases.py 根据实际运行生成。Mock 只验证流程，不证明模型的决策效果。

## mock

| 用例 | 预期验收点 | 实际 | 证据 |
| --- | --- | --- | --- |
| normal | approved / saved / 原时间 / 无待办 | PASS：approved / saved / completed；drafts=1，steps=5 | [输入](cases/normal.json) · [输出](outputs/normal_mock.json) · [Trace](traces/normal_mock.jsonl) |
| missing_info | needs_info / not_saved / 已补查 | PASS：needs_info / not_saved / needs_attention；drafts=0，steps=4 | [输入](cases/missing_info.json) · [输出](outputs/missing_info_mock.json) · [Trace](traces/missing_info_mock.jsonl) |
| rule_risk | blocked / not_saved / 保留风险 | PASS：blocked / not_saved / needs_attention；drafts=0，steps=3 | [输入](cases/rule_risk.json) · [输出](outputs/rule_risk_mock.json) · [Trace](traces/rule_risk_mock.jsonl) |
| slot_conflict | 19:00 / saved / 待确认 | PASS：approved / saved / needs_attention；drafts=1，steps=5 | [输入](cases/slot_conflict.json) · [输出](outputs/slot_conflict_mock.json) · [Trace](traces/slot_conflict_mock.jsonl) |
| slot_conflict_hard | 不改hard时间 / not_saved / 待确认 | PASS：approved / not_saved / needs_attention；drafts=0，steps=5 | [输入](cases/slot_conflict_hard.json) · [输出](outputs/slot_conflict_hard_mock.json) · [Trace](traces/slot_conflict_hard_mock.jsonl) |
| duplicate | duplicate / 原ID / 同库仅一条 | PASS：approved / duplicate / needs_attention；drafts=1，steps=5 | [输入](cases/duplicate.json) · [输出](outputs/duplicate_mock.json) · [Trace](traces/duplicate_mock.jsonl) |
| save_failure | 两次保存失败 / failed / 无新增草稿 | PASS：approved / failed / needs_attention；drafts=0，steps=6 | [输入](cases/save_failure.json) · [输出](outputs/save_failure_mock.json) · [Trace](traces/save_failure_mock.jsonl) |
| slot_swap | 同一18:00输入 / 建议20:00 / saved | PASS：approved / saved / needs_attention；drafts=1，steps=5 | [输入](cases/slot_swap.json) · [输出](outputs/slot_swap_mock.json) · [Trace](traces/slot_swap_mock.jsonl) |
| low_risk | 低风险 / saved / 待人工复核 | PASS：approved / saved / needs_attention；drafts=1，steps=5 | [输入](cases/low_risk.json) · [输出](outputs/low_risk_mock.json) · [Trace](traces/low_risk_mock.jsonl) |
| hard_confirmed | 精确确认19:00 / saved / 保留改时标记 | PASS：approved / saved / completed；drafts=1，steps=6 | [输入](cases/hard_confirmed.json) · [输出](outputs/hard_confirmed_mock.json) · [Trace](traces/hard_confirmed_mock.jsonl) |

## real

| 用例 | 预期验收点 | 实际 | 证据 |
| --- | --- | --- | --- |
| normal | approved / saved / 原时间 / 无待办 | PASS：approved / saved / completed；drafts=1，steps=6 | [输入](cases/normal.json) · [输出](outputs/normal_real.json) · [Trace](traces/normal_real.jsonl) |
| missing_info | needs_info / not_saved / 已补查 | PASS：needs_info / not_saved / needs_attention；drafts=0，steps=4 | [输入](cases/missing_info.json) · [输出](outputs/missing_info_real.json) · [Trace](traces/missing_info_real.jsonl) |
| rule_risk | blocked / not_saved / 保留风险 | PASS：blocked / not_saved / needs_attention；drafts=0，steps=3 | [输入](cases/rule_risk.json) · [输出](outputs/rule_risk_real.json) · [Trace](traces/rule_risk_real.jsonl) |
| slot_conflict | 19:00 / saved / 待确认 | PASS：approved / saved / needs_attention；drafts=1，steps=5 | [输入](cases/slot_conflict.json) · [输出](outputs/slot_conflict_real.json) · [Trace](traces/slot_conflict_real.jsonl) |
| slot_conflict_hard | 不改hard时间 / not_saved / 待确认 | PASS：approved / not_saved / needs_attention；drafts=0，steps=5 | [输入](cases/slot_conflict_hard.json) · [输出](outputs/slot_conflict_hard_real.json) · [Trace](traces/slot_conflict_hard_real.jsonl) |
| duplicate | duplicate / 原ID / 同库仅一条 | PASS：approved / duplicate / needs_attention；drafts=1，steps=6 | [输入](cases/duplicate.json) · [输出](outputs/duplicate_real.json) · [Trace](traces/duplicate_real.jsonl) |
| save_failure | 两次保存失败 / failed / 无新增草稿 | PASS：approved / failed / needs_attention；drafts=0，steps=7 | [输入](cases/save_failure.json) · [输出](outputs/save_failure_real.json) · [Trace](traces/save_failure_real.jsonl) |
| slot_swap | 同一18:00输入 / 建议20:00 / saved | PASS：approved / saved / needs_attention；drafts=1，steps=5 | [输入](cases/slot_swap.json) · [输出](outputs/slot_swap_real.json) · [Trace](traces/slot_swap_real.jsonl) |
| low_risk | 低风险 / saved / 待人工复核 | PASS：approved / saved / needs_attention；drafts=1，steps=7 | [输入](cases/low_risk.json) · [输出](outputs/low_risk_real.json) · [Trace](traces/low_risk_real.jsonl) |
| hard_confirmed | 精确确认19:00 / saved / 保留改时标记 | PASS：approved / saved / completed；drafts=1，steps=6 | [输入](cases/hard_confirmed.json) · [输出](outputs/hard_confirmed_real.json) · [Trace](traces/hard_confirmed_real.jsonl) |

批量、规则变化和接口契约扩展见[跟进结果](followup/results.md)。

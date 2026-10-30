# 批量、规则变化及接口兼容扩展结果

2026-10-30，由本人执行。Mock只验证流程，不证明模型决策效果。机器报告：[report.json](report.json)。复现：`python scripts/verify_followup.py`。

| 用例 | 实际 | 输入 | 输出 | Trace |
| --- | --- | --- | --- | --- |
| long_batch_default | PASS；12步未完成，5项有证据，未保存 | [输入](cases/long_batch_default.json) | [输出](outputs/long_batch_default_mock.json) | [Trace](traces/long_batch_default_mock.jsonl) |
| long_batch_raised | PASS；35步处理16项，15个候选存1份草稿，1项无时段 | [输入](cases/long_batch_raised.json) | [输出](outputs/long_batch_raised_mock.json) | [Trace](traces/long_batch_raised_mock.jsonl) |
| rules_changed_version | PASS；旧审核拒绝，重审后blocked，未保存 | [输入](cases/rules_changed_version.json) | [输出](outputs/rules_changed_version_mock.json) | [Trace](traces/rules_changed_version_mock.jsonl) |
| rules_changed_content | PASS；同版本变动仍识别，重审后blocked | [输入](cases/rules_changed_content.json) | [输出](outputs/rules_changed_content_mock.json) | [Trace](traces/rules_changed_content_mock.jsonl) |
| rules_invalid | PASS；无效规则导致12步安全退出，未保存 | [输入](cases/rules_invalid.json) | [输出](outputs/rules_invalid_mock.json) | [Trace](traces/rules_invalid_mock.jsonl) |
| rules_changed_at_budget | PASS；3步退出，不沿用失效审核 | [输入](cases/rules_changed_at_budget.json) | [输出](outputs/rules_changed_at_budget_mock.json) | [Trace](traces/rules_changed_at_budget_mock.jsonl) |

规则变化和批量资料由脚本生成，仅运行案例JSON不足以复现；原data/review_rules.json和已有业务库不改变。

## 接口验证

- 原生SDK+内存传输：19项契约测试通过，覆盖路径、可选参数、HTTP错误、超时和异常工具响应。这是离线模拟。
- 当前真实接口省略并行参数模式：6步saved/completed；[报告](serial_gateway_report.json)、[输入](cases/normal_serial_gateway.json)、[输出](outputs/normal_serial_gateway_real.json)、[Trace](traces/normal_serial_gateway_real.jsonl)。复现：`python scripts/verify_serial_gateway.py`，会调用.env中的真实模型。
- README复跑：[normal](readme/outputs/normal_mock.json)、[保存失败](readme/outputs/save_failure_mock.json)，对应Trace在readme/traces/。

代码走读、执行条件和边界见[跟进报告](../../docs/06-followup-validation.md)。

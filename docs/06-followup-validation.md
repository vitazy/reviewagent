# 复盘前三项跟进验证

日期：2026-10-30。跟进相关**代码改动**由 Codex 完成；安装、单测、Mock/真实场景与扩展验证的**命令执行基本上由本人完成**。分工见 [04-ai-usage.md](04-ai-usage.md)。

## 代码走读与 README 命令复跑

| 走读对象 | 结论与修正 |
| --- | --- |
| [agent.py](../src/schedule_agent/agent.py) | 循环仅处理模型调用、协议、调度、预算和回填，不按素材ID决定业务。新增缺ID、重复ID、缺函数的检查，异常响应不执行工具 |
| [tools.py](../src/schedule_agent/tools.py) | 保存前验证候选，再计算key和记录持久化尝试，故障在副作用前注入；写入前拒绝不算实际保存尝试 |
| [guards.py](../src/schedule_agent/guards.py) | hard授权绑定素材和具体时间，reason不能授权。待办可以附带有证据的候选/风险代码，无证据范围及已解决待办仍拒绝 |
| [storage.py](../src/schedule_agent/storage.py) | BEGIN IMMEDIATE、唯一key、事务内查槽和回滚提供幂等；重复返回原ID，草稿不预占真实schedule |
| [rules.py](../src/schedule_agent/rules.py) | 新增结构校验和内容指纹，不只比版本标签；旧审核拒绝保存/finish，无效规则返回RuleDataError |
| [llm.py](../src/schedule_agent/llm.py) | SDK显式超时、max_retries=0；增加可省略parallel_tool_calls的模式，运行时仍限制一个工具 |

已在虚拟环境核对安装固定依赖，并复跑 seed、单用例、故障注入、pytest 和 Mock 批量入口。为保留已有数据，单例使用 README 支持的 `--db` 和 `--output-root` 生成独立合成库。

| 操作 | 结果 | 证据 |
| --- | --- | --- |
| 安装requirements.txt | 依赖可安装，原生SDK及HTTPX/SOCKS可用 | requirements.txt及实际SDK契约测试 |
| 激活虚拟环境后`pytest -q` | 109 passed，无跳过 | [实际终端结果](../examples/pytest.txt) |
| seed后运行normal | saved / completed | [输出](../examples/followup/readme/outputs/normal_mock.json)、[Trace](../examples/followup/readme/traces/normal_mock.jsonl) |
| 独立库注入两次save_draft失败 | failed / needs_attention | [输出](../examples/followup/readme/outputs/save_failure_mock.json)、[Trace](../examples/followup/readme/traces/save_failure_mock.jsonl) |
| Mock批量脚本 | 10/10通过 | [报告](../examples/run_report_mock.json) |

以上为本人执行得到的证据；并已走读循环/护栏/事务，结论与上表一致。

## 真实模型扩展

通过 `.env` 配置的同一真实接口，全部10个场景复跑通过，含hard未授权冲突、精确确认、高/低风险、资料缺失、重复、两次保存失败及slot_swap。

hard未确认不改时、不保存；精确确认后可改时，保留变更标记但不重复挂待办。M03阻断、M04待复核、M02补查后仍缺则不保存。两次注入失败无新增草稿，duplicate同库仅一行，slot_swap仍请求18:00而建议20:00。

见[真实报告](../examples/run_report_real.json)及[完整索引](../examples/results.md)。结论限定于本次配置和合成场景，不代表所有模型或真实内容均可靠。

首轮扩展有3项未通过：hard场景重复finish拒绝后接口超时；保存失败验收把写入前拒绝也计入；已确认改时仍被模型列为待办。修正待办匹配、已解决待办校验和验收计数后，整套真实复跑10/10通过。上一轮输出与Trace保存在[history/real](../examples/history/real/)，未伪造历史调用。

## 更长批量与规则变化

以下为离线Mock/外部变更夹具验证，不记为真实模型效果。复现：

```bash
python scripts/verify_followup.py
```

详见 [examples/followup/results.md](../examples/followup/results.md)。含16项批量、规则版本/内容变更与无效规则等边界。

## 接口契约与可选参数

原生OpenAI SDK配合HTTPX MockTransport完成19项离线HTTP契约测试，全部通过。仅使用合成密钥和内存传输，不调用其他厂商。

当前真实接口还验证了省略可选 `parallel_tool_calls` 参数的模式（`LLM_SEND_PARALLEL_TOOL_CALLS=0`）；运行时仍限制每轮一个工具。不代表其他厂商均已实测。

| 场景 | 行为要点 |
| --- | --- |
| ReadTimeout | 无SDK隐式重试，明确未完成 |
| 其他异常结构 | 校验后可解释失败，不静默当成功 |

复现：`python scripts/verify_serial_gateway.py`（会实际调用 `.env` 配置的模型）。

## 小结

复盘前三项的工程跟进：**代码由 Codex 完成，测试与场景执行基本上由本人完成。** 3 小时为本人投入。提交信息见 [README](../README.md#提交信息)。

# 复盘前三项跟进验证

日期：2026-10-30。本节工程执行与证据初跑由Codex完成；本人另做走读与复跑确认，分工见[04-ai-usage.md](04-ai-usage.md)。

## 代码走读与README命令复跑

| 走读对象 | 结论与修正 |
| --- | --- |
| [agent.py](../src/schedule_agent/agent.py) | 循环仅处理模型调用、协议、调度、预算和回填，不按素材ID决定业务。新增缺ID、重复ID、缺函数的检查，异常响应不执行工具 |
| [tools.py](../src/schedule_agent/tools.py) | 保存前验证候选，再计算key和记录持久化尝试，故障在副作用前注入；写入前拒绝不算实际保存尝试 |
| [guards.py](../src/schedule_agent/guards.py) | hard授权绑定素材和具体时间，reason不能授权。待办可以附带有证据的候选/风险代码，无证据范围及已解决待办仍拒绝 |
| [storage.py](../src/schedule_agent/storage.py) | BEGIN IMMEDIATE、唯一key、事务内查槽和回滚提供幂等；重复返回原ID，草稿不预占真实schedule |
| [rules.py](../src/schedule_agent/rules.py) | 新增结构校验和内容指纹，不只比版本标签；旧审核拒绝保存/finish，无效规则返回RuleDataError |
| [llm.py](../src/schedule_agent/llm.py) | SDK显式超时、max_retries=0；增加可省略parallel_tool_calls的模式，运行时仍限制一个工具 |

已在虚拟环境核对安装固定依赖，并复跑seed、单用例、故障注入、pytest和Mock批量入口。为保留已有数据，单例使用README支持的`--db`和`--output-root`生成独立合成库。

| 操作 | 结果 | 证据 |
| --- | --- | --- |
| 安装requirements.txt | 依赖可安装，原生SDK及HTTPX/SOCKS可用 | requirements.txt及实际SDK契约测试 |
| 激活虚拟环境后`pytest -q` | 109 passed，无跳过 | [实际终端结果](../examples/pytest.txt) |
| seed后运行normal | saved / completed | [输出](../examples/followup/readme/outputs/normal_mock.json)、[Trace](../examples/followup/readme/traces/normal_mock.jsonl) |
| 独立库注入两次save_draft失败 | failed / needs_attention | [输出](../examples/followup/readme/outputs/save_failure_mock.json)、[Trace](../examples/followup/readme/traces/save_failure_mock.jsonl) |
| Mock批量脚本 | 10/10通过 | [报告](../examples/run_report_mock.json) |

以上为跟进轮次的代执行证据；本人已按README复跑关键命令并走读循环/护栏/事务，结论与上表一致。

## 真实模型扩展

通过`.env`配置的同一真实接口，全部10个场景复跑通过，含hard未授权冲突、精确确认、高/低风险、资料缺失、重复、两次保存失败及slot_swap。

hard未确认不改时、不保存；精确确认后可改时，保留变更标记但不重复挂待办。M03阻断、M04待复核、M02补查后仍缺则不保存。两次注入失败无新增草稿，duplicate同库仅一行，slot_swap仍请求18:00而建议20:00。

见[真实报告](../examples/run_report_real.json)及[完整索引](../examples/results.md)。结论限定于本次配置和合成场景，不代表所有模型或真实内容均可靠。

首轮扩展有3项未通过：hard场景重复finish拒绝后接口超时；保存失败验收把写入前拒绝也计入；已确认改时仍被模型列为待办。修正待办匹配、已解决待办校验和验收计数后，整套复跑10/10通过。上一轮输出与Trace保存在[history/real](../examples/history/real/)，未伪造历史调用。

## 更长批量与规则变化

以下为离线Mock/外部变更夹具验证，不记为真实模型效果。复现：

```bash
python scripts/verify_followup.py
```

| 场景 | 实际结果 | 边界 |
| --- | --- | --- |
| 16项批量，默认12步/工具预算 | 12步退出，5项有完整审核，未保存，列出未处理项 | 不绕过上限或编造完成 |
| 相同16项，提高至48步/工具预算 | 35步处理16项，保存15个不冲突候选为1份草稿，剩1项待处理 | 08–23点中18点占用，容量仅15，不强塞第16项 |
| 保存前规则版本变化 | 6步，旧保存拒绝，重新审核后blocked，0行草稿 | 不沿用旧审核 |
| 同版本但禁用词变化 | 同样6步，重新审核后blocked，0行 | 比较实际内容指纹 |
| 保存前规则JSON损坏 | 12步安全退出，未保存 | 规则不可用不能当无风险 |
| 最后一步查槽时规则变化 | 3步预算退出，不输出失效的approved项 | 部分退出同样刷新规则，不因护栏崩溃 |

见[扩展索引](../examples/followup/results.md)及[机器报告](../examples/followup/report.json)。规则文件和批量资料由脚本创建，运行单个JSON不能复现外部变更，需使用该脚本。规则检查是在校验边界读取当前内容，不能替代生产环境的规则发布锁或跨资源事务。

## 接口兼容

原生OpenAI SDK配合HTTPX MockTransport完成19项离线HTTP契约测试，全部通过。仅使用合成密钥和内存传输，不调用其他厂商。

| 接口行为 | 验证 |
| --- | --- |
| 标准/v1及代理前缀/gateway/openai/v1 | 请求路径、schema、temperature和响应解析 |
| 接受并行参数 | 发送parallel_tool_calls=false |
| 不接受该可选参数 | 配置LLM_SEND_PARALLEL_TOOL_CALLS=0省略，不隐式换服务或重试 |
| HTTP 400/401/403/404/422/429/500 | 每次仅1个请求，incomplete_model_error，响应正文不进Trace |
| ReadTimeout | 无SDK隐式重试，明确未完成 |
| 纯文本、多工具、坏JSON、缺ID、重复ID、缺函数 | 不执行业务副作用，消耗预算并安全退出 |

见[test_sdk_compat.py](../tests/test_sdk_compat.py)和完整pytest记录。

另对当前真实接口实际运行了省略可选参数的normal：6步，saved / completed。见[报告](../examples/followup/serial_gateway_report.json)、[输出](../examples/followup/outputs/normal_serial_gateway_real.json)、[Trace](../examples/followup/traces/normal_serial_gateway_real.jsonl)。当前只有一个外部服务的配置；其他厂商仍需对应配置，不能把离线契约测试当作多厂商实测。

## 完成范围

复盘前三项的工程跟进初跑由Codex完成；本人已复核。3小时为本人原阶段投入，代执行时长不计入。提交信息见[README](../README.md#提交信息)。

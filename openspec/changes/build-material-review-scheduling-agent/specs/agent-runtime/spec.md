## ADDED Requirements

### Requirement: Validated request and result contracts

系统 SHALL 使用 Pydantic 定义并校验 RunRequest、工具参数及 AgentResult。请求 SHALL 包含非空且无重复的 asset_ids、同一 channel、与素材集合一致的 requested_times 和可选 confirmations；时间 SHALL 含时区并位于整点，要求类型 SHALL 为 hard 或 soft。结果 SHALL 包含逐项审核/时间/确认字段，以及 draft_status、draft_id、status 和 pending_items。

#### Scenario: Valid single asset request
- **WHEN** 输入 M01、channel=video、带时区的整点时间及 type=soft
- **THEN** 请求通过校验，结果中 requested_time 保留原始时间语义，review_status 仅允许 approved、blocked 或 needs_info

#### Scenario: Invalid request rejected before model execution
- **WHEN** 请求包含重复素材、缺少对应时间、未知 hard/soft 类型或无时区时间
- **THEN** CLI 返回明确输入错误，不调用模型、不写草稿

### Requirement: Model driven ReAct loop

系统 SHALL 实现“模型产生 function tool_call → 调度工具 → 回填完整 observation → 模型选择下一步或 finish”的循环。运行时 SHALL 只承担协议、预算、证据记录和护栏职责，不得按素材 ID、预设案例或业务条件硬编码动作链。系统提示词 SHALL 位于 src/schedule_agent/prompts.py，说明工具、停止条件、追问条件及禁止编造。

#### Scenario: Model changes action after tool feedback
- **WHEN** query_slots 返回请求时段占用且存在其他可用时段
- **THEN** 运行时将真实工具结果以匹配 tool_call_id 的 tool 消息交给模型，由下一次模型响应决定查询、确认或保存动作

#### Scenario: Invalid assistant response is recoverable
- **WHEN** 模型返回纯文本、多工具调用、未知工具或无效 JSON 参数
- **THEN** 本轮不执行不合法业务动作，回填可修正错误，并消耗决策轮次；多调用响应中的每个 tool_call_id 均获得错误回填

#### Scenario: Malformed gateway identifiers
- **WHEN** 接口返回缺失或重复的调用ID、缺失函数或错误的调用结构
- **THEN** 不执行业务工具，使用协议纠错消息继续，受轮次预算约束

### Requirement: Compatible real and mock model providers

真实客户端 SHALL 通过 OpenAI SDK 的兼容接口读取 LLM_BASE_URL、LLM_API_KEY、LLM_MODEL，显式设置 temperature=0，并使用有界超时和禁用 SDK 隐式重试。LLM_PROVIDER=mock SHALL 使用根据最近 observation 和已发生历史选择动作的 MockLLM；两个 provider SHALL 产生同格式 tool_calls。真实客户端配置缺失 SHALL 明确报错，不能静默降级成 Mock。

系统 SHALL 同时兼容 OPENAI_BASE_URL、OPENAI_API_KEY 和 provider=openai；非空 LLM_* 值优先，openai SHALL 统一标记为 real，保持输出路径和 Trace 来源一致。

#### Scenario: Standard OpenAI environment aliases
- **WHEN** 用户设置 OPENAI_BASE_URL、OPENAI_API_KEY、LLM_MODEL 和 LLM_PROVIDER=openai
- **THEN** 系统使用真实客户端，生成_real证据；如果同时提供非空LLM_BASE_URL或LLM_API_KEY，优先使用对应LLM值

#### Scenario: Gateway rejects optional parallel parameter
- **WHEN** 用户配置LLM_SEND_PARALLEL_TOOL_CALLS=0
- **THEN** SDK请求省略该可选参数，运行时仍严格限制一个工具；不隐式重试或切换服务

#### Scenario: Observation based mock decision
- **WHEN** 相同类型请求收到的空闲时段从19:00变成20:00
- **THEN** Mock 的后续工具参数及结果随 observation 变成20:00，不复用预写日志

#### Scenario: Real provider unavailable
- **WHEN** 显式使用真实 provider 但缺少密钥，或模型接口超时/报错
- **THEN** 缺配置在运行前报错；运行中接口错误输出 incomplete_model_error 和已完成部分，不伪造工具结果或真实 trace

### Requirement: Bounded execution and truthful partial results

系统 SHALL 默认使用 MAX_STEPS=12 和 MAX_TOOL_CALLS=12，允许显式配置正整数上限。一次模型决策为一步；每次工具调度尝试包括 finish、参数错误和故障注入 SHALL 消耗工具预算。任一预算用尽且没有通过 finish 时 SHALL 返回 status=incomplete_step_limit，列明耗尽预算、已完成部分和缺口，禁止继续调用模型或工具。

#### Scenario: Step budget exhausted
- **WHEN** 第12步执行完仍需下一动作且 finish 尚未通过
- **THEN** 返回 incomplete_step_limit，未完成素材写入 pending_items，已保存的真实草稿状态与 ID 被保留

#### Scenario: Finish succeeds exactly at limit
- **WHEN** 第12步是通过护栏的 finish 且工具预算足够
- **THEN** 正常结束，不错误标记为超限

#### Scenario: Tool budget exhausted first
- **WHEN** 工具调度次数先达到设置上限且未完成
- **THEN** 返回相同未完成状态，并在 pending_items 明确指出工具预算耗尽

### Requirement: Uniform local tool protocol and exception recovery

系统 SHALL 仅提供本地 read_asset、check_rules、query_slots、save_draft、request_confirmation 和 finish 六个工具，每个工具 SHALL 支持可选短字符串 reason。工具 SHALL 返回统一结构 {ok, data, error}，失败的 error SHALL 包含 type 和 message，成功时 error=null；工具异常 SHALL 捕获并作为 observation 返回。系统 SHALL 不提供任何真实发布工具或函数。

#### Scenario: Business tool raises an exception
- **WHEN** 本地工具发生可捕获数据库或规则读取异常
- **THEN** 模型收到 ok=false 的结构化错误，程序保持可继续决策

#### Scenario: Missing metadata is a business observation
- **WHEN** 素材存在但缺少 title 或版权信息
- **THEN** 读取/审核返回成功 envelope 中的缺失信息，不将其伪装成运行时崩溃

### Requirement: Model initiated finish and guarded termination

所有正常及可表达的业务失败结果 SHALL 由模型调用 finish(result, reason) 提交，并经过 Pydantic 和业务证据护栏。失败 SHALL 作为 observation 回填并消耗本步预算。只有预算耗尽或模型调用失败等无法继续决策的运行时退出 SHALL 由代码构造同样受校验的部分结果；部分结果不得给未审核素材编造 review_status。

#### Scenario: Finish rejected and corrected
- **WHEN** 模型提交缺少改时确认标记的结果，随后根据 GuardViolation 修正
- **THEN** 第一次 finish 不结束运行，第二次校验通过才接受最终结果，两次均计入预算

#### Scenario: Unreviewed item at runtime exit
- **WHEN** 模型在审核 M02 前耗尽预算
- **THEN** 不将 M02 标成 approved、blocked 或 needs_info，而将其列为 pending_items 中的 unprocessed

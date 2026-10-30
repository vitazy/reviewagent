## ADDED Requirements

### Requirement: Time slot queries use actual schedule data

query_slots SHALL 根据 channel、业务 date、around_time 查询 SQLite schedule，并返回请求时段可用性及当日更晚的可用整点，候选按时间升序排列，默认不提前到原请求之前。业务日期 SHALL 使用 Asia/Shanghai，每条素材占一个小时，比较与存储采用 UTC。模型 SHALL 根据查询证据决定候选，不能固定加一小时或固定选择19:00。

#### Scenario: Requested slot available
- **WHEN** M01 请求19:00且实际 schedule 未占用该槽位
- **THEN** 建议原时间，无时间变更确认要求，可继续保存

#### Scenario: Fixture changes available slot
- **WHEN** 同一份18:00 soft请求的夹具从18:00占用/19:00可用变成18:00和19:00均占用/20:00可用
- **THEN** 候选建议随工具结果变成20:00

### Requirement: Soft conflicts allow pending alternatives

soft 请求的时段冲突时，模型 SHALL 查询并核实替代时段，保留原 requested_time，将具体可用候选设为 suggested_time，同时设置 needs_confirmation=true 和原因。该候选 SHALL 允许保存为待确认草稿，但未确认时整体状态 SHALL 为 needs_attention。

#### Scenario: Soft request moves to a free slot
- **WHEN** M01 请求18:00 soft、18:00被占用、19:00可用
- **THEN** 建议19:00，保留18:00为 requested_time，标记待确认，允许 draft_status=saved

### Requirement: Hard conflicts require exact authorization

hard 请求 SHALL 在没有匹配的可信确认时禁止改到其他时间，且此限制 SHALL 同时用于保存前和 finish。冲突未获同意时 SHALL 请求确认或明确停止该项排期，保持原 requested_time、suggested_time=null，记录待解决冲突。即使用户同意变更，改时结果 SHALL 保留 needs_confirmation=true 的变更标记。

#### Scenario: Hard conflict without response
- **WHEN** 18:00 hard 已占用，request_confirmation 没有匹配回答
- **THEN** 不保存该项候选，不自动改成19:00，输出待确认问题及原时间冲突

#### Scenario: Exact alternative accepted
- **WHEN** 原请求或确认工具提供针对 M01、time_change、19:00 的 accepted=true，且19:00仍可用
- **THEN** 允许建议并保存19:00，保留18:00原请求和改时标记，不再把该已解决确认列为待办

#### Scenario: Confirmation does not match candidate
- **WHEN** 已确认的是 M02 或20:00，而模型将 M01 hard 改到19:00
- **THEN** 保存和 finish 均拒绝该改动

### Requirement: Confirmation provenance is outside model control

request_confirmation SHALL 记录 asset_id 和 question，并支持 confirmation_type、proposed_time、risk_codes 来绑定确认范围。可信确认 SHALL 只来自原始请求 confirmations 或匹配的预设回答；模型 reason、问题措辞、传入结果或自行声称的 accepted 均不得作为授权。无回答 SHALL 返回 pending，拒绝回答 SHALL 返回 rejected，不阻塞 CLI。

#### Scenario: Model fabricates user consent
- **WHEN** 模型在 finish 的 confirmation_reason 写“用户已同意”，但可信记录中没有确认
- **THEN** 该文字不生效，hard 改时仍被拒绝

#### Scenario: Unscoped question has an answer
- **WHEN** 工具只有普通 question，没有具体时间/风险确认范围
- **THEN** 可以记录回答，但不能以此授权某个 hard 时间变更

### Requirement: Saved candidates are conflict free at save time

系统 SHALL 验证每个保存候选有该具体时段可用的成功查询证据，且在保存事务内重新检查 schedule 和本批次候选的区间冲突。blocked、needs_info、无具体时间或未授权 hard 改时的素材 SHALL 不进入保存子集。草稿 SHALL 不写入或预占真实 schedule。

#### Scenario: Two assets share one proposed slot
- **WHEN** 同渠道两项素材都建议19:00到20:00
- **THEN** save_draft 拒绝内部冲突，模型需重新查询或留下待处理项

#### Scenario: Slot becomes occupied after query
- **WHEN** query_slots 后、首次插入草稿前该时段被写入 schedule
- **THEN** 事务内检查发现冲突并返回 SlotUnavailable，不插入失效候选

#### Scenario: Mixed valid and invalid assets
- **WHEN** 一次请求中 M01 合法而 M02 缺资料
- **THEN** 可以只保存 M01，最终结果仍包含 M02 的 needs_info 与待办，整体 needs_attention

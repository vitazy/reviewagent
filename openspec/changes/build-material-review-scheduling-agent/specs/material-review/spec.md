## ADDED Requirements

### Requirement: Synthetic asset and rule evidence

系统 SHALL 使用本地合成 assets 数据及 data/review_rules.json，覆盖 M01 无风险、M02 缺字段、M03 高风险、M04 人工复核的低风险。read_asset SHALL 返回元数据和缺失字段；check_rules SHALL 服务端读取素材，返回 risk_level=none|low|high、risk_codes、risk_reasons、missing_fields 和规则版本，不能依赖模型声称的元数据。

#### Scenario: Safe asset reviewed
- **WHEN** 对字段完整且无风险的 M01 执行 read_asset 和 check_rules
- **THEN** 获取成功读取和 risk_level=none 的审核证据，可将其标为 approved 并继续查询时段

#### Scenario: Unknown asset requested
- **WHEN** 读取不存在的素材 ID
- **THEN** 返回 AssetNotFound observation，不编造素材或视其为审核通过

### Requirement: Missing information triggers supplementary inspection

模型 SHALL 在发现缺失必填字段后至少补充读取一次素材；信息仍不足时 SHALL 输出 review_status=needs_info 和明确缺口，suggested_time=null。保存护栏 SHALL 拒绝这类素材进入草稿。

#### Scenario: Supplementary read remains incomplete
- **WHEN** M02 首次读取或规则检查报告缺少 title/版权资料，补查后仍然缺失
- **THEN** Trace 中存在至少两次 read_asset，该项最终为 needs_info，不查询或保存该项排期候选

### Requirement: High risk blocks scheduling

高风险证据 SHALL 导致 review_status=blocked，并保留风险依据与 suggested_time=null。高风险 SHALL 优先于缺字段和低风险处理，不能通过用户一般确认、删除原因或修改模型文字绕过保存护栏。

#### Scenario: Unauthorized music or prohibited content
- **WHEN** M03 命中未授权音乐或禁用词的 high 规则
- **THEN** 输出 blocked 和对应风险原因，不将其放入 save_draft.items

#### Scenario: Risk evidence conflicts with model approval
- **WHEN** 模型把有 high 证据的素材标成 approved 并尝试保存或 finish
- **THEN** 返回 GuardViolation，不接受该结论

### Requirement: Low risk produces a confirmation marked draft

低风险素材 SHALL 保留风险原因和 needs_confirmation=true，可在其他约束满足时使用 review_status=approved 形成待确认草稿。approved SHALL 仅表示可进入草稿的规则判断，不能表示人工复核已完成；未收到匹配风险代码的确认时 SHALL 保留风险待办。

#### Scenario: Manual review still pending
- **WHEN** M04 触发 low 风险，时段可用但没有 risk_ack
- **THEN** 允许保存带风险标记的草稿，status=needs_attention，pending_items 包含人工复核要求

#### Scenario: Acknowledgement refers to different risk
- **WHEN** 用户确认的 risk_codes 与 M04 实际风险不匹配
- **THEN** 该确认不能消除当前风险待办

### Requirement: Review output remains tied to tool evidence

保存和 finish 护栏 SHALL 验证素材读取、规则检查与输出一致；缺少成功审核证据的素材不得输出为 approved 或写入草稿。工具失败只能导致继续调查、明确待处理或部分退出，不得被解释为“无风险”。

#### Scenario: Rules tool fails before approval
- **WHEN** check_rules 返回 RuleDataError，模型直接生成 approved
- **THEN** 保存或 finish 被拒绝，并提示缺少审核证据

### Requirement: Rule content freshness

系统 SHALL 校验规则结构并以规范化内容指纹绑定审核证据。保存和finish SHALL 拒绝已失效审核并要求重新check_rules；规则不可用 SHALL 返回RuleDataError，部分退出 SHALL 不将失效审核当作当前已批准结果。

#### Scenario: Same label with changed prohibited words
- **WHEN** 审核后、保存前规则内容改变但version未变
- **THEN** 返回StaleReview且不增加持久化尝试；重新审核可得到新的blocked结论

#### Scenario: Rules change at budget boundary
- **WHEN** 最后一步期间规则变化或不可读取，随后预算耗尽
- **THEN** 安全输出部分结果和待处理项，不崩溃，不沿用失效的未保存审核

## ADDED Requirements

### Requirement: Canonical idempotency key

系统 SHALL 使用 sha256(规范化后的业务请求 + 规范化排期结果) 作为 idempotency_key。规范化 SHALL 稳定排序素材和确认项、统一时间、采用固定 JSON 编码；SHALL 排除 case_id、provider、faults、运行时间、reason、draft_id 及自由说明文字。排期事实 SHALL 包含素材、渠道、审核状态、原时间、候选时间、风险代码、确认标记和有效确认。计算 SHALL 由代码执行；save_draft 的 key 参数 SHALL 接受 auto 并展开为真实哈希，显式哈希不匹配时 SHALL 拒绝。

#### Scenario: Equivalent requests share key
- **WHEN** 两次请求仅字典/素材顺序、时间的等价时区表达、case_id 或模型说明措辞不同
- **THEN** 产生相同 key，不因描述差异创建另一份草稿

#### Scenario: Business outcome changes
- **WHEN** 建议时间或有效确认事实发生变化
- **THEN** 产生不同 key，不能将旧内容误判为相同草稿

#### Scenario: Explicit incorrect key supplied
- **WHEN** 模型传入的显式 key 与代码计算值不一致
- **THEN** 返回可修正错误，不写数据库；auto 则由代码展开且 Trace 记录真实哈希

### Requirement: Transactional duplicate safe persistence

drafts 表 SHALL 对 idempotency_key 建立 UNIQUE 约束。save_draft SHALL 在有界锁等待的 SQLite 事务中检查 key、重新检查候选冲突并插入，异常时 rollback。相同 key 已存在时 SHALL 返回 draft_status=duplicate 及原 draft_id，不插入第二行；首次成功 SHALL 返回 saved。已存在草稿的读取不构成新的真实排期预约。

#### Scenario: Repeated submission returns original draft
- **WHEN** soft 冲突草稿保存后，用同一请求与同一排期事实再次提交
- **THEN** 返回 duplicate 和原 ID，同库 drafts 只有一条记录

#### Scenario: Concurrent duplicate attempts
- **WHEN** 两个连接尝试保存相同 key 和合法内容
- **THEN** 唯一约束确保最多一行；成功完成的两个调用分别返回 saved/duplicate 或重复结果，不出现两个 draft_id

### Requirement: Persistence validates business facts before effects

save_draft SHALL 复用审核、时间、确认与内容护栏，拒绝缺少证据、高风险、缺资料、hard 未授权改时、改时缺标记及内部冲突的候选。finish SHALL 将保存子集与全部审核结果关联验证，不能通过最终校验掩盖先前非法写入。

#### Scenario: Unauthorized hard change submitted directly to save
- **WHEN** 模型跳过合法确认，直接把18:00 hard改为19:00传入 save_draft
- **THEN** 写入前返回 GuardViolation，drafts 表没有该非法草稿

### Requirement: Save retries are model selected and bounded

保存失败 SHALL 作为 observation 返回，允许模型基于错误选择一次重试；每次运行最多两次持久化尝试，注入失败也计数。运行时不得在模型之外隐式重试业务保存。没有成功保存且两次失败时，结果 SHALL 为 draft_status=failed、draft_id=null，并说明失败；第三次尝试 SHALL 被拒绝且不执行写入。

#### Scenario: First save fails and retry succeeds
- **WHEN** 只注入 save_draft:1，模型在看到失败后再次调用
- **THEN** 第二次允许保存，最终保存状态来自实际成功返回，不沿用第一次失败

#### Scenario: Both save attempts fail
- **WHEN** 注入 save_draft:1,save_draft:2
- **THEN** 两次均返回错误，最终 failed，无成功 ID，不得声称草稿保存成功

#### Scenario: Model exceeds retry allowance
- **WHEN** 已有两次失败持久化尝试后再次调用 save_draft
- **THEN** 返回 RetryLimitExceeded，不产生第三次数据库写入

### Requirement: Final persistence status follows observed truth

finish SHALL 只接受与本次真实 save_draft 返回和数据库内容相符的 saved/duplicate、draft_id 和候选摘要。failed SHALL 有真实失败尝试且没有已确认成功；not_saved SHALL 仅表示未尝试保存。存在已形成的合法可保存候选时，模型 SHALL 先尝试保存再正常结束；不能用 not_saved 绕过保存流程。预算/模型失败的部分退出 SHALL 保留已确认保存事实。

#### Scenario: Model fabricates saved status
- **WHEN** 本轮没有成功 save_draft，模型提交 saved 与任意 draft_id
- **THEN** finish 拒绝，返回保存证据缺失错误

#### Scenario: Model changes result after save
- **WHEN** 已存19:00草稿，但 finish 在未重新保存情况下声称同一草稿建议20:00
- **THEN** finish 拒绝保存内容不一致

#### Scenario: No schedulable asset
- **WHEN** 所有素材均 blocked、needs_info 或无可用/已授权时间，且没有调用 save_draft
- **THEN** 允许 not_saved、draft_id=null，并保留各项待处理原因

#### Scenario: Resolved confirmation is not pending
- **WHEN** hard候选已获得匹配的可信确认且没有其他待办，但模型再次列为待确认
- **THEN** finish拒绝虚假的未解决事项；保留needs_confirmation改时标记后可修正为completed

### Requirement: Output vocabulary remains draft scoped

系统 SHALL 不含真实发布工具或函数，并在 finish 对结果所有文本字段执行禁词检查，至少拒绝“已发布”“已上线”。命中 SHALL 返回错误供模型修正；对外结果 SHALL 使用草稿保存与待确认措辞。检查 SHALL 覆盖嵌套原因和 pending_items，不能只扫描顶层摘要。

#### Scenario: Publication claim appears in nested reason
- **WHEN** 模型在 risk_reasons、confirmation_reason 或 pending_items 中写入“已上线”
- **THEN** finish 拒绝接受该结果，修正后才能结束

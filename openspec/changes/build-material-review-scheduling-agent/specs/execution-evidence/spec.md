## ADDED Requirements

### Requirement: Reproducible fault injection

系统 SHALL 支持 --faults "tool_name:N[,tool_name:N]" 和 FAULTS 环境变量，CLI 优先。故障计数 SHALL 按运行和工具隔离，参数有效的业务调用递增序号，命中时在副作用前返回统一 InjectedFailure；同一工具的多个序号 SHALL 累积生效。无效工具、格式或非正整数 SHALL 在运行前拒绝。finish 护栏 SHALL 不能通过故障配置绕过。

#### Scenario: Two configured save failures
- **WHEN** 配置 save_draft:1,save_draft:2 并连续执行两次有效保存调用
- **THEN** 两次在写入前失败，数据库无新增草稿，Trace 中包含两个失败 observation

#### Scenario: New run resets counters
- **WHEN** 用相同故障配置启动另一次运行
- **THEN** 调用序号重新从1开始，可重复制造同样失败

### Requirement: Per step trace with actual next action

系统 SHALL 将运行记录写入 examples/traces/<case_id>.jsonl，每个决策步一行，包含 step、action、args、observation_summary、next_action、decision_note。摘要 SHALL 不超过200字符；decision_note SHALL 仅来自模型可选 reason；next_action SHALL 为下一轮实际选择，终止时使用明确结束标记。Trace SHALL 标明 provider，排除密钥和内部思维过程。

#### Scenario: Next decision recorded faithfully
- **WHEN** 某步 query_slots 后模型下一轮选择 request_confirmation
- **THEN** 前一步的 next_action 为实际的 request_confirmation，而非预先推测的 save_draft

#### Scenario: Guard failure appears in trace
- **WHEN** finish 校验失败而模型下一步修正结果
- **THEN** 两次调用及错误摘要分别落盘，reason 缺省时 decision_note 为空

### Requirement: Validated output files and safe evidence paths

系统 SHALL 将校验后的最终结果写入 examples/outputs/<case_id>.json，case_id SHALL 限制为安全文件名字符。Mock 与真实运行的 case_id SHALL 使用不同后缀，例如 normal_mock、normal_real，防止覆盖；证据 SHALL 明确关联来源用例与 provider。无法执行的真实模型用例 SHALL 标为待运行，不得制造输出文件。

#### Scenario: Provider evidence remains separate
- **WHEN** 对 normal 用例分别运行 Mock 与真实 provider
- **THEN** 两份输出和 Trace 各自保留，能够识别来源，不以 Mock 记录充当真实调用

#### Scenario: Unsafe case identifier
- **WHEN** case_id 包含 ../ 或路径分隔符
- **THEN** 在写文件前拒绝，不写入 examples 之外的位置

### Requirement: Required business cases and isolation

交付 SHALL 提供 normal、missing_info、rule_risk、slot_conflict、slot_conflict_hard、duplicate、save_failure、slot_swap 八份输入用例与实际运行材料。测试 SHALL 使用临时数据库；批量脚本 SHALL 隔离独立用例数据，但 duplicate SHALL 与 slot_conflict 共享未重置数据库并核对草稿行数。

#### Scenario: Offline acceptance suite
- **WHEN** 执行 LLM_PROVIDER=mock bash scripts/run_all_cases.sh
- **THEN** 运行八份用例并验证业务预期，逐项汇总实际结果，任一断言失败最终退出码非零

#### Scenario: Duplicate verifies persisted state
- **WHEN** 批量脚本完成 slot_conflict 后运行 duplicate
- **THEN** 不重新 seed 这组数据库，返回原 draft_id，核对 drafts 总行数为1

### Requirement: Meaningful offline tests and real model verification

pytest -q SHALL 默认离线运行 Mock，不依赖 API Key。测试 SHALL 覆盖业务路径、故障注入、step/tool 上限、finish 修正、hard 授权、防伪保存、幂等与事务、低风险、多素材冲突及保存前时段变化。真实模型 SHALL 至少实际验证 normal 与 slot_conflict，或 slot_conflict 与 slot_swap；没有模型访问条件时 SHALL 如实列为未完成验证。

#### Scenario: Default tests run without network credentials
- **WHEN** 无 LLM_API_KEY 且执行 pytest -q
- **THEN** 默认测试不访问真实接口，使用临时数据库完成离线校验

#### Scenario: No access to real model
- **WHEN** 当前没有真实模型密钥或额度
- **THEN** 只生成 Mock 的真实运行材料，results.md 将真实模型列为“待真实模型运行”，不标注为通过

### Requirement: Reviewable submission documents

后续实现交付 SHALL 包含指定的 src、tests、examples、data、docs、固定版本 requirements.txt、.env.example 和 scripts/run_all_cases.sh。README SHALL 提供环境、可复制安装/单用例/测试/批量命令、评审入口与 Mock 边界；docs/01–05 SHALL 分别覆盖需求、方案、评估、AI 使用和个人复盘。results.md 与评估文档 SHALL 逐项关联预期、实际、文件路径、provider 和限制；未执行项 SHALL 不写成通过。AI 使用与复盘 SHALL 不虚构个人贡献或经历。

#### Scenario: Reviewer follows acceptance evidence
- **WHEN** 评审查看任一验收点
- **THEN** 能定位其输入、实际输出、Trace 和 Mock/real 标记，未运行项有明确说明

#### Scenario: AI contribution template is generated
- **WHEN** 生成 docs/04-ai-usage.md 和 docs/05-retrospective.md
- **THEN** 只写可确认的 AI 产物事实及待本人填写的栏目，不编造“我修改了什么”或学习经历

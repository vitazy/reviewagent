## 1. 工程骨架与契约

- [x] 1.1 创建 src/schedule_agent、tests、examples/cases、examples/outputs、examples/traces、data、docs、scripts 目录，配置 src 导入路径，确保支持 python -m schedule_agent.cli 与 pytest -q。
- [x] 1.2 安装并验证 OpenAI SDK、Pydantic、环境变量加载库和 pytest 的兼容版本，固定 requirements.txt；提供不含真实密钥的 .env.example 和必要忽略规则。
- [x] 1.3 实现 RunRequest、CaseSpec、Confirmation、AssetResult、AgentResult 和工具 envelope 模型；校验素材集合、hard/soft、时区整点、结果枚举和安全 case_id。
- [x] 1.4 定义轻量 RuntimeContext，分别保存原请求、可信工具证据、确认、调用预算及持久化记录；不得将模型文字当作可信授权。

## 2. 合成数据与 SQLite

- [x] 2.1 实现 assets、schedule、drafts 表和 idempotency_key UNIQUE 约束，所有数据库时间统一 UTC，业务查询日期采用 Asia/Shanghai。
- [x] 2.2 编写 data/review_rules.json 与 scripts/seed_db.py，生成 M01–M04、2026-10-30 的基础/slot_swap 夹具，显式重置时才清除数据。
- [x] 2.3 为 pytest 提供临时数据库夹具，验证不同测试隔离，并为重复提交场景保留同库状态。

## 3. 审核、时段和确认工具

- [x] 3.1 实现 read_asset、check_rules 和统一异常 envelope，返回缺失字段、风险代码/等级/原因及规则版本；覆盖 M01无风险、M02缺资料、M03高风险、M04低风险。
- [x] 3.2 实现 query_slots，返回指定时段状态与同日后续可用整点；按数据生成19:00/20:00候选，不硬编码案例答案。
- [x] 3.3 实现 request_confirmation 的待办记录和预设回答匹配；绑定素材、确认类型、精确候选时间或风险代码，支持 accepted/rejected/pending。
- [x] 3.4 建立六工具注册表和 function schema，为每个工具添加可选 reason；保存完整 observation，业务异常不抛出 Agent 主循环，不提供发布工具或函数。

## 4. 幂等保存与业务护栏

- [x] 4.1 实现规范化请求及排期结果的 SHA-256，支持 key=auto 的代码展开与显式 key 校验；单测覆盖排序、时区等价、自由措辞变化和业务事实变化。
- [x] 4.2 实现保存前校验：审核证据、缺字段补查、高/低风险处理、时段证据、改时标记、hard 精确授权及批内冲突；验证非法候选无法产生写入。
- [x] 4.3 实现 save_draft 的 BEGIN IMMEDIATE 事务、唯一 key 查重、事务内 schedule 再检查、异常回滚和成功返回；覆盖并发重复、时段变化及重复原 ID。
- [x] 4.4 记录持久化尝试和真实返回，每个运行最多两次尝试，注入失败也计数；实现 RetryLimitExceeded 与 commit 异常按 key 回查，不将不确定结果当成成功。
- [x] 4.5 实现 finish 的 Pydantic 与证据护栏，核对原请求、完整素材集合、草稿内容/ID/状态及待办；覆盖伪造保存、保存后漂移、合法候选跳过保存和嵌套禁词。

## 5. 模型与真实 ReAct 循环

- [x] 5.1 在 prompts.py 编写可用工具、补查、风险、soft/hard、确认、保存重试、停止和禁止编造规则，不要求模型计算哈希或输出内部思维过程。
- [x] 5.2 实现 OpenAICompatibleLLM，读取三个 LLM 配置变量，temperature=0，采用 function calling、有界超时和关闭隐式重试；缺配置明确报错。
- [x] 5.3 实现 MockLLM 的 observation 驱动策略，输出相同 tool_calls；用同一18:00请求的不同 query_slots observation 验证建议随19:00/20:00可用性变化。
- [x] 5.4 实现通用循环与消息回填，要求每轮一个工具调用；对纯文本、多调用、未知工具和坏参数返回可修正错误；对失败 finish 继续决策。
- [x] 5.5 实现默认 MAX_STEPS=12、MAX_TOOL_CALLS=12 及配置入口；覆盖恰好上限完成、反复无效响应、工具预算先耗尽和部分结果退出。
- [x] 5.6 实现模型接口失败的 incomplete_model_error 退出，保留真实已保存状态，对未审核素材只列 unprocessed，不编造审核结论。

## 6. CLI、故障注入与 Trace

- [x] 6.1 实现 FAULTS/--faults 解析与优先级、逐工具逐运行计数及副作用前故障；覆盖同工具多个序号、计数重置和无效配置。
- [x] 6.2 实现 Trace writer，保证摘要≤200字符、reason 直接取自模型、next_action 来自实际下一步，并在正常/异常/预算终止时 flush。
- [x] 6.3 实现 CLI run --case、数据库/预算配置、provider 选择和结果落盘；执行 ID 自动带 _mock/_real 后缀，保留 source_case_id，阻止路径穿越和敏感配置落盘。
- [x] 6.4 验证单用例命令可复制执行，最终 JSON 通过结果模型校验，工具异常不会导致未处理崩溃；明确 CLI 运行错误与业务失败结果的区别。

## 7. 离线验收与补充测试

- [x] 7.1 添加 normal、missing_info、rule_risk、slot_conflict、slot_conflict_hard、duplicate、save_failure、slot_swap 八份 CaseSpec 输入，业务请求及夹具与 design.md 的 A01–A08 一致。
- [x] 7.2 实现 scripts/run_all_cases.sh，独立场景隔离数据库，slot_conflict→duplicate 共享同库并验证仅一行；对输出业务断言逐项汇总，任一失败最终返回非零。
- [x] 7.3 添加 A09–A12 测试：低风险、hard接受/拒绝/错误范围确认、批量素材混合结果及冲突、保存前占用变化、finish拒绝后修正和全部代码护栏。
- [x] 7.4 在无密钥环境执行 pytest -q 与 LLM_PROVIDER=mock bash scripts/run_all_cases.sh，修复失败项，并仅使用实际运行产生的 outputs/traces。

## 8. 评审材料与真实模型验证

- [x] 8.1 整理 README 为环境、安装、seed、单用例、测试、批量运行和评审入口；在 docs/01-requirements.md 保留三份需求来源及逐条验收映射，在 docs/02-solution.md 同步最终方案与取舍。
- [x] 8.2 根据实际 Mock 结果填写 examples/results.md 和 docs/03-evaluation.md，逐项列出预期、实际、provider、证据路径、失败和限制，不把设计预期标成实测。
- [x] 8.3 提供真实 provider 的可复制运行命令，实际调用 normal+slot_conflict 或 slot_conflict+slot_swap，保留独立证据；无密钥/额度时本项保持未完成，评估明确标记“待真实模型运行”。
- [x] 8.4 整理 docs/04-ai-usage.md 和 docs/05-retrospective.md，记录可确认AI产物和人工分工；按本人提供记录实际投入3小时，列全需人工介入的修改/配置/验证事项，依据项目事实撰写复盘，不将AI工作冒充个人独立经历。
- [x] 8.5 最后逐条对照三份来源和五份规格，核对目录、无真实密钥、无发布能力与证据真实性，输出“验收点→文件→状态”清单并如实列出未完成验证。

实施状态（2026-10-29）：35/35项完成。用户提供.env后，normal与slot_conflict两条真实模型路径实际通过并保留独立证据；离线70项测试与10个Mock场景通过。兼容OPENAI配置名及openai provider别名，包含SOCKS依赖，密钥未写入证据或文档。

## 9. 复盘前三项跟进（2026-10-30）

- [x] 9.1 走读循环、确认护栏和事务保存；由本人按README执行安装、单例、测试和批量命令并记录结果。
- [x] 9.2 扩展真实模型至全部10个既有场景，覆盖hard冲突、风险、保存失败、slot_swap，保留实际证据并逐项断言。
- [x] 9.3 验证16项批量输入在默认预算下的部分退出、提高预算后的完成和内部冲突/容量处理，保存可复现输入输出及Trace。
- [x] 9.4 验证审核规则运行中改变、版本号未变但内容改变和无效规则；确保旧审核不能直接保存，能够重新审核或安全部分退出。
- [x] 9.5 使用真实OpenAI SDK和离线HTTP传输模拟验证多种接口响应、错误和并行参数兼容，不将模拟接口结果记为外部服务实测。
- [x] 9.6 汇总新增证据和测试结果，更新复盘前三项状态、README、评估与AI参与记录；GitHub提交信息写入README。

跟进状态（2026-10-30）：本轮6项完成，总计41/41。109项测试、10个Mock及10个真实业务场景通过；另完成6个批量/规则场景、19项原生SDK离线契约测试和1个当前真实接口兼容模式。跟进相关代码由Codex完成，测试与场景执行基本上由本人完成（见docs/04、05）；仓库已公开提交，见README提交信息。

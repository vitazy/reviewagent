# 素材审核与发布排期 Agent

原生 Python ReAct 循环：模型选择工具 → 执行本地工具 → 回填 observation → 模型调整动作或调用 finish。数据均为合成资料，仅保存 SQLite 草稿。

**Mock只验证流程，不证明模型决策效果。当前109项测试、10个Mock场景和全部10个真实模型业务场景通过；另有批量、规则变化及接口兼容验证。**

## 安装与运行

需要 Python 3.11+；开发验证环境为 Python 3.13.5。以下命令在仓库根目录执行。

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scripts/seed_db.py --db data/app.db
LLM_PROVIDER=mock python -m schedule_agent.cli run --case examples/cases/normal.json
pytest -q
LLM_PROVIDER=mock bash scripts/run_all_cases.sh
```

seed 不隐式清空已有数据库；确实需要重置合成资料时使用 `--reset`。单例使用已有数据库，重复运行可能返回 duplicate。批量脚本运行全部10例，独立场景使用独立数据库，slot_conflict→duplicate共享同库；业务断言失败时非零退出。测试默认离线使用临时数据库。

保存失败复现：

```bash
LLM_PROVIDER=mock python -m schedule_agent.cli run --case examples/cases/save_failure.json --faults "save_draft:1,save_draft:2"
```

支持 `--db`、`--provider mock|real`、`--max-steps`、`--max-tool-calls`、`--output-root`。环境变量为 LLM_PROVIDER、MAX_STEPS、MAX_TOOL_CALLS、FAULTS，CLI优先。两项预算默认均为12，多素材可显式提高。有效业务结果（包括保存失败/待处理）退出0，配置错误退出2，运行未完成退出3。

## 真实模型

```bash
cp -n .env.example .env
# 编辑 .env：LLM_PROVIDER=real，填写 LLM_BASE_URL、LLM_API_KEY、LLM_MODEL
python -m schedule_agent.cli run --provider real --case examples/cases/normal.json
python -m schedule_agent.cli run --provider real --case examples/cases/slot_conflict.json
# 或验证全部场景
LLM_PROVIDER=real bash scripts/run_all_cases.sh
```

接口须支持 Chat Completions function calling 和 parallel_tool_calls=false。temperature=0，默认30秒超时，SDK隐式重试为0。缺配置明确报错，不自动切换Mock。只有实际调用才生成_real证据；离线SDK接线测试不算真实模型效果验证。真实验收至少需normal+slot_conflict，或slot_conflict+slot_swap。

兼容 `OPENAI_BASE_URL`、`OPENAI_API_KEY` 和 `LLM_PROVIDER=openai`；非空 `LLM_BASE_URL`/`LLM_API_KEY` 优先于对应OPENAI变量，openai统一记为real。requirements.txt包含SOCKS代理依赖，无需修改已有配置名。

接口若拒绝可选的parallel_tool_calls参数，可设置`LLM_SEND_PARALLEL_TOOL_CALLS=0`；省略参数后运行时仍只接受每轮一个工具调用。

## 扩展验证与选择性复跑

```bash
python scripts/verify_followup.py
# 以下命令会实际调用.env配置的模型
python scripts/verify_serial_gateway.py
LLM_PROVIDER=real bash scripts/run_all_cases.sh --cases slot_conflict_hard rule_risk save_failure slot_swap
```

跟进验证包含16项批量、运行中规则变化和接口契约测试。原生SDK契约测试为离线模拟，当前真实接口还通过省略可选参数模式；不代表其他厂商均已实测。见[跟进报告](docs/06-followup-validation.md)。

选择slot_conflict或duplicate会自动一起运行以验证同库幂等。选择性复跑合并报告；覆盖前的输出和Trace存入examples/history/，不会把失败历史改成成功。

## 输入、结果与业务规则

用例文件为CaseSpec，request包含asset_ids、channel、requested_times和可选confirmations；外层包含case_id、fixture和preset_answers。参考 [冲突输入](examples/cases/slot_conflict.json)。时间必须带时区且为整点，每条占1小时，替代建议默认取同日后续整点。

soft冲突可保存待确认建议；hard改时必须有绑定素材与精确候选的可信确认。low风险可形成待复核草稿，高风险及缺资料项不保存。approved只表示规则允许形成草稿，不表示人工终审完成。

结果含每项审核、风险、原时间、建议时间和确认标记，以及整体保存状态、草稿ID、执行状态和待办。任何改时即使已确认仍保留needs_confirmation=true，只有未解决事项列入pending_items。

输出在examples/outputs/<case_id>_mock.json，Trace在examples/traces/<case_id>_mock.jsonl，真实运行使用_real。Trace记录实际动作/参数、≤200字符的观察摘要、实际后续动作及模型reason，不保存内部思维过程。

## 评审入口

- [需求与验收映射](docs/01-requirements.md)
- [调用图、工具和技术取舍](docs/02-solution.md)
- [实际评估与限制](docs/03-evaluation.md)
- [复盘前三项跟进](docs/06-followup-validation.md)
- [用例实际结果及证据索引](examples/results.md)
- [AI与人工参与记录](docs/04-ai-usage.md)、[项目复盘](docs/05-retrospective.md)
- 根目录保留原选题及考试说明；面向评审的需求映射见 docs/01
- [OpenSpec设计](openspec/changes/build-material-review-scheduling-agent/design.md)、[实施任务](openspec/changes/build-material-review-scheduling-agent/tasks.md)

依赖固定于requirements.txt，.env被忽略，不提交密钥。数据库由scripts/seed_db.py生成，不提交app.db。规范化SHA-256、SQLite事务及唯一约束保证相同业务请求和排期事实只存一份草稿。草稿不预占schedule，保存后排期可能变化，后续执行前须再次查槽。

本人报告实际投入3小时；Codex主要写代码，测试与场景执行基本上由本人完成，问题定位在本人审阅纠偏中同步进行，见[docs/04](docs/04-ai-usage.md)、[docs/05](docs/05-retrospective.md)。

## 提交信息

| 项 | 内容 |
| --- | --- |
| 题号 | 素材审核与发布排期 Agent |
| GitHub URL | https://github.com/vitazy/reviewagent |
| 最终 commit SHA | 以仓库 `main` 分支最新完整 SHA 为准 |
| 仓库可见性 | 公开（无需额外评审账号授权） |

## Why

内容团队需要把素材审核、时段冲突处理、用户确认和草稿保存串成可核验的工作流，避免擅改硬性时间、重复建草稿和虚报保存成功。当前仓库仅有笔试要求与业务说明，需要先形成可实施、可验收的设计，再实现真实模型驱动的 ReAct Agent。

## What Changes

- 新建 Python 包 `schedule_agent`，以 CLI 提供单 Agent、原生 ReAct 循环；真实模型通过 OpenAI SDK 的兼容接口调用工具，离线 Mock 根据 observation 选择动作。
- 建立本地合成素材、审核规则和 SQLite 排期/草稿存储，提供题目要求的六个工具与统一返回协议。
- 明确缺字段补查、高风险阻断、低风险待确认、soft 冲突建议及 hard 冲突授权边界；仅保存草稿。
- 用 Pydantic、运行时证据、保存前校验和 `finish` 护栏约束结果；用事务与唯一幂等键证明重复提交只生成一份草稿。
- 提供默认 12 步的执行预算、独立工具预算、可重复故障注入、逐步 Trace 和实际输出文件。
- 设计八个必需业务用例、低风险及护栏补充测试、真实模型验证入口和评估材料；明确区分预期结果、Mock 实测和真实模型实测。

## Capabilities

### New Capabilities

- `agent-runtime`: 输入输出契约、真实 ReAct 循环、OpenAI 兼容模型、observation 驱动的 Mock、预算与异常恢复。
- `material-review`: 素材读取、规则审核、缺字段补查及风险分级处理。
- `schedule-planning`: 时段查询、soft/hard 约束、可信确认记录和批量素材冲突检测。
- `draft-persistence`: 草稿候选校验、规范化幂等键、事务保存、重试和基于真实保存结果的结束护栏。
- `execution-evidence`: 故障注入、Trace、验收用例、离线测试、真实模型验证与交付文档。

### Modified Capabilities

无。`openspec/specs/` 尚无既有能力，本次均为新增规格。

## Impact

- 后续实现将新增 `src/schedule_agent/`、`tests/`、`data/`、`examples/`、`docs/`、`scripts/`、固定版本的 `requirements.txt` 和 `.env.example`；届时将当前需求型 README 整理为可复制的运行与评审入口，并在需求文档保留来源。
- 运行依赖计划为 OpenAI SDK、Pydantic 和环境变量加载库，测试采用 pytest；SQLite、CLI、哈希和日志使用 Python 标准库。具体补丁版本在实现时经安装与兼容验证后固定。
- 外部调用仅为用户配置的模型接口；业务工具均在本地执行，不涉及真实发布、UI、部署或多 Agent。
- 交付 OpenSpec 材料、业务代码、合成数据脚本、测试、实际运行证据及文档；真实模型记录只通过实际接口调用生成，未验证的部分明确标注。

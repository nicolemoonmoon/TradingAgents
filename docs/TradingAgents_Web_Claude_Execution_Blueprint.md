# TradingAgents Web + DeepSeek/Claude 执行蓝图

> 版本：v1.0  
> 适用项目：`/Users/nicolemoonmoon/ClaudeWork/TradingAgents`  
> 当前目标：用 Claude 做开发助手；运行时先用 DeepSeek API 完成 TradingAgents 主流程；Claude API 之后作为独立 Final Review 模块接入。  
> 核心原则：**DeepSeek 做繁琐多智能体分析；Claude 做关键风控/逻辑终审；暂不做 agent-level routing。**

---

## 0. 给 Claude 的使用方式

这份文档不是让 Claude 一次性全部执行。正确使用方式是：

1. 把本文档放到项目里，例如：

```bash
mkdir -p /Users/nicolemoonmoon/ClaudeWork/TradingAgents/docs
cp TradingAgents_Web_Claude_Execution_Blueprint.md /Users/nicolemoonmoon/ClaudeWork/TradingAgents/docs/
```

2. 在 Claude Code / Claude 里说：

```text
请先阅读 docs/TradingAgents_Web_Claude_Execution_Blueprint.md。不要马上修改代码。先总结你理解的架构、列出当前代码中相关文件、给出 Phase 0 的最小 diff 计划，等我确认后再动代码。
```

3. 每次只让 Claude 执行一个阶段，例如：

```text
现在只做 Phase 0A：定义 Pydantic/JSON Schema、目录结构和枚举。不要做 UI，不要做 Claude Final Review，不要做 agent-level routing。
```

---

## 1. 总体目标

基于现有 TradingAgents 项目做一个网站，手机和电脑都能访问。用户在网页输入股票代码后，系统运行多智能体分析，并在页面展示：

- 多智能体运行过程；
- 每个 agent 的分析报告；
- Bull/Bear 辩论；
- Trader 建议；
- Risk Debate；
- Portfolio Decision；
- 后续 Claude Final Review；
- 完整报告导出。

系统定位是：

```text
美股单票投资研究 + 交易建议草案 + 风控终审工作台
```

不是：

```text
自动交易系统
```

因此必须禁止真实下单、券商 API、`place_order`、`submit_order`、broker execution 等逻辑。

---

## 2. 模型与职责分工

### 2.1 当前阶段职责

| 角色 | 用途 | 是否现在接入 |
|---|---|---|
| Claude / Claude Code | 开发助手，帮助写代码、改前后端、做架构实现 | 是 |
| DeepSeek API | 运行 TradingAgents 多智能体主流程 | 是 |
| Claude API / Anthropic API | 独立 Final Risk Review，读取 DeepSeek 产物后做终审 | 后续 Phase 3 接入 |
| Agent-level routing | 每个 agent 单独选择 provider/model | 暂缓 |

### 2.2 最终运行逻辑

```text
Web UI
   ↓
Run API / Job Orchestrator
   ↓
DeepSeekAnalysisRunner
   ↓
runs/{run_id}/ analysis artifacts
   ↓
ClaudeFinalReviewRunner
   ↓
runs/{run_id}/reviews/{review_id}/ decision artifacts
   ↓
Human Review
   ↓
Research artifact only; no broker execution
```

### 2.3 不要现在做的事情

- 不要把 Claude 塞进 LangGraph 的每个 agent。
- 不要做复杂 agent-level routing。
- 不要把整个主流程 provider 改成 Anthropic。
- 不要接券商。
- 不要做真实下单按钮。
- 不要让前端直接依赖 markdown 正则解析作为长期方案。
- 不要让 FastAPI 请求同步等待十几分钟。

---

## 3. 推荐开发阶段总览

| 阶段 | 名称 | 核心目标 | 完成标准 |
|---|---|---|---|
| Phase 0A | Schema / Contract | 定义目录结构、Pydantic/JSON Schema、枚举 | 有明确 JSON 契约和 artifact 目录规范 |
| Phase 0B | Artifact Writer / Legacy Importer | 实现 atomic writer、events writer、历史报告导入器 | 能为现有 SERVICENOW 报告生成 manifest/status |
| Phase 1A | DeepSeek Runner | 后端可用 DeepSeek 跑 TradingAgents 主流程 | AAPL/NOW 能生成完整 run folder |
| Phase 1B | Stream / Status | 支持粗粒度或 agent 级运行状态 | status/events 可驱动网页进度 |
| Phase 2 | Web API + UI | 手机/电脑展示 run、报告、agent 过程 | 可输入 ticker，后台任务运行，页面展示结果 |
| Phase 3 | Claude Final Review | 独立终审，不侵入 LangGraph | 生成 reviews/{review_id}/decision.json 和 decision.md |
| Phase 4 | Evidence / Cost / Audit | 来源、证据、成本、审计 | 有 source/evidence/cost/audit artifact |
| Phase 5 | Agent-level Routing | 只在有数据证明必要时局部升级 | Research Manager/Portfolio 等可单独用 Claude |

---

## 4. Phase 0A：定义 Run Artifact Contract

### 4.1 目标

先定义稳定的数据契约，让后端 API 和前端 UI 主要读取 JSON，而不是硬解析 markdown。

### 4.2 目录结构

建议使用 `runs/` 作为新网站的运行产物目录。如果保留现有 `reports/`，可以后续做兼容导入。

```text
runs/{run_id}/
├── analysis_manifest.json
├── status.json
├── events.jsonl
├── complete_report.md
├── 1_analysts/
│   ├── market.md
│   ├── fundamentals.md
│   ├── sentiment.md
│   └── news.md
├── 2_research/
│   ├── bull.md
│   ├── bear.md
│   └── manager.md
├── 3_trading/
│   └── trader.md
├── 4_risk/
│   ├── aggressive.md
│   ├── neutral.md
│   └── conservative.md
├── 5_portfolio/
│   └── decision.md
└── reviews/
    └── {review_id}/
        ├── review_manifest.json
        ├── decision.json
        └── decision.md
```

### 4.3 关键原则

- `status.json` 是可变运行视图，可以在执行期间更新。
- `events.jsonl` 是追加式事件日志。
- `analysis_manifest.json` 在 DeepSeek 分析完成后封存，不应被覆盖。
- Claude review 是追加式 artifact，写入 `reviews/{review_id}/`。
- 不要说整个 run folder 完全不可变；准确说法是：**已完成的 analysis artifacts 不覆盖，review artifacts 追加。**

### 4.4 `analysis_manifest.json` 建议 Schema

```json
{
  "schema_version": "1.0",
  "artifact_type": "analysis_manifest",
  "run_id": "AAPL_20260701_165131",
  "ticker": "AAPL",
  "analysis_date": "2026-07-01",
  "created_at": "ISO-8601 timestamp",
  "analysis_status": "completed",
  "analysis_provider": "deepseek",
  "quick_model": "deepseek-v4-flash",
  "deep_model": "deepseek-v4-pro",
  "selected_agents": [
    "market",
    "fundamentals",
    "sentiment",
    "news",
    "bull",
    "bear",
    "research_manager",
    "trader",
    "aggressive_risk",
    "neutral_risk",
    "conservative_risk",
    "portfolio_manager"
  ],
  "draft_rating": null,
  "trader_action": null,
  "research_manager_recommendation": null,
  "stop_loss": null,
  "position_sizing": null,
  "time_horizon": null,
  "position_context_available": false,
  "data_quality_assessment": "not_available",
  "data_quality_flags": [],
  "disclaimer_version": "research-only-v1"
}
```

### 4.5 `status.json` 建议 Schema

```json
{
  "schema_version": "1.0",
  "artifact_type": "run_status",
  "run_id": "AAPL_20260701_165131",
  "analysis_status": "completed",
  "review_status": "not_requested",
  "overall_status": "analysis_completed",
  "current_stage": "portfolio_decision",
  "agents": {
    "market": "completed",
    "fundamentals": "completed",
    "sentiment": "completed",
    "news": "completed",
    "bull": "completed",
    "bear": "completed",
    "research_manager": "completed",
    "trader": "completed",
    "aggressive_risk": "completed",
    "neutral_risk": "completed",
    "conservative_risk": "completed",
    "portfolio_manager": "completed"
  },
  "latest_error": null,
  "updated_at": "ISO-8601 timestamp"
}
```

### 4.6 状态枚举

```text
analysis_status:
queued / running / completed / failed / cancelled

review_status:
not_requested / queued / running / completed / failed / cancelled

agent_status:
not_selected / pending / running / completed / failed / skipped / cancelled
```

`overall_status` 应由 `analysis_status` 和 `review_status` 推导，避免多个地方手写后发生漂移。

### 4.7 `events.jsonl` 事件格式

```json
{"event_type":"run_queued","run_id":"AAPL_20260701_165131","created_at":"ISO-8601"}
{"event_type":"analysis_started","run_id":"AAPL_20260701_165131","created_at":"ISO-8601"}
{"event_type":"agent_started","run_id":"AAPL_20260701_165131","agent_id":"fundamentals","created_at":"ISO-8601"}
{"event_type":"agent_completed","run_id":"AAPL_20260701_165131","agent_id":"fundamentals","created_at":"ISO-8601"}
{"event_type":"agent_failed","run_id":"AAPL_20260701_165131","agent_id":"sentiment","error":"...","created_at":"ISO-8601"}
{"event_type":"analysis_completed","run_id":"AAPL_20260701_165131","created_at":"ISO-8601"}
```

### 4.8 Phase 0A 验收标准

- 有 Pydantic model 或 JSON Schema。
- 有清晰的目录结构定义。
- 有枚举定义。
- 有单元测试验证 schema。
- 不修改 TradingAgents 主流程。
- 不接 Claude Final Review。
- 不做 UI。

---

## 5. Phase 0B：Atomic Writer 与 Legacy Importer

### 5.1 目标

实现稳定的写入工具和历史报告导入器。

### 5.2 Atomic Writer 要求

- 写 JSON 时先写临时文件，再 rename。
- 避免前端读到半写入文件。
- `events.jsonl` 使用 append。
- `status.json` 每次更新必须包含 `updated_at`。
- 不要把 `status.json` 当作任务队列或锁。

### 5.3 Legacy Importer 要求

当前已有历史报告，例如：

```text
reports/SERVICENOW_20260702_165131/
```

该报告结构类似：

```text
complete_report.md
1_analysts/market.md
1_analysts/fundamentals.md
1_analysts/sentiment.md
1_analysts/news.md
2_research/bull.md
2_research/bear.md
2_research/manager.md
3_trading/trader.md
4_risk/aggressive.md
4_risk/neutral.md
4_risk/conservative.md
5_portfolio/decision.md
```

历史导入规则：

- 可以从 markdown 中谨慎提取字段。
- 提取不到就填 `null`。
- 不要编造。
- 对历史报告标记：

```json
{
  "data_quality_assessment": "legacy_import_limited"
}
```

### 5.4 新 run 规则

新 run 不应该靠 markdown 反向解析核心字段。

正确方式：

```text
TradingAgents final state / structured output
        ↓
analysis_manifest.json / status.json
        ↓
Markdown report rendering
```

错误方式：

```text
Markdown report
        ↓
正则表达式猜 JSON
```

### 5.5 Phase 0B 验收标准

- 可以为历史 SERVICENOW 报告生成 `analysis_manifest.json` 和 `status.json`。
- 提取不到的字段保持 `null`。
- 有 atomic JSON writer。
- 有 append-only events writer。
- 不破坏已有 markdown 报告。

---

## 6. Phase 1A：DeepSeek Runner

### 6.1 目标

让后端可以不用交互 CLI，直接调用 TradingAgents 主流程。

推荐方式：

```python
TradingAgentsGraph(...)
graph.propagate(ticker, analysis_date)
graph.save_reports(...)
```

### 6.2 `.env` 当前配置

```bash
DEEPSEEK_API_KEY=你的_deepseek_key

TRADINGAGENTS_LLM_PROVIDER=deepseek
TRADINGAGENTS_QUICK_THINK_LLM=deepseek-v4-flash
TRADINGAGENTS_DEEP_THINK_LLM=deepseek-v4-pro
TRADINGAGENTS_OUTPUT_LANGUAGE=Chinese
TRADINGAGENTS_MAX_DEBATE_ROUNDS=1
TRADINGAGENTS_MAX_RISK_ROUNDS=1
TRADINGAGENTS_CHECKPOINT_ENABLED=true
```

Anthropic key 可以先不用于主流程。若已填写，也不要让 TradingAgents 主流程切换到 Anthropic。

### 6.3 DeepSeek Runner 输出

每次运行生成：

```text
runs/{run_id}/
├── analysis_manifest.json
├── status.json
├── events.jsonl
├── complete_report.md
├── 1_analysts/
├── 2_research/
├── 3_trading/
├── 4_risk/
└── 5_portfolio/
```

### 6.4 验收标准

- 可以跑 AAPL。
- 可以跑 NOW 或 SERVICENOW。
- 使用 DeepSeek provider。
- 生成完整 markdown 报告。
- 生成 `analysis_manifest.json`。
- 生成 `status.json`。
- 失败时 `status.json` 能记录 failed 和 latest_error。
- 没有真实交易执行。

---

## 7. Phase 1B：Streaming / Status Runner

### 7.1 目标

网页最终需要展示多智能体运行过程，因此需要事件流或至少阶段状态。

### 7.2 现实约束

当前 `propagate()` 可能只适合完成后返回最终 state，不一定能稳定提供逐 agent 事件。

因此需要评估是否能新增类似：

```python
graph.stream_analysis(
    ticker,
    analysis_date,
    on_event=update_status
)
```

### 7.3 最小可接受版本

如果短期无法做到 agent 级 streaming，第一版可以只做到粗粒度：

```text
queued → running_analysis → analysis_completed / failed
```

但正式设计应预留 agent 级事件：

```text
market started / completed
fundamentals started / completed
sentiment started / failed
...
```

### 7.4 验收标准

MVP 标准：

- `status.json` 可显示 queued/running/completed/failed。
- `events.jsonl` 有 run_queued、analysis_started、analysis_completed 或 failed。

进阶标准：

- 每个 agent 有 started/completed/failed 事件。
- UI 可展示 agent timeline。
- 异常时记录失败 agent。
- checkpoint 接线不依赖有缺陷的交互 CLI。

---

## 8. Phase 2：Web API + Responsive UI

### 8.1 目标

做一个手机和电脑都能访问的网站。用户可以输入股票代码并查看多智能体分析结果。

### 8.2 后端 API 建议

```text
POST   /api/runs
GET    /api/runs
GET    /api/runs/{run_id}
GET    /api/runs/{run_id}/status
GET    /api/runs/{run_id}/artifacts
GET    /api/runs/{run_id}/report
POST   /api/runs/{run_id}/final-review   # Phase 3 才实现
```

`POST /api/runs` 不应同步等待十几分钟。应返回：

```json
{
  "run_id": "AAPL_20260701_165131",
  "status": "queued"
}
```

HTTP 状态可以使用 `202 Accepted`。

### 8.3 后台任务

单机 MVP 可以使用简单 worker 或后台线程/进程，但要保留升级到持久任务队列的边界。

不要把 `status.json` 同时当作任务队列和锁。

### 8.4 UI 页面结构

#### 全局导航

```text
New Analysis
Research Runs
Dashboard
Reports
Settings
```

#### 单个 Run 页面 Tabs

```text
Overview
Timeline
Analysts
Bull vs Bear
Trader
Risk Debate
Portfolio Decision
Evidence Preview
Full Report
Final Review
```

### 8.5 移动端优先信息顺序

手机端不要一上来展示长 markdown。优先显示：

```text
Final Rating
Trader Action
Research Manager Recommendation
Risk Level
Position Guidance
Human Review Required
Agent Progress
Key Risks
Full Report
```

### 8.6 UI 设计参考

- Research Runs / Dashboard：Koyfin + YCharts + Linear。
- Evidence Center：Quartr，但第一版是 extracted claims，不是真实 citation system。
- Final Rating：WallStreetZen。
- Full Report：Seeking Alpha 阅读体验。
- Technical Chart：第一版先展示技术指标卡片，不做完整 TradingView，因为目前报告没有 OHLCV 数据。

### 8.7 UI 必须显示的免责声明

所有页面必须显示：

```text
本报告仅用于研究与教育目的，不构成投资建议、交易建议或财务建议。所有结论均需人工复核，任何交易决策应由用户自行承担风险。
```

### 8.8 验收标准

- 电脑端可用。
- 手机端可用。
- 用户可以输入 ticker 创建 run。
- 后台运行 DeepSeek analysis。
- UI 能展示 status。
- 完成后能展示各 agent markdown。
- 能展示 final rating / trader action / portfolio decision。
- 不出现真实下单按钮。
- 不接券商 API。

---

## 9. Phase 3：Claude Final Review

### 9.1 目标

Claude 作为独立终审模块，不侵入 LangGraph 主流程。

```text
DeepSeek analysis artifacts
        ↓
Claude Final Review
        ↓
reviews/{review_id}/decision.json + decision.md
```

### 9.2 API

```text
POST /api/runs/{run_id}/final-review
```

### 9.3 输入

MVP 输入：

```text
complete_report.md
analysis_manifest.json
```

更稳版本输入：

```text
complete_report.md
analysis_manifest.json
status.json
agent markdown reports
source_manifest.json（未来）
evidence.json（未来）
```

### 9.4 审查范围必须明确

MVP Claude Review 只能声明：

```json
{
  "review_scope": "reasoning_and_risk_consistency",
  "evidence_verification_status": "not_performed"
}
```

它可以检查：

- 内部逻辑矛盾；
- 风险遗漏；
- 过度自信；
- Bull/Bear 是否平衡；
- 是否需要人工复核；
- 缺少组合上下文时是否不应给精确仓位。

它不能声称已经验证：

- 财务数字真实性；
- SEC filing 原文；
- 新闻来源真实性；
- 行情指标计算正确性。

### 9.5 `review_manifest.json`

```json
{
  "schema_version": "1.0",
  "artifact_type": "final_review_manifest",
  "review_id": "review_20260701_001",
  "run_id": "AAPL_20260701_165131",
  "created_at": "ISO-8601 timestamp",
  "review_provider": "anthropic",
  "review_model": "claude-sonnet-4-6",
  "prompt_version": "final-review-v1",
  "review_scope": "reasoning_and_risk_consistency",
  "evidence_verification_status": "not_performed",
  "reviewed_analysis_manifest_hash": "sha256:..."
}
```

### 9.6 `decision.json`

```json
{
  "schema_version": "1.0",
  "artifact_type": "final_review",
  "review_id": "review_20260701_001",
  "run_id": "AAPL_20260701_165131",
  "verdict": "revise",
  "final_rating": "Hold",
  "confidence": "medium",
  "recommended_position_cap_pct": null,
  "position_context_missing": true,
  "position_guidance": "缺少现有持仓和组合风险信息，仅建议人工结合组合确认。",
  "review_scope": "reasoning_and_risk_consistency",
  "evidence_verification_status": "not_performed",
  "factual_uncertainties": [],
  "missing_evidence": [],
  "risk_gaps": [],
  "required_human_checks": [],
  "human_review_required": true,
  "disclaimer_version": "research-only-v1"
}
```

### 9.7 仓位字段规则

缺少 portfolio snapshot 时：

```json
{
  "recommended_position_cap_pct": null,
  "position_context_missing": true
}
```

不能假装知道用户应该买多少仓位。

### 9.8 验收标准

- Claude Final Review 是独立 API 或独立脚本。
- 不修改 LangGraph 主流程。
- 不影响 DeepSeek analysis。
- 生成 `review_manifest.json`。
- 生成 `decision.json`。
- 生成 `decision.md`。
- UI 显示 review scope 和 evidence verification status。
- 无组合上下文时 position cap 为 null。
- 仍然没有真实交易功能。

---

## 10. Phase 4：Evidence / Cost / Audit

### 10.1 目标

提升系统可信度和成本可控性。

新增可选 artifacts：

```text
source_manifest.json
evidence.json
cost.json
audit_log.json
```

### 10.2 `source_manifest.json`

记录数据来源、时间戳、工具调用信息。

### 10.3 `evidence.json`

每条证据应包含：

```json
{
  "evidence_id": "ev_001",
  "claim": "Revenue growth remained strong",
  "source_type": "filing/news/market/social/agent_report",
  "source_ref": "...",
  "timestamp": "...",
  "used_by_agent": "fundamentals",
  "supports": "bull/bear/neutral/risk",
  "needs_human_check": true
}
```

### 10.4 `cost.json`

记录：

- agent；
- provider；
- model；
- input tokens；
- output tokens；
- reasoning tokens；
- estimated cost；
- fallback；
- prompt version。

### 10.5 `audit_log.json`

记录：

- run_id；
- artifact hashes；
- prompt version；
- model version；
- created_at；
- who triggered run；
- error log。

### 10.6 验收标准

- UI 可以显示本次 run 大致成本。
- Claude review 可以引用 evidence ID。
- 用户可以看到数据来源是否完整。
- 审计信息足够复盘。

---

## 11. Phase 5：Agent-level Routing

### 11.1 目标

只有当数据证明某些环节确实需要 Claude 时，才局部升级模型。

### 11.2 不要全量切 Claude

优先考虑升级：

```text
Research Manager
Portfolio Manager
Final Reviewer
```

不建议先升级：

```text
Market Analyst
Sentiment Analyst
News Analyst
Technical Analyst
```

因为这些 agent 多为高频、批量、低价值 token 消耗。

### 11.3 何时启动 Phase 5

当你已经收集到：

- DeepSeek 一次完整 run 的成本；
- Claude Final Review 是否经常推翻 DeepSeek；
- 哪些 agent 输出最不稳定；
- 哪些 agent 最耗 token；
- UI 用户最关注哪些结论。

再考虑 agent-level routing。

### 11.4 验收标准

- 默认关闭 routing。
- 每个 agent 的 provider/model 可配置。
- fallback 逻辑明确。
- usage/cost 能归因到 agent。
- 不破坏现有 DeepSeek-only 模式。

---

## 12. 前端页面详细设计

### 12.1 New Analysis

字段：

```text
Ticker
Analysis Date
Provider: DeepSeek
Quick Model
Deep Model
Debate Rounds
Risk Rounds
Selected Analysts
Start Analysis
```

验收标准：

- 可以创建 run。
- 手机端表单可用。
- 不显示真实下单选项。

### 12.2 Research Runs

展示所有历史 run：

```text
Run ID
Ticker
Analysis Date
Analysis Status
Review Status
Draft Rating
Trader Action
Research Manager Recommendation
Created At
```

验收标准：

- 可点击进入详情。
- 可区分 analysis completed 和 review completed。

### 12.3 Run Overview

顶部卡片：

```text
DeepSeek Analysis Status
Claude Review Status
Final Rating / Draft Rating
Trader Action
Research Manager Recommendation
Position Guidance
Human Review Required
Evidence Verification Status
```

验收标准：

- 没有 Claude Review 时显示 Not Requested。
- Review 完成后显示 verdict。
- 缺少组合上下文时不显示假仓位百分比。

### 12.4 Timeline

展示 events.jsonl。

验收标准：

- 可以显示 run queued / started / completed。
- 若支持 agent events，显示每个 agent 进度。

### 12.5 Analysts

映射：

```text
1_analysts/market.md
1_analysts/fundamentals.md
1_analysts/sentiment.md
1_analysts/news.md
```

验收标准：

- 每个 analyst 一张 card。
- 可展开完整 markdown。
- sentiment 数据缺失时突出 data quality flags。

### 12.6 Bull vs Bear

映射：

```text
2_research/bull.md
2_research/bear.md
2_research/manager.md
```

验收标准：

- 左右双栏显示多空。
- 显示 manager 平衡结论。
- 显示争议矩阵。

### 12.7 Trader

映射：

```text
3_trading/trader.md
```

验收标准：

- 显示 action、reasoning、stop loss、position sizing。
- 不出现 Buy Now / Sell Now。
- 只允许 Save Note / Export / Mark for Human Review。

### 12.8 Risk Debate

映射：

```text
4_risk/aggressive.md
4_risk/neutral.md
4_risk/conservative.md
```

验收标准：

- 三栏展示 aggressive / neutral / conservative。
- 显示 risk spectrum。
- 显示分歧点。

### 12.9 Portfolio Decision

映射：

```text
5_portfolio/decision.md
```

验收标准：

- 显示 Portfolio Manager 草案。
- 不把它误称为真正组合层风险系统，除非已有 portfolio snapshot。

### 12.10 Final Review

映射：

```text
reviews/{review_id}/decision.json
reviews/{review_id}/decision.md
```

验收标准：

- review_status 为 not_requested 时显示未运行。
- 完成后显示 verdict、final rating、confidence、human checks。
- 明确显示 evidence verification status。

### 12.11 Full Report

映射：

```text
complete_report.md
```

验收标准：

- 支持 markdown 渲染。
- 支持搜索/复制/导出。
- 固定显示免责声明。

---

## 13. 安全与合规 Guardrails

必须遵守：

- 本系统仅用于研究，不构成投资建议。
- 所有结论需人工复核。
- 不接券商。
- 不真实下单。
- 不出现交易执行按钮。
- 缺少数据时显示 unknown/null，不编造。
- 缺少组合上下文时，仓位上限为 null。
- Claude MVP 只做逻辑和风险一致性审查，不声称事实核验。
- Portfolio Manager 当前是单票审批者，不是真正组合经理。

---

## 14. 推荐给 Claude 的分阶段执行 Prompt

### 14.1 Phase 0A Prompt

```text
请先阅读 docs/TradingAgents_Web_Claude_Execution_Blueprint.md。

现在只做 Phase 0A：定义 Run Artifact Contract 的 Pydantic/JSON Schema、目录结构和枚举。

不要做 UI。
不要实现 Claude Final Review。
不要做 agent-level routing。
不要修改 TradingAgents 主流程。
不要接券商或真实下单。

请先输出：
1. 你理解的目标。
2. 当前项目中相关文件。
3. 准备新增或修改哪些文件。
4. 最小 diff 方案。
5. 测试方案。
等我确认后再改代码。
```

### 14.2 Phase 0B Prompt

```text
现在只做 Phase 0B：实现 atomic JSON writer、events.jsonl append writer、legacy importer。

要求：
1. 为历史 reports/SERVICENOW_20260702_165131 生成 analysis_manifest.json 和 status.json。
2. 提取不到的字段填 null，不要编造。
3. data_quality_assessment 标记为 legacy_import_limited。
4. 新 run 以后必须从 structured state 写 JSON，不要从 markdown 反向猜。
5. 先给最小 diff 和测试方案，等我确认再改。
```

### 14.3 Phase 1 Prompt

```text
现在只做 Phase 1：DeepSeek Runner。

目标：后端不用交互 CLI，直接调用 TradingAgentsGraph.propagate() 或你建议的更稳定入口，使用 DeepSeek provider 跑完整 analysis，并生成 run artifact。

要求：
1. 使用 deepseek-v4-flash / deepseek-v4-pro。
2. 生成 complete_report.md 和 agent reports。
3. 生成 analysis_manifest.json、status.json、events.jsonl。
4. 失败时更新 status failed 和 latest_error。
5. 不接 Claude Final Review。
6. 不接券商。
7. 先给最小 diff 和测试方案。
```

### 14.4 Phase 2 Prompt

```text
现在只做 Phase 2：Web API + Responsive UI。

目标：用户可以在网页输入 ticker，创建 DeepSeek analysis run，后台执行，前端轮询状态并展示报告。

要求：
1. POST /api/runs 返回 202 Accepted 和 run_id。
2. 不要同步等待长任务完成。
3. GET /api/runs/{run_id}/status 返回 status.json。
4. UI 支持手机和电脑。
5. 展示 Research Runs、Overview、Timeline、Analysts、Bull vs Bear、Trader、Risk、Portfolio、Full Report。
6. 不出现真实交易按钮。
7. 先给最小 diff 和测试方案。
```

### 14.5 Phase 3 Prompt

```text
现在只做 Phase 3：独立 Claude Final Review。

目标：Claude 不侵入 LangGraph，只读取 DeepSeek run artifact，生成 reviews/{review_id}/decision.json 和 decision.md。

要求：
1. review_scope = reasoning_and_risk_consistency。
2. evidence_verification_status = not_performed。
3. 缺少组合上下文时 recommended_position_cap_pct 必须为 null。
4. 输出 review_manifest.json、decision.json、decision.md。
5. UI 显示 Claude 未做事实核验。
6. 不修改 DeepSeek 主流程。
7. 先给最小 diff 和测试方案。
```

---

## 15. 最终验收清单

### 15.1 产品验收

- 手机和电脑都能访问。
- 用户可以输入股票代码。
- 系统可以启动 DeepSeek 多 agent analysis。
- 页面可以显示运行状态。
- 页面可以展示每个 agent 报告。
- 页面可以展示最终 Portfolio Decision。
- 页面可以展示 Claude Final Review。
- 页面可以导出或查看完整报告。

### 15.2 工程验收

- JSON 是 API/UI 事实来源。
- Markdown 只是阅读层。
- status 可变，analysis artifact 封存，review artifact 追加。
- 有 atomic writer。
- 有 events log。
- 有 legacy importer。
- 有测试。

### 15.3 安全验收

- 无券商 API。
- 无真实下单。
- 无 Buy Now / Sell Now 执行按钮。
- 所有页面有免责声明。
- 缺少数据时不编造。
- 缺少组合上下文时仓位为 null。
- Claude MVP 明确未做事实核验。

---

## 16. 一句话总路线

```text
Claude 负责帮你写代码和搭系统；DeepSeek 先负责完整 TradingAgents 主分析；网页先围绕结构化 run artifact 展示多智能体过程；Claude API 后续作为独立 Final Review 接入；最后再根据真实成本和质量决定是否做 agent-level routing。
```

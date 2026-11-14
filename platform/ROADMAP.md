# 平台建设路线图

> 状态：**M0 已批准，可开工（2026-11-12）**。
> 模块职责见 `MODULES.md`；租户与 Langfuse 映射见 `DESIGN.md`；接入与重聚类见 `LIFECYCLE.md`；
> 内网部署事项持续记录在 `DEPLOYMENT.md`；业务方使用说明持续记录在 `USAGE_GUIDE.md`。

## 0. 已批准决策

1. **首版范围**：只支持 Langfuse Cloud v4 与自托管 v4；自托管 v3 延后。
2. **技术栈**：后端 FastAPI + Uvicorn；前端 React + TypeScript + ECharts。
3. **持久化**：M1 使用 SQLite；DDL 保持 PostgreSQL 兼容，M5 再切换评估。
4. **异步作业**：M1 使用进程内线程池 + 数据库状态机；M5 压测后再评估引入队列。
5. **契约策略**：M0 一次性设计 M1~M4 的 REST 契约与持久化 schema，分阶段实现。

三个时序判断也已批准：

1. M1 先做无 Langfuse key 的基准闭环，M2 再接真实 Langfuse。
2. REST 契约和 DDL 先冻结，前端与后端并行开发。
3. 多租户硬化放在 M5；若真实租户接入时间提前，限流与隔离同步提前。

## 1. 阶段总览

```text
M0 契约冻结
  └─> M1 基准数据纵向闭环
        └─> M2 真实 Langfuse 接入
              └─> M3 回写与复核闭环
                    └─> M4 生命周期与重聚类
                          └─> M5 多租户与性能硬化
```

| 阶段 | 目标 | 依赖 Langfuse key | 出口验收 |
|---|---|---|---|
| M0 | 冻结 OpenAPI、DDL、配置 schema、`TraceSource` 接口、前端路由 | 否 | 前后端可各自对 mock 开工 |
| M1 | 用基准数据打通端到端最小闭环 | 否 | 基准结果位级复现 |
| M2 | 接入 Cloud v4 / 自托管 v4 真实数据 | 是 | 一个真实 project 完成首跑 |
| M3 | 分数写回、人工复核、告警预算 | 是 | Langfuse 中可见分数并完成回流 |
| M4 | R1/R2/R3 生命周期与 lineage | 是 | 一次受控 R2 前后可对账 |
| M5 | 多租户限流、隔离与性能 | 是 | 10 万条/天压测达标 |

## 2. M0 交付物

1. **OpenAPI 3 契约**
   - 覆盖 M1~M4 的 REST 端点。
   - 明确请求、响应、错误码、分页、异步状态、幂等键。
   - 前端只允许调用平台 REST，不允许直连 Langfuse。

2. **持久化 schema**
   - 表：`tenants`、`ontologies`、`cohort_runs`、`run_steps`、`cells`、`cell_lineage`、
     `trace_scores`、`score_evidence`、`calibration_runs`、`startup_records`。
   - 必须从第一版就包含 `structure_version`、`anchor_version`、`ontology_version`、`code_hash`。
   - 历史分数不可变；趋势图跨版本画边界线，不跨版本连线。

3. **配置 schema**
   - `endpoints.yaml`：Langfuse API 路径与请求旋钮。
   - `profiles/cloud-v4.yaml`、`profiles/selfhosted-v4.yaml`：`base_url`、capabilities、
     `version_constraint`、throttle。
   - `tenants/<id>.yaml`：org/project/key/queue 等租户档案。
   - 本体 YAML：Tier 0 / Tier 1 分层。

4. **`TraceSource` 接口**
   - `list_traces(window, sampling) -> Iterator[RawTrace]`。
   - 输出符合 `contracts/schemas.md` 的 19 键 trace 与 29 键 span。
   - 不可得字段必须置 `None`，不允许伪造或静默丢弃。

5. **前端路由与数据依赖**
   - M1 页面：F0 全局状态、F2 Run 发起、F3 聚类结果、F4 异常工作台、F5 单轨迹下钻。
   - M2 之后页面：F1 接入注册、F6 复核回流、F7 趋势、F8 自检、F9 管理面。

6. **活文档初始化**
   - `DEPLOYMENT.md`：持续记录三方件、版本、DDL、模型资产、启动与验收命令。
   - `USAGE_GUIDE.md`：持续记录业务方接入、使用、结果解读和复核流程。

M0 契约文件已落盘（路径均相对仓库根目录）：

- `platform/contracts/openapi.yaml`
- `platform/contracts/schema.sql`
- `platform/contracts/TRACE_SOURCE.md`
- `platform/contracts/FRONTEND_ROUTES.md`
- `platform/config/endpoints.yaml`
- `platform/config/profiles/cloud-v4.yaml`
- `platform/config/profiles/selfhosted-v4.yaml`

M3.4 calibration record: [`M3_4_CALIBRATION.md`](M3_4_CALIBRATION.md).

## 3. M1 纵向闭环

- 后端：已实现 `JsonlTraceSource`、作业状态机、算法执行壳、结果存储、REST 最小子集。
- 前端：已实现 F0/F2/F3/F4/F5 的最小版本。
- 数据：读取 `data/bench_v1/`，注册为平台内部租户。
- 验收：
  1. 基准 scorecard 位级复现。
  2. Run 生命周期可追踪。
  3. 零残差证据链可三步下钻。
  4. R1 只做冻结结构下的贴标签与基线刷新，不允许每天触发结构重聚类。
  当前状态：第 1~4 条已通过。生产算法首跑会捕获完整冻结状态
  （质心、medoid、`sigma2`、`geo_cut`、singleton 集、`memcons` 与本体）；
  后续 R1 Run 复用同一 `structure_version`，只贴新轨迹标签并重建簇内基线，
  不再调用 `cluster_views`。旧版仅含 `cluster_info` 的结构无法重放时会重建一次
  兼容结构，之后的 R1 均走冻结路径。

## 4. M2 真实 Langfuse

- 实现 `LangfuseTraceSource`，只使用 Observations v2。
- 支持游标分页、限流、字段组、`expandMetadata`、usage 映射。
- 完成 8 项适配度预检、Tier 0 本体合成、首跑。
- 启动时调用 `GET /api/public/health` 做 profile 版本核对，不匹配则拒绝启动。

当前状态：

- 已实现 fixture 级 `LangfuseTraceSource`：Observations v2 游标分页、空页续拉、
  跨页按 `traceId` 重组、19/29 键内核契约映射、usage/cost 映射、429/网络错误重试、
  endpoint/profile 配置装配。
- 已实现业务租户注册、Tier 0/Tier 1 本体注册，以及基于近 7 天样本的 8 项适配度
  预检 REST 入口。
- 已覆盖 11 个单测；真实 Langfuse Cloud v4 key 联通已通过。
- 已新增 `LangfuseOTLPTraceIngestor` 与
  `platform/scripts/langfuse_v4_smoke.py`：向
  `POST /api/public/otel/v1/traces` 写入一条 3-span 开发轨迹，再通过
  Observations v2 读回并映射为内核契约。
- Cloud v4 实测返回 `otel-ingestion-job` 异步任务对象而非文档示例的空对象；
  两种响应均已按合法成功处理。
- 已实现 Tier 0 自动合成与不可变 `ontology@version` 发布：仅包含
  `id` / `version` / `unit_price`，业务方零填写。
- 已实现生产执行壳 `platform/app/algorithm.py`：从 Langfuse 轨迹观测自动合成
  动态最小本体，不改 `kernel/`，驱动
  `ingest → features → cluster → baseline → detect → score`，并输出生产版
  `scores.jsonl` 与 `metrics.json`。
- 已实现 `source=langfuse` 的 REST Run 发起与异步执行链路。
- 真实 Cloud Project 首跑已通过：
  `run-1a703e4a8c584836`，20 条轨迹、1 个 cell、Run 成功、冷启动降级为 true，
  内核 `code_hash=2064664e6aa5fb46` 未变化。
- 已实现基准数据批量导入脚本
  `platform/scripts/langfuse_benchmark_import.py`：支持批量 OTLP 写入、
  ID 偏移、历史时间窗展开、异步等待与读回校验；导入时保留
  `answer_numbers` / `output_facts` 等结果评估字段，避免结果维度被误判。
- 真实 Cloud Project 千条级非冷启动 Run 已通过：
  `run-35339336f1e24ab4`，1000 条轨迹、5 个 cell、冷启动 false、
  40 条告警、85 条弃权、平均分 89.9738，内核
  `code_hash=2064664e6aa5fb46` 未变化。该结果证明读写链路、动态 Tier 0
  本体、结果评估字段回传和生产打分链路均可用。
- R1 冻结结构 1000 条基准复验已通过：首跑为 R2，复跑为 R1；
  逐条比较 `trace_id / cell / novelty` 完全一致，非冷启动，内核
  `code_hash=2064664e6aa5fb46` 未变化。

## 5. M3 运营闭环

- 已实现 `POST /api/public/scores` 写回租户 project：每条 trace 写回
  `traj-engine-total-score`、`traj-engine-alert`、`traj-engine-abstain`
  三个 trace 级 Score；总分携带五维分数、cell、runId、codeHash 等 metadata。
- 写回由 Run 输入的 `writebackToLangfuse` 显式开启；默认失败只把
  `score_writeback` 步骤标记为 failed，不推翻算法 Run 的 succeeded 状态。
  `writebackStrict=true` 时可将写回失败升级为 Run 失败。
- 写回使用可配置 endpoint 与 Basic Auth，批量分片默认 100，支持
  429/5xx 重试，兼容 Langfuse 的 202 全量接受与 207 部分拒绝响应。
- 前端 Run 发起器支持选择 `基准 JSONL` / `Langfuse Project`，Langfuse
  模式下可勾选「评分写回 Langfuse Scores」。
- 真实 Cloud v4 冒烟已通过：1 条 trace、3 个 Score，全部 accepted，
  rejected=0。
- 复用 Langfuse 原生标注队列做人工复核：
  - 平台自动创建/复用 `traj-engine-review` 队列。
  - 自动创建/复用 3 个人工复核 Score Config：
    `traj-engine-human-verdict`（Agree / Disagree / Uncertain）、
    `traj-engine-human-label`、`traj-engine-human-comment`。
  - `POST /api/v1/runs/{runId}/review-queue` 可把告警/弃权轨迹推入队列，
    本地 `review_queue_items` 记录 run、trace、queue item 的映射。
  - `POST /api/v1/runs/{runId}/review-queue/sync` 同步队列完成状态，
    并把该 queue 的 ANNOTATION Scores 转成 `human_reviews`。
  - 前端 Run 概览提供「推送复核队列」与「同步 Langfuse 人工复核」。
  - 真实 Cloud v4 已完成队列、Score Config、队列 item、人工 Score、
    完成状态与读回验证。
- 告警预算与 top-K 排序已实现：
  - 每条告警计算统一优先级：低分严重度 34%、最差维度 20%、扣分强度 16%、
    规则/统计根因严重度 20%、cell 影响面 10%。
  - 按「cell + 主根因」分组，同组只放行 1 条代表告警，其余标记
    `suppressed_duplicate`。
  - 按 Run 预算只放行 top-K 代表告警，其余代表告警标记 `candidate`。
  - 预算默认 5，配置在 `platform/config/alerts.yaml`。
  - 新增 `alert_decisions` 表持久化每个 Run 的优先级、排名、分组、
    状态与原因；Run Steps 新增 `alert_budget`。
  - REST 提供 `GET /runs/{runId}/alerts`、
    `GET /runs/{runId}/alert-candidates`、
    `GET /runs/{runId}/alerts/summary`、`GET /config/alerts`。
  - 前端新增「告警工作台」，区分正式告警与候选异常，并展示预算摘要、
    根因组、优先级和下钻入口。
  - 1000 条真实 Cloud Run 复验：原始告警 40 条 → 21 个根因组 →
    正式告警 5 条、预算外 16 条、同组去重 19 条，满足预算目标。
- 复核标签回流触发校准。

## 6. M4 生命周期

### 6.1 已实现

- `lifecycle_schedules` / `lifecycle_evaluations` 两张表与 REST 契约：
  - `GET/PUT /api/v1/ontologies/{id}/lifecycle`
  - `POST /api/v1/ontologies/{id}/lifecycle/evaluate`
  - `GET /api/v1/ontologies/{id}/lifecycle/evaluations`
- 显式评估入口：按调度策略创建 R1/R2 Run；`forceR2=true` 可人工强制重聚类。
- R1：固定 active structure，周期到期时刷新簇内基线与分数。
- R2：冷启动、强制触发、novelty 阈值或告警率阈值触发新结构版本。
- 幂等：按 R1 周期把当前时间切成固定评估桶；同一桶且调度未更新时
  idempotency key 为
  `lifecycle:{ontologyId}:{evaluationBucket}:{scheduleUpdatedAt}`，
  重复评估会复用已创建的 Run。
- R2 结构演化写入 `cell_lineage`，按相同 trace 在新旧 cell 的重叠计数生成
  `continued / split / merged` 关系，overlap 用旧 cell 中被延续的样本比例表示。
- 前端新增「生命周期」页：选择本体、保存调度、手动评估、强制 R2、
  查看评估历史并跳转 Run。

### 6.2 尚未实现

- 常驻定时器与调度锁：当前采用 REST 显式评估，避免首版引入后台任务竞态。
- R3：本体升版流程。
- novelty 积累到最小样本数后的自动 R2 提案。

### 6.3 M4.1 受控 R2 对账

- `GET /runs/{runId}/lineage` 返回新旧 cell 的 key、规模、关系与 overlap，
  前端无需再拼装多个接口。
- 前端新增 `#/runs/{runId}/lineage` 结构演化页：
  - 汇总延续 / 拆分 / 合并 / 新生 / 消亡数量。
  - 逐行展示旧 cell → 新 cell、overlap 和规模变化。
  - 明确提示 R2 不改写历史分数，R1 不会生成 lineage。
- 新增 `platform/scripts/r2_lineage_validation.py`：
  - `--source benchmark`：本地基准快速验收，不依赖 Langfuse key。
  - `--source langfuse`：真实 Project 受控验收。
  - 连续创建两次 R2，校验结构版本 +2、第二个结构 active、
    第一个 Run 分数摘要不变、lineage 非空、overlap 合法、
    `code_hash=2064664e6aa5fb46`。

### 6.4 M4.2 生命周期调度与运维可靠性

- 新增 `platform/app/scheduler.py`：
  - 后台周期扫描全部 enabled lifecycle schedule。
  - 每轮先执行 Run 看门狗，再调用既有生命周期评估入口。
  - 单实例租约锁：`scheduler_locks`；锁过期后可被新实例接管。
  - 每轮扫描审计：`scheduler_scans`，记录看门狗处理数、评估数、创建 Run
    数、完整结果与错误。
- 新增配置：`platform/config/scheduler.yaml`。
  - `intervalSeconds` 默认 60。
  - `leaseSeconds` 默认 120。
  - `watchdog.queuedTimeoutSeconds` 默认 900。
  - `watchdog.runningTimeoutSeconds` 默认 86400。
- 后端启动：
  - `python -m platform.app.cli --scheduler ...` 开启常驻调度线程。
  - 或设置 `TRAJ_SCHEDULER=1` 后启动 `platform.app.service:app`。
- REST：
  - `GET /api/v1/scheduler/status`
  - `POST /api/v1/scheduler/evaluate-all`
- 前端生命周期页新增调度器状态面板与「调度扫描全部本体」按钮。

R3：本体升级仍由业务规则变更触发，后续独立实现。

## 7. M5 多租户与硬化

- 多租户配额与隔离。
- 10 万条/天压测。
- SQLite → PostgreSQL 切换评估。
- 失败恢复、重试、幂等与运维告警。

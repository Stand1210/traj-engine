# 内网部署记录（活文档）

> 状态：随工程开发持续补充，不在当前阶段一次性编写完整部署手册。
> 目标：当平台进入内网部署时，本文能回答「需要哪些组件、哪些版本、如何初始化数据、如何启动、如何验证」。
> 内网迁移、凭据隔离、发布包迁移与 AI 工具/模型接管总流程见
> [`INTRANET_HANDOFF.md`](INTRANET_HANDOFF.md)。

## 1. 部署范围

| 项 | 首版决策 | 记录状态 |
|---|---|---|
| Langfuse | Cloud v4 或自托管 v4 | 已定；自托管 v3 延后 |
| 平后端 | FastAPI `0.115.6` + Uvicorn `0.34.0` | M1 最小闭环已实现 |
| 前端 | Node.js `24.x` + Vite `6.0.7` + React `18.3.1` + ECharts `5.6.0` | M1 最小闭环已实现 |
| 数据库 | SQLite（内置于 Python 3.11） | 当前契约：23 张表，schema v10 |
| Embedding | 待定 | 选型后记录模型名、版本、维度、输入截断规则与哈希 |

## 2. 持续记录规则

后续每个开发阶段涉及以下内容时，必须同步更新本文：

1. **三方件与版本**：数据库、Web 框架、驱动、序列化库、前端构建工具、图表库等。
2. **数据库初始化**：建表 DDL、迁移脚本、索引、约束、初始化数据。
3. **模型资产**：embedding 模型名、版本、维度、缓存策略、输入长度限制、产物哈希。
4. **启动与配置**：`--profile`、`--base-url`、环境变量、profile 文件、租户档案。
5. **验证命令**：部署后连通性检查、版本核对、M1 基准位级复现、核心接口冒烟测试。
6. **升级影响**：组件或模型变更对 `code_hash`、`structure_version`、历史分数可比性的影响。

## 3. 当前已确定事项

- 首版 profile 仅包含 `cloud-v4` 与 `selfhosted-v4`。
- 一套平台部署只对接一个 Langfuse 实例。
- `Organization = 租户`，`Project = 本体`，一个 project 只承载一类 agent 轨迹。
- 基准数据集不导入 Langfuse，通过 `JsonlTraceSource` 作为平台内部租户接入。
- M0 已冻结 `platform/contracts/openapi.yaml`、`platform/contracts/schema.sql`、
  `platform/config/endpoints.yaml` 与两份 v4 profile。
- M1 后端运行依赖：
  - Python `3.11.x`
  - `fastapi==0.115.6`
  - `uvicorn[standard]==0.34.0`
  - `PyYAML==6.0.3`
  - 运行期传递依赖：`pydantic==2.14.3`、`starlette==0.41.3`
- M1 前端依赖：
  - Node.js `24.19.0`（内网可按 `>=24 <25` 准备）
  - `vite==6.0.7`
  - `react==18.3.1`
  - `react-dom==18.3.1`
  - `echarts==5.6.0`
  - TypeScript `5.7.2`
  - 锁文件：`frontend/package-lock.json`
- M1 启动：
  ```powershell
  python -m pip install -r requirements.txt
  python -m uvicorn platform.app.service:app --host 127.0.0.1 --port 8000
  ```
  或使用启动参数封装：
  ```powershell
  python -m platform.app.cli run --profile selfhosted-v4 --base-url http://langfuse.internal --db platform/var/traj-engine.db
  ```
- M1 前端启动：
  ```powershell
  cd frontend
  npm install
  npm run dev
  ```
  开发代理默认指向 `http://127.0.0.1:8000`。
  生产构建：
  ```powershell
  cd frontend
  npm run build
  ```
- M1 数据库初始化：
  - 默认库：`platform/var/traj-engine.db`
  - 建表语句：`platform/contracts/schema.sql`
  - 应用启动时自动执行；本地运行产物目录已 gitignore
  - 推荐部署前显式执行：
    `python -m platform.app.cli init --db platform/var/traj-engine.db`
- M1 已验证：
  - 5 个 YAML 契约解析通过
  - SQLite DDL 建表 23 张通过
  - R1 全量 4000 条 Run 成功
  - `reports/R1/scores.jsonl` 位级复现通过
  - 前端 `npm run build` 通过
- M2 新增后端源（无新增三方件）：
  - `LangfuseTraceSource` 使用 Python 标准库 `urllib.request` 访问
    `GET /api/public/v2/observations`，通过 `platform/config/endpoints.yaml`
    与 v4 profile 装配 URL 和请求参数。
  - `LangfuseOTLPTraceIngestor` 使用 Python 标准库访问
    `POST /api/public/otel/v1/traces`，携带
    `x-langfuse-ingestion-version: 4`；仅用于开发环境播种与连通性自检。
  - 配置加载支持仓库根目录 `.env`，可设置
    `LANGFUSE_BASE_URL`、`LANGFUSE_PUBLIC_KEY`、`LANGFUSE_SECRET_KEY`；
    `.env` 已被 gitignore，真实凭据不得入库。
  - 本阶段验证命令：`python -m unittest discover -s platform/tests -v`
- M2 真实 Cloud v4 冒烟：
  ```powershell
  python platform/scripts/langfuse_v4_smoke.py --profile cloud-v4 --wait-seconds 10
  ```
  脚本会写入一条固定 `trace_id`、3 个 span 的开发轨迹，等待异步 ingestion
  落库后按时间窗读回，输出 kind/action/tool/model/token 映射结果。
  已实测通过：`agent`、`tool`、`llm` 三类 span 均保留，工具名、模型名与
  prompt token 可读回。
- M2 真实 Project 生产 Run 冒烟：
  ```powershell
  python platform/scripts/langfuse_production_smoke.py --profile cloud-v4 --project-name development_env --minutes 30 --limit 20
  ```
  脚本会注册/复用租户与 Tier 0 本体，从 Langfuse 拉取时间窗内轨迹，执行
  生产算法壳并落库。已实测 `run-1a703e4a8c584836` 成功：20 条轨迹、1 个
  cell、冷启动降级 true、`code_hash=2064664e6aa5fb46`。
  该脚本仅用于开发验收，不是业务方日常入口。
- M2 千条级基准导入与非冷启动验证：
  ```powershell
  python platform/scripts/langfuse_benchmark_import.py --profile cloud-v4 --regime R1 --count 1000 --batch-size 50 --wait-seconds 30 --spread-seconds 3600 --id-offset 400000000000
  python platform/scripts/langfuse_production_smoke.py --profile cloud-v4 --project-name development_env --minutes 120 --limit 1000 --id-offset 400000000000 --id-count 1000
  ```
  第一条命令写入 1000 条基准轨迹并读回校验；第二条命令只分析该 ID 段，
  避免混入同项目中的历史导入数据。已实测 `run-35339336f1e24ab4`：
  1000 条轨迹、5 个 cell、冷启动 false、40 条告警、85 条弃权、平均分
  89.9738。
  Cloud OTLP ingestion 为异步落库；子观测可能先于根观测可见，因此读回
  路径会跳过并统计 incomplete traces，等待后再执行 Run。
- M2 后续 R1 行为：首跑或兼容旧结构时会生成/重建冻结结构；之后同一本体
  的 R1 Run 复用 `structure_versions` 中当前 active 版本，不再新建结构。
- 本地 1000 条 R1 基准复验：首跑 R2、复跑 R1，逐条
  `trace_id / cell / novelty` 完全一致，`code_hash=2064664e6aa5fb46`。
- M2 新增 REST 能力：
  - `POST /api/v1/tenants`：注册 Langfuse org/project 与项目 API key。
  - `POST /api/v1/ontologies`：创建 Tier 0/Tier 1 本体占位。
  - `POST /api/v1/ontologies/{id}/prechecks`：拉取近 7 天样本并执行 8 项适配度预检。
  - `GET /api/v1/ontologies/{id}/versions/current`：查看当前不可变本体版本。
  - `POST /api/v1/runs` 支持 `source=langfuse`，按时间窗发起真实数据 Run。

## 3.1 M3 Score 写回部署记录

- 无新增数据库表、三方件或 embedding 模型；复用 SQLite 表
  `run_steps` 记录写回结果。
- 新增后端源：
  - `LangfuseScoreWriter` 使用 Python 标准库访问
    `POST /api/public/scores`。
  - endpoint 与批量大小由 `platform/config/endpoints.yaml` 的
    `endpoints.scores.create` 与 `limits.scoresCreateBatchSize` 配置。
- 写回内容：每条 trace 三个 Score
  （`traj-engine-total-score` / `traj-engine-alert` /
  `traj-engine-abstain`），批量默认 100，自动重试 429/5xx。
- 失败语义：默认 `score_writeback` failed 不影响 Run succeeded；
  `writebackStrict=true` 时升级为 Run failed。
- 验证命令：
  ```powershell
  python -m unittest discover -s platform/tests -v
  python platform/scripts/langfuse_production_smoke.py --profile cloud-v4 --project-name development_env --minutes 240 --limit 1 --id-offset 400000000000 --id-count 1 --write-scores
  ```
- 真实 Cloud v4 已验证：直接写回 1 条 trace 的 3 个 Score，
  返回 `accepted=3 / rejected=0`。同一脚本的完整读-算-写链路在当前
  代理环境下读取阶段可能挂起；这是开发网络问题，不代表 Scores API
  写回失败。

### 3.1.1 M3 人工复核队列部署记录

- 新增数据表：`review_queue_items`，记录 Run、trace score、Langfuse
  queue item 与人工复核导入结果的映射。建表语句在
  `platform/contracts/schema.sql`，应用启动时自动创建。
- 新增后端源：`LangfuseAnnotationQueueClient`，使用 Python 标准库访问：
  - `GET/POST /api/public/score-configs`
  - `GET/POST /api/public/annotation-queues`
  - `GET/POST/PATCH /api/public/annotation-queues/{queueId}/items`
  - `GET /api/public/v3/scores`
  所有 URL 均由 `platform/config/endpoints.yaml` 装配。
- 平台自动创建的复核资产：
  - 队列：`traj-engine-review`
  - categorical config：`traj-engine-human-verdict`
  - text configs：`traj-engine-human-label`、`traj-engine-human-comment`
- 无新增三方件、无 embedding 模型；人工结论最终落在 SQLite 表
  `human_reviews`。
- 真实 Cloud v4 验证记录：
  - queue id：`cmwdd9lhj000uad0khg1zb4zn`
  - queue item id：`cmwdd9uzi005rad0el1kr4rh5`
  - 已推入 1 条 trace、写入 1 条 `ANNOTATION` verdict Score、
    将 item 置为 `COMPLETED`，并可通过 Scores v3 按 `queueId + traceId`
    读回。

### 3.1.2 M3 告警预算部署记录

- 新增数据表：`alert_decisions`，记录每个 Run 内每条原始告警的
  优先级、全局排名、根因组、组内排名、状态与解释原因。建表语句在
  `platform/contracts/schema.sql`，应用启动时自动创建。
- 新增配置文件：`platform/config/alerts.yaml`。
  - `budgetPerRun`：每个 Run 的正式告警数，默认 5。
  - `maxPerGroup`：当前固定为 1，同组只放行一条代表告警。
  - `weights`：优先级各分量权重，当前实现读取配置用于展示，
    计算公式与配置保持一致。
- 无新增三方件、无 embedding 模型；计算在 Python 标准库内完成。
- Run 持久化后自动执行 `alert_budget` 步骤并写入 `alert_decisions`。
- REST：
  - `GET /api/v1/runs/{runId}/alerts`
  - `GET /api/v1/runs/{runId}/alert-candidates`
  - `GET /api/v1/runs/{runId}/alerts/summary`
  - `GET /api/v1/config/alerts`

M3.4 calibration deployment: [`M3_4_CALIBRATION.md`](M3_4_CALIBRATION.md).
- 前端路由：`#/runs/{runId}/alerts`。
- 1000 条真实 Cloud Run 验证：
  - 原始告警 40
  - 根因组 21
  - 正式告警 5
  - 预算外候选 16
  - 同组去重 19

## 3.2 M4 生命周期部署记录

- 新增数据表：
  - `lifecycle_schedules`：保存每个本体的调度策略、分析窗口、阈值与写回开关。
  - `lifecycle_evaluations`：保存每次评估的决策、原因、指标与创建的 Run。
  建表语句在 `platform/contracts/schema.sql`，应用启动时自动执行。
- 新增后端模块：`platform/app/lifecycle.py`，只依赖 Python 标准库与现有
  SQLite 存储层；无新增三方件、无 embedding 模型。
- 新增 REST：
  - `GET/PUT /api/v1/ontologies/{id}/lifecycle`
  - `POST /api/v1/ontologies/{id}/lifecycle/evaluate`
  - `GET /api/v1/ontologies/{id}/lifecycle/evaluations`
- 生命周期触发 Run 时复用现有 `POST /runs` 作业链路，并用
  `lifecycle:{ontologyId}:{evaluationBucket}:{scheduleUpdatedAt}` 作为幂等键；
  同一评估桶内重复触发会复用已创建的 Run。
- R2 结构演化复用 `cell_lineage` 表，无额外迁移。
- 前端新增路由 `#/lifecycle`；依赖仍是现有 React/Vite/TypeScript 栈。
- 验证命令：
  ```powershell
  python -m unittest platform.tests.test_lifecycle platform.tests.test_algorithm.ProductionAlgorithmTest.test_engine_creates_r2_structure -v
  cd frontend
  npm run build
  ```

### 3.2.1 M4.1 受控 R2 对账部署记录

- 无新增数据表、三方件或 embedding 模型。
- `GET /api/v1/runs/{runId}/lineage` 通过 SQL JOIN 补充新旧 cell 的
  `cellKey` 和 `size`。
- 前端新增 `#/runs/{runId}/lineage`，依赖现有 React/Vite/TypeScript 栈。
- 新增验证脚本：`platform/scripts/r2_lineage_validation.py`。
- 本地基准验收命令：
  ```powershell
  python platform/scripts/r2_lineage_validation.py --source benchmark --limit 40 --db platform/var/r2-lineage-validation.db
  ```
- 真实 Cloud v4 验收命令（需先配置 `LANGFUSE_PUBLIC_KEY` 与
  `LANGFUSE_SECRET_KEY`）：
  ```powershell
  python platform/scripts/r2_lineage_validation.py --source langfuse --profile cloud-v4 --project-name development_env --minutes 2880 --id-offset 400000000000 --id-count 1000
  ```
- 验收项：两个 R2 Run 成功、结构版本新增两个、第二个结构 active、
  第一个 Run 分数摘要不变、lineage 非空且 overlap 在 `(0, 1]`、
  kernel hash 不变。
- 本地基准实测（2026-11-13，40 条 R1 轨迹）：全部检查通过；
  生成 2 个结构版本、9 条 `continued` lineage，第一个 Run 分数摘要为
  `8034d5948a0b6bff80527971d60745ac5a7980648ee5ca4405d2742131d1e198`。
- 真实 Cloud v4 受控 R2 尝试在当前代理环境下读取 Langfuse 长时间无响应，
  已中断；与既有 M3 记录的 Cloud readback 网络问题一致，待网络恢复后执行。
- 真实 Cloud v4 复验通过（2026-11-13）：
  - `firstRunId=run-581704123cc249ee`
  - `secondRunId=run-991e8373bdf8442f`
  - `firstTraceCount=274`
  - `lineageEdgeCount=3`，全部为 `continued`
  - `firstScoreDigest=491ebf2a4a87f89bdfe9bbc33499b0fb0ec58f84a0881ac60b5a7c9025b9a5f4`
  - `structureVersionsBefore=7`，`structureVersionsAfter=9`
  - 全部检查项通过，`code_hash=2064664e6aa5fb46`
- 复验命令示例：
  ```powershell
  python platform/scripts/r2_lineage_validation.py --source langfuse --profile cloud-v4 --project-name development_env --window-start 2026-11-12T08:00:00Z --window-end 2026-11-12T09:30:00Z --id-offset 400000000000 --id-count 1000 --limit 1000 --page-size 100
  ```

### 3.3 M4.2 生命周期调度部署记录

- 新增数据表：
  - `scheduler_locks`：单实例租约锁，默认租约 120 秒。
  - `scheduler_scans`：每轮调度扫描审计与看门狗结果。
  建表语句在 `platform/contracts/schema.sql`。
- 新增配置文件：`platform/config/scheduler.yaml`。
  - `intervalSeconds=60`
  - `leaseSeconds=120`
  - `queuedTimeoutSeconds=900`
  - `runningTimeoutSeconds=86400`
- 无新增三方件、无 embedding 模型；调度器使用 Python 标准库线程。
- 启动命令：
  ```powershell
  python -m platform.app.cli --profile cloud-v4 --scheduler
  ```
  自托管环境可改为：
  ```powershell
  python -m platform.app.cli --profile selfhosted-v4 --base-url http://langfuse.internal --scheduler
  ```
- REST：
  - `GET /api/v1/scheduler/status`
  - `POST /api/v1/scheduler/evaluate-all`
- 前端路由复用 `#/lifecycle`，新增调度器状态与手动全量扫描入口。
- 验证：
  ```powershell
  python -m unittest platform.tests.test_scheduler -v
  cd frontend
  npm run build
  ```

### 3.4 M4.3 自动 R2 护栏部署记录

- 数据库变更：`lifecycle_schedules` 新增列
  `r2_min_novelty_traces INTEGER NOT NULL DEFAULT 50`。
  - 新库由 `platform/contracts/schema.sql` 创建。
  - 旧 SQLite 库在后端初始化连接时自动 `ALTER TABLE` 补列，默认值 50。
- 无新增数据表、无新增三方件、无 embedding 模型变更。
- 配置入口：
  - REST：`PUT /api/v1/ontologies/{id}/lifecycle` 的 `r2MinNoveltyTraces`。
  - 前端：生命周期页「R2 最小 novelty 轨迹数」。
- 该值表示自当前 active 结构生成后，成功 Run 中去重累计的 novelty 轨迹数
  门槛；0 表示关闭护栏。

### 3.5 M5.0 性能基线部署记录

- 新增脚本：`platform/scripts/performance_baseline.py`。
- 无新增数据库三方件、无新增数据表、无 embedding 模型变更。
- RunEngine 新增 `var_root` 参数；默认仍使用 `platform/var/runs`，生产行为不变。
- 压测临时文件位于 `platform/var/perf-*`，脚本结束后自动删除。
- 性能报告默认输出到 `platform/var/performance-baseline.json`，该目录已被
  `.gitignore` 忽略。
- 首轮实测与瓶颈分析见 `platform/M5_0_PERFORMANCE_BASELINE.md`。

### 3.6 M5.1 R2 抽样训练部署记录

- 配置文件：`platform/config/performance.yaml`。
  - `r2TrainingLimit: 0`：0 表示自动策略，正整数表示手动训练上限。
  - `r2AutoBudgetSeconds: 3600`：自动策略的 R2 耗时预算。
  - `r2FullCostPerTraceSeconds: 0.022` / `r2TrainingQuadraticCostSeconds: 0.020`：
    基于既有压测拟合的耗时估算系数。
- 生命周期配置表新增 `r2_training_limit` 字段，页面支持自动 / 手动两种模式。
- 自动策略在加载时间窗轨迹后决策：预计不超过 1 小时使用全量结构学习；
  超过预算则按剩余预算推荐训练样本数。全量轨迹仍使用冻结结构完成检测和评分。
- 无新增数据库三方件、无新增 embedding 模型变更。
- 10,000 条实测：R2 299.149s，R1 293.025s，SQLite 88,051,712 B，
  峰值内存 221,447,153 B。
- 100,000 条前仍需完成流式读取与分批持久化，避免一次性内存放大。

### 3.7 M5.2 流式评分部署记录

- `platform/config/performance.yaml` 新增：
  - `persistBatchSize: 500`
  - `scoreBatchSize: 1000`
- 无新增数据库表、无新增三方件、无 embedding 模型变更。
- RunEngine 直接流式写 `scores.jsonl`，数据库持久化按 `persistBatchSize`
  分批提交；Langfuse Score 回写改为迭代器消费。
- 实测 10,000 条峰值内存 197,650,611 B；100,000 条 R2 耗时
  4,560.980 s、峰值内存 1,934,930,761 B。
- 100,000 条内存未达 500 MB 目标，剩余瓶颈在内核 `detect_all` 全量
  `stage` 与 `feature_rows`；在“不改 kernel”的红线下无法继续压缩。

### 3.8 Project 轨迹配额部署记录

- `tenants` 表新增一列：
  - `max_traces_per_run INTEGER NOT NULL DEFAULT 100000`
- 旧 SQLite 库在后端初始化启动时自动 `ALTER TABLE` 补列。
- 配置入口：`platform/config/performance.yaml` 的
  `projectDefaultMaxTracesPerRun`。
- REST 入口：
  - `POST /api/v1/tenants` 可在注册时覆盖默认限额。
  - `PATCH /api/v1/tenants/{tenantId}/quota` 可更新限额。
- 无新增三方件、无 embedding 模型变更。
- 每日 Run 数与并发 Run 数限制暂不实现。

### 3.9 R3 本体升版部署记录

- 无新增数据表、无新增三方件、无 embedding 模型变更。
- 复用既有 `ontologies.current_version` 与 `ontology_versions` 表。
- REST 新增：
  - `GET /api/v1/ontologies/{id}/versions`
  - `POST /api/v1/ontologies/{id}/versions`
  - `POST /api/v1/ontologies/{id}/versions/{version}/activate`
- 发布写入不可变 `ontology_versions`；激活仅更新
  `ontologies.current_version`。
- 历史 Run 的 `ontology_version_id` 不迁移、不改写，新 Run 使用激活后的
  当前版本。
- 前端新增 `#/ontologies/{id}/versions` 页面。

### 3.10 生产接入控制台部署记录

- 新增后端源：`platform/app/langfuse_admin.py`。
  - `LangfuseAdminClient` 使用 Python 标准库访问
    `GET /api/public/health` 与 `GET /api/public/projects`。
  - 端点仍来自 `platform/config/endpoints.yaml`，后端源不写 URL 字面量。
- 后端启动时读取当前 profile 与 `.env` 中的平台 key，调用 health 接口，
  并把返回的 Langfuse server 版本写入 `startup_records.langfuse_version`。
  - 网络失败不阻塞服务启动；记录 `skipped=1` 与失败原因。
  - 当前 Cloud v4 实测返回 `4.81.0`。
- REST 新增：
  - `POST /api/v1/langfuse/connection/check`：校验 key 与 Project 归属。
  - `POST /api/v1/onboarding/register`：校验通过后原子创建租户、
    Tier 0 本体与本体 v1。
- 前端新增 `#/onboarding` 生产接入控制台：
  - 填写 Langfuse org/project/key 与本体信息。
  - 支持连接校验、注册、查看已接入业务、进入本体版本管理。
  - Run 发起页新增租户/本体选择、R1/R2/R3 类型选择、时间窗输入，
    并区分「基准数据集 R1~R8」与「Langfuse Run 标识」。
- 无新增数据库表、三方件或 embedding 模型；复用 `tenants`、
  `ontologies`、`ontology_versions`、`startup_records`。

### 3.11 轨迹门禁明细部署记录

- 数据库变更：`trace_scores` 新增可空列 `gates_json TEXT`。
  - 新库由 `platform/contracts/schema.sql` 创建。
  - 旧 SQLite 库在后端初始化连接时自动 `ALTER TABLE` 补列。
  - `gates_json` 记录内核硬门禁命中项与乘数，例如
    `{"loop_runaway": 0.35, "t1_unfinished": 0.25}`。
- 无新增数据表、无新增三方件、无 embedding 模型变更。
- REST：`GET /api/v1/runs/{runId}/traces/{traceId}` 新增返回
  `gates` 与 `gateDeduction`。
- 前端轨迹详情页新增「硬门禁命中明细」，逐项展示门禁、触发条件、
  乘数与累计 G。

## 4. M6.0 生产交付与验收闭环

### 4.1 一键初始化、升级与启动

- 数据库版本记录新增 `schema_migrations` 表：
  - `version INTEGER PRIMARY KEY`
  - `applied_at TEXT NOT NULL`
- 当前版本为 `9`；`init` 与 `upgrade` 都会执行幂等建表和补列迁移。
- DB 路径统一由 `TRAJ_DB_PATH` 或 CLI `--db` 控制；未配置时仍为
  `platform/var/traj-engine.db`，兼容既有部署。
- 首次部署：
  ```powershell
  python -m pip install -r requirements.txt
  python -m platform.app.cli init --db platform/var/traj-engine.db
  python -m platform.app.cli run --profile cloud-v4 --db platform/var/traj-engine.db --scheduler
  ```
  自托管 v4 替换 profile 并配置 base URL：
  ```powershell
  python -m platform.app.cli run --profile selfhosted-v4 --base-url http://langfuse.internal --db platform/var/traj-engine.db --scheduler
  ```
- 版本升级：
  ```powershell
  python -m platform.app.cli upgrade --db platform/var/traj-engine.db
  ```
  应用包升级后先执行 `upgrade`，再重启服务；旧命令
  `python -m platform.app.cli --profile ...` 保持兼容并等价于 `run`。

### 4.2 前端构建与静态资源部署

- 构建版本：Node.js `>=24 <25`，锁文件 `frontend/package-lock.json`。
  ```powershell
  npm --prefix frontend ci
  npm --prefix frontend run build
  ```
- 产物：`frontend/dist`；将整个目录发布到静态服务器。
- 后端本身也内置 SPA 静态资源回退：启动 `platform.app.service` 后，
  `/` 与非 API 路径会读取 `frontend/dist/index.html`，`/assets/...`
  会返回对应静态文件。内网试点可直接使用单进程模式。
- 反向代理需把 `/api/` 转发到后端，其余路径回退到 `index.html`。
  Nginx 示例：
  ```nginx
  server {
    listen 80;
    root /opt/traj-engine/frontend/dist;

    location /api/ {
      proxy_pass http://127.0.0.1:8000/api/;
      proxy_set_header Host $host;
      proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }

    location / {
      try_files $uri /index.html;
    }
  }
  ```

### 4.3 部署后冒烟验收

- 后端启动后执行：
  ```powershell
  python -m platform.app.cli smoke --base-url http://127.0.0.1:8000 --expected-profile cloud-v4
  ```
- 冒烟覆盖：
  - `GET /api/v1/health`
  - `GET /api/v1/config/profile`
  - `GET /api/v1/startup-records/current`
  - `GET /api/v1/tenants?limit=1`
  - `GET /api/v1/ontologies?limit=1`
- 该脚本只验证平台本地契约，不访问 Langfuse，也不要求业务 key。
  真实数据链路仍使用既有 `langfuse_production_smoke.py`。

### 4.4 升级与回滚

- 升级前备份：
  ```powershell
  Copy-Item platform/var/traj-engine.db platform/var/traj-engine.db.bak
  ```
- 回滚步骤：
  1. 停止后端进程与调度器。
  2. 恢复应用包到上一个发布标签。
  3. 恢复 `traj-engine.db.bak`。
  4. 启动后端并重跑 `smoke`。
- `cohort_runs`、`trace_scores`、`ontology_versions`、
  `structure_versions` 均按不可变历史记录设计；普通应用升级不回写历史
  分数。若未来迁移发生存储格式变更，必须新增映射表并保留原记录。

### 4.5 待补充清单

- [ ] PostgreSQL 迁移脚本（首版明确不做）
- [ ] Embedding 模型清单与版本记录（当前无 embedding）
- [ ] 认证与租户凭据加密（首版明确不做）

### 4.6 M6.1 发布包构建与完整性校验

- 发布前必须先构建前端：
  ```powershell
  npm --prefix frontend run build
  python -m unittest discover -s platform/tests -v
  ```
- 构建发布包：
  ```powershell
  python -m platform.app.cli release --version 0.1.0
  ```
  默认输出 `platform/var/releases/traj-engine-0.1.0.zip`。包内包含：
  - 后端源代码、脚本、DDL、OpenAPI 契约与配置模板
  - `bench/`、`kernel/` 与 `ontology/` 源代码
  - `frontend/dist/` 静态构建产物
  - `DEPLOYMENT.md` 与 `USAGE_GUIDE.md`
  - `release-manifest.json`：发布版本、Git commit、schema 版本、内核
    `code_hash`、每个文件的 size 与 SHA256
- 发布包不包含 `.env`、`node_modules`、`platform/var`、真实租户档案和
  240 MB 基准数据集，避免凭据、运行数据与不必要的体积进入内网包。
- 交付后校验：
  ```powershell
  python -m platform.app.cli release-verify --package platform/var/releases/traj-engine-0.1.0.zip --expected-kernel-code-hash 2064664e6aa5fb46
  ```
  校验会检查 zip 完整性、manifest 格式、文件清单、逐文件 size 与 SHA256，
  并可比对内核 `code_hash`。
- 无新增数据库表、无新增三方件、无 embedding 模型变更。

### 4.7 M6.2 发布包离线验收

- 新增脚本：
  ```powershell
  python platform/scripts/release_acceptance.py `
    --package platform/var/releases/traj-engine-0.1.0.zip `
    --work-dir platform/var/release-acceptance `
    --profile cloud-v4 `
    --port 18080
  ```
- 验收步骤：
  1. 先执行 `release-verify` 校验包完整性。
  2. 解压到空的 `--work-dir`。
  3. 在解压目录内执行 `init` 创建 SQLite。
  4. 在解压目录内启动 `run`，只使用包内代码与配置。
  5. 等待 `/api/v1/health` 返回 `ok`。
  6. 调用包内 `smoke` 并校验 profile。
  7. 停止临时服务并输出 JSON 结果。
- 默认使用当前 Python 环境，适合 CI 和快速验收。内网首次部署可加
  `--create-venv`，脚本会在解压目录创建 `.venv` 并安装包内
  `requirements.txt`；如内网无法访问公网 PyPI，需预先提供内部镜像。
- `--work-dir` 必须为空目录，避免把历史运行数据误当作本次验收结果。
- 验收不访问 Langfuse，不需要业务 key；真实数据链路仍用
  `langfuse_production_smoke.py`。
- 无新增数据库表、无新增三方件、无 embedding 模型变更。

### 4.8 M6.3 单进程前端托管与验收

- 启动命令与后端一致，无需额外静态服务器：
  ```powershell
  python -m platform.app.cli run --profile cloud-v4 --port 8000
  ```
- 访问 `http://127.0.0.1:8000/` 即为前端页面；`/api/` 仍由同一 FastAPI
  服务处理。前端刷新或访问前端路由时回退到 `index.html`，静态资源按文件返回。
- 该模式适合内网试点、演示和小规模部署。多实例或需要独立缓存时，可继续
  使用 4.2 的 Nginx 分离部署模式。
- 离线验收在 M6.2 基础上新增前端检查：
  1. `GET /` 必须返回非空 `text/html`。
  2. 解析 `index.html` 中的本地 `src` / `href` 引用。
  3. 逐个请求静态资源并要求返回成功。
- 隔离环境验收命令：
  ```powershell
  python platform/scripts/release_acceptance.py `
    --package platform/var/releases/traj-engine-0.1.0.zip `
    --work-dir platform/var/release-acceptance `
    --create-venv
  ```
- 该阶段无新增数据库表、无新增三方件、无 embedding 模型变更。

## 5. M0 契约验证

```powershell
python -c "import yaml; yaml.safe_load(open('platform/contracts/openapi.yaml', encoding='utf-8'))"
python -c "import sqlite3, pathlib; con=sqlite3.connect(':memory:'); con.executescript(pathlib.Path('platform/contracts/schema.sql').read_text(encoding='utf-8'))"
```


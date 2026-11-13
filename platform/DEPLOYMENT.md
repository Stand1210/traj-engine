# 内网部署记录（活文档）

> 状态：随工程开发持续补充，不在当前阶段一次性编写完整部署手册。
> 目标：当平台进入内网部署时，本文能回答「需要哪些组件、哪些版本、如何初始化数据、如何启动、如何验证」。

## 1. 部署范围

| 项 | 首版决策 | 记录状态 |
|---|---|---|
| Langfuse | Cloud v4 或自托管 v4 | 已定；自托管 v3 延后 |
| 平后端 | FastAPI `0.115.6` + Uvicorn `0.34.0` | M1 最小闭环已实现 |
| 前端 | Node.js `24.x` + Vite `6.0.7` + React `18.3.1` + ECharts `5.6.0` | M1 最小闭环已实现 |
| 数据库 | SQLite（内置于 Python 3.11） | 当前契约：20 张表 |
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
  python -m platform.app.cli --profile selfhosted-v4 --base-url http://langfuse.internal
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
- M1 已验证：
  - 5 个 YAML 契约解析通过
  - SQLite DDL 建表 20 张通过
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

## 4. 待补充清单

- [ ] Node.js 版本与前端依赖锁文件
- [ ] SQLite 初始化命令与 PostgreSQL 迁移脚本
- [ ] Embedding 模型清单与版本记录
- [ ] 后端启动命令与配置文件
- [ ] 前端构建与静态资源部署
- [ ] 部署后验收命令

## 5. M0 契约验证

```powershell
python -c "import yaml; yaml.safe_load(open('platform/contracts/openapi.yaml', encoding='utf-8'))"
python -c "import sqlite3, pathlib; con=sqlite3.connect(':memory:'); con.executescript(pathlib.Path('platform/contracts/schema.sql').read_text(encoding='utf-8'))"
```


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

## 3. M1 纵向闭环

- 后端：已实现 `JsonlTraceSource`、作业状态机、算法执行壳、结果存储、REST 最小子集。
- 前端：已实现 F0/F2/F3/F4/F5 的最小版本。
- 数据：读取 `data/bench_v1/`，注册为平台内部租户。
- 验收：
  1. 基准 scorecard 位级复现。
  2. Run 生命周期可追踪。
  3. 零残差证据链可三步下钻。
  4. R1 只做冻结结构下的贴标签与基线刷新，不允许每天触发结构重聚类。
  当前状态：第 1~3 条已通过；第 4 条尚未完成，当前 M1 每次算法 Run 会生成新的
  `structure_version`，冻结结构复用将在 M4 统一实现。

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
  两种响应均已按合法成功处理。Tier 0 YAML 合成与真实 Project 首跑尚未开始。

## 5. M3 运营闭环

- 使用 `POST /api/public/scores` 写回租户 project。
- 复用 Langfuse 原生标注队列做人工复核。
- 实现告警预算与 top-K 排序。
- 复核标签回流触发校准。

## 6. M4 生命周期

- R1：每日基线刷新，cell 定义不变。
- R2：结构重聚类，受 novelty、drift、instability、冷启动与业务声明触发。
- R3：本体升版，由业务规则变更触发。
- R2 后必须记录 lineage、重置 drift、重拟合校准并显式标注盲区。

## 7. M5 多租户与硬化

- 多租户配额与隔离。
- 10 万条/天压测。
- SQLite → PostgreSQL 切换评估。
- 失败恢复、重试、幂等与运维告警。

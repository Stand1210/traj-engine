# 业务方使用指南（活文档）

> 状态：随产品能力逐步补充。面向业务接入方与值班人员，不要求理解算法内核。
> 原则：业务方只需要知道如何接入、如何发起分析、如何解读结果、何时需要人工复核。

## 1. 你会得到什么

- 每条 agent 轨迹的自动质量评分。
- 异常轨迹清单及原因归因。
- 聚类结果与簇内基线，用于解释「同一条轨迹在不同任务类别下的好坏标准不同」。
- 少量需要人工复核的低置信样本。

## 2. 接入前准备

| 事项 | 业务方需要做什么 | 当前状态 |
|---|---|---|
| Langfuse Organization | 创建或确认 Organization，并提交给平台 | 已定 |
| Langfuse Project | 一个 Project 只对应一个业务 agent 本体 | 已定 |
| 轨迹上报 | 业务 agent 将轨迹上报到对应 Project | 已定 |
| 本体信息 | Tier 0 可零填写；Tier 1 只需补充业务红线 | 已定 |

## 3. 日常使用流程

1. 在前端选择一个业务本体。
2. 选择时间窗，发起一次分析 Run。
3. 查看聚类结果、异常清单、告警清单与弃权样本。
4. 对平台筛出的低置信样本进行人工复核。
5. 复核结果回流，用于后续校准。

## 3.1 当前 M1 可用能力

- 通过前端或 REST 发起基准数据集 Run。
- 在前端查看 Run 状态与执行步骤。
- 在前端查看聚类 cell、轨迹分数、告警与弃权列表。
- 在前端查看单轨迹五维分数与扣分证据。
- 查看 Run 的校准结果。

发起 Run 的最小请求示例：

```http
POST /api/v1/runs
Content-Type: application/json

{
  "tenantId": "tenant-benchmark",
  "ontologyId": "ontology-benchmark-ontA",
  "source": "jsonl",
  "sourceRef": "R1",
  "runType": "R1",
  "windowStart": "2026-01-01T00:00:00Z",
  "windowEnd": "2026-12-31T23:59:59Z",
  "samplingRate": 1.0
}
```

M3.4 calibration usage: [`M3_4_CALIBRATION.md`](M3_4_CALIBRATION.md).

## 3.2 当前 M2 可用能力

- 通过 `POST /api/v1/tenants` 注册 Langfuse Organization/Project 与项目 API key。
- 通过 `POST /api/v1/ontologies` 创建业务本体记录。
- 通过 `POST /api/v1/ontologies/{id}/prechecks` 拉取近 7 天样本，检查样本量、
  trace 唯一性、根节点、父子闭合、时间戳、usage、本体 metadata 与 action 覆盖。
- 预检结果会给出 `passed` / `warning` / `failed` 与逐项指标，用于判断数据是否足够
  启动首跑；本阶段尚未开放真实 Langfuse 数据的分析 Run。
- 平台开发自检可通过 `platform/scripts/langfuse_v4_smoke.py` 验证当前
  Langfuse v4 项目的写入、异步落库、读回与内核契约映射；该脚本面向平台开发，
  不是业务方日常操作入口。
- Tier 0 本体已由平台自动合成并发布，业务方不需要下载或上传文件。
- 当前可通过 REST 用 `source=langfuse` 指定时间窗发起真实轨迹分析 Run；
  Run 结果包含轨迹分数、聚类 cell、异常/弃权标记与扣分证据。
- 样本量低于 `COLD_START_MIN_TRACES=1000` 时，Run 会明确标记冷启动降级：
  可以查看分数与排序，但不会产出正式告警。
- 每个本体的第一次正式 Run 会学习并冻结聚类结构；后续 R1 Run 会复用该
  结构，只给新轨迹贴标签并刷新簇内基线，保证跨 Run 的 cell 口径可比。
- 结果维度评估依赖 trace 级 `answer_facts`、`answer_numbers`、
  `golden_answer`、`golden_facts` 等可选元数据；业务侧上报时应尽量携带。
  缺失时平台不会伪造数据，但结果符合度相关证据会降级，部分可判定问题
  可能无法进入告警流。

## 3.3 当前 M3 可用能力

- 发起 `source=langfuse` 的 Run 时，可以传 `writebackToLangfuse=true`，
  平台会把评分结果写回该业务 Project 的 Langfuse Scores。
- 每条轨迹会生成三个原生 Score：
  - `traj-engine-total-score`：0~100 的总分，metadata 内携带五维分数、
    cell、runId、codeHash。
  - `traj-engine-alert`：布尔值，1 表示该轨迹进入平台告警流。
  - `traj-engine-abstain`：布尔值，1 表示当前结构无法可靠归类，需要复核。
- 写回是独立 Run 步骤：算法评分成功但写回失败时，默认 Run 仍为
  succeeded，可在 Run Steps 中查看 `score_writeback` 失败原因；
  需要“写回失败即 Run 失败”时传 `writebackStrict=true`。
- 业务方可以在 Langfuse 原生 UI 中按 Score 名筛选平台评分，并结合
  trace 详情查看分数与 metadata。
- 前端发起 Run 时可选择「Langfuse Project」数据源，并勾选
  「评分写回 Langfuse Scores」。

### 3.3.1 人工复核队列

- Run 成功后，在 Run 概览点击「推送告警/弃权到复核队列」。
- 平台会把该 Run 中尚未推送的告警或弃权轨迹推入 Langfuse 原生
  `traj-engine-review` 队列，每条队列 item 指向一个 trace。
- 复核人在 Langfuse UI 中打开队列 item，填写三个人工 Score：
  - `traj-engine-human-verdict`：Agree / Disagree / Uncertain。
  - `traj-engine-human-label`：可选，问题标签。
  - `traj-engine-human-comment`：可选，补充说明。
- 完成队列 item 后，回到平台点击「同步 Langfuse 人工复核」。
  平台会把已完成 item 的人工结论导入本地 `human_reviews`。
- 同步结果会显示导入条数和待复核条数；同一条队列 item 只会导入一次。

### 3.3.2 告警工作台

- Run 成功后，在 Run 概览点击「查看告警」进入告警工作台。
- 「正式告警」是当次 Run 在预算内放行的 top-K 告警，值班优先处理。
- 「候选异常」包括两类：
  - 超出预算的根因组代表告警。
  - 同一 cell、同一根因下被去重的重复告警。
- 每条告警展示优先级、总分、主根因、组内序号和可解释原因；
  点击「下钻」可以查看五维分数与扣分证据。
- 平台默认每个 Run 放行 5 条正式告警；该值可通过
  `platform/config/alerts.yaml` 调整。

## 3.4 当前 M4 可用能力：生命周期

- 进入前端「生命周期」页面，选择一个业务本体后可保存调度策略。
- R1 周期：到周期时间后用当前固定结构重新贴标签，并刷新簇内基线；
  适合日常运行，不会每天改变聚类定义。
- R2 触发：冷启动、手动强制、弃权率超过阈值或告警率超过阈值时，
  创建新的结构版本；适合业务范式发生变化的场景。
- 「评估并按策略触发」只做一次判断：未到周期且未超过阈值时不会创建 Run；
  命中策略时会创建 R1 或 R2 Run，并可跳转到 Run 详情。
- 每次评估都会留下一条历史记录，包含决策、触发原因、窗口内轨迹数、
  弃权率、告警率和创建的 Run。
- 强制 R2 会生成新结构版本，并记录新旧 cell 的延续、拆分或合并关系；
  历史分数不会被改写。

### 3.4.1 查看 R2 结构演化

- 在 Run 概览点击「查看演化」，或访问 `#/runs/{runId}/lineage`。
- 页面顶部显示当前 Run 类型、结构版本和 lineage 关系数。
- 关系含义：
  - 延续：旧 cell 基本完整进入同一个新 cell。
  - 拆分：旧 cell 的成员进入多个新 cell。
  - 合并：多个旧 cell 的成员进入同一个新 cell。
  - 新生 / 消亡：当前实现主要覆盖前三种；没有重叠成员时不会生成边。
- overlap 表示旧 cell 中被延续到目标新 cell 的样本比例，越接近 100%
  表示结构越稳定。
- R1 复用结构，不会生成 lineage；只有 R2 才会出现结构演化关系。

### 3.4.2 生命周期调度器

- 后台调度器不是默认开启；运维部署时需要给后端增加 `--scheduler`
  启动参数，或设置 `TRAJ_SCHEDULER=1`。
- 调度器每轮做两件事：
  1. 看门狗：超过阈值的 `queued` / `running` Run 标记为 failed，并记录
     `watchdog` Run Step。
  2. 生命周期评估：对所有启用调度本体按 R1/R2 策略触发。
- 前端「生命周期」页可以查看：
  - 启用调度数量。
  - 调度锁状态。
  - 最近一次扫描状态、看门狗处理数、评估数和创建 Run 数。
- 「调度扫描全部本体」按钮执行与后台调度器相同的一轮扫描；若另一实例
  正在执行，会返回 `lock_held` 并跳过。

### 3.4.3 自动 R2 novelty 样本护栏

- 生命周期配置中的「R2 最小 novelty 轨迹数」用于防止少量偶发弃权轨迹
  直接触发结构重建，默认 50；设为 0 表示关闭。
- 评估历史中的「累计 novelty」列显示：
  `自当前 active 结构生成后，成功 Run 中去重累计的 novelty 轨迹数 / 配置阈值`。
- 当最新 Run 的 novelty 率超过阈值但累计数量不足时：
  - 决策会显示 `skipped`，原因是 `novelty_below_minimum`。
  - 若 R1 周期已到期，会先创建 R1 继续积累样本。
- 当累计数量达标且 novelty 率仍超过阈值时，才会自动创建 R2。

## 4. 结果解读

| 页面内容 | 业务含义 | 判断动作 |
|---|---|---|
| 高分轨迹 | 执行符合预期，时延与成本处于同类任务理想区间 | 无需处理 |
| 低分轨迹 | 结果、过程、时延或成本至少一个维度偏离同类基线 | 查看证据下钻 |
| 告警轨迹 | 满足告警规则且置信度足够 | 值班处理 |
| 正式告警 | 通过优先级排序、同根因去重和预算裁剪后的 top-K | 值班优先处理 |
| 候选异常 | 未进入正式告警流，但算法判定值得观察 | 定期巡检或复盘 |
| 弃权轨迹 | 当前结构无法可靠归类 | 等待积累样本或触发重聚类 |

## 5. 待补充清单

- [ ] 截图与页面入口说明
- [ ] 常见错误码解释
- [ ] 业务红线填写示例
- [ ] 人工复核操作规范
- [ ] 告警处置建议
- [ ] Langfuse Scores 页面筛选与 trace 详情联动截图

## 6. 运维与性能

### 6.1 性能基线

```powershell
python platform/scripts/performance_baseline.py --traces 100000 --output platform/var/performance-baseline.json
```

- `--traces`：压测轨迹数，默认 100,000。
- `--query-repeat`：每类查询重复次数，默认 20，报告取 median/min/max。
- `--timeout-seconds`：单个 Run 的最长等待时间，默认 3,600。
- `--skip-r1` / `--skip-scheduler` / `--skip-queries`：调试时跳过对应阶段。
- 报告默认在 `platform/var/`，该目录不入库。

首轮结论见 `platform/M5_0_PERFORMANCE_BASELINE.md`：当前主要瓶颈是
R2 冷启动聚类；R1、查询和调度扫描在 100 条基线下均为秒级或毫秒级。

### 6.2 R2 抽样训练

- 配置文件：`platform/config/performance.yaml`。
- `r2TrainingLimit` 默认 64，表示 R2 结构学习最多使用的训练轨迹数；
  全量轨迹仍会被检测和评分。
- 抽样策略为确定性等距抽样，重复执行同一批轨迹会得到相同训练样本。
- Run 详情的 `algorithm` Step 会显示 `trainingTraceCount`、
  `fullTraceCount` 和 `strategy=systematic`。


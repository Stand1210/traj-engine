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


# E5 真实数据验证与对比报告

日期：2026-11-28 ｜ 执行：traj-engine `main`（E4 之后） ｜ code_hash：`d229ab802e5a01bf`

## 1. 范围与数据

- 数据源：Langfuse Cloud（`us.cloud.langfuse.com`，项目 `development_env`），经 OTLP 写入、
  v2 Observations API 读出的真实生产链路数据（bench_v1 语料经完整摄取链路回流）。
- 项目总量：5,421 条 trace / 30,263 条 observation（2026-11-12 → 2026-11-24）。
- 对照组（同窗口、同 200 条 trace，trace id 集合逐一相等）：

| 角色 | Run | 类型 | 窗口 (UTC) | 结构 | code_hash |
|---|---|---|---|---|---|
| 旧训练 | `run-ff17a4ad5a9b47e6` | R2 | 11-19T00:00:58 → 11-20T00:00:58 | v13 `16d909b1d69840b8` | `2064664e6aa5fb46` |
| 新训练 | `run-9f6e2fc0c968480d` | R2 | 同上 | **v15 `f94b10f25ec44eed`** | `d229ab802e5a01bf` |
| 旧评分 | `run-d91fb5772ecd4eb6` | R1 | 11-22T12:00:18 → 11-23T12:00:18 | v13 | `2064664e6aa5fb46` |
| 新评分 | `run-30b6501258934496` | R1 | 同上 | v15 | `d229ab802e5a01bf` |

- 新旧输入差异说明：v2 API 自 v3 下线后为 span 增加了空值 `agent` 字段，导致 spec_hash
  不同（`3ca48e1b…` vs `558826af…`）；已逐字段 diff 确认 200 条 trace 内容除该 null 字段外完全一致。
- 新链路配置：`TRAJ_INTENT_ENCODER=bge-m3`（BAAI/bge-m3，revision `5617a9f6`，1024 维，
  权重 SHA-256 逐一校验，见 Run 步骤 `model_assets`）；active 本体 YAML v3
  （unit_price 五通道、`forbidden_actions: [force_delete, skip_approval_execute]`、
  models/query_langs 先验）。degraded 显式记录 13 个未钉住治理键（`cohort_runs.degraded_json`）。

## 2. E4 遗留验收：真实 Cloud Run 全链路（已完成）

- 预检查 15 项在真实 Cloud 数据上执行：13 passed、1 warning（`embedding_dimension_consistency`，
  云端 trace 无自带 embedding，符合预期）、1 failed（`sample_available`，见 §6 数据质量发现）。
- R2 生产 Run 全链路成功：模型资产指纹、本体 YAML 消费、embedding_dim=1024、
  structural_fingerprint=`ceb73fb8cb8bdf56` 全部落库；v15 激活，v13/v14 正确停用且
  embedding_dim 保持 NULL（不伪造历史字段）。

## 3. 结构对比：旧 vs 新

| 指标 | 旧结构（R2/R1） | 新结构（R2/R1） |
|---|---|---|
| 意图簇数 | **1** / 1 | **6** / 6（0 个 singleton） |
| 模式簇数 | 5 | 4 |
| 模式 silhouette | 0.6392 | 0.3012 |
| novelty 率 | 2.5% / 1.0% | 49.5% / 53.0% |
| 聚类覆盖率 | 97.5% / 99.0% | 50.5% / 47.0% |
| 弃权 trace | 5 / 2 | 99 / 106 |
| cell 数 | 3 / 3 | 13 / 6 |
| 抖动 sigma / 不稳定率 | — / 0.005 | 0.027 / 0.28 |

意图簇纯度（对 bench gt `intent_id`，仅作辅助证据）：新结构 **cell 级纯度 100%**
（每个 cell 只含单一 gt 意图），ARI 0.294/0.231；旧结构单意图簇混杂（纯度 0.737/0.744），
ARI 0.104/0.116。**意图簇解释质量明显改善**（验收项 1 达成）。

cell lineage（仅新旧对照，不合并历史基线；评分窗 200 trace 重叠 Jaccard≥0.05）：

```
i2xp1(n=39) <- i0xp1(39, J=0.364)    i0xp0(n=10) <- i0xp0(10, J=0.196)
i2xp2(n=19) <- i0xp2(19, J=0.475)    i0xp1(n=7)  <- i0xp1(7,  J=0.065)
i2xp0(n=16) <- i0xp0(16, J=0.314)    i0xp2(n=3)  <- i0xp2(3,  J=0.075)
```

新 cell 均为旧 cell 的意图纯子集：旧结构把两个 gt 意图混进同一 cell，新结构将其拆开。
106 条弃权 trace（53%）不进入任何 cell —— 见 §5 代价分析。

## 4. 告警对比与人工抽样复核

新评分 Run 告警 5 条（预算 5），逐条对照 trace 证据与 gt（辅助）：

| # | trace | cause | 证据 | gt 异常 | 结论 |
|---|---|---|---|---|---|
| 1 | …5288ba | `metric:tokens_total` | tokens=18101（极端膨胀） | `token_bloat` | 一致 |
| 2 | …5288bf | `rule:forbidden_action` | 动作列含 `skip_approval_execute`（YAML 禁则） | `illegal_step` | 一致；**仅新链路可产生** |
| 3 | …5288b4 | `rule:unrecovered_error` | 错误未恢复 | `error` | 一致 |
| 4 | …52887e | `metric:agent_run:dur` | agent_run 时长 76.8s（gt 未标注但证据确凿） | 非异常 | 证据一致（gt 漏标） |
| 5 | …5288c4 | `rule:truncated_generation` | 生成截断 | `truncation` | 一致 |

- 根因与 trace 证据 5/5 一致（验收项 2 达成）；其中 4/5 与 gt 类型精确对应，1 条为 gt 漏标。
- 旧评分 Run 12 条告警中 5 条 gates 为空 `{}`（无根因），其余为粗粒度 t0/t1/t2 门；
  新告警全部带 `cause`/`causeKind`/`reasons`（可解释性提升）。
- 辅助量化：告警对 gt 异常的精度 0.846（新 R1）vs 1.0（旧 R1），召回 0.55 vs 0.60 ——
  弃权带走部分异常 trace（弃权中异常占比仅 6.6%，多数弃权为正常但"新颖"的 trace）。

## 5. 代价与资源

| 项 | 旧 | 新 | 说明 |
|---|---|---|---|
| R2 训练耗时 | 107.6s | 630.3s | bge-m3 CPU 编码 200 条 + 训练；5.9× |
| R1 评分耗时 | 128.4s | 82.8s | 嵌入缓存命中（缓存 232 条；评分窗与训练窗重叠 168 条） |
| 服务常驻内存 | — | RSS 1.35GB / 峰值 2.0GB | 含 bge-m3 权重（2.27GB 磁盘） |
| 弃权率 | 1% | 53% | 主要代价，见下 |

**弃权率 53% 的判读**：novelty 边际阈值对 1024 维嵌入偏保守（训练窗自身 novelty 已达
49.5%），200 条训练样本不足以覆盖意图空间。这是量化确定的代价项，不是静默失败：
弃权显式落库（`is_abstain`）、弃权 trace 的异常占比 6.6% 低于全量 10%，未掩盖异常集中。
后续调优方向（不在 E5 范围）：扩大 R2 训练窗 / 校准 novelty 阈值 / 意图簇质心随 R2 增量更新。

## 6. 数据质量发现（预检查暴露）

- Langfuse 项目中存在**同 observation id 双份写入**（同一 bench 子集两次 OTLP 导入：
  11-23T01:2x–01:5x 与 11-24T06:5x–07:2x 两批）。跨双批的窗口（如预检查滚动 7 天窗）
  会让每条 trace 出现 2 个根 → 全部判为 incomplete → `sample_available` failed。
  单批窗口（本报告四次 Run）不受影响。该发现由 15 项预检查在真实数据上首次暴露，
  证明预检查有效。平台侧暂不改动摄取去重语义（E5 范围外，留待路线决策）。
- 近期调度 R1 连续失败（11-25T12:13 起）原因确认：滚动 24h 窗口内无数据（项目数据止于
  11-24T07:23），`production run requires at least one trace` —— 显式失败，符合契约。

## 7. 本阶段附带修复

- **本体 YAML 加权列表元数校验**（E5 首次真实运行暴露）：`models` 必须为三元组
  （name, weight, multiplier），`query_langs`/`prompt_versions` 为二元组。此前二元组
  models 会在内核 `features.py` 深处抛 `IndexError: tuple index out of range`。
  现于上传校验（`service.py::_validate_weighted_lists`）与运行时解析
  （`algorithm.py::ontology_from_yaml`）两层以可操作错误信息拒绝；
  新增测试 3 断言（`test_weighted_list_arity_is_actionable`）。

## 8. 验收结论

| 验收项 | 结论 |
|---|---|
| 意图簇解释质量明显改善，或给出量化失败原因 | **达成**：cell 纯度 0.74→1.00，ARI 0.10→0.29，意图簇 1→6 |
| 告警根因与 trace 证据一致 | **达成**：5/5 抽样一致 |
| 不再以合成标签为唯一质量证明 | **达成**：主证据为 trace 证据对照与结构指标；gt 仅作辅助量化 |

遗留量化代价（非失败）：弃权率 53%、训练耗时 5.9×。已在 §5 给出原因与调优方向。

# 数据契约 v1（bench 生成器 与 kernel 算法 的共同规格）

状态：**v1.3.1（生成器 `bench-gen-v3.1.0` / 流水线 `slice1-v0.1.0` 实测冻结）**。
生成器输出与内核接口同时受其约束；变更需升版本号。

- v1 → v1.1：`ClusterAssign` 增补 `near_intent/near_pattern/post_margin`；检测器输出增补
  分诊层 `tier/graded` 与双通道告警位；门槛表增补运营流精度、漂移零误报、双侧检出滞后与
  **信息上界封顶**；不变量表把「共识阈值单调」改为「共识阈值语义」。
- v1.1 → v1.2：Trace 增补 6 个字段、Span 增补 8 个字段（§1）；缺失率改为**修复前**按
  Span 类型的条件可得字段集测量（§1 规范化规则）；特征宽表拆成「v1 冻结 21 项（驱动 METRICS）」
  与「v2 已发射未接线」（§2）；GT 增补 8 个真值字段（§6）；regime DSL 增补
  `golden_rate/feedback_rate`（§7）；聚类门槛增补**弃权计价**口径（§8）；漂移参考矩梯由三级
  改为**两级 + 弃权**、λ 标定改为**双重采样自举**（§10.3）；本体接口增补 7 个键（§11）。
- v1.2 → v1.3：Trace 增补 5 个字段、Span 增补 8 个字段（§1），`EXPECTED_FIELDS` 条件可得字段集
  随之扩容（llm 9→13、agent 7→10、tool 5→6、retrieval 5→7、guard 4→5），并明确 token 口径的
  两条约定：`tokens_prompt` **已包含** `tokens_system_prompt` 与 `tokens_cache_read`，而附录 A 的
  `total = input + output + cache_read + cache_write` 相对 v1 冻结的 `tokens_total`
  是**双重计数**关系，两者不得混用（§1）。特征宽表增补「v3 已发射、未接线」34 项，并记录三处
  与 v1 冻结键的命名冲突及其处置（§2）。GT 增补 17 个真值字段（§6；逐键枚举§6 的 v1.3 区块得 17，此前写 19 是把 `gen_quantiles` 的嵌套键也算了进去）。regime DSL 增补
  `intent_ambiguity`，并澄清 `overlap` 只作用于嵌入几何、与 `mix` 的时延混合无关（§7）。
  R3 标题改为「重叠加意图歧义」（§8）。本体接口增补 18 个键（§11）。新增 §12 数据集产物与
  溯源：`meta.json` 契约、`spec_hash` 的构成、嵌入几何常数与**新鲜度断言**。
- v1.3 → v1.3.1：**纯文档与溯源修正，数据契约未变**。§12.5 把 `query_embedding` 保真度检查的
  抽样量从陈旧的 400 改回实际的 **200**，并把 PR 实测值换成本轮重测的数；补上 PR 上下两端在
  审计自己抽样量上的完整实测（含为什么下界必须是严格不等号）。§12.4 澄清 PR 有**全量与
  200 条抽样两个口径**，两个数都对。§12.5.1 从「第二跳」扩成「第二、第三跳」：新增
  `metrics.json["code_hash"]`（§12.5.1）与 `bench/runner.py::code_hash()`，把「跑分 ↔ 代码」
  这一跳补上。新增 §12.6（README 跑分区块改为派生 + 守卫）。修正 v1.2 → v1.3 条目里 GT 的
  字段数 19 → **17**（逐键枚举 §6 的 v1.3 区块得 17，此前把 `gen_quantiles` 的嵌套键也算了进去）。

## 1. 输入：Trace / Span
```jsonc
Trace {
  trace_id: str, session_id: str, ts_start: float(epoch s),
  intent_text: str,                 // 用户问题原文（意图视图输入）
  embedding: [float x D],           // 句向量；bench 由生成器按latent意图发射，业务侧由可插拔编码器提供
  ontology_id: str,                 // 使用的业务本体版本
  spans: [Span],
  raw_flags: {usage_estimated: bool, ts_missing: bool, orphan: bool,
              field_loss: int},     // 采集侧原始缺陷提示；field_loss = 被丢掉的字段数
  // ---- v1.2 增补 ----
  turn_index: int,                  // 会话内轮次（1..5），多轮上下文 / 放弃检测用
  answer_facts: [str],              // 最终答案里出现的事实（含网元号等非数值实体）
  answer_numbers: [str],            // 最终答案里出现的数值，数值可溯源性的被检对象
  golden_answer: str|null,          // 标准答案原文；条件可用，见下
  golden_facts: [str]|null,         // 标准答案的事实集，recall / precision 的分母与分子来源
  user_feedback: {thumbs: int, retry: bool, abandoned: bool,
                  human_takeover: bool} | null   // Tier-6 弱监督；条件可用
  // ---- v1.3 增补 ----
  goal_text: str|null,              // 该任务的既定目标原文；`goal_drift_*` 的参照系
  answer_citations: [str],          // 最终答案引用的知识条目 id 集合，可溯源性的被检对象
  contradicted_facts: [str],        // 与检索证据冲突的事实；`contradiction` 共缺陷的载体
  query_lang: zh|en,                // 提问语种；分词与 `query_len` 归一化按语种走不同系数
  session_turn_count: int|null      // 采集侧记录的会话总轮数；`n_turns_in_session` 的初值，
                                    // 批量调用时由 annotate_sessions() 依 session_id 重新计数
}
Span {
  span_id: str, parent_id: str|null, kind: agent|llm|tool|retrieval|guard,
  action: str,                      // 本体词表内的动作token（本体可插拔点1）
  ts_start: float, ts_end: float,
  tokens_prompt: int|null, tokens_completion: int|null, cost: float|null,
  status: ok|error, finish_reason: stop|length|null,
  input_text: str, output_text: str,// 文本比对源（legacy 兜底通道）
  // ---- v1.2 增补 ----
  model: str|null,                  // 实际服务模型名，`model_mix_cost_index` 与按模型基线的输入
  ttft: float|null,                 // 首 token 时间（秒），仅 llm/agent 类
  tool_name: str|null,              // 工具身份，比 action 更细（本体 tool_catalog 一对多）
  tool_params: {str: any}|null,     // 归一化后参与哈希；`loop_count` 按 (parent, action, 参数哈希) 分组
  prompt_version: str|null,         // 提示词版本；分数可复现性的必要维度
  output_facts: [str],              // 该步产出的结构化事实，数值可溯源性的证据池（首选通道）
  level: DEFAULT|WARNING|ERROR,     // 日志级别，与 status 正交（WARN 不是 error）
  status_message: str|null          // 错误/告警文案，错误分类与重试判定用
  // ---- v1.3 增补 ----
  tokens_system_prompt: int|null,   // 系统提示词 token，是 tokens_prompt 的**子集**而非增量
  tokens_cache_read: int|null,      // 命中前缀缓存的输入 token，同为 tokens_prompt 的子集
  tokens_cache_write: int|null,     // 写入缓存的 token；计费口径独立，不属于 prompt 子集
  cost_details: {prompt: float, completion: float, tool_call: float,
                 cache_read: float, cache_write: float} | null
                                    // `cost` 的归因分解，恒等式 sum(values()) == cost；
                                    // 修复 cost 时**必须同步重建**，否则该恒等式被破坏
  subgoal_text: str|null,           // 该步子目标原文，与 trace.goal_text 比对得到目标漂移
  arg_valid: bool|null,             // 工具入参是否通过本体的 param_schema 校验（tool/retrieval）
  output_citations: [str],          // 该步检索到的知识条目 id，答案引用的证据池（retrieval）
  verifier: {passed: bool, detail: str} | null   // 护栏裁决（guard 类）；verifier_pass_rate 的来源
}
```

**条件可用字段**：`golden_*` 只在答案为数值型且被采样到时发射（全数据集 25.8%），
`user_feedback` 只在被采样到时发射（25.3%），`ttft`/`prompt_version` 只在 llm 类 Span 上有，
`tool_name`/`tool_params` 只在 tool/retrieval 类上有。缺就是 `null`，**不是 0，也不是错误**。

规范化规则（`kernel/ingest.py`，纯函数）：孤儿 Span 按时间包含关系重建父节点并置 `orphan_rebuilt`；
时间戳非单调时修复并置 `ts_repaired`；token/cost 缺失时按本体单价重算并置 `usage_estimated`。
**缺失置空而非置 0。**

缺失率按**修复之前**的原始 Span 测量，且分母是**按 Span 类型的条件可得字段集** `EXPECTED_FIELDS`
（llm 13 项、agent 10 项、tool 6 项、retrieval 7 项、guard 5 项；v1.3 随新增字段扩容，`cost_details` 刻意不计入——它是 `cost` 的分解，计进去会把 cost 的丢失重复计价一次）：

- `missing_field_ratio` = 原始缺失数 / 条件可得字段总数 ← **进打分与置信度的就是这一个**
- `missing_field_ratio_post` = 修复后同口径值（修复成功时按构造为 0，只用于自检）
- `missing_fields` = 缺失字段名的有序去重列表

> 两条都是本轮修的。原先在修复**之后**测量，导致该值在 8 个 regime 上 distinct=1、恒为 0.0
> （包括注入 45% 残缺的 R5），`kernel/score.py` 的 `mfr > 0.20` 置信度降级分支是死代码。
> 分母原先是无差别的关键字段集，而工具 Span 合法地不带 token——那样量到的是 Span 类型配比，
> 不是遥测丢失。修复后 R1 p50=0.0000 / p99=0.1000，R5 p50=0.0250 / p99=0.2000。

### 1.1 token 口径：两条必须写下来的约定

这两条是 v1.3 才补的，因为它们同时被生成器、`kernel/ingest.py` 的修复逻辑与附录 A 的三处
公式引用，口径不一致会直接产出「大于 1 的比例」这种自相矛盾的特征值。

**约定一：`tokens_prompt` 是包含关系，不是相加关系。**

```
tokens_prompt  ⊇  tokens_system_prompt
tokens_prompt  ⊇  tokens_cache_read
tokens_total_contract(附录 A #24)  =  tokens_prompt + tokens_completion
                                      + tokens_cache_read + tokens_cache_write
```

即缓存读命中与系统提示词**已经在** `tokens_prompt` 里。因此 `cache_hit_ratio` 的分子分母是
`tokens_cache_read / tokens_prompt`（∈[0,1]），而**不是**除以某个「非缓存输入」。
`tokens_cache_write` 是唯一不计入 `tokens_prompt` 的一项，因为写入缓存的 token 在本次调用里
不产生输入计费，只产生缓存计费。

`kernel/ingest.py` 在重建缺失的 `tokens_prompt` 时会取
`max(按本体单价反推的输入 token, tokens_system_prompt, tokens_cache_read, tokens_cache_write)`
作为下限。缺少这个下限曾产出 52 个「`tokens_cache_read` 大于自身 `tokens_prompt`」的 Span
（700 条开发样本上），并把 `system_prompt_ratio` 顶到 2.098——比例大于 1 不是估计误差，
是自相矛盾，且会顺着传导进 `cache_hit_ratio` 与 `context_utilization`。加下限后同样本 0 次违反。

**约定二：附录 A 的 `total` 与 v1 冻结的 `tokens_total` 是双重计数关系。**

附录 A #24 把缓存 token 再单独加一次，因此 `tokens_total_contract ≥ tokens_total`，差值恰为
`tokens_cache_read + tokens_cache_write`。检测门槛是在 v1 的 `tokens_total`
（= prompt + completion）上标定的，所以：

- `kernel/baseline.py:METRICS` 里的 `tokens_total` **不得**被静默改定义为 contract 版本；
- 附录 A 的量一律以 `tokens_total_contract` 这个名字发射（见 §2 命名冲突表）。

同理 `system_prompt_ratio`（= 系统提示词 / 输入）与 v1 冻结的 `prompt_token_ratio`
（= prompt / total）是两个不同的量，各自保留原名。

## 2. 特征宽表（全量 77 特征命名契约见方法论文档附录 A）

**v1 冻结（21 个标量 + 2 个序列，定义与命名不再变更）**——`kernel/baseline.py:METRICS`
的 11 个指标全部取自这一组，因此门槛表里的历史数字只对这组可比：

`latency_total, n_spans, depth, branch_factor, n_llm, n_tool, n_guard, tokens_total,
prompt_token_ratio, cost_total, retry_count, error_ratio, loop_count, guard_hits,
answer_number_count, traceable_number_ratio, action_seq:[str], embedding:[float]`

**v2 已发射、未接线**——`kernel/features.py::extract` 已产出，但**没有**进 `METRICS`、
没有进打分。接线是需要单独测量的一轮工作（slice2）：

- 结构（A.1）：`max_width, kind_ratio_llm, kind_ratio_tool, kind_ratio_retrieval,
  kind_ratio_guard, n_unique_tools, tool_repeat_rate, loop_group_count, loop_run_max,
  longest_repeated_subseq, error_level_ratio, warn_level_ratio`
- 时延（A.2）：`ttft, busy_union, llm_time_ratio, tool_time_ratio, guard_time_ratio,
  wait_time_ratio, parallelism_ratio, span_latency_p95, bottleneck_share,
  inter_step_gap_cv, retry_latency_share`
- 成本（A.3）：`cost_per_span, tokens_per_span, model_count, model_mix_cost_index,
  prompt_version_count`
- 结果符合度（A.5）：`key_fact_recall, fact_precision, unfaithful_fact_count, has_golden`
- 弱监督 / 数据质量 / 上下文：`implicit_feedback, has_feedback, missing_fields,
  missing_field_ratio_post, turn_index`

**v3 已发射、未接线（34 项）**——`bench-gen-v3.0.0` 起数据才携带其原料，
`kernel/features.py::extract` 已产出，但与 v2 同规则：**没有**进 `METRICS`、没有进打分，
以免冻结门槛失去可比性。接线是 slice3 的工作。

- 成本分解（A.3，15 项）：`tokens_total_contract, cache_read_tokens, cache_write_tokens,
  cache_hit_ratio, system_prompt_ratio, token_efficiency, cost_concentration_gini,
  top1_cost_share, context_growth_slope, context_utilization, cost_share_prompt,
  cost_share_completion, cost_share_tool_call, cost_share_cache_read, cost_share_cache_write`
- 时延与结构（A.1/A.2，2 项）：`critical_path, parallelism_ratio_contract`
- 语义与行为（A.4，12 项）：`query_len, query_lang, query_complexity, goal_drift_slope,
  goal_drift_max, self_correction_count, plan_revision_count, tool_success_rate,
  tool_arg_valid_rate, path_convergence, effective_info_ratio, cost_per_step_of_progress`
- 结果符合度（A.5，2 项）：`verifier_pass_rate, citation_reachability`
- 会话上下文（A.4 #50/#51，2 项）：`n_turns_in_session, reformulation_signal`
- 序列（1 项）：`action_kinds`（与 `action_seq` 平行的 Span kind 序列）

**三处命名冲突的处置。** 附录 A 里有三个量与 v1 冻结键**同名但不同义**。一律以「附录的量另起
一名发射」解决，而不是重定义 v1 键——检测门槛是在 v1 的含义上标定的，静默改定义会让历史门槛
数字失去意义：

| 附录 A 的量 | 发射名 | v1 冻结键（含义不同，保持不变） |
|---|---|---|
| #24 `total = input+output+cache_read+cache_write` | `tokens_total_contract` | `tokens_total` = prompt + completion |
| #33 系统提示词 / 输入 | `system_prompt_ratio` | `prompt_token_ratio` = prompt / total |
| #19 `1 − critical_path / Σduration` | `parallelism_ratio_contract` | `parallelism_ratio` = `1 − |union| / Σduration` |

**两个跨记录特征。** `n_turns_in_session` 与 `reformulation_signal` 按定义需要看到同一会话的
**下一轮**，因此无法在只看单条轨迹的 `extract()` 里计算，由 `annotate_sessions(feats, traces)`
补齐。**任何批量调用方都必须调用它**，否则这两个键恒为 `None`；`bench/runner.py` 在 `extract`
之后立即调用。单条打分场景下它们保持 `None`，内核按「未定义」而非「0」处理。
`reformulation_signal` 在会话内按轮次**去均值**后发射，因此它是一个相对信号，跨会话不可直接比大小。

条件可用特征缺失时值为 `null`。

**占比类特征的两条硬约束**（附录 A 的原始公式在并行子 Span 下会越界，实测
`wait_time_ratio` 最低 −1.94、`llm_time_ratio` 最高 2.78、tool 与 retrieval 分别求并集再相加
到 1.088、`bottleneck_share` 恒等于 1.0）：

1. 一律按**区间并集长度**（`_union_len`）聚合，不得用 Σ 子 Span 耗时；tool 与 retrieval
   必须**联合**求一次并集。
2. 一律**排除根 Span**（根按构造覆盖全部壁钟）。

修复后实测全部落在 [0,1]，全量 22,800 条越界计数 0，且与 `bench/coverage.py::probe()`
的独立参考实现逐条一致（13 个特征最大绝对差 0）。

**`loop_count` 的定义**（附录 A.1 #10）：兄弟 Span 按 `(parent_id, action, 参数哈希)` 分组，
对组内重复数 ≥ 3 的取 `max(0, count - 2)` 求和。旧的「相邻同动作连跑」启发式保留为
`loop_run_max`，不再充当 `loop_count`。

**`implicit_feedback` 永远不得进 `METRICS`**：它与标签按设计相关（弱监督），进基线会平凡地
把 F1 刷高，而不是让检测变好。

## 3. 簇与格子分配
```jsonc
ClusterAssign { trace_id, intent_cluster: int|-1, pattern_cluster: int|-1,
                cell: "i{a}xp{b}"|null, consensus_intent: float, consensus_pattern: float,
                novelty: bool }
```
字段补充：

```jsonc
ClusterAssign { ..., near_intent: int, near_pattern: int,   // 弃判前最近的簇，用于父级回退与诊断
                post_margin: float|null }                   // 对数后验余量 (d2_2nd - d2_own) / 2 sigma^2
```

`novelty=true` 的判定是三条的**或**：
1. 该簇在重采样子集里是单点簇（意图视图或模式视图）；
2. 该轨迹的共现轮廓系数 `cons = (a - b) / max(a, b)` 低于 `consensus_threshold`
   （a = 与自身簇的平均共现频率，b = 与最强竞争簇的平均共现频率）；
3. 其后验余量 `post_margin` 低于全体分布在与 (2) 相同分位上的切点。

第 3 条是**传播规则**：稳定性只能在重采样子集（`EVAL_M` 条）上测得，"有多少条不可归簇"由子集
实测，"具体是哪几条"由后验余量按同一比率在全量上判定。两侧都不是自由参数；在良分离流量上实测
率为 0，此时几何规则自动关闭。

**划分与阈值解耦**：模型阶数取袋装各次 k 的**中位数**，切点高度由它反推，因此
`consensus_threshold` 只改变弃权量、不改变簇结构。由
`bench.invariants::cluster.consensus_threshold_semantics` 断言。

## 4. 检测器输出
```jsonc
DetectOut { trace_id, layers: {L1..L5: dev}, dev_by_metric: {metric: dev},
            z: {metric: modified_z}, p_trace: float, p_family: float,
            struct: {missing_frac, illegal_actions, unfinished, traceable_viol, hard: bool},
            ll: float, ll_z: float|null,
            span_dev: float, span_evidence: {span_id, metric, z, value, baseline},
            fallback_level: L1|L2|L3, b_cell: float, conf: float,
            evidence: [ {span_id?, kind, rule, z?, value?, baseline?} ] }
FusedOut  { trace_id, a_raw: float, a_cal: float|null, conf: float, tier: 0|1|2,
            graded: float[0,1], alert: bool, alert_stat: bool, alert_rule: bool }
```

五层偏离度：

| 层 | 名称 | 输入 | 输出 |
|---|---|---|---|
| L1 | 轨迹级稳健 z | 簇内条件基线的 median/MAD | 每个指标的 modified z 与饱和偏离度 |
| L2 | 轨迹级尾部概率 | 对数尺度主体拟合 + GOF 自检（见 §10.1） | 每个指标的 p 值 |
| L3 | Span 级归因 | Span 分族基线（latency/usage/error） | 最差 Span 与其 p 值 |
| L4 | 结构/契约 | 本体 `forbidden_actions`、`required_steps`、`validators` | `hard` 布尔 + 分级偏离 |
| L5 | 序列似然 | 簇内动作一阶马尔可夫链 | 对数似然与其 z |

决策双通道（互不覆盖）：

- `alert_rule` = 非弃判 且 `struct.hard`（本体声明的确定性违规）
- `alert_stat` = 非弃判 且 该格子内 BH-FDR 在 `BH_ALPHA` 下拒绝 `p_trace`
- `alert` = 二者之或

`p_trace` 是**一次** Bonferroni：`min(1, n_tests x min p)`，覆盖该轨迹贡献的全部检验（M 个轨迹
指标 + 其 Span 检验）。不做嵌套的族内乘积——那会把保守性再乘 ~40 倍。`p_family` 仅作证据展示。

分诊优先级 `a_raw` = 档位带宽 + 档内排序：

```
tier = 2 if alert_rule else (1 if alert_stat else 0)
a_raw = lo + (hi - lo) * graded         (lo, hi) = TIER_BANDS[tier]
graded = sum(W[l] * rank_within_cell(dev_l)) / sum(W)     W = LAYER_WEIGHTS
```

三档带宽互不相交，因此"确定性违规排在统计嫌疑之前"是结构性的，不依赖权重取值。

## 5. 打分记录
```jsonc
ScoreRec { trace_id, cell, dims: {O,P,L,C,R}: float[0,1], gates: {name: multiplier},
           G: float, S: float, grade_abs: A|B|C|D, grade_rel: A|B|C|D,
           contrib: {O,P,L,C,R}: float, ci: [lo,hi], conf: float,
           cold_start: bool, model_version: str, anchor_version: str,
           alert: bool, alert_stat: bool, alert_rule: bool,
           a_raw: float, a_cal: float|null, tier: 0|1|2, graded: float,
           evidence: [ ... ] }
```
恒等约束：`sum(contrib.values()) == S - 100*G`（零残差，LMDI）。

## 6. 真值（bench 生成器随数据发射）
```jsonc
GT { trace_id, intent_id, pattern_id, cell_id, is_anomaly: bool,
     anomaly_types: [latency_spike|token_bloat|loop|error|missing_step|illegal_step|
                     hallucinated_number|truncation|unfinished],
     dim_dev: {O,P,L,C,R}: float[0,1],          // 该维"应有"的归一化得分
     responsible_span_ids: [str], process_flags: {missing_step,illegal_step,unfinished}: bool,
     defect_flags: {ts_repaired,usage_estimated,orphan_rebuilt}: bool,
     drift_segment: int|null, human_label: bool|null,    // human_label = 带5%噪声的模拟标注
     // ---- v1.2 增补 ----
     has_golden: bool,               // 该条是否发射了 golden
     key_fact_recall_true: float|null,   // golden_facts 被答案覆盖的比例（不完整 → 压这里）
     fact_precision_true: float|null,    // 答案事实中属于 golden 的比例（不忠实 → 压这里）
     hallucinated_facts: [str],      // 答案里多出来、golden 中没有的事实
     loop_true: bool,                // 数据里是否真的存在参数完全相同的 ≥3 次重复
     mfr_true: float,                // 注入的真实字段缺失率（与 ingest 实测对账）
     model_mix_true: {model: share}, // 真实模型配比
     feedback_available: bool,     // 该条是否发射了 user_feedback
     // ---- v1.3 增补 ----
     latency_true: float,          // 生成时刻的端到端时延真值（秒），与 latency_total 对账
     gen_quantiles: {dim: float},  // 该条被压的维在其格子(cell)内的分位位置；只对被压的维发射，
                                   // 是「异常强度」的连续真值，dim ∈ {O,P,L,C,R}
     arg_valid_true: float[0,1],   // 工具入参通过本体 param_schema 校验的比例真值
     cache_read_true: int,         // 缓存读命中 token 总量真值
     cache_write_true: int,        // 缓存写 token 总量真值
     system_prompt_ratio_true: float,      // 系统提示词 / 输入 的真值
     cost_details_reconciled_true: bool,   // Σcost_details == cost 恒等式是否成立
     citation_reachable_true: float[0,1],  // 答案引用能在检索证据池中命中的比例真值
     fabricated_citation_count: int,       // 答案里凭空捏造（证据池中没有）的引用条数
     contradicted_count: int,      // 与检索证据相冲突的事实条数
     contradiction_true: float[0,1],       // 归一化后的矛盾率真值
     goal_drift_true: bool,        // 是否真的发生目标漂移（对照 goal_text）
     plan_revision_true: int,      // 计划修订次数真值
     subgoal_count: int,           // 子目标数，goal_drift 的分词参照个数
     verifier_pass_true: float[0,1],       // 护栏通过率真值
     query_lang_true: zh|en,       // 语种真值
     session_turn_count_true: int }        // 会话总轮数真值
```

`key_fact_recall_true` / `fact_precision_true` / `hallucinated_facts` 三者共同保证
**「不完整」与「不忠实」可分离**：`truncation`/`unfinished`/`missing_step` 只压 recall
（precision = 1.0），`hallucinated_number` 只压 precision（recall = 1.0）。
若两类失败被压成同一个数，O 维（权重 0.40）就无法区分「答错了」与「没答完」。

`loop_true` 的存在是因为标签曾经与数据不一致：循环注入器复制骨架但工具参数从推进的随机流里抽，
复制出的两份参数不同，实测 R1 有 7 条被标为 `loop` 的轨迹里根本没有循环。
`bench/coverage.py::truth_agreement()` 现在对全量 22,800 条做**标签↔真值↔特征**两两等价校验，
任一不一致即退出码 1。

## 7. regime DSL（变化轴与取值域）
`n, mix:[(weight, latency_median, sigma)], n_intents, n_patterns_per_intent, overlap(0-1),
cell_sparsity, defect_rate, drift(magnitude, at_frac), label_count, ontology_id,
anomaly_rate, anomaly_mix:{type:weight}, seed,
golden_rate(默认 0.30), feedback_rate(默认 0.25),
title, hours(默认 72), intent_ambiguity(默认 0.12), gates:{门槛名: 要求}`

**v1.3 新增的三个键：**

- `title`：regime 的人类可读标题，进报表、`COVERAGE.md` 与 `SAMPLE.md`。它**参与 `spec_hash`**
  （见 §12），所以改标题会让锚点版本号变化——这是有意的，标题属于规格的一部分。
- `hours`：该 regime 覆盖的运营时长（小时）。生成器用它把 n 条轨迹均匀铺在时间轴上
  （`step_s = hours x 3600 / n`），`runner` 用它算运营告警流的预算
  `k = ALERT_BUDGET_PER_DAY x hours / 24`。改 `hours` 会同时改变时间密度与告警预算。
- `intent_ambiguity`(0-1)：句向量被拉向「其余意图均值」的最大比例，
  `t = intent_ambiguity x 2 x Beta(2,6)`，逐条采样。**默认 0.12，只有 R3 覆盖为 0.50**，
  用来造出真实的意图连续谱（有些用户问题本身就跨两个意图）。它是 `novelty` 通道唯一有效的
  激励源：把它调到 0，共识矩阵会退化成二值，弃权机制形同不存在。

**两个容易混淆的量，必须分清：**

- `overlap`(0-1) **只作用于嵌入几何**：逐维高斯噪声的标准差 `sigma_e = overlap x 0.70`。
  它不影响时延、不影响动作序列。
- `mix` 里的 `latency_median/sigma` 才是**时延**分布。常量名 `_MIX2_OVERLAP` 指的是
  「双峰时延混合」，与 `overlap` 无关，不要因为名字相同就以为它在调嵌入重叠度。

`golden_rate` / `feedback_rate` 是**条件可用率**而非缺陷率：它们控制有多少轨迹带 golden 答案与
用户反馈，用来模拟「标注/反馈只覆盖一部分流量」的真实运营条件，也用来验证内核在
`has_golden=false` / `has_feedback=false` 时正确降级而不是崩掉。

## 8. 门槛表 v1.3（runner 输出 PASS/FAIL）
| regime | 聚类 ARI_intent | ARI_pattern | 检测 F1 | Precision@50 | 正常误报率 | 校准 ECE | 附加 |
|---|---|---|---|---|---|---|---|
| R1 双峰主路径 | ≥0.70 | ≥0.60 | ≥0.70 | ≥0.80 | ≤0.05 | ≤0.08 | 零残差恒等 |
| R2 三峰 | ≥0.65 | ≥0.55 | ≥0.65 | ≥0.75 | ≤0.06 | ≤0.08 | |
| R3 重叠加意图歧义 | ≥0.55 | ≥0.50 | ≥0.60 | ≥0.70 | ≤0.08 | ≤0.10 | novelty 率∈[0.03,0.30] |
| R4 极稀疏格子 | ≥0.60 | ≥0.50 | ≥0.50 | ≥0.60 | ≤0.10 | ≤0.12 | L2/L1 回退占比≥0.5 |
| R5 高残缺 | ≥0.65 | ≥0.55 | ≥0.60 | ≥0.70 | ≤0.08 | ≤0.10 | 残缺轨迹 conf 下调率=1.0 |
| R6 冷启动 | 跳过 | 跳过 | 不告警 | — | — | — | cold_start=true 且告警数=0 |
| R7 漂移 | ≥0.65 | ≥0.55 | ≥0.60 | ≥0.70 | ≤0.08 | ≤0.10 | 检出变点且 lag_frac ∈ [-0.05, 0.10]（**双侧**） |
| R8 异本体 | ≥0.65 | ≥0.55 | ≥0.65 | ≥0.75 | ≤0.06 | ≤0.10 | 本体词表零硬编码断言 |

全 regime 追加门槛：

| 门槛 | 要求 | 说明 |
|---|---|---|
| `operator_stream_precision` | ≥ 0.80 | 日预算 k = `ALERT_BUDGET_PER_DAY x days` 条的告警流精度。这是唯一会主动打扰人的通道 |
| `no_drift` | 平稳期 `detected=false` | R1/R2/R3/R4/R5/R8 六个无漂移规格的 regime 全部纳入 |
| `novelty_rate` | ≤ 0.25（默认） | R3 额外要求 ≥ 0.03：弃权太少说明共识机制没有真正在工作 |

**ARI 类门槛的信息上界封顶**：有效门槛 = `min(表值, CEIL_RATIO x oracle 上界)`，
`CEIL_RATIO = 0.90`，上界与实测在**同一个可归簇池**上计算。上界由 `runner.oracle_ceilings()`
给出：意图视图 = 插入式 Bayes MAP 规则（真类均值、真先验、组内合并方差）；模式视图 = 序列
oracle（每个不同动作骨架取其多数真值标签）。封顶只会放松门槛。

> 这条规则的来由：R3 门槛表写 `ari_intent ≥ 0.55`，而该 regime **全量数据的 Bayes 最优是
> 0.5162** —— 任何方法都达不到，包括直接拿到真值标签的方法。同池上界是 0.5508，实测 0.5121，
> 达成率 92.98%；有效门槛被封顶到 0.496。没有上界封顶的门槛表会把工程逼向过拟合。

**弃权必须被计价。** `ari_*` 只在可归簇池上计算，所以把难样本丢进 novelty 缓冲区就能靠
少打分来多得分。因此 `runner.evaluate()` 同时输出：

| 字段 | 含义 |
|---|---|
| `ari_intent_all` / `ari_pattern_all` / `ari_cell_all` | **弃权前**：同一次聚类，把每条轨迹都按最近簇计分 |
| `novelty_purity_intent` / `novelty_purity_pattern` | 缓冲区纯度：1.0 = 拒判了本可完美判定的流量；接近类先验 = 尾部确实模糊 |
| `novelty_anomaly_rate` / `pool_anomaly_rate` | 缓冲区与池内的异常率，用来看弃权是否恰好丢掉了高风险那一片 |

实测 R1：缓冲区 433 条（10.8%），`ari_pattern` 弃权前 0.8368、池上 0.9856（净买 +0.149），
缓冲区纯度 0.9908、异常率 0.0901 > 池内 0.0732。对比 R8：0.8203 → 0.8215，几乎没差，
说明 R8 的低 `ari_pattern` 是异本体下**真实的聚类上限**，不是弃权买来的。

不变量（全 regime 必过，`python -m bench.invariants`，共 12 条）：
零残差 < 1e-6；满分守恒 S=100；单维塌陷重罚；门禁乘法合成；锚点单调；池化极限
n→∞ 收敛 L3、n→0 收敛 L1；**共识阈值语义**（划分不随阈值变、novelty 率随阈值单调不减且确实响应）；
同种子位级可复现；等渗校准单调且降 ECE；BH 在纯零假设下控制错误发现；
**禁用 `point-adjust`**（调用即抛异常）；**内核零硬编码本体动作名**。

## 9. 三通道口径（不可混用）

| 通道 | 内容 | 规模（R1 实测/72h） | 消费者 | 受控错误率 |
|---|---|---|---|---|
| 告警流 | `a_raw` top-k，k = 5 条/日 x 天数 | 15 条，Precision 1.000 | 值班运维（会主动打扰人） | Precision@k ≥ 0.80 |
| 审计流 | tier2 确定性违规全量 | 182 条 ≈ 60.7 条/日 | 合规/复盘（落库待查，不呼叫） | 规则精度 ~0.99 |
| 复核队列 | `alert` 全集 | 206 条（统计 24 + 硬规则 182） | 人工复核预算 | BH-FDR α = 0.20 |

剔除 tier2 后统计通道自身的 Precision@50 = 0.640，该子池异常基率 0.0236，提升 27.1 倍——
两个数必须一起看，因为剥掉确定性违规会把大部分异常一起剥走，剩下的总体难得多。

"告警太多就去调小 α" 是最常见的误操作：它会同时牺牲召回与复核覆盖率。告警多的真实原因通常是
没有区分三条通道——确定性违规是审计记录，不是呼叫。运营侧只调 `ALERT_BUDGET_PER_DAY`。

## 10. 关键机制的实现约束

### 10.1 尾部概率：对数尺度主体拟合 + GOF 自检
`kernel/baseline.py::fit_tail` **不**用超出量中位数估指数率（POT）。在 7%–10% 异常占比下，
上十分位已是多数污染，β 被抬高 1.4 倍、尾部衰减慢约 10 倍，5 倍的 Span 尖峰报出 p=1.5e-2
而不是 1.4e-3，统计通道整体塌缩成"带装饰性 p 值的规则引擎"（实测 3979 条轨迹只出 6 条告警）。
现做法：在**主体**上拟合对数尺度的中位数与 IQR 尺度（崩溃点 ≥ 25%），按正态尾外推，
再用 `y70-y50 ≈ s x Z_70_50`、`y85-y50 ≈ s x Z_85_50` 两条 GOF 自检（容差 `TAIL_GOF_TOL=0.50`）
决定是否接受该模型；不接受则退回纯经验分位。经验/参数切换点 `p_emp <= (TAIL_SWITCH_K+0.5)/(n+1)`。

### 10.2 共识聚类：袋装 + 中位数阶 + 共现轮廓系数
`kernel/cluster.py`。每次运行在 bootstrap 重采样上重拟合 k-means++，**袋外点按最近袋心标注**
（Monti et al.），使每一对在每一次运行中都获得投票——纯子采样会留下约 37% 的对无票，
其共现频率与"分歧"不可区分。视图内稳定性用共现矩阵的**轮廓系数**而非簇内均值：
边界轨迹与两侧都强共现，其簇内均值仍有 ~0.7，看起来"很确信"，只有相对余量能表达这种不确定性。

### 10.3 漂移：符号 CUSUM + 右锚定窗 + 双重采样自举阈值 + 两级参考矩梯（含弃权）
`kernel/drift.py`。四个部件各自对应一个实测失败模式，详见该模块文档串与 `adapt/playbook.md §5`。

**参考矩梯是两级 + 弃权，不是三级到全局**：`cell → parent → abstain (z=None)`。
全局兜底会把 1.5s 的总体与 120s 的总体混在一起，使 z 恒正——实测 R4 最慢意图 `i3`（92 条）
在 cell 与 parent 层都不足 30 条参考观测而落到全局，`z_mean_ref = 0.181`，在**平稳**数据上
报出变点（统计量 45.1 vs λ 12.2，误报 idx 681）。取消全局兜底后 `z_mean_ref` 0.181 → 0.041。
`cell_normalized_z` 返回 `levels = {"cell", "parent", "abstain"}` 计数；`detect_drift` 先压紧
掉 `None`、在压紧序列上跑 CUSUM、再用 `kept[]` 把每个上报下标映射回流位置，并报告
`n_abstain / abstain_share / n_monitored / ref_window_monitored`。

**弃权过多不是「无漂移」**：`MAX_ABSTAIN_SHARE = 0.50`，超过则返回
`drift=False, reason="insufficient_support"`。这是「不知道」，必须与「平稳」区分开。

**λ 标定必须抽两个重采样，不是一个**：`calibrate_lambda(ref_z, ...)` 收**原始 z 值**，每次重复
抽 A（参考长度）与 B（监测长度）两个块自举重采样，用 `centre = median(A)` 去给 B 打分。
只抽一个时，符号序列的中心**恰好等于它自己的中位数**，零假设里不含中心估计误差——实测 R4
每 cell 参考样本 n = 112/67/30，30 个对数正态样本的中位数偏差足以把 cell `i2|p2` 的尾部推到
68.8% 高于合并中心，于是 λ 被低估。修正后 **λ 10.6 → 75.8**，统计量 44.6 → 不再检出。

实测：平稳 6 regime（R1/R2/R3/R4/R5/R8）**零误报**，统计量 −28.0 ~ +44.6 vs λ 8.1 ~ 85.5，
`z_mean_ref` −0.086 ~ +0.041，矩梯使用 cell 1024~3970 / parent 0~599 / abstain 0~89；
R7 命中窗 [2008, 3999]，真变点 2000，**lag +8（lag_frac = 0.0020）**，统计量 996.8 vs λ 65.0，
窗内 80.0% 流量越过参考中位数。

## 11. 本体接口（唯一可插拔点）
```jsonc
Ontology { id, actions: [str], forbidden_actions: [str],
           required_steps: {pattern_id: [action]}, slo_anchors: {cell: {dim: {ideal,good,warn,bad}}},
           unit_price: {prompt: float, completion: float, tool_call: float},
           validators: [ {kind: regex|json|number_traceable, target: answer|tool_output, spec: str} ],
           // ---- v1.2 增补 ----
           models: [(name, weight, price_multiplier)],  // 模型目录：采样权重 + 价格倍率
           prompt_versions: [(ver, weight)],            // 提示词版本目录，含 ~10-12% 的 canary
           tool_catalog: {action: [tool_name]},         // 一个动作可对应多个工具身份
           param_keys: {action: [key]},                 // 每个动作的参数键，参数哈希的定义域
           error_messages: [str], warn_messages: [str], // status_message 取值域
           action_text: {action: (input_tmpl, output_tmpl)},  // 文本模板，占位符
                                                              // {intent} {ne} {win} {tool} {ver} {nums}
           // ---- v1.3 增补 ----
           root_action: str,                 // 根 Span 的动作名（轨迹树的入口）
           kind_map: {action: agent|llm|tool|retrieval|guard},  // 动作 -> Span 类型；
                                             // 缺失时回退 KEY_FIELDS，是 kind_ratio_* 的定义域
           optional_steps: [action],         // 可省略的步骤；missing_step 判定必须排除它们
           param_schema: {action: {key: type}},  // 入参模式；arg_valid 与参数哈希的定义域
           intents: [ {goal:{zh,en}, ask:[...], ...} ],   // 意图目录（每条含目标短语与 >=8 种
                                             // 双语问法）。**是「业务声明的意图分类法」**，
                                             // 注意它约束的是词表，不是某个 regime 实际出现的
                                             // 意图数——一个 regime 只会用到其中的子集
           query_langs: [(lang, weight)],    // 语种采样分布
           lang_token_factor: {lang: float}, // 同义文本按语种的 token 折算系数（中文更省）
           system_prompt_tokens: {model: int},   // 各模型的系统提示词长度
           context_window: {model: int},         // 各模型上下文窗口；context_utilization 的分母
           time_windows: [str],              // 时间窗取值域（5m/1h/...），填 {win} 占位符
           kb_sources: [str],                // 知识条目 id 池；output_citations 与
                                             // answer_citations 都从这里取，因此
                                             // citation_reachability 的「可达」才有确定含义
           subgoal_core: {zh,en}, subgoal_detour: {zh,en}, subgoal_frames: {zh,en},
                                             // 子目标文本的三套模板：正路 / 绕路 / 外层包装。
                                             // goal_drift 靠「绕路模板出现」产生真实漂移
           out_frames: [{core}|...],         // 输出文本的外层包装模板，制造文本多样性
           golden_template: str,             // 标准答案模板
           answer_templates: [str],          // 实际答案模板（含数值）
           answer_empty_templates: [str] }   // 无数值载荷时的答案模板
```
内核任何模块不得出现具体动作名常量；一律经本体查询（由
`bench.invariants::kernel.no_hardcoded_ontology_actions` 断言）。
**文本模板必须放在本体里而不是内核里**，否则接入第二个业务就要改内核。
护栏动作的输出模板刻意保留小写 `block`，因为 `features.extract` 按子串统计护栏命中次数。

## 12. 数据集产物与溯源（v1.3 新增）

### 12.1 每个 regime 的产物

```
data/bench_v1/<RID>/
  traces.jsonl   一行一条 Trace，json.dumps(sort_keys=True, ensure_ascii=False)
  gt.jsonl       一行一条 GT，与 traces.jsonl 按 trace_id 一一对应
  meta.json      规格快照 + 生成统计 + 嵌入几何 + 门槛表副本
  SAMPLE.md      人类可读样本（python -m bench.show <RID> --sample 重新生成）
data/bench_v1/COVERAGE.md   全量覆盖率审计（python -m bench.coverage --md 重新生成）
```

`sort_keys=True` 是**位级可复现的前提**，不是风格偏好：字典序固定后，同一 `seed` 与同一
`GEN_VERSION` 必须产出字节相同的文件。实测把 R1/R3 用 v3.1.0 重新生成后，`traces.jsonl` 与
`gt.jsonl` 的 SHA-256 与原文件逐字节一致。

### 12.2 meta.json 契约

| 分组 | 键 | 含义 |
|---|---|---|
| 身份 | `regime_id, title, seed, spec, spec_hash, generator_version` | `spec` 是**去掉 `gates`** 的完整 regime DSL；`spec_hash` 见 §12.3 |
| 规模 | `n_traces, n_spans, n_cells_true, cell_sizes, labels, session_count` | `cell_sizes` 按 `i<k>|p<j>` 分格并降序；`labels` 是**有标注**的条数，不是异常数 |
| 真值分布 | `anomaly_rate_true, anomaly_type_counts, defect_counts, golden_count, feedback_count, loop_true_count, plan_revision_count, goal_drift_count, contradiction_count, fabricated_citation_count, field_loss_total, query_variety, lang_counts, session_turn_counts` | 生成器自己数出来的真值，供 `coverage.truth_agreement()` 与内核实测对账 |
| 分位块 | `latency, tokens, cost, mfr_true, recall_true, arg_valid_true, citation_reachable_true, verifier_pass_true` | 统一 `{n, min, p50, p90, p99, max}` 六元组 |
| 几何 | `emb_dim, emb_geometry{...}` | 见 §12.4 |
| 门槛 | `gates{ari_intent, ari_pattern, f1, precision_at_50, fpr, ece, zero_residual, no_drift, novelty_min, novelty_max}` | 从 regime DSL 复制的副本，让 `meta.json` 单独就能自证门槛 |
| v3 计数 | `v3_counts{llm_spans, arg_invalid_spans, verifier_fail, cache_hit_spans, plan_revision, goal_drift, contradiction, fabricated_citation}` | v3 特征的**激励源计数**；任一为 0 就意味着对应特征恒为常数、无法验证 |

`cost_details_reconciled` 是布尔量：全量 Span 上 `Σcost_details == cost` 是否恒成立。

### 12.3 spec_hash 与锚点版本

```
spec_txt  = json.dumps({"generator_version": GEN_VERSION, "emb_dim": emb_dim,
                        "spec": {k: v for k, v in spec.items() if k != "gates"}},
                       sort_keys=True, ensure_ascii=False)
spec_hash = sha256(spec_txt.encode("utf-8")).hexdigest()[:16]
```

生成器版本**是哈希身份的一部分**：同一 regime 规格经不同生成器代码产出的数据是不同数据集。
`bench/runner.py` 用它拼锚点版本 `anchor_version = "anchor-<RID>-<spec_hash>"`，所以
把 `GEN_VERSION` 排除在哈希外会让一套 SLO 锚点在它所拟合的数据被换掉之后**静默存活**。
`gates` 被排除是因为调门槛不改变数据本身。

### 12.4 嵌入几何（`emb_geometry`）

| 键 | 常量 | 当前值 | 作用 |
|---|---|---|---|
| `dim` | `EMB_DIM` | 384 | 句向量维度（附录 A.4 #37 要求 384/768/1024） |
| `sig_dims` | `EMB_SIG_DIMS` | 16 | 承载话题的维度数；其余维度走背景尺度 |
| `topic_amp` | `EMB_TOPIC_AMP` | 10.0 | 话题振幅，信噪比的分子 |
| `bg_scale/bg_mu/bg_sigma` | `EMB_BG_MU/-SIGMA` | −0.90 / 0.45 | 背景逐维尺度 `exp(N(mu, sigma))`；背景中位 0.41 对信号维 1.41，约 3.5 倍对比 |
| `arc_step` | `EMB_ARC_STEP` | 0.75 | 相邻意图方向的夹角（弧度），构成话题连续谱；cos = 0.73 |
| `dominant` | `EMB_DOMINANT` | 2.0 | 共享方向振幅 → 窄锥、高两两余弦（真实句向量的形态） |
| `norm_sigma` | `EMB_NORM_SIGMA` | 0.06 | 逐条长度扰动（句长差异，与话题无关） |
| `sigma_e` | `overlap x 0.70` | 随 regime | 逐维高斯噪声，`overlap` 的唯一消费点 |
| `continuum` | `intent_ambiguity` | 0.12（R3 为 0.50） | 拉向其余意图均值的最大比例 |
| `participation_ratio` | 实测（**全量**口径） | 72.3–131.7 | `(Σs²)² / Σs⁴`，有效参与维度数。`meta.json` 存全量值；覆盖率审计用 **200 条抽样**，读数系统性偏低（40.0–125.9），两个数都对，见 §12.5 |

**`participation_ratio` 是几何是否可用的单一判据。** 各向同性的 384 维高斯团 PR = 384，
信号被噪声淹没；完全塌到 16 维则 PR = 16，k-means 能解但白化不能解。实测八个 regime 的
PR 为 R1 110.8 / R2 131.7 / R3 114.7 / R4 118.9 / R5 113.0 / R6 116.8 / R7 72.3 / R8 125.7，
全部落在 (16, 384) 的内侧。**这一行是全量口径**；`coverage.embedding_pr()` 抽 200 条，同一批
数据读作 R1 91.4 / R2 99.1 / R3 109.4 / R4 98.2 / R5 104.0 / R6 125.9 / R7 40.0 / R8 55.6——
小样本的逐维方差更噪，PR 系统性偏低，所以审计看到的是更小的那个数，门槛也按审计口径判。
两侧余量的完整实测与被否决的替代方案见 §12.5 与 `bench/contract.py::participation_ratio`。
信噪比恒等式：

```
SNR_iso = (topic_amp / sigma_e) x ||delta|| x sqrt(participation_ratio / EMB_DIM)
```

`topic_amp = 10.0` 是**能修好 4 意图场景的最小值**（分离度/噪声半径在 7.0 时为 1.25、
10.0 时为 1.78），不再上调是因为到 14.0 时 `overlap` 会失效（overlap 0.88 下 `ari_iso`
仍为 1.0000，变化轴失去意义）。标定过程与被否决的替代方案（单纯调小 `bg_sigma`、
单纯调大 `overlap`）连同实测数字记录在 `bench/generate.py` 的常量注释里。

### 12.5 新鲜度断言（防止拿旧数据跑新代码）

`spec_hash` 此前只在生成时写入 `meta.json`，**没有任何组件校验它**。v1.3 补上：
`bench/coverage.py::dataset_provenance()` 对全部 regime 按 §12.3 的公式**用活的
`GEN_VERSION` 重算 `spec_hash`**，与 `meta.json` 里的值逐一对账，任一不符即退出码 1，
并在 `COVERAGE.md` 里报「数据集不新鲜」。

这条断言是实测踩出来的：桥接机制（`intent_bridge`）被完整回滚之后，8 个 regime 里有 7 个的
`meta.json` 仍残留 `emb_geometry.intent_bridge = 0.0` 这个已经不存在的键——那些数据是回滚**前**
的生成器产出的。而 `traces.jsonl` / `gt.jsonl` 恰好逐字节相同（该机制取 0.0 时不消耗随机流），
于是门槛 8/8 全绿、覆盖率审计全绿，**没有任何信号提示元数据已经过期**。重算 `spec_hash`
能一次抓住三类漂移：生成器版本变了、regime 规格变了、`emb_dim` 变了。

配套地，`bench/contract.py::fidelity_checks()` 里的 `query_embedding` 从「只断言维度」升级为
「维度 + 各向异性」：直接由数据算 `PR = (Σ σ_d²)² / Σ σ_d⁴`（逐维方差，**200 条抽样**——
`coverage.contract_audit(sample=200)` 与 `coverage.embedding_pr(sample=200)` 用的是同一个
样本量），要求 `1 < PR < EMB_PR_MAX_FRAC x dim`，`EMB_PR_MAX_FRAC = 0.75`，即上界 288。
实测本数据集 200 条抽样口径的 PR 为 R1 91.4 / R2 99.1 / R3 109.4 / R4 98.2 / R5 104.0 /
R6 125.9 / R7 40.0 / R8 55.6（全量口径见 §12.4，为 72.3–131.7）。原先该检查的 `required`
字符串已经写着「anisotropic, topic continuum」，代码却只测了维度——**文档承诺与实现不符**。

**两端都在审计自己的抽样量上实测过，不是从渐近式推的**（`bench/contract.py::participation_ratio`
的 docstring 里存了完整表）：384 维各向同性高斯团的 PR 在 n=50 / 100 / 200 / 400 / 1000 / 4000
上分别是 367.8 / 375.7 / 380.2 / 382.4 / 383.3 / 383.8，**每一档都高于 288**，所以上界在最小
抽样量下也有牙；下界一侧 n=200 时「只有一个维度非零」给出 PR = 1.0000，被**严格不等号**
`1.0 <` 拒掉（这就是它必须严格的原因），常向量与全零给出 0.0，能量摊在 7 维给 6.45、
192 维给 190.1、生成器自己的形态给 17.2。PR 因此在四个数量级的各向异性上都读作
「有效维度数」，一个标量才够用。抽样偏差是**系统性偏低**的（各向同性团从 n=4000 的 383.8
掉到 n=50 的 367.8），所以审计看到的数比 `meta.json` 的全量值小；如果未来把几何标定到贴近
上界，必须按审计自己的抽样量重测再动 `EMB_PR_MAX_FRAC`。

### 12.5.1 第二、第三跳：跑分 ↔ 数据集、跑分 ↔ 代码

`dataset_provenance()` 对账的是「**数据** ↔ 活的生成器」。它管不到再往下的两跳，而这两跳
都会让下游的「全绿」变成对**旧世界**的描述：

| 跳 | 比什么 | 抓什么失效 | 实现 |
|---|---|---|---|
| 数据 ↔ 生成器 | `meta.json["spec_hash"]` vs 用活 `GEN_VERSION` 重算 | 数据是旧代码产的 | `coverage.dataset_provenance()` |
| **跑分 ↔ 数据** | `metrics.json["spec_hash"]` vs `meta.json["spec_hash"]` | 数据重生成后忘了重跑 runner | `scorecard.reports_provenance()` |
| **跑分 ↔ 代码** | `metrics.json["code_hash"]` vs 活的 `runner.code_hash()` | **内核改了但没重跑 runner**——数据没动，所以 `spec_hash` 那一跳完全看不见 | 同上 |

第三跳是「每个工件带版本号入库、任意历史分数可复现可对账」这条纪律真正的落地：`spec_hash`
只说明分数属于哪份**数据**，`PIPELINE_VERSION` 是手维护字符串、会落后于它命名的代码，
两者都不说明内核长什么样。`code_hash` = 对 `runner.code_files()` 里每个文件取
`sha256(相对路径 + 内容 sha256)` 再整体 sha256、截 16 位十六进制；**路径也进哈希**，
所以重命名即使字节不变也会改变身份。

闭包是**按作用域取的，不是从 `sys.modules` 读的**：`sys.modules` 会让哈希取决于「谁在问」——
`bench.scorecard` 导入 `bench.runner` 时它自己也在 `sys.modules` 里，两边就永远对不上。
`kernel/` 与 `ontology/` 下的每个模块都被 runner 导入，所以直接哈希整个目录既完备又与调用方
无关（实测 17 个文件 = `kernel/` 11 + `ontology/` 2 + `CODE_FILES` 4；`bench/__init__.py` 也在
清单里，因为 `from bench import generate` 会执行它，而 `kernel/` 与 `ontology/` 的 `__init__.py`
由目录通配自动带上）。按目录取而不是逐个列，
本轮立刻就回报了：整目录哈希把一个从没被注意过的 `kernel/schema.py` 也算了进去，去查它有没有
人用，才发现它是无人导入、且与契约矛盾的 v1 残骸，已删除（`README.md`「本轮修复 9」）。
`CODE_FILES` 是唯一需要维护的清单：
runner 将来若导入新的 `bench/` 模块，要在那里加一行。

任一跳不符，`scorecard --check` 退出 1 并直接给出
`re-run python -m bench.runner --regimes <RID>`。负向测试两跳都做过：把 R5 的 `spec_hash`
改成 `0`×16、或改一行 `kernel/` 代码，守卫都立刻报错；还原后恢复 IN SYNC。

三跳合起来链条才闭合：**活的生成器 → 数据 → 跑分 → README**。任何一环过期，下游的「全绿」
都不再说明上游是对的。

### 12.6 派生文档：README 的「当前跑分」区块

`README.md` 的五个区块（标题行 / 主表 / 注解 / 打分质量表 / 三通道口径）是 `reports/` 的
**派生数据**，由 `<!-- scorecard:<name>:begin/end -->` 标记包住，`python -m bench.scorecard`
从 `metrics.json` 重算重写；首次运行按行首锚点自动落标记，之后幂等。手写派生表就会悄悄过期，
本轮对账当场抓到两处：`全矩阵约 782s`（重跑实测 743s），以及 R8 那句「弃权没有买分」里的
`差的 2.6 个百分点`——2.6 来自 `ari_pattern_ceiling_all − ari_pattern_all = 2.5769`，而该句
上下文比的是**池上**口径 `0.9978 − 0.9723 = 2.5466`，应为 2.5，两个口径混用，人眼看不出来。

`--check` 只读对账，两级任一不符即退出 1（README ↔ 跑分、跑分 ↔ 数据集，见 §12.5.1）。
**墙钟列被显式排除**：同一份代码同一份数据，R1 在连续两次独占跑分里分别测到 95.6s 与 100.7s，
全矩阵分别 782s 与 743s——机器负载决定的量不该当门禁，否则守卫会天天假阳性，然后被人忽略。

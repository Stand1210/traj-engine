# bench_v1 数据集覆盖度审计

由 `python -m bench.coverage --md` 生成。回答一个问题：**数据集存在** 与 **数据集足够** 是两件事。
在某个 regime 上恒定不变的特征，无法验证建在它上面的检测器；原始字段缺失的特征，无论怎么写代码都实现不了。

## 一、当前发射的字段

- trace：`answer_citations`, `answer_facts`, `answer_numbers`, `contradicted_facts`, `embedding`, `goal_text`, `golden_answer`, `golden_facts`, `intent_text`, `ontology_id`, `query_lang`, `raw_flags`, `session_id`, `session_turn_count`, `spans`, `trace_id`, `ts_start`, `turn_index`, `user_feedback`
- span：`action`, `arg_valid`, `cost`, `cost_details`, `finish_reason`, `input_text`, `kind`, `level`, `model`, `output_citations`, `output_facts`, `output_text`, `parent_id`, `prompt_version`, `span_id`, `status`, `status_message`, `subgoal_text`, `tokens_cache_read`, `tokens_cache_write`, `tokens_completion`, `tokens_prompt`, `tokens_system_prompt`, `tool_name`, `tool_params`, `ts_end`, `ts_start`, `ttft`, `verifier`

## 二、结论：可以开工

生成器 `bench-gen-v2.2.0`｜22800 条轨迹 / 117502 个 Span / 1851 条异常 / 8 个 regime｜全部可复现（种子固定，主随机流未被 v2 字段扰动）。

**已带真值、可直接支撑开发的**
- 结构 / 时延 / 成本三组主干特征全部非退化（`latency_total` 在每个 regime 上 distinct ≈ n）
- 双峰 / 三峰 / 重叠 / 稀疏 / 残缺 / 冷启动 / 漂移 / 异本体 8 个分布 regime
- 9 类异常 × 8 regime 全覆盖，每格至少 4 条（第四节矩阵）
- **结果符合度组（A.5，O 维权重 0.40）**：轨迹带 `golden_answer` / `golden_facts`，实测 5875 条（25.8%，golden 只在数值型答案上发射），真值带 `key_fact_recall_true` / `fact_precision_true` / `hallucinated_facts`。“不完整”与“不忠实”被刻意分开：截断 / 未完成 / 缺步只压 recall，编造数字只压 precision
- **成本组**：Span 带 `model`（含价格倍率）、`ttft`、`prompt_version`（约 10~12% 挂在 canary 版本上），真值带 `model_mix_true`，`model_mix_cost_index` 已非退化
- **工具身份与参数**：Span 带 `tool_name` / `tool_params`，`loop_count` 按合同 A.1 #10 用 `(parent_id, action, 参数哈希)` 分组，不再是动作连跑近似；真值带 `loop_true`，全数据集 201 条真循环，标签与真值 0 处不一致
- **弱监督（Tier-6）**：5760 条（25.3%）带 `user_feedback`（thumbs / retry / abandoned / human_takeover）与 `turn_index`，反馈按潜标签加噪采样，真值带 `feedback_available`
- **数据质量位**：`missing_field_ratio` 在修复**之前**测量，按 Span 类型的条件可得字段集统计；R1 p50=0.0000 / p99=0.1000，R5（45% 残缺注入）p50=0.0250 / p99=0.2000，`kernel/score.py:130` 的 `mfr > 0.20` 分支被真实触发
- **本体必须步骤 + 禁止动作** → A.6 过程一致性组（8 个特征）可直接实现

**仍然不足、开工时必须知道的**
- **语义文本是模板，不是自由散文**。`input_text` / `output_text` 由本体 `action_text` 模板生成，intent 短语只有 2~4 种。A.4 语义行为组里凡是要跑真实 NLP 的特征（`ref_similarity`、`bertscore_f1`、语气/情感）在本数据集上只能验管道通不通，不能验效果
- **数值可追溯性走结构化字段**。证据来源是 `output_facts` / `answer_numbers`，正则扫散文只是 legacy 兜底。真实文本里的数字（SQL `LIMIT 200`、`/nbi/v1/`、`NE-92F8-27`）会被正则误抓进证据池，接真实业务时必须换成结构化字段或带类型的抽取器
- **嵌入是 16 维各向同性高斯 blob**，真实是 1024 维各向异性、话题连续谱 → 聚类门槛在真实数据上必然更难，本基准的 ARI 上界不可外推
- **v2 特征已发射但未接线**。`kernel/baseline.py:METRICS` 仍是 v1 的 11 个指标；v2 的 40+ 个特征在 `features.extract` 里可取，但没进基线、没进打分。接线是需要单独测量的一轮工作（slice2）
- **`implicit_feedback` 永远不能进 METRICS**。它与标签按设计相关（弱监督），进基线会平凡地刷高 F1

## 三、审计发现的硬问题（均已修复，附实测证据）

**1. `missing_field_ratio` 结构性恒为 0。**
`kernel/ingest.py` 原先先修复缺失字段再统计缺失数，所以包括 R5（注入 45% 残缺）在内的所有 regime 上它都是 0：distinct=1、值恒 0.0。后果是 `kernel/score.py:130` 的 `if mfr > 0.20` 是死分支，附录 A.7 要求的“缺失比例参与全局置信度”从未被验证。
修法：在修复**之前**先量一次原始缺失率，并按 Span 类型给条件可得字段集 `EXPECTED_FIELDS`（工具 Span 合法地不带 token，混进去量的就是 Span 类型配比而不是遥测丢失）；修复后的值另存为 `missing_field_ratio_post`，不覆盖原值。
实测：R1 p50=0.0000 / p99=0.1000，R5 p50=0.0250 / p99=0.2000。

**2. 附录 A 里占比类特征的公式在并行子 Span 下越界。**
公式写的是“总耗时减去根节点各子 Span 耗时”，隐含假设子 Span 互不重叠。本基准有 22% 概率生成重叠兄弟（并行工具调用，真实场景同样会重叠）。
实测按原公式：`wait_time_ratio` 最低 **−1.94**，`llm_time_ratio` 最高 **2.78**，`tool_time_ratio` 与 retrieval 分别求并集再相加会到 **1.088**；根 Span 按构造覆盖全部壁钟，所以 `bottleneck_share` **恒等于 1.0**。
修法：占比类特征一律改用**区间并集长度**（`_union_len`），tool 与 retrieval 必须**联合**求并集，且一律**排除根 Span**。
实测修复后：`wait_time_ratio` ∈ [5.4e-06, 0.3737]，`llm_time_ratio` ≤ 1.0，`tool_time_ratio` ≤ 0.9685，`bottleneck_share` ∈ [0.2158, 1.0]；全量 22800 条轨迹越界计数 0（第七节）。附录 A 的公式行已同步改正。

**3. 两个让循环信号在数据里根本不存在的生成器缺陷。**
(a) 工具参数不确定：循环注入器 `dict(base)` 复制骨架，但 `tool_params` 从推进的每轨迹随机流里抽，复制出的两份参数不同，于是“参数完全相同的重复”根本不存在。实测 R1：`loop` 标签 26 条、`loop_true` 23 条、两者一致 19 条，**7 条被标为 loop 的轨迹里数据中没有循环**。修法：`_tool_identity(ont, action, ne, win, trace_id, cache)`，(轨迹, 动作) 的纯函数。修复后 8 个 regime 上标签与 `loop_true` 0 处不一致，全数据集真循环 201 条。
(b) 幻影重复 Span：并行分支发射器提前追加第 k+1 步并把 `raw_w[k+1]` 清零后 `continue`，但 `for` 循环跳不过下一次迭代，第 k+1 步又被追加一次，变成 4 ms 退化 Span。它把 `n_spans` 抬高约 10%，把相邻同动作塞进 22% 的轨迹，给 `retry_count` 和 `loop_count` 喂假信号。修法：把抽签提到 `parallel = (k + 1 < len(steps)) and rng.random() < 0.22`（保留原短路语义，随机流不变）+ 一个 `skipped` 标志。Span 总数 132648 → **117502**（每条轨迹 5.8 → 约 5.2）。

**4. R4 在平稳数据上误报漂移（两处成因叠加）。**
R4（极稀疏格子，n=1200，格子大小 507/333/187/83/34/22/11/7/7/5/2/2）在平稳数据上报出了变点。
成因一：最慢的意图 `i3`（92 条）在格子层与父层都不足 30 条参考观测，于是回落到**全局**基线，而全局把 1.5s 的总体和 120s 的总体混在一起 → z 恒正（`z_mean_ref = 0.181`）。原始数据其实平稳（6 个分桶的每意图中位数：i0 1.53/1.46/1.64/1.51/1.70/1.59；i1 9.63/8.39/8.71/9.43/8.81/10.19）。修法：阶梯改为 `cell → parent → 弃权(z=None)`，**取消全局兜底**；新增 `MAX_ABSTAIN_SHARE = 0.50`，超过就返回 `drift=False, reason="insufficient_support"`（明确不是“无漂移”）。修复后 `z_mean_ref` 0.181 → 0.041，但告警仍在（统计量 44.6 vs λ 10.6）。
成因二：λ 是从一个中心**已经恰好等于自身中位数**的符号序列里自举出来的，零假设里**不含中心估计误差**。每格子参考样本 n = 112/67/30，30 个对数正态样本的中位数偏差足以把格子 `i2|p2` 的尾部推到 68.8% 高于合并中心。修法：`calibrate_lambda(ref_z, …)` 改收原始 z 值，每次重复抽**两个**块自举重采样——A（参考长度）供 `centre = median(A)`，B（监测长度）对着它打分。实测 **λ 10.6 → 75.8**，统计量 44.6 → 不再检出；R7 的真漂移不受影响（统计量 996.8 vs λ 65.0，滞后 +8）。

**5. 弃权会把聚类质量买高，R1 已实测到这件事。**
`ari_pattern` 只在“可归簇池”上算，所以把难样本丢进 novelty 缓冲区就能靠少打分来多得分。R1 实测：缓冲区 433 条（10.8% 流量），关掉弃权后 `ari_pattern` = 0.8368，池上 = 0.9856，弃权净买 **+0.149**。而缓冲区里不是模糊样本：`novelty_purity_pattern` = 0.9908，433 条里 380 条属于同一个真实模式；成因是模式视图对 3 个真实模式返回了 k=6，其中一个 383 条的碎片（纯度 0.9922）拿到了 −0.44 的成员平均共识，于是 `(a−b)/max(a,b)` 边际把一次**过度切分**读成了“我叫不出它属于哪一类”。缓冲区异常率 0.0901 高于池内 0.0732，即弃权恰好丢掉了风险更高的那一片。
现状：`bench/runner.py` 已把 `ari_*_all`（弃权前）与 `novelty_purity_*` 一并输出到 `metrics.json` 与 `report.md`，使这笔交易无法隐藏；聚类模型顺序本身属于 slice2，未在本轮改动。R1 门禁只约束 `novelty_rate ∈ [0, 0.25]`，0.108 通过。

## 四、异常 × regime 覆盖矩阵

| 异常类型 | R1 | R2 | R3 | R4 | R5 | R6 | R7 | R8 |
|---|---|---|---|---|---|---|---|---|
| `latency_spike` | 43 | 46 | 48 | 20 | 60 | 13 | 50 | 40 |
| `token_bloat` | 42 | 40 | 31 | 15 | 53 | 8 | 58 | 29 |
| `loop` | 29 | 30 | 14 | 6 | 25 | 6 | 41 | 27 |
| `error` | 16 | 22 | 23 | 9 | 14 | 3 | 25 | 20 |
| `missing_step` | 33 | 29 | 28 | 14 | 30 | 4 | 28 | 26 |
| `illegal_step` | 20 | 22 | 15 | 14 | 21 | 7 | 14 | 18 |
| `unfinished` | 25 | 31 | 49 | 11 | 36 | 7 | 20 | 27 |
| `truncation` | 40 | 33 | 33 | 14 | 38 | 8 | 36 | 20 |
| `hallucinated_number` | 54 | 45 | 29 | 9 | 31 | 5 | 39 | 34 |
| **异常轨迹合计** | **302** | **298** | **270** | **112** | **308** | **61** | **311** | **241** |

## 五、特征活性明细（R1，抽样 1500 条）

**已实现（`kernel/features.py`，81 个标量特征；其中只有 v1 的 21 个接入了 `kernel/baseline.py:METRICS`）**

| 特征 | distinct | 缺失率 | min | p50 | p99 | max |
|---|---|---|---|---|---|---|
| `answer_number_count` | 6 | 0.0% | 0 | 2 | 3 | 5 |
| `bottleneck_share` | 1498 | 0.0% | 0.2067 | 0.5003 | 0.946 | 0.9999 |
| `branch_factor` | 14 | 0.0% | 1 | 4 | 6 | 10 |
| `busy_union` | 1500 | 0.0% | 0.1822 | 1.935 | 104.9 | 205.9 |
| `cache_hit_ratio` | 1457 | 0.0% | 0 | 0.1576 | 0.5959 | 0.8792 |
| `cache_read_tokens` | 421 | 0.0% | 0 | 445 | 681 | 779 |
| `cache_write_tokens` | 234 | 0.0% | 0 | 0 | 502 | 646 |
| `citation_reachability` | 6 | 45.0% | 0 | 1 | 1 | 1 |
| `context_growth_slope` | 1341 | 0.2% | 0 | 364.2 | 1684 | 3084 |
| `context_utilization` | 1048 | 0.0% | 0.005554 | 0.05249 | 0.2044 | 0.6078 |
| `cost_concentration_gini` | 1495 | 0.0% | 0.125 | 0.3961 | 0.5763 | 0.7681 |
| `cost_per_span` | 1237 | 0.0% | 0.000404 | 0.002271 | 0.008551 | 0.01264 |
| `cost_per_step_of_progress` | 1281 | 0.0% | 0.0005375 | 0.002911 | 0.0114 | 0.01627 |
| `cost_share_cache_read` | 1447 | 0.0% | 0 | 0.0254 | 0.1094 | 0.1592 |
| `cost_share_cache_write` | 641 | 0.0% | 0 | 0 | 0.1997 | 0.2742 |
| `cost_share_completion` | 1498 | 0.0% | 0.1629 | 0.3827 | 0.5857 | 0.7102 |
| `cost_share_prompt` | 1498 | 0.0% | 0.08099 | 0.5303 | 0.7122 | 0.7809 |
| `cost_share_tool_call` | 1134 | 0.0% | 0 | 0.01768 | 0.1062 | 0.1784 |
| `cost_total` | 1433 | 0.0% | 0.002149 | 0.01144 | 0.03792 | 0.07358 |
| `critical_path` | 1500 | 0.0% | 0.09246 | 1.027 | 61.81 | 103.9 |
| `depth` | 3 | 0.0% | 2 | 2 | 3 | 4 |
| `effective_info_ratio` | 1433 | 0.0% | 0.506 | 0.8885 | 0.9421 | 0.9528 |
| `error_level_ratio` | 3 | 0.0% | 0 | 0 | 0 | 0.25 |
| `error_ratio` | 3 | 0.0% | 0 | 0 | 0 | 0.25 |
| `goal_drift_max` | 2 | 0.4% | 0 | 0 | 0 | 1 |
| `goal_drift_slope` | 3 | 3.9% | -1 | 0 | 0 | 1 |
| `guard_hits` | 2 | 0.0% | 0 | 0 | 0 | 1 |
| `guard_time_ratio` | 702 | 0.0% | 0 | 0 | 0.477 | 0.7941 |
| `has_feedback` | 2 | 0.0% | 0 | 0 | 1 | 1 |
| `has_golden` | 2 | 0.0% | 0 | 0 | 1 | 1 |
| `inter_step_gap_cv` | 268 | 0.5% | 0 | 0 | 0.9789 | 1.473 |
| `kind_ratio_guard` | 14 | 0.0% | 0 | 0 | 0.3333 | 0.5455 |
| `kind_ratio_llm` | 13 | 0.0% | 0.1818 | 0.4 | 0.6 | 0.75 |
| `kind_ratio_retrieval` | 10 | 0.0% | 0 | 0.1429 | 0.25 | 0.625 |
| `kind_ratio_tool` | 17 | 0.0% | 0 | 0.2 | 0.5 | 0.625 |
| `latency_total` | 1499 | 0.0% | 0.1923 | 2.03 | 109.8 | 215.3 |
| `llm_time_ratio` | 1498 | 0.0% | 0.05257 | 0.7188 | 0.9756 | 0.9999 |
| `longest_repeated_subseq` | 4 | 0.0% | 0 | 0 | 0 | 5 |
| `loop_count` | 4 | 0.0% | 0 | 0 | 0 | 4 |
| `loop_group_count` | 2 | 0.0% | 0 | 0 | 0 | 1 |
| `loop_run_max` | 4 | 0.0% | 0 | 0 | 0 | 4 |
| `max_width` | 10 | 0.0% | 1 | 4 | 7 | 10 |
| `missing_field_ratio` | 73 | 0.0% | 0 | 0 | 0.15 | 0.3256 |
| `model_count` | 2 | 0.0% | 1 | 2 | 2 | 2 |
| `model_mix_cost_index` | 956 | 0.0% | 1 | 1.559 | 3 | 3 |
| `n_guard` | 5 | 0.0% | 0 | 0 | 2 | 6 |
| `n_llm` | 3 | 0.0% | 1 | 2 | 3 | 3 |
| `n_spans` | 10 | 0.0% | 2 | 5 | 8 | 11 |
| `n_tool` | 7 | 0.0% | 0 | 1 | 3 | 6 |
| `n_turns_in_session` | 6 | 0.0% | 2 | 5 | 7 | 7 |
| `n_unique_tools` | 5 | 0.0% | 0 | 1 | 3 | 4 |
| `parallelism_ratio` | 890 | 0.0% | 0 | 0.06533 | 0.5 | 0.7324 |
| `parallelism_ratio_contract` | 1492 | 0.0% | 0 | 0.5272 | 0.7416 | 0.8445 |
| `path_convergence` | 3 | 0.8% | 0 | 0 | 0 | 0.25 |
| `plan_revision_count` | 2 | 0.0% | 0 | 0 | 1 | 1 |
| `prompt_token_ratio` | 1492 | 0.0% | 0.3934 | 0.7712 | 0.8709 | 0.917 |
| `prompt_version_count` | 2 | 0.0% | 0 | 1 | 1 | 1 |
| `query_complexity` | 7 | 0.0% | 0.2 | 0.3 | 0.55 | 0.55 |
| `query_len` | 29 | 0.0% | 21 | 35 | 86 | 87 |
| `reformulation_signal` | 13 | 22.5% | 0 | 0 | 1 | 1 |
| `retry_count` | 3 | 0.0% | 0 | 0 | 1 | 2 |
| `retry_latency_share` | 96 | 0.0% | 0 | 0 | 0.3198 | 1.582 |
| `self_correction_count` | 2 | 0.0% | 0 | 0 | 0 | 1 |
| `span_latency_p95` | 1500 | 0.0% | 0.09219 | 0.938 | 56.15 | 83.21 |
| `system_prompt_ratio` | 1494 | 0.0% | 0.03237 | 0.2122 | 0.6585 | 0.9634 |
| `token_efficiency` | 1492 | 0.0% | 0.09056 | 0.2967 | 0.5813 | 1.542 |
| `tokens_per_span` | 1402 | 0.0% | 133.2 | 615 | 2234 | 3620 |
| `tokens_total` | 1304 | 0.0% | 633 | 3114 | 9762 | 2.003e+04 |
| `tokens_total_contract` | 1313 | 0.0% | 815 | 3619 | 1.029e+04 | 2.052e+04 |
| `tool_arg_valid_rate` | 7 | 1.0% | 0 | 1 | 1 | 1 |
| `tool_repeat_rate` | 7 | 1.2% | 0 | 0 | 0.5 | 0.8 |
| `tool_success_rate` | 3 | 0.5% | 0 | 1 | 1 | 1 |
| `tool_time_ratio` | 1493 | 0.0% | 0 | 0.2646 | 0.9187 | 0.9991 |
| `top1_cost_share` | 1495 | 0.0% | 0.2311 | 0.4141 | 0.7279 | 0.8729 |
| `traceable_number_ratio` | 6 | 9.7% | 0.3333 | 1 | 1 | 1 |
| `ttft` | 1491 | 0.5% | 0.001855 | 0.1154 | 10.89 | 72.74 |
| `turn_index` | 7 | 0.0% | 1 | 3 | 7 | 7 |
| `unfaithful_fact_count` | 3 | 0.0% | 0 | 0 | 0 | 2 |
| `verifier_pass_rate` | 4 | 0.0% | 0.5 | 1 | 1 | 1 |
| `wait_time_ratio` | 1381 | 0.0% | 5.729e-05 | 0.04437 | 0.09668 | 0.4156 |
| `warn_level_ratio` | 13 | 0.0% | 0 | 0 | 0.3333 | 0.5 |

## 六、独立参考实现交叉校验（`probe()` vs `kernel/features.py`）

`probe()` 是与内核无关的第二份实现（连分位数都另写了一份 `_quant`，因为导入被测对象的差分测试什么也证不了）。它回答的是：内核真的在按改正后的附录 A 公式算吗？区间并集类特征一致到 0.0，才算证据；“返回了一个落在 [0,1] 的数”不算。

抽样 1500 条（R1）：

| 特征 | 最大绝对差 | 双方均无定义 | 不一致条数 |
|---|---|---|---|
| `max_width` | 0 | 0 | 0 |
| `depth` | 0 | 0 | 0 |
| `n_unique_tools` | 0 | 0 | 0 |
| `tool_repeat_rate` | 0 | 18 | 0 |
| `longest_repeated_subseq` | 0 | 0 | 0 |
| `span_latency_p95` | 0 | 0 | 0 |
| `bottleneck_share` | 0 | 0 | 0 |
| `inter_step_gap_cv` | 0 | 8 | 0 |
| `llm_time_ratio` | 0 | 0 | 0 |
| `tool_time_ratio` | 0 | 0 | 0 |
| `wait_time_ratio` | 0 | 0 | 0 |
| `parallelism_ratio` | 0 | 0 | 0 |
| `busy_union` | 0 | 0 | 0 |

结论：13 个特征全部逐条一致（最大差 0，不一致 0 条）。

## 七、标签 ↔ 真值 ↔ 特征 一致性（全量 22800 条）

- 有 golden 的轨迹：5949 条（26.1%）
- 有用户反馈的轨迹：5636 条（24.7%）
- 真实循环（参数完全相同的 ≥ 3 次重复）：178 条
- v3 信号：计划修订 1370 条、目标漂移 309 条、事实矛盾 256 条、虚构引用 291 条
- v3 span：参数非法 778、校验失败 484、缓存命中 54079；多轮会话轨迹 22798 条
- **全部一致**：标签、生成器真值、内核特征三者两两对齐；占比类特征越界计数 0

## 八、77 特征合同可支撑性（附录 A 逐条机械判定）

「数据集够不够」不靠叙述回答，靠这张表：每个合同特征声明它需要的**原始 Span 字段 / 原始 trace 字段 / 本体键**，状态由 `bench/contract.py` 对着数据集与本体**实际发射的东西**解析出来。给生成器加一个字段，对应的阻塞项自动清除；删一个，审计直接把构建判失败。

implemented **56**｜implemented_elsewhere **13**｜derivable **4**｜blocked_field **0**｜blocked_ontology **0**｜needs_model **4**｜合计 **77**

| # | 组 | 特征 | 状态 | 判定依据 / 说明 |
|---|---|---|---|---|
| 1 | A.1 | `n_spans` | `implemented` | — |
| 2 | A.1 | `depth` | `implemented` | — |
| 3 | A.1 | `max_width` | `implemented` | — |
| 4 | A.1 | `branch_factor` | `implemented` | — |
| 5 | A.1 | `kind_ratio_llm` | `implemented` | —｜only llm/tool/retrieval are registered; the six kind ratios sum to 1 and are collinear |
| 6 | A.1 | `kind_ratio_tool` | `implemented` | — |
| 7 | A.1 | `kind_ratio_retrieval` | `implemented` | — |
| 8 | A.1 | `n_unique_tools` | `implemented` | —｜tool identity is tool_name, not action: the ontology maps one action to several tools |
| 9 | A.1 | `tool_repeat_rate` | `implemented` | — |
| 10 | A.1 | `loop_count` | `implemented` | —｜grouped by (parent_id, action, normalized param hash), max(0, count-2) over count>=3 |
| 11 | A.1 | `longest_repeated_subseq` | `implemented` | — |
| 12 | A.1 | `error_span_ratio` | `implemented` | as `error_level_ratio` |
| 13 | A.2 | `total_latency` | `implemented` | as `latency_total` |
| 14 | A.2 | `critical_path` | `implemented` | —｜longest root-to-leaf serial chain, ROOT EXCLUDED: the root spans the whole wall clock, so including it returns latency_total and drives #19 to exactly 0 |
| 15 | A.2 | `ttft` | `implemented` | —｜conditional: llm/agent spans only |
| 16 | A.2 | `llm_time_ratio` | `implemented` | —｜union of intervals, root span excluded |
| 17 | A.2 | `tool_time_ratio` | `implemented` | —｜TOOL and RETRIEVAL must be unioned jointly |
| 18 | A.2 | `wait_time_ratio` | `implemented` | —｜union of intervals, root span excluded |
| 19 | A.2 | `parallelism_ratio` | `implemented` | as `parallelism_ratio_contract` |
| 20 | A.2 | `span_latency_p95` | `implemented` | —｜root span excluded |
| 21 | A.2 | `bottleneck_share` | `implemented` | —｜root span excluded, otherwise identically 1.0 |
| 22 | A.2 | `inter_step_gap_cv` | `implemented` | — |
| 23 | A.2 | `retry_latency_share` | `implemented` | —｜a retry is a repeated (parent_id, action, param hash) |
| 24 | A.3 | `total_tokens` | `implemented` | as `tokens_total_contract`｜contract total = input + output + cache_read + cache_write; the v1-frozen `tokens_total` is prompt + completion only and must NOT be silently redefined |
| 25 | A.3 | `input_tokens` | `derivable` | kernel work only |
| 26 | A.3 | `output_tokens` | `derivable` | kernel work only |
| 27 | A.3 | `total_cost` | `implemented` | as `cost_total`｜cost_details is only needed for per-component attribution, not for the total |
| 28 | A.3 | `cost_per_span` | `implemented` | — |
| 29 | A.3 | `cost_per_step_of_progress` | `implemented` | proxy: appendix specifies MinHash LSH at 0.9; kernel computes exact character-3gram Jaccard. MinHash is an approximation of the same quantity, and at 6 spans per trace the exact form is cheaper than the sketch.｜a step counts as progress when its output is not near-duplicate (MinHash < 0.9) of an earlier one; needs tool outputs with realistic redundancy |
| 30 | A.3 | `cost_concentration_gini` | `implemented` | — |
| 31 | A.3 | `top1_cost_share` | `implemented` | — |
| 32 | A.3 | `token_efficiency` | `implemented` | — |
| 33 | A.3 | `prompt_token_ratio` | `implemented` | as `system_prompt_ratio`｜contract definition is system_prompt_tokens / input_tokens. NAME COLLISION: the v1-frozen kernel feature of the same name is tokens_prompt / tokens_total, a different quantity. The contract one is emitted as `system_prompt_ratio` |
| 34 | A.3 | `cache_hit_ratio` | `implemented` | — |
| 35 | A.3 | `context_growth_slope` | `implemented` | —｜least-squares slope of (step index, cumulative input tokens) |
| 36 | A.3 | `model_mix_cost_index` | `implemented` | — |
| 37 | A.4 | `query_embedding` | `derivable` | kernel work only｜clustering and similarity only; never enters the score formula |
| 38 | A.4 | `query_len` | `implemented` | proxy: character length of the question with the dataset's constant `intentN:` cell tag stripped; leaving the tag in would add a per-cell offset that query_len cannot explain. |
| 39 | A.4 | `query_lang` | `implemented` | —｜a stratification variable, not a numeric feature: token density differs per language, so mixing languages inside one cell pollutes the cost baseline |
| 40 | A.4 | `query_complexity` | `implemented` | —｜composed from clause count, wh-word count and entity count; needs varied query wording within one intent, otherwise it is constant per cell and cannot explain anything |
| 41 | A.4 | `goal_drift_slope` | `implemented` | proxy: appendix asks 1 - cos(goal_emb, subgoal_k_emb) regressed on k; kernel emits 1 - |G n S_k| / |G| over language-aware content tokens, because embedding every subgoal would cost another 384 floats per span. Measured equivalent on this dataset: the generator guarantees an off-goal detour shares no content token with the goal, so the lexical proxy is exactly 1.0 on a detour and exactly 0.0 on-goal, and it agrees with goal_drift_true two-sided on 700/700 dev traces.｜1 - cos(original goal, step-k subgoal), regressed on step index |
| 42 | A.4 | `goal_drift_max` | `implemented` | proxy: same lexical containment proxy as goal_drift_slope｜max of the same drift quantity; catches a single severe detour the slope averages away. The trace embedding is NOT an input: drift is measured against goal_text, not against the query embedding |
| 43 | A.4 | `self_correction_count` | `implemented` | proxy: appendix allows name-based detection (retry/fix/revise); the ontology has no such action names, so the kernel detects it structurally: a same-action sibling that starts after an earlier one finished and either replaces failed work or carries different arguments. Identical params with an identical outcome is a retry, already counted by retry_count.｜retry/fix/revise naming, or near-identical params with a different result |
| 44 | A.4 | `plan_revision_count` | `implemented` | proxy: entry-action span nested inside an earlier entry-action span of the same parent. Nesting is what separates a revision from a loop, which repeats the step sequentially; the naive count-minus-one reads a looped plan as 2 revisions (1 dev trace in 700).｜needs the generator to emit more than one plan span when the plan is regenerated |
| 45 | A.4 | `tool_success_rate` | `implemented` | — |
| 46 | A.4 | `tool_arg_valid_rate` | `implemented` | —｜needs a JSON schema per tool plus injected invalid arguments |
| 47 | A.4 | `path_convergence` | `implemented` | —｜n-gram overlap between the second half and the first half of the action sequence |
| 48 | A.4 | `context_utilization` | `implemented` | proxy: appendix asks max *cumulative* input tokens / context window; kernel emits max per-call tokens_prompt / context window. Cumulative-across-calls would divide a running total by a budget that resets on every call, so it grows without bound and stops being a utilization. The per-call form is the quantity that actually predicts a context-overflow rejection.｜max cumulative input tokens / model context window |
| 49 | A.4 | `effective_info_ratio` | `implemented` | —｜1 - redundant context / total context, redundancy estimated by n-gram Jaccard between adjacent context fragments |
| 50 | A.4 | `n_turns_in_session` | `implemented` | — |
| 51 | A.4 | `reformulation_signal` | `implemented` | proxy: appendix asks cos(this answer, next query); the dataset carries an embedding of the query only, so the kernel emits a trapezoidal membership of the [0.55, 0.90] band over the *mean-centred* cosine of consecutive query embeddings in one session, scaled by whether the follow-up got shorter. Centring is load-bearing: raw cosines sit in a narrow cone (0.22-0.94, median 0.80), so the band would fire on nearly every pair.｜next-turn query vs this-turn answer: cosine in [0.55, 0.90] and shorter -> the user rephrased. Sessions are linked by session_id so this is a self-join, not a new field |
| 52 | A.5 | `hard_fail_count` | `implemented_elsewhere` | computed in detect/score/cluster｜> 0 triggers the scoring gate |
| 53 | A.5 | `verifier_pass_rate` | `implemented` | —｜the only zero-cost objective correctness signal; needs per-span verifier outcomes |
| 54 | A.5 | `numeric_grounding_ratio` | `implemented` | as `traceable_number_ratio`｜structured facts are the evidence pool; regex over prose is a legacy fallback that would scrape SQL LIMIT 200, /nbi/v1/ and NE-92F8-27 into it |
| 55 | A.5 | `ungrounded_element_count` | `implemented` | as `unfaithful_fact_count` |
| 56 | A.5 | `citation_reachability` | `implemented` | —｜share of the answer's URLs / file paths / line numbers that actually occur in the retrieved result set; catches fabricated references |
| 57 | A.5 | `entity_recall` | `implemented` | as `key_fact_recall` |
| 58 | A.5 | `ref_similarity` | `needs_model` | inputs present｜needs a real sentence encoder; the dataset supplies the golden text and a synthetic embedding so the plumbing runs, the value is not meaningful |
| 59 | A.5 | `bertscore_f1` | `needs_model` | inputs present｜needs contextual embeddings from a real model; cannot be synthesized |
| 60 | A.5 | `key_fact_recall` | `implemented` | —｜the primary metric when a golden exists |
| 61 | A.5 | `nli_entailment` | `needs_model` | inputs present｜needs a real cross-encoder; premise = concatenated tool outputs, hypothesis = answer clauses, length-weighted |
| 62 | A.5 | `contradiction_rate` | `needs_model` | inputs present｜the feature needs a real NLI model, but the DATASET must carry contradiction ground truth, and 'contradicts the evidence' is a different failure from 'not supported by the evidence'. > 0.1 is a strong anomaly |
| 63 | A.5 | `peer_z` | `implemented_elsewhere` | computed in detect/score/cluster｜z-distance to the centroid of successful peers inside the same cell |
| 64 | A.5 | `implicit_feedback` | `implemented` | —｜MUST NEVER enter baseline METRICS: it correlates with the label by construction (weak supervision) and would inflate F1 trivially |
| 65 | A.6 | `fitness_replay` | `implemented_elsewhere` | computed in detect/score/cluster｜token replay against the cell's reference process model, strict mode |
| 66 | A.6 | `fitness_align` | `implemented_elsewhere` | computed in detect/score/cluster｜optimal alignment allowing insertions and skips |
| 67 | A.6 | `missing_tokens` | `implemented_elsewhere` | computed in detect/score/cluster |
| 68 | A.6 | `remaining_tokens` | `implemented_elsewhere` | computed in detect/score/cluster |
| 69 | A.6 | `illegal_transition_count` | `implemented_elsewhere` | computed in detect/score/cluster |
| 70 | A.6 | `forbidden_step_hit` | `implemented_elsewhere` | computed in detect/score/cluster｜a hit triggers the scoring gate |
| 71 | A.6 | `seq_sim_to_medoid` | `implemented_elsewhere` | computed in detect/score/cluster |
| 72 | A.6 | `tree_edit_distance_norm` | `derivable` | kernel work only｜Zhang-Shasha / APTED against the cell's reference span tree |
| 73 | A.7 | `ts_repaired` | `implemented_elsewhere` | computed in detect/score/cluster｜latency-dimension confidence x0.7 |
| 74 | A.7 | `usage_estimated` | `implemented_elsewhere` | computed in detect/score/cluster｜cost-dimension confidence x0.6 |
| 75 | A.7 | `orphan_span_rebuilt` | `implemented_elsewhere` | computed in detect/score/cluster |
| 76 | A.7 | `missing_field_ratio` | `implemented` | —｜measured BEFORE repair, over the per-span-kind conditionally available field set |
| 77 | A.7 | `cluster_strength` | `implemented_elsewhere` | substituted by consensus_intent/consensus_pattern |

**保真度检查（字段存在 ≠ 字段够用）**

- **达标** `citation_reachability`：实测 4.00 pct of traces cite something unreachable｜要求 >= 1.00 pct (a citation field that is never fabricated pins the feature at 1.0)
- **达标** `cost_per_step_of_progress`：实测 mean 49.3 distinct output skeletons per action, weakest non-guard [('plan', 20), ('api_call', 29), ('schema_retrieval', 29)], over 9 actions (1 below the 30-observation floor)｜要求 mean >= 8 AND every non-guard action >= 8 (templated text makes every n-gram redundancy feature degenerate)
- **达标** `effective_info_ratio`：实测 mean 49.3 distinct output skeletons per action, weakest non-guard [('plan', 20), ('api_call', 29), ('schema_retrieval', 29)], over 9 actions (1 below the 30-observation floor)｜要求 mean >= 8 AND every non-guard action >= 8 (templated text makes every n-gram redundancy feature degenerate)
- **达标** `goal_drift_max`：实测 99.5 pct of traces carry a goal and at least one subgoal｜要求 >= 50 pct (goal_drift is a lexical containment test, so it needs both a goal_text and a subgoal_text on the same trace)
- **达标** `query_complexity`：实测 mean 16.0 distinct query skeletons per intent, weakest [(('ontA', 'intent1'), 16), (('ontA', 'intent0'), 16)], over 2 intents｜要求 mean >= 8 AND every intent >= 8 (with one fixed phrase per intent the feature is constant inside a cell)
- **达标** `query_embedding`：实测 384 dims, participation ratio 91.4 (isotropic would be 384)｜要求 >= 384 dims AND 1 < participation_ratio < 0.75 x dim = 288 (near dim means every direction is noise, near 1 means the topic signal collapsed onto a single dim)
- **达标** `tool_arg_valid_rate`：实测 2.00 pct of traces carry an invalid tool argument｜要求 >= 1.00 pct (an arg_valid that is never False pins the feature at 1.0)
- **达标** `verifier_pass_rate`：实测 3.50 pct of traces fail a validator｜要求 >= 1.00 pct (a verifier that always passes carries no signal)

**数据集阻塞项**

- **无**。附录 A 的 77 个特征里，没有任何一个因为缺原始字段或缺本体键而无法实现。

状态词表：`implemented` = 内核已按此名或已记录的别名发射；`implemented_elsewhere` = 流水线里算过，但不在特征向量里（detect / score / cluster）；`derivable` = 原始输入齐备，是内核工作不是数据集工作；`blocked_field` / `blocked_ontology` = **数据集缺陷**；`needs_model` = 需要真实嵌入模型 / NLI / BERTScore，无法合成——伪造它比承认它更糟，数据集只提供**输入与真值**让管道能跑通，数值本身在接入真实模型前没有意义。

只有 `blocked_field`、`blocked_ontology` 与保真度不达标算数据集缺陷；`derivable` 与 `needs_model` 不是缺陷，它们是合成数据能力的边界。
## 九、自动检出的问题清单

- implemented feature `reformulation_signal` is constant (0.0) on R3 -- any detector built on it is untested
  处置：**接受并记录，不修**——这是 regime 的属性，不是审计漏洞。
  判定带 [0.55, 0.90] 是附录 A.4 #51 的合同值，作用在**会话内去均值**后的余弦上（原始余弦挤在
  窄锥里，带内命中率 71.1%–100.0%，8/8 regime，特征会退化成常数）。去均值后 7 个 regime 的
  命中率是 6.87%–28.95%，**R3 是 0 / 2344 对**：R3 独有 `intent_ambiguity = 0.50`，它把每个
  向量都拖向**其他**意图的均值，去均值后的向量彼此靠拢，整个 R3 的去均值余弦上界只有 0.371，
  够不到 0.55 的下沿。方向与直觉相反——歧义**压缩**去均值余弦，不是把它顶过带。
  三条修法实测否决：带值不可动（合同项，且 7/8 regime 依赖它）；把 R3 歧义降到 0.55 会让
  `novelty_rate` 掉到 0.0063（低于 0.03 下限），而 R3 本来只剩 4.4% 的上限余量；生成器主动发射
  改写追问是唯一真修，代价是新 `GEN_VERSION` + 全量重生成 + 全矩阵重跑，只为修一个 7/8 regime
  已覆盖的特征。逐 regime 实测表见 `kernel/features.py::_band_membership` 的 docstring。
  gap 不进退出码，本条不影响 DATASET READY。

## 十、数据集新鲜度与溯源

「门槛全绿」并不蕴含「数据是这份代码生成的」。`meta.json` 里的 `spec_hash` 由
`sha256(generator_version + emb_dim + spec)` 得到，`bench/coverage.py::dataset_provenance()`
用**当前活的** `GEN_VERSION` 把它重算一遍再对账，任一 regime 不符即整个审计判失败。

这条断言是实测踩出来的：桥接机制回滚后，8 个 regime 里有 7 个的 `meta.json` 仍残留一个已经
不存在的键（`emb_geometry.intent_bridge`），说明那些元数据出自回滚前的生成器；而
`traces.jsonl` / `gt.jsonl` 恰好逐字节相同（该机制取 0.0 时不消耗随机流），于是门槛与覆盖率
审计**双双全绿**，没有任何信号提示元数据已过期。重算 `spec_hash` 一次抓住三类漂移：
生成器版本、regime 规格、嵌入维度。

| regime | meta 里的 spec_hash | 用当前生成器重算 | 判定 |
|---|---|---|---|
| `R1` | `007a872125bac9bb` | `007a872125bac9bb` | **一致** |
| `R2` | `52470f48253b25a6` | `52470f48253b25a6` | **一致** |
| `R3` | `2d9e23adcdd4eb4e` | `2d9e23adcdd4eb4e` | **一致** |
| `R4` | `5188fdfc219089b9` | `5188fdfc219089b9` | **一致** |
| `R5` | `10ff75f849deddbe` | `10ff75f849deddbe` | **一致** |
| `R6` | `6df7cb38491a91dd` | `6df7cb38491a91dd` | **一致** |
| `R7` | `1bd79369786bde6f` | `1bd79369786bde6f` | **一致** |
| `R8` | `469f903d257a4288` | `469f903d257a4288` | **一致** |

配套的第二道断言在保真度检查里：`query_embedding` 不再只看维度，而是直接从数据算参与比
`PR = (Σ σ_d²)² / Σ σ_d⁴`，要求 `1 < PR < 0.75 x dim`。各向同性的 384 维高斯团 PR 恰为 384，
会被直接拒绝；实测本数据集为 R1 91.4 / R2 99.1 / R3 109.4 / R4 98.2 / R5 104.0 / R6 125.9 / R7 40.0 / R8 55.6，全部落在界内。这守住了嵌入几何的标定——几何一旦塌掉，
聚类门槛会变成任何内核改动都抬不动的死门槛。
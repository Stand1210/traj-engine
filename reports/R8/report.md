# 基准跑分报告 R8 - foreign ontology

- 流水线版本 `slice1-v0.1.0`｜数据集 `469f903d257a4288`｜代码 `e2e2a7670771ce5a`｜n=3000（可归簇 2930，覆盖率 0.977）｜冷启动 False｜墙钟 73.7s
- 生成器真值：真实格子数 9｜异常率 0.0803｜异常类型 {"error": 20, "hallucinated_number": 34, "illegal_step": 18, "latency_spike": 40, "loop": 27, "missing_step": 26, "token_bloat": 29, "truncation": 20, "unfinished": 27}
- 端到端时延分布 p50/p90/p99 = 4.27 / 68.90 / 166.05

## 1 聚类（共识双视图 -> 分析格子）

| 指标 | 值 |
|---|---|
| ari_intent | 1.0000 |
| ari_pattern | 0.9723 |
| ari_cell | 0.9852 |
| nmi_intent | 1.0000 |
| nmi_pattern | 0.9474 |
| purity_intent | 1.0000 |
| purity_pattern | 0.9904 |
| ARI 弃权前 / 弃权后（意图 / 模式 / 格子） | 1.0000 -> 1.0000 / 0.9721 -> 0.9723 / 0.9850 -> 0.9852 |
| novelty 缓冲区内 多数真实类占比（意图 / 模式） | 1.0000 / 0.9857 |
| novelty 缓冲区异常率 / 可归簇池异常率 | 0.0714 / 0.0805 |
| 意图簇数 / 真实 | 3 / 3 |
| 模式簇数 / 真实 | 3 / 3 |
| 格子数 / 真实 | 9 / 9 |
| novelty 率 | 0.0233 |
| 意图视图信息上界（oracle，同池 / 全量） | 1.0000 / 1.0000 |
| 模式视图信息上界（oracle，同池 / 全量） | 0.9978 / 0.9979 |
| 上界达成率（意图 / 模式） | 1.0000 / 0.9745 |

## 2 异常识别（L1 稳健z / L2 ECOD / L4 结构 / L5 马尔可夫 + BH-FDR 决策）

| 指标 | 可归簇池 | 全量 |
|---|---|---|
| precision | 0.9942 | 0.9942 |
| recall | 0.7246 | 0.7095 |
| f1 | 0.8382 | 0.8281 |
| fpr | 0.0004 | 0.0004 |

- 排序质量：AUC(a_raw)=0.9220｜PR-AUC=0.8435｜Precision@50=1.0000｜Recall@50=0.2119
- 分诊分层：tier2 确定性违规 152｜tier1 统计拒绝 20｜tier0 其余 2758｜剔除 tier2 后 Precision@50=0.5400（该子池异常基率 0.0306，提升 17.65 倍）
- 告警构成：总计 172（统计 21 + 硬规则 152）｜BH alpha=0.200｜折算 57.33 条/日
- 运营口径（唯一会主动打扰人的通道）：日预算 5 条 x 3 天 = k=15，Precision=1.0000
- 漂移监测：未检出变点｜统计量 -7.20 vs 自举阈值 42.53（alpha=0.01，bootstrap）｜最短窗长 120｜命中窗 null｜窗内高于参考中位数占比 n/a
- 三通道口径区分：告警流 k=15（会主动打扰人，Precision=1.0000）｜审计流 152 条确定性违规（50.7 条/日，落库待查不呼叫）｜复核队列 172 条（BH-FDR alpha=0.20，受人工复核预算约束）
- 池化回退：格子层权重 B<0.5 的占比 0.000（检测层非 L3 占比 0.023）
- 本体绑定：3/3 个模式簇绑定到声明模式 {"0": "b1", "1": "b2", "2": "b3"}
- span 级归因（诊断，slice2 才设门槛）：Precision=0.643 Recall=0.350 tp=83 fp=46 fn=154

| 异常类型 | 样本 | 命中 | 召回 | 统计通道 | 规则通道 |
|---|---|---|---|---|---|
| normal | 2694 | 1 | 0.000 | 0 | 1 |
| latency_spike | 39 | 9 | 0.231 | 9 | 0 |
| hallucinated_number | 34 | 19 | 0.559 | 0 | 19 |
| token_bloat | 28 | 11 | 0.393 | 11 | 0 |
| unfinished | 27 | 27 | 1.000 | 0 | 27 |
| loop | 26 | 26 | 1.000 | 1 | 26 |
| missing_step | 26 | 23 | 0.885 | 0 | 23 |
| truncation | 20 | 20 | 1.000 | 0 | 20 |
| error | 18 | 18 | 1.000 | 0 | 18 |
| illegal_step | 18 | 18 | 1.000 | 0 | 18 |

## 3 打分（5 维 x 4 锚点 x 硬门禁 x LMDI 零残差）

- 零残差最大偏差 `9.370e-14`（恒等式 sum(contrib) == S - 100G）
- 分数区分度：AUC(-S vs 异常)=0.8436｜正常均分 89.69｜异常均分 53.37｜分离度 36.31
- 与生成器 oracle 维度分的相关：Spearman=0.7551｜Kendall tau-b=0.5617

| 维度 | Spearman(vs oracle) | 正常均值 | 异常均值 |
|---|---|---|---|
| O | 0.2886 | 0.977 | 0.887 |
| P | 0.8863 | 0.999 | 0.884 |
| L | 0.6832 | 0.770 | 0.718 |
| C | 0.9248 | 0.768 | 0.715 |
| R | 0.3754 | 0.982 | 0.938 |

- 绝对档位分布 {"A": 1690, "B": 1001, "D": 248, "C": 61}
- 相对档位分布 {"B": 1050, "A": 754, "C": 751, "D": 445}
- 门禁触发次数 {"novelty": 70, "t1_unfinished": 57, "t0_result_broken": 25, "loop_runaway": 19, "forbidden_action": 18, "t2_untraceable_number": 14, "guard_violation": 10}

## 4 校准（交叉拟合，出折外 ECE）

- 方法 platt｜标注数 300｜ECE(出折)=0.0333｜ECE(原始 a_raw)=0.1445｜AUC(校准概率)=0.8451

| bin | n | 预测均值 | 实际频率 |
|---|---|---|---|
| 0 | 255 | 0.051 | 0.027 |
| 1 | 27 | 0.135 | 0.259 |
| 2 | 1 | 0.204 | 0.000 |
| 8 | 1 | 0.864 | 1.000 |
| 9 | 16 | 0.981 | 1.000 |

## 5 数据质量与漂移

- 采集缺陷召回（规范化侧检出率）{"ts_repaired": 1.0, "usage_estimated": 1.0, "orphan_rebuilt": 1.0}
- 真实缺陷轨迹数 {"ts_repaired": 76, "usage_estimated": 123, "orphan_rebuilt": 55}｜被降级置信度的轨迹 202｜降级率 1.0000
- 漂移：spec=null｜检出=False｜index=None｜真实 index=None｜滞后占比=n/a｜嫌疑轨迹 0

## 6 门槛表（contracts/schemas.md 8）

| 门槛 | 要求 | 实测 | 结论 |
|---|---|---|---|
| ari_intent | >=0.650 (table 0.65, oracle ceiling 1.0000) | 1.0000 | PASS |
| ari_pattern | >=0.550 (table 0.55, oracle ceiling 0.9978) | 0.9723 | PASS |
| ece | <=0.10 | 0.0333 | PASS |
| f1 | >=0.65 | 0.8382 | PASS |
| fpr | <=0.06 | 0.0004 | PASS |
| no_false_drift | detected=false | detected=False stat=-7.20 lambda=42.53 | PASS |
| no_hardcoded_actions | [] | [] | PASS |
| novelty_rate | [0.00,0.25] | 0.023 | PASS |
| operator_stream_precision | >=0.80 @k=15/day=5 | 1.0000 | PASS |
| precision_at_50 | >=0.75 | 1.0000 | PASS |
| zero_residual | <=1e-06 | 9.370e-14 | PASS |

**总体：全部通过**

- 计时 {"ingest_features": 3.73, "cluster": 68.04, "baseline": 0.21, "detect": 0.71, "score": 0.08}


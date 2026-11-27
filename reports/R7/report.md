# 基准跑分报告 R7 - mid-stream drift x1.6

- 流水线版本 `slice6-v0.6.0`｜数据集 `1bd79369786bde6f`｜代码 `d229ab802e5a01bf`｜n=4000（可归簇 3964，覆盖率 0.991）｜冷启动 False｜墙钟 99.1s
- 生成器真值：真实格子数 6｜异常率 0.0777｜异常类型 {"error": 25, "hallucinated_number": 39, "illegal_step": 14, "latency_spike": 50, "loop": 41, "missing_step": 28, "token_bloat": 58, "truncation": 36, "unfinished": 20}
- 端到端时延分布 p50/p90/p99 = 2.55 / 77.04 / 194.25

## 1 聚类（共识双视图 -> 分析格子）

| 指标 | 值 |
|---|---|
| ari_intent | 1.0000 |
| ari_pattern | 0.9537 |
| ari_cell | 0.9569 |
| nmi_intent | 1.0000 |
| nmi_pattern | 0.9533 |
| purity_intent | 1.0000 |
| purity_pattern | 0.9990 |
| ARI 弃权前 / 弃权后（意图 / 模式 / 格子） | 1.0000 -> 1.0000 / 0.9495 -> 0.9537 / 0.9536 -> 0.9569 |
| novelty 缓冲区内 多数真实类占比（意图 / 模式） | 1.0000 / 0.8889 |
| novelty 缓冲区异常率 / 可归簇池异常率 | 0.5000 / 0.0739 |
| 意图簇数 / 真实 | 2 / 2 |
| 模式簇数 / 真实 | 5 / 3 |
| 格子数 / 真实 | 8 / 6 |
| novelty 率 | 0.0090 |
| 意图视图信息上界（oracle，同池 / 全量） | 1.0000 / 1.0000 |
| 模式视图信息上界（oracle，同池 / 全量） | 0.9969 / 0.9953 |
| 上界达成率（意图 / 模式） | 1.0000 / 0.9566 |

## 2 异常识别（L1 稳健z / L2 ECOD / L4 结构 / L5 马尔可夫 + BH-FDR 决策）

| 指标 | 可归簇池 | 全量 |
|---|---|---|
| precision | 0.9865 | 0.9865 |
| recall | 0.7509 | 0.7074 |
| f1 | 0.8527 | 0.8240 |
| fpr | 0.0008 | 0.0008 |

- 排序质量：AUC(a_raw)=0.9453｜PR-AUC=0.8695｜Precision@50=1.0000｜Recall@50=0.1706
- 分诊分层：tier2 确定性违规 179｜tier1 统计拒绝 44｜tier0 其余 3741｜剔除 tier2 后 Precision@50=0.9000（该子池异常基率 0.0301，提升 29.88 倍）
- 告警构成：总计 223（统计 44 + 硬规则 179）｜BH alpha=0.200｜折算 74.33 条/日
- 运营口径（唯一会主动打扰人的通道）：日预算 5 条 x 3 天 = k=15，Precision=1.0000
- 漂移监测：检出变点 index=2001｜统计量 981.10 vs 自举阈值 14.62（alpha=0.01，bootstrap）｜最短窗长 160｜命中窗 [2001, 3999]｜窗内高于参考中位数占比 0.795
- 三通道口径区分：告警流 k=15（会主动打扰人，Precision=1.0000）｜审计流 179 条确定性违规（59.7 条/日，落库待查不呼叫）｜复核队列 223 条（BH-FDR alpha=0.20，受人工复核预算约束）
- 池化回退：格子层权重 B<0.5 的占比 0.125（检测层非 L3 占比 0.012）
- 本体绑定：3/4 个模式簇绑定到声明模式 {"0": "p1", "1": "p2", "2": "p3"}
- span 级归因（诊断，slice2 才设门槛）：Precision=0.616 Recall=0.332 tp=114 fp=71 fn=229

| 异常类型 | 样本 | 命中 | 召回 | 统计通道 | 规则通道 |
|---|---|---|---|---|---|
| normal | 3671 | 3 | 0.001 | 3 | 0 |
| token_bloat | 58 | 35 | 0.603 | 35 | 0 |
| latency_spike | 47 | 6 | 0.128 | 6 | 0 |
| loop | 41 | 41 | 1.000 | 0 | 41 |
| hallucinated_number | 39 | 34 | 0.872 | 0 | 34 |
| truncation | 35 | 35 | 1.000 | 0 | 35 |
| error | 25 | 25 | 1.000 | 0 | 25 |
| missing_step | 19 | 15 | 0.789 | 0 | 15 |
| unfinished | 15 | 15 | 1.000 | 0 | 15 |
| illegal_step | 14 | 14 | 1.000 | 0 | 14 |

## 3 打分（5 维 x 4 锚点 x 硬门禁 x LMDI 零残差）

- 零残差最大偏差 `9.592e-14`（恒等式 sum(contrib) == S - 100G）
- 分数区分度：AUC(-S vs 异常)=0.8718｜正常均分 88.92｜异常均分 50.01｜分离度 38.91
- 与生成器 oracle 维度分的相关：Spearman=0.7605｜Kendall tau-b=0.5730

| 维度 | Spearman(vs oracle) | 正常均值 | 异常均值 |
|---|---|---|---|
| O | 0.9598 | 0.998 | 0.868 |
| P | 0.9777 | 1.000 | 0.937 |
| L | 0.6480 | 0.769 | 0.711 |
| C | 0.9241 | 0.777 | 0.671 |
| R | 1.0000 | 0.999 | 0.937 |

- 绝对档位分布 {"A": 2558, "B": 954, "D": 455, "C": 33}
- 相对档位分布 {"B": 1401, "A": 1003, "C": 1001, "D": 595}
- 门禁触发次数 {"drift_suspect": 264, "t0_result_broken": 55, "novelty": 36, "loop_runaway": 27, "t1_unfinished": 21, "t2_untraceable_number": 15, "forbidden_action": 14, "guard_violation": 14}

## 4 校准（交叉拟合，出折外 ECE）

- 方法 platt｜标注数 300｜ECE(出折)=0.0140｜ECE(原始 a_raw)=0.1263｜AUC(校准概率)=0.7655

| bin | n | 预测均值 | 实际频率 |
|---|---|---|---|
| 0 | 213 | 0.065 | 0.056 |
| 1 | 65 | 0.132 | 0.138 |
| 2 | 5 | 0.213 | 0.000 |
| 7 | 1 | 0.791 | 1.000 |
| 8 | 2 | 0.833 | 1.000 |
| 9 | 14 | 0.978 | 1.000 |

## 5 数据质量与漂移

- 采集缺陷召回（规范化侧检出率）{"ts_repaired": 1.0, "usage_estimated": 1.0, "orphan_rebuilt": 1.0}
- 真实缺陷轨迹数 {"ts_repaired": 85, "usage_estimated": 152, "orphan_rebuilt": 67}｜被降级置信度的轨迹 228｜降级率 1.0000
- 漂移：spec={"magnitude": 1.6, "at_frac": 0.5}｜检出=True｜index=2001｜真实 index=2000｜滞后占比=0.0003｜嫌疑轨迹 264

## 6 门槛表（contracts/schemas.md 8）

| 门槛 | 要求 | 实测 | 结论 |
|---|---|---|---|
| ari_intent | >=0.650 (table 0.65, oracle ceiling 1.0000) | 1.0000 | PASS |
| ari_pattern | >=0.550 (table 0.55, oracle ceiling 0.9969) | 0.9537 | PASS |
| drift | detected & lag_frac in [-0.05,0.10] | detected=True lag_frac=0.0003 | PASS |
| ece | <=0.10 | 0.0140 | PASS |
| f1 | >=0.60 | 0.8527 | PASS |
| fpr | <=0.08 | 0.0008 | PASS |
| novelty_rate | [0.00,0.25] | 0.009 | PASS |
| operator_stream_precision | >=0.80 @k=15/day=5 | 1.0000 | PASS |
| precision_at_50 | >=0.70 | 1.0000 | PASS |
| zero_residual | <=1e-06 | 9.592e-14 | PASS |

**总体：全部通过**

- 计时 {"ingest_features": 3.35, "cluster": 92.68, "baseline": 0.36, "detect": 1.11, "score": 0.12}


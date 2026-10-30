# 基准跑分报告 R2 - trimodal

- 流水线版本 `slice3-v0.3.0`｜数据集 `52470f48253b25a6`｜代码 `f651db1a9f2380b0`｜n=4000（可归簇 3967，覆盖率 0.992）｜冷启动 False｜墙钟 89.2s
- 生成器真值：真实格子数 9｜异常率 0.0745｜异常类型 {"error": 22, "hallucinated_number": 45, "illegal_step": 22, "latency_spike": 46, "loop": 30, "missing_step": 29, "token_bloat": 40, "truncation": 33, "unfinished": 31}
- 端到端时延分布 p50/p90/p99 = 3.05 / 67.13 / 152.98

## 1 聚类（共识双视图 -> 分析格子）

| 指标 | 值 |
|---|---|
| ari_intent | 1.0000 |
| ari_pattern | 0.9912 |
| ari_cell | 0.9943 |
| nmi_intent | 1.0000 |
| nmi_pattern | 0.9838 |
| purity_intent | 1.0000 |
| purity_pattern | 0.9972 |
| ARI 弃权前 / 弃权后（意图 / 模式 / 格子） | 1.0000 -> 1.0000 / 0.9913 -> 0.9912 / 0.9943 -> 0.9943 |
| novelty 缓冲区内 多数真实类占比（意图 / 模式） | 1.0000 / 1.0000 |
| novelty 缓冲区异常率 / 可归簇池异常率 | 0.0909 / 0.0744 |
| 意图簇数 / 真实 | 3 / 3 |
| 模式簇数 / 真实 | 3 / 3 |
| 格子数 / 真实 | 9 / 9 |
| novelty 率 | 0.0083 |
| 意图视图信息上界（oracle，同池 / 全量） | 1.0000 / 1.0000 |
| 模式视图信息上界（oracle，同池 / 全量） | 0.9960 / 0.9960 |
| 上界达成率（意图 / 模式） | 1.0000 / 0.9952 |

## 2 异常识别（L1 稳健z / L2 ECOD / L4 结构 / L5 马尔可夫 + BH-FDR 决策）

| 指标 | 可归簇池 | 全量 |
|---|---|---|
| precision | 0.9828 | 0.9828 |
| recall | 0.7763 | 0.7685 |
| f1 | 0.8674 | 0.8625 |
| fpr | 0.0011 | 0.0011 |

- 排序质量：AUC(a_raw)=0.9714｜PR-AUC=0.8957｜Precision@50=1.0000｜Recall@50=0.1695
- 分诊分层：tier2 确定性违规 207｜tier1 统计拒绝 26｜tier0 其余 3734｜剔除 tier2 后 Precision@50=0.7400（该子池异常基率 0.0242，提升 30.58 倍）
- 告警构成：总计 233（统计 26 + 硬规则 207）｜BH alpha=0.200｜折算 77.67 条/日
- 运营口径（唯一会主动打扰人的通道）：日预算 5 条 x 3 天 = k=15，Precision=1.0000
- 漂移监测：未检出变点｜统计量 -31.10 vs 自举阈值 21.13（alpha=0.01，bootstrap）｜最短窗长 160｜命中窗 null｜窗内高于参考中位数占比 n/a
- 三通道口径区分：告警流 k=15（会主动打扰人，Precision=1.0000）｜审计流 207 条确定性违规（69.0 条/日，落库待查不呼叫）｜复核队列 233 条（BH-FDR alpha=0.20，受人工复核预算约束）
- 池化回退：格子层权重 B<0.5 的占比 0.000（检测层非 L3 占比 0.008）
- 本体绑定：3/3 个模式簇绑定到声明模式 {"0": "p3", "1": "p1", "2": "p2"}
- span 级归因（诊断，slice2 才设门槛）：Precision=0.635 Recall=0.357 tp=101 fp=58 fn=182

| 异常类型 | 样本 | 命中 | 召回 | 统计通道 | 规则通道 |
|---|---|---|---|---|---|
| normal | 3672 | 4 | 0.001 | 1 | 3 |
| latency_spike | 45 | 7 | 0.156 | 7 | 0 |
| hallucinated_number | 44 | 38 | 0.864 | 0 | 38 |
| token_bloat | 40 | 18 | 0.450 | 18 | 0 |
| truncation | 33 | 33 | 1.000 | 0 | 33 |
| loop | 30 | 30 | 1.000 | 0 | 30 |
| unfinished | 30 | 30 | 1.000 | 0 | 30 |
| missing_step | 29 | 29 | 1.000 | 0 | 29 |
| error | 22 | 22 | 1.000 | 0 | 22 |
| illegal_step | 22 | 22 | 1.000 | 0 | 22 |

## 3 打分（5 维 x 4 锚点 x 硬门禁 x LMDI 零残差）

- 零残差最大偏差 `9.681e-14`（恒等式 sum(contrib) == S - 100G）
- 分数区分度：AUC(-S vs 异常)=0.8897｜正常均分 89.85｜异常均分 49.71｜分离度 40.14
- 与生成器 oracle 维度分的相关：Spearman=0.7947｜Kendall tau-b=0.6120

| 维度 | Spearman(vs oracle) | 正常均值 | 异常均值 |
|---|---|---|---|
| O | 0.9454 | 0.999 | 0.861 |
| P | 0.7935 | 0.998 | 0.895 |
| L | 0.7216 | 0.766 | 0.716 |
| C | 0.9241 | 0.772 | 0.696 |
| R | 1.0000 | 0.999 | 0.948 |

- 绝对档位分布 {"A": 2505, "B": 1091, "D": 333, "C": 71}
- 相对档位分布 {"B": 1397, "A": 1006, "C": 1002, "D": 595}
- 门禁触发次数 {"t1_unfinished": 103, "t0_result_broken": 45, "novelty": 33, "t2_untraceable_number": 27, "forbidden_action": 22, "loop_runaway": 22, "guard_violation": 14}

## 4 校准（交叉拟合，出折外 ECE）

- 方法 isotonic｜标注数 500｜ECE(出折)=0.0127｜ECE(原始 a_raw)=0.1360｜AUC(校准概率)=0.7362

| bin | n | 预测均值 | 实际频率 |
|---|---|---|---|
| 0 | 451 | 0.050 | 0.055 |
| 1 | 23 | 0.160 | 0.087 |
| 8 | 8 | 0.837 | 0.875 |
| 9 | 18 | 0.995 | 0.889 |

## 5 数据质量与漂移

- 采集缺陷召回（规范化侧检出率）{"ts_repaired": 1.0, "usage_estimated": 1.0, "orphan_rebuilt": 1.0}
- 真实缺陷轨迹数 {"ts_repaired": 90, "usage_estimated": 111, "orphan_rebuilt": 52}｜被降级置信度的轨迹 193｜降级率 1.0000
- 漂移：spec=null｜检出=False｜index=None｜真实 index=None｜滞后占比=n/a｜嫌疑轨迹 0

## 6 门槛表（contracts/schemas.md 8）

| 门槛 | 要求 | 实测 | 结论 |
|---|---|---|---|
| ari_intent | >=0.650 (table 0.65, oracle ceiling 1.0000) | 1.0000 | PASS |
| ari_pattern | >=0.550 (table 0.55, oracle ceiling 0.9960) | 0.9912 | PASS |
| ece | <=0.08 | 0.0127 | PASS |
| f1 | >=0.65 | 0.8674 | PASS |
| fpr | <=0.06 | 0.0011 | PASS |
| no_false_drift | detected=false | detected=False stat=-31.10 lambda=21.13 | PASS |
| novelty_rate | [0.00,0.25] | 0.008 | PASS |
| operator_stream_precision | >=0.80 @k=15/day=5 | 1.0000 | PASS |
| precision_at_50 | >=0.75 | 1.0000 | PASS |
| zero_residual | <=1e-06 | 9.681e-14 | PASS |

**总体：全部通过**

- 计时 {"ingest_features": 4.93, "cluster": 80.86, "baseline": 0.41, "detect": 1.41, "score": 0.13}


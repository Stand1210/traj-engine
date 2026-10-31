# 基准跑分报告 R4 - extremely sparse cells

- 流水线版本 `slice5-v0.5.0`｜数据集 `5188fdfc219089b9`｜代码 `0064f089a6b550d7`｜n=1200（可归簇 1021，覆盖率 0.851）｜冷启动 False｜墙钟 71.2s
- 生成器真值：真实格子数 12｜异常率 0.0933｜异常类型 {"error": 9, "hallucinated_number": 9, "illegal_step": 14, "latency_spike": 20, "loop": 6, "missing_step": 14, "token_bloat": 15, "truncation": 14, "unfinished": 11}
- 端到端时延分布 p50/p90/p99 = 5.67 / 58.20 / 277.61

## 1 聚类（共识双视图 -> 分析格子）

| 指标 | 值 |
|---|---|
| ari_intent | 1.0000 |
| ari_pattern | 0.9879 |
| ari_cell | 0.9917 |
| nmi_intent | 1.0000 |
| nmi_pattern | 0.9762 |
| purity_intent | 1.0000 |
| purity_pattern | 0.9971 |
| ARI 弃权前 / 弃权后（意图 / 模式 / 格子） | 1.0000 -> 1.0000 / 0.9842 -> 0.9879 / 0.9874 -> 0.9917 |
| novelty 缓冲区内 多数真实类占比（意图 / 模式） | 1.0000 / 0.9888 |
| novelty 缓冲区异常率 / 可归簇池异常率 | 0.1229 / 0.0881 |
| 意图簇数 / 真实 | 4 / 4 |
| 模式簇数 / 真实 | 4 / 3 |
| 格子数 / 真实 | 13 / 11 |
| novelty 率 | 0.1492 |
| 意图视图信息上界（oracle，同池 / 全量） | 1.0000 / 1.0000 |
| 模式视图信息上界（oracle，同池 / 全量） | 0.9938 / 0.9919 |
| 上界达成率（意图 / 模式） | 1.0000 / 0.9941 |

## 2 异常识别（L1 稳健z / L2 ECOD / L4 结构 / L5 马尔可夫 + BH-FDR 决策）

| 指标 | 可归簇池 | 全量 |
|---|---|---|
| precision | 0.9839 | 0.9839 |
| recall | 0.6778 | 0.5446 |
| f1 | 0.8026 | 0.7011 |
| fpr | 0.0011 | 0.0009 |

- 排序质量：AUC(a_raw)=0.9385｜PR-AUC=0.8272｜Precision@50=0.9800｜Recall@50=0.5444
- 分诊分层：tier2 确定性违规 56｜tier1 统计拒绝 6｜tier0 其余 959｜剔除 tier2 后 Precision@50=0.2800（该子池异常基率 0.0363，提升 7.72 倍）
- 告警构成：总计 62（统计 6 + 硬规则 56）｜BH alpha=0.200｜折算 31.00 条/日
- 运营口径（唯一会主动打扰人的通道）：日预算 5 条 x 2 天 = k=10，Precision=1.0000
- 漂移监测：未检出变点｜统计量 -14.30 vs 自举阈值 42.19（alpha=0.01，bootstrap）｜最短窗长 50｜命中窗 null｜窗内高于参考中位数占比 n/a
- 三通道口径区分：告警流 k=10（会主动打扰人，Precision=1.0000）｜审计流 56 条确定性违规（28.0 条/日，落库待查不呼叫）｜复核队列 62 条（BH-FDR alpha=0.20，受人工复核预算约束）
- 池化回退：格子层权重 B<0.5 的占比 0.769（检测层非 L3 占比 0.231）
- 本体绑定：3/3 个模式簇绑定到声明模式 {"0": "p1", "1": "p2", "2": "p3"}
- span 级归因（诊断，slice2 才设门槛）：Precision=0.635 Recall=0.471 tp=33 fp=19 fn=37

| 异常类型 | 样本 | 命中 | 召回 | 统计通道 | 规则通道 |
|---|---|---|---|---|---|
| normal | 931 | 1 | 0.001 | 0 | 1 |
| latency_spike | 17 | 3 | 0.176 | 3 | 0 |
| token_bloat | 12 | 3 | 0.250 | 3 | 0 |
| missing_step | 11 | 6 | 0.545 | 0 | 6 |
| truncation | 11 | 11 | 1.000 | 0 | 11 |
| illegal_step | 10 | 10 | 1.000 | 0 | 10 |
| error | 9 | 9 | 1.000 | 0 | 9 |
| hallucinated_number | 8 | 7 | 0.875 | 0 | 7 |
| unfinished | 8 | 8 | 1.000 | 0 | 8 |
| loop | 4 | 4 | 1.000 | 0 | 4 |

## 3 打分（5 维 x 4 锚点 x 硬门禁 x LMDI 零残差）

- 零残差最大偏差 `9.415e-14`（恒等式 sum(contrib) == S - 100G）
- 分数区分度：AUC(-S vs 异常)=0.8577｜正常均分 91.33｜异常均分 53.60｜分离度 37.73
- 与生成器 oracle 维度分的相关：Spearman=0.8258｜Kendall tau-b=0.6434

| 维度 | Spearman(vs oracle) | 正常均值 | 异常均值 |
|---|---|---|---|
| O | 0.9604 | 0.999 | 0.880 |
| P | 0.9539 | 1.000 | 0.914 |
| L | 0.7447 | 0.777 | 0.710 |
| C | 0.9177 | 0.767 | 0.759 |
| R | 1.0000 | 0.999 | 0.950 |

- 绝对档位分布 {"A": 673, "B": 298, "D": 204, "C": 25}
- 相对档位分布 {"B": 420, "A": 309, "C": 295, "D": 176}
- 门禁触发次数 {"novelty": 179, "t0_result_broken": 16, "forbidden_action": 14, "guard_violation": 13, "t1_unfinished": 12, "t2_untraceable_number": 6, "loop_runaway": 5}

## 4 校准（交叉拟合，出折外 ECE）

- 方法 platt｜标注数 150｜ECE(出折)=0.0200｜ECE(原始 a_raw)=0.1015｜AUC(校准概率)=0.6658

| bin | n | 预测均值 | 实际频率 |
|---|---|---|---|
| 0 | 80 | 0.068 | 0.075 |
| 1 | 55 | 0.133 | 0.109 |
| 2 | 8 | 0.234 | 0.125 |
| 9 | 7 | 0.960 | 1.000 |

## 5 数据质量与漂移

- 采集缺陷召回（规范化侧检出率）{"ts_repaired": 1.0, "usage_estimated": 1.0, "orphan_rebuilt": 1.0}
- 真实缺陷轨迹数 {"ts_repaired": 32, "usage_estimated": 36, "orphan_rebuilt": 18}｜被降级置信度的轨迹 60｜降级率 1.0000
- 漂移：spec=null｜检出=False｜index=None｜真实 index=None｜滞后占比=n/a｜嫌疑轨迹 0

## 6 门槛表（contracts/schemas.md 8）

| 门槛 | 要求 | 实测 | 结论 |
|---|---|---|---|
| ari_intent | >=0.600 (table 0.60, oracle ceiling 1.0000) | 1.0000 | PASS |
| ari_pattern | >=0.500 (table 0.50, oracle ceiling 0.9938) | 0.9879 | PASS |
| ece | <=0.12 | 0.0200 | PASS |
| f1 | >=0.50 | 0.8026 | PASS |
| fpr | <=0.10 | 0.0011 | PASS |
| no_false_drift | detected=false | detected=False stat=-14.30 lambda=42.19 | PASS |
| novelty_rate | [0.00,0.25] | 0.149 | PASS |
| operator_stream_precision | >=0.80 @k=10/day=5 | 1.0000 | PASS |
| pooling_fallback_share | >=0.50 | 0.769 | PASS |
| precision_at_50 | >=0.60 | 0.9800 | PASS |
| zero_residual | <=1e-06 | 9.415e-14 | PASS |

**总体：全部通过**

- 计时 {"ingest_features": 0.93, "cluster": 68.91, "baseline": 0.2, "detect": 0.58, "score": 0.07}


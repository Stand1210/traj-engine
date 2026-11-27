# 基准跑分报告 R4 - extremely sparse cells

- 流水线版本 `slice6-v0.6.0`｜数据集 `5188fdfc219089b9`｜代码 `d229ab802e5a01bf`｜n=1200（可归簇 978，覆盖率 0.815）｜冷启动 False｜墙钟 75.5s
- 生成器真值：真实格子数 12｜异常率 0.0933｜异常类型 {"error": 9, "hallucinated_number": 9, "illegal_step": 14, "latency_spike": 20, "loop": 6, "missing_step": 14, "token_bloat": 15, "truncation": 14, "unfinished": 11}
- 端到端时延分布 p50/p90/p99 = 5.67 / 58.20 / 277.61

## 1 聚类（共识双视图 -> 分析格子）

| 指标 | 值 |
|---|---|
| ari_intent | 1.0000 |
| ari_pattern | 0.9775 |
| ari_cell | 0.9815 |
| nmi_intent | 1.0000 |
| nmi_pattern | 0.9661 |
| purity_intent | 1.0000 |
| purity_pattern | 0.9980 |
| ARI 弃权前 / 弃权后（意图 / 模式 / 格子） | 1.0000 -> 1.0000 / 0.9364 -> 0.9775 / 0.9498 -> 0.9815 |
| novelty 缓冲区内 多数真实类占比（意图 / 模式） | 1.0000 / 0.9775 |
| novelty 缓冲区异常率 / 可归簇池异常率 | 0.1261 / 0.0859 |
| 意图簇数 / 真实 | 4 / 4 |
| 模式簇数 / 真实 | 5 / 3 |
| 格子数 / 真实 | 15 / 11 |
| novelty 率 | 0.1850 |
| 意图视图信息上界（oracle，同池 / 全量） | 1.0000 / 1.0000 |
| 模式视图信息上界（oracle，同池 / 全量） | 0.9970 / 0.9919 |
| 上界达成率（意图 / 模式） | 1.0000 / 0.9805 |

## 2 异常识别（L1 稳健z / L2 ECOD / L4 结构 / L5 马尔可夫 + BH-FDR 决策）

| 指标 | 可归簇池 | 全量 |
|---|---|---|
| precision | 0.9833 | 0.9833 |
| recall | 0.7024 | 0.5268 |
| f1 | 0.8194 | 0.6860 |
| fpr | 0.0011 | 0.0009 |

- 排序质量：AUC(a_raw)=0.9531｜PR-AUC=0.8509｜Precision@50=0.9800｜Recall@50=0.5833
- 分诊分层：tier2 确定性违规 54｜tier1 统计拒绝 6｜tier0 其余 918｜剔除 tier2 后 Precision@50=0.2600（该子池异常基率 0.0335，提升 7.75 倍）
- 告警构成：总计 60（统计 6 + 硬规则 54）｜BH alpha=0.200｜折算 30.00 条/日
- 运营口径（唯一会主动打扰人的通道）：日预算 5 条 x 2 天 = k=10，Precision=1.0000
- 漂移监测：未检出变点｜统计量 -12.30 vs 自举阈值 57.55（alpha=0.01，bootstrap）｜最短窗长 50｜命中窗 null｜窗内高于参考中位数占比 n/a
- 三通道口径区分：告警流 k=10（会主动打扰人，Precision=1.0000）｜审计流 54 条确定性违规（27.0 条/日，落库待查不呼叫）｜复核队列 60 条（BH-FDR alpha=0.20，受人工复核预算约束）
- 池化回退：格子层权重 B<0.5 的占比 0.800（检测层非 L3 占比 0.268）
- 本体绑定：3/5 个模式簇绑定到声明模式 {"0": "p1", "1": "p2", "2": "p3"}
- span 级归因（诊断，slice2 才设门槛）：Precision=0.635 Recall=0.471 tp=33 fp=19 fn=37

| 异常类型 | 样本 | 命中 | 召回 | 统计通道 | 规则通道 |
|---|---|---|---|---|---|
| normal | 894 | 1 | 0.001 | 0 | 1 |
| latency_spike | 17 | 3 | 0.176 | 3 | 0 |
| token_bloat | 12 | 3 | 0.250 | 3 | 0 |
| truncation | 11 | 11 | 1.000 | 0 | 11 |
| illegal_step | 10 | 10 | 1.000 | 0 | 10 |
| error | 9 | 9 | 1.000 | 0 | 9 |
| hallucinated_number | 8 | 7 | 0.875 | 0 | 7 |
| missing_step | 7 | 6 | 0.857 | 0 | 6 |
| unfinished | 6 | 6 | 1.000 | 0 | 6 |
| loop | 4 | 4 | 1.000 | 0 | 4 |

## 3 打分（5 维 x 4 锚点 x 硬门禁 x LMDI 零残差）

- 零残差最大偏差 `9.237e-14`（恒等式 sum(contrib) == S - 100G）
- 分数区分度：AUC(-S vs 异常)=0.8574｜正常均分 91.45｜异常均分 53.17｜分离度 38.28
- 与生成器 oracle 维度分的相关：Spearman=0.8217｜Kendall tau-b=0.6389

| 维度 | Spearman(vs oracle) | 正常均值 | 异常均值 |
|---|---|---|---|
| O | 0.9576 | 0.999 | 0.883 |
| P | 1.0000 | 1.000 | 0.914 |
| L | 0.7383 | 0.777 | 0.711 |
| C | 0.9192 | 0.768 | 0.755 |
| R | 1.0000 | 0.999 | 0.947 |

- 绝对档位分布 {"A": 649, "B": 305, "D": 221, "C": 25}
- 相对档位分布 {"B": 420, "A": 313, "C": 292, "D": 175}
- 门禁触发次数 {"novelty": 222, "t0_result_broken": 16, "forbidden_action": 14, "guard_violation": 13, "t1_unfinished": 12, "t2_untraceable_number": 6, "loop_runaway": 5}

## 4 校准（交叉拟合，出折外 ECE）

- 方法 platt｜标注数 150｜ECE(出折)=0.0168｜ECE(原始 a_raw)=0.0999｜AUC(校准概率)=0.6808

| bin | n | 预测均值 | 实际频率 |
|---|---|---|---|
| 0 | 84 | 0.068 | 0.071 |
| 1 | 49 | 0.135 | 0.122 |
| 2 | 10 | 0.237 | 0.100 |
| 9 | 7 | 0.962 | 1.000 |

## 5 数据质量与漂移

- 采集缺陷召回（规范化侧检出率）{"ts_repaired": 1.0, "usage_estimated": 1.0, "orphan_rebuilt": 1.0}
- 真实缺陷轨迹数 {"ts_repaired": 32, "usage_estimated": 36, "orphan_rebuilt": 18}｜被降级置信度的轨迹 60｜降级率 1.0000
- 漂移：spec=null｜检出=False｜index=None｜真实 index=None｜滞后占比=n/a｜嫌疑轨迹 0

## 6 门槛表（contracts/schemas.md 8）

| 门槛 | 要求 | 实测 | 结论 |
|---|---|---|---|
| ari_intent | >=0.600 (table 0.60, oracle ceiling 1.0000) | 1.0000 | PASS |
| ari_pattern | >=0.500 (table 0.50, oracle ceiling 0.9970) | 0.9775 | PASS |
| ece | <=0.12 | 0.0168 | PASS |
| f1 | >=0.50 | 0.8194 | PASS |
| fpr | <=0.10 | 0.0011 | PASS |
| no_false_drift | detected=false | detected=False stat=-12.30 lambda=57.55 | PASS |
| novelty_rate | [0.00,0.25] | 0.185 | PASS |
| operator_stream_precision | >=0.80 @k=10/day=5 | 1.0000 | PASS |
| pooling_fallback_share | >=0.50 | 0.800 | PASS |
| precision_at_50 | >=0.60 | 0.9800 | PASS |
| zero_residual | <=1e-06 | 9.237e-14 | PASS |

**总体：全部通过**

- 计时 {"ingest_features": 1.18, "cluster": 73.06, "baseline": 0.2, "detect": 0.42, "score": 0.06}


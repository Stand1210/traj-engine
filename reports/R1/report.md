# 基准跑分报告 R1 - bimodal main path

- 流水线版本 `slice6-v0.6.0`｜数据集 `007a872125bac9bb`｜代码 `d229ab802e5a01bf`｜n=4000（可归簇 3639，覆盖率 0.910）｜冷启动 False｜墙钟 101.3s
- 生成器真值：真实格子数 6｜异常率 0.0755｜异常类型 {"error": 16, "hallucinated_number": 54, "illegal_step": 20, "latency_spike": 43, "loop": 29, "missing_step": 33, "token_bloat": 42, "truncation": 40, "unfinished": 25}
- 端到端时延分布 p50/p90/p99 = 2.00 / 55.61 / 118.03

## 1 聚类（共识双视图 -> 分析格子）

| 指标 | 值 |
|---|---|
| ari_intent | 1.0000 |
| ari_pattern | 0.9983 |
| ari_cell | 0.9982 |
| nmi_intent | 1.0000 |
| nmi_pattern | 0.9962 |
| purity_intent | 1.0000 |
| purity_pattern | 0.9995 |
| ARI 弃权前 / 弃权后（意图 / 模式 / 格子） | 1.0000 -> 1.0000 / 0.8534 -> 0.9983 / 0.8616 -> 0.9982 |
| novelty 缓冲区内 多数真实类占比（意图 / 模式） | 1.0000 / 0.9723 |
| novelty 缓冲区异常率 / 可归簇池异常率 | 0.1080 / 0.0723 |
| 意图簇数 / 真实 | 2 / 2 |
| 模式簇数 / 真实 | 5 / 3 |
| 格子数 / 真实 | 6 / 6 |
| novelty 率 | 0.0902 |
| 意图视图信息上界（oracle，同池 / 全量） | 1.0000 / 1.0000 |
| 模式视图信息上界（oracle，同池 / 全量） | 0.9983 / 0.9928 |
| 上界达成率（意图 / 模式） | 1.0000 / 1.0000 |

## 2 异常识别（L1 稳健z / L2 ECOD / L4 结构 / L5 马尔可夫 + BH-FDR 决策）

| 指标 | 可归簇池 | 全量 |
|---|---|---|
| precision | 0.9952 | 0.9952 |
| recall | 0.7947 | 0.6921 |
| f1 | 0.8837 | 0.8164 |
| fpr | 0.0003 | 0.0003 |

- 排序质量：AUC(a_raw)=0.9676｜PR-AUC=0.9067｜Precision@50=1.0000｜Recall@50=0.1901
- 分诊分层：tier2 确定性违规 180｜tier1 统计拒绝 30｜tier0 其余 3429｜剔除 tier2 后 Precision@50=0.6800（该子池异常基率 0.0240，提升 28.34 倍）
- 告警构成：总计 210（统计 30 + 硬规则 180）｜BH alpha=0.200｜折算 70.00 条/日
- 运营口径（唯一会主动打扰人的通道）：日预算 5 条 x 3 天 = k=15，Precision=1.0000
- 漂移监测：未检出变点｜统计量 -20.50 vs 自举阈值 9.22（alpha=0.01，bootstrap）｜最短窗长 160｜命中窗 null｜窗内高于参考中位数占比 n/a
- 三通道口径区分：告警流 k=15（会主动打扰人，Precision=1.0000）｜审计流 180 条确定性违规（60.0 条/日，落库待查不呼叫）｜复核队列 210 条（BH-FDR alpha=0.20，受人工复核预算约束）
- 池化回退：格子层权重 B<0.5 的占比 0.000（检测层非 L3 占比 0.090）
- 本体绑定：3/3 个模式簇绑定到声明模式 {"0": "p2", "1": "p1", "2": "p3"}
- span 级归因（诊断，slice2 才设门槛）：Precision=0.620 Recall=0.348 tp=85 fp=52 fn=159

| 异常类型 | 样本 | 命中 | 召回 | 统计通道 | 规则通道 |
|---|---|---|---|---|---|
| normal | 3376 | 1 | 0.000 | 1 | 0 |
| hallucinated_number | 50 | 46 | 0.920 | 0 | 46 |
| latency_spike | 41 | 14 | 0.341 | 14 | 0 |
| truncation | 39 | 39 | 1.000 | 0 | 39 |
| token_bloat | 36 | 15 | 0.417 | 15 | 0 |
| loop | 28 | 28 | 1.000 | 0 | 28 |
| unfinished | 19 | 19 | 1.000 | 0 | 19 |
| missing_step | 18 | 16 | 0.889 | 0 | 16 |
| illegal_step | 17 | 17 | 1.000 | 0 | 17 |
| error | 15 | 15 | 1.000 | 0 | 15 |

## 3 打分（5 维 x 4 锚点 x 硬门禁 x LMDI 零残差）

- 零残差最大偏差 `9.681e-14`（恒等式 sum(contrib) == S - 100G）
- 分数区分度：AUC(-S vs 异常)=0.9030｜正常均分 91.18｜异常均分 48.21｜分离度 42.97
- 与生成器 oracle 维度分的相关：Spearman=0.8285｜Kendall tau-b=0.6384

| 维度 | Spearman(vs oracle) | 正常均值 | 异常均值 |
|---|---|---|---|
| O | 0.9752 | 1.000 | 0.824 |
| P | 0.9940 | 1.000 | 0.932 |
| L | 0.7441 | 0.770 | 0.684 |
| C | 0.9285 | 0.769 | 0.707 |
| R | 1.0000 | 1.000 | 0.956 |

- 绝对档位分布 {"A": 2343, "B": 1116, "D": 461, "C": 80}
- 相对档位分布 {"B": 1400, "A": 1002, "C": 1001, "D": 597}
- 门禁触发次数 {"novelty": 361, "t0_result_broken": 63, "t1_unfinished": 28, "t2_untraceable_number": 26, "forbidden_action": 20, "loop_runaway": 16, "guard_violation": 11}

## 4 校准（交叉拟合，出折外 ECE）

- 方法 isotonic｜标注数 500｜ECE(出折)=0.0233｜ECE(原始 a_raw)=0.1158｜AUC(校准概率)=0.7407

| bin | n | 预测均值 | 实际频率 |
|---|---|---|---|
| 0 | 324 | 0.040 | 0.056 |
| 1 | 125 | 0.140 | 0.144 |
| 2 | 17 | 0.231 | 0.000 |
| 3 | 9 | 0.301 | 0.111 |
| 9 | 25 | 0.986 | 0.960 |

## 5 数据质量与漂移

- 采集缺陷召回（规范化侧检出率）{"ts_repaired": 1.0, "usage_estimated": 1.0, "orphan_rebuilt": 1.0}
- 真实缺陷轨迹数 {"ts_repaired": 81, "usage_estimated": 120, "orphan_rebuilt": 62}｜被降级置信度的轨迹 205｜降级率 1.0000
- 漂移：spec=null｜检出=False｜index=None｜真实 index=None｜滞后占比=n/a｜嫌疑轨迹 0

## 6 门槛表（contracts/schemas.md 8）

| 门槛 | 要求 | 实测 | 结论 |
|---|---|---|---|
| ari_intent | >=0.700 (table 0.70, oracle ceiling 1.0000) | 1.0000 | PASS |
| ari_pattern | >=0.600 (table 0.60, oracle ceiling 0.9983) | 0.9983 | PASS |
| ece | <=0.08 | 0.0233 | PASS |
| f1 | >=0.70 | 0.8837 | PASS |
| fpr | <=0.05 | 0.0003 | PASS |
| no_false_drift | detected=false | detected=False stat=-20.50 lambda=9.22 | PASS |
| novelty_rate | [0.00,0.25] | 0.090 | PASS |
| operator_stream_precision | >=0.80 @k=15/day=5 | 1.0000 | PASS |
| precision_at_50 | >=0.80 | 1.0000 | PASS |
| zero_residual | <=1e-06 | 9.681e-14 | PASS |

**总体：全部通过**

- 计时 {"ingest_features": 5.05, "cluster": 93.28, "baseline": 0.28, "detect": 1.19, "score": 0.19}


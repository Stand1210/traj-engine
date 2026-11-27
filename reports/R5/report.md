# 基准跑分报告 R5 - heavily corrupted telemetry

- 流水线版本 `slice6-v0.6.0`｜数据集 `10ff75f849deddbe`｜代码 `d229ab802e5a01bf`｜n=3000（可归簇 2980，覆盖率 0.993）｜冷启动 False｜墙钟 104.2s
- 生成器真值：真实格子数 6｜异常率 0.1027｜异常类型 {"error": 14, "hallucinated_number": 31, "illegal_step": 21, "latency_spike": 60, "loop": 25, "missing_step": 30, "token_bloat": 53, "truncation": 38, "unfinished": 36}
- 端到端时延分布 p50/p90/p99 = 1.99 / 60.01 / 137.03

## 1 聚类（共识双视图 -> 分析格子）

| 指标 | 值 |
|---|---|
| ari_intent | 1.0000 |
| ari_pattern | 0.9551 |
| ari_cell | 0.9649 |
| nmi_intent | 1.0000 |
| nmi_pattern | 0.9433 |
| purity_intent | 1.0000 |
| purity_pattern | 0.9953 |
| ARI 弃权前 / 弃权后（意图 / 模式 / 格子） | 1.0000 -> 1.0000 / 0.9551 -> 0.9551 / 0.9648 -> 0.9649 |
| novelty 缓冲区内 多数真实类占比（意图 / 模式） | 1.0000 / 1.0000 |
| novelty 缓冲区异常率 / 可归簇池异常率 | 0.0500 / 0.1030 |
| 意图簇数 / 真实 | 2 / 2 |
| 模式簇数 / 真实 | 4 / 3 |
| 格子数 / 真实 | 8 / 6 |
| novelty 率 | 0.0067 |
| 意图视图信息上界（oracle，同池 / 全量） | 1.0000 / 1.0000 |
| 模式视图信息上界（oracle，同池 / 全量） | 0.9892 / 0.9893 |
| 上界达成率（意图 / 模式） | 1.0000 / 0.9656 |

## 2 异常识别（L1 稳健z / L2 ECOD / L4 结构 / L5 马尔可夫 + BH-FDR 决策）

| 指标 | 可归簇池 | 全量 |
|---|---|---|
| precision | 0.9953 | 0.9953 |
| recall | 0.6971 | 0.6948 |
| f1 | 0.8199 | 0.8184 |
| fpr | 0.0004 | 0.0004 |

- 排序质量：AUC(a_raw)=0.9547｜PR-AUC=0.8741｜Precision@50=1.0000｜Recall@50=0.1629
- 分诊分层：tier2 确定性违规 187｜tier1 统计拒绝 28｜tier0 其余 2765｜剔除 tier2 后 Precision@50=0.7800（该子池异常基率 0.0430，提升 18.15 倍）
- 告警构成：总计 215（统计 28 + 硬规则 187）｜BH alpha=0.200｜折算 71.67 条/日
- 运营口径（唯一会主动打扰人的通道）：日预算 5 条 x 3 天 = k=15，Precision=1.0000
- 漂移监测：未检出变点｜统计量 9.10 vs 自举阈值 41.60（alpha=0.01，bootstrap）｜最短窗长 120｜命中窗 null｜窗内高于参考中位数占比 n/a
- 三通道口径区分：告警流 k=15（会主动打扰人，Precision=1.0000）｜审计流 187 条确定性违规（62.3 条/日，落库待查不呼叫）｜复核队列 215 条（BH-FDR alpha=0.20，受人工复核预算约束）
- 池化回退：格子层权重 B<0.5 的占比 0.125（检测层非 L3 占比 0.013）
- 本体绑定：3/3 个模式簇绑定到声明模式 {"0": "p3", "1": "p1", "2": "p2"}
- span 级归因（诊断，slice2 才设门槛）：Precision=0.665 Recall=0.417 tp=115 fp=58 fn=161

| 异常类型 | 样本 | 命中 | 召回 | 统计通道 | 规则通道 |
|---|---|---|---|---|---|
| normal | 2673 | 1 | 0.000 | 1 | 0 |
| latency_spike | 60 | 13 | 0.217 | 13 | 0 |
| token_bloat | 53 | 14 | 0.264 | 14 | 0 |
| truncation | 38 | 38 | 1.000 | 0 | 38 |
| unfinished | 35 | 35 | 1.000 | 0 | 35 |
| hallucinated_number | 31 | 29 | 0.935 | 0 | 29 |
| missing_step | 30 | 26 | 0.867 | 0 | 26 |
| loop | 25 | 24 | 0.960 | 0 | 24 |
| illegal_step | 21 | 21 | 1.000 | 0 | 21 |
| error | 14 | 14 | 1.000 | 0 | 14 |

## 3 打分（5 维 x 4 锚点 x 硬门禁 x LMDI 零残差）

- 零残差最大偏差 `9.770e-14`（恒等式 sum(contrib) == S - 100G）
- 分数区分度：AUC(-S vs 异常)=0.9035｜正常均分 91.87｜异常均分 51.54｜分离度 40.33
- 与生成器 oracle 维度分的相关：Spearman=0.8188｜Kendall tau-b=0.6311

| 维度 | Spearman(vs oracle) | 正常均值 | 异常均值 |
|---|---|---|---|
| O | 0.9785 | 1.000 | 0.868 |
| P | 0.9912 | 1.000 | 0.916 |
| L | 0.7364 | 0.773 | 0.697 |
| C | 0.9149 | 0.773 | 0.702 |
| R | 0.9896 | 1.000 | 0.964 |

- 绝对档位分布 {"A": 1949, "B": 788, "D": 206, "C": 57}
- 相对档位分布 {"B": 1050, "A": 753, "C": 749, "D": 448}
- 门禁触发次数 {"t0_result_broken": 49, "t1_unfinished": 36, "forbidden_action": 21, "loop_runaway": 20, "novelty": 20, "guard_violation": 18, "t2_untraceable_number": 18}

## 4 校准（交叉拟合，出折外 ECE）

- 方法 platt｜标注数 300｜ECE(出折)=0.0224｜ECE(原始 a_raw)=0.1068｜AUC(校准概率)=0.7940

| bin | n | 预测均值 | 实际频率 |
|---|---|---|---|
| 0 | 164 | 0.070 | 0.067 |
| 1 | 107 | 0.133 | 0.103 |
| 2 | 8 | 0.217 | 0.500 |
| 8 | 1 | 0.876 | 1.000 |
| 9 | 20 | 0.974 | 1.000 |

## 5 数据质量与漂移

- 采集缺陷召回（规范化侧检出率）{"ts_repaired": 1.0, "usage_estimated": 1.0, "orphan_rebuilt": 1.0}
- 真实缺陷轨迹数 {"ts_repaired": 525, "usage_estimated": 843, "orphan_rebuilt": 425}｜被降级置信度的轨迹 1361｜降级率 1.0000
- 漂移：spec=null｜检出=False｜index=None｜真实 index=None｜滞后占比=n/a｜嫌疑轨迹 0

## 6 门槛表（contracts/schemas.md 8）

| 门槛 | 要求 | 实测 | 结论 |
|---|---|---|---|
| ari_intent | >=0.650 (table 0.65, oracle ceiling 1.0000) | 1.0000 | PASS |
| ari_pattern | >=0.550 (table 0.55, oracle ceiling 0.9892) | 0.9551 | PASS |
| conf_downgrade_rate | >=1.00 | 1.000 | PASS |
| ece | <=0.10 | 0.0224 | PASS |
| f1 | >=0.60 | 0.8199 | PASS |
| fpr | <=0.08 | 0.0004 | PASS |
| no_false_drift | detected=false | detected=False stat=9.10 lambda=41.60 | PASS |
| novelty_rate | [0.00,0.25] | 0.007 | PASS |
| operator_stream_precision | >=0.80 @k=15/day=5 | 1.0000 | PASS |
| precision_at_50 | >=0.70 | 1.0000 | PASS |
| zero_residual | <=1e-06 | 9.770e-14 | PASS |

**总体：全部通过**

- 计时 {"ingest_features": 3.68, "cluster": 97.21, "baseline": 0.37, "detect": 1.17, "score": 0.12}


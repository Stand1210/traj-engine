# 基准跑分报告 R5 - heavily corrupted telemetry

- 流水线版本 `slice2-v0.2.0`｜数据集 `10ff75f849deddbe`｜代码 `6f246e5b1df5bb02`｜n=3000（可归簇 2979，覆盖率 0.993）｜冷启动 False｜墙钟 122.6s
- 生成器真值：真实格子数 6｜异常率 0.1027｜异常类型 {"error": 14, "hallucinated_number": 31, "illegal_step": 21, "latency_spike": 60, "loop": 25, "missing_step": 30, "token_bloat": 53, "truncation": 38, "unfinished": 36}
- 端到端时延分布 p50/p90/p99 = 1.99 / 60.01 / 137.03

## 1 聚类（共识双视图 -> 分析格子）

| 指标 | 值 |
|---|---|
| ari_intent | 1.0000 |
| ari_pattern | 0.9804 |
| ari_cell | 0.9862 |
| nmi_intent | 1.0000 |
| nmi_pattern | 0.9597 |
| purity_intent | 1.0000 |
| purity_pattern | 0.9950 |
| ARI 弃权前 / 弃权后（意图 / 模式 / 格子） | 1.0000 -> 1.0000 / 0.9798 -> 0.9804 / 0.9858 -> 0.9862 |
| novelty 缓冲区内 多数真实类占比（意图 / 模式） | 1.0000 / 1.0000 |
| novelty 缓冲区异常率 / 可归簇池异常率 | 0.0952 / 0.1027 |
| 意图簇数 / 真实 | 2 / 2 |
| 模式簇数 / 真实 | 5 / 3 |
| 格子数 / 真实 | 10 / 6 |
| novelty 率 | 0.0070 |
| 意图视图信息上界（oracle，同池 / 全量） | 1.0000 / 1.0000 |
| 模式视图信息上界（oracle，同池 / 全量） | 0.9892 / 0.9893 |
| 上界达成率（意图 / 模式） | 1.0000 / 0.9911 |

## 2 异常识别（L1 稳健z / L2 ECOD / L4 结构 / L5 马尔可夫 + BH-FDR 决策）

| 指标 | 可归簇池 | 全量 |
|---|---|---|
| precision | 0.9894 | 0.9894 |
| recall | 0.6111 | 0.6071 |
| f1 | 0.7556 | 0.7525 |
| fpr | 0.0007 | 0.0007 |

- 排序质量：AUC(a_raw)=0.9131｜PR-AUC=0.8108｜Precision@50=1.0000｜Recall@50=0.1634
- 分诊分层：tier2 确定性违规 161｜tier1 统计拒绝 28｜tier0 其余 2790｜剔除 tier2 后 Precision@50=0.7800（该子池异常基率 0.0515，提升 15.16 倍）
- 告警构成：总计 189（统计 28 + 硬规则 161）｜BH alpha=0.200｜折算 63.00 条/日
- 运营口径（唯一会主动打扰人的通道）：日预算 5 条 x 3 天 = k=15，Precision=1.0000
- 漂移监测：未检出变点｜统计量 9.10 vs 自举阈值 43.61（alpha=0.01，bootstrap）｜最短窗长 120｜命中窗 null｜窗内高于参考中位数占比 n/a
- 三通道口径区分：告警流 k=15（会主动打扰人，Precision=1.0000）｜审计流 161 条确定性违规（53.7 条/日，落库待查不呼叫）｜复核队列 189 条（BH-FDR alpha=0.20，受人工复核预算约束）
- 池化回退：格子层权重 B<0.5 的占比 0.400（检测层非 L3 占比 0.017）
- 本体绑定：3/4 个模式簇绑定到声明模式 {"0": "p3", "1": "p1", "2": "p2"}
- span 级归因（诊断，slice2 才设门槛）：Precision=0.659 Recall=0.413 tp=114 fp=59 fn=162

| 异常类型 | 样本 | 命中 | 召回 | 统计通道 | 规则通道 |
|---|---|---|---|---|---|
| normal | 2673 | 2 | 0.001 | 2 | 0 |
| latency_spike | 60 | 13 | 0.217 | 13 | 0 |
| token_bloat | 53 | 13 | 0.245 | 13 | 0 |
| truncation | 38 | 38 | 1.000 | 0 | 38 |
| unfinished | 35 | 25 | 0.714 | 0 | 25 |
| hallucinated_number | 31 | 29 | 0.935 | 0 | 29 |
| missing_step | 29 | 10 | 0.345 | 0 | 10 |
| loop | 25 | 24 | 0.960 | 0 | 24 |
| illegal_step | 21 | 21 | 1.000 | 0 | 21 |
| error | 14 | 14 | 1.000 | 0 | 14 |

## 3 打分（5 维 x 4 锚点 x 硬门禁 x LMDI 零残差）

- 零残差最大偏差 `9.592e-14`（恒等式 sum(contrib) == S - 100G）
- 分数区分度：AUC(-S vs 异常)=0.8920｜正常均分 90.74｜异常均分 50.68｜分离度 40.06
- 与生成器 oracle 维度分的相关：Spearman=0.7879｜Kendall tau-b=0.6074

| 维度 | Spearman(vs oracle) | 正常均值 | 异常均值 |
|---|---|---|---|
| O | 0.9292 | 1.000 | 0.883 |
| P | 0.7683 | 0.999 | 0.913 |
| L | 0.7358 | 0.773 | 0.696 |
| C | 0.9151 | 0.774 | 0.701 |
| R | 0.3003 | 0.971 | 0.940 |

- 绝对档位分布 {"A": 1867, "B": 831, "D": 241, "C": 61}
- 相对档位分布 {"B": 1047, "A": 757, "C": 747, "D": 449}
- 门禁触发次数 {"t1_unfinished": 80, "t0_result_broken": 49, "forbidden_action": 21, "novelty": 21, "loop_runaway": 20, "guard_violation": 18, "t2_untraceable_number": 18}

## 4 校准（交叉拟合，出折外 ECE）

- 方法 platt｜标注数 300｜ECE(出折)=0.0332｜ECE(原始 a_raw)=0.1036｜AUC(校准概率)=0.7510

| bin | n | 预测均值 | 实际频率 |
|---|---|---|---|
| 0 | 146 | 0.071 | 0.082 |
| 1 | 125 | 0.132 | 0.088 |
| 2 | 9 | 0.219 | 0.444 |
| 8 | 2 | 0.861 | 1.000 |
| 9 | 18 | 0.967 | 1.000 |

## 5 数据质量与漂移

- 采集缺陷召回（规范化侧检出率）{"ts_repaired": 1.0, "usage_estimated": 1.0, "orphan_rebuilt": 1.0}
- 真实缺陷轨迹数 {"ts_repaired": 525, "usage_estimated": 843, "orphan_rebuilt": 425}｜被降级置信度的轨迹 1361｜降级率 1.0000
- 漂移：spec=null｜检出=False｜index=None｜真实 index=None｜滞后占比=n/a｜嫌疑轨迹 0

## 6 门槛表（contracts/schemas.md 8）

| 门槛 | 要求 | 实测 | 结论 |
|---|---|---|---|
| ari_intent | >=0.650 (table 0.65, oracle ceiling 1.0000) | 1.0000 | PASS |
| ari_pattern | >=0.550 (table 0.55, oracle ceiling 0.9892) | 0.9804 | PASS |
| conf_downgrade_rate | >=1.00 | 1.000 | PASS |
| ece | <=0.10 | 0.0332 | PASS |
| f1 | >=0.60 | 0.7556 | PASS |
| fpr | <=0.08 | 0.0007 | PASS |
| no_false_drift | detected=false | detected=False stat=9.10 lambda=43.61 | PASS |
| novelty_rate | [0.00,0.25] | 0.007 | PASS |
| operator_stream_precision | >=0.80 @k=15/day=5 | 1.0000 | PASS |
| precision_at_50 | >=0.70 | 1.0000 | PASS |
| zero_residual | <=1e-06 | 9.592e-14 | PASS |

**总体：全部通过**

- 计时 {"ingest_features": 2.8, "cluster": 117.17, "baseline": 0.34, "detect": 0.81, "score": 0.12}


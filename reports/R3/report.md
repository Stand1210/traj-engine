# 基准跑分报告 R3 - heavy overlap + intent ambiguity

- 流水线版本 `slice6-v0.6.0`｜数据集 `2d9e23adcdd4eb4e`｜代码 `d229ab802e5a01bf`｜n=3000（可归簇 2134，覆盖率 0.711）｜冷启动 False｜墙钟 122.8s
- 生成器真值：真实格子数 6｜异常率 0.0900｜异常类型 {"error": 23, "hallucinated_number": 29, "illegal_step": 15, "latency_spike": 48, "loop": 14, "missing_step": 28, "token_bloat": 31, "truncation": 33, "unfinished": 49}
- 端到端时延分布 p50/p90/p99 = 6.84 / 25.23 / 65.06

## 1 聚类（共识双视图 -> 分析格子）

| 指标 | 值 |
|---|---|
| ari_intent | 0.7522 |
| ari_pattern | 0.9866 |
| ari_cell | 0.8528 |
| nmi_intent | 0.6419 |
| nmi_pattern | 0.9775 |
| purity_intent | 0.9339 |
| purity_pattern | 0.9967 |
| ARI 弃权前 / 弃权后（意图 / 模式 / 格子） | 0.4827 -> 0.7522 / 0.9857 -> 0.9866 / 0.6616 -> 0.8528 |
| novelty 缓冲区内 多数真实类占比（意图 / 模式） | 0.6894 / 0.9988 |
| novelty 缓冲区异常率 / 可归簇池异常率 | 0.1039 / 0.0843 |
| 意图簇数 / 真实 | 6 / 2 |
| 模式簇数 / 真实 | 5 / 3 |
| 格子数 / 真实 | 10 / 6 |
| novelty 率 | 0.2887 |
| 意图视图信息上界（oracle，同池 / 全量） | 0.7530 / 0.6261 |
| 模式视图信息上界（oracle，同池 / 全量） | 0.9907 / 0.9934 |
| 上界达成率（意图 / 模式） | 0.9988 / 0.9958 |

## 2 异常识别（L1 稳健z / L2 ECOD / L4 结构 / L5 马尔可夫 + BH-FDR 决策）

| 指标 | 可归簇池 | 全量 |
|---|---|---|
| precision | 0.9716 | 0.9716 |
| recall | 0.7611 | 0.5074 |
| f1 | 0.8536 | 0.6667 |
| fpr | 0.0020 | 0.0015 |

- 排序质量：AUC(a_raw)=0.9580｜PR-AUC=0.8797｜Precision@50=1.0000｜Recall@50=0.2778
- 分诊分层：tier2 确定性违规 124｜tier1 统计拒绝 17｜tier0 其余 1993｜剔除 tier2 后 Precision@50=0.4600（该子池异常基率 0.0284，提升 16.22 倍）
- 告警构成：总计 141（统计 17 + 硬规则 124）｜BH alpha=0.200｜折算 47.00 条/日
- 运营口径（唯一会主动打扰人的通道）：日预算 5 条 x 3 天 = k=15，Precision=1.0000
- 漂移监测：未检出变点｜统计量 -18.40 vs 自举阈值 20.82（alpha=0.01，bootstrap）｜最短窗长 120｜命中窗 null｜窗内高于参考中位数占比 n/a
- 三通道口径区分：告警流 k=15（会主动打扰人，Precision=1.0000）｜审计流 124 条确定性违规（41.3 条/日，落库待查不呼叫）｜复核队列 141 条（BH-FDR alpha=0.20，受人工复核预算约束）
- 池化回退：格子层权重 B<0.5 的占比 0.400（检测层非 L3 占比 0.296）
- 本体绑定：3/3 个模式簇绑定到声明模式 {"0": "p1", "1": "p3", "2": "p2"}
- span 级归因（诊断，slice2 才设门槛）：Precision=0.674 Recall=0.470 tp=62 fp=30 fn=70

| 异常类型 | 样本 | 命中 | 召回 | 统计通道 | 规则通道 |
|---|---|---|---|---|---|
| normal | 1954 | 4 | 0.002 | 3 | 1 |
| unfinished | 38 | 38 | 1.000 | 0 | 38 |
| latency_spike | 34 | 3 | 0.088 | 3 | 0 |
| token_bloat | 21 | 11 | 0.524 | 11 | 0 |
| truncation | 19 | 19 | 1.000 | 0 | 19 |
| error | 18 | 18 | 1.000 | 0 | 18 |
| hallucinated_number | 16 | 14 | 0.875 | 0 | 14 |
| missing_step | 15 | 15 | 1.000 | 0 | 15 |
| loop | 10 | 10 | 1.000 | 0 | 10 |
| illegal_step | 9 | 9 | 1.000 | 0 | 9 |

## 3 打分（5 维 x 4 锚点 x 硬门禁 x LMDI 零残差）

- 零残差最大偏差 `9.681e-14`（恒等式 sum(contrib) == S - 100G）
- 分数区分度：AUC(-S vs 异常)=0.8962｜正常均分 91.15｜异常均分 50.56｜分离度 40.59
- 与生成器 oracle 维度分的相关：Spearman=0.8488｜Kendall tau-b=0.6740

| 维度 | Spearman(vs oracle) | 正常均值 | 异常均值 |
|---|---|---|---|
| O | 0.9774 | 0.999 | 0.846 |
| P | 0.9999 | 1.000 | 0.893 |
| L | 0.8327 | 0.777 | 0.742 |
| C | 0.9204 | 0.764 | 0.755 |
| R | 1.0000 | 0.999 | 0.949 |

- 绝对档位分布 {"A": 1374, "B": 782, "D": 781, "C": 63}
- 相对档位分布 {"B": 1048, "A": 756, "C": 750, "D": 446}
- 门禁触发次数 {"novelty": 866, "t1_unfinished": 50, "t0_result_broken": 45, "forbidden_action": 15, "t2_untraceable_number": 14, "loop_runaway": 11, "guard_violation": 9}

## 4 校准（交叉拟合，出折外 ECE）

- 方法 platt｜标注数 300｜ECE(出折)=0.0323｜ECE(原始 a_raw)=0.1080｜AUC(校准概率)=0.7115

| bin | n | 预测均值 | 实际频率 |
|---|---|---|---|
| 0 | 190 | 0.069 | 0.084 |
| 1 | 82 | 0.131 | 0.073 |
| 2 | 10 | 0.217 | 0.200 |
| 7 | 1 | 0.744 | 1.000 |
| 8 | 1 | 0.823 | 0.000 |
| 9 | 16 | 0.947 | 1.000 |

## 5 数据质量与漂移

- 采集缺陷召回（规范化侧检出率）{"ts_repaired": 1.0, "usage_estimated": 1.0, "orphan_rebuilt": 1.0}
- 真实缺陷轨迹数 {"ts_repaired": 78, "usage_estimated": 112, "orphan_rebuilt": 58}｜被降级置信度的轨迹 186｜降级率 1.0000
- 漂移：spec=null｜检出=False｜index=None｜真实 index=None｜滞后占比=n/a｜嫌疑轨迹 0

## 6 门槛表（contracts/schemas.md 8）

| 门槛 | 要求 | 实测 | 结论 |
|---|---|---|---|
| ari_intent | >=0.550 (table 0.55, oracle ceiling 0.7530) | 0.7522 | PASS |
| ari_pattern | >=0.500 (table 0.50, oracle ceiling 0.9907) | 0.9866 | PASS |
| ece | <=0.10 | 0.0323 | PASS |
| f1 | >=0.60 | 0.8536 | PASS |
| fpr | <=0.08 | 0.0020 | PASS |
| no_false_drift | detected=false | detected=False stat=-18.40 lambda=20.82 | PASS |
| novelty_rate | [0.03,0.30] | 0.289 | PASS |
| operator_stream_precision | >=0.80 @k=15/day=5 | 1.0000 | PASS |
| precision_at_50 | >=0.70 | 1.0000 | PASS |
| zero_residual | <=1e-06 | 9.681e-14 | PASS |

**总体：全部通过**

- 计时 {"ingest_features": 2.94, "cluster": 117.37, "baseline": 0.2, "detect": 0.77, "score": 0.11}


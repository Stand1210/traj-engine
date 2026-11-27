# 基准跑分报告 R8 - foreign ontology

- 流水线版本 `slice6-v0.6.0`｜数据集 `469f903d257a4288`｜代码 `d229ab802e5a01bf`｜n=3000（可归簇 2921，覆盖率 0.974）｜冷启动 False｜墙钟 83.2s
- 生成器真值：真实格子数 9｜异常率 0.0803｜异常类型 {"error": 20, "hallucinated_number": 34, "illegal_step": 18, "latency_spike": 40, "loop": 27, "missing_step": 26, "token_bloat": 29, "truncation": 20, "unfinished": 27}
- 端到端时延分布 p50/p90/p99 = 4.27 / 68.90 / 166.05

## 1 聚类（共识双视图 -> 分析格子）

| 指标 | 值 |
|---|---|
| ari_intent | 1.0000 |
| ari_pattern | 0.8625 |
| ari_cell | 0.8771 |
| nmi_intent | 1.0000 |
| nmi_pattern | 0.8630 |
| purity_intent | 1.0000 |
| purity_pattern | 0.9870 |
| ARI 弃权前 / 弃权后（意图 / 模式 / 格子） | 1.0000 -> 1.0000 / 0.8582 -> 0.8625 / 0.8749 -> 0.8771 |
| novelty 缓冲区内 多数真实类占比（意图 / 模式） | 1.0000 / 0.9620 |
| novelty 缓冲区异常率 / 可归簇池异常率 | 0.1646 / 0.0781 |
| 意图簇数 / 真实 | 3 / 3 |
| 模式簇数 / 真实 | 6 / 3 |
| 格子数 / 真实 | 12 / 9 |
| novelty 率 | 0.0263 |
| 意图视图信息上界（oracle，同池 / 全量） | 1.0000 / 1.0000 |
| 模式视图信息上界（oracle，同池 / 全量） | 0.9978 / 0.9979 |
| 上界达成率（意图 / 模式） | 1.0000 / 0.8644 |

## 2 异常识别（L1 稳健z / L2 ECOD / L4 结构 / L5 马尔可夫 + BH-FDR 决策）

| 指标 | 可归簇池 | 全量 |
|---|---|---|
| precision | 0.9939 | 0.9939 |
| recall | 0.7149 | 0.6763 |
| f1 | 0.8316 | 0.8049 |
| fpr | 0.0004 | 0.0004 |

- 排序质量：AUC(a_raw)=0.9168｜PR-AUC=0.8324｜Precision@50=1.0000｜Recall@50=0.2193
- 分诊分层：tier2 确定性违规 144｜tier1 统计拒绝 20｜tier0 其余 2757｜剔除 tier2 后 Precision@50=0.5000（该子池异常基率 0.0306，提升 16.34 倍）
- 告警构成：总计 164（统计 21 + 硬规则 144）｜BH alpha=0.200｜折算 54.67 条/日
- 运营口径（唯一会主动打扰人的通道）：日预算 5 条 x 3 天 = k=15，Precision=1.0000
- 漂移监测：未检出变点｜统计量 -5.20 vs 自举阈值 22.32（alpha=0.01，bootstrap）｜最短窗长 120｜命中窗 null｜窗内高于参考中位数占比 n/a
- 三通道口径区分：告警流 k=15（会主动打扰人，Precision=1.0000）｜审计流 144 条确定性违规（48.0 条/日，落库待查不呼叫）｜复核队列 164 条（BH-FDR alpha=0.20，受人工复核预算约束）
- 池化回退：格子层权重 B<0.5 的占比 0.083（检测层非 L3 占比 0.032）
- 本体绑定：3/4 个模式簇绑定到声明模式 {"0": "b1", "1": "b2", "2": "b3"}
- span 级归因（诊断，slice2 才设门槛）：Precision=0.643 Recall=0.350 tp=83 fp=46 fn=154

| 异常类型 | 样本 | 命中 | 召回 | 统计通道 | 规则通道 |
|---|---|---|---|---|---|
| normal | 2693 | 1 | 0.000 | 0 | 1 |
| latency_spike | 39 | 10 | 0.256 | 10 | 0 |
| hallucinated_number | 34 | 19 | 0.559 | 0 | 19 |
| token_bloat | 28 | 10 | 0.357 | 10 | 0 |
| unfinished | 27 | 27 | 1.000 | 0 | 27 |
| loop | 26 | 26 | 1.000 | 1 | 26 |
| truncation | 20 | 20 | 1.000 | 0 | 20 |
| error | 18 | 18 | 1.000 | 0 | 18 |
| illegal_step | 18 | 18 | 1.000 | 0 | 18 |
| missing_step | 18 | 15 | 0.833 | 0 | 15 |

## 3 打分（5 维 x 4 锚点 x 硬门禁 x LMDI 零残差）

- 零残差最大偏差 `9.437e-14`（恒等式 sum(contrib) == S - 100G）
- 分数区分度：AUC(-S vs 异常)=0.8594｜正常均分 91.10｜异常均分 52.92｜分离度 38.18
- 与生成器 oracle 维度分的相关：Spearman=0.7965｜Kendall tau-b=0.6284

| 维度 | Spearman(vs oracle) | 正常均值 | 异常均值 |
|---|---|---|---|
| O | 0.8876 | 0.999 | 0.874 |
| P | 0.9945 | 1.000 | 0.908 |
| L | 0.6849 | 0.770 | 0.711 |
| C | 0.9252 | 0.770 | 0.712 |
| R | 1.0000 | 1.000 | 0.943 |

- 绝对档位分布 {"A": 1860, "B": 866, "D": 229, "C": 45}
- 相对档位分布 {"B": 1051, "A": 754, "C": 752, "D": 443}
- 门禁触发次数 {"novelty": 79, "t1_unfinished": 29, "t0_result_broken": 25, "loop_runaway": 19, "forbidden_action": 18, "t2_untraceable_number": 14, "guard_violation": 10}

## 4 校准（交叉拟合，出折外 ECE）

- 方法 platt｜标注数 300｜ECE(出折)=0.0290｜ECE(原始 a_raw)=0.1390｜AUC(校准概率)=0.8261

| bin | n | 预测均值 | 实际频率 |
|---|---|---|---|
| 0 | 250 | 0.052 | 0.032 |
| 1 | 32 | 0.132 | 0.219 |
| 2 | 2 | 0.209 | 0.000 |
| 8 | 1 | 0.839 | 1.000 |
| 9 | 15 | 0.982 | 1.000 |

## 5 数据质量与漂移

- 采集缺陷召回（规范化侧检出率）{"ts_repaired": 1.0, "usage_estimated": 1.0, "orphan_rebuilt": 1.0}
- 真实缺陷轨迹数 {"ts_repaired": 76, "usage_estimated": 123, "orphan_rebuilt": 55}｜被降级置信度的轨迹 202｜降级率 1.0000
- 漂移：spec=null｜检出=False｜index=None｜真实 index=None｜滞后占比=n/a｜嫌疑轨迹 0

## 6 门槛表（contracts/schemas.md 8）

| 门槛 | 要求 | 实测 | 结论 |
|---|---|---|---|
| ari_intent | >=0.650 (table 0.65, oracle ceiling 1.0000) | 1.0000 | PASS |
| ari_pattern | >=0.550 (table 0.55, oracle ceiling 0.9978) | 0.8625 | PASS |
| ece | <=0.10 | 0.0290 | PASS |
| f1 | >=0.65 | 0.8316 | PASS |
| fpr | <=0.06 | 0.0004 | PASS |
| no_false_drift | detected=false | detected=False stat=-5.20 lambda=22.32 | PASS |
| no_hardcoded_actions | [] | [] | PASS |
| novelty_rate | [0.00,0.25] | 0.026 | PASS |
| operator_stream_precision | >=0.80 @k=15/day=5 | 1.0000 | PASS |
| precision_at_50 | >=0.75 | 1.0000 | PASS |
| zero_residual | <=1e-06 | 9.437e-14 | PASS |

**总体：全部通过**

- 计时 {"ingest_features": 2.43, "cluster": 78.31, "baseline": 0.3, "detect": 0.84, "score": 0.1}


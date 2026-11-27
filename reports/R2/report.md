# 基准跑分报告 R2 - trimodal

- 流水线版本 `slice6-v0.6.0`｜数据集 `52470f48253b25a6`｜代码 `d229ab802e5a01bf`｜n=4000（可归簇 3757，覆盖率 0.939）｜冷启动 False｜墙钟 93.3s
- 生成器真值：真实格子数 9｜异常率 0.0745｜异常类型 {"error": 22, "hallucinated_number": 45, "illegal_step": 22, "latency_spike": 46, "loop": 30, "missing_step": 29, "token_bloat": 40, "truncation": 33, "unfinished": 31}
- 端到端时延分布 p50/p90/p99 = 3.05 / 67.13 / 152.98

## 1 聚类（共识双视图 -> 分析格子）

| 指标 | 值 |
|---|---|
| ari_intent | 1.0000 |
| ari_pattern | 0.9941 |
| ari_cell | 0.9959 |
| nmi_intent | 1.0000 |
| nmi_pattern | 0.9893 |
| purity_intent | 1.0000 |
| purity_pattern | 0.9981 |
| ARI 弃权前 / 弃权后（意图 / 模式 / 格子） | 1.0000 -> 1.0000 / 0.9075 -> 0.9941 / 0.9103 -> 0.9959 |
| novelty 缓冲区内 多数真实类占比（意图 / 模式） | 1.0000 / 0.9877 |
| novelty 缓冲区异常率 / 可归簇池异常率 | 0.1152 / 0.0719 |
| 意图簇数 / 真实 | 3 / 3 |
| 模式簇数 / 真实 | 4 / 3 |
| 格子数 / 真实 | 9 / 9 |
| novelty 率 | 0.0607 |
| 意图视图信息上界（oracle，同池 / 全量） | 1.0000 / 1.0000 |
| 模式视图信息上界（oracle，同池 / 全量） | 0.9958 / 0.9960 |
| 上界达成率（意图 / 模式） | 1.0000 / 0.9983 |

## 2 异常识别（L1 稳健z / L2 ECOD / L4 结构 / L5 马尔可夫 + BH-FDR 决策）

| 指标 | 可归簇池 | 全量 |
|---|---|---|
| precision | 0.9814 | 0.9814 |
| recall | 0.7815 | 0.7081 |
| f1 | 0.8701 | 0.8226 |
| fpr | 0.0011 | 0.0011 |

- 排序质量：AUC(a_raw)=0.9709｜PR-AUC=0.8925｜Precision@50=1.0000｜Recall@50=0.1852
- 分诊分层：tier2 确定性违规 188｜tier1 统计拒绝 27｜tier0 其余 3542｜剔除 tier2 后 Precision@50=0.7600（该子池异常基率 0.0238，提升 31.91 倍）
- 告警构成：总计 215（统计 27 + 硬规则 188）｜BH alpha=0.200｜折算 71.67 条/日
- 运营口径（唯一会主动打扰人的通道）：日预算 5 条 x 3 天 = k=15，Precision=1.0000
- 漂移监测：未检出变点｜统计量 -25.10 vs 自举阈值 17.51（alpha=0.01，bootstrap）｜最短窗长 160｜命中窗 null｜窗内高于参考中位数占比 n/a
- 三通道口径区分：告警流 k=15（会主动打扰人，Precision=1.0000）｜审计流 188 条确定性违规（62.7 条/日，落库待查不呼叫）｜复核队列 215 条（BH-FDR alpha=0.20，受人工复核预算约束）
- 池化回退：格子层权重 B<0.5 的占比 0.000（检测层非 L3 占比 0.061）
- 本体绑定：3/3 个模式簇绑定到声明模式 {"0": "p3", "1": "p1", "2": "p2"}
- span 级归因（诊断，slice2 才设门槛）：Precision=0.658 Recall=0.366 tp=96 fp=50 fn=166

| 异常类型 | 样本 | 命中 | 召回 | 统计通道 | 规则通道 |
|---|---|---|---|---|---|
| normal | 3487 | 4 | 0.001 | 1 | 3 |
| hallucinated_number | 42 | 37 | 0.881 | 0 | 37 |
| latency_spike | 41 | 6 | 0.146 | 6 | 0 |
| token_bloat | 39 | 20 | 0.513 | 20 | 0 |
| truncation | 31 | 31 | 1.000 | 0 | 31 |
| loop | 28 | 28 | 1.000 | 0 | 28 |
| unfinished | 27 | 27 | 1.000 | 0 | 27 |
| missing_step | 24 | 24 | 1.000 | 0 | 24 |
| error | 21 | 21 | 1.000 | 0 | 21 |
| illegal_step | 17 | 17 | 1.000 | 0 | 17 |

## 3 打分（5 维 x 4 锚点 x 硬门禁 x LMDI 零残差）

- 零残差最大偏差 `9.592e-14`（恒等式 sum(contrib) == S - 100G）
- 分数区分度：AUC(-S vs 异常)=0.9051｜正常均分 91.00｜异常均分 50.29｜分离度 40.71
- 与生成器 oracle 维度分的相关：Spearman=0.8168｜Kendall tau-b=0.6487

| 维度 | Spearman(vs oracle) | 正常均值 | 异常均值 |
|---|---|---|---|
| O | 0.9573 | 0.999 | 0.854 |
| P | 1.0000 | 1.000 | 0.921 |
| L | 0.7251 | 0.766 | 0.718 |
| C | 0.9246 | 0.771 | 0.692 |
| R | 1.0000 | 0.999 | 0.946 |

- 绝对档位分布 {"A": 2425, "B": 1122, "D": 367, "C": 86}
- 相对档位分布 {"B": 1398, "A": 1006, "C": 1001, "D": 595}
- 门禁触发次数 {"novelty": 243, "t0_result_broken": 45, "t1_unfinished": 34, "t2_untraceable_number": 27, "forbidden_action": 22, "loop_runaway": 22, "guard_violation": 14}

## 4 校准（交叉拟合，出折外 ECE）

- 方法 isotonic｜标注数 500｜ECE(出折)=0.0082｜ECE(原始 a_raw)=0.1291｜AUC(校准概率)=0.7042

| bin | n | 预测均值 | 实际频率 |
|---|---|---|---|
| 0 | 431 | 0.050 | 0.053 |
| 1 | 35 | 0.164 | 0.171 |
| 2 | 11 | 0.200 | 0.091 |
| 5 | 2 | 0.500 | 0.500 |
| 7 | 3 | 0.745 | 0.667 |
| 9 | 18 | 0.995 | 0.944 |

## 5 数据质量与漂移

- 采集缺陷召回（规范化侧检出率）{"ts_repaired": 1.0, "usage_estimated": 1.0, "orphan_rebuilt": 1.0}
- 真实缺陷轨迹数 {"ts_repaired": 90, "usage_estimated": 111, "orphan_rebuilt": 52}｜被降级置信度的轨迹 193｜降级率 1.0000
- 漂移：spec=null｜检出=False｜index=None｜真实 index=None｜滞后占比=n/a｜嫌疑轨迹 0

## 6 门槛表（contracts/schemas.md 8）

| 门槛 | 要求 | 实测 | 结论 |
|---|---|---|---|
| ari_intent | >=0.650 (table 0.65, oracle ceiling 1.0000) | 1.0000 | PASS |
| ari_pattern | >=0.550 (table 0.55, oracle ceiling 0.9958) | 0.9941 | PASS |
| ece | <=0.08 | 0.0082 | PASS |
| f1 | >=0.65 | 0.8701 | PASS |
| fpr | <=0.06 | 0.0011 | PASS |
| no_false_drift | detected=false | detected=False stat=-25.10 lambda=17.51 | PASS |
| novelty_rate | [0.00,0.25] | 0.061 | PASS |
| operator_stream_precision | >=0.80 @k=15/day=5 | 1.0000 | PASS |
| precision_at_50 | >=0.75 | 1.0000 | PASS |
| zero_residual | <=1e-06 | 9.592e-14 | PASS |

**总体：全部通过**

- 计时 {"ingest_features": 4.58, "cluster": 85.61, "baseline": 0.33, "detect": 1.12, "score": 0.13}


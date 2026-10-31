# 基准跑分报告 R6 - cold start

- 流水线版本 `slice4-v0.4.0`｜数据集 `6df7cb38491a91dd`｜代码 `c7e53c3d81d94dcc`｜n=600（可归簇 591，覆盖率 0.985）｜冷启动 True｜墙钟 101.5s
- 生成器真值：真实格子数 6｜异常率 0.1017｜异常类型 {"error": 3, "hallucinated_number": 5, "illegal_step": 7, "latency_spike": 13, "loop": 6, "missing_step": 4, "token_bloat": 8, "truncation": 8, "unfinished": 7}
- 端到端时延分布 p50/p90/p99 = 2.01 / 60.73 / 130.18

## 1 聚类（共识双视图 -> 分析格子）

| 指标 | 值 |
|---|---|
| ari_intent | 1.0000 |
| ari_pattern | 0.9949 |
| ari_cell | 0.9946 |
| nmi_intent | 1.0000 |
| nmi_pattern | 0.9900 |
| purity_intent | 1.0000 |
| purity_pattern | 0.9983 |
| ARI 弃权前 / 弃权后（意图 / 模式 / 格子） | 1.0000 -> 1.0000 / 0.9887 -> 0.9949 / 0.9899 -> 0.9946 |
| novelty 缓冲区内 多数真实类占比（意图 / 模式） | 1.0000 / 1.0000 |
| novelty 缓冲区异常率 / 可归簇池异常率 | 0.4444 / 0.0964 |
| 意图簇数 / 真实 | 2 / 2 |
| 模式簇数 / 真实 | 5 / 3 |
| 格子数 / 真实 | 6 / 6 |
| novelty 率 | 0.0150 |
| 意图视图信息上界（oracle，同池 / 全量） | 1.0000 / 1.0000 |
| 模式视图信息上界（oracle，同池 / 全量） | 0.9949 / 0.9950 |
| 上界达成率（意图 / 模式） | 1.0000 / 1.0000 |

## 2 异常识别（L1 稳健z / L2 ECOD / L4 结构 / L5 马尔可夫 + BH-FDR 决策）

| 指标 | 可归簇池 | 全量 |
|---|---|---|
| precision | 0.0000 | 0.0000 |
| recall | 0.0000 | 0.0000 |
| f1 | 0.0000 | 0.0000 |
| fpr | 0.0000 | 0.0000 |

- 排序质量：AUC(a_raw)=0.9172｜PR-AUC=0.8194｜Precision@50=0.8200｜Recall@50=0.7193
- 分诊分层：tier2 确定性违规 34｜tier1 统计拒绝 4｜tier0 其余 553｜剔除 tier2 后 Precision@50=0.2400（该子池异常基率 0.0413，提升 5.81 倍）
- 告警构成：总计 0（统计 0 + 硬规则 0）｜BH alpha=0.200｜折算 0.00 条/日
- 运营口径（唯一会主动打扰人的通道）：日预算 5 条 x 0 天 = k=1，Precision=1.0000
- 漂移监测：未检出变点｜统计量 n/a vs 自举阈值 n/a（alpha=0.00，None）｜最短窗长 0｜命中窗 null｜窗内高于参考中位数占比 n/a
- 三通道口径区分：告警流 k=1（会主动打扰人，Precision=1.0000）｜审计流 0 条确定性违规（0.0 条/日，落库待查不呼叫）｜复核队列 0 条（BH-FDR alpha=0.20，受人工复核预算约束）
- 池化回退：格子层权重 B<0.5 的占比 0.000（检测层非 L3 占比 0.015）
- 本体绑定：3/3 个模式簇绑定到声明模式 {"0": "p3", "1": "p1", "2": "p2"}
- span 级归因（诊断，slice2 才设门槛）：Precision=0.750 Recall=0.466 tp=27 fp=9 fn=31

| 异常类型 | 样本 | 命中 | 召回 | 统计通道 | 规则通道 |
|---|---|---|---|---|---|
| normal | 534 | 0 | 0.000 | 0 | 0 |
| latency_spike | 13 | 0 | 0.000 | 0 | 0 |
| token_bloat | 8 | 0 | 0.000 | 0 | 0 |
| truncation | 8 | 0 | 0.000 | 0 | 0 |
| unfinished | 7 | 0 | 0.000 | 0 | 0 |
| illegal_step | 6 | 0 | 0.000 | 0 | 0 |
| loop | 6 | 0 | 0.000 | 0 | 0 |
| hallucinated_number | 5 | 0 | 0.000 | 0 | 0 |
| error | 3 | 0 | 0.000 | 0 | 0 |
| missing_step | 1 | 0 | 0.000 | 0 | 0 |

## 3 打分（5 维 x 4 锚点 x 硬门禁 x LMDI 零残差）

- 零残差最大偏差 `9.059e-14`（恒等式 sum(contrib) == S - 100G）
- 分数区分度：AUC(-S vs 异常)=0.8873｜正常均分 90.84｜异常均分 48.17｜分离度 42.66
- 与生成器 oracle 维度分的相关：Spearman=0.8113｜Kendall tau-b=0.6341

| 维度 | Spearman(vs oracle) | 正常均值 | 异常均值 |
|---|---|---|---|
| O | 0.9555 | 0.999 | 0.886 |
| P | 0.9999 | 1.000 | 0.908 |
| L | 0.7737 | 0.774 | 0.731 |
| C | 0.9084 | 0.768 | 0.719 |
| R | 1.0000 | 1.000 | 0.958 |

- 绝对档位分布 {"A": 375, "B": 160, "D": 54, "C": 11}
- 相对档位分布 {"B": 208, "A": 154, "C": 152, "D": 86}
- 门禁触发次数 {"t1_unfinished": 15, "novelty": 9, "t0_result_broken": 9, "forbidden_action": 7, "guard_violation": 5, "loop_runaway": 3, "t2_untraceable_number": 3}

## 4 校准（交叉拟合，出折外 ECE）

- 标注数不足（<60），跳过校准；冷启动阶段只出分数不出概率。

## 5 数据质量与漂移

- 采集缺陷召回（规范化侧检出率）{"ts_repaired": 1.0, "usage_estimated": 1.0, "orphan_rebuilt": 1.0}
- 真实缺陷轨迹数 {"ts_repaired": 15, "usage_estimated": 20, "orphan_rebuilt": 6}｜被降级置信度的轨迹 35｜降级率 1.0000
- 漂移：spec=null｜检出=False｜index=None｜真实 index=None｜滞后占比=n/a｜嫌疑轨迹 0

## 6 门槛表（contracts/schemas.md 8）

| 门槛 | 要求 | 实测 | 结论 |
|---|---|---|---|
| cold_start_flag | true | True | PASS |
| zero_alerts | <=0 | 0 | PASS |
| zero_residual | <=1e-06 | 9.059e-14 | PASS |

**总体：全部通过**

- 计时 {"ingest_features": 0.47, "cluster": 100.65, "baseline": 0.06, "detect": 0.18, "score": 0.02}


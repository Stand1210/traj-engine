# M5.0 性能与生产可行性基线

> 日期：2026-11-14。以下数据来自本机 Windows / Python 3.11 的一次受控运行，
> 用于发现瓶颈方向，不作为 SLA 或跨环境承诺。

## 1. 基线工具

新增 `platform/scripts/performance_baseline.py`：

- 使用基准 R1 轨迹循环克隆，生成指定规模的独立 `trace_id` / `session_id`。
- 依次执行：
  1. R2 冷启动结构与全量打分。
  2. R1 固定结构刷新与打分。
  3. 生命周期调度扫描（看门狗 + 状态评估，不额外创建 Run）。
  4. 核心 SQL 查询计时：Run 分页、轨迹分页、告警轨迹、证据、active 结构、
     调度扫描审计分页。
- 输出 JSON 报告，默认写入 `platform/var/performance-baseline.json`。
- 压测数据库与 Run 产物放在 `platform/var/perf-*` 临时目录，结束后自动删除。

常用命令：

```powershell
python platform/scripts/performance_baseline.py --traces 100000 --output platform/var/performance-baseline.json
```

调试或冒烟：

```powershell
python platform/scripts/performance_baseline.py --traces 24 --query-repeat 2 --timeout-seconds 60
```

## 2. 100 条实测结果

| 指标 | 数值 |
|---|---:|
| R2 总耗时 | 180.890 s |
| R2 algorithm step | 180.093 s |
| R2 每条耗时 | 1,808.897 ms |
| R1 总耗时 | 1.835 s |
| R1 algorithm step | 1.189 s |
| 调度扫描耗时 | 0.024 s |
| SQLite 大小 | 1,204,224 B |
| Run 产物大小 | 2,094,178 B |
| Python 峰值分配 | 4,578,266 B |

数据量：

| 表 | 行数 |
|---|---:|
| `cohort_runs` | 2 |
| `run_steps` | 12 |
| `cells` | 12 |
| `trace_scores` | 200 |
| `score_evidence` | 1,000 |
| `alert_decisions` | 2 |
| `structure_versions` | 1 |

查询中位数：

| 查询 | median |
|---|---:|
| Run 分页 | 0.192 ms |
| 轨迹分数分页 | 2.380 ms |
| 告警轨迹 | 0.266 ms |
| 单轨迹证据 | 0.431 ms |
| active 结构 | 0.127 ms |
| 调度扫描分页 | 0.162 ms |

## 3. 关键瓶颈结论

1. **R2 冷启动是当前唯一硬瓶颈。**
   - 100 条 R2 的 99.6% 时间耗在 algorithm step。
   - R1 同规模仅 1.835 s，说明固定结构分配与打分路径可扩展。
   - 查询与调度扫描均处于毫秒级，当前不是瓶颈。
2. **1,000 条 R2 在 600 秒内未完成。**
   - 该结果在锁重试修复后复现，不是数据库锁导致。
   - 结合 100 条耗时，R2 路径呈现明显超线性增长，优先怀疑聚类/共识阶段的
     pairwise 计算。
3. **10 万条/天目标当前不可直接承诺。**
   - 每日 R2 全量冷启动不可行。
   - 需要改为抽样训练 + 全量冻结结构分配，或对 R2 训练集设置规模上限。
4. **SQLite 写入与查询在小规模下健康。**
   - 压测期间曾因 50ms 高频轮询与持久化事务竞争出现 `database is locked`。
   - 工具已改为 500ms 轮询并加入锁重试，压测框架不再干扰被测系统。

## 4. M5.1 建议方向

## 4. M5.1 CPU Profile

对 100 条 R2 执行 `cProfile`：

| 热点 | 累计耗时 | 占比 |
|---|---:|---:|
| `cluster_views` | 117.602 s | 99.7% |
| `silhouette` | 78.904 s | 67.0% |
| `kmeans_cent` | 35.964 s | 30.5% |
| `euclid` | 79.225 s | 67.2% |

结论：瓶颈不是 UPGMA 或 SQLite，而是意图视图 k-means 选 k 时的
silhouette 距离计算。该路径随参与结构学习的样本数平方增长。

## 5. M5.1 抽样训练实现

已实现工程层 R2 抽样训练，未修改 `kernel/`：

1. 当 R2 全量轨迹数超过 `r2TrainingLimit` 时，先做确定性等距抽样。
2. 仅用训练样本执行结构学习，生成 frozen structure。
3. 再用该 frozen structure 对全量轨迹执行分配、异常识别和打分。
4. Run 仍保持 `R2` 语义，并创建新的 structure version 与 lineage。
5. `algorithm` Run Step 记录：
   - `training.sampled=true`
   - `trainingTraceCount`
   - `fullTraceCount`
   - `strategy=systematic`

配置文件：`platform/config/performance.yaml`

```yaml
r2TrainingLimit: 64
```

## 6. 优化后实测

| 规模 | R2 | R1 | SQLite | 峰值内存 | 结果 |
|---:|---:|---:|---:|---:|---|
| 1,000 | 102.986 s | 21.859 s | 9,076,736 B | 23,421,613 B | 成功 |
| 10,000 | 299.149 s | 293.025 s | 88,051,712 B | 221,447,153 B | 成功 |

1,000 条从“600 秒超时”变为 103 秒完成。10,000 条完整 R2/R1 双 Run
可在约 10 分钟内完成。

10,000 条查询中位数：

| 查询 | median |
|---|---:|
| Run 分页 | 0.439 ms |
| 轨迹分数分页 | 67.514 ms |
| 告警轨迹 | 31.557 ms |
| 单轨迹证据 | 89.424 ms |
| active 结构 | 0.056 ms |
| 调度扫描分页 | 0.059 ms |

> 10,000 条查询中位数以 `platform/var/performance-baseline-10000-sampled.json`
> 为准；该文件是本机运行产物，不入库。

## 7. 剩余风险

1. 当前实现仍一次性加载全量轨迹并在内存中完成分配与持久化：
   - 10,000 条峰值内存约 221 MB。
   - 线性外推 100,000 条约 2.2 GB，内网部署前必须做流式化。
2. R1 与优化后 R2 在 10,000 条下耗时接近，说明剩余成本主要在全量
   特征提取、检测、评分和 SQLite 持久化。
3. 下一阶段应做 M5.2：
   - TraceSource 流式读取。
   - 分批特征提取与评分。
   - 分批写库，避免一次性保存全部 score/evidence。
   - 对 100,000 条重新压测。

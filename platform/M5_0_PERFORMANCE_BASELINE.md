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

1. 对 R2 algorithm step 做 CPU profile，定位 pairwise 距离、共识矩阵或
   UPGMA 中的热点。
2. 评估 R2 抽样训练：
   - 训练/结构发现仅使用分层抽样样本。
   - 全量轨迹用冻结结构执行 R1 式分配与打分。
3. 为 R2 增加训练规模上限与超时预算，避免单租户冷启动拖垮调度线程。
4. 在压测工具中增加多租户、多本体并发场景，验证调度锁和 SQLite 写锁。
5. 待 R2 优化后重新执行 1,000 / 10,000 / 100,000 三档基线。

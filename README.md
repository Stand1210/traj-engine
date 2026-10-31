# traj-engine：智能体轨迹聚类 / 异常识别 / 打分 通用算法工程

目标形态：**通用算法内核 + 可插拔业务本体 + 有门控的适配流程**。

先建标准基准数据集（`bench/`），再以基准驱动内核（`kernel/`）逐切片开发；任何业务接入只装配
工件与本体（`ontology/`），按 `adapt/playbook.md` 的门控流程放量。**不使用任何生成式判官**：
相同输入位级一致，分数携带模型版本号，扣分归因可逐条对账。

方法论出处：`insight-reports/风险与轨迹/智能体轨迹聚类异常识别与打分方法论设计.md`。

当前版本：数据集生成器 `bench-gen-v3.1.0`｜流水线 `slice4-v0.4.0`｜数据契约 v1.3.1。

## 目录

- `contracts/schemas.md` — 数据契约 v1.3.1：输入（含 token 口径两条约定）/ 特征（v1 冻结 21 项
  + v2 40 余项 + v3 34 项，后两者已发射未接线）/ 簇 / 检测 / 打分 / 真值 schema、regime DSL、
  **门槛表（含信息上界封顶）**、三通道口径、关键机制的实现约束、本体接口、
  **§12 数据集产物与溯源（`meta.json` 契约 / `spec_hash` 构成 / 嵌入几何与标定证据 /
  §12.5.1 溯源第二跳：跑分 ↔ 数据集 / §12.6 派生文档与守卫）**
- `bench/` — 基准套件
  - `regime.py` — 8 个 regime 规格与门槛（变化轴而非业务：峰数 / 稀疏 / 残缺 / 冷启动 / 漂移 / 异本体）
  - `generate.py` — 参数化生成器，种子固定、纯 Python、无 numpy，随数据发射真值
  - `invariants.py` — 12 条业务无关不变量
  - `runner.py` — 全链路跑分 + 门槛判定 + 报告渲染
  - `show.py` — 人类可读检视器：把单条 trace 渲染成 Span 树，并把真值与算法输出并排显示
  - `coverage.py` — 数据集充分性审计：**`spec_hash` 新鲜度对账**、字段清单 vs 77 特征合同、
    逐特征活性、异常×regime 矩阵、**标签↔真值↔特征全量一致性**、
    **独立参考实现差分测试**、自动缺口清单（**已查清并接受的缺口带处置结论**，
    含实测数据与被否决的修法，直接渲染进报告）
  - `scorecard.py` — 本文件「当前跑分」五个区块的**生成器与漂移守卫**：表格是 `reports/` 的
    派生数据，手写就会悄悄过期，因此改成派生。`--check` 不写盘，做**三级对账**：
    README ↔ `reports/*/metrics.json`（跑分区块是否漂移）、
    `metrics.json["spec_hash"]` ↔ `data/bench_v1/*/meta.json`（**跑分是否属于当前数据集**）、
    `metrics.json["code_hash"]` ↔ 活的 `runner.code_hash()`（**跑分是否由当前内核产出**，
    即改了 `kernel/` 却忘了重跑 runner——数据没动，`spec_hash` 那一跳看不见），任一不符即退出 1
  - `reprocheck.py` — **数据集的字节身份证**：把生成器重跑一遍到临时目录，与已提交的 240 MB
    逐文件 sha256 对账，外加 8 份 `SAMPLE.md` 的幂等重生成。`coverage.dataset_provenance()`
    对账的是 `spec_hash`，而 `spec_hash` 哈希的是 regime **规格**、不是**发射出来的字节**——
    删一条 trace、加一个 BOM、或把整份文件转成 CRLF，`spec_hash` 依旧合法、provenance 依旧 PASS。
    本机全局 `core.autocrlf=true`，这不是假想。默认严格逐字节（实测 8 regime + 8 份 SAMPLE.md
    全等，53.0s）；`--numeric-tol REL` 提供跨 libc 的结构化回退：sha 先试（相同就走快路径），
    不符才逐字段比，并**打印实测到的最大相对偏差**，让新平台自己量出自己的可移植性
  - `matrixcheck.py` — **流水线可复现性对账**：把 `runner --out` 的产物与已提交的 `reports/`
    做三层比对——`scores.jsonl` 整文件 sha256（每条轨迹的算法输出，4000 条全等则聚合量不可能不等）、
    `metrics.json` 逐叶子（每 regime 379–437 个叶子，排除 6 个机器相关项，全矩阵共比对 **3334** 个值）、
    `report.md` 全文（屏蔽 2 行机器相关行）。门槛带是四位小数宽（F1 ≥ 0.70、ARI ≥ 0.55），
    公布的数字也是四位小数——一个把指标挪动 1e-5 却仍落在带内的改动，能同时通过其余四条门禁，
    并让 README、专利交底书、方法论文档里的每一个数字静默失效
- `kernel/` — 业务无关算法内核
  - `ingest.py` — 规范化（孤儿 Span 重建、时间戳修复、usage 重算），纯函数，缺失置空而非置 0；
    缺失率在修复**之前**按 Span 类型的条件可得字段集测量
  - `features.py` — 特征宽表抽取（v1 21 项 + v2 40 余项 + v3 34 项；所有占比类特征一律按区间并集
    且排除根 Span；两个跨记录特征由 `annotate_sessions()` 补齐）
  - `cluster.py` — 双视图共识聚类 → 二维分析格子（袋装 + 中位数阶 + 共现轮廓系数 + 后验余量弃权；
    两个视图的轮廓系数均为 **k-neutral** 口径）
  - `baseline.py` — 簇内条件基线：四档锚点 P10/P50/P90/P99、L3→L2→L1 credibility 池化、对数尺度尾部模型
  - `binding.py` — 模式簇 → 本体声明工作流的绑定
  - `detect.py` — L1–L5 五层偏离度 + 单次 Bonferroni + BH-FDR + 分诊分层
  - `drift.py` — 符号 CUSUM + 右锚定窗 + 双重采样自举阈值 + 两级参考矩梯（cell → parent → 弃权）
  - `score.py` — 5 维 × 4 锚点 × 硬门禁 × LMDI 零残差 → S ∈ [0,100]；O 维为**四通道加权**
    （数字可溯源 / 事实精度 / 执行成功 / 结构完整），R 维为**三通道加权**
    （步骤失败率 / 未恢复错误 / 循环规则），P 维为**五通道加权 + 归因门**
    （违规动作 / 确认未完成 / 循环饱和 / 声明工作流缺失比例 / 目标漂移），
    缺失通道一律**丢弃并重归一**而非填常数，通道准入以**污染实测**为准，
    准入之外再加一条**归因门**：别的维度已认领的证据，本维度不再投票
    （见下方 slice2 / slice3 / slice4 三节）
  - `calib.py` — 交叉拟合等渗校准，`a_raw → a_cal` 概率
  - `meta.py` — ARI / NMI / purity / PRF / AUC / PR-AUC / Spearman / Kendall / ECE；**`point_adjust` 调用即抛异常**
- `ontology/base.py` — 可插拔业务本体（ontA / ontB 两套，各声明 3 个工作流；文本模板、模型价目、
  工具目录、参数键、告警文案全部在本体里，内核不含任何硬编码业务动作）
- `adapt/playbook.md` — 适配六步流程、**可调白名单 vs 锁定参数**、α 的三口径、取值纪律、失败模式处方
- `data/bench_v1/` — 生成产物（`traces.jsonl` + `gt.jsonl` + `meta.json`，带 `spec_hash`，可复现可 diff）；
  每个 regime 另有 `SAMPLE.md`（人类可读样本手册，8 个样本，由 `bench.show --sample` 生成）。
  **注意耦合**：`show.py` 会读 `reports/<rid>/scores.jsonl` 并把分数渲染进去，所以 `SAMPLE.md` 是
  **数据集 × 流水线输出**的共同派生物——任何改动打分的切片都必须重生成全 8 份，
  否则 `reprocheck --sample` 会报 0/8（slice2 实际踩到，已写进下方一节）；
  顶层 `COVERAGE.md` 为数据集充分性审计报告
- `reports/<rid>/` — 每个 regime 的 `report.md` / `metrics.json` / `scores.jsonl`
- `.github/workflows/` — 两档 CI。`gates.yml` 每次 push/PR 跑五道门禁（双 OS）；
  `matrix.yml` 在改了 `kernel/ ontology/ bench/ contracts/ data/` 时、以及每周日跑全矩阵重算 +
  逐叶子对账（双 OS）
- `.gitattributes` — **不是可选项**：`*.jsonl -text` + 源码文档 `eol=lf`。本机全局
  `core.autocrlf=true`，没有它一次 checkout 就会把 240 MB 数据全改写成 CRLF，
  README 里公布的每个 sha 与 MiB 口径同时失效。实测：加了它之后，在本机 `git clone` 出来的
  84 个文件与源目录 sha256 **零失配**

## 运行

```
python -m bench.generate --regimes R1,R2,R3,R4,R5,R6,R7,R8   # 生成标准数据集
python -m bench.invariants                                   # 12 条业务无关不变量
python -m bench.runner  --regimes R1,R2,R3,R4,R5,R6,R7,R8    # 全链路跑分 + 门槛 + 报告
python -m bench.scorecard                                    # 用跑分结果重写本文件「当前跑分」五个区块
python -m bench.coverage --md                                # 数据集够不够用：充分性审计（写 COVERAGE.md）
python -m bench.reprocheck --sample                          # 数据集字节身份：重生成后逐文件 sha256 对账
python -m bench.runner  --regimes R1,R2,R3,R4,R5,R6,R7,R8 --out /tmp/reports-ci  # 跑分到临时目录
python -m bench.matrixcheck --candidate /tmp/reports-ci      # 流水线可复现性：与已提交 reports/ 三层对账
```

三条验证命令全绿即视为可开工：`invariants` 12/12、`runner` 8/8 regime ALL-PASS、`coverage` 退出码 0。
`coverage` 的退出码同时受三道硬门约束：**`spec_hash` 与当前生成器不符**（数据集是旧代码产的）、
**标签↔真值↔特征不一致**（任一条）或**差分测试不通过**（`probe()` 与 `kernel/features.py`
任一特征不一致）都会返回 1。

第四条是文档守卫，不进上面三条：`python -m bench.scorecard --check` 做**三级对账**——
① README 的跑分区块与 `reports/*/metrics.json` **逐格一致**（只放过墙钟：同一份代码同一份数据，
R1 在连续两次独占跑分里分别测到 95.6s 与 100.7s，机器负载决定的量不该当门禁用）；
② 每份 `metrics.json` 的 `spec_hash` 与 `data/bench_v1/*/meta.json` **相符**，即**跑分确实属于
盘上这份数据集**；③ 每份 `metrics.json` 的 `code_hash` 与活的 `runner.code_hash()` **相符**，
即**跑分确实由盘上这份内核产出**。②③ 都是必要的：只派生 README 的话，数据重生成或内核改动之后
忘了重跑 runner，`--check` 会拿一份描述旧世界的跑分把 README 重写成"完全自洽且完全过期"，
照样报 IN SYNC。加上 `coverage` 的 `dataset_provenance`（数据 ↔ 活的生成器），链条是
**生成器 → 数据 → 跑分 → README**，详见 `contracts/schemas.md §12.5.1`。
任何调参后重跑 `runner`，都应顺手跑一次 `scorecard`（写盘）或 `scorecard --check`（只读断言）。

第五条是**数据身份**：`python -m bench.reprocheck --sample`。前四条都相信盘上这份数据是生成器
产出的，只有它去验证这件事——重跑 `bench.generate` 到临时目录，与已提交文件逐一对 sha256。
`spec_hash` 那一跳看不见字节级损伤，因为它哈希的是规格不是产物。

第六条是**流水线身份**：`python -m bench.matrixcheck --candidate <dir>`。前五条都不比较
**两次运行**：门槛只要求 F1 ≥ 0.70，而 README 公布的是 0.8807。把 `runner` 跑进
`--out /tmp/reports-ci` 再与已提交的 `reports/` 三层对账，才能证明公布的那些四位小数
仍然是这套代码产出的。

单个 regime：`python -m bench.runner --regimes R3`。可选覆盖：`--threshold`（共识阈值）、
`--bh-alpha`（复核队列目标 FDR）、`--limit`、`--force-gen`。

### 看数据（JSONL 一行一条，直接打开没法读）

```
python -m bench.show R1 --stats                        # 数据集侧写：条数 / Span 数 / 异常率 / 类型分布
python -m bench.show R1 R1-00357                       # 单条：Span 树 + 真值 + 算法输出（输入→真值→输出闭环）
python -m bench.show R1 --list latency_spike 5         # 按异常类型找 trace_id
python -m bench.show R1 --list hallucinated_number 5 --golden   # 只看带 golden 答案的
python -m bench.show R1 --sample                       # 重新生成 data/bench_v1/R1/SAMPLE.md
```

单条渲染里，Span 树每一步除 `in:` / `out:` 外还有两行：`meta:`
（`model` / `tool_name` / `level` / `ttft` / `prompt_version` / `tool_params` / `output_facts` /
`status_message`）与 `v3 :`（`sys` / `cache_r` / `cache_w` / `cost_det={...}` / `arg_valid` /
`verifier=<id>:PASS|FAIL` / `subgoal=` / `retrieved=[...]`）。v3 单独成行是因为它每一项都
**按 Span 类型条件可得**，折进 `meta:` 会让一个工具 Span 广告它从没跑过的 verifier。
轨迹头部有 `turn` / `goal_text` / `query_lang` / `user_feedback` / `answer_facts` /
`golden_answer` / `golden_facts`。真值块除 v2 的 `loop_true` / `mfr_true` / `model_mix_true` /
`has_golden` / `key_fact_recall_true` / `fact_precision_true` / `hallucinated_facts` 外，
v3 再列 `query_lang_true` / `session_turn_count_true` / `subgoal_count` / `plan_revision_true` /
`goal_drift_true` / `arg_valid_true` / `verifier_pass_true` / `citation_reachable_true` /
`contradiction_true` / `contradicted_count` / `fabricated_citation_count` / `cache_read_true` /
`cache_write_true` / `system_prompt_ratio_true` / `cost_details_reconciled_true`。
把真值印出来的理由与 v2 相同：`coverage.truth_agreement()` 对它们与对应内核特征做**双向等价**
断言，所以这里看得见的不一致是构建失败，不是趣闻。自 bench-gen-v3 起记录里带**真实中文**
（`intent_text` / `goal_text` / `subgoal_text` / 答案 / 标准答案），控制台输出因此强制 ASCII，
中文原文只落在 `SAMPLE.md` 里。

`bench/coverage.py` 输出 `data/bench_v1/COVERAGE.md`，回答“数据集**存在**”与“数据集**足够**”的差别：
恒定的特征无法验证建立在它上面的检测器，缺失的原始字段则无论怎么写代码都实现不了。
它现在由**三道硬门**给出退出码：`spec_hash` 新鲜度对账、标签↔真值↔特征全量一致、
独立参考实现差分测试。当前审计结论：**合同阻断项 0 条、保真度失败 0 条、过期 regime 0 条**，
22,800 条轨迹的标签↔真值↔特征全量一致，
13 个合同特征与独立参考实现逐条一致（最大绝对差 0），8/8 regime 的 `spec_hash` 与当前生成器相符，
句向量参与比 40.0–125.9 / 384（各向同性团会是 384，直接判失败）。自动问题清单还剩 **1 条**
（R3 的 `reformulation_signal` 恒为 0.0），已给出处置结论并**接受**：`GAP_DISPOSITIONS` 把结论
连同实测分布与被否决的三条修法一起渲染进报告，所以清单里不会留下一个无人解释的洞；gap 不进
退出码。仍不足以支撑的部分
（语义文本是本体模板、嵌入未经真实编码器、v2/v3 特征未接线）在该文件第二节明确列出。

`bench/show.py` 是只读检视器，不参与跑分，控制台输出为纯 ASCII（GBK 控制台安全），
中文叙述只写进 `SAMPLE.md`。

## 持续集成

两档，都是 `windows-latest` + `ubuntu-latest` 双 OS、`fail-fast: false`、`permissions: contents read`、
`defaults.run.shell: bash`（Windows 上走 Git Bash，YAML 才能两边通用）。**不装任何第三方依赖**——
项目本来就是纯标准库，这也是双 OS 矩阵跑得起、且「确定性可复现」这句话可审计的原因。

| | `.github/workflows/gates.yml` | `.github/workflows/matrix.yml` |
|---|---|---|
| 触发 | 每次 push / PR / 手动 | 改 `kernel/ ontology/ bench/ contracts/ data/`、每周日 03:17（北京时间）、手动 |
| 时长 | 本机约 2 分钟 | 本机 750s，共享 runner 上按 90 分钟设超时 |
| 内容 | 五道门禁：`invariants` → `reprocheck --sample` → `coverage --md` → `scorecard --check` → 重生成派生文档后 `git diff --exit-code` | `runner` 全矩阵跑进临时目录 → `matrixcheck` 三层对账 → `git diff --exit-code` → 上传产物（失败也传，便于离线 diff） |
| 并发 | `cancel-in-progress: true`（快，重来便宜） | `false`（40 分钟的跑分值得跑完） |

**两个 OS 跑的不是同一条断言，这是量出来的、不是偷懒**。已提交的基线产于 Windows/MSVC，
所以 `windows-latest` 那一腿断言**逐字节相等**；`ubuntu-latest` 是另一套 libc，而 IEEE-754
**不要求** `exp` / `log` / `erf` / `erfc` / `pow` 正确舍入，本仓库用了 `math.log` 17 次、
`math.exp` 7 次、`math.erfc` 1 次、`**` 107 次——包括 `bench/generate.py:765` 的
`lat = math.exp(math.log(med) + sig * z_l)`，而 `ts_start` / `ts_end` / `cost` 是**全精度发射**的
（实测形如 `1767225604.0650926`），只有 `embedding`（5 位）、`ttft`（6 位）、`latency_true`（4 位）
被粗化过。所以 Linux 那一腿用 `--numeric-tol 1e-12` / `--rel-tol 1e-12`：sha256 照样先试，
不符才回退到结构化比对，并**把实测到的最大相对偏差打印出来**。偏差打印为 0.0 就说明该平台
其实逐位可复现、容差根本没被用到——这是把「可移植性」变成每次 CI 都在量的东西，而不是假设。

**上面这段现在是量出来的，不是推测**。`matrix.yml` 首跑 run 40995616332（ubuntu-24.04 /
Python 3.11.17 / GCC 13.3.0 对 Windows 产的基线，3334 个 metrics 叶子）量到了偏差，也量出了
校验器自己的两个 bug——ubuntu 腿当时是**判红**的，经过见「本轮修复」第 13 条。
修好后 run 40998664364 复跑，两腿全绿，结论如下：

- **数据集逐位相同**。同一台 runner 上 `reprocheck --numeric-tol 1e-12` 报
  `worst relative float deviation observed: 0.000e+00`，容差根本没被用到——glibc 的
  `exp` / `log` 与 MSVC CRT 对生成器喂给它们的每一个值都末位一致。
- **流水线不是**：58 个叶子有差，分布在 5/8 个 regime。浮点叶子的最大偏差 `4.441e-16`
  （= 2 ulp）；连同 `gates.zero_residual.got` 那个字符串叶子一起，整体报为 `4.500e-16`，
  比 1e-12 的容差还小六个数量级。复跑的汇总是 `8/8 regimes PASS, 3/8 byte-identical
  (3334 metric leaves compared, 4 differences absorbed by the tolerance)`——R1 / R2 / R6
  连 `scores.jsonl` 的 sha256 都两侧相同，被吸收的 4 处全在 R8（2 个 metrics 叶子 +
  2 行 `report.md`，都是那同一个零残差噪声地板）。
  而这 58 个**全是同一个字段 `a_cal`**（等渗校准后的异常概率），因果链已完全定位：
  `math.erfc`（`kernel/baseline.py:543`，流水线独有；生成器用的是 `math.erf`，
  `bench/generate.py:553`）→ `stage` 里**未取整**的 `a_raw` → `IsotonicCalibrator._one`
  在结点之间做**线性插值**（`kernel/calib.py:93`）。落在结点上或落在区间外的 trace
  原样返回结点值、逐位相同，只有严格落在两结点之间的才继承那 1 ulp——
  这正是每个 regime 只有 4~18 条动、而不是全部动的原因。
- **没有级联**。F1 / P@50 / FPR / AUC / ARI、五个维度分、等级带、每一条 LMDI 贡献量
  全部逐位相同，8/8 regime 仍然 `gates=ALL-PASS`。下一段担心的「1 ulp 翻掉一个浮点比较」
  **实测没有发生**：发射出去的 `a_raw` 取整到 5 位小数（`bench/runner.py:723`），
  而门槛带有 4 位小数宽。
- **同机严格判据是全矩阵尺度的，不是抽样**。`windows-latest` 那一腿复跑报
  `8/8 regimes PASS, 8/8 byte-identical (3334 metric leaves compared, 0 differences absorbed
  by the tolerance)`：8 个 regime 从原始 trace 重新跑完整条流水线，产出与已提交基线
  逐字节相同，容差一次都没被用到。在此之前这条只在 R4 一个 regime 上被单独证明过。
- 顺带量到一条与 `.gitattributes` 有关的：`windows-latest` runner 的全局 `core.autocrlf`
  实测就是 `true`，而 `gates` 那一腿的严格逐字节 `reprocheck` 照样 8/8 通过、
  连 8 个 `SAMPLE.md` 都零告警。把 `*.jsonl` 标成 binary 这件事是在真 runner 上验证过的，
  不是纸面推演。
- **slice2 是第一次在「流水线被改过」的前提下跑这套对账**，commit `5ec0e71`，
  `gates` run 41024716299 / `matrix` run 41024716466，四条 job 全绿。这一跑同时验证了
  容差机制在**真改动**下不会失灵：`windows-latest` 腿仍是
  `8/8 regimes PASS, 8/8 byte-identical (3334 leaves, 0 differences absorbed)`；
  `ubuntu-latest` 腿 `8/8 PASS, 3/8 byte-identical (3334 leaves, 0 differences absorbed)`，
  `worst relative float deviation observed: 2.776e-17`——比上一轮的 `4.500e-16` 又小一个数量级，
  且这次**字符串叶子一处都没被吸收**（上轮 R8 那 4 处零残差噪声地板恰好两侧渲染一致）。
  `gates` 两腿的 `reprocheck --sample` 都是 `8/8 regimes reproduced | warnings=0 incl. SAMPLE.md`，
  ubuntu 腿照旧 `0.000e+00`；派生文档守卫两腿都报
  `README.md, COVERAGE.md and SAMPLE.md are byte-identical after regeneration`——
  即本轮重生成的 8 份 `SAMPLE.md` 与 CI 独立重算的结果逐字节一致。
- **slice3 是第二次在「流水线被改过」的前提下跑这套对账**，commit `18005ef`，
  `gates` run 41036262104 / `matrix` run 41036262008，四条 job 全绿。
  `windows-latest` 腿 `8/8 regimes PASS, 8/8 byte-identical (3334 leaves, 0 differences absorbed)`；
  `ubuntu-latest` 腿 `8/8 PASS, 3/8 byte-identical (3334 leaves, 0 differences absorbed)`，
  `worst relative float deviation observed: 2.776e-17`——与 slice2 那一轮**逐位相同**，
  且仍是 R1 / R2 / R6 三条 `scores.jsonl` 的 sha256 两侧全等。这不是巧合：slice3 只改 R 块，
  而那条 1 ulp 的因果链（`math.erfc` → 未取整的 `a_raw` → 等渗插值）一个环节都没碰到，
  所以跨 libc 的偏差地板原地不动。**这条恰好是对「改动面被正确隔离」的独立证据**：
  如果 slice3 意外碰到了校准或基线，这个数字会变。
  `gates` 两腿的 `reprocheck --sample` 都是 `8/8 regimes reproduced | warnings=0 incl. SAMPLE.md`
  （windows `mode=strict` 25.3s、ubuntu `mode=numeric-tol 1e-12` 24.8s 且照旧 `0.000e+00`）；
  两腿 `invariants 12/12`、`coverage -> DATASET READY`、`scorecard IN SYNC`、
  派生文档守卫均报 `README.md, COVERAGE.md and SAMPLE.md are byte-identical after regeneration`。

1e-12 相对容差比任何算法改动能造成的变化还小八个数量级（门槛带四位小数宽，真改动至少动 1e-4），
所以它藏不住回归。但它也**不该被用来掩盖级联**：末位差有可能翻掉一个浮点**比较**，
比如 novelty 分数差 1 ulp 就改变池成员，进而改变 `n_pool` 与它下游的每个聚合量——
真发生时逐叶子 diff 会指名道姓地给出是从哪个指标开始分叉的，这正是要的结果。

`PYTHONHASHSEED` **故意不固定**。默认是每进程随机种子，所以任何代码路径一旦开始依赖 str 的
哈希顺序，CI 会当场红掉，而不是被 CI 环境悄悄冻成「确定性」。实测现状：`kernel/ bench/ ontology/`
里没有裸 `hash()` 调用，每个 `set()` 都包在 `sorted()` 里，每处 `glob()` / `os.listdir()` 也都排序。

## 数据集规模（bench-gen-v3.1.0）

22,800 条轨迹 / 118,687 个 Span（每条 5.21 个）/ 1,903 条异常（8.3%）/ 8 个 regime /
句向量 **384 维**。带 golden 答案 5,949 条（26.1%，只在数值型答案上发射）；带用户反馈
5,636 条（24.7%）；真循环（参数完全相同的 ≥3 次重复）178 条；注入字段丢失 12,693 处；
人工标注预算合计 2,350 条（150 / 300 / 500 三档，R6 冷启动为 0）。
9 类异常 × 8 regime 全覆盖，最薄的一格 3 条（R6 冷启动的 `error`），其余每格 ≥ 4 条。
落盘 **228.8 MiB ≈ 240 MB**（`traces.jsonl` + `gt.jsonl` + `meta.json`；另 8 份 `SAMPLE.md` 合计 0.70 MB 未计入）。

相对 v2.2.0 的**数据面**扩容：Span 增补 8 个字段、Trace 增补 5 个字段、GT 增补 17 个真值字段、
本体增补 18 个键；特征在 v1 冻结 21 项 + v2 的 40 余项之上再加 v3 的 34 项。
句向量从 16 维各向同性高斯 blob 换成 **384 维各向异性、带话题连续谱**的真实形态
（逐维参与比：审计的 200 条抽样口径实测 40.0–125.9 / 384，`meta.json` 的全量口径 72.3–131.7——小样本逐维方差更噪，读数系统性偏低，两个数都对；各向同性团会是 384，单维塔缩会是 1.0000，两端都会被判失败）。

<!-- scorecard:header:begin -->
## 当前跑分（流水线 `slice4-v0.4.0`，8/8 regime 全门槛通过，全矩阵约 819s）
<!-- scorecard:header:end -->

`ARI_pattern` 列的括号内是「oracle 同池上界 / **弃权前**（关掉 novelty、按最近簇给全部轨迹打分）」。
弃权前那一列是诚实性口径，见「前轮修复 5」。

<!-- scorecard:main:begin -->
| regime | 分布形态 | n | 可归簇 | novelty | ARI_intent（上界） | ARI_pattern（上界 / 弃权前） | novelty 纯度 | F1 | P@50 | FPR | AUC | ECE | 漂移 | 墙钟 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| R1 | bimodal main path | 4000 | 3945 | 0.0138 | 1.0000 (1.0000) | 0.9976 (0.9976 / 0.9856) | 0.8545 | 0.881 | 1.000 | 0.0003 | 0.966 | 0.0167 | 无漂移，-12.5 vs λ 12.3 | 111.3s |
| R2 | trimodal | 4000 | 3967 | 0.0083 | 1.0000 (1.0000) | 0.9912 (0.9960 / 0.9913) | 1.0000 | 0.867 | 1.000 | 0.0011 | 0.971 | 0.0127 | 无漂移，-31.1 vs λ 21.1 | 94.4s |
| R3 | heavy overlap + intent ambiguity | 3000 | 2140 | 0.2867 | 0.7512 (0.7521) | 0.9866 (0.9907 / 0.9893) | 0.9988 | 0.796 | 1.000 | 0.0020 | 0.916 | 0.0330 | 无漂移，-18.4 vs λ 18.8 | 127.1s |
| R4 | extremely sparse cells | 1200 | 1021 | 0.1492 | 1.0000 (1.0000) | 0.9879 (0.9938 / 0.9842) | 0.9888 | 0.787 | 0.980 | 0.0011 | 0.927 | 0.0200 | 无漂移，-14.3 vs λ 42.2 | 82.3s |
| R5 | heavily corrupted telemetry | 3000 | 2979 | 0.0070 | 1.0000 (1.0000) | 0.9804 (0.9892 / 0.9798) | 1.0000 | 0.756 | 1.000 | 0.0007 | 0.913 | 0.0332 | 无漂移，9.1 vs λ 43.6 | 107.7s |
| R6 | cold start | 600 | 591 | 0.0150 | 1.0000 (1.0000) | 0.9949 (0.9949 / 0.9887) | 1.0000 | 0.000 | 0.820 | 0.0000 | 0.917 | 0.0000 | 冷启动抑制 | 101.5s |
| R7 | mid-stream drift x1.6 | 4000 | 3968 | 0.0080 | 1.0000 (1.0000) | 0.9891 (0.9953 / 0.9868) | 1.0000 | 0.823 | 1.000 | 0.0005 | 0.922 | 0.0118 | 检出 idx 2001 / 真值 2000，lag +1（963.1 vs λ 17.6） | 113.3s |
| R8 | foreign ontology | 3000 | 2930 | 0.0233 | 1.0000 (1.0000) | 0.9723 (0.9978 / 0.9721) | 0.9857 | 0.838 | 1.000 | 0.0004 | 0.922 | 0.0333 | 无漂移，-7.2 vs λ 42.5 | 81.8s |
<!-- scorecard:main:end -->

<!-- scorecard:notes:begin -->
- F1 取 `detection["pool"]["f1"]`（门控后、可归簇池上），不是 `detection["all"]["f1"]`。
- R6 的 F1 = 0.000 是**要求的行为**：冷启动只出分不告警，其门槛是 `cold_start=true 且告警数=0`。
- R3 的 `ari_intent` 门槛表值 0.55、oracle 上界 0.7521；`0.9 x 0.7521 = 0.677 > 0.55`，
  所以封顶没有生效，有效门槛就是 0.55；实测 **0.7512，即上界的 99.88 百分位**，不是压线通过。
- R7 漂移检出滞后 **+1**（检出 idx 2001 / 真值 2000，统计量 963.1 对 λ 17.6）；
  门槛要求 `lag_frac ∈ [-0.05, 0.10]`，实测 0.0003。
- 弃权计价：R1 `ari_pattern` 弃权前 0.9856 → 池上 0.9976（净买 +0.012），缓冲区纯度 0.8545；
  R8 弃权前 0.9721 → 池上 0.9723，几乎没差，弃权没有买分；而其上界是 0.9978，
  差的 2.5 个百分点是异本体下**真实的聚类难度**。
<!-- scorecard:notes:end -->

打分质量：

<!-- scorecard:scoring:begin -->
| regime | 正常均分 | 异常均分 | 分离度 | Spearman(vs oracle) | 零残差最大偏差 |
|---|---|---|---|---|---|
| R1 | 90.2 | 47.6 | 42.6 | 0.810 | 9.5e-14 |
| R2 | 89.9 | 49.8 | 40.0 | 0.795 | 9.7e-14 |
| R3 | 90.2 | 51.2 | 39.0 | 0.832 | 9.7e-14 |
| R4 | 90.4 | 51.2 | 39.2 | 0.806 | 9.4e-14 |
| R5 | 91.0 | 50.8 | 40.2 | 0.803 | 9.6e-14 |
| R6 | 90.8 | 48.2 | 42.7 | 0.811 | 9.1e-14 |
| R7 | 88.0 | 50.3 | 37.6 | 0.748 | 9.4e-14 |
| R8 | 90.6 | 53.5 | 37.1 | 0.783 | 9.4e-14 |
<!-- scorecard:scoring:end -->

<!-- scorecard:channels:begin -->
三通道口径（R1，72h 窗口）：**告警流** k=15、Precision 1.000（唯一会主动打扰人的通道）｜
**审计流** 180 条确定性违规 = 60.0 条/日（落库待查不呼叫）｜**复核队列** 215 条
（统计 35 + 硬规则 180，BH-FDR α=0.20），剔除 tier2 后 Precision@50 = 0.760
（该子池异常基率 0.0242，提升 31.4 倍）。
<!-- scorecard:channels:end -->

## 本轮修复（`bench-gen-v2.2.0` → `v3.1.0`，附实测证据）

1. **意图视图的轮廓系数带 k 偏置，八个 regime 一律回答 k=2**。`silhouette()` 的分离项取
   「到**最近**其他簇」的距离，每多分出一个簇只会让 `b_i` 变小，因此该指标**结构性偏向粗划分**。
   它在全仓只有一个调用点——意图视图选 k，而其余地方用的都是 `silhouette_dm`。后果：意图视图在
   R2/R4/R8 上的插入式 Bayes 上界都是 **1.0000**（数据完全可分），实测却一律报
   `k_intent_consensus = 2`。意图方向排在一条弧上，分得最开的 2-cut 恰好是弧的两半，它以明显
   优势赢得经典指标（R4：k=2 时 0.3639 对真 k=4 时 0.3153）。
   修法：分离项改为「到**全部**簇外质量的重心距」（k-neutral），与 `silhouette_dm` 对齐。
   实测 R4 精确恢复 k=4（`ari_intent` 0.4810 → **1.0000**），R8 0.7485 → 0.8827；
   R4 的第二个门槛 `pooling_fallback_share ≥ 0.5` 也随之从 0.286 升到 **0.769**
   （k=2 时簇少而大，回落到池化基线的自然就少）。

2. **R4 的 `ari_intent` 只有 0.4810，而它自己的上界是 1.0000**——诊断顺序值得记下来。
   先怀疑嵌入几何：标定后发现 R4（4 意图）的 `ari_km / ari_iso = 0.705`，即 k-means 只能拿到
   各向同性 oracle 的七成，几何确实有问题；但把几何修好之后 R4 **仍是 0.4810**，说明真正的
   根因在模型顺序，也就是第 1 条。两处都修完才到 1.0000。只看其中一个会得出错误结论。

3. **嵌入几何标定：`topic_amp` 7.0 → 10.0，背景尺度 `bg_mu` −2.5 → −0.90、
   `bg_sigma` 1.0 → 0.45**。判据是参与比 `PR = (Σs²)²/Σs⁴`（有效承载信号的维度数）与
   信噪比恒等式 `SNR_iso = (topic_amp/σ_e)·‖δ‖·√(PR/EMB_DIM)`。改前背景尺度过重，
   PR 只有 23–32 / 384，话题信号被 350 多个噪声维淹没；改后 PR 40–126：
   4 意图场景 `ari_km` 0.6970 → **1.0000**，3 意图 1.0000 / 1.0000，
   2 意图 + 歧义 0.55 时 `ari_iso 0.6159 / ari_wht 0.6397 / ari_km 0.6081`
   （km/iso = 0.987，无监督已贴近有监督上界）。10.0 是**能修好 4 意图的最小值**
   （分离度/噪声半径在 7.0 时为 1.25、10.0 时为 1.78）；不再上调是因为到 14.0 时 `overlap`
   这根变化轴会失效（overlap 0.88 下 `ari_iso` 仍为 1.0000）。
   **被否决的替代方案**（都实测过）：
   - 单纯调小 `bg_sigma`：`PR ≈ (f²S+(d−S))² / (f⁴S+(d−S))` 在对比度 f=13 时对**任何**
     `bg_sigma` 都只给 20.6；实测 `ari_km` 只从 0.0974 动到 0.2313（km/iso 0.705）。
   - 单纯调大 `overlap`：在**平坦**几何上（`bg_sigma` 0.05，PR 296–301）km/iso 仍随
     overlap 0.88 / 1.20 / 1.55 / 1.90 / 2.40 崩到 0.997 / 0.986 / 0.908 / 0.052 / 0.034。
     说明问题不在重叠度，而在背景尺度把 PR 压死了。

4. **R3 重造：`overlap` 0.88 → 0.70，新增 `intent_ambiguity` 0.50**。R3 是唯一带 novelty
   **下限**门槛的 regime，它必须真的产出「不属于任何已知任务类」的流量。只调 `overlap` 做不到
   ——它加的是各向同性噪声，会让整簇一起模糊，而不是产出一小撮真正跨界的问题。
   `intent_ambiguity` 才是对的机制：把每条轨迹按比例 `t = amb × 2 × Beta(2,6)` 拉向其余意图的
   均值，造出真实的意图连续谱。扫描（真跑 `cluster_views`，n=3000，seed 103）：

   | ambiguity | overlap | ari_intent | 上界 | 达成率 | novelty | 结论 |
   |---|---|---|---|---|---|---|
   | 0.55 | 0.30 | 0.6218 | 0.6208 | 1.002 | 0.0063 | novelty 低于下限 |
   | 0.40 | 0.88 | 0.7959 | 0.8328 | 0.956 | 0.0540 | 上界过高，门槛失去约束力 |
   | 0.45 | 0.88 | 0.7176 | 0.7457 | 0.962 | 0.1887 | novelty 逼近上限 |
   | **0.50** | **0.70** | 0.6776 | 0.6929 | 0.978 | 0.0570 | **选定** |
   | 0.55 | 0.55 | 0.5798 | 0.5819 | 0.996 | 0.0327 | novelty 只有下限的 1.09 倍 |

   **被否决的替代方案：桥接人群（bridge）**。曾实现 `intent_bridge` + `intent_bridge_jitter`，
   在两个意图的分界面附近停一批轨迹。实测 novelty 随 bridge 0.04–0.07 × jitter 0.010–0.020
   摆动为 0.0097 / 0.0200 / 0.3617 / 0.0230 / 0.0170；而**参数完全相同、只有随机流不同**的
   两次生成给出 0.0717 与 0.0230——40 倍的离散度托不住任何门槛带。另一个更根本的错误：
   jitter 必须用**噪声单位**而不是 `t` 的单位来陈述，沿判别方向两个质心相距 **34.9 个噪声
   标准差**，所以 jitter 0.06 把「边界」轨迹停在某一类内部 2.1 个标准差处，那里根本没有任何
   东西会触发弃权。机制已完整回滚，仅作为被否决项留档。

5. **数据集新鲜度此前无人校验**。`spec_hash` 只在生成时写入 `meta.json`，没有任何组件重算它。
   桥接机制回滚后，8 个 regime 里有 7 个的 `meta.json` 仍残留一个已经不存在的键
   （`emb_geometry.intent_bridge = 0.0`），而 `traces.jsonl` / `gt.jsonl` 恰好逐字节相同
   （该机制取 0.0 时不消耗随机流），于是门槛 8/8 全绿、覆盖率审计零阻塞，**没有任何信号提示
   元数据已过期**。修法：`bench/coverage.py::dataset_provenance()` 用活的 `GEN_VERSION`
   重算全部 regime 的 `spec_hash` 并对账，不符即退出码 1。负向测试已验证：篡改 `spec.overlap`
   立刻被判为 stale，还原后恢复干净。

6. **`query_embedding` 保真度检查名不副实**。它的 `required` 字符串早就写着
   「anisotropic, topic continuum」，函数体上方的 docstring 更点名「16 维各向同性高斯团」正是
   要防的失效模式——但代码只断言了 `dim >= 384`。修法：新增 `contract.participation_ratio()`，
   直接由数据算 `PR = (Σσ_d²)²/Σσ_d⁴`（200 条抽样），要求 `1 < PR < EMB_PR_MAX_FRAC × dim`
   （0.75）。实测本数据集 40.0–125.9 / 384，而各向同性团恰为 384，会被直接拒绝。这样几何一旦
   被未来的重标定悄悄压塌，会在覆盖率审计当场失败，而不是变成一个任何内核改动都抬不动的聚类门槛。

7. **README 的「当前跑分」区块一直是手写的派生数据，本轮对账抓到它错了两处**。派生数据手写
   就会悄悄过期，而且没有任何门禁看它——这与第 5 条的 `meta.json` 过期是同一类失效。
   新增 `bench/scorecard.py`，先以 `--check` 只读对账，实测到两条不一致：
   一是 `全矩阵约 782s`（本轮独占重跑实测 **743s**）；二是 R8「弃权没有买分」那句里的
   `差的 2.6 个百分点`——2.6 来自 `ari_pattern_ceiling_all − ari_pattern_all = 2.5769`，
   而那句话的上下文比的是**池上**口径 `0.9978 − 0.9723 = 2.5466`，应为 **2.5**。
   两个口径混用，人眼看不出来。
   修法不是加断言而是**改成派生**：五个区块（标题行 / 主表 / 注解 / 打分表 / 三通道口径）用
   `<!-- scorecard:<name>:begin/end -->` 包住，由 `reports/*/metrics.json` 重算重写；
   首次运行按行首锚点自动落标记，之后幂等。墙钟列在 `--check` 里被**显式屏蔽**——同码同数据
   两次独占跑分 R1 分别测到 95.6s 与 100.7s，机器负载决定的量不该当门禁。
   负向测试：把 R3 的 `ari_pattern` 篡改成 0.5，`--check` 退出 1 并逐行打印差异；还原后恢复
   IN SYNC，数值位级回滚。
   **但只派生 README 还不够**：`--check` 于是做两级对账，第二级是
   `reports/*/metrics.json` 的 `spec_hash` ↔ `data/bench_v1/*/meta.json`。缺了它，数据重生成后
   忘了重跑 runner 时，`scorecard` 会拿一份描述**旧数据**的跑分把 README 重写成完全自洽的样子
   并报 IN SYNC——这与第 5 条 `meta.json` 过期是同一类失效，只是往后挪了一跳。
   `bench/coverage.dataset_provenance()` 对账的是「数据 ↔ 活的生成器」，
   `scorecard.reports_provenance()` 对账的是「跑分 ↔ 数据」，两跳都补上链条才闭合。
   负向测试：把 R5 的 `spec_hash` 改成 `0`×16，`--check` 退出 1 并直接给出
   `re-run python -m bench.runner --regimes R5`；还原后恢复 IN SYNC。

8. **分数此前只带数据身份，不带代码身份**。`metrics.json` 里有 `spec_hash`（属于哪份数据）与
   `pipeline_version`（手维护字符串，会落后于它命名的代码），但没有任何字段说明产出它的
   `kernel/` 长什么样。后果：改了内核却忘了重跑 runner，`reports/` 仍在描述旧行为，而
   `spec_hash` 那一跳完全看不见（数据没动）——`scorecard` 会拿这份过期跑分把 README 重写成
   完全自洽的样子并报 IN SYNC。本轮实测踩到：给 `kernel/features.py` 改完 docstring 之后，
   唯一能证明「8/8 全绿属于盘上这份代码」的手段，是一支一次性的 mtime 比对脚本。
   修法：`bench/runner.py::code_hash()` = 对闭包里每个文件取 `sha256(相对路径 + 内容 sha256)`
   再整体 sha256、截 16 位十六进制，写进 `metrics.json["code_hash"]` 与 `report.md` 抬头；
   `scorecard.reports_provenance()` 拿它与活的 `code_hash()` 对账，不符即 STALE。
   闭包**按作用域取，不读 `sys.modules`**——后者会让哈希取决于「谁在问」：`bench.scorecard`
   导入 `bench.runner` 时它自己也在 `sys.modules` 里，两边永远对不上。`kernel/` 与 `ontology/`
   下每个模块都被 runner 导入，所以直接哈希整个目录既完备又与调用方无关。
   负向测试：往 `kernel/meta.py`、`ontology/base.py` 各追加一行注释，哈希分别移动；改
   `bench/scorecard.py` 哈希不动（正确地在闭包外）；全部还原后位级回到原值。
   **闭包按目录取而非逐个列，本轮立刻就回报了**：整目录哈希把一个从没被注意过的
   `kernel/schema.py` 也算了进去，去查它有没有人用，结果发现它是无人导入、且与契约矛盾的
   v1 残骸（见第 9 条）。

9. **`kernel/schema.py` 是无人导入、且与数据契约矛盾的 v1 残骸，已删除**。它的 docstring 自称
   「Typed records mirroring contracts/schemas.md」，实测三件事：
   ① 全仓**零个模块导入它**——runner 的 import 列表里没有，`ingest` / `features` /
   `cluster` 全程用 dict；② 它的 `Span` 只有数据实际 29 个字段里的 **13** 个，v2/v3 的 16 个
   （`tokens_cache_read` / `tokens_cache_write` / `tokens_system_prompt` / `cost_details` /
   `arg_valid` / `verifier` / `subgoal_text` / `tool_params` / `tool_name` / `model` / `ttft` /
   `level` / `status_message` / `prompt_version` / `output_facts` / `output_citations`）
   全部缺席；③ 它的 `Trace` 还带两个**数据里根本不存在**的字段——`flags`（真名是 `raw_flags`）
   与 `missing_field_ratio`（该项在 v1 就修掉了，现在是 ingest 的**输出**而不是输入）。
   危害不是「没用」而是**误导**：slice2 的开发者要找类型化记录，第一个翻到的就是它，
   然后按 v1 的形状建东西、静默丢掉 16 个 Span 字段。它同时在 `code_hash` 的闭包里，
   改它会让全部跑分失效却不影响任何行为。修它比删它贵：补齐到 v1.3.1 之后**仍然没有消费者**，
   而且没有东西能阻止它再次漂走（要防漂移就得再加一条审计）。删除。
   发现它的方式见第 8 条。

10. **前五条门禁全绿，也不能证明盘上那 240 MB 是生成器产出的**。`spec_hash` 哈希的是 regime
    规格，不是发射出来的字节：删一条 trace、加一个 BOM、整份转 CRLF，`spec_hash` 都依旧合法，
    `coverage.dataset_provenance()` 依旧 PASS。本机全局 `core.autocrlf=true`，一次绕过
    `.gitattributes` 的拷贝就足以让 README 里每个 sha 与 MiB 口径静默失真。
    修法：新增 `bench/reprocheck.py`，重跑生成器到临时目录后逐文件 sha256 对账；
    `SAMPLE.md` 因为 `bench.show.write_sample()` 的输出路径是硬编码的、无法重定向，
    改用幂等性对账（前后各取一次 sha），**不符时写回它读到的原始字节、绝不写回自己的输出**——
    一个会顺手「修好」被检文件的校验工具，毁掉的正是运维需要的证据。
    实测：R6 三个文件 1.0s 内全等；8 regime + 8 份 `SAMPLE.md` 53.0s 全等。
    负向测试 9 项：多一个尾换行、LF→CRLF、加 BOM、删最后一条 trace、改一个浮点、
    改 `SAMPLE.md`、未知 regime（退出 2）、还原后复绿、全程工作树不留脏。

11. **`matrixcheck` 的第一版少屏蔽了一行，是端到端跑分抓到的，不是读代码抓到的**。
    初版只屏蔽 `report.md` 抬头里的墙钟，依据是一次对字面量 `timings` 的 grep——而这个词
    在渲染出来的 Markdown 里**根本不出现**，因为那一行的标签是中文「计时」（`bench/runner.py:892`）。
    基于拷贝的测试也抓不到：它拿一个文件跟它自己的副本比。只有一次真实的
    `runner --regimes R4 --out <临时目录>`（95.5s）才在 report 第 114 行暴露出来。
    现在两行都屏蔽，并且**比对屏蔽数量本身**——将来谁再加一行机器相关输出，
    屏蔽数变了会直接判失败，而不是静默放过。修好后 R4 端到端复绿：
    `scores.jsonl` sha 两侧同为 `9dc0fa2a1e157873`、420 个 metrics 叶子全等、
    `report.md` 屏蔽 2 行后全等。**这是「流水线逐位可复现」第一次被机械证明**。

12. **`--numeric-tol` 差点变成一个后门：CRLF 翻转在容差模式下比对通过**。
    三重归一化叠加所致——`io.open(..., encoding="utf-8")` 走 universal-newline 翻译、
    `str.splitlines()` 本身也按 `\r\n` 切、`json.loads()` 又把尾部 `\r` 当 JSON 空白接受。
    也就是说，把 240 MB 整份从 LF 转成 CRLF（正是全局 `core.autocrlf=true` 对漏掉
    `.gitattributes` 的 checkout 所做的事），结构化回退会报「完全一致」。
    初版 docstring 还写着「CRLF 会让该行解析失败」，是错的。
    修法：`compare_numeric()` 改成先读**二进制**、数 CR 字节，任一侧非零直接判失败——
    数据集契约本来就是 LF-only（所有 writer 都传 `newline="\n"`，`.gitattributes` 把 `*.jsonl`
    标为 binary 使任何 checkout 都无法改写它），所以 CR 是契约损伤，不是该被容差吸收的东西。
    负向测试复跑：报出 `carriage return present (600 ...)`，23/23 全绿。

13. **CI 第一次跨平台对账就抓到两个校验器自身的 bug，两个都不是流水线的问题**。
    `matrix.yml` 首跑：`windows-latest` 全绿（逐字节），`ubuntu-latest` 在 `matrixcheck` 判红。
    - **类型盲的字符串叶子**（真 bug）。`metrics.json` 把每个门槛读数存成**预渲染字符串**
      ——全矩阵 66 个这样的叶子，分布在 11 个 `gates.*.got` 路径上——目的是让数据与
      `report.md` 不可能各说各话。其中 10 个渲染成 3~4 位小数，2 ulp 的抖动够不着第 4 位；
      第 11 个是 `gates.zero_residual.got`，用 `%.3e` 渲染一个**本身就是纯舍入误差**的量。
      Linux 产出 `'9.415e-14'`、基线是 `'9.370e-14'`：在 0~100 的分值尺度上绝对差
      4.5e-16，但按字符串比就是两个不相等的串，整腿因此判红——`--rel-tol` 当时只放宽
      float，够不着它。修法：认**裸十进制字面量**（`NUMSTR_FULL`）并按数值比。
      这不放宽任何东西：regime id、`PASS`/`FAIL`、版本号都解析不出来，照样逐字节；
      而 `same_value` **先比类型**，所以 float→str 的类型变更即使数值相同也判失败。
      `report.md` 同理，但多一道守卫：先剥掉所有数字 token、**残余文本必须逐字节相同**，
      再按序把数字配对。少了这道守卫，`- F1 0.838` 与 `- F2 0.838` 就会被容差放过去。
      考虑过并**否决**了再加一个 `--abs-tol`：`within()` 的分母本来就在 1.0 处截断，
      量级小于 1 的叶子走的已经是绝对判据，多一个旋钮只会多一处自相矛盾的可能。
    - **汇总计数说谎**（真 bug）。原来写的是 `checked if allok else 0`——只要有一个 regime
      失败就打印 `0/8 regimes identical`，而事实是 7/8 通过、3/8 逐字节相同。
      这会把人支去找一场并不存在的全面崩塌，真相只是一个叶子。现在三个数分开报：
      `regimes PASS` / `byte-identical` / `被容差吸收的差异数`。
    - 负向测试电池 **29/29 全绿**。第一条就是**把 CI 那次失败在本机原样重放**：合成一个
      15 处 `a_cal` 差 2 ulp、`zero_residual.got` 为 `'9.415e-14'`、`report.md` 两行同变的
      R8 候选，要求严格模式判红且指名那个字符串叶子，容差模式转绿并报
      `0/1 byte-identical`、`3 differences absorbed`、最大偏差 `4.500e-16`。
      其余覆盖：同一字段真动到 `1.5e-05` 仍判红、float→str 类型变更仍判红、
      四位小数门槛串 `0.838→0.700` 仍判红、数字不变只改词
      （`zero_residual`→`zero_residuel`）仍判红、行内多塞一个数字仍判红、
      `NUMSTR_FULL` 对 `nan`/`inf`/空串/带空格/版本号/`0x10`/`1_000` 一律不认。
      又有两条断言是**我自己写错的**（把最大偏差预期成 `a_cal` 的 `1.388e-17`，
      实际是字符串叶子的 `4.500e-16`；以及 `--allow-missing` 那次忘了它跑在严格模式下），
      两处都按实测改正——这与第 12 条那次一样，断言写错也算收获。
    - 修好后真实端到端复验：`runner --regimes R4 --out <临时目录>`（90.5s）→ 严格模式
      `sha=9dc0fa2a1e157873|9dc0fa2a1e157873`、420 个叶子全等、`report.md` 屏蔽 2 行后全等、
      `1/1 byte-identical`、`0 differences absorbed`、最大偏差 `0.000e+00`。
      **同机严格判据一点没被削弱**。四道原始门禁复跑全绿（`invariants` 12/12、
      `coverage` DATASET READY、`scorecard --check` IN SYNC、`git diff` 只剩本次改动），
      `code_hash` 仍是 `e2e2a7670771ce5a`——`matrixcheck.py` 不在闭包里，
      所以 `reports/` 无需重跑。

**与 v2.2.0 的跑分不可直接比大小**：数据集本身换了（16 维各向同性 → 384 维各向异性、
R3 重造、Span/Trace/GT/本体全面扩容），两个版本的 F1 / AUC / ARI 是**不同考卷上的分数**。
可比且必须记住的只有一条：全矩阵墙钟 102s → **十分钟量级**（准确值见「当前跑分」标题行）。
两个版本都是 8/8 regime 全门槛通过，
差别在于 v3.1.0 的门槛是在一个**能真正区分方法优劣**的数据集上通过的。

## 前轮修复（`bench-gen-v1` → `v2.2.0`，附实测证据）

1. **`missing_field_ratio` 结构性恒为 0**。`kernel/ingest.py` 原先先修复缺失字段再统计缺失数，
   所以包括 R5（45% 残缺注入）在内的 8 个 regime 上它 distinct=1、值恒 0.0，`kernel/score.py:130`
   的 `if mfr > 0.20` 是死分支。修法：在修复**之前**测量，并按 Span 类型给条件可得字段集
   `EXPECTED_FIELDS`（工具 Span 合法地不带 token，混进去量到的是 Span 类型配比而不是遥测丢失）。
   修复后 R1 p50=0.0000 / p99=0.1000，**R5 p50=0.0250 / p99=0.2000**，分支被真实触发。

2. **附录 A 的占比类公式在并行子 Span 下越界**。生成器以 p=0.22 发射重叠兄弟（并行工具调用，
   真实场景同样重叠），而原公式写的是「总耗时 − Σ子 Span 耗时」，隐含互不重叠假设。实测原公式：
   `wait_time_ratio` 最低 **−1.94**，`llm_time_ratio` 最高 **2.78**，tool 与 retrieval 分别求并集
   再相加到 **1.088**；根 Span 按构造覆盖全部壁钟，所以 `bottleneck_share` **恒等于 1.0**。
   修法：一律改用区间并集长度（`_union_len`），tool 与 retrieval 联合求并集，且排除根 Span。
   修复后全部落在 [0,1]（`wait_time_ratio` ∈ [5.4e-06, 0.3737]、`tool_time_ratio` ≤ 0.9685），
   全量 22,800 条越界计数 0，且与 `coverage.probe()` 独立实现逐条一致（最大绝对差 0）。
   方法论附录 A 的公式行已同步改正。

3. **两个让循环信号在数据里根本不存在的生成器缺陷**。
   (a) 工具参数不确定：循环注入器 `dict(base)` 复制骨架，但 `tool_params` 从推进的每轨迹随机流里抽，
   复制出的两份参数不同，「参数完全相同的重复」根本不存在。实测 R1：`loop` 标签 26 条、`loop_true` 23 条、
   一致 19 条，**7 条被标为 loop 的轨迹里数据中没有循环**。修法：`_tool_identity(...)` 改成
   (轨迹, 动作) 的纯函数。修复后 8 个 regime 标签与 `loop_true` **0 处不一致**，全数据集真循环 201 条。
   (b) 幻影重复 Span：并行分支发射器提前追加第 k+1 步并清零 `raw_w[k+1]` 后 `continue`，但 `for`
   循环跳不过下一次迭代，第 k+1 步又被追加一次，变成 4 ms 退化 Span；它把 `n_spans` 抬高约 10%，
   把相邻同动作塞进 22% 的轨迹，给 `retry_count` / `loop_count` 喂假信号。修法：把抽签提到
   `parallel = (k + 1 < len(steps)) and rng.random() < 0.22`（保留原短路语义，随机流不变）+ `skipped` 标志。
   Span 总数 132,648 → **117,502**。

4. **R4 在平稳数据上误报漂移**（两处成因叠加，按诊断顺序）。
   成因一：最慢意图 `i3`（92 条）在 cell 层与 parent 层都不足 30 条参考观测，回落到**全局**基线，
   而全局把 1.5s 总体与 120s 总体混在一起 → z 恒正（`z_mean_ref = 0.181`）；原始数据其实平稳
   （6 个分桶的每意图中位数 i0 1.53/1.46/1.64/1.51/1.70/1.59）。修法：矩梯改为
   `cell → parent → 弃权(z=None)`，**取消全局兜底**；新增 `MAX_ABSTAIN_SHARE = 0.50`，超过则返回
   `drift=False, reason="insufficient_support"`（明确不是「无漂移」）。`z_mean_ref` 0.181 → 0.041，
   但告警仍在（统计量 44.6 vs λ 10.6）。
   成因二：λ 是从一个中心**已恰好等于自身中位数**的符号序列里自举出来的，零假设中**不含中心估计误差**。
   每 cell 参考样本 n = 112/67/30，30 个对数正态样本的中位数偏差足以把 cell `i2|p2` 的尾部推到
   68.8% 高于合并中心。修法：`calibrate_lambda(ref_z, ...)` 改收原始 z，每次重复抽**两个**块自举
   重采样——A（参考长度）供 `centre = median(A)`，B（监测长度）对着它打分。实测 **λ 10.6 → 75.8**，
   统计量 44.6 → 不再检出；R7 真漂移不受影响（996.8 vs λ 65.0，lag +8）。

5. **弃权会把聚类质量买高，R1 已实测到**。`ari_pattern` 只在可归簇池上算，所以把难样本丢进
   novelty 缓冲区就能靠少打分来多得分。R1 缓冲区 433 条（10.8% 流量），关掉弃权后 `ari_pattern`
   0.8368、池上 0.9856，弃权净买 **+0.149**；而缓冲区并不模糊：`novelty_purity_pattern` = 0.9908，
   433 条里 380 条属同一个真实模式，异常率 0.0901 还高于池内 0.0732。成因是模式视图对 3 个真实
   模式返回 k=6，其中一个 383 条的碎片（纯度 0.9922）拿到 −0.44 的成员平均共识，于是
   `(a−b)/max(a,b)` 边际把一次**过度切分**读成了「叫不出它属于哪一类」。
   处置：`runner.py` 现在把 `ari_*_all`（弃权前）与 `novelty_purity_*`、`novelty_anomaly_rate`
   一并写进 `metrics.json` 与 `report.md`，让这笔交易无法隐藏；聚类模型顺序本身属 slice2，本轮未改。

对比修复前：F1 在 7 个出分 regime 中 5 升 2 降（R1 .799→.874、R3 .791→.838、R4 .735→.872、
R7 .830→.854、R8 .754→.801；R2 .815→.796、R5 .811→.786），AUC 8 个中 6 升，
`ari_pattern` 在 R3（.921→.994）与 R4（.928→.981）显著上升、R8（.979→.821）下降。

## slice2：O 维从「一个代理」到「四通道 + 污染准入」（附实测证据）

`slice1-v0.1.0` → `slice2-v0.2.0`，内核 `kernel-v0.1.0` → `kernel-v0.2.0`，`code_hash`
`e2e2a7670771ce5a` → `6f246e5b1df5bb02`。**数据集一个字节没动**：8 个 regime 的
`traces.jsonl` / `gt.jsonl` / `meta.json` sha256 全部不变，`spec_hash` 不变，
`reprocheck` 严格模式仍 8/8 逐字节一致。本轮只改 `kernel/score.py` 的 O 块与
`bench/runner.py` 的版本号，加三份文档；**8 份 `SAMPLE.md` 必须重生成**（原因见本节末）。

### 为什么第一刀切 O

`reports/<rid>/metrics.json` 的 `scoring.per_dim[d].spearman` 是「内核该维分数 ↔ 生成器该维
真值 `gt.dim_dev[d]`」的秩相关，是维度级的自证口径。8 个 regime 的均值：

| 维度 | 权重 | slice1 | slice2 | 说明 |
| --- | --- | --- | --- | --- |
| **O** | **0.40（最大）** | **+0.4397（倒数第二）** | **+0.9332（第一）** | 本轮唯一改动 |
| C | 0.15 | +0.9201 | +0.9201 | 逐叶子相同 |
| P | 0.20 | +0.7859 | +0.7859 | 逐叶子相同 |
| L | 0.15 | +0.7359 | +0.7359 | 逐叶子相同 |
| R | 0.10 | +0.3260 | +0.3260 | 逐叶子相同 |

**权重最大的维度秩保真度倒数第二**，所以 slice2 从它开刀。后四行「逐叶子相同」不是没提升，
而是**回归证据**：本轮只碰 O 块，P/L/C/R 的 `per_dim` 在 8 个 regime 上全部逐叶子未变。

O 维逐 regime：

| regime | R1 | R2 | R3 | R4 | R5 | R6 | R7 | R8 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| slice1 | 0.4850 | 0.4638 | 0.4071 | 0.5089 | 0.4769 | 0.3842 | 0.5033 | 0.2886 |
| slice2 | 0.9713 | 0.9454 | 0.9063 | 0.9347 | 0.9292 | 0.9555 | 0.9354 | 0.8876 |

最差 regime 从 +0.2886（R8）抬到 +0.8876，**8/8 全部大幅上升，无一例外**。

### slice1 的 O 为什么不行（两个结构缺陷，不是调参问题）

slice1 的公式是 `s_o = (0.70*tr_score + 0.30*(1-err_r)) * (1 - 0.40*trunc)`，
`traceable_number_ratio` 缺失时 `tr_score` 取常数 **0.90**。

1. **0.90 常数把「答案里没有数字」的轨迹全铉在 0.93**。这类轨迹占 bench_v1 的 13.4%
   （3046/22800），R8 高达 **32.7%**。一条干净轨迹与一条编造了十个数字的轨迹，
   只要答案本身不含数字，O **完全同分**——这个维度在最需要它的那部分流量上直接失明。
2. **O 根本没有完整性通道**。生成器 `unfinished` 类的真值是 0.55，slice1 给它打 **1.000**。

实测口径：这个合成量的单独 spearman 只有 **+0.4394**，比它自己的**每一个原料都差**——
`traceable_number_ratio` 单独 +0.7248、`fact_precision` +0.6575、`verifier_pass_rate` +0.5887、
`error_ratio`（取负）+0.4811。把原料混成合成量反而丢了秩保真度，说明问题在结构不在权重，
所以本轮不是去调 0.70/0.30，而是换掉整套通道。

### 准入规则：通道要能给 O 扣分，必须先证明它不读别人的缺陷

**一个通道只有在所有 `dim_dev["O"] == 1.0` 的缺陷类上都不动，才准给 O 扣分。**
污染度按这五个类（`illegal_step` / `latency_spike` / `loop` / `missing_step` / `token_bloat`）
的轨迹加权 `|mean(通道|类) − mean(通道|normal)|` 之和实测：

| 通道 | 可得性 | 单独 spearman | 污染 | 判决 |
| --- | --- | --- | --- | --- |
| `traceable_number_ratio` | 86.6% | +0.7248 | **0.0** | 准入，`W_O_NUM = 0.70` |
| `fact_precision` | 25.9% | +0.6575 | **0.0** | 准入，`W_O_PREC = 0.15` |
| `error_ratio`（取负） | 100% | +0.4811 | 3.2 | 准入，`W_O_EXEC = 0.30` |
| 结构完整性 `1 - unfinished` | 100% | — | **0.0** | 准入，`W_O_COMP = 0.25` |
| `verifier_pass_rate` | 100% | +0.5887 | 24.5 | **否决**：`illegal_step` 上掉到 0.813（P 的缺陷） |
| `citation_reachability` | 51.1% | +0.5192 | 27.3 | **否决**：`missing_step` / `token_bloat` 上 0.932 / 0.936（P / C） |
| `key_fact_recall` | 25.9% | +0.5818 | **65.6** | **否决**：`missing_step` 上掉到 0.659（P 的缺陷） |
| `unfaithful_fact_count` | 100% | +0.3091 | **0.0** | **否决**（理由是稀疏不是污染，见下） |

被污染的通道在读**别的维度**的缺陷。把它接进 O，等于同一个缺陷记到两个维度上，
而这恰好是 LMDI 零残差归因承诺**不做**的事：审计人问「哪个维度扣了多少分」，
会得到同一个缺陷被数两遍的答案。它们**仍然作为特征发射、仍然可被检测层使用**，
只是不在 O 投票。

`key_fact_recall` 是 slice1 时期写定的 slice2 首选，**按实测否决，不按口味否决**：
可得性只有 25.9%（需要 `golden_facts`）、污染是八个通道里最高的 65.6，
而且在结构完整性通道进来之后**秩冗余**——带它 +0.9561，不带它也是 +0.9561。
`1 - struct.unfinished` 在 100% 的流量上说的是同一件事。

判别器是真的、不是拟合出来的：生成器的 `unfinished` 弹出的是**尾部** Span，
所以最后一个动作不再是该格子的主导终结动作，`detect.py:259` 给 **1.0**；
`missing_step` 删的是**中间**的必需步骤，终结动作还在，给 **0.0**。
因此只取 `unfinished >= 1.0`：0.35 的软判例是「终结在了不寻常的步骤上」，那是 P 的事，
否则会让 O 为一个恰好排在最后的 `illegal_step` 扣分。

### 选型：为什么是 `GROUND_SAT = 2.0` / `W_O_COMP = 0.25`

对 (GROUND_SAT, 完整性权重) 做 6×6 网格。**关键教训：整张网格的 mean spearman 是个平台**，
36 格全距只有 **0.00027**（+0.95585…+0.95612）——也就是说这个网格选的**根本不是秩保真度，
而是类序**。原因：每个异常类都不到流量的 1.1%，把 truncation 排到 hallucinated 下面
在整 regime 的 spearman 上**测不出任何代价**，却会把分诊队列的顺序弄反。
所以判据改成「**类序零倒置**前提下取最大 mean spearman」，类序按真值
hallucinated 0.15 < truncation 0.35 < unfinished 0.55 < error 0.75 < normal 1.00。

- `GROUND_SAT = 1.0`（slice1 的线性形式）在**每一个**完整性权重上都有倒置——饱和是必需的。
- 零倒置的格子里，`2.0 @ 0.25` 的约束性余量最大：**+0.0793**（= error 0.819 − unfinished 0.740）。
- **`GROUND_SAT = 2.0` 不是自由参数，它被 `TR_FLOOR` 钉死**：`1 - 2.0*(1-0.5) = 0`，
  即渐变通道恰好在 `traceable_number_ratio = 0.5` 饱和，而那正是 `t0_result_broken`
  一票否决接管的点——**渐变与硬门槛既不空档也不重叠**。2.5 同样零倒置、余量并列 +0.0793，
  但它在 0.4 就饱和，会与否决带重叠，故否决；1.75 / 1.5 / 1.25 的余量只剩
  +0.0423 / +0.0312 / +0.0044。这条已写进 `adapt/playbook.md` §2.2 的**锁定**清单，
  四个通道权重则在 §2.1 的**可调**清单。
- **slice1 的截断乘子被去掉（`kt = 0`）**：任何 `kt > 0` 都会把 truncation（真值 0.35）
  压到 hallucinated（真值 0.15）**下面**——因为两者在 `GROUND_SAT = 2.0` 下的
  `g_num` 都被夹到 0，只剩乘子区分它们，方向正好反了。truncation 本来就已经是
  `t0_result_broken` 否决项，本来就已经把 `traceable_number_ratio` 压到 0.637。
- **记录一个被否决的更高分**：无视类序时最好的格子是 mean spearman **+0.9761**，
  但它带 1 处倒置。按上述理由**拒绝**——多出的 0.02 是用分诊顺序换来的。

选定格子在离线（22800 条、完整性通道用 oracle `gt.process_flags.unfinished`）的类均值：
hallucinated 0.550 < truncation 0.655 < unfinished 0.740 < error 0.819 < normal 0.999，
零倒置，最小相邻余量 +0.0793。上线代码把 oracle 换成 `detect.l4_contract` 的
`struct.unfinished` **代理**，代价很小：R4 实测 0.5089 → 0.9347（离线上界约 0.956）。

### 缺失通道的处理：丢弃并重归一，绝不填常数

四个通道按 `(0.70, 0.15, 0.30, 0.25)` 加权，**值为 `None` 的通道直接跳过、权重和重归一**。
这是 slice1 那个 0.90 常数的正面替代：常数会让「测不到」伪装成「测到了 0.90」，
重归一则让分数只由**真的测到的**通道决定。同时把不可得记进**置信度**而不是分数：
`g_num` 缺失 `u["O"] *= 0.90`，`fact_precision` 也缺再 `*= 0.85`，完整性缺失 `*= 0.80`。
`s_o` 因此永远不会退化成常数（只有分母为 0 时才回落到 1.0）。

### 一个被否决的干净通道：`unfaithful_fact_count`

它是**整个契约里最干净的通道**——可得性 100%、污染恰好 0.00，而且在 bench_v1 上是
truncation / hallucination 的**完美判别器**（truncation 只取 1、hallucinated 只取 2、其余全 0）。
但它**几乎是空的**：22800 条里只有 **102** 条非零（0.45%）。按 `1 - min(1, count/FAITH_SAT)`
（`FAITH_SAT = 2`）接进去，mean spearman 只动 **+0.00002**，而**约束性余量被削**：

| 权重 | 0（不接） | 0.05 | 0.10 | 0.15 | 0.20 |
| --- | --- | --- | --- | --- | --- |
| 最小相邻余量 | **+0.0793** | +0.0732 | +0.0680 | +0.0634 | +0.0595 |
| mean spearman | +0.95609 | +0.95611 | +0.95611 | +0.95611 | +0.95611 |

原因是它在 unfinished 与 error 上都读 1.0，把这两类一起往 normal 拖。
**一个在秩保真度上一无所获、却把整套类序赖以成立的余量削掉的通道，是净损失。**
用它替掉 `fact_precision` 也一样（两者都是 +0.95611）。它继续作为检测特征存在，不在 O 投票。

### 全局影响：该涨的全涨，唯一回落的一项已查清并接受

8 regime 均值：

| 指标 | slice1 | slice2 | 方向 |
| --- | --- | --- | --- |
| `per_dim.O.spearman` | +0.4397 | **+0.9332** | 本轮目标 |
| `spearman_vs_oracle` | +0.7750 | **+0.7845** | 8/8 上升 |
| `kendall_vs_oracle` | +0.5881 | **+0.5990** | 8/8 上升 |
| `grade_separation` | 39.298 | **39.616** | 8/8 上升 |
| `mean_S_normal` | 89.584 | **89.862** | 干净轨迹不再被常数误伤 |
| `mean_S_anomaly` | 50.286 | **50.246** | 异常轨迹略降，分离度因此扩大 |
| `score_auc` | 0.8758 | 0.8699 | **8/8 回落 −0.0058，已查清** |
| `zero_residual_max` | ~9.5e-14 | ~9.5e-14 | LMDI 恒等式未受影响 |

检测侧**完全未动**：F1 / P@50 / FPR / AUC / ARI 逐 regime 与 slice1 参考跑分完全一致
（R1 `pool=3945/4000 F1=0.881 P@50=1.000 FPR=0.000 AUC=0.966 ARI_i=1.000 ARI_p=0.998`，
R6 `F1=0.000 P@50=0.820 pool=591/600`），8/8 `gates=ALL-PASS`。
门槛表里唯一变动的叶子是 R6 / R8 的 `gates.zero_residual.got`
（9.237e-14 → 9.059e-14、9.370e-14 → 9.415e-14），那是**纯舍入误差的噪声底**，
正是上一轮 CI 修复里 `matrixcheck` 的 `NUMSTR` 通道要吸收的东西。

**`score_auc` 为什么回落，以及为什么这是对的。** slice1 的 0.90 常数在**偶然地**帮忙判别：
它给所有「答案不含数字」的轨迹打 0.93 而不是 1.00，而这个集合的异常富集度是 **1.42 倍**
（11.2% vs 7.9%），主要集中在 `missing_step`（3.4 倍基线）与 `unfinished`（1.9 倍）。
也就是说 **O 在借它叫不出名字的缺陷来刷 AUC**。去掉常数就把这份借来的判别力还了回去。
这与准入规则是同一件事的两面：凡是该涨的（vs_oracle、kendall、separation）8/8 全涨，
唯一回落的是那份**本就不该属于 O 的**贡献。**接受，不修。**

### 本轮踩到的耦合：`SAMPLE.md` 同时派生自数据集与流水线

`reprocheck --sample` 一度报 **0/8**，而 `traces.jsonl` / `gt.jsonl` / `meta.json`
全部逐字节一致。根因：`bench/show.py:49` 会读 `reports/<rid>/scores.jsonl`、
`:179` 把分数渲染进 `SAMPLE.md`，所以 `SAMPLE.md` 是**数据集 × 流水线输出**的共同派生物，
不是纯数据集产物。改了打分，8 份 `SAMPLE.md` 就必须重生成
（`python -m bench.show <rid> --sample`）。实测差异 100% 落在分数派生行上：
版本横幅、`S`、五维、`contrib`、零残差；R7 为 −50/+50 行。
**这不是要放宽门禁**——恰恰相反，是 `--sample` 这一跳抓住了「派生文档忘了跟着刷新」，
处置是重生成而不是加容差。

## slice3：R 维从「两个被污染的代理」到「三个精确零通道」（附实测证据）

`slice2-v0.2.0` → `slice3-v0.3.0`，内核 `kernel-v0.2.0` → `kernel-v0.3.0`，`code_hash`
`6f246e5b1df5bb02` → `f651db1a9f2380b0`。**数据集一个字节没动**：8 个 regime 的
`traces.jsonl` / `gt.jsonl` / `meta.json` sha256 全部不变，`spec_hash` 不变，
`reprocheck --sample` 严格模式仍 **8/8 逐字节一致、warnings=0**（含 8 份 `SAMPLE.md`），
`matrixcheck` 在 R4 上 **1/1 byte-identical（420 个 metrics 叶子，0 处被容差吸收）**。
本轮只改 `kernel/score.py` 的 R 块与 `bench/runner.py` 的版本号，加文档；
**8 份 `SAMPLE.md` 照例必须重生成**（耦合原因见 slice2 一节末）。

### 为什么第二刀切 R

slice2 之后 `scoring.per_dim[d].spearman` 的 8 regime 均值是
O +0.9332 / C +0.9201 / P +0.7859 / L +0.7359 / **R +0.3260**。R 是最差的一维，
而它自己的最佳单一原料 `error_ratio` 单独就有 **+0.7504**——
**合成项低于它自己的每一个零件**，与 slice1 的 O 是同一种病。三个结构性缺陷，按破坏力排序：

1. **`retry_count`（权重 0.30，锚点分，缺锚点时填常数 1.0）是主凶。** 重试是**正常流量**而不是
   鲁棒性缺陷：它在 **16% 的干净轨迹**上非零，干净组均值 **0.1714**，而 error / loop /
   err_recov 三类分别是 0.2045 / 1.1404 / 0.9908——在占 **98.2%** 流量、R 真值恒为 1.0 的
   那组内部制造了 **d = 1.596** 的离散度。这不是信号，是稀释。
2. **`guard_hits`（权重 0.30）被污染，而且重复计价。** 对 R 真值为 1.0 的缺陷类，
   轨迹加权污染 **0.28**，最坏 `illegal_step` 达 **64.0**（生成器给该类插了一个 `guard_block`
   Span）；同时它又是 `guard_violation` 硬门禁的判据，一次守护命中被扣了两次分。
3. **缺锚点填常数 1.0**——正是 slice2 从 O 里摘掉的那个缺陷，R 块还留着。

### R 的真值只有四级，98.2% 挤在 1.0

生成器只在三条分支上压低 `dim_dev["R"]`，所以全域只有 4 个取值：

| 级别 | 真值 | 条数 | 触发分支 |
|---|---|---|---|
| `error`（未恢复） | **0.35** | 132 | 注入错误且未被成功重试 |
| `loop` | **0.55** | 178 | 死循环 |
| `err_recov`（已恢复） | **0.60** | 109 | 注入错误后被成功重试；**`atype` 置空，故 `is_anomaly == False`** |
| 其余 | **1.00** | 22,381 | — |

98.2% 的流量真值相同 ⇒ R 的 spearman **几乎全部**来自「那 419 条低真值轨迹能不能被干净地分开」。
任何在 ok 组内部会变的通道，按构造就是噪声。所以 R 的选道标准不是效应量，是**精确性**。

### 通道准入：污染实测

准入规则与 O 同：一个通道只有在所有 `dim_dev["R"] == 1.0` 的缺陷类上都不动，才准给 R 扣分。
R 的真值-1.0 异常类比 O 多两个（`loop` 的真值是 0.55，出局；`truncation` /
`hallucinated_number` / `unfinished` 的真值是 1.0，入局），共 **7 类**。污染 = 轨迹加权
`|mean(ch|class) − mean(ch|normal)|` 在这 7 类上求和：

| 通道 | 可得性 | 污染 | error .35 | loop .55 | err_recov .60 | ok 1.00 | 结论 |
|---|---|---|---|---|---|---|---|
| `error_ratio` | 100% | **0.00** | 0.1993 | **0** | 0.1688 | **0** | **准入** |
| `unrecovered_errors`（条数） | 100% | **0.00** | 0.5038 | **0** | **0** | **0** | **准入** |
| `loop_rule` | 100% | **0.00** | **0** | 0.7500 | **0** | **0** | **准入** |
| `self_correction_count` | 100% | 0.00 | 0 | 0 | 0.9817 | 0 | 否决（秩冗余） |
| `loop_run_max` / `loop_count` | 100% | 0.00 | 0 | 3.13 / 3.01 | ~0 | **0** | 否决（与 `loop_rule` 冗余） |
| `path_convergence` | 99.3% | 0.00 | 0 | 0.1339（66% 非零） | 0 | 0 | 否决（冗余） |
| `tool_success_rate` | 96.3% | 0.00 | 0.7891 | 1.0 | 0.8679 | 1.0 | 否决（ok 组内非零） |
| `retry_count` | 100% | **0.34** | 0.2045 | 1.1404 | 0.9908 | **0.1714** | **否决**（稀释） |
| `guard_hits` | 100% | **0.28** | 0.0985 | 0 | 0.1560 | 0 | **否决**（污染 + 已是门禁） |
| `n_guard` / `n_spans` | 100% | 0.57 / 3.44 | — | — | — | — | 否决 |
| `warn_level_ratio` `plan_revision_count` `kind_ratio_guard` `guard_time_ratio` | 100% | ≈0 | 效应量 ≤ 0.27，单独 spearman ≈ 0 | | | | 否决（无信号） |

前三行不只是「污染低」，是在全部 **22,381 条 ok 轨迹上精确为 0**（非零计数 0）。
所以干净轨迹拿到 `s_r = 1.0` **精确值**，对组内并列噪声零贡献。

### 选权重：153 格单纯形

三个权重按 0.05 步长扫 153 格，判据 = **零类序逆序**约束下最大化最小相邻余量。
和 O 一样，**均值 spearman 在这里是个平台**（153 格全距 6e-5），所以网格真正在选的是
**排序**而不是秩保真。选定 **0.20 / 0.50 / 0.30**：

```
x_fail  = 1 - clamp01(error_ratio / ERR_SAT)                  # ERR_SAT = 0.30，与 O 共用
x_unrec = 1 - clamp01(len(unrecovered_errors) / UNREC_SAT)     # UNREC_SAT = 2.0，锁定
x_loop  = 1 - clamp01(loop_rule)
s_r     = (0.20*x_fail + 0.50*x_unrec + 0.30*x_loop) / 在场权重之和
```

**离线复算（全 22,800 条）：均值 spearman +0.3260 → +0.998693，最差 regime +0.2665 →
+0.989599，零逆序，最小相邻余量 +0.1121。** 类均值 error 0.6154 < loop 0.7750 <
err_recov 0.8879 < ok 1.0000，对真值 0.35 < 0.55 < 0.60 < 1.00。

### 消融：每一条通道都在承重

| 变体 | 均值 Sp | 最差 | 逆序 | 余量 |
|---|---|---|---|---|
| **选定（3 通道）** | **+0.998693** | **+0.989599** | **0** | **+0.1121** |
| 去掉 `unrecovered_errors` | +0.998613 | +0.989532 | **1** | −0.1847（error 0.7347 > loop 0.5500） |
| 去掉 `loop_rule` | +0.750435 | +0.672159 | **1** | −0.1682（loop 类得 1.0000） |
| 只用 `unrecovered_errors` | +0.571877 | +0.499891 | **2** | +0.0000 |
| 加 `self_correction_count` 作第 4 项罚分 | +0.997752 | +0.989540 | **1** | −0.1210（err_recov 0.6915 < loop 0.8125） |
| 加 `self_correction_count` 作恢复加分 | +0.998693 | +0.989599 | 0 | **+0.0793**（秩冗余，白削余量） |
| 加 `retry_count`（sat 3）权重 0.25 | **+0.350623** | +0.293140 | 0 | +0.0417 |
| 加 `guard_hits`（sat 2）权重 0.25 | +0.910665 | +0.815452 | 0 | +0.0652 |
| slice2 原式（retry + guard） | +0.327410 | +0.267551 | 1 | −0.2327 |

最后一行是**离线台架对自身的校验**：slice2 那个公式离线复算 +0.327410，
而它当时实现出来的均值是 +0.32598——差 4e-4，所以这套台架是可信的。
两个被否决的新增项不是「帮助不大」，是**量级上的灾难**。

### 恢复不需要单独的项

生成器给「错误被成功重试」写 R 真值 0.60、给「没被重试」写 0.35，而两个错误通道**恰好在这里分叉**：
`error_ratio` 两种情况都算这一步，`unrecovered_errors` 只算活下来的。所以**恢复被编码成
`x_fail` 与 `x_unrec` 之间的落差**，正是 `kernel/detect.py` 自己的语义（「已恢复的错误是瑕疵，
不是事故」）。再显式加 `self_correction_count`，两个方向都实测过、两个方向都否决（见上表）。

### 两处刻意的「不改」

- **`ERR_SAT` 与 O 共用，不另立 `ERR_SAT_R`。** 单独的 0.25 能把余量推到 +0.1231，
  但均值 spearman 到小数点后 5 位完全一样（+0.998691 vs +0.998693，共用值还略高），
  而零逆序的可行域**更窄**（153 格里 42 格 vs 47 格）。一个物理量——「出错步骤占比」——
  只配一个饱和点；两个旋钮会在适配手册里把 O 与 R **静默耦合**起来。
- **`error_ratio` 同时在 O 与 R 投票，不破坏零残差归因。** 因为**生成器自己就是双重计价**的：
  错误注入分支同时写 `dim["O"]`（0.95 / 0.75）和 `dim["R"]`（0.60 / 0.35）。
  准入规则禁止的是「目标维真值不动」的通道；`error_ratio` 对 O 和 R 的真值-1.0 类集
  污染都是 **0.00**，两边都合规。这一条会被审稿人／专利审查员追问，所以写在这里。

### 实现后的全矩阵实测（8/8 `gates=ALL-PASS`，全矩阵 809s）

| 指标 | slice2 | slice3 | 方向 |
|---|---|---|---|
| `per_dim.R.spearman` 均值 | +0.32598 | **+0.99869** | **8/8 升** |
| `per_dim.R.spearman` 最差 | +0.26647（R1） | **+0.98960（R5）** | — |
| `per_dim.R.pearson` 均值 | +0.46880 | **+0.96552** | 8/8 升 |
| `per_dim.O/P/L/C.spearman` | — | **逐叶子完全不变** | 0/8 变 |
| 检测 / 聚类 / 基线 / 漂移全部叶子 | — | **完全不变** | 0/8 变 |
| `score_auc` 均值 | 0.86998 | **0.87340** | **8/8 升** |
| `spearman_vs_oracle` 均值 | 0.78454 | **0.79839** | 8/8 升 |
| `kendall_vs_oracle` 均值 | 0.59900 | **0.61490** | 8/8 升 |
| `grade_separation` 均值 | 39.6155 | **39.8696** | 8/8 升 |
| `mean_S_normal` 均值 | 89.862 | **90.124** | 8/8 升 |
| `mean_S_anomaly` 均值 | 50.246 | 50.254 | 5/8 升（见下） |
| `zero_residual_max` | ≤9.5e-14 | ≤9.7e-14 | 噪声地板 |

逐 regime 的 R：R1 +0.2665→+1.0000、R2 +0.3253→+1.0000、R3 +0.3202→+1.0000、
R4 +0.3298→+1.0000、**R5 +0.3003→+0.9896**、R6 +0.3221→+1.0000、R7 +0.3683→+1.0000、
R8 +0.3754→+1.0000。**R 从最差的一维变成最好的一维**（超过 O 的 +0.9332）。

**`mean_S_anomaly` 几乎不动（+0.008）不是没生效，而是两股相反的位移抵消了**，按类拆开：

- `error` −0.897、`loop` −0.120：真该扣的扣得更狠。
- `err_recov` **+2.391**：这 109 条的 `is_anomaly` 是 **False**（生成器把 `atype` 置空），
  它们本来就在**非异常池**里。slice2 的 `retry_count` 污染把它们压到 61.07，
  即把 109 条正常轨迹推向了异常带；去掉污染后回到 63.46。
  **`score_auc` 8/8 上升的直接原因就在这里**——不是「异常检得更多」，
  而是「不再把已恢复错误的正常轨迹错判成低分」。
- 其余 7 个 R 真值为 1.0 的异常类各升 +0.03~+0.17：它们此前被 `guard_hits` / `retry_count`
  错误地扣了 R 分，现在 R 精确等于 1.0。这些类的扣分本来就该由它们**自己的**维度
  （O / P / L / C）承担，这正是零残差归因的承诺。
- `normal` +0.253：16% 的干净轨迹不再因为「重试过」被扣分。

等级带随之整体右移：全矩阵 `grade_abs` A 13321→**13685**、B 6343→6006、C 403→379、D 2733→2730。

### L 维：实测到顶，本刀不动（负面结果，附证据）

L 是 `s_l = 锚点分(latency_total)` 单通道，slice2 后均值 +0.7359。先归因，再做**上界实测**：

- **锚点截断造成并列。** 与真值并列@1.0 均值 **11.8%**（R3 高达 **21.6%**），并列@0.0 均值
  4.2%（R3 **14.7%**、R4 9.8%）。剔掉被截断的轨迹后 R3 0.67974→**0.80917**、
  R4 0.54344→**0.74214**、均值 0.68373→0.72691。
- **R7 的差距是基准真值的假象，不是内核 bug。** R7 是唯一带 `drift_segment` 的 regime，
  其**未漂移子集** +0.72221 对全体 +0.64111。根因：生成器在抽出 `z_l` **之后**才做
  `lat *= drift.magnitude`，而 `q_l = phi(z_l)` 用的是**未漂移**的 `z_l`——
  漂移轨迹确实变慢了，L 真值却没跟着变。
- **`latency_spike` 不是原因**：剔除它均值 0.68373→0.68016（几乎不动）。
- **L 真值 `1 − 0.5·φ(z_l)` 是意图条件的**（`lat = exp(log(med_i) + sig_i·z_l)`，
  逐意图取中位与尺度），所以它与**格子条件**锚点并不冲突。

**决定性的一步：oracle 上界实测。** 用「格子条件 + 每特征四锚点 + 同一把锁定阶梯」做
单通道 oracle（71 个格子、21,541 条格内轨迹，且**不**限制在 `METRICS` 内）：

| 通道 | 均值 Sp | 最差 Sp | 并列@1.0 |
|---|---|---|---|
| **`latency_total`（现用）** | **+0.737765** | +0.648989 | 0.1012 |
| `busy_union` | +0.735014 | +0.646069 | 0.1012 |
| `span_latency_p95` | +0.735202 | +0.657726 | 0.1012 |
| `critical_path` | +0.716678 | +0.643807 | 0.1012 |
| `ttft` | +0.373276 | +0.319539 | 0.1013 |
| `bottleneck_share` | +0.028983 | −0.010287 | 0.1012 |
| `inter_step_gap_cv` | −0.007400 | −0.038558 | 0.8312 |
| `wait_time_ratio` | −0.131018 | −0.201882 | 0.1012 |

同批格内轨迹上**已实现**的 `dims.L` 是 **+0.722300**。也就是说：oracle 单通道上界
（+0.7378）与已实现值（+0.7359 / +0.7223）**在测量精度内不可区分**，
且**没有任何一个替代时延特征能打赢 `latency_total`**。与 C 维（+0.9201，两个锚点通道取平均）
不同，L 没有值得加的第二通道；而要加就得动 **v1 冻结的 `METRICS`**，那会破坏冻结门槛的可比性。
残余差距的两条来源都已定性：(a) 截断并列，那是**锁定**的 P10/P50/P90/P99 阶梯的
**预期语义**；(b) R7 的漂移真值假象。**结论：L 已到结构上界，slice3 = 只改 R。**

## slice4：P 维从「一个加性公式」到「五通道 + 归因门」（附实测证据）

slice3 之后五维的秩保真排序是 R +0.9987 / O +0.9332 / C +0.9201 / **P +0.7859** / L +0.7359，
而 L 已实测到结构上界，所以第四刀只能切 P。切完的结果：`scoring.per_dim.P.spearman` 均值
**+0.78592 → +0.96112**，最差制度 **+0.68771 → +0.90375**，**8/8 制度全部上升**；
Pearson 均值 +0.93433 → **+0.94628**；P 的假扣分 **300 → 0**，干净轨迹拿到 `s_p = 1.000000`
的**精确**值（整个 ok 组只有这一个取值）。3382 个 metrics 叶子里只有 **99** 个变化，
全部落在 `/scoring` 内；`detection / clustering / baseline / drift / data_quality /
calibration` 一个都没动，`per_dim` 里 O / L / C / R **逐位不变**。

P 的病症与 R 不同，所以选道标准也不同。**类序本来就是对的**（零逆序：违规 0.5220 <
未完成 0.6529 < 循环 0.8156 < 漏步 0.9362 < 正常 0.9984，对真值 0.05 < 0.20 < 0.50 < 0.80 <
1.00），坏在**并列、假扣分与漏检**三件事上。

### P 真值的形状：五级、96.9% 挤在 1.0

| 档位 | 真值 | 池内条数 | 来源 |
|---|---|---|---|
| `illegal_step` | 0.05 | 120 | 执行序列里出现禁用动作 |
| `unfinished` | 0.20 | 173 | 确认未完成 |
| `loop` | 0.50 | 170 | 出现重复动作组 |
| `missing_step` | 0.80 | 111 | 声明的 3 个必做步骤删掉 1 个 |
| `missing_step` | 0.85 | 48 | 声明的 4 个删掉 1 个；真值 = `1 − 0.6/len(required)` |
| 其余全部 | 1.00 | **20,919** | normal + latency_spike + token_bloat + error + err_recov + truncation + hallucinated_number |

低 P 真值一共 **622** 条（2.9%）。和 R 一样，这个系数几乎 entirely 在问一句话：
**能不能把这 622 条分开，同时不碰那 20,919 条**。

### 诊断：三个结构缺陷

1. **`unfinished == 0.35` 软分支**（权重 0.30）。`detect.l4_contract` 只在**确认**未完成
   （有 span 被 abort / 报错，或必做步骤不足）时报 1.0，末步不是本格子的终止动作时只报 0.35。
   把这个「嫌疑」按 0.30 × 0.35 计分，会让 **343 条**轨迹（全量口径）精确停在
   `s_p = 1 − 0.30×0.35 = 0.895`，其中 **316 条 P 真值是 1.0**：295 normal、15 latency_spike、
   4 hallucinated_number、2 token_bloat —— 占原方案 **327 条假扣分的 96.6%**。
   而且它们**不是无害的并列**：0.895 排在 `missing_step` 实测的 0.9362 **之下**，
   等于把一条普通轨迹排到一条确认的工作流违规后面。
2. **一个打分侧补不上的覆盖率缺口**。`missing = [a for a in required if a not in set(seq)]`
   意味着「被删掉的必做动作恰好在序列别处也出现过」时完全不可见，所以 `missing_frac > 0`
   只在 **66.67%** 的 `missing_step` 上触发（池内 159 条中 106 条）。剩下 53 条（全量 76 条）
   就是原方案的全部漏检，**在 `score.py` 里怎么调权重都够不着**。
3. **常数填充**，slice1 在 O 维上犯过的同一个错：`struct.get("missing_frac", 0.0) or 0.0`
   把「没有契约层」翻译成了「什么都没缺」，即给缺失数据发满分。

### 通道准入：污染实测

准入规则同 O / R：一个通道只有在所有 `dim_dev["P"] == 1.0` 的缺陷类上都不动，才准给 P 扣分。
`nz@ok` 是那 20,919 条真值-1.0 轨迹上该通道非零的比例。

| 通道 | 污染 | nz@ok | 结论 |
|---|---|---|---|
| `struct.missing_frac` | 0.000 | 0.00% | 准入，**渐变** |
| `struct.illegal_actions` | 0.000 | 0.00% | 准入，二值 |
| `unfinished >= 1.0` | 0.000 | 0.05% | 准入，二值，**受门约束** |
| `feats.loop_count / LOOP_SAT` | 0.000 | 0.00% | 准入 |
| `feats.goal_drift_max` | 0.001 | 0.13% | **只有加了归因门才准入**（见下） |
| `struct.loop_rule` | 0.000 | 0.00% | 否决：与 `loop_count` 秩冗余 |
| `feats.loop_group_count` | 0.000 | 0.00% | 否决：**基准过拟合**，见下 |
| `feats.path_convergence` / `longest_repeated_subseq` | 0.000 | 0.00% / 0.03% | 否决：loop 冗余 |
| `unfinished` 原值（0/0.35/1） | 0.000 | 1.43% | 否决：即缺陷 1 |
| `struct.dev`（检测器复合偏离度） | **0.024** | 3.90% | 否决：折进了 `err_dev` / `truncated` / `traceable_viol`，即 R 与 O 的缺陷 |
| `plan_revision_count` / `goal_drift_slope` / `self_correction_count` | 0.000 | 6.05% / 0.13% / — | 否决：**零信号**（单独 spearman +0.0006 / +0.0184 / −0.0077） |
| `tool_*` / `effective_info_ratio` / `cost_per_step_of_progress` / `query_complexity` / `n_turns_in_session` | — | 99–100% | 否决：在真值恒为 1.0 的组内部会变，按定义就是噪声 |
| `max_width` / `depth` / `n_spans` / `branch_factor` / `n_unique_tools` / `kind_ratio_guard` / `warn_level_ratio` / `missing_field_ratio` / `reformulation_signal` / `tool_repeat_rate` / `error_level_ratio` | .001–.003 | 1.08%–100% | 否决，逐条数字在 `kernel/score.py` docstring |

### ★ 归因门（attribution gate）：本刀的核心贡献

`goal_drift_max` 是唯一一个覆盖面够宽的准入通道 —— 它在 `illegal_step` 上触发 55.8%、
`missing_step` 40.3%、`unfinished` 38.2%、`loop` 29.4%，而在 normal 上 **0.00%** ——
所以它也是打分侧唯一能够到缺陷 2 那 53 条的东西。但它**不精确**：它在 `error` 类上触发
20.8%（26 条），而 `error` 的 P 真值是 1.0，于是污染 0.001，**按准入规则应当否决**。
否决它，就等于放弃覆盖率缺口唯一的解法。

出路是：那 26 条恰好是**别的维度已经认领了同一份证据**的轨迹。实测 —— 低 P 真值轨迹里
`error_ratio > 0` 的有 **0 条**。所以把 `goal_drift_max` 门控在 `error_ratio == 0` 上，
**低 P 侧代价为零**，同时精确移除那 26 条：污染 0.001 → **0.000**，通道按锁定规则合格。
而且秩保真不是「勉强及格」，是**变好**：门控前 +0.9327，门控后 **+0.9520**，
假扣分 37 → 11。

同一招清掉最后 11 条假扣分，而且它们干净地二分：`unfinished >= 1.0` 触发在真值-1.0 轨迹上的
11 条里，6 条是带错的 normal（错误已由 `error_ratio` 在 O 与 R 计价），5 条是 truncation
（截断已由 `t0_result_broken` 否决计价）。把 `unfinished` 门控在
`error_ratio > 0 or truncated > 0` 上，11 条全清，低 P 侧代价实测仍是 **0 条**。
**两道门都是免费的。**

所以「归因门」是准入规则的推广形式：**一个通道只有在没有别的维度已经认领同一份证据的轨迹上
才准投票**，实现为「按跨维指示量**条件性地丢弃并重归一**」。它把准入判据从「实测污染恰好为 0」
升级为「结构上不重叠」。机制与门条件的取值纪律已写进 `adapt/playbook.md` §2.2 的锁定清单。

### 台账：两件事必须分开算

弃用软分支和加归因门是两件事，混在一起算就会把功劳记错。池内 622 条低 P / 20,919 条真值-1.0，
「漏检」= 低 P 轨迹被打成 1.0，「假扣分」= 真值-1.0 轨迹被打到 1.0 以下：

| 方案 | 漏检 | 假扣分 |
|---|---|---|
| 原加性公式（slice3 交付态） | 53 | 300 |
| 五通道，保留 0.35 软分支，无门 | 29 | 326 |
| 五通道，保留 0.35 软分支，加门 | 29 | 289 |
| 五通道，只用硬 `unfinished`，无门 | 49 | 37 |
| **五通道，硬 `unfinished` + 双门（交付）** | **49** | **0** |

竖着看最后两行：**归因门清掉全部 37 条假扣分，漏检一条不动**。横着看中间两行：
**付漏检代价的是弃用软分支（+20），换来的是少 252 条假扣分**。软分支一共碰到池内 368 条轨迹，
其中 289 条真值是 1.0；剩下 79 条真的低 P 里，59 条即使没有它也由别的通道抓住，只有 20 条抓不住
—— 它作为 P 信号的**边际精度只有 20/368 = 5.4%**，假扣分率却是 78.5%。

### 选权重：3876 格单纯形，以及为什么不能只按余量取 argmax

0.05 步长的五权单纯形共 3876 格，判据仍是「零类序逆序 → 最小相邻余量最大」。均值 spearman
在这里是一片比 R 更平的平台：**736 个零逆序格全部落在 +0.960992…+0.961134，跨度 1.4e-4**。
于是这一刀必须把选择规则说明白，因为两个事实让「取 argmax」不再自动正确：

- **余量与 Pearson 在平台区上互相打架**。余量最大格 (0.30/0.25/0.15/**0.05**/0.25) 的
  Pearson 均值只有 +0.8999，**低于原方案的 +0.9343**，因为它给了 `missing_frac`
  这个直接、精确、与真值同形的通道**五者中最低**的权重，而给了间接的二值漂移代理两倍于它的权重。
  同一片平台上 Pearson 的跨度是 **+0.686…+0.955**，所以这是真实权衡不是噪声。
- **量级在下游不是装饰**。`s_p` 经几何平均进 S，而 S 要对着**锁定**的绝对档位
  A90/B75/C60 读数；一维系统性偏松会挪动 `grade_abs`，不只是挪动一个相关系数。

交付的选择规则：在零逆序格里，先要求**每个权重 ≥ 0.10**（不许有刀刃通道）且**余量 ≥ 原方案的
+0.0622**，再取 Pearson 均值距最优 1e-3 以内的格子，最后按余量最大定夺。22 格合格，
Pearson 带里只剩两格：(0.35/0.25/0.15/0.15/0.10) 的 Pearson +0.94640 / 余量 +0.0643，
与 (0.30/0.20/0.15/0.25/0.10) 的 +0.94628 / 余量 **+0.0803**。两者 Pearson 差 1.2e-4（噪声级），
余量差 25%，于是余量说了算：**`W_P_ILL 0.30 / W_P_UNF 0.20 / W_P_LOOP 0.15 / W_P_MISS 0.25 /
W_P_DRIFT 0.10`**。这个排序同时也是语义上站得住的那个 —— 越权动作最贵，其次是声明工作流被跳过的
**比例**，再次是确认未完成，然后是打转，最后是间接的漂移代理。

离线（21,541 条绑定轨迹，判据脚本对 `reports/<rid>/metrics.json` 的 8/8 制度、
spearman 与 pearson 两个系数**逐位复现**）：

| 指标 | 原方案 | 交付 |
|---|---|---|
| spearman 均值 / 最差 | +0.785920 / +0.687707 | **+0.961115 / +0.903748** |
| pearson 均值 / 最差 | +0.934334 / +0.893057 | **+0.946277** / +0.891651 |
| 最小相邻类序余量 | +0.062165 | **+0.080300** |
| 类序逆序 | 0 | 0 |
| 假扣分 / 漏检 | 300 / 53 | **0** / 49 |
| 组均值 | 0.5220 / 0.6529 / 0.8156 / 0.9362 / 0.9984 | 0.6442 / 0.7480 / 0.8365 / 0.9197 / **1.0000** |

### 消融：五条通道每一条都在承重

**在交付权重上**逐条丢弃并把其余重归一，五条里有**三条会直接把类序搞逆**：

| 丢弃 | spearman 均值 / 最差 | 余量 | 逆序 | 漏检 |
|---|---|---|---|---|
| `illegal` | +0.907006 / +0.847437 | **−0.2813** | **1** | 102 |
| `unfinished` | +0.961037 / +0.903659 | **−0.0859** | **1** | 49 |
| `loop` | +0.863013 / +0.768794 | **−0.0599** | **1** | 169 |
| `missing_frac` | +0.906454 / +0.852623 | +0.0431 | 0 | **120** |
| `goal_drift_max` | +0.932208 / +0.858287 | +0.0443 | 0 | **80** |

丢掉 `illegal` 会把 `illegal_step` 抬到 0.9202、高于 `unfinished` 的 0.6390；丢掉 `unfinished`
会把 `unfinished` 抬到 0.8815、高于 `loop` 的 0.7956；丢掉 `loop` 会把 loop 类打到 0.9654、
高于其余全部。后两条不逆序但漏检暴涨，`goal_drift_max` 那条的 80 → 49 正是缺陷 2 的覆盖率数字。
**改成每条丢弃后重新搜权**（而不是固定在交付权重上），结论不变而且更强：`drop loop` 在 969 格里
**一个零逆序格都没有**，`drop illegal` 只剩 4 格，`drop missing_frac` 225 格。

### 否决的替代方案（都在交付权重上实测）

- **`missing_frac` 二值化**：spearman 均值几乎不变（+0.961032 vs +0.961115），但产生
  **两个类序逆序**（`unfinished` 0.5922 掉到 `illegal` 0.6442 之下、`missing` 0.7922 掉到
  `loop` 0.8365 之下），Pearson 均值掉到 +0.8999。渐变也是唯一站得住的业务语义 ——
  扣分应当正比于**声明工作流被跳过的比例**，而且它与生成器自己的真值同形（`1 − 0.6/len(required)`）。
- **保留 0.35 软分支**：+0.816144，假扣分 289。决定性。
- **`loop ← struct.loop_rule`**：+0.960480，余量 +0.0609 对 +0.0803，两项都更差。
- **`loop ← feats.loop_group_count`**：+0.961117 / Pearson +0.948250，**两项名义上都更好，仍然否决**。
  两条理由：它与生成器自己的 `orc_loop_true` 在 **21,541/21,541** 条上逐位相同，
  所以那点优势是**基准过拟合**而不是特征性质；而且它不在 v1 冻结的 `METRICS` 里，
  为这点在真实流量上不会存在的收益去扩契约不值得。`loop_count` 本来就在。
- **给漂移加饱和除子 `DRIFT_SAT`**：`goal_drift_max` 在 bench_v1 上是**事实二值**的
  （273 个非零值全部恰为 1.0），任何饱和除子都惰置。二值化门槛 `DRIFT_FLOOR = 0.50`
  同样在 bench_v1 上惰置，但**保留并进了可调白名单** —— 业务侧的漂移量若是连续余弦距离，
  裸 `> 0` 会让数值噪声也扣 P 分。

### 实现后的全矩阵实测（8/8 `gates=ALL-PASS`，全矩阵约 819s）

`scoring.per_dim.P`，逐制度：

| regime | spearman 原 → 新 | pearson 原 → 新 | `mean_normal` 原 → 新 |
|---|---|---|---|
| R1 | +0.72314 → **+0.98731** | +0.92429 → +0.96959 | 0.99846 → **1.00000** |
| R2 | +0.79349 → **+0.99996** | +0.94370 → +0.96811 | 0.99804 → **1.00000** |
| R3 | +0.79687 → **+0.93060** | +0.90466 → +0.89165 | 0.99840 → **1.00000** |
| R4 | +0.74222 → **+0.93731** | +0.93467 → +0.95260 | 0.99832 → **1.00000** |
| R5 | +0.76827 → **+0.90375** | +0.92603 → +0.90731 | 0.99870 → **1.00000** |
| R6 | +0.88935 → **+0.99994** | +0.98156 → +0.98675 | 0.99961 → **1.00000** |
| R7 | +0.68771 → **+0.93513** | +0.89306 → +0.91931 | 0.99823 → **1.00000** |
| R8 | +0.88631 → **+0.99493** | +0.96672 → +0.97489 | 0.99915 → **1.00000** |
| **均值** | **+0.78592 → +0.96112** | **+0.93433 → +0.94628** | 0.99861 → **1.00000** |

综合指标（8 制度均值）：`score_auc` 0.873404 → **0.875632**（**7/8 上升**，R8 −0.000264）；
`spearman_vs_oracle` 0.798390 → 0.798565（6/8）；`kendall_vs_oracle` 0.614901 → 0.615048（5/8）；
`mean_S_normal` **8/8 上升**（+0.0013…+0.0087）；`zero_residual_max` ≤ 9.7e-14，8/8 全绿。
扰动面很小：22,800 条里 `dims.P` 变了 **996** 条，`grade_abs` 只变了 **16** 条
（7 B→A、7 A→B、1 D→C、1 C→B），**A 档总数 13685 → 13685 不变**。

### 一处刻意的代价：`grade_separation` 7/8 微降

`mean_S_anomaly` **8/8 上升**（+0.0018…+0.1099），于是 `grade_separation` **7/8 下降**
（−0.034…−0.106，只有 R7 +0.006）。这与 slice3 是同一个现象、同一个解释方向：
去掉假扣分，抬起来的正是那些**在别的维度上确实是异常、但 P 真值是 1.0** 的轨迹
（`unfinished` +0.6029 / 206 条、`illegal_step` +0.3791 / 131 条、`loop` +0.1461 / 178 条，
`missing_step` 反向 −0.4313 / 154 条）。

量级压缩还有一个结构原因，值得单独记下来：**「丢弃并重归一」的加权平均形式有一个下界
`1 − max_i w_i`**，所以违规类最多只能被压到 0.70 左右，够不到生成器给的 0.05；原方案用的是
加性截断形式 `1 − min(1, Σ 罚分)`，罚分可以叠过 1 再被截断，因此能压到 0.5220 ——
**它那点更好的量级，正是靠一个会重复计分的形式换来的**。而加权平均是 O / R / P 三维共用的、
写进锁定清单的形式（「缺失通道一律丢弃并重归一，禁止填常数」就依赖它）。
所以这 0.2% 的 `grade_separation` 是买「假扣分 300 → 0 + 干净轨迹精确 1.0 + 三维同构」的价钱，
而更好的那个判别指标 `score_auc` 是 7/8 上升的。

### 实测后回退的一条「看起来显然该改」的东西（负面结果）

`if unfinished > 0` 会给 0.35 软分支也挂上 `t1_unfinished` **分类否决（乘 0.25）**，
而 `detect.l4_contract` 自己的 `hard` 判据用的是 `unfinished >= 1.0`。表面上这是同一份代码里
两个不一致的定义，而且后果很重：全量 343 条软分支轨迹**全部**落到 D 档、S 中位数 22.93
（全集中位数 91.79），其中 **313 条只挂着这一个门禁**。把它对齐成 `>= 1.0` 之后在 R4 上实测：
`t1_unfinished` 命中 37 → 10，15 条 normal 被抬起来、其中 **12 条正确离开 D 档**
（S 均值 21.53 → 86.12）—— 但 `score_auc` **0.85693 → 0.83700**、`grade_separation`
**39.188 → 35.969**、`mean_S_anomaly` 51.215 → 55.357，只换来 oracle 秩相关 +0.0096 / +0.0072。
`per_dim` 与所有检测叶子两种改法都逐位相同，所以这个损失是真的，不是测量噪声。**已回退。**

它为什么会输才是有用的部分：**那个否决在意外地补偿一个检测器缺口**。`l4_contract` 只有经
`aborted` 或 `short` 才能到 1.0，而 `short` 是拿 `required` 量的，`term` 却是 `baseline.build`
按「本格子的主流末步动作」**学出来**的。当学出来的终止动作本身不是 `required` 的成员
（`optional_steps` 里的 `verify` / `api_call` / `peer_review` 完全可能就是那个主流末步），
被弹掉终止步之后必做步骤仍然齐备，检测器只能报 0.35，下游没有任何东西能把它和「一次普通的
非常规收尾」区分开。R4 的 11 条 `unfinished` 里有 2 条正是这个状态，它们就是 4 条错误升档中的 2 条
（S 24.56 → 98.22，D → A；另 2 条是一个 token_bloat 和一个 latency_spike）。
所以正确修法在**检测侧**：把「声明的终止动作在整条序列里从未出现」也算作确认未完成。
它必须**先于或与**门禁改动同时落地 —— 单独拆掉否决，是拿 12 次正确救回换 4 次错误升档。

**这条缺口同时也就是 P 维剩下 49 条漏检的全部来源**：弃用软分支后新增的 20 条漏检，
**全部**是 `struct.unfinished == 0.35` 的 `unfinished` 类轨迹，而门在其中 **0 条**上触发
（两个方向都实测过：恢复软分支救回 20/20，拆掉门救回 0/20）。**一个缺陷，两个症状**，
所以它们该在同一刀里修，而不是两刀。那是一刀检测侧的活：它会动 F1、precision 与告警流。

## 已知边界（开工前必读）

- **`METRICS` 仍是 v1 冻结的那 **12** 个，一个都没加**。slice2 只把 `fact_precision` 接进了**打分**
  （O 维第二通道），**没有**接进 `kernel/baseline.py:METRICS`，所以门槛表的历史数字仍然可比。
  v2 其余 40 余项与 v3 的 34 项依旧「只发射」。接线状态分**三态**（进 `METRICS` / 进打分 / 只发射），
  逐特征结论与否决理由见 `contracts/schemas.md` §2。
- **`implicit_feedback` 永远不能进 `METRICS`**。它与标签按设计相关（弱监督），进基线会平凡地刷高 F1。
- **五维里只剩 L 没动过，而它已实测到结构上界（均值 +0.7359，最差 regime +0.6492）**。
  slice3 把 R 从 +0.3260 提到 +0.9987、slice4 把 P 从 +0.7859 提到 **+0.9611** 之后，
  五维排序是 R +0.9987 / **P +0.9611** / O +0.9332 / C +0.9201 / **L +0.7359** ——
  **下一刀没有候选了**。L 的 oracle 单通道上界（格子条件四锚点，不限 `METRICS`）实测只有 **+0.7378**，
  与已实现值不可区分，且 8 个替代时延特征无一能打赢 `latency_total`；残余差距来自
  (a) **锁定**阶梯的截断并列（均值 11.8%，R3 达 21.6%）与 (b) R7 的**基准真值假象**
  （生成器在抽 `z_l` 之后才乘漂移倍率，L 真值用的却是未漂移的 `z_l`）。
  证据表在上方 slice3 一节。**要继续提 L 只能改生成器真值或解锁 `METRICS`，两者都超出算法侧范围。**
  另一个未解决项：O 维四通道里 `fact_precision` 只有 25.9% 可得性，剩下 74.1% 的流量靠
  丢弃重归一过活；要提可得性只能等业务侧补 `golden_facts`，算法侧无解。
- **下一刀的候选不在打分侧，在检测侧**：`l4_contract` 的 `unfinished` 只有经 `aborted` / `short`
  两条路能到 1.0，而 `short` 是拿 `required` 量的、`term` 却是学出来的。当学出的终止动作不在
  `required` 里时，被弹掉终止步的轨迹只能报 0.35。这一个边界同时是 (a) P 维剩下 49 条漏检里
  那 20 条新增漏检的全部来源、(b) 313 条 normal 轨迹被 `t1_unfinished` 误伤到 D 档的原因、
  (c) slice4 实测后回退那次改动的输因。证据与两个方向的实测在上方 slice4 一节。
  修它会动 F1 / precision / 告警流，是独立的一刀。
- **本体 `slo_anchors` 里给 R 写档位，slice3 之后会静默失效**。`kernel/baseline.py:DIM_METRIC`
  仍把 R 映射到 `retry_count`，`_apply_slo` 也照样收紧进制品；但四档锚点在全内核**只剩一个消费者**
  （`kernel/score.py::_anch`），而它 slice3 之后只被 `latency_total` / `cost_total` /
  `tokens_total` 三处调用。O / P / R 三维都是**规则通道**不是锚点通道。**没有直接删掉这个映射**：
  删了会让业务侧的 R SLO 从「静默失效」变成「静默丢弃」，更糟；正确修法是让 `baseline.build`
  收到 R 档 SLO 时**显式报错**，那是一次契约变更，要单独升版走一遍。在 bench_v1 上这条分支
  **不可达**（两套本体的 `slo_anchors` 都是 `{}`），所以它没有污染任何已公布的数字——
  这是适配期陷阱，不是跑分回归。红线与处方已写进 `adapt/playbook.md` Step 3。
- **合成数据只验工程与分布 regime 通用性**。语义文本是本体模板不是自由散文；句向量虽已是
  384 维各向异性、带话题连续谱，但它由生成器**按 latent 意图直接发射，没有经过真实编码器**，
  所以本基准的 ARI 上界仍不可外推到真实业务。
- **R3 的意图视图过度切分，novelty 余量只有 4.4%**。R3 是唯一被造成意图连续谱的 regime，
  k-neutral 轮廓系数在其上近乎平坦（k=2..6 为 0.0464 / 0.0439 / 0.0460 / 0.0453 / 0.0482，
  9% 跨度），argmax 落到 k=6 而真值是 2，于是 `novelty_rate = 0.2867` 贴着 `[0.03, 0.30]`
  的上限（余量 4.4%），`coverage` 只有 0.7133——28.7% 的 R3 流量拿不到条件基线。
  两种修法都实测过并**否决**（本体上界无效、简约带会同时打穿 R3 下限与 R4 的 k=4），
  证据在 `kernel/cluster.py` 的 `silhouette` docstring 里。它是确定性的，不是跑一次抖一次；
  但**任何改动嵌入几何或 `R_RUNS` 的重标定都必须回看 R3**。
- **意图视图的模型顺序没有本体上界**。模式视图的阶数来自本体声明的工作流数
  （`K_MAX_PATTERN_HEADROOM`），意图视图只能靠全局 `K_MAX = 6`。两个本体各声明 4 个意图，
  `min(6, 4+2) = 6` 等于没约束；而一个 regime 只会用到声明意图的**子集**（R3 用 2 个），
  所以「声明数」约束不了「实际出现数」。要加同样的上界，本体得先声明**该业务实际启用的意图集**。
- **`reformulation_signal` 在 R3 上恒为 0.0**，是唯一一个"某个 regime 完全测不到"的已实现特征。
  附录 A.4 #51 把判定带锁在余弦 ∈ [0.55, 0.90]，而内核用的是**会话内去均值**后的余弦
  （原始余弦挤在窄锥里，8 个 regime 的**原始**带内命中率是 71.1%–100.0%，特征会退化成常数）。
  去均值后 7 个 regime 的带内命中率为 6.87%–28.95%，**R3 是 0/2344**：R3 独有
  `intent_ambiguity = 0.50`，它把每个向量都拖向**其他**意图的均值，去均值后的向量彼此靠拢，
  整个 R3 的去均值余弦上界只有 0.371，够不到 0.55。方向与直觉相反——歧义是**压缩**去均值余弦，
  不是把它顶过带。三条修法都实测否决：带是合同值不能动；把 R3 歧义降到 0.55 会让 novelty 掉到
  0.0063（低于 0.03 下限），而 R3 本来只有 4.4% 上限余量；生成器主动发射改写追问是唯一真修，
  代价是新 `GEN_VERSION` + 全量重生成 + 13 分钟重跑，只为修一个 7/8 regime 已覆盖的特征。
  `bench.coverage` 把它报成 **gap 而非 blocker**，不进退出码。逐 regime 实测表在
  `kernel/features.py` 的 `_band_membership` docstring 里。

- **`oracle_ceilings()` 的「上界」是监督规则，不是无监督可达上界**。它用真类均值、真先验与
  单一合并各向同性方差做插入式 Bayes，在 v3.0.0 的几何上曾以 4.7 倍**优于**无监督 k-means；
  当前 v3.1.0 几何上恰好 `ari_wht ≈ ari_iso`，所以「上界」的解读成立，但那是几何标定的结果，
  不是定理。`CEIL_RATIO = 0.90` 只会放松门槛，因此这个偏差方向是安全的。
- **全矩阵墙钟从 102s 涨到十分钟量级**（v3.1.0 三次独占跑分实测 782 / 743 / 747s：同一份代码同一份数据，
  两次之间最大差 5.2%，所以 `scorecard --check` 明确放过墙钟，准确值以「当前跑分」标题行
  为准，那一行由 `bench.scorecard` 生成）。384 维句向量让共识聚类的
  距离矩阵贵了约 8 倍，这是几何保真度的直接代价，不是回归。要压缩只能降 `EVAL_M`（当前 400）
  或 `R_RUNS`（当前 8），两者都会削弱共识/弃权的分辨率。

## 开发纪律

- 检测类评估一律 Affiliation / precision@k / F1，**禁用 `point-adjust`**（时序异常检测里最通用的
  这个口径会让"预测全序列皆异常"的退化解拿到接近 1.0 的 F1）
- **不使用 LLM-as-a-Judge**。判别式模型（等渗 / 逻辑回归校准）允许，但必须交叉拟合、出 ECE
- 合成数据只验工程与分布 regime 通用性；业务真值以人工标注为准，标签预算 150 / 300 / 500
- 每个工件（本体、格子、锚点、绑定、校准器、门控）带版本号入库；分数记录永久携带
  `model_version` 与 `anchor_version`，任意历史分数可复现可对账
- **ARI 类门槛必须被 oracle 信息上界封顶**（`CEIL_RATIO = 0.90`），否则会出现任何方法都达不到
  的门槛（R3 表值 0.55 > 全量 Bayes 最优 0.5508）
- **弃权必须被计价**：任何只在可归簇池上算的质量指标，都要同时报「弃权前」的口径与缓冲区纯度
- 参数分两类：**可调白名单**与**锁定项**，见 `adapt/playbook.md §2`。白名单以外的改动 = 换方法
- **跑分后必须重生成 README 的「当前跑分」区块**（`python -m bench.scorecard`）；`--check` 是
  文档守卫，三级对账任一不符即退出 1：README ↔ `reports`（墙钟除外，那是机器负载量）、
  `reports` ↔ 数据集的 `spec_hash`（跑分是否属于当前数据）、`reports` ↔ 活内核的 `code_hash`
  （跑分是否由当前代码产出）。改了 `kernel/` 而没重跑 runner，也会被判 STALE
- 每一次调参都要在代码注释里留下**测量证据**（改前的数字、为什么错、改后的数字），
   包括负结果（例如 Thorndike 最大合并间隔规则在本基准每个 regime 上都退化成 k=2）
- **派生文档一律生成、不手写**：README 的五个跑分区块由 `bench.scorecard` 写，
  `COVERAGE.md` 由 `bench.coverage --md` 写，`SAMPLE.md` 由 `bench.show --sample` 写。
  三者实测都是**逐字节幂等**的，所以 CI 里重跑一遍再 `git diff --exit-code` 就能守住——
  手改这些文件在下一次 push 就会被覆盖
- **新增校验模块必须自带负向测试，且负向测试要跑真东西**。第 11、12 条两个 bug 都不是读代码
  或跑拷贝比对发现的：一个只有真实的 `runner --out` 二次跑分能抓到，一个只有把数据真的转成
  CRLF 才能抓到。断言写错也算收获——第 12 条那次电池测试 21/23，两个 FAIL 一个是模块真 bug、
  一个是我的断言把「末行被截断」错当成「行数不同」，两边都要改
- **跨平台的浮点断言必须区分「同一台机器」与「同一个契约」**。同机重跑要求逐位相等（实测三次
  全矩阵 782/743/747s，除墙钟外 3334 个值全等）；跨 libc 只要求 1e-12 相对，
  并**把实测偏差打印出来**，因为 `exp/log/erf/erfc/pow` 不保证正确舍入
- **渲染成字符串的数字仍然是数字**。`metrics.json` 里 11 个 `gates.*.got` 是预渲染字符串
  （为了让数据与 `report.md` 不可能各说各话），任何按类型分派的比对器都必须认得它们，
  否则一个用 `%.3e` 渲染的噪声地板就能把整条跨平台断言判红。同理，按行比对渲染文档时
  必须要求「剥掉数字 token 后残余文本逐字节相同」，否则 `- F1 0.838` 与 `- F2 0.838`
  会被容差放过去
- **汇总里的计数不许说谎**。`checked if allok else 0` 这种写法会在 7/8 通过时打印 `0/8`，
  把人支去找一场并不存在的全面崩塌。通过数、逐字节相同数、被容差吸收的差异数分开报
- **跨平台断言要连因果链一起量下来**。第 13 条那句「58 个叶子全是 `a_cal`」不是靠读代码
  猜的：先由 `reprocheck` 的 `0.000e+00` 排除生成器，再由「只有 `erfc` 是流水线独有」
  缩小到 `kernel/baseline.py:543`，最后由「只有严格落在两个结点之间的 trace 才动、
  每个 regime 4~18 条」反证出 `kernel/calib.py:93` 的线性插值。三条独立证据对上了才算定位

# traj-engine：智能体轨迹聚类 / 异常识别 / 打分 通用算法工程

目标形态：**通用算法内核 + 可插拔业务本体 + 有门控的适配流程**。

先建标准基准数据集（`bench/`），再以基准驱动内核（`kernel/`）逐切片开发；任何业务接入只装配
工件与本体（`ontology/`），按 `adapt/playbook.md` 的门控流程放量。**不使用任何生成式判官**：
相同输入位级一致，分数携带模型版本号，扣分归因可逐条对账。

方法论出处：`insight-reports/风险与轨迹/智能体轨迹聚类异常识别与打分方法论设计.md`。

当前版本：数据集生成器 `bench-gen-v3.1.0`｜流水线 `slice1-v0.1.0`｜数据契约 v1.3.1。

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
  - `score.py` — 5 维 × 4 锚点 × 硬门禁 × LMDI 零残差 → S ∈ [0,100]
  - `calib.py` — 交叉拟合等渗校准，`a_raw → a_cal` 概率
  - `meta.py` — ARI / NMI / purity / PRF / AUC / PR-AUC / Spearman / Kendall / ECE；**`point_adjust` 调用即抛异常**
- `ontology/base.py` — 可插拔业务本体（ontA / ontB 两套，各声明 3 个工作流；文本模板、模型价目、
  工具目录、参数键、告警文案全部在本体里，内核不含任何硬编码业务动作）
- `adapt/playbook.md` — 适配六步流程、**可调白名单 vs 锁定参数**、α 的三口径、取值纪律、失败模式处方
- `data/bench_v1/` — 生成产物（`traces.jsonl` + `gt.jsonl` + `meta.json`，带 `spec_hash`，可复现可 diff）；
  每个 regime 另有 `SAMPLE.md`（人类可读样本手册，8 个样本，由 `bench.show --sample` 生成）；
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
## 当前跑分（流水线 `slice1-v0.1.0`，8/8 regime 全门槛通过，全矩阵约 750s）
<!-- scorecard:header:end -->

`ARI_pattern` 列的括号内是「oracle 同池上界 / **弃权前**（关掉 novelty、按最近簇给全部轨迹打分）」。
弃权前那一列是诚实性口径，见「前轮修复 5」。

<!-- scorecard:main:begin -->
| regime | 分布形态 | n | 可归簇 | novelty | ARI_intent（上界） | ARI_pattern（上界 / 弃权前） | novelty 纯度 | F1 | P@50 | FPR | AUC | ECE | 漂移 | 墙钟 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| R1 | bimodal main path | 4000 | 3945 | 0.0138 | 1.0000 (1.0000) | 0.9976 (0.9976 / 0.9856) | 0.8545 | 0.881 | 1.000 | 0.0003 | 0.966 | 0.0167 | 无漂移，-12.5 vs λ 12.3 | 112.8s |
| R2 | trimodal | 4000 | 3967 | 0.0083 | 1.0000 (1.0000) | 0.9912 (0.9960 / 0.9913) | 1.0000 | 0.867 | 1.000 | 0.0011 | 0.971 | 0.0127 | 无漂移，-31.1 vs λ 21.1 | 87.4s |
| R3 | heavy overlap + intent ambiguity | 3000 | 2140 | 0.2867 | 0.7512 (0.7521) | 0.9866 (0.9907 / 0.9893) | 0.9988 | 0.796 | 1.000 | 0.0020 | 0.916 | 0.0330 | 无漂移，-18.4 vs λ 18.8 | 113.3s |
| R4 | extremely sparse cells | 1200 | 1021 | 0.1492 | 1.0000 (1.0000) | 0.9879 (0.9938 / 0.9842) | 0.9888 | 0.787 | 0.980 | 0.0011 | 0.927 | 0.0200 | 无漂移，-14.3 vs λ 42.2 | 73.7s |
| R5 | heavily corrupted telemetry | 3000 | 2979 | 0.0070 | 1.0000 (1.0000) | 0.9804 (0.9892 / 0.9798) | 1.0000 | 0.756 | 1.000 | 0.0007 | 0.913 | 0.0332 | 无漂移，9.1 vs λ 43.6 | 92.6s |
| R6 | cold start | 600 | 591 | 0.0150 | 1.0000 (1.0000) | 0.9949 (0.9949 / 0.9887) | 1.0000 | 0.000 | 0.820 | 0.0000 | 0.917 | 0.0000 | 冷启动抑制 | 104.1s |
| R7 | mid-stream drift x1.6 | 4000 | 3968 | 0.0080 | 1.0000 (1.0000) | 0.9891 (0.9953 / 0.9868) | 1.0000 | 0.823 | 1.000 | 0.0005 | 0.922 | 0.0118 | 检出 idx 2001 / 真值 2000，lag +1（963.1 vs λ 17.6） | 92.7s |
| R8 | foreign ontology | 3000 | 2930 | 0.0233 | 1.0000 (1.0000) | 0.9723 (0.9978 / 0.9721) | 0.9857 | 0.838 | 1.000 | 0.0004 | 0.922 | 0.0333 | 无漂移，-7.2 vs λ 42.5 | 73.7s |
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
| R1 | 89.7 | 47.7 | 42.0 | 0.785 | 9.5e-14 |
| R2 | 89.4 | 50.0 | 39.4 | 0.776 | 9.7e-14 |
| R3 | 89.7 | 51.1 | 38.6 | 0.810 | 9.7e-14 |
| R4 | 89.9 | 51.1 | 38.8 | 0.781 | 9.5e-14 |
| R5 | 90.5 | 50.7 | 39.8 | 0.780 | 9.6e-14 |
| R6 | 90.3 | 48.1 | 42.2 | 0.785 | 9.2e-14 |
| R7 | 87.5 | 50.3 | 37.2 | 0.728 | 9.6e-14 |
| R8 | 89.7 | 53.4 | 36.3 | 0.755 | 9.4e-14 |
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

## 已知边界（开工前必读）

- **v2 / v3 特征已发射但未接线**。`kernel/baseline.py:METRICS` 仍是 v1 冻结的 **12** 个指标；
  `features.py` 里 v2 的 40 余项与 v3 的 34 项可取，但没进基线、没进打分。接线是需要单独
  测量的一轮工作（slice2 / slice3）。
- **`implicit_feedback` 永远不能进 `METRICS`**。它与标签按设计相关（弱监督），进基线会平凡地刷高 F1。
- **O 维（权重 0.40）目前只有 `traceable_number_ratio` 一个代理**。数据已带 `key_fact_recall` /
  `fact_precision` / `unfaithful_fact_count`，v3 又补了 `verifier_pass_rate` /
  `citation_reachability`，替换是 slice2 的第一件事。
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

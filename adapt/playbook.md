# 适配手册：把通用内核落到一个具体业务

> 配套阅读：`contracts/schemas.md`（数据契约与门槛表）、`README.md`（模块地图）、
> `insight-reports/风险与轨迹/智能体轨迹聚类异常识别与打分方法论设计.md`（方法论）。

## 0. 这本手册解决什么问题

内核（`kernel/`）是业务无关的：它只知道"轨迹 = 带属性的 Span 树"，不认识任何具体动作名。
业务通过两样东西进入内核：

1. **本体（ontology）** —— 声明式配置：这个业务有哪些动作、哪些动作被禁止、每个工作流必须
   经过哪些步骤、单价怎么算、答案要过哪些确定性校验器。
2. **制品（artifacts）** —— 从该业务历史轨迹拟合出来的锚点、模式绑定、校准曲线，**每件都带
   版本号**。

于是：**适配 = 换本体 + 重拟制品 + 只动白名单参数 + 过门槛。不改内核代码。**

这条性质是可执行验证的，不是口号：

- `bench.invariants::kernel.no_hardcoded_ontology_actions` 静态扫描内核，断言没有任何硬编码
  动作名；
- 基准矩阵里的 **R8（异本体）** 用 `ontB` 跑同一套内核、同一套代码路径，通过全部门槛。

## 1. 六步适配流程

### Step 1 探针（probe）—— 先判断数据能不能用

- **输入**：≥ 1 个完整业务日的真实轨迹（Langfuse 导出 → `contracts/schemas.md §1` 的
  Trace/Span 结构）。
- **动作**：`ingest.normalize` + `features.extract`，产出数据质量画像。
- **必看指标**：关键字段缺失率 `missing_field_ratio`；三类修复标记的发生率
  （`ts_repaired` / `usage_estimated` / `orphan_rebuilt`）；单轨迹 Span 数与深度分布；动作
  词表规模。
- **门槛（不满足就不要往下走，先修埋点）**：

| 指标 | 要求 | 不满足的后果 |
|---|---|---|
| 关键字段缺失率 | ≤ 5% | 时延/成本维度失真，L、C 两维不可信 |
| 时间戳可修复率 | ≥ 95% | 时序不可信，漂移检测与顺序类特征全部失效 |
| 动作词表规模 | ≥ 5 | 模式视图没有可聚的结构，双视图退化成单视图 |
| usage 可获取率 | ≥ 70% | 成本维度退化为估算，`conf` 被系统性下调 |

- **产出物**：`probe_report.md`（n、时间跨度、字段完整度、词表、修复率）。

### Step 2 regime 匹配 —— 用基准矩阵给门槛定初值

把探针数据的**分布形态**对到 `bench/regime.py` 的 8 个 regime 上。注意匹配的是形态不是业务：
峰数、时延跨度、样本量、残缺率、是否漂移、是否异本体。

| 业务特征 | 对应 regime | 门槛要点 |
|---|---|---|
| 2 类任务、时延差 ≥10x、日均 > 3000 | R1 双峰主路径 | ari_i .70 / f1 .70 / P@50 .80 / fpr .05 / ece .08 |
| 3–4 类任务 | R2 三峰 | 各项 −0.05 |
| 意图语义高度重叠（同类问题多种问法） | R3 重叠加 | + novelty ∈ [.03,.30]，**ARI 必须按上界封顶** |
| 日均 < 1500 或格子极碎 | R4 极稀疏 | + `fallback_min .50`（池化回退占比） |
| 埋点残缺 > 30% | R5 高残缺 | + `conf_downgrade 1.0`（残缺轨迹必须下调置信） |
| 首日上线 / 历史 < 1000 条 | R6 冷启动 | 只出分不告警，`max_alerts 0` |
| 有版本发布、模型切换、流量结构变化 | R7 漂移 | `drift_detected` 且 \|lag_frac\| ≤ .10（**双侧**） |
| 动作词表与本手册示例业务不同 | R8 异本体 | `no_hardcoded_actions` 断言 |

**关键纪律：ARI 类门槛必须被信息上界封顶。**

`bench/runner.py` 的 `oracle_ceilings()` 会算两个上界：意图视图用生成模型的**插入式 Bayes
MAP 规则**（真类均值、真先验、组内合并方差），模式视图用**序列 oracle**（每个不同动作骨架
取其多数真值标签）。门槛取 `min(表值, CEIL_RATIO × 上界)`，`CEIL_RATIO = 0.90`。封顶只能放松
门槛、不会收紧。

R3 是活教材：门槛表写 `ari_intent ≥ 0.55`，而该 regime **全量数据的 Bayes 最优只有 0.5298**
——任何方法都达不到，包括直接拿到真值标签的方法。没有上界封顶的门槛表，会把工程一步步逼向
过拟合。同一个 regime 的同池上界是 0.5988，实测 0.5817，**达成率 97.2%**；两者之差
（0.5298 → 0.5988）正好是 novelty 弃权换来 ARI 的价格，报告里两个数都给。

### Step 3 制品装配（artifact fit）—— 四件套，各自带版本号

**① 本体** `ontology/<biz>.py`

| 字段 | 作用 | 下游影响 |
|---|---|---|
| `actions` / `kind_map` / `root_action` | 动作词表与类型映射（llm/tool/retrieval/guard/agent） | 特征抽取、Span 分类统计 |
| `forbidden_actions` | 确定性违规清单 | L4 硬门禁 → tier2 → 审计流 |
| `required_steps` | 每个声明工作流的必经步骤 | **决定 `K_MAX_PATTERN`**（见 §4） |
| `optional_steps` | 允许缺席的步骤 | 缺失步骤判定不误伤 |
| `unit_price` | prompt/completion/tool_call 单价 | 成本维度 C |
| `validators` | 只允许 `regex` / `json` / `number_traceable` 三类**确定性**校验器 | 结果符合度维度 O |
| `slo_anchors` | 可选，业务方直接给四档锚点 | 留空则用数据分位数锚点 |

> **红线：`validators` 里不得出现任何生成式判官。** 评分必须相同输入位级一致、可复现、可作审计
> 证据。判别式模型（校准用的等渗/逻辑回归）不在此列。

版本：`ontology_version`。

**② 锚点** `baseline.build(records, ont, anchor_version)`
四档锚点 ideal/good/warn/bad 来自格子内分位数阶梯 **P10/P50/P90/P99**，并按
**L3（格子）→ L2（意图）→ L1（全局）** 的 credibility 池化，`B(n) = n/(n+KAPPA)`，
`KAPPA = 30`（即 30 条样本时格子自身权重恰好 50%）。版本：`anchor_version`。

**③ 模式绑定** `binding.bind_patterns(art, ont)`
数据驱动的模式簇 → 声明工作流的自动映射。报告必须给出 `n_bound / n_clusters`；
**未绑定的簇 = 本体没声明的工作流**，这是本体演进的信号，不是噪声。
（判定用到 `binding.UNIVERSAL_PREVALENCE = 0.95`：某动作在几乎所有轨迹里出现就不具区分度。）

**④ 校准** `calib`（交叉拟合等渗回归）
人工标签三档 **150 / 300 / 500**；`MIN_LABELS_CALIB = 60` 以下不出概率，只出分数。
`K_FOLDS = 3` 折外评估，ECE 用 out-of-fold 值，避免被同样本拟合美化。版本：`calib_version`。

### Step 4 门槛（gates）—— 全绿才准进影子

跑 `python -m bench.runner --regimes ...`（或生产等价物），核对 `contracts/schemas.md §8`
全表，另加三条业务门槛：

- `operator_stream_precision ≥ 0.80`：日预算 k 条的告警流精度。**这是唯一会主动打扰人的通道。**
- `no_drift`：平稳期不得报出变点（基准矩阵 6 个平稳 regime 全部纳入）。
- `zero_residual ≤ 1e-6`：扣分归因之和严格等于总扣分（LMDI 恒等式）。

不通过时的处置顺序：**先查制品**（本体是否漏声明工作流、锚点是否过期、绑定率是否偏低）
→ **再查数据**（埋点、字段完整度）→ **最后才动白名单参数**。反过来做一定会过拟合。

### Step 5 影子（shadow）—— 只记录不告警

≥ 2 个完整业务周，与现有人工评估并行运行。

| 度量 | 门槛 |
|---|---|
| 与人工判定的 Cohen kappa | ≥ 0.60 |
| 日均主动告警 | ≤ 5（Phase 1 可放宽到 ≤ 10） |
| 单条复核耗时（含 3 步下钻到 Span） | ≤ 3 min |
| novelty 率周间波动 | ≤ 5 个百分点 |
| ECE（out-of-fold） | ≤ 0.08 |

**回流**：人工复核结论写回标签池，作为下一轮校准拟合的输入 —— 这是"越用越准"的唯一合法来源，
不引入任何在线学习。

### Step 6 发布（release）—— 灰度 + 明确回滚线

灰度 10% → 50% → 100%，每档观察 ≥ 3 天。自动回滚触发（任一）：

- FPR 相对影子期上升 > 50%
- kappa 相对影子期下降 > 0.10
- novelty 率 > 0.25
- 平稳期报出变点（漂移误报）
- 零残差被破坏 —— 这是不变量，破坏即代码缺陷，直接回滚并定位

发布后常态运营：右锚定符号 CUSUM（阈值由参考窗循环块自举标定）持续监测漂移 → 触发后重拟锚点
并递增 `anchor_version`。每条分数记录永久携带 `model_version` 与 `anchor_version`，
保证任意历史分数可复现、可对账。

## 2. 可调白名单 vs 锁定参数

### 2.1 可调（换业务可以不同，但每一次改动都要写进取值与理由）

| 参数 | 位置 | 默认 | 语义 | 调整依据 |
|---|---|---|---|---|
| `CONSENSUS_THRESHOLD` | `kernel/cluster.py` | 0.35 | novelty 灵敏度：自身簇支持度须比最强竞争簇高 35% | **必须重扫平台**，见 §4 |
| `BH_ALPHA` | `kernel/detect.py` | 0.20 | 复核队列的目标 FDR | 按人工复核预算调，**不按告警疲劳调** |
| `TIER_BANDS` | `kernel/detect.py` | 0 / .40 / .75 / 1.0 | 分诊三档带宽 | 只能在保持不相交的前提下平移 |
| `LAYER_WEIGHTS` | `kernel/detect.py` | L1 .24 / L2 .20 / L3 .24 / L4 .22 / L5 .10 | 五层偏离的相对重要性 | 按业务对"结果符合度 vs 过程合规"的偏好 |
| `MISSING_HARD` `LOOP_HARD` `DEFAULT_MIN_RATIO` | `kernel/detect.py` | .50 / 2 / 1.0 | 硬违规判据 | 按合规要求 |
| `Z_TRIGGER` `Z_SAT` | `kernel/detect.py` | 3.5 / 10.0 | 偏离度的触发点与饱和点 | 一般不动 |
| `DEFAULT_DELTA` | `kernel/drift.py` | 0.10 | 漂移最小持续效应：55% vs 50% 流量越过参考中位数 | 按 SLO 容忍度 |
| `DRIFT_ALPHA` `DRIFT_MIN_SEG_FRAC` `DRIFT_MIN_SEG_ABS` | `kernel/drift.py` | .01 / .05 / 50 | 显著性水平与最短窗长 | 按流量规模 |
| `Z_CLIP` `Z_SUSPECT` | `kernel/drift.py` | 3.5 / 2.0 | 稳健 z 裁剪与嫌疑阈值 | 一般不动 |
| `MIN_CELL_REF` `MIN_PARENT_REF` | `kernel/drift.py` | 30 / 30 | 参考矩梯各级最小支撑 | 与 `KAPPA` 保持一致 |
| `COLD_START_MIN_TRACES` | `bench/regime.py` | 1000 | 冷启动判定（按**入库量**，不是可归簇量） | 按业务日流量 |
| `ALERT_BUDGET_PER_DAY` `OPS_STREAM_PRECISION_MIN` | `bench/regime.py` | 5 / 0.80 | 运营告警流预算与精度底线 | 按值班人力 |
| `R_RUNS` `EVAL_M` | `kernel/cluster.py` | 8 / 400 | 共识分辨率 | 算力换分辨率 |
| `K_MAX` `K_MAX_PATTERN_HEADROOM` `K_MAX_PATTERN_ABS` | `kernel/cluster.py` | 6 / 2 / 8 | 两视图模型阶数上界 | headroom 须由本体声明推导，见 §4 |
| `SIL_TOL` `SIL_ABS_TOL` `JITTER_SEQ` `JITTER_EMB_FRAC` | `kernel/cluster.py` | .15 / .02 / .02 / .03 | 切点选择容差与扰动尺度 | 一般不动 |
| `TAIL_GOF_TOL` `TAIL_MIN_N` `TAIL_SWITCH_K` | `kernel/baseline.py` | .50 / 40 / 5 | 尾部模型自检容差与经验/参数切换点 | 按样本量 |
| `KAPPA` `POOL_W` `SAMPLE_CAP` `SPAN_SAMPLE_CAP` `SPAN_MIN_N` | `kernel/baseline.py` | 30 / 400 / 400 / 150 / 8 | 池化 credibility 与采样上限 | 按格子稀疏度 |
| `W_O_NUM` `W_O_PREC` `W_O_EXEC` `W_O_COMP` | `kernel/score.py` | .70 / .15 / .30 / .25 | O 维四通道相对权重（数字可溯源 / 事实精度 / 执行成功 / 结构完整） | 按业务对「答案有据 vs 执行无错 vs 交付完整」的偏好；缺失通道一律**丢弃并重归一**，禁止填常数 |
| `W_R_FAIL` `W_R_UNREC` `W_R_LOOP` | `kernel/score.py` | .20 / .50 / .30 | R 维三通道相对权重（步骤失败率 / 未恢复错误 / 循环规则） | 按业务对「彻底不出错 vs 出错能自愈 vs 不打转」的偏好；三通道在干净流量上**精确为 0**，任何在 ok 组内会变的通道都不准进 R（见 §2.2） |
| `CEIL_RATIO` | `bench/runner.py` | 0.90 | 门槛相对信息上界的封顶比例 | 只能更严不能更松 |
| `MIN_LABELS_CALIB` `K_FOLDS` | `bench/runner.py` | 60 / 3 | 校准的最小标签数与折数 | 按标签预算 |

### 2.2 锁定（换业务也不许动；动了就不是同一套方法）

- 锚点阶梯 **P10 / P50 / P90 / P99**（四档语义：理想 / 良好 / 告警 / 劣化）
- 门禁乘子及其**乘法**合成方式（`score.GATES`）
- 绝对档位阶梯 `GRADE_ABS`（A ≥ 90 / B ≥ 75 / C ≥ 60 / D）
- **LMDI 分解**与零残差恒等式 `sum(contrib) == S - 100*G`
- 五维权重 **O .40 / P .20 / L .15 / C .15 / R .10**
- 维度**几何平均**聚合（单维塌陷必须重罚，算术平均会把它抹平）
- `EPS = 0.02`
- `GROUND_SAT = 2.0`（`kernel/score.py`）：它被 `TR_FLOOR` **钉死**，不是偏好。渐变通道的饱和点必须正好落在硬门槛的接管点上，即
  `1 - GROUND_SAT * (1 - TR_FLOOR) = 0`，故 `GROUND_SAT = 1 / (1 - TR_FLOOR)`。调大到 2.5 会在 0.4–0.5 与 `t0_result_broken` **重叠**，
  调小到 1.5 / 1.25 会**留空档**；实测类序约束性余量分别只剩 +0.0312 / +0.0044（2.0 是 +0.0793）。
- `UNREC_SAT = 2.0`（`kernel/score.py`）：它被**检测器自己的定义**钉死，不是偏好。
  `kernel/detect.py` 里就是 `err_dev = min(1.0, len(unrecovered) / 2.0)`；打分器另取一个饱和点
  等于对同一个物理量（活下来的错误条数）用两把尺子，会出现检测器报「未恢复错误」而打分器不扣分
  （或反过来）的对不上账，审计链当场断掉。
- `ERR_SAT = 0.30` **O 维与 R 维共用，不许拆成 `ERR_SAT_R`**。一个物理量（出错步骤占比）
  只配一个饱和点；拆开会在本手册里把 O 与 R 静默耦合。实测拆分收益为零：
  `ERR_SAT_R = 0.25` 的均值 spearman 与共用值到小数点后 5 位相同（+0.998691 vs +0.998693），
  而零类序逆序的可行域更窄（153 格里 42 格 vs 47 格）。
- **O 维的通道准入规则**：一个通道只有在所有 `dim_dev["O"] == 1.0` 的缺陷类上都不动，才准给 O 扣分。
  准入以**污染实测**为准，不以直觉为准；违反它会把同一个缺陷记到两个维度上，破坏 LMDI 零残差归因。
- **R 维的通道准入规则（比 O 更严）**：一个通道只有在所有 `dim_dev["R"] == 1.0` 的缺陷类上都不动，
  才准给 R 扣分。R 真值只有四级、**98.2% 的流量挤在 1.0**，所以选道标准是**在 ok 组上精确为 0**，
  不是效应量：`retry_count` 的效应量高达 d = 1.596，但那 1.596 是**在真值恒为 1.0 的组内部**的
  离散度，接进去把 R 的均值 spearman 从 +0.9987 打到 **+0.3506**；`guard_hits` 污染 0.28
  （`illegal_step` 上 64.0）且与 `guard_violation` 门禁重复计价，接进去打到 +0.9107。
  现用三通道 `error_ratio` / `len(unrecovered_errors)` / `loop_rule` 在全部 22,381 条 ok 轨迹上
  **非零计数为 0**，干净轨迹因此拿到 `s_r = 1.0` 的精确值。
- **`error_ratio` 同时在 O 与 R 投票是合规的，不是重复计价**。因为**生成器自己就双重计价**：
  错误注入分支同时写 `dim["O"]`（0.95 / 0.75）与 `dim["R"]`（0.60 / 0.35）。
  准入规则禁止的是「目标维真值不动」的通道，而 `error_ratio` 对 O 和 R 的真值-1.0 类集
  污染都是 **0.00**。换业务时若生成侧不再双重计价，这条豁免立刻失效，必须重测。
- **禁用 `point-adjust`** 评估口径（`meta.point_adjust_is_banned` 抛异常断言）
- **禁用任何生成式判官**（LLM-as-a-Judge）

## 3. α 有三个口径，不要混

| 错误率 | 控制对象 | 消费者 | 由谁保证 |
|---|---|---|---|
| **FDR** | 复核队列（tier0/1/2 全集） | 人工复核预算 | `BH_ALPHA = 0.20` |
| **FPR** | 正常流量被打扰的比例 | 业务方（"别冤枉好轨迹"） | 门槛 `fpr ≤ 0.05~0.10` |
| **Precision@k** | 运营告警流（top-k by `a_raw`） | 值班运维 | `ALERT_BUDGET_PER_DAY = 5` + `OPS_STREAM_PRECISION_MIN = 0.80` |

最常见的误操作是"告警太多 → 调小 α"。这会同时牺牲召回和复核队列覆盖率，而告警多的真正原因
通常是**没有区分三条通道**：确定性违规是**审计记录**（落库待查），不是**呼叫**。

R1 实测（72 小时窗口）：

- 审计流 153 条确定性违规 ≈ **51 条/日**，落库不呼叫；
- 告警流 **k = 15**（5 条/日 × 3 天），**Precision = 1.000**；
- 复核队列 192 条，BH-FDR α = 0.20，受人工复核预算约束。

## 4. 两个参数的取值纪律（换业务必须重推）

这两个参数不是"调出来的"，是"推出来的"。

**`K_MAX_PATTERN = min(K_MAX_PATTERN_ABS, len(ontology.required_steps) + K_MAX_PATTERN_HEADROOM)`**

理由：切点选择统计量在去掉 k 偏置之后（`SIL_NEAREST = False`，分离项用**质量加权的全簇外平均
距离**而非"最近邻簇"距离）对更细的划分是单调的，于是上界成了唯一的实际约束 —— 约束就必须来自
声明的业务知识，不能是一个全局常数。ontA / ontB 都声明 3 个工作流 → 上界 5。实测：把上界放到 8，
高残缺（R5）与异本体（R8）regime 会把 3 个工作流碎成 9–12 簇。

> 顺带记录一个**负结果**：Thorndike 最大合并间隔规则（取谱系图上垂直跨度最大的那一刀）在本基准
> 的**每一个** regime 上都退化成 k=2，因为最后一次合并（k=2→1）总是拥有最大的垂直跨度。R3 实测
> 该间隔 0.1823 出现在 k=2。这条规则不能用，代码里保留说明而非实现。

**`CONSENSUS_THRESHOLD` 必须落在 co-association 统计量的低密度带里**

`cons = (a - b) / max(a, b)`，其中 a 是与自身簇的平均共现频率，b 是与最强竞争簇的平均共现频率；
两者都是 `R_RUNS` 次袋装投票频率的均值，取值呈**格点分布**。实测（8 个 regime，0.01 步长扫描）：

- 阈值在 **[0.35, 0.37]** 内变化时，novelty 率最大变动 **0.0014**；
- 跨过 **0.375**（= 3/8，对应 a=1, b=5/8）后，R3 的 novelty 率从 **0.098 跳到 0.308**。

所以 0.35 放在平台下沿，远离上下两个格点（1/3 与 3/8）。**换业务后必须重扫这条曲线**再定阈值，
直接沿用 0.35 不成立。旧值 0.60 是上一版"平均共现频率"语义下的合理取值，换到 margin 语义后正好
压在 `a = 2b` 的格点上，把 30%–45% 的正常流量判成了 novelty。

阈值不参与划分（模型阶数取袋装各次 k 的中位数，切点高度由它反推），所以这是一个**隔离的**旋钮：
调它只会改变弃权量，不会改变簇的结构。这一性质由
`bench.invariants::cluster.consensus_threshold_semantics` 断言。

## 5. 常见失败模式与处方

| 症状 | 根因 | 处方 |
|---|---|---|
| novelty 率异常高（> 25%） | 阈值落在格点上；或本体 `required_steps` 与真实工作流不符 | 重扫 cons 分布找平台；核对声明工作流数与绑定率 |
| ARI 低于门槛但达成率已 > 90% | 意图在 embedding 上本就不可分（Bayes 错误率高） | 接受上界封顶；改埋点或直接采集意图字段，**而不是调聚类** |
| FPR 偏高 | 走了全局阈值而非簇内条件基线；或尾部模型 GOF 自检被拒后退回纯经验 | 检查格子数与 fallback 占比；看 `tail_pvalue` 的 switch 点 |
| 告警太多 | α 与预算口径混淆 | 调 `ALERT_BUDGET_PER_DAY`，**不要动 `BH_ALPHA`** |
| P@50 低但规则通道精度 ~0.99 | 分诊未分层，统计嫌疑压过确定性违规 | 检查 `TIER_BANDS` 是否相交 |
| 冷启动误判 | 用可归簇量而非入库量判定 | `cold_start = len(feats) < COLD_START_MIN_TRACES` |
| 平稳期报漂移 | 均值型 CUSUM 处理偏态 z；或窗口允许中段结束 | 符号 CUSUM + 右锚定窗 + 自举阈值（见 `kernel/drift.py` 文档串） |
| 格子内 MAD ≈ 0 导致 z 顶到裁剪值 | 参考窗内该格子样本过少 | 三级参考矩梯 cell → parent intent → global，各级最小支撑 30 |
| 尾部 p 值普遍偏大、统计通道几乎不告警 | 用超出量中位数估指数率，而高异常占比下上十分位已被污染 | 改用对数尺度主体拟合 + GOF 自检（`kernel/baseline.py::fit_tail`） |

## 6. 一次适配的交付物清单

- `ontology/<biz>.py` + `ontology_version`
- `probe_report.md`
- `regime_match.md`（选了哪个 regime、门槛表值、上界、封顶后的有效门槛）
- `reports/<biz>/{report.md, metrics.json, scores.jsonl}`
- `tunables.md`（白名单里每个改动的参数：旧值 → 新值 → 理由 → 证据）
- `shadow_report.md`（kappa、告警量、复核耗时、回流标签数）
- `release_checklist.md`（灰度档位、回滚线、值班对接人）
# Embedding 与执行视图修复计划

> 状态：E1 已完成（2026-11-26），E2–E6 待实施。
> 背景：当前工程尚未达到生产算法验收标准。Cloud/Lifecycle 轨迹没有经过平台 encoder，intent embedding 为空时算法会静默降级；执行视图也尚未严格实现方法论 §5.3 的默认路线。本计划用于指导后续修复和内网工具接管。

## 1. 问题结论

1. **意图视图缺失真实 embedding**
   - 基准数据使用预生成的 384 维合成 embedding。
   - Langfuse 生产轨迹仅读取 metadata 中已有 embedding，当前来源没有该字段，因此进入内核时为空。
   - 空 embedding 会导致 intent 聚类退化为结构/序列信息主导，但 Run 仍显示成功，缺少显式降级或失败门禁。

2. **执行视图与设计文档存在差距**
   - 当前实现使用 action 序列的 1/2-gram 加权 profile、cosine 距离和 UPGMA。
   - 该路线总体接近方法论 §5.3 路线 A，可以先保留，不需要推倒重写。
   - 差距：未使用稳定 `agent::operation::tool` span key、缺少 3-gram、未使用 sublinear TF-IDF 与 L2 归一化、未输出簇级 top n-gram 解释、未记录 structural vectorizer fingerprint。

3. **旧 R2 结构不可复用**
   - 既有生产 R2 结构建立在空 intent embedding 基础上。
   - 引入真实 encoder 后必须强制触发新 R2，旧结构只能作为对照数据，不允许继续给 R1 贴标签。

4. **其他生产化风险同步处理**
   - active ontology YAML 未被生产 Run 消费，当前存在动态空约束本体 fallback。
   - 预检查未覆盖 embedding、span key、action 命名质量和模型资产。
   - cost 维度依赖价格配置，当前存在 0 价格弱化。

## 2. 目标架构

### 2.1 意图编码器

- 引入平台侧可插拔 `IntentEncoder` 合同。
- 默认模型使用 `BAAI/bge-m3`，首版仅启用 dense embedding。
- 模型治理信息必须落盘：
  - provider、model name、exact revision；
  - 权重文件清单与 SHA-256 hash；
  - embedding 维度，`bge-m3` 为 1024；
  - max token 与截断策略；
  - 归一化策略与推理后端；
  - 模型缓存路径和加载状态。
- embedding 为空、维度不一致、数量不齐时直接失败，禁止静默降级。

备选模型：

| 模型 | 评估 |
|---|---|
| `BAAI/bge-m3` | 推荐。多语言能力强，1024 维，8192 token 上下文，适合中英文混合轨迹 |
| `paraphrase-multilingual-MiniLM-L12-v2` | 轻量备选，但表达能力和长文本能力弱 |
| `all-MiniLM-L6-v2` | 不推荐。英文导向明显，不适合本项目 |

### 2.2 执行视图

按方法论 §5.3 路线 A 补齐默认实现：

1. 每个 span 构造 `span_key = f"{agent}::{operation}::{tool}"`。
2. span key 按时间排序生成序列。
3. 生成 1-gram、2-gram、3-gram。
4. 使用 sublinear TF-IDF：`tf' = 1 + log(tf)`。
5. L2 归一化，使用 cosine 距离。
6. 平均连接层次聚类。
7. 每个执行簇输出 top n-gram，例如 `plan→sql_query→summarize`。
8. 记录 structural vectorizer fingerprint。

当前实现中的 saliency 加权可作为可选增强保留，但必须通过 A/B 对比证明收益，不能默认宣称等价于设计文档。

### 2.3 结构指纹与版本治理

R2 冻结结构必须记录两类独立 fingerprint：

- intent encoder fingerprint：模型名、revision、hash、维度、输入构造和归一化策略；
- structural vectorizer fingerprint：span key 构造、n-gram range、TF-IDF 参数、距离和聚类配置。

fingerprint 变化时：

- R1 不得复用旧结构；
- 必须触发新 R2；
- 新旧 cell 只能生成 lineage 关系，不允许直接合并历史基线。

## 3. 实施阶段

### 阶段 E1：Encoder 合同与失败门禁

> 已完成（2026-11-26）：新增 `platform/app/encoder.py`；`run_production` 前置
> `validate_trace_embeddings` 门禁与 R1 维度/旧结构兼容校验；`cohort_runs.model_assets_json`
> （schema v11）持久化 provenance；`platform/tests/test_encoder.py` 17 个用例与平台全套
> 103 个测试通过。kernel 未改动。

交付：

- `IntentEncoder` 接口与配置模型。
- 空值、维度、数量、hash 校验。
- Run provenance 记录模型资产信息。
- 空 embedding 不再允许静默通过。

验收：

- fake encoder 单元测试覆盖正常、空值、维度错误、数量错误。
- 生产链路缺少模型资产时显式失败并给出修复指引。

### 阶段 E2：`bge-m3` 平台集成

交付：

- 离线模型加载器。
- 模型资产注册表与 hash 校验。
- embedding 缓存策略与缓存 fingerprint。
- 推理批处理与异常处理。
- 部署文档记录模型版本、权重、尺寸和资源需求。

验收：

- 断网环境下能从本地权重完成加载与推理。
- hash 不匹配时拒绝加载。
- 相同输入与配置得到可复现 embedding。

### 阶段 E3 A/B 裁决（2026-11-26，先于 kernel 改动）

`platform/tfidfexp.py` 全因子 A/B（8 regime × token 配方 {action, kind::action,
kind::action::tool} × saliency {off, on} + 现方案基线，结果 `platform/tfidfexp-results.json`）：

- **saliency 收益被决定性证明**：纯 TF-IDF（无 saliency）ari_p 全部 ≤0.88（多数 ≤0.70）；
  `action + TF-IDF + saliency` 在 R1/R2/R3/R6 与现方案持平（≥0.986），R4/R5/R7 略低
  （0.954–0.980），R8 回归 0.861 vs 0.972（门禁 0.55，余量充足）；满足 §2.2 "A/B 证明收益
  才保留 saliency" 的要求 → **保留 saliency 作为默认开启的工程增强**。
- **富 token 配方在 bench 上不可行**：`kind::action::tool` 全部 ≤0.47（`min_df=2` 亦无法
  修复），根因是 bench 生成器对同一 action 独立采样 tool_name（`tool_catalog` 一对多），
  完整 span_key n-gram 在轨迹间几乎不共享，cosine 距离饱和至切分网格上限 0.85 之上触发
  fallback 碎簇。**决定**：kernel 默认 token 配方保持 `action:v1`；`span_key:v1` 与
  `span_key:v1-no-tool` 实现为指纹化可选配方，待 E4 预检查在真实 Langfuse 数据上验证
  tool/agent 字段质量后再启用。
- **耗时**：pattern 距离现方案 1.2–2.6s vs TF-IDF 2.4–9.7s/regime，同量级，O(N·L) 成立。
- **解释输出**：top n-gram 解释在 tfidf 臂验证可行，随 kernel 实现写入 `cluster_info`。

### 阶段 E3 实施与全矩阵重跑记录（2026-11-26）

- **kernel 实施**（`kernel/cluster.py`，stdlib-only）：`span_key`（显式降级、缺失字段不捏造）、
  token 配方注册表（默认 `action:v1`；`span_key:v1` / `span_key:v1-no-tool` 为指纹化可选配方）、
  1/2/3-gram sublinear TF-IDF（`tf'=1+ln tf`，`idf=ln((1+N)/(1+df))+1`）、L2 归一化、cosine 距离、
  平均连接；saliency 乘子默认开启（`SIG_WEIGHT=3.0`，A/B 已证）。`cluster_info` 新增
  `pattern_top_ngrams`（簇级 top-5 解释）、`pattern_token_recipe`、`structural_fingerprint`
  （构造配置 SHA-256[:16]，不含数据导出的 idf）。
- **冻结结构与 R1 门**：`_tfidf_ctx` 纳入 `FROZEN_STATE_KEYS` 持久化；R1 复用前
  `_assert_frozen_structural_compatible` 比对 frozen 指纹与当前代码指纹，缺失或不符即抛
  `EncoderContractError`（旧结构可加载、门禁拒绝，不静默复用）。`run_production` 新增
  `pattern_recipe` 参数。Langfuse 适配层把 metadata 中的 `agent` / `operation` 映射为可选
  span 字段（缺失保持缺失）。
- **code_hash 变更与基线重发布**：`2064664e6aa5fb46` → `d229ab802e5a01bf`。全矩阵重跑
  **8/8 ALL-PASS**：ari_p = R1 0.998 / R2 0.994 / R3 0.987 / R4 0.978 / R5 0.955 / R6 0.995 /
  R7 0.954 / R8 0.862（全部高于门禁地板 0.50–0.60）。`matrixcheck` 逐叶子枚举差异
  （表头 code_hash、模式簇数、calibration、scores sha，均为内核变更的预期后果）后，
  `reports/` 重发布、`bench.scorecard` 重写 README 五区块，`--check` 报 **IN SYNC** 且
  8/8 溯源 PASS（report == live）。活引用同步更新：`r2_lineage_validation.py`
  `EXPECTED_CODE_HASH`、`DEPLOYMENT.md` §4.6 发布校验命令、前端 `App.tsx` 内核 hash 显示；
  带日期的历史对账记录（README 对账日志、`ROADMAP.md`、`freezeexp.py`、`DESIGN.md` §7.7）
  按惯例保持原值不改写。
- **观察到的矩阵级权衡**（备案，非回归）：TF-IDF cosine 的弃权尾部与编辑距离不同，
  R1 novelty 率 0.0138 → 0.0902（缓冲区更干净：多数真实类占比 0.8545 → 0.9723，缓冲区异常率
  0.5636 → 0.1080），R1 全量 recall 0.709 → 0.692、F1 0.828 → 0.816，均在门禁内；R8 ari_p
  0.861 vs 旧 0.972 的有界回归与 A/B 记录一致（`min_df=2` 修复假设已检验并拒绝）。

### 阶段 E3：执行视图补齐

交付：

- `agent::operation::tool` span key 构造。
- 1/2/3-gram sublinear TF-IDF。
- L2 归一化与 cosine 距离。
- 平均连接聚类。
- 簇级 top n-gram 解释。
- structural vectorizer fingerprint。

验收：

- 结构解释能直接回答“这个执行簇代表什么流程”。
- fingerprint 变化触发结构不兼容。
- 与当前 1/2-gram 实现做 A/B 对比，记录 ARI、novelty、告警质量和耗时。

### 阶段 E4：生产链路修复

交付：

- 生产 Run 加载 active ontology YAML。
- 禁止无提示使用动态空约束本体；确需 fallback 时显式标记 degraded。
- 预检查增加：
  - intent 文本覆盖率；
  - embedding 模型可用性；
  - embedding 维度与完整性；
  - span key 质量；
  - action 命名稳定性；
  - usage 与 cost 覆盖率；
  - ontology 价格有效性。
- 旧空 embedding R2 结构标记为不可复用。

验收：

- 一个真实 Cloud Run 完成模型、本体、embedding、结构指纹全链路检查。
- 不满足质量门禁的 Run 不产生“看似成功”的结果。

### 阶段 E5：真实数据验证与对比

交付：

- 旧结构与新结构对比报告。
- 真实 Cloud 数据诊断：文本覆盖率、embedding 参与率、聚类可分性、novelty 与弃权率、告警可解释性、耗时与内存。
- 人工抽样复核新告警。

验收：

- 新结构能明显改善意图簇解释质量，或给出量化失败原因。
- 告警根因与 trace 证据一致。
- 不再用合成标签作为唯一质量证明。

### 阶段 E6：内网部署治理

交付：

- 离线模型包与 hash 校验说明。
- Python、依赖、数据库、模型、前端构建版本清单。
- 资源评估：内存、磁盘、首次加载时间、批推理吞吐。
- 回滚方案。
- 更新 `DEPLOYMENT.md`、`INTRANET_HANDOFF.md`、`USAGE_GUIDE.md`。

验收：

- 内网环境按文档完成一次冷启动和端到端 Run。
- 模型权重缺失或 hash 错误时启动失败且错误信息可操作。

## 4. 实施顺序

1. E1：Encoder 合同与失败门禁。
2. E3：执行视图补齐与 structural fingerprint。
3. E2：`bge-m3` 离线集成。
4. E4：active ontology 与预检查修复。
5. E5：新 R2 与真实数据对比验证。
6. E6：内网部署文档与回滚治理。

E1 必须最先做，因为它阻断“空 embedding 仍成功”的问题。E3 先于 E2，是为了让结构视图接口和 fingerprint 合同稳定，避免真实模型接入后二次迁移。

## 5. 非目标

- 不引入生成式 judge。
- 不在本计划中实现执行视图路线 B（编辑距离、DTW）或路线 C（图嵌入）。
- 不修改 R1/R2 生命周期语义和幂等规则。
- 不引入外部在线模型服务，内网部署必须可离线运行。
- 不把当前旧结构结果作为新模型质量基准，仅作为对照。

## 6. 关键风险

| 风险 | 处理 |
|---|---|
| `bge-m3` 内网资源不足 | 先做批推理压测；必要时提供轻量多语言模型作为降级选项，但降级必须改变 fingerprint |
| span key 命名不稳定 | 预检查给出覆盖率与重复度，不达标时禁止 R2 |
| active ontology 缺失价格或约束 | Run 显式 degraded 或失败，并输出具体缺失项 |
| 旧结构误复用 | fingerprint 不匹配直接拒绝 R1 |
| embedding 缓存污染 | 缓存 key 绑定模型 hash、输入构造和预处理版本 |

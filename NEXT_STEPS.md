# traj-engine 项目理解与下一步工作清单

> 依据：`platform/EMBEDDING_REMEDIATION_PLAN.md`（2026-11-26，待实施）、方法论设计文档
> 《智能体轨迹聚类异常识别与打分方法论设计.md》、`README.md`、`ROADMAP.md`、`INTRANET_HANDOFF.md`
> 及全仓代码现状调查。Git 基线：`main @ 0ddb7ea`，工作区干净。
> 本文件为工作梳理稿，正式决策以 `platform/EMBEDDING_REMEDIATION_PLAN.md` 为准。

## 一、项目目标

**通用算法内核 + 可插拔业务本体 + 有门控的适配流程**，对智能体轨迹做三件事：

1. **聚类**：意图视图（embedding）× 执行视图（span 序列）双视图共识聚类 → 二维分析格子 cell；
2. **异常识别**：簇内条件基线 + L1–L5 五层检测 + 漂移检测 + 告警预算抑制；
3. **打分**：O/P/L/C/R 五维 × 四锚点 × 硬门禁 × LMDI 零残差归因 → S ∈ [0,100]。

硬性纪律：确定性可复现（位级一致）、**禁用生成式判官**、缺失字段置空而非伪造、
一项目一本体、分数携带版本号（model/cluster/anchor/weight）。

## 二、当前进展

### 2.1 已完成（M0–M7 主线）

| 阶段 | 状态 |
|---|---|
| M0 契约冻结 | 完成（OpenAPI / schema.sql v10 / 23 张表 / TraceSource / 前端路由） |
| M1 基准闭环 | 完成（8 regime 全链路可复现，R1 冻结结构贴标签） |
| M2 真实 Langfuse | 完成（Cloud v4 联通；1000 条千条级 Run、5 cell、40 告警通过） |
| M3 运营闭环 | 完成（Scores 写回、复核队列、告警预算 top-K、校准触发） |
| M4 生命周期 | 完成（R1/R2/R3、lineage、调度器、novelty 护栏、本体版本） |
| M5 硬化 | 完成（R2 抽样训练、流式化：10 万条 R2 4561s/1.93GB、配额） |
| M6 生产交付 | 完成（发布包 + 离线验收 + 单进程前端托管） |
| M7 真实试点 | **进行中**：复核包已导出，等待业务专家回填 20 条标签 |

### 2.2 关键缺口（修复计划的动因）

| # | 缺口 | 现状证据 |
|---|---|---|
| 1 | **意图视图无真实 embedding** | Langfuse 源仅透传 `metadata["embedding"]`（`langfuse_source.py:244`），生产为空；内核 `dim=0` 时静默跑完全程且 Run 显示成功（`kernel/cluster.py:735-812`），无降级标记无门禁 |
| 2 | **执行视图偏离方法论 §5.3 路线 A** | 现状：span `name` 序列 1/2-gram saliency 加权计数 + (1−cosine) + UPGMA（`kernel/cluster.py:159-201`）。缺：`agent::operation::tool` span key、3-gram、sublinear TF-IDF、L2 归一化、簇级 top n-gram 解释、structural fingerprint |
| 3 | **旧 R2 结构不可复用** | `structure_versions.state_json` 无任何向量化指纹；R1 无条件复用 active 结构，解析失败还会静默重建（`service.py:806-814`） |
| 4 | **生产链路风险** | 生产 Run 从不加载 active ontology YAML，统一走 `build_dynamic_ontology` 零约束零价格 fallback（`algorithm.py:48-98`）；预检查仅 8 项遥测完整性，不覆盖 embedding/span key/intent 文本/cost/价格 |

## 三、下一步工作列表（实施顺序 E1 → E3 → E2 → E4 → E5 → E6）

排序理由：E1 阻断"空 embedding 仍成功"的假象，必须最先；E3 先于 E2 是为让结构视图接口
与 fingerprint 合同先稳定，避免真实模型接入后二次迁移。

### 阶段 E1：Encoder 合同与失败门禁（最先做）—— ✅ 已完成（2026-11-26）

- [x] 定义平台侧 `IntentEncoder` 接口与配置模型：新增 `platform/app/encoder.py`
      （`ModelAsset` / `IntentEncoder` Protocol / `encode_intents` / 权重 SHA-256 校验），kernel 不动
- [x] 空值 / 维度 / 数量 / hash 四类校验，**空 embedding 直接失败，禁止静默降级**：
      `run_production` 在归一化前执行 `validate_trace_embeddings` 门禁，缺 embedding 或维度
      不一致即抛 `EncoderContractError` 并附修复指引
- [x] Run provenance 记录模型资产：`cohort_runs.model_assets_json`（schema v10→v11，含
      自动迁移），算法步骤 payload 与 `metrics.json` 同步记录；冻结结构新增 `embedding_dim`
- [x] R1 兼容性门禁：维度不匹配或旧空 embedding 结构（无 `embedding_dim` 且质心为空）
      直接拒绝复用并提示触发新 R2；kernel `dim=0` 静默路径保持原样但生产链路已不可达
- [x] 验收：新增 `platform/tests/test_encoder.py` 17 个用例（fake encoder 正常/空值/维度错/
      数量错、权重 hash、生产门禁、R1 拒绝、engine provenance 落库）全部通过；
      平台全套 103 个测试通过无回归

### 阶段 E3：执行视图补齐 + structural fingerprint（先于 E2）—— ✅ 已完成（2026-11-26）

> A/B 裁决与全矩阵重跑记录见修复计划「阶段 E3 A/B 裁决」「阶段 E3 实施与全矩阵
> 重跑记录」两节；决策归档 `DESIGN.md` §7.8。要点：默认 token 配方 `action:v1`、
> saliency 经全因子 A/B 实证保留、`cluster_info` 增 top n-gram 解释、
> `_tfidf_ctx` 进冻结结构 + R1 结构指纹门、`code_hash d229ab802e5a01bf` +
> `reports/` 重发布（scorecard IN SYNC）。

### 阶段 E2：`bge-m3` 平台集成 —— ✅ 已完成（2026-11-27）

> 实施与验收记录见修复计划「阶段 E2 实施记录」；决策归档 `DESIGN.md` §7.9；
> 部署记录 `DEPLOYMENT.md` §3.12。要点：sentence-transformers 6.3.0 离线后端、
> 固定 revision + 10 文件 SHA-256 注册表、加载前逐文件 hash 校验（不符拒绝启动）、
> 指纹绑定 SQLite 缓存、provenance 增 `cache_fingerprint`、E2 测试 20/20。
> **一项显式推迟**：方法论 §5.2.1 的 `[CTX]` session 上下文所需数据不在 trace
> 契约中，保持 `intent-text:v1`，待 E4 预检查验证可得性后引入（须 bump
> `INTENT_INPUT_VERSION` + 新 R2）。

### 阶段 E4：生产链路修复 —— ✅ 已完成（2026-11-27）

> 实施与验证记录见修复计划「阶段 E4 实施记录」。要点：生产 Run 经
> `ontology_from_yaml` 加载 active YAML（动态发现打底 + 治理键覆盖 + `unit_price`
> 通道级合并）；无 YAML → Run 显式 `degraded`，YAML 无效 → 直接失败；
> 预检查 8 → 15 项；R1 冻结结构解析失败不再静默重训（409
> `frozen_structure_unusable` + Run 置 failed）；schema v12 增
> `structure_versions.embedding_dim/structural_fingerprint`（存量回填）与
> `cohort_runs.degraded_json`（同步进运行步骤、metrics.json 与 Run API）。
- [x] 验收：真实 Cloud Run 通过模型/本体/embedding/结构指纹全链路检查——
      已随 E5 完成（2026-11-28，见 E5 报告 §2）

### 阶段 E5：真实数据验证与对比 —— ✅ 已完成（2026-11-28）

> 详细报告见 `platform/E5_VALIDATION_REPORT.md`；实施记录见修复计划「阶段 E5 实施记录」。
> 要点：新旧对照（同窗口同 200 trace）意图簇 1→6、cell 意图纯度 0.74→1.00、
> ARI 0.10→0.29；告警抽样 5/5 根因与 trace 证据一致；附带修复 YAML 加权列表元数校验。
> 遗留量化代价：弃权率 53%（novelty 阈值偏保守 + 训练样本不足）、R2 训练耗时 5.9×。
- [x] 旧结构 vs 新结构对比报告（新旧 cell 仅生成 lineage，不合并历史基线）
- [x] 真实 Cloud 数据诊断：文本覆盖率、embedding 参与率、聚类可分性、novelty 与弃权率、
      告警可解释性、耗时与内存
- [x] 人工抽样复核新告警（结合 M7 试点复核包流程）
- [x] 验收：意图簇解释质量明显改善或给出量化失败原因；告警根因与 trace 证据一致；
      不再以合成标签为唯一质量证明

### 阶段 E6：内网部署治理

- [ ] 离线模型包 + hash 校验说明；Python/依赖/数据库/模型/前端构建版本清单
- [ ] 资源评估：内存、磁盘、首次加载时间、批推理吞吐
- [ ] 回滚方案；更新 `DEPLOYMENT.md` / `INTRANET_HANDOFF.md` / `USAGE_GUIDE.md`
- [ ] 验收：内网按文档完成一次冷启动端到端 Run；权重缺失/hash 错误时启动失败且报错可操作

## 四、非目标与红线（全程遵守）

- 不引入生成式判官；不实现执行视图路线 B（编辑距离/DTW）与路线 C（图嵌入）
- 不修改 R1/R2 生命周期语义与幂等规则；不引入在线模型服务（内网必须离线可运行）
- 旧结构结果仅作对照，不作为新模型质量基准
- kernel 保持纯标准库、确定性；模型资产永不入 Git / 本体 YAML / 发布包

## 五、关键风险与对策

| 风险 | 对策 |
|---|---|
| `bge-m3` 内网资源不足 | 先批推理压测；必要时轻量多语言模型降级，但降级必须改变 fingerprint |
| span key 命名不稳定 | 预检查报覆盖率与重复度，不达标禁止 R2 |
| active ontology 缺价格/约束 | Run 显式 degraded 或失败并输出缺失项 |
| 旧结构误复用 | fingerprint 不匹配直接拒绝 R1 |
| embedding 缓存污染 | 缓存 key 绑定模型 hash + 输入构造 + 预处理版本 |
| kernel 改动破坏可复现性 | 重跑 `invariants` / `runner` 全矩阵 / `reprocheck` / `scorecard --check` / `matrixcheck` 五道门禁 |

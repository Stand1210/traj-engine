# 生产平台设计（多租户 · Langfuse 承载）

> 状态：**设计讨论中**。§1~§4 已定稿并归档；§5/§6 待用户确认后定稿；§7 是待决清单。
> 本文所有 Langfuse 事实均取自 2026-11-09 抓取的官方 OpenAPI 规格与文档，缓存于 `_tmp_lfdocs/`
> （含 `openapi_api.yml` 465 KB / 120 条路径、`openapi_org.yml` 17 KB / 9 条路径，均 gitignored）。
> 所有「我们侧」字段清单均取自实测，不凭记忆：`data/bench_v1/R1/traces.jsonl` 首条记录 +
> `kernel/ingest.py` 的 `EXPECTED_FIELDS` + `ontology/base.py` 的 32 键 + 对 `kernel/ ontology/`
> 全量 `.py` 的引号字面量普查。

---

## 0. 一页速览

**前提（用户拍定，不可动摇）**：两层边界 ——
**Organization = 租户**（限流 / 账务 / 审计边界，决策 1.A），**Project = 本体**（分析边界，
2026-11-09 追加拍定：一个 project 默认只承载一类 agent 的执行轨迹，一个 project 对应一个本体 YAML）。
project 内部混入的噪声属于业务方自己的行为，平台**不清理**，但**必须度量并隔离出告警流**（F5 / §6）。
**★部署形态（2026-11-11 拍定，取代原「暂不讨论」）**：**一套平台部署只对接一个 Langfuse 实例**，
所有接入业务方共用它（各自不同 Organization / Project，但 `base_url` 与版本完全相同）。
不存在「同一部署下 A 业务方是 v3、B 业务方是 v4」。
⟹ `base_url` 与 `profile` 是**部署级单值**，**不进租户档案**。
**★2026-11-11 第二次简化（用户提出）**：profile 由**后端启动命令参数 `--profile <name>`** 选定，
开发期固定三份 profile 文件（`cloud-v4` / `selfhosted-v3` / `selfhosted-v4`），
`base_url` 放进 profile 内（可被 `--base-url` 或环境变量覆盖）。
**原设计的 `platform.yaml` 已删除**。整体迁移 = 换启动参数 + 重启。详见 `MODULES.md` §1.2.1 / §1.5。

| # | 议题 | 决策 | 落地后果 |
|---|---|---|---|
| 1 | 组织边界 | **A：一租户一 Organization** | Cloud 上 Org 要人建一次；建好后 project / apiKey / membership 全部可程序化（F1） |
| 2 | Key 保管 | **明文**（暂不考虑安全） | 但**不能放本体 YAML**，放 L0 租户档案 —— 理由是版本学不是安全（§3.3） |
| 3 | 本体绑定 | **认可 L1/L2 分层，按「谁填写」重划** | L1 业务专家 / L2 平台；原则：L1 说"什么是对的"，L2 说"从哪儿读到"（§3） |
| 4 | 混范式 cohort | **改为 1 project = 1 本体**（用户提出，F5 实测支持，我原先反对） | 删掉自动分桶；cohort 退化为 project + 时间窗 + 抽样（§5） |
| 5 | 租户内噪声 | **不清理，但度量 + 隔离出告警流**（F5 实测：打分安全、告警流被摧毁） | 删掉范式扫描；改为零阈值准入自检 `foreign_ratio`（§6） |
| 6 | 基准数据集接入 | **认可：不导入 Langfuse** | `TraceSource` 抽象 + `JsonlTraceSource`；基准注册为平台内部租户 |
| 7 | 结果存放 | **认可：写回租户自己 project** | `POST /api/public/scores`，`source=API`；平台侧另存零残差证据链 |
| 8 | 人工复核 | **复用原生标注队列** | 有完整公开 API（F2）→ 全程可程序化；前端 M6 从"采集"缩成"看回流" |

**五条新核实事实（其中三条推翻了我自己上一轮的判断）**：F1 组织开通 · F2 标注队列 API ·
F3 `expandMetadata` 截断 + `usageDetails` 开放映射 · F4 Langfuse 自带 Topics（闭测）·
**F5 混本体 cohort 实测（新做的实验，直接决定了 #4/#5）**。见 §2。

---

## 1. 决策记录（用户 2026-11-09 拍定）

### 1.1 一租户一 Organization（决策 1 = A）
- **依据**：Cloud 限流是**按 Organization 分桶**的，桶由该 Org 下**所有 project、所有 API key 共享**。
  我们唯一的批量读路径 `GET /api/public/v2/observations` 落在 **General API 桶**：
  Hobby 30 req/min · Core 100 req/min · Pro/Team/Enterprise 1000 req/min。
  若全平台共用一个 Org，这个桶就是**全平台的总预算**，一个租户能把其余租户饿死。
- **选 A 的代价**：Cloud 上**没有**程序化建 Org 的公开 API（F1）→ 租户需手工建一次 Org。
- **选 A 的收益**：限流天然隔离、随租户数线性扩展、租户数据在自己 Org 内、审计边界清晰。
- **落地形态（F1 之后修正）**：租户只做**一次**手工动作 —— 建 Org + 铸一个 **org-scoped API key**
  交给我们；此后 project 创建、project key 铸造（可带 `expiresAt`）、成员授权全部自动化。

### 1.2 凭据明文（决策 2）
用户明示"先不考虑安全性"。本设计遵从，但把凭据放在 **L0 租户档案**而非本体 YAML，
理由是**版本学**（§3.3），不是安全。**唯一必须提一次的事实**：本仓库
`https://github.com/Stand1210/traj-engine` 是**公开仓库**，明文凭据一旦提交即公开泄露，
且历史不可擦。故 L0 档案必须 gitignored（`.gitignore` 已覆盖 `.env`；新增 `/tenants/`）。

### 1.3 本体分层按「谁填写」重划（决策 3）
见 §3。核心原则：**L1 声明"什么是对的"（业务专家签字），L2 声明"从哪儿读到它"（平台工程师维护）**。

### 1.4 基准数据集不导入 Langfuse（决策 6）
- **依据**：229.5 MB；384 维合成 `embedding` 在 Langfuse **没有存放位置**，且从未过真实编码器；
  `gt.jsonl` 的 38 个真值键**没有存放位置**；逐条摄入直接撞配额。
- **做法**：`TraceSource` 抽象 → `JsonlTraceSource`（读 `data/bench_v1/`）+ `LangfuseTraceSource`
  （读租户 project）。把基准**注册为平台内部租户**，走完全相同的代码路径。
- **附带红利**：可演示"同一个 UI 在基准 cohort 上复现已发表的 scorecard"。

### 1.5 结果写回租户自己的 project（决策 7）
- `POST /api/public/scores`（**接受 list**）。`source` 枚举 `API | EVAL | ANNOTATION` ——
  取 **`API`**，这让"我们的分数不是 LLM-as-a-Judge"在**租户自己的 Langfuse UI 里自证**，
  是专利与比赛答辩的强资产。
- `dataType`：`NUMERIC`（总分 `traj_s`、五维 `traj_dim_*`）· `CATEGORICAL`（等级 A/B/C/D）·
  `BOOLEAN`（`traj_alert`）· `TEXT`（首要扣分归因）。
- `ScoreConfig` **不可变但可归档/恢复** → 与本体"发布即不可变"同构；`configId` 关联；
  Score `id` 可当**幂等键**（重跑不产生重复分数）。
- 租户可用过滤搜索栏 `scores.traj_s:<60` 自查（Cloud 需开 v4 preview）。
- **Langfuse 表达不了的**（`contrib` 零残差分解、`gates`、`evidence` 三步下钻、版本四元组）
  由平台侧持久化，UI 从平台读，Langfuse 只做"分数入口"。

### 1.6 复用原生标注队列（决策 8）
见 F2。闭环变成：算法选出 3~5% → `POST /annotation-queues/{queueId}/items` 自动入队到**租户自己的**
队列 → 复核在租户 UI 内完成（尊重租户边界）→ 我们从 `GET /api/public/v3/scores` 带 `annotation`
字段组读回（`authorUserId` / `queueId` / `source=ANNOTATION`）→ 喂 `kernel/calib.py` 重校准。

---

## 2. 新核实事实（F1~F5）

### F1 组织开通：admin API 自托管限定，但 org-scoped key 能自动化其余全部 ★推翻我上一轮判断
- 上一轮我说"A = 无程序化开通"。**只对了一半。**
- `openapi_org.yml` 首部原文：**"This admin API is only available on self-hosted instances, not on
  Langfuse Cloud. An administrator must set the `ADMIN_API_KEY` environment variable."**
  9 条路径：`GET|POST /api/admin/organizations`、`GET|PUT|DELETE /api/admin/organizations/{id}`、
  `GET|POST /api/admin/organizations/{id}/apiKeys`、`DELETE .../apiKeys/{apiKeyId}`、
  `POST /api/admin/projects/{projectId}/transfer`。鉴权 `Bearer $ADMIN_API_KEY`。
- **但公开 API 里有这些**（`openapi_api.yml`，Cloud 可用）：
  - `POST /api/public/projects` —— 描述原文 **"Create a new project (requires organization-scoped
    API key)"**。body：`name`（必填）、`retention`（**必填**，"Must be 0 or at least 3 days.
    Requires data-retention entitlement for non-zero values"）、`metadata`（可选）。
  - `POST /api/public/projects/{projectId}/apiKeys` —— 同样需 org-scoped key；支持 `name`、
    `expiresAt`（ISO 8601，**可让 key 自动过期**）、以及**预定义** `publicKey`（须 `pk-lf-` 开头）
    与 `secretKey`（须 `sk-lf-` 开头）。`note` 是 `name` 的已弃用别名，二者不可同给。
  - `GET /api/public/projects`、`PUT /api/public/projects/{projectId}`、`DELETE /api/public/projects/{projectId}`
  - `GET /api/public/organizations/apiKeys`、`GET /api/public/organizations/projects`
  - `GET|PUT|DELETE /api/public/organizations/memberships`、`GET|PUT|DELETE /api/public/projects/{projectId}/memberships`
- **结论**：存在 **org-scoped API key** 这一独立凭据类别（区别于 project-scoped）。
  1.A 的接入流程可压到"租户手工建 Org + 交一个 org key"，其余全自动 ⟹ **1.A 的最大缺点被消掉，A 更稳。**
- ⚠ 未验证：org-scoped key 在 UI 的哪个位置铸造、Cloud 各档位是否都开放 `POST /projects`。
  接入前需用一个真实 Org 实测一次。

### F2 标注队列有完整公开 API（10 端点）
`GET|POST /api/public/annotation-queues` · `GET /api/public/annotation-queues/{queueId}` ·
`GET|POST /api/public/annotation-queues/{queueId}/items` ·
`GET|PATCH|DELETE /api/public/annotation-queues/{queueId}/items/{itemId}` ·
`POST|DELETE /api/public/annotation-queues/{queueId}/assignments`。
`GET items` 支持 `status` 过滤 + `page`/`limit`（page 从 1 起）。
文档亦确认："You can manage annotation queues via the API. This allows for scaling and automating
your annotation workflows."
⟹ 决策 8 **可全程程序化**，前端 M6 模块从"采集标注"缩为"看回流 + 触发重校准"，前端工作量下降。

### F3 两个会静默咬人的细节 ★新增适配器硬要求
- **(a) `metadata` 默认截断到 200 字符。** 官方原文：`metadata` 字段组
  "truncated to 200 chars by default, use `expandMetadata` to get full values"；
  参数表：`expandMetadata` = **"comma-separated keys — Metadata keys to return untruncated"**。
  我们有 **6 个字段只能走 metadata**（§4.3），其中 `output_citations` / `output_facts` 极易超 200 字符。
  **⟹ 适配器必须显式传 `expandMetadata=<这 6 个键>`，否则静默截断 → `traceable_number_ratio` 算错 → O 维误判。**
  这是一个"不报错、只算错"的陷阱，优先级高于任何功能开发。
- **(b) `usageDetails` / `costDetails` 是开放映射，契约不保证键名。**
  规格原文：`usageDetails: object, additionalProperties: integer` —
  "Key is the usage metric name, value is the number of units consumed"；
  `costDetails: object, additionalProperties: number(double)` — "value is the cost in USD"。
  文档示例只出现 `input` / `output` 两个键。
  **⟹ `tokens_system_prompt` / `tokens_cache_read` / `tokens_cache_write` 不是契约保证的**，
  各 provider 键名不同（如 Anthropic 系 `cache_read_input_tokens` / `cache_creation_input_tokens`）。
  必须在 **L2 做每租户可配的 `usage_key_map`**；映射不到就诚实计入 telemetry loss
  （`missing_field_ratio` 会如实上升，`kernel/score.py` 的 `mfr > 0.20` 置信度降级会生效）。
  上一轮我给这三个字段打的 hedge，现在可以定性了。
- 另：`parseIoAsJson` **已弃用**，`true` 直接返回 400；`input`/`output` 是**原始字符串**，需自行解析。

### F4 Langfuse 自带 Topics（closed beta，`unstable`）★专利/答辩必须提前想好差异化
`GET /api/public/unstable/{topics,topic-facets,topic-rules,topic-summaries}`（各含 POST/PATCH/DELETE）。
规格原文摘录：
- facet：有 `name` / `description` / `isBuiltIn` / `active`；`topic-summaries` =
  "the current Topics summary per trace and facet: **what the trace is about from the facet's
  perspective**"。
- rule："**A rule selects traces with an observation filter and a sampling rate**, runs the facets
  in `facetIds` and keeps its own live topic map."
- topic："List the topics of each active facet's **live map**, with the number of traces currently
  assigned to each topic in the window. **Retired topics are not listed.**" 窗口默认近 7 天、最长 93 天。
- 全部标注 **"Unstable: Topics is in closed beta. The shape may change without notice."**

**这是与我们「意图视图聚类」最接近的原生能力，比赛评委与专利审查都可能拿它质疑。差异化五条：**
1. **Topics 是生成式的**（每条 trace 一次 LLM 摘要）→ 正落在我们要规避的那一类：不可位级复现、
   有偏置、按条计费、输出自由文本、**不能当审计证据**。我们的聚类是判别式/结构式的。
2. **Topics 没有条件基线、没有异常识别、没有打分。** 它回答"大家在问什么"，不回答
   "哪条执行偏离了它自己那一类的基线、偏离多少、归因到哪一步"。没有 `dims` / `contrib` /
   `gates` / 零残差 / 概率校准。
3. **Topics 是单一扁平语义轴**；我们是**多视图共识**（意图 × 模式，`CONSENSUS_THRESHOLD=0.35`）
   + **弃权桶一等公民**（R3 `novelty_rate=0.2867`，藏起来就会把 71% 覆盖率读成 100%）。
4. **Topics 是本体无关的**；我们的聚类必须绑定已注册业务本体，且簇直接喂 `slo_anchors` 条件基线。
5. **Topics 处于 closed beta 且 `unstable`**，官方明示 shape 随时变 → 不能作为专利级生产依赖。
**可借鉴（不依赖）**：`topic-rules` 的"**observation filter + 采样率**"结构与本文 §5 的
cohort 选择器**同构** → 说明这是业界正在收敛的原语，我们命名与之对齐不吃亏。
若某租户已开 Topics，`GET /unstable/topic-summaries` 可作为**额外一个聚类视图的输入特征**
（当特征用，绝不当判官用）—— 但闭测，**只观望，不写进主链路**。

---

### F5 ★混本体 cohort 实测（本文件唯一新做的实验，直接决定 #4/#5）
- **动机**：R8 是**纯 ontB** cohort，"一个 cohort 里混两个本体"**从未测过**。用户在拍架构，不能靠猜。
- **方法**：**事后重算，不落盘**。替换式设计（总量恒为 4000 条，ontB 占 0 / 5 / 20 / 50%），
  全部用 **ontA** 归一与打分 —— 这正是 1:1 下生产的真实行为（project 只注册了一个本体）。
  照抄 `bench/runner.py:199-263` 的调用口径。**未改任何 `code_hash` 闭包文件**，
  `data/`、`reports/` 零写入。脚本 `platform/mixexp.py`，原始结果 `platform/mixexp-results.json`。
- **拼接伪影已排查**（这类实验最容易死在这里）：
  - `session_id` **跨 regime 撞名 658 个**（两边都叫 `sess-00000`）→ 已给 ontB 加命名空间。
    不处理的话 `FEAT.annotate_sessions` 会把两个范式的轮次合并，**静默**污染
    `session_turn_count` / `turn_index` / `reformulation_signal`。
  - `trace_id` / `span_id` 不撞（自带 regime 前缀）。
  - `ts_start` 两个 regime 天然重叠（同为 ~72 h、同一起点）→ **无需平移**。
    平移本来是必需的，因为 `drift.detect_drift` 按 `ts_start` 排序，错接时间轴会造出假漂移。
  - 实测四档 `drift_detected` 全为 `False`，确认无伪影。
- **三条结论**：
  1. **聚类是天然的噪声防火墙 —— 证伪我自己的担心。** `shared_cells = 0` 在四个污染档**全部成立**：
     外来轨迹**从不**与合法轨迹共用一个 cell。`A.mean_S_normal` 91.05 → 90.99 / 91.48 / 91.47，
     `A.fpr_pool` ≤ 0.00057，`A.p_at_50 = 1.0` 四档不变。
     我原先"混合分布会让簇内基线失效"的说法，对**结构互异的外来范式不成立**。
  2. **告警流被摧毁 —— 证伪用户假设的另一半。** B 档 `fire_unfulfilled = 1.0`、`fire_hard = 1.0`、
     `alert_rate = 0.951~0.995`；overall `fpr_pool` 0.00027 → **0.48374**（**1790 倍**），
     `f1_pool` 0.889 → **0.235**，`alert_rate` 0.0585 → **0.503**（8.6 倍）。
     机制**先由读码预言、后被实测确认**：`kernel/detect.py:280` 的 `unfulfilled` →
     `:388` 的 `hard` → `:631` 的 `alert_rule = (not novelty) and struct["hard"]`；
     外来轨迹对已注册本体声明的**任何一条** pattern 都不成立 → `unfulfilled=True` →
     `hard=True` → **无条件硬告警**，与它自己是否真的有问题无关。
     换算到业务：20% 污染、4000 条 / 3 天时，B 单独产出约 **766 条告警 ≈ 255 条/天**，
     是 `ALERT_BUDGET_PER_DAY = 5`（`bench/regime.py:167`）的 **51 倍**。
  3. **★反直觉：污染越轻，运营流越危险。** `topk(15) precision`：ctrl 1.0 → **5% 档 0.6** →
     20% 档 1.0 → 50% 档 1.0。**5% 档跌破了 `OPS_STREAM_PRECISION_MIN = 0.80`
     （`bench/regime.py:171`）门禁，而更重的污染反而恢复了。**
     机制：`a_raw` 是**簇内相对量**。少量外来轨迹挤成 **1 个紧致簇**（`n_cells_B = 1`），
     簇内基线极窄 → 每个成员都显得极端偏离 → 霸占 top-K（`topk_A_share = 0.5333`）；
     大量外来轨迹裂成 2~3 个簇、簇内方差变宽 → **自我归一** → A 的真极端值重新夺回 top
     （`topk_A_share = 1.0 / 0.9333`）。
     **⟹「少量噪声可以忽略」这个直觉是错的，方向恰好相反：少量异范式噪声在运营流里的密度最高。**
- **附带验证了一条既有不变量**：B 簇**确实被 bind 上了** ontA 的某条 pattern
  （`n_bound_cells == n_bindable_cells` 四档全成立），但 `unfulfilled` 仍以 1.0 触发 ⟹
  slice6 的不变量 `detect.unfulfilled_needs_no_binding` 正在做它该做的事，
  这是它在真实混流量下的一次独立验证。
- **诚实的适用边界**：已证明的防火墙只对**结构互异**的外来范式成立
  （ontA / ontB 声明动作交集 = ∅、模型名不同 `adn-llm-*` vs `rca-llm-*`、span 形态不同）。
  对**近邻范式**（同一个 agent 换了几个工具）**未测** —— 按 §5.2 那种情况本就该写成
  一个本体的多条 `required_steps`；若业务方没这么做，我们手上没有数据。
  这是唯一值得后续补一个 regime 的点。
- **控制组不精确复现已发表的 R1**（`f1_pool` 0.88931 vs 0.8807、`n_cells` 8 vs 6、
  `novelty_rate` 0.008 vs 0.01375），因为本 harness 用 `SEED=20261109` 而非 R1 的 spec seed，
  且跳过校准。**有效对比是同一 harness 内的 ctrl vs mixed（同 seed、同代码路径）**，
  不是与已发表 scorecard 对比。四档 wall clock 93~122 s。

---

## 3. 配置分层：L0 / L1 / L2 / L3（按「谁填写」重划）

### 3.1 划分原则
> **L1 声明"什么是对的"，L2 声明"从哪儿读到它"。**

上一轮我按"谁读取"分（内核读 = L1，适配器读 = L2），用户否掉，改按**谁有能力填 + 谁对变更负责**分。
新轴的好处：变更评审路径清晰 —— L1 改动要走**业务方评审**（改的是业务规则，分数会变），
L2 改动走**平台工程评审**（改的是取数实现，分数不该变；若变了就是 bug）。

| 层 | 谁填写 | 内容 | 变更评审 | 是否入 `spec_hash`/`anchor_version` |
|---|---|---|---|---|
| **L0 租户档案** | 平台（接入时录入） | 凭据、org/project id、队列 id、默认本体（**★2026-11-11 移除 `host` 与 `profile`**：部署级属性，见 `MODULES.md` §1.2.1） | 平台工程 | **否**（关键，见 §3.3） |
| **L0' 部署选择**（**不是文件，是启动参数**） | 部署时的**启动命令** | **`--profile <name>`**（三选一）· 可选 `--base-url` 覆盖 · 可选 `--skip-version-check` | 平台工程 | **否**（不入 hash：换环境不该让历史分数溯源断裂）。**原设计的 `platform.yaml` 已删** |
| **L1 分析本体** | **业务专家** | 业务语义与业务规则：动作词表、红线、必经流程、SLO、单价、意图、参数合法域 | **业务方** | **是** |
| **L2 接入映射** | **算法平台** | Langfuse 侧取数实现：识别谓词、kind 映射、root 规则、参数取值路径、usage 键名映射、metadata 键名约定、字段组、`expandMetadata` 清单、运行参数 | 平台工程 | **是** |
| **L3 合成词表** | 基准生成器 | 答案模板、错误文案、子目标措辞、KB 源名等 | 不外发 | 仅 bench |

L1 与 L2 **必须是两个文件**：变更节奏与责任人不同。混在一起会导致"改一次埋点就要动业务规则文件"，
业务方评审被无谓触发。

### 3.2 32 键归属表（普查结果；**最终租户契约以 `LIFECYCLE.md` §2.5 为准**）

> **★2026-11-10 两处纠正（都有代码出处，保留原文以留审计痕迹）**
> 1. **内核读取键是 7 个，不是 8 个。** 上一轮把 `actions` 记成读取点是**假阳性**：
>    它在 `kernel/` 的唯一命中是 `kernel/detect.py:558` 的 `{"actions": struct["illegal_actions"]}`
>    —— 那是**证据字典的 key**，不是读本体。
> 2. **「内核读不读」≠「业务方要不要填」。** 前者是静态事实，后者的判据是
>    **失败方向是否安全**（`LIFECYCLE.md` §2.3）。据此**10 个键从租户 YAML 删除**。
>    下表「最终归属」列已按此更新，被删项划掉但保留原判定。

普查方法：对 `kernel/*.py` + `ontology/*.py` 搜引号字面量，再逐条人工确认
「读本体」vs「证据字典 key」。**内核只读 7 键**：
`unit_price`(ingest，**硬索引**) · `forbidden_actions`(detect) ·
`required_steps`(binding,detect,features) · `validators`(detect) · `slo_anchors`(baseline) ·
`context_window`(features) · `models`(features)。**其余 25 键内核零引用。**

| 键 | 内核读 | 最终归属 | 谁填 | 依据 / 缺省后果 |
|---|---|---|---|---|
| `id` · `version` | ✗（bench 用） | **Tier 0** | **平台合成** | 注册标识；发布即不可变，入 `spec_hash` |
| `unit_price` | ✓ ingest（**硬索引**，缺失即 `KeyError`） | **Tier 0** | **平台合成 0 值**；业务方有采购价则覆盖 | 只在 `span.cost is None` 时兜底（`ingest.py:92`）。全 0 且 Langfuse 也无 `totalCost` ⟹ **C 维退化成常数**，预检必须报「C 维不可用」，**不得静默给成本满分** |
| `forbidden_actions` | ✓ detect（`:283`） | **Tier 1 · 唯一必填** | **业务专家（红线）** | 漏填 = **漏报**（安全侧）。ontB 的 `commit_change_without_peer_review` 就是「变更须同行评审」的红线表达 ⟹ 正向义务可写成负向红线 |
| `validators` | ✓ detect（`:216/:370`） | 可选 | 业务专家 | **实测只是一个浮点**：`detect.py:371` 仅 dispatch `kind=="number_traceable"` 读 `spec.min_ratio`（默认 `DEFAULT_MIN_RATIO=1.0`）。`ontology/base.py:69,71` 声明的 `max_hits`/`min_chars` **内核零引用** ⟹ UI 不得渲染成可填项 |
| `pattern_count`（**新增**） | ✗（**待接线**，见下注） | 可选 | 业务方**确认平台提案** | 替代 `required_steps` 喂 `cluster_views(n_declared_patterns=...)` → `cluster.py:794-795` `kmax_pat=min(8, n_dec+2)`。**零内核改动**：`bench/runner.py:213` 现在传 `len(required_steps)`，生产改由 **B4 执行壳**传 `pattern_count` |
| `slo_anchors` | ✓ baseline（`:347`） | 可选 | 业务专家 | **两个出厂本体本来就是 `{}`** ⟹ 已发表的全部 8 档、五维均值 +0.921022 就是在**零 SLO 声明**下跑出的。键集须 ⊆ `{L, latency_total, C, cost_total, tokens_total}` |
| `models` | ✓ features（`:405`） | 可选 | 业务方 | 可从 trace 的 `model` 取值自动兜底；缺省 ⟹ `mult={}` |
| `context_window` | ✓ features（`:437`） | 可选 | 业务方平台团队 | 缺省 ⟹ `context_utilization=None`（**如实缺失，不伪造**） |
| ~~`actions`~~ | **✗ 假阳性**（`detect.py:558` 是证据 key） | **删除** | — | 平台侧 `foreign_ratio` 改用 **L2 自动收集的观测 `name` 词表**（§6.1 已同步修正） |
| ~~`required_steps`~~ | ✓ binding/detect/features | **删除** | — | 失败方向**危险**：漏一条合法路径 ⟹ 走该路的**所有**轨迹 `unfulfilled`（`detect.py:280`，与 binding 无关）→ `hard`（`:388`）→ **无条件告警**（`:631`）= 大规模误报。代价与缓解见 `LIFECYCLE.md` §2.4。⚠ `bench/invariants.py:379` 要求本体声明它 ⟹ **`ontology/base.py` 的 ontA/ontB 保持不动**，只在租户 YAML 层不暴露 |
| ~~`optional_steps`~~ · ~~`intents`~~ | ✗ | **删除** | — | 内核零引用。「声明性但未生效」的字段只会让业务方改了没效果、误判平台有 bug（§3.4-a 的同一原则：**不如不暴露**） |
| ~~`time_windows`~~ · ~~`param_schema`~~ | ✗ | **删除 → 下沉 L2** | — | 见 §3.4-b 的 2026-11-10 追加纠正 |
| `param_keys` · `kind_map` · `root_action` · `tool_catalog` | ✗ | **L2 · 平台** | 平台 | `kind_map` 是**平台常量**（Langfuse `type` 枚举是平台词表，对所有租户一样）；`root_action` 生产由 `isRootObservation` 原生给出 |
| `action_text` / `answer_templates` / `answer_empty_templates` / `golden_template` / `out_frames` / `subgoal_core` / `subgoal_detour` / `subgoal_frames` / `error_messages` / `warn_messages` / `kb_sources` / `query_langs` / `lang_token_factor` / `system_prompt_tokens` / `prompt_versions` | ✗ | **L3 · 基准生成器** | **永不外发** |

**L2 需新增的键**（基准里不存在，因为基准直接吐 `kind`/`arg_valid`）：
`recognition`（识别谓词）· `kind_map_from_observation_type` · `root_rule` ·
`param_paths`（参数在 `input` 原始串里的路径）· `usage_key_map`（F3-b）·
`metadata_keys`（6 个字段的键名约定 + `expandMetadata` 清单）· `field_groups`（固定请求的字段组）·
`status_map`（`level`+`statusMessage` → 我们的 `status`）· `intent_source`（`traceName` 还是 root `input`）。

### 3.3 为什么凭据不能放本体 YAML（版本学理由，非安全理由）
本体**发布即不可变**，且被哈希进 `spec_hash` → 驱动 `anchor_version` → 驱动每一条分数。
这与 Langfuse 自己给 `ScoreConfig` 选"不可变但可归档"是同一个理由。
**若 key 写在本体 YAML 里，轮换一次 key 就要升一次本体版本、重算一次 anchor、让历史分数的
溯源链断裂。** 这是可直接度量的错误，与"安不安全"无关。
⟹ 凭据放 **L0 租户档案**（明文，遵从决策 2），L0 **不入 hash**，轮换 key 不惊动任何版本。
L0 必须 gitignored（仓库是公开的，见 §1.2）。

### 3.4 三条诚实提示
- **(a) 「声明性·当前未生效」字段不能装作能改分数。** `intents` / `optional_steps` 内核零引用。
  归 L1 是对的（业务专家最懂），但 UI 上必须标注"当前版本不参与打分"，否则业务方改了没效果
  会认为平台有 bug。这与 `kernel/features.py:5` 那句"21 scalars"是同一类已知文档债，
  同一处理原则：**如实标注，不为了好看而改在 hash 闭包里的东西。**
- **(b) ★「generator-only」在生产会变强制 —— 这是上一轮分类的陷阱。**
  `param_schema` / `time_windows` / `param_keys` / `kind_map` / `tool_catalog` 被判为"生成器专用"，
  **仅仅因为基准把派生字段预先算好了**：`arg_valid` 是生成器直接写进 span 的布尔值，
  内核只读结果。**生产上 Langfuse 没有 `arg_valid` 这一列** → 必须适配器现算 →
  现算就需要 `param_schema`（合法域，L1）+ `param_keys`/`param_paths`（去哪儿读，L2）。
  同理 `kind` 在基准里是直接吐的，生产上要靠 `kind_map` 从 `type`+`name` 推。
  **⟹ 静态分析的"内核不读"不等于"生产不需要"。判断依据必须是：这个字段是不是派生字段的上游。**
  **★2026-11-10 追加纠正（推理成立，但归属改了）**：「生产需要」**不等于「要业务方填」**。
  `param_schema`（合法域）与 `time_windows`（合法取值枚举）**从 L1 删除、下沉 L2**，
  由平台在接入预检时**从观测值自动收集候选域**（与 `name` 词表同一趟扫描，**零额外 API 调用**）。
  **诚实的代价**：自动收集的域是**流行度估计，不是契约** —— 与 `binding.py:102-104`
  对 declared / learned 的区分同理。所以生产上 `arg_valid` 降级为「偏离观测域」而非「违反声明域」；
  需要契约级判定的租户走 **L1 `validators`** 这条已实现的路（当前只有
  `number_traceable.min_ratio` 一个旋钮被消费）。
  `kind_map` / `root_action` / `tool_catalog` / `param_keys` 维持 L2 不变。
- **(c) `ontology_id` 至今仍无任何校验。** 它写在每条 trace 上
  （`bench/generate.py:1270`、契约 `contracts/schemas.md:48`），但 `kernel/`、`bench/invariants.py`、
  `bench/reprocheck.py`、`bench/matrixcheck.py` **零引用**，22 条不变量没有一条覆盖它。
  绑错本体的后果是**全面崩塌而非降级**：ontA(9 动作) ∩ ontB(7 动作) = **∅**
  （⚠ 这只对**声明词表**成立；**观测词表**共有 root action `agent_run`，
  所以判据必须排除 root —— 见 §6.1，F5 实测过这一点），
  `required_steps` 指向的动作一个都不出现 → binding 交集为空 → slice6 的 `unfulfilled`
  （"声明的工作流一个都没完整实现"）对 **100%** 轨迹成立 → 大规模误报；
  同时 `forbidden_actions` 一个都匹配不上 → 该通道彻底静默。
  **⟹ 生产适配器必须在入口做 `ontology_id` 一致性断言，并把它补成第 23 条不变量。**

---

## 4. 逐字段 Langfuse 映射表

字段组提醒（F3）：默认只返回 `core,basic`。**未请求的字段组是「缺席」不是「null」**。
`kernel/ingest.py:37` 在**修复前**的原始 span 上按 `EXPECTED_FIELDS[kind]` 数缺失，
`kernel/ingest.py:32-36` 的注释记录了"在修复后测量会让它处处为 0.0，从而使
`kernel/score.py` 的 `mfr > 0.20` 置信度降级变成死代码"。
**⟹ 必须请求固定的全字段组集合并把它写进溯源，否则 `missing_field_ratio ≈ 1.0`、
每条轨迹都被降级、置信度维度退化成常数。**

`EXPECTED_FIELDS` 实测：llm 13 · agent 10 · tool 6 · retrieval 7 · guard 5；
`KEY_FIELDS = (ts_start, ts_end, tokens_prompt, tokens_completion, cost, status)`。
基准对**所有 kind 一律吐满 29 键**（不适用的置 null）。

### 4.1 span 的 29 键（实测内核消费 28，唯一无消费者的是 `status_message`）

| 我们的字段 | 内核消费 | Langfuse 来源 | 字段组 | 备注 |
|---|---|---|---|---|
| `span_id` | detect,features,ingest | `id` | core | 原生 |
| `parent_id` | features,ingest | `parentObservationId` | core | ⚠ root 陷阱见下 |
| `ts_start` | baseline,detect,features,ingest | `startTime` | core | 原生 |
| `ts_end` | baseline,detect,features,ingest | `endTime` | core | 未结束会缺 → `has:endTime` 可过滤 |
| `kind` | detect,features,ingest | **无原生列** ← L2 `kind_map` 从 `type`+`name` 推 | core,basic | `type` 枚举大写：GENERATION/SPAN/EVENT/AGENT/TOOL/CHAIN/RETRIEVER/EVALUATOR/EMBEDDING/GUARDRAIL（10 类）。我们 5 类的建议映射：`agent←AGENT` · `llm←GENERATION(+EMBEDDING)` · `tool←TOOL` · `retrieval←RETRIEVER` · `guard←GUARDRAIL(+EVALUATOR)`；**SPAN/CHAIN/EVENT 无对应，必须靠 name 规则** |
| `action` | baseline,detect,features | `name`，或 L2 `tool_catalog[tool_name]` 回退 | basic | 精确匹配 |
| `level` | baseline,features | `level` | basic | DEBUG/DEFAULT/WARNING/ERROR，原生 |
| `status` | detect,features,ingest | **无同名列** ← L2 `status_map`(`level`,`statusMessage`) | basic | |
| `status_message` | **无消费者** | `statusMessage` | basic | 留作证据展示 |
| `model` | features,ingest | `model` | model | 另有 `internalModelId`、`modelParameters` |
| `prompt_version` | features,ingest | `promptVersion` | prompt | |
| `ttft` | features,ingest | `timeToFirstToken` | metrics | 同组还有 `latency` |
| `tokens_prompt` | baseline,detect,features,ingest | `usageDetails.input` | usage | `inputUsage` 已弃用 |
| `tokens_completion` | baseline,detect,features,ingest | `usageDetails.output` | usage | |
| `tokens_system_prompt` | features,ingest | ⚠ **契约不保证** ← L2 `usage_key_map` | usage | F3-b |
| `tokens_cache_read` | features,ingest | ⚠ 同上 | usage | 如 `cache_read_input_tokens` |
| `tokens_cache_write` | features,ingest | ⚠ 同上 | usage | 如 `cache_creation_input_tokens` |
| `cost` | features,ingest | `totalCost`（USD double） | usage | `ingest.py:71` 再用 `unit_price` 归一 |
| `cost_details` | features,ingest | `costDetails`（开放浮点映射） | usage | 基准里**故意**排除在 `EXPECTED_FIELDS` 外（它分解 `cost`） |
| `input_text` | features,ingest | `input`（**原始字符串**） | io | `parseIoAsJson=true` → 400 |
| `output_text` | features,ingest | `output`（原始字符串） | io | |
| `tool_name` | features,ingest | `name`（TOOL 类型时）或从 `input` 解析 | basic,io | 无独立列 |
| `tool_params` | features | 从 `input` 解析（L2 `param_paths`） | io | 无原生列 |
| `arg_valid` | features,ingest | **无原生列** → 适配器用 L1 `param_schema`+`time_windows` 现算 | — | ⚠ 基准由生成器预写；见 §3.4-b |
| `output_citations` | features,ingest | **无原生列** → metadata + `expandMetadata` | metadata | 易超 200 字符 |
| `output_facts` | features | **无原生列** → metadata + `expandMetadata` | metadata | 易超 200 字符 |
| `subgoal_text` | features,ingest | **无原生列** → metadata | metadata | |
| `verifier` | features,ingest | **无原生列** → metadata | metadata | GUARDRAIL/EVALUATOR 的判定结果 |
| `finish_reason` | detect,score | **无原生列** → metadata | metadata | 影响 `truncation` 与 `unfinished` 两条判据 |

**root 识别陷阱（必须处理）**：`isRootObservation=true` **不等价于** `parentObservationId` 为空 ——
应用级 root 的父节点可能在另一个服务里。官方明说"multiple matching roots indicate an integration
issue"，且若本 project 没导出 root，该过滤器直接不命中 → 退回按 `traceId` 分组。
而 `kernel/ingest.py:45` 靠 `parent_id is None` 找 root、`:47-57` 按时间包含关系重建孤儿 ⟹
**朴素映射会把合法 root 错误重挂父节点，直接改变 `depth` / `branch_factor` / `critical_path`。**
处理：**以 `isRootObservation` 为准，显式把 `parent_id` 置 null**，并上报"0 个 root"与"≥2 个 root"
的轨迹计数。

### 4.2 trace 的 19 键（实测 19，不是 18）

分类三值：**遥测**（生产可得）· **平台派生**（平台侧算）· **真值专属**（基准独有，生产恒缺）。

| 字段 | 内核消费 | 生产来源 | 分类 |
|---|---|---|---|
| `trace_id` | cluster,detect,features,score | group by `traceId`（v4 是 observations-first，trace 靠分组重建） | 遥测 |
| `ts_start` | baseline,detect,features,ingest | min(`startTime`) / root 的 `startTime` | 遥测 |
| `spans` | baseline,detect,features,ingest,score | 同 `traceId` 的 observations | 遥测 |
| `session_id` | features | `sessionId` | 遥测 |
| `turn_index` | features | session 内按 `startTime` 排序推导 | 平台派生 |
| `session_turn_count` | features | session 聚合推导 | 平台派生 |
| `intent_text` | features | `traceName`（trace_context 组）或 root `input`，由 L2 `intent_source` 定 | 遥测（约定） |
| `goal_text` | features | root observation 的 `input` 原始串 | 遥测 |
| `query_lang` | features | 由 `goal_text` 语言检测 | 平台派生 |
| `embedding` | cluster,features | **平台侧可插拔编码器**（`contracts/schemas.md:46`："业务侧由可插拔编码器提供"） | 平台派生 |
| `user_feedback` | features | Score（`source=API/EVAL/ANNOTATION`）或 metadata | 遥测；⚠ `implicit_feedback`（`kernel/features.py:643`）**永久禁入** `METRICS` |
| `answer_numbers` | features | 从最终 output 抽取 | 平台派生 |
| `answer_citations` | features | 从最终 output 抽取 | 平台派生 |
| `answer_facts` | features | 从最终 output 抽取 | 平台派生 |
| `golden_facts` | features | **真值专属** —— 生产没有，除非租户用 Langfuse Dataset 挂 expected output | 真值 |
| `golden_answer` | **无消费者**（bench 算 `fact_precision_true` 用） | 真值专属 | 真值 |
| `contradicted_facts` | **无消费者** | 真值专属 | 真值 |
| `raw_flags` | **无消费者** | 真值专属（注入缺陷的记录） | 真值 |
| `ontology_id` | **无消费者**（且无校验，§3.4-c） | 生产 = L2 识别谓词命中的本体 id | 平台派生 |

**★ 必须写进接入文档的因果链**：`golden_facts` 缺失 ⟹ `fact_precision` = None ⟹
**O 维第二通道关闭** ⟹ `kernel/score.py` 的 confidence **×0.85**（若 `traceable_number_ratio`
也缺则再 ×0.90）。这正是基准里那 **38 条"盲区"**（36 in pool + 2 novelty，占 246 的 15.4%）
的同一个机制。**⟹ 生产分数系统性地比基准分数保守，这不是 bug，是"没有真值就不硬判"的设计。**
要让 O 维满血，租户必须挂 Dataset expected output，或至少埋 `output_facts` metadata。

### 4.3 六个无原生列的字段（决策 6 之外的第 6 项待确认）
`subgoal_text` · `arg_valid` · `output_citations` · `verifier` · `output_facts` · `finish_reason`
—— Langfuse **没有对应列**，只能走 metadata。其中 `arg_valid` 可由适配器现算（§3.4-b），
其余 5 个**不埋点就只能恒为 None**，`missing_field_ratio` 会如实把它们计成遥测损失
（可接受，但后果必须让租户知情）。
**待确认**：这个埋点要求能否强加给租户？（见 §7）

### 4.4 两个静默截断源
- SDK 老于 Python 4.7.0 / JS 5.4.0，或 OTel exporter 未发 `x-langfuse-ingestion-version: 4`
  → v2 端点上**最多延迟 15 分钟**才可见。
- **游标分页可能返回空页而 `meta.cursor` 仍在** → "页空就停"会静默截断整个 cohort。必须按 cursor 判停。
- 另：Legacy API **2026-11-16 下线**（距今 7 天）→ 第一天就必须只用
  `/v2/observations` + `/v3/scores` + `POST /api/public/scores`。
  自托管需 v4+ 才有 v2 observations；Scores v3 需自托管 v3.179.0+。
- 载荷：**单请求与单响应各 5 MB**。请求 `io` 字段组时 `limit=1000` 可能撑爆响应上限
  → limit 要按字段集调。

---

## 5. 1 project = 1 本体（决策 4/5 合并，2026-11-09 改定）

### 5.1 采纳的理由
用户提出：**一个 project 默认只承载一类 agent 的执行轨迹，一个 project 对应一个本体 YAML。**
project 内的噪声是业务方自己的行为，平台不清理；要分析另一类 agent 就另起一个 project。

我原先反对（为此设计了"范式扫描 + 自动分桶"两套机制），**实测后同意并删除了它们**（F5）。四条理由：
1. **实测支持**：`shared_cells = 0` 在 0 / 5 / 20 / 50% 四个污染档全部成立 ——
   多视图共识聚类**本来就完全隔离**结构互异的外来范式，合法轨迹的分数不受污染
   （`A.mean_S_normal` 91.05 → 90.99 / 91.48 / 91.47，`A.fpr_pool` ≤ 0.00057，`A.p_at_50 = 1.0`）。
2. **与 Langfuse 的原生粒度对齐**：`ScoreConfig`、标注队列、dashboard **全是 project 级**。
   1:1 之后它们天然就是"每本体一套"，不需要任何命名约定去区分。
3. **与决策 1.A 组成干净的两层**：**Organization = 租户**（限流 / 账务 / 审计），
   **Project = 本体**（分析边界）。管控析的管理域 / 控制域 / 分析域 = **1 个 Org + 3 个 project**，
   且 `POST /api/public/projects` 可程序化创建（F1），租户只需手工建一次 Org。
4. **删掉的是实打实的复杂度**：无本体的轻量分组器（新代码，且**不能**复用 `kernel/cluster.py`，
   因为 `kernel/ingest.py:71` 的归一化需要本体）· 异步扫描作业（Hobby 档光配额就 3.3 分钟）·
   name 撞车时的退化 · "扫描不能替代打标"的纠结。
   接入要求也随之降低：**`metadata.traj_ontology` 从硬性降为可选**（埋了则 §6 的度量更准、更便宜）。

### 5.2 边界规则（防止以后扯皮）
- **多种工作流 → 一个本体，多条 `required_steps`。** R1 实测 3 条 pattern，`ari_pattern = 0.9976`。
- **多种范式（动作词表不相交 / SLO 不同 / 单价不同）→ 多个 project。**
- **判据就是 `foreign_ratio`**（§6.1）：它 > 0，就说明这个 project 该拆了。

### 5.3 cohort 选择器（1:1 之后大幅简化）
**定义不变**：cohort = **一次分析要圈定的那批轨迹的「取数规则」**，不是数据本身；
选择器会被逐字翻译成 `GET /api/public/v2/observations` 的查询参数与 `filter` JSON 数组。
但 1:1 之后它**不再承担"识别本体"的职责**，只剩三件事：

```yaml
cohort:
  id: adn-control-prod-24h
  tenant: adn-mgmt              # L0
  project_id: clxxx             # L0；本体由 project 注册关系唯一确定，不再靠谓词猜
  ontology: adn-control@1.2.0   # 由 project 绑定推出，写入 Run 溯源
  selector:
    environment: [prod]         # 可选：正常的 prod/staging/dev 卫生，不是噪声圈定
  window: {from: "now-24h", to: "now"}   # 必填：官方要求总是带 fromStartTime/toStartTime
  sampling: {max_traces: 20000, seed: 20261109}
```

- **删掉的**：`metadata.traj_ontology` 谓词匹配、`exclude_name` 排除清单、多本体自动分桶、
  范式扫描向导。
- **保留 cohort 概念的四条理由不变**：① UI 上「发起聚类」必须先选一个；
  ② 一次 Run 的完整定义 = cohort + 版本四元组
  (`pipeline_version` / `code_hash` / `ontology@version` / `anchor_version`)，
  这是专利主张「相同输入位级一致」的可视化证据；③ 时间窗是 Langfuse 的硬要求；
  ④ cohort 决定 `n`，`n < COLD_START_MIN_TRACES = 1000`（`bench/regime.py:164`）触发冷启动闸门 ——
  R6（n=600）实测 pool **F1 = 0.000 但 AUC 0.917 / P@50 0.820** ⟹
  「冷启动能排序、不能卡阈值，且校准不可用」这句话必须挂在 cohort 上显示。

---

## 6. 准入自检：不清理噪声，但必须度量它、并把它隔离出告警流

这是 F5 之后**唯一保留**的噪声机制。它比被删掉的范式扫描小两个数量级：
不需要扫描作业、不需要额外 API 调用、不需要新聚类器、**不需要调任何阈值**。

### 6.1 判据 `foreign_ratio`（零阈值，实测完美分离）
```
foreign_ratio(trace) = |{非 root span : action 不在 V}| / |非 root span|
V = L2 自动收集的观测 name 词表（接入预检 §1.2 第 2 项那一趟扫描） ∪ forbidden_actions
```
- **★2026-11-10 修正词表来源**：原式写的是 `actions ∪ forbidden_actions`，
  但 `actions` 已从租户 YAML **删除**（§3.2），且它本来就是**假阳性读取点** ——
  照原式实现会依赖一个不存在的声明字段。改用 **L2 观测词表 `V`**：
  由预检对 `name` 的 top-K 扫描直接产出，**不需要业务方填任何东西**，
  与「按上报的 trace 规矩聚类」的原则一致。
  **语义变化（必须记）**：`V` 从**本 project 自己的流量**学，所以 `foreign_ratio`
  度量的是「这条轨迹像不像本 project 的常态」，而不是「像不像本体声明」——
  这恰好是 **1 project = 1 本体** 决策想要的语义。
  **★新发现的耦合**：`V` 会随业务演进漂移 ⟹ **每次 R2 之后必须重算 `V`**，
  否则业务的新范式会被判成「外来」。这与 §3.2-a 的 cell 身份不稳定是同一类问题，
  应与 lineage 重算同批执行（`LIFECYCLE.md` §3.2）。
- **★必须排除 root action**：实测 `agent_run` 是 ontA 与 ontB **共有**的 root action。
  所以"声明词表交集为空"这个判据**对观测词表不成立** —— 朴素的"词表交集"测试会返回
  **0 分离度**。这修正了我上一轮的说法（声明词表 ∩ = ∅ 为真，观测词表 ∩ = `{agent_run}`）。
- **实测分离度：A = 0.0，B = 1.0，四个污染档全部如此，零重叠** ⟹ ROC = 1.0，
  **阈值恒为 0，无需调参，不新增任何白名单常数**（`adapt/playbook.md` §2.1 不必扩）。
- **成本近零**：只用已经在手里的 span 数据，约 10 行；参考实现见 `platform/mixexp.py` 的
  `foreign_ratio()`。

### 6.2 为什么必须隔离出告警流（F5 实测全表）

| 指标 | ctrl 0% | 5% | 20% | 50% |
|---|---|---|---|---|
| `shared_cells (A cells 交 B cells)` | 0 | 0 | 0 | 0 |
| `n_cells / A / B` | 8 / 8 / 0 | 7 / 6 / 1 | 4 / 2 / 2 | 5 / 2 / 3 |
| `drift_detected` | False | False | False | False |
| `A mean_S_normal` | 91.05185 | 90.98706 | 91.47617 | 91.46666 |
| `A fpr_pool` | 0.00027 | 0.00057 | 0.00034 | 0.00054 |
| `A recall_pool` | 0.77152 | 0.77972 | 0.73663 | 0.77857 |
| `A f1_pool` | 0.88931 | 0.88142 | 0.84634 | 0.872 |
| `A auc_pool` | 0.96786 | 0.96632 | 0.9207 | 0.9377 |
| `A p_at_50` | 1.0 | 1.0 | 1.0 | 1.0 |
| `B alert_rate` | - | 0.995 | 0.9575 | 0.951 |
| `B fire_unfulfilled` | - | 1.0 | 1.0 | 1.0 |
| `B fire_hard` | - | 1.0 | 1.0 | 1.0 |
| `B fpr_pool` | - | 1.0 | 1.0 | 1.0 |
| `B foreign_ratio_gt0` | - | 1.0 | 1.0 | 1.0 |
| `A foreign_ratio_gt0` | 0.0 | 0.0 | 0.0 | 0.0 |
| `overall fpr_pool` | 0.00027 | 0.05123 | 0.19113 | 0.48374 |
| `overall f1_pool` | 0.88931 | 0.65738 | 0.39428 | 0.23499 |
| `overall alert_rate` | 0.0585 | 0.106 | 0.2365 | 0.503 |
| `overall p_at_50` | 1.0 | 0.62 | 0.52 | 0.7 |
| `overall auc_pool` | 0.96786 | 0.94572 | 0.86558 | 0.82096 |
| `topk(15) precision` | 1.0 | 0.6 | 1.0 | 1.0 |
| `topk(15) A share` | 1.0 | 0.5333 | 1.0 | 0.9333 |
| `wall_s` | 122.0 | 105.1 | 96.6 | 93.4 |

读法：`A` = 合法轨迹（ontA，即该 project 注册的本体），`B` = 外来范式轨迹（ontB）。
`topk(15)` = 按 `a_raw` 排序的前 15 条，即值班运营流（`ALERT_BUDGET_PER_DAY = 5` × 3 天）。

- **打分侧安全**：`shared_cells = 0` 四档全成立；`A.mean_S_normal` 91.05 → 90.99 / 91.48 / 91.47；
  `A.fpr_pool` ≤ 0.00057；`A.p_at_50 = 1.0` 四档不变。**⟹ 「不清理噪声」对打分是可接受的。**
- **告警侧崩塌**：overall `fpr_pool` 0.00027 → **0.48374**，`f1_pool` 0.889 → **0.235**，
  `alert_rate` 0.0585 → **0.503**。B 档 `fire_unfulfilled = fire_hard = 1.0`、
  `alert_rate = 0.951~0.995`。**⟹ 「不清理噪声」对告警是不可接受的。**
- **最危险的点是轻污染**：5% 档 `topk(15) precision = 0.6`，**跌破 0.80 门禁**；
  20% / 50% 档反而恢复到 1.0。机制见 F5 结论 3。

### 6.2.1 ★两个失效模式是**脱钩**的（表里最容易被误读的一点）

- `alert` 由**硬规则**驱动（`kernel/detect.py:631`），外来轨迹**恒为真**，与污染比例无关。
- `a_raw` 的**排序**由**严重度分档 + 档内簇内排名**两级驱动（`kernel/detect.py:643-647`），
  外来轨迹在重污染下会**自己降下来**。
- 所以 `fpr_pool`（告警总量）与 `topk(15) precision`（值班实际看到的）
  **随污染比例非单调、且峰值错位**：

| 污染 | `fpr_pool`（总量层面） | `topk(15) precision`（运营流层面） | 谁先崩 |
|---|---|---|---|
| 0% | 0.00027 | 1.0 | — |
| 5% | 0.051（189×） | **0.60（跌破 0.80 门禁）** | **运营流先崩** |
| 20% | 0.191（707×） | 1.0 | 总量崩、运营流仍干净 |
| 50% | 0.484（1793×） | 1.0 | 同上，更严重 |

- **⟹ 只盯一个指标会得出错误结论**：只盯 `topk` 会以为"20% / 50% 污染没事"；
  只盯 `fpr_pool` 会以为"5% 是四档里最轻的、可以先不管"。**两个都错。**
- **★2026-11-10 机制纠正（我上一版给的解释被实测证伪，原文保留在下方）**
  **真正起决定作用的是严重度分档，不是簇内标准差。** `kernel/detect.py:96`
  `TIER_BANDS = {0:(0.00,0.40), 1:(0.40,0.75), 2:(0.75,1.00)}`，`:643`
  `tier = 2 if alert_rule else (1 if alert_stat else 0)`，`:647` `a_raw = lo + (hi-lo)*graded`。
  **tier 2 的下界 0.75 就是 tier 1 的上界** ⟹ 任何一条触发了硬规则的非 novelty 轨迹，
  **永远排在所有统计检出的异常之前**，与它自己有多异常、簇有多小都无关。
  外来轨迹 `unfulfilled → hard → alert_rule → tier 2`，而合法轨迹的统计异常只有 tier 1。
  实测（`platform/tierexp.py`，与 mixexp 同一 harness）：
  | 档 | `a_raw` 最小的 tier-2 外来轨迹 | `a_raw` 最大的 tier-1 轨迹 | 外来轨迹落在 tier 1 的数量 |
  |---|---|---|---|
  | 5% | **0.81003** | 0.72777 | **0** |
  | 20% | **0.80830** | 0.69434 | **0** |
  ⟹ 外来轨迹是「**全有或全无**」地进 tier 2，这就是它们霸榜的**充分**原因。
- **★被证伪的原解释（记录在案，不要再引用）**：我曾说「轻污染时外来轨迹挤成 1 个紧致簇、
  簇内标准差极小 → 偏离被放大成极端 z 分」。三点全错：
  ① 那个簇**不小**——实测 5% 档 B 有 **n=199** 条在同一个 cell `i2xp2`；
  ② `graded` 是**簇内排名**（`detect.py:636` 的 `_rank_norm`），**根本没有标准差参与**；
  ③ 该 cell 的 `credibility(199) = 0.8690` → level **L3**，是**完全可信**档，没有被降级。
- **★顺带证伪一个常见误解（用户提出的，实测回答）**：novelty 缓冲区**不会**接住这类噪声。
  `kernel/cluster.py:862` 的判据是
  `nov = singleton(ci) or singleton(cp) or cons_i<0.35 or cons_p<0.35 or geo<=geo_cut` ——
  它量的是**跨 8 次 bagging 重采样的可复现性（稳定性）**，**不是样本量**。
  200 条同质外来轨迹恰恰是**最可复现**的：实测 `novelty_rate` 仅 **0.005**（200 条里只有 1 条），
  `consensus_intent` **中位数 0.9565**（阈值 0.35）。
  **⟹ 「样本量不足就不成簇、转低置信人工复核」这个闸门不存在。**
  确实存在的样本量机制是 `credibility(n)=n/(n+KAPPA)`（`kernel/baseline.py:175`），
  但它只决定**锚点池的混合层级 L3/L2/L1**（借多少父层统计），
  **既不否决 cell 成立，也不把任何轨迹送人工复核**。
- **非单调性的机制：只确定了一半，剩下一半是公开未解问题。**
  实测 top-15 明细：5% 档 A 占 8 席（`graded` 0.9362→0.9065）、B 占 7 席（0.8767→0.8091）；
  20% 档 **A 占满 15 席**（`graded` 0.9733→0.8673），B 的最高 `graded` 已低于 A 的第 15 名。
  所以翻转是由 **A 自己的 `graded` 分布上移**造成的，不是 B 自己塌下去：
  A 的 cell 数从 5% 档的 **6 个**（488/2021/151/589/485/31）塌缩到 20% 档的 **2 个**（930/2268）。
  **★为什么污染变重反而让 A 的意图簇从 6 塌到 2，我没有解释，需要单独实验**（`LIFECYCLE.md` §4.3）。
  在查清之前，**不要**把「重污染更安全」当成可依赖的性质来设计任何东西。
- **这就是 §6.3 要在进告警流之前摘掉 `foreign_ratio > 0` 的原因**：不是为了分数好看
  （分数本来就没事，见 F5 结论 1），是为了**保住值班那 5 个位置**。

### 6.2.2 ★删掉 `required_steps` 本身就能消掉这场告警风暴（实测，`platform/tierexp.py`）
上面 §6.2.1 的全部损害都源自 `unfulfilled`，而 `kernel/detect.py:279-280` 是
`declared_all = ontology.get("required_steps") or {}` / `unfulfilled = bool(declared_all) and ...`。
**键不存在 ⟹ `bool({})` 为假 ⟹ `unfulfilled` 对所有轨迹（含外来）恒为假 ⟹ tier 2 不再被霸占。**
这正是 `LIFECYCLE.md` §2.5 的 Tier-1 最小本体。实测（先由读码预言，后测量确认）：

| 指标 | 5% 声明版 | 5% **删除版** | 20% 声明版 | 20% **删除版** |
|---|---|---|---|---|
| 外来轨迹落 tier 2 | **199 / 200** | **6 / 200** | **766 / 800** | **31 / 800** |
| 外来轨迹 `alert_rate` | 0.995 | **0.030** | 0.9575 | **0.065** |
| overall `alert_rate` | 0.106 | **0.0512** | 0.2365 | **0.0530** |
| overall `fpr_pool` | 0.0512 | **0.00054** | 0.19113 | **0.00597**（32×） |
| `topk(15)` precision | **0.60** | **1.00** | 1.00 | 1.00 |
| A 侧 `f1_pool` | 0.88142 | **0.80745** | 0.84634 | **0.74300** |
| `n_pattern_clusters` | 4 | 4 | 4 | **10** |
| `novelty_rate` | 0.009 | 0.009 | 0.009 | **0.04625** |

- **收益**：0.80 门禁的破口消失（0.60 → 1.00），20% 档 overall `fpr` 降 32 倍。
- **代价**：A 侧 `f1_pool` −0.074（5%）/ −0.103（20%）。**这个代价不是污染造成的**：
  声明版下污染本身只让 A 的 f1 从 0.88931 掉到 0.88142（−0.008）。
  ⟹ 它是「**放弃 `unfulfilled` 通道**」的通用价格，**project 干不干净都要付**。
- **⟹ 结论：§6.3 的 `foreign_ratio` 摘除仍然是必需的**，不能靠删字段替代 ——
  删字段是**花 0.074 F1 买保险**，摘除是**零成本**。两者解决的是同一个问题的不同侧面：
  删字段防的是「业务把 `required_steps` 填漏」，摘除防的是「外来范式混进 project」。
- **★20% 档的 `n_pattern_clusters` 4 → 10、`novelty_rate` 0.009 → 0.046（5 倍）
  是 `kernel/cluster.py:48-54` 那条「cap 是 binding constraint」警告的实测确认**：
  `n_declared_patterns=0` → `cluster.py:794` `n_dec = 0 or 8 = 8` → `kmax_pat = 8`。
  这正是 `pattern_count` 字段（`LIFECYCLE.md` §2.4）要堵的洞。
  **注意 5% 档没有碎裂（4 → 4）** ⟹ 与 `LIFECYCLE.md` §2.4 的修正结论一致：**代价只在脏流量上显现。**

### 6.3 处置（三条，都不需要业务方配合）
1. **照旧打分、照旧可见、不隐藏** —— 但**不进入告警流**，单独成一类发现：
   **不是「异常」，是「走错门」（misrouted traffic）**。
   理由：它们不是已注册 agent 的质量问题；以 ~255 条/天的量级告警，
   会摧毁决策 7 的审计场景所依赖的那个通道。
2. **作为接入线索上报**：「本 project 有 X% 轨迹属于未注册范式 —— 拆一个 project，
   还是注册第二个本体？」这是多租户平台的自然增长入口，且**由实测数字驱动**，不是拍脑袋提示。
3. **不设污染阈值、不做红绿灯**：既然分离器在 0 处完美分离，
   直接排除 `foreign_ratio > 0` **严格优于**任何阈值方案。Run 头部只显示 X% 这个数字。

### 6.4 前端影响
- **删掉**：范式扫描向导、多本体自动分桶 UI、cohort 里的手写 exclude 条件。
- **新增（很小）**：Run 头部一个「未注册范式 X%」计数 + 一个「走错门」发现类别的列表页
  （与告警工作台并列，不混在一起）。
- **不变**：M0 cohort 圈定、M1 本体注册（现在是 project ↔ 本体 1:1 的绑定页）、
  M3 聚类结果、M4 告警工作台、M5 单轨迹下钻、M6 校准回流、M8 门槛自检。

---

## 7. ★聚类算法：方法论文档与已交付内核的分歧记录（答辩必问）

**分歧是真实存在的，而且此前 `platform/` 四份文档里一个字都没记。本节补上。**
触发：用户提问「为什么需要业务确认 `pattern_count`，我们用 HDBSCAN 相较于 k-means、GMM
的优点不就是不需要预设簇数吗」——**这个前提对方法论文档是对的，对已交付内核是错的。**

### 7.1 文档说什么 vs 内核做什么

| | 《方法论设计》文档 | 已交付内核（`kernel/cluster.py`） |
|---|---|---|
| 意图视图降维 | §5.2.3：**UMAP 降到 5-15 维**（原文第 726 行：「直接在 1024 维余弦空间上跑 HDBSCAN 效果差（维度灾难 + 密度定义失真）」） | **无降维**，直接在原始句向量上算欧氏距离 |
| 意图视图聚类 | §5.2.4：**HDBSCAN**，并给了「选 HDBSCAN 而非 K-Means / GMM 的理由」对照表（第 742-748 行：需预设簇数 是/是/**否**） | **k-means++ 播种的 Lloyd 算法**（`cluster.py:217`），k 在 `range(2, kmax+1)` 上扫描（`:762`），由 k-neutral silhouette 选 |
| 执行视图聚类 | §5.2.5 路线 A：n-gram TF-IDF + **层次聚类** | **average-linkage UPGMA**（`cluster.py:511`）—— **与文档一致** |
| 融合 | §5.4：**共识聚类**（co-association 矩阵 → 再聚类） | **一致**（`cluster.py:772 _consensus`），8 次 bagged run |
| 噪声 / 弃权 | HDBSCAN 原生 `label=-1` | novelty 缓冲区（`cluster.py:862`），判据是**共识边际**，不是密度 |

**根本原因是硬约束**：内核是**纯 stdlib Python** —— 全部 import 只有
`math` `random` `json` `re` `bisect`（实测 `rg "^(import|from) " kernel`），
装不了 `hdbscan` / `umap-learn` / `sklearn` / `numpy`。**UMAP 与 HDBSCAN 都不可用。**

**这个分歧早就被登记过，但只记在一个不起眼的地方**：`bench/contract.py:59-63` 把它列为
**SUBSTITUTION** —— 文档契约里的 `cluster_strength`（HDBSCAN 的成员强度）
「has no analogue in a consensus-partition clustering」，改用 bagged co-association 边际替代。

**辩护要点**：文档自己在 §5.4（第 893 行）就论证了**承重的是共识层，不是 base learner**：
「T4 拿不到多数票就单独成簇…**这就是"证据不足就不合并"的保守策略，也是它比单次 HDBSCAN
稳健的根本原因**」。⟹ base learner 换成 k-means + UPGMA 之后，共识层的语义
（`cons = (a-b)/max(a,b)`、票数下限、弃权缓冲区）**一字未改**。

### 7.2 ★「不需要预设簇数」这个优点我们保留了 —— `pattern_count` 不是 k

**`pattern_count` 喂的是 k 的上限，不是 k 本身。**

- 意图视图：k 在 `range(2, kmax+1)` 上**逐个试**，用 k-neutral silhouette 选（`cluster.py:762-766`）。
- 执行视图：切高在 `HEIGHT_GRID`（0.05~0.85 共 17 档）上**逐个试**，同一个统计量选
  （`select_cut_height`，`cluster.py:440`）。
- 最终模型阶次 = **8 次 bagged run 的 k 中位数**，共识树在**恰好实现该 k** 的高度上切。
  `cluster.py:13-15` docstring 原文：「the model order is the **median k over the runs** …
  so `consensus_threshold` does **NOT** decide how many task classes exist」。

`pattern_count` 只出现在**一个地方**：

```python
n_dec    = n_declared_patterns or K_MAX_PATTERN_ABS                        # cluster.py:794
kmax_pat = max(2, min(K_MAX_PATTERN_ABS, n_dec + K_MAX_PATTERN_HEADROOM))   # :795, headroom = 2
```

⟹ 它是**单边正则**：「最多找 n+2 种模式」。数据里真的更少，silhouette 自然会选更少。

### 7.3 ★那为什么这个上限需要业务先验？因为 cap 是 binding constraint（代码原文 + 实测）

`cluster.py:48-54` 的注释是**这个字段存在的全部理由**：
> 「the cut-selection statistic is **monotone toward finer partitions** once its k-bias is removed
> (see `silhouette_dm`), which **makes the cap the binding constraint** — leaving it at a loose
> global 8 let the heavily corrupted and foreign-ontology regimes **shatter 3 declared workflows
> into 9-12 clusters**.」

**实测确认**（`platform/tierexp.py`，20% 污染档，`n_declared_patterns=0` → cap 落到 8）：
`n_pattern_clusters` **4 → 10**、`novelty_rate` **0.009 → 0.046（5 倍）**。
**而 5% 档没有碎裂（4 → 4）** ⟹ **代价只在脏流量上显现**；干净流量上这个字段确实可有可无。

### 7.4 ★为什么是「业务确认」而不是「业务填写」：失败方向不对称

`cluster.py:468-472` 的注释给出了判据：
> 「Residual ties break toward the **finer** cut: **over-splitting a workflow is cheap**, because a
> small cell is shrunk toward its intent and global levels by the credibility weight and its
> baseline stays sound; **under-splitting is not recoverable anywhere downstream**, since a cell
> that silently mixes two workflows has a **bimodal conditional distribution** — precisely the
> failure this design exists to avoid.」

| 业务答错的方向 | 后果 | 可恢复吗 |
|---|---|---|
| **答多了**（cap 偏高） | 过切分 → 小 cell 被 credibility 权重往意图层 / 全局层收缩 | **便宜**，基线仍然可靠 |
| **答少了**（cap 偏低） | 欠切分 → 一个 cell 静默混两种工作流 → **条件基线双峰** | **不可恢复**，下游任何地方都救不回来 |

⟹ 风险集中在「答少」这一侧，所以不能让业务方对着空白框猜。
流程是：**平台先跑一次探索性聚类给出候选**（「你的 agent 看起来有 3~5 种执行模式，对吗？」），
业务只需**点头或往上纠正**。这也解释了为什么它**发生在首跑之后**，不是接入时填的空。

**另一个理由**：业务方**答不出**「会走哪几步」（那是已删除的 `required_steps` ——
漏一条合法路径 = 走那条路的所有轨迹无条件告警，实测告警率 0.995），
但**答得出**「大概几种做法」。前者是路径枚举（组合爆炸、极易漏），后者是粗粒度计数（稳健）。

### 7.5 ★诚实缺口，以及一个由此暴露的生产风险（本轮新发现）

**(a) 我们从未在自家数据上跑过 HDBSCAN 对照基准。**
`bench/contract.py` 只登记了「概念替换」，**没有**登记「性能对比」。
答辩被问「为什么不用 HDBSCAN」时，诚实的回答是**「纯 stdlib 依赖约束 + 共识层才是承重结构」**，
**不是**「我们测过 HDBSCAN 更差」。

**(b) ★更严重：基准数据集的几何被主动调平过，因此它测不出意图视图在生产上的主要风险。**
`bench/generate.py:117-129` 记录了 v3.0.0 的实测：

| 几何 | `ari_iso`（各向同性 oracle） | `ari_wht`（**白化** oracle） | `ari_km`（**一次朴素 k-means**） |
|---|---|---|---|
| v3.0.0，2 意图，overlap 0.88 | 0.4574 | **0.9967** | **0.0974** |
| v3.0.0，4 意图，overlap 0.30 | 1.0000 | 1.0000 | 0.6970 |

机制写在 `generate.py:121-127`：各维尺度对比 22 倍 ⟹ **参与率 `PR = (Σs²)² / Σs⁴` 只有
23~32 维（共 384 维）** ⟹ 原文「unwhitened k-means was solving a **~30-dim problem wearing a
384-dim costume**」。**信息全在（白化 oracle 0.9967），但未白化的欧氏距离读不到（k-means 0.0974）。**

**当时的处置是把数据集调到 k-means 能读的几何**（`generate.py:147`：AMP 10.0 / 对比 3.5 倍 /
PR ~106-140），而**不是**给内核加白化。这个选择本身站得住，理由写在 `generate.py:62-66`：
`sigma_e` 驱动的难度是「无监督视图结构上读不到的那种难度」，所以难度改由 `intent_ambiguity` 注入，
让 oracle 与 k-means **一起**下降，天花板才是诚实的界。

**但副作用是**：shipped 基准上 `ari_km == ari_iso == 1.0000`，
**白化的收益在当前数据集上恒等于 0** ⟹「要不要加白化」这个问题**在现有基准上无法验证**。

**生产上的真实风险**：真实句向量（384 / 1024 维）的**各维尺度对比是未知的**，
完全可能落在 v3.0.0 那种 `PR ≈ 30` 的几何上。那时意图视图会**静默退化**到 ARI 0.0974 量级，
而**表面上看不出问题**：聚类照样出簇、`novelty_rate` 也不报警 ——
因为它退化的是**划分质量**，不是**稳定性**。而 consensus 层只看稳定性。

**候选缓解（都还没做，M0 未批不动手）**：
1. **给意图视图加白化**：按维 pooled 标准差归一化后再算欧氏距离。**纯 stdlib 可实现**，
   而且 `cluster.py:611 pooled_var()` **已经在算逐维 pooled 方差**了 —— 机器已有一半。
   代价：改内核 ⟹ `code_hash` 变 ⟹ 8 份 `SAMPLE.md` 必须重生成。
2. **新增一个「敌对几何」regime**（**不替换**现有 8 档）：高对比度、`PR ≈ 30`，
   期望未白化 k-means 失败、白化后恢复。**这是唯一能验证缓解 1 的办法**，
   属于 `bench-gen-v4` 级别的数据集改动。
3. **★M2 真实数据接入后立刻量一次 PR**：一行诊断代码，在真实 embedding 上算 `(Σs²)² / Σs⁴`。
   **若 `PR ≪` 维度数，缓解 1 从「可选」变成「必须」。**
   **这是三条里最便宜的，且不依赖任何待决决策 —— 建议排为 M2 的第一件事。**


## 8. 待决清单

| # | 议题 | 状态 | 备注 |
|---|---|---|---|
| A | ~~cohort 选择器概念~~ | **已定稿** | 1:1 之后简化，见 §5.3 |
| B | ~~范式扫描~~ | **已删除** | 被 §6 的零阈值准入自检取代，F5 实测支持 |
| C | 凭据放 L0 而非本体 YAML | **待用户点头** | 理由是版本学（§3.3）；明文本身遵从决策 2 |
| C2 | §6.3 把 `foreign_ratio > 0` 的轨迹排除出告警流 | **待用户点头** | F5 实测：不排除则 5% 污染即跌破 0.80 运营流门禁 |
| D | 6 个 metadata 字段的埋点要求能否强加给租户 | 待确认 | §4.3 |
| E | 5 类 `kind` 与 10 类 observation `type` 的映射 | 待确认 | §4.1；SPAN/CHAIN/EVENT 需 name 规则 |
| F | org-scoped key 在 UI 何处铸造、Cloud 各档是否都开放 `POST /projects` | **待实测** | F1 的唯一未验证点 |
| G | 前端模块清单在多租户下重排 | 待做 | 原清单产出于前提修正前，缺租户层；§6.4 已给出增删 |
| G2 | 近邻范式（同 agent 换几个工具）在混流量下的行为 | **未测** | F5 只覆盖结构互异范式；唯一值得补 regime 的点 |
| H | REST 接口清单 | **阻塞中** | 形状由 §4 映射表决定，顺序不可颠倒 |
| I | `ontology_id` 一致性断言 + 补成第 23 条不变量 | 待做 | §3.4-c；改 `bench/invariants.py` 不在 hash 闭包内，可随时做 |
| J | 适配器必须处理的四个陷阱 | 待做 | `fields` 字段组 · `isRootObservation` · 两处静默截断 · Legacy API 11-16 下线 |
| K | ~~部署形态~~ | **已定稿（2026-11-11，两次）** | 一套部署只对接一个 Langfuse 实例 ⟹ `base_url`/`profile` 部署级、接入流程 9 步→8 步、注册表单无 profile 选项。**第二次简化**：profile 由**启动参数 `--profile`** 选定，`platform.yaml` 删除，运行时只做**一次 `health` 版本核对**（不做逐端点探测、不做周期重探）。见 `MODULES.md` §1.2.1 / §1.5 |
| K2 | ~~「capabilities 填错会静默算错」~~ | **已证伪（2026-11-11）** | 逐个开关推演：能力错配一律表现为 **404**（响亮），不是静默。真正的静默失效来自 `field_groups` / `expandMetadata` / `usage_key_map`，归 **B1 适配度预检**。推演表见 `MODULES.md` §1.5 |
| M | 意图视图**未白化** k-means 在真实 embedding 几何上的退化风险 | **★新发现，未处置** | §7.5(b)。基准几何被调平过（`ari_km == ari_iso == 1.0000`）⟹ **现有 8 档测不出这个风险**。最便宜的一步：M2 接真实数据后立刻量一次 `PR = (Σs²)²/Σs⁴` |
| N | 是否给意图视图加**逐维白化** | **待 M 的实测结果** | §7.5 缓解 1。`cluster.py:611 pooled_var()` 已在算逐维 pooled 方差，纯 stdlib 可实现；代价是 `code_hash` 变 + 8 份 `SAMPLE.md` 重生成。**在新增「敌对几何」regime 之前无法验证收益** |
| O | 方法论文档声明 HDBSCAN + UMAP，内核实为 k-means + UPGMA | **已记录（§7.1），文档不改** | 方法论设计文档属**冻结交付物**不得修改；分歧已由 `bench/contract.py:59` 登记为 SUBSTITUTION。**答辩口径见 §7.1「辩护要点」** |
| L | v1 映射器在 v4 开发环境里**不可达** ⟹ 只能靠 fixture 验证 | **强制** | §1.2.1 的部署级前提使「另一个映射器是死代码」；fixture 是唯一验证手段，硬截止 11-16 |

**可立即开工、不需要任何用户决策、也不需要 Langfuse key 的第一块代码**：
`TraceSource` 抽象 + `JsonlTraceSource`（读 `data/bench_v1/*/traces.jsonl`），
把基准注册为平台内部租户，让它走与生产完全相同的代码路径；
同时把 §6.1 的 `foreign_ratio()` 落成 `kernel` 之外的准入自检（参考实现已在
`platform/mixexp.py`）。

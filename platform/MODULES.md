# 平台黑盒模块设计（前后端）+ Langfuse 端点配置化方案

> 状态：**黑盒设计稿**。只定义职责 / 输入 / 输出 / 约束，不涉及实现选型。
> 前提沿用 `platform/DESIGN.md`：Organization = 租户，Project = 本体（1:1），
> Tier 0 零声明接入 / Tier 1 加 `forbidden_actions`（**字段清单以 `LIFECYCLE.md` §2.5 为准**）。
> 本文所有 Langfuse 事实取自 `_tmp_lfdocs/`（含 `openapi_api.yml` 120 条路径），2026-11-09/10 抓取。

---

## 1. Langfuse 依赖配置化：URL 提取是对的，但**只提 URL 不够**

### 1.1 为什么不够
Cloud v4 与自托管 v3 的差异**不止路径**，有五类，其中三类配置文件表达不了：

| 差异 | 纯 URL 配置能否表达 | 说明 |
|---|---|---|
| base_url / 区域 / 路径 | ✅ 能 | `cloud.langfuse.com` vs `us.` vs `jp.` vs `hipaa.` vs 自托管域名 |
| **响应 schema** | ❌ **不能** | `/v2/observations` 返回 **原始字符串** I/O + 字段组语义（未请求=**缺席**不是 null）；`/observations`(v1) 返回**已解析 JSON**、无字段组 |
| **能力有无** | ❌ **不能** | v2 observations 需自托管 **v4+**；`/v3/scores` 需自托管 **v3.179.0+**；标注队列 API 在自托管 v3 上**待实测** |
| **开通 API 完全不同** | ❌ **不能** | Cloud：`POST /api/public/projects`（org-scoped key）；自托管：`POST /api/admin/organizations`（需 `ADMIN_API_KEY`，Bearer 鉴权） |
| **限流行为** | ❌ **不能** | Cloud 按 **Organization** 分桶（General API：Hobby 30 / Core 100 / Pro+ 1000 req/min）；**自托管不强制限流** → 照搬节流只会白白增加延迟 |

### 1.2 方案：**两层配置**（都是配置文件，都不是代码）
- **第 1 层 `endpoints.yaml`** —— 你要的那个文件。`base_url` + `api_prefix` + **全部路径模板** +
  每路径的请求旋钮。代码里**不允许出现字面量 URL**。
- **第 2 层 `profiles/<name>.yaml`** —— 一个 profile = 一组 **capabilities 开关** + **throttle 数值** +
  指向哪个 endpoints 文件。三档出厂：`cloud-v4` / `selfhosted-v3` / `selfhosted-v4`。
  **迁移 = 改一个 profile 名，不改代码。**

`capabilities` 决定**走哪条代码路径**，`endpoints` 决定**打到哪个 URL**。二者缺一不可。

### 1.3 必须承认的代价
`observations_api: v2 | v1` 意味着**必须存在两个 Observation 映射器**（v2 原始串 + 字段组 vs
v1 已解析 JSON + 无字段组）。这是"兼容两种部署形态"的**真实成本**，配置得再好也省不掉。
但它是有界的：一个 `ObservationMapper` 接口、两个实现、由 capability 开关选择。

### 1.4 ★一个时间敏感的行动项（今天 2026-11-10，硬截止 11-16，**M0 的强制入口条件**）
**官方原文（`_tmp_lfdocs/`，2026-11-10 抓取）**：
- `public-api.md:117-118`：「Observations API v2 and Metrics API v2 are available on Langfuse Cloud
  and self-hosted Langfuse **v4**. On self-hosted Langfuse **v3**, use the `api.legacy.*` …」
- `public-api.md:280`：「On self-hosted Langfuse **v3**, use the **v1 Observations API**
  (`GET /api/public/observations`) instead」
- `deprecated-api-migration.md:643`：「Langfuse **Cloud** serves these endpoints until
  **November 16, 2026**; migrate to v4 before this date.」
- `deprecated-api-migration.md:331`：「**On Langfuse v4, these will return `404`.**」

**⟹ 两个必须分清的结论：**
1. **11-16 只影响 Cloud，与自托管 v3 的可用性无关。** 自托管 v3 **继续**提供 legacy 端点。
   所以这个日期威胁的**不是「能不能支持 v3」**，而是「**能不能拿到 v1 的真实响应用于验证
   v3 适配器**」——11-16 之后 Cloud 返回 404，而我们手上没有自托管 v3 实例。
2. **v3 适配器 = legacy v1 映射器，二者是同一个东西，不是可选项。**
   「不适配 v1」与「支持自托管 v3」互相矛盾。范围已定案为 **v3 + v4 都支持**
   （`ROADMAP.md` §5.1），所以这个映射器**必须写**。

**行动**：在 11-16 之前用 Cloud 把 `GET /api/public/observations`(v1)、`GET /api/public/traces`、
`GET /api/public/scores`(v1) 的**真实响应抓成 fixture 存进仓库**（约半天），
之后 v3 映射器对着 fixture 做契约测试。
**不做的话，v3 适配器会是整条链路上唯一无法在开发期验证的代码路径，而生产环境恰恰就是自托管 v3。**

### 1.5 ★注册时的「能力探测」：三层，缺一层就会静默走错代码路径

**能力探测回答的是「这个 Langfuse 实例能提供哪些 API」**，与「适配度预检」
（问「你的埋点数据质量够不够我们的算法用」）是相邻但完全不同的两道闸，对照见 §1.6。

**为什么必须有它**：§1.2 的两层配置里，`profiles/*.yaml` 的 `capabilities` 开关**决定走哪条代码路径**
（`observations_api: v2 | v1` 选哪个 Observation 映射器），`endpoints.yaml` 只决定打哪个 URL。
capabilities 填错 → 代码**静默**走错分支 → 字段大面积缺席但 HTTP 全 200，
下游表现是 `missing_field_ratio` 接近 1.0（触发 `score.py` 的 `mfr > 0.20` 降级，
**置信度维退化成常数**），全程不报错。
所以 capabilities **不能靠人在注册表单里勾选**，必须由平台实测。

**三层探测（自上而下，后一层校核前一层）：**

| 层 | 做什么 | 数据来源 | 产出 |
|---|---|---|---|
| **L1 声明** | 注册表单里由人选一个 profile | 人 | `cloud-v4` / `selfhosted-v4` / `selfhosted-v3` |
| **L2 推断** | 读服务端**自报的精确版本号**，查「版本→能力表」 | `GET /api/public/health` | 期望的 capabilities 集合 |
| **L3 实证** | 对关键端点各打一次最小请求，看 HTTP 状态码 | 实例本身 | 实测的 capabilities 集合 |

**★L2 是本轮新增的关键发现**（`_tmp_lfdocs/openapi_api.yml:12611`-`:12622`，Cloud 自述 spec 原文）：

```yaml
HealthResponse:
  properties:
    version: {type: string, description: Langfuse server version}
    status:  {type: string}
  required: [version, status]
```

`version` 与 `status` **都是 required** ⟹ 一次 `health` 调用就拿到**精确版本号**，不是靠试探猜大版本。
这把 L3 从「逐端点试错」降级为**校核**：能力主要由 `version` 查表**确定性推导**，
L3 只负责验证推导结果，并把「版本→能力表」尚未覆盖的新版本**暴露出来**而不是猜。
两个附带利好：
- `health` 在不健康时返回 **503**（`openapi_api.yml:2470`）⟹ 它同时充当连通性 + 依赖（数据库）健康探针。
- **它是全套 API 里唯一免鉴权的端点**：实测统计 Cloud 自述 spec 的 **120 个 operation 中，
  只有 `health_health` 一个没有 `security` 块**（其余 118 个是 `security: *ref_0`）。
  ⟹ 探测可以在**拿到 key 之前**就先验一次「这个地址活着吗、是什么版本」，
  注册表单能在用户填凭据前就把 profile 下拉框预填对。
  （注意 spec 仍为它声明了 401/403，疑为生成器样板；实现上按「先无凭据试，401 则带 Basic Auth 重试」处理。）

**L3 有两种精度**（`public-api.md:23` 原文）：「Self-hosted: every instance running Langfuse
**v4.36.0 or later** serves its own spec at `/api/openapi.yaml` and an interactive reference at
`/api/docs`」（`openapi_api.yml:39`-`:40` 同样记载）：
- **v4.36.0+**：拉取实例**自述的 spec**，与 profile **逐端点对账** →
  差异清单精确到端点与字段，而不是一个笼统的「profile 不匹配」。
- **v3 与 v4.36.0 以下**：无此端点，只能逐项试调（`observations v2` 是否 200 → 否则回落 v1；
  `v3/scores`；`annotation-queues`）。

**★三层必须互相一致，任一不符 = 注册期硬失败，绝不进入运行期静默降级。**
三种不符各有明确含义，报错时必须区分：

| 不符 | 含义 | 最常见成因 |
|---|---|---|
| **L1 ≠ L2** | 人选错了 profile | 自托管 v3 被当成 v4（本项目的头号风险，见 §1.4） |
| **L2 ≠ L3** | 实例被裁剪过，或「版本→能力表」需要更新 | 反代挡了端点；灰度版本；表滞后于新版本 |
| **限流数值与实测不符** | 预算算错 | Cloud 按 **Org** 分桶而非按 project，见 §1.2 |

探测结果（**三层各自的原始证据** + 最终 capabilities）**写进 Run 溯源**，
这样任一次 run 的分数都能回答「当时是按哪套能力假设读的数据」——审计要求，不是调试便利。

**与「静默截断」的关系**：探测挡住的是**能力层**的静默截断。
另有两个**运行期**静默截断源探测挡不住，必须在 B2 适配层用不变量测试兜住：
① 老 SDK（Python <4.7.0 / JS <5.4.0）或 OTel 未发 `x-langfuse-ingestion-version: 4` →
v2 端点**最多延迟 15 分钟**；② 游标分页**可能返回空页而 `meta.cursor` 仍在**，
「页空就停」会截掉整个 cohort。

### 1.6 ★能力探测 vs 适配度预检：两个相邻但完全不同的闸

这两步在接入流程里紧挨着（第 2 步、第 3 步），极易混为一谈。区别如下：

| | **能力探测**（§1.5，注册第 2 步） | **适配度预检**（B1 / `LIFECYCLE.md` §1.2，注册第 3 步） |
|---|---|---|
| 问的对象 | **Langfuse 实例**：「你能提供哪些 API」 | **业务的数据**：「你的埋点够不够我们的算法用」 |
| 关心的层次 | 平台 ↔ Langfuse **兼容性** | 业务侧 **数据质量** |
| 结果形态 | **二元**、**逐端点**（有 / 没有） | **分级**、**逐字段**（0~1 比率 + 是否达标） |
| 典型条目 | observations v2 / v1、`v3/scores`、`annotation-queues`、`/api/openapi.yaml`、限流桶 | `kind_map` 命中率、`isRootObservation` 唯一性、`usageDetails` 键名、`expandMetadata` 必要性、`golden_facts` 是否有值 |
| 决定了什么 | **走哪条代码路径** | **是否允许发布本体** + **L2 映射如何自动生成** |
| 不通过的后果 | **注册期硬失败**，租户建不起来 | **阻断发布**，但给出「补哪个字段」的处方 |
| 能否在拿到 key 前跑 | **能**（`health` 免鉴权） | 不能（要拉真实样本 trace） |
| 换个业务方要重跑吗 | 换**实例**才重跑（同实例下所有租户共享） | **每个租户都要跑**（数据各不相同） |

**一句话记法**：能力探测问「**这台机器能不能对话**」，适配度预检问「**对话内容有没有营养**」。
两道闸都过了，才谈得上首跑。


---

## 2. 后端黑盒模块（B0~B10）

### B0 配置与档案
- **输入**：`endpoints.yaml` · `profiles/*.yaml` · `tenants/*.yaml`（L0：host / profile / keys /
  project_id / queue_id / 默认本体）
- **输出**：解析后的**不可变**配置对象 + 启动自检结果
- **约束**：`kernel/` **不得** import 本层；只有适配层可以。所有 Langfuse 字面量收敛于此。
  profile 与探测结果不符 → 启动失败。
- **与 B1 的分工**：B0 只做**平台自身启动自检**（配置能否解析、profile 与 endpoints 是否自洽）；
  **每租户的能力探测发生在注册期、归 B1**（§1.5），B0 只负责把探测结果**存成不可变档案**并供 B2 读。

### B1 租户与本体注册中心
- **输入**：注册请求（租户、Langfuse 连接、本体 YAML）
- **输出**：`tenant_id` · `ontology@version`（**发布即不可变**）· project↔ontology 1:1 绑定 ·
  **有效 capabilities（能力探测结果）** · 适配度预检报告
- **保存时校验清单**（Python dict 时代靠"同一个文件"隐式保证，YAML 化后必须显式做）：
  `slo_anchors` 键集 ⊆ `{L, latency_total, C, cost_total, tokens_total}`（否则 `baseline.build` 抛
  `ValueError`）· `validators[].kind` 在白名单内且**不得含生成式判官**（锁定项）·
  Tier 1 只有 `forbidden_actions` 必填（漏填 = **漏报**，安全侧）·
  **`required_steps` 已从租户契约删除**（失败方向危险：漏一条合法路径 = 大规模误报，
  见 `LIFECYCLE.md` §2.3/§2.4）· `validators` 只暴露 `number_traceable.min_ratio` 一个旋钮
  （`min_chars`/`max_hits` 内核零引用，不得渲染成可填项）·
  `pattern_count` 走「**平台提案 → 业务确认**」，不是填空
- **★能力探测（注册第 4 步，先于预检）**：§1.5 的三层（人选 profile → `health.version`
  查表推断 → 逐端点实证）。产出「有效 capabilities」，**决定 B2 走 v2 还是 v1 映射器**；
  三层任一不符 → 注册期硬失败。`health` 是全套 API 中**唯一免鉴权**的端点
  ⟹ 探测可在录入 key **之前**先跑一次。
- **适配度预检（注册第 5 步，9 项，逐项给「达标/不达标 + 不达标的具体后果」）**：清单见 `LIFECYCLE.md` §1.2。
  其中 **3 项是静默失败源**（不检就会运行期算错而不报错）：
  ① `metadata` 默认截断 200 字符 → `traceable_number_ratio` **算错但不报错**；
  ② `usageDetails` 是开放映射 → `tokens_system_prompt`/`cache_read`/`cache_write`
  **不是契约保证的**；③ `totalCost` 缺失 + `unit_price=0` → **C 维退化成常数**却仍打满分。
- **预检同时产出 L2**（一趟扫描，零额外 API 调用）：观测 `name` 词表
  （即 `foreign_ratio` 的 `V`，见 `DESIGN.md` §6.1）· `usage_key_map` · `metadata_keys` ·
  `root_rule` · `param` 候选域 · **`pattern_count` 提案**

### B2 Trace 摄取适配层（`TraceSource`）
- **抽象**：`list_traces(window, sampling) -> Iterator[RawTrace]`
- **两实现**：`LangfuseTraceSource`（分页拉 observations，按 `traceId` 重建轨迹）·
  `JsonlTraceSource`（读 `data/bench_v1/`，把**基准注册为平台内部租户**，走完全相同代码路径）
- **输出**：符合 `contracts/schemas.md` §1 的 **19 键 trace / 29 键 span** 记录；
  拿不到的字段**诚实置 None**，让 `missing_field_ratio` 如实上升
- **黑盒约束（每条都有实测/官方依据）**：
  - **必须请求固定的全字段组集合并写进溯源**。`kernel/ingest.py:37` 在**修复前**的原始 span 上按
    `EXPECTED_FIELDS[kind]` 数缺失（llm 13 / agent 10 / tool 6 / retrieval 7 / guard 5）；
    只请求默认 `core,basic` 会让 `missing_field_ratio ≈ 1.0` → 每条轨迹被降级 →
    **置信度维度退化成常数**。
  - **必须传 `expandMetadata`**：metadata 值默认截断到 **200 字符**，
    而 6 个字段只能走 metadata，`output_citations` / `output_facts` 极易超长 →
    **截断会让 `traceable_number_ratio` 算错但不报错**。
  - **`isRootObservation` 优先于 `parentObservationId`**：应用级 root 的父节点可能在别的服务里；
    `kernel/ingest.py:45` 靠 `parent_id is None` 找 root、`:47-57` 按时间包含重建孤儿 ⟹
    朴素映射会**把合法 root 错误重挂父节点**，改变 `depth` / `branch_factor` / `critical_path`。
  - **游标分页：页空但 `meta.cursor` 仍在时必须继续**。
  - **单请求与单响应各 5 MB**：带 `io` 时 `limit=1000` 会撑爆响应 → limit 按字段集动态调。
  - **节流按 profile**：Cloud 按 Org 桶限速；自托管 `general_api_rpm: null` = 不节流。

### B3 作业编排
- **输入**：run 请求（cohort + `ontology@version` + 可选参数覆盖）
- **输出**：`run_id` · 状态机 · **按阶段的进度** · artefact 引用
- **状态机**：`queued → fetching → normalizing → clustering → baselining → detecting →
  scoring → calibrating → writing_back → done | failed`
- **约束**：**异步优先**。实测 600~4000 条轨迹需 **83~153 秒**；生产 1 万~10 万条/天 ⟹
  分钟到十分钟级。进度必须按阶段报，因为各阶段耗时极不均（clustering 最重）。
- **幂等**：同 cohort + 同**版本四元组** = 同结果；重跑生成新 `run_id`，**不覆盖旧的**。

### B4 算法执行壳
- **职责**：把 B2 的输出喂给 `kernel/` 的 10 个阶段
  （`ingest → features → cluster → baseline → binding → detect → score → calib → drift → meta`），
  **不改内核**；固定 seed；记录版本四元组
- **输出**：`scores` 记录（`G,S,a_raw,a_cal,alert,cell,conf,contrib,dims,evidence,gates,grade_*,
  novelty,tier`）+ `metrics` 等价物 + 聚类制品 + 校准制品
- **★准入自检在这里执行**：`foreign_ratio > 0` 的轨迹标记为 **misrouted**，
  **仍打分、仍可见，但不进入告警流**。实测依据见 `DESIGN.md` §6.2：
  不排除则 5% 污染即让 `topk(15) precision` 从 1.0 掉到 **0.60**，跌破
  `OPS_STREAM_PRECISION_MIN = 0.80`。

### B5 结果存储
- **职责**：持久化 **Langfuse 表达不了**的部分 —— `contrib` 零残差分解、`gates`、
  `evidence`（≤3 条，**规则优先的顺序是契约**）、版本四元组、聚类制品、校准可靠性分箱
- **分工**：**Langfuse 存分数入口，平台存证据链**

### B6 回写与复核闭环
- **回写**：`POST /api/public/scores`（**接受 list**）· `source=API`（这让"我们不是 LLM-as-a-Judge"
  在**租户自己的 UI 里自证**）· Score `id` 当**幂等键** · ScoreConfig **不可变可归档**
- **复核**：复用**租户原生标注队列**（有完整公开 API，10 个端点：建队列 / 列队列 /
  列·入队·PATCH·删 item / 加删 assignment）；`human_label` 从 `GET /v3/scores` 带 `annotation`
  字段组读回（`authorUserId` / `queueId` / `source=ANNOTATION`）→ 触发 `kernel/calib.py` 重拟合
- **输出**：回写计数 · 幂等冲突数 · 队列深度 · 回流标签数 · 新 `model_version`

### B7 告警与预算
- **职责**：**强制执行 `ALERT_BUDGET_PER_DAY = 5`** · 按 `a_cal` 排序取 top-K ·
  misrouted 走独立通道 · 去重与静默 · 通知渠道
- **约束**：≤5 条/天是**产品承诺**，必须在**这一层**硬性执行，不能依赖算法自觉。
  单条误报处置目标 ≤3 分钟。

### B8 自检与门禁
- **职责**：暴露 **22 条不变量**运行结果 · 溯源一致性（`scorecard --check` 式）·
  冷启动闸门状态（`COLD_START_MIN_TRACES = 1000`）· 覆盖度审计 gap 清单 ·
  **复现校验**（同四元组重算，验位级一致）
- **★还需暴露 `eval_m` 实际取值**：它是 `cluster.py:729` 的**函数形参**（不是模块常量），
  B4 若在生产放大它，则生产 run 与已发表基准的结构学习样本量不同 ⟹
  **复现必须区分「复现基准（eval_m=400）」与「复现本 run（eval_m=实际值）」**，
  且 `eval_m` 要单列进 Run 溯源（见 `LIFECYCLE.md` §4.2 更正 4 的决策请求）
- **价值**：这是专利主张「相同输入位级一致」的**可执行证据**

### B9 REST façade
- **约束**：**前端不得直连 Langfuse**，全部经平台 —— 否则字段组、`expandMetadata`、
  分页陷阱、限流会在前端**再犯一遍**。

### B10 本体合成器（**Tier 0「零填写」能成立的唯一支撑**）
- **输入**：L0 租户档案 + B1 预检产出的 L2 观测事实
- **输出**：一份可发布的最小本体 —— `id` / `version` / `unit_price`（**平台合成，
  因为 `kernel/ingest.py:71` 是硬索引，缺失即 `KeyError`**）+ 业务方在 Tier 1 填的
  `forbidden_actions`（可空）
- **为什么独立成模块**：`kernel/` 冻结（`code_hash` 闭包）不能改，
  `bench/invariants.py:379` 又要求本体声明 `required_steps` ⟹
  **「租户不声明」这件事只能在平台侧合成空值实现**（`detect.py:280` 已支持静默降级）。
  这条边界一旦被绕过，22 条不变量与已发表的 8 档 scorecard 就会全部失同步。
- **`pattern_count` 提案**也在这里生成：先跑一次探索性过程视图聚类，
  给业务方一句可回答的问题 ——「你的 agent 看起来有 3~5 种执行模式，对吗？」

---

## 3. 前端黑盒模块（F0~F9）

### F0 全局切换器 + 版本四元组（常驻页头）
- 当前租户 · 当前本体@version（= Langfuse project，1:1）·
  **版本四元组** `pipeline_version` / `code_hash` / `ontology@version` / `anchor_version` ·
  **复现按钮**
- **为什么常驻而不藏在详情页**：它是专利主张的可视化证据。

### F1 本体注册中心
- **已注册列表**：租户 · project · Tier · 版本 · 状态 · 最近 run · 覆盖度
- **新接入向导**：按 `LIFECYCLE.md` §1.1 的 **9 步**走（业务方只动手第 1/3/7 步，
  第 7 步在 Tier 0 下是空的）：连接 Langfuse → **能力探测** → **适配度预检报告**
  → 填 L1 → 保存时校验 → 发布（不可变）→ 建 cohort → 首跑
- **★预检报告必须是独立一屏**：9 项逐项给「达标/不达标 + 不达标的具体后果」。
  它是业务方**唯一能看懂的「我的埋点够不够」的答案**，藏在向导步骤里等于没有
- **★能力探测结果与预检报告必须分屏**：探测是**逐端点二元表**
  （端点 / L1 声明 / L2 推断 / L3 实测 / 是否一致），预检是**逐字段分级表**。
  混在一屏会让业务方以为「端点不可用」和「埋点缺字段」是同一类问题（对照见 §1.6）。
  **profile 下拉框可自动预填**：`GET /api/public/health` 免鉴权且返回精确 `version`，
  填完 host 就能探，不必等 key。
- **表单按 Tier 分档渲染**：Tier 0 **可以一屏 0 字段**（口径字段标「已自动兜底，可覆盖」）；
  Tier 1 只有 `forbidden_actions` 必填；`validators`（**一个浮点**）/ `pattern_count`
  （**确认提案，不是填空**）/ `slo_anchors` / `models` / `context_window` 全部可选
- **配置面板必须分区**：`adapt/playbook.md` §2.1 **可调白名单**（可编辑 + 取值纪律提示）vs
  §2.2 **锁定项**（**只读 + 显示锁定理由**）。混在一起渲染会让业务方以为能改锚点阶梯。

### F2 Cohort 与 Run
- **cohort**（1:1 之后极简）：project + 可选 `environment` + 时间窗 + 抽样上限/seed
- **发起分析** = 选 cohort + 选本体版本 + 可选参数覆盖 → 提交异步作业
- **Run 列表**：按阶段的进度条 · 耗时 · n · **冷启动闸门提示**
  （n < 1000 时明确写「**能排序、不能卡阈值，且校准不可用**」——
  R6 n=600 实测 pool **F1 = 0.000 但 AUC 0.917 / P@50 0.820**）
- **重新聚类（三档，风险与成本差两个数量级，UI 必须区分）**：详见 `LIFECYCLE.md` §3。
  **R1 基线刷新**（每日；cell 定义不变；**分数可比**；bump `anchor_version`）·
  **R2 结构重聚类**（**有门槛才做**：`novelty_rate` 出 `[0,0.25]` 带 / `drift` 触发 /
  冷启动恢复强制 / 业务主动；bump **`structure_version`**；**跨版本不可比**）·
  **R3 本体升版**（业务触发）。R2 之后必须联动三件事：cell 稳定 key + lineage、
  **drift 盲区横幅**（`ref_frac=0.2` 参考窗重置，每层攒够 `min_ref=30` 前是盲的）、
  **校准作废 → 禁用告警预算分配**并说明原因
- **重跑语义**：① 同四元组重跑（验位级一致）② 改参数重跑（新 run，不覆盖旧的）
  ③ **不重打分历史轨迹**（审计不可变；趋势图跨版本**画版本边界线**，不连成一条曲线）

### F3 聚类结果视图
- 多视图共识：意图视图 × 过程视图 → cell 矩阵
- **★弃权桶（novelty）必须是一等公民**，与已分配簇并列，标 `novelty_rate` 与 `coverage`。
  理由：R3 `novelty_rate = 0.2867`、`coverage = 0.7133` —— **藏起来就会把 71% 读成 100%**。
- **★misrouted 桶**独立显示，标注「走错门，不进告警流」
- 每 cell：n · **稳定 cell key + 从内容派生的业务命名**（**不显示裸簇号** ——
  簇号换一批数据就会置换，见 `LIFECYCLE.md` §3.2-a）· 簇内基线 P10/P50/P90/P99 阶梯 ·
  可信度层级 `L1/L2/L3`（`credibility(n)=n/(n+KAPPA)`，`KAPPA=30`）
- **★2026-11-10 修正**：原文写「绑定到的声明工作流（Tier 1 才有）」。
  但 `required_steps` 已从租户契约**删除** ⟹ **生产上 `bind_patterns` 恒返回 `{}`，
  所有 cell 都是「纯学习」**，Tier 0 与 Tier 1 在这一点上没有区别。
  `required_for` 回落到 `learned`（`REQUIRED_PREVALENCE=0.95`）——
  **「missing step」判断并未消失，只是从契约变成了流行度估计**（`binding.py:102-104`）。
- **lineage 视图（R2 之后必需）**：延续 / 分裂 / 合并 / 新生 / 消亡。
  趋势图沿 lineage 连线，**不沿簇号连线**

### F4 异常与告警工作台（**值班默认落地页**）
- **四栏，绝不能混成一个列表**（处置动作完全不同）：
  ① **告警**（占预算的 top-K）② **异常但未告警**（`a_cal` 高但被预算截断）
  ③ **misrouted**（走错门）④ **弃权**（novelty）
- 每条：分数 · 等级 · **首要扣分归因** · 一键下钻
- **≤3 分钟处置目标** ⟹ 必须能**不跳转**完成「看证据 → 判定 → 送标注队列」

### F5 单轨迹下钻（**专利演示核心画面**）
- 左：span 树（`kind` / `action` / 耗时 / token / 成本 / status），异常 span 高亮
- 右：**零残差瀑布** —— `contrib` 各项之和严格等于 `S − 100·G`（残差 ~9.5e-14），
  **没有「其他」桶**。LMDI 分解可视化，这是别人画不出来的图。
- **★门禁与维度分必须分区显示**：28 条 `truncation` 类 O 维漏判轨迹的 `dims.O = 1.0`，
  但 28/28 都带 `t0_result_broken`、都是 D 级、`S` 均值 22.778 ——
  **不分区看起来自相矛盾**。
- **★缺失通道显示「丢弃并重归一」，不是 0**。
- 证据 **3 步下钻**：规则 → span → 原始字段
- **参考实现已有**：`bench/show.py:173` 的 `render_trace()`（span 树 + 真值并排渲染）

### F6 校准与标注闭环
- 可靠性曲线（`reliability` 分箱**已算好并持久化**，直接画）
- `ece_raw` → `ece_oof` 对比（实测 0.1014~0.1445 → 最差 **0.0333**，全部 ≤ 0.08 要求）
- 队列深度 · 已回流标签数 · 上次重校准时间 · **重校准按钮**（生成新 `model_version`）

### F7 趋势与漂移（P2）
分数分布随时间 · 簇结构漂移（`DRIFT_ALPHA .01`）· 告警量与预算消耗

### F8 自检与门禁面板（P1）
22 条不变量逐条状态 · 覆盖度 gap 清单与处置 · 溯源一致性 · 复现校验结果 ·
**★「什么时候该重聚类」的四个触发信号实时值与门槛距离**
（`novelty_rate` 距 0.25 还有多少 · drift 统计量距 `DRIFT_ALPHA=.01` 还有多少 ·
n 距 `COLD_START_MIN_TRACES=1000` 还有多少 · 距上次 R2 的天数）——
让重聚类决策**变成可读的仪表，而不是拍脑袋**
- **★第五个信号，且方向相反**：`instability_rate_measured`（`cluster_info`）。
  **它等于 0 才是坏消息** —— 那一刻 `geo_cut=None`、稀有形态的兜底网整个关闭，
  非采样轨迹继承簇均共识（`kernel/cluster.py:859`），平台**对未见形态盲且自信**。
  已发表 8 档最低 0.005、从不为 0 ⟹ 基准里从未触发，但生产流量更干净、更可能撞上。
  **必须反向渲染（0 = 红色告警），并作为强制 R2 的触发条件**（`LIFECYCLE.md` §3.3 / §4.2 更正 3）

### F9 管理面（P2）
配置文件版本 · profile 探测结果 · 限流配额消耗 · 作业队列

---

## 4. 优先级与最小可演示闭环

| 层 | P0 | P1 | P2 |
|---|---|---|---|
| 后端 | B0 B1 B2 B3 B4 B5 B9 **B10** | B6 B8 | B7 的通知渠道（预算强制在 P0） |
| 前端 | F0 F1(只读+最简向导) F2 F3 F4 F5 | F1(完整向导) F6 F8 | F7 F9 |

**最小可演示闭环（不需要 Langfuse key 就能跑通）**：
`JsonlTraceSource`（基准当内部租户）→ B3 发起 run → B4 跑内核 → B5 存证据 →
F2 看进度 → F3 看聚类（含弃权桶）→ F4 看四栏 → F5 看零残差瀑布 →
F0 点复现按钮验位级一致 → **同一个 UI 复现已发表的 scorecard**。
**这条闭环是 P0 里的 P0**：它既是开发期的自测台，也是比赛/专利的演示台，
且不阻塞在"拿到 Langfuse key"这件事上。

---

## 5. 本轮唯一有硬截止日期的事
**2026-11-16 Cloud legacy API 下线（距今 6 天）** → 在此之前把 v1 端点的真实响应抓成 fixture 入库，
否则 v1 映射器将成为整条链路上**唯一无法验证**的代码路径。见 §1.4。

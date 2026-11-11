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
  **迁移 = 换一个启动参数 `--profile <name>`，不改代码**（见 §1.2.1）。

`capabilities` 决定**走哪条代码路径**，`endpoints` 决定**打到哪个 URL**。二者缺一不可。

#### ★1.2.1 作用域（2026-11-11 用户澄清，**此前我理解错了**）
**`base_url` 与 `profile` 是「部署级」单值，不是「租户级」属性。**

- **原误解（已作废，不要再引用）**：我以为同一套平台部署下，可能 A 业务方的 Langfuse 是 v3、
  B 业务方是 v4，所以把 `host` / `profile` 放进了每租户的 `tenants/<id>.yaml`，
  并把能力探测设计成**每租户注册时各跑一次**。
- **实际前提（用户明示）**：**一套平台部署只对接一个 Langfuse 实例**，所有接入业务共用它
  （各自是不同的 Organization / Project，但 `base_url` 与版本完全相同）。
- **配置文件要解决的真实问题**：当**整个平台**在 Cloud ↔ 自托管、v3 ↔ v4 之间**整体迁移**时
  （开发期用 Cloud v4，生产迁自托管 v3，将来再升 v4），**只换启动参数 + 重启**即可，不改代码。

**★2026-11-11 第二次简化（用户提出）**：profile 由**后端启动命令的参数**选定，
不需要额外的平台配置文件；三个 profile 文件在**开发期就固定**下来。
据此**删除了原设计的 `platform.yaml`** —— 它的三个字段全被吸收（见 §1.5）。

| 配置 | 作用域 | 谁改 | 何时改 | 内容 |
|---|---|---|---|---|
| **启动参数 `--profile <name>`**（**取代原 `platform.yaml`**） | **部署级 · 单值** | 部署时的启动命令 | 整体迁移时 | `cloud-v4` / `selfhosted-v3` / `selfhosted-v4` 三选一 |
| `profiles/<name>.yaml`（**出厂固定三份**） | 部署级 | 平台工程 | 升级 Langfuse 版本时 | `base_url`（可被 `--base-url` / 环境变量覆盖）· capabilities · **`version_constraint`** · throttle 数值 · 指向哪个 endpoints |
| `endpoints.yaml` | 部署级 | 平台工程 | 路径变更时 | 全部路径模板 + 每路径旋钮 |
| `tenants/<id>.yaml`（L0） | **租户级** | 平台（接入时录入） | 每接入一个业务方 | **只剩** `org_id` / `project_id` / `keys` / `queue_id` / 默认本体 —— **不再有 `host`，不再有 `profile`** |

**两个由此简化的结论：**
1. **限流仍是租户级配额，但数值来自部署级配置。** Cloud 按 **Organization** 分桶
   （`public-api.md:390`），一租户一 Org（决策 1.A）⟹ 每租户各有独立桶；
   桶的**大小**由 profile 给出，全平台一致。**别把「配置上移」误读成「全平台共享一个桶」。**
2. **任一部署里只有一个 Observation 映射器是活的**（见 §1.3 的强化论据）。

### 1.3 必须承认的代价
`observations_api: v2 | v1` 意味着**必须存在两个 Observation 映射器**（v2 原始串 + 字段组 vs
v1 已解析 JSON + 无字段组）。这是"兼容两种部署形态"的**真实成本**，配置得再好也省不掉。
但它是有界的：一个 `ObservationMapper` 接口、两个实现、由 capability 开关选择。

**★1.2.1 的前提把这笔代价的性质改变了，而且是往坏的方向：**
既然一套部署只对接一个实例，那么**任一部署里两个映射器中只有一个会被执行到，另一个是死代码**。
⟹ **在 Cloud v4 的开发环境里，v1 映射器永远走不到，无法靠"跑起来试试"验证。**
而生产恰恰可能是自托管 v3。**这就是 §1.4 抓 fixture 从"顺手做"升级为 M0 强制入口条件的根本原因**：
fixture 是**唯一**能在 v4 开发环境里验证 v1 代码路径的手段。

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

### 1.5 ★profile 由启动参数选定；运行时只做一次「版本核对」，不做探测套件

**版本核对回答的是「这个 Langfuse 实例是不是我以为的那个形态」**，与「适配度预检」
（问「你的埋点数据质量够不够我们的算法用」）是两件完全不同的事，对照见 §1.6。

**★2026-11-11 第二次简化（用户提出，我接受；并且它证伪了我上一轮的核心论据）**

**用户的方案**：开发期就把三个 profile 文件固定下来 —— `cloud-v4`（Cloud 只支持 v4）·
`selfhosted-v3` · `selfhosted-v4`；**后端启动命令增加一个参数指定用哪个配置文件**，
不做每次启动的探测。

**采纳，并连带两处简化：**
1. **`platform.yaml` 删除。** 它原本只有三个字段，全被吸收：
   `active_profile` → **启动参数 `--profile <name>`**；
   `base_url` → **移进 profile 文件**（自托管地址是站点特定的，允许 `--base-url` 或环境变量覆盖）；
   `探测周期` → **取消**（理由见下「为什么不做周期重探」）。
2. **三层探测砍成一次 `health` 调用。** 逐端点实证（原 L3）与 `/api/openapi.yaml` 对账
   **降级为开发期离线脚本**，不在运行时路径上。

**★自我纠正：我上一轮「为什么必须有探测」的论据不成立，已作废，不要再引用。**
原文是：「capabilities 填错 → 代码**静默**走错分支 → 字段大面积缺席但 HTTP 全 200 →
`missing_field_ratio` 接近 1.0 → 置信度维退化成常数，全程不报错」。
逐个开关推演后，这个说法是**错的**：

| capability 开关 | 填错后的实际表现 | 响亮还是静默 |
|---|---|---|
| `observations_api: v2 或 v1` | v4 上打 legacy、或 v3 上打 v2 → **404**（`deprecated-api-migration.md:331`：「On Langfuse v4, these will return `404`」） | **响亮** |
| `scores_read_api` | `/v3/scores` 需 v3.179.0+，版本不够 → **404** | **响亮** |
| `annotation_queue_api` | 端点不存在 → **404** | **响亮** |
| `project_provisioning` | `/api/admin/organizations` **仅自托管**（`openapi_org.yml` 首部原文）→ **404 / 401 / 403** | **响亮** |
| `io_pre_parsed` · `field_groups_supported` | 与 `observations_api` **完全耦合**（v1 端点在 v4 上不存在，反之亦然）⟹ **无法独立填错** | 不适用 |

⟹ **能力错配几乎全部表现为 404，是响亮的，不是静默的。**
Langfuse 的版本差异是**按端点存在与否**切的，不是**按语义悄悄变**的。
**真正的静默失效来自另一批东西** —— `field_groups` 只请了默认的 `core,basic`、
忘传 `expandMetadata`（metadata 截断到 200 字符）、`usage_key_map` 键名对不上 ——
它们是**每路径旋钮与数据质量**问题，归 **B1 的适配度预检**（§1.6），与 capabilities 无关。
**我把两类风险混为一谈，用一个不成立的「静默失效」论据支撑了一套过重的运行时探测。**

**那么还留什么？一次 `health` 调用。理由是 fail fast 与报错可读，不是防静默算错。**

| 项 | 内容 |
|---|---|
| 时机 | **后端启动时一次**（解析完 `--profile` 之后） |
| 调用 | `GET /api/public/health`，**免鉴权**，约 50ms |
| 比对 | profile 里声明的 `version_constraint` vs 响应中的 `version` |
| 不符 | **拒绝启动**，一行错误：「`--profile=selfhosted-v4` 但实例自报 `3.87.0`，要求 `>=4.0.0`」 |
| 连不上 | 重试若干次；仍失败则**区分两种错误**：「无法核对版本（网络/实例不可达）」vs「版本不符」 |
| 逃生口 | `--skip-version-check`（打警告并记进溯源），供离线开发与气隙环境 |

**`version_constraint` 出厂值**：`cloud-v4` → `>=4.0.0` · `selfhosted-v4` → `>=4.0.0` ·
`selfhosted-v3` → `>=3.0.0,<4.0.0`。

**留这一次调用的唯一价值**：没有它，运维选错 `--profile` 时平台会**正常启动**、
正常接单、直到第一个 run 排到取数阶段才抛一个孤零零的 404，
排查者需要自己把 404 反推成「profile 选错了」。有它，**启动即失败且错误信息直接说出病因**。
50ms 换掉一次可能几十分钟的排查，值。

**依据**（`_tmp_lfdocs/openapi_api.yml:12611`-`:12622`，Cloud 自述 spec 原文）：

```yaml
HealthResponse:
  properties:
    version: {type: string, description: Langfuse server version}
    status:  {type: string}
  required: [version, status]
```

`version` 与 `status` **都是 required** ⟹ 一次调用就拿到**精确版本号**，足以做约束比对。
另两条附带事实：`health` 不健康时返回 **503**（`openapi_api.yml:2470`）⟹ 顺带充当连通性 +
数据库健康探针；实测该 spec 的 **120 个 operation 中只有 `health_health` 一个没有 `security` 块**
（其余 118 个是 `security: *ref_0`）⟹ **启动核对不需要任何租户凭据**，
平台刚部署、一个业务方都没接入时就能跑。

**为什么不做周期重探（原设计取消）**：运维在底下升级 Langfuse 之后，
若跨大版本（v3→v4），legacy 端点直接 **404**，下一个 run 会**响亮地失败**，
不需要我们主动轮询去发现；若是小版本升级，能力集不变，重探没有信息量。
⟹ 替代方案：**run 期遇到 404/400 时给出可操作的错误信息**
（「实例能力与 `--profile` 不符，请核对 `GET /api/public/health` 返回的 `version`」），
把发现成本压到零，而不是常驻一个轮询器。

**溯源记录（轻量，替代原 capability snapshot）**：每次启动存一条**启动记录**
（`profile 名` + `profile 文件内容哈希` + `核对到的 health.version` + `核对时刻` + `是否 skip`），
每个 Run 引用其 id。审计问题「这条分数是按哪套能力假设读的」仍然可答；
但**不再维护「snapshot 变更时间线」**——那是为周期重探设计的，重探已取消。

**开发期离线对账脚本（不在运行时路径上）**：`public-api.md:23` 原文
「Self-hosted: every instance running Langfuse **v4.36.0 or later** serves its own spec at
`/api/openapi.yaml` and an interactive reference at `/api/docs`」（`openapi_api.yml:39`-`:40` 同）。
⟹ 写一个**人工运行**的脚本：拉实例自述 spec，与 profile + endpoints **逐端点对账**，输出差异清单。
用途是**升级 Langfuse 版本时更新那三个 profile 文件**，不是每次启动都跑。
v3 与 v4.36.0 以下无此端点，脚本对它们退化为逐项试调（同样只在开发期跑）。

**两个静默截断源仍然挡不住，仍归 B2**（与版本核对无关，别指望它）：
① 老 SDK（Python <4.7.0 / JS <5.4.0）或 OTel 未发 `x-langfuse-ingestion-version: 4` →
v2 端点**最多延迟 15 分钟**；② 游标分页**可能返回空页而 `meta.cursor` 仍在**，
「页空就停」会截掉整个 cohort。

### 1.6 ★版本核对 vs 适配度预检：两个极易混淆但完全不同的闸

两者名字都带「检查」意味、都发生在平台侧、失败都会「挡住点什么」，因此极易混为一谈。
但依 §1.2.1，它们**连发生的时机和层级都不同**：一个在**平台启动时**（部署级，全局一次），
一个在**每个业务方接入时**（租户级，各跑一次）。区别如下：

| | **版本核对**（§1.5，**平台启动时 · 部署级**） | **适配度预检**（B1 / `LIFECYCLE.md` §1.2，**接入第 4 步 · 租户级**） |
|---|---|---|
| 问的对象 | **Langfuse 实例**：「你是不是我以为的那个形态」 | **业务的数据**：「你的埋点够不够我们的算法用」 |
| 关心的层次 | 平台 ↔ Langfuse **兼容性**（`--profile` 选对没有） | 业务侧 **数据质量** |
| 代价 | **一次 `health` 调用，约 50ms，免鉴权** | 拉样本 trace，多次分页调用 |
| 结果形态 | **一次版本比对**（约束满足 / 不满足） | **分级**、**逐字段**（0~1 比率 + 是否达标） |
| 典型条目 | `health.version` vs profile 的 `version_constraint` | `kind_map` 命中率、`isRootObservation` 唯一性、`usageDetails` 键名、`expandMetadata` 必要性、`golden_facts` 是否有值 |
| 防的是什么 | **选错 profile**（响亮失败，但要等到第一个 run 才炸） | **静默算错**（`missing_field_ratio`、`traceable_number_ratio`、C 维退化） |
| 决定了什么 | **走哪条代码路径**（v2 还是 v1 映射器） | **是否允许发布本体** + **L2 映射如何自动生成** |
| 不通过的后果 | **拒绝启动**，一行错误说出病因 | **阻断该租户发布**，但给出「补哪个字段」的处方 |
| 何时跑 · 跑几次 | **平台启动时一次**，与租户数无关；**无周期重探** | **每个租户注册时都跑一次** |
| 归属模块 | **B0**（配置与档案 / 启动自检） | **B1**（注册中心） |
| 能否在拿到任何 key 前跑 | **能**（`health` 免鉴权；此时一个租户都还没接入） | 不能（要拉该租户真实样本 trace） |
| 失败影响面 | **全平台**（所有租户同时受影响） | **单租户**（只挡住它自己发布） |
| 结果展示位置 | **F9 管理面**一行状态（运维视角） | **F1 注册向导内独立一屏**（业务方视角） |

**一句话记法**：版本核对问「**我是不是找对了门**」，适配度预检问「**门里的东西够不够吃**」。
前者在**平台部署时**过一次（全局），后者在**每个业务方接入时**各过一次（租户级）；
两道都过了，某个租户才谈得上首跑。


---

## 2. 后端黑盒模块（B0~B10）

### B0 配置与档案
- **输入**：**启动参数 `--profile <name>`**（+ 可选 `--base-url` 覆盖 / `--skip-version-check`）·
  `profiles/<name>.yaml`（出厂固定三份，含 `base_url` / capabilities / `version_constraint` / throttle）·
  `endpoints.yaml` · `tenants/*.yaml`（L0，**租户级**：`org_id` / `project_id` /
  `keys` / `queue_id` / 默认本体 —— **依 §1.2.1 已移除 `host` 与 `profile`**）
  ·**没有 `platform.yaml`**（已删，见 §1.2.1 / §1.5）
- **输出**：解析后的**不可变**配置对象 + **一条启动记录**（profile 名 + profile 内容哈希 +
  核对到的 `health.version` + 核对时刻 + 是否 skip），每个 Run 引用其 id
- **约束**：`kernel/` **不得** import 本层；只有适配层可以。所有 Langfuse 字面量收敛于此。
- **★启动时版本核对归本模块**（§1.5）：一次 `GET /api/public/health`（免鉴权，约 50ms），
  把 `version` 与 profile 的 `version_constraint` 比对，**不符则拒绝启动并说出病因**。
  capabilities **直接取自 profile 文件**（决定 B2 走 v2 还是 v1 映射器），**不做逐端点探测** ——
  依据见 §1.5 的开关推演表：能力错配一律表现为 **404**，是响亮的，不值得为它常驻探测。
- **不做周期重探**：跨大版本升级会让 legacy 端点 **404**，下一个 run 会响亮失败；
  小版本升级能力集不变。替代做法是 **run 期 404/400 的错误信息里直接提示核对 `--profile`**。
- **与 B1 的分工**：B0 管**实例形态**（`--profile` 选对没有，启动时一次、全局）；
  B1 管**每个租户的数据**（埋点够不够，每租户一次）。B1 **不做**版本核对，只**读** B0 的启动记录。

### B1 租户与本体注册中心
- **输入**：注册请求（租户、Langfuse 连接、本体 YAML）
- **输出**：`tenant_id` · `ontology@version`（**发布即不可变**）· project↔ontology 1:1 绑定 ·
  适配度预检报告
  （**版本核对不在本模块** —— 它是部署级的、由 `--profile` 决定，归 B0，见 §1.5 / §1.2.1）
- **保存时校验清单**（Python dict 时代靠"同一个文件"隐式保证，YAML 化后必须显式做）：
  `slo_anchors` 键集 ⊆ `{L, latency_total, C, cost_total, tokens_total}`（否则 `baseline.build` 抛
  `ValueError`）· `validators[].kind` 在白名单内且**不得含生成式判官**（锁定项）·
  Tier 1 只有 `forbidden_actions` 必填（漏填 = **漏报**，安全侧）·
  **`required_steps` 已从租户契约删除**（失败方向危险：漏一条合法路径 = 大规模误报，
  见 `LIFECYCLE.md` §2.3/§2.4）· `validators` 只暴露 `number_traceable.min_ratio` 一个旋钮
  （`min_chars`/`max_hits` 内核零引用，不得渲染成可填项）·
  `pattern_count` 走「**平台提案 → 业务确认**」，不是填空
- **适配度预检（注册第 4 步，9 项，逐项给「达标/不达标 + 不达标的具体后果」）**：清单见 `LIFECYCLE.md` §1.2。
  **这是本模块唯一的闸**；版本核对已由 B0 在平台启动时做完，此处只**读**那条启动记录。
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
- **新接入向导**：按 `LIFECYCLE.md` §1.1 的 **8 步**走（业务方只动手第 1/3/6 步，
  第 6 步在 Tier 0 下是空的）：填 project + API key → **适配度预检报告**
  → 填 L1 → 保存时校验 → 发布（不可变）→ 建 cohort → 首跑
- **★向导里不得出现「选 Langfuse 地址 / 选 profile」步骤**（依 §1.2.1：那是部署级属性，
  平台启动时就定了）。业务方视角里 Langfuse 实例是**既成事实**，他只需交出 project 与 key。
  原先设计的「profile 下拉框自动预填」**已作废**。
- **★预检报告必须是独立一屏**：9 项逐项给「达标/不达标 + 不达标的具体后果」。
  它是业务方**唯一能看懂的「我的埋点够不够」的答案**，藏在向导步骤里等于没有
- **★预检报告留在 F1，部署状态（profile + 核对到的 version）移到 F9**：两者受众不同、影响面不同（§1.6）。
  预检是**逐字段分级表**、给业务方看、只挡住他自己；
  版本核对是**给平台运维看的一行状态**、一旦不符全平台起不来。
  把它塞进租户向导会让业务方误以为「实例形态不对」是他埋点没埋好。
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
- **★四栏的判据与处置必须并排写清（此前只列了名字，没定义，容易被问住）**：

| 栏 | 它是什么 | 判据（代码出处） | 值班该做什么 |
|---|---|---|---|
| ① **告警** | 已注册 agent 的轨迹，**统计或规则上确实异常**，且挤进了当日预算 | `detect.py:643` `tier = 2 if alert_rule else (1 if alert_stat else 0)`；预算 `ALERT_BUDGET_PER_DAY=5` 在 **B7** 层硬性截断 | **立即处置**，≤3 分钟看完证据并判定 |
| ② **异常但未告警** | 同上，但**被预算挤出**（`a_cal` 高而排名不够） | 同 ①，只是不在 top-K | 复盘时看；**它是预算是否太紧的唯一证据** |
| ③ **misrouted**（走错门） | **不是异常**，是**根本不该进这个 project 的流量**（别的 agent 的合法轨迹） | `foreign_ratio > 0`（`DESIGN.md` §6.1）：非 root span 里 action 不在词表 `V` 的占比；实测 A=0.0 / B=1.0 **零重叠 ⟹ 阈值恒为 0，无需调参** | **不处置**。**照旧打分、照旧可见、但不进告警流**；它是**接入线索**：「本 project 有 X% 未注册范式 —— 拆一个 project 还是注册第二个本体？」 |
| ④ **弃权**（novelty） | **我们不知道它属于哪一类**，所以拒绝命名 | `cluster.py:862` `singleton(ci) or singleton(cp) or cons_i<0.35 or cons_p<0.35 or geo<=geo_cut`；`cell = null`，**永不喂基线、永不进告警** | 不逐条处置。**攒够样本后触发 R2 重聚类**，或抽样送标注队列 |

- **★③ 与 ④ 最容易被混为一谈，但语义正相反**：
  ③ 是**语义确定、归属错误** —— 我们知道它是什么（另一个 agent 的合法轨迹），它只是走错了门；
  ④ 是**语义不确定** —— 我们不知道它是什么，所以不判。
  **运营动作因此完全不同**：③ 指向「拆 project / 注册第二个本体」，④ 指向「重聚类 / 补标注」。
  把两者混进一个列表，值班就分不清该找**业务方谈接入边界**还是该找**平台谈重聚类**。
- **为什么 ③ 必须独立成栏（实测依据）**：不排除则 **5% 污染即让 `topk(15) precision` 从 1.0 掉到
  0.60**，跌破 `OPS_STREAM_PRECISION_MIN = 0.80`（`DESIGN.md` §6.2 / §6.2.1）。
  机制是 `TIER_BANDS` 的**band 2 下界 = band 1 上界**：外来轨迹对已声明的任何 pattern 都不成立
  → `unfulfilled` → `hard` → 无条件告警，**排在所有统计异常之前**，霸占 top-K。
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
- **部署状态一行**（§1.5 的启动记录）：当前 `--profile` · profile 内容哈希 ·
  核对到的 `health.version` · 核对时刻 · 是否 `--skip-version-check`
  **（只一行，不是面板）** —— 逐端点对账已降级为开发期离线脚本，运行时不产出对账表
- 配置文件版本（`profiles/*` / `endpoints.yaml` 各自的内容哈希）·
  **限流配额消耗（按租户 Org 分桶展示，数值来自部署级 profile）** · 作业队列
- **P2 的理由**：版本核对不通过时平台**根本起不来**，运维看启动日志即可，UI 不在关键路径上。
  **原先「snapshot 变更告警不能推后」的说法已随周期重探一并取消** ——
  实例被升级后 legacy 端点会 404，run 失败本身就是告警，不需要额外的轮询与横幅。

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
**2026-11-16 Cloud legacy API 下线（今天 2026-11-11，距今 5 天）** → 在此之前把 v1 端点的真实响应抓成 fixture 入库，
否则 v1 映射器将成为整条链路上**唯一无法验证**的代码路径。见 §1.4。

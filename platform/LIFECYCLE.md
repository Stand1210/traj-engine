# 平台生命周期设计：接入 · 最小本体 · 重聚类

> 回答三个问题：①新业务如何接入 ②最简洁本体 YAML 需要哪些字段 ③运行一段时间后如何重新聚类。
> 与 `platform/DESIGN.md`（租户/本体/Langfuse 映射）、`platform/MODULES.md`（前后端黑盒模块）配套。
> **本文所有结论都标注了代码或实测出处**；凡是推测都写明「待实测」。
> 日期 2026-11-10。实测脚本：`platform/mixexp.py`（arms 1-2）· `platform/tierexp.py`（arms 3-4）。

---

## 0. 三个答案的一句话版

1. **接入**：**8 步**，其中业务方只动手 2 步（交凭据、确认红线）。平台自动生成映射层 →
   适配度预检 → 发布不可变本体 → 建 cohort → 首跑。**Tier 0 可以一个字段都不填。**
   （原为 9 步：**版本核对已移出接入流程**，因为它是部署级的、由后端启动参数 `--profile`
   决定并在启动时一次做完，与业务方无关 —— 见 `MODULES.md` §1.2.1 / §1.5。）
2. **最小本体**：**Tier 0 = 2 个字段且都由平台合成**（`id` + `unit_price`）；
   **Tier 1 = 业务方只填 `forbidden_actions` 一项**。其余 5 个内核读取的键全部可缺省。
   **★两侧都已实测定价**（§2.3 / §2.4）：填漏 `required_steps` 的代价是**告警率 0.995**；
   删除它的代价是 **A 侧 f1 −0.074**、收益是 `topk` precision **0.60 → 1.00**。
3. **重聚类**：**分三档节奏**，风险与成本差两个数量级。基线刷新（每日，安全）·
   结构重聚类（**有门槛才做**，会改 cell 语义、重置 drift、作废校准）· 本体升版（业务触发）。
   **结构重聚类的成本对 n 是 O(1)**（被 `EVAL_M=400` 采样上限钉住），所以成本不是约束，
   **语义稳定性才是**。

---

## 1. 新业务如何接入

### 1.1 八步流程

> **★2026-11-11 前提纠正**：一套平台部署只对接**一个** Langfuse 实例，所有业务方共用
> （各自不同 Org / Project，但 `base_url` 与版本相同）。所以「选 profile / 探测实例能力」
> 是**部署级**动作，归 B0、平台启动时跑一次，**不在业务方接入流程里**。
> 原第 4 步「能力探测」已删除并**简化为启动时一次 `health` 版本核对**（profile 由启动参数选定），
> 后续步骤顺延重编号。依据与影响面见 `MODULES.md` §1.2.1 / §1.5 / §1.6。

| # | 步骤 | 谁做 | 产出 | 失败即停的判据 |
|---|---|---|---|---|
| 1 | 建 Organization（= 租户边界） | **业务方**（Cloud 上无程序化建 Org 的公开 API；`/api/admin/organizations` **仅自托管**） | `org_id` | — |
| 2 | 建 Project（= 本体边界，1:1） | 业务方或平台代建（`POST /api/public/projects`，需 **org-scoped key**；body 必填 `name` + `retention`，`retention` 须为 0 或 ≥3 天） | `project_id` | — |
| 3 | 交凭据 → 平台录 **L0 租户档案** | **业务方** | `tenants/<id>.yaml`：`org_id` / `project_id` / `keys` / `queue_id`（**依 §1.2.1 已移除 `host` 与 `profile`** —— 那是部署级配置） | — |
| 4 | **拉样本 + 适配度预检**（问「你的埋点够不够我们的算法用」；与部署级的「版本核对」是两件不同的事，对照表见 `MODULES.md` §1.6） | 平台自动 | 预检报告（见 §1.2） | 关键项不达标 → 阻断发布并给出具体原因 |
| 5 | **自动生成 L2 接入映射** | 平台自动 | `kind_map`（平台常量）/ `root_rule` / `param_paths` / `usage_key_map` / `metadata_keys` / `field_groups` / `expandMetadata` 清单 | — |
| 6 | **业务方填 L1** | **业务方** | Tier 0：无。Tier 1：`forbidden_actions`（+ 可选 `validators` / `pattern_count`） | 保存时校验（见 §2.3） |
| 7 | **发布 `ontology@version`** | 平台 | 不可变版本；驱动 `anchor_version` 与每条分数 | — |
| 8 | 建 cohort → **首跑** | 平台 | `run_id` + 冷启动判定 | n < `COLD_START_MIN_TRACES=1000` → 明确标注降级，不假装正常 |

**业务方只动手第 1、3、6 步**，其中第 6 步在 Tier 0 下是空的。

**★流程外还有一道部署级的闸（业务方看不到）**：后端启动命令带 `--profile <name>`
（`cloud-v4` / `selfhosted-v3` / `selfhosted-v4` 三选一），启动时做**一次** `GET /api/public/health`，
把返回的 `version` 与该 profile 声明的 `version_constraint` 比对，**不符则拒绝启动**。
约 50ms、免鉴权、与租户数无关，不属于任何一个租户的接入流程，详见 `MODULES.md` §1.5。

#### 1.1.1 ★业务方视角：其实只有三个动作（避免把流程想复杂）
上面 8 步里，**业务方只碰 3 步，而且全程在网页表单上完成，没有任何文件往返**：

| 业务方做的事 | 形式 | 能否为空 |
|---|---|---|
| ① 在 Langfuse 上建 **Organization**（= 租户边界） | Langfuse 自己的控制台，**手工一次** | 否（Cloud 无程序化建 Org 的公开 API） |
| ② 把 **project 的 API key** 交给平台 | 我们前端的「新增租户」表单 | 否（不给 key 我们读不到任何 trace） |
| ③ 确认 **红线清单** `forbidden_actions` | 同一个表单里的一个多行输入框 | **可以**（Tier 0 就是全空） |

**其余 5 步全部由平台自动完成**，业务方看不到也不用管：
建 Project（可代建）· 拉样本跑 9 项适配度预检 · 自动生成 L2 接入映射 ·
合成 Tier 0 本体 · 发布不可变版本 · 建 cohort · 首跑。
（版本核对**不在这 5 步里，也不在 8 步里** —— 它由后端启动参数决定，
平台部署起来的那一刻就做完了，业务方接入时早已生效。）

**★三个常见误解，逐条否掉：**
- **「平台会生成一个 tier0 文件给我下载」** —— 不会。Tier 0 是**平台内部合成物**
  （`id` + `version` + `unit_price`），业务方既不需要看也不需要签回。
- **「我填完 tier1 要再上传一次」** —— 不用。②③ 是**同一张表单的同一次提交**。
- **「提交完就能直接跑」** —— 中间隔着 **9 项适配度预检**，
  **预检不达标会阻断发布**并给出具体原因（§1.2）；而且首跑若 n < `COLD_START_MIN_TRACES=1000`
  会**明确标注为降级**（能排序、不能卡阈值、校准不可用），不会假装正常。
- **「我要先选我们用的是 Cloud 还是自托管 / v3 还是 v4」** —— **不用，也不该由你选**。
  那是**部署级**属性（一套平台只对接一个 Langfuse 实例），平台启动时已探测确定。
  注册表单里**没有** profile 选项，也**没有** Langfuse 地址输入框（依据见 `MODULES.md` §1.2.1）。
- **`pattern_count` 是「确认提案」不是「填空」**：提案来自平台的一次探索性聚类，
  所以它**发生在首跑之后**，业务方看到的是一句「你的 agent 看起来有 3~5 种执行模式，对吗？」

#### 1.1.2 L2 七个字段是什么（**平台自动生成，业务方一个都不填**）
分工一句话：**L1 回答「什么算不合格」（业务判断），L2 回答「去哪儿读到判断需要的数据」（技术翻译）**。
内核只吃一种固定形状的记录（19 键 trace / 29 键 span，`contracts/schemas.md` §1），
而 Langfuse 给的是另一种形状 —— L2 就是那张翻译配方。

| 字段 | 直观是什么 | 漏配 / 配错会怎样 |
|---|---|---|
| `kind_map` | Langfuse 有 **10 种** observation `type`（`GENERATION`/`TOOL`/`RETRIEVER`/`GUARDRAIL`/`SPAN`/`CHAIN`/`EVENT`/`AGENT`/`EMBEDDING`/`EVALUATOR`），内核只认 **5 种角色**（`llm`/`tool`/`retrieval`/`guard`/`agent`）。这就是那张对号入座的表。**是平台常量**，因为 Langfuse 的 `type` 枚举对所有租户都一样 | **最隐蔽的一个**。`kernel/ingest.py:8` 的 `EXPECTED_FIELDS` 是**按角色**定义的：`tool` 只该带 6 个字段（不含 token），`llm` 该带 13 个（含 `model`/`ttft`/`subgoal_text`）。角色认错 ⟹ 缺失率按错误清单去算 ⟹ `missing_field_ratio` 变成在测「角色配比」而不是「埋点质量」 |
| `root_rule` | 一棵树得知道**谁是树根**。生产上直接用 Langfuse 原生的 `isRootObservation` | `kernel/ingest.py:45` 靠「没有父节点」找根、`:47-57` 按时间包含关系**把孤儿重新挂上去**。分布式场景下应用级的根，其父节点可能在**另一个服务里** ⟹ 会被错误重挂，直接改变 `depth`、`branch_factor`、`critical_path` |
| `param_paths` | 工具调用的参数埋在 `input` 这坨原始串里，这是「**去哪儿掏**」的地图。掏出来才能算 `arg_valid`（参数合不合法）—— Langfuse **没有这一列**，只能适配器现算 | `arg_valid` 恒为 None → 如实计入缺失率。⚠ 合法域现在**由平台从观测值自动收集**（§3.4-b 纠正），不再要求业务声明 ⟹ 它是「偏离常态」而非「违反契约」 |
| `usage_key_map` | Langfuse 的 `usageDetails` 是**开放映射**（官方示例只有 `input`/`output`），各家 SDK 键名不统一 —— 这是「他家叫 `input`、你家叫 `prompt`」的对照表 | **`tokens_system_prompt`/`tokens_cache_read`/`tokens_cache_write` 不是契约保证的键名**。对不上就静默变 None，token 相关特征算错但不报错 |
| `metadata_keys` | 有 **6 个字段 Langfuse 根本没有对应的列**（`subgoal_text`/`arg_valid`/`output_citations`/`verifier`/`output_facts`/`finish_reason`），只能塞进 `metadata` 这个自由口袋。这是「口袋里的东西各叫什么名字」的约定 | 业务没埋点就恒为 None → 缺失率如实上升 → `kernel/score.py` 的 `mfr>0.20` 置信度降级生效。**这是设计不是 bug**：生产分数会系统性地比基准保守 |
| `field_groups` | `GET /v2/observations` 是**按组点菜**的（`core`/`basic`/`time`/`io`/`metadata`/`model`/`usage`/`prompt`/`metrics`/`trace_context`），**默认只上 `core,basic` 两道**。这是「我们每次固定点哪几组」的清单 | **未请求的字段是「缺席」，不是 null**。少点一组 `usage` ⟹ 缺失率 ≈1.0 → 触发 `mfr>0.20` 降级 → **整个置信度维度退化成一个常数** |
| `expandMetadata` 清单 | `metadata` 的值**默认只给前 200 个字符**，超出部分悄悄截断。这个参数是「哪几个键要给我完整的」 | **七项里最危险的一个**。`output_citations`/`output_facts` 极易超 200 字符 ⟹ `traceable_number_ratio` **在截断的字符串上算**，得出一个错数，**且不报任何错** |

**★其中三个是「静默算错、不报错」的**：`expandMetadata`、`field_groups`、`usage_key_map`。
这正是 §1.2 的 9 项预检把它们排在最前面的原因 —— 它们不会让程序崩，只会让分数**悄悄地错**。

#### 1.1.3 L1 三个字段是什么（**业务方唯一要表态的东西**）

| 字段 | 直观是什么 | 缺省会怎样 |
|---|---|---|
| **`forbidden_actions`**（Tier 1 唯一必填） | **红线清单** ——「这些动作一次都不许出现」，如 `commit_change_without_peer_review`、`purge_logs`。正向义务也能写成红线：「变更必须经同行评审」= 把「未经评审就提交」列进红线 | 留空 = 关闭规范性判据。**漏填一条只会漏报（安全侧），不会误报** —— 这正是它被选为唯一必填项的原因（§2.3） |
| `validators`（可选） | **其实只是一个数**：「答案里的数字，必须有多大比例能追溯到检索到的来源」。默认 `min_ratio=1.0` = 每个数字都要有出处；低于阈值 → 硬性违规 | 用默认值 1.0。⚠ `ontology/base.py:69,71` 还声明了 `max_hits`/`min_chars`，但**内核根本不读**（`kernel/detect.py:371` 只 dispatch `number_traceable`）⟹ **UI 上不该出现这两个填写项** |
| `pattern_count`（可选） | **一个整数**：「你的 agent 大概有**几种做法**」—— 注意**不是**「会走哪几步」。业务答不出步骤（LLM 路径不确定），但答得出「大概 3~5 种」。且**由平台先探索性聚类给出候选、业务只需点头** | 留空退到 `K_MAX_PATTERN_ABS=8`。干净流量上影响很小，但**脏流量上过程视图会碎裂**（§2.4 实测：4 簇 → 10 簇、弃权率涨 5 倍） |

**Tier 0 = 业务方一个字段都不填**：平台合成 `id` + `version` + `unit_price:{prompt:0,completion:0}`。
`unit_price` 必须合成，因为 `kernel/ingest.py:71` 是硬索引、缺了直接 `KeyError`；
但它只在 Langfuse 没给 `totalCost` 时才兜底（`:92`）—— **若两边都没有，成本维会退化成常数，
预检必须明说「成本维不可用」，不能悄悄给所有轨迹打成本满分。**


### 1.2 第 4 步「适配度预检」必须报告的 9 项
每一项都对应一个已知的静默失败模式，**不检查就会在运行期算错而不报错**：

| 检查项 | 不达标的后果 | 出处 |
|---|---|---|
| observation `type` 分布（10 类占比） | `kind_map` 无法覆盖 → 有 span 落不进 5 个 `kind` | v4 数据模型 |
| observation `name` 词表 top-K 与覆盖率 | `action` 取值不可控 → 聚类词表爆炸 | `action ← name` |
| `isRootObservation` 命中率；**0 个 root / ≥2 个 root 的轨迹计数** | `kernel/ingest.py:45` 靠 `parent_id is None` 找 root、`:47-57` 按时间包含重建孤儿 → **会把合法 root 错误重挂**，改变 `depth`/`branch_factor`/`critical_path` | 官方：应用级 root 的父节点可能在别的服务里 |
| **`totalCost` / `costDetails` 非空率** | 若 Langfuse 也没成本，`cost_total ≡ 0` → **C 维退化成常数**，却仍会给所有轨迹打"成本满分" | `kernel/ingest.py:92` 仅在 `cost is None` 时用 `unit_price` 兜底 |
| **`usageDetails` 的实际键名** | `tokens_system_prompt`/`tokens_cache_read`/`tokens_cache_write` **不是契约保证的**（`usageDetails` 是开放整数映射，文档示例只有 `input`/`output`）→ 决定 `usage_key_map` | 官方 OpenAPI |
| **6 个无原生列字段的埋点率**（`subgoal_text`/`arg_valid`/`output_citations`/`verifier`/`output_facts`/`finish_reason`） | 未埋点则恒为 None → `missing_field_ratio` 如实上升 → `kernel/score.py` 的 `mfr>0.20` 置信度降级生效 | `DESIGN.md` §4.3 |
| metadata 值长度分布 | 默认**截断到 200 字符**，必须传 `expandMetadata` 才返完整值 → 截断会让 `traceable_number_ratio` **算错但不报错** | 官方参数表 |
| `foreign_ratio` 分布（见 `DESIGN.md` §6.1） | 判断这个 project 是否真的只有一类范式；> 0 说明该拆 project | 实测 A=0.0 / B=1.0，零重叠 |
| 日均轨迹量与 3 天窗口内的 n | 决定首跑是否冷启动、以及 `EVAL_M` 采样比例（§4.2） | `bench/regime.py:164` |

### 1.3 接入后的常态运行
`cohort（project + 可选 environment + 时间窗 + 抽样）→ 异步 run → 分数写回租户 project
（source=API）→ 3~5% 入租户原生标注队列 → 标签回流 → 重校准`。
详见 `MODULES.md` B3/B4/B6。

---

## 2. 最简洁本体 YAML

### 2.1 实测依据：内核只读 7 个键，其中 6 个可缺省
普查方法：对 `kernel/*.py` 全量搜键名的引号字面量，再逐条人工确认是「读取本体」还是
「证据字典的 key」。**上一轮把 `actions` 记成内核读取点是错的** —— 它唯一的命中是
`kernel/detect.py:558` 的 `{"actions": struct["illegal_actions"]}`，那是证据字段名。

| 键 | 读取点 | 缺失时行为 | 结论 |
|---|---|---|---|
| **`unit_price`** | `kernel/ingest.py:71` | **`ontology["unit_price"]` 硬索引 → `KeyError`** | **唯一必须由平台合成的字段** |
| `forbidden_actions` | `kernel/detect.py:283` | `.get(...) or []` → `illegal_actions` 通道静默 | Tier 1 唯一必填 |
| `required_steps` | `binding.py:37,70,114` / `detect.py:279` / `features.py:523` | `.get(...) or {}` → `bool(declared_all)` 为假 → `unfulfilled` 恒 False；`bind_patterns` 返回 `{}`；`plan_revision_count` 恒 0 | **可从租户契约删除**（见 §2.4 的代价） |
| `validators` | `kernel/detect.py:216` | `.get(...) or []` → 循环不执行 | 可选 |
| `slo_anchors` | `kernel/baseline.py:347` | `.get(...) or {}` → `validate_slo_anchors({})` 通过，走学到的 P10/P50/P90/P99 阶梯 | 可选；**两个出厂本体本来就是 `{}`** |
| `models` | `kernel/features.py:405` | `.get(...) or []` → `mult = {}` | 可选，可从 trace 的 `model` 取值自动兜底 |
| `context_window` | `kernel/features.py:437` | `.get(...) or {}` → `cwin.get(model, cwin.get("default"))` 为 None → 跳过 → `context_utilization = None` | 可选 |

**内核完全不读的键**（`actions` / `optional_steps` / `root_action` / `kind_map` / `tool_catalog` /
`intents` / `time_windows` / `param_schema` / `param_keys`）—— **一律不进租户 YAML**。
其中 `kind_map` 是**平台常量**（对所有租户都一样，因为 Langfuse 的 `type` 枚举是平台词表）；
`root_action` 生产上由 `isRootObservation` 原生给出；`param_schema`/`time_windows`/`param_keys`
只在适配器现算 `arg_valid` 时用，那是 **L2 平台的事**。

**已发表的全部 8 个 regime、五维均值 +0.921022，是在 `slo_anchors = {}` 下跑出来的** ⟹
「零 SLO 声明」不是妥协，是**已被基准证明的默认状态**。

### 2.2 Tier 0：业务方一个字段都不填（平台合成）
```yaml
id: <tenant>-<project>
version: 1.0.0
unit_price: {prompt: 0.0, completion: 0.0}   # 平台合成，绕过 ingest.py:71 的硬索引
```
**诚实的后果**：`unit_price` 只在 `span.cost is None` 时参与计算（`ingest.py:92`）。
所以若租户的 Langfuse 已给 `totalCost`，这两个 0 值**根本不影响结果**；
若 Langfuse 也没给，则 `cost_total ≡ 0` → **C 维退化成常数** →
预检必须报出「C 维不可用」，**不能静默给所有轨迹打成本满分**。

### 2.3 Tier 1：业务方唯一要填的
```yaml
forbidden_actions:                     # 红线。漏填 = 漏报（安全侧），不会造成误报
  - commit_change_without_peer_review
  - purge_logs
```
**为什么规范性负担全压在这一项**（而不是 `required_steps`）——**失败方向不对称**：
- `forbidden_actions` 漏一条 → **少抓一个违规**（漏报，安全侧）
- `required_steps` 漏一条合法路径 → 走那条路的**所有**轨迹 `unfulfilled=True`
  （`detect.py:280`，与 binding 无关）→ `hard=True`（`:388`）→ **无条件告警**（`:631`）
  = **大规模误报**（危险侧）
  **★「大规模」现在有实测数字了**（`platform/tierexp.py`，2026-11-10）。
  ontB 轨迹在 ontA 的 `required_steps` 下运行，**精确等价于「业务把一条合法路径填漏了」**：
  | | 声明 `required_steps` | **删除 `required_steps`** |
  |---|---|---|
  | 触发 `unfulfilled` | **199 / 200** | 6 / 200 |
  | 落 tier 2（`a_raw ≥ 0.75`，霸占运营流） | **199 / 200** | 6 / 200 |
  | 告警率 | **0.995** | **0.030** |
  ⟹ 「填漏一条」的代价不是精度掉几个点，是**那条路径上的轨迹以 99.5% 的比率灌进告警流**，
  把值班那 5 个位置全部吃掉。这就是为什么这一项不能进多租户契约。
- 多租户平台上**控制不了租户填得多认真** ⟹ 契约里只应留「填错也安全」的字段。
- 这不是假想风险：`adapt/playbook.md:343` 的故障排查表里已有一行
  「novelty 率异常高（>25%）→ 阈值落在格点上；**或本体 `required_steps` 与真实工作流不符**」。
- 正向义务可以写成负向红线：**ontB 的 `commit_change_without_peer_review` 就是
  「变更必须经同行评审」的红线表达**。

**保存时校验清单**（YAML 化后必须显式做，Python dict 时代靠「同一个文件」隐式保证）：
`slo_anchors` 键集 ⊆ `{L, latency_total, C, cost_total, tokens_total}`（否则 `baseline.build` 抛
`ValueError`，且被不变量 `baseline.slo_anchors_match_consumers` 锁住）·
`validators[].kind` 在白名单内且**不得含生成式判官**（锁定项）·
`forbidden_actions` 与各声明词表不冲突 · 本体**发布即不可变**。

### 2.4 删掉 `required_steps` 的代价（必须如实记，含对我上一轮的纠正）
**零损失的部分**：`unfulfilled` 静默关闭（P 维少一个权重 0.20 的通道，
`W_P_ILL .30 / W_P_UNF .20 / W_P_LOOP .15 / W_P_MISS .25 / W_P_DRIFT .10`）；
`binding` 返回空 → cell 失去业务命名（UI 改为从内容命名）；
`features.py:523` 的 `plan_revision_count` 恒 0 —— 而该特征**已被实测否决**
（`kernel/score.py:182`：`rejected, zero signal (solo Spearman +0.0006)`），**零损失**。
**「missing step」判断并未消失**：`binding.py:106-116` 的 `required_for` 在未绑定时回落
`learned`，即 `baseline._profile` 按 **`REQUIRED_PREVALENCE = 0.95`** 学出的簇内近普适动作。
`binding.py:102-104` 的原文区分得很清楚：「Declared steps are a contract: missing one is a
violation and needs no statistics. Learned steps are a prevalence estimate.」

**★有损失的部分（我上一轮低估了）**：`required_steps` 的**数量**会喂给
`cluster.cluster_views(n_declared_patterns=...)` → `kernel/cluster.py:794`
`n_dec = n_declared_patterns or K_MAX_PATTERN_ABS` → `kmax_pat = min(8, n_dec + 2)`。
`kernel/cluster.py:48-54` 的注释明写：
> 「the cut-selection statistic is monotone toward finer partitions once its k-bias is removed,
> **which makes the cap the binding constraint** — leaving it at a loose global 8 let the
> **heavily corrupted and foreign-ontology regimes shatter 3 declared workflows into 9-12 clusters**。」

我上一轮只测了 R1（干净档），实测 `n_pattern_clusters` 5→7、检测质量几乎不动，
就下了「聚类不需要声明」的结论。**这是以偏概全**：注释点名会碎的是
**重污染档与外来本体档**，而那两档我没测。
**⟹ 修正后的结论：去掉声明在干净流量上代价很小，在脏流量上会导致过程视图碎裂。**

**★2026-11-10 补测了那两档，`cluster.py:48-54` 的警告成立**（`platform/tierexp.py`）：
| 污染档 | `n_pattern_clusters` 声明版 → 删除版 | `novelty_rate` 声明版 → 删除版 |
|---|---|---|
| 5% | 4 → **4**（不碎） | 0.009 → 0.009 |
| 20% | 4 → **10**（碎裂） | 0.009 → **0.04625**（5 倍） |

机制：`n_declared_patterns=0` → `cluster.py:794` `n_dec = 0 or 8 = 8` → `kmax_pat = 8`；
声明版是 `min(8, 3+2) = 5`。**⟹ 碎裂只发生在脏流量上，`pattern_count` 正是对症的那个整数。**

**★删除的收益与代价，两边都已实测**（`platform/tierexp.py`，完整对照表在 `DESIGN.md` §6.2.2）：
- **收益**：5% 档 `topk(15)` precision **0.60 → 1.00**（`OPS_STREAM_PRECISION_MIN=0.80`
  的破口被堵上）；20% 档 overall `fpr_pool` **0.19113 → 0.00597（32 倍）**。
- **代价**：A 侧 `f1_pool` **0.88142 → 0.80745**（5%）、**0.84634 → 0.74300**（20%）。
- **★代价与污染无关**：声明版下污染本身只让 A 的 f1 从 0.88931 掉到 0.88142（**−0.008**）。
  ⟹ 这 −0.074 是「放弃 `unfulfilled` 通道」的**通用价格，干净 project 也要付**。
- **⟹ 但删除字段不能替代 `DESIGN.md` §6.3 的 `foreign_ratio` 摘除。**
  摘除是**零成本**的，删字段是**花 0.074 F1 买保险**。二者防的是不同故障：
  删字段防「业务把 `required_steps` 填漏」，摘除防「外来范式混进 project」。

**缓解方案（比让业务列步骤清单现实得多）——新增一个整数字段 `pattern_count`：**
- 业务方**答不出**「我的 agent 会走哪几步、什么顺序」（这是实现细节，LLM 路径不确定）。
- 但业务方**答得出**「我的 agent 大概有几类做法」——而且这个问题可以
  **由平台先做一次探索性聚类、给出候选数、让业务方确认**：
  「你的 agent 看起来有 3~5 种执行模式，对吗？」
- 一个整数就足以把 `kmax_pat` 从 8 收回到 `pattern_count + 2`，避免碎裂。
- **提案来源是数据，不是业务的想象** —— 与「根据上报的 trace 规矩去聚类」的原则一致。
- 仍留空时退到 `K_MAX_PATTERN_ABS = 8`；此时过分裂**会优雅降级**：
  cell 变小 → `credibility(n) = n/(n+KAPPA)`，`KAPPA=30`，`B(30)=0.5` →
  `baseline.build` 的 `level` 从 `"L3"` 落回 `"L2"`，锚点池 `POOL_W=400` 中
  `k3 = round(400*B)` 来自本格、其余借父层（LOO）。**即部分池化/收缩，不是崩塌。**

### 2.5 最终 L1 字段清单
| 档 | 字段 | 谁填 | 可缺省 |
|---|---|---|---|
| Tier 0 | `id` · `version` · `unit_price` | **平台合成** | `unit_price` 不可省（硬索引），但平台代填 |
| Tier 1 | **`forbidden_actions`** | **业务方** | 可留空 = 关闭规范性判据 |
| 可选 | `validators` | 业务方 | 是 |
| 可选 | **`pattern_count`**（新增，替代 `required_steps`） | 业务方**确认平台的提案** | 是（退到 8，脏流量上会过分裂） |
| 可选 | `slo_anchors` · `models` · `context_window` | 业务方或平台兜底 | 是 |
| **删除** | `actions` · `optional_steps` · `root_action` · `kind_map` · `tool_catalog` · `intents` · `time_windows` · `param_schema` · `param_keys` · **`required_steps`** | — | 内核不读，或属 L2 平台职责 |

**从 32 键 → 13 键 → 最终 Tier 0 零填写、Tier 1 一项必填。**

---

## 3. 运行一段时间后如何重新聚类

### 3.1 三档节奏（风险与成本差两个数量级，绝不能混为一谈）

| 档 | 动作 | 触发 | 成本 | 版本影响 | 分数可比性 |
|---|---|---|---|---|---|
| **R1 基线刷新** | 只重跑 `baseline.build`，**cell 定义不变** | 定时（每日）/ 滚动窗 | 极低，O(n) 统计 | bump `anchor_version` | **可比** |
| **R2 结构重聚类** | 重跑 `cluster_views` + `bind_patterns` + `baseline.build` | 见 §3.3 门槛 | **对 n 是 O(1)**（结构只从 `EVAL_M=400` 采样学）+ O(n·k) 贴标签 | bump **`structure_version`** + `anchor_version` | **跨版本不可比** |
| **R3 本体升版** | 业务改 L1 → 新 `ontology@version` | 业务方主动 | 同 R2 | bump 本体版本 + `anchor_version` | 跨版本不可比 |

**R2 成本对 n 是 O(1) 的依据**：`kernel/cluster.py:733-734` `m = min(eval_m, n)`，
`eval_m = EVAL_M = 400` —— 意图视图的 8 次 bagging（`R_RUNS`）、`kmax ≤ K_MAX=6` 的
kmeans + silhouette 全部只在 ≤400 个采样点上跑；过程视图先把动作序列 `collapse` 成骨架、
去重成 `u` 个唯一骨架，再建 `u×u` 距离矩阵（`u ≤ 400`）。
其余 n−400 条只是按最近质心贴标签，线性。
**⟹ 成本不是约束，语义稳定性才是。**
**⚠ 限定（2026-11-10 补）**：这个 O(1) **以 `eval_m` 恒为 400 为前提**。
若采纳 §4.2 更正 4 的选项 ②（B4 传 `eval_m = min(n, 4000)`），
上界变成 4000 而非 400，且过程视图的 `u×u` 距离矩阵是 **O(u²)**、`u` 随 `eval_m` 增长
⟹ **仍然是 O(1) in n，但常数会显著变大，必须在 10 万条 cohort 上实测 wall time 后才可采纳。**

### 3.2 R2 的三个必须处理的后果

**(a) cell 身份不稳定 —— 不能把裸簇号暴露给 UI**
`cell` 形如 `"i<int>xp<int>"`，簇号由共识算法给出；换一批数据簇号就会置换。
⟹ 必须做两件事：
- **稳定 cell key**：由 cell 的**学习画像**派生（dominant terminal + `REQUIRED_PREVALENCE`
  必需动作集 + intent 质心桶）取哈希，而不是用簇号。
- **lineage 映射**：按**成员最大重叠**计算旧 cell → 新 cell 的关系，分类为
  `延续 / 分裂 / 合并 / 新生 / 消亡`。UI 显示「簇 A 分裂为 A1、A2」「簇 B 并入 A1」。
  趋势图沿 lineage 连线，而不是沿簇号连线。

**(b) drift 检测会被重置，且有一段盲区**
`kernel/drift.py:238` `cell_normalized_z(stream, ref_frac=0.2, min_ref=30, ...)` ——
**参考窗是「传入流的前 20%」**，而流是按 **cell** 归一的
（`stream = [(trace_id, cell, parent, latency_total)]`，按时间排序）。
⟹ 重聚类后 cell 变了 → 整条归一流必须重算 → 参考窗从头开始 →
**直到每层攒够 `min_ref=30` 个观测之前，drift 检测是盲的**（阶梯为 cell → 父意图 → 弃权）。
**这段盲区必须在 UI 上显式标出，不能静默。**
另一个可直接用的设计杠杆：**`ref_frac` 是「传入窗口的比例」，所以 run 的时间窗就是 drift 的参考期定义**。

**(c) 校准模型作废**
`a_raw` 的分布随 cell 结构变化 → `kernel/calib.py` 拟合的 `a_raw → a_cal` 映射失效 →
必须重拟合；标签不足时降级为 `kind=None`（R6 冷启动已证明这是**正确降级**，
其实测 `ece_oof` 最差 0.0333、`n_labels=None`）。
**`a_cal` 是告警排序的依据** ⟹ 这段时间的**告警预算分配也不可信**，必须一并标注。

### 3.3 R2 的触发门槛（可测量，不靠感觉；**四个信号，盲区互不重叠**）
- **`novelty_rate` 超出 `[0.00, 0.25]` 带** → 抓的是**新出现的小子群体**（无法归入现有 cell）。
- **`drift.detect_drift` 触发**（`DRIFT_ALPHA=.01`，`DEFAULT_DELTA=.10` = 「超过漂移前中位数的
  流量占比从 50% 移到 55% 并停在那里」）→ 抓的是**主体流量整体位移**。
- **★为什么两个都要**：`kernel/drift.py:77-81` 明写代价 ——
  「a shift that severely affects a **small sub-population** moves the median little and
  **will not be reported as drift**」。所以只靠 drift 会**漏掉新范式**；
  只靠 novelty 会**漏掉整体劣化**。二者盲区互补。
- **★`instability_rate_measured == 0` → 强制 R2 并告警**（2026-11-10 新增，依据见 §4.2 更正 3）。
  这一刻 `geo_cut = None`、兜底网整个关闭，非采样轨迹继承所属簇的平均共识
  （`cluster.py:859`）⟹ **平台对未见形态是盲的，而且是自信的**。
  已发表 8 档最低 0.005、从不为 0，所以这条**在基准里从未触发**；
  但它在代码里可达，且**生产流量通常比基准更干净**，所以恰恰更可能撞上。
  这是四个信号里唯一一个「**值为 0 才是坏消息**」的，UI 上必须与另外三个反向渲染。
- **冷启动恢复**：n 首次跨过 `COLD_START_MIN_TRACES = 1000` 时**强制** R2 ——
  首跑按定义是降级的（R6 n=600 实测 pool **F1 = 0.000** 但 AUC **0.917**、
  `P@50 0.820`，即「能排序、不能卡阈值」）。
- **业务方主动声明**：改了 prompt 版本、加了工具、换了模型。

### 3.4 明确不要做的事
- **不要重打分历史轨迹**。审计记录必须不可变。每条分数携带它计算时的
  `structure_version` + `anchor_version` + `ontology@version` + `code_hash`；
  趋势图跨版本时**画一条版本边界线**，而不是把两版本的分数连成一条曲线。
- **不要每次 run 都重聚类**。虽然 R2 成本是 O(1)，但 cell 语义每次都变会让趋势图彻底不可读，
  也会让 lineage 图退化成噪声。
- **不要在 R2 之后沿用旧的告警阈值分位**。`a_cal` 分布已变（§3.2c）。

---

## 4. 本轮纠正与新发现的待决策项

### 4.1 纠正：我上一轮「聚类不需要声明」是以偏概全
只测了 R1（干净档）就下结论，而 `kernel/cluster.py:48-54` 点名会碎的是重污染档与外来本体档。
**修正见 §2.4**，缓解方案是 `pattern_count`（一个整数，由平台提案、业务确认）。

### 4.2 `EVAL_M = 400`：★我上一轮把它写成了一个不存在的风险，已更正

**先分清两个「覆盖率」——我上一轮混为一谈，这是本节要修的根本错误：**

| | 采样吗 | 覆盖率 | 出处 |
|---|---|---|---|
| **打分 / 检测 / 归因** | **不采样** | **100%** | `cluster.py:852` 的 `for i in range(n)` 给**每条**轨迹判 cell 或 novelty；`detect_all` 与 `score_all` 都吃全量 `feats` |
| **簇结构学习**（有几类任务、边界在哪） | **采样 ≤400** | 0.4%~4% | `cluster.py:733-734` `m = min(eval_m, n)`；`rng.sample` 是**均匀无放回**，非分层 |
| **簇内基线锚点** | **不采样**（等距压缩，非随机） | 100% 的分位信息 | `baseline.py:179 _equispaced`；`POOL_W=400` 是**保分位的等距抽取**，与随机采样性质完全不同，**不是风险** |

**⟹ 「全量自动评分覆盖 100%」这个产品承诺是对的，没有被 `EVAL_M` 削弱。**
被 400 限制的只有「**决定有几类任务**」这一步。我上一轮写「小群体可能永远采不到」时
没有区分这两件事，读起来像是打分有盲区——**不是**。

**★更正 1：漏采概率我算高了约 10 倍。** `P(漏采) = (1-p)^m`，`m=400`：
| 子群体占比 p | @1万条/天 | @10万条/天 | **单次 run 漏采概率** |
|---|---|---|---|
| 0.25%（=1/400） | 25 条/天 | 250 条/天 | **36.7%** |
| 0.025% | 2 条/天 | 25 条/天 | **90.5%** |
| 0.0025% | 0.25 条/天 | 2 条/天 | **99.0%** |

所以「永远采不到」的门槛是 **p ≲ 0.025%**，不是我写的 0.25%。**在 p=0.25% 处有 63% 的概率采到。**

**★更正 2（更重要）：漏采 ≠ 丢失，因为兜底网的宽度随 n 放大，而样本量不随 n 放大。**
`cluster.py:846-850`：`geo_cut = _quantile(all_geo, flag_rate)`，`all_geo` 是**全量 n** 的后验边距。
⟹ **网宽 = `flag_rate × n`**。已发表 8 档实测（`reports/R*/metrics.json` 的 `cluster_info`）：

| rid | `instability_rate_measured` | `post_margin_cut` | `n_novelty_by_margin` | n | 网宽/n |
|---|---|---|---|---|---|
| R1 | 0.0050 | 419.66 | **20** | 4000 | 0.50% |
| R2 | 0.0075 | 293.85 | **30** | 4000 | 0.75% |
| R3 | 0.2300 | 8.06 | **690** | 3000 | 23.0% |
| R4 | 0.0725 | 352.87 | **87** | 1200 | 7.25% |
| R5 | 0.0050 | 248.07 | **15** | 3000 | 0.50% |
| R6 | 0.0050 | 280.14 | **3** | 600 | 0.50% |
| R7 | 0.0050 | 296.51 | **20** | 4000 | 0.50% |
| R8 | 0.0200 | 367.74 | **60** | 3000 | 2.00% |

`n_novelty_by_margin` 精确等于 `flag_rate × n`（20 = 0.005×4000，690 = 0.23×3000，3 = 0.005×600），
**⟹ 网宽公式已被 8 档数据逐档验证。**

**两个失效条件在生产规模下近乎互斥：**
- 要被 400 采样漏掉，需要 `p ≲ 0.25%`，即 `r = p·n ≲ 0.0025n`；
- 要溢出兜底网，需要 `r > flag_rate·n ≈ 0.005n`；
- `0.0025n < 0.005n` ⟹ **一般情况下不可能同时成立。**
- 残余的脆弱带只有 `p ∈ [flag_rate, ~1%]`：此时漏采概率 13%~37%，且 `r ≳ 网宽`，
  超出部分会被**静默并入最近的错误 cell**（`cluster.py:857`），
  然后**按错误 cell 的基线打分**——这正是 tierexp 里「外来轨迹被错判」的同一机制。
- 举例：n=4000、flag_rate=0.009 → 网宽 36；一个 r=100 的未见群体 → **36 条进 novelty（可见），
  64 条被静默吸收（不可见）**。而在 n=100000、flag_rate=0.009 → 网宽 900，r=250 → **250 条全部接住**。

**★更正 3：真正剩下的风险是「循环性」，不是「样本量」。**
`flag_rate` 是在**那 400 条采样上**测出来的（`cluster.py:843-844` `n_flag/m`），
它估计的是**采样所见流量**的不稳定性。**若 `flag_rate` 恰好为 0，`geo_cut = None`，
兜底网整个关闭**（`cluster.py:846` 的 `if flag_rate > 0.0`），此时非采样轨迹走
`:859` `vi = memcons_i.get(ci, 0.0)`——**继承所属簇的平均共识**，
而 `:831-835` 的注释亲口说这正是被替换掉的旧行为，因为它「makes every one of them look confident」。
**实测状态：8 档里 `flag_rate` 最低 0.005，从不为 0 ⟹ 这个失效路径在基准里从未被触发，
但它在代码里是可达的。** 这是应当写进 §3.3 触发门槛监控的量：
**`instability_rate_measured == 0` 必须作为一个显式告警**，因为那一刻平台对未见形态是**盲的且自信的**。

**★更正 4：我上一轮说「我倾向 ③ 分层采样」，在成本判断上是错的。**
| 选项 | 能否解决 | 成本 | 是否动 `code_hash` |
|---|---|---|---|
| ① 保持 400 | 残余风险已收窄到 `p ∈ [flag_rate, ~1%]` 的窄带 | 0 | 否 |
| ② **调用侧放大 `eval_m`** | 直接压漏采概率（m=4000 时 p=0.25% 漏采降到 **0.0%**） | 过程视图 `u×u` 距离矩阵是 **O(u²)**，u 随 m 涨 | **否**——`eval_m` 是 `cluster.py:729` 的**函数形参**，B4 传值即可，内核不用改 |
| ③ 分层 / 骨架覆盖采样 | 最对症（保证每种 `collapse(action_seq)` 骨架至少 1 条代表） | 同 ② 的 O(u²) | **是**——要加形参就得改 `kernel/cluster.py`，`code_hash` 变 ⟹ **8 份 `SAMPLE.md` 全部重生成** |

**⟹ ② 严格支配 ③**：同样解决问题、同样不动已发表基准（基准走默认值）、但**不触发 `code_hash` 断裂**。
我上一轮没意识到 `eval_m` 是形参而非模块常量，所以把 ③ 排在了 ② 前面。**修正为：先 ②，③ 只在 ② 实测不够时再考虑。**

**★但 ② 治不了另一半盲区，必须说清。** 上面全部讨论的是「**没采到**」。
还有「**采到了但被 k 上限合并**」：`cluster.py:741` `kmax = max(2, min(K_MAX, m-1))`，`K_MAX=6`；
`:795` `kmax_pat = max(2, min(8, n_dec+2))`。放大 `eval_m` **完全不改这两个上限** ⟹
一个采到了的稀有群体仍可能因为「簇数配额用完」而被并进大簇。
而 §2.4 的 tierexp 刚刚实测过：**放松这个上限会在脏流量上导致碎裂**（`n_pattern_clusters` 4 → 10、
novelty 5 倍）。**⟹ k 上限是一个真实的张力，不是免费的旋钮；这一半盲区目前无解，只能靠
`novelty_rate` 出带 + `pattern_count` 提案两条路部分缓解。**

**决策请求（已收窄）**：是否让 B4 在生产 run 传 `eval_m = min(n, 4000)`？
需要一并接受的两个后果：**① 生产 run 与已发表基准的 `eval_m` 不同 ⟹ 复现按钮必须显式区分
「复现基准（eval_m=400）」与「复现本 run（eval_m=实际值）」，且 `eval_m` 必须进 Run 溯源四元组之外单列；
② 过程视图 O(u²) 成本上升，需要先在 10 万条 cohort 上实测 wall time。**

### 4.3 ★新的公开未解问题：污染变重为什么反而让合法簇塌缩
实测（`platform/tierexp.py`）A 侧的 **cell 结构随污染加重而变粗**：
| 污染档 | A 的 cell 数与各 cell 大小 | A 的 `graded` 顶端 → 第 15 名 | `topk` 里 A 占 |
|---|---|---|---|
| 5% | **6 个**：488 / 2021 / 151 / 589 / 485 / **31** | 0.9362 → 0.9065（第 7 名） | 8 / 15 |
| 20% | **2 个**：930 / 2268 | 0.9733 → **0.8673**（第 15 名） | **15 / 15** |

`topk` 从 0.60 翻回 1.00 的直接原因是 **A 自己的 `graded` 分布整体上移**，
把外来轨迹挤出了前 15 —— **不是**外来轨迹自己塌下去（我上一版的解释，已证伪，见
`DESIGN.md` §6.2.1）。而 A 的意图簇为什么从 6 个塌到 2 个，**我没有解释**。
候选假说（**均未验证，不要当结论用**）：外来轨迹挤占了共识切割的 k 配额
（`k_cons` 取 R_RUNS 次 k 的中位数，`cluster.py:668-671`），A 内部原本的细分被合并；
或 `EVAL_M=400` 采样里 A 的占比从 95% 降到 80%，细分簇采不满而并入大簇。
**⟹ 在查清之前，不得把「重污染更安全」当成可依赖的性质去设计任何东西。**
这也是 §6.3 的 `foreign_ratio` 摘除必须做**前置**而非**兜底**的又一个理由。

### 4.4 待决策：`structure_version` 与 lineage 的存储形态
lineage 是「旧 cell → 新 cell 的关系图」，跨 run 累积。是存成每 run 一张边表，
还是维护一个长期的 cell 谱系树？前者简单、后者才能支撑「这个簇从上线到现在怎么演化」的视图。

---

## 5. 因此需要新增/改动的前后端模块（映射回 `MODULES.md`）

### 5.1 后端
- **B0 配置与档案**：**接收启动参数 `--profile`**（+ 可选 `--base-url` / `--skip-version-check`），
  启动时做**一次 `health` 版本核对**（不符即拒绝启动），产出**一条启动记录**供每个 Run 引用。
  **不做逐端点探测、不做周期重探**（依据见 `MODULES.md` §1.5 的开关推演表：能力错配一律 404，是响亮的）。
  归 B0 不归 B1，因为它是**每部署一次**而非**每租户一次**。
- **B1 注册中心**：新增 §1.2 的 **9 项适配度预检**；新增 **L2 自动生成**；
  新增 `pattern_count` 的**探索性提案**流程；保存时校验清单落地。
- **B0 配置**：`endpoints.yaml` + **出厂固定三份** `profiles/{cloud-v4,selfhosted-v3,selfhosted-v4}.yaml`
  （含 `base_url` / capabilities / `version_constraint` / throttle，见 `MODULES.md` §1.2 / §1.2.1）。
  **没有 `platform.yaml`**（原设计已删）。
- **B3 作业编排**：状态机需区分 **R1 / R2 / R3** 三种作业类型（成本与影响面完全不同），
  并在 R2 上挂 §3.3 的门槛判定与 §3.2 的三个后置动作。
- **B4 执行壳**：R2 后必须**触发作废校准**（§3.2c）并标出 **drift 盲区**（§3.2b）。
- **B5 结果存储**：新增 **`structure_version`** 与 **cell lineage 边表**（§3.2a、§4.4）。
- **新增 B10 本体合成器**：Tier 0 下由探测结果自动合成最小本体（§2.2）。
  这是「业务方零填写」能成立的**唯一支撑**，值得独立成模块。

### 5.2 前端
- **F1 注册中心**：向导按 §1.1 的 **8 步**走（**无 profile / 无 Langfuse 地址选项** —— profile 是后端启动参数）；**预检报告必须是独立一屏**（9 项，逐项给
  达标/不达标 + 后果说明），因为它是业务方唯一能看懂的"我的埋点够不够"的答案；
  **`pattern_count` 用「确认提案」而不是「填空」**。
- **F2 Run**：作业类型必须显示 R1/R2/R3；R2 之后**在趋势图上画版本边界线**；
  **drift 盲区**与**校准作废期**用显式横幅标出。
- **F3 聚类结果**：cell 显示**稳定 key + 业务命名**，不显示裸簇号；
  新增 **lineage 视图**（延续/分裂/合并/新生/消亡）。
- **F6 校准闭环**：显示「当前 `a_cal` 模型对应的 `structure_version`」，
  版本不匹配时**禁用告警预算分配**并说明原因。
- **F8 自检面板**：新增 §3.3 四个触发信号的实时值与门槛距离
  （`novelty_rate` 距 0.25 还有多少、drift 统计量距 λ 还有多少），
  让"什么时候该重聚类"**变成可读的仪表而不是拍脑袋**。

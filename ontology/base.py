"""Pluggable business ontologies. The kernel must never hardcode action names.

v3 vocabulary (bench-gen-v3.0.0). Everything below is *business vocabulary*: the kernel reads
it through `get_ontology` and hardcodes none of it, which is what allows one pipeline to run
over ontA (ADN alarm / perf / change) and ontB (a foreign RCA ontology) without a code change.

  intents                 per-intent goal phrase plus >= 8 bilingual query wordings. The goal
                          phrase is substituted into every wording, so `intent_text` always
                          contains the goal tokens; that is what makes goal drift computable
                          from text alone, without an encoder.
  query_langs             (lang, weight). Language is a real stratification axis, not
                          decoration: `lang_token_factor` makes the same request cost a
                          different number of tokens, so a cost baseline fitted across
                          languages is biased by construction.
  context_window          per-model context budget; the denominator of context_utilization.
  system_prompt_tokens    per-model boilerplate prompt volume; drives tokens_system_prompt and
                          therefore the cache accounting.
  param_schema            per-action argument constraints. The generator injects violations so
                          that tool_arg_valid_rate has something to measure.
  validators              now carry stable ids so a span can say which verifier produced it.
  kb_sources              citation vocabulary for retrieval spans; fabricated citations are
                          answer_citations entries that do not occur here.
  subgoal_*               on-goal frames (always contain {goal}) and a detour bank (never
                          contains a goal token): the two poles of goal drift.
  out_frames              wrapper variety for step outputs. Without it each action has one or
                          two distinct output realizations and every n-gram redundancy feature
                          is degenerate (bench/contract.py fidelity check).
"""
import copy

_ONT_A = {
    "id": "ontA",
    "actions": ["plan", "schema_retrieval", "sql_query", "api_call",
                "retrieve_kb", "summarize", "verify", "approve", "execute"],
    "forbidden_actions": ["force_delete", "skip_approval_execute"],
    "required_steps": {
        "p1": ["plan", "sql_query", "summarize"],
        "p2": ["plan", "schema_retrieval", "sql_query", "summarize"],
        "p3": ["plan", "retrieve_kb", "summarize"],
    },
    "optional_steps": ["verify", "api_call", "approve"],
    "root_action": "agent_run",
    "kind_map": {"agent_run": "agent", "plan": "llm", "schema_retrieval": "retrieval",
                 "sql_query": "tool", "api_call": "tool", "retrieve_kb": "retrieval",
                 "summarize": "llm", "verify": "guard", "approve": "guard",
                 "execute": "tool", "force_delete": "tool",
                 "skip_approval_execute": "tool"},
    # cache_read is a discount, cache_write is a surcharge; both are quoted per token so the
    # generator can decompose `cost` exactly into `cost_details`.
    "unit_price": {"prompt": 3e-6, "completion": 6e-6, "tool_call": 2e-4,
                   "cache_read": 7.5e-7, "cache_write": 3.75e-6},
    "context_window": {"adn-llm-72b": 32768, "adn-llm-14b": 16384, "default": 16384},
    "system_prompt_tokens": {"adn-llm-72b": 214, "adn-llm-14b": 152, "default": 168},
    "models": [("adn-llm-72b", 0.30, 3.0), ("adn-llm-14b", 0.70, 1.0)],
    "prompt_versions": [("pv-2026-03", 0.88), ("pv-2026-04-canary", 0.12)],
    "query_langs": [("zh", 0.55), ("en", 0.45)],
    # A Chinese request carries the same intent in fewer characters but more tokens, so the
    # cost baseline of a mixed-language cell is bimodal even when nothing is wrong.
    "lang_token_factor": {"zh": 1.15, "en": 1.0},
    # single source of truth for the {win} vocabulary: param_schema enums and the
    # query templates must not be allowed to drift apart, or a legitimate argument
    # would fail validation and tool_arg_valid_rate would measure the generator.
    "time_windows": ["5m", "15m", "1h", "24h"],
    "slo_anchors": {},
    "validators": [
        {"id": "v_numbers_traceable", "kind": "number_traceable", "target": "answer",
         "spec": "min_ratio=1.0"},
        {"id": "v_no_forbidden_action", "kind": "forbidden_actions", "target": "process",
         "spec": "max_hits=0"},
        {"id": "v_answer_nonempty", "kind": "nonempty_answer", "target": "answer",
         "spec": "min_chars=8"},
    ],
    "tool_catalog": {
        "schema_retrieval": ["catalog.table_schema"],
        "sql_query": ["alarm_db.query", "perf_db.query"],
        "api_call": ["nbi.ne_status", "nbi.alarm_list"],
        "retrieve_kb": ["kb.runbook_search", "kb.history_search"],
        "execute": ["nbi.config_apply"],
        "force_delete": ["nbi.ne_force_delete"],
        "skip_approval_execute": ["nbi.config_apply_nocheck"],
    },
    "param_keys": {
        "sql_query": ["ne_id", "time_window", "severity"],
        "api_call": ["ne_id", "scope"],
        "retrieve_kb": ["query", "top_k"],
        "schema_retrieval": ["table"],
        "execute": ["ne_id", "change_id"],
    },
    "param_schema": {
        "sql_query": {"ne_id": {"type": "string", "prefix": "NE-"},
                      "time_window": {"enum": ["5m", "15m", "1h", "24h"]},
                      "severity": {"enum": ["critical", "major", "minor"]}},
        "api_call": {"ne_id": {"type": "string", "prefix": "NE-"},
                     "scope": {"enum": ["ne", "subnetwork"]}},
        "retrieve_kb": {"query": {"type": "string", "prefix": ""},
                        "top_k": {"enum": [3, 5, 10]}},
        "schema_retrieval": {"table": {"enum": ["current_alarms", "alarm_history",
                                                "kpi_15min"]}},
        "execute": {"ne_id": {"type": "string", "prefix": "NE-"},
                    "change_id": {"type": "string", "prefix": "CHG-"}},
    },
    "kb_sources": ["runbook://adn/alarm-clear-procedure#L12",
                   "runbook://adn/ne-health-check#L48",
                   "runbook://adn/capacity-expansion#L25",
                   "kb://history/incident-2025-1187",
                   "kb://history/incident-2026-0043",
                   "doc://vendor/nbi-api-reference#L310",
                   "doc://policy/change-approval-rules#L7",
                   "doc://topology/subnetwork-east-map"],
    "error_messages": ["upstream timeout after retries", "HTTP 503 from nbi gateway",
                       "query rejected by alarm_db", "connection reset by peer"],
    "warn_messages": ["slow query above soft limit", "partial result set returned"],
}
# ---- ontA intent vocabulary -------------------------------------------------------------
# Every wording embeds {goal} verbatim, so the goal tokens are always a subset of the query
# tokens. That is a deliberate constraint: goal drift is measured as "how much of the goal
# vocabulary survives into step k", and it is only well defined if the goal vocabulary is
# literally present in the request. Variety comes from the surrounding clause structure, which
# is what query_complexity (clause / wh-word / entity counts) is supposed to read.
_INTENTS_A = [
    {"goal": {"zh": "当前告警清单", "en": "current alarm list"},
     "ask": {
         "zh": ["查询网元 {ne} 的{goal}",
                "{ne} 在 {win} 内的{goal}是什么",
                "请列出网元 {ne} {goal}中的每一条记录",
                "按严重级别排序输出 {ne} 的{goal}",
                "{ne} 的{goal}里还有哪些活动告警",
                "给出 {ne} 的{goal}，并说明每条告警的触发原因",
                "先取 {ne} 在 {win} 内的{goal}，再总结最严重的三条",
                "我需要 {ne} 的{goal}，若存在紧急告警请标记出来"],
         "en": ["show the {goal} of {ne}",
                "what is the {goal} for {ne} over the last {win}",
                "list every entry in the {goal} of network element {ne}",
                "pull the {goal} for {ne} and sort it by severity",
                "which alarms are still active in the {goal} of {ne}",
                "give me the {goal} on {ne}, then explain why each one was raised",
                "return the {goal} of {ne} within {win} and summarise the top three",
                "I need the {goal} for {ne}; if any alarm is critical, flag it"]}},
    {"goal": {"zh": "劣化根因", "en": "degradation root cause"},
     "ask": {
         "zh": ["定位网元 {ne} 的{goal}",
                "解释 {ne} 在 {win} 内发生劣化的{goal}",
                "分析 {ne} 的指标下降并给出{goal}",
                "{ne} 的{goal}尚不明确，请结合告警与拓扑排查",
                "{ne} 为什么劣化，请给出{goal}及证据",
                "关联 {ne} 的告警与指标序列，然后输出{goal}",
                "追溯 {ne} 在 {win} 内的{goal}，并对候选因素排序",
                "我需要 {ne} 的{goal}，并附上可证明它的指标"],
         "en": ["find the {goal} for {ne}",
                "explain the {goal} of the {win} degradation on {ne}",
                "analyse the KPI drops on {ne} and state the {goal}",
                "the {goal} on {ne} is unclear, investigate alarms and topology",
                "why did {ne} degrade; give me the {goal} with evidence",
                "correlate alarms and KPI series on {ne}, then report the {goal}",
                "trace the {goal} for {ne} over {win} and rank the candidate factors",
                "I need the {goal} on {ne}; include the metric that proves it"]}},
    {"goal": {"zh": "配置变更方案", "en": "configuration change plan"},
     "ask": {
         "zh": ["为网元 {ne} 拟定{goal}",
                "输出 {ne} 的{goal}并提交审批",
                "评审并最终确定覆盖 {ne} 的{goal}",
                "我要一份可回滚的 {ne} {goal}",
                "编写 {ne} 的{goal}，并列出受影响对象",
                "在维护窗口前准备并校验 {ne} 的{goal}",
                "生成 {ne} 在 {win} 的{goal}并做策略检查",
                "给我一份 {ne} 的{goal}，暂时不要执行"],
         "en": ["draft a {goal} for {ne}",
                "produce the {goal} on {ne} and send it for approval",
                "review then finalise the {goal} covering {ne}",
                "I want a {goal} for {ne} that can be rolled back",
                "write the {goal} for {ne} and list the impacted objects",
                "prepare and validate a {goal} on {ne} before the maintenance window",
                "generate the {goal} for {ne} over {win} and check it against policy",
                "give me a {goal} on {ne}; do not execute it yet"]}},
    {"goal": {"zh": "容量趋势预测", "en": "capacity trend forecast"},
     "ask": {
         "zh": ["给出网元 {ne} 的{goal}",
                "汇总 {ne} 的资源利用率并输出{goal}",
                "{ne} 下个季度的{goal}是什么样",
                "基于 {win} 采样数据计算 {ne} 的{goal}",
                "报告 {ne} 的带宽余量以及{goal}",
                "解释 {ne} 的{goal}，并指出主要驱动业务类型",
                "构建 {ne} 的{goal}，随后建议扩容时间点",
                "我需要 {ne} 的{goal}，并标出最先耗尽的资源"],
         "en": ["produce the {goal} for {ne}",
                "summarise utilisation on {ne} and give the {goal}",
                "what does the {goal} look like for {ne} over the next quarter",
                "compute the {goal} of {ne} from the {win} sampling data",
                "report bandwidth headroom on {ne} together with the {goal}",
                "explain the {goal} for {ne} and name the driving traffic class",
                "build the {goal} on {ne}, then recommend an expansion date",
                "I need the {goal} for {ne}; flag any resource that runs out first"]}},
]

# ---- ontA step text ---------------------------------------------------------------------
# `in` / `out` are the raw agent-log templates; `out_frames` wrap them so that one action has
# many distinct surface realizations. Step logs are English even when the operator asked in
# Chinese, which is how the ADN stack actually logs.
_TEXT_A = {
    "plan": {"in": ["task={goal} ne={ne} window={win}; produce a step plan",
                    "decompose request from {ne} over {win} into executable steps"],
             "out": ["decompose into retrieval then aggregation; window={win}",
                     "step list drafted for {ne}; {nums} candidate actions"]},
    "schema_retrieval": {"in": ["lookup schema for alarm tables of {ne}",
                                "resolve table definitions needed by {ne} query"],
                         "out": ["schema rows: {nums}",
                                 "table metadata resolved: {nums}"]},
    "sql_query": {"in": ["SELECT alarm_id,severity FROM current_alarms WHERE ne='{ne}' "
                         "AND window='{win}' LIMIT 200",
                        "SELECT kpi_ts,value FROM perf_15min WHERE ne='{ne}' "
                        "AND window='{win}' LIMIT 500"],
                  "out": ["rows returned: {nums}",
                          "query settled; row ids {nums}"]},
    "api_call": {"in": ["GET /nbi/v1/ne/{ne}/alarms?window={win}",
                        "GET /nbi/v1/ne/{ne}/status?detail=true"],
                 "out": ["response payload ids: {nums}",
                         "northbound returned objects {nums}"]},
    "retrieve_kb": {"in": ["runbook search: {goal} (ne={ne})",
                           "history search over incidents touching {ne}"],
                    "out": ["matched runbook evidence: {nums}",
                            "knowledge hits ranked: {nums}"]},
    "summarize": {"in": ["condense evidence {nums} into an operator-facing answer",
                         "write the final response for {ne} from evidence {nums}"],
                  "out": ["summary drafted from {nums}",
                          "answer composed citing {nums}"]},
    "verify": {"in": ["policy check on pending action for {ne}",
                      "compliance scan of the pending step set for {ne}"],
               "out": ["verdict {verdict} for {ne}",
                       "policy evaluation on {ne}: {verdict}"]},
    "approve": {"in": ["approval gate for change on {ne}",
                       "route the pending change on {ne} to the approver"],
                "out": ["approval gate {verdict} on {ne}",
                        "change ticket for {ne}: {verdict}"]},
    "execute": {"in": ["apply approved change to {ne}",
                       "commit the sanctioned operation on {ne}"],
                "out": ["applied; affected object ids: {nums}",
                        "commit finished on {ne}; touched {nums}"]},
    "force_delete": {"in": ["FORCE DELETE objects on {ne} without approval",
                            "drop records on {ne} skipping the ticket flow"],
                     "out": ["deleted: {nums}",
                             "objects removed on {ne}: {nums}"]},
    "skip_approval_execute": {"in": ["apply change to {ne} bypassing approval gate",
                                     "push configuration to {ne} with the gate disabled"],
                              "out": ["applied without approval: {nums}",
                                      "gate bypassed on {ne}; ids {nums}"]},
}

_OUT_FRAMES = [
    "{core}",
    "{core}; noted for the operator",
    "{core} (window {win})",
    "step done - {core}",
    "{core}; nothing further required",
    "checked and recorded: {core}",
    "{core} for {ne}",
    "attempt finished, {core}",
    "{core}; payload attached to the trace",
    "ok - {core}",
]

# On-goal frames always carry {goal}; the detour bank must never carry a goal token, and the
# generator additionally filters detours against the goal token set of the current trace, so a
# wording mistake in this file cannot silently turn a detour into an on-goal step.
_SUBGOAL_FRAMES = {
    "zh": ["为{goal}{core}",
           "围绕{goal}执行{core}",
           "推进{goal}：{core}",
           "在 {ne} 上为{goal}完成{core}",
           "针对{goal}进行{core}（窗口 {win}）",
           "步骤目标：{core}，服务于{goal}"],
    "en": ["{core} for the {goal}",
           "work on {core} to advance the {goal}",
           "{core} on {ne} as part of the {goal}",
           "step goal: {core}, serving the {goal}",
           "{core} within {win} for the {goal}",
           "advance the {goal} by {core}"],
}

_SUBGOAL_CORE_A = {
    "zh": {"agent_run": "受理请求", "plan": "拆解任务步骤",
           "schema_retrieval": "检索表结构", "sql_query": "查询数据行",
           "api_call": "调用北向接口", "retrieve_kb": "检索知识库",
           "summarize": "归纳证据", "verify": "执行策略校验", "approve": "触发审批",
           "execute": "下发已批准操作", "force_delete": "强制删除对象",
           "skip_approval_execute": "绕过审批下发"},
    "en": {"agent_run": "accepting the request", "plan": "decomposing the task steps",
           "schema_retrieval": "retrieving the table schema",
           "sql_query": "querying the data rows",
           "api_call": "calling the northbound interface",
           "retrieve_kb": "searching the knowledge base",
           "summarize": "condensing the evidence", "verify": "running the policy check",
           "approve": "triggering the approval gate",
           "execute": "applying the approved operation",
           "force_delete": "force deleting the objects",
           "skip_approval_execute": "applying while bypassing approval"},
}

_SUBGOAL_DETOUR = {
    "zh": ["浏览与本次请求无关的计费台账",
           "翻阅仓库存放的备件登记簿",
           "查询员工通讯录寻找值班人员",
           "整理机房空调巡检的纸质记录",
           "读取门禁系统的刷卡流水",
           "检索培训资料库里的课件目录"],
    "en": ["browse the billing ledger of unrelated subscribers",
           "page through archived warehouse stock records",
           "walk the staff directory looking for an on-call engineer",
           "tidy the paper log of the air-conditioning rounds",
           "read the badge-in stream of the access control system",
           "search the training vault for slide decks"],
}

_ANSWER_TMPL = [
    "{intent} for {ne}: {nums}",
    "result for {ne} ({intent}): {nums}",
    "completed '{intent}' on {ne}; values: {nums}",
    "here is the outcome of '{intent}' on {ne} - {nums}",
    "{ne} | {intent} | observed values {nums}",
    "finished '{intent}' for {ne}; the relevant figures are {nums}",
    "answer to '{intent}' on {ne} over {win}: {nums}",
    "operator summary for {ne} ({intent}): {nums}",
    "'{intent}' on {ne} resolved; see {nums}",
]

_ANSWER_EMPTY_TMPL = [
    "{intent} for {ne}: operation completed, no numeric payload",
    "completed '{intent}' on {ne}",
    "'{intent}' on {ne} finished with an empty result set",
    "no numeric evidence for '{intent}' on {ne}",
]

_GOLDEN_TMPL = "expected answer for {ne} ({intent}): {nums}"

_ONT_A.update({
    "intents": _INTENTS_A,
    "action_text": _TEXT_A,
    "out_frames": _OUT_FRAMES,
    "subgoal_frames": _SUBGOAL_FRAMES,
    "subgoal_core": _SUBGOAL_CORE_A,
    "subgoal_detour": _SUBGOAL_DETOUR,
    "answer_templates": _ANSWER_TMPL,
    "answer_empty_templates": _ANSWER_EMPTY_TMPL,
    "golden_template": _GOLDEN_TMPL,
})
# ---- ontB: a deliberately foreign ontology (R8) -----------------------------------------
# Different actions, different kinds, different price list, different request vocabulary. It
# exists so that "the kernel never hardcodes an action name" is a measured property rather
# than an intention.
_INTENTS_B = [
    {"goal": {"zh": "指标劣化分析报告", "en": "kpi degradation analysis"},
     "ask": {
         "zh": ["出具 {ne} 的{goal}",
                "{ne} 在 {win} 的{goal}要包含哪些内容",
                "请完成 {ne} 的{goal}，并标注异常采样点",
                "针对 {ne} 编写{goal}，说明受影响业务",
                "{ne} 的{goal}需要引用哪些指标序列",
                "先采集 {ne} 的指标，再形成{goal}",
                "给我 {ne} 的{goal}，并给出置信度",
                "复核 {ne} 的{goal}是否遗漏了抖动区间"],
         "en": ["produce the {goal} for {ne}",
                "what belongs in the {goal} of {ne} over {win}",
                "write the {goal} for {ne} and mark the abnormal samples",
                "draft the {goal} covering {ne}, naming the affected services",
                "which metric series must the {goal} of {ne} cite",
                "collect the metrics of {ne} first, then form the {goal}",
                "give me the {goal} for {ne} together with a confidence level",
                "review whether the {goal} of {ne} misses the jitter interval"]}},
    {"goal": {"zh": "拓扑影响范围", "en": "topology impact scope"},
     "ask": {
         "zh": ["评估 {ne} 的{goal}",
                "{ne} 故障时的{goal}有多大",
                "请给出 {ne} 的{goal}，按层级列出",
                "围绕 {ne} 计算{goal}，包含邻居节点",
                "{ne} 的{goal}是否波及核心层",
                "先取拓扑，再判定 {ne} 的{goal}",
                "输出 {ne} 在 {win} 内的{goal}清单",
                "我需要 {ne} 的{goal}，用于停机通告"],
         "en": ["assess the {goal} of {ne}",
                "how large is the {goal} when {ne} fails",
                "give the {goal} of {ne}, listed layer by layer",
                "compute the {goal} around {ne} including neighbour nodes",
                "does the {goal} of {ne} reach the core layer",
                "fetch the topology first, then decide the {goal} of {ne}",
                "output the {goal} list of {ne} within {win}",
                "I need the {goal} of {ne} for the outage notice"]}},
    {"goal": {"zh": "变更评审结论", "en": "change review verdict"},
     "ask": {
         "zh": ["形成 {ne} 的{goal}",
                "{ne} 本次变更的{goal}是什么",
                "请复核 {ne} 的变更并给出{goal}",
                "针对 {ne} 的工单出具{goal}",
                "{ne} 的{goal}是否需要附加条件",
                "召集同行评审，产出 {ne} 的{goal}",
                "在 {win} 窗口前完成 {ne} 的{goal}",
                "我要 {ne} 的{goal}，并附上反对意见"],
         "en": ["form the {goal} for {ne}",
                "what is the {goal} on this change to {ne}",
                "review the change on {ne} and issue the {goal}",
                "release the {goal} for the ticket covering {ne}",
                "does the {goal} on {ne} need extra conditions",
                "convene a peer review and produce the {goal} for {ne}",
                "complete the {goal} on {ne} before the {win} window",
                "I want the {goal} on {ne}, dissenting opinions included"]}},
    {"goal": {"zh": "事件关联结论", "en": "event correlation verdict"},
     "ask": {
         "zh": ["推导 {ne} 的{goal}",
                "{ne} 在 {win} 内的{goal}如何表述",
                "请基于告警与指标给出 {ne} 的{goal}",
                "围绕 {ne} 汇总事件并形成{goal}",
                "{ne} 的{goal}里哪些事件同源",
                "先关联事件，再写下 {ne} 的{goal}",
                "给我 {ne} 的{goal}，标明时间先后",
                "复核 {ne} 的{goal}是否存在误关联"],
         "en": ["derive the {goal} for {ne}",
                "how should the {goal} of {ne} over {win} be worded",
                "give the {goal} on {ne} based on alarms and metrics",
                "aggregate the events around {ne} and form the {goal}",
                "which events in the {goal} of {ne} share one origin",
                "correlate the events first, then write the {goal} for {ne}",
                "give me the {goal} on {ne} with the temporal order marked",
                "check whether the {goal} of {ne} contains a false correlation"]}},
]

_TEXT_B = {
    "intent_parse": {"in": ["parse request: {goal} (ne={ne}, window={win})",
                            "slot filling for the request coming from {ne}"],
                     "out": ["parsed slots: ne={ne} window={win}",
                             "intent normalised for {ne}"]},
    "query_metrics": {"in": ["query kpi for {ne} over {win}",
                             "pull the 15 minute series of {ne}"],
                      "out": ["kpi samples: {nums}",
                              "series fetched, sample ids {nums}"]},
    "fetch_topology": {"in": ["fetch topology around {ne}",
                              "resolve neighbours of {ne} to depth 2"],
                        "out": ["neighbour ids: {nums}",
                                "topology subtree materialised: {nums}"]},
    "correlate_events": {"in": ["correlate kpi {nums} with alarm window {win}",
                                "join the event streams touching {ne}"],
                         "out": ["correlated event ids: {nums}",
                                 "correlation groups formed: {nums}"]},
    "draft_rca": {"in": ["draft root cause from evidence {nums}",
                        "compose the analyst facing conclusion for {ne}"],
                  "out": ["draft cites evidence {nums}",
                          "conclusion written over {nums}"]},
    "peer_review": {"in": ["peer review of draft rca for {ne}",
                           "second pair of eyes on the {ne} conclusion"],
                    "out": ["review {verdict} for {ne}",
                            "peer sign-off on {ne}: {verdict}"]},
    "commit_change": {"in": ["submit change for {ne}",
                             "hand the sanctioned change of {ne} to the orchestrator"],
                      "out": ["submitted; change ids: {nums}",
                              "orchestrator accepted {nums}"]},
    "commit_change_without_peer_review": {
        "in": ["submit change for {ne} skipping peer review",
               "push the change of {ne} with the review stage disabled"],
        "out": ["submitted without review: {nums}",
                "review bypassed on {ne}; ids {nums}"]},
    "purge_logs": {"in": ["purge log store for {ne}",
                          "drop the retained segments belonging to {ne}"],
                   "out": ["purged segments: {nums}",
                           "log store trimmed on {ne}: {nums}"]},
}

_SUBGOAL_CORE_B = {
    "zh": {"agent_run": "受理请求", "intent_parse": "解析请求槽位",
           "query_metrics": "查询指标", "fetch_topology": "获取拓扑",
           "correlate_events": "关联事件", "draft_rca": "起草结论",
           "peer_review": "同行评审", "commit_change": "提交变更",
           "commit_change_without_peer_review": "免评审提交",
           "purge_logs": "清理日志"},
    "en": {"agent_run": "accepting the request", "intent_parse": "parsing the request slots",
           "query_metrics": "querying the metrics", "fetch_topology": "fetching the topology",
           "correlate_events": "correlating the events",
           "draft_rca": "drafting the conclusion",
           "peer_review": "running the peer review",
           "commit_change": "committing the change",
           "commit_change_without_peer_review": "committing without review",
           "purge_logs": "purging the logs"},
}

_ONT_B = {
    "id": "ontB",
    "actions": ["intent_parse", "query_metrics", "correlate_events",
                "draft_rca", "peer_review", "commit_change", "fetch_topology"],
    "forbidden_actions": ["commit_change_without_peer_review", "purge_logs"],
    "required_steps": {
        "b1": ["intent_parse", "query_metrics", "draft_rca"],
        "b2": ["intent_parse", "fetch_topology", "correlate_events", "draft_rca"],
        "b3": ["intent_parse", "correlate_events", "peer_review", "draft_rca"],
    },
    "optional_steps": ["peer_review", "query_metrics"],
    "root_action": "agent_run",
    "kind_map": {"agent_run": "agent", "intent_parse": "llm",
                 "query_metrics": "tool", "correlate_events": "llm",
                 "draft_rca": "llm", "peer_review": "guard", "commit_change": "tool",
                 "fetch_topology": "retrieval",
                 "commit_change_without_peer_review": "tool", "purge_logs": "tool"},
    "unit_price": {"prompt": 4e-6, "completion": 8e-6, "tool_call": 3e-4,
                   "cache_read": 1e-6, "cache_write": 5e-6},
    "context_window": {"rca-llm-xl": 65536, "rca-llm-s": 16384, "default": 16384},
    "system_prompt_tokens": {"rca-llm-xl": 268, "rca-llm-s": 140, "default": 150},
    "models": [("rca-llm-xl", 0.25, 3.5), ("rca-llm-s", 0.75, 1.0)],
    "prompt_versions": [("rca-pv-11", 0.90), ("rca-pv-12-canary", 0.10)],
    "query_langs": [("zh", 0.40), ("en", 0.60)],
    "lang_token_factor": {"zh": 1.18, "en": 1.0},
    "time_windows": ["5m", "15m", "1h", "24h"],
    "slo_anchors": {},
    "validators": [
        {"id": "v_numbers_traceable", "kind": "number_traceable", "target": "answer",
         "spec": "min_ratio=1.0"},
        {"id": "v_no_forbidden_action", "kind": "forbidden_actions", "target": "process",
         "spec": "max_hits=0"},
        {"id": "v_answer_nonempty", "kind": "nonempty_answer", "target": "answer",
         "spec": "min_chars=8"},
    ],
    "tool_catalog": {
        "query_metrics": ["tsdb.kpi_query"],
        "fetch_topology": ["gis.topology_query"],
        "commit_change": ["change_api.submit"],
        "commit_change_without_peer_review": ["change_api.submit_direct"],
        "purge_logs": ["logstore.purge"],
    },
    "param_keys": {
        "query_metrics": ["ne_id", "kpi", "granularity"],
        "fetch_topology": ["region", "depth"],
        "commit_change": ["change_id", "rollback"],
    },
    "param_schema": {
        "query_metrics": {"ne_id": {"type": "string", "prefix": "NE-"},
                          "kpi": {"enum": ["cpu_usage", "packet_loss", "latency_ms"]},
                          "granularity": {"enum": ["1m", "5m", "15m"]}},
        "fetch_topology": {"region": {"enum": ["east", "north", "south"]},
                           "depth": {"enum": [1, 2, 3]}},
        "commit_change": {"change_id": {"type": "string", "prefix": "CHG-"},
                          "rollback": {"enum": ["auto", "manual"]}},
    },
    "kb_sources": ["runbook://rca/kpi-jitter-playbook#L9",
                   "runbook://rca/topology-fault-propagation#L31",
                   "kb://postmortem/2025-0712-core-outage",
                   "kb://postmortem/2026-0119-silent-drop",
                   "doc://vendor/tsdb-query-guide#L77",
                   "doc://policy/peer-review-charter#L3",
                   "doc://change/rollback-matrix#L54",
                   "kb://fleet/ne-generation-mapping"],
    "error_messages": ["tsdb query timed out", "topology service unreachable",
                       "change_api rejected payload", "metric store returned 500"],
    "warn_messages": ["kpi series has gaps", "topology depth truncated"],
    "intents": _INTENTS_B,
    "action_text": _TEXT_B,
    "out_frames": _OUT_FRAMES,
    "subgoal_frames": _SUBGOAL_FRAMES,
    "subgoal_core": _SUBGOAL_CORE_B,
    "subgoal_detour": _SUBGOAL_DETOUR,
    "answer_templates": _ANSWER_TMPL,
    "answer_empty_templates": _ANSWER_EMPTY_TMPL,
    "golden_template": _GOLDEN_TMPL,
}

_REG = {_ONT_A["id"]: _ONT_A, _ONT_B["id"]: _ONT_B}
ONTOLOGY_IDS = tuple(_REG)


def get_ontology(oid):
    if oid not in _REG:
        raise KeyError("unknown ontology %r (registered: %s)" % (oid, ONTOLOGY_IDS))
    return copy.deepcopy(_REG[oid])
# R4 样本阅读手册

这个文件由 `python -m bench.show R4 --sample` 生成，内容是真实数据，不是示意图。

## 一、这套东西是什么

它是一个**离线基准（benchmark）+ 算法工程 harness**，不是生产服务。因为要验证的是“聚类 → 异常识别 → 打分”三个算法模块本身是否成立，
就必须有一份**带真值标签**的轨迹数据：真实 Langfuse 数据没有人工标注的“这条异常/这条正常”，无法算 F1 / ARI / AUC。

因此流程是：

```
bench/generate.py   造数据：模拟智能体执行过程 → traces.jsonl（输入）+ gt.jsonl（真值）
        ↓
kernel/*            算法工程：ingest → features → cluster → baseline → detect → drift → score → calib
        ↓
bench/runner.py     跑全链路 → reports/<regime>/scores.jsonl（每条轨迹的分数+证据）
        ↓
bench/runner.py     拿 gt.jsonl 对自己打分，过 contracts/schemas.md 里的门槛表 → report.md
```

## 二、trace 记录在哪里

| 文件 | 内容 | 行数 |
|---|---|---|
| `data/bench_v1/R4/traces.jsonl` | 模拟出来的轨迹（一行一条，含完整 Span 树） | 1200 |
| `data/bench_v1/R4/gt.jsonl` | 真值：是否异常、异常类型、真实意图/模式、责任 Span | 1200 |
| `reports/R4/scores.jsonl` | 算法输出：S 分、五维、扣分归因、证据、告警 | 1200 |

JSONL = 每行一个压缩 JSON，直接打开会看到一堆没法读的长行。用下面的命令看：

```
python -m bench.show R4 R4-00001        # 看单条轨迹（输入+真值+算法输出）
python -m bench.show R4 --list latency_spike    # 列出某类异常的 trace_id
python -m bench.show R4 --stats                 # 数据集侧写
```

## 三、一条 trace 长什么样

每条 trace = 一棵 Span 树。根节点是整次 agent 执行，子节点是具体步骤（大模型调用 / 工具调用 / 知识检索 / 护栏校验），
每个节点带开始结束时间、token、成本、状态、输入输出文本。下面是真实样本。


## 四、数据集侧写


- 轨迹数 **1200**，Span 数 **6212**，平均 5.2 Span/轨迹
- 异常轨迹 **112** 条（基率 9.33%），正常 **1088** 条
- 意图分布：i0=533，i1=351，i2=217，i3=99
- 真实单元格（意图×模式）**12** 个
- 异常类型分布：latency_spike=20，token_bloat=15，missing_step=14，truncation=14，illegal_step=14，unfinished=11，hallucinated_number=9，error=9，loop=6
- `spec_hash=5188fdfc219089b9`  `gen_version=bench-gen-v3.1.0`
- v3 信号：arg_invalid_spans=59，cache_hit_spans=1987，contradiction=10，fabricated_citation=17，goal_drift=26，llm_spans=2464，plan_revision=75，verifier_fail=33
- 语种分布：en=557，zh=643；会话数 **270**，每会话轮次 {'max': 7, 'min': 1, 'n': 1200, 'p50': 5.0, 'p90': 7.0, 'p99': 7.0}

---

## 五、完整样本：输入 → 真值 → 算法输出

### 样本 A：一条正常轨迹（应该得高分、不告警）

```text
==============================================================================
TRACE R4-00000   [intent0: 按严重级别排序输出 NE-0274-44 的当前告警清单]
  ontology=ontA  session=sess-00000  turn=1/7  spans=5  wall=1.146s  ts_start=1767225588.958
  user_feedback: none captured
  answer_numbers=['8003', '4396']
  answer_facts  =['NE-0274-44', '8003', '4396']
  golden_answer =
  golden_facts  =None
  goal_text     =当前告警清单   query_lang=zh
  answer_citations  =[]
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[0.0051, -0.1268, -0.3055, 0.199] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run           1.146 ######### 597       207        0.00358 ok    stop
       in : 按严重级别排序输出 NE-0274-44 的当前告警清单
       out: result for NE-0274-44 (按严重级别排序输出 NE-0274-44 的当前告警清单): 8003, 4396
       meta: model=adn-llm-14b  facts=[8003 4396]
       v3  : sys=145  cache_w=145  cost_det={cache_write:0.000544,completion:0.00124,prompt:0.00179}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan                0.985 ########  2172      653        0.01097 ok    stop
         in : task=当前告警清单 ne=NE-0274-44 window=1h; produce a step plan
         out: decompose into retrieval then aggregation; window=1h for NE-0274-44
         meta: model=adn-llm-14b  ttft=0.1121  pv=pv-2026-04-canary
         v3  : sys=142  cache_w=142  cost_det={cache_write:0.000532,completion:0.00392,prompt:0.00652}  subgoal=推进当前告警清单：拆解任务步骤
  `- s02           tool        sql_query           0.035 #         0         0          0.00020 ok    -
         in : SELECT alarm_id,severity FROM current_alarms WHERE ne='NE-0274-44' AND w
         out: rows returned: 8729 8222 8003 (window 1h)
         meta: tool=alarm_db.query  params={ne_id:NE-0274-44,severity:major,time_window:1h}  facts=[8729 8222 8003]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s03           tool        api_call            0.069 #         0         0          0.00020 ok    -
         in : GET /nbi/v1/ne/NE-0274-44/alarms?window=1h
         out: response payload ids: 9195 4396 4828 3475; noted for the operator
         meta: tool=nbi.ne_status  params={ne_id:NE-0274-44,scope:ne}  facts=[9195 4396 4828 3475]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s04           llm         summarize           0.069 #         1359      452        0.00633 ok    stop
         in : write the final response for NE-0274-44 from evidence 8222 8003 9195 439
         out: answer composed citing 8222 8003 9195 4396 4828 3475 (window 1h)
         meta: model=adn-llm-72b  ttft=0.0035  pv=pv-2026-04-canary
         v3  : sys=204  cache_r=204  cost_det={cache_read:0.000153,completion:0.00271,prompt:0.00347}  verifier=v_numbers_traceable:PASS  subgoal=在 NE-0274-44 上为当前告警清单完成归纳证据

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=False  anomaly_types=[]
    intent=i0  pattern=p1  cell=i0|p1
    oracle dim_dev : O=1.00  P=1.00  L=0.77  C=0.56  R=1.00
    latency_true=1.143s  gen_quantiles={'C': 0.8891, 'L': 0.4632}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=[]  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.0000  model_mix_true={'adn-llm-14b': 0.6671, 'adn-llm-72b': 0.3329}  feedback_available=False
    has_golden=False  key_fact_recall_true=n/a  fact_precision_true=n/a
    hallucinated_facts=[]
    query_lang_true=zh  session_turn_count_true=7  subgoal_count=2
    plan_revision_true=0  goal_drift_true=False  arg_valid_true=1.0000  verifier_pass_true=1.0000
    citation_reachable_true=n/a  contradiction_true=0.0000  contradicted_count=0  fabricated_citation_count=0
    cache_read_true=204  cache_write_true=287  system_prompt_ratio_true=0.1189  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice5b-v0.5.1)
    S=89.3100  G=1.00  grade_abs=B  grade_rel=C  tier=0  novelty=False
    alert=False (rule=False stat=False)  cold_start=False  cell=i0xp0
    dims    : O=1.000  P=1.000  L=0.906  C=0.520  R=1.000
    contrib : O=+0.000  P=+0.000  L=-1.404  C=-9.286  R=+0.000   sum=-10.6900
    zero-residual: S-100G=-10.6900  |diff|=3.30e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.2301  a_cal=0.1182  conf=0.9809  anchor=anchor-R4-5188fdfc219089b9
    evidence (3 items, drill-down order):
      - [trace] cost_total               span=R4-00000-s01   value=0.0213      cell_median=0.0111      z=  +1.90 dev=0.2258
      - [trace] tokens_total             span=R4-00000-s01   value=5440.0000   cell_median=3002.0000   z=  +1.67 dev=0.2105
      - [span ] tok                      span=R4-00000-s01   value=2825.0000   peer_median=1101.0000   z=  +3.15 dev=0.2644 (L3/L3span action=plan)
```

### 样本 B：latency_spike —— R4-00002

某一步耗时被放大 5~20 倍。看 SPAN TREE 里的 dur(s) 列和 share 条：其中一个子步骤吃掉了几乎全部壁钟时间。真值把 L 维打到 0.10，算法应该在 L 上扣分并把责任指向那个 Span。

```text
==============================================================================
TRACE R4-00002   [intent1: find the degradation root cause for NE-F691-48]
  ontology=ontA  session=sess-00000  turn=3/7  spans=5  wall=18.150s  ts_start=1767225888.581
  user_feedback: none captured
  answer_numbers=['7759']
  answer_facts  =['NE-F691-48', '7759']
  golden_answer =
  golden_facts  =None
  goal_text     =degradation root cause   query_lang=en
  answer_citations  =['kb://history/incident-2025-1187']
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[0.104, -0.2014, -0.1902, 0.4475] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run          18.150 ######### 217       87         0.00080 ok    stop
       in : find the degradation root cause for NE-F691-48
       out: 'find the degradation root cause for NE-F691-48' on NE-F691-48 resolved;
       meta: model=adn-llm-14b  facts=[7759]
       v3  : sys=166  cache_r=166  cost_det={cache_read:0.000124,completion:0.000522,prompt:0.000153}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan                7.758 ####      697       98         0.00216 ok    stop
         in : task=degradation root cause ne=NE-F691-48 window=15m; produce a step pla
         out: step list drafted for NE-F691-48;  candidate actions
         meta: model=adn-llm-72b  level=WARNING  ttft=2.3244  pv=pv-2026-03  msg=slow query above soft limit
         v3  : sys=230  cache_r=230  cost_det={cache_read:0.000172,completion:0.000588,prompt:0.0014}  subgoal=step goal: decomposing the task steps, serving the degradati
  `- s02           guard       verify              0.448 #         232       38         0.00092 ok    -
         in : policy check on pending action for NE-F691-48
         out: policy evaluation on NE-F691-48: pass
         v3  : cost_det={completion:0.000228,prompt:0.000696}  verifier=v_no_forbidden_action:PASS
  `- s03           retrieval   retrieve_kb         9.443 #####     106       0          0.00032 ok    -
         in : history search over incidents touching NE-F691-48
         out: attempt finished, matched runbook evidence: 7759 3509 4328
         meta: tool=kb.history_search  params={query:NE-F691-48,top_k:5}  facts=[7759 3509 4328]
         v3  : cost_det={prompt:0.000318}  arg_valid=True  retrieved=[kb://history/incident-2025-1187 runbook://adn/ne-health-check#L48]
  `- s04           llm         summarize           0.693 #         614       170        0.00236 ok    stop
         in : condense evidence 7759 3509 4328 into an operator-facing answer
         out: summary drafted from 7759 3509 4328
         meta: model=adn-llm-72b  ttft=0.1807  pv=pv-2026-03
         v3  : sys=222  cache_r=222  cost_det={cache_read:0.000167,completion:0.00102,prompt:0.00118}  verifier=v_numbers_traceable:PASS  subgoal=advance the degradation root cause by condensing the evidenc

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['latency_spike']
    intent=i1  pattern=p3  cell=i1|p3
    oracle dim_dev : O=1.00  P=1.00  L=0.10  C=0.88  R=1.00
    latency_true=18.147s  gen_quantiles={'C': 0.239, 'L': 0.8095}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=['R4-00002-s03']  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.0000  model_mix_true={'adn-llm-14b': 0.1614, 'adn-llm-72b': 0.8386}  feedback_available=False
    has_golden=False  key_fact_recall_true=n/a  fact_precision_true=n/a
    hallucinated_facts=[]
    query_lang_true=en  session_turn_count_true=7  subgoal_count=2
    plan_revision_true=0  goal_drift_true=False  arg_valid_true=1.0000  verifier_pass_true=1.0000
    citation_reachable_true=1.0000  contradiction_true=0.0000  contradicted_count=0  fabricated_citation_count=0
    cache_read_true=618  cache_write_true=0  system_prompt_ratio_true=0.3312  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice5b-v0.5.1)
    S=90.2248  G=1.00  grade_abs=A  grade_rel=C  tier=0  novelty=False
    alert=False (rule=False stat=False)  cold_start=False  cell=i2xp2
    dims    : O=1.000  P=1.000  L=0.520  C=0.968  R=1.000
    contrib : O=+0.000  P=+0.000  L=-9.314  C=-0.461  R=+0.000   sum=-9.7752
    zero-residual: S-100G=-9.7752  |diff|=4.80e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.2474  a_cal=0.1324  conf=0.9717  anchor=anchor-R4-5188fdfc219089b9
    evidence (3 items, drill-down order):
      - [trace] latency_total            span=R4-00002-s00   value=18.1502     cell_median=9.4474      z=  +1.65 dev=0.2303
      - [trace] branch_factor            span=-              value=4.0000      cell_median=4.0000      z=  +0.00 dev=0.0831
      - [span ] dur                      span=R4-00002-s03   value=9.4426      peer_median=1.5866      z=  +6.61 dev=0.3606 (L3/L3span action=retrieve_kb)
```

### 样本 C：hallucinated_number（带 golden） —— R4-01191

最终答案里出现了检索证据中不存在的数字。对比子 Span 的 `out: evidence: ...` 与根 Span 的 `out: answer: ...`：后者多出了两个 5 位数。这是唯一一个靠文本内容判定的异常（`traceable_number_ratio` 特征）。

这条带 golden。看 GROUND TRUTH 里的 `fact_precision_true` 与 `key_fact_recall_true`：编造数字只压 precision，recall 仍为 1.00——答案里的事实都在，只是多了不该有的。`hallucinated_facts` 直接列出多出来的那几个。

```text
==============================================================================
TRACE R4-01191   [intent1: trace the degradation root cause for NE-FDF2-36 over 1h and rank the candidate factors]
  ontology=ontA  session=sess-00267  turn=2/5  spans=6  wall=12.613s  ts_start=1767397083.079
  user_feedback: none captured
  answer_numbers=['6192', '6239', '68896', '27574']
  answer_facts  =['NE-FDF2-36', '6192', '6239', '68896', '27574']
  golden_answer =expected answer for NE-FDF2-36 (trace the degradation root cause for NE-FDF2-36 over 1h and rank the candidate factors): 6192, 6239
  golden_facts  =['NE-FDF2-36', '6192', '6239']
  goal_text     =degradation root cause   query_lang=en
  answer_citations  =['runbook://adn/alarm-clear-procedure#L12', 'runbook://adn/capacity-expansion#L1758', 'runbook://adn/capacity-expansion#L1794']
  contradicted_facts=['6192', '6239']
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[0.1226, -0.1557, -0.1584, 0.3042] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run          12.613 ######### 521       208        0.00341 ok    stop
       in : trace the degradation root cause for NE-FDF2-36 over 1h and rank the can
       out: answer to 'trace the degradation root cause for NE-FDF2-36 over 1h and r
       meta: model=adn-llm-14b  facts=[6192 6239 68896 27574]
       v3  : sys=160  cache_w=160  cost_det={cache_write:0.0006,completion:0.00125,prompt:0.00156}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan                0.930 #         1020      152        0.00346 ok    stop
         in : decompose request from NE-FDF2-36 over 1h into executable steps
         out: step list drafted for NE-FDF2-36;  candidate actions; nothing further re
         meta: model=adn-llm-72b  ttft=0.2388  pv=pv-2026-03
         v3  : sys=229  cache_r=229  cost_det={cache_read:0.000172,completion:0.000912,prompt:0.00237}  subgoal=decomposing the task steps within 1h for the degradation roo
  `- s02           guard       approve             0.930 #         542       137        0.00245 ok    -
         in : route the pending change on NE-FDF2-36 to the approver
         out: approval gate pass on NE-FDF2-36
         v3  : cost_det={completion:0.000822,prompt:0.00163}  verifier=v_no_forbidden_action:PASS
  `- s03           retrieval   retrieve_kb         1.700 #         850       0          0.00255 ok    -
         in : runbook search: degradation root cause (ne=NE-FDF2-36)
         out: ok - knowledge hits ranked: 6239 9437 6192
         meta: tool=kb.runbook_search  params={query:NE-FDF2-36,top_k:10}  facts=[6239 9437 6192]
         v3  : cost_det={prompt:0.00255}  arg_valid=True  retrieved=[runbook://adn/alarm-clear-procedure#L12]
  `- s04           guard       verify              1.529 #         307       31         0.00111 ok    -
         in : policy check on pending action for NE-FDF2-36
         out: verdict pass for NE-FDF2-36
         v3  : cost_det={completion:0.000186,prompt:0.000921}  verifier=v_no_forbidden_action:PASS
  `- s05           llm         summarize           7.963 ######    1545      780        0.00899 ok    stop
         in : condense evidence 6239 9437 6192 into an operator-facing answer
         out: summary drafted from 6239 9437 6192 for NE-FDF2-36
         meta: model=adn-llm-14b  ttft=1.2549  pv=pv-2026-03
         v3  : sys=144  cache_r=144  cost_det={cache_read:0.000108,completion:0.00468,prompt:0.0042}  verifier=v_numbers_traceable:FAIL(answer number absent from the evidence pool)  subgoal=condensing the evidence on NE-FDF2-36 as part of the de

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['hallucinated_number']
    intent=i1  pattern=p3  cell=i1|p3
    oracle dim_dev : O=0.15  P=1.00  L=0.67  C=0.55  R=1.00
    latency_true=12.610s  gen_quantiles={'C': 0.8905, 'L': 0.6634}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=[]  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.0000  model_mix_true={'adn-llm-14b': 0.7227, 'adn-llm-72b': 0.2773}  feedback_available=False
    has_golden=True  key_fact_recall_true=1.0000  fact_precision_true=0.6000
    hallucinated_facts=['27574', '68896']
    query_lang_true=en  session_turn_count_true=5  subgoal_count=2
    plan_revision_true=0  goal_drift_true=False  arg_valid_true=1.0000  verifier_pass_true=0.7500
    citation_reachable_true=0.3333  contradiction_true=0.4000  contradicted_count=2  fabricated_citation_count=2
    cache_read_true=373  cache_write_true=160  system_prompt_ratio_true=0.1114  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice5b-v0.5.1)
    S=38.1873  G=0.60  grade_abs=D  grade_rel=D  tier=2  novelty=False
    alert=True (rule=True stat=False)  cold_start=False  cell=i2xp2
    dims    : O=0.457  P=1.000  L=0.698  C=0.568  R=1.000
    contrib : O=-15.115  P=+0.000  L=-2.601  C=-4.097  R=+0.000   sum=-21.8127
    zero-residual: S-100G=-21.8127  |diff|=4.90e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.9281  a_cal=0.9608  conf=0.9717  anchor=anchor-R4-5188fdfc219089b9
    gates: {"t2_untraceable_number": 0.6}
    evidence (3 items, drill-down order):
      - [trace] traceable_number_ratio   span=-              value=0.5000      cell_median=1.0000      z= -50.00 dev=0.3817
      - [trace] branch_factor            span=-              value=5.0000      cell_median=4.0000      z=  +0.67 dev=0.2108
      - [span ] tok                      span=R4-01191-s02   value=679.0000    peer_median=356.5000    z=  +1.60 dev=0.2344 (L3/L3span action=approve)
```

### 样本 D：loop —— R4-00062

同一步骤被重复插入 3~5 次。SPAN TREE 里会看到连续多行相同 action，时间戳也相同（生成器直接复制了 Span）。

```text
==============================================================================
TRACE R4-00062   [intent0: show the current alarm list of NE-F3C0-10]
  ontology=ontA  session=sess-00017  turn=2/5  spans=9  wall=2.791s  ts_start=1767234510.765
  user_feedback: none captured
  answer_numbers=['7498', '7453']
  answer_facts  =['NE-F3C0-10', '7498', '7453']
  golden_answer =
  golden_facts  =None
  goal_text     =current alarm list   query_lang=en
  answer_citations  =[]
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[-0.157, -0.0583, -0.0655, 0.2213] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run           2.791 ######### 271       108        0.00099 ok    stop
       in : show the current alarm list of NE-F3C0-10
       out: finished 'show the current alarm list of NE-F3C0-10' for NE-F3C0-10; the
       meta: model=adn-llm-72b  facts=[7498 7453]
       v3  : sys=210  cache_r=210  cost_det={cache_read:0.000158,completion:0.000648,prompt:0.000183}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan                0.085 #         309       293        0.00328 ok    stop
         in : task=current alarm list ne=NE-F3C0-10 window=15m; produce a step plan
         out: decompose into retrieval then aggregation; window=15m; noted for the ope
         meta: model=adn-llm-14b  ttft=0.0149  pv=pv-2026-04-canary
         v3  : sys=160  cache_w=160  cost_det={cache_write:0.0006,completion:0.00176,prompt:0.000927}  subgoal=decomposing the task steps on NE-F3C0-10 as part of the curr
  `- s02           tool        api_call            0.085 #         0         0          0.00020 ok    -
         in : GET /nbi/v1/ne/NE-F3C0-10/status?detail=true
         out: checked and recorded: northbound returned objects 7453 6804 1726 6429
         meta: tool=nbi.ne_status  params={ne_id:NE-F3C0-10,scope:ne}  facts=[7453 6804 1726 6429]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s03           tool        sql_query           0.881 ###       0         0          0.00020 ok    -
         in : SELECT kpi_ts,value FROM perf_15min WHERE ne='NE-F3C0-10' AND window='15
         out: ok - query settled; row ids 7547 9878 7498 3563
         meta: tool=perf_db.query  params={ne_id:NE-F3C0-10,severity:critical,time_window:15m}  facts=[7547 9878 7498 3563]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s04           guard       approve             0.292 #         127       76         0.00084 ok    -
         in : route the pending change on NE-F3C0-10 to the approver
         out: approval gate pass on NE-F3C0-10
         v3  : cost_det={completion:0.000456,prompt:0.000381}  verifier=v_no_forbidden_action:PASS
  `- s05           guard       approve             0.292 #         258       54         0.00110 ok    -
         in : approval gate for change on NE-F3C0-10
         out: change ticket for NE-F3C0-10: pass
         v3  : cost_det={completion:0.000324,prompt:0.000774}  verifier=v_no_forbidden_action:PASS
  `- s06           guard       approve             0.292 #         379       64         0.00152 ok    -
         in : route the pending change on NE-F3C0-10 to the approver
         out: approval gate pass on NE-F3C0-10
         v3  : cost_det={completion:0.000384,prompt:0.00114}  verifier=v_no_forbidden_action:PASS
  `- s07           guard       approve             0.292 #         221       95         0.00123 ok    -
         in : approval gate for change on NE-F3C0-10
         out: change ticket for NE-F3C0-10: pass
         v3  : cost_det={completion:0.00057,prompt:0.000663}  verifier=v_no_forbidden_action:PASS
  `- s08           llm         summarize           1.413 #####     705       217        0.00294 ok    stop
         in : write the final response for NE-F3C0-10 from evidence 1726 6429 7547 987
         out: summary drafted from 1726 6429 7547 9878 7498 3563 for NE-F3C0-10
         meta: model=adn-llm-72b  ttft=0.2770  pv=pv-2026-04-canary
         v3  : sys=213  cache_r=213  cost_det={cache_read:0.00016,completion:0.0013,prompt:0.00148}  verifier=v_numbers_traceable:PASS  subgoal=work on condensing the evidence to advance the current alarm

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['loop']
    intent=i0  pattern=p1  cell=i0|p1
    oracle dim_dev : O=1.00  P=0.50  L=0.54  C=0.79  R=0.55
    latency_true=2.788s  gen_quantiles={'C': 0.4117, 'L': 0.9126}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=['R4-00062-s04', 'R4-00062-s05', 'R4-00062-s06', 'R4-00062-s07']  human_label=None  drift_segment=None
    loop_true=True  mfr_true=0.0000  model_mix_true={'adn-llm-14b': 0.3163, 'adn-llm-72b': 0.6837}  feedback_available=False
    has_golden=False  key_fact_recall_true=n/a  fact_precision_true=n/a
    hallucinated_facts=[]
    query_lang_true=en  session_turn_count_true=5  subgoal_count=2
    plan_revision_true=0  goal_drift_true=False  arg_valid_true=1.0000  verifier_pass_true=1.0000
    citation_reachable_true=n/a  contradiction_true=0.0000  contradicted_count=0  fabricated_citation_count=0
    cache_read_true=423  cache_write_true=160  system_prompt_ratio_true=0.2568  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice5b-v0.5.1)
    S=70.7143  G=0.80  grade_abs=C  grade_rel=A  tier=0  novelty=True
    alert=False (rule=False stat=False)  cold_start=False  cell=None
    dims    : O=1.000  P=0.900  L=1.000  C=0.400  R=0.850
    contrib : O=+0.000  P=-1.934  L=+0.000  C=-6.307  R=-1.044   sum=-9.2857
    zero-residual: S-100G=-9.2857  |diff|=3.40e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.2198  a_cal=0.1105  conf=0.3500  anchor=anchor-R4-5188fdfc219089b9
    gates: {"novelty": 0.8}
    evidence (3 items, drill-down order):
      - [trace] branch_factor            span=-              value=8.0000      cell_median=4.0000      z=  +2.70 dev=0.3911
      - [trace] loop_count               span=-              value=2.0000      cell_median=0.0000      z= +50.00 dev=0.3686
      - [span ] tok                      span=R4-00062-s06   value=443.0000    peer_median=339.0000    z=  +0.57 dev=0.1136 (L3/L1span action=approve)
```

### 样本 E：token_bloat —— R4-00047

某个 LLM 步骤的 token 被放大 4~10 倍，耗时不变。只有成本维（C）会崩，时延维不崩——用来验证五维不会互相污染。

```text
==============================================================================
TRACE R4-00047   [intent0: NE-1FDB-15 在 5m 内的当前告警清单是什么]
  ontology=ontA  session=sess-00012  turn=2/2  spans=5  wall=2.587s  ts_start=1767232368.948
  user_feedback: none captured
  answer_numbers=['4847', '6175']
  answer_facts  =['NE-1FDB-15', '4847', '6175']
  golden_answer =
  golden_facts  =None
  goal_text     =当前告警清单   query_lang=zh
  answer_citations  =[]
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[0.0176, -0.0818, -0.2786, 0.1306] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run           2.587 ######### 143       49         0.00040 ok    stop
       in : NE-1FDB-15 在 5m 内的当前告警清单是什么
       out: 'NE-1FDB-15 在 5m 内的当前告警清单是什么' on NE-1FDB-15 resolved; see 4847, 6175
       meta: model=adn-llm-72b  facts=[4847 6175]
       v3  : sys=143  cache_r=143  cost_det={cache_read:0.000107,completion:0.000294}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan                1.079 ####      2704      689        0.01190 ok    stop
         in : task=当前告警清单 ne=NE-1FDB-15 window=5m; produce a step plan
         out: decompose into retrieval then aggregation; window=5m
         meta: model=adn-llm-14b  ttft=0.0745  pv=pv-2026-03
         v3  : sys=155  cache_r=155  cost_det={cache_read:0.000116,completion:0.00413,prompt:0.00765}  subgoal=步骤目标：拆解任务步骤，服务于当前告警清单
  `- s02           tool        sql_query           0.722 ###       0         0          0.00020 ok    -
         in : SELECT kpi_ts,value FROM perf_15min WHERE ne='NE-1FDB-15' AND window='5m
         out: query settled; row ids 4847 6175
         meta: tool=alarm_db.query  level=WARNING  msg=slow query above soft limit  params={ne_id:NE-1FDB-15,severity:minor,time_window:5m}  facts=[4847 6175]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s03           guard       verify              0.722 ###       103       25         0.00046 ok    -
         in : policy check on pending action for NE-1FDB-15
         out: policy evaluation on NE-1FDB-15: pass
         v3  : cost_det={completion:0.00015,prompt:0.000309}  verifier=v_no_forbidden_action:PASS
  `- s04           llm         summarize           0.679 ##        473       83         0.00144 ok    stop
         in : condense evidence 4847 6175 into an operator-facing answer
         out: answer composed citing 4847 6175 for NE-1FDB-15
         meta: model=adn-llm-72b  ttft=0.1503  pv=pv-2026-03
         v3  : sys=213  cache_r=213  cost_det={cache_read:0.00016,completion:0.000498,prompt:0.00078}  verifier=v_numbers_traceable:PASS  subgoal=推进当前告警清单：归纳证据

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['token_bloat']
    intent=i0  pattern=p1  cell=i0|p1
    oracle dim_dev : O=1.00  P=1.00  L=0.53  C=0.12  R=1.00
    latency_true=2.584s  gen_quantiles={'C': 0.0258, 'L': 0.9397}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=['R4-00047-s01']  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.0000  model_mix_true={'adn-llm-14b': 0.8194, 'adn-llm-72b': 0.1806}  feedback_available=False
    has_golden=False  key_fact_recall_true=n/a  fact_precision_true=n/a
    hallucinated_facts=[]
    query_lang_true=zh  session_turn_count_true=2  subgoal_count=2
    plan_revision_true=0  goal_drift_true=False  arg_valid_true=1.0000  verifier_pass_true=1.0000
    citation_reachable_true=n/a  contradiction_true=0.0000  contradicted_count=0  fabricated_citation_count=0
    cache_read_true=511  cache_write_true=0  system_prompt_ratio_true=0.1493  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice5b-v0.5.1)
    S=87.8500  G=1.00  grade_abs=B  grade_rel=C  tier=0  novelty=False
    alert=False (rule=False stat=False)  cold_start=False  cell=i0xp0
    dims    : O=1.000  P=1.000  L=0.612  C=0.689  R=1.000
    contrib : O=+0.000  P=+0.000  L=-6.906  C=-5.244  R=+0.000   sum=-12.1500
    zero-residual: S-100G=-12.1500  |diff|=2.10e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.2307  a_cal=0.1188  conf=0.9809  anchor=anchor-R4-5188fdfc219089b9
    evidence (3 items, drill-down order):
      - [trace] latency_total            span=R4-00047-s00   value=2.5867      cell_median=1.5924      z=  +1.14 dev=0.1806
      - [trace] tokens_total             span=R4-00047-s01   value=4269.0000   cell_median=3002.0000   z=  +0.86 dev=0.1581
      - [span ] tok                      span=R4-00047-s01   value=3393.0000   peer_median=1101.0000   z=  +4.19 dev=0.3482 (L3/L3span action=plan)
```

### 样本 F：illegal_step —— R4-00085

插入了本体禁止的动作（如 `force_delete` / `skip_approval_execute`）。这是确定性违规，走规则闸门（alert_rule=True）而不是统计异常。

```text
==============================================================================
TRACE R4-00085   [intent1: trace the degradation root cause for NE-A9DC-51 over 15m and rank the candidate factors]
  ontology=ontA  session=sess-00022  turn=3/6  spans=8  wall=1.907s  ts_start=1767237839.537
  user_feedback: abandoned=False human_takeover=False retry=False thumbs=None
  answer_numbers=['6519']
  answer_facts  =['NE-A9DC-51', '6519']
  golden_answer =
  golden_facts  =None
  goal_text     =degradation root cause   query_lang=en
  answer_citations  =['runbook://adn/alarm-clear-procedure#L12']
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[0.0996, -0.1406, -0.3275, 0.3165] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run           1.907 ######### 385       154        0.00171 ok    stop
       in : trace the degradation root cause for NE-A9DC-51 over 15m and rank the ca
       out: completed 'trace the degradation root cause for NE-A9DC-51 over 15m and 
       meta: model=adn-llm-14b  facts=[6519]
       v3  : sys=165  cache_r=165  cost_det={cache_read:0.000124,completion:0.000924,prompt:0.00066}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan                1.019 #####     344       240        0.00197 ok    stop
         in : task=degradation root cause ne=NE-A9DC-51 window=15m; produce a step pla
         out: decompose into retrieval then aggregation; window=15m (window 15m)
         meta: model=adn-llm-72b  ttft=0.2302  pv=pv-2026-03
         v3  : sys=223  cache_r=223  cost_det={cache_read:0.000167,completion:0.00144,prompt:0.000363}  subgoal=work on decomposing the task steps to advance the degradatio
  `- s04           guard       verify              1.019 #####     427       23         0.00142 ok    -
         in : policy check on pending action for NE-A9DC-51
         out: verdict pass for NE-A9DC-51
         v3  : cost_det={completion:0.000138,prompt:0.00128}  verifier=v_no_forbidden_action:PASS
  `- s02           tool        force_delete        0.199 #         0         0          0.00020 ok    -
         in : drop records on NE-A9DC-51 skipping the ticket flow
         out: ok - objects removed on NE-A9DC-51: 8206 6618
         meta: tool=nbi.ne_force_delete  facts=[8206 6618]
         v3  : cost_det={tool_call:0.0002}
    `- s02-n1        tool        force_delete        0.119 #         0         0          0.00020 ok    -
           in : nested force_delete call for NE-A9DC-51
           out: ok - objects removed on NE-A9DC-51: 8206 6618
           meta: tool=nbi.ne_force_delete  facts=[8206 6618]
           v3  : cost_det={tool_call:0.0002}
  `- s03           guard       verify              0.099 #         378       59         0.00149 ok    -
         in : policy check on pending action for NE-A9DC-51
         out: policy evaluation on NE-A9DC-51: block - policy violation
         v3  : cost_det={completion:0.000354,prompt:0.00113}  verifier=v_no_forbidden_action:FAIL(forbidden action before gate: force_delete)
  `- s05           retrieval   retrieve_kb         0.746 ####      657       0          0.00197 ok    -
         in : runbook search: degradation root cause (ne=NE-A9DC-51)
         out: ok - matched runbook evidence: 9676 9547 9667 6519
         meta: tool=kb.history_search  params={query:12345,top_k:5}  facts=[9676 9547 9667 6519]
         v3  : cost_det={prompt:0.00197}  arg_valid=False  retrieved=[runbook://adn/alarm-clear-procedure#L12]
  `- s06           llm         summarize           0.746 ####      916       529        0.00542 ok    stop
         in : condense evidence 8206 6618 9676 9547 9667 6519 into an operator-facing 
         out: step done - summary drafted from 8206 6618 9676 9547 9667 6519
         meta: model=adn-llm-72b  ttft=0.1769  pv=pv-2026-03
         v3  : sys=224  cache_r=224  cost_det={cache_read:0.000168,completion:0.00317,prompt:0.00208}  verifier=v_numbers_traceable:PASS  subgoal=step goal: condensing the evidence, serving the degradation 

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['illegal_step']
    intent=i1  pattern=p3  cell=i1|p3
    oracle dim_dev : O=1.00  P=0.05  L=0.83  C=0.64  R=1.00
    latency_true=1.904s  gen_quantiles={'C': 0.7109, 'L': 0.337}
    process_flags={'illegal_step': True, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=['R4-00085-s02']  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.0308  model_mix_true={'adn-llm-14b': 0.2099, 'adn-llm-72b': 0.7901}  feedback_available=True
    has_golden=False  key_fact_recall_true=n/a  fact_precision_true=n/a
    hallucinated_facts=[]
    query_lang_true=en  session_turn_count_true=6  subgoal_count=2
    plan_revision_true=0  goal_drift_true=False  arg_valid_true=0.0000  verifier_pass_true=0.7500
    citation_reachable_true=1.0000  contradiction_true=0.0000  contradicted_count=0  fabricated_citation_count=0
    cache_read_true=612  cache_write_true=0  system_prompt_ratio_true=0.1970  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice5b-v0.5.1)
    S=4.0113  G=0.04  grade_abs=D  grade_rel=D  tier=2  novelty=False
    alert=True (rule=True stat=False)  cold_start=False  cell=i2xp2
    dims    : O=1.000  P=0.700  L=1.000  C=0.748  R=1.000
    contrib : O=+0.000  P=-0.303  L=+0.000  C=-0.185  R=+0.000   sum=-0.4887
    zero-residual: S-100G=-0.4887  |diff|=3.60e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.9082  a_cal=0.9548  conf=0.9567  anchor=anchor-R4-5188fdfc219089b9
    gates: {"forbidden_action": 0.3, "guard_violation": 0.15}
    evidence (3 items, drill-down order):
      - [trace] guard_hits               span=-              value=1.0000      cell_median=0.0000      z= +50.00 dev=0.3817
      - [trace] n_spans                  span=-              value=8.0000      cell_median=5.0000      z=  +2.02 dev=0.3536
      - [span ] tok                      span=R4-00085-s05   value=657.0000    peer_median=458.5000    z=  +0.83 dev=0.1607 (L3/L3span action=retrieve_kb)
```

### 样本 G：truncation（带 golden） —— R4-00636

根 Span 的 `finish_reason=length`，答案被截断，结果维（O）重罚。

这条带 golden。与上一个样本对着看：截断只压 `key_fact_recall_true`，precision 仍为 1.00——说出来的都对，只是没说完。生成器故意把“不完整”与“不忠实”做成可分离的两类，否则O 维会把两种完全不同的失败打成同一个分。

```text
==============================================================================
TRACE R4-00636   [intent2: write the configuration change plan for NE-7D22-11 and list the impacted objects]
  ontology=ontA  session=sess-00141  turn=4/7  spans=7  wall=54.395s  ts_start=1767317175.277
  user_feedback: none captured
  answer_numbers=['1153', '7999', '6055', '45']
  answer_facts  =['NE-7D22-11', '1153', '7999', '6055', '45']
  golden_answer =expected answer for NE-7D22-11 (write the configuration change plan for NE-7D22-11 and list the impacted objects): 1153, 7999, 6055, 9143
  golden_facts  =['NE-7D22-11', '1153', '7999', '6055', '9143']
  goal_text     =configuration change plan   query_lang=en
  answer_citations  =['doc://policy/change-approval-rules#L7', 'runbook://adn/alarm-clear-procedure#L1508', 'runbook://adn/ne-health-check#L1184']
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[0.1802, -0.3865, 0.1354, 0.2403] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run          54.395 ######### 440       176        0.00207 ok    length
       in : write the configuration change plan for NE-7D22-11 and list the impacted
       out: operator summary for NE-7D22-11 (write the configuration change plan for
       meta: model=adn-llm-14b  facts=[1153 7999 6055 45]
       v3  : sys=138  cache_r=138  cost_det={cache_read:0.000104,completion:0.00106,prompt:0.000906}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan               11.901 ##        946       539        0.00562 ok    stop
         in : task=configuration change plan ne=NE-7D22-11 window=15m; produce a step 
         out: step list drafted for NE-7D22-11;  candidate actions for NE-7D22-11
         meta: model=adn-llm-72b  ttft=1.4000  pv=pv-2026-03
         v3  : sys=199  cache_r=199  cost_det={cache_read:0.000149,completion:0.00323,prompt:0.00224}  subgoal=work on decomposing the task steps to advance the configurat
  `- s02           tool        api_call            1.996 #         0         0          0.00020 ok    -
         in : GET /nbi/v1/ne/NE-7D22-11/status?detail=true
         out: response payload ids: 5994 7698 6249
         meta: tool=nbi.alarm_list  params={ne_id:NE-7D22-11,scope:ne}  facts=[5994 7698 6249]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s03           retrieval   schema_retrieval    0.920 #         562       0          0.00169 ok    -
         in : lookup schema for alarm tables of NE-7D22-11
         out: table metadata resolved: 6055 5330 (window 15m)
         meta: tool=catalog.table_schema  params={table:kpi_15min}  facts=[6055 5330]
         v3  : cost_det={prompt:0.00169}  arg_valid=True  retrieved=[doc://policy/change-approval-rules#L7 doc://topology/subnetwork-east-map runbook://adn/capacity-expansion#L25]
  `- s04           guard       approve             7.376 #         364       77         0.00155 ok    -
         in : approval gate for change on NE-7D22-11
         out: change ticket for NE-7D22-11: pass
         v3  : cost_det={completion:0.000462,prompt:0.00109}  verifier=v_no_forbidden_action:PASS
  `- s05           tool        sql_query           4.278 #         0         0          0.00020 ok    -
         in : SELECT alarm_id,severity FROM current_alarms WHERE ne='NE-7D22-11' AND w
         out: ok - rows returned: 1153 3858 7999 5355
         meta: tool=alarm_db.query  params={ne_id:NE-7D22-11,severity:minor,time_window:15m}  facts=[1153 3858 7999 5355]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s06           llm         summarize          25.294 ####      977       58         0.00276 ok    stop
         in : write the final response for NE-7D22-11 from evidence 6055 5330 1153 385
         out: ok - answer composed citing 6055 5330 1153 3858 7999 5355
         meta: model=adn-llm-72b  ttft=5.7142  pv=pv-2026-03
         v3  : sys=231  cache_r=231  cost_det={cache_read:0.000173,completion:0.000348,prompt:0.00224}  verifier=v_numbers_traceable:FAIL(answer number absent from the evidence pool)  subgoal=work on condensing the evidence to advance the config

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['truncation']
    intent=i2  pattern=p2  cell=i2|p2
    oracle dim_dev : O=0.35  P=1.00  L=0.65  C=0.60  R=1.00
    latency_true=54.392s  gen_quantiles={'C': 0.804, 'L': 0.6903}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=[]  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.0000  model_mix_true={'adn-llm-14b': 0.1964, 'adn-llm-72b': 0.8036}  feedback_available=False
    has_golden=True  key_fact_recall_true=0.8000  fact_precision_true=0.8000
    hallucinated_facts=['45']
    query_lang_true=en  session_turn_count_true=7  subgoal_count=2
    plan_revision_true=0  goal_drift_true=False  arg_valid_true=1.0000  verifier_pass_true=0.6667
    citation_reachable_true=0.3333  contradiction_true=0.0000  contradicted_count=0  fabricated_citation_count=2
    cache_read_true=568  cache_write_true=0  system_prompt_ratio_true=0.1727  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice5b-v0.5.1)
    S=19.3362  G=0.25  grade_abs=D  grade_rel=D  tier=2  novelty=False
    alert=True (rule=True stat=False)  cold_start=False  cell=i1xp1
    dims    : O=0.729  P=1.000  L=0.575  C=0.730  R=1.000
    contrib : O=-2.793  P=+0.000  L=-1.829  C=-1.042  R=+0.000   sum=-5.6638
    zero-residual: S-100G=-5.6638  |diff|=2.30e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.9249  a_cal=0.9599  conf=0.9600  anchor=anchor-R4-5188fdfc219089b9
    gates: {"t0_result_broken": 0.25}
    evidence (3 items, drill-down order):
      - [trace] traceable_number_ratio   span=-              value=0.7500      cell_median=1.0000      z= -50.00 dev=0.3746
      - [trace] branch_factor            span=-              value=6.0000      cell_median=4.0000      z=  +1.35 dev=0.2112
      - [span ] dur                      span=R4-00636-s04   value=7.3764      peer_median=2.8723      z=  +2.35 dev=0.2697 (L3/L3span action=approve)
```

### 样本 H：missing_step —— R4-00024

本体要求的必须步骤被删掉一个，过程维（P）扣分。

```text
==============================================================================
TRACE R4-00024   [intent0: what is the current alarm list for NE-ABDD-19 over the last 5m]
  ontology=ontA  session=sess-00005  turn=2/7  spans=4  wall=1.326s  ts_start=1767229060.508
  user_feedback: none captured
  answer_numbers=['4915']
  answer_facts  =['NE-ABDD-19', '4915']
  golden_answer =
  golden_facts  =None
  goal_text     =current alarm list   query_lang=en
  answer_citations  =[]
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[-0.0592, -0.0468, 0.0956, 0.0825] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run           1.326 ######### 395       158        0.00182 ok    stop
       in : what is the current alarm list for NE-ABDD-19 over the last 5m
       out: what is the current alarm list for NE-ABDD-19 over the last 5m for NE-AB
       meta: model=adn-llm-14b  facts=[4915]
       v3  : sys=141  cache_r=141  cost_det={cache_read:0.000106,completion:0.000948,prompt:0.000762}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan                0.722 #####     721       348        0.00375 ok    stop
         in : decompose request from NE-ABDD-19 over 5m into executable steps
         out: decompose into retrieval then aggregation; window=5m; payload attached t
         meta: model=adn-llm-72b  ttft=0.0456  pv=pv-2026-03
         v3  : sys=223  cache_r=223  cost_det={cache_read:0.000167,completion:0.00209,prompt:0.00149}  subgoal=advance the current alarm list by decomposing the task steps
  `- s02           tool        api_call            0.123 #         0         0          0.00020 ok    -
         in : GET /nbi/v1/ne/NE-ABDD-19/status?detail=true
         out: northbound returned objects 4915 3066 (window 5m)
         meta: tool=nbi.ne_status  params={ne_id:NE-ABDD-19,scope:ne}  facts=[4915 3066]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s03           llm         summarize           0.402 ###       828       345        0.00412 ok    stop
         in : write the final response for NE-ABDD-19 from evidence 4915 3066
         out: summary drafted from 4915 3066 for NE-ABDD-19
         meta: model=adn-llm-72b  ttft=0.0123  pv=pv-2026-03
         v3  : sys=193  cache_r=193  cost_det={cache_read:0.000145,completion:0.00207,prompt:0.00191}  verifier=v_numbers_traceable:PASS  subgoal=search the training vault for slide decks

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['missing_step']
    intent=i0  pattern=p1  cell=i0|p1
    oracle dim_dev : O=1.00  P=0.80  L=0.61  C=0.63  R=1.00
    latency_true=1.323s  gen_quantiles={'C': 0.7308, 'L': 0.7769}
    process_flags={'illegal_step': False, 'missing_step': True, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=[]  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.0000  model_mix_true={'adn-llm-14b': 0.1979, 'adn-llm-72b': 0.8021}  feedback_available=False
    has_golden=False  key_fact_recall_true=n/a  fact_precision_true=n/a
    hallucinated_facts=[]
    query_lang_true=en  session_turn_count_true=7  subgoal_count=2
    plan_revision_true=0  goal_drift_true=True  arg_valid_true=1.0000  verifier_pass_true=1.0000
    citation_reachable_true=n/a  contradiction_true=0.0000  contradicted_count=0  fabricated_citation_count=0
    cache_read_true=557  cache_write_true=0  system_prompt_ratio_true=0.2865  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice5b-v0.5.1)
    S=77.9704  G=0.80  grade_abs=B  grade_rel=A  tier=0  novelty=True
    alert=False (rule=False stat=False)  cold_start=False  cell=None
    dims    : O=1.000  P=0.900  L=1.000  C=1.000  R=1.000
    contrib : O=+0.000  P=-2.030  L=+0.000  C=+0.000  R=+0.000   sum=-2.0296
    zero-residual: S-100G=-2.0296  |diff|=2.50e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.1095  a_cal=0.0517  conf=0.3500  anchor=anchor-R4-5188fdfc219089b9
    gates: {"novelty": 0.8}
    evidence (3 items, drill-down order):
      - [trace] tokens_total             span=R4-00024-s03   value=2795.0000   cell_median=3224.0000   z=  -0.28 dev=0.0542
      - [trace] cost_total               span=R4-00024-s03   value=0.0099      cell_median=0.0116      z=  -0.30 dev=0.0505
      - [span ] tok                      span=R4-00024-s00   value=553.0000    peer_median=449.0000    z=  +0.53 dev=0.1173 (L3/L1span action=agent_run)
```

## 六、v3 共生缺陷样本（附录 A 新增特征的原始证据）

下面这些**不是**独立的异常类型，而是叠加在已异常轨迹上的共生缺陷。每一个都由
`bench/coverage.truth_agreement()` 在全部轨迹上做双向等价校验（内核特征 ⟺ 生成器真值），
任何一条对不上都会让构建直接失败，而不是只在报告里留一行警告。


### v3 样本 A：plan_revision —— R4-00007

入口步骤（ontA 的 `plan`、ontB 的 `intent_parse`）出现了两次，第二次的时间区间**嵌套在**第一次之内——智能体在一步还没走完时就重开了计划。`kernel/cluster.collapse()` 会折叠相邻重复，所以模式视图看到的骨架完全不变，只有 `plan_revision_count` 能看见它。这也是该特征被定义成“时间包含”而不是“计数减一”的原因：循环注入器同样可能选中入口步骤，计数减一会把一次循环读成两次计划修订。

```text
==============================================================================
TRACE R4-00007   [intent0: 请列出网元 NE-8F31-31 当前告警清单中的每一条记录]
  ontology=ontA  session=sess-00001  turn=1/5  spans=5  wall=1.489s  ts_start=1767226609.897
  user_feedback: abandoned=False human_takeover=False retry=False thumbs=1
  answer_numbers=['3673', '6839']
  answer_facts  =['NE-8F31-31', '3673', '6839']
  golden_answer =expected answer for NE-8F31-31 (请列出网元 NE-8F31-31 当前告警清单中的每一条记录): 3673, 6839
  golden_facts  =['NE-8F31-31', '3673', '6839']
  goal_text     =当前告警清单   query_lang=zh
  answer_citations  =[]
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[0.1369, -0.0719, -0.2589, 0.1545] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run           1.489 ######### 174       60         0.00147 ok    stop
       in : 请列出网元 NE-8F31-31 当前告警清单中的每一条记录
       out: finished '请列出网元 NE-8F31-31 当前告警清单中的每一条记录' for NE-8F31-31; the relevant f
       meta: model=adn-llm-14b  facts=[3673 6839]
       v3  : sys=156  cache_w=156  cost_det={cache_write:0.000585,completion:0.00036,prompt:0.000522}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan                0.781 #####     633       103        0.00307 ok    stop
         in : decompose request from NE-8F31-31 over 24h into executable steps
         out: attempt finished, decompose into retrieval then aggregation; window=24h
         meta: model=adn-llm-14b  ttft=0.2332  pv=pv-2026-03
         v3  : sys=147  cache_w=147  cost_det={cache_write:0.000551,completion:0.000618,prompt:0.0019}  subgoal=针对当前告警清单进行拆解任务步骤（窗口 24h）
  `- s02           llm         plan                0.312 ##        369       167        0.00176 ok    stop
         in : task=当前告警清单 ne=NE-8F31-31 window=24h; produce a step plan
         out: checked and recorded: step list drafted for NE-8F31-31;  candidate actio
         meta: model=adn-llm-14b  ttft=0.0793  pv=pv-2026-03
         v3  : sys=157  cache_r=157  cost_det={cache_read:0.000118,completion:0.001,prompt:0.000636}  subgoal=针对当前告警清单进行拆解任务步骤（窗口 24h）
  `- s03           tool        sql_query           0.261 ##        0         0          0.00020 ok    -
         in : SELECT kpi_ts,value FROM perf_15min WHERE ne='NE-8F31-31' AND window='24
         out: step done - query settled; row ids 3673 6839
         meta: tool=perf_db.query  params={ne_id:NE-8F31-31,severity:major,time_window:24h}  facts=[3673 6839]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s04           llm         summarize           0.386 ##        377       145        0.00288 ok    stop
         in : condense evidence 3673 6839 into an operator-facing answer
         out: checked and recorded: answer composed citing 3673 6839
         meta: model=adn-llm-72b  ttft=0.0425  pv=pv-2026-03
         v3  : sys=234  cache_w=234  cost_det={cache_write:0.000878,completion:0.00087,prompt:0.00113}  verifier=v_numbers_traceable:PASS  subgoal=围绕当前告警清单执行归纳证据

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=False  anomaly_types=[]
    intent=i0  pattern=p1  cell=i0|p1
    oracle dim_dev : O=1.00  P=1.00  L=0.87  C=0.97  R=1.00
    latency_true=1.486s  gen_quantiles={'C': 0.0643, 'L': 0.2632}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=[]  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.0000  model_mix_true={'adn-llm-14b': 0.7426, 'adn-llm-72b': 0.2574}  feedback_available=True
    has_golden=True  key_fact_recall_true=1.0000  fact_precision_true=1.0000
    hallucinated_facts=[]
    query_lang_true=zh  session_turn_count_true=5  subgoal_count=3
    plan_revision_true=1  goal_drift_true=False  arg_valid_true=1.0000  verifier_pass_true=1.0000
    citation_reachable_true=n/a  contradiction_true=0.0000  contradicted_count=0  fabricated_citation_count=0
    cache_read_true=157  cache_write_true=537  system_prompt_ratio_true=0.4469  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice5b-v0.5.1)
    S=95.5290  G=1.00  grade_abs=A  grade_rel=B  tier=0  novelty=False
    alert=False (rule=False stat=False)  cold_start=False  cell=i0xp0
    dims    : O=1.000  P=1.000  L=0.825  C=0.894  R=1.000
    contrib : O=+0.000  P=+0.000  L=-2.830  C=-1.641  R=+0.000   sum=-4.4710
    zero-residual: S-100G=-4.4710  |diff|=4.60e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.1684  a_cal=0.0780  conf=0.9809  anchor=anchor-R4-5188fdfc219089b9
    evidence (3 items, drill-down order):
      - [trace] retry_count              span=-              value=1.0000      cell_median=0.0000      z= +50.00 dev=0.1855
      - [trace] branch_factor            span=-              value=4.0000      cell_median=3.2500      z=  +0.67 dev=0.0837
      - [span ] dur                      span=R4-00007-s01   value=0.7811      peer_median=0.4455      z=  +0.99 dev=0.1533 (L3/L3span action=plan)
```

### v3 样本 B：goal_drift —— R4-00024

某个 `subgoal_text` 与本条轨迹的 `goal_text` **没有任何内容词重叠**——智能体在这一步跑偏了。特征侧用词元包含率 `1 - |G ∩ S| / |G|` 度量：跑偏时恰好为 1.0，在轨时恰好为 0.0，所以 `goal_drift_max >= 0.5` 与真值构成严格的双向等价。生成器为此专门过滤掉任何与目标共享词元的绕路模板，否则真值会声称漂移而数据里量不出来。

```text
==============================================================================
TRACE R4-00024   [intent0: what is the current alarm list for NE-ABDD-19 over the last 5m]
  ontology=ontA  session=sess-00005  turn=2/7  spans=4  wall=1.326s  ts_start=1767229060.508
  user_feedback: none captured
  answer_numbers=['4915']
  answer_facts  =['NE-ABDD-19', '4915']
  golden_answer =
  golden_facts  =None
  goal_text     =current alarm list   query_lang=en
  answer_citations  =[]
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[-0.0592, -0.0468, 0.0956, 0.0825] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run           1.326 ######### 395       158        0.00182 ok    stop
       in : what is the current alarm list for NE-ABDD-19 over the last 5m
       out: what is the current alarm list for NE-ABDD-19 over the last 5m for NE-AB
       meta: model=adn-llm-14b  facts=[4915]
       v3  : sys=141  cache_r=141  cost_det={cache_read:0.000106,completion:0.000948,prompt:0.000762}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan                0.722 #####     721       348        0.00375 ok    stop
         in : decompose request from NE-ABDD-19 over 5m into executable steps
         out: decompose into retrieval then aggregation; window=5m; payload attached t
         meta: model=adn-llm-72b  ttft=0.0456  pv=pv-2026-03
         v3  : sys=223  cache_r=223  cost_det={cache_read:0.000167,completion:0.00209,prompt:0.00149}  subgoal=advance the current alarm list by decomposing the task steps
  `- s02           tool        api_call            0.123 #         0         0          0.00020 ok    -
         in : GET /nbi/v1/ne/NE-ABDD-19/status?detail=true
         out: northbound returned objects 4915 3066 (window 5m)
         meta: tool=nbi.ne_status  params={ne_id:NE-ABDD-19,scope:ne}  facts=[4915 3066]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s03           llm         summarize           0.402 ###       828       345        0.00412 ok    stop
         in : write the final response for NE-ABDD-19 from evidence 4915 3066
         out: summary drafted from 4915 3066 for NE-ABDD-19
         meta: model=adn-llm-72b  ttft=0.0123  pv=pv-2026-03
         v3  : sys=193  cache_r=193  cost_det={cache_read:0.000145,completion:0.00207,prompt:0.00191}  verifier=v_numbers_traceable:PASS  subgoal=search the training vault for slide decks

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['missing_step']
    intent=i0  pattern=p1  cell=i0|p1
    oracle dim_dev : O=1.00  P=0.80  L=0.61  C=0.63  R=1.00
    latency_true=1.323s  gen_quantiles={'C': 0.7308, 'L': 0.7769}
    process_flags={'illegal_step': False, 'missing_step': True, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=[]  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.0000  model_mix_true={'adn-llm-14b': 0.1979, 'adn-llm-72b': 0.8021}  feedback_available=False
    has_golden=False  key_fact_recall_true=n/a  fact_precision_true=n/a
    hallucinated_facts=[]
    query_lang_true=en  session_turn_count_true=7  subgoal_count=2
    plan_revision_true=0  goal_drift_true=True  arg_valid_true=1.0000  verifier_pass_true=1.0000
    citation_reachable_true=n/a  contradiction_true=0.0000  contradicted_count=0  fabricated_citation_count=0
    cache_read_true=557  cache_write_true=0  system_prompt_ratio_true=0.2865  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice5b-v0.5.1)
    S=77.9704  G=0.80  grade_abs=B  grade_rel=A  tier=0  novelty=True
    alert=False (rule=False stat=False)  cold_start=False  cell=None
    dims    : O=1.000  P=0.900  L=1.000  C=1.000  R=1.000
    contrib : O=+0.000  P=-2.030  L=+0.000  C=+0.000  R=+0.000   sum=-2.0296
    zero-residual: S-100G=-2.0296  |diff|=2.50e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.1095  a_cal=0.0517  conf=0.3500  anchor=anchor-R4-5188fdfc219089b9
    gates: {"novelty": 0.8}
    evidence (3 items, drill-down order):
      - [trace] tokens_total             span=R4-00024-s03   value=2795.0000   cell_median=3224.0000   z=  -0.28 dev=0.0542
      - [trace] cost_total               span=R4-00024-s03   value=0.0099      cell_median=0.0116      z=  -0.30 dev=0.0505
      - [span ] tok                      span=R4-00024-s00   value=553.0000    peer_median=449.0000    z=  +0.53 dev=0.1173 (L3/L1span action=agent_run)
```

### v3 样本 C：invalid_tool_arg —— R4-00011

工具入参违反了本体的 `param_schema`（枚举越界 / 前缀不符）。`arg_valid` 是**测量**出来的而不是断言的：生成器构造完违规参数后会再跑一次同一个校验函数，只有确实判为违规才落库。循环与重试的副本共享同一份参数，所以一个违规组里的每个副本都同样违规——这是刻意的，否则 `(parent, action, 参数哈希)` 分组会被拆开，一个真循环就悄悄变成了非循环。

```text
==============================================================================
TRACE R4-00011   [intent0: 我需要 NE-BA00-59 的当前告警清单，若存在紧急告警请标记出来]
  ontology=ontA  session=sess-00001  turn=5/5  spans=4  wall=0.353s  ts_start=1767227184.876
  user_feedback: none captured
  answer_numbers=['3950', '4481']
  answer_facts  =['NE-BA00-59', '3950', '4481']
  golden_answer =
  golden_facts  =None
  goal_text     =当前告警清单   query_lang=zh
  answer_citations  =[]
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[-0.0031, 0.0244, -0.2369, 0.1454] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run           0.353 ######### 275       95         0.00104 ok    stop
       in : 我需要 NE-BA00-59 的当前告警清单，若存在紧急告警请标记出来
       out: NE-BA00-59 | 我需要 NE-BA00-59 的当前告警清单，若存在紧急告警请标记出来 | observed values 3950,
       meta: model=adn-llm-14b  facts=[3950 4481]
       v3  : sys=158  cache_r=158  cost_det={cache_read:0.000119,completion:0.00057,prompt:0.000351}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan                0.255 #######   686       221        0.00306 ok    stop
         in : task=当前告警清单 ne=NE-BA00-59 window=24h; produce a step plan
         out: step list drafted for NE-BA00-59;  candidate actions
         meta: model=adn-llm-14b  ttft=0.0569  pv=pv-2026-03
         v3  : sys=145  cache_r=145  cost_det={cache_read:0.000109,completion:0.00133,prompt:0.00162}  subgoal=针对当前告警清单进行拆解任务步骤（窗口 24h）
  `- s02           tool        sql_query           0.255 #######   0         0          0.00020 ok    -
         in : SELECT alarm_id,severity FROM current_alarms WHERE ne='NE-BA00-59' AND w
         out: rows returned: 4481 3950; nothing further required
         meta: tool=alarm_db.query  params={ne_id:NE-BA00-59,severity:minor,time_window:not-in-enum}  facts=[4481 3950]
         v3  : cost_det={tool_call:0.0002}  arg_valid=False
  `- s03           llm         summarize           0.077 ##        598       190        0.00352 ok    stop
         in : condense evidence 4481 3950 into an operator-facing answer
         out: answer composed citing 4481 3950 for NE-BA00-59
         meta: model=adn-llm-14b  ttft=0.0213  pv=pv-2026-03
         v3  : sys=157  cache_w=157  cost_det={cache_write:0.000589,completion:0.00114,prompt:0.00179}  verifier=v_numbers_traceable:PASS  subgoal=针对当前告警清单进行归纳证据（窗口 24h）

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=False  anomaly_types=[]
    intent=i0  pattern=p1  cell=i0|p1
    oracle dim_dev : O=1.00  P=1.00  L=0.99  C=0.85  R=1.00
    latency_true=0.350s  gen_quantiles={'C': 0.3088, 'L': 0.0289}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=[]  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.0000  model_mix_true={'adn-llm-14b': 1.0}  feedback_available=False
    has_golden=False  key_fact_recall_true=n/a  fact_precision_true=n/a
    hallucinated_facts=[]
    query_lang_true=zh  session_turn_count_true=5  subgoal_count=2
    plan_revision_true=0  goal_drift_true=False  arg_valid_true=0.0000  verifier_pass_true=1.0000
    citation_reachable_true=n/a  contradiction_true=0.0000  contradicted_count=0  fabricated_citation_count=0
    cache_read_true=303  cache_write_true=157  system_prompt_ratio_true=0.2951  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice5b-v0.5.1)
    S=98.8636  G=1.00  grade_abs=A  grade_rel=A  tier=0  novelty=False
    alert=False (rule=False stat=False)  cold_start=False  cell=i0xp0
    dims    : O=1.000  P=1.000  L=1.000  C=0.927  R=1.000
    contrib : O=+0.000  P=+0.000  L=+0.000  C=-1.136  R=+0.000   sum=-1.1364
    zero-residual: S-100G=-1.1364  |diff|=1.90e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.1114  a_cal=0.0524  conf=0.9809  anchor=anchor-R4-5188fdfc219089b9
    evidence (3 items, drill-down order):
      - [trace] cost_total               span=R4-00011-s01   value=0.0078      cell_median=0.0111      z=  -0.61 dev=0.0377
      - [trace] tokens_total             span=R4-00011-s01   value=2065.0000   cell_median=3002.0000   z=  -0.64 dev=0.0337
      - [span ] dur                      span=R4-00011-s02   value=0.2550      peer_median=0.2679      z=  -0.06 dev=0.0769 (L3/L3span action=sql_query)
```

### v3 样本 D：verifier_fail —— R4-00056

确定性校验器给出 FAIL。三个校验器全部是代码判定，没有任何生成式判官参与：`v_numbers_traceable`（答案里的数字必须能在证据池中找到）、`v_no_forbidden_action`（禁用动作不得被启动）、`v_answer_nonempty`（答案非空）。它们的结果是从落库记录本身反推出来的，而不是生成器的意图。

```text
==============================================================================
TRACE R4-00056   [intent0: which alarms are still active in the current alarm list of NE-E3D1-06]
  ontology=ontA  session=sess-00015  turn=3/3  spans=4  wall=1.770s  ts_start=1767233645.004
  user_feedback: abandoned=False human_takeover=False retry=False thumbs=-1
  answer_numbers=['6125', '55']
  answer_facts  =['NE-E3D1-06', '6125', '55']
  golden_answer =
  golden_facts  =None
  goal_text     =current alarm list   query_lang=en
  answer_citations  =['doc://topology/subnetwork-east-map#L1080', 'kb://history/incident-2025-1187#L1685']
  contradicted_facts=['6125']
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[0.1002, 0.104, -0.1067, 0.1272] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run           1.770 ######### 456       182        0.00211 ok    length
       in : which alarms are still active in the current alarm list of NE-E3D1-06
       out: operator summary for NE-E3D1-06 (which alarms are still active in the cu
       meta: model=adn-llm-14b  facts=[6125 55]
       v3  : sys=157  cache_r=157  cost_det={cache_read:0.000118,completion:0.00109,prompt:0.000897}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan                0.440 ##        612       437        0.00394 ok    stop
         in : task=current alarm list ne=NE-E3D1-06 window=1h; produce a step plan
         out: step done - step list drafted for NE-E3D1-06;  candidate actions
         meta: model=adn-llm-72b  ttft=0.0162  pv=pv-2026-03
         v3  : sys=232  cache_r=232  cost_det={cache_read:0.000174,completion:0.00262,prompt:0.00114}  subgoal=decomposing the task steps for the current alarm list
  `- s02           tool        sql_query           0.440 ##        0         0          0.00020 ok    -
         in : SELECT kpi_ts,value FROM perf_15min WHERE ne='NE-E3D1-06' AND window='1h
         out: checked and recorded: query settled; row ids 7271 6125
         meta: tool=perf_db.query  params={ne_id:NE-E3D1-06,severity:major,time_window:1h}  facts=[7271 6125]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s03           llm         summarize           1.269 ######    1491      688        0.00827 ok    stop
         in : condense evidence 7271 6125 into an operator-facing answer
         out: summary drafted from 7271 6125 (window 1h)
         meta: model=adn-llm-14b  ttft=0.1091  pv=pv-2026-03
         v3  : sys=145  cache_r=145  cost_det={cache_read:0.000109,completion:0.00413,prompt:0.00404}  verifier=v_numbers_traceable:FAIL(answer number absent from the evidence pool)  subgoal=step goal: condensing the evidence, serving the curren

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['truncation']
    intent=i0  pattern=p1  cell=i0|p1
    oracle dim_dev : O=0.35  P=1.00  L=0.57  C=0.59  R=1.00
    latency_true=1.767s  gen_quantiles={'C': 0.824, 'L': 0.8603}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=[]  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.0000  model_mix_true={'adn-llm-14b': 0.7287, 'adn-llm-72b': 0.2713}  feedback_available=True
    has_golden=False  key_fact_recall_true=n/a  fact_precision_true=n/a
    hallucinated_facts=[]
    query_lang_true=en  session_turn_count_true=3  subgoal_count=2
    plan_revision_true=0  goal_drift_true=False  arg_valid_true=1.0000  verifier_pass_true=0.5000
    citation_reachable_true=0.0000  contradiction_true=0.3333  contradicted_count=1  fabricated_citation_count=2
    cache_read_true=534  cache_write_true=0  system_prompt_ratio_true=0.2087  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice5b-v0.5.1)
    S=16.4107  G=0.25  grade_abs=D  grade_rel=D  tier=2  novelty=False
    alert=True (rule=True stat=False)  cold_start=False  cell=i0xp0
    dims    : O=0.440  P=1.000  L=0.766  C=0.704  R=1.000
    contrib : O=-6.701  P=+0.000  L=-0.814  C=-1.075  R=+0.000   sum=-8.5893
    zero-residual: S-100G=-8.5893  |diff|=1.40e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.9298  a_cal=0.9613  conf=0.9809  anchor=anchor-R4-5188fdfc219089b9
    gates: {"t0_result_broken": 0.25}
    evidence (3 items, drill-down order):
      - [trace] traceable_number_ratio   span=-              value=0.5000      cell_median=1.0000      z= -50.00 dev=0.3684
      - [trace] cost_total               span=R4-00056-s03   value=0.0145      cell_median=0.0111      z=  +0.64 dev=0.1367
      - [span ] dur                      span=R4-00056-s03   value=1.2691      peer_median=0.4515      z=  +2.12 dev=0.2388 (L3/L3span action=summarize)
```

### v3 样本 E：fabricated_citation —— R4-00056

答案引用了一个**格式完全合法**的定位符，但它不在本次检索到的结果集里。真实智能体的编造几乎从不是凭空造一个URL，而是把片段号写错——所以 `citation_reachability` 必须对着检索结果集算，而不是对着 URL 白名单或格式校验算。生成器正是这样伪造的：取一个真实定位符，把 `#L` 片段改到 1001~1900 区间。

```text
==============================================================================
TRACE R4-00056   [intent0: which alarms are still active in the current alarm list of NE-E3D1-06]
  ontology=ontA  session=sess-00015  turn=3/3  spans=4  wall=1.770s  ts_start=1767233645.004
  user_feedback: abandoned=False human_takeover=False retry=False thumbs=-1
  answer_numbers=['6125', '55']
  answer_facts  =['NE-E3D1-06', '6125', '55']
  golden_answer =
  golden_facts  =None
  goal_text     =current alarm list   query_lang=en
  answer_citations  =['doc://topology/subnetwork-east-map#L1080', 'kb://history/incident-2025-1187#L1685']
  contradicted_facts=['6125']
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[0.1002, 0.104, -0.1067, 0.1272] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run           1.770 ######### 456       182        0.00211 ok    length
       in : which alarms are still active in the current alarm list of NE-E3D1-06
       out: operator summary for NE-E3D1-06 (which alarms are still active in the cu
       meta: model=adn-llm-14b  facts=[6125 55]
       v3  : sys=157  cache_r=157  cost_det={cache_read:0.000118,completion:0.00109,prompt:0.000897}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan                0.440 ##        612       437        0.00394 ok    stop
         in : task=current alarm list ne=NE-E3D1-06 window=1h; produce a step plan
         out: step done - step list drafted for NE-E3D1-06;  candidate actions
         meta: model=adn-llm-72b  ttft=0.0162  pv=pv-2026-03
         v3  : sys=232  cache_r=232  cost_det={cache_read:0.000174,completion:0.00262,prompt:0.00114}  subgoal=decomposing the task steps for the current alarm list
  `- s02           tool        sql_query           0.440 ##        0         0          0.00020 ok    -
         in : SELECT kpi_ts,value FROM perf_15min WHERE ne='NE-E3D1-06' AND window='1h
         out: checked and recorded: query settled; row ids 7271 6125
         meta: tool=perf_db.query  params={ne_id:NE-E3D1-06,severity:major,time_window:1h}  facts=[7271 6125]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s03           llm         summarize           1.269 ######    1491      688        0.00827 ok    stop
         in : condense evidence 7271 6125 into an operator-facing answer
         out: summary drafted from 7271 6125 (window 1h)
         meta: model=adn-llm-14b  ttft=0.1091  pv=pv-2026-03
         v3  : sys=145  cache_r=145  cost_det={cache_read:0.000109,completion:0.00413,prompt:0.00404}  verifier=v_numbers_traceable:FAIL(answer number absent from the evidence pool)  subgoal=step goal: condensing the evidence, serving the curren

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['truncation']
    intent=i0  pattern=p1  cell=i0|p1
    oracle dim_dev : O=0.35  P=1.00  L=0.57  C=0.59  R=1.00
    latency_true=1.767s  gen_quantiles={'C': 0.824, 'L': 0.8603}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=[]  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.0000  model_mix_true={'adn-llm-14b': 0.7287, 'adn-llm-72b': 0.2713}  feedback_available=True
    has_golden=False  key_fact_recall_true=n/a  fact_precision_true=n/a
    hallucinated_facts=[]
    query_lang_true=en  session_turn_count_true=3  subgoal_count=2
    plan_revision_true=0  goal_drift_true=False  arg_valid_true=1.0000  verifier_pass_true=0.5000
    citation_reachable_true=0.0000  contradiction_true=0.3333  contradicted_count=1  fabricated_citation_count=2
    cache_read_true=534  cache_write_true=0  system_prompt_ratio_true=0.2087  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice5b-v0.5.1)
    S=16.4107  G=0.25  grade_abs=D  grade_rel=D  tier=2  novelty=False
    alert=True (rule=True stat=False)  cold_start=False  cell=i0xp0
    dims    : O=0.440  P=1.000  L=0.766  C=0.704  R=1.000
    contrib : O=-6.701  P=+0.000  L=-0.814  C=-1.075  R=+0.000   sum=-8.5893
    zero-residual: S-100G=-8.5893  |diff|=1.40e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.9298  a_cal=0.9613  conf=0.9809  anchor=anchor-R4-5188fdfc219089b9
    gates: {"t0_result_broken": 0.25}
    evidence (3 items, drill-down order):
      - [trace] traceable_number_ratio   span=-              value=0.5000      cell_median=1.0000      z= -50.00 dev=0.3684
      - [trace] cost_total               span=R4-00056-s03   value=0.0145      cell_median=0.0111      z=  +0.64 dev=0.1367
      - [span ] dur                      span=R4-00056-s03   value=1.2691      peer_median=0.4515      z=  +2.12 dev=0.2388 (L3/L3span action=summarize)
```

### v3 样本 F：contradicted_evidence —— R4-00056

答案陈述了与证据相反的关系。注意它与幻觉的区别：矛盾涉及的事实**在**证据池里，只是关系被说反了。生成器只从`golden_facts ∩ answer_facts` 里采样，从结构上保证了这一点。特征侧的 `contradiction_rate` 仍标记为`needs_model`——数据集负责提供输入与真值，数值本身要等真实 NLI 模型接上才有意义。

```text
==============================================================================
TRACE R4-00056   [intent0: which alarms are still active in the current alarm list of NE-E3D1-06]
  ontology=ontA  session=sess-00015  turn=3/3  spans=4  wall=1.770s  ts_start=1767233645.004
  user_feedback: abandoned=False human_takeover=False retry=False thumbs=-1
  answer_numbers=['6125', '55']
  answer_facts  =['NE-E3D1-06', '6125', '55']
  golden_answer =
  golden_facts  =None
  goal_text     =current alarm list   query_lang=en
  answer_citations  =['doc://topology/subnetwork-east-map#L1080', 'kb://history/incident-2025-1187#L1685']
  contradicted_facts=['6125']
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[0.1002, 0.104, -0.1067, 0.1272] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run           1.770 ######### 456       182        0.00211 ok    length
       in : which alarms are still active in the current alarm list of NE-E3D1-06
       out: operator summary for NE-E3D1-06 (which alarms are still active in the cu
       meta: model=adn-llm-14b  facts=[6125 55]
       v3  : sys=157  cache_r=157  cost_det={cache_read:0.000118,completion:0.00109,prompt:0.000897}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan                0.440 ##        612       437        0.00394 ok    stop
         in : task=current alarm list ne=NE-E3D1-06 window=1h; produce a step plan
         out: step done - step list drafted for NE-E3D1-06;  candidate actions
         meta: model=adn-llm-72b  ttft=0.0162  pv=pv-2026-03
         v3  : sys=232  cache_r=232  cost_det={cache_read:0.000174,completion:0.00262,prompt:0.00114}  subgoal=decomposing the task steps for the current alarm list
  `- s02           tool        sql_query           0.440 ##        0         0          0.00020 ok    -
         in : SELECT kpi_ts,value FROM perf_15min WHERE ne='NE-E3D1-06' AND window='1h
         out: checked and recorded: query settled; row ids 7271 6125
         meta: tool=perf_db.query  params={ne_id:NE-E3D1-06,severity:major,time_window:1h}  facts=[7271 6125]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s03           llm         summarize           1.269 ######    1491      688        0.00827 ok    stop
         in : condense evidence 7271 6125 into an operator-facing answer
         out: summary drafted from 7271 6125 (window 1h)
         meta: model=adn-llm-14b  ttft=0.1091  pv=pv-2026-03
         v3  : sys=145  cache_r=145  cost_det={cache_read:0.000109,completion:0.00413,prompt:0.00404}  verifier=v_numbers_traceable:FAIL(answer number absent from the evidence pool)  subgoal=step goal: condensing the evidence, serving the curren

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['truncation']
    intent=i0  pattern=p1  cell=i0|p1
    oracle dim_dev : O=0.35  P=1.00  L=0.57  C=0.59  R=1.00
    latency_true=1.767s  gen_quantiles={'C': 0.824, 'L': 0.8603}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=[]  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.0000  model_mix_true={'adn-llm-14b': 0.7287, 'adn-llm-72b': 0.2713}  feedback_available=True
    has_golden=False  key_fact_recall_true=n/a  fact_precision_true=n/a
    hallucinated_facts=[]
    query_lang_true=en  session_turn_count_true=3  subgoal_count=2
    plan_revision_true=0  goal_drift_true=False  arg_valid_true=1.0000  verifier_pass_true=0.5000
    citation_reachable_true=0.0000  contradiction_true=0.3333  contradicted_count=1  fabricated_citation_count=2
    cache_read_true=534  cache_write_true=0  system_prompt_ratio_true=0.2087  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice5b-v0.5.1)
    S=16.4107  G=0.25  grade_abs=D  grade_rel=D  tier=2  novelty=False
    alert=True (rule=True stat=False)  cold_start=False  cell=i0xp0
    dims    : O=0.440  P=1.000  L=0.766  C=0.704  R=1.000
    contrib : O=-6.701  P=+0.000  L=-0.814  C=-1.075  R=+0.000   sum=-8.5893
    zero-residual: S-100G=-8.5893  |diff|=1.40e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.9298  a_cal=0.9613  conf=0.9809  anchor=anchor-R4-5188fdfc219089b9
    gates: {"t0_result_broken": 0.25}
    evidence (3 items, drill-down order):
      - [trace] traceable_number_ratio   span=-              value=0.5000      cell_median=1.0000      z= -50.00 dev=0.3684
      - [trace] cost_total               span=R4-00056-s03   value=0.0145      cell_median=0.0111      z=  +0.64 dev=0.1367
      - [span ] dur                      span=R4-00056-s03   value=1.2691      peer_median=0.4515      z=  +2.12 dev=0.2388 (L3/L3span action=summarize)
```

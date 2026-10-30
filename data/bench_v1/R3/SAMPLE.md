# R3 样本阅读手册

这个文件由 `python -m bench.show R3 --sample` 生成，内容是真实数据，不是示意图。

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
| `data/bench_v1/R3/traces.jsonl` | 模拟出来的轨迹（一行一条，含完整 Span 树） | 3000 |
| `data/bench_v1/R3/gt.jsonl` | 真值：是否异常、异常类型、真实意图/模式、责任 Span | 3000 |
| `reports/R3/scores.jsonl` | 算法输出：S 分、五维、扣分归因、证据、告警 | 3000 |

JSONL = 每行一个压缩 JSON，直接打开会看到一堆没法读的长行。用下面的命令看：

```
python -m bench.show R3 R3-00001        # 看单条轨迹（输入+真值+算法输出）
python -m bench.show R3 --list latency_spike    # 列出某类异常的 trace_id
python -m bench.show R3 --stats                 # 数据集侧写
```

## 三、一条 trace 长什么样

每条 trace = 一棵 Span 树。根节点是整次 agent 执行，子节点是具体步骤（大模型调用 / 工具调用 / 知识检索 / 护栏校验），
每个节点带开始结束时间、token、成本、状态、输入输出文本。下面是真实样本。


## 四、数据集侧写


- 轨迹数 **3000**，Span 数 **15579**，平均 5.2 Span/轨迹
- 异常轨迹 **270** 条（基率 9.00%），正常 **2730** 条
- 意图分布：i0=1662，i1=1338
- 真实单元格（意图×模式）**6** 个
- 异常类型分布：unfinished=49，latency_spike=48，truncation=33，token_bloat=31，hallucinated_number=29，missing_step=28，error=23，illegal_step=15，loop=14
- `spec_hash=2d9e23adcdd4eb4e`  `gen_version=bench-gen-v3.1.0`
- v3 信号：arg_invalid_spans=88，cache_hit_spans=4883，contradiction=29，fabricated_citation=42，goal_drift=45，llm_spans=6113，plan_revision=172，verifier_fail=59
- 语种分布：en=1328，zh=1672；会话数 **656**，每会话轮次 {'max': 7, 'min': 2, 'n': 3000, 'p50': 5.0, 'p90': 7.0, 'p99': 7.0}

---

## 五、完整样本：输入 → 真值 → 算法输出

### 样本 A：一条正常轨迹（应该得高分、不告警）

```text
==============================================================================
TRACE R3-00002   [intent0: 先取 NE-9FB0-21 在 1h 内的当前告警清单，再总结最严重的三条]
  ontology=ontA  session=sess-00001  turn=1/7  spans=6  wall=8.096s  ts_start=1767225760.522
  user_feedback: none captured
  answer_numbers=['2033', '8996', '8101']
  answer_facts  =['NE-9FB0-21', '2033', '8996', '8101']
  golden_answer =
  golden_facts  =None
  goal_text     =当前告警清单   query_lang=zh
  answer_citations  =['runbook://adn/capacity-expansion#L25', 'runbook://adn/ne-health-check#L48']
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[-0.0004, 0.1229, 0.0115, 0.0613] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run           8.096 ######### 617       214        0.00397 ok    stop
       in : 先取 NE-9FB0-21 在 1h 内的当前告警清单，再总结最严重的三条
       out: finished '先取 NE-9FB0-21 在 1h 内的当前告警清单，再总结最严重的三条' for NE-9FB0-21; the rel
       meta: model=adn-llm-72b  facts=[2033 8996 8101]
       v3  : sys=223  cache_w=223  cost_det={cache_write:0.000836,completion:0.00128,prompt:0.00185}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan                1.094 #         2380      271        0.00933 ok    stop
         in : decompose request from NE-9FB0-21 over 1h into executable steps
         out: ok - step list drafted for NE-9FB0-21;  candidate actions
         meta: model=adn-llm-14b  ttft=0.1443  pv=pv-2026-03
         v3  : sys=150  cache_w=150  cost_det={cache_write:0.000563,completion:0.00163,prompt:0.00714}  subgoal=为当前告警清单拆解任务步骤
  `- s02           retrieval   schema_retrieval    3.915 ####      1108      0          0.00332 ok    -
         in : resolve table definitions needed by NE-9FB0-21 query
         out: table metadata resolved: 2033 8421 8101 7047 for NE-9FB0-21
         meta: tool=catalog.table_schema  params={table:alarm_history}  facts=[2033 8421 8101 7047]
         v3  : cost_det={prompt:0.00332}  arg_valid=True  retrieved=[runbook://adn/capacity-expansion#L25 runbook://adn/ne-health-check#L48]
  `- s03           tool        sql_query           2.593 ###       0         0          0.00020 ok    -
         in : SELECT kpi_ts,value FROM perf_15min WHERE ne='NE-9FB0-21' AND window='1h
         out: rows returned: 8996 7600; noted for the operator
         meta: tool=alarm_db.query  params={ne_id:NE-9FB0-21,severity:major,time_window:1h}  facts=[8996 7600]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
    `- s03-n1        tool        sql_query           1.556 ##        0         0          0.00020 ok    -
           in : nested sql_query call for NE-9FB0-21
           out: rows returned: 8996 7600; noted for the operator
           meta: tool=alarm_db.query  params={ne_id:NE-9FB0-21,severity:major,time_window:1h}  facts=[8996 7600]
           v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s04           llm         summarize           2.593 ###       1876      690        0.00927 ok    stop
         in : condense evidence 2033 8421 8101 7047 8996 7600 into an operator-facing 
         out: summary drafted from 2033 8421 8101 7047 8996 7600; nothing further requ
         meta: model=adn-llm-72b  ttft=0.3647  pv=pv-2026-03
         v3  : sys=222  cache_r=222  cost_det={cache_read:0.000167,completion:0.00414,prompt:0.00496}  verifier=v_numbers_traceable:PASS  subgoal=围绕当前告警清单执行归纳证据

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=False  anomaly_types=[]
    intent=i0  pattern=p2  cell=i0|p2
    oracle dim_dev : O=1.00  P=1.00  L=0.53  C=0.55  R=1.00
    latency_true=8.093s  gen_quantiles={'C': 0.9019, 'L': 0.9371}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=[]  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.0000  model_mix_true={'adn-llm-14b': 0.4383, 'adn-llm-72b': 0.5617}  feedback_available=False
    has_golden=False  key_fact_recall_true=n/a  fact_precision_true=n/a
    hallucinated_facts=[]
    query_lang_true=zh  session_turn_count_true=7  subgoal_count=2
    plan_revision_true=0  goal_drift_true=False  arg_valid_true=1.0000  verifier_pass_true=1.0000
    citation_reachable_true=1.0000  contradiction_true=0.0000  contradicted_count=0  fabricated_citation_count=0
    cache_read_true=222  cache_write_true=373  system_prompt_ratio_true=0.0995  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice3-v0.3.0)
    S=19.8138  G=0.25  grade_abs=D  grade_rel=D  tier=0  novelty=False
    alert=False (rule=False stat=False)  cold_start=False  cell=i0xp2
    dims    : O=1.000  P=0.895  L=0.681  C=0.362  R=1.000
    contrib : O=+0.000  P=-0.495  L=-1.287  C=-3.404  R=+0.000   sum=-5.1862
    zero-residual: S-100G=-5.1862  |diff|=7.00e-06  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.2831  a_cal=0.1533  conf=0.9758  anchor=anchor-R3-2d9e23adcdd4eb4e
    gates: {"t1_unfinished": 0.25}
    evidence (3 items, drill-down order):
      - [trace] cost_total               span=R3-00002-s01   value=0.0263      cell_median=0.0113      z=  +2.64 dev=0.2790
      - [trace] tokens_total             span=R3-00002-s01   value=7156.0000   cell_median=3159.0000   z=  +2.61 dev=0.2674
      - [span ] tok                      span=R3-00002-s02   value=1108.0000   peer_median=409.0000    z=  +3.27 dev=0.2970 (L3/L3span action=schema_retrieval)
```

### 样本 B：latency_spike —— R3-00017

某一步耗时被放大 5~20 倍。看 SPAN TREE 里的 dur(s) 列和 share 条：其中一个子步骤吃掉了几乎全部壁钟时间。真值把 L 维打到 0.10，算法应该在 L 上扣分并把责任指向那个 Span。

```text
==============================================================================
TRACE R3-00017   [intent1: analyse the KPI drops on NE-6377-40 and state the degradation root cause]
  ontology=ontA  session=sess-00004  turn=1/5  spans=5  wall=7.959s  ts_start=1767227063.626
  user_feedback: none captured
  answer_numbers=['8762', '3741', '6725']
  answer_facts  =['NE-6377-40', '8762', '3741', '6725']
  golden_answer =
  golden_facts  =None
  goal_text     =degradation root cause   query_lang=en
  answer_citations  =['runbook://adn/capacity-expansion#L25']
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[-0.6983, 0.125, 0.1768, -0.2538] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run           7.959 ######### 206       82         0.00186 ok    stop
       in : analyse the KPI drops on NE-6377-40 and state the degradation root cause
       out: answer to 'analyse the KPI drops on NE-6377-40 and state the degradation
       meta: model=adn-llm-72b  facts=[8762 3741 6725]
       v3  : sys=200  cache_w=200  cost_det={cache_write:0.00075,completion:0.000492,prompt:0.000618}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan                1.172 #         334       151        0.00269 ok    stop
         in : task=degradation root cause ne=NE-6377-40 window=15m; produce a step pla
         out: decompose into retrieval then aggregation; window=15m for NE-6377-40
         meta: model=adn-llm-72b  ttft=0.3002  pv=pv-2026-03
         v3  : sys=208  cache_w=208  cost_det={cache_write:0.00078,completion:0.000906,prompt:0.001}  subgoal=decomposing the task steps within 15m for the degradation ro
  `- s02           retrieval   retrieve_kb         0.774 #         274       0          0.00082 ok    -
         in : history search over incidents touching NE-6377-40
         out: matched runbook evidence: 8762 5591 4431 for NE-6377-40
         meta: tool=kb.history_search  params={query:NE-6377-40,top_k:5}  facts=[8762 5591 4431]
         v3  : cost_det={prompt:0.000822}  arg_valid=True  retrieved=[doc://policy/change-approval-rules#L7 doc://vendor/nbi-api-reference#L310 runbook://adn/capacity-expansion#L25]
  `- s03           tool        api_call            0.618 #         0         0          0.00020 ok    -
         in : GET /nbi/v1/ne/NE-6377-40/alarms?window=15m
         out: northbound returned objects 3297 3741 6725 8252; noted for the operator
         meta: tool=nbi.alarm_list  params={ne_id:NE-6377-40,scope:subnetwork}  facts=[3297 3741 6725 8252]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s04           llm         summarize           5.822 #######   566       343        0.00338 ok    stop
         in : write the final response for NE-6377-40 from evidence 5591 4431 3297 374
         out: summary drafted from 5591 4431 3297 3741 6725 8252 for NE-6377-40
         meta: model=adn-llm-14b  ttft=1.3025  pv=pv-2026-03
         v3  : sys=166  cache_r=166  cost_det={cache_read:0.000124,completion:0.00206,prompt:0.0012}  verifier=v_numbers_traceable:PASS  subgoal=step goal: condensing the evidence, serving the degradation 

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['latency_spike']
    intent=i1  pattern=p3  cell=i1|p3
    oracle dim_dev : O=1.00  P=1.00  L=0.10  C=0.90  R=1.00
    latency_true=7.956s  gen_quantiles={'C': 0.2039, 'L': 0.0803}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=['R3-00017-s04']  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.0000  model_mix_true={'adn-llm-14b': 0.5404, 'adn-llm-72b': 0.4596}  feedback_available=False
    has_golden=False  key_fact_recall_true=n/a  fact_precision_true=n/a
    hallucinated_facts=[]
    query_lang_true=en  session_turn_count_true=5  subgoal_count=2
    plan_revision_true=0  goal_drift_true=False  arg_valid_true=1.0000  verifier_pass_true=1.0000
    citation_reachable_true=1.0000  contradiction_true=0.0000  contradicted_count=0  fabricated_citation_count=0
    cache_read_true=166  cache_write_true=408  system_prompt_ratio_true=0.4159  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice3-v0.3.0)
    S=97.8659  G=1.00  grade_abs=A  grade_rel=A  tier=0  novelty=False
    alert=False (rule=False stat=False)  cold_start=False  cell=i1xp1
    dims    : O=1.000  P=1.000  L=0.915  C=0.947  R=1.000
    contrib : O=+0.000  P=+0.000  L=-1.319  C=-0.815  R=+0.000   sum=-2.1341
    zero-residual: S-100G=-2.1341  |diff|=3.00e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.1341  a_cal=0.0566  conf=0.9827  anchor=anchor-R3-2d9e23adcdd4eb4e
    evidence (3 items, drill-down order):
      - [trace] branch_factor            span=-              value=4.0000      cell_median=4.0000      z=  +0.00 dev=0.0702
      - [trace] n_spans                  span=-              value=5.0000      cell_median=5.0000      z=  +0.00 dev=0.0605
      - [span ] dur                      span=R3-00017-s04   value=5.8218      peer_median=3.5950      z=  +0.62 dev=0.1192 (L3/L3span action=summarize)
```

### 样本 C：hallucinated_number（带 golden） —— R3-00952

最终答案里出现了检索证据中不存在的数字。对比子 Span 的 `out: evidence: ...` 与根 Span 的 `out: answer: ...`：后者多出了两个 5 位数。这是唯一一个靠文本内容判定的异常（`traceable_number_ratio` 特征）。

这条带 golden。看 GROUND TRUTH 里的 `fact_precision_true` 与 `key_fact_recall_true`：编造数字只压 precision，recall 仍为 1.00——答案里的事实都在，只是多了不该有的。`hallucinated_facts` 直接列出多出来的那几个。

```text
==============================================================================
TRACE R3-00952   [intent1: 定位网元 NE-FB6B-29 的劣化根因]
  ontology=ontA  session=sess-00209  turn=1/3  spans=5  wall=15.135s  ts_start=1767307856.783
  user_feedback: none captured
  answer_numbers=['8449', '6487', '9009', '66881', '29248']
  answer_facts  =['NE-FB6B-29', '8449', '6487', '9009', '66881', '29248']
  golden_answer =expected answer for NE-FB6B-29 (定位网元 NE-FB6B-29 的劣化根因): 8449, 6487, 9009
  golden_facts  =['NE-FB6B-29', '8449', '6487', '9009']
  goal_text     =劣化根因   query_lang=zh
  answer_citations  =['doc://topology/subnetwork-east-map', 'kb://history/incident-2025-1187#L1175']
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[-0.3852, 0.1492, 0.1273, 0.0104] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run          15.135 ######### 292       101        0.00210 ok    stop
       in : 定位网元 NE-FB6B-29 的劣化根因
       out: operator summary for NE-FB6B-29 (定位网元 NE-FB6B-29 的劣化根因): 8449, 6487, 900
       meta: model=adn-llm-14b  facts=[8449 6487 9009 66881 29248]
       v3  : sys=165  cache_w=165  cost_det={cache_write:0.000619,completion:0.000606,prompt:0.000876}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan               10.842 ######    624       313        0.00459 ok    stop
         in : decompose request from NE-FB6B-29 over 1h into executable steps
         out: attempt finished, step list drafted for NE-FB6B-29;  candidate actions
         meta: model=adn-llm-72b  level=WARNING  ttft=3.1991  pv=pv-2026-03  msg=slow query above soft limit
         v3  : sys=223  cache_w=223  cost_det={cache_write:0.000836,completion:0.00188,prompt:0.00187}  subgoal=在 NE-FB6B-29 上为劣化根因完成拆解任务步骤
  `- s02           retrieval   retrieve_kb         1.983 #         710       0          0.00213 ok    -
         in : runbook search: 劣化根因 (ne=NE-FB6B-29)
         out: matched runbook evidence: 8449 9009 6487 (window 1h)
         meta: tool=kb.runbook_search  params={query:NE-FB6B-29,top_k:5}  facts=[8449 9009 6487]
         v3  : cost_det={prompt:0.00213}  arg_valid=True  retrieved=[doc://topology/subnetwork-east-map]
  `- s03           guard       approve             1.708 #         335       55         0.00134 ok    -
         in : approval gate for change on NE-FB6B-29
         out: approval gate pass on NE-FB6B-29
         v3  : cost_det={completion:0.00033,prompt:0.00101}  verifier=v_no_forbidden_action:PASS
  `- s04           llm         summarize           1.708 #         231       273        0.00294 ok    stop
         in : write the final response for NE-FB6B-29 from evidence 8449 9009 6487
         out: summary drafted from 8449 9009 6487 (window 1h)
         meta: model=adn-llm-14b  ttft=0.3781  pv=pv-2026-03
         v3  : sys=162  cache_w=162  cost_det={cache_write:0.000607,completion:0.00164,prompt:0.000693}  verifier=v_numbers_traceable:FAIL(answer number absent from the evidence pool)  subgoal=步骤目标：归纳证据，服务于劣化根因

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['hallucinated_number']
    intent=i1  pattern=p3  cell=i1|p3
    oracle dim_dev : O=0.15  P=1.00  L=0.70  C=0.82  R=1.00
    latency_true=15.132s  gen_quantiles={'C': 0.3574, 'L': 0.5976}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=[]  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.0000  model_mix_true={'adn-llm-14b': 0.4891, 'adn-llm-72b': 0.5109}  feedback_available=False
    has_golden=True  key_fact_recall_true=1.0000  fact_precision_true=0.6667
    hallucinated_facts=['29248', '66881']
    query_lang_true=zh  session_turn_count_true=3  subgoal_count=2
    plan_revision_true=0  goal_drift_true=False  arg_valid_true=1.0000  verifier_pass_true=0.6667
    citation_reachable_true=0.5000  contradiction_true=0.0000  contradicted_count=0  fabricated_citation_count=1
    cache_read_true=0  cache_write_true=550  system_prompt_ratio_true=0.2509  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice3-v0.3.0)
    S=23.3470  G=0.48  grade_abs=D  grade_rel=D  tier=0  novelty=True
    alert=False (rule=False stat=False)  cold_start=False  cell=None
    dims    : O=0.564  P=1.000  L=0.000  C=0.400  R=1.000
    contrib : O=-9.547  P=+0.000  L=-12.239  C=-2.867  R=+0.000   sum=-24.6530
    zero-residual: S-100G=-24.6530  |diff|=2.00e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.2896  a_cal=0.1596  conf=0.3500  anchor=anchor-R3-2d9e23adcdd4eb4e
    gates: {"novelty": 0.8, "t2_untraceable_number": 0.6}
    evidence (3 items, drill-down order):
      - [trace] traceable_number_ratio   span=-              value=0.6000      cell_median=1.0000      z= -50.00 dev=0.3085
      - [trace] latency_total            span=R3-00952-s00   value=15.1351     cell_median=6.8790      z=  +1.39 dev=0.1341
      - [span ] dur                      span=R3-00952-s01   value=10.8422     peer_median=2.0042      z=  +4.31 dev=0.2058 (L3/L1span action=plan)
```

### 样本 D：loop —— R3-00314

同一步骤被重复插入 3~5 次。SPAN TREE 里会看到连续多行相同 action，时间戳也相同（生成器直接复制了 Span）。

```text
==============================================================================
TRACE R3-00314   [intent0: 给出 NE-CEAF-13 的当前告警清单，并说明每条告警的触发原因]
  ontology=ontA  session=sess-00067  turn=3/3  spans=12  wall=13.092s  ts_start=1767252740.664
  user_feedback: none captured
  answer_numbers=['7792', '7755']
  answer_facts  =['NE-CEAF-13', '7792', '7755']
  golden_answer =
  golden_facts  =None
  goal_text     =当前告警清单   query_lang=zh
  answer_citations  =['doc://policy/change-approval-rules#L7']
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[-0.6209, 0.1296, 0.1122, -0.1686] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run          13.092 ######### 337       117        0.00124 ok    stop
       in : 给出 NE-CEAF-13 的当前告警清单，并说明每条告警的触发原因
       out: answer to '给出 NE-CEAF-13 的当前告警清单，并说明每条告警的触发原因' on NE-CEAF-13 over 15m: 7
       meta: model=adn-llm-72b  facts=[7792 7755]
       v3  : sys=210  cache_r=210  cost_det={cache_read:0.000158,completion:0.000702,prompt:0.000381}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan                1.426 #         1137      323        0.00485 ok    stop
         in : task=当前告警清单 ne=NE-CEAF-13 window=15m; produce a step plan
         out: checked and recorded: decompose into retrieval then aggregation; window=
         meta: model=adn-llm-72b  ttft=0.1641  pv=pv-2026-04-canary
         v3  : sys=221  cache_r=221  cost_det={cache_read:0.000166,completion:0.00194,prompt:0.00275}  subgoal=针对当前告警清单进行拆解任务步骤（窗口 15m）
  `- s02           guard       verify              0.818 #         296       13         0.00097 ok    -
         in : policy check on pending action for NE-CEAF-13
         out: policy evaluation on NE-CEAF-13: pass
         v3  : cost_det={completion:7.8e-05,prompt:0.000888}  verifier=v_no_forbidden_action:PASS
  `- s03           retrieval   schema_retrieval    1.072 #         479       0          0.00144 ok    -
         in : lookup schema for alarm tables of NE-CEAF-13
         out: step done - schema rows: 2716 8378 6868
         meta: tool=catalog.table_schema  params={table:kpi_15min}  facts=[2716 8378 6868]
         v3  : cost_det={prompt:0.00144}  arg_valid=True  retrieved=[doc://policy/change-approval-rules#L7]
  `- s04           retrieval   schema_retrieval    1.072 #         529       0          0.00159 ok    -
         in : lookup schema for alarm tables of NE-CEAF-13
         out: schema rows: 4085 3853 1298 7792; nothing further required
         meta: tool=catalog.table_schema  params={table:kpi_15min}  facts=[4085 3853 1298 7792]
         v3  : cost_det={prompt:0.00159}  arg_valid=True  retrieved=[doc://policy/change-approval-rules#L7]
  `- s05           retrieval   schema_retrieval    1.072 #         474       0          0.00142 ok    -
         in : resolve table definitions needed by NE-CEAF-13 query
         out: ok - table metadata resolved: 1744 8414 7021 7464
         meta: tool=catalog.table_schema  params={table:kpi_15min}  facts=[1744 8414 7021 7464]
         v3  : cost_det={prompt:0.00142}  arg_valid=True  retrieved=[doc://policy/change-approval-rules#L7]
  `- s06           retrieval   schema_retrieval    1.072 #         437       0          0.00131 ok    -
         in : lookup schema for alarm tables of NE-CEAF-13
         out: schema rows: 8278 9837 for NE-CEAF-13
         meta: tool=catalog.table_schema  params={table:kpi_15min}  facts=[8278 9837]
         v3  : cost_det={prompt:0.00131}  arg_valid=True  retrieved=[doc://policy/change-approval-rules#L7]
  `- s07           retrieval   schema_retrieval    1.072 #         471       0          0.00141 ok    -
         in : resolve table definitions needed by NE-CEAF-13 query
         out: schema rows: 8794 6021; payload attached to the trace
         meta: tool=catalog.table_schema  params={table:kpi_15min}  facts=[8794 6021]
         v3  : cost_det={prompt:0.00141}  arg_valid=True  retrieved=[doc://policy/change-approval-rules#L7]
  `- s08           retrieval   schema_retrieval    1.072 #         326       0          0.00098 ok    -
         in : resolve table definitions needed by NE-CEAF-13 query
         out: attempt finished, table metadata resolved: 6588 7755
         meta: tool=catalog.table_schema  params={table:kpi_15min}  facts=[6588 7755]
         v3  : cost_det={prompt:0.000978}  arg_valid=True  retrieved=[doc://policy/change-approval-rules#L7]
  `- s09           tool        sql_query           1.072 #         0         0          0.00020 ok    -
         in : SELECT alarm_id,severity FROM current_alarms WHERE ne='NE-CEAF-13' AND w
         out: attempt finished, rows returned: 4289 3367 2736
         meta: tool=perf_db.query  params={ne_id:NE-CEAF-13,severity:minor,time_window:15m}  facts=[4289 3367 2736]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
    `- s09-n1        tool        sql_query           0.643 #         0         0          0.00020 ok    -
           in : nested sql_query call for NE-CEAF-13
           out: attempt finished, rows returned: 4289 3367 2736
           meta: tool=perf_db.query  params={ne_id:NE-CEAF-13,severity:minor,time_window:15m}  facts=[4289 3367 2736]
           v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s10           llm         summarize           9.158 ######    1349      413        0.00615 ok    stop
         in : write the final response for NE-CEAF-13 from evidence 6021 6588 7755 428
         out: summary drafted from 6021 6588 7755 4289 3367 2736 for NE-CEAF-13
         meta: model=adn-llm-14b  level=WARNING  ttft=1.1973  pv=pv-2026-04-canary  msg=partial result set returned
         v3  : sys=165  cache_r=165  cost_det={cache_read:0.000124,completion:0.00248,prompt:0.00355}  verifier=v_numbers_traceable:PASS  subgoal=在 NE-CEAF-13 上为当前告警清单完成归纳证据

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['loop']
    intent=i0  pattern=p2  cell=i0|p2
    oracle dim_dev : O=1.00  P=0.50  L=0.53  C=0.76  R=0.55
    latency_true=13.089s  gen_quantiles={'C': 0.4817, 'L': 0.9447}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=['R3-00314-s03', 'R3-00314-s04', 'R3-00314-s05', 'R3-00314-s06', 'R3-00314-s07', 'R3-00314-s08']  human_label=None  drift_segment=None
    loop_true=True  mfr_true=0.0000  model_mix_true={'adn-llm-14b': 0.4793, 'adn-llm-72b': 0.5207}  feedback_available=False
    has_golden=False  key_fact_recall_true=n/a  fact_precision_true=n/a
    hallucinated_facts=[]
    query_lang_true=zh  session_turn_count_true=3  subgoal_count=2
    plan_revision_true=0  goal_drift_true=False  arg_valid_true=1.0000  verifier_pass_true=1.0000
    citation_reachable_true=1.0000  contradiction_true=0.0000  contradicted_count=0  fabricated_citation_count=0
    cache_read_true=596  cache_write_true=0  system_prompt_ratio_true=0.1021  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice3-v0.3.0)
    S=12.5751  G=0.28  grade_abs=D  grade_rel=D  tier=0  novelty=True
    alert=False (rule=False stat=False)  cold_start=False  cell=None
    dims    : O=1.000  P=0.800  L=0.000  C=0.000  R=0.700
    contrib : O=+0.000  P=-1.049  L=-6.895  C=-6.895  R=-0.587   sum=-15.4249
    zero-residual: S-100G=-15.4249  |diff|=1.50e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.3341  a_cal=0.2091  conf=0.3500  anchor=anchor-R3-2d9e23adcdd4eb4e
    gates: {"loop_runaway": 0.35, "novelty": 0.8}
    evidence (3 items, drill-down order):
      - [trace] loop_count               span=-              value=4.0000      cell_median=0.0000      z= +50.00 dev=0.3676
      - [trace] n_spans                  span=-              value=12.0000     cell_median=5.0000      z=  +4.72 dev=0.3676
      - [span ] dur                      span=R3-00314-s10   value=9.1578      peer_median=1.9867      z=  +3.54 dev=0.1871 (L3/L1span action=summarize)
```

### 样本 E：token_bloat —— R3-00087

某个 LLM 步骤的 token 被放大 4~10 倍，耗时不变。只有成本维（C）会崩，时延维不崩——用来验证五维不会互相污染。

```text
==============================================================================
TRACE R3-00087   [intent1: the degradation root cause on NE-0FF1-20 is unclear, investigate alarms and topology]
  ontology=ontA  session=sess-00019  turn=2/2  spans=6  wall=4.092s  ts_start=1767233125.428
  user_feedback: abandoned=False human_takeover=True retry=True thumbs=None
  answer_numbers=['5953', '8879', '7491']
  answer_facts  =['NE-0FF1-20', '5953', '8879', '7491']
  golden_answer =
  golden_facts  =None
  goal_text     =degradation root cause   query_lang=en
  answer_citations  =['kb://history/incident-2026-0043']
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[-0.3054, 0.0307, -0.0965, 0.2257] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run           4.092 ######### 305       122        0.00121 ok    stop
       in : the degradation root cause on NE-0FF1-20 is unclear, investigate alarms 
       out: finished 'the degradation root cause on NE-0FF1-20 is unclear, investiga
       meta: model=adn-llm-72b  facts=[5953 8879 7491]
       v3  : sys=195  cache_r=195  cost_det={cache_read:0.000146,completion:0.000732,prompt:0.00033}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan                0.340 #         5634      2962       0.03420 ok    stop
         in : decompose request from NE-0FF1-20 over 1h into executable steps
         out: step list drafted for NE-0FF1-20;  candidate actions; noted for the oper
         meta: model=adn-llm-72b  ttft=0.0864  pv=pv-2026-03
         v3  : sys=210  cache_r=210  cost_det={cache_read:0.000158,completion:0.0178,prompt:0.0163}  subgoal=work on decomposing the task steps to advance the degradatio
  `- s02           retrieval   schema_retrieval    0.340 #         562       0          0.00169 ok    -
         in : resolve table definitions needed by NE-0FF1-20 query
         out: step done - schema rows: 5877 8879 5953 7315
         meta: tool=catalog.table_schema  params={table:alarm_history}  facts=[5877 8879 5953 7315]
         v3  : cost_det={prompt:0.00169}  arg_valid=True  retrieved=[kb://history/incident-2026-0043]
  `- s03           tool        api_call            1.173 ###       0         0          0.00020 ok    -
         in : GET /nbi/v1/ne/NE-0FF1-20/status?detail=true
         out: northbound returned objects 3000 3107 7491
         meta: tool=nbi.ne_status  params={ne_id:NE-0FF1-20,scope:ne}  facts=[3000 3107 7491]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s04           tool        sql_query           0.723 ##        0         0          0.00020 ok    -
         in : SELECT kpi_ts,value FROM perf_15min WHERE ne='NE-0FF1-20' AND window='1h
         out: rows returned: 6200 7759 6637 5573 for NE-0FF1-20
         meta: tool=alarm_db.query  params={ne_id:NE-0FF1-20,severity:critical,time_window:1h}  facts=[6200 7759 6637 5573]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s05           llm         summarize           1.685 ####      914       219        0.00368 ok    stop
         in : condense evidence 3107 7491 6200 7759 6637 5573 into an operator-facing 
         out: summary drafted from 3107 7491 6200 7759 6637 5573; noted for the operat
         meta: model=adn-llm-14b  ttft=0.4871  pv=pv-2026-03
         v3  : sys=165  cache_r=165  cost_det={cache_read:0.000124,completion:0.00131,prompt:0.00225}  verifier=v_numbers_traceable:PASS  subgoal=condensing the evidence for the degradation root cause

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['token_bloat']
    intent=i1  pattern=p2  cell=i1|p2
    oracle dim_dev : O=1.00  P=1.00  L=0.98  C=0.12  R=1.00
    latency_true=4.089s  gen_quantiles={'C': 0.5156, 'L': 0.0336}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=['R3-00087-s01']  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.0000  model_mix_true={'adn-llm-14b': 0.1116, 'adn-llm-72b': 0.8884}  feedback_available=True
    has_golden=False  key_fact_recall_true=n/a  fact_precision_true=n/a
    hallucinated_facts=[]
    query_lang_true=en  session_turn_count_true=2  subgoal_count=2
    plan_revision_true=0  goal_drift_true=False  arg_valid_true=1.0000  verifier_pass_true=1.0000
    citation_reachable_true=1.0000  contradiction_true=0.0000  contradicted_count=0  fabricated_citation_count=0
    cache_read_true=570  cache_write_true=0  system_prompt_ratio_true=0.0769  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice3-v0.3.0)
    S=55.9366  G=0.80  grade_abs=D  grade_rel=B  tier=0  novelty=True
    alert=False (rule=False stat=False)  cold_start=False  cell=None
    dims    : O=1.000  P=1.000  L=1.000  C=0.000  R=1.000
    contrib : O=+0.000  P=+0.000  L=+0.000  C=-24.063  R=+0.000   sum=-24.0634
    zero-residual: S-100G=-24.0634  |diff|=4.20e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.3216  a_cal=0.1941  conf=0.3500  anchor=anchor-R3-2d9e23adcdd4eb4e
    gates: {"novelty": 0.8}
    evidence (3 items, drill-down order):
      - [trace] cost_total               span=R3-00087-s01   value=0.0412      cell_median=0.0115      z=  +5.35 dev=0.3413
      - [trace] tokens_total             span=R3-00087-s01   value=10718.0000  cell_median=3172.5000   z=  +4.94 dev=0.3386
      - [span ] tok                      span=R3-00087-s01   value=8596.0000   peer_median=1106.0000   z= +13.37 dev=0.6028 (L3/L1span action=plan)
```

### 样本 F：illegal_step —— R3-00179

插入了本体禁止的动作（如 `force_delete` / `skip_approval_execute`）。这是确定性违规，走规则闸门（alert_rule=True）而不是统计异常。

```text
==============================================================================
TRACE R3-00179   [intent0: I need the current alarm list for NE-2054-30; if any alarm is critical, flag it]
  ontology=ontA  session=sess-00038  turn=3/3  spans=5  wall=4.692s  ts_start=1767241074.897
  user_feedback: none captured
  answer_numbers=[]
  answer_facts  =[]
  golden_answer =
  golden_facts  =None
  goal_text     =current alarm list   query_lang=en
  answer_citations  =[]
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[-0.5724, 0.374, -0.0053, 0.0987] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run           4.692 ######### 197       79         0.00062 ok    stop
       in : I need the current alarm list for NE-2054-30; if any alarm is critical, 
       out: completed 'I need the current alarm list for NE-2054-30; if any alarm is
       meta: model=adn-llm-72b
       v3  : sys=197  cache_r=197  cost_det={cache_read:0.000148,completion:0.000474}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan                1.108 ##        557       201        0.00252 ok    stop
         in : decompose request from NE-2054-30 over 24h into executable steps
         out: step done - decompose into retrieval then aggregation; window=24h
         meta: model=adn-llm-14b  ttft=0.3277  pv=pv-2026-03
         v3  : sys=158  cache_r=158  cost_det={cache_read:0.000119,completion:0.00121,prompt:0.0012}  subgoal=search the training vault for slide decks
  `- s02           tool        sql_query           1.931 ####      0         0          0.00020 ok    -
         in : SELECT kpi_ts,value FROM perf_15min WHERE ne='NE-2054-30' AND window='24
         out: query settled; row ids 2978 1985 6471 (window 24h)
         meta: tool=alarm_db.query  params={ne_id:NE-2054-30,severity:not-in-enum,time_window:24h}  facts=[2978 1985 6471]
         v3  : cost_det={tool_call:0.0002}  arg_valid=False
  `- s03           llm         summarize           1.375 ###       696       256        0.00418 ok    stop
         in : condense evidence 2978 1985 6471 into an operator-facing answer
         out: step done - summary drafted from 2978 1985 6471
         meta: model=adn-llm-14b  ttft=0.2102  pv=pv-2026-03
         v3  : sys=148  cache_w=148  cost_det={cache_write:0.000555,completion:0.00154,prompt:0.00209}  verifier=v_numbers_traceable:PASS  subgoal=condensing the evidence for the current alarm list
  `- s04           tool        skip_approval_execute    0.096 #         0         0          0.00020 ok    -
         in : apply change to NE-2054-30 bypassing approval gate
         out: step done - applied without approval: 6176 3003 4577
         meta: tool=nbi.config_apply_nocheck  facts=[6176 3003 4577]
         v3  : cost_det={tool_call:0.0002}

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['illegal_step']
    intent=i0  pattern=p1  cell=i0|p1
    oracle dim_dev : O=1.00  P=0.05  L=0.81  C=0.91  R=1.00
    latency_true=4.689s  gen_quantiles={'C': 0.1768, 'L': 0.3747}
    process_flags={'illegal_step': True, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=['R3-00179-s04']  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.0208  model_mix_true={'adn-llm-14b': 0.861, 'adn-llm-72b': 0.139}  feedback_available=False
    has_golden=False  key_fact_recall_true=n/a  fact_precision_true=n/a
    hallucinated_facts=[]
    query_lang_true=en  session_turn_count_true=3  subgoal_count=2
    plan_revision_true=0  goal_drift_true=True  arg_valid_true=0.0000  verifier_pass_true=1.0000
    citation_reachable_true=n/a  contradiction_true=n/a  contradicted_count=0  fabricated_citation_count=0
    cache_read_true=355  cache_write_true=148  system_prompt_ratio_true=0.3469  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice3-v0.3.0)
    S=4.8004  G=0.06  grade_abs=D  grade_rel=D  tier=0  novelty=True
    alert=False (rule=False stat=False)  cold_start=False  cell=None
    dims    : O=1.000  P=0.445  L=1.000  C=1.000  R=1.000
    contrib : O=+0.000  P=-1.200  L=+0.000  C=+0.000  R=+0.000   sum=-1.1996
    zero-residual: S-100G=-1.1996  |diff|=3.70e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.2243  a_cal=0.1048  conf=0.3464  anchor=anchor-R3-2d9e23adcdd4eb4e
    gates: {"forbidden_action": 0.3, "novelty": 0.8, "t1_unfinished": 0.25}
    evidence (3 items, drill-down order):
      - [trace] missing_field_ratio      span=-              value=0.0208      cell_median=0.0000      z= +50.00 dev=0.2072
      - [trace] branch_factor            span=-              value=4.0000      cell_median=4.0000      z=  +0.00 dev=0.0586
      - [span ] dur                      span=R3-00179-s02   value=1.9306      peer_median=1.0203      z=  +0.87 dev=0.1091 (L3/L1span action=sql_query)
```

### 样本 G：truncation（带 golden） —— R3-00401

根 Span 的 `finish_reason=length`，答案被截断，结果维（O）重罚。

这条带 golden。与上一个样本对着看：截断只压 `key_fact_recall_true`，precision 仍为 1.00——说出来的都对，只是没说完。生成器故意把“不完整”与“不忠实”做成可分离的两类，否则O 维会把两种完全不同的失败打成同一个分。

```text
==============================================================================
TRACE R3-00401   [intent0: show the current alarm list of NE-63E6-24]
  ontology=ontA  session=sess-00090  turn=2/2  spans=6  wall=12.865s  ts_start=1767260234.992
  user_feedback: none captured
  answer_numbers=['4125', '5582', '9793', '48']
  answer_facts  =['NE-63E6-24', '4125', '5582', '9793', '48']
  golden_answer =expected answer for NE-63E6-24 (show the current alarm list of NE-63E6-24): 4125, 5582, 9793, 7390, 6610
  golden_facts  =['NE-63E6-24', '4125', '5582', '9793', '7390', '6610']
  goal_text     =current alarm list   query_lang=en
  answer_citations  =['doc://policy/change-approval-rules#L1483', 'doc://topology/subnetwork-east-map', 'runbook://adn/capacity-expansion#L25']
  contradicted_facts=['4125']
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[-0.5068, 0.2525, 0.1992, -0.0838] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run          12.865 ######### 339       135        0.00147 ok    length
       in : show the current alarm list of NE-63E6-24
       out: answer to 'show the current alarm list of NE-63E6-24' on NE-63E6-24 over
       meta: model=adn-llm-14b  facts=[4125 5582 9793 48]
       v3  : sys=158  cache_r=158  cost_det={cache_read:0.000119,completion:0.00081,prompt:0.000543}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan                3.000 ##        1262      213        0.00469 ok    stop
         in : task=current alarm list ne=NE-63E6-24 window=5m; produce a step plan
         out: ok - decompose into retrieval then aggregation; window=5m
         meta: model=adn-llm-14b  ttft=0.2483  pv=pv-2026-03
         v3  : sys=165  cache_r=165  cost_det={cache_read:0.000124,completion:0.00128,prompt:0.00329}  subgoal=decomposing the task steps on NE-63E6-24 as part of the curr
  `- s02           retrieval   schema_retrieval    3.000 ##        621       0          0.00186 ok    -
         in : resolve table definitions needed by NE-63E6-24 query
         out: ok - table metadata resolved: 9793 6612 4125 3899
         meta: tool=catalog.table_schema  params={table:alarm_history}  facts=[9793 6612 4125 3899]
         v3  : cost_det={prompt:0.00186}  arg_valid=True  retrieved=[doc://topology/subnetwork-east-map runbook://adn/alarm-clear-procedure#L12 runbook://adn/capacity-expansion#L25]
  `- s03           tool        sql_query           2.481 ##        0         0          0.00020 ok    -
         in : SELECT alarm_id,severity FROM current_alarms WHERE ne='NE-63E6-24' AND w
         out: rows returned: 4827 5582; nothing further required
         meta: tool=alarm_db.query  params={ne_id:NE-63E6-24,severity:minor,time_window:5m}  facts=[4827 5582]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s04           guard       verify              1.203 #         428       47         0.00157 ok    -
         in : policy check on pending action for NE-63E6-24
         out: verdict pass for NE-63E6-24
         v3  : cost_det={completion:0.000282,prompt:0.00128}  verifier=v_no_forbidden_action:PASS
  `- s05           llm         summarize           5.574 ####      862       237        0.00365 ok    stop
         in : condense evidence 9793 6612 4125 3899 4827 5582 into an operator-facing 
         out: answer composed citing 9793 6612 4125 3899 4827 5582; noted for the oper
         meta: model=adn-llm-14b  ttft=0.5396  pv=pv-2026-03
         v3  : sys=160  cache_r=160  cost_det={cache_read:0.00012,completion:0.00142,prompt:0.00211}  verifier=v_numbers_traceable:FAIL(answer number absent from the evidence pool)  subgoal=condensing the evidence for the current alarm list

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['truncation']
    intent=i0  pattern=p2  cell=i0|p2
    oracle dim_dev : O=0.35  P=1.00  L=0.53  C=0.70  R=1.00
    latency_true=12.862s  gen_quantiles={'C': 0.6077, 'L': 0.9411}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=[]  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.0000  model_mix_true={'adn-llm-14b': 1.0}  feedback_available=False
    has_golden=True  key_fact_recall_true=0.6667  fact_precision_true=0.8000
    hallucinated_facts=['48']
    query_lang_true=en  session_turn_count_true=2  subgoal_count=2
    plan_revision_true=0  goal_drift_true=False  arg_valid_true=1.0000  verifier_pass_true=0.6667
    citation_reachable_true=0.6667  contradiction_true=0.2000  contradicted_count=1  fabricated_citation_count=1
    cache_read_true=483  cache_write_true=0  system_prompt_ratio_true=0.1375  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice3-v0.3.0)
    S=8.3783  G=0.20  grade_abs=D  grade_rel=D  tier=0  novelty=True
    alert=False (rule=False stat=False)  cold_start=False  cell=None
    dims    : O=0.729  P=1.000  L=0.000  C=0.000  R=1.000
    contrib : O=-2.063  P=+0.000  L=-4.779  C=-4.779  R=+0.000   sum=-11.6217
    zero-residual: S-100G=-11.6217  |diff|=2.00e-06  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.2670  a_cal=0.1384  conf=0.3500  anchor=anchor-R3-2d9e23adcdd4eb4e
    gates: {"novelty": 0.8, "t0_result_broken": 0.25}
    evidence (3 items, drill-down order):
      - [trace] traceable_number_ratio   span=-              value=0.7500      cell_median=1.0000      z= -50.00 dev=0.2927
      - [trace] branch_factor            span=-              value=5.0000      cell_median=4.0000      z=  +0.67 dev=0.1385
      - [span ] dur                      span=R3-00401-s02   value=3.0005      peer_median=0.7986      z=  +2.68 dev=0.1590 (L3/L1span action=schema_retrieval)
```

### 样本 H：missing_step —— R3-00030

本体要求的必须步骤被删掉一个，过程维（P）扣分。

```text
==============================================================================
TRACE R3-00030   [intent0: NE-8F88-14 在 15m 内的当前告警清单是什么]
  ontology=ontA  session=sess-00007  turn=3/4  spans=3  wall=4.979s  ts_start=1767228195.729
  user_feedback: none captured
  answer_numbers=[]
  answer_facts  =[]
  golden_answer =
  golden_facts  =None
  goal_text     =当前告警清单   query_lang=zh
  answer_citations  =[]
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[-0.5432, 0.2479, 0.1785, 0.101] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run           4.979 ######### 315       109        0.00128 ok    stop
       in : NE-8F88-14 在 15m 内的当前告警清单是什么
       out: NE-8F88-14 在 15m 内的当前告警清单是什么 for NE-8F88-14: operation completed, no num
       meta: model=adn-llm-14b
       v3  : sys=142  cache_r=142  cost_det={cache_read:0.000107,completion:0.000654,prompt:0.000519}  verifier=v_answer_nonempty:PASS
  `- s01           tool        sql_query           0.733 #         0         0          0.00020 ok    -
         in : SELECT alarm_id,severity FROM current_alarms WHERE ne='NE-8F88-14' AND w
         out: query settled; row ids 7716 4484; noted for the operator
         meta: tool=alarm_db.query  params={ne_id:NE-8F88-14,severity:minor,time_window:15m}  facts=[7716 4484]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s02           llm         summarize           4.057 #######   1066      336        0.00485 ok    stop
         in : write the final response for NE-8F88-14 from evidence 7716 4484
         out: answer composed citing 7716 4484; nothing further required
         meta: model=adn-llm-14b  ttft=0.4641  pv=pv-2026-03
         v3  : sys=163  cache_r=163  cost_det={cache_read:0.000122,completion:0.00202,prompt:0.00271}  verifier=v_numbers_traceable:PASS  subgoal=针对当前告警清单进行归纳证据（窗口 15m）

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['missing_step']
    intent=i0  pattern=p1  cell=i0|p1
    oracle dim_dev : O=1.00  P=0.80  L=0.62  C=0.79  R=1.00
    latency_true=4.976s  gen_quantiles={'C': 0.4211, 'L': 0.7657}
    process_flags={'illegal_step': False, 'missing_step': True, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=[]  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.0000  model_mix_true={'adn-llm-14b': 1.0}  feedback_available=False
    has_golden=False  key_fact_recall_true=n/a  fact_precision_true=n/a
    hallucinated_facts=[]
    query_lang_true=zh  session_turn_count_true=4  subgoal_count=1
    plan_revision_true=0  goal_drift_true=False  arg_valid_true=1.0000  verifier_pass_true=1.0000
    citation_reachable_true=n/a  contradiction_true=n/a  contradicted_count=0  fabricated_citation_count=0
    cache_read_true=305  cache_write_true=0  system_prompt_ratio_true=0.2209  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice3-v0.3.0)
    S=93.0236  G=1.00  grade_abs=A  grade_rel=B  tier=2  novelty=False
    alert=True (rule=True stat=False)  cold_start=False  cell=i0xp0
    dims    : O=1.000  P=0.900  L=0.768  C=0.969  R=1.000
    contrib : O=+0.000  P=-2.244  L=-4.223  C=-0.510  R=+0.000   sum=-6.9764
    zero-residual: S-100G=-6.9764  |diff|=2.30e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.8865  a_cal=0.9409  conf=0.9853  anchor=anchor-R3-2d9e23adcdd4eb4e
    evidence (3 items, drill-down order):
      - [trace] latency_total            span=R3-00030-s00   value=4.9789      cell_median=4.0857      z=  +0.28 dev=0.0986
      - [trace] tokens_total             span=R3-00030-s02   value=1826.0000   cell_median=2926.0000   z=  -0.86 dev=0.0233
      - [span ] dur                      span=R3-00030-s02   value=4.0567      peer_median=1.2786      z=  +2.48 dev=0.2083 (L3/L3span action=summarize)
```

## 六、v3 共生缺陷样本（附录 A 新增特征的原始证据）

下面这些**不是**独立的异常类型，而是叠加在已异常轨迹上的共生缺陷。每一个都由
`bench/coverage.truth_agreement()` 在全部轨迹上做双向等价校验（内核特征 ⟺ 生成器真值），
任何一条对不上都会让构建直接失败，而不是只在报告里留一行警告。


### v3 样本 A：plan_revision —— R3-00063

入口步骤（ontA 的 `plan`、ontB 的 `intent_parse`）出现了两次，第二次的时间区间**嵌套在**第一次之内——智能体在一步还没走完时就重开了计划。`kernel/cluster.collapse()` 会折叠相邻重复，所以模式视图看到的骨架完全不变，只有 `plan_revision_count` 能看见它。这也是该特征被定义成“时间包含”而不是“计数减一”的原因：循环注入器同样可能选中入口步骤，计数减一会把一次循环读成两次计划修订。

```text
==============================================================================
TRACE R3-00063   [intent0: pull the current alarm list for NE-ACBB-45 and sort it by severity]
  ontology=ontA  session=sess-00014  turn=2/3  spans=6  wall=2.824s  ts_start=1767231043.839
  user_feedback: none captured
  answer_numbers=['3072']
  answer_facts  =['NE-ACBB-45', '3072']
  golden_answer =
  golden_facts  =None
  goal_text     =current alarm list   query_lang=en
  answer_citations  =[]
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[-0.413, 0.0115, 0.1292, 0.1052] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run           2.824 ######### 792       316        0.00482 ok    stop
       in : pull the current alarm list for NE-ACBB-45 and sort it by severity
       out: operator summary for NE-ACBB-45 (pull the current alarm list for NE-ACBB
       meta: model=adn-llm-14b  facts=[3072]
       v3  : sys=145  cache_w=145  cost_det={cache_write:0.000544,completion:0.0019,prompt:0.00238}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan                1.346 ####      2088      1080       0.01240 ok    stop
         in : decompose request from NE-ACBB-45 over 15m into executable steps
         out: step done - decompose into retrieval then aggregation; window=15m
         meta: model=adn-llm-14b  ttft=0.3223  pv=pv-2026-03
         v3  : sys=153  cache_r=153  cost_det={cache_read:0.000115,completion:0.00648,prompt:0.00581}  subgoal=decomposing the task steps for the current alarm list
  `- s02           llm         plan                0.539 ##        2160      578        0.00960 ok    stop
         in : decompose request from NE-ACBB-45 over 15m into executable steps
         out: ok - decompose into retrieval then aggregation; window=15m
         meta: model=adn-llm-14b  ttft=0.0648  pv=pv-2026-03
         v3  : sys=155  cache_r=155  cost_det={cache_read:0.000116,completion:0.00347,prompt:0.00602}  subgoal=work on decomposing the task steps to advance the current al
  `- s03           tool        sql_query           0.180 #         0         0          0.00020 ok    -
         in : SELECT kpi_ts,value FROM perf_15min WHERE ne='NE-ACBB-45' AND window='15
         out: ok - rows returned: 1705 3072 9462 7416
         meta: tool=alarm_db.query  params={ne_id:NE-ACBB-45,severity:major,time_window:15m}  facts=[1705 3072 9462 7416]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
    `- s03-n1        tool        sql_query           0.108 #         0         0          0.00020 ok    -
           in : nested sql_query call for NE-ACBB-45
           out: ok - rows returned: 1705 3072 9462 7416
           meta: tool=alarm_db.query  params={ne_id:NE-ACBB-45,severity:major,time_window:15m}  facts=[1705 3072 9462 7416]
           v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s04           llm         summarize           1.184 ####      2878      713        0.01247 ok    stop
         in : write the final response for NE-ACBB-45 from evidence 1705 3072 9462 741
         out: step done - summary drafted from 1705 3072 9462 7416
         meta: model=adn-llm-72b  ttft=0.1520  pv=pv-2026-03
         v3  : sys=197  cache_r=197  cost_det={cache_read:0.000148,completion:0.00428,prompt:0.00804}  verifier=v_numbers_traceable:PASS  subgoal=condensing the evidence within 15m for the current alarm lis

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=False  anomaly_types=[]
    intent=i0  pattern=p1  cell=i0|p1
    oracle dim_dev : O=1.00  P=1.00  L=0.92  C=0.51  R=1.00
    latency_true=2.821s  gen_quantiles={'C': 0.9845, 'L': 0.1548}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=[]  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.0000  model_mix_true={'adn-llm-14b': 0.6614, 'adn-llm-72b': 0.3386}  feedback_available=False
    has_golden=False  key_fact_recall_true=n/a  fact_precision_true=n/a
    hallucinated_facts=[]
    query_lang_true=en  session_turn_count_true=3  subgoal_count=3
    plan_revision_true=1  goal_drift_true=False  arg_valid_true=1.0000  verifier_pass_true=1.0000
    citation_reachable_true=n/a  contradiction_true=0.0000  contradicted_count=0  fabricated_citation_count=0
    cache_read_true=505  cache_write_true=145  system_prompt_ratio_true=0.0821  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice3-v0.3.0)
    S=54.7231  G=1.00  grade_abs=D  grade_rel=D  tier=0  novelty=False
    alert=False (rule=False stat=False)  cold_start=False  cell=i0xp0
    dims    : O=1.000  P=1.000  L=0.898  C=0.000  R=1.000
    contrib : O=+0.000  P=+0.000  L=-1.208  C=-44.069  R=+0.000   sum=-45.2769
    zero-residual: S-100G=-45.2769  |diff|=2.80e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.3201  a_cal=0.1924  conf=0.9853  anchor=anchor-R3-2d9e23adcdd4eb4e
    evidence (3 items, drill-down order):
      - [trace] cost_total               span=R3-00063-s04   value=0.0397      cell_median=0.0108      z=  +5.64 dev=0.4407
      - [trace] tokens_total             span=R3-00063-s04   value=10605.0000  cell_median=2926.0000   z=  +6.03 dev=0.4320
      - [span ] tok                      span=R3-00063-s01   value=3168.0000   peer_median=1077.0000   z=  +4.30 dev=0.3600 (L3/L3span action=plan)
```

### v3 样本 B：goal_drift —— R3-00073

某个 `subgoal_text` 与本条轨迹的 `goal_text` **没有任何内容词重叠**——智能体在这一步跑偏了。特征侧用词元包含率 `1 - |G ∩ S| / |G|` 度量：跑偏时恰好为 1.0，在轨时恰好为 0.0，所以 `goal_drift_max >= 0.5` 与真值构成严格的双向等价。生成器为此专门过滤掉任何与目标共享词元的绕路模板，否则真值会声称漂移而数据里量不出来。

```text
==============================================================================
TRACE R3-00073   [intent1: 定位网元 NE-1050-45 的劣化根因]
  ontology=ontA  session=sess-00017  turn=1/6  spans=5  wall=4.150s  ts_start=1767231891.392
  user_feedback: none captured
  answer_numbers=['9634']
  answer_facts  =['NE-1050-45', '9634']
  golden_answer =expected answer for NE-1050-45 (定位网元 NE-1050-45 的劣化根因): 9634, 1697
  golden_facts  =['NE-1050-45', '9634', '1697']
  goal_text     =劣化根因   query_lang=zh
  answer_citations  =['runbook://adn/capacity-expansion#L25']
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[-0.3302, 0.2905, 0.242, -0.3136] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run           4.150 ######### 343       119        0.00250 ok    stop
       in : 定位网元 NE-1050-45 的劣化根因
       out: completed '定位网元 NE-1050-45 的劣化根因' on NE-1050-45; values: 9634
       meta: model=adn-llm-72b  facts=[9634]
       v3  : sys=201  cache_w=201  cost_det={cache_write:0.000754,completion:0.000714,prompt:0.00103}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan                2.326 #####     1068      240        0.00525 ok    stop
         in : decompose request from NE-1050-45 over 1h into executable steps
         out: step list drafted for NE-1050-45;  candidate actions; nothing further re
         meta: model=adn-llm-14b  ttft=0.5215  pv=pv-2026-03
         v3  : sys=162  cache_w=162  cost_det={cache_write:0.000607,completion:0.00144,prompt:0.0032}  verifier=v_numbers_traceable:PASS  subgoal=整理机房空调巡检的纸质记录
  `- s02           retrieval   schema_retrieval    1.280 ###       753       0          0.00226 ok    -
         in : lookup schema for alarm tables of NE-1050-45
         out: schema rows: 4922 3725; noted for the operator
         meta: tool=catalog.table_schema  params={table:kpi_15min}  facts=[4922 3725]
         v3  : cost_det={prompt:0.00226}  arg_valid=True  retrieved=[runbook://adn/capacity-expansion#L25]
  `- s03           guard       approve             0.368 #         322       56         0.00130 ok    -
         in : route the pending change on NE-1050-45 to the approver
         out: change ticket for NE-1050-45: pass
         v3  : cost_det={completion:0.000336,prompt:0.000966}  verifier=v_no_forbidden_action:PASS
  `- s04           tool        sql_query           0.368 #         0         0          0.00020 ok    -
         in : SELECT alarm_id,severity FROM current_alarms WHERE ne='NE-1050-45' AND w
         out: step done - query settled; row ids 4773 9634
         meta: tool=perf_db.query  params={ne_id:NE-1050-45,severity:critical,time_window:1h}  facts=[4773 9634]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['unfinished']
    intent=i1  pattern=p2  cell=i1|p2
    oracle dim_dev : O=0.55  P=0.20  L=0.94  C=0.75  R=1.00
    latency_true=4.147s  gen_quantiles={'C': 0.4963, 'L': 0.1141}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': True}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=[]  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.0000  model_mix_true={'adn-llm-14b': 0.739, 'adn-llm-72b': 0.261}  feedback_available=False
    has_golden=True  key_fact_recall_true=0.6667  fact_precision_true=1.0000
    hallucinated_facts=[]
    query_lang_true=zh  session_turn_count_true=6  subgoal_count=1
    plan_revision_true=0  goal_drift_true=True  arg_valid_true=1.0000  verifier_pass_true=1.0000
    citation_reachable_true=1.0000  contradiction_true=0.0000  contradicted_count=0  fabricated_citation_count=0
    cache_read_true=0  cache_write_true=363  system_prompt_ratio_true=0.1460  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice3-v0.3.0)
    S=20.3696  G=0.25  grade_abs=D  grade_rel=D  tier=2  novelty=False
    alert=True (rule=True stat=False)  cold_start=False  cell=i1xp2
    dims    : O=0.821  P=0.620  L=0.992  C=0.823  R=1.000
    contrib : O=-1.779  P=-2.161  L=-0.028  C=-0.663  R=+0.000   sum=-4.6304
    zero-residual: S-100G=-4.6304  |diff|=5.00e-06  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.8754  a_cal=0.9361  conf=0.9589  anchor=anchor-R3-2d9e23adcdd4eb4e
    gates: {"t1_unfinished": 0.25}
    evidence (3 items, drill-down order):
      - [trace] cost_total               span=R3-00073-s01   value=0.0115      cell_median=0.0117      z=  -0.02 dev=0.0883
      - [trace] tokens_total             span=R3-00073-s01   value=2901.0000   cell_median=3291.0000   z=  -0.23 dev=0.0663
      - [span ] tok                      span=R3-00073-s02   value=753.0000    peer_median=425.0000    z=  +1.33 dev=0.2135 (L3/L3span action=schema_retrieval)
```

### v3 样本 C：invalid_tool_arg —— R3-00085

工具入参违反了本体的 `param_schema`（枚举越界 / 前缀不符）。`arg_valid` 是**测量**出来的而不是断言的：生成器构造完违规参数后会再跑一次同一个校验函数，只有确实判为违规才落库。循环与重试的副本共享同一份参数，所以一个违规组里的每个副本都同样违规——这是刻意的，否则 `(parent, action, 参数哈希)` 分组会被拆开，一个真循环就悄悄变成了非循环。

```text
==============================================================================
TRACE R3-00085   [intent0: NE-8255-26 在 1h 内的当前告警清单是什么]
  ontology=ontA  session=sess-00018  turn=7/7  spans=6  wall=4.277s  ts_start=1767232960.881
  user_feedback: none captured
  answer_numbers=['2846', '2543', '5020']
  answer_facts  =['NE-8255-26', '2846', '2543', '5020']
  golden_answer =
  golden_facts  =None
  goal_text     =当前告警清单   query_lang=zh
  answer_citations  =['kb://history/incident-2025-1187']
  contradicted_facts=['2846']
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[-0.2227, 0.2479, -0.088, 0.0285] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run           4.277 ######### 370       128        0.00157 ok    stop
       in : NE-8255-26 在 1h 内的当前告警清单是什么
       out: NE-8255-26 在 1h 内的当前告警清单是什么 for NE-8255-26: 2846, 2543, 5020
       meta: model=adn-llm-14b  facts=[2846 2543 5020]
       v3  : sys=136  cache_r=136  cost_det={cache_read:0.000102,completion:0.000768,prompt:0.000702}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan                1.988 ####      1029      435        0.00523 ok    stop
         in : decompose request from NE-8255-26 over 1h into executable steps
         out: step list drafted for NE-8255-26;  candidate actions (window 1h)
         meta: model=adn-llm-72b  ttft=0.3887  pv=pv-2026-04-canary
         v3  : sys=209  cache_r=209  cost_det={cache_read:0.000157,completion:0.00261,prompt:0.00246}  subgoal=步骤目标：拆解任务步骤，服务于当前告警清单
  `- s02           guard       verify              0.290 #         360       67         0.00148 ok    -
         in : compliance scan of the pending step set for NE-8255-26
         out: verdict pass for NE-8255-26
         v3  : cost_det={completion:0.000402,prompt:0.00108}  verifier=v_no_forbidden_action:PASS
  `- s03           retrieval   schema_retrieval    0.258 #         713       0          0.00214 error -
         in : lookup schema for alarm tables of NE-8255-26
         out: schema rows: 2543 5020 5485 9794; noted for the operator
         meta: tool=catalog.table_schema  level=ERROR  msg=connection reset by peer  params={table:not-in-enum}  facts=[2543 5020 5485 9794]
         v3  : cost_det={prompt:0.00214}  arg_valid=False  retrieved=[kb://history/incident-2025-1187 kb://history/incident-2026-0043 runbook://adn/ne-health-check#L48]
  `- s04           tool        sql_query           0.269 #         0         0          0.00020 ok    -
         in : SELECT alarm_id,severity FROM current_alarms WHERE ne='NE-8255-26' AND w
         out: checked and recorded: rows returned: 4505 2846 1128
         meta: tool=alarm_db.query  params={ne_id:NE-8255-26,severity:critical,time_window:1h}  facts=[4505 2846 1128]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s05           llm         summarize           1.271 ###       813       356        0.00420 ok    stop
         in : write the final response for NE-8255-26 from evidence 5020 5485 9794 450
         out: summary drafted from 5020 5485 9794 4505 2846 1128 (window 1h)
         meta: model=adn-llm-14b  ttft=0.1756  pv=pv-2026-04-canary
         v3  : sys=166  cache_r=166  cost_det={cache_read:0.000124,completion:0.00214,prompt:0.00194}  verifier=v_numbers_traceable:PASS  subgoal=推进当前告警清单：归纳证据

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['error']
    intent=i0  pattern=p2  cell=i0|p2
    oracle dim_dev : O=0.75  P=1.00  L=0.83  C=0.72  R=0.35
    latency_true=4.274s  gen_quantiles={'C': 0.5626, 'L': 0.3324}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=['R3-00085-s03']  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.0000  model_mix_true={'adn-llm-14b': 0.5324, 'adn-llm-72b': 0.4676}  feedback_available=False
    has_golden=False  key_fact_recall_true=n/a  fact_precision_true=n/a
    hallucinated_facts=[]
    query_lang_true=zh  session_turn_count_true=7  subgoal_count=2
    plan_revision_true=0  goal_drift_true=False  arg_valid_true=0.5000  verifier_pass_true=1.0000
    citation_reachable_true=1.0000  contradiction_true=0.2500  contradicted_count=1  fabricated_citation_count=0
    cache_read_true=511  cache_write_true=0  system_prompt_ratio_true=0.1556  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice3-v0.3.0)
    S=82.9508  G=1.00  grade_abs=B  grade_rel=C  tier=2  novelty=False
    alert=True (rule=True stat=False)  cold_start=False  cell=i0xp2
    dims    : O=0.867  P=1.000  L=0.816  C=0.696  R=0.639
    contrib : O=-5.221  P=+0.000  L=-2.786  C=-4.956  R=-4.086   sum=-17.0492
    zero-residual: S-100G=-17.0492  |diff|=1.90e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.9132  a_cal=0.9510  conf=0.9758  anchor=anchor-R3-2d9e23adcdd4eb4e
    evidence (3 items, drill-down order):
      - [trace] error_ratio              span=R3-00085-s03   value=0.1667      cell_median=0.0000      z= +50.00 dev=0.3891
      - [trace] tokens_total             span=R3-00085-s01   value=4271.0000   cell_median=3159.0000   z=  +0.73 dev=0.1467
      - [span ] tok                      span=R3-00085-s03   value=713.0000    peer_median=409.0000    z=  +1.42 dev=0.1862 (L3/L3span action=schema_retrieval)
```

### v3 样本 D：verifier_fail —— R3-00006

确定性校验器给出 FAIL。三个校验器全部是代码判定，没有任何生成式判官参与：`v_numbers_traceable`（答案里的数字必须能在证据池中找到）、`v_no_forbidden_action`（禁用动作不得被启动）、`v_answer_nonempty`（答案非空）。它们的结果是从落库记录本身反推出来的，而不是生成器的意图。

```text
==============================================================================
TRACE R3-00006   [intent0: show the current alarm list of NE-3DC2-54]
  ontology=ontA  session=sess-00001  turn=5/7  spans=4  wall=1.841s  ts_start=1767226107.169
  user_feedback: none captured
  answer_numbers=['9753', '30']
  answer_facts  =['NE-3DC2-54', '9753', '30']
  golden_answer =
  golden_facts  =None
  goal_text     =current alarm list   query_lang=en
  answer_citations  =[]
  contradicted_facts=['9753']
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[-0.6816, 0.1185, 0.1486, 0.2166] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run           1.841 ######### 340       136        0.00244 ok    length
       in : show the current alarm list of NE-3DC2-54
       out: result for NE-3DC2-54 (show the current alarm list of NE-3DC2-54): 9753,
       meta: model=adn-llm-14b  facts=[9753 30]
       v3  : sys=162  cache_w=162  cost_det={cache_write:0.000607,completion:0.000816,prompt:0.00102}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan                1.629 ########  788       373        0.00425 ok    stop
         in : task=current alarm list ne=NE-3DC2-54 window=24h; produce a step plan
         out: decompose into retrieval then aggregation; window=24h; noted for the ope
         meta: model=adn-llm-14b  ttft=0.1518  pv=pv-2026-04-canary
         v3  : sys=155  cache_r=155  cost_det={cache_read:0.000116,completion:0.00224,prompt:0.0019}  subgoal=decomposing the task steps within 24h for the current alarm 
  `- s02           tool        sql_query           0.161 #         0         0          0.00020 ok    -
         in : SELECT alarm_id,severity FROM current_alarms WHERE ne='NE-3DC2-54' AND w
         out: rows returned: 7934 2229 9753
         meta: tool=alarm_db.query  params={ne_id:NE-3DC2-54,severity:critical,time_window:24h}  facts=[7934 2229 9753]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s03           llm         summarize           0.161 #         1108      448        0.00553 ok    stop
         in : write the final response for NE-3DC2-54 from evidence 7934 2229 9753
         out: checked and recorded: answer composed citing 7934 2229 9753
         meta: model=adn-llm-72b  ttft=0.0388  pv=pv-2026-04-canary
         v3  : sys=213  cache_r=213  cost_det={cache_read:0.00016,completion:0.00269,prompt:0.00268}  verifier=v_numbers_traceable:FAIL(answer number absent from the evidence pool)  subgoal=condensing the evidence within 24h for the current alar

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['truncation']
    intent=i0  pattern=p1  cell=i0|p1
    oracle dim_dev : O=0.35  P=1.00  L=0.94  C=0.69  R=1.00
    latency_true=1.838s  gen_quantiles={'C': 0.6103, 'L': 0.1152}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=[]  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.0000  model_mix_true={'adn-llm-14b': 0.5127, 'adn-llm-72b': 0.4873}  feedback_available=False
    has_golden=False  key_fact_recall_true=n/a  fact_precision_true=n/a
    hallucinated_facts=[]
    query_lang_true=en  session_turn_count_true=7  subgoal_count=2
    plan_revision_true=0  goal_drift_true=False  arg_valid_true=1.0000  verifier_pass_true=0.5000
    citation_reachable_true=n/a  contradiction_true=0.3333  contradicted_count=1  fabricated_citation_count=0
    cache_read_true=368  cache_write_true=162  system_prompt_ratio_true=0.2370  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice3-v0.3.0)
    S=17.1976  G=0.25  grade_abs=D  grade_rel=D  tier=2  novelty=False
    alert=True (rule=True stat=False)  cold_start=False  cell=i0xp0
    dims    : O=0.440  P=1.000  L=0.975  C=0.756  R=1.000
    contrib : O=-6.849  P=+0.000  L=-0.079  C=-0.874  R=+0.000   sum=-7.8024
    zero-residual: S-100G=-7.8024  |diff|=4.90e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.9053  a_cal=0.9482  conf=0.9853  anchor=anchor-R3-2d9e23adcdd4eb4e
    gates: {"t0_result_broken": 0.25}
    evidence (3 items, drill-down order):
      - [trace] traceable_number_ratio   span=-              value=0.5000      cell_median=1.0000      z= -50.00 dev=0.3497
      - [trace] cost_total               span=R3-00006-s03   value=0.0124      cell_median=0.0108      z=  +0.31 dev=0.1042
      - [span ] tok                      span=R3-00006-s03   value=1556.0000   peer_median=1106.0000   z=  +0.79 dev=0.1393 (L3/L3span action=summarize)
```

### v3 样本 E：fabricated_citation —— R3-00056

答案引用了一个**格式完全合法**的定位符，但它不在本次检索到的结果集里。真实智能体的编造几乎从不是凭空造一个URL，而是把片段号写错——所以 `citation_reachability` 必须对着检索结果集算，而不是对着 URL 白名单或格式校验算。生成器正是这样伪造的：取一个真实定位符，把 `#L` 片段改到 1001~1900 区间。

```text
==============================================================================
TRACE R3-00056   [intent0: NE-76B9-29 的当前告警清单里还有哪些活动告警]
  ontology=ontA  session=sess-00012  turn=3/4  spans=5  wall=8.310s  ts_start=1767230451.063
  user_feedback: none captured
  answer_numbers=['5374', '66968', '74803']
  answer_facts  =['NE-76B9-29', '5374', '66968', '74803']
  golden_answer =
  golden_facts  =None
  goal_text     =当前告警清单   query_lang=zh
  answer_citations  =['doc://policy/change-approval-rules#L7', 'doc://vendor/nbi-api-reference#L310', 'runbook://adn/alarm-clear-procedure#L1444', 'runbook://adn/ne-health-check#L1339']
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=3 orphan=False ts_missing=False usage_estimated=True
  embedding[0:4]=[-0.0594, 0.2209, -0.0185, -0.1351] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run           8.310 ######### 350       121        0.00130 ok    stop
       in : NE-76B9-29 的当前告警清单里还有哪些活动告警
       out: 'NE-76B9-29 的当前告警清单里还有哪些活动告警' on NE-76B9-29 resolved; see 5374, 66968, 7
       meta: model=adn-llm-72b  facts=[5374 66968 74803]
       v3  : sys=210  cache_r=210  cost_det={cache_read:0.000158,completion:0.000726,prompt:0.00042}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan                0.331 #         766       187        0.00310 ok    stop
         in : task=当前告警清单 ne=NE-76B9-29 window=15m; produce a step plan
         out: decompose into retrieval then aggregation; window=15m
         meta: ttft=0.0775  pv=pv-2026-03
         v3  : cost_det={cache_read:0.000108,completion:0.00112,prompt:0.00187}  subgoal=步骤目标：拆解任务步骤，服务于当前告警清单
  `- s02           guard       verify              0.493 #         470       80         0.00189 ok    -
         in : compliance scan of the pending step set for NE-76B9-29
         out: verdict pass for NE-76B9-29
         v3  : cost_det={completion:0.00048,prompt:0.00141}  verifier=v_no_forbidden_action:PASS
  `- s03           retrieval   retrieve_kb         0.493 #         521       0          0.00156 ok    -
         in : runbook search: 当前告警清单 (ne=NE-76B9-29)
         out: ok - matched runbook evidence: 5374 2654
         meta: tool=kb.history_search  params={query:NE-76B9-29,top_k:10}  facts=[5374 2654]
         v3  : cost_det={prompt:0.00156}  arg_valid=True  retrieved=[doc://policy/change-approval-rules#L7 doc://vendor/nbi-api-reference#L310 kb://history/incident-2026-0043]
  `- s04           llm         summarize           7.206 ########  None      179        0.00540 ok    stop
         in : write the final response for NE-76B9-29 from evidence 5374 2654
         out: attempt finished, summary drafted from 5374 2654
         meta: model=adn-llm-14b  ttft=1.2005  pv=pv-2026-03
         v3  : sys=148  cache_r=148  cost_det={cache_read:0.000111,completion:0.00107,prompt:0.00421}  verifier=v_numbers_traceable:FAIL(answer number absent from the evidence pool)  subgoal=围绕当前告警清单执行归纳证据

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['hallucinated_number']
    intent=i0  pattern=p3  cell=i0|p3
    oracle dim_dev : O=0.15  P=1.00  L=0.62  C=0.74  R=1.00
    latency_true=8.307s  gen_quantiles={'C': 0.513, 'L': 0.7628}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': True}
    responsible_span_ids=[]  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.0833  model_mix_true={'adn-llm-14b': 0.2754, 'adn-llm-72b': 0.7246}  feedback_available=False
    has_golden=False  key_fact_recall_true=n/a  fact_precision_true=n/a
    hallucinated_facts=[]
    query_lang_true=zh  session_turn_count_true=4  subgoal_count=2
    plan_revision_true=0  goal_drift_true=False  arg_valid_true=1.0000  verifier_pass_true=0.6667
    citation_reachable_true=0.5000  contradiction_true=0.0000  contradicted_count=0  fabricated_citation_count=2
    cache_read_true=358  cache_write_true=0  system_prompt_ratio_true=0.1699  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice3-v0.3.0)
    S=16.3744  G=0.25  grade_abs=D  grade_rel=D  tier=2  novelty=False
    alert=True (rule=True stat=False)  cold_start=False  cell=i0xp1
    dims    : O=0.440  P=1.000  L=0.718  C=0.804  R=1.000
    contrib : O=-7.121  P=+0.000  L=-1.078  C=-0.426  R=+0.000   sum=-8.6256
    zero-residual: S-100G=-8.6256  |diff|=1.90e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.9344  a_cal=0.9578  conf=0.7863  anchor=anchor-R3-2d9e23adcdd4eb4e
    gates: {"t0_result_broken": 0.25}
    evidence (3 items, drill-down order):
      - [trace] traceable_number_ratio   span=-              value=0.3333      cell_median=1.0000      z= -50.00 dev=0.4023
      - [trace] missing_field_ratio      span=-              value=0.0833      cell_median=0.0000      z= +50.00 dev=0.2903
      - [span ] dur                      span=R3-00056-s04   value=7.2061      peer_median=1.6588      z=  +3.79 dev=0.2677 (L3/L3span action=summarize)
```

### v3 样本 F：contradicted_evidence —— R3-00006

答案陈述了与证据相反的关系。注意它与幻觉的区别：矛盾涉及的事实**在**证据池里，只是关系被说反了。生成器只从`golden_facts ∩ answer_facts` 里采样，从结构上保证了这一点。特征侧的 `contradiction_rate` 仍标记为`needs_model`——数据集负责提供输入与真值，数值本身要等真实 NLI 模型接上才有意义。

```text
==============================================================================
TRACE R3-00006   [intent0: show the current alarm list of NE-3DC2-54]
  ontology=ontA  session=sess-00001  turn=5/7  spans=4  wall=1.841s  ts_start=1767226107.169
  user_feedback: none captured
  answer_numbers=['9753', '30']
  answer_facts  =['NE-3DC2-54', '9753', '30']
  golden_answer =
  golden_facts  =None
  goal_text     =current alarm list   query_lang=en
  answer_citations  =[]
  contradicted_facts=['9753']
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[-0.6816, 0.1185, 0.1486, 0.2166] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run           1.841 ######### 340       136        0.00244 ok    length
       in : show the current alarm list of NE-3DC2-54
       out: result for NE-3DC2-54 (show the current alarm list of NE-3DC2-54): 9753,
       meta: model=adn-llm-14b  facts=[9753 30]
       v3  : sys=162  cache_w=162  cost_det={cache_write:0.000607,completion:0.000816,prompt:0.00102}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan                1.629 ########  788       373        0.00425 ok    stop
         in : task=current alarm list ne=NE-3DC2-54 window=24h; produce a step plan
         out: decompose into retrieval then aggregation; window=24h; noted for the ope
         meta: model=adn-llm-14b  ttft=0.1518  pv=pv-2026-04-canary
         v3  : sys=155  cache_r=155  cost_det={cache_read:0.000116,completion:0.00224,prompt:0.0019}  subgoal=decomposing the task steps within 24h for the current alarm 
  `- s02           tool        sql_query           0.161 #         0         0          0.00020 ok    -
         in : SELECT alarm_id,severity FROM current_alarms WHERE ne='NE-3DC2-54' AND w
         out: rows returned: 7934 2229 9753
         meta: tool=alarm_db.query  params={ne_id:NE-3DC2-54,severity:critical,time_window:24h}  facts=[7934 2229 9753]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s03           llm         summarize           0.161 #         1108      448        0.00553 ok    stop
         in : write the final response for NE-3DC2-54 from evidence 7934 2229 9753
         out: checked and recorded: answer composed citing 7934 2229 9753
         meta: model=adn-llm-72b  ttft=0.0388  pv=pv-2026-04-canary
         v3  : sys=213  cache_r=213  cost_det={cache_read:0.00016,completion:0.00269,prompt:0.00268}  verifier=v_numbers_traceable:FAIL(answer number absent from the evidence pool)  subgoal=condensing the evidence within 24h for the current alar

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['truncation']
    intent=i0  pattern=p1  cell=i0|p1
    oracle dim_dev : O=0.35  P=1.00  L=0.94  C=0.69  R=1.00
    latency_true=1.838s  gen_quantiles={'C': 0.6103, 'L': 0.1152}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=[]  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.0000  model_mix_true={'adn-llm-14b': 0.5127, 'adn-llm-72b': 0.4873}  feedback_available=False
    has_golden=False  key_fact_recall_true=n/a  fact_precision_true=n/a
    hallucinated_facts=[]
    query_lang_true=en  session_turn_count_true=7  subgoal_count=2
    plan_revision_true=0  goal_drift_true=False  arg_valid_true=1.0000  verifier_pass_true=0.5000
    citation_reachable_true=n/a  contradiction_true=0.3333  contradicted_count=1  fabricated_citation_count=0
    cache_read_true=368  cache_write_true=162  system_prompt_ratio_true=0.2370  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice3-v0.3.0)
    S=17.1976  G=0.25  grade_abs=D  grade_rel=D  tier=2  novelty=False
    alert=True (rule=True stat=False)  cold_start=False  cell=i0xp0
    dims    : O=0.440  P=1.000  L=0.975  C=0.756  R=1.000
    contrib : O=-6.849  P=+0.000  L=-0.079  C=-0.874  R=+0.000   sum=-7.8024
    zero-residual: S-100G=-7.8024  |diff|=4.90e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.9053  a_cal=0.9482  conf=0.9853  anchor=anchor-R3-2d9e23adcdd4eb4e
    gates: {"t0_result_broken": 0.25}
    evidence (3 items, drill-down order):
      - [trace] traceable_number_ratio   span=-              value=0.5000      cell_median=1.0000      z= -50.00 dev=0.3497
      - [trace] cost_total               span=R3-00006-s03   value=0.0124      cell_median=0.0108      z=  +0.31 dev=0.1042
      - [span ] tok                      span=R3-00006-s03   value=1556.0000   peer_median=1106.0000   z=  +0.79 dev=0.1393 (L3/L3span action=summarize)
```

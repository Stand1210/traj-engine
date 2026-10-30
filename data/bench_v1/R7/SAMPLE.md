# R7 样本阅读手册

这个文件由 `python -m bench.show R7 --sample` 生成，内容是真实数据，不是示意图。

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
| `data/bench_v1/R7/traces.jsonl` | 模拟出来的轨迹（一行一条，含完整 Span 树） | 4000 |
| `data/bench_v1/R7/gt.jsonl` | 真值：是否异常、异常类型、真实意图/模式、责任 Span | 4000 |
| `reports/R7/scores.jsonl` | 算法输出：S 分、五维、扣分归因、证据、告警 | 4000 |

JSONL = 每行一个压缩 JSON，直接打开会看到一堆没法读的长行。用下面的命令看：

```
python -m bench.show R7 R7-00001        # 看单条轨迹（输入+真值+算法输出）
python -m bench.show R7 --list latency_spike    # 列出某类异常的 trace_id
python -m bench.show R7 --stats                 # 数据集侧写
```

## 三、一条 trace 长什么样

每条 trace = 一棵 Span 树。根节点是整次 agent 执行，子节点是具体步骤（大模型调用 / 工具调用 / 知识检索 / 护栏校验），
每个节点带开始结束时间、token、成本、状态、输入输出文本。下面是真实样本。


## 四、数据集侧写


- 轨迹数 **4000**，Span 数 **21004**，平均 5.3 Span/轨迹
- 异常轨迹 **311** 条（基率 7.78%），正常 **3689** 条
- 意图分布：i0=2826，i1=1174
- 真实单元格（意图×模式）**6** 个
- 异常类型分布：token_bloat=58，latency_spike=50，loop=41，hallucinated_number=39，truncation=36，missing_step=28，error=25，unfinished=20，illegal_step=14
- `spec_hash=1bd79369786bde6f`  `gen_version=bench-gen-v3.1.0`
- v3 信号：arg_invalid_spans=123，cache_hit_spans=6606，contradiction=44，fabricated_citation=41，goal_drift=49，llm_spans=8228，plan_revision=240，verifier_fail=73
- 语种分布：en=1841，zh=2159；会话数 **883**，每会话轮次 {'max': 7, 'min': 2, 'n': 4000, 'p50': 5.0, 'p90': 7.0, 'p99': 7.0}

---

## 五、完整样本：输入 → 真值 → 算法输出

### 样本 A：一条正常轨迹（应该得高分、不告警）

```text
==============================================================================
TRACE R7-00000   [intent0: 给出 NE-353E-22 的当前告警清单，并说明每条告警的触发原因]
  ontology=ontA  session=sess-00000  turn=1/3  spans=7  wall=1.742s  ts_start=1767225590.601
  user_feedback: none captured
  answer_numbers=['2876']
  answer_facts  =['NE-353E-22', '2876']
  golden_answer =expected answer for NE-353E-22 (给出 NE-353E-22 的当前告警清单，并说明每条告警的触发原因): 2876
  golden_facts  =['NE-353E-22', '2876']
  goal_text     =当前告警清单   query_lang=zh
  answer_citations  =['doc://policy/change-approval-rules#L7', 'doc://topology/subnetwork-east-map', 'runbook://adn/capacity-expansion#L25']
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[0.157, -0.2772, 0.1513, 0.2331] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run           1.742 ######### 731       254        0.00434 ok    stop
       in : 给出 NE-353E-22 的当前告警清单，并说明每条告警的触发原因
       out: NE-353E-22 | 给出 NE-353E-22 的当前告警清单，并说明每条告警的触发原因 | observed values 2876
       meta: model=adn-llm-14b  facts=[2876]
       v3  : sys=166  cache_w=166  cost_det={cache_write:0.000623,completion:0.00152,prompt:0.00219}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan                0.180 #         1550      604        0.00902 ok    stop
         in : decompose request from NE-353E-22 over 15m into executable steps
         out: checked and recorded: step list drafted for NE-353E-22;  candidate actio
         meta: model=adn-llm-72b  ttft=0.0453  pv=pv-2026-03
         v3  : sys=198  cache_w=198  cost_det={cache_write:0.000742,completion:0.00362,prompt:0.00465}  subgoal=围绕当前告警清单执行拆解任务步骤
  `- s02           retrieval   schema_retrieval    0.428 ##        975       0          0.00293 ok    -
         in : resolve table definitions needed by NE-353E-22 query
         out: attempt finished, schema rows: 2182 2970
         meta: tool=catalog.table_schema  params={table:alarm_history}  facts=[2182 2970]
         v3  : cost_det={prompt:0.00293}  arg_valid=True  retrieved=[doc://policy/change-approval-rules#L7 doc://topology/subnetwork-east-map runbook://adn/capacity-expansion#L25]
  `- s03           guard       approve             0.182 #         724       120        0.00289 ok    -
         in : approval gate for change on NE-353E-22
         out: approval gate pass on NE-353E-22
         v3  : cost_det={completion:0.00072,prompt:0.00217}  verifier=v_no_forbidden_action:PASS
  `- s04           tool        sql_query           0.660 ###       0         0          0.00020 ok    -
         in : SELECT alarm_id,severity FROM current_alarms WHERE ne='NE-353E-22' AND w
         out: rows returned: 6785 2876; payload attached to the trace
         meta: tool=alarm_db.query  params={ne_id:NE-353E-22,severity:critical,time_window:15m}  facts=[6785 2876]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
    `- s04-n1        tool        sql_query           0.396 ##        0         0          0.00020 ok    -
           in : nested sql_query call for NE-353E-22
           out: rows returned: 6785 2876; payload attached to the trace
           meta: tool=alarm_db.query  params={ne_id:NE-353E-22,severity:critical,time_window:15m}  facts=[6785 2876]
           v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s05           llm         summarize           0.208 #         1672      245        0.00615 ok    stop
         in : write the final response for NE-353E-22 from evidence 2182 2970 6785 287
         out: attempt finished, answer composed citing 2182 2970 6785 2876
         meta: model=adn-llm-14b  ttft=0.0554  pv=pv-2026-03
         v3  : sys=148  cache_r=148  cost_det={cache_read:0.000111,completion:0.00147,prompt:0.00457}  verifier=v_numbers_traceable:PASS  subgoal=在 NE-353E-22 上为当前告警清单完成归纳证据

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=False  anomaly_types=[]
    intent=i0  pattern=p2  cell=i0|p2
    oracle dim_dev : O=1.00  P=1.00  L=0.81  C=0.52  R=1.00
    latency_true=1.739s  gen_quantiles={'C': 0.9526, 'L': 0.3834}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=[]  human_label=None  drift_segment=0
    loop_true=False  mfr_true=0.0000  model_mix_true={'adn-llm-14b': 0.574, 'adn-llm-72b': 0.426}  feedback_available=False
    has_golden=True  key_fact_recall_true=1.0000  fact_precision_true=1.0000
    hallucinated_facts=[]
    query_lang_true=zh  session_turn_count_true=3  subgoal_count=2
    plan_revision_true=0  goal_drift_true=False  arg_valid_true=1.0000  verifier_pass_true=1.0000
    citation_reachable_true=1.0000  contradiction_true=0.0000  contradicted_count=0  fabricated_citation_count=0
    cache_read_true=148  cache_write_true=364  system_prompt_ratio_true=0.0906  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice1-v0.1.0)
    S=85.1585  G=1.00  grade_abs=B  grade_rel=C  tier=0  novelty=False
    alert=False (rule=False stat=False)  cold_start=False  cell=i0xp1
    dims    : O=1.000  P=1.000  L=0.833  C=0.458  R=0.850
    contrib : O=+0.000  P=+0.000  L=-2.533  C=-10.807  R=-1.501   sum=-14.8415
    zero-residual: S-100G=-14.8415  |diff|=3.80e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.2408  a_cal=0.1062  conf=0.9882  anchor=anchor-R7-1bd79369786bde6f
    evidence (3 items, drill-down order):
      - [trace] cost_total               span=R7-00000-s01   value=0.0257      cell_median=0.0122      z=  +2.26 dev=0.2461
      - [trace] tokens_total             span=R7-00000-s01   value=6875.0000   cell_median=3331.5000   z=  +2.30 dev=0.2412
      - [span ] tok                      span=R7-00000-s00   value=985.0000    peer_median=442.0000    z=  +2.95 dev=0.2770 (L3/L3span action=agent_run)
```

### 样本 B：latency_spike —— R7-00204

某一步耗时被放大 5~20 倍。看 SPAN TREE 里的 dur(s) 列和 share 条：其中一个子步骤吃掉了几乎全部壁钟时间。真值把 L 维打到 0.10，算法应该在 L 上扣分并把责任指向那个 Span。

```text
==============================================================================
TRACE R7-00204   [intent0: 查询网元 NE-C46D-45 的当前告警清单]
  ontology=ontA  session=sess-00043  turn=3/5  spans=7  wall=9.703s  ts_start=1767238808.193
  user_feedback: none captured
  answer_numbers=['5377', '6280']
  answer_facts  =['NE-C46D-45', '5377', '6280']
  golden_answer =
  golden_facts  =None
  goal_text     =当前告警清单   query_lang=zh
  answer_citations  =[]
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[0.0197, -0.2436, -0.0143, 0.4011] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run           9.703 ######### 532       185        0.00239 ok    stop
       in : 查询网元 NE-C46D-45 的当前告警清单
       out: here is the outcome of '查询网元 NE-C46D-45 的当前告警清单' on NE-C46D-45 - 5377, 6
       meta: model=adn-llm-14b  facts=[5377 6280]
       v3  : sys=142  cache_r=142  cost_det={cache_read:0.000107,completion:0.00111,prompt:0.00117}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan                0.443 #         945       395        0.00486 ok    stop
         in : task=当前告警清单 ne=NE-C46D-45 window=15m; produce a step plan
         out: step done - step list drafted for NE-C46D-45;  candidate actions
         meta: model=adn-llm-14b  ttft=0.0603  pv=pv-2026-03
         v3  : sys=155  cache_r=155  cost_det={cache_read:0.000116,completion:0.00237,prompt:0.00237}  subgoal=步骤目标：拆解任务步骤，服务于当前告警清单
  `- s02           tool        sql_query           9.235 ######### 0         0          0.00020 ok    -
         in : SELECT kpi_ts,value FROM perf_15min WHERE ne='NE-C46D-45' AND window='15
         out: rows returned: 2711 5555; nothing further required
         meta: tool=perf_db.query  params={ne_id:NE-C46D-45,severity:minor,time_window:15m}  facts=[2711 5555]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s03           tool        api_call            0.173 #         0         0          0.00020 ok    -
         in : GET /nbi/v1/ne/NE-C46D-45/status?detail=true
         out: northbound returned objects 6280 5377 8098; payload attached to the trac
         meta: tool=nbi.ne_status  level=WARNING  msg=partial result set returned  params={ne_id:NE-C46D-45,scope:subnetwork}  facts=[6280 5377 8098]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s04           guard       approve             0.018 #         651       106        0.00259 ok    -
         in : route the pending change on NE-C46D-45 to the approver
         out: approval gate pass on NE-C46D-45
         v3  : cost_det={completion:0.000636,prompt:0.00195}  verifier=v_no_forbidden_action:PASS
  `- s05           guard       verify              0.181 #         433       94         0.00186 ok    -
         in : policy check on pending action for NE-C46D-45
         out: verdict pass for NE-C46D-45
         v3  : cost_det={completion:0.000564,prompt:0.0013}  verifier=v_no_forbidden_action:PASS
  `- s06           llm         summarize           0.705 #         970       310        0.00433 ok    stop
         in : write the final response for NE-C46D-45 from evidence 2711 5555 6280 537
         out: answer composed citing 2711 5555 6280 5377 8098 (window 15m)
         meta: model=adn-llm-72b  ttft=0.1145  pv=pv-2026-03
         v3  : sys=197  cache_r=197  cost_det={cache_read:0.000148,completion:0.00186,prompt:0.00232}  verifier=v_numbers_traceable:PASS  subgoal=推进当前告警清单：归纳证据

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['latency_spike']
    intent=i0  pattern=p1  cell=i0|p1
    oracle dim_dev : O=1.00  P=1.00  L=0.10  C=0.58  R=1.00
    latency_true=9.700s  gen_quantiles={'C': 0.8326, 'L': 0.6692}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=['R7-00204-s02']  human_label=None  drift_segment=0
    loop_true=False  mfr_true=0.0000  model_mix_true={'adn-llm-14b': 0.6164, 'adn-llm-72b': 0.3836}  feedback_available=False
    has_golden=False  key_fact_recall_true=n/a  fact_precision_true=n/a
    hallucinated_facts=[]
    query_lang_true=zh  session_turn_count_true=5  subgoal_count=2
    plan_revision_true=0  goal_drift_true=False  arg_valid_true=1.0000  verifier_pass_true=1.0000
    citation_reachable_true=n/a  contradiction_true=0.0000  contradicted_count=0  fabricated_citation_count=0
    cache_read_true=494  cache_write_true=0  system_prompt_ratio_true=0.1399  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice1-v0.1.0)
    S=51.7688  G=1.00  grade_abs=D  grade_rel=D  tier=0  novelty=False
    alert=False (rule=False stat=False)  cold_start=False  cell=i0xp0
    dims    : O=1.000  P=1.000  L=0.000  C=0.621  R=1.000
    contrib : O=+0.000  P=+0.000  L=-42.988  C=-5.244  R=+0.000   sum=-48.2312
    zero-residual: S-100G=-48.2312  |diff|=3.30e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.3308  a_cal=0.2045  conf=0.9943  anchor=anchor-R7-1bd79369786bde6f
    evidence (3 items, drill-down order):
      - [trace] latency_total            span=R7-00204-s00   value=9.7027      cell_median=1.9595      z=  +7.45 dev=0.4211
      - [trace] branch_factor            span=-              value=6.0000      cell_median=3.0000      z=  +4.05 dev=0.2793
      - [span ] dur                      span=R7-00204-s02   value=9.2348      peer_median=0.3735      z= +27.32 dev=0.7856 (L3/L3span action=sql_query)
```

### 样本 C：hallucinated_number（带 golden） —— R7-00504

最终答案里出现了检索证据中不存在的数字。对比子 Span 的 `out: evidence: ...` 与根 Span 的 `out: answer: ...`：后者多出了两个 5 位数。这是唯一一个靠文本内容判定的异常（`traceable_number_ratio` 特征）。

这条带 golden。看 GROUND TRUTH 里的 `fact_precision_true` 与 `key_fact_recall_true`：编造数字只压 precision，recall 仍为 1.00——答案里的事实都在，只是多了不该有的。`hallucinated_facts` 直接列出多出来的那几个。

```text
==============================================================================
TRACE R7-00504   [intent0: 我需要 NE-FFCB-14 的当前告警清单，若存在紧急告警请标记出来]
  ontology=ontA  session=sess-00107  turn=5/5  spans=6  wall=2.591s  ts_start=1767258268.229
  user_feedback: none captured
  answer_numbers=['1347', '49541', '99344']
  answer_facts  =['NE-FFCB-14', '1347', '49541', '99344']
  golden_answer =expected answer for NE-FFCB-14 (我需要 NE-FFCB-14 的当前告警清单，若存在紧急告警请标记出来): 1347
  golden_facts  =['NE-FFCB-14', '1347']
  goal_text     =当前告警清单   query_lang=zh
  answer_citations  =[]
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[0.0992, -0.411, -0.0026, 0.1597] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run           2.591 ######### 237       82         0.00085 ok    stop
       in : 我需要 NE-FFCB-14 的当前告警清单，若存在紧急告警请标记出来
       out: answer to '我需要 NE-FFCB-14 的当前告警清单，若存在紧急告警请标记出来' on NE-FFCB-14 over 15m: 
       meta: model=adn-llm-14b  facts=[1347 49541 99344]
       v3  : sys=155  cache_r=155  cost_det={cache_read:0.000116,completion:0.000492,prompt:0.000246}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan                0.385 #         915       202        0.00346 ok    stop
         in : decompose request from NE-FFCB-14 over 15m into executable steps
         out: step done - decompose into retrieval then aggregation; window=15m
         meta: model=adn-llm-72b  ttft=0.0258  pv=pv-2026-03
         v3  : sys=220  cache_r=220  cost_det={cache_read:0.000165,completion:0.00121,prompt:0.00209}  subgoal=为当前告警清单拆解任务步骤
  `- s02           llm         plan                0.154 #         621       83         0.00200 ok    stop
         in : task=当前告警清单 ne=NE-FFCB-14 window=15m; produce a step plan
         out: step list drafted for NE-FFCB-14;  candidate actions; payload attached t
         meta: model=adn-llm-14b  ttft=0.0429  pv=pv-2026-03
         v3  : sys=161  cache_r=161  cost_det={cache_read:0.000121,completion:0.000498,prompt:0.00138}  subgoal=针对当前告警清单进行拆解任务步骤（窗口 15m）
  `- s03           tool        sql_query           0.815 ###       0         0          0.00020 ok    -
         in : SELECT kpi_ts,value FROM perf_15min WHERE ne='NE-FFCB-14' AND window='15
         out: rows returned: 1347 7458 (window 15m)
         meta: tool=alarm_db.query  params={ne_id:NE-FFCB-14,severity:minor,time_window:15m}  facts=[1347 7458]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s04           guard       verify              0.513 ##        175       73         0.00096 ok    -
         in : policy check on pending action for NE-FFCB-14
         out: policy evaluation on NE-FFCB-14: pass
         v3  : cost_det={completion:0.000438,prompt:0.000525}  verifier=v_no_forbidden_action:PASS
  `- s05           llm         summarize           0.761 ###       625       168        0.00253 ok    stop
         in : condense evidence 1347 7458 into an operator-facing answer
         out: summary drafted from 1347 7458 for NE-FFCB-14
         meta: model=adn-llm-14b  ttft=0.1178  pv=pv-2026-03
         v3  : sys=158  cache_r=158  cost_det={cache_read:0.000119,completion:0.00101,prompt:0.0014}  verifier=v_numbers_traceable:FAIL(answer number absent from the evidence pool)  subgoal=为当前告警清单归纳证据

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['hallucinated_number']
    intent=i0  pattern=p1  cell=i0|p1
    oracle dim_dev : O=0.15  P=1.00  L=0.60  C=0.90  R=1.00
    latency_true=2.588s  gen_quantiles={'C': 0.2046, 'L': 0.8015}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=[]  human_label=None  drift_segment=0
    loop_true=False  mfr_true=0.0000  model_mix_true={'adn-llm-14b': 0.6192, 'adn-llm-72b': 0.3808}  feedback_available=False
    has_golden=True  key_fact_recall_true=1.0000  fact_precision_true=0.5000
    hallucinated_facts=['49541', '99344']
    query_lang_true=zh  session_turn_count_true=5  subgoal_count=3
    plan_revision_true=1  goal_drift_true=False  arg_valid_true=1.0000  verifier_pass_true=0.6667
    citation_reachable_true=n/a  contradiction_true=0.0000  contradicted_count=0  fabricated_citation_count=0
    cache_read_true=694  cache_write_true=0  system_prompt_ratio_true=0.2697  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice1-v0.1.0)
    S=17.5333  G=0.25  grade_abs=D  grade_rel=D  tier=2  novelty=False
    alert=True (rule=True stat=False)  cold_start=False  cell=i0xp0
    dims    : O=0.533  P=1.000  L=0.690  C=0.811  R=0.850
    contrib : O=-5.292  P=+0.000  L=-1.172  C=-0.661  R=-0.342   sum=-7.4667
    zero-residual: S-100G=-7.4667  |diff|=8.88e-16  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.9231  a_cal=0.9765  conf=0.9943  anchor=anchor-R7-1bd79369786bde6f
    gates: {"t0_result_broken": 0.25}
    evidence (3 items, drill-down order):
      - [trace] traceable_number_ratio   span=-              value=0.3333      cell_median=1.0000      z= -50.00 dev=0.3341
      - [trace] branch_factor            span=-              value=5.0000      cell_median=3.0000      z=  +2.70 dev=0.1783
      - [span ] dur                      span=R7-00504-s04   value=0.5134      peer_median=0.1731      z=  +2.24 dev=0.1941 (L3/L3span action=verify)
```

### 样本 D：loop —— R7-00043

同一步骤被重复插入 3~5 次。SPAN TREE 里会看到连续多行相同 action，时间戳也相同（生成器直接复制了 Span）。

```text
==============================================================================
TRACE R7-00043   [intent0: list every entry in the current alarm list of network element NE-20FD-54]
  ontology=ontA  session=sess-00011  turn=3/5  spans=9  wall=1.623s  ts_start=1767228389.502
  user_feedback: none captured
  answer_numbers=['5519', '5562']
  answer_facts  =['NE-20FD-54', '5519', '5562']
  golden_answer =
  golden_facts  =None
  goal_text     =current alarm list   query_lang=en
  answer_citations  =[]
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[0.0923, -0.1715, 0.1124, 0.1153] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run           1.623 ######### 358       143        0.00157 ok    stop
       in : list every entry in the current alarm list of network element NE-20FD-54
       out: list every entry in the current alarm list of network element NE-20FD-54
       meta: model=adn-llm-14b  facts=[5519 5562]
       v3  : sys=160  cache_r=160  cost_det={cache_read:0.00012,completion:0.000858,prompt:0.000594}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan                0.175 #         499       317        0.00305 ok    stop
         in : task=current alarm list ne=NE-20FD-54 window=15m; produce a step plan
         out: decompose into retrieval then aggregation; window=15m; noted for the ope
         meta: model=adn-llm-14b  ttft=0.0315  pv=pv-2026-03
         v3  : sys=153  cache_r=153  cost_det={cache_read:0.000115,completion:0.0019,prompt:0.00104}  subgoal=search the training vault for slide decks
  `- s02           guard       verify              0.175 #         160       53         0.00080 ok    -
         in : compliance scan of the pending step set for NE-20FD-54
         out: policy evaluation on NE-20FD-54: pass
         v3  : cost_det={completion:0.000318,prompt:0.00048}  verifier=v_no_forbidden_action:PASS
  `- s03           tool        sql_query           0.655 ####      0         0          0.00020 ok    -
         in : SELECT alarm_id,severity FROM current_alarms WHERE ne='NE-20FD-54' AND w
         out: rows returned: 1635 9682 9453 5646 for NE-20FD-54
         meta: tool=alarm_db.query  params={ne_id:NE-20FD-54,severity:major,time_window:15m}  facts=[1635 9682 9453 5646]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s04           tool        sql_query           0.655 ####      0         0          0.00020 ok    -
         in : SELECT alarm_id,severity FROM current_alarms WHERE ne='NE-20FD-54' AND w
         out: rows returned: 2309 6036 4506; payload attached to the trace
         meta: tool=alarm_db.query  params={ne_id:NE-20FD-54,severity:major,time_window:15m}  facts=[2309 6036 4506]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s05           tool        sql_query           0.655 ####      0         0          0.00020 ok    -
         in : SELECT alarm_id,severity FROM current_alarms WHERE ne='NE-20FD-54' AND w
         out: query settled; row ids 5562 5519 6880 (window 15m)
         meta: tool=alarm_db.query  params={ne_id:NE-20FD-54,severity:major,time_window:15m}  facts=[5562 5519 6880]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s06           tool        sql_query           0.655 ####      0         0          0.00020 ok    -
         in : SELECT kpi_ts,value FROM perf_15min WHERE ne='NE-20FD-54' AND window='15
         out: query settled; row ids 7106 6440 6532 4545 (window 15m)
         meta: tool=alarm_db.query  params={ne_id:NE-20FD-54,severity:major,time_window:15m}  facts=[7106 6440 6532 4545]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s07           tool        sql_query           0.655 ####      0         0          0.00020 ok    -
         in : SELECT alarm_id,severity FROM current_alarms WHERE ne='NE-20FD-54' AND w
         out: rows returned: 9111 4885 for NE-20FD-54
         meta: tool=alarm_db.query  params={ne_id:NE-20FD-54,severity:major,time_window:15m}  facts=[9111 4885]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s08           llm         summarize           0.733 ####      972       550        0.00585 ok    stop
         in : condense evidence 7106 6440 6532 4545 9111 4885 into an operator-facing 
         out: answer composed citing 7106 6440 6532 4545 9111 4885 (window 15m)
         meta: model=adn-llm-14b  ttft=0.0587  pv=pv-2026-03
         v3  : sys=161  cache_r=161  cost_det={cache_read:0.000121,completion:0.0033,prompt:0.00243}  verifier=v_numbers_traceable:PASS  subgoal=work on condensing the evidence to advance the current alarm

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['loop']
    intent=i0  pattern=p1  cell=i0|p1
    oracle dim_dev : O=1.00  P=0.50  L=0.73  C=0.67  R=0.55
    latency_true=1.621s  gen_quantiles={'C': 0.654, 'L': 0.5448}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=['R7-00043-s03', 'R7-00043-s04', 'R7-00043-s05', 'R7-00043-s06', 'R7-00043-s07']  human_label=None  drift_segment=0
    loop_true=True  mfr_true=0.0000  model_mix_true={'adn-llm-14b': 1.0}  feedback_available=False
    has_golden=False  key_fact_recall_true=n/a  fact_precision_true=n/a
    hallucinated_facts=[]
    query_lang_true=en  session_turn_count_true=5  subgoal_count=2
    plan_revision_true=0  goal_drift_true=True  arg_valid_true=1.0000  verifier_pass_true=1.0000
    citation_reachable_true=n/a  contradiction_true=0.0000  contradicted_count=0  fabricated_citation_count=0
    cache_read_true=474  cache_write_true=0  system_prompt_ratio_true=0.2383  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice1-v0.1.0)
    S=30.9762  G=0.35  grade_abs=D  grade_rel=D  tier=2  novelty=False
    alert=True (rule=True stat=False)  cold_start=False  cell=i0xp0
    dims    : O=1.000  P=0.800  L=0.863  C=0.770  R=0.850
    contrib : O=+0.000  P=-1.470  L=-0.727  C=-1.291  R=-0.535   sum=-4.0238
    zero-residual: S-100G=-4.0238  |diff|=4.70e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.9361  a_cal=0.9789  conf=0.9943  anchor=anchor-R7-1bd79369786bde6f
    gates: {"loop_runaway": 0.35}
    evidence (3 items, drill-down order):
      - [trace] branch_factor            span=-              value=8.0000      cell_median=3.0000      z=  +6.75 dev=0.3463
      - [trace] n_spans                  span=-              value=9.0000      cell_median=5.0000      z=  +2.70 dev=0.3341
      - [span ] dur                      span=R7-00043-s03   value=0.6547      peer_median=0.3735      z=  +0.87 dev=0.1303 (L3/L3span action=sql_query)
```

### 样本 E：token_bloat —— R7-00021

某个 LLM 步骤的 token 被放大 4~10 倍，耗时不变。只有成本维（C）会崩，时延维不崩——用来验证五维不会互相污染。

```text
==============================================================================
TRACE R7-00021   [intent0: 先取 NE-43A6-27 在 15m 内的当前告警清单，再总结最严重的三条]
  ontology=ontA  session=sess-00006  turn=3/3  spans=5  wall=1.862s  ts_start=1767226965.355
  user_feedback: none captured
  answer_numbers=[]
  answer_facts  =[]
  golden_answer =
  golden_facts  =None
  goal_text     =当前告警清单   query_lang=zh
  answer_citations  =['runbook://adn/alarm-clear-procedure#L12']
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[-0.0463, -0.4667, 0.3415, 0.2297] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run           1.862 ######### 287       100        0.00112 ok    stop
       in : 先取 NE-43A6-27 在 15m 内的当前告警清单，再总结最严重的三条
       out: 先取 NE-43A6-27 在 15m 内的当前告警清单，再总结最严重的三条 for NE-43A6-27: operation complet
       meta: model=adn-llm-14b
       v3  : sys=150  cache_r=150  cost_det={cache_read:0.000112,completion:0.0006,prompt:0.000411}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan                0.378 ##        4415      1517       0.02197 ok    stop
         in : task=当前告警清单 ne=NE-43A6-27 window=15m; produce a step plan
         out: attempt finished, step list drafted for NE-43A6-27;  candidate actions
         meta: model=adn-llm-14b  ttft=0.0696  pv=pv-2026-03
         v3  : sys=166  cache_r=166  cost_det={cache_read:0.000124,completion:0.0091,prompt:0.0127}  subgoal=在 NE-43A6-27 上为当前告警清单完成拆解任务步骤
  `- s02           guard       verify              0.142 #         161       60         0.00084 ok    -
         in : policy check on pending action for NE-43A6-27
         out: verdict pass for NE-43A6-27
         v3  : cost_det={completion:0.00036,prompt:0.000483}  verifier=v_no_forbidden_action:PASS
  `- s03           retrieval   retrieve_kb         0.423 ##        332       0          0.00100 ok    -
         in : runbook search: 当前告警清单 (ne=NE-43A6-27)
         out: matched runbook evidence: 2691 7903 7274 7739; payload attached to the t
         meta: tool=kb.runbook_search  params={query:NE-43A6-27,top_k:3}  facts=[2691 7903 7274 7739]
         v3  : cost_det={prompt:0.000996}  arg_valid=True  retrieved=[runbook://adn/alarm-clear-procedure#L12]
  `- s04           llm         summarize           0.835 ####      688       65         0.00213 ok    stop
         in : write the final response for NE-43A6-27 from evidence 2691 7903 7274 773
         out: ok - summary drafted from 2691 7903 7274 7739
         meta: model=adn-llm-14b  ttft=0.1512  pv=pv-2026-03
         v3  : sys=146  cache_r=146  cost_det={cache_read:0.00011,completion:0.00039,prompt:0.00163}  verifier=v_numbers_traceable:PASS  subgoal=围绕当前告警清单执行归纳证据

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['token_bloat']
    intent=i0  pattern=p3  cell=i0|p3
    oracle dim_dev : O=1.00  P=1.00  L=0.77  C=0.12  R=1.00
    latency_true=1.859s  gen_quantiles={'C': 0.3429, 'L': 0.4612}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=['R7-00021-s01']  human_label=None  drift_segment=0
    loop_true=False  mfr_true=0.0000  model_mix_true={'adn-llm-14b': 1.0}  feedback_available=False
    has_golden=False  key_fact_recall_true=n/a  fact_precision_true=n/a
    hallucinated_facts=[]
    query_lang_true=zh  session_turn_count_true=3  subgoal_count=2
    plan_revision_true=0  goal_drift_true=False  arg_valid_true=1.0000  verifier_pass_true=1.0000
    citation_reachable_true=1.0000  contradiction_true=n/a  contradicted_count=0  fabricated_citation_count=0
    cache_read_true=462  cache_write_true=0  system_prompt_ratio_true=0.0785  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice1-v0.1.0)
    S=80.3807  G=1.00  grade_abs=B  grade_rel=D  tier=0  novelty=False
    alert=False (rule=False stat=False)  cold_start=False  cell=i0xp2
    dims    : O=0.930  P=1.000  L=0.802  C=0.381  R=1.000
    contrib : O=-2.268  P=+0.000  L=-3.227  C=-14.125  R=+0.000   sum=-19.6193
    zero-residual: S-100G=-19.6193  |diff|=7.00e-06  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.2677  a_cal=0.1301  conf=0.9834  anchor=anchor-R7-1bd79369786bde6f
    evidence (3 items, drill-down order):
      - [trace] tokens_total             span=R7-00021-s01   value=7625.0000   cell_median=3292.5000   z=  +2.76 dev=0.2715
      - [trace] cost_total               span=R7-00021-s01   value=0.0271      cell_median=0.0117      z=  +2.63 dev=0.2684
      - [span ] tok                      span=R7-00021-s01   value=5932.0000   peer_median=1045.0000   z=  +8.61 dev=0.4789 (L3/L3span action=plan)
```

### 样本 F：illegal_step —— R7-00469

插入了本体禁止的动作（如 `force_delete` / `skip_approval_execute`）。这是确定性违规，走规则闸门（alert_rule=True）而不是统计异常。

```text
==============================================================================
TRACE R7-00469   [intent0: NE-B3F0-14 在 5m 内的当前告警清单是什么]
  ontology=ontA  session=sess-00099  turn=2/6  spans=7  wall=3.173s  ts_start=1767255992.965
  user_feedback: none captured
  answer_numbers=[]
  answer_facts  =[]
  golden_answer =
  golden_facts  =None
  goal_text     =当前告警清单   query_lang=zh
  answer_citations  =[]
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[-0.1314, -0.3735, -0.1833, 0.006] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run           3.173 ######### 341       118        0.00125 ok    stop
       in : NE-B3F0-14 在 5m 内的当前告警清单是什么
       out: 'NE-B3F0-14 在 5m 内的当前告警清单是什么' on NE-B3F0-14 finished with an empty resul
       meta: model=adn-llm-72b
       v3  : sys=214  cache_r=214  cost_det={cache_read:0.00016,completion:0.000708,prompt:0.000381}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan                0.664 ##        725       305        0.00363 ok    stop
         in : task=当前告警清单 ne=NE-B3F0-14 window=5m; produce a step plan
         out: step list drafted for NE-B3F0-14;  candidate actions; noted for the oper
         meta: model=adn-llm-14b  ttft=0.1685  pv=pv-2026-03
         v3  : sys=165  cache_r=165  cost_det={cache_read:0.000124,completion:0.00183,prompt:0.00168}  subgoal=针对当前告警清单进行拆解任务步骤（窗口 5m）
  `- s02           guard       verify              0.332 #         395       36         0.00140 ok    -
         in : policy check on pending action for NE-B3F0-14
         out: policy evaluation on NE-B3F0-14: pass
         v3  : cost_det={completion:0.000216,prompt:0.00119}  verifier=v_no_forbidden_action:PASS
  `- s03           tool        skip_approval_execute    0.066 #         0         0          0.00020 ok    -
         in : push configuration to NE-B3F0-14 with the gate disabled
         out: checked and recorded: gate bypassed on NE-B3F0-14; ids 3668 3188 4695 54
         meta: tool=nbi.config_apply_nocheck  facts=[3668 3188 4695 5482]
         v3  : cost_det={tool_call:0.0002}
  `- s04           tool        sql_query           0.752 ##        0         0          0.00020 ok    -
         in : SELECT kpi_ts,value FROM perf_15min WHERE ne='NE-B3F0-14' AND window='5m
         out: rows returned: 9035 9990 8955 for NE-B3F0-14
         meta: tool=perf_db.query  params={ne_id:NE-B3F0-14,severity:not-in-enum,time_window:5m}  facts=[9035 9990 8955]
         v3  : cost_det={tool_call:0.0002}  arg_valid=False
  `- s05           guard       approve             0.155 #         224       83         0.00117 ok    -
         in : approval gate for change on NE-B3F0-14
         out: approval gate pass on NE-B3F0-14
         v3  : cost_det={completion:0.000498,prompt:0.000672}  verifier=v_no_forbidden_action:FAIL(forbidden action before gate: skip_approval_execute)
  `- s06           llm         summarize           1.119 ###       1063      198        0.00406 ok    stop
         in : condense evidence 3188 4695 5482 9035 9990 8955 into an operator-facing 
         out: step done - summary drafted from 3188 4695 5482 9035 9990 8955
         meta: model=adn-llm-14b  ttft=0.3117  pv=pv-2026-03
         v3  : sys=143  cache_r=143  cost_det={cache_read:0.000107,completion:0.00119,prompt:0.00276}  verifier=v_numbers_traceable:PASS  subgoal=浏览与本次请求无关的计费台账

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['illegal_step']
    intent=i0  pattern=p1  cell=i0|p1
    oracle dim_dev : O=1.00  P=0.05  L=0.54  C=0.75  R=1.00
    latency_true=3.170s  gen_quantiles={'C': 0.4905, 'L': 0.9219}
    process_flags={'illegal_step': True, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=['R7-00469-s03']  human_label=None  drift_segment=0
    loop_true=False  mfr_true=0.0172  model_mix_true={'adn-llm-14b': 0.8331, 'adn-llm-72b': 0.1669}  feedback_available=False
    has_golden=False  key_fact_recall_true=n/a  fact_precision_true=n/a
    hallucinated_facts=[]
    query_lang_true=zh  session_turn_count_true=6  subgoal_count=2
    plan_revision_true=0  goal_drift_true=True  arg_valid_true=0.0000  verifier_pass_true=0.7500
    citation_reachable_true=n/a  contradiction_true=n/a  contradicted_count=0  fabricated_citation_count=0
    cache_read_true=522  cache_write_true=0  system_prompt_ratio_true=0.1900  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice1-v0.1.0)
    S=22.5140  G=0.30  grade_abs=D  grade_rel=D  tier=2  novelty=False
    alert=True (rule=True stat=False)  cold_start=False  cell=i0xp0
    dims    : O=0.930  P=0.550  L=0.588  C=0.757  R=1.000
    contrib : O=-0.658  P=-3.389  L=-2.255  C=-1.183  R=+0.000   sum=-7.4860
    zero-residual: S-100G=-7.4860  |diff|=3.10e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.9377  a_cal=0.9792  conf=0.9857  anchor=anchor-R7-1bd79369786bde6f
    gates: {"forbidden_action": 0.3}
    evidence (3 items, drill-down order):
      - [trace] branch_factor            span=-              value=6.0000      cell_median=3.0000      z=  +4.05 dev=0.2793
      - [trace] n_spans                  span=-              value=7.0000      cell_median=5.0000      z=  +1.35 dev=0.2171
      - [span ] dur                      span=R7-00469-s00   value=3.1729      peer_median=1.9592      z=  +1.17 dev=0.1658 (L3/L3span action=agent_run)
```

### 样本 G：truncation（带 golden） —— R7-00994

根 Span 的 `finish_reason=length`，答案被截断，结果维（O）重罚。

这条带 golden。与上一个样本对着看：截断只压 `key_fact_recall_true`，precision 仍为 1.00——说出来的都对，只是没说完。生成器故意把“不完整”与“不忠实”做成可分离的两类，否则O 维会把两种完全不同的失败打成同一个分。

```text
==============================================================================
TRACE R7-00994   [intent0: show the current alarm list of NE-C06C-06]
  ontology=ontA  session=sess-00211  turn=7/7  spans=4  wall=1.175s  ts_start=1767290003.315
  user_feedback: none captured
  answer_numbers=['9613', '84']
  answer_facts  =['NE-C06C-06', '9613', '84']
  golden_answer =expected answer for NE-C06C-06 (show the current alarm list of NE-C06C-06): 9613, 5617
  golden_facts  =['NE-C06C-06', '9613', '5617']
  goal_text     =current alarm list   query_lang=en
  answer_citations  =['runbook://adn/capacity-expansion#L1271']
  contradicted_facts=['9613']
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[0.1702, -0.3828, 0.4253, -0.0567] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run           1.175 ######### 397       159        0.00181 ok    length
       in : show the current alarm list of NE-C06C-06
       out: operator summary for NE-C06C-06 (show the current alarm list of NE-C06C-
       meta: model=adn-llm-14b  facts=[9613 84]
       v3  : sys=150  cache_r=150  cost_det={cache_read:0.000112,completion:0.000954,prompt:0.000741}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan                0.386 ###       882       349        0.00438 ok    stop
         in : task=current alarm list ne=NE-C06C-06 window=1h; produce a step plan
         out: decompose into retrieval then aggregation; window=1h for NE-C06C-06
         meta: model=adn-llm-14b  level=WARNING  ttft=0.0212  pv=pv-2026-03  msg=partial result set returned
         v3  : sys=161  cache_r=161  cost_det={cache_read:0.000121,completion:0.00209,prompt:0.00216}  subgoal=advance the current alarm list by decomposing the task steps
  `- s02           tool        sql_query           0.386 ###       0         0          0.00020 ok    -
         in : SELECT alarm_id,severity FROM current_alarms WHERE ne='NE-C06C-06' AND w
         out: rows returned: 1497 9613 for NE-C06C-06
         meta: tool=alarm_db.query  params={ne_id:NE-C06C-06,severity:minor,time_window:1h}  facts=[1497 9613]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s03           llm         summarize           0.745 ######    1472      267        0.00554 ok    stop
         in : condense evidence 1497 9613 into an operator-facing answer
         out: answer composed citing 1497 9613; nothing further required
         meta: model=adn-llm-72b  ttft=0.0274  pv=pv-2026-03
         v3  : sys=212  cache_r=212  cost_det={cache_read:0.000159,completion:0.0016,prompt:0.00378}  verifier=v_numbers_traceable:FAIL(answer number absent from the evidence pool)  subgoal=advance the current alarm list by condensing the eviden

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['truncation']
    intent=i0  pattern=p1  cell=i0|p1
    oracle dim_dev : O=0.35  P=1.00  L=0.69  C=0.63  R=1.00
    latency_true=1.172s  gen_quantiles={'C': 0.7342, 'L': 0.6186}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=[]  human_label=None  drift_segment=0
    loop_true=False  mfr_true=0.0000  model_mix_true={'adn-llm-14b': 0.5068, 'adn-llm-72b': 0.4932}  feedback_available=False
    has_golden=True  key_fact_recall_true=0.6667  fact_precision_true=0.6667
    hallucinated_facts=['84']
    query_lang_true=en  session_turn_count_true=7  subgoal_count=2
    plan_revision_true=0  goal_drift_true=False  arg_valid_true=1.0000  verifier_pass_true=0.5000
    citation_reachable_true=0.0000  contradiction_true=0.3333  contradicted_count=1  fabricated_citation_count=1
    cache_read_true=523  cache_write_true=0  system_prompt_ratio_true=0.1901  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice1-v0.1.0)
    S=16.3138  G=0.25  grade_abs=D  grade_rel=D  tier=2  novelty=False
    alert=True (rule=True stat=False)  cold_start=False  cell=i0xp0
    dims    : O=0.390  P=1.000  L=0.948  C=0.755  R=1.000
    contrib : O=-7.664  P=+0.000  L=-0.164  C=-0.858  R=+0.000   sum=-8.6862
    zero-residual: S-100G=-8.6862  |diff|=2.60e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.9084  a_cal=0.9734  conf=0.9943  anchor=anchor-R7-1bd79369786bde6f
    gates: {"t0_result_broken": 0.25}
    evidence (3 items, drill-down order):
      - [trace] traceable_number_ratio   span=-              value=0.5000      cell_median=1.0000      z= -50.00 dev=0.3078
      - [trace] tokens_total             span=R7-00994-s03   value=3526.0000   cell_median=2939.5000   z=  +0.44 dev=0.1049
      - [span ] tok                      span=R7-00994-s03   value=1739.0000   peer_median=1111.0000   z=  +1.17 dev=0.1543 (L3/L3span action=summarize)
```

### 样本 H：missing_step —— R7-00079

本体要求的必须步骤被删掉一个，过程维（P）扣分。

```text
==============================================================================
TRACE R7-00079   [intent0: 请列出网元 NE-3CB3-19 当前告警清单中的每一条记录]
  ontology=ontA  session=sess-00017  turn=3/4  spans=5  wall=0.927s  ts_start=1767230721.612
  user_feedback: none captured
  answer_numbers=['8848', '1486']
  answer_facts  =['NE-3CB3-19', '8848', '1486']
  golden_answer =
  golden_facts  =None
  goal_text     =当前告警清单   query_lang=zh
  answer_citations  =['kb://history/incident-2026-0043']
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[0.118, -0.4552, -0.0119, 0.3861] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run           0.927 ######### 357       124        0.00237 ok    stop
       in : 请列出网元 NE-3CB3-19 当前告警清单中的每一条记录
       out: operator summary for NE-3CB3-19 (请列出网元 NE-3CB3-19 当前告警清单中的每一条记录): 8848, 
       meta: model=adn-llm-14b  facts=[8848 1486]
       v3  : sys=148  cache_w=148  cost_det={cache_write:0.000555,completion:0.000744,prompt:0.00107}  verifier=v_answer_nonempty:PASS
  `- s01           retrieval   retrieve_kb         0.030 #         633       0          0.00190 ok    -
         in : runbook search: 当前告警清单 (ne=NE-3CB3-19)
         out: knowledge hits ranked: 1220 8848 4641 4583; payload attached to the trac
         meta: tool=kb.history_search  params={query:NE-3CB3-19,top_k:3}  facts=[1220 8848 4641 4583]
         v3  : cost_det={prompt:0.0019}  arg_valid=True  retrieved=[kb://history/incident-2026-0043]
  `- s02           guard       verify              0.262 ###       421       116        0.00196 ok    -
         in : compliance scan of the pending step set for NE-3CB3-19
         out: verdict pass for NE-3CB3-19
         v3  : cost_det={completion:0.000696,prompt:0.00126}  verifier=v_no_forbidden_action:PASS
  `- s03           tool        api_call            0.262 ###       0         0          0.00020 ok    -
         in : GET /nbi/v1/ne/NE-3CB3-19/status?detail=true
         out: response payload ids: 1486 9879
         meta: tool=nbi.alarm_list  params={ne_id:NE-3CB3-19,scope:subnetwork}  facts=[1486 9879]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s04           llm         summarize           0.586 ######    945       352        0.00457 ok    stop
         in : condense evidence 1220 8848 4641 4583 1486 9879 into an operator-facing 
         out: answer composed citing 1220 8848 4641 4583 1486 9879 for NE-3CB3-19
         meta: model=adn-llm-14b  ttft=0.1736  pv=pv-2026-03
         v3  : sys=166  cache_r=166  cost_det={cache_read:0.000124,completion:0.00211,prompt:0.00234}  verifier=v_numbers_traceable:PASS  subgoal=查询员工通讯录寻找值班人员

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['missing_step']
    intent=i0  pattern=p3  cell=i0|p3
    oracle dim_dev : O=1.00  P=0.80  L=0.74  C=0.73  R=1.00
    latency_true=0.924s  gen_quantiles={'C': 0.5311, 'L': 0.5255}
    process_flags={'illegal_step': False, 'missing_step': True, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=[]  human_label=None  drift_segment=0
    loop_true=False  mfr_true=0.0000  model_mix_true={'adn-llm-14b': 1.0}  feedback_available=False
    has_golden=False  key_fact_recall_true=n/a  fact_precision_true=n/a
    hallucinated_facts=[]
    query_lang_true=zh  session_turn_count_true=4  subgoal_count=1
    plan_revision_true=0  goal_drift_true=True  arg_valid_true=1.0000  verifier_pass_true=1.0000
    citation_reachable_true=1.0000  contradiction_true=0.0000  contradicted_count=0  fabricated_citation_count=0
    cache_read_true=166  cache_write_true=148  system_prompt_ratio_true=0.1333  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice1-v0.1.0)
    S=95.1342  G=1.00  grade_abs=A  grade_rel=B  tier=2  novelty=False
    alert=True (rule=True stat=False)  cold_start=False  cell=i0xp2
    dims    : O=1.000  P=0.900  L=0.992  C=0.832  R=1.000
    contrib : O=+0.000  P=-2.056  L=-0.122  C=-2.688  R=+0.000   sum=-4.8658
    zero-residual: S-100G=-4.8658  |diff|=3.00e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.8752  a_cal=0.9649  conf=0.9834  anchor=anchor-R7-1bd79369786bde6f
    evidence (3 items, drill-down order):
      - [trace] cost_total               span=R7-00079-s04   value=0.0110      cell_median=0.0117      z=  -0.12 dev=0.0718
      - [trace] tokens_total             span=R7-00079-s04   value=2948.0000   cell_median=3292.5000   z=  -0.22 dev=0.0654
      - [span ] tok                      span=R7-00079-s02   value=537.0000    peer_median=319.5000    z=  +1.23 dev=0.1815 (L3/L3span action=verify)
```

## 六、v3 共生缺陷样本（附录 A 新增特征的原始证据）

下面这些**不是**独立的异常类型，而是叠加在已异常轨迹上的共生缺陷。每一个都由
`bench/coverage.truth_agreement()` 在全部轨迹上做双向等价校验（内核特征 ⟺ 生成器真值），
任何一条对不上都会让构建直接失败，而不是只在报告里留一行警告。


### v3 样本 A：plan_revision —— R7-00002

入口步骤（ontA 的 `plan`、ontB 的 `intent_parse`）出现了两次，第二次的时间区间**嵌套在**第一次之内——智能体在一步还没走完时就重开了计划。`kernel/cluster.collapse()` 会折叠相邻重复，所以模式视图看到的骨架完全不变，只有 `plan_revision_count` 能看见它。这也是该特征被定义成“时间包含”而不是“计数减一”的原因：循环注入器同样可能选中入口步骤，计数减一会把一次循环读成两次计划修订。

```text
==============================================================================
TRACE R7-00002   [intent1: NE-E138-47 为什么劣化，请给出劣化根因及证据]
  ontology=ontA  session=sess-00000  turn=3/3  spans=7  wall=50.592s  ts_start=1767225743.023
  user_feedback: none captured
  answer_numbers=[]
  answer_facts  =[]
  golden_answer =
  golden_facts  =None
  goal_text     =劣化根因   query_lang=zh
  answer_citations  =['doc://topology/subnetwork-east-map', 'kb://history/incident-2026-0043']
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[-0.0204, -0.2737, 0.1428, 0.0578] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run          50.592 ######### 294       102        0.00117 ok    stop
       in : NE-E138-47 为什么劣化，请给出劣化根因及证据
       out: 'NE-E138-47 为什么劣化，请给出劣化根因及证据' on NE-E138-47 finished with an empty resul
       meta: model=adn-llm-14b
       v3  : sys=145  cache_r=145  cost_det={cache_read:0.000109,completion:0.000612,prompt:0.000447}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan               18.934 ###       655       207        0.00285 ok    stop
         in : task=劣化根因 ne=NE-E138-47 window=1h; produce a step plan
         out: attempt finished, step list drafted for NE-E138-47;  candidate actions
         meta: model=adn-llm-14b  ttft=1.8582  pv=pv-2026-03
         v3  : sys=159  cache_r=159  cost_det={cache_read:0.000119,completion:0.00124,prompt:0.00149}  subgoal=为劣化根因拆解任务步骤
  `- s02           llm         plan                7.574 #         534       134        0.00191 ok    stop
         in : decompose request from NE-E138-47 over 1h into executable steps
         out: step list drafted for NE-E138-47;  candidate actions for NE-E138-47
         meta: model=adn-llm-72b  ttft=1.6217  pv=pv-2026-03
         v3  : sys=222  cache_r=222  cost_det={cache_read:0.000167,completion:0.000804,prompt:0.000936}  subgoal=为劣化根因拆解任务步骤
  `- s03           retrieval   schema_retrieval    7.386 #         598       0          0.00179 ok    -
         in : resolve table definitions needed by NE-E138-47 query
         out: table metadata resolved: 6681 6834
         meta: tool=catalog.table_schema  params={table:alarm_history}  facts=[6681 6834]
         v3  : cost_det={prompt:0.00179}  arg_valid=True  retrieved=[doc://topology/subnetwork-east-map kb://history/incident-2026-0043]
  `- s04           guard       approve            16.961 ###       368       58         0.00145 ok    -
         in : route the pending change on NE-E138-47 to the approver
         out: change ticket for NE-E138-47: pass
         v3  : cost_det={completion:0.000348,prompt:0.0011}  verifier=v_no_forbidden_action:PASS
  `- s05           tool        sql_query           2.586 #         0         0          0.00020 ok    -
         in : SELECT alarm_id,severity FROM current_alarms WHERE ne='NE-E138-47' AND w
         out: step done - query settled; row ids 2622 4702 3563
         meta: tool=perf_db.query  params={ne_id:NE-E138-47,severity:critical,time_window:1h}  facts=[2622 4702 3563]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s06           llm         summarize           2.586 #         686       230        0.00405 ok    stop
         in : write the final response for NE-E138-47 from evidence 6681 6834 2622 470
         out: summary drafted from 6681 6834 2622 4702 3563 for NE-E138-47
         meta: model=adn-llm-14b  ttft=0.3504  pv=pv-2026-03
         v3  : sys=163  cache_w=163  cost_det={cache_write:0.000611,completion:0.00138,prompt:0.00206}  verifier=v_numbers_traceable:PASS  subgoal=步骤目标：归纳证据，服务于劣化根因

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=False  anomaly_types=[]
    intent=i1  pattern=p2  cell=i1|p2
    oracle dim_dev : O=1.00  P=1.00  L=0.52  C=0.82  R=1.00
    latency_true=50.589s  gen_quantiles={'C': 0.3637, 'L': 0.9556}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=[]  human_label=None  drift_segment=0
    loop_true=False  mfr_true=0.0000  model_mix_true={'adn-llm-14b': 0.765, 'adn-llm-72b': 0.235}  feedback_available=False
    has_golden=False  key_fact_recall_true=n/a  fact_precision_true=n/a
    hallucinated_facts=[]
    query_lang_true=zh  session_turn_count_true=3  subgoal_count=3
    plan_revision_true=1  goal_drift_true=False  arg_valid_true=1.0000  verifier_pass_true=1.0000
    citation_reachable_true=1.0000  contradiction_true=n/a  contradicted_count=0  fabricated_citation_count=0
    cache_read_true=526  cache_write_true=163  system_prompt_ratio_true=0.2198  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice1-v0.1.0)
    S=88.4105  G=1.00  grade_abs=B  grade_rel=C  tier=0  novelty=False
    alert=False (rule=False stat=False)  cold_start=False  cell=i1xp1
    dims    : O=0.930  P=1.000  L=0.819  C=0.747  R=0.850
    contrib : O=-2.375  P=+0.000  L=-3.069  C=-4.483  R=-1.662   sum=-11.5895
    zero-residual: S-100G=-11.5895  |diff|=3.10e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.2128  a_cal=0.0854  conf=0.9634  anchor=anchor-R7-1bd79369786bde6f
    evidence (3 items, drill-down order):
      - [trace] branch_factor            span=-              value=6.0000      cell_median=4.0000      z=  +1.35 dev=0.2255
      - [trace] retry_count              span=-              value=1.0000      cell_median=0.0000      z= +50.00 dev=0.1746
      - [span ] dur                      span=R7-00002-s04   value=16.9615     peer_median=4.3747      z=  +2.99 dev=0.2660 (L3/L3span action=approve)
```

### v3 样本 B：goal_drift —— R7-00043

某个 `subgoal_text` 与本条轨迹的 `goal_text` **没有任何内容词重叠**——智能体在这一步跑偏了。特征侧用词元包含率 `1 - |G ∩ S| / |G|` 度量：跑偏时恰好为 1.0，在轨时恰好为 0.0，所以 `goal_drift_max >= 0.5` 与真值构成严格的双向等价。生成器为此专门过滤掉任何与目标共享词元的绕路模板，否则真值会声称漂移而数据里量不出来。

```text
==============================================================================
TRACE R7-00043   [intent0: list every entry in the current alarm list of network element NE-20FD-54]
  ontology=ontA  session=sess-00011  turn=3/5  spans=9  wall=1.623s  ts_start=1767228389.502
  user_feedback: none captured
  answer_numbers=['5519', '5562']
  answer_facts  =['NE-20FD-54', '5519', '5562']
  golden_answer =
  golden_facts  =None
  goal_text     =current alarm list   query_lang=en
  answer_citations  =[]
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[0.0923, -0.1715, 0.1124, 0.1153] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run           1.623 ######### 358       143        0.00157 ok    stop
       in : list every entry in the current alarm list of network element NE-20FD-54
       out: list every entry in the current alarm list of network element NE-20FD-54
       meta: model=adn-llm-14b  facts=[5519 5562]
       v3  : sys=160  cache_r=160  cost_det={cache_read:0.00012,completion:0.000858,prompt:0.000594}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan                0.175 #         499       317        0.00305 ok    stop
         in : task=current alarm list ne=NE-20FD-54 window=15m; produce a step plan
         out: decompose into retrieval then aggregation; window=15m; noted for the ope
         meta: model=adn-llm-14b  ttft=0.0315  pv=pv-2026-03
         v3  : sys=153  cache_r=153  cost_det={cache_read:0.000115,completion:0.0019,prompt:0.00104}  subgoal=search the training vault for slide decks
  `- s02           guard       verify              0.175 #         160       53         0.00080 ok    -
         in : compliance scan of the pending step set for NE-20FD-54
         out: policy evaluation on NE-20FD-54: pass
         v3  : cost_det={completion:0.000318,prompt:0.00048}  verifier=v_no_forbidden_action:PASS
  `- s03           tool        sql_query           0.655 ####      0         0          0.00020 ok    -
         in : SELECT alarm_id,severity FROM current_alarms WHERE ne='NE-20FD-54' AND w
         out: rows returned: 1635 9682 9453 5646 for NE-20FD-54
         meta: tool=alarm_db.query  params={ne_id:NE-20FD-54,severity:major,time_window:15m}  facts=[1635 9682 9453 5646]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s04           tool        sql_query           0.655 ####      0         0          0.00020 ok    -
         in : SELECT alarm_id,severity FROM current_alarms WHERE ne='NE-20FD-54' AND w
         out: rows returned: 2309 6036 4506; payload attached to the trace
         meta: tool=alarm_db.query  params={ne_id:NE-20FD-54,severity:major,time_window:15m}  facts=[2309 6036 4506]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s05           tool        sql_query           0.655 ####      0         0          0.00020 ok    -
         in : SELECT alarm_id,severity FROM current_alarms WHERE ne='NE-20FD-54' AND w
         out: query settled; row ids 5562 5519 6880 (window 15m)
         meta: tool=alarm_db.query  params={ne_id:NE-20FD-54,severity:major,time_window:15m}  facts=[5562 5519 6880]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s06           tool        sql_query           0.655 ####      0         0          0.00020 ok    -
         in : SELECT kpi_ts,value FROM perf_15min WHERE ne='NE-20FD-54' AND window='15
         out: query settled; row ids 7106 6440 6532 4545 (window 15m)
         meta: tool=alarm_db.query  params={ne_id:NE-20FD-54,severity:major,time_window:15m}  facts=[7106 6440 6532 4545]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s07           tool        sql_query           0.655 ####      0         0          0.00020 ok    -
         in : SELECT alarm_id,severity FROM current_alarms WHERE ne='NE-20FD-54' AND w
         out: rows returned: 9111 4885 for NE-20FD-54
         meta: tool=alarm_db.query  params={ne_id:NE-20FD-54,severity:major,time_window:15m}  facts=[9111 4885]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s08           llm         summarize           0.733 ####      972       550        0.00585 ok    stop
         in : condense evidence 7106 6440 6532 4545 9111 4885 into an operator-facing 
         out: answer composed citing 7106 6440 6532 4545 9111 4885 (window 15m)
         meta: model=adn-llm-14b  ttft=0.0587  pv=pv-2026-03
         v3  : sys=161  cache_r=161  cost_det={cache_read:0.000121,completion:0.0033,prompt:0.00243}  verifier=v_numbers_traceable:PASS  subgoal=work on condensing the evidence to advance the current alarm

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['loop']
    intent=i0  pattern=p1  cell=i0|p1
    oracle dim_dev : O=1.00  P=0.50  L=0.73  C=0.67  R=0.55
    latency_true=1.621s  gen_quantiles={'C': 0.654, 'L': 0.5448}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=['R7-00043-s03', 'R7-00043-s04', 'R7-00043-s05', 'R7-00043-s06', 'R7-00043-s07']  human_label=None  drift_segment=0
    loop_true=True  mfr_true=0.0000  model_mix_true={'adn-llm-14b': 1.0}  feedback_available=False
    has_golden=False  key_fact_recall_true=n/a  fact_precision_true=n/a
    hallucinated_facts=[]
    query_lang_true=en  session_turn_count_true=5  subgoal_count=2
    plan_revision_true=0  goal_drift_true=True  arg_valid_true=1.0000  verifier_pass_true=1.0000
    citation_reachable_true=n/a  contradiction_true=0.0000  contradicted_count=0  fabricated_citation_count=0
    cache_read_true=474  cache_write_true=0  system_prompt_ratio_true=0.2383  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice1-v0.1.0)
    S=30.9762  G=0.35  grade_abs=D  grade_rel=D  tier=2  novelty=False
    alert=True (rule=True stat=False)  cold_start=False  cell=i0xp0
    dims    : O=1.000  P=0.800  L=0.863  C=0.770  R=0.850
    contrib : O=+0.000  P=-1.470  L=-0.727  C=-1.291  R=-0.535   sum=-4.0238
    zero-residual: S-100G=-4.0238  |diff|=4.70e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.9361  a_cal=0.9789  conf=0.9943  anchor=anchor-R7-1bd79369786bde6f
    gates: {"loop_runaway": 0.35}
    evidence (3 items, drill-down order):
      - [trace] branch_factor            span=-              value=8.0000      cell_median=3.0000      z=  +6.75 dev=0.3463
      - [trace] n_spans                  span=-              value=9.0000      cell_median=5.0000      z=  +2.70 dev=0.3341
      - [span ] dur                      span=R7-00043-s03   value=0.6547      peer_median=0.3735      z=  +0.87 dev=0.1303 (L3/L3span action=sql_query)
```

### v3 样本 C：invalid_tool_arg —— R7-00046

工具入参违反了本体的 `param_schema`（枚举越界 / 前缀不符）。`arg_valid` 是**测量**出来的而不是断言的：生成器构造完违规参数后会再跑一次同一个校验函数，只有确实判为违规才落库。循环与重试的副本共享同一份参数，所以一个违规组里的每个副本都同样违规——这是刻意的，否则 `(parent, action, 参数哈希)` 分组会被拆开，一个真循环就悄悄变成了非循环。

```text
==============================================================================
TRACE R7-00046   [intent0: which alarms are still active in the current alarm list of NE-7465-02]
  ontology=ontA  session=sess-00012  turn=1/7  spans=10  wall=1.967s  ts_start=1767228587.769
  user_feedback: none captured
  answer_numbers=[]
  answer_facts  =[]
  golden_answer =
  golden_facts  =None
  goal_text     =current alarm list   query_lang=en
  answer_citations  =[]
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[0.1835, -0.4658, 0.1965, 0.0775] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run           1.967 ######### 396       158        0.00272 ok    stop
       in : which alarms are still active in the current alarm list of NE-7465-02
       out: no numeric evidence for 'which alarms are still active in the current al
       meta: model=adn-llm-14b
       v3  : sys=155  cache_w=155  cost_det={cache_write:0.000581,completion:0.000948,prompt:0.00119}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan                0.088 #         1481      52         0.00528 ok    stop
         in : task=current alarm list ne=NE-7465-02 window=15m; produce a step plan
         out: decompose into retrieval then aggregation; window=15m; payload attached 
         meta: model=adn-llm-14b  ttft=0.0044  pv=pv-2026-03
         v3  : sys=141  cache_w=141  cost_det={cache_write:0.000529,completion:0.000312,prompt:0.00444}  subgoal=work on decomposing the task steps to advance the current al
  `- s02           guard       approve             0.088 #         465       105        0.00202 ok    -
         in : route the pending change on NE-7465-02 to the approver
         out: change ticket for NE-7465-02: pass
         v3  : cost_det={completion:0.00063,prompt:0.00139}  verifier=v_no_forbidden_action:PASS
  `- s03           tool        sql_query           0.441 ##        0         0          0.00020 ok    -
         in : SELECT alarm_id,severity FROM current_alarms WHERE ne='NE-7465-02' AND w
         out: step done - query settled; row ids 7771 5445 9660 7004
         meta: tool=alarm_db.query  params={ne_id:NE-7465-02,severity:major,time_window:15m}  facts=[7771 5445 9660 7004]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s04           tool        sql_query           0.441 ##        0         0          0.00020 ok    -
         in : SELECT kpi_ts,value FROM perf_15min WHERE ne='NE-7465-02' AND window='15
         out: query settled; row ids 3474 3425; payload attached to the trace
         meta: tool=alarm_db.query  params={ne_id:NE-7465-02,severity:major,time_window:15m}  facts=[3474 3425]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s05           tool        sql_query           0.441 ##        0         0          0.00020 ok    -
         in : SELECT kpi_ts,value FROM perf_15min WHERE ne='NE-7465-02' AND window='15
         out: attempt finished, query settled; row ids 4429 7533 6460 6824
         meta: tool=alarm_db.query  params={ne_id:NE-7465-02,severity:major,time_window:15m}  facts=[4429 7533 6460 6824]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s06           tool        sql_query           0.441 ##        0         0          0.00020 ok    -
         in : SELECT kpi_ts,value FROM perf_15min WHERE ne='NE-7465-02' AND window='15
         out: attempt finished, query settled; row ids 1433 6566 4297
         meta: tool=alarm_db.query  params={ne_id:NE-7465-02,severity:major,time_window:15m}  facts=[1433 6566 4297]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s07           tool        sql_query           0.441 ##        0         0          0.00020 ok    -
         in : SELECT kpi_ts,value FROM perf_15min WHERE ne='NE-7465-02' AND window='15
         out: checked and recorded: query settled; row ids 3430 3683
         meta: tool=alarm_db.query  level=WARNING  msg=slow query above soft limit  params={ne_id:NE-7465-02,severity:major,time_window:15m}  facts=[3430 3683]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s08           tool        api_call            0.861 ####      0         0          0.00020 ok    -
         in : GET /nbi/v1/ne/NE-7465-02/alarms?window=15m
         out: response payload ids: 9463 6263 (window 15m)
         meta: tool=nbi.alarm_list  params={ne_id:legacy-id-9931,scope:subnetwork}  facts=[9463 6263]
         v3  : cost_det={tool_call:0.0002}  arg_valid=False
  `- s09           llm         summarize           0.496 ##        721       458        0.00459 ok    stop
         in : condense evidence 6566 4297 3430 3683 9463 6263 into an operator-facing 
         out: summary drafted from 6566 4297 3430 3683 9463 6263; payload attached to 
         meta: model=adn-llm-14b  ttft=0.1201  pv=pv-2026-03
         v3  : sys=144  cache_r=144  cost_det={cache_read:0.000108,completion:0.00275,prompt:0.00173}  verifier=v_numbers_traceable:PASS  subgoal=step goal: condensing the evidence, serving the current alar

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['loop']
    intent=i0  pattern=p1  cell=i0|p1
    oracle dim_dev : O=1.00  P=0.50  L=0.66  C=0.63  R=0.55
    latency_true=1.964s  gen_quantiles={'C': 0.7322, 'L': 0.6776}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=['R7-00046-s03', 'R7-00046-s04', 'R7-00046-s05', 'R7-00046-s06', 'R7-00046-s07']  human_label=None  drift_segment=0
    loop_true=True  mfr_true=0.0000  model_mix_true={'adn-llm-14b': 1.0}  feedback_available=False
    has_golden=False  key_fact_recall_true=n/a  fact_precision_true=n/a
    hallucinated_facts=[]
    query_lang_true=en  session_turn_count_true=7  subgoal_count=2
    plan_revision_true=0  goal_drift_true=False  arg_valid_true=0.8333  verifier_pass_true=1.0000
    citation_reachable_true=n/a  contradiction_true=n/a  contradicted_count=0  fabricated_citation_count=0
    cache_read_true=144  cache_write_true=296  system_prompt_ratio_true=0.1436  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice1-v0.1.0)
    S=28.8312  G=0.35  grade_abs=D  grade_rel=D  tier=2  novelty=False
    alert=True (rule=True stat=False)  cold_start=False  cell=i0xp0
    dims    : O=0.930  P=0.800  L=0.799  C=0.668  R=0.850
    contrib : O=-0.803  P=-1.543  L=-1.166  C=-2.094  R=-0.562   sum=-6.1688
    zero-residual: S-100G=-6.1688  |diff|=9.00e-06  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.9558  a_cal=0.9821  conf=0.9943  anchor=anchor-R7-1bd79369786bde6f
    gates: {"loop_runaway": 0.35}
    evidence (3 items, drill-down order):
      - [trace] branch_factor            span=-              value=9.0000      cell_median=3.0000      z=  +8.09 dev=0.4141
      - [trace] n_spans                  span=-              value=10.0000     cell_median=5.0000      z=  +3.37 dev=0.3463
      - [span ] dur                      span=R7-00046-s08   value=0.8608      peer_median=0.3089      z=  +2.09 dev=0.1941 (L3/L3span action=api_call)
```

### v3 样本 D：verifier_fail —— R7-00075

确定性校验器给出 FAIL。三个校验器全部是代码判定，没有任何生成式判官参与：`v_numbers_traceable`（答案里的数字必须能在证据池中找到）、`v_no_forbidden_action`（禁用动作不得被启动）、`v_answer_nonempty`（答案非空）。它们的结果是从落库记录本身反推出来的，而不是生成器的意图。

```text
==============================================================================
TRACE R7-00075   [intent0: 请列出网元 NE-B651-29 当前告警清单中的每一条记录]
  ontology=ontA  session=sess-00016  turn=3/4  spans=6  wall=2.139s  ts_start=1767230447.661
  user_feedback: abandoned=False human_takeover=False retry=True thumbs=1
  answer_numbers=['2509', '3755', '9262', '58']
  answer_facts  =['NE-B651-29', '2509', '3755', '9262', '58']
  golden_answer =
  golden_facts  =None
  goal_text     =当前告警清单   query_lang=zh
  answer_citations  =[]
  contradicted_facts=['2509', '9262']
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[0.0077, -0.3939, 0.3422, 0.074] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run           2.139 ######### 197       68         0.00069 ok    length
       in : 请列出网元 NE-B651-29 当前告警清单中的每一条记录
       out: answer to '请列出网元 NE-B651-29 当前告警清单中的每一条记录' on NE-B651-29 over 1h: 2509, 
       meta: model=adn-llm-14b  facts=[2509 3755 9262 58]
       v3  : sys=138  cache_r=138  cost_det={cache_read:0.000104,completion:0.000408,prompt:0.000177}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan                0.210 #         486       193        0.00230 ok    stop
         in : task=当前告警清单 ne=NE-B651-29 window=1h; produce a step plan
         out: checked and recorded: step list drafted for NE-B651-29;  candidate actio
         meta: model=adn-llm-14b  level=WARNING  ttft=0.0470  pv=pv-2026-03  msg=partial result set returned
         v3  : sys=140  cache_r=140  cost_det={cache_read:0.000105,completion:0.00116,prompt:0.00104}  subgoal=推进当前告警清单：拆解任务步骤
  `- s02           guard       verify              0.210 #         229       34         0.00089 ok    -
         in : compliance scan of the pending step set for NE-B651-29
         out: verdict pass for NE-B651-29
         meta: level=WARNING  msg=slow query above soft limit
         v3  : cost_det={completion:0.000204,prompt:0.000687}  verifier=v_no_forbidden_action:PASS
  `- s03           tool        api_call            0.869 ####      0         0          0.00020 ok    -
         in : GET /nbi/v1/ne/NE-B651-29/status?detail=true
         out: northbound returned objects 2509 9262 (window 1h)
         meta: tool=nbi.ne_status  params={ne_id:NE-B651-29,scope:ne}  facts=[2509 9262]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s04           tool        sql_query           0.483 ##        0         0          0.00020 ok    -
         in : SELECT alarm_id,severity FROM current_alarms WHERE ne='NE-B651-29' AND w
         out: query settled; row ids 8893 3755 (window 1h)
         meta: tool=alarm_db.query  params={ne_id:NE-B651-29,severity:critical,time_window:1h}  facts=[8893 3755]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s05           llm         summarize           0.487 ##        380       138        0.00162 ok    stop
         in : write the final response for NE-B651-29 from evidence 2509 9262 8893 375
         out: answer composed citing 2509 9262 8893 3755 (window 1h)
         meta: model=adn-llm-14b  ttft=0.1392  pv=pv-2026-03
         v3  : sys=154  cache_r=154  cost_det={cache_read:0.000116,completion:0.000828,prompt:0.000678}  verifier=v_numbers_traceable:FAIL(answer number absent from the evidence pool)  subgoal=在 NE-B651-29 上为当前告警清单完成归纳证据

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['truncation']
    intent=i0  pattern=p1  cell=i0|p1
    oracle dim_dev : O=0.35  P=1.00  L=0.62  C=0.95  R=1.00
    latency_true=2.136s  gen_quantiles={'C': 0.1086, 'L': 0.761}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=[]  human_label=None  drift_segment=0
    loop_true=False  mfr_true=0.0000  model_mix_true={'adn-llm-14b': 1.0}  feedback_available=True
    has_golden=False  key_fact_recall_true=n/a  fact_precision_true=n/a
    hallucinated_facts=[]
    query_lang_true=zh  session_turn_count_true=4  subgoal_count=2
    plan_revision_true=0  goal_drift_true=False  arg_valid_true=1.0000  verifier_pass_true=0.6667
    citation_reachable_true=n/a  contradiction_true=0.4000  contradicted_count=2  fabricated_citation_count=0
    cache_read_true=432  cache_write_true=0  system_prompt_ratio_true=0.3344  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice1-v0.1.0)
    S=18.1196  G=0.25  grade_abs=D  grade_rel=D  tier=2  novelty=False
    alert=True (rule=True stat=False)  cold_start=False  cell=i0xp0
    dims    : O=0.495  P=1.000  L=0.769  C=0.992  R=1.000
    contrib : O=-6.012  P=+0.000  L=-0.843  C=-0.025  R=+0.000   sum=-6.8804
    zero-residual: S-100G=-6.8804  |diff|=2.40e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.9198  a_cal=0.9758  conf=0.9943  anchor=anchor-R7-1bd79369786bde6f
    gates: {"t0_result_broken": 0.25}
    evidence (3 items, drill-down order):
      - [trace] traceable_number_ratio   span=-              value=0.7500      cell_median=1.0000      z= -50.00 dev=0.2841
      - [trace] branch_factor            span=-              value=5.0000      cell_median=3.0000      z=  +2.70 dev=0.1783
      - [span ] dur                      span=R7-00075-s03   value=0.8692      peer_median=0.3089      z=  +2.13 dev=0.1983 (L3/L3span action=api_call)
```

### v3 样本 E：fabricated_citation —— R7-00153

答案引用了一个**格式完全合法**的定位符，但它不在本次检索到的结果集里。真实智能体的编造几乎从不是凭空造一个URL，而是把片段号写错——所以 `citation_reachability` 必须对着检索结果集算，而不是对着 URL 白名单或格式校验算。生成器正是这样伪造的：取一个真实定位符，把 `#L` 片段改到 1001~1900 区间。

```text
==============================================================================
TRACE R7-00153   [intent0: show the current alarm list of NE-4ED5-30]
  ontology=ontA  session=sess-00031  turn=3/4  spans=5  wall=0.847s  ts_start=1767235524.855
  user_feedback: abandoned=False human_takeover=False retry=False thumbs=None
  answer_numbers=['8485', '92591', '61441']
  answer_facts  =['NE-4ED5-30', '8485', '92591', '61441']
  golden_answer =
  golden_facts  =None
  goal_text     =current alarm list   query_lang=en
  answer_citations  =['doc://policy/change-approval-rules#L1806', 'doc://vendor/nbi-api-reference#L310', 'kb://history/incident-2025-1187#L1109', 'runbook://adn/capacity-expansion#L25']
  contradicted_facts=['8485']
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[0.1605, -0.1997, 0.1171, 0.3414] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run           0.847 ######### 258       103        0.00103 ok    stop
       in : show the current alarm list of NE-4ED5-30
       out: completed 'show the current alarm list of NE-4ED5-30' on NE-4ED5-30; val
       meta: model=adn-llm-14b  facts=[8485 92591 61441]
       v3  : sys=162  cache_r=162  cost_det={cache_read:0.000121,completion:0.000618,prompt:0.000288}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan                0.427 #####     831       188        0.00423 ok    stop
         in : decompose request from NE-4ED5-30 over 24h into executable steps
         out: step list drafted for NE-4ED5-30;  candidate actions; payload attached t
         meta: model=adn-llm-14b  ttft=0.1171  pv=pv-2026-03
         v3  : sys=162  cache_w=162  cost_det={cache_write:0.000607,completion:0.00113,prompt:0.00249}  subgoal=work on decomposing the task steps to advance the current al
  `- s02           retrieval   retrieve_kb         0.427 #####     525       0          0.00158 ok    -
         in : runbook search: current alarm list (ne=NE-4ED5-30)
         out: matched runbook evidence: 3314 4775 8485 for NE-4ED5-30
         meta: tool=kb.history_search  params={query:NE-4ED5-30,top_k:5}  facts=[3314 4775 8485]
         v3  : cost_det={prompt:0.00158}  arg_valid=True  retrieved=[doc://vendor/nbi-api-reference#L310 runbook://adn/capacity-expansion#L25]
  `- s03           guard       approve             0.361 ####      221       7          0.00071 ok    -
         in : approval gate for change on NE-4ED5-30
         out: change ticket for NE-4ED5-30: pass
         v3  : cost_det={completion:4.2e-05,prompt:0.000663}  verifier=v_no_forbidden_action:PASS
  `- s04           llm         summarize           0.361 ####      504       284        0.00287 ok    stop
         in : condense evidence 3314 4775 8485 into an operator-facing answer
         out: answer composed citing 3314 4775 8485; noted for the operator
         meta: model=adn-llm-14b  ttft=0.0433  pv=pv-2026-03
         v3  : sys=152  cache_r=152  cost_det={cache_read:0.000114,completion:0.0017,prompt:0.00106}  verifier=v_numbers_traceable:FAIL(answer number absent from the evidence pool)  subgoal=condensing the evidence within 24h for the current alar

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['hallucinated_number']
    intent=i0  pattern=p3  cell=i0|p3
    oracle dim_dev : O=0.15  P=1.00  L=0.51  C=0.81  R=1.00
    latency_true=0.844s  gen_quantiles={'C': 0.3709, 'L': 0.9765}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=[]  human_label=None  drift_segment=0
    loop_true=False  mfr_true=0.0000  model_mix_true={'adn-llm-14b': 1.0}  feedback_available=True
    has_golden=False  key_fact_recall_true=n/a  fact_precision_true=n/a
    hallucinated_facts=[]
    query_lang_true=en  session_turn_count_true=4  subgoal_count=2
    plan_revision_true=0  goal_drift_true=False  arg_valid_true=1.0000  verifier_pass_true=0.6667
    citation_reachable_true=0.5000  contradiction_true=0.2500  contradicted_count=1  fabricated_citation_count=2
    cache_read_true=314  cache_write_true=162  system_prompt_ratio_true=0.2035  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice1-v0.1.0)
    S=18.9593  G=0.25  grade_abs=D  grade_rel=D  tier=2  novelty=False
    alert=True (rule=True stat=False)  cold_start=False  cell=i0xp2
    dims    : O=0.533  P=1.000  L=1.000  C=0.846  R=1.000
    contrib : O=-5.492  P=+0.000  L=+0.000  C=-0.549  R=+0.000   sum=-6.0407
    zero-residual: S-100G=-6.0407  |diff|=2.90e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.9107  a_cal=0.9739  conf=0.9834  anchor=anchor-R7-1bd79369786bde6f
    gates: {"t0_result_broken": 0.25}
    evidence (3 items, drill-down order):
      - [trace] traceable_number_ratio   span=-              value=0.3333      cell_median=1.0000      z= -50.00 dev=0.3928
      - [trace] cost_total               span=R7-00153-s01   value=0.0104      cell_median=0.0117      z=  -0.23 dev=0.0664
      - [span ] dur                      span=R7-00153-s03   value=0.3610      peer_median=0.2008      z=  +0.97 dev=0.1560 (L3/L3span action=approve)
```

### v3 样本 F：contradicted_evidence —— R7-00067

答案陈述了与证据相反的关系。注意它与幻觉的区别：矛盾涉及的事实**在**证据池里，只是关系被说反了。生成器只从`golden_facts ∩ answer_facts` 里采样，从结构上保证了这一点。特征侧的 `contradiction_rate` 仍标记为`needs_model`——数据集负责提供输入与真值，数值本身要等真实 NLI 模型接上才有意义。

```text
==============================================================================
TRACE R7-00067   [intent0: NE-1FD3-07 的当前告警清单里还有哪些活动告警]
  ontology=ontA  session=sess-00015  turn=1/6  spans=6  wall=1.261s  ts_start=1767229936.057
  user_feedback: none captured
  answer_numbers=['7059', '6030']
  answer_facts  =['NE-1FD3-07', '7059', '6030']
  golden_answer =expected answer for NE-1FD3-07 (NE-1FD3-07 的当前告警清单里还有哪些活动告警): 7059, 6030
  golden_facts  =['NE-1FD3-07', '7059', '6030']
  goal_text     =当前告警清单   query_lang=zh
  answer_citations  =[]
  contradicted_facts=['6030', '7059']
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[0.0367, -0.442, 0.4851, 0.312] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run           1.261 ######### 273       94         0.00198 ok    stop
       in : NE-1FD3-07 的当前告警清单里还有哪些活动告警
       out: completed 'NE-1FD3-07 的当前告警清单里还有哪些活动告警' on NE-1FD3-07; values: 7059, 603
       meta: model=adn-llm-14b  facts=[7059 6030]
       v3  : sys=160  cache_w=160  cost_det={cache_write:0.0006,completion:0.000564,prompt:0.000819}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan                0.566 ####      596       326        0.00453 ok    stop
         in : decompose request from NE-1FD3-07 over 1h into executable steps
         out: decompose into retrieval then aggregation; window=1h; noted for the oper
         meta: model=adn-llm-72b  ttft=0.1067  pv=pv-2026-03
         v3  : sys=210  cache_w=210  cost_det={cache_write:0.000788,completion:0.00196,prompt:0.00179}  subgoal=在 NE-1FD3-07 上为当前告警清单完成拆解任务步骤
  `- s02           guard       verify              0.017 #         348       49         0.00134 ok    -
         in : compliance scan of the pending step set for NE-1FD3-07
         out: policy evaluation on NE-1FD3-07: pass
         v3  : cost_det={completion:0.000294,prompt:0.00104}  verifier=v_no_forbidden_action:PASS
  `- s03           tool        sql_query           0.017 #         0         0          0.00020 ok    -
         in : SELECT alarm_id,severity FROM current_alarms WHERE ne='NE-1FD3-07' AND w
         out: query settled; row ids 4005 6940 8949; noted for the operator
         meta: tool=alarm_db.query  params={ne_id:NE-1FD3-07,severity:critical,time_window:1h}  facts=[4005 6940 8949]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s04           tool        api_call            0.346 ##        0         0          0.00020 ok    -
         in : GET /nbi/v1/ne/NE-1FD3-07/alarms?window=1h
         out: northbound returned objects 6030 8240 6659 7059; nothing further require
         meta: tool=nbi.ne_status  params={ne_id:NE-1FD3-07,scope:subnetwork}  facts=[6030 8240 6659 7059]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s05           llm         summarize           0.260 ##        646       269        0.00321 error stop
         in : condense evidence 6940 8949 6030 8240 6659 7059 into an operator-facing 
         out: ok - summary drafted from 6940 8949 6030 8240 6659 7059
         meta: model=adn-llm-14b  level=ERROR  ttft=0.0629  pv=pv-2026-03  msg=query rejected by alarm_db
         v3  : sys=150  cache_r=150  cost_det={cache_read:0.000112,completion:0.00161,prompt:0.00149}  verifier=v_numbers_traceable:PASS  subgoal=针对当前告警清单进行归纳证据（窗口 1h）

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['error']
    intent=i0  pattern=p1  cell=i0|p1
    oracle dim_dev : O=0.75  P=1.00  L=0.73  C=0.85  R=0.35
    latency_true=1.258s  gen_quantiles={'C': 0.3017, 'L': 0.5362}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=['R7-00067-s05']  human_label=None  drift_segment=0
    loop_true=False  mfr_true=0.0000  model_mix_true={'adn-llm-14b': 0.5817, 'adn-llm-72b': 0.4183}  feedback_available=False
    has_golden=True  key_fact_recall_true=1.0000  fact_precision_true=1.0000
    hallucinated_facts=[]
    query_lang_true=zh  session_turn_count_true=6  subgoal_count=2
    plan_revision_true=0  goal_drift_true=False  arg_valid_true=1.0000  verifier_pass_true=1.0000
    citation_reachable_true=n/a  contradiction_true=0.6667  contradicted_count=2  fabricated_citation_count=0
    cache_read_true=150  cache_write_true=370  system_prompt_ratio_true=0.2791  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice1-v0.1.0)
    S=86.9274  G=1.00  grade_abs=B  grade_rel=C  tier=2  novelty=False
    alert=True (rule=True stat=False)  cold_start=False  cell=i0xp0
    dims    : O=0.833  P=1.000  L=0.931  C=0.811  R=0.778
    contrib : O=-6.805  P=+0.000  L=-0.994  C=-2.929  R=-2.345   sum=-13.0726
    zero-residual: S-100G=-13.0726  |diff|=4.60e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.8966  a_cal=0.9707  conf=0.9943  anchor=anchor-R7-1bd79369786bde6f
    evidence (3 items, drill-down order):
      - [trace] error_ratio              span=R7-00067-s05   value=0.1667      cell_median=0.0000      z= +50.00 dev=0.3153
      - [trace] branch_factor            span=-              value=5.0000      cell_median=3.0000      z=  +2.70 dev=0.1783
      - [span ] tok                      span=R7-00067-s02   value=397.0000    peer_median=321.0000    z=  +0.50 dev=0.1022 (L3/L3span action=verify)
```

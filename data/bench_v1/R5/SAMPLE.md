# R5 样本阅读手册

这个文件由 `python -m bench.show R5 --sample` 生成，内容是真实数据，不是示意图。

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
| `data/bench_v1/R5/traces.jsonl` | 模拟出来的轨迹（一行一条，含完整 Span 树） | 3000 |
| `data/bench_v1/R5/gt.jsonl` | 真值：是否异常、异常类型、真实意图/模式、责任 Span | 3000 |
| `reports/R5/scores.jsonl` | 算法输出：S 分、五维、扣分归因、证据、告警 | 3000 |

JSONL = 每行一个压缩 JSON，直接打开会看到一堆没法读的长行。用下面的命令看：

```
python -m bench.show R5 R5-00001        # 看单条轨迹（输入+真值+算法输出）
python -m bench.show R5 --list latency_spike    # 列出某类异常的 trace_id
python -m bench.show R5 --stats                 # 数据集侧写
```

## 三、一条 trace 长什么样

每条 trace = 一棵 Span 树。根节点是整次 agent 执行，子节点是具体步骤（大模型调用 / 工具调用 / 知识检索 / 护栏校验），
每个节点带开始结束时间、token、成本、状态、输入输出文本。下面是真实样本。


## 四、数据集侧写


- 轨迹数 **3000**，Span 数 **15483**，平均 5.2 Span/轨迹
- 异常轨迹 **308** 条（基率 10.27%），正常 **2692** 条
- 意图分布：i0=2117，i1=883
- 真实单元格（意图×模式）**6** 个
- 异常类型分布：latency_spike=60，token_bloat=53，truncation=38，unfinished=36，hallucinated_number=31，missing_step=30，loop=25，illegal_step=21，error=14
- `spec_hash=10ff75f849deddbe`  `gen_version=bench-gen-v3.1.0`
- v3 信号：arg_invalid_spans=86，cache_hit_spans=4933，contradiction=46，fabricated_citation=48，goal_drift=38，llm_spans=6163，plan_revision=203，verifier_fail=81
- 语种分布：en=1308，zh=1692；会话数 **672**，每会话轮次 {'max': 7, 'min': 2, 'n': 3000, 'p50': 5.0, 'p90': 7.0, 'p99': 7.0}

---

## 五、完整样本：输入 → 真值 → 算法输出

### 样本 A：一条正常轨迹（应该得高分、不告警）

```text
==============================================================================
TRACE R5-00000   [intent0: 查询网元 NE-3170-30 的当前告警清单]
  ontology=ontA  session=sess-00000  turn=1/6  spans=6  wall=2.128s  ts_start=1767225609.102
  user_feedback: none captured
  answer_numbers=['4029', '3126']
  answer_facts  =['NE-3170-30', '4029', '3126']
  golden_answer =
  golden_facts  =None
  goal_text     =当前告警清单   query_lang=zh
  answer_citations  =['doc://policy/change-approval-rules#L7', 'runbook://adn/capacity-expansion#L25']
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=0 orphan=True ts_missing=False usage_estimated=False
  embedding[0:4]=[0.0086, -0.0086, 0.1683, -0.0665] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run           2.128 ######### 360       125        0.00245 ok    stop
       in : 查询网元 NE-3170-30 的当前告警清单
       out: completed '查询网元 NE-3170-30 的当前告警清单' on NE-3170-30; values: 4029, 3126
       meta: model=adn-llm-14b  facts=[4029 3126]
       v3  : sys=164  cache_w=164  cost_det={cache_write:0.000615,completion:0.00075,prompt:0.00108}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan                0.637 ###       1057      207        0.00497 ok    stop
         in : decompose request from NE-3170-30 over 24h into executable steps
         out: step list drafted for NE-3170-30;  candidate actions; payload attached t
         meta: model=adn-llm-14b  ttft=0.0895  pv=pv-2026-03
         v3  : sys=148  cache_w=148  cost_det={cache_write:0.000555,completion:0.00124,prompt:0.00317}  subgoal=围绕当前告警清单执行拆解任务步骤
  `- s02           guard       verify              0.144 #         303       50         0.00121 ok    -
         in : policy check on pending action for NE-3170-30
         out: verdict pass for NE-3170-30
         v3  : cost_det={completion:0.0003,prompt:0.000909}  verifier=v_no_forbidden_action:PASS
  `- s03           retrieval   retrieve_kb         0.428 ##        344       0          0.00103 ok    -
         in : history search over incidents touching NE-3170-30
         out: knowledge hits ranked: 3725 4029 3126; nothing further required
         meta: tool=kb.runbook_search  params={query:NE-3170-30,top_k:10}  facts=[3725 4029 3126]
         v3  : cost_det={prompt:0.00103}  arg_valid=True  retrieved=[doc://policy/change-approval-rules#L7 runbook://adn/alarm-clear-procedure#L12 runbook://adn/capacity-expansion#L25]
  `- s04           guard       approve             0.158 #         321       48         0.00125 ok    -
         in : route the pending change on NE-3170-30 to the approver
         out: change ticket for NE-3170-30: pass
         v3  : cost_det={completion:0.000288,prompt:0.000963}  verifier=v_no_forbidden_action:PASS
  -  s05           llm         summarize           0.660 ###       1171      442        0.00571 ok    stop
       in : condense evidence 3725 4029 3126 into an operator-facing answer
       out: step done - summary drafted from 3725 4029 3126
       meta: model=adn-llm-72b  ttft=0.1032  pv=pv-2026-03
       v3  : sys=203  cache_r=203  cost_det={cache_read:0.000152,completion:0.00265,prompt:0.0029}  verifier=v_numbers_traceable:PASS  subgoal=推进当前告警清单：归纳证据

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=False  anomaly_types=[]
    intent=i0  pattern=p3  cell=i0|p3
    oracle dim_dev : O=1.00  P=1.00  L=0.70  C=0.73  R=1.00
    latency_true=2.125s  gen_quantiles={'C': 0.5386, 'L': 0.6087}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': True, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=[]  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.0000  model_mix_true={'adn-llm-14b': 0.5202, 'adn-llm-72b': 0.4798}  feedback_available=False
    has_golden=False  key_fact_recall_true=n/a  fact_precision_true=n/a
    hallucinated_facts=[]
    query_lang_true=zh  session_turn_count_true=6  subgoal_count=2
    plan_revision_true=0  goal_drift_true=False  arg_valid_true=1.0000  verifier_pass_true=1.0000
    citation_reachable_true=1.0000  contradiction_true=0.0000  contradicted_count=0  fabricated_citation_count=0
    cache_read_true=203  cache_write_true=312  system_prompt_ratio_true=0.1448  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice3-v0.3.0)
    S=88.8321  G=1.00  grade_abs=B  grade_rel=C  tier=0  novelty=False
    alert=False (rule=False stat=False)  cold_start=False  cell=i1xp0
    dims    : O=1.000  P=1.000  L=0.661  C=0.687  R=1.000
    contrib : O=+0.000  P=+0.000  L=-5.854  C=-5.314  R=+0.000   sum=-11.1679
    zero-residual: S-100G=-11.1679  |diff|=4.10e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.1557  a_cal=0.0685  conf=0.8947  anchor=anchor-R5-10ff75f849deddbe
    evidence (3 items, drill-down order):
      - [trace] branch_factor            span=-              value=5.0000      cell_median=4.0000      z=  +0.67 dev=0.1861
      - [trace] n_spans                  span=-              value=6.0000      cell_median=5.0000      z=  +0.67 dev=0.1603
      - [span ] tok                      span=R5-00000-s05   value=1613.0000   peer_median=1116.5000   z=  +0.81 dev=0.1628 (L3/L3span action=summarize)
```

### 样本 B：latency_spike —— R5-00023

某一步耗时被放大 5~20 倍。看 SPAN TREE 里的 dur(s) 列和 share 条：其中一个子步骤吃掉了几乎全部壁钟时间。真值把 L 维打到 0.10，算法应该在 L 上扣分并把责任指向那个 Span。

```text
==============================================================================
TRACE R5-00023   [intent0: list every entry in the current alarm list of network element NE-53AB-51]
  ontology=ontA  session=sess-00006  turn=1/3  spans=5  wall=2.314s  ts_start=1767227581.961
  user_feedback: abandoned=True human_takeover=True retry=False thumbs=None
  answer_numbers=['3421']
  answer_facts  =['NE-53AB-51', '3421']
  golden_answer =
  golden_facts  =None
  goal_text     =current alarm list   query_lang=en
  answer_citations  =[]
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=True usage_estimated=False
  embedding[0:4]=[-0.0448, 0.1095, 0.2291, -0.0418] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run           2.314 ######### 269       107        0.00204 ok    stop
       in : list every entry in the current alarm list of network element NE-53AB-51
       out: here is the outcome of 'list every entry in the current alarm list of ne
       meta: model=adn-llm-14b  facts=[3421]
       v3  : sys=158  cache_w=158  cost_det={cache_write:0.000593,completion:0.000642,prompt:0.000807}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan                0.661 ###       852       351        0.00526 ok    stop
         in : task=current alarm list ne=NE-53AB-51 window=24h; produce a step plan
         out: decompose into retrieval then aggregation; window=24h; nothing further r
         meta: model=adn-llm-14b  ttft=0.0808  pv=pv-2026-03
         v3  : sys=159  cache_w=159  cost_det={cache_write:0.000596,completion:0.00211,prompt:0.00256}  subgoal=decomposing the task steps on NE-53AB-51 as part of the curr
  `- s02           tool        api_call            0.072 #         0         0          0.00020 ok    -
         in : GET /nbi/v1/ne/NE-53AB-51/alarms?window=24h
         out: northbound returned objects 5552 9408 8759 3421 for NE-53AB-51
         meta: tool=nbi.ne_status  params={ne_id:NE-53AB-51,scope:ne}  facts=[5552 9408 8759 3421]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s04           llm         summarize           0.113 #         1039      141        0.00349 ok    stop
         in : write the final response for NE-53AB-51 from evidence 5552 9408 8759 342
         out: answer composed citing 5552 9408 8759 3421 2940 8381 for NE-53AB-51
         meta: model=adn-llm-72b  ttft=0.0153  pv=pv-2026-03
         v3  : sys=208  cache_r=208  cost_det={cache_read:0.000156,completion:0.000846,prompt:0.00249}  verifier=v_numbers_traceable:PASS  subgoal=condensing the evidence within 24h for the current alarm lis
  `- s03           tool        sql_query          -1.536           0         0          0.00020 ok    -
         in : SELECT kpi_ts,value FROM perf_15min WHERE ne='NE-53AB-51' AND window='24
         out: query settled; row ids 2940 8381; noted for the operator
         meta: tool=alarm_db.query  params={ne_id:NE-53AB-51,severity:critical,time_window:24h}  facts=[2940 8381]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['latency_spike']
    intent=i0  pattern=p1  cell=i0|p1
    oracle dim_dev : O=1.00  P=1.00  L=0.10  C=0.80  R=1.00
    latency_true=2.311s  gen_quantiles={'C': 0.4045, 'L': 0.1997}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': True, 'usage_estimated': False}
    responsible_span_ids=['R5-00023-s03']  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.0000  model_mix_true={'adn-llm-14b': 0.5723, 'adn-llm-72b': 0.4277}  feedback_available=True
    has_golden=False  key_fact_recall_true=n/a  fact_precision_true=n/a
    hallucinated_facts=[]
    query_lang_true=en  session_turn_count_true=3  subgoal_count=2
    plan_revision_true=0  goal_drift_true=False  arg_valid_true=1.0000  verifier_pass_true=1.0000
    citation_reachable_true=n/a  contradiction_true=0.0000  contradicted_count=0  fabricated_citation_count=0
    cache_read_true=208  cache_write_true=317  system_prompt_ratio_true=0.2431  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice3-v0.3.0)
    S=91.4073  G=1.00  grade_abs=A  grade_rel=B  tier=0  novelty=False
    alert=False (rule=False stat=False)  cold_start=False  cell=i1xp1
    dims    : O=1.000  P=1.000  L=0.604  C=0.804  R=1.000
    contrib : O=+0.000  P=+0.000  L=-5.307  C=-3.286  R=+0.000   sum=-8.5927
    zero-residual: S-100G=-8.5927  |diff|=4.50e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.2139  a_cal=0.1053  conf=0.8444  anchor=anchor-R5-10ff75f849deddbe
    evidence (3 items, drill-down order):
      - [trace] latency_total            span=R5-00023-s00   value=2.3141      cell_median=1.5598      z=  +1.03 dev=0.1563
      - [trace] branch_factor            span=-              value=4.0000      cell_median=3.0000      z=  +1.35 dev=0.0858
      - [span ] dur                      span=R5-00023-s03   value=1.5357      peer_median=0.2902      z=  +5.37 dev=0.3178 (L3/L3span action=sql_query)
```

### 样本 C：hallucinated_number（带 golden） —— R5-00356

最终答案里出现了检索证据中不存在的数字。对比子 Span 的 `out: evidence: ...` 与根 Span 的 `out: answer: ...`：后者多出了两个 5 位数。这是唯一一个靠文本内容判定的异常（`traceable_number_ratio` 特征）。

这条带 golden。看 GROUND TRUTH 里的 `fact_precision_true` 与 `key_fact_recall_true`：编造数字只压 precision，recall 仍为 1.00——答案里的事实都在，只是多了不该有的。`hallucinated_facts` 直接列出多出来的那几个。

```text
==============================================================================
TRACE R5-00356   [intent0: 我需要 NE-B394-19 的当前告警清单，若存在紧急告警请标记出来]
  ontology=ontA  session=sess-00085  turn=6/7  spans=5  wall=1.208s  ts_start=1767256364.721
  user_feedback: abandoned=True human_takeover=False retry=False thumbs=1
  answer_numbers=['4662', '24871', '93515']
  answer_facts  =['NE-B394-19', '4662', '24871', '93515']
  golden_answer =expected answer for NE-B394-19 (我需要 NE-B394-19 的当前告警清单，若存在紧急告警请标记出来): 4662
  golden_facts  =['NE-B394-19', '4662']
  goal_text     =当前告警清单   query_lang=zh
  answer_citations  =[]
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=True
  embedding[0:4]=[0.0138, 0.1909, 0.1923, 0.0135] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run           1.208 ######### 303       105        0.00105 ok    stop
       in : 我需要 NE-B394-19 的当前告警清单，若存在紧急告警请标记出来
       out: here is the outcome of '我需要 NE-B394-19 的当前告警清单，若存在紧急告警请标记出来' on NE-B394-
       meta: model=adn-llm-72b  facts=[4662 24871 93515]
       v3  : sys=217  cache_r=217  cost_det={cache_read:0.000163,completion:0.00063,prompt:0.000258}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan                0.570 ####      498       289        0.00288 ok    stop
         in : task=当前告警清单 ne=NE-B394-19 window=24h; produce a step plan
         out: attempt finished, step list drafted for NE-B394-19;  candidate actions
         meta: model=adn-llm-14b  level=WARNING  ttft=0.0989  pv=pv-2026-03  msg=slow query above soft limit
         v3  : sys=156  cache_r=156  cost_det={cache_read:0.000117,completion:0.00173,prompt:0.00103}  subgoal=针对当前告警清单进行拆解任务步骤（窗口 24h）
  `- s02           guard       verify              0.143 #         390       107        0.00181 ok    -
         in : compliance scan of the pending step set for NE-B394-19
         out: verdict pass for NE-B394-19
         v3  : cost_det={completion:0.000642,prompt:0.00117}  verifier=v_no_forbidden_action:PASS
  `- s03           tool        sql_query           0.143 #         0         0          0.00020 ok    -
         in : SELECT alarm_id,severity FROM current_alarms WHERE ne='NE-B394-19' AND w
         out: ok - query settled; row ids 4662 2440 9079 4144
         meta: tool=perf_db.query  params={ne_id:NE-B394-19,severity:major,time_window:24h}  facts=[4662 2440 9079 4144]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s04           llm         summarize           0.441 ###       None      162        0.00339 ok    stop
         in : condense evidence 4662 2440 9079 4144 into an operator-facing answer
         out: answer composed citing 4662 2440 9079 4144
         meta: model=adn-llm-14b  ttft=0.0206  pv=pv-2026-03
         v3  : sys=137  cache_r=137  cost_det={cache_read:0.000103,completion:0.000972,prompt:0.00232}  verifier=v_numbers_traceable:FAIL(answer number absent from the evidence pool)  subgoal=推进当前告警清单：归纳证据

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['hallucinated_number']
    intent=i0  pattern=p1  cell=i0|p1
    oracle dim_dev : O=0.15  P=1.00  L=0.80  C=0.81  R=1.00
    latency_true=1.206s  gen_quantiles={'C': 0.387, 'L': 0.3967}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': True}
    responsible_span_ids=[]  human_label=True  drift_segment=None
    loop_true=False  mfr_true=0.0213  model_mix_true={'adn-llm-14b': 0.6993, 'adn-llm-72b': 0.3007}  feedback_available=True
    has_golden=True  key_fact_recall_true=1.0000  fact_precision_true=0.5000
    hallucinated_facts=['24871', '93515']
    query_lang_true=zh  session_turn_count_true=7  subgoal_count=2
    plan_revision_true=0  goal_drift_true=False  arg_valid_true=1.0000  verifier_pass_true=0.6667
    citation_reachable_true=n/a  contradiction_true=0.0000  contradicted_count=0  fabricated_citation_count=0
    cache_read_true=510  cache_write_true=0  system_prompt_ratio_true=0.4282  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice3-v0.3.0)
    S=17.2051  G=0.25  grade_abs=D  grade_rel=D  tier=2  novelty=False
    alert=True (rule=True stat=False)  cold_start=False  cell=i1xp1
    dims    : O=0.446  P=1.000  L=0.886  C=0.889  R=1.000
    contrib : O=-7.159  P=+0.000  L=-0.402  C=-0.234  R=+0.000   sum=-7.7949
    zero-residual: S-100G=-7.7949  |diff|=7.00e-06  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.9022  a_cal=0.9689  conf=0.8354  anchor=anchor-R5-10ff75f849deddbe
    gates: {"t0_result_broken": 0.25}
    evidence (3 items, drill-down order):
      - [trace] traceable_number_ratio   span=-              value=0.3333      cell_median=1.0000      z= -50.00 dev=0.3378
      - [trace] branch_factor            span=-              value=4.0000      cell_median=3.0000      z=  +1.35 dev=0.0858
      - [span ] tok                      span=R5-00356-s02   value=497.0000    peer_median=318.0000    z=  +0.94 dev=0.1461 (L3/L3span action=verify)
```

### 样本 D：loop —— R5-00198

同一步骤被重复插入 3~5 次。SPAN TREE 里会看到连续多行相同 action，时间戳也相同（生成器直接复制了 Span）。

```text
==============================================================================
TRACE R5-00198   [intent0: which alarms are still active in the current alarm list of NE-8B7F-34]
  ontology=ontA  session=sess-00050  turn=1/6  spans=9  wall=3.215s  ts_start=1767242695.366
  user_feedback: none captured
  answer_numbers=['9831', '1639']
  answer_facts  =['NE-8B7F-34', '9831', '1639']
  golden_answer =
  golden_facts  =None
  goal_text     =current alarm list   query_lang=en
  answer_citations  =['doc://vendor/nbi-api-reference#L310']
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[0.0902, 0.0572, 0.2095, 0.0236] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run           3.215 ######### 271       108        0.00224 ok    stop
       in : which alarms are still active in the current alarm list of NE-8B7F-34
       out: 'which alarms are still active in the current alarm list of NE-8B7F-34' 
       meta: model=adn-llm-72b  facts=[9831 1639]
       v3  : sys=209  cache_w=209  cost_det={cache_write:0.000784,completion:0.000648,prompt:0.000813}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan                1.888 #####     930       215        0.00494 ok    stop
         in : decompose request from NE-8B7F-34 over 1h into executable steps
         out: decompose into retrieval then aggregation; window=1h
         meta: model=adn-llm-72b  ttft=0.2810  pv=pv-2026-03
         v3  : sys=230  cache_w=230  cost_det={cache_write:0.000862,completion:0.00129,prompt:0.00279}  subgoal=advance the current alarm list by decomposing the task steps
  `- s02           llm         plan                0.755 ##        797       381        0.00434 ok    stop
         in : task=current alarm list ne=NE-8B7F-34 window=1h; produce a step plan
         out: attempt finished, decompose into retrieval then aggregation; window=1h
         meta: model=adn-llm-14b  ttft=0.1633  pv=pv-2026-03
         v3  : sys=150  cache_r=150  cost_det={cache_read:0.000112,completion:0.00229,prompt:0.00194}  subgoal=advance the current alarm list by decomposing the task steps
  `- s03           retrieval   retrieve_kb         0.584 ##        473       0          0.00142 ok    -
         in : runbook search: current alarm list (ne=NE-8B7F-34)
         out: attempt finished, knowledge hits ranked: 1639 7350
         meta: tool=kb.history_search  params={query:NE-8B7F-34,top_k:10}  facts=[1639 7350]
         v3  : cost_det={prompt:0.00142}  arg_valid=True  retrieved=[doc://vendor/nbi-api-reference#L310]
  `- s04           retrieval   retrieve_kb         0.584 ##        394       0          0.00118 ok    -
         in : runbook search: current alarm list (ne=NE-8B7F-34)
         out: step done - knowledge hits ranked: 4655 9984 4908 1508
         meta: tool=kb.history_search  params={query:NE-8B7F-34,top_k:10}  facts=[4655 9984 4908 1508]
         v3  : cost_det={prompt:0.00118}  arg_valid=True  retrieved=[doc://vendor/nbi-api-reference#L310]
  `- s05           retrieval   retrieve_kb         0.584 ##        279       0          0.00084 ok    -
         in : runbook search: current alarm list (ne=NE-8B7F-34)
         out: ok - matched runbook evidence: 4967 9831 3254 9724
         meta: tool=kb.history_search  params={query:NE-8B7F-34,top_k:10}  facts=[4967 9831 3254 9724]
         v3  : cost_det={prompt:0.000837}  arg_valid=True  retrieved=[doc://vendor/nbi-api-reference#L310]
  `- s06           retrieval   retrieve_kb         0.584 ##        279       0          0.00084 ok    -
         in : history search over incidents touching NE-8B7F-34
         out: knowledge hits ranked: 3438 7134 6109; payload attached to the trace
         meta: tool=kb.history_search  params={query:NE-8B7F-34,top_k:10}  facts=[3438 7134 6109]
         v3  : cost_det={prompt:0.000837}  arg_valid=True  retrieved=[doc://vendor/nbi-api-reference#L310]
  `- s07           retrieval   retrieve_kb         0.584 ##        321       0          0.00096 ok    -
         in : runbook search: current alarm list (ne=NE-8B7F-34)
         out: attempt finished, knowledge hits ranked: 3764 9251
         meta: tool=kb.history_search  params={query:NE-8B7F-34,top_k:10}  facts=[3764 9251]
         v3  : cost_det={prompt:0.000963}  arg_valid=True  retrieved=[doc://vendor/nbi-api-reference#L310]
  `- s08           llm         summarize           0.615 ##        750       304        0.00370 ok    stop
         in : write the final response for NE-8B7F-34 from evidence 9724 3438 7134 610
         out: answer composed citing 9724 3438 7134 6109 3764 9251; noted for the oper
         meta: model=adn-llm-14b  ttft=0.1121  pv=pv-2026-03
         v3  : sys=165  cache_r=165  cost_det={cache_read:0.000124,completion:0.00182,prompt:0.00176}  verifier=v_numbers_traceable:PASS  subgoal=condensing the evidence for the current alarm list

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['loop']
    intent=i0  pattern=p3  cell=i0|p3
    oracle dim_dev : O=1.00  P=0.50  L=0.53  C=0.79  R=0.55
    latency_true=3.212s  gen_quantiles={'C': 0.4138, 'L': 0.9303}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=['R5-00198-s03', 'R5-00198-s04', 'R5-00198-s05', 'R5-00198-s06', 'R5-00198-s07']  human_label=None  drift_segment=None
    loop_true=True  mfr_true=0.0000  model_mix_true={'adn-llm-14b': 0.5942, 'adn-llm-72b': 0.4058}  feedback_available=False
    has_golden=False  key_fact_recall_true=n/a  fact_precision_true=n/a
    hallucinated_facts=[]
    query_lang_true=en  session_turn_count_true=6  subgoal_count=3
    plan_revision_true=1  goal_drift_true=False  arg_valid_true=1.0000  verifier_pass_true=1.0000
    citation_reachable_true=1.0000  contradiction_true=0.0000  contradicted_count=0  fabricated_citation_count=0
    cache_read_true=315  cache_write_true=439  system_prompt_ratio_true=0.1678  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice3-v0.3.0)
    S=26.2865  G=0.35  grade_abs=D  grade_rel=D  tier=2  novelty=False
    alert=True (rule=True stat=False)  cold_start=False  cell=i1xp0
    dims    : O=1.000  P=0.800  L=0.408  C=0.580  R=0.775
    contrib : O=+0.000  P=-1.358  L=-4.094  C=-2.486  R=-0.776   sum=-8.7135
    zero-residual: S-100G=-8.7135  |diff|=3.70e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.9415  a_cal=0.9772  conf=0.9725  anchor=anchor-R5-10ff75f849deddbe
    gates: {"loop_runaway": 0.35}
    evidence (3 items, drill-down order):
      - [trace] branch_factor            span=-              value=8.0000      cell_median=4.0000      z=  +2.70 dev=0.4101
      - [trace] loop_count               span=-              value=3.0000      cell_median=0.0000      z= +50.00 dev=0.4101
      - [span ] dur                      span=R5-00198-s01   value=1.8879      peer_median=0.4909      z=  +4.13 dev=0.3333 (L3/L3span action=plan)
```

### 样本 E：token_bloat —— R5-00027

某个 LLM 步骤的 token 被放大 4~10 倍，耗时不变。只有成本维（C）会崩，时延维不崩——用来验证五维不会互相污染。

```text
==============================================================================
TRACE R5-00027   [intent0: NE-1DB0-54 的当前告警清单里还有哪些活动告警]
  ontology=ontA  session=sess-00007  turn=2/2  spans=6  wall=2.356s  ts_start=1767227920.602
  user_feedback: none captured
  answer_numbers=[]
  answer_facts  =[]
  golden_answer =
  golden_facts  =None
  goal_text     =当前告警清单   query_lang=zh
  answer_citations  =['doc://policy/change-approval-rules#L7']
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=8 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[-0.0838, 0.2215, 0.284, -0.0175] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run           2.356 ######### 144       50         0.00041 ok    stop
       in : NE-1DB0-54 的当前告警清单里还有哪些活动告警
       out: completed 'NE-1DB0-54 的当前告警清单里还有哪些活动告警' on NE-1DB0-54
       meta: model=adn-llm-72b
       v3  : sys=144  cache_r=144  cost_det={cache_read:0.000108,completion:0.0003}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan                0.361 #         4395      1203       0.02008 ok    stop
         in : task=当前告警清单 ne=NE-1DB0-54 window=15m; produce a step plan
         out: ok - step list drafted for NE-1DB0-54;  candidate actions
         meta: model=adn-llm-14b
         v3  : cost_det={cache_read:0.000107,completion:0.00722,prompt:0.0128}  subgoal=针对当前告警清单进行拆解任务步骤（窗口 15m）
  `- s02           tool        api_call            0.361 #         0         0          0.00020 ok    -
         in : GET /nbi/v1/ne/NE-1DB0-54/alarms?window=15m
         out: response payload ids: 1218 1785
         meta: tool=nbi.alarm_list  params={ne_id:NE-1DB0-54,scope:subnetwork}  facts=[1218 1785]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s03           retrieval   schema_retrieval    0.787 ###       178       0          0.00053 ok    -
         in : lookup schema for alarm tables of NE-1DB0-54
         out: schema rows: 5898 6012 3036; noted for the operator
         meta: tool=catalog.table_schema  params={table:current_alarms}  facts=[5898 6012 3036]
         v3  : cost_det={prompt:0.000534}  arg_valid=True  retrieved=[doc://policy/change-approval-rules#L7]
  `- s04           tool        sql_query           0.272 #         0         0          0.00020 ok    -
         in : SELECT alarm_id,severity FROM current_alarms WHERE ne='NE-1DB0-54' AND w
         out: query settled; row ids 2418 5160; noted for the operator
         meta: tool=perf_db.query  params={ne_id:NE-1DB0-54,severity:minor,time_window:15m}  facts=[2418 5160]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s05           llm         summarize           0.833 ###       357       168        0.00170 ok    stop
         in : write the final response for NE-1DB0-54 from evidence 1785 5898 6012 303
         out: step done - answer composed citing 1785 5898 6012 3036 2418 5160
         meta: model=adn-llm-14b  level=WARNING  pv=pv-2026-03  msg=partial result set returned
         v3  : cost_det={cache_read:0.000125,completion:0.00101,prompt:0.00057}  verifier=v_numbers_traceable:PASS  subgoal=围绕当前告警清单执行归纳证据

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['token_bloat']
    intent=i0  pattern=p2  cell=i0|p2
    oracle dim_dev : O=1.00  P=1.00  L=0.56  C=0.12  R=1.00
    latency_true=2.353s  gen_quantiles={'C': 0.0266, 'L': 0.8711}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=['R5-00027-s01']  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.1455  model_mix_true={'adn-llm-14b': 0.9693, 'adn-llm-72b': 0.0307}  feedback_available=False
    has_golden=False  key_fact_recall_true=n/a  fact_precision_true=n/a
    hallucinated_facts=[]
    query_lang_true=zh  session_turn_count_true=2  subgoal_count=2
    plan_revision_true=0  goal_drift_true=False  arg_valid_true=1.0000  verifier_pass_true=1.0000
    citation_reachable_true=1.0000  contradiction_true=n/a  contradicted_count=0  fabricated_citation_count=0
    cache_read_true=144  cache_write_true=0  system_prompt_ratio_true=0.0284  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice3-v0.3.0)
    S=80.0485  G=1.00  grade_abs=B  grade_rel=D  tier=0  novelty=False
    alert=False (rule=False stat=False)  cold_start=False  cell=i1xp2
    dims    : O=1.000  P=1.000  L=0.576  C=0.453  R=1.000
    contrib : O=+0.000  P=+0.000  L=-8.200  C=-11.751  R=+0.000   sum=-19.9515
    zero-residual: S-100G=-19.9515  |diff|=3.30e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.3006  a_cal=0.1922  conf=0.9103  anchor=anchor-R5-10ff75f849deddbe
    evidence (3 items, drill-down order):
      - [trace] tokens_total             span=R5-00027-s01   value=6495.0000   cell_median=3185.5000   z=  +2.34 dev=0.2571
      - [trace] cost_total               span=R5-00027-s01   value=0.0231      cell_median=0.0122      z=  +1.91 dev=0.2496
      - [span ] tok                      span=R5-00027-s01   value=5598.0000   peer_median=1021.5000   z=  +9.05 dev=0.4955 (L3/L3span action=plan)
```

### 样本 F：illegal_step —— R5-00017

插入了本体禁止的动作（如 `force_delete` / `skip_approval_execute`）。这是确定性违规，走规则闸门（alert_rule=True）而不是统计异常。

```text
==============================================================================
TRACE R5-00017   [intent1: I need the degradation root cause on NE-BA47-39; include the metric that proves it]
  ontology=ontA  session=sess-00005  turn=2/7  spans=7  wall=21.462s  ts_start=1767227077.755
  user_feedback: none captured
  answer_numbers=['5100']
  answer_facts  =['NE-BA47-39', '5100']
  golden_answer =
  golden_facts  =None
  goal_text     =degradation root cause   query_lang=en
  answer_citations  =[]
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=1 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[-0.1057, 0.0574, 0.097, 0.1086] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run          21.462 ######### 348       139        0.00138 ok    stop
       in : I need the degradation root cause on NE-BA47-39; include the metric that
       out: completed 'I need the degradation root cause on NE-BA47-39; include the 
       meta: model=adn-llm-72b  facts=[5100]
       v3  : sys=222  cache_r=222  cost_det={cache_read:0.000167,completion:0.000834,prompt:0.000378}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan                7.340 ###       1024      331        0.00473 ok    stop
         in : decompose request from NE-BA47-39 over 15m into executable steps
         out: attempt finished, step list drafted for NE-BA47-39;  candidate actions
         meta: model=adn-llm-14b  ttft=1.8209  pv=pv-2026-03
         v3  : sys=145  cache_r=145  cost_det={cache_read:0.000109,completion:0.00199,prompt:0.00264}  subgoal=decomposing the task steps within 15m for the degradation ro
  `- s02           tool        api_call            4.066 ##        0         0          0.00020 ok    -
         in : GET /nbi/v1/ne/NE-BA47-39/status?detail=true
         out: northbound returned objects 4359 4738 5100 2675 (window 15m)
         meta: tool=nbi.ne_status  params={ne_id:NE-BA47-39,scope:not-in-enum}  facts=[4359 4738 5100 2675]
         v3  : cost_det={tool_call:0.0002}  arg_valid=False
  `- s03           tool        skip_approval_execute    1.020 #         0         0          0.00020 ok    -
         in : apply change to NE-BA47-39 bypassing approval gate
         out: applied without approval: 4533 4084; payload attached to the trace
         meta: tool=nbi.config_apply_nocheck  facts=[4533 4084]
         v3  : cost_det={tool_call:0.0002}
  `- s04           guard       verify              0.510 #         290       54         0.00119 ok    -
         in : compliance scan of the pending step set for NE-BA47-39
         out: policy evaluation on NE-BA47-39: block - policy violation
         v3  : cost_det={completion:0.000324,prompt:0.00087}  verifier=v_no_forbidden_action:FAIL(forbidden action before gate: skip_approval_execute)
  `- s05           tool        sql_query           8.625 ####      0         0          0.00020 ok    -
         in : SELECT kpi_ts,value FROM perf_15min WHERE ne='NE-BA47-39' AND window='15
         out: rows returned: 7242 9329 8302; nothing further required
         meta: tool=alarm_db.query  params={ne_id:NE-BA47-39,severity:major,time_window:not-in-enum}  facts=[7242 9329 8302]
         v3  : cost_det={tool_call:0.0002}
  `- s06           llm         summarize           8.625 ####      950       170        0.00340 ok    stop
         in : write the final response for NE-BA47-39 from evidence 2675 4533 4084 724
         out: attempt finished, summary drafted from 2675 4533 4084 7242 9329 8302
         meta: model=adn-llm-72b  ttft=0.3269  pv=pv-2026-03
         v3  : sys=210  cache_r=210  cost_det={cache_read:0.000158,completion:0.00102,prompt:0.00222}  verifier=v_numbers_traceable:PASS  subgoal=advance the degradation root cause by condensing the evidenc

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['illegal_step']
    intent=i1  pattern=p1  cell=i1|p1
    oracle dim_dev : O=1.00  P=0.05  L=0.81  C=0.68  R=1.00
    latency_true=21.459s  gen_quantiles={'C': 0.6313, 'L': 0.3725}
    process_flags={'illegal_step': True, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=['R5-00017-s03']  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.0339  model_mix_true={'adn-llm-14b': 0.4575, 'adn-llm-72b': 0.5425}  feedback_available=False
    has_golden=False  key_fact_recall_true=n/a  fact_precision_true=n/a
    hallucinated_facts=[]
    query_lang_true=en  session_turn_count_true=7  subgoal_count=2
    plan_revision_true=0  goal_drift_true=False  arg_valid_true=0.0000  verifier_pass_true=0.6667
    citation_reachable_true=n/a  contradiction_true=0.0000  contradicted_count=0  fabricated_citation_count=0
    cache_read_true=577  cache_write_true=0  system_prompt_ratio_true=0.2209  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice3-v0.3.0)
    S=3.8320  G=0.04  grade_abs=D  grade_rel=D  tier=2  novelty=False
    alert=True (rule=True stat=False)  cold_start=False  cell=i0xp1
    dims    : O=1.000  P=0.550  L=0.987  C=0.770  R=1.000
    contrib : O=+0.000  P=-0.497  L=-0.008  C=-0.163  R=+0.000   sum=-0.6680
    zero-residual: S-100G=-0.6680  |diff|=2.00e-06  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.9469  a_cal=0.9782  conf=0.9485  anchor=anchor-R5-10ff75f849deddbe
    gates: {"forbidden_action": 0.3, "guard_violation": 0.15}
    evidence (3 items, drill-down order):
      - [trace] guard_hits               span=-              value=1.0000      cell_median=0.0000      z= +50.00 dev=0.3789
      - [trace] branch_factor            span=-              value=6.0000      cell_median=3.0000      z=  +2.02 dev=0.3474
      - [span ] dur                      span=R5-00017-s03   value=1.0199      peer_median=0.0383      z= +50.00 dev=0.8774 (L3/L1span action=skip_approval_execute)
```

### 样本 G：truncation（带 golden） —— R5-00357

根 Span 的 `finish_reason=length`，答案被截断，结果维（O）重罚。

这条带 golden。与上一个样本对着看：截断只压 `key_fact_recall_true`，precision 仍为 1.00——说出来的都对，只是没说完。生成器故意把“不完整”与“不忠实”做成可分离的两类，否则O 维会把两种完全不同的失败打成同一个分。

```text
==============================================================================
TRACE R5-00357   [intent1: 分析 NE-B955-02 的指标下降并给出劣化根因]
  ontology=ontA  session=sess-00085  turn=7/7  spans=5  wall=75.320s  ts_start=1767256456.732
  user_feedback: abandoned=False human_takeover=True retry=True thumbs=-1
  answer_numbers=['5497', '4197', '95']
  answer_facts  =['NE-B955-02', '5497', '4197', '95']
  golden_answer =expected answer for NE-B955-02 (分析 NE-B955-02 的指标下降并给出劣化根因): 5497, 4197, 5340
  golden_facts  =['NE-B955-02', '5497', '4197', '5340']
  goal_text     =劣化根因   query_lang=zh
  answer_citations  =['doc://policy/change-approval-rules#L7', 'doc://vendor/nbi-api-reference#L1860', 'kb://history/incident-2026-0043', 'runbook://adn/ne-health-check#L1823']
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=2 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[-0.0474, 0.05, 0.0364, 0.0869] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run          75.320 ######### 376       130        0.00272 ok    length
       in : 分析 NE-B955-02 的指标下降并给出劣化根因
       out: '分析 NE-B955-02 的指标下降并给出劣化根因' on NE-B955-02 resolved; see 5497, 4197, 95
       meta: model=adn-llm-72b  facts=[5497 4197 95]
       v3  : sys=217  cache_w=217  cost_det={cache_write:0.000814,completion:0.00078,prompt:0.00113}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan               39.268 #####     1077      71         0.00333 ok    stop
         in : task=劣化根因 ne=NE-B955-02 window=1h; produce a step plan
         out: step list drafted for NE-B955-02;  candidate actions (window 1h)
         meta: model=adn-llm-14b  ttft=1.5680  pv=pv-2026-03
         v3  : sys=147  cache_r=147  cost_det={cache_read:0.00011,completion:0.000426,prompt:0.00279}  subgoal=针对劣化根因进行拆解任务步骤（窗口 1h）
  `- s02           guard       approve             4.299 #         328       81         0.00147 ok    -
         in : route the pending change on NE-B955-02 to the approver
         out: approval gate pass on NE-B955-02
         v3  : cost_det={completion:0.000486,prompt:0.000984}  verifier=v_no_forbidden_action:PASS
  `- s03           retrieval   retrieve_kb         6.098 #         339       0          0.00102 ok    -
         in : runbook search: 劣化根因 (ne=NE-B955-02)
         out: attempt finished, matched runbook evidence: 4197 5497
         meta: tool=kb.history_search  params={query:NE-B955-02,top_k:5}  facts=[4197 5497]
         v3  : cost_det={prompt:0.00102}  arg_valid=True  retrieved=[doc://policy/change-approval-rules#L7 doc://topology/subnetwork-east-map kb://history/incident-2026-0043]
  `- s04           llm         summarize          22.364 ###       911       174        0.00342 ok    stop
         in : write the final response for NE-B955-02 from evidence 4197 5497
         out: step done - summary drafted from 4197 5497
         meta: model=adn-llm-14b  ttft=2.9362  pv=pv-2026-03
         v3  : cache_r=158  cost_det={cache_read:0.000119,completion:0.00104,prompt:0.00226}  verifier=v_numbers_traceable:FAIL(answer number absent from the evidence pool)  subgoal=为劣化根因归纳证据

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['truncation']
    intent=i1  pattern=p3  cell=i1|p3
    oracle dim_dev : O=0.35  P=1.00  L=0.65  C=0.71  R=1.00
    latency_true=75.317s  gen_quantiles={'C': 0.5758, 'L': 0.7027}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=[]  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.0417  model_mix_true={'adn-llm-14b': 0.8153, 'adn-llm-72b': 0.1847}  feedback_available=True
    has_golden=True  key_fact_recall_true=0.7500  fact_precision_true=0.7500
    hallucinated_facts=['95']
    query_lang_true=zh  session_turn_count_true=7  subgoal_count=2
    plan_revision_true=0  goal_drift_true=False  arg_valid_true=1.0000  verifier_pass_true=0.6667
    citation_reachable_true=0.5000  contradiction_true=0.0000  contradicted_count=0  fabricated_citation_count=2
    cache_read_true=305  cache_write_true=217  system_prompt_ratio_true=0.1201  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice3-v0.3.0)
    S=18.7932  G=0.25  grade_abs=D  grade_rel=D  tier=2  novelty=False
    alert=True (rule=True stat=False)  cold_start=False  cell=i0xp0
    dims    : O=0.640  P=1.000  L=0.622  C=0.790  R=1.000
    contrib : O=-3.884  P=+0.000  L=-1.552  C=-0.771  R=+0.000   sum=-6.2068
    zero-residual: S-100G=-6.2068  |diff|=3.00e-06  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.9102  a_cal=0.9708  conf=0.9631  anchor=anchor-R5-10ff75f849deddbe
    gates: {"t0_result_broken": 0.25}
    evidence (3 items, drill-down order):
      - [trace] traceable_number_ratio   span=-              value=0.6667      cell_median=1.0000      z= -50.00 dev=0.3013
      - [trace] latency_total            span=R5-00357-s00   value=75.3197     cell_median=45.8001     z=  +1.03 dev=0.1643
      - [span ] dur                      span=R5-00357-s01   value=39.2680     peer_median=14.2248     z=  +2.08 dev=0.2065 (L3/L3span action=plan)
```

### 样本 H：missing_step —— R5-00086

本体要求的必须步骤被删掉一个，过程维（P）扣分。

```text
==============================================================================
TRACE R5-00086   [intent0: give me the current alarm list on NE-1B6B-43, then explain why each one was raised]
  ontology=ontA  session=sess-00019  turn=6/6  spans=4  wall=2.724s  ts_start=1767233019.542
  user_feedback: none captured
  answer_numbers=['7546', '1343', '3291']
  answer_facts  =['NE-1B6B-43', '7546', '1343', '3291']
  golden_answer =
  golden_facts  =None
  goal_text     =current alarm list   query_lang=en
  answer_citations  =[]
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=9 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[-0.0199, 0.0157, 0.1617, -0.021] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run           2.724 ######### 253       101        0.00105 ok    stop
       in : give me the current alarm list on NE-1B6B-43, then explain why each one 
       out: completed 'give me the current alarm list on NE-1B6B-43, then explain wh
       meta: model=adn-llm-14b  facts=[7546 1343 3291]
       v3  : sys=142  cache_r=142  cost_det={cache_read:0.000107,completion:0.000606,prompt:0.000333}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan                0.962 ###       797       280        0.00374 ok    stop
         in : decompose request from NE-1B6B-43 over 24h into executable steps
         out: step list drafted for NE-1B6B-43;  candidate actions; payload attached t
         meta: model=adn-llm-14b  pv=pv-2026-03
         v3  : sys=147  cost_det={cache_read:0.00011,completion:0.00168,prompt:0.00195}
  `- s02           tool        api_call            0.595 ##        0         0          0.00020 ok    -
         in : GET /nbi/v1/ne/NE-1B6B-43/status?detail=true
         out: step done - response payload ids: 3291 1343 7546
         meta: tool=nbi.alarm_list  params={ne_id:NE-1B6B-43,scope:subnetwork}  facts=[3291 1343 7546]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s03           llm         summarize           0.580 ##        848       176        0.00326 ok    stop
         in : condense evidence 3291 1343 7546 into an operator-facing answer
         out: ok - answer composed citing 3291 1343 7546
         v3  : sys=149  cost_det={cache_read:0.000112,completion:0.00106,prompt:0.0021}  verifier=v_numbers_traceable:PASS

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['missing_step']
    intent=i0  pattern=p1  cell=i0|p1
    oracle dim_dev : O=1.00  P=0.80  L=0.58  C=0.82  R=1.00
    latency_true=2.721s  gen_quantiles={'C': 0.3527, 'L': 0.8389}
    process_flags={'illegal_step': False, 'missing_step': True, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=[]  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.2143  model_mix_true={'adn-llm-14b': 1.0}  feedback_available=False
    has_golden=False  key_fact_recall_true=n/a  fact_precision_true=n/a
    hallucinated_facts=[]
    query_lang_true=en  session_turn_count_true=6  subgoal_count=0
    plan_revision_true=0  goal_drift_true=False  arg_valid_true=1.0000  verifier_pass_true=1.0000
    citation_reachable_true=n/a  contradiction_true=0.0000  contradicted_count=0  fabricated_citation_count=0
    cache_read_true=142  cache_write_true=0  system_prompt_ratio_true=0.2308  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice3-v0.3.0)
    S=88.5489  G=1.00  grade_abs=B  grade_rel=B  tier=0  novelty=False
    alert=False (rule=False stat=False)  cold_start=False  cell=i1xp4
    dims    : O=1.000  P=1.000  L=0.500  C=0.888  R=1.000
    contrib : O=+0.000  P=+0.000  L=-9.777  C=-1.674  R=+0.000   sum=-11.4511
    zero-residual: S-100G=-11.4511  |diff|=1.40e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.2170  a_cal=0.1078  conf=0.6868  anchor=anchor-R5-10ff75f849deddbe
    evidence (3 items, drill-down order):
      - [trace] missing_field_ratio      span=-              value=0.2143      cell_median=0.0280      z=  +4.49 dev=0.3637
      - [trace] latency_total            span=R5-00086-s00   value=2.7237      cell_median=1.5418      z=  +1.34 dev=0.3482
      - [span ] dur                      span=R5-00086-s00   value=2.7237      peer_median=1.2354      z=  +1.46 dev=0.2670 (L3/L3span action=agent_run)
```

## 六、v3 共生缺陷样本（附录 A 新增特征的原始证据）

下面这些**不是**独立的异常类型，而是叠加在已异常轨迹上的共生缺陷。每一个都由
`bench/coverage.truth_agreement()` 在全部轨迹上做双向等价校验（内核特征 ⟺ 生成器真值），
任何一条对不上都会让构建直接失败，而不是只在报告里留一行警告。


### v3 样本 A：plan_revision —— R5-00007

入口步骤（ontA 的 `plan`、ontB 的 `intent_parse`）出现了两次，第二次的时间区间**嵌套在**第一次之内——智能体在一步还没走完时就重开了计划。`kernel/cluster.collapse()` 会折叠相邻重复，所以模式视图看到的骨架完全不变，只有 `plan_revision_count` 能看见它。这也是该特征被定义成“时间包含”而不是“计数减一”的原因：循环注入器同样可能选中入口步骤，计数减一会把一次循环读成两次计划修订。

```text
==============================================================================
TRACE R5-00007   [intent0: 我需要 NE-8BD0-42 的当前告警清单，若存在紧急告警请标记出来]
  ontology=ontA  session=sess-00001  turn=2/3  spans=6  wall=3.235s  ts_start=1767226188.463
  user_feedback: abandoned=False human_takeover=False retry=False thumbs=1
  answer_numbers=['3577', '7235']
  answer_facts  =['NE-8BD0-42', '3577', '7235']
  golden_answer =
  golden_facts  =None
  goal_text     =当前告警清单   query_lang=zh
  answer_citations  =['kb://history/incident-2025-1187']
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=True
  embedding[0:4]=[-0.1423, 0.0653, 0.1588, -0.0081] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run           3.235 ######### 256       89         0.00095 ok    stop
       in : 我需要 NE-8BD0-42 的当前告警清单，若存在紧急告警请标记出来
       out: here is the outcome of '我需要 NE-8BD0-42 的当前告警清单，若存在紧急告警请标记出来' on NE-8BD0-
       meta: model=adn-llm-14b  facts=[3577 7235]
       v3  : sys=155  cache_r=155  cost_det={cache_read:0.000116,completion:0.000534,prompt:0.000303}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan                0.471 #         None      142        0.00249 ok    stop
         in : task=当前告警清单 ne=NE-8BD0-42 window=1h; produce a step plan
         out: attempt finished, decompose into retrieval then aggregation; window=1h
         meta: model=adn-llm-72b  ttft=0.0560  pv=pv-2026-03
         v3  : sys=234  cache_r=234  cost_det={cache_read:0.000176,completion:0.000852,prompt:0.00146}  subgoal=推进当前告警清单：拆解任务步骤
  `- s02           llm         plan                0.188 #         747       186            n/a ok    stop
         in : task=当前告警清单 ne=NE-8BD0-42 window=1h; produce a step plan
         out: decompose into retrieval then aggregation; window=1h (window 1h)
         meta: model=adn-llm-14b  ttft=0.0255  pv=pv-2026-03
         v3  : sys=136  cache_r=136  cost_det={cache_read:0.000102,completion:0.00112,prompt:0.00183}  subgoal=步骤目标：拆解任务步骤，服务于当前告警清单
  `- s03           tool        api_call            0.542 ##        None      0          0.00020 ok    -
         in : GET /nbi/v1/ne/NE-8BD0-42/alarms?window=1h
         out: northbound returned objects 7235 8916 3577; payload attached to the trac
         meta: tool=nbi.ne_status  params={ne_id:NE-8BD0-42,scope:subnetwork}  facts=[7235 8916 3577]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s04           retrieval   retrieve_kb         1.151 ###       257       0          0.00077 ok    -
         in : runbook search: 当前告警清单 (ne=NE-8BD0-42)
         out: attempt finished, matched runbook evidence: 1685 1547
         meta: tool=kb.runbook_search  params={query:NE-8BD0-42,top_k:3}  facts=[1685 1547]
         v3  : cost_det={prompt:0.000771}  arg_valid=True  retrieved=[kb://history/incident-2025-1187]
  `- s05           llm         summarize           0.927 ###       512       132        0.00320 ok    stop
         in : condense evidence 7235 8916 3577 1685 1547 into an operator-facing answe
         out: summary drafted from 7235 8916 3577 1685 1547; nothing further required
         meta: model=adn-llm-72b  ttft=0.1166  pv=pv-2026-03
         v3  : sys=232  cache_w=232  cost_det={cache_write:0.00087,completion:0.000792,prompt:0.00154}  verifier=v_numbers_traceable:PASS  subgoal=步骤目标：归纳证据，服务于当前告警清单

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=False  anomaly_types=[]
    intent=i0  pattern=p3  cell=i0|p3
    oracle dim_dev : O=1.00  P=1.00  L=0.53  C=0.87  R=1.00
    latency_true=3.232s  gen_quantiles={'C': 0.2557, 'L': 0.9308}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': True}
    responsible_span_ids=[]  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.0323  model_mix_true={'adn-llm-14b': 0.6192, 'adn-llm-72b': 0.3808}  feedback_available=True
    has_golden=False  key_fact_recall_true=n/a  fact_precision_true=n/a
    hallucinated_facts=[]
    query_lang_true=zh  session_turn_count_true=3  subgoal_count=3
    plan_revision_true=1  goal_drift_true=False  arg_valid_true=1.0000  verifier_pass_true=1.0000
    citation_reachable_true=1.0000  contradiction_true=0.0000  contradicted_count=0  fabricated_citation_count=0
    cache_read_true=525  cache_write_true=232  system_prompt_ratio_true=0.4272  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice3-v0.3.0)
    S=85.4134  G=1.00  grade_abs=B  grade_rel=C  tier=0  novelty=False
    alert=False (rule=False stat=False)  cold_start=False  cell=i1xp0
    dims    : O=1.000  P=1.000  L=0.403  C=0.875  R=1.000
    contrib : O=+0.000  P=+0.000  L=-13.403  C=-1.183  R=+0.000   sum=-14.5866
    zero-residual: S-100G=-14.5866  |diff|=2.00e-06  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.2436  a_cal=0.1303  conf=0.8133  anchor=anchor-R5-10ff75f849deddbe
    evidence (3 items, drill-down order):
      - [trace] latency_total            span=R5-00007-s00   value=3.2346      cell_median=1.5417      z=  +2.35 dev=0.2739
      - [trace] retry_count              span=-              value=1.0000      cell_median=0.0000      z= +50.00 dev=0.2261
      - [span ] dur                      span=R5-00007-s04   value=1.1510      peer_median=0.2883      z=  +3.64 dev=0.3401 (L3/L3span action=retrieve_kb)
```

### v3 样本 B：goal_drift —— R5-00029

某个 `subgoal_text` 与本条轨迹的 `goal_text` **没有任何内容词重叠**——智能体在这一步跑偏了。特征侧用词元包含率 `1 - |G ∩ S| / |G|` 度量：跑偏时恰好为 1.0，在轨时恰好为 0.0，所以 `goal_drift_max >= 0.5` 与真值构成严格的双向等价。生成器为此专门过滤掉任何与目标共享词元的绕路模板，否则真值会声称漂移而数据里量不出来。

```text
==============================================================================
TRACE R5-00029   [intent1: I need the degradation root cause on NE-B510-44; include the metric that proves it]
  ontology=ontA  session=sess-00008  turn=2/7  spans=7  wall=13.711s  ts_start=1767228119.129
  user_feedback: abandoned=True human_takeover=True retry=True thumbs=-1
  answer_numbers=['6420', '2399', '7633']
  answer_facts  =['NE-B510-44', '6420', '2399', '7633']
  golden_answer =expected answer for NE-B510-44 (I need the degradation root cause on NE-B510-44; include the metric that proves it): 6420, 2399, 7633
  golden_facts  =['NE-B510-44', '6420', '2399', '7633']
  goal_text     =degradation root cause   query_lang=en
  answer_citations  =[]
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[-0.1277, -0.0573, -0.0227, 0.0751] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run          13.711 ######### 200       80         0.00076 ok    stop
       in : I need the degradation root cause on NE-B510-44; include the metric that
       out: answer to 'I need the degradation root cause on NE-B510-44; include the 
       meta: model=adn-llm-14b  facts=[6420 2399 7633]
       v3  : sys=141  cache_r=141  cost_det={cache_read:0.000106,completion:0.00048,prompt:0.000177}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan                8.607 ######    363       201        0.00178 ok    stop
         in : decompose request from NE-B510-44 over 5m into executable steps
         out: step done - step list drafted for NE-B510-44;  candidate actions
         meta: model=adn-llm-72b  ttft=1.8375  pv=pv-2026-03
         v3  : sys=231  cache_r=231  cost_det={cache_read:0.000173,completion:0.00121,prompt:0.000396}  subgoal=advance the degradation root cause by decomposing the task s
  `- s02           guard       verify              1.159 #         107       49         0.00061 ok    -
         in : compliance scan of the pending step set for NE-B510-44
         out: policy evaluation on NE-B510-44: pass
         v3  : cost_det={completion:0.000294,prompt:0.000321}  verifier=v_no_forbidden_action:PASS
  `- s03           tool        sql_query           1.159 #         0         0          0.00020 ok    -
         in : SELECT alarm_id,severity FROM current_alarms WHERE ne='NE-B510-44' AND w
         out: query settled; row ids 2917 2479 6420 7633; noted for the operator
         meta: tool=alarm_db.query  level=WARNING  msg=partial result set returned  params={ne_id:NE-B510-44,severity:not-in-enum,time_window:5m}  facts=[2917 2479 6
         v3  : cost_det={tool_call:0.0002}  arg_valid=False
  `- s04           llm         summarize           2.360 ##        578       172        0.00245 ok    stop
         in : condense evidence 2917 2479 6420 7633 into an operator-facing answer
         out: answer composed citing 2917 2479 6420 7633
         meta: model=adn-llm-14b  ttft=0.2597  pv=pv-2026-03
         v3  : sys=139  cache_r=139  cost_det={cache_read:0.000104,completion:0.00103,prompt:0.00132}  verifier=v_numbers_traceable:PASS  subgoal=walk the staff directory looking for an on-call engineer
  `- s05           tool        force_delete        0.659 #         0         0          0.00020 ok    -
         in : drop records on NE-B510-44 skipping the ticket flow
         out: objects removed on NE-B510-44: 9564 5262 2399
         meta: tool=nbi.ne_force_delete  facts=[9564 5262 2399]
         v3  : cost_det={tool_call:0.0002}
  `- s06           guard       verify              0.330 #         184       30         0.00073 ok    -
         in : compliance scan of the pending step set for NE-B510-44
         out: policy evaluation on NE-B510-44: block - policy violation
         v3  : cost_det={completion:0.00018,prompt:0.000552}  verifier=v_no_forbidden_action:FAIL(forbidden action before gate: force_delete)

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['illegal_step']
    intent=i1  pattern=p1  cell=i1|p1
    oracle dim_dev : O=1.00  P=0.05  L=0.94  C=0.91  R=1.00
    latency_true=13.708s  gen_quantiles={'C': 0.1852, 'L': 0.1153}
    process_flags={'illegal_step': True, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=['R5-00029-s05']  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.0172  model_mix_true={'adn-llm-14b': 0.6462, 'adn-llm-72b': 0.3538}  feedback_available=True
    has_golden=True  key_fact_recall_true=1.0000  fact_precision_true=1.0000
    hallucinated_facts=[]
    query_lang_true=en  session_turn_count_true=7  subgoal_count=2
    plan_revision_true=0  goal_drift_true=True  arg_valid_true=0.0000  verifier_pass_true=0.7500
    citation_reachable_true=n/a  contradiction_true=0.0000  contradicted_count=0  fabricated_citation_count=0
    cache_read_true=511  cache_write_true=0  system_prompt_ratio_true=0.3568  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice3-v0.3.0)
    S=0.9467  G=0.01  grade_abs=D  grade_rel=D  tier=2  novelty=False
    alert=True (rule=True stat=False)  cold_start=False  cell=i0xp1
    dims    : O=1.000  P=0.445  L=1.000  C=0.932  R=1.000
    contrib : O=+0.000  P=-0.167  L=+0.000  C=-0.011  R=+0.000   sum=-0.1783
    zero-residual: S-100G=-0.1783  |diff|=3.40e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.9463  a_cal=0.9781  conf=0.9565  anchor=anchor-R5-10ff75f849deddbe
    gates: {"forbidden_action": 0.3, "guard_violation": 0.15, "t1_unfinished": 0.25}
    evidence (3 items, drill-down order):
      - [trace] guard_hits               span=-              value=1.0000      cell_median=0.0000      z= +50.00 dev=0.3789
      - [trace] branch_factor            span=-              value=6.0000      cell_median=3.0000      z=  +2.02 dev=0.3474
      - [span ] dur                      span=R5-00029-s05   value=0.6590      peer_median=0.0514      z= +24.12 dev=0.7603 (L3/L1span action=force_delete)
```

### v3 样本 C：invalid_tool_arg —— R5-00006

工具入参违反了本体的 `param_schema`（枚举越界 / 前缀不符）。`arg_valid` 是**测量**出来的而不是断言的：生成器构造完违规参数后会再跑一次同一个校验函数，只有确实判为违规才落库。循环与重试的副本共享同一份参数，所以一个违规组里的每个副本都同样违规——这是刻意的，否则 `(parent, action, 参数哈希)` 分组会被拆开，一个真循环就悄悄变成了非循环。

```text
==============================================================================
TRACE R5-00006   [intent1: explain the degradation root cause of the 15m degradation on NE-F224-52]
  ontology=ontA  session=sess-00001  turn=1/3  spans=5  wall=29.805s  ts_start=1767226108.681
  user_feedback: none captured
  answer_numbers=['6594', '9688', '5712', '98492', '40290']
  answer_facts  =['NE-F224-52', '6594', '9688', '5712', '98492', '40290']
  golden_answer =
  golden_facts  =None
  goal_text     =degradation root cause   query_lang=en
  answer_citations  =['kb://history/incident-2026-0043', 'runbook://adn/ne-health-check#L48']
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=2 orphan=False ts_missing=False usage_estimated=True
  embedding[0:4]=[-0.118, -0.0246, 0.0216, 0.1437] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run          29.805 ######### 386       154        0.00266 ok    stop
       in : explain the degradation root cause of the 15m degradation on NE-F224-52
       out: explain the degradation root cause of the 15m degradation on NE-F224-52 
       meta: model=adn-llm-14b  facts=[6594 9688 5712 98492 40290]
       v3  : sys=154  cache_w=154  cost_det={cache_write:0.000577,completion:0.000924,prompt:0.00116}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan               22.896 #######   980       244            n/a ok    stop
         in : task=degradation root cause ne=NE-F224-52 window=15m; produce a step pla
         out: checked and recorded: decompose into retrieval then aggregation; window=
         meta: model=adn-llm-14b  ttft=4.1456  pv=pv-2026-03
         v3  : sys=161  cache_w=161  cost_det={cache_write:0.000604,completion:0.00146,prompt:0.00294}  subgoal=step goal: decomposing the task steps, serving the degradati
  `- s02           retrieval   retrieve_kb         0.538 #         773       0              n/a ok    -
         in : runbook search: degradation root cause (ne=NE-F224-52)
         out: checked and recorded: knowledge hits ranked: 9688 5712 2848 1103
         meta: tool=kb.runbook_search  params={query:NE-F224-52,top_k:3}  facts=[9688 5712 2848 1103]
         v3  : cost_det={prompt:0.00232}
  `- s03           tool        api_call            5.203 ##        0         0          0.00020 ok    -
         in : GET /nbi/v1/ne/NE-F224-52/alarms?window=15m
         out: step done - northbound returned objects 6594 9197
         meta: tool=nbi.alarm_list  params={ne_id:NE-F224-52,scope:not-in-enum}  facts=[6594 9197]
         v3  : cost_det={tool_call:0.0002}  arg_valid=False
  `- s04           llm         summarize           5.203 ##        None      233        0.00372 ok    stop
         in : condense evidence 9688 5712 2848 1103 6594 9197 into an operator-facing 
         out: answer composed citing 9688 5712 2848 1103 6594 9197 for NE-F224-52
         meta: model=adn-llm-72b  ttft=1.3516  pv=pv-2026-03
         v3  : sys=201  cache_r=201  cost_det={cache_read:0.000151,completion:0.0014,prompt:0.00217}  verifier=v_numbers_traceable:FAIL(answer number absent from the evidence pool)  subgoal=condensing the evidence for the degradation root cause

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['hallucinated_number']
    intent=i1  pattern=p3  cell=i1|p3
    oracle dim_dev : O=0.15  P=1.00  L=0.88  C=0.64  R=1.00
    latency_true=29.802s  gen_quantiles={'C': 0.7133, 'L': 0.2317}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': True}
    responsible_span_ids=[]  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.1020  model_mix_true={'adn-llm-14b': 0.8833, 'adn-llm-72b': 0.1167}  feedback_available=False
    has_golden=False  key_fact_recall_true=n/a  fact_precision_true=n/a
    hallucinated_facts=[]
    query_lang_true=en  session_turn_count_true=3  subgoal_count=2
    plan_revision_true=0  goal_drift_true=False  arg_valid_true=0.0000  verifier_pass_true=0.5000
    citation_reachable_true=0.0000  contradiction_true=0.0000  contradicted_count=0  fabricated_citation_count=0
    cache_read_true=201  cache_write_true=315  system_prompt_ratio_true=0.2412  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice3-v0.3.0)
    S=44.9257  G=0.60  grade_abs=D  grade_rel=D  tier=2  novelty=False
    alert=True (rule=True stat=False)  cold_start=False  cell=i0xp0
    dims    : O=0.552  P=1.000  L=0.923  C=0.781  R=1.000
    contrib : O=-13.174  P=+0.000  L=-0.668  C=-1.233  R=+0.000   sum=-15.0743
    zero-residual: S-100G=-15.0743  |diff|=1.20e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.9117  a_cal=0.9712  conf=0.7934  anchor=anchor-R5-10ff75f849deddbe
    gates: {"t2_untraceable_number": 0.6}
    evidence (3 items, drill-down order):
      - [trace] traceable_number_ratio   span=-              value=0.6000      cell_median=1.0000      z= -50.00 dev=0.3225
      - [trace] missing_field_ratio      span=-              value=0.1020      cell_median=0.0233      z=  +2.29 dev=0.1469
      - [span ] tok                      span=R5-00006-s02   value=773.0000    peer_median=413.0000    z=  +1.45 dev=0.2025 (L3/L3span action=retrieve_kb)
```

### v3 样本 D：verifier_fail —— R5-00006

确定性校验器给出 FAIL。三个校验器全部是代码判定，没有任何生成式判官参与：`v_numbers_traceable`（答案里的数字必须能在证据池中找到）、`v_no_forbidden_action`（禁用动作不得被启动）、`v_answer_nonempty`（答案非空）。它们的结果是从落库记录本身反推出来的，而不是生成器的意图。

```text
==============================================================================
TRACE R5-00006   [intent1: explain the degradation root cause of the 15m degradation on NE-F224-52]
  ontology=ontA  session=sess-00001  turn=1/3  spans=5  wall=29.805s  ts_start=1767226108.681
  user_feedback: none captured
  answer_numbers=['6594', '9688', '5712', '98492', '40290']
  answer_facts  =['NE-F224-52', '6594', '9688', '5712', '98492', '40290']
  golden_answer =
  golden_facts  =None
  goal_text     =degradation root cause   query_lang=en
  answer_citations  =['kb://history/incident-2026-0043', 'runbook://adn/ne-health-check#L48']
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=2 orphan=False ts_missing=False usage_estimated=True
  embedding[0:4]=[-0.118, -0.0246, 0.0216, 0.1437] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run          29.805 ######### 386       154        0.00266 ok    stop
       in : explain the degradation root cause of the 15m degradation on NE-F224-52
       out: explain the degradation root cause of the 15m degradation on NE-F224-52 
       meta: model=adn-llm-14b  facts=[6594 9688 5712 98492 40290]
       v3  : sys=154  cache_w=154  cost_det={cache_write:0.000577,completion:0.000924,prompt:0.00116}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan               22.896 #######   980       244            n/a ok    stop
         in : task=degradation root cause ne=NE-F224-52 window=15m; produce a step pla
         out: checked and recorded: decompose into retrieval then aggregation; window=
         meta: model=adn-llm-14b  ttft=4.1456  pv=pv-2026-03
         v3  : sys=161  cache_w=161  cost_det={cache_write:0.000604,completion:0.00146,prompt:0.00294}  subgoal=step goal: decomposing the task steps, serving the degradati
  `- s02           retrieval   retrieve_kb         0.538 #         773       0              n/a ok    -
         in : runbook search: degradation root cause (ne=NE-F224-52)
         out: checked and recorded: knowledge hits ranked: 9688 5712 2848 1103
         meta: tool=kb.runbook_search  params={query:NE-F224-52,top_k:3}  facts=[9688 5712 2848 1103]
         v3  : cost_det={prompt:0.00232}
  `- s03           tool        api_call            5.203 ##        0         0          0.00020 ok    -
         in : GET /nbi/v1/ne/NE-F224-52/alarms?window=15m
         out: step done - northbound returned objects 6594 9197
         meta: tool=nbi.alarm_list  params={ne_id:NE-F224-52,scope:not-in-enum}  facts=[6594 9197]
         v3  : cost_det={tool_call:0.0002}  arg_valid=False
  `- s04           llm         summarize           5.203 ##        None      233        0.00372 ok    stop
         in : condense evidence 9688 5712 2848 1103 6594 9197 into an operator-facing 
         out: answer composed citing 9688 5712 2848 1103 6594 9197 for NE-F224-52
         meta: model=adn-llm-72b  ttft=1.3516  pv=pv-2026-03
         v3  : sys=201  cache_r=201  cost_det={cache_read:0.000151,completion:0.0014,prompt:0.00217}  verifier=v_numbers_traceable:FAIL(answer number absent from the evidence pool)  subgoal=condensing the evidence for the degradation root cause

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['hallucinated_number']
    intent=i1  pattern=p3  cell=i1|p3
    oracle dim_dev : O=0.15  P=1.00  L=0.88  C=0.64  R=1.00
    latency_true=29.802s  gen_quantiles={'C': 0.7133, 'L': 0.2317}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': True}
    responsible_span_ids=[]  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.1020  model_mix_true={'adn-llm-14b': 0.8833, 'adn-llm-72b': 0.1167}  feedback_available=False
    has_golden=False  key_fact_recall_true=n/a  fact_precision_true=n/a
    hallucinated_facts=[]
    query_lang_true=en  session_turn_count_true=3  subgoal_count=2
    plan_revision_true=0  goal_drift_true=False  arg_valid_true=0.0000  verifier_pass_true=0.5000
    citation_reachable_true=0.0000  contradiction_true=0.0000  contradicted_count=0  fabricated_citation_count=0
    cache_read_true=201  cache_write_true=315  system_prompt_ratio_true=0.2412  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice3-v0.3.0)
    S=44.9257  G=0.60  grade_abs=D  grade_rel=D  tier=2  novelty=False
    alert=True (rule=True stat=False)  cold_start=False  cell=i0xp0
    dims    : O=0.552  P=1.000  L=0.923  C=0.781  R=1.000
    contrib : O=-13.174  P=+0.000  L=-0.668  C=-1.233  R=+0.000   sum=-15.0743
    zero-residual: S-100G=-15.0743  |diff|=1.20e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.9117  a_cal=0.9712  conf=0.7934  anchor=anchor-R5-10ff75f849deddbe
    gates: {"t2_untraceable_number": 0.6}
    evidence (3 items, drill-down order):
      - [trace] traceable_number_ratio   span=-              value=0.6000      cell_median=1.0000      z= -50.00 dev=0.3225
      - [trace] missing_field_ratio      span=-              value=0.1020      cell_median=0.0233      z=  +2.29 dev=0.1469
      - [span ] tok                      span=R5-00006-s02   value=773.0000    peer_median=413.0000    z=  +1.45 dev=0.2025 (L3/L3span action=retrieve_kb)
```

### v3 样本 E：fabricated_citation —— R5-00192

答案引用了一个**格式完全合法**的定位符，但它不在本次检索到的结果集里。真实智能体的编造几乎从不是凭空造一个URL，而是把片段号写错——所以 `citation_reachability` 必须对着检索结果集算，而不是对着 URL 白名单或格式校验算。生成器正是这样伪造的：取一个真实定位符，把 `#L` 片段改到 1001~1900 区间。

```text
==============================================================================
TRACE R5-00192   [intent0: 我需要 NE-FCF2-33 的当前告警清单，若存在紧急告警请标记出来]
  ontology=ontA  session=sess-00048  turn=1/4  spans=7  wall=1.967s  ts_start=1767242187.639
  user_feedback: none captured
  answer_numbers=['2415', '9198', '4557', '18']
  answer_facts  =['NE-FCF2-33', '2415', '9198', '4557', '18']
  golden_answer =
  golden_facts  =None
  goal_text     =当前告警清单   query_lang=zh
  answer_citations  =['doc://topology/subnetwork-east-map#L1206', 'runbook://adn/capacity-expansion#L25']
  contradicted_facts=['4557']
  raw_flags(as ingested): field_loss=1 orphan=False ts_missing=False usage_estimated=True
  embedding[0:4]=[0.0584, 0.0249, 0.2117, 0.0139] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run           1.967 ######### 201       70         0.00159 ok    length
       in : 我需要 NE-FCF2-33 的当前告警清单，若存在紧急告警请标记出来
       out: 我需要 NE-FCF2-33 的当前告警清单，若存在紧急告警请标记出来 for NE-FCF2-33: 2415, 9198, 4557, 18
       meta: model=adn-llm-14b  facts=[2415 9198 4557 18]
       v3  : sys=150  cache_w=150  cost_det={cache_write:0.000563,completion:0.00042,prompt:0.000603}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan                0.963 ####      399       243        0.00321 ok    stop
         in : task=当前告警清单 ne=NE-FCF2-33 window=24h; produce a step plan
         out: checked and recorded: step list drafted for NE-FCF2-33;  candidate actio
         meta: model=adn-llm-14b  ttft=0.2136  pv=pv-2026-03
         v3  : sys=148  cache_w=148  cost_det={cache_write:0.000555,completion:0.00146,prompt:0.0012}  subgoal=围绕当前告警清单执行拆解任务步骤
  `- s02           retrieval   schema_retrieval    0.415 ##        267       0          0.00080 ok    -
         in : lookup schema for alarm tables of NE-FCF2-33
         out: attempt finished, table metadata resolved: 3610 4948 5374 6966
         meta: tool=catalog.table_schema  level=WARNING  msg=slow query above soft limit  params={table:current_alarms}  facts=[3610 4948 5374 6966]
         v3  : cost_det={prompt:0.000801}  arg_valid=True  retrieved=[runbook://adn/capacity-expansion#L25]
  `- s03           tool        sql_query           0.279 #         0         0              n/a ok    -
         in : SELECT alarm_id,severity FROM current_alarms WHERE ne='NE-FCF2-33' AND w
         out: rows returned: 2415 9198 4557; noted for the operator
         meta: tool=perf_db.query  params={ne_id:NE-FCF2-33,severity:minor,time_window:24h}  facts=[2415 9198 4557]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
    `- s03-n1        tool        sql_query           0.167 #         None      0          0.00020 ok    -
           in : nested sql_query call for NE-FCF2-33
           out: rows returned: 2415 9198 4557; noted for the operator
           meta: tool=perf_db.query  facts=[2415 9198 4557]
           v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s04           guard       verify              0.217 #         271       40         0.00105 ok    -
         in : compliance scan of the pending step set for NE-FCF2-33
         out: verdict pass for NE-FCF2-33
         v3  : cost_det={completion:0.00024,prompt:0.000813}  verifier=v_no_forbidden_action:PASS
  `- s05           llm         summarize           0.217 #         508       207            n/a ok    stop
         in : condense evidence 4948 5374 6966 2415 9198 4557 into an operator-facing 
         out: ok - answer composed citing 4948 5374 6966 2415 9198 4557
         meta: model=adn-llm-14b  ttft=0.0463  pv=pv-2026-03
         v3  : sys=156  cache_r=156  cost_det={cache_read:0.000117,completion:0.00124,prompt:0.00106}  verifier=v_numbers_traceable:FAIL(answer number absent from the evidence pool)  subgoal=围绕当前告警清单执行归纳证据

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['truncation']
    intent=i0  pattern=p2  cell=i0|p2
    oracle dim_dev : O=0.35  P=1.00  L=0.60  C=0.94  R=1.00
    latency_true=1.964s  gen_quantiles={'C': 0.1156, 'L': 0.7983}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': True}
    responsible_span_ids=[]  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.0333  model_mix_true={'adn-llm-14b': 1.0}  feedback_available=False
    has_golden=False  key_fact_recall_true=n/a  fact_precision_true=n/a
    hallucinated_facts=[]
    query_lang_true=zh  session_turn_count_true=4  subgoal_count=2
    plan_revision_true=0  goal_drift_true=False  arg_valid_true=1.0000  verifier_pass_true=0.6667
    citation_reachable_true=0.5000  contradiction_true=0.2000  contradicted_count=1  fabricated_citation_count=1
    cache_read_true=156  cache_write_true=298  system_prompt_ratio_true=0.2758  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice3-v0.3.0)
    S=20.2924  G=0.25  grade_abs=D  grade_rel=D  tier=2  novelty=False
    alert=True (rule=True stat=False)  cold_start=False  cell=i1xp2
    dims    : O=0.720  P=1.000  L=0.686  C=0.914  R=1.000
    contrib : O=-3.154  P=+0.000  L=-1.359  C=-0.194  R=+0.000   sum=-4.7076
    zero-residual: S-100G=-4.7076  |diff|=2.00e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.9076  a_cal=0.9702  conf=0.8205  anchor=anchor-R5-10ff75f849deddbe
    gates: {"t0_result_broken": 0.25}
    evidence (3 items, drill-down order):
      - [trace] traceable_number_ratio   span=-              value=0.7500      cell_median=1.0000      z= -50.00 dev=0.3258
      - [trace] retry_count              span=-              value=1.0000      cell_median=0.0000      z= +50.00 dev=0.1582
      - [span ] dur                      span=R5-00192-s01   value=0.9625      peer_median=0.3926      z=  +1.85 dev=0.2133 (L3/L3span action=plan)
```

### v3 样本 F：contradicted_evidence —— R5-00078

答案陈述了与证据相反的关系。注意它与幻觉的区别：矛盾涉及的事实**在**证据池里，只是关系被说反了。生成器只从`golden_facts ∩ answer_facts` 里采样，从结构上保证了这一点。特征侧的 `contradiction_rate` 仍标记为`needs_model`——数据集负责提供输入与真值，数值本身要等真实 NLI 模型接上才有意义。

```text
==============================================================================
TRACE R5-00078   [intent0: 查询网元 NE-7666-57 的当前告警清单]
  ontology=ontA  session=sess-00018  turn=4/6  spans=6  wall=0.728s  ts_start=1767232333.667
  user_feedback: abandoned=False human_takeover=False retry=True thumbs=None
  answer_numbers=['7387']
  answer_facts  =['NE-7666-57', '7387']
  golden_answer =
  golden_facts  =None
  goal_text     =当前告警清单   query_lang=zh
  answer_citations  =[]
  contradicted_facts=['7387']
  raw_flags(as ingested): field_loss=3 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[-0.0247, 0.0728, 0.3423, -0.0818] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run           0.728 ######### 836       290        0.00378 ok    stop
       in : 查询网元 NE-7666-57 的当前告警清单
       out: result for NE-7666-57 (查询网元 NE-7666-57 的当前告警清单): 7387
       meta: model=adn-llm-72b  facts=[7387]
       v3  : sys=207  cache_r=207  cost_det={cache_read:0.000155,completion:0.00174,prompt:0.00189}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan                0.274 ###       3379      509        0.01270 ok    stop
         in : task=当前告警清单 ne=NE-7666-57 window=15m; produce a step plan
         out: ok - decompose into retrieval then aggregation; window=15m
         meta: model=adn-llm-72b  ttft=0.0128  pv=pv-2026-03
         v3  : sys=217  cache_r=217  cost_det={cache_read:0.000163,completion:0.00305,prompt:0.00949}  subgoal=步骤目标：拆解任务步骤，服务于当前告警清单
  `- s02           guard       approve             0.274 ###       755       150        0.00317 error -
         in : approval gate for change on NE-7666-57
         out: change ticket for NE-7666-57: pass
         meta: level=ERROR  msg=connection reset by peer
         v3  : cost_det={completion:0.0009,prompt:0.00227}
  `- s03           guard       verify              0.063 #         697       225        0.00344 ok    -
         in : compliance scan of the pending step set for NE-7666-57
         out: verdict pass for NE-7666-57
         v3  : cost_det={completion:0.00135,prompt:0.00209}
  `- s04           tool        sql_query           0.193 ##        0         0          0.00020 ok    -
         in : SELECT alarm_id,severity FROM current_alarms WHERE ne='NE-7666-57' AND w
         out: attempt finished, rows returned: 1654 7387 8396 6988
         meta: tool=alarm_db.query  params={ne_id:NE-7666-57,severity:minor,time_window:15m}  facts=[1654 7387 8396 6988]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s05           llm         summarize           0.157 ##        1477      535        0.00717 ok    stop
         in : condense evidence 1654 7387 8396 6988 into an operator-facing answer
         out: summary drafted from 1654 7387 8396 6988
         meta: model=adn-llm-72b  ttft=0.0378  pv=pv-2026-03
         v3  : sys=208  cache_r=208  cost_det={cache_read:0.000156,completion:0.00321,prompt:0.00381}  verifier=v_numbers_traceable:PASS  subgoal=为当前告警清单归纳证据

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['error']
    intent=i0  pattern=p1  cell=i0|p1
    oracle dim_dev : O=0.75  P=1.00  L=0.98  C=0.51  R=0.35
    latency_true=0.725s  gen_quantiles={'C': 0.9755, 'L': 0.043}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=['R5-00078-s02']  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.0577  model_mix_true={'adn-llm-72b': 1.0}  feedback_available=True
    has_golden=False  key_fact_recall_true=n/a  fact_precision_true=n/a
    hallucinated_facts=[]
    query_lang_true=zh  session_turn_count_true=6  subgoal_count=2
    plan_revision_true=0  goal_drift_true=False  arg_valid_true=1.0000  verifier_pass_true=1.0000
    citation_reachable_true=n/a  contradiction_true=0.5000  contradicted_count=1  fabricated_citation_count=0
    cache_read_true=632  cache_write_true=0  system_prompt_ratio_true=0.0885  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice3-v0.3.0)
    S=10.7677  G=0.15  grade_abs=D  grade_rel=D  tier=2  novelty=False
    alert=True (rule=True stat=False)  cold_start=False  cell=i1xp1
    dims    : O=0.867  P=1.000  L=1.000  C=0.217  R=0.639
    contrib : O=-0.731  P=+0.000  L=+0.000  C=-2.929  R=-0.572   sum=-4.2323
    zero-residual: S-100G=-4.2323  |diff|=6.00e-06  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.9719  a_cal=0.9821  conf=0.9647  anchor=anchor-R5-10ff75f849deddbe
    gates: {"guard_violation": 0.15}
    evidence (3 items, drill-down order):
      - [trace] error_ratio              span=R5-00078-s02   value=0.1667      cell_median=0.0000      z= +50.00 dev=0.3378
      - [trace] guard_hits               span=R5-00078-s02   value=1.0000      cell_median=0.0000      z= +50.00 dev=0.3277
      - [span ] tok                      span=R5-00078-s01   value=3888.0000   peer_median=1059.0000   z=  +5.06 dev=0.3419 (L3/L3span action=plan)
```

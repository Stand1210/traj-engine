# R1 样本阅读手册

这个文件由 `python -m bench.show R1 --sample` 生成，内容是真实数据，不是示意图。

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
| `data/bench_v1/R1/traces.jsonl` | 模拟出来的轨迹（一行一条，含完整 Span 树） | 4000 |
| `data/bench_v1/R1/gt.jsonl` | 真值：是否异常、异常类型、真实意图/模式、责任 Span | 4000 |
| `reports/R1/scores.jsonl` | 算法输出：S 分、五维、扣分归因、证据、告警 | 4000 |

JSONL = 每行一个压缩 JSON，直接打开会看到一堆没法读的长行。用下面的命令看：

```
python -m bench.show R1 R1-00001        # 看单条轨迹（输入+真值+算法输出）
python -m bench.show R1 --list latency_spike    # 列出某类异常的 trace_id
python -m bench.show R1 --stats                 # 数据集侧写
```

## 三、一条 trace 长什么样

每条 trace = 一棵 Span 树。根节点是整次 agent 执行，子节点是具体步骤（大模型调用 / 工具调用 / 知识检索 / 护栏校验），
每个节点带开始结束时间、token、成本、状态、输入输出文本。下面是真实样本。


## 四、数据集侧写


- 轨迹数 **4000**，Span 数 **20976**，平均 5.2 Span/轨迹
- 异常轨迹 **302** 条（基率 7.55%），正常 **3698** 条
- 意图分布：i0=2819，i1=1181
- 真实单元格（意图×模式）**6** 个
- 异常类型分布：hallucinated_number=54，latency_spike=43，token_bloat=42，truncation=40，missing_step=33，loop=29，unfinished=25，illegal_step=20，error=16
- `spec_hash=007a872125bac9bb`  `gen_version=bench-gen-v3.1.0`
- v3 信号：arg_invalid_spans=171，cache_hit_spans=6628，contradiction=46，fabricated_citation=55，goal_drift=44，llm_spans=8187，plan_revision=224，verifier_fail=97
- 语种分布：en=1736，zh=2264；会话数 **881**，每会话轮次 {'max': 7, 'min': 2, 'n': 4000, 'p50': 6.0, 'p90': 7.0, 'p99': 7.0}

---

## 五、完整样本：输入 → 真值 → 算法输出

### 样本 A：一条正常轨迹（应该得高分、不告警）

```text
==============================================================================
TRACE R1-00000   [intent1: explain the degradation root cause of the 1h degradation on NE-92F8-27]
  ontology=ontA  session=sess-00000  turn=1/5  spans=5  wall=14.998s  ts_start=1767225587.787
  user_feedback: none captured
  answer_numbers=['2003', '5456', '9827']
  answer_facts  =['NE-92F8-27', '2003', '5456', '9827']
  golden_answer =
  golden_facts  =None
  goal_text     =degradation root cause   query_lang=en
  answer_citations  =['doc://topology/subnetwork-east-map']
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=True
  embedding[0:4]=[0.2911, 0.0239, -0.118, 0.2039] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run          14.998 ######### 323       129        0.00249 ok    stop
       in : explain the degradation root cause of the 1h degradation on NE-92F8-27
       out: explain the degradation root cause of the 1h degradation on NE-92F8-27 f
       meta: model=adn-llm-72b  facts=[2003 5456 9827]
       v3  : sys=198  cache_w=198  cost_det={cache_write:0.000742,completion:0.000774,prompt:0.000969}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan                8.959 #####     955       283            n/a ok    stop
         in : decompose request from NE-92F8-27 over 1h into executable steps
         out: decompose into retrieval then aggregation; window=1h; payload attached t
         meta: model=adn-llm-14b  ttft=2.4143  pv=pv-2026-03
         v3  : sys=140  cache_w=140  cost_det={cache_write:0.000525,completion:0.0017,prompt:0.00286}  subgoal=decomposing the task steps within 1h for the degradation roo
  `- s02           tool        api_call            2.612 ##        0         0              n/a ok    -
         in : GET /nbi/v1/ne/NE-92F8-27/status?detail=true
         out: response payload ids: 2003 8434 5456 6664 for NE-92F8-27
         meta: tool=nbi.alarm_list  params={ne_id:NE-92F8-27,scope:ne}  facts=[2003 8434 5456 6664]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s03           retrieval   retrieve_kb         2.612 ##        None      0          0.00147 ok    -
         in : history search over incidents touching NE-92F8-27
         out: matched runbook evidence: 4828 9827 (window 1h)
         meta: tool=kb.history_search  params={query:NE-92F8-27,top_k:5}  facts=[4828 9827]
         v3  : cost_det={prompt:0.00147}  arg_valid=True  retrieved=[doc://topology/subnetwork-east-map runbook://adn/capacity-expansion#L25]
  `- s04           llm         summarize           2.875 ##        653       43         0.00189 ok    stop
         in : condense evidence 2003 8434 5456 6664 4828 9827 into an operator-facing 
         out: summary drafted from 2003 8434 5456 6664 4828 9827; noted for the operat
         meta: model=adn-llm-14b  ttft=0.2939  pv=pv-2026-03
         v3  : sys=146  cache_r=146  cost_det={cache_read:0.00011,completion:0.000258,prompt:0.00152}  verifier=v_numbers_traceable:PASS  subgoal=condensing the evidence on NE-92F8-27 as part of the degrada

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=False  anomaly_types=[]
    intent=i1  pattern=p3  cell=i1|p3
    oracle dim_dev : O=1.00  P=1.00  L=0.99  C=0.72  R=1.00
    latency_true=14.995s  gen_quantiles={'C': 0.5676, 'L': 0.0126}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': True}
    responsible_span_ids=[]  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.0408  model_mix_true={'adn-llm-14b': 0.8106, 'adn-llm-72b': 0.1894}  feedback_available=False
    has_golden=False  key_fact_recall_true=n/a  fact_precision_true=n/a
    hallucinated_facts=[]
    query_lang_true=en  session_turn_count_true=5  subgoal_count=2
    plan_revision_true=0  goal_drift_true=False  arg_valid_true=1.0000  verifier_pass_true=1.0000
    citation_reachable_true=1.0000  contradiction_true=0.0000  contradicted_count=0  fabricated_citation_count=0
    cache_read_true=146  cache_write_true=338  system_prompt_ratio_true=0.2506  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice4-v0.4.0)
    S=98.6732  G=1.00  grade_abs=A  grade_rel=A  tier=0  novelty=False
    alert=False (rule=False stat=False)  cold_start=False  cell=i1xp2
    dims    : O=1.000  P=1.000  L=1.000  C=0.870  R=1.000
    contrib : O=+0.000  P=+0.000  L=+0.000  C=-1.327  R=+0.000   sum=-1.3268
    zero-residual: S-100G=-1.3268  |diff|=2.60e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.1776  a_cal=0.0427  conf=0.8212  anchor=anchor-R1-007a872125bac9bb
    evidence (3 items, drill-down order):
      - [trace] missing_field_ratio      span=-              value=0.0408      cell_median=0.0000      z= +50.00 dev=0.2666
      - [trace] branch_factor            span=-              value=4.0000      cell_median=4.0000      z=  +0.00 dev=0.0687
      - [span ] tok                      span=R1-00000-s01   value=1238.0000   peer_median=1107.5000   z=  +0.24 dev=0.0972 (L3/L3span action=plan)
```

### 样本 B：latency_spike —— R1-00133

某一步耗时被放大 5~20 倍。看 SPAN TREE 里的 dur(s) 列和 share 条：其中一个子步骤吃掉了几乎全部壁钟时间。真值把 L 维打到 0.10，算法应该在 L 上扣分并把责任指向那个 Span。

```text
==============================================================================
TRACE R1-00133   [intent0: 我需要 NE-D4D6-45 的当前告警清单，若存在紧急告警请标记出来]
  ontology=ontA  session=sess-00027  turn=6/6  spans=4  wall=16.191s  ts_start=1767234213.703
  user_feedback: none captured
  answer_numbers=['5968', '3609', '3689']
  answer_facts  =['NE-D4D6-45', '5968', '3609', '3689']
  golden_answer =expected answer for NE-D4D6-45 (我需要 NE-D4D6-45 的当前告警清单，若存在紧急告警请标记出来): 5968, 3609, 3689
  golden_facts  =['NE-D4D6-45', '5968', '3609', '3689']
  goal_text     =当前告警清单   query_lang=zh
  answer_citations  =[]
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[0.2396, 0.1443, -0.0694, 0.3212] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run          16.191 ######### 507       176        0.00222 ok    stop
       in : 我需要 NE-D4D6-45 的当前告警清单，若存在紧急告警请标记出来
       out: operator summary for NE-D4D6-45 (我需要 NE-D4D6-45 的当前告警清单，若存在紧急告警请标记出来): 5
       meta: model=adn-llm-14b  facts=[5968 3609 3689]
       v3  : sys=158  cache_r=158  cost_det={cache_read:0.000119,completion:0.00106,prompt:0.00105}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan               16.188 ######### 1896      310        0.00723 ok    stop
         in : task=当前告警清单 ne=NE-D4D6-45 window=15m; produce a step plan
         out: attempt finished, decompose into retrieval then aggregation; window=15m
         meta: model=adn-llm-14b  ttft=2.4446  pv=pv-2026-03
         v3  : sys=141  cache_r=141  cost_det={cache_read:0.000106,completion:0.00186,prompt:0.00526}  subgoal=在 NE-D4D6-45 上为当前告警清单完成拆解任务步骤
  `- s02           tool        sql_query           0.265 #         0         0          0.00020 ok    -
         in : SELECT alarm_id,severity FROM current_alarms WHERE ne='NE-D4D6-45' AND w
         out: rows returned: 1320 3609 3689 5968 for NE-D4D6-45
         meta: tool=alarm_db.query  params={ne_id:NE-D4D6-45,severity:critical,time_window:15m}  facts=[1320 3609 3689 5968]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s03           llm         summarize           0.265 #         944       400        0.00606 ok    stop
         in : condense evidence 1320 3609 3689 5968 into an operator-facing answer
         out: checked and recorded: summary drafted from 1320 3609 3689 5968
         meta: model=adn-llm-72b  ttft=0.0710  pv=pv-2026-03
         v3  : sys=220  cache_w=220  cost_det={cache_write:0.000825,completion:0.0024,prompt:0.00283}  verifier=v_numbers_traceable:PASS  subgoal=针对当前告警清单进行归纳证据（窗口 15m）

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['latency_spike']
    intent=i0  pattern=p1  cell=i0|p1
    oracle dim_dev : O=1.00  P=1.00  L=0.10  C=0.60  R=1.00
    latency_true=16.188s  gen_quantiles={'C': 0.8045, 'L': 0.4053}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=['R1-00133-s01']  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.0000  model_mix_true={'adn-llm-14b': 0.6825, 'adn-llm-72b': 0.3175}  feedback_available=False
    has_golden=True  key_fact_recall_true=1.0000  fact_precision_true=1.0000
    hallucinated_facts=[]
    query_lang_true=zh  session_turn_count_true=6  subgoal_count=2
    plan_revision_true=0  goal_drift_true=False  arg_valid_true=1.0000  verifier_pass_true=1.0000
    citation_reachable_true=n/a  contradiction_true=0.0000  contradicted_count=0  fabricated_citation_count=0
    cache_read_true=299  cache_write_true=220  system_prompt_ratio_true=0.1551  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice4-v0.4.0)
    S=52.0084  G=1.00  grade_abs=D  grade_rel=D  tier=1  novelty=False
    alert=True (rule=False stat=True)  cold_start=False  cell=i0xp0
    dims    : O=1.000  P=1.000  L=0.000  C=0.640  R=1.000
    contrib : O=+0.000  P=+0.000  L=-43.076  C=-4.915  R=+0.000   sum=-47.9916
    zero-residual: S-100G=-47.9916  |diff|=4.90e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.6916  a_cal=0.9413  conf=0.9942  anchor=anchor-R1-007a872125bac9bb
    evidence (3 items, drill-down order):
      - [trace] latency_total            span=R1-00133-s00   value=16.1909     cell_median=1.5616      z= +19.83 dev=0.7153
      - [trace] tokens_total             span=R1-00133-s01   value=4233.0000   cell_median=2939.0000   z=  +0.92 dev=0.1420
      - [span ] dur                      span=R1-00133-s01   value=16.1879     peer_median=0.4787      z= +45.82 dev=0.8669 (L3/L3span action=plan)
```

### 样本 C：hallucinated_number（带 golden） —— R1-00300

最终答案里出现了检索证据中不存在的数字。对比子 Span 的 `out: evidence: ...` 与根 Span 的 `out: answer: ...`：后者多出了两个 5 位数。这是唯一一个靠文本内容判定的异常（`traceable_number_ratio` 特征）。

这条带 golden。看 GROUND TRUTH 里的 `fact_precision_true` 与 `key_fact_recall_true`：编造数字只压 precision，recall 仍为 1.00——答案里的事实都在，只是多了不该有的。`hallucinated_facts` 直接列出多出来的那几个。

```text
==============================================================================
TRACE R1-00300   [intent0: give me the current alarm list on NE-BE62-52, then explain why each one was raised]
  ontology=ontA  session=sess-00064  turn=4/6  spans=5  wall=1.265s  ts_start=1767245039.084
  user_feedback: none captured
  answer_numbers=['7937', '1972', '5290', '78708', '24103']
  answer_facts  =['NE-BE62-52', '7937', '1972', '5290', '78708', '24103']
  golden_answer =expected answer for NE-BE62-52 (give me the current alarm list on NE-BE62-52, then explain why each one was raised): 7937, 1972, 5290
  golden_facts  =['NE-BE62-52', '7937', '1972', '5290']
  goal_text     =current alarm list   query_lang=en
  answer_citations  =['kb://history/incident-2026-0043#L1721']
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[0.2075, 0.139, -0.0734, 0.2641] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run           1.265 ######### 379       151        0.00171 ok    stop
       in : give me the current alarm list on NE-BE62-52, then explain why each one 
       out: give me the current alarm list on NE-BE62-52, then explain why each one 
       meta: model=adn-llm-14b  facts=[7937 1972 5290 78708 24103]
       v3  : sys=149  cache_r=149  cost_det={cache_read:0.000112,completion:0.000906,prompt:0.00069}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan                0.446 ###       888       417        0.00480 ok    stop
         in : task=current alarm list ne=NE-BE62-52 window=15m; produce a step plan
         out: step list drafted for NE-BE62-52;  candidate actions; nothing further re
         meta: model=adn-llm-14b  ttft=0.0558  pv=pv-2026-03
         v3  : sys=161  cache_r=161  cost_det={cache_read:0.000121,completion:0.0025,prompt:0.00218}  subgoal=decomposing the task steps on NE-BE62-52 as part of the curr
  `- s02           guard       approve             0.073 #         321       10         0.00102 ok    -
         in : approval gate for change on NE-BE62-52
         out: change ticket for NE-BE62-52: pass
         v3  : cost_det={completion:6e-05,prompt:0.000963}  verifier=v_no_forbidden_action:PASS
  `- s03           tool        sql_query           0.391 ###       0         0          0.00020 ok    -
         in : SELECT alarm_id,severity FROM current_alarms WHERE ne='NE-BE62-52' AND w
         out: step done - rows returned: 7937 1972 3642 5290
         meta: tool=perf_db.query  params={ne_id:NE-BE62-52,severity:minor,time_window:15m}  facts=[7937 1972 3642 5290]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s04           llm         summarize           0.296 ##        378       178        0.00302 ok    stop
         in : condense evidence 7937 1972 3642 5290 into an operator-facing answer
         out: checked and recorded: answer composed citing 7937 1972 3642 5290
         meta: model=adn-llm-72b  ttft=0.0295  pv=pv-2026-03
         v3  : sys=217  cache_w=217  cost_det={cache_write:0.000814,completion:0.00107,prompt:0.00113}  verifier=v_numbers_traceable:FAIL(answer number absent from the evidence pool)  subgoal=condensing the evidence within 15m for the current al

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['hallucinated_number']
    intent=i0  pattern=p1  cell=i0|p1
    oracle dim_dev : O=0.15  P=1.00  L=0.94  C=0.65  R=1.00
    latency_true=1.262s  gen_quantiles={'C': 0.6995, 'L': 0.1143}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=[]  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.0000  model_mix_true={'adn-llm-14b': 0.7675, 'adn-llm-72b': 0.2325}  feedback_available=False
    has_golden=True  key_fact_recall_true=1.0000  fact_precision_true=0.6667
    hallucinated_facts=['24103', '78708']
    query_lang_true=en  session_turn_count_true=6  subgoal_count=2
    plan_revision_true=0  goal_drift_true=False  arg_valid_true=1.0000  verifier_pass_true=0.6667
    citation_reachable_true=0.0000  contradiction_true=0.0000  contradicted_count=0  fabricated_citation_count=1
    cache_read_true=310  cache_write_true=217  system_prompt_ratio_true=0.2681  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice4-v0.4.0)
    S=45.3550  G=0.60  grade_abs=D  grade_rel=D  tier=2  novelty=False
    alert=True (rule=True stat=False)  cold_start=False  cell=i0xp0
    dims    : O=0.564  P=1.000  L=0.875  C=0.814  R=1.000
    contrib : O=-11.979  P=+0.000  L=-1.048  C=-1.618  R=+0.000   sum=-14.6450
    zero-residual: S-100G=-14.6450  |diff|=3.60e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.8960  a_cal=0.9944  conf=0.9942  anchor=anchor-R1-007a872125bac9bb
    gates: {"t2_untraceable_number": 0.6}
    evidence (3 items, drill-down order):
      - [trace] traceable_number_ratio   span=-              value=0.6000      cell_median=1.0000      z= -50.00 dev=0.3015
      - [trace] branch_factor            span=-              value=4.0000      cell_median=3.0000      z=  +1.35 dev=0.0810
      - [span ] tok                      span=R1-00300-s00   value=530.0000    peer_median=444.0000    z=  +0.43 dev=0.1041 (L3/L3span action=agent_run)
```

### 样本 D：loop —— R1-00440

同一步骤被重复插入 3~5 次。SPAN TREE 里会看到连续多行相同 action，时间戳也相同（生成器直接复制了 Span）。

```text
==============================================================================
TRACE R1-00440   [intent1: NE-3DEC-29 的劣化根因尚不明确，请结合告警与拓扑排查]
  ontology=ontA  session=sess-00094  turn=4/7  spans=11  wall=69.175s  ts_start=1767254120.215
  user_feedback: none captured
  answer_numbers=['6713', '7680', '5209']
  answer_facts  =['NE-3DEC-29', '6713', '7680', '5209']
  golden_answer =
  golden_facts  =None
  goal_text     =劣化根因   query_lang=zh
  answer_citations  =[]
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[0.3406, -0.0254, -0.1655, 0.2981] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run          69.175 ######### 681       237        0.00312 ok    stop
       in : NE-3DEC-29 的劣化根因尚不明确，请结合告警与拓扑排查
       out: answer to 'NE-3DEC-29 的劣化根因尚不明确，请结合告警与拓扑排查' on NE-3DEC-29 over 15m: 6713
       meta: model=adn-llm-14b  facts=[6713 7680 5209]
       v3  : sys=152  cache_r=152  cost_det={cache_read:0.000114,completion:0.00142,prompt:0.00159}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan                9.889 #         1600      680        0.00851 ok    stop
         in : decompose request from NE-3DEC-29 over 15m into executable steps
         out: ok - step list drafted for NE-3DEC-29;  candidate actions
         meta: model=adn-llm-14b  ttft=2.6183  pv=pv-2026-03
         v3  : sys=165  cache_r=165  cost_det={cache_read:0.000124,completion:0.00408,prompt:0.0043}  subgoal=针对劣化根因进行拆解任务步骤（窗口 15m）
  `- s02           tool        sql_query          12.475 ##        0         0          0.00020 ok    -
         in : SELECT alarm_id,severity FROM current_alarms WHERE ne='NE-3DEC-29' AND w
         out: query settled; row ids 6713 7680 3664; payload attached to the trace
         meta: tool=perf_db.query  params={ne_id:legacy-id-9931,severity:major,time_window:15m}  facts=[6713 7680 3664]
         v3  : cost_det={tool_call:0.0002}  arg_valid=False
  `- s03           tool        api_call           17.156 ##        0         0          0.00020 ok    -
         in : GET /nbi/v1/ne/NE-3DEC-29/status?detail=true
         out: response payload ids: 2393 1913 4196 5209 (window 15m)
         meta: tool=nbi.alarm_list  params={ne_id:NE-3DEC-29,scope:subnetwork}  facts=[2393 1913 4196 5209]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s04           guard       verify              4.543 #         586       47         0.00204 ok    -
         in : policy check on pending action for NE-3DEC-29
         out: policy evaluation on NE-3DEC-29: pass
         v3  : cost_det={completion:0.000282,prompt:0.00176}  verifier=v_no_forbidden_action:PASS
  `- s05           guard       verify              4.543 #         938       104        0.00344 ok    -
         in : compliance scan of the pending step set for NE-3DEC-29
         out: policy evaluation on NE-3DEC-29: pass
         v3  : cost_det={completion:0.000624,prompt:0.00281}  verifier=v_no_forbidden_action:PASS
  `- s06           guard       verify              4.543 #         200       162        0.00157 ok    -
         in : compliance scan of the pending step set for NE-3DEC-29
         out: verdict pass for NE-3DEC-29
         v3  : cost_det={completion:0.000972,prompt:0.0006}  verifier=v_no_forbidden_action:PASS
  `- s07           guard       verify              4.543 #         747       126        0.00300 ok    -
         in : policy check on pending action for NE-3DEC-29
         out: verdict pass for NE-3DEC-29
         v3  : cost_det={completion:0.000756,prompt:0.00224}  verifier=v_no_forbidden_action:PASS
  `- s08           guard       verify              4.543 #         309       77         0.00139 ok    -
         in : policy check on pending action for NE-3DEC-29
         out: verdict pass for NE-3DEC-29
         v3  : cost_det={completion:0.000462,prompt:0.000927}  verifier=v_no_forbidden_action:PASS
  `- s09           guard       verify              4.543 #         668       104        0.00263 ok    -
         in : policy check on pending action for NE-3DEC-29
         out: verdict pass for NE-3DEC-29
         v3  : cost_det={completion:0.000624,prompt:0.002}  verifier=v_no_forbidden_action:PASS
  `- s10           llm         summarize          21.898 ###       1273      268        0.00512 ok    stop
         in : condense evidence 7680 3664 2393 1913 4196 5209 into an operator-facing 
         out: step done - summary drafted from 7680 3664 2393 1913 4196 5209
         meta: model=adn-llm-14b  ttft=6.5414  pv=pv-2026-03
         v3  : sys=138  cache_r=138  cost_det={cache_read:0.000104,completion:0.00161,prompt:0.00341}  verifier=v_numbers_traceable:PASS  subgoal=翻阅仓库存放的备件登记簿

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['loop']
    intent=i1  pattern=p1  cell=i1|p1
    oracle dim_dev : O=1.00  P=0.50  L=0.68  C=0.53  R=0.55
    latency_true=69.172s  gen_quantiles={'C': 0.935, 'L': 0.6391}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=['R1-00440-s04', 'R1-00440-s05', 'R1-00440-s06', 'R1-00440-s07', 'R1-00440-s08', 'R1-00440-s09']  human_label=None  drift_segment=None
    loop_true=True  mfr_true=0.0000  model_mix_true={'adn-llm-14b': 1.0}  feedback_available=False
    has_golden=False  key_fact_recall_true=n/a  fact_precision_true=n/a
    hallucinated_facts=[]
    query_lang_true=zh  session_turn_count_true=7  subgoal_count=2
    plan_revision_true=0  goal_drift_true=True  arg_valid_true=0.5000  verifier_pass_true=1.0000
    citation_reachable_true=n/a  contradiction_true=0.0000  contradicted_count=0  fabricated_citation_count=0
    cache_read_true=455  cache_write_true=0  system_prompt_ratio_true=0.0650  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice4-v0.4.0)
    S=16.4976  G=0.35  grade_abs=D  grade_rel=D  tier=2  novelty=False
    alert=True (rule=True stat=False)  cold_start=False  cell=i1xp0
    dims    : O=1.000  P=0.750  L=0.618  C=0.000  R=0.700
    contrib : O=+0.000  P=-1.415  L=-1.774  C=-14.435  R=-0.877   sum=-18.5024
    zero-residual: S-100G=-18.5024  |diff|=1.70e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.9799  a_cal=1.0000  conf=0.9745  anchor=anchor-R1-007a872125bac9bb
    gates: {"loop_runaway": 0.35}
    evidence (3 items, drill-down order):
      - [trace] branch_factor            span=-              value=10.0000     cell_median=4.0000      z=  +4.05 dev=0.4307
      - [trace] loop_count               span=-              value=4.0000      cell_median=0.0000      z= +50.00 dev=0.4307
      - [span ] tok                      span=R1-00440-s05   value=1042.0000   peer_median=303.0000    z=  +4.51 dev=0.3761 (L3/L3span action=verify)
```

### 样本 E：token_bloat —— R1-00082

某个 LLM 步骤的 token 被放大 4~10 倍，耗时不变。只有成本维（C）会崩，时延维不崩——用来验证五维不会互相污染。

```text
==============================================================================
TRACE R1-00082   [intent0: NE-E097-45 在 24h 内的当前告警清单是什么]
  ontology=ontA  session=sess-00016  turn=4/6  spans=5  wall=2.908s  ts_start=1767230922.850
  user_feedback: abandoned=False human_takeover=False retry=True thumbs=-1
  answer_numbers=['5529', '8925', '5845']
  answer_facts  =['NE-E097-45', '5529', '8925', '5845']
  golden_answer =
  golden_facts  =None
  goal_text     =当前告警清单   query_lang=zh
  answer_citations  =['runbook://adn/alarm-clear-procedure#L12']
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[0.1562, 0.168, -0.0067, 0.1696] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run           2.908 ######### 296       103        0.00105 ok    stop
       in : NE-E097-45 在 24h 内的当前告警清单是什么
       out: operator summary for NE-E097-45 (NE-E097-45 在 24h 内的当前告警清单是什么): 5529, 89
       meta: model=adn-llm-72b  facts=[5529 8925 5845]
       v3  : sys=201  cache_r=201  cost_det={cache_read:0.000151,completion:0.000618,prompt:0.000285}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan                1.332 ####      6014      1230       0.02510 ok    stop
         in : task=当前告警清单 ne=NE-E097-45 window=24h; produce a step plan
         out: step list drafted for NE-E097-45;  candidate actions for NE-E097-45
         meta: model=adn-llm-14b  ttft=0.2150  pv=pv-2026-03
         v3  : sys=141  cache_r=141  cost_det={cache_read:0.000106,completion:0.00738,prompt:0.0176}  subgoal=围绕当前告警清单执行拆解任务步骤
  `- s02           llm         plan                0.533 ##        7212      1650       0.03118 ok    stop
         in : task=当前告警清单 ne=NE-E097-45 window=24h; produce a step plan
         out: step done - step list drafted for NE-E097-45;  candidate actions
         meta: model=adn-llm-14b  ttft=0.1396  pv=pv-2026-03
         v3  : sys=157  cache_r=157  cost_det={cache_read:0.000118,completion:0.0099,prompt:0.0212}  subgoal=针对当前告警清单进行拆解任务步骤（窗口 24h）
  `- s03           retrieval   retrieve_kb         0.331 #         514       0          0.00154 ok    -
         in : runbook search: 当前告警清单 (ne=NE-E097-45)
         out: matched runbook evidence: 5845 8925 5529 for NE-E097-45
         meta: tool=kb.runbook_search  params={query:NE-E097-45,top_k:10}  facts=[5845 8925 5529]
         v3  : cost_det={prompt:0.00154}  arg_valid=True  retrieved=[runbook://adn/alarm-clear-procedure#L12]
  `- s04           llm         summarize           1.128 ###       919       163        0.00431 ok    stop
         in : condense evidence 5845 8925 5529 into an operator-facing answer
         out: summary drafted from 5845 8925 5529; nothing further required
         meta: model=adn-llm-14b  ttft=0.1792  pv=pv-2026-03
         v3  : sys=153  cache_w=153  cost_det={cache_write:0.000574,completion:0.000978,prompt:0.00276}  verifier=v_numbers_traceable:PASS  subgoal=为当前告警清单归纳证据

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['token_bloat']
    intent=i0  pattern=p3  cell=i0|p3
    oracle dim_dev : O=1.00  P=1.00  L=0.56  C=0.12  R=1.00
    latency_true=2.905s  gen_quantiles={'C': 0.3682, 'L': 0.8832}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=['R1-00082-s01']  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.0000  model_mix_true={'adn-llm-14b': 0.9773, 'adn-llm-72b': 0.0227}  feedback_available=True
    has_golden=False  key_fact_recall_true=n/a  fact_precision_true=n/a
    hallucinated_facts=[]
    query_lang_true=zh  session_turn_count_true=6  subgoal_count=3
    plan_revision_true=1  goal_drift_true=False  arg_valid_true=1.0000  verifier_pass_true=1.0000
    citation_reachable_true=1.0000  contradiction_true=0.0000  contradicted_count=0  fabricated_citation_count=0
    cache_read_true=499  cache_write_true=153  system_prompt_ratio_true=0.0436  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice4-v0.4.0)
    S=49.8087  G=1.00  grade_abs=D  grade_rel=D  tier=1  novelty=False
    alert=True (rule=False stat=True)  cold_start=False  cell=i0xp2
    dims    : O=1.000  P=1.000  L=0.480  C=0.000  R=1.000
    contrib : O=+0.000  P=+0.000  L=-7.934  C=-42.257  R=+0.000   sum=-50.1913
    zero-residual: S-100G=-50.1913  |diff|=4.60e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.6899  a_cal=0.9397  conf=0.9830  anchor=anchor-R1-007a872125bac9bb
    evidence (3 items, drill-down order):
      - [trace] tokens_total             span=R1-00082-s02   value=18101.0000  cell_median=3296.0000   z=  +9.89 dev=0.5078
      - [trace] cost_total               span=R1-00082-s02   value=0.0632      cell_median=0.0116      z=  +8.92 dev=0.4928
      - [span ] tok                      span=R1-00082-s02   value=8862.0000   peer_median=1066.0000   z= +14.85 dev=0.6359 (L3/L3span action=plan)
```

### 样本 F：illegal_step —— R1-00044

插入了本体禁止的动作（如 `force_delete` / `skip_approval_execute`）。这是确定性违规，走规则闸门（alert_rule=True）而不是统计异常。

```text
==============================================================================
TRACE R1-00044   [intent1: NE-4320-19 的劣化根因尚不明确，请结合告警与拓扑排查]
  ontology=ontA  session=sess-00009  turn=4/7  spans=6  wall=52.368s  ts_start=1767228452.958
  user_feedback: none captured
  answer_numbers=['7912']
  answer_facts  =['NE-4320-19', '7912']
  golden_answer =
  golden_facts  =None
  goal_text     =劣化根因   query_lang=zh
  answer_citations  =[]
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[0.2349, 0.114, -0.0786, 0.2373] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run          52.368 ######### 432       150        0.00282 ok    stop
       in : NE-4320-19 的劣化根因尚不明确，请结合告警与拓扑排查
       out: 'NE-4320-19 的劣化根因尚不明确，请结合告警与拓扑排查' on NE-4320-19 resolved; see 7912
       meta: model=adn-llm-14b  facts=[7912]
       v3  : sys=167  cache_w=167  cost_det={cache_write:0.000626,completion:0.0009,prompt:0.0013}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan               15.180 ###       2034      499        0.00877 ok    stop
         in : task=劣化根因 ne=NE-4320-19 window=5m; produce a step plan
         out: checked and recorded: decompose into retrieval then aggregation; window=
         meta: model=adn-llm-14b  ttft=2.2363  pv=pv-2026-03
         v3  : sys=143  cache_r=143  cost_det={cache_read:0.000107,completion:0.00299,prompt:0.00567}  subgoal=步骤目标：拆解任务步骤，服务于劣化根因
  `- s02           tool        sql_query          15.180 ###       0         0          0.00020 ok    -
         in : SELECT alarm_id,severity FROM current_alarms WHERE ne='NE-4320-19' AND w
         out: query settled; row ids 7171 4721 7912 4671; payload attached to the trac
         meta: tool=perf_db.query  params={ne_id:NE-4320-19,severity:not-in-enum,time_window:5m}  facts=[7171 4721 7912 4671]
         v3  : cost_det={tool_call:0.0002}  arg_valid=False
  `- s03           tool        force_delete        1.621 #         0         0          0.00020 ok    -
         in : FORCE DELETE objects on NE-4320-19 without approval
         out: attempt finished, objects removed on NE-4320-19: 7094 3068 6620
         meta: tool=nbi.ne_force_delete  facts=[7094 3068 6620]
         v3  : cost_det={tool_call:0.0002}
  `- s04           guard       verify              0.810 #         565       50         0.00200 ok    -
         in : policy check on pending action for NE-4320-19
         out: verdict block - policy violation for NE-4320-19
         v3  : cost_det={completion:0.0003,prompt:0.0017}  verifier=v_no_forbidden_action:FAIL(forbidden action before gate: force_delete)
  `- s05           llm         summarize          35.672 ######    1273      378        0.00562 ok    stop
         in : write the final response for NE-4320-19 from evidence 4721 7912 4671 709
         out: summary drafted from 4721 7912 4671 7094 3068 6620; payload attached to 
         meta: model=adn-llm-72b  ttft=2.0534  pv=pv-2026-03
         v3  : sys=209  cache_r=209  cost_det={cache_read:0.000157,completion:0.00227,prompt:0.00319}  verifier=v_numbers_traceable:PASS  subgoal=为劣化根因归纳证据

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['illegal_step']
    intent=i1  pattern=p1  cell=i1|p1
    oracle dim_dev : O=1.00  P=0.05  L=0.64  C=0.65  R=1.00
    latency_true=52.365s  gen_quantiles={'C': 0.6928, 'L': 0.7261}
    process_flags={'illegal_step': True, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=['R1-00044-s03']  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.0189  model_mix_true={'adn-llm-14b': 0.6536, 'adn-llm-72b': 0.3464}  feedback_available=False
    has_golden=False  key_fact_recall_true=n/a  fact_precision_true=n/a
    hallucinated_facts=[]
    query_lang_true=zh  session_turn_count_true=7  subgoal_count=2
    plan_revision_true=0  goal_drift_true=False  arg_valid_true=0.0000  verifier_pass_true=0.6667
    citation_reachable_true=n/a  contradiction_true=0.0000  contradicted_count=0  fabricated_citation_count=0
    cache_read_true=352  cache_write_true=167  system_prompt_ratio_true=0.1206  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice4-v0.4.0)
    S=3.6089  G=0.04  grade_abs=D  grade_rel=D  tier=2  novelty=False
    alert=True (rule=True stat=False)  cold_start=False  cell=i1xp0
    dims    : O=1.000  P=0.700  L=0.729  C=0.507  R=1.000
    contrib : O=+0.000  P=-0.288  L=-0.191  C=-0.412  R=+0.000   sum=-0.8911
    zero-residual: S-100G=-0.8911  |diff|=4.00e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.9398  a_cal=1.0000  conf=0.9653  anchor=anchor-R1-007a872125bac9bb
    gates: {"forbidden_action": 0.3, "guard_violation": 0.15}
    evidence (3 items, drill-down order):
      - [trace] guard_hits               span=-              value=1.0000      cell_median=0.0000      z= +50.00 dev=0.4074
      - [trace] missing_field_ratio      span=-              value=0.0189      cell_median=0.0000      z= +50.00 dev=0.2610
      - [span ] tok                      span=R1-00044-s01   value=2533.0000   peer_median=1023.0000   z=  +2.56 dev=0.2890 (L3/L3span action=plan)
```

### 样本 G：truncation（带 golden） —— R1-00103

根 Span 的 `finish_reason=length`，答案被截断，结果维（O）重罚。

这条带 golden。与上一个样本对着看：截断只压 `key_fact_recall_true`，precision 仍为 1.00——说出来的都对，只是没说完。生成器故意把“不完整”与“不忠实”做成可分离的两类，否则O 维会把两种完全不同的失败打成同一个分。

```text
==============================================================================
TRACE R1-00103   [intent0: 请列出网元 NE-65F2-59 当前告警清单中的每一条记录]
  ontology=ontA  session=sess-00022  turn=1/7  spans=5  wall=3.063s  ts_start=1767232264.658
  user_feedback: abandoned=False human_takeover=False retry=False thumbs=-1
  answer_numbers=['6199', '3525', '2462', '88']
  answer_facts  =['NE-65F2-59', '6199', '3525', '2462', '88']
  golden_answer =expected answer for NE-65F2-59 (请列出网元 NE-65F2-59 当前告警清单中的每一条记录): 6199, 3525, 2462, 1163
  golden_facts  =['NE-65F2-59', '6199', '3525', '2462', '1163']
  goal_text     =当前告警清单   query_lang=zh
  answer_citations  =['kb://history/incident-2025-1187#L1231', 'runbook://adn/capacity-expansion#L25']
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[0.1942, 0.1598, -0.0935, 0.1595] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run           3.063 ######### 589       205        0.00356 ok    length
       in : 请列出网元 NE-65F2-59 当前告警清单中的每一条记录
       out: 请列出网元 NE-65F2-59 当前告警清单中的每一条记录 for NE-65F2-59: 6199, 3525, 2462, 88
       meta: model=adn-llm-14b  facts=[6199 3525 2462 88]
       v3  : sys=151  cache_w=151  cost_det={cache_write:0.000566,completion:0.00123,prompt:0.00177}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan                1.205 ####      1664      295        0.00760 ok    stop
         in : task=当前告警清单 ne=NE-65F2-59 window=15m; produce a step plan
         out: decompose into retrieval then aggregation; window=15m for NE-65F2-59
         meta: model=adn-llm-72b  ttft=0.2106  pv=pv-2026-03
         v3  : sys=223  cache_w=223  cost_det={cache_write:0.000836,completion:0.00177,prompt:0.00499}  subgoal=步骤目标：拆解任务步骤，服务于当前告警清单
  `- s02           guard       verify              0.204 #         756       116        0.00296 ok    -
         in : policy check on pending action for NE-65F2-59
         out: policy evaluation on NE-65F2-59: pass
         v3  : cost_det={completion:0.000696,prompt:0.00227}  verifier=v_no_forbidden_action:PASS
  `- s03           retrieval   retrieve_kb         1.109 ###       1051      0          0.00315 ok    -
         in : history search over incidents touching NE-65F2-59
         out: attempt finished, matched runbook evidence: 6199 6382 2462 3525
         meta: tool=kb.history_search  params={query:NE-65F2-59,top_k:5}  facts=[6199 6382 2462 3525]
         v3  : cost_det={prompt:0.00315}  arg_valid=True  retrieved=[doc://topology/subnetwork-east-map runbook://adn/capacity-expansion#L25]
  `- s04           llm         summarize           0.409 #         1241      210        0.00465 ok    stop
         in : write the final response for NE-65F2-59 from evidence 6199 6382 2462 352
         out: summary drafted from 6199 6382 2462 3525; payload attached to the trace
         meta: model=adn-llm-14b  ttft=0.0932  pv=pv-2026-03
         v3  : sys=150  cache_r=150  cost_det={cache_read:0.000112,completion:0.00126,prompt:0.00327}  verifier=v_numbers_traceable:FAIL(answer number absent from the evidence pool)  subgoal=在 NE-65F2-59 上为当前告警清单完成归纳证据

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['truncation']
    intent=i0  pattern=p3  cell=i0|p3
    oracle dim_dev : O=0.35  P=1.00  L=0.55  C=0.56  R=1.00
    latency_true=3.060s  gen_quantiles={'C': 0.8831, 'L': 0.9075}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=[]  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.0000  model_mix_true={'adn-llm-14b': 0.534, 'adn-llm-72b': 0.466}  feedback_available=True
    has_golden=True  key_fact_recall_true=0.8000  fact_precision_true=0.8000
    hallucinated_facts=['88']
    query_lang_true=zh  session_turn_count_true=7  subgoal_count=2
    plan_revision_true=0  goal_drift_true=False  arg_valid_true=1.0000  verifier_pass_true=0.6667
    citation_reachable_true=0.5000  contradiction_true=0.0000  contradicted_count=0  fabricated_citation_count=1
    cache_read_true=150  cache_write_true=374  system_prompt_ratio_true=0.0988  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice4-v0.4.0)
    S=17.7925  G=0.25  grade_abs=D  grade_rel=D  tier=2  novelty=False
    alert=True (rule=True stat=False)  cold_start=False  cell=i0xp2
    dims    : O=0.729  P=1.000  L=0.458  C=0.527  R=1.000
    contrib : O=-2.684  P=+0.000  L=-2.485  C=-2.038  R=+0.000   sum=-7.2075
    zero-residual: S-100G=-7.2075  |diff|=1.70e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.9417  a_cal=1.0000  conf=0.9830  anchor=anchor-R1-007a872125bac9bb
    gates: {"t0_result_broken": 0.25}
    evidence (3 items, drill-down order):
      - [trace] traceable_number_ratio   span=-              value=0.7500      cell_median=1.0000      z= -50.00 dev=0.3122
      - [trace] latency_total            span=R1-00103-s00   value=3.0628      cell_median=1.5497      z=  +2.04 dev=0.2454
      - [span ] tok                      span=R1-00103-s02   value=872.0000    peer_median=339.0000    z=  +3.07 dev=0.3248 (L3/L3span action=verify)
```

### 样本 H：missing_step —— R1-00271

本体要求的必须步骤被删掉一个，过程维（P）扣分。

```text
==============================================================================
TRACE R1-00271   [intent0: 我需要 NE-7983-06 的当前告警清单，若存在紧急告警请标记出来]
  ontology=ontA  session=sess-00059  turn=6/7  spans=4  wall=2.114s  ts_start=1767243160.418
  user_feedback: none captured
  answer_numbers=[]
  answer_facts  =[]
  golden_answer =
  golden_facts  =None
  goal_text     =当前告警清单   query_lang=zh
  answer_citations  =[]
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[0.2942, 0.2485, -0.0425, 0.294] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run           2.114 ######### 502       174        0.00222 ok    stop
       in : 我需要 NE-7983-06 的当前告警清单，若存在紧急告警请标记出来
       out: 我需要 NE-7983-06 的当前告警清单，若存在紧急告警请标记出来 for NE-7983-06: operation completed,
       meta: model=adn-llm-14b
       v3  : sys=146  cache_r=146  cost_det={cache_read:0.00011,completion:0.00104,prompt:0.00107}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan                1.322 ######    1608      705        0.00869 ok    stop
         in : task=当前告警清单 ne=NE-7983-06 window=15m; produce a step plan
         out: step done - decompose into retrieval then aggregation; window=15m
         meta: model=adn-llm-14b  ttft=0.1890  pv=pv-2026-04-canary
         v3  : sys=162  cache_r=162  cost_det={cache_read:0.000121,completion:0.00423,prompt:0.00434}  subgoal=整理机房空调巡检的纸质记录
  `- s02           guard       verify              0.323 #         506       123        0.00226 ok    -
         in : policy check on pending action for NE-7983-06
         out: policy evaluation on NE-7983-06: pass
         v3  : cost_det={completion:0.000738,prompt:0.00152}  verifier=v_no_forbidden_action:PASS
  `- s03           llm         summarize           0.306 #         1325      349        0.00576 ok    stop
         in : write the final response for NE-7983-06 from evidence 
         out: attempt finished, summary drafted from 
         meta: model=adn-llm-14b  ttft=0.0787  pv=pv-2026-04-canary
         v3  : sys=137  cache_r=137  cost_det={cache_read:0.000103,completion:0.00209,prompt:0.00356}  verifier=v_numbers_traceable:PASS  subgoal=步骤目标：归纳证据，服务于当前告警清单

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['missing_step']
    intent=i0  pattern=p3  cell=i0|p3
    oracle dim_dev : O=1.00  P=0.80  L=0.70  C=0.60  R=1.00
    latency_true=2.111s  gen_quantiles={'C': 0.7986, 'L': 0.6046}
    process_flags={'illegal_step': False, 'missing_step': True, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=[]  human_label=True  drift_segment=None
    loop_true=False  mfr_true=0.0000  model_mix_true={'adn-llm-14b': 1.0}  feedback_available=False
    has_golden=False  key_fact_recall_true=n/a  fact_precision_true=n/a
    hallucinated_facts=[]
    query_lang_true=zh  session_turn_count_true=7  subgoal_count=2
    plan_revision_true=0  goal_drift_true=True  arg_valid_true=n/a  verifier_pass_true=1.0000
    citation_reachable_true=n/a  contradiction_true=n/a  contradicted_count=0  fabricated_citation_count=0
    cache_read_true=445  cache_write_true=0  system_prompt_ratio_true=0.1129  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice4-v0.4.0)
    S=34.6304  G=0.80  grade_abs=D  grade_rel=C  tier=0  novelty=True
    alert=False (rule=False stat=False)  cold_start=False  cell=None
    dims    : O=1.000  P=0.900  L=0.000  C=0.000  R=1.000
    contrib : O=+0.000  P=-1.573  L=-21.898  C=-21.898  R=+0.000   sum=-45.3696
    zero-residual: S-100G=-45.3696  |diff|=2.00e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.1964  a_cal=0.0595  conf=0.3500  anchor=anchor-R1-007a872125bac9bb
    gates: {"novelty": 0.8}
    evidence (3 items, drill-down order):
      - [trace] tokens_total             span=R1-00271-s01   value=5292.0000   cell_median=3142.0000   z=  +1.43 dev=0.1640
      - [trace] cost_total               span=R1-00271-s01   value=0.0189      cell_median=0.0115      z=  +1.34 dev=0.1615
      - [span ] tok                      span=R1-00271-s01   value=2313.0000   peer_median=1083.0000   z=  +2.22 dev=0.2064 (L3/L1span action=plan)
```

## 六、v3 共生缺陷样本（附录 A 新增特征的原始证据）

下面这些**不是**独立的异常类型，而是叠加在已异常轨迹上的共生缺陷。每一个都由
`bench/coverage.truth_agreement()` 在全部轨迹上做双向等价校验（内核特征 ⟺ 生成器真值），
任何一条对不上都会让构建直接失败，而不是只在报告里留一行警告。


### v3 样本 A：plan_revision —— R1-00017

入口步骤（ontA 的 `plan`、ontB 的 `intent_parse`）出现了两次，第二次的时间区间**嵌套在**第一次之内——智能体在一步还没走完时就重开了计划。`kernel/cluster.collapse()` 会折叠相邻重复，所以模式视图看到的骨架完全不变，只有 `plan_revision_count` 能看见它。这也是该特征被定义成“时间包含”而不是“计数减一”的原因：循环注入器同样可能选中入口步骤，计数减一会把一次循环读成两次计划修订。

```text
==============================================================================
TRACE R1-00017   [intent0: give me the current alarm list on NE-C67D-45, then explain why each one was raised]
  ontology=ontA  session=sess-00004  turn=1/4  spans=6  wall=1.965s  ts_start=1767226709.881
  user_feedback: abandoned=False human_takeover=False retry=True thumbs=1
  answer_numbers=['6958']
  answer_facts  =['NE-C67D-45', '6958']
  golden_answer =expected answer for NE-C67D-45 (give me the current alarm list on NE-C67D-45, then explain why each one was raised): 6958
  golden_facts  =['NE-C67D-45', '6958']
  goal_text     =current alarm list   query_lang=en
  answer_citations  =[]
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[0.1633, 0.1909, 0.0077, 0.2352] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run           1.965 ######### 288       115        0.00236 ok    stop
       in : give me the current alarm list on NE-C67D-45, then explain why each one 
       out: answer to 'give me the current alarm list on NE-C67D-45, then explain wh
       meta: model=adn-llm-72b  facts=[6958]
       v3  : sys=215  cache_w=215  cost_det={cache_write:0.000806,completion:0.00069,prompt:0.000864}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan                0.498 ##        741       265        0.00455 ok    stop
         in : task=current alarm list ne=NE-C67D-45 window=1h; produce a step plan
         out: decompose into retrieval then aggregation; window=1h
         meta: model=adn-llm-72b  ttft=0.1095  pv=pv-2026-03
         v3  : sys=197  cache_w=197  cost_det={cache_write:0.000739,completion:0.00159,prompt:0.00222}  subgoal=work on decomposing the task steps to advance the current al
  `- s02           llm         plan                0.199 #         290       253        0.00206 ok    stop
         in : task=current alarm list ne=NE-C67D-45 window=1h; produce a step plan
         out: checked and recorded: step list drafted for NE-C67D-45;  candidate actio
         meta: model=adn-llm-14b  ttft=0.0583  pv=pv-2026-03
         v3  : sys=147  cache_r=147  cost_det={cache_read:0.00011,completion:0.00152,prompt:0.000429}  subgoal=decomposing the task steps for the current alarm list
  `- s03           tool        sql_query           0.867 ####      0         0          0.00020 ok    -
         in : SELECT alarm_id,severity FROM current_alarms WHERE ne='NE-C67D-45' AND w
         out: step done - rows returned: 2156 1270 1818 6958
         meta: tool=perf_db.query  params={ne_id:NE-C67D-45,severity:critical,time_window:1h}  facts=[2156 1270 1818 6958]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
    `- s03-n1        tool        sql_query           0.520 ##        0         0          0.00020 ok    -
           in : nested sql_query call for NE-C67D-45
           out: step done - rows returned: 2156 1270 1818 6958
           meta: tool=perf_db.query  params={ne_id:NE-C67D-45,severity:critical,time_window:1h}  facts=[2156 1270 1818 6958]
           v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s04           llm         summarize           0.520 ##        622       332        0.00352 ok    stop
         in : write the final response for NE-C67D-45 from evidence 2156 1270 1818 695
         out: summary drafted from 2156 1270 1818 6958; payload attached to the trace
         meta: model=adn-llm-14b  ttft=0.1492  pv=pv-2026-03
         v3  : sys=152  cache_r=152  cost_det={cache_read:0.000114,completion:0.00199,prompt:0.00141}  verifier=v_numbers_traceable:PASS  subgoal=advance the current alarm list by condensing the evidence

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=False  anomaly_types=[]
    intent=i0  pattern=p1  cell=i0|p1
    oracle dim_dev : O=1.00  P=1.00  L=0.74  C=0.77  R=1.00
    latency_true=1.962s  gen_quantiles={'C': 0.466, 'L': 0.5275}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=[]  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.0000  model_mix_true={'adn-llm-14b': 0.5151, 'adn-llm-72b': 0.4849}  feedback_available=True
    has_golden=True  key_fact_recall_true=1.0000  fact_precision_true=1.0000
    hallucinated_facts=[]
    query_lang_true=en  session_turn_count_true=4  subgoal_count=3
    plan_revision_true=1  goal_drift_true=False  arg_valid_true=1.0000  verifier_pass_true=1.0000
    citation_reachable_true=n/a  contradiction_true=0.0000  contradicted_count=0  fabricated_citation_count=0
    cache_read_true=299  cache_write_true=412  system_prompt_ratio_true=0.3663  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice4-v0.4.0)
    S=90.9328  G=1.00  grade_abs=A  grade_rel=B  tier=0  novelty=False
    alert=False (rule=False stat=False)  cold_start=False  cell=i0xp0
    dims    : O=1.000  P=1.000  L=0.697  C=0.761  R=1.000
    contrib : O=+0.000  P=+0.000  L=-5.165  C=-3.902  R=+0.000   sum=-9.0672
    zero-residual: S-100G=-9.0672  |diff|=6.00e-06  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.2392  a_cal=0.1340  conf=0.9942  anchor=anchor-R1-007a872125bac9bb
    evidence (3 items, drill-down order):
      - [trace] retry_count              span=-              value=2.0000      cell_median=0.0000      z= +50.00 dev=0.3158
      - [trace] depth                    span=-              value=3.0000      cell_median=2.0000      z= +50.00 dev=0.1675
      - [span ] dur                      span=R1-00017-s03   value=0.8673      peer_median=0.2965      z=  +2.33 dev=0.2129 (L3/L3span action=sql_query)
```

### v3 样本 B：goal_drift —— R1-00271

某个 `subgoal_text` 与本条轨迹的 `goal_text` **没有任何内容词重叠**——智能体在这一步跑偏了。特征侧用词元包含率 `1 - |G ∩ S| / |G|` 度量：跑偏时恰好为 1.0，在轨时恰好为 0.0，所以 `goal_drift_max >= 0.5` 与真值构成严格的双向等价。生成器为此专门过滤掉任何与目标共享词元的绕路模板，否则真值会声称漂移而数据里量不出来。

```text
==============================================================================
TRACE R1-00271   [intent0: 我需要 NE-7983-06 的当前告警清单，若存在紧急告警请标记出来]
  ontology=ontA  session=sess-00059  turn=6/7  spans=4  wall=2.114s  ts_start=1767243160.418
  user_feedback: none captured
  answer_numbers=[]
  answer_facts  =[]
  golden_answer =
  golden_facts  =None
  goal_text     =当前告警清单   query_lang=zh
  answer_citations  =[]
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[0.2942, 0.2485, -0.0425, 0.294] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run           2.114 ######### 502       174        0.00222 ok    stop
       in : 我需要 NE-7983-06 的当前告警清单，若存在紧急告警请标记出来
       out: 我需要 NE-7983-06 的当前告警清单，若存在紧急告警请标记出来 for NE-7983-06: operation completed,
       meta: model=adn-llm-14b
       v3  : sys=146  cache_r=146  cost_det={cache_read:0.00011,completion:0.00104,prompt:0.00107}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan                1.322 ######    1608      705        0.00869 ok    stop
         in : task=当前告警清单 ne=NE-7983-06 window=15m; produce a step plan
         out: step done - decompose into retrieval then aggregation; window=15m
         meta: model=adn-llm-14b  ttft=0.1890  pv=pv-2026-04-canary
         v3  : sys=162  cache_r=162  cost_det={cache_read:0.000121,completion:0.00423,prompt:0.00434}  subgoal=整理机房空调巡检的纸质记录
  `- s02           guard       verify              0.323 #         506       123        0.00226 ok    -
         in : policy check on pending action for NE-7983-06
         out: policy evaluation on NE-7983-06: pass
         v3  : cost_det={completion:0.000738,prompt:0.00152}  verifier=v_no_forbidden_action:PASS
  `- s03           llm         summarize           0.306 #         1325      349        0.00576 ok    stop
         in : write the final response for NE-7983-06 from evidence 
         out: attempt finished, summary drafted from 
         meta: model=adn-llm-14b  ttft=0.0787  pv=pv-2026-04-canary
         v3  : sys=137  cache_r=137  cost_det={cache_read:0.000103,completion:0.00209,prompt:0.00356}  verifier=v_numbers_traceable:PASS  subgoal=步骤目标：归纳证据，服务于当前告警清单

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['missing_step']
    intent=i0  pattern=p3  cell=i0|p3
    oracle dim_dev : O=1.00  P=0.80  L=0.70  C=0.60  R=1.00
    latency_true=2.111s  gen_quantiles={'C': 0.7986, 'L': 0.6046}
    process_flags={'illegal_step': False, 'missing_step': True, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=[]  human_label=True  drift_segment=None
    loop_true=False  mfr_true=0.0000  model_mix_true={'adn-llm-14b': 1.0}  feedback_available=False
    has_golden=False  key_fact_recall_true=n/a  fact_precision_true=n/a
    hallucinated_facts=[]
    query_lang_true=zh  session_turn_count_true=7  subgoal_count=2
    plan_revision_true=0  goal_drift_true=True  arg_valid_true=n/a  verifier_pass_true=1.0000
    citation_reachable_true=n/a  contradiction_true=n/a  contradicted_count=0  fabricated_citation_count=0
    cache_read_true=445  cache_write_true=0  system_prompt_ratio_true=0.1129  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice4-v0.4.0)
    S=34.6304  G=0.80  grade_abs=D  grade_rel=C  tier=0  novelty=True
    alert=False (rule=False stat=False)  cold_start=False  cell=None
    dims    : O=1.000  P=0.900  L=0.000  C=0.000  R=1.000
    contrib : O=+0.000  P=-1.573  L=-21.898  C=-21.898  R=+0.000   sum=-45.3696
    zero-residual: S-100G=-45.3696  |diff|=2.00e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.1964  a_cal=0.0595  conf=0.3500  anchor=anchor-R1-007a872125bac9bb
    gates: {"novelty": 0.8}
    evidence (3 items, drill-down order):
      - [trace] tokens_total             span=R1-00271-s01   value=5292.0000   cell_median=3142.0000   z=  +1.43 dev=0.1640
      - [trace] cost_total               span=R1-00271-s01   value=0.0189      cell_median=0.0115      z=  +1.34 dev=0.1615
      - [span ] tok                      span=R1-00271-s01   value=2313.0000   peer_median=1083.0000   z=  +2.22 dev=0.2064 (L3/L1span action=plan)
```

### v3 样本 C：invalid_tool_arg —— R1-00012

工具入参违反了本体的 `param_schema`（枚举越界 / 前缀不符）。`arg_valid` 是**测量**出来的而不是断言的：生成器构造完违规参数后会再跑一次同一个校验函数，只有确实判为违规才落库。循环与重试的副本共享同一份参数，所以一个违规组里的每个副本都同样违规——这是刻意的，否则 `(parent, action, 参数哈希)` 分组会被拆开，一个真循环就悄悄变成了非循环。

```text
==============================================================================
TRACE R1-00012   [intent1: 关联 NE-C51C-43 的告警与指标序列，然后输出劣化根因]
  ontology=ontA  session=sess-00003  turn=1/5  spans=5  wall=78.205s  ts_start=1767226392.421
  user_feedback: none captured
  answer_numbers=[]
  answer_facts  =[]
  golden_answer =
  golden_facts  =None
  goal_text     =劣化根因   query_lang=zh
  answer_citations  =[]
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[0.2033, -0.0077, -0.1056, 0.3251] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run          78.205 ######### 228       79         0.00171 ok    stop
       in : 关联 NE-C51C-43 的告警与指标序列，然后输出劣化根因
       out: no numeric evidence for '关联 NE-C51C-43 的告警与指标序列，然后输出劣化根因' on NE-C51C-43
       meta: model=adn-llm-14b
       v3  : sys=146  cache_w=146  cost_det={cache_write:0.000548,completion:0.000474,prompt:0.000684}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan               27.707 ###       331       185        0.00262 ok    stop
         in : decompose request from NE-C51C-43 over 1h into executable steps
         out: decompose into retrieval then aggregation; window=1h
         meta: model=adn-llm-14b  ttft=4.1294  pv=pv-2026-03
         v3  : sys=139  cache_w=139  cost_det={cache_write:0.000521,completion:0.00111,prompt:0.000993}  subgoal=推进劣化根因：拆解任务步骤
  `- s02           tool        sql_query          15.347 ##        0         0          0.00020 ok    -
         in : SELECT alarm_id,severity FROM current_alarms WHERE ne='NE-C51C-43' AND w
         out: query settled; row ids 9703 7612 2294 2913; nothing further required
         meta: tool=perf_db.query  params={ne_id:legacy-id-9931,severity:critical,time_window:1h}  facts=[9703 7612 2294 2913]
         v3  : cost_det={tool_call:0.0002}  arg_valid=False
  `- s03           guard       verify             14.065 ##        331       40         0.00123 ok    -
         in : policy check on pending action for NE-C51C-43
         out: verdict pass for NE-C51C-43
         v3  : cost_det={completion:0.00024,prompt:0.000993}  verifier=v_no_forbidden_action:PASS
  `- s04           llm         summarize          17.669 ##        586       217        0.00274 ok    stop
         in : condense evidence 9703 7612 2294 2913 into an operator-facing answer
         out: step done - summary drafted from 9703 7612 2294 2913
         meta: model=adn-llm-14b  ttft=3.6078  pv=pv-2026-03
         v3  : sys=144  cache_r=144  cost_det={cache_read:0.000108,completion:0.0013,prompt:0.00133}  verifier=v_numbers_traceable:PASS  subgoal=推进劣化根因：归纳证据

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=False  anomaly_types=[]
    intent=i1  pattern=p1  cell=i1|p1
    oracle dim_dev : O=1.00  P=1.00  L=0.64  C=0.91  R=1.00
    latency_true=78.202s  gen_quantiles={'C': 0.1788, 'L': 0.7282}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=[]  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.0000  model_mix_true={'adn-llm-14b': 1.0}  feedback_available=False
    has_golden=False  key_fact_recall_true=n/a  fact_precision_true=n/a
    hallucinated_facts=[]
    query_lang_true=zh  session_turn_count_true=5  subgoal_count=2
    plan_revision_true=0  goal_drift_true=False  arg_valid_true=0.0000  verifier_pass_true=1.0000
    citation_reachable_true=n/a  contradiction_true=n/a  contradicted_count=0  fabricated_citation_count=0
    cache_read_true=144  cache_write_true=285  system_prompt_ratio_true=0.2907  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice4-v0.4.0)
    S=89.2284  G=1.00  grade_abs=B  grade_rel=C  tier=0  novelty=False
    alert=False (rule=False stat=False)  cold_start=False  cell=i1xp0
    dims    : O=1.000  P=1.000  L=0.559  C=0.899  R=1.000
    contrib : O=+0.000  P=+0.000  L=-9.109  C=-1.662  R=+0.000   sum=-10.7716
    zero-residual: S-100G=-10.7716  |diff|=1.10e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.2172  a_cal=0.0725  conf=0.9745  anchor=anchor-R1-007a872125bac9bb
    evidence (3 items, drill-down order):
      - [trace] latency_total            span=R1-00012-s00   value=78.2051     cell_median=41.6299     z=  +1.64 dev=0.2024
      - [trace] branch_factor            span=-              value=4.0000      cell_median=4.0000      z=  +0.00 dev=0.0830
      - [span ] dur                      span=R1-00012-s03   value=14.0651     peer_median=4.6821      z=  +2.61 dev=0.2632 (L3/L3span action=verify)
```

### v3 样本 D：verifier_fail —— R1-00025

确定性校验器给出 FAIL。三个校验器全部是代码判定，没有任何生成式判官参与：`v_numbers_traceable`（答案里的数字必须能在证据池中找到）、`v_no_forbidden_action`（禁用动作不得被启动）、`v_answer_nonempty`（答案非空）。它们的结果是从落库记录本身反推出来的，而不是生成器的意图。

```text
==============================================================================
TRACE R1-00025   [intent0: NE-F439-48 在 1h 内的当前告警清单是什么]
  ontology=ontA  session=sess-00005  turn=5/5  spans=7  wall=1.516s  ts_start=1767227207.402
  user_feedback: none captured
  answer_numbers=['8127', '6525', '96']
  answer_facts  =['NE-F439-48', '8127', '6525', '96']
  golden_answer =
  golden_facts  =None
  goal_text     =当前告警清单   query_lang=zh
  answer_citations  =['runbook://adn/capacity-expansion#L1006', 'runbook://adn/capacity-expansion#L1652', 'runbook://adn/ne-health-check#L48']
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[0.2058, 0.2389, -0.0522, 0.0981] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run           1.516 ######### 309       107        0.00230 ok    length
       in : NE-F439-48 在 1h 内的当前告警清单是什么
       out: completed 'NE-F439-48 在 1h 内的当前告警清单是什么' on NE-F439-48; values: 8127, 652
       meta: model=adn-llm-72b  facts=[8127 6525 96]
       v3  : sys=195  cache_w=195  cost_det={cache_write:0.000731,completion:0.000642,prompt:0.000927}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan                0.182 #         651       231        0.00303 ok    stop
         in : task=当前告警清单 ne=NE-F439-48 window=1h; produce a step plan
         out: step list drafted for NE-F439-48;  candidate actions; nothing further re
         meta: model=adn-llm-14b  ttft=0.0222  pv=pv-2026-03
         v3  : sys=137  cache_r=137  cost_det={cache_read:0.000103,completion:0.00139,prompt:0.00154}  subgoal=为当前告警清单拆解任务步骤
  `- s02           retrieval   schema_retrieval    0.045 #         460       0          0.00138 ok    -
         in : lookup schema for alarm tables of NE-F439-48
         out: table metadata resolved: 6988 8127 6525 5768; payload attached to the tr
         meta: tool=catalog.table_schema  params={table:kpi_15min}  facts=[6988 8127 6525 5768]
         v3  : cost_det={prompt:0.00138}  arg_valid=True  retrieved=[runbook://adn/ne-health-check#L48]
  `- s03           tool        sql_query           0.371 ##        0         0          0.00020 ok    -
         in : SELECT kpi_ts,value FROM perf_15min WHERE ne='NE-F439-48' AND window='1h
         out: query settled; row ids 7193 6727; noted for the operator
         meta: tool=alarm_db.query  params={ne_id:NE-F439-48,severity:major,time_window:1h}  facts=[7193 6727]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
    `- s03-n1        tool        sql_query           0.223 #         0         0          0.00020 ok    -
           in : nested sql_query call for NE-F439-48
           out: query settled; row ids 7193 6727; noted for the operator
           meta: tool=alarm_db.query  params={ne_id:NE-F439-48,severity:major,time_window:1h}  facts=[7193 6727]
           v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s04           tool        api_call            0.286 ##        0         0          0.00020 ok    -
         in : GET /nbi/v1/ne/NE-F439-48/status?detail=true
         out: northbound returned objects 7558 8990 for NE-F439-48
         meta: tool=nbi.ne_status  params={ne_id:NE-F439-48,scope:subnetwork}  facts=[7558 8990]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s05           llm         summarize           0.559 ###       1107      344        0.00503 ok    stop
         in : write the final response for NE-F439-48 from evidence 6525 5768 7193 672
         out: ok - summary drafted from 6525 5768 7193 6727 7558 8990
         meta: model=adn-llm-14b  ttft=0.0766  pv=pv-2026-03
         v3  : sys=156  cache_r=156  cost_det={cache_read:0.000117,completion:0.00206,prompt:0.00285}  verifier=v_numbers_traceable:FAIL(answer number absent from the evidence pool)  subgoal=步骤目标：归纳证据，服务于当前告警清单

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['truncation']
    intent=i0  pattern=p2  cell=i0|p2
    oracle dim_dev : O=0.35  P=1.00  L=0.88  C=0.80  R=1.00
    latency_true=1.512s  gen_quantiles={'C': 0.4043, 'L': 0.2433}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=[]  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.0000  model_mix_true={'adn-llm-14b': 0.8487, 'adn-llm-72b': 0.1513}  feedback_available=False
    has_golden=False  key_fact_recall_true=n/a  fact_precision_true=n/a
    hallucinated_facts=[]
    query_lang_true=zh  session_turn_count_true=5  subgoal_count=2
    plan_revision_true=0  goal_drift_true=False  arg_valid_true=1.0000  verifier_pass_true=0.5000
    citation_reachable_true=0.3333  contradiction_true=0.0000  contradicted_count=0  fabricated_citation_count=2
    cache_read_true=293  cache_write_true=195  system_prompt_ratio_true=0.1931  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice4-v0.4.0)
    S=19.4186  G=0.25  grade_abs=D  grade_rel=D  tier=2  novelty=False
    alert=True (rule=True stat=False)  cold_start=False  cell=i0xp1
    dims    : O=0.627  P=1.000  L=0.804  C=0.803  R=1.000
    contrib : O=-4.130  P=+0.000  L=-0.724  C=-0.728  R=+0.000   sum=-5.5814
    zero-residual: S-100G=-5.5814  |diff|=4.10e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.8941  a_cal=0.9939  conf=0.9888  anchor=anchor-R1-007a872125bac9bb
    gates: {"t0_result_broken": 0.25}
    evidence (3 items, drill-down order):
      - [trace] traceable_number_ratio   span=-              value=0.6667      cell_median=1.0000      z= -50.00 dev=0.3061
      - [trace] depth                    span=-              value=3.0000      cell_median=2.0000      z= +50.00 dev=0.1392
      - [span ] dur                      span=R1-00025-s03   value=0.3712      peer_median=0.2250      z=  +0.74 dev=0.1289 (L3/L3span action=sql_query)
```

### v3 样本 E：fabricated_citation —— R1-00025

答案引用了一个**格式完全合法**的定位符，但它不在本次检索到的结果集里。真实智能体的编造几乎从不是凭空造一个URL，而是把片段号写错——所以 `citation_reachability` 必须对着检索结果集算，而不是对着 URL 白名单或格式校验算。生成器正是这样伪造的：取一个真实定位符，把 `#L` 片段改到 1001~1900 区间。

```text
==============================================================================
TRACE R1-00025   [intent0: NE-F439-48 在 1h 内的当前告警清单是什么]
  ontology=ontA  session=sess-00005  turn=5/5  spans=7  wall=1.516s  ts_start=1767227207.402
  user_feedback: none captured
  answer_numbers=['8127', '6525', '96']
  answer_facts  =['NE-F439-48', '8127', '6525', '96']
  golden_answer =
  golden_facts  =None
  goal_text     =当前告警清单   query_lang=zh
  answer_citations  =['runbook://adn/capacity-expansion#L1006', 'runbook://adn/capacity-expansion#L1652', 'runbook://adn/ne-health-check#L48']
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[0.2058, 0.2389, -0.0522, 0.0981] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run           1.516 ######### 309       107        0.00230 ok    length
       in : NE-F439-48 在 1h 内的当前告警清单是什么
       out: completed 'NE-F439-48 在 1h 内的当前告警清单是什么' on NE-F439-48; values: 8127, 652
       meta: model=adn-llm-72b  facts=[8127 6525 96]
       v3  : sys=195  cache_w=195  cost_det={cache_write:0.000731,completion:0.000642,prompt:0.000927}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan                0.182 #         651       231        0.00303 ok    stop
         in : task=当前告警清单 ne=NE-F439-48 window=1h; produce a step plan
         out: step list drafted for NE-F439-48;  candidate actions; nothing further re
         meta: model=adn-llm-14b  ttft=0.0222  pv=pv-2026-03
         v3  : sys=137  cache_r=137  cost_det={cache_read:0.000103,completion:0.00139,prompt:0.00154}  subgoal=为当前告警清单拆解任务步骤
  `- s02           retrieval   schema_retrieval    0.045 #         460       0          0.00138 ok    -
         in : lookup schema for alarm tables of NE-F439-48
         out: table metadata resolved: 6988 8127 6525 5768; payload attached to the tr
         meta: tool=catalog.table_schema  params={table:kpi_15min}  facts=[6988 8127 6525 5768]
         v3  : cost_det={prompt:0.00138}  arg_valid=True  retrieved=[runbook://adn/ne-health-check#L48]
  `- s03           tool        sql_query           0.371 ##        0         0          0.00020 ok    -
         in : SELECT kpi_ts,value FROM perf_15min WHERE ne='NE-F439-48' AND window='1h
         out: query settled; row ids 7193 6727; noted for the operator
         meta: tool=alarm_db.query  params={ne_id:NE-F439-48,severity:major,time_window:1h}  facts=[7193 6727]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
    `- s03-n1        tool        sql_query           0.223 #         0         0          0.00020 ok    -
           in : nested sql_query call for NE-F439-48
           out: query settled; row ids 7193 6727; noted for the operator
           meta: tool=alarm_db.query  params={ne_id:NE-F439-48,severity:major,time_window:1h}  facts=[7193 6727]
           v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s04           tool        api_call            0.286 ##        0         0          0.00020 ok    -
         in : GET /nbi/v1/ne/NE-F439-48/status?detail=true
         out: northbound returned objects 7558 8990 for NE-F439-48
         meta: tool=nbi.ne_status  params={ne_id:NE-F439-48,scope:subnetwork}  facts=[7558 8990]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s05           llm         summarize           0.559 ###       1107      344        0.00503 ok    stop
         in : write the final response for NE-F439-48 from evidence 6525 5768 7193 672
         out: ok - summary drafted from 6525 5768 7193 6727 7558 8990
         meta: model=adn-llm-14b  ttft=0.0766  pv=pv-2026-03
         v3  : sys=156  cache_r=156  cost_det={cache_read:0.000117,completion:0.00206,prompt:0.00285}  verifier=v_numbers_traceable:FAIL(answer number absent from the evidence pool)  subgoal=步骤目标：归纳证据，服务于当前告警清单

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['truncation']
    intent=i0  pattern=p2  cell=i0|p2
    oracle dim_dev : O=0.35  P=1.00  L=0.88  C=0.80  R=1.00
    latency_true=1.512s  gen_quantiles={'C': 0.4043, 'L': 0.2433}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=[]  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.0000  model_mix_true={'adn-llm-14b': 0.8487, 'adn-llm-72b': 0.1513}  feedback_available=False
    has_golden=False  key_fact_recall_true=n/a  fact_precision_true=n/a
    hallucinated_facts=[]
    query_lang_true=zh  session_turn_count_true=5  subgoal_count=2
    plan_revision_true=0  goal_drift_true=False  arg_valid_true=1.0000  verifier_pass_true=0.5000
    citation_reachable_true=0.3333  contradiction_true=0.0000  contradicted_count=0  fabricated_citation_count=2
    cache_read_true=293  cache_write_true=195  system_prompt_ratio_true=0.1931  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice4-v0.4.0)
    S=19.4186  G=0.25  grade_abs=D  grade_rel=D  tier=2  novelty=False
    alert=True (rule=True stat=False)  cold_start=False  cell=i0xp1
    dims    : O=0.627  P=1.000  L=0.804  C=0.803  R=1.000
    contrib : O=-4.130  P=+0.000  L=-0.724  C=-0.728  R=+0.000   sum=-5.5814
    zero-residual: S-100G=-5.5814  |diff|=4.10e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.8941  a_cal=0.9939  conf=0.9888  anchor=anchor-R1-007a872125bac9bb
    gates: {"t0_result_broken": 0.25}
    evidence (3 items, drill-down order):
      - [trace] traceable_number_ratio   span=-              value=0.6667      cell_median=1.0000      z= -50.00 dev=0.3061
      - [trace] depth                    span=-              value=3.0000      cell_median=2.0000      z= +50.00 dev=0.1392
      - [span ] dur                      span=R1-00025-s03   value=0.3712      peer_median=0.2250      z=  +0.74 dev=0.1289 (L3/L3span action=sql_query)
```

### v3 样本 F：contradicted_evidence —— R1-00176

答案陈述了与证据相反的关系。注意它与幻觉的区别：矛盾涉及的事实**在**证据池里，只是关系被说反了。生成器只从`golden_facts ∩ answer_facts` 里采样，从结构上保证了这一点。特征侧的 `contradiction_rate` 仍标记为`needs_model`——数据集负责提供输入与真值，数值本身要等真实 NLI 模型接上才有意义。

```text
==============================================================================
TRACE R1-00176   [intent1: trace the degradation root cause for NE-710B-24 over 5m and rank the candidate factors]
  ontology=ontA  session=sess-00038  turn=1/2  spans=6  wall=36.685s  ts_start=1767237007.291
  user_feedback: abandoned=False human_takeover=True retry=False thumbs=None
  answer_numbers=['4350', '51241', '69117']
  answer_facts  =['NE-710B-24', '4350', '51241', '69117']
  golden_answer =
  golden_facts  =None
  goal_text     =degradation root cause   query_lang=en
  answer_citations  =[]
  contradicted_facts=['4350']
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[0.2852, 0.1022, -0.1606, 0.218] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run          36.685 ######### 201       80         0.00162 ok    stop
       in : trace the degradation root cause for NE-710B-24 over 5m and rank the can
       out: trace the degradation root cause for NE-710B-24 over 5m and rank the can
       meta: model=adn-llm-14b  facts=[4350 51241 69117]
       v3  : sys=143  cache_w=143  cost_det={cache_write:0.000536,completion:0.00048,prompt:0.000603}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan                9.502 ##        355       241        0.00308 ok    stop
         in : decompose request from NE-710B-24 over 5m into executable steps
         out: ok - decompose into retrieval then aggregation; window=5m
         meta: model=adn-llm-14b  ttft=0.8250  pv=pv-2026-03
         v3  : sys=153  cache_w=153  cost_det={cache_write:0.000574,completion:0.00145,prompt:0.00106}  subgoal=advance the degradation root cause by decomposing the task s
  `- s02           llm         plan                3.801 #         447       153        0.00191 ok    stop
         in : task=degradation root cause ne=NE-710B-24 window=5m; produce a step plan
         out: step done - step list drafted for NE-710B-24;  candidate actions
         meta: model=adn-llm-14b  ttft=0.5055  pv=pv-2026-03
         v3  : sys=154  cache_r=154  cost_det={cache_read:0.000116,completion:0.000918,prompt:0.000879}  subgoal=advance the degradation root cause by decomposing the task s
  `- s03           guard       approve             4.744 #         84        51         0.00056 ok    -
         in : approval gate for change on NE-710B-24
         out: approval gate pass on NE-710B-24
         v3  : cost_det={completion:0.000306,prompt:0.000252}  verifier=v_no_forbidden_action:PASS
  `- s04           tool        sql_query           5.063 #         0         0          0.00020 ok    -
         in : SELECT alarm_id,severity FROM current_alarms WHERE ne='NE-710B-24' AND w
         out: attempt finished, rows returned: 4411 6312 4350 7063
         meta: tool=alarm_db.query  params={ne_id:NE-710B-24,severity:minor,time_window:5m}  facts=[4411 6312 4350 7063]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s05           llm         summarize          15.771 ####      279       173        0.00142 ok    stop
         in : condense evidence 4411 6312 4350 7063 into an operator-facing answer
         out: summary drafted from 4411 6312 4350 7063
         meta: model=adn-llm-72b  ttft=1.7470  pv=pv-2026-03
         v3  : sys=204  cache_r=204  cost_det={cache_read:0.000153,completion:0.00104,prompt:0.000225}  verifier=v_numbers_traceable:FAIL(answer number absent from the evidence pool)  subgoal=condensing the evidence on NE-710B-24 as part of the 

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['hallucinated_number']
    intent=i1  pattern=p1  cell=i1|p1
    oracle dim_dev : O=0.15  P=1.00  L=0.91  C=0.91  R=1.00
    latency_true=36.682s  gen_quantiles={'C': 0.1879, 'L': 0.1823}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=[]  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.0000  model_mix_true={'adn-llm-14b': 0.7657, 'adn-llm-72b': 0.2343}  feedback_available=True
    has_golden=False  key_fact_recall_true=n/a  fact_precision_true=n/a
    hallucinated_facts=[]
    query_lang_true=en  session_turn_count_true=2  subgoal_count=3
    plan_revision_true=1  goal_drift_true=False  arg_valid_true=1.0000  verifier_pass_true=0.6667
    citation_reachable_true=n/a  contradiction_true=0.2500  contradicted_count=1  fabricated_citation_count=0
    cache_read_true=358  cache_write_true=296  system_prompt_ratio_true=0.4788  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice4-v0.4.0)
    S=17.2405  G=0.25  grade_abs=D  grade_rel=D  tier=2  novelty=False
    alert=True (rule=True stat=False)  cold_start=False  cell=i1xp0
    dims    : O=0.440  P=1.000  L=0.844  C=0.888  R=1.000
    contrib : O=-6.857  P=+0.000  L=-0.532  C=-0.371  R=+0.000   sum=-7.7595
    zero-residual: S-100G=-7.7595  |diff|=1.90e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.8955  a_cal=0.9943  conf=0.9745  anchor=anchor-R1-007a872125bac9bb
    gates: {"t0_result_broken": 0.25}
    evidence (3 items, drill-down order):
      - [trace] traceable_number_ratio   span=-              value=0.3333      cell_median=1.0000      z= -50.00 dev=0.3909
      - [trace] branch_factor            span=-              value=5.0000      cell_median=4.0000      z=  +0.67 dev=0.2024
      - [span ] dur                      span=R1-00176-s03   value=4.7443      peer_median=3.4416      z=  +0.44 dev=0.1031 (L3/L3span action=approve)
```

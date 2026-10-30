# R8 样本阅读手册

这个文件由 `python -m bench.show R8 --sample` 生成，内容是真实数据，不是示意图。

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
| `data/bench_v1/R8/traces.jsonl` | 模拟出来的轨迹（一行一条，含完整 Span 树） | 3000 |
| `data/bench_v1/R8/gt.jsonl` | 真值：是否异常、异常类型、真实意图/模式、责任 Span | 3000 |
| `reports/R8/scores.jsonl` | 算法输出：S 分、五维、扣分归因、证据、告警 | 3000 |

JSONL = 每行一个压缩 JSON，直接打开会看到一堆没法读的长行。用下面的命令看：

```
python -m bench.show R8 R8-00001        # 看单条轨迹（输入+真值+算法输出）
python -m bench.show R8 --list latency_spike    # 列出某类异常的 trace_id
python -m bench.show R8 --stats                 # 数据集侧写
```

## 三、一条 trace 长什么样

每条 trace = 一棵 Span 树。根节点是整次 agent 执行，子节点是具体步骤（大模型调用 / 工具调用 / 知识检索 / 护栏校验），
每个节点带开始结束时间、token、成本、状态、输入输出文本。下面是真实样本。


## 四、数据集侧写


- 轨迹数 **3000**，Span 数 **15345**，平均 5.1 Span/轨迹
- 异常轨迹 **241** 条（基率 8.03%），正常 **2759** 条
- 意图分布：i0=1448，i1=922，i2=630
- 真实单元格（意图×模式）**9** 个
- 异常类型分布：latency_spike=40，hallucinated_number=34，token_bloat=29，unfinished=27，loop=27，missing_step=26，error=20，truncation=20，illegal_step=18
- `spec_hash=469f903d257a4288`  `gen_version=bench-gen-v3.1.0`
- v3 信号：arg_invalid_spans=72，cache_hit_spans=6580，contradiction=25，fabricated_citation=37，goal_drift=46，llm_spans=7942，plan_revision=177，verifier_fail=45
- 语种分布：en=1814，zh=1186；会话数 **658**，每会话轮次 {'max': 7, 'min': 2, 'n': 3000, 'p50': 5.0, 'p90': 7.0, 'p99': 7.0}

---

## 五、完整样本：输入 → 真值 → 算法输出

### 样本 A：一条正常轨迹（应该得高分、不告警）

```text
==============================================================================
TRACE R8-00001   [intent0: 给我 NE-87F6-25 的指标劣化分析报告，并给出置信度]
  ontology=ontB  session=sess-00000  turn=2/4  spans=6  wall=0.690s  ts_start=1767225694.425
  user_feedback: abandoned=False human_takeover=False retry=False thumbs=1
  answer_numbers=['6314']
  answer_facts  =['NE-87F6-25', '6314']
  golden_answer =
  golden_facts  =None
  goal_text     =指标劣化分析报告   query_lang=zh
  answer_citations  =[]
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[-0.1019, -0.1246, 0.094, -0.4885] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run           0.690 ######### 186       63         0.00080 ok    stop
       in : 给我 NE-87F6-25 的指标劣化分析报告，并给出置信度
       out: '给我 NE-87F6-25 的指标劣化分析报告，并给出置信度' on NE-87F6-25 resolved; see 6314
       meta: model=rca-llm-s  facts=[6314]
       v3  : sys=148  cache_r=148  cost_det={cache_read:0.000148,completion:0.000504,prompt:0.000152}  verifier=v_answer_nonempty:PASS
  `- s01           llm         intent_parse        0.336 ####      617       146        0.00427 ok    stop
         in : parse request: 指标劣化分析报告 (ne=NE-87F6-25, window=5m)
         out: intent normalised for NE-87F6-25 for NE-87F6-25
         meta: model=rca-llm-s  ttft=0.0423  pv=rca-pv-12-canary
         v3  : sys=126  cache_w=126  cost_det={cache_write:0.00063,completion:0.00117,prompt:0.00247}  subgoal=围绕指标劣化分析报告执行解析请求槽位
  `- s02           tool        query_metrics       0.336 ####      0         0          0.00030 ok    -
         in : query kpi for NE-87F6-25 over 5m
         out: series fetched, sample ids 8631 6314; noted for the operator
         meta: tool=tsdb.kpi_query  params={granularity:5m,kpi:packet_loss,ne_id:NE-87F6-25}  facts=[8631 6314]
         v3  : cost_det={tool_call:0.0003}  arg_valid=True
    `- s02-n1        tool        query_metrics       0.201 ###       0         0          0.00030 ok    -
           in : nested query_metrics call for NE-87F6-25
           out: series fetched, sample ids 8631 6314; noted for the operator
           meta: tool=tsdb.kpi_query  params={granularity:5m,kpi:packet_loss,ne_id:NE-87F6-25}  facts=[8631 6314]
           v3  : cost_det={tool_call:0.0003}  arg_valid=True
  `- s03           guard       peer_review         0.101 #         119       9          0.00055 ok    -
         in : second pair of eyes on the NE-87F6-25 conclusion
         out: peer sign-off on NE-87F6-25: pass
         v3  : cost_det={completion:7.2e-05,prompt:0.000476}  verifier=v_no_forbidden_action:PASS
  `- s04           llm         draft_rca           0.206 ###       539       82         0.00353 ok    stop
         in : draft root cause from evidence 8631 6314
         out: conclusion written over 8631 6314 (window 5m)
         meta: model=rca-llm-s  ttft=0.0109  pv=rca-pv-12-canary
         v3  : sys=144  cache_w=144  cost_det={cache_write:0.00072,completion:0.000656,prompt:0.00216}  verifier=v_numbers_traceable:PASS  subgoal=针对指标劣化分析报告进行起草结论（窗口 5m）

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=False  anomaly_types=[]
    intent=i0  pattern=b1  cell=i0|b1
    oracle dim_dev : O=1.00  P=1.00  L=0.72  C=0.96  R=1.00
    latency_true=0.687s  gen_quantiles={'C': 0.0769, 'L': 0.5551}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=[]  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.0000  model_mix_true={'rca-llm-s': 1.0}  feedback_available=True
    has_golden=False  key_fact_recall_true=n/a  fact_precision_true=n/a
    hallucinated_facts=[]
    query_lang_true=zh  session_turn_count_true=4  subgoal_count=2
    plan_revision_true=0  goal_drift_true=False  arg_valid_true=1.0000  verifier_pass_true=1.0000
    citation_reachable_true=n/a  contradiction_true=0.0000  contradicted_count=0  fabricated_citation_count=0
    cache_read_true=148  cache_write_true=270  system_prompt_ratio_true=0.2861  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice2-v0.2.0)
    S=96.8166  G=1.00  grade_abs=A  grade_rel=A  tier=0  novelty=False
    alert=False (rule=False stat=False)  cold_start=False  cell=i1xp0
    dims    : O=1.000  P=1.000  L=0.953  C=0.942  R=0.850
    contrib : O=+0.000  P=+0.000  L=-0.707  C=-0.877  R=-1.599   sum=-3.1834
    zero-residual: S-100G=-3.1834  |diff|=1.00e-06  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.1819  a_cal=0.0472  conf=0.9907  anchor=anchor-R8-469f903d257a4288
    evidence (3 items, drill-down order):
      - [trace] depth                    span=-              value=3.0000      cell_median=2.0000      z= +50.00 dev=0.2080
      - [trace] n_spans                  span=-              value=6.0000      cell_median=4.0000      z= +50.00 dev=0.1895
      - [span ] dur                      span=R8-00001-s02   value=0.3355      peer_median=0.2409      z=  +0.50 dev=0.1147 (L3/L3span action=query_metrics)
```

### 样本 B：latency_spike —— R8-00006

某一步耗时被放大 5~20 倍。看 SPAN TREE 里的 dur(s) 列和 share 条：其中一个子步骤吃掉了几乎全部壁钟时间。真值把 L 维打到 0.10，算法应该在 L 上扣分并把责任指向那个 Span。

```text
==============================================================================
TRACE R8-00006   [intent1: does the topology impact scope of NE-9912-25 reach the core layer]
  ontology=ontB  session=sess-00001  turn=3/7  spans=5  wall=47.537s  ts_start=1767226120.758
  user_feedback: abandoned=False human_takeover=False retry=True thumbs=-1
  answer_numbers=[]
  answer_facts  =[]
  golden_answer =
  golden_facts  =None
  goal_text     =topology impact scope   query_lang=en
  answer_citations  =[]
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[-0.003, -0.1852, 0.2329, -0.1144] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run          47.537 ######### 254       101        0.00143 ok    stop
       in : does the topology impact scope of NE-9912-25 reach the core layer
       out: does the topology impact scope of NE-9912-25 reach the core layer for NE
       meta: model=rca-llm-s
       v3  : sys=133  cache_r=133  cost_det={cache_read:0.000133,completion:0.000808,prompt:0.000484}  verifier=v_answer_nonempty:PASS
  `- s01           llm         intent_parse        3.472 #         807       350        0.00744 ok    stop
         in : slot filling for the request coming from NE-9912-25
         out: checked and recorded: parsed slots: ne=NE-9912-25 window=15m
         meta: model=rca-llm-xl  ttft=0.8265  pv=rca-pv-11
         v3  : sys=283  cache_w=283  cost_det={cache_write:0.00142,completion:0.0028,prompt:0.00323}  subgoal=step goal: parsing the request slots, serving the topology i
  `- s02           llm         correlate_events   43.909 ########  962       277        0.00739 ok    stop
         in : correlate kpi  with alarm window 15m
         out: attempt finished, correlated event ids: 
         meta: model=rca-llm-xl  ttft=2.9267  pv=rca-pv-11
         v3  : sys=265  cache_w=265  cost_det={cache_write:0.00133,completion:0.00222,prompt:0.00385}  subgoal=correlating the events within 15m for the topology impact sc
  `- s03           guard       peer_review         0.661 #         165       37         0.00096 ok    -
         in : peer review of draft rca for NE-9912-25
         out: peer sign-off on NE-9912-25: pass
         v3  : cost_det={completion:0.000296,prompt:0.00066}  verifier=v_no_forbidden_action:PASS
  `- s04           llm         draft_rca           2.570 #         747       149        0.00377 ok    stop
         in : draft root cause from evidence 
         out: draft cites evidence 
         meta: model=rca-llm-s  ttft=0.4502  pv=rca-pv-11
         v3  : sys=137  cache_r=137  cost_det={cache_read:0.000137,completion:0.00119,prompt:0.00244}  verifier=v_numbers_traceable:PASS  subgoal=step goal: drafting the conclusion, serving the topology imp

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['latency_spike']
    intent=i1  pattern=b3  cell=i1|b3
    oracle dim_dev : O=1.00  P=1.00  L=0.10  C=0.82  R=1.00
    latency_true=47.535s  gen_quantiles={'C': 0.356, 'L': 0.2142}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=['R8-00006-s02']  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.0000  model_mix_true={'rca-llm-s': 0.343, 'rca-llm-xl': 0.657}  feedback_available=True
    has_golden=False  key_fact_recall_true=n/a  fact_precision_true=n/a
    hallucinated_facts=[]
    query_lang_true=en  session_turn_count_true=7  subgoal_count=3
    plan_revision_true=0  goal_drift_true=False  arg_valid_true=n/a  verifier_pass_true=1.0000
    citation_reachable_true=n/a  contradiction_true=n/a  contradicted_count=0  fabricated_citation_count=0
    cache_read_true=270  cache_write_true=548  system_prompt_ratio_true=0.2787  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice2-v0.2.0)
    S=50.4264  G=1.00  grade_abs=D  grade_rel=D  tier=0  novelty=False
    alert=False (rule=False stat=False)  cold_start=False  cell=i0xp2
    dims    : O=1.000  P=1.000  L=0.000  C=0.800  R=1.000
    contrib : O=+0.000  P=+0.000  L=-46.897  C=-2.677  R=+0.000   sum=-49.5736
    zero-residual: S-100G=-49.5736  |diff|=2.80e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.3266  a_cal=0.1636  conf=0.9857  anchor=anchor-R8-469f903d257a4288
    evidence (3 items, drill-down order):
      - [trace] latency_total            span=R8-00006-s00   value=47.5375     cell_median=11.0465     z=  +6.32 dev=0.4180
      - [trace] cost_total               span=R8-00006-s02   value=0.0210      cell_median=0.0199      z=  +0.11 dev=0.0895
      - [span ] dur                      span=R8-00006-s02   value=43.9092     peer_median=2.6613      z= +19.13 dev=0.7063 (L3/L3span action=correlate_events)
```

### 样本 C：hallucinated_number（带 golden） —— R8-00335

最终答案里出现了检索证据中不存在的数字。对比子 Span 的 `out: evidence: ...` 与根 Span 的 `out: answer: ...`：后者多出了两个 5 位数。这是唯一一个靠文本内容判定的异常（`traceable_number_ratio` 特征）。

这条带 golden。看 GROUND TRUTH 里的 `fact_precision_true` 与 `key_fact_recall_true`：编造数字只压 precision，recall 仍为 1.00——答案里的事实都在，只是多了不该有的。`hallucinated_facts` 直接列出多出来的那几个。

```text
==============================================================================
TRACE R8-00335   [intent2: NE-4026-16 的变更评审结论是否需要附加条件]
  ontology=ontB  session=sess-00071  turn=3/3  spans=4  wall=48.083s  ts_start=1767254559.538
  user_feedback: abandoned=False human_takeover=False retry=False thumbs=1
  answer_numbers=['7748', '56774', '89018']
  answer_facts  =['NE-4026-16', '7748', '56774', '89018']
  golden_answer =expected answer for NE-4026-16 (NE-4026-16 的变更评审结论是否需要附加条件): 7748
  golden_facts  =['NE-4026-16', '7748']
  goal_text     =变更评审结论   query_lang=zh
  answer_citations  =['doc://vendor/tsdb-query-guide#L1102']
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[-0.162, -0.3217, 0.3011, 0.2428] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run          48.083 ######### 292       99         0.00155 ok    stop
       in : NE-4026-16 的变更评审结论是否需要附加条件
       out: operator summary for NE-4026-16 (NE-4026-16 的变更评审结论是否需要附加条件): 7748, 5677
       meta: model=rca-llm-s  facts=[7748 56774 89018]
       v3  : sys=136  cache_r=136  cost_det={cache_read:0.000136,completion:0.000792,prompt:0.000624}  verifier=v_answer_nonempty:PASS
  `- s01           llm         intent_parse       10.578 ##        621       181        0.00349 ok    stop
         in : slot filling for the request coming from NE-4026-16
         out: intent normalised for NE-4026-16 (window 5m)
         meta: model=rca-llm-s  ttft=0.6888  pv=rca-pv-11
         v3  : sys=147  cache_r=147  cost_det={cache_read:0.000147,completion:0.00145,prompt:0.0019}  subgoal=推进变更评审结论：解析请求槽位
  `- s02           tool        query_metrics      10.578 ##        0         0          0.00030 ok    -
         in : query kpi for NE-4026-16 over 5m
         out: kpi samples: 7748 4560 8023 6524; nothing further required
         meta: tool=tsdb.kpi_query  params={granularity:1m,kpi:cpu_usage,ne_id:NE-4026-16}  facts=[7748 4560 8023 6524]
         v3  : cost_det={tool_call:0.0003}  arg_valid=True
  `- s03           llm         draft_rca          36.261 #######   1148      392        0.00732 ok    stop
         in : draft root cause from evidence 7748 4560 8023 6524
         out: draft cites evidence 7748 4560 8023 6524 for NE-4026-16
         meta: model=rca-llm-s  ttft=9.0942  pv=rca-pv-11
         v3  : sys=136  cache_r=136  cost_det={cache_read:0.000136,completion:0.00314,prompt:0.00405}  verifier=v_numbers_traceable:FAIL(answer number absent from the evidence pool)  subgoal=推进变更评审结论：起草结论

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['hallucinated_number']
    intent=i2  pattern=b1  cell=i2|b1
    oracle dim_dev : O=0.15  P=1.00  L=0.87  C=0.83  R=1.00
    latency_true=48.080s  gen_quantiles={'C': 0.3358, 'L': 0.2506}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=[]  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.0000  model_mix_true={'rca-llm-s': 1.0}  feedback_available=True
    has_golden=True  key_fact_recall_true=1.0000  fact_precision_true=0.5000
    hallucinated_facts=['56774', '89018']
    query_lang_true=zh  session_turn_count_true=3  subgoal_count=2
    plan_revision_true=0  goal_drift_true=False  arg_valid_true=1.0000  verifier_pass_true=0.5000
    citation_reachable_true=0.0000  contradiction_true=0.0000  contradicted_count=0  fabricated_citation_count=1
    cache_read_true=419  cache_write_true=0  system_prompt_ratio_true=0.2033  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice2-v0.2.0)
    S=17.3431  G=0.25  grade_abs=D  grade_rel=D  tier=2  novelty=False
    alert=True (rule=True stat=False)  cold_start=False  cell=i2xp0
    dims    : O=0.446  P=1.000  L=0.883  C=0.850  R=1.000
    contrib : O=-6.755  P=+0.000  L=-0.392  C=-0.510  R=+0.000   sum=-7.6569
    zero-residual: S-100G=-7.6569  |diff|=3.10e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.9069  a_cal=0.9796  conf=0.9043  anchor=anchor-R8-469f903d257a4288
    gates: {"t0_result_broken": 0.25}
    evidence (3 items, drill-down order):
      - [trace] traceable_number_ratio   span=-              value=0.3333      cell_median=1.0000      z= -50.00 dev=0.4377
      - [trace] tokens_total             span=R8-00335-s03   value=2733.0000   cell_median=3091.0000   z=  -0.24 dev=0.0790
      - [span ] dur                      span=R8-00335-s03   value=36.2606     peer_median=19.8221     z=  +0.88 dev=0.2141 (L3/L3span action=draft_rca)
```

### 样本 D：loop —— R8-00066

同一步骤被重复插入 3~5 次。SPAN TREE 里会看到连续多行相同 action，时间戳也相同（生成器直接复制了 Span）。

```text
==============================================================================
TRACE R8-00066   [intent0: write the kpi degradation analysis for NE-A80E-27 and mark the abnormal samples]
  ontology=ontB  session=sess-00013  turn=6/7  spans=10  wall=1.224s  ts_start=1767231285.962
  user_feedback: none captured
  answer_numbers=[]
  answer_facts  =[]
  golden_answer =
  golden_facts  =None
  goal_text     =kpi degradation analysis   query_lang=en
  answer_citations  =[]
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=10 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[-0.0849, -0.0662, 0.1755, -0.6256] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run           1.224 ######### 851       340        0.00528 ok    stop
       in : write the kpi degradation analysis for NE-A80E-27 and mark the abnormal 
       out: write the kpi degradation analysis for NE-A80E-27 and mark the abnormal 
       meta: model=rca-llm-xl
       v3  : sys=282  cache_r=282  cost_det={cache_read:0.000282,completion:0.00272,prompt:0.00228}  verifier=v_answer_nonempty:PASS
  `- s01           llm         intent_parse        0.460 ###       2333      201        0.01055 ok    stop
         in : slot filling for the request coming from NE-A80E-27
         out: parsed slots: ne=NE-A80E-27 window=24h (window 24h)
         meta: model=rca-llm-s  ttft=0.0498  pv=rca-pv-12-canary
         v3  : sys=131  cache_r=131  cost_det={cache_read:0.000131,completion:0.00161,prompt:0.00881}  subgoal=work on parsing the request slots to advance the kpi degrada
  `- s02           llm         correlate_events    0.620 #####     829       641        0.00802 ok    stop
         in : correlate kpi  with alarm window 24h
         out: correlated event ids:  (window 24h)
         meta: model=rca-llm-s  ttft=0.0598  pv=rca-pv-12-canary
         v3  : sys=141  cache_r=141  cost_det={cache_read:0.000141,completion:0.00513,prompt:0.00275}  subgoal=step goal: correlating the events, serving the kpi degradati
  `- s03           llm         correlate_events    0.620 #####     2138      1081       0.01678 ok    stop
         in : correlate kpi  with alarm window 24h
         out: correlation groups formed:  (window 24h)
         meta: level=WARNING  pv=rca-pv-12-canary  msg=topology depth truncated
         v3  : cache_r=140  cost_det={cache_read:0.00014,completion:0.00865,prompt:0.00799}
  `- s04           llm         correlate_events    0.620 #####     4531      1283       0.02795 ok    stop
         in : correlate kpi  with alarm window 24h
         out: correlated event ids:  (window 24h)
         meta: model=rca-llm-s  ttft=0.0579  pv=rca-pv-12-canary
         v3  : sys=147  cache_r=147  cost_det={cache_read:0.000147,completion:0.0103,prompt:0.0175}  subgoal=step goal: correlating the events, serving the kpi degradati
  `- s05           llm         correlate_events    0.620 #####     2350      1022       0.01714 ok    stop
         in : join the event streams touching NE-A80E-27
         out: correlation groups formed:  (window 24h)
         meta: model=rca-llm-s  ttft=0.0738  pv=rca-pv-12-canary
         v3  : sys=146  cache_r=146  cost_det={cache_read:0.000146,completion:0.00818,prompt:0.00882}  subgoal=correlating the events within 24h for the kpi degradation an
  `- s06           llm         correlate_events    0.620 #####     1757      1547       0.01852 ok    stop
         in : join the event streams touching NE-A80E-27
         out: correlation groups formed: ; payload attached to the trace
         meta: pv=rca-pv-12-canary
         v3  : sys=293  cost_det={cache_read:0.000293,completion:0.0124,prompt:0.00586}
  `- s07           llm         correlate_events    0.620 #####     2325      709        0.01458 ok    stop
         in : join the event streams touching NE-A80E-27
         out: correlated event ids: ; nothing further required
         meta: model=rca-llm-s  ttft=0.1273  pv=rca-pv-12-canary
         v3  : sys=132  cache_r=132  cost_det={cache_read:0.000132,completion:0.00567,prompt:0.00877}  subgoal=correlating the events on NE-A80E-27 as part of the kpi degr
  `- s08           guard       peer_review         0.008 #         633       130        0.00357 ok    -
         in : second pair of eyes on the NE-A80E-27 conclusion
         out: review pass for NE-A80E-27
         v3  : cost_det={completion:0.00104,prompt:0.00253}  verifier=v_no_forbidden_action:PASS
  `- s09           llm         draft_rca           0.079 #         1405      945        0.01274 ok    stop
         in : draft root cause from evidence 
         out: conclusion written over  for NE-A80E-27
         meta: model=rca-llm-s  ttft=0.0223  pv=rca-pv-12-canary
         v3  : sys=148  cache_r=148  cost_det={cache_read:0.000148,completion:0.00756,prompt:0.00503}  verifier=v_numbers_traceable:PASS  subgoal=advance the kpi degradation analysis by drafting the conclus

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['loop']
    intent=i0  pattern=b3  cell=i0|b3
    oracle dim_dev : O=1.00  P=0.50  L=0.86  C=0.51  R=0.55
    latency_true=1.221s  gen_quantiles={'C': 0.9898, 'L': 0.2887}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=['R8-00066-s02', 'R8-00066-s03', 'R8-00066-s04', 'R8-00066-s05', 'R8-00066-s06', 'R8-00066-s07']  human_label=True  drift_segment=None
    loop_true=True  mfr_true=0.0840  model_mix_true={'rca-llm-s': 0.9397, 'rca-llm-xl': 0.0603}  feedback_available=False
    has_golden=False  key_fact_recall_true=n/a  fact_precision_true=n/a
    hallucinated_facts=[]
    query_lang_true=en  session_turn_count_true=7  subgoal_count=6
    plan_revision_true=0  goal_drift_true=False  arg_valid_true=n/a  verifier_pass_true=1.0000
    citation_reachable_true=n/a  contradiction_true=n/a  contradicted_count=0  fabricated_citation_count=0
    cache_read_true=1267  cache_write_true=0  system_prompt_ratio_true=0.0741  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice2-v0.2.0)
    S=16.3072  G=0.35  grade_abs=D  grade_rel=D  tier=2  novelty=False
    alert=True (rule=True stat=True)  cold_start=False  cell=i1xp2
    dims    : O=1.000  P=0.800  L=0.744  C=0.000  R=0.850
    contrib : O=+0.000  P=-1.206  L=-1.196  C=-15.852  R=-0.439   sum=-18.6928
    zero-residual: S-100G=-18.6928  |diff|=2.70e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.9936  a_cal=0.9910  conf=0.9151  anchor=anchor-R8-469f903d257a4288
    gates: {"loop_runaway": 0.35}
    evidence (3 items, drill-down order):
      - [trace] cost_total               span=R8-00066-s04   value=0.1351      cell_median=0.0192      z= +11.73 dev=0.6078
      - [trace] tokens_total             span=R8-00066-s04   value=27051.0000  cell_median=4027.5000   z= +11.23 dev=0.6069
      - [span ] tok                      span=R8-00066-s04   value=5814.0000   peer_median=1118.5000   z=  +7.90 dev=0.5023 (L3/L3span action=correlate_events)
```

### 样本 E：token_bloat —— R8-00091

某个 LLM 步骤的 token 被放大 4~10 倍，耗时不变。只有成本维（C）会崩，时延维不崩——用来验证五维不会互相污染。

```text
==============================================================================
TRACE R8-00091   [intent0: what belongs in the kpi degradation analysis of NE-037B-12 over 5m]
  ontology=ontB  session=sess-00018  turn=5/6  spans=5  wall=4.144s  ts_start=1767233461.742
  user_feedback: none captured
  answer_numbers=[]
  answer_facts  =[]
  golden_answer =
  golden_facts  =None
  goal_text     =kpi degradation analysis   query_lang=en
  answer_citations  =[]
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[0.0358, -0.0385, 0.2089, -0.4367] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run           4.144 ######### 412       164        0.00251 ok    stop
       in : what belongs in the kpi degradation analysis of NE-037B-12 over 5m
       out: what belongs in the kpi degradation analysis of NE-037B-12 over 5m for N
       meta: model=rca-llm-s
       v3  : sys=150  cache_r=150  cost_det={cache_read:0.00015,completion:0.00131,prompt:0.00105}  verifier=v_answer_nonempty:PASS
  `- s01           llm         intent_parse        0.627 #         963       318        0.00598 ok    stop
         in : parse request: kpi degradation analysis (ne=NE-037B-12, window=5m)
         out: parsed slots: ne=NE-037B-12 window=5m (window 5m)
         meta: model=rca-llm-s  ttft=0.0962  pv=rca-pv-11
         v3  : sys=137  cache_r=137  cost_det={cache_read:0.000137,completion:0.00254,prompt:0.0033}  subgoal=parsing the request slots for the kpi degradation analysis
  `- s02           llm         correlate_events    0.826 ##        664       276        0.00449 ok    stop
         in : correlate kpi  with alarm window 5m
         out: correlation groups formed:  for NE-037B-12
         meta: model=rca-llm-s  ttft=0.0255  pv=rca-pv-11
         v3  : sys=126  cache_r=126  cost_det={cache_read:0.000126,completion:0.00221,prompt:0.00215}  subgoal=correlating the events on NE-037B-12 as part of the kpi degr
  `- s03           guard       peer_review         0.460 #         331       125        0.00232 ok    -
         in : peer review of draft rca for NE-037B-12
         out: review pass for NE-037B-12
         meta: level=WARNING  msg=topology depth truncated
         v3  : cost_det={completion:0.001,prompt:0.00132}  verifier=v_no_forbidden_action:PASS
  `- s04           llm         draft_rca           2.046 ####      5785      2321       0.04128 ok    stop
         in : compose the analyst facing conclusion for NE-037B-12
         out: checked and recorded: draft cites evidence 
         meta: model=rca-llm-s  ttft=0.1400  pv=rca-pv-11
         v3  : sys=142  cache_r=142  cost_det={cache_read:0.000142,completion:0.0186,prompt:0.0226}  verifier=v_numbers_traceable:PASS  subgoal=drafting the conclusion on NE-037B-12 as part of the kpi deg

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['token_bloat']
    intent=i0  pattern=b3  cell=i0|b3
    oracle dim_dev : O=1.00  P=1.00  L=0.50  C=0.12  R=1.00
    latency_true=4.141s  gen_quantiles={'C': 0.7604, 'L': 0.9998}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=['R8-00091-s04']  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.0000  model_mix_true={'rca-llm-s': 1.0}  feedback_available=False
    has_golden=False  key_fact_recall_true=n/a  fact_precision_true=n/a
    hallucinated_facts=[]
    query_lang_true=en  session_turn_count_true=6  subgoal_count=3
    plan_revision_true=0  goal_drift_true=False  arg_valid_true=n/a  verifier_pass_true=1.0000
    citation_reachable_true=n/a  contradiction_true=n/a  contradicted_count=0  fabricated_citation_count=0
    cache_read_true=555  cache_write_true=0  system_prompt_ratio_true=0.0681  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice2-v0.2.0)
    S=41.2193  G=1.00  grade_abs=D  grade_rel=D  tier=1  novelty=False
    alert=True (rule=False stat=True)  cold_start=False  cell=i1xp2
    dims    : O=1.000  P=1.000  L=0.000  C=0.237  R=1.000
    contrib : O=+0.000  P=+0.000  L=-42.957  C=-15.823  R=+0.000   sum=-58.7807
    zero-residual: S-100G=-58.7807  |diff|=1.60e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.6838  a_cal=0.8529  conf=0.9552  anchor=anchor-R8-469f903d257a4288
    evidence (3 items, drill-down order):
      - [trace] latency_total            span=R8-00091-s00   value=4.1439      cell_median=1.0612      z=  +6.19 dev=0.4744
      - [trace] cost_total               span=R8-00091-s04   value=0.0566      cell_median=0.0192      z=  +3.78 dev=0.3296
      - [span ] tok                      span=R8-00091-s04   value=8106.0000   peer_median=1135.5000   z= +11.83 dev=0.5852 (L3/L3span action=draft_rca)
```

### 样本 F：illegal_step —— R8-00044

插入了本体禁止的动作（如 `force_delete` / `skip_approval_execute`）。这是确定性违规，走规则闸门（alert_rule=True）而不是统计异常。

```text
==============================================================================
TRACE R8-00044   [intent0: 出具 NE-C8A9-44 的指标劣化分析报告]
  ontology=ontB  session=sess-00009  turn=2/7  spans=7  wall=0.948s  ts_start=1767229399.181
  user_feedback: none captured
  answer_numbers=['7843']
  answer_facts  =['NE-C8A9-44', '7843']
  golden_answer =
  golden_facts  =None
  goal_text     =指标劣化分析报告   query_lang=zh
  answer_citations  =['doc://change/rollback-matrix#L54', 'doc://policy/peer-review-charter#L3']
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[-0.1439, -0.0186, 0.0445, -0.6414] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run           0.948 ######### 275       93         0.00143 ok    stop
       in : 出具 NE-C8A9-44 的指标劣化分析报告
       out: 出具 NE-C8A9-44 的指标劣化分析报告 for NE-C8A9-44: 7843
       meta: model=rca-llm-s  facts=[7843]
       v3  : sys=137  cache_r=137  cost_det={cache_read:0.000137,completion:0.000744,prompt:0.000552}  verifier=v_answer_nonempty:PASS
  `- s01           llm         intent_parse        0.181 ##        919       169        0.00460 ok    stop
         in : slot filling for the request coming from NE-C8A9-44
         out: checked and recorded: parsed slots: ne=NE-C8A9-44 window=24h
         meta: model=rca-llm-s  ttft=0.0190  pv=rca-pv-11
         v3  : sys=144  cache_r=144  cost_det={cache_read:0.000144,completion:0.00135,prompt:0.0031}  subgoal=推进指标劣化分析报告：解析请求槽位
  `- s02           retrieval   fetch_topology      0.011 #         278       0          0.00111 ok    -
         in : resolve neighbours of NE-C8A9-44 to depth 2
         out: attempt finished, neighbour ids: 7843 1635 1010
         meta: tool=gis.topology_query  params={depth:-7,region:east}  facts=[7843 1635 1010]
         v3  : cost_det={prompt:0.00111}  arg_valid=False  retrieved=[doc://change/rollback-matrix#L54 doc://policy/peer-review-charter#L3]
  `- s05           llm         correlate_events    0.011 #         729       242        0.00445 ok    stop
         in : join the event streams touching NE-C8A9-44
         out: correlated event ids: 7843 1635 1010 9149 7780 8462
         meta: model=rca-llm-s  ttft=0.0014  pv=rca-pv-11
         v3  : sys=135  cache_r=135  cost_det={cache_read:0.000135,completion:0.00194,prompt:0.00238}  subgoal=步骤目标：关联事件，服务于指标劣化分析报告
  `- s03           tool        purge_logs          0.036 #         0         0          0.00030 ok    -
         in : drop the retained segments belonging to NE-C8A9-44
         out: purged segments: 9149 7780 8462; payload attached to the trace
         meta: tool=logstore.purge  facts=[9149 7780 8462]
         v3  : cost_det={tool_call:0.0003}
  `- s04           guard       peer_review         0.018 #         295       45         0.00154 ok    -
         in : peer review of draft rca for NE-C8A9-44
         out: review block - policy violation for NE-C8A9-44
         v3  : cost_det={completion:0.00036,prompt:0.00118}  verifier=v_no_forbidden_action:FAIL(forbidden action before gate: purge_logs)
  `- s06           llm         draft_rca           0.703 #######   720       254        0.00410 ok    stop
         in : draft root cause from evidence 7843 1635 1010 9149 7780 8462
         out: attempt finished, draft cites evidence 7843 1635 1010 9149 7780 8462
         meta: model=rca-llm-xl  ttft=0.1688  pv=rca-pv-11
         v3  : sys=272  cache_r=272  cost_det={cache_read:0.000272,completion:0.00203,prompt:0.00179}  verifier=v_numbers_traceable:PASS  subgoal=为指标劣化分析报告起草结论

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['illegal_step']
    intent=i0  pattern=b2  cell=i0|b2
    oracle dim_dev : O=1.00  P=0.05  L=0.63  C=0.86  R=1.00
    latency_true=0.945s  gen_quantiles={'C': 0.2876, 'L': 0.7331}
    process_flags={'illegal_step': True, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=['R8-00044-s03']  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.0149  model_mix_true={'rca-llm-s': 0.7136, 'rca-llm-xl': 0.2864}  feedback_available=False
    has_golden=False  key_fact_recall_true=n/a  fact_precision_true=n/a
    hallucinated_facts=[]
    query_lang_true=zh  session_turn_count_true=7  subgoal_count=3
    plan_revision_true=0  goal_drift_true=False  arg_valid_true=0.0000  verifier_pass_true=0.6667
    citation_reachable_true=1.0000  contradiction_true=0.0000  contradicted_count=0  fabricated_citation_count=0
    cache_read_true=688  cache_write_true=0  system_prompt_ratio_true=0.2139  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice2-v0.2.0)
    S=3.7352  G=0.04  grade_abs=D  grade_rel=D  tier=2  novelty=False
    alert=True (rule=True stat=False)  cold_start=False  cell=i1xp1
    dims    : O=1.000  P=0.550  L=0.873  C=0.818  R=0.850
    contrib : O=+0.000  P=-0.491  L=-0.084  C=-0.124  R=-0.067   sum=-0.7648
    zero-residual: S-100G=-0.7648  |diff|=2.90e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.9279  a_cal=0.9833  conf=0.9674  anchor=anchor-R8-469f903d257a4288
    gates: {"forbidden_action": 0.3, "guard_violation": 0.15}
    evidence (3 items, drill-down order):
      - [trace] guard_hits               span=-              value=1.0000      cell_median=0.0000      z= +50.00 dev=0.3778
      - [trace] branch_factor            span=-              value=6.0000      cell_median=4.0000      z=  +1.35 dev=0.2387
      - [span ] dur                      span=R8-00044-s06   value=0.7025      peer_median=0.2798      z=  +1.97 dev=0.2521 (L3/L3span action=draft_rca)
```

### 样本 G：truncation（带 golden） —— R8-01223

根 Span 的 `finish_reason=length`，答案被截断，结果维（O）重罚。

这条带 golden。与上一个样本对着看：截断只压 `key_fact_recall_true`，precision 仍为 1.00——说出来的都对，只是没说完。生成器故意把“不完整”与“不忠实”做成可分离的两类，否则O 维会把两种完全不同的失败打成同一个分。

```text
==============================================================================
TRACE R8-01223   [intent0: 出具 NE-4FC0-07 的指标劣化分析报告]
  ontology=ontB  session=sess-00263  turn=1/7  spans=5  wall=1.098s  ts_start=1767331259.671
  user_feedback: none captured
  answer_numbers=['7451', '1642', '65']
  answer_facts  =['NE-4FC0-07', '7451', '1642', '65']
  golden_answer =expected answer for NE-4FC0-07 (出具 NE-4FC0-07 的指标劣化分析报告): 7451, 1642, 1308, 7985
  golden_facts  =['NE-4FC0-07', '7451', '1642', '1308', '7985']
  goal_text     =指标劣化分析报告   query_lang=zh
  answer_citations  =[]
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[0.0285, -0.1089, 0.174, -0.3203] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run           1.098 ######### 475       161        0.00446 ok    length
       in : 出具 NE-4FC0-07 的指标劣化分析报告
       out: completed '出具 NE-4FC0-07 的指标劣化分析报告' on NE-4FC0-07; values: 7451, 1642, 6
       meta: model=rca-llm-xl  facts=[7451 1642 65]
       v3  : sys=255  cache_w=255  cost_det={cache_write:0.00128,completion:0.00129,prompt:0.0019}  verifier=v_answer_nonempty:PASS
  `- s01           llm         intent_parse        0.331 ###       1144      260        0.00733 ok    stop
         in : slot filling for the request coming from NE-4FC0-07
         out: parsed slots: ne=NE-4FC0-07 window=15m (window 15m)
         meta: model=rca-llm-s  ttft=0.0589  pv=rca-pv-11
         v3  : sys=135  cache_w=135  cost_det={cache_write:0.000675,completion:0.00208,prompt:0.00458}  subgoal=在 NE-4FC0-07 上为指标劣化分析报告完成解析请求槽位
  `- s02           guard       peer_review         0.331 ###       516       10         0.00214 ok    -
         in : second pair of eyes on the NE-4FC0-07 conclusion
         out: peer sign-off on NE-4FC0-07: pass
         v3  : cost_det={completion:8e-05,prompt:0.00206}  verifier=v_no_forbidden_action:PASS
  `- s03           tool        query_metrics       0.266 ##        0         0          0.00030 ok    -
         in : query kpi for NE-4FC0-07 over 15m
         out: kpi samples: 7451 1642 for NE-4FC0-07
         meta: tool=tsdb.kpi_query  params={granularity:5m,kpi:cpu_usage,ne_id:NE-4FC0-07}  facts=[7451 1642]
         v3  : cost_det={tool_call:0.0003}  arg_valid=True
  `- s04           llm         draft_rca           0.455 ####      1182      444        0.00784 ok    stop
         in : compose the analyst facing conclusion for NE-4FC0-07
         out: attempt finished, conclusion written over 7451 1642
         meta: model=rca-llm-s  ttft=0.1327  pv=rca-pv-11
         v3  : sys=146  cache_r=146  cost_det={cache_read:0.000146,completion:0.00355,prompt:0.00414}  verifier=v_numbers_traceable:FAIL(answer number absent from the evidence pool)  subgoal=在 NE-4FC0-07 上为指标劣化分析报告完成起草结论

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['truncation']
    intent=i0  pattern=b1  cell=i0|b1
    oracle dim_dev : O=0.35  P=1.00  L=0.73  C=0.63  R=1.00
    latency_true=1.095s  gen_quantiles={'C': 0.7434, 'L': 0.5456}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=[]  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.0000  model_mix_true={'rca-llm-s': 0.8265, 'rca-llm-xl': 0.1735}  feedback_available=False
    has_golden=True  key_fact_recall_true=0.6000  fact_precision_true=0.7500
    hallucinated_facts=['65']
    query_lang_true=zh  session_turn_count_true=7  subgoal_count=2
    plan_revision_true=0  goal_drift_true=False  arg_valid_true=1.0000  verifier_pass_true=0.6667
    citation_reachable_true=n/a  contradiction_true=0.0000  contradicted_count=0  fabricated_citation_count=0
    cache_read_true=146  cache_write_true=390  system_prompt_ratio_true=0.1616  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice2-v0.2.0)
    S=18.8842  G=0.25  grade_abs=D  grade_rel=D  tier=2  novelty=False
    alert=True (rule=True stat=False)  cold_start=False  cell=i1xp0
    dims    : O=0.640  P=1.000  L=0.811  C=0.625  R=1.000
    contrib : O=-3.893  P=+0.000  L=-0.685  C=-1.538  R=+0.000   sum=-6.1158
    zero-residual: S-100G=-6.1158  |diff|=2.10e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.9351  a_cal=0.9843  conf=0.9907  anchor=anchor-R8-469f903d257a4288
    gates: {"t0_result_broken": 0.25}
    evidence (3 items, drill-down order):
      - [trace] traceable_number_ratio   span=-              value=0.6667      cell_median=1.0000      z= -50.00 dev=0.3068
      - [trace] cost_total               span=R8-01223-s04   value=0.0221      cell_median=0.0142      z=  +1.13 dev=0.1575
      - [span ] dur                      span=R8-01223-s02   value=0.3310      peer_median=0.1149      z=  +2.28 dev=0.2221 (L3/L3span action=peer_review)
```

### 样本 H：missing_step —— R8-00126

本体要求的必须步骤被删掉一个，过程维（P）扣分。

```text
==============================================================================
TRACE R8-00126   [intent1: compute the topology impact scope around NE-763A-20 including neighbour nodes]
  ontology=ontB  session=sess-00027  turn=6/6  spans=5  wall=11.742s  ts_start=1767236485.443
  user_feedback: abandoned=False human_takeover=False retry=False thumbs=-1
  answer_numbers=['1858']
  answer_facts  =['NE-763A-20', '1858']
  golden_answer =expected answer for NE-763A-20 (compute the topology impact scope around NE-763A-20 including neighbour nodes): 1858, 2330
  golden_facts  =['NE-763A-20', '1858', '2330']
  goal_text     =topology impact scope   query_lang=en
  answer_citations  =[]
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[-0.0189, -0.3716, 0.2945, -0.206] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run          11.742 ######### 205       82         0.00105 ok    stop
       in : compute the topology impact scope around NE-763A-20 including neighbour 
       out: NE-763A-20 | compute the topology impact scope around NE-763A-20 includi
       meta: model=rca-llm-s  facts=[1858]
       v3  : sys=143  cache_r=143  cost_det={cache_read:0.000143,completion:0.000656,prompt:0.000248}  verifier=v_answer_nonempty:PASS
  `- s01           llm         intent_parse        2.384 ##        475       166        0.00247 ok    stop
         in : slot filling for the request coming from NE-763A-20
         out: checked and recorded: intent normalised for NE-763A-20
         meta: model=rca-llm-xl  ttft=0.1837  pv=rca-pv-11
         v3  : sys=251  cache_r=251  cost_det={cache_read:0.000251,completion:0.00133,prompt:0.000896}  subgoal=page through archived warehouse stock records
  `- s02           guard       peer_review         1.063 #         95        67         0.00092 ok    -
         in : second pair of eyes on the NE-763A-20 conclusion
         out: peer sign-off on NE-763A-20: pass
         v3  : cost_det={completion:0.000536,prompt:0.00038}  verifier=v_no_forbidden_action:PASS
  `- s03           tool        query_metrics       0.550 #         0         0          0.00030 ok    -
         in : pull the 15 minute series of NE-763A-20
         out: kpi samples: 1858 5708 (window 5m)
         meta: tool=tsdb.kpi_query  params={granularity:15m,kpi:packet_loss,ne_id:NE-763A-20}  facts=[1858 5708]
         v3  : cost_det={tool_call:0.0003}  arg_valid=True
  `- s04           llm         draft_rca           5.508 ####      550       254        0.00385 ok    stop
         in : draft root cause from evidence 1858 5708
         out: draft cites evidence 1858 5708; noted for the operator
         meta: model=rca-llm-s  ttft=0.9356  pv=rca-pv-11
         v3  : sys=128  cache_r=128  cost_det={cache_read:0.000128,completion:0.00203,prompt:0.00169}  verifier=v_numbers_traceable:PASS  subgoal=drafting the conclusion for the topology impact scope

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['missing_step']
    intent=i1  pattern=b3  cell=i1|b3
    oracle dim_dev : O=1.00  P=0.85  L=0.85  C=0.90  R=1.00
    latency_true=11.739s  gen_quantiles={'C': 0.2015, 'L': 0.3004}
    process_flags={'illegal_step': False, 'missing_step': True, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=[]  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.0000  model_mix_true={'rca-llm-s': 0.6299, 'rca-llm-xl': 0.3701}  feedback_available=True
    has_golden=True  key_fact_recall_true=0.6667  fact_precision_true=1.0000
    hallucinated_facts=[]
    query_lang_true=en  session_turn_count_true=6  subgoal_count=2
    plan_revision_true=0  goal_drift_true=True  arg_valid_true=1.0000  verifier_pass_true=1.0000
    citation_reachable_true=n/a  contradiction_true=0.0000  contradicted_count=0  fabricated_citation_count=0
    cache_read_true=522  cache_write_true=0  system_prompt_ratio_true=0.3940  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice2-v0.2.0)
    S=96.0172  G=1.00  grade_abs=A  grade_rel=A  tier=0  novelty=False
    alert=False (rule=False stat=False)  cold_start=False  cell=i0xp0
    dims    : O=1.000  P=1.000  L=0.807  C=0.946  R=1.000
    contrib : O=+0.000  P=+0.000  L=-3.160  C=-0.822  R=+0.000   sum=-3.9828
    zero-residual: S-100G=-3.9828  |diff|=2.40e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.1645  a_cal=0.0403  conf=0.9614  anchor=anchor-R8-469f903d257a4288
    evidence (3 items, drill-down order):
      - [trace] branch_factor            span=-              value=4.0000      cell_median=3.0000      z= +50.00 dev=0.1225
      - [trace] n_spans                  span=-              value=5.0000      cell_median=4.0000      z= +50.00 dev=0.0989
      - [span ] dur                      span=R8-00126-s04   value=5.5084      peer_median=3.5717      z=  +0.64 dev=0.1500 (L3/L3span action=draft_rca)
```

## 六、v3 共生缺陷样本（附录 A 新增特征的原始证据）

下面这些**不是**独立的异常类型，而是叠加在已异常轨迹上的共生缺陷。每一个都由
`bench/coverage.truth_agreement()` 在全部轨迹上做双向等价校验（内核特征 ⟺ 生成器真值），
任何一条对不上都会让构建直接失败，而不是只在报告里留一行警告。


### v3 样本 A：plan_revision —— R8-00002

入口步骤（ontA 的 `plan`、ontB 的 `intent_parse`）出现了两次，第二次的时间区间**嵌套在**第一次之内——智能体在一步还没走完时就重开了计划。`kernel/cluster.collapse()` 会折叠相邻重复，所以模式视图看到的骨架完全不变，只有 `plan_revision_count` 能看见它。这也是该特征被定义成“时间包含”而不是“计数减一”的原因：循环注入器同样可能选中入口步骤，计数减一会把一次循环读成两次计划修订。

```text
==============================================================================
TRACE R8-00002   [intent0: collect the metrics of NE-C88D-34 first, then form the kpi degradation analysis]
  ontology=ontB  session=sess-00000  turn=3/4  spans=6  wall=1.253s  ts_start=1767225780.259
  user_feedback: none captured
  answer_numbers=['6125']
  answer_facts  =['NE-C88D-34', '6125']
  golden_answer =
  golden_facts  =None
  goal_text     =kpi degradation analysis   query_lang=en
  answer_citations  =[]
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[0.0425, 0.0305, 0.1576, -0.5891] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run           1.253 ######### 499       199        0.00284 ok    stop
       in : collect the metrics of NE-C88D-34 first, then form the kpi degradation a
       out: completed 'collect the metrics of NE-C88D-34 first, then form the kpi de
       meta: model=rca-llm-xl  facts=[6125]
       v3  : sys=250  cache_r=250  cost_det={cache_read:0.00025,completion:0.00159,prompt:0.000996}  verifier=v_answer_nonempty:PASS
  `- s01           llm         intent_parse        0.595 ####      1858      579        0.01167 ok    stop
         in : parse request: kpi degradation analysis (ne=NE-C88D-34, window=15m)
         out: parsed slots: ne=NE-C88D-34 window=15m
         meta: model=rca-llm-s  ttft=0.1221  pv=rca-pv-11
         v3  : sys=132  cache_r=132  cost_det={cache_read:0.000132,completion:0.00463,prompt:0.0069}  subgoal=step goal: parsing the request slots, serving the kpi degrad
  `- s02           llm         intent_parse        0.238 ##        881       333        0.00546 ok    stop
         in : slot filling for the request coming from NE-C88D-34
         out: intent normalised for NE-C88D-34; noted for the operator
         meta: model=rca-llm-xl  ttft=0.0695  pv=rca-pv-11
         v3  : sys=241  cache_r=241  cost_det={cache_read:0.000241,completion:0.00266,prompt:0.00256}  subgoal=work on parsing the request slots to advance the kpi degrada
  `- s03           guard       peer_review         0.097 #         729       71         0.00348 ok    -
         in : second pair of eyes on the NE-C88D-34 conclusion
         out: review pass for NE-C88D-34
         v3  : cost_det={completion:0.000568,prompt:0.00292}  verifier=v_no_forbidden_action:PASS
  `- s04           tool        query_metrics       0.378 ###       0         0          0.00030 ok    -
         in : query kpi for NE-C88D-34 over 15m
         out: checked and recorded: series fetched, sample ids 6125 4717 8232
         meta: tool=tsdb.kpi_query  params={granularity:15m,kpi:latency_ms,ne_id:NE-C88D-34}  facts=[6125 4717 8232]
         v3  : cost_det={tool_call:0.0003}  arg_valid=True
  `- s05           llm         draft_rca           0.126 #         1352      443        0.00856 ok    stop
         in : draft root cause from evidence 6125 4717 8232
         out: conclusion written over 6125 4717 8232; payload attached to the trace
         meta: model=rca-llm-s  ttft=0.0176  pv=rca-pv-11
         v3  : sys=131  cache_r=131  cost_det={cache_read:0.000131,completion:0.00354,prompt:0.00488}  verifier=v_numbers_traceable:PASS  subgoal=drafting the conclusion on NE-C88D-34 as part of the kpi deg

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=False  anomaly_types=[]
    intent=i0  pattern=b1  cell=i0|b1
    oracle dim_dev : O=1.00  P=1.00  L=0.84  C=0.56  R=1.00
    latency_true=1.250s  gen_quantiles={'C': 0.8716, 'L': 0.3162}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=[]  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.0000  model_mix_true={'rca-llm-s': 0.6888, 'rca-llm-xl': 0.3112}  feedback_available=False
    has_golden=False  key_fact_recall_true=n/a  fact_precision_true=n/a
    hallucinated_facts=[]
    query_lang_true=en  session_turn_count_true=4  subgoal_count=3
    plan_revision_true=1  goal_drift_true=False  arg_valid_true=1.0000  verifier_pass_true=1.0000
    citation_reachable_true=n/a  contradiction_true=0.0000  contradicted_count=0  fabricated_citation_count=0
    cache_read_true=754  cache_write_true=0  system_prompt_ratio_true=0.1418  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice2-v0.2.0)
    S=82.2552  G=1.00  grade_abs=B  grade_rel=D  tier=0  novelty=False
    alert=False (rule=False stat=False)  cold_start=False  cell=i1xp0
    dims    : O=1.000  P=1.000  L=0.752  C=0.403  R=0.850
    contrib : O=+0.000  P=+0.000  L=-3.880  C=-12.388  R=-1.476   sum=-17.7448
    zero-residual: S-100G=-17.7448  |diff|=3.30e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.2556  a_cal=0.0906  conf=0.9907  anchor=anchor-R8-469f903d257a4288
    evidence (3 items, drill-down order):
      - [trace] branch_factor            span=-              value=5.0000      cell_median=3.0000      z= +50.00 dev=0.2739
      - [trace] tokens_total             span=R8-00002-s01   value=6944.0000   cell_median=2888.0000   z=  +2.79 dev=0.2541
      - [span ] tok                      span=R8-00002-s03   value=800.0000    peer_median=344.0000    z=  +2.54 dev=0.2465 (L3/L3span action=peer_review)
```

### v3 样本 B：goal_drift —— R8-00126

某个 `subgoal_text` 与本条轨迹的 `goal_text` **没有任何内容词重叠**——智能体在这一步跑偏了。特征侧用词元包含率 `1 - |G ∩ S| / |G|` 度量：跑偏时恰好为 1.0，在轨时恰好为 0.0，所以 `goal_drift_max >= 0.5` 与真值构成严格的双向等价。生成器为此专门过滤掉任何与目标共享词元的绕路模板，否则真值会声称漂移而数据里量不出来。

```text
==============================================================================
TRACE R8-00126   [intent1: compute the topology impact scope around NE-763A-20 including neighbour nodes]
  ontology=ontB  session=sess-00027  turn=6/6  spans=5  wall=11.742s  ts_start=1767236485.443
  user_feedback: abandoned=False human_takeover=False retry=False thumbs=-1
  answer_numbers=['1858']
  answer_facts  =['NE-763A-20', '1858']
  golden_answer =expected answer for NE-763A-20 (compute the topology impact scope around NE-763A-20 including neighbour nodes): 1858, 2330
  golden_facts  =['NE-763A-20', '1858', '2330']
  goal_text     =topology impact scope   query_lang=en
  answer_citations  =[]
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[-0.0189, -0.3716, 0.2945, -0.206] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run          11.742 ######### 205       82         0.00105 ok    stop
       in : compute the topology impact scope around NE-763A-20 including neighbour 
       out: NE-763A-20 | compute the topology impact scope around NE-763A-20 includi
       meta: model=rca-llm-s  facts=[1858]
       v3  : sys=143  cache_r=143  cost_det={cache_read:0.000143,completion:0.000656,prompt:0.000248}  verifier=v_answer_nonempty:PASS
  `- s01           llm         intent_parse        2.384 ##        475       166        0.00247 ok    stop
         in : slot filling for the request coming from NE-763A-20
         out: checked and recorded: intent normalised for NE-763A-20
         meta: model=rca-llm-xl  ttft=0.1837  pv=rca-pv-11
         v3  : sys=251  cache_r=251  cost_det={cache_read:0.000251,completion:0.00133,prompt:0.000896}  subgoal=page through archived warehouse stock records
  `- s02           guard       peer_review         1.063 #         95        67         0.00092 ok    -
         in : second pair of eyes on the NE-763A-20 conclusion
         out: peer sign-off on NE-763A-20: pass
         v3  : cost_det={completion:0.000536,prompt:0.00038}  verifier=v_no_forbidden_action:PASS
  `- s03           tool        query_metrics       0.550 #         0         0          0.00030 ok    -
         in : pull the 15 minute series of NE-763A-20
         out: kpi samples: 1858 5708 (window 5m)
         meta: tool=tsdb.kpi_query  params={granularity:15m,kpi:packet_loss,ne_id:NE-763A-20}  facts=[1858 5708]
         v3  : cost_det={tool_call:0.0003}  arg_valid=True
  `- s04           llm         draft_rca           5.508 ####      550       254        0.00385 ok    stop
         in : draft root cause from evidence 1858 5708
         out: draft cites evidence 1858 5708; noted for the operator
         meta: model=rca-llm-s  ttft=0.9356  pv=rca-pv-11
         v3  : sys=128  cache_r=128  cost_det={cache_read:0.000128,completion:0.00203,prompt:0.00169}  verifier=v_numbers_traceable:PASS  subgoal=drafting the conclusion for the topology impact scope

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['missing_step']
    intent=i1  pattern=b3  cell=i1|b3
    oracle dim_dev : O=1.00  P=0.85  L=0.85  C=0.90  R=1.00
    latency_true=11.739s  gen_quantiles={'C': 0.2015, 'L': 0.3004}
    process_flags={'illegal_step': False, 'missing_step': True, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=[]  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.0000  model_mix_true={'rca-llm-s': 0.6299, 'rca-llm-xl': 0.3701}  feedback_available=True
    has_golden=True  key_fact_recall_true=0.6667  fact_precision_true=1.0000
    hallucinated_facts=[]
    query_lang_true=en  session_turn_count_true=6  subgoal_count=2
    plan_revision_true=0  goal_drift_true=True  arg_valid_true=1.0000  verifier_pass_true=1.0000
    citation_reachable_true=n/a  contradiction_true=0.0000  contradicted_count=0  fabricated_citation_count=0
    cache_read_true=522  cache_write_true=0  system_prompt_ratio_true=0.3940  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice2-v0.2.0)
    S=96.0172  G=1.00  grade_abs=A  grade_rel=A  tier=0  novelty=False
    alert=False (rule=False stat=False)  cold_start=False  cell=i0xp0
    dims    : O=1.000  P=1.000  L=0.807  C=0.946  R=1.000
    contrib : O=+0.000  P=+0.000  L=-3.160  C=-0.822  R=+0.000   sum=-3.9828
    zero-residual: S-100G=-3.9828  |diff|=2.40e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.1645  a_cal=0.0403  conf=0.9614  anchor=anchor-R8-469f903d257a4288
    evidence (3 items, drill-down order):
      - [trace] branch_factor            span=-              value=4.0000      cell_median=3.0000      z= +50.00 dev=0.1225
      - [trace] n_spans                  span=-              value=5.0000      cell_median=4.0000      z= +50.00 dev=0.0989
      - [span ] dur                      span=R8-00126-s04   value=5.5084      peer_median=3.5717      z=  +0.64 dev=0.1500 (L3/L3span action=draft_rca)
```

### v3 样本 C：invalid_tool_arg —— R8-00044

工具入参违反了本体的 `param_schema`（枚举越界 / 前缀不符）。`arg_valid` 是**测量**出来的而不是断言的：生成器构造完违规参数后会再跑一次同一个校验函数，只有确实判为违规才落库。循环与重试的副本共享同一份参数，所以一个违规组里的每个副本都同样违规——这是刻意的，否则 `(parent, action, 参数哈希)` 分组会被拆开，一个真循环就悄悄变成了非循环。

```text
==============================================================================
TRACE R8-00044   [intent0: 出具 NE-C8A9-44 的指标劣化分析报告]
  ontology=ontB  session=sess-00009  turn=2/7  spans=7  wall=0.948s  ts_start=1767229399.181
  user_feedback: none captured
  answer_numbers=['7843']
  answer_facts  =['NE-C8A9-44', '7843']
  golden_answer =
  golden_facts  =None
  goal_text     =指标劣化分析报告   query_lang=zh
  answer_citations  =['doc://change/rollback-matrix#L54', 'doc://policy/peer-review-charter#L3']
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[-0.1439, -0.0186, 0.0445, -0.6414] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run           0.948 ######### 275       93         0.00143 ok    stop
       in : 出具 NE-C8A9-44 的指标劣化分析报告
       out: 出具 NE-C8A9-44 的指标劣化分析报告 for NE-C8A9-44: 7843
       meta: model=rca-llm-s  facts=[7843]
       v3  : sys=137  cache_r=137  cost_det={cache_read:0.000137,completion:0.000744,prompt:0.000552}  verifier=v_answer_nonempty:PASS
  `- s01           llm         intent_parse        0.181 ##        919       169        0.00460 ok    stop
         in : slot filling for the request coming from NE-C8A9-44
         out: checked and recorded: parsed slots: ne=NE-C8A9-44 window=24h
         meta: model=rca-llm-s  ttft=0.0190  pv=rca-pv-11
         v3  : sys=144  cache_r=144  cost_det={cache_read:0.000144,completion:0.00135,prompt:0.0031}  subgoal=推进指标劣化分析报告：解析请求槽位
  `- s02           retrieval   fetch_topology      0.011 #         278       0          0.00111 ok    -
         in : resolve neighbours of NE-C8A9-44 to depth 2
         out: attempt finished, neighbour ids: 7843 1635 1010
         meta: tool=gis.topology_query  params={depth:-7,region:east}  facts=[7843 1635 1010]
         v3  : cost_det={prompt:0.00111}  arg_valid=False  retrieved=[doc://change/rollback-matrix#L54 doc://policy/peer-review-charter#L3]
  `- s05           llm         correlate_events    0.011 #         729       242        0.00445 ok    stop
         in : join the event streams touching NE-C8A9-44
         out: correlated event ids: 7843 1635 1010 9149 7780 8462
         meta: model=rca-llm-s  ttft=0.0014  pv=rca-pv-11
         v3  : sys=135  cache_r=135  cost_det={cache_read:0.000135,completion:0.00194,prompt:0.00238}  subgoal=步骤目标：关联事件，服务于指标劣化分析报告
  `- s03           tool        purge_logs          0.036 #         0         0          0.00030 ok    -
         in : drop the retained segments belonging to NE-C8A9-44
         out: purged segments: 9149 7780 8462; payload attached to the trace
         meta: tool=logstore.purge  facts=[9149 7780 8462]
         v3  : cost_det={tool_call:0.0003}
  `- s04           guard       peer_review         0.018 #         295       45         0.00154 ok    -
         in : peer review of draft rca for NE-C8A9-44
         out: review block - policy violation for NE-C8A9-44
         v3  : cost_det={completion:0.00036,prompt:0.00118}  verifier=v_no_forbidden_action:FAIL(forbidden action before gate: purge_logs)
  `- s06           llm         draft_rca           0.703 #######   720       254        0.00410 ok    stop
         in : draft root cause from evidence 7843 1635 1010 9149 7780 8462
         out: attempt finished, draft cites evidence 7843 1635 1010 9149 7780 8462
         meta: model=rca-llm-xl  ttft=0.1688  pv=rca-pv-11
         v3  : sys=272  cache_r=272  cost_det={cache_read:0.000272,completion:0.00203,prompt:0.00179}  verifier=v_numbers_traceable:PASS  subgoal=为指标劣化分析报告起草结论

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['illegal_step']
    intent=i0  pattern=b2  cell=i0|b2
    oracle dim_dev : O=1.00  P=0.05  L=0.63  C=0.86  R=1.00
    latency_true=0.945s  gen_quantiles={'C': 0.2876, 'L': 0.7331}
    process_flags={'illegal_step': True, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=['R8-00044-s03']  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.0149  model_mix_true={'rca-llm-s': 0.7136, 'rca-llm-xl': 0.2864}  feedback_available=False
    has_golden=False  key_fact_recall_true=n/a  fact_precision_true=n/a
    hallucinated_facts=[]
    query_lang_true=zh  session_turn_count_true=7  subgoal_count=3
    plan_revision_true=0  goal_drift_true=False  arg_valid_true=0.0000  verifier_pass_true=0.6667
    citation_reachable_true=1.0000  contradiction_true=0.0000  contradicted_count=0  fabricated_citation_count=0
    cache_read_true=688  cache_write_true=0  system_prompt_ratio_true=0.2139  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice2-v0.2.0)
    S=3.7352  G=0.04  grade_abs=D  grade_rel=D  tier=2  novelty=False
    alert=True (rule=True stat=False)  cold_start=False  cell=i1xp1
    dims    : O=1.000  P=0.550  L=0.873  C=0.818  R=0.850
    contrib : O=+0.000  P=-0.491  L=-0.084  C=-0.124  R=-0.067   sum=-0.7648
    zero-residual: S-100G=-0.7648  |diff|=2.90e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.9279  a_cal=0.9833  conf=0.9674  anchor=anchor-R8-469f903d257a4288
    gates: {"forbidden_action": 0.3, "guard_violation": 0.15}
    evidence (3 items, drill-down order):
      - [trace] guard_hits               span=-              value=1.0000      cell_median=0.0000      z= +50.00 dev=0.3778
      - [trace] branch_factor            span=-              value=6.0000      cell_median=4.0000      z=  +1.35 dev=0.2387
      - [span ] dur                      span=R8-00044-s06   value=0.7025      peer_median=0.2798      z=  +1.97 dev=0.2521 (L3/L3span action=draft_rca)
```

### v3 样本 D：verifier_fail —— R8-00044

确定性校验器给出 FAIL。三个校验器全部是代码判定，没有任何生成式判官参与：`v_numbers_traceable`（答案里的数字必须能在证据池中找到）、`v_no_forbidden_action`（禁用动作不得被启动）、`v_answer_nonempty`（答案非空）。它们的结果是从落库记录本身反推出来的，而不是生成器的意图。

```text
==============================================================================
TRACE R8-00044   [intent0: 出具 NE-C8A9-44 的指标劣化分析报告]
  ontology=ontB  session=sess-00009  turn=2/7  spans=7  wall=0.948s  ts_start=1767229399.181
  user_feedback: none captured
  answer_numbers=['7843']
  answer_facts  =['NE-C8A9-44', '7843']
  golden_answer =
  golden_facts  =None
  goal_text     =指标劣化分析报告   query_lang=zh
  answer_citations  =['doc://change/rollback-matrix#L54', 'doc://policy/peer-review-charter#L3']
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[-0.1439, -0.0186, 0.0445, -0.6414] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run           0.948 ######### 275       93         0.00143 ok    stop
       in : 出具 NE-C8A9-44 的指标劣化分析报告
       out: 出具 NE-C8A9-44 的指标劣化分析报告 for NE-C8A9-44: 7843
       meta: model=rca-llm-s  facts=[7843]
       v3  : sys=137  cache_r=137  cost_det={cache_read:0.000137,completion:0.000744,prompt:0.000552}  verifier=v_answer_nonempty:PASS
  `- s01           llm         intent_parse        0.181 ##        919       169        0.00460 ok    stop
         in : slot filling for the request coming from NE-C8A9-44
         out: checked and recorded: parsed slots: ne=NE-C8A9-44 window=24h
         meta: model=rca-llm-s  ttft=0.0190  pv=rca-pv-11
         v3  : sys=144  cache_r=144  cost_det={cache_read:0.000144,completion:0.00135,prompt:0.0031}  subgoal=推进指标劣化分析报告：解析请求槽位
  `- s02           retrieval   fetch_topology      0.011 #         278       0          0.00111 ok    -
         in : resolve neighbours of NE-C8A9-44 to depth 2
         out: attempt finished, neighbour ids: 7843 1635 1010
         meta: tool=gis.topology_query  params={depth:-7,region:east}  facts=[7843 1635 1010]
         v3  : cost_det={prompt:0.00111}  arg_valid=False  retrieved=[doc://change/rollback-matrix#L54 doc://policy/peer-review-charter#L3]
  `- s05           llm         correlate_events    0.011 #         729       242        0.00445 ok    stop
         in : join the event streams touching NE-C8A9-44
         out: correlated event ids: 7843 1635 1010 9149 7780 8462
         meta: model=rca-llm-s  ttft=0.0014  pv=rca-pv-11
         v3  : sys=135  cache_r=135  cost_det={cache_read:0.000135,completion:0.00194,prompt:0.00238}  subgoal=步骤目标：关联事件，服务于指标劣化分析报告
  `- s03           tool        purge_logs          0.036 #         0         0          0.00030 ok    -
         in : drop the retained segments belonging to NE-C8A9-44
         out: purged segments: 9149 7780 8462; payload attached to the trace
         meta: tool=logstore.purge  facts=[9149 7780 8462]
         v3  : cost_det={tool_call:0.0003}
  `- s04           guard       peer_review         0.018 #         295       45         0.00154 ok    -
         in : peer review of draft rca for NE-C8A9-44
         out: review block - policy violation for NE-C8A9-44
         v3  : cost_det={completion:0.00036,prompt:0.00118}  verifier=v_no_forbidden_action:FAIL(forbidden action before gate: purge_logs)
  `- s06           llm         draft_rca           0.703 #######   720       254        0.00410 ok    stop
         in : draft root cause from evidence 7843 1635 1010 9149 7780 8462
         out: attempt finished, draft cites evidence 7843 1635 1010 9149 7780 8462
         meta: model=rca-llm-xl  ttft=0.1688  pv=rca-pv-11
         v3  : sys=272  cache_r=272  cost_det={cache_read:0.000272,completion:0.00203,prompt:0.00179}  verifier=v_numbers_traceable:PASS  subgoal=为指标劣化分析报告起草结论

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['illegal_step']
    intent=i0  pattern=b2  cell=i0|b2
    oracle dim_dev : O=1.00  P=0.05  L=0.63  C=0.86  R=1.00
    latency_true=0.945s  gen_quantiles={'C': 0.2876, 'L': 0.7331}
    process_flags={'illegal_step': True, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=['R8-00044-s03']  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.0149  model_mix_true={'rca-llm-s': 0.7136, 'rca-llm-xl': 0.2864}  feedback_available=False
    has_golden=False  key_fact_recall_true=n/a  fact_precision_true=n/a
    hallucinated_facts=[]
    query_lang_true=zh  session_turn_count_true=7  subgoal_count=3
    plan_revision_true=0  goal_drift_true=False  arg_valid_true=0.0000  verifier_pass_true=0.6667
    citation_reachable_true=1.0000  contradiction_true=0.0000  contradicted_count=0  fabricated_citation_count=0
    cache_read_true=688  cache_write_true=0  system_prompt_ratio_true=0.2139  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice2-v0.2.0)
    S=3.7352  G=0.04  grade_abs=D  grade_rel=D  tier=2  novelty=False
    alert=True (rule=True stat=False)  cold_start=False  cell=i1xp1
    dims    : O=1.000  P=0.550  L=0.873  C=0.818  R=0.850
    contrib : O=+0.000  P=-0.491  L=-0.084  C=-0.124  R=-0.067   sum=-0.7648
    zero-residual: S-100G=-0.7648  |diff|=2.90e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.9279  a_cal=0.9833  conf=0.9674  anchor=anchor-R8-469f903d257a4288
    gates: {"forbidden_action": 0.3, "guard_violation": 0.15}
    evidence (3 items, drill-down order):
      - [trace] guard_hits               span=-              value=1.0000      cell_median=0.0000      z= +50.00 dev=0.3778
      - [trace] branch_factor            span=-              value=6.0000      cell_median=4.0000      z=  +1.35 dev=0.2387
      - [span ] dur                      span=R8-00044-s06   value=0.7025      peer_median=0.2798      z=  +1.97 dev=0.2521 (L3/L3span action=draft_rca)
```

### v3 样本 E：fabricated_citation —— R8-00123

答案引用了一个**格式完全合法**的定位符，但它不在本次检索到的结果集里。真实智能体的编造几乎从不是凭空造一个URL，而是把片段号写错——所以 `citation_reachability` 必须对着检索结果集算，而不是对着 URL 白名单或格式校验算。生成器正是这样伪造的：取一个真实定位符，把 `#L` 片段改到 1001~1900 区间。

```text
==============================================================================
TRACE R8-00123   [intent1: output the topology impact scope list of NE-5B32-51 within 24h]
  ontology=ontB  session=sess-00027  turn=3/6  spans=4  wall=25.177s  ts_start=1767236224.767
  user_feedback: none captured
  answer_numbers=['4876', '8165', '97474', '95464']
  answer_facts  =['NE-5B32-51', '4876', '8165', '97474', '95464']
  golden_answer =
  golden_facts  =None
  goal_text     =topology impact scope   query_lang=en
  answer_citations  =['doc://policy/peer-review-charter#L1456', 'kb://postmortem/2025-0712-core-outage#L1540']
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[-0.127, -0.2767, 0.1978, -0.0638] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run          25.177 ######### 290       116        0.00168 ok    stop
       in : output the topology impact scope list of NE-5B32-51 within 24h
       out: result for NE-5B32-51 (output the topology impact scope list of NE-5B32-
       meta: model=rca-llm-s  facts=[4876 8165 97474 95464]
       v3  : sys=136  cache_r=136  cost_det={cache_read:0.000136,completion:0.000928,prompt:0.000616}  verifier=v_answer_nonempty:PASS
  `- s01           llm         intent_parse        6.551 ##        679       310        0.00445 ok    stop
         in : parse request: topology impact scope (ne=NE-5B32-51, window=24h)
         out: checked and recorded: intent normalised for NE-5B32-51
         meta: model=rca-llm-xl  ttft=0.6101  pv=rca-pv-11
         v3  : sys=249  cache_r=249  cost_det={cache_read:0.000249,completion:0.00248,prompt:0.00172}  subgoal=parsing the request slots within 24h for the topology impact
  `- s02           tool        query_metrics      10.146 ####      0         0          0.00030 ok    -
         in : pull the 15 minute series of NE-5B32-51
         out: kpi samples: 8165 4994 4876; payload attached to the trace
         meta: tool=tsdb.kpi_query  params={granularity:15m,kpi:cpu_usage,ne_id:NE-5B32-51}  facts=[8165 4994 4876]
         v3  : cost_det={tool_call:0.0003}  arg_valid=True
  `- s03           llm         draft_rca           7.496 ###       626       197        0.00330 ok    stop
         in : compose the analyst facing conclusion for NE-5B32-51
         out: checked and recorded: draft cites evidence 8165 4994 4876
         meta: model=rca-llm-xl  ttft=1.8390  pv=rca-pv-11
         v3  : sys=261  cache_r=261  cost_det={cache_read:0.000261,completion:0.00158,prompt:0.00146}  verifier=v_numbers_traceable:FAIL(answer number absent from the evidence pool)  subgoal=drafting the conclusion within 24h for the topology im

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['hallucinated_number']
    intent=i1  pattern=b1  cell=i1|b1
    oracle dim_dev : O=0.15  P=1.00  L=0.54  C=0.76  R=1.00
    latency_true=25.174s  gen_quantiles={'C': 0.4711, 'L': 0.9198}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=[]  human_label=True  drift_segment=None
    loop_true=False  mfr_true=0.0000  model_mix_true={'rca-llm-s': 0.183, 'rca-llm-xl': 0.817}  feedback_available=False
    has_golden=False  key_fact_recall_true=n/a  fact_precision_true=n/a
    hallucinated_facts=[]
    query_lang_true=en  session_turn_count_true=6  subgoal_count=2
    plan_revision_true=0  goal_drift_true=False  arg_valid_true=1.0000  verifier_pass_true=0.5000
    citation_reachable_true=0.0000  contradiction_true=0.0000  contradicted_count=0  fabricated_citation_count=2
    cache_read_true=646  cache_write_true=0  system_prompt_ratio_true=0.4050  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice2-v0.2.0)
    S=36.8012  G=0.60  grade_abs=D  grade_rel=D  tier=2  novelty=False
    alert=True (rule=True stat=False)  cold_start=False  cell=i0xp0
    dims    : O=0.440  P=1.000  L=0.378  C=0.908  R=1.000
    contrib : O=-15.585  P=+0.000  L=-6.923  C=-0.690  R=+0.000   sum=-23.1988
    zero-residual: S-100G=-23.1988  |diff|=4.80e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.9374  a_cal=0.9847  conf=0.9614  anchor=anchor-R8-469f903d257a4288
    gates: {"t2_untraceable_number": 0.6}
    evidence (3 items, drill-down order):
      - [trace] traceable_number_ratio   span=-              value=0.5000      cell_median=1.0000      z= -50.00 dev=0.4065
      - [trace] latency_total            span=R8-00123-s00   value=25.1771     cell_median=11.9784     z=  +2.01 dev=0.2791
      - [span ] dur                      span=R8-00123-s02   value=10.1461     peer_median=2.5047      z=  +3.79 dev=0.3025 (L3/L3span action=query_metrics)
```

### v3 样本 F：contradicted_evidence —— R8-00172

答案陈述了与证据相反的关系。注意它与幻觉的区别：矛盾涉及的事实**在**证据池里，只是关系被说反了。生成器只从`golden_facts ∩ answer_facts` 里采样，从结构上保证了这一点。特征侧的 `contradiction_rate` 仍标记为`needs_model`——数据集负责提供输入与真值，数值本身要等真实 NLI 模型接上才有意义。

```text
==============================================================================
TRACE R8-00172   [intent0: what belongs in the kpi degradation analysis of NE-6185-59 over 1h]
  ontology=ontB  session=sess-00038  turn=1/5  spans=4  wall=1.240s  ts_start=1767240476.874
  user_feedback: none captured
  answer_numbers=['7031', '4643']
  answer_facts  =['NE-6185-59', '7031', '4643']
  golden_answer =
  golden_facts  =None
  goal_text     =kpi degradation analysis   query_lang=en
  answer_citations  =[]
  contradicted_facts=['4643']
  raw_flags(as ingested): field_loss=3 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[-0.0554, 0.0073, 0.2096, -0.5337] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run           1.240 ######### 229       91         0.00239 ok    stop
       in : what belongs in the kpi degradation analysis of NE-6185-59 over 1h
       out: what belongs in the kpi degradation analysis of NE-6185-59 over 1h for N
       meta: model=rca-llm-s  facts=[7031 4643]
       v3  : sys=149  cache_w=149  cost_det={cache_write:0.000745,completion:0.000728,prompt:0.000916}  verifier=v_answer_nonempty:PASS
  `- s01           llm         intent_parse        0.348 ###       513       155        0.00404 ok    stop
         in : slot filling for the request coming from NE-6185-59
         out: attempt finished, parsed slots: ne=NE-6185-59 window=1h
         meta: model=rca-llm-s  ttft=0.0188
         v3  : sys=149  cost_det={cache_write:0.000745,completion:0.00124,prompt:0.00205}  subgoal=step goal: parsing the request slots, serving the kpi degrad
  `- s02           tool        query_metrics       0.490 ####      0         0          0.00030 ok    -
         in : pull the 15 minute series of NE-6185-59
         out: ok - kpi samples: 7031 4643
         meta: tool=tsdb.kpi_query  params={granularity:15m,kpi:cpu_usage,ne_id:NE-6185-59}  facts=[7031 4643]
         v3  : cost_det={tool_call:0.0003}
  `- s03           llm         draft_rca           0.351 ###       640       258        0.00381 error stop
         in : compose the analyst facing conclusion for NE-6185-59
         out: draft cites evidence 7031 4643; nothing further required
         meta: model=rca-llm-xl  level=ERROR  ttft=0.0272  pv=rca-pv-11  msg=metric store returned 500
         v3  : sys=271  cache_r=271  cost_det={cache_read:0.000271,completion:0.00206,prompt:0.00148}  verifier=v_numbers_traceable:PASS  subgoal=drafting the conclusion on NE-6185-59 as part of the kpi deg

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['error']
    intent=i0  pattern=b1  cell=i0|b1
    oracle dim_dev : O=0.75  P=1.00  L=0.85  C=0.86  R=0.35
    latency_true=1.237s  gen_quantiles={'C': 0.2761, 'L': 0.3098}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=['R8-00172-s03']  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.0714  model_mix_true={'rca-llm-s': 0.5239, 'rca-llm-xl': 0.4761}  feedback_available=False
    has_golden=False  key_fact_recall_true=n/a  fact_precision_true=n/a
    hallucinated_facts=[]
    query_lang_true=en  session_turn_count_true=5  subgoal_count=2
    plan_revision_true=0  goal_drift_true=False  arg_valid_true=n/a  verifier_pass_true=1.0000
    citation_reachable_true=n/a  contradiction_true=0.3333  contradicted_count=1  fabricated_citation_count=0
    cache_read_true=271  cache_write_true=149  system_prompt_ratio_true=0.4117  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice2-v0.2.0)
    S=83.2075  G=1.00  grade_abs=B  grade_rel=C  tier=2  novelty=False
    alert=True (rule=True stat=False)  cold_start=False  cell=i1xp0
    dims    : O=0.800  P=1.000  L=0.757  C=0.921  R=0.667
    contrib : O=-8.153  P=+0.000  L=-3.812  C=-1.123  R=-3.704   sum=-16.7925
    zero-residual: S-100G=-16.7925  |diff|=1.30e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.9126  a_cal=0.9807  conf=0.9553  anchor=anchor-R8-469f903d257a4288
    evidence (3 items, drill-down order):
      - [trace] error_ratio              span=R8-00172-s03   value=0.2500      cell_median=0.0000      z= +50.00 dev=0.3752
      - [trace] missing_field_ratio      span=-              value=0.0714      cell_median=0.0000      z= +50.00 dev=0.2634
      - [span ] dur                      span=R8-00172-s02   value=0.4900      peer_median=0.2409      z=  +1.31 dev=0.1770 (L3/L3span action=query_metrics)
```

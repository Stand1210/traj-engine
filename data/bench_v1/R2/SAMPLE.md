# R2 样本阅读手册

这个文件由 `python -m bench.show R2 --sample` 生成，内容是真实数据，不是示意图。

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
| `data/bench_v1/R2/traces.jsonl` | 模拟出来的轨迹（一行一条，含完整 Span 树） | 4000 |
| `data/bench_v1/R2/gt.jsonl` | 真值：是否异常、异常类型、真实意图/模式、责任 Span | 4000 |
| `reports/R2/scores.jsonl` | 算法输出：S 分、五维、扣分归因、证据、告警 | 4000 |

JSONL = 每行一个压缩 JSON，直接打开会看到一堆没法读的长行。用下面的命令看：

```
python -m bench.show R2 R2-00001        # 看单条轨迹（输入+真值+算法输出）
python -m bench.show R2 --list latency_spike    # 列出某类异常的 trace_id
python -m bench.show R2 --stats                 # 数据集侧写
```

## 三、一条 trace 长什么样

每条 trace = 一棵 Span 树。根节点是整次 agent 执行，子节点是具体步骤（大模型调用 / 工具调用 / 知识检索 / 护栏校验），
每个节点带开始结束时间、token、成本、状态、输入输出文本。下面是真实样本。


## 四、数据集侧写


- 轨迹数 **4000**，Span 数 **20933**，平均 5.2 Span/轨迹
- 异常轨迹 **298** 条（基率 7.45%），正常 **3702** 条
- 意图分布：i0=1988，i1=1231，i2=781
- 真实单元格（意图×模式）**9** 个
- 异常类型分布：latency_spike=46，hallucinated_number=45，token_bloat=40，truncation=33，unfinished=31，loop=30，missing_step=29，illegal_step=22，error=22
- `spec_hash=52470f48253b25a6`  `gen_version=bench-gen-v3.1.0`
- v3 信号：arg_invalid_spans=155，cache_hit_spans=6619，contradiction=49，fabricated_citation=42，goal_drift=51，llm_spans=8220，plan_revision=249，verifier_fail=78
- 语种分布：en=1776，zh=2224；会话数 **885**，每会话轮次 {'max': 7, 'min': 1, 'n': 4000, 'p50': 5.0, 'p90': 7.0, 'p99': 7.0}

---

## 五、完整样本：输入 → 真值 → 算法输出

### 样本 A：一条正常轨迹（应该得高分、不告警）

```text
==============================================================================
TRACE R2-00000   [intent1: 定位网元 NE-7CE2-12 的劣化根因]
  ontology=ontA  session=sess-00000  turn=1/7  spans=5  wall=14.200s  ts_start=1767225603.606
  user_feedback: none captured
  answer_numbers=['8575', '3514']
  answer_facts  =['NE-7CE2-12', '8575', '3514']
  golden_answer =
  golden_facts  =None
  goal_text     =劣化根因   query_lang=zh
  answer_citations  =['doc://vendor/nbi-api-reference#L310']
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[-0.3899, -0.0238, -0.3084, 0.0775] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run          14.200 ######### 286       99         0.00197 ok    stop
       in : 定位网元 NE-7CE2-12 的劣化根因
       out: NE-7CE2-12 | 定位网元 NE-7CE2-12 的劣化根因 | observed values 8575, 3514
       meta: model=adn-llm-14b  facts=[8575 3514]
       v3  : sys=137  cache_w=137  cost_det={cache_write:0.000514,completion:0.000594,prompt:0.000858}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan                4.605 ###       882       192        0.00465 ok    stop
         in : task=劣化根因 ne=NE-7CE2-12 window=15m; produce a step plan
         out: checked and recorded: decompose into retrieval then aggregation; window=
         meta: model=adn-llm-72b  ttft=0.4503  pv=pv-2026-03
         v3  : sys=228  cache_w=228  cost_det={cache_write:0.000855,completion:0.00115,prompt:0.00265}  subgoal=推进劣化根因：拆解任务步骤
  `- s02           guard       verify              4.605 ###       226       6          0.00071 ok    -
         in : policy check on pending action for NE-7CE2-12
         out: verdict pass for NE-7CE2-12
         v3  : cost_det={completion:3.6e-05,prompt:0.000678}  verifier=v_no_forbidden_action:PASS
  `- s03           retrieval   retrieve_kb         2.952 ##        454       0          0.00136 ok    -
         in : runbook search: 劣化根因 (ne=NE-7CE2-12)
         out: matched runbook evidence: 8575 6384 3514
         meta: tool=kb.runbook_search  params={query:NE-7CE2-12,top_k:3}  facts=[8575 6384 3514]
         v3  : cost_det={prompt:0.00136}  arg_valid=True  retrieved=[doc://vendor/nbi-api-reference#L310]
  `- s04           llm         summarize           6.042 ####      921       220        0.00466 ok    stop
         in : write the final response for NE-7CE2-12 from evidence 8575 6384 3514
         out: attempt finished, answer composed citing 8575 6384 3514
         meta: model=adn-llm-14b  ttft=0.9065  pv=pv-2026-03
         v3  : sys=154  cache_w=154  cost_det={cache_write:0.000577,completion:0.00132,prompt:0.00276}  verifier=v_numbers_traceable:PASS  subgoal=围绕劣化根因执行归纳证据

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=False  anomaly_types=[]
    intent=i1  pattern=p3  cell=i1|p3
    oracle dim_dev : O=1.00  P=1.00  L=0.59  C=0.83  R=1.00
    latency_true=14.197s  gen_quantiles={'C': 0.34, 'L': 0.8129}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=[]  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.0000  model_mix_true={'adn-llm-14b': 0.5869, 'adn-llm-72b': 0.4131}  feedback_available=False
    has_golden=False  key_fact_recall_true=n/a  fact_precision_true=n/a
    hallucinated_facts=[]
    query_lang_true=zh  session_turn_count_true=7  subgoal_count=2
    plan_revision_true=0  goal_drift_true=False  arg_valid_true=1.0000  verifier_pass_true=1.0000
    citation_reachable_true=1.0000  contradiction_true=0.0000  contradicted_count=0  fabricated_citation_count=0
    cache_read_true=0  cache_write_true=519  system_prompt_ratio_true=0.1874  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice4-v0.4.0)
    S=92.0966  G=1.00  grade_abs=A  grade_rel=B  tier=0  novelty=False
    alert=False (rule=False stat=False)  cold_start=False  cell=i2xp0
    dims    : O=1.000  P=1.000  L=0.731  C=0.790  R=1.000
    contrib : O=+0.000  P=+0.000  L=-4.508  C=-3.395  R=+0.000   sum=-7.9034
    zero-residual: S-100G=-7.9034  |diff|=3.30e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.2007  a_cal=0.0421  conf=0.9897  anchor=anchor-R2-52470f48253b25a6
    evidence (3 items, drill-down order):
      - [trace] latency_total            span=R2-00000-s00   value=14.2005     cell_median=11.9643     z=  +0.40 dev=0.1110
      - [trace] cost_total               span=R2-00000-s04   value=0.0134      cell_median=0.0121      z=  +0.20 dev=0.0901
      - [span ] dur                      span=R2-00000-s02   value=4.6048      peer_median=1.0540      z=  +3.95 dev=0.2564 (L3/L3span action=verify)
```

### 样本 B：latency_spike —— R2-00190

某一步耗时被放大 5~20 倍。看 SPAN TREE 里的 dur(s) 列和 share 条：其中一个子步骤吃掉了几乎全部壁钟时间。真值把 L 维打到 0.10，算法应该在 L 上扣分并把责任指向那个 Span。

```text
==============================================================================
TRACE R2-00190   [intent1: 解释 NE-7C29-11 在 15m 内发生劣化的劣化根因]
  ontology=ontA  session=sess-00039  turn=6/6  spans=5  wall=92.384s  ts_start=1767237923.441
  user_feedback: none captured
  answer_numbers=['6529']
  answer_facts  =['NE-7C29-11', '6529']
  golden_answer =
  golden_facts  =None
  goal_text     =劣化根因   query_lang=zh
  answer_citations  =['runbook://adn/alarm-clear-procedure#L12', 'runbook://adn/capacity-expansion#L25']
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[-0.2325, -0.2496, -0.2757, -0.1419] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run          92.384 ######### 341       118        0.00138 ok    stop
       in : 解释 NE-7C29-11 在 15m 内发生劣化的劣化根因
       out: 解释 NE-7C29-11 在 15m 内发生劣化的劣化根因 for NE-7C29-11: 6529
       meta: model=adn-llm-14b  facts=[6529]
       v3  : sys=154  cache_r=154  cost_det={cache_read:0.000116,completion:0.000708,prompt:0.000561}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan                0.870 #         786       108        0.00268 ok    stop
         in : task=劣化根因 ne=NE-7C29-11 window=15m; produce a step plan
         out: checked and recorded: step list drafted for NE-7C29-11;  candidate actio
         meta: model=adn-llm-14b  ttft=0.1243  pv=pv-2026-03
         v3  : sys=146  cache_r=146  cost_det={cache_read:0.00011,completion:0.000648,prompt:0.00192}  subgoal=围绕劣化根因执行拆解任务步骤
  `- s02           retrieval   retrieve_kb         1.116 #         627       0          0.00188 ok    -
         in : runbook search: 劣化根因 (ne=NE-7C29-11)
         out: knowledge hits ranked: 9478 4561 6529 (window 15m)
         meta: tool=kb.history_search  params={query:NE-7C29-11,top_k:10}  facts=[9478 4561 6529]
         v3  : cost_det={prompt:0.00188}  arg_valid=True  retrieved=[runbook://adn/alarm-clear-procedure#L12 runbook://adn/capacity-expansion#L25]
  `- s03           guard       verify              1.116 #         467       47         0.00168 ok    -
         in : policy check on pending action for NE-7C29-11
         out: policy evaluation on NE-7C29-11: pass
         v3  : cost_det={completion:0.000282,prompt:0.0014}  verifier=v_no_forbidden_action:PASS
  `- s04           llm         summarize          89.989 ######### 1025      292        0.00431 ok    stop
         in : write the final response for NE-7C29-11 from evidence 9478 4561 6529
         out: answer composed citing 9478 4561 6529; nothing further required
         meta: model=adn-llm-72b  ttft=24.2214  pv=pv-2026-03
         v3  : sys=230  cache_r=230  cost_det={cache_read:0.000172,completion:0.00175,prompt:0.00238}  verifier=v_numbers_traceable:PASS  subgoal=推进劣化根因：归纳证据

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['latency_spike']
    intent=i1  pattern=p3  cell=i1|p3
    oracle dim_dev : O=1.00  P=1.00  L=0.10  C=0.75  R=1.00
    latency_true=92.381s  gen_quantiles={'C': 0.4918, 'L': 0.4657}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=['R2-00190-s04']  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.0000  model_mix_true={'adn-llm-14b': 0.5067, 'adn-llm-72b': 0.4933}  feedback_available=False
    has_golden=False  key_fact_recall_true=n/a  fact_precision_true=n/a
    hallucinated_facts=[]
    query_lang_true=zh  session_turn_count_true=6  subgoal_count=2
    plan_revision_true=0  goal_drift_true=False  arg_valid_true=1.0000  verifier_pass_true=1.0000
    citation_reachable_true=1.0000  contradiction_true=0.0000  contradicted_count=0  fabricated_citation_count=0
    cache_read_true=530  cache_write_true=0  system_prompt_ratio_true=0.1633  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice4-v0.4.0)
    S=53.6935  G=1.00  grade_abs=D  grade_rel=D  tier=1  novelty=False
    alert=True (rule=False stat=True)  cold_start=False  cell=i2xp0
    dims    : O=1.000  P=1.000  L=0.000  C=0.791  R=1.000
    contrib : O=+0.000  P=+0.000  L=-43.695  C=-2.612  R=+0.000   sum=-46.3065
    zero-residual: S-100G=-46.3065  |diff|=5.00e-06  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.6912  a_cal=0.8824  conf=0.9897  anchor=anchor-R2-52470f48253b25a6
    evidence (3 items, drill-down order):
      - [trace] latency_total            span=R2-00190-s00   value=92.3837     cell_median=11.9643     z= +14.30 dev=0.6244
      - [trace] tokens_total             span=R2-00190-s04   value=3811.0000   cell_median=3469.5000   z=  +0.20 dev=0.0930
      - [span ] dur                      span=R2-00190-s04   value=89.9887     peer_median=4.0441      z= +26.03 dev=0.7761 (L3/L3span action=summarize)
```

### 样本 C：hallucinated_number（带 golden） —— R2-00251

最终答案里出现了检索证据中不存在的数字。对比子 Span 的 `out: evidence: ...` 与根 Span 的 `out: answer: ...`：后者多出了两个 5 位数。这是唯一一个靠文本内容判定的异常（`traceable_number_ratio` 特征）。

这条带 golden。看 GROUND TRUTH 里的 `fact_precision_true` 与 `key_fact_recall_true`：编造数字只压 precision，recall 仍为 1.00——答案里的事实都在，只是多了不该有的。`hallucinated_facts` 直接列出多出来的那几个。

```text
==============================================================================
TRACE R2-00251   [intent0: 查询网元 NE-1162-31 的当前告警清单]
  ontology=ontA  session=sess-00051  turn=2/4  spans=5  wall=1.031s  ts_start=1767241869.780
  user_feedback: none captured
  answer_numbers=['6858', '99021', '37507']
  answer_facts  =['NE-1162-31', '6858', '99021', '37507']
  golden_answer =expected answer for NE-1162-31 (查询网元 NE-1162-31 的当前告警清单): 6858
  golden_facts  =['NE-1162-31', '6858']
  goal_text     =当前告警清单   query_lang=zh
  answer_citations  =[]
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[-0.4207, 0.0074, 0.2219, 0.0636] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run           1.031 ######### 195       68         0.00066 ok    stop
       in : 查询网元 NE-1162-31 的当前告警清单
       out: answer to '查询网元 NE-1162-31 的当前告警清单' on NE-1162-31 over 5m: 6858, 99021, 
       meta: model=adn-llm-14b  facts=[6858 99021 37507]
       v3  : sys=146  cache_r=146  cost_det={cache_read:0.00011,completion:0.000408,prompt:0.000147}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan                0.472 ####      478       98         0.00155 ok    stop
         in : decompose request from NE-1162-31 over 5m into executable steps
         out: step list drafted for NE-1162-31;  candidate actions (window 5m)
         meta: model=adn-llm-72b  ttft=0.0526  pv=pv-2026-04-canary
         v3  : sys=210  cache_r=210  cost_det={cache_read:0.000158,completion:0.000588,prompt:0.000804}  subgoal=步骤目标：拆解任务步骤，服务于当前告警清单
  `- s02           tool        sql_query           0.123 #         0         0          0.00020 ok    -
         in : SELECT kpi_ts,value FROM perf_15min WHERE ne='NE-1162-31' AND window='5m
         out: rows returned: 6244 6858
         meta: tool=alarm_db.query  params={ne_id:NE-1162-31,severity:minor,time_window:5m}  facts=[6244 6858]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s03           guard       verify              0.385 ###       160       39         0.00071 ok    -
         in : policy check on pending action for NE-1162-31
         out: verdict pass for NE-1162-31
         v3  : cost_det={completion:0.000234,prompt:0.00048}  verifier=v_no_forbidden_action:PASS
  `- s04           llm         summarize           0.385 ###       491       122        0.00173 ok    stop
         in : write the final response for NE-1162-31 from evidence 6244 6858
         out: answer composed citing 6244 6858 (window 5m)
         meta: model=adn-llm-72b  ttft=0.0923  pv=pv-2026-04-canary
         v3  : sys=210  cache_r=210  cost_det={cache_read:0.000158,completion:0.000732,prompt:0.000843}  verifier=v_numbers_traceable:FAIL(answer number absent from the evidence pool)  subgoal=步骤目标：归纳证据，服务于当前告警清单

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['hallucinated_number']
    intent=i0  pattern=p1  cell=i0|p1
    oracle dim_dev : O=0.15  P=1.00  L=0.67  C=0.95  R=1.00
    latency_true=1.028s  gen_quantiles={'C': 0.1044, 'L': 0.662}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=[]  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.0000  model_mix_true={'adn-llm-14b': 0.1811, 'adn-llm-72b': 0.8189}  feedback_available=False
    has_golden=True  key_fact_recall_true=1.0000  fact_precision_true=0.5000
    hallucinated_facts=['37507', '99021']
    query_lang_true=zh  session_turn_count_true=4  subgoal_count=2
    plan_revision_true=0  goal_drift_true=False  arg_valid_true=1.0000  verifier_pass_true=0.6667
    citation_reachable_true=n/a  contradiction_true=0.0000  contradicted_count=0  fabricated_citation_count=0
    cache_read_true=566  cache_write_true=0  system_prompt_ratio_true=0.4275  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice4-v0.4.0)
    S=17.6541  G=0.25  grade_abs=D  grade_rel=D  tier=2  novelty=False
    alert=True (rule=True stat=False)  cold_start=False  cell=i1xp1
    dims    : O=0.446  P=1.000  L=0.847  C=0.997  R=1.000
    contrib : O=-6.811  P=+0.000  L=-0.525  C=-0.009  R=+0.000   sum=-7.3459
    zero-residual: S-100G=-7.3459  |diff|=2.00e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.9374  a_cal=1.0000  conf=0.9931  anchor=anchor-R2-52470f48253b25a6
    gates: {"t0_result_broken": 0.25}
    evidence (3 items, drill-down order):
      - [trace] traceable_number_ratio   span=-              value=0.3333      cell_median=1.0000      z= -50.00 dev=0.3512
      - [trace] branch_factor            span=-              value=4.0000      cell_median=3.0000      z=  +1.35 dev=0.0820
      - [span ] dur                      span=R2-00251-s03   value=0.3849      peer_median=0.1136      z=  +2.86 dev=0.2473 (L3/L3span action=verify)
```

### 样本 D：loop —— R2-00393

同一步骤被重复插入 3~5 次。SPAN TREE 里会看到连续多行相同 action，时间戳也相同（生成器直接复制了 Span）。

```text
==============================================================================
TRACE R2-00393   [intent1: 解释 NE-4231-31 在 24h 内发生劣化的劣化根因]
  ontology=ontA  session=sess-00080  turn=1/2  spans=9  wall=12.273s  ts_start=1767251070.975
  user_feedback: abandoned=False human_takeover=True retry=False thumbs=None
  answer_numbers=['2188', '8475']
  answer_facts  =['NE-4231-31', '2188', '8475']
  golden_answer =
  golden_facts  =None
  goal_text     =劣化根因   query_lang=zh
  answer_citations  =['doc://vendor/nbi-api-reference#L310', 'kb://history/incident-2026-0043']
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[-0.5233, -0.0917, -0.1419, 0.0712] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run          12.273 ######### 277       96         0.00201 ok    stop
       in : 解释 NE-4231-31 在 24h 内发生劣化的劣化根因
       out: completed '解释 NE-4231-31 在 24h 内发生劣化的劣化根因' on NE-4231-31; values: 2188, 
       meta: model=adn-llm-14b  facts=[2188 8475]
       v3  : sys=160  cache_w=160  cost_det={cache_write:0.0006,completion:0.000576,prompt:0.000831}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan                3.285 ##        985       456        0.00651 ok    stop
         in : decompose request from NE-4231-31 over 24h into executable steps
         out: decompose into retrieval then aggregation; window=24h; noted for the ope
         meta: model=adn-llm-72b  ttft=0.8890  pv=pv-2026-03
         v3  : sys=218  cache_w=218  cost_det={cache_write:0.000817,completion:0.00274,prompt:0.00296}  subgoal=在 NE-4231-31 上为劣化根因完成拆解任务步骤
  `- s02           retrieval   retrieve_kb         3.285 ##        404       0          0.00121 ok    -
         in : history search over incidents touching NE-4231-31
         out: knowledge hits ranked: 9161 9580 7721; nothing further required
         meta: tool=kb.history_search  params={query:NE-4231-31,top_k:-7}  facts=[9161 9580 7721]
         v3  : cost_det={prompt:0.00121}  arg_valid=False  retrieved=[doc://vendor/nbi-api-reference#L310 kb://history/incident-2026-0043]
  `- s03           tool        api_call            5.325 ####      0         0          0.00020 ok    -
         in : GET /nbi/v1/ne/NE-4231-31/status?detail=true
         out: response payload ids: 8799 8751 1331; nothing further required
         meta: tool=nbi.ne_status  params={ne_id:NE-4231-31,scope:subnetwork}  facts=[8799 8751 1331]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s04           tool        api_call            5.325 ####      0         0          0.00020 ok    -
         in : GET /nbi/v1/ne/NE-4231-31/alarms?window=24h
         out: response payload ids: 5732 1614 4535 2461
         meta: tool=nbi.ne_status  params={ne_id:NE-4231-31,scope:subnetwork}  facts=[5732 1614 4535 2461]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s05           tool        api_call            5.325 ####      0         0          0.00020 ok    -
         in : GET /nbi/v1/ne/NE-4231-31/alarms?window=24h
         out: response payload ids: 4415 5644; noted for the operator
         meta: tool=nbi.ne_status  params={ne_id:NE-4231-31,scope:subnetwork}  facts=[4415 5644]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s06           tool        api_call            5.325 ####      0         0          0.00020 ok    -
         in : GET /nbi/v1/ne/NE-4231-31/status?detail=true
         out: northbound returned objects 8475 5933 2188 6409; payload attached to the
         meta: tool=nbi.ne_status  params={ne_id:NE-4231-31,scope:subnetwork}  facts=[8475 5933 2188 6409]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s07           tool        api_call            5.325 ####      0         0          0.00020 ok    -
         in : GET /nbi/v1/ne/NE-4231-31/alarms?window=24h
         out: response payload ids: 4966 4630 5222 4042
         meta: tool=nbi.ne_status  params={ne_id:NE-4231-31,scope:subnetwork}  facts=[4966 4630 5222 4042]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s08           llm         summarize           3.063 ##        839       124        0.00294 ok    stop
         in : write the final response for NE-4231-31 from evidence 2188 6409 4966 463
         out: summary drafted from 2188 6409 4966 4630 5222 4042
         meta: model=adn-llm-14b  ttft=0.7719  pv=pv-2026-03
         v3  : sys=143  cache_r=143  cost_det={cache_read:0.000107,completion:0.000744,prompt:0.00209}  verifier=v_numbers_traceable:PASS  subgoal=推进劣化根因：归纳证据

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['loop']
    intent=i1  pattern=p3  cell=i1|p3
    oracle dim_dev : O=1.00  P=0.50  L=0.59  C=0.84  R=0.55
    latency_true=12.270s  gen_quantiles={'C': 0.3149, 'L': 0.8116}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=['R2-00393-s03', 'R2-00393-s04', 'R2-00393-s05', 'R2-00393-s06', 'R2-00393-s07']  human_label=None  drift_segment=None
    loop_true=True  mfr_true=0.0000  model_mix_true={'adn-llm-14b': 0.4811, 'adn-llm-72b': 0.5189}  feedback_available=True
    has_golden=False  key_fact_recall_true=n/a  fact_precision_true=n/a
    hallucinated_facts=[]
    query_lang_true=zh  session_turn_count_true=2  subgoal_count=2
    plan_revision_true=0  goal_drift_true=False  arg_valid_true=0.8333  verifier_pass_true=1.0000
    citation_reachable_true=1.0000  contradiction_true=0.0000  contradicted_count=0  fabricated_citation_count=0
    cache_read_true=143  cache_write_true=378  system_prompt_ratio_true=0.2080  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice4-v0.4.0)
    S=30.7769  G=0.35  grade_abs=D  grade_rel=D  tier=2  novelty=False
    alert=True (rule=True stat=False)  cold_start=False  cell=i2xp0
    dims    : O=1.000  P=0.850  L=0.790  C=0.790  R=0.775
    contrib : O=+0.000  P=-1.068  L=-1.158  C=-1.160  R=-0.837   sum=-4.2231
    zero-residual: S-100G=-4.2231  |diff|=4.70e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.9213  a_cal=0.9574  conf=0.9897  anchor=anchor-R2-52470f48253b25a6
    gates: {"loop_runaway": 0.35}
    evidence (3 items, drill-down order):
      - [trace] branch_factor            span=-              value=8.0000      cell_median=4.0000      z=  +2.70 dev=0.3624
      - [trace] loop_count               span=-              value=3.0000      cell_median=0.0000      z= +50.00 dev=0.3624
      - [span ] dur                      span=R2-00393-s03   value=5.3248      peer_median=2.0337      z=  +1.79 dev=0.2011 (L3/L3span action=api_call)
```

### 样本 E：token_bloat —— R2-00205

某个 LLM 步骤的 token 被放大 4~10 倍，耗时不变。只有成本维（C）会崩，时延维不崩——用来验证五维不会互相污染。

```text
==============================================================================
TRACE R2-00205   [intent0: 查询网元 NE-F75B-13 的当前告警清单]
  ontology=ontA  session=sess-00042  turn=6/6  spans=8  wall=0.749s  ts_start=1767238876.554
  user_feedback: none captured
  answer_numbers=['5898', '2066', '5660']
  answer_facts  =['NE-F75B-13', '5898', '2066', '5660']
  golden_answer =
  golden_facts  =None
  goal_text     =当前告警清单   query_lang=zh
  answer_citations  =['kb://history/incident-2025-1187']
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[-0.3844, -0.4293, 0.2574, 0.1212] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run           0.749 ######### 233       81         0.00069 ok    stop
       in : 查询网元 NE-F75B-13 的当前告警清单
       out: NE-F75B-13 | 查询网元 NE-F75B-13 的当前告警清单 | observed values 5898, 2066, 5660
       meta: model=adn-llm-72b  facts=[5898 2066 5660]
       v3  : sys=218  cache_r=218  cost_det={cache_read:0.000164,completion:0.000486,prompt:4.5e-05}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan                0.221 ###       350       194        0.00186 ok    stop
         in : decompose request from NE-F75B-13 over 5m into executable steps
         out: step list drafted for NE-F75B-13;  candidate actions; noted for the oper
         meta: model=adn-llm-14b  ttft=0.0130  pv=pv-2026-03
         v3  : sys=156  cache_r=156  cost_det={cache_read:0.000117,completion:0.00116,prompt:0.000582}  subgoal=在 NE-F75B-13 上为当前告警清单完成拆解任务步骤
  `- s02           guard       verify              0.221 ###       227       51         0.00099 ok    -
         in : compliance scan of the pending step set for NE-F75B-13
         out: verdict pass for NE-F75B-13
         v3  : cost_det={completion:0.000306,prompt:0.000681}  verifier=v_no_forbidden_action:PASS
  `- s03           tool        api_call            0.081 #         0         0          0.00020 ok    -
         in : GET /nbi/v1/ne/NE-F75B-13/status?detail=true
         out: northbound returned objects 2316 5660 5898 3769 (window 5m)
         meta: tool=nbi.ne_status  params={ne_id:NE-F75B-13,scope:subnetwork}  facts=[2316 5660 5898 3769]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s04           retrieval   schema_retrieval    0.067 #         472       0          0.00142 ok    -
         in : resolve table definitions needed by NE-F75B-13 query
         out: schema rows: 3301 2778 2333; nothing further required
         meta: tool=catalog.table_schema  level=WARNING  msg=partial result set returned  params={table:current_alarms}  facts=[3301 2778 2333]
         v3  : cost_det={prompt:0.00142}  arg_valid=True  retrieved=[kb://history/incident-2025-1187]
  `- s05           tool        sql_query           0.170 ##        0         0          0.00020 ok    -
         in : SELECT kpi_ts,value FROM perf_15min WHERE ne='NE-F75B-13' AND window='5m
         out: ok - rows returned: 7542 2066 2485 3154
         meta: tool=perf_db.query  level=WARNING  msg=partial result set returned  params={ne_id:NE-F75B-13,severity:minor,time_window:5m}  facts=[7542 2066 2485 315
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s06           guard       approve             0.029 #         259       5          0.00081 ok    -
         in : route the pending change on NE-F75B-13 to the approver
         out: approval gate pass on NE-F75B-13
         v3  : cost_det={completion:3e-05,prompt:0.000777}  verifier=v_no_forbidden_action:PASS
  `- s07           llm         summarize           0.136 ##        5662      1364       0.02484 ok    stop
         in : condense evidence 2778 2333 7542 2066 2485 3154 into an operator-facing 
         out: ok - answer composed citing 2778 2333 7542 2066 2485 3154
         meta: model=adn-llm-14b  ttft=0.0074  pv=pv-2026-03
         v3  : sys=148  cache_r=148  cost_det={cache_read:0.000111,completion:0.00818,prompt:0.0165}  verifier=v_numbers_traceable:PASS  subgoal=为当前告警清单归纳证据

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['token_bloat']
    intent=i0  pattern=p2  cell=i0|p2
    oracle dim_dev : O=1.00  P=1.00  L=0.94  C=0.12  R=1.00
    latency_true=0.746s  gen_quantiles={'C': 0.1924, 'L': 0.1142}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=['R2-00205-s07']  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.0000  model_mix_true={'adn-llm-14b': 0.9602, 'adn-llm-72b': 0.0398}  feedback_available=False
    has_golden=False  key_fact_recall_true=n/a  fact_precision_true=n/a
    hallucinated_facts=[]
    query_lang_true=zh  session_turn_count_true=6  subgoal_count=2
    plan_revision_true=0  goal_drift_true=False  arg_valid_true=1.0000  verifier_pass_true=1.0000
    citation_reachable_true=1.0000  contradiction_true=0.0000  contradicted_count=0  fabricated_citation_count=0
    cache_read_true=522  cache_write_true=0  system_prompt_ratio_true=0.0725  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice4-v0.4.0)
    S=78.7204  G=1.00  grade_abs=B  grade_rel=D  tier=0  novelty=False
    alert=False (rule=False stat=False)  cold_start=False  cell=i1xp2
    dims    : O=1.000  P=1.000  L=0.944  C=0.215  R=1.000
    contrib : O=+0.000  P=+0.000  L=-0.767  C=-20.513  R=+0.000   sum=-21.2796
    zero-residual: S-100G=-21.2796  |diff|=4.70e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.3178  a_cal=0.1351  conf=0.9815  anchor=anchor-R2-52470f48253b25a6
    evidence (3 items, drill-down order):
      - [trace] branch_factor            span=-              value=7.0000      cell_median=4.0000      z=  +2.02 dev=0.3326
      - [trace] tokens_total             span=R2-00205-s07   value=8898.0000   cell_median=3315.0000   z=  +3.60 dev=0.3096
      - [span ] tok                      span=R2-00205-s07   value=7026.0000   peer_median=1066.0000   z= +11.23 dev=0.5485 (L3/L3span action=summarize)
```

### 样本 F：illegal_step —— R2-00090

插入了本体禁止的动作（如 `force_delete` / `skip_approval_execute`）。这是确定性违规，走规则闸门（alert_rule=True）而不是统计异常。

```text
==============================================================================
TRACE R2-00090   [intent0: 请列出网元 NE-89AB-49 当前告警清单中的每一条记录]
  ontology=ontA  session=sess-00020  turn=4/6  spans=9  wall=0.419s  ts_start=1767231419.899
  user_feedback: none captured
  answer_numbers=['7963', '1225', '6823']
  answer_facts  =['NE-89AB-49', '7963', '1225', '6823']
  golden_answer =
  golden_facts  =None
  goal_text     =当前告警清单   query_lang=zh
  answer_citations  =['kb://history/incident-2025-1187', 'runbook://adn/ne-health-check#L48']
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[-0.0985, -0.3279, 0.2867, 0.1762] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run           0.419 ######### 179       62         0.00059 ok    stop
       in : 请列出网元 NE-89AB-49 当前告警清单中的每一条记录
       out: here is the outcome of '请列出网元 NE-89AB-49 当前告警清单中的每一条记录' on NE-89AB-49 - 
       meta: model=adn-llm-14b  facts=[7963 1225 6823]
       v3  : sys=142  cache_r=142  cost_det={cache_read:0.000107,completion:0.000372,prompt:0.000111}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan                0.319 #######   554       137        0.00196 ok    stop
         in : task=当前告警清单 ne=NE-89AB-49 window=15m; produce a step plan
         out: ok - step list drafted for NE-89AB-49;  candidate actions
         meta: model=adn-llm-72b  ttft=0.0937  pv=pv-2026-03
         v3  : sys=233  cache_r=233  cost_det={cache_read:0.000175,completion:0.000822,prompt:0.000963}  subgoal=推进当前告警清单：拆解任务步骤
  `- s02           retrieval   schema_retrieval    0.015 #         293       0          0.00088 ok    -
         in : lookup schema for alarm tables of NE-89AB-49
         out: schema rows: 6483 6224 2010 5396; payload attached to the trace
         meta: tool=catalog.table_schema  level=WARNING  msg=slow query above soft limit  params={table:not-in-enum}  facts=[6483 6224 2010 5396]
         v3  : cost_det={prompt:0.000879}  arg_valid=False  retrieved=[kb://history/incident-2025-1187 runbook://adn/ne-health-check#L48]
  `- s05           tool        sql_query           0.015 #         0         0          0.00020 ok    -
         in : SELECT kpi_ts,value FROM perf_15min WHERE ne='NE-89AB-49' AND window='15
         out: query settled; row ids 1225 6823 7051
         meta: tool=alarm_db.query  params={ne_id:legacy-id-9931,severity:minor,time_window:15m}  facts=[1225 6823 7051]
         v3  : cost_det={tool_call:0.0002}  arg_valid=False
  `- s03           tool        force_delete        0.027 #         0         0          0.00020 ok    -
         in : drop records on NE-89AB-49 skipping the ticket flow
         out: objects removed on NE-89AB-49: 6048 9537 7963 5574 (window 15m)
         meta: tool=nbi.ne_force_delete  facts=[6048 9537 7963 5574]
         v3  : cost_det={tool_call:0.0002}
    `- s03-n1        tool        force_delete        0.016 #         0         0          0.00020 ok    -
           in : nested force_delete call for NE-89AB-49
           out: objects removed on NE-89AB-49: 6048 9537 7963 5574 (window 15m)
           meta: tool=nbi.ne_force_delete  facts=[6048 9537 7963 5574]
           v3  : cost_det={tool_call:0.0002}
  `- s04           guard       verify              0.013 #         167       35         0.00071 ok    -
         in : compliance scan of the pending step set for NE-89AB-49
         out: policy evaluation on NE-89AB-49: block - policy violation
         meta: level=WARNING  msg=slow query above soft limit
         v3  : cost_det={completion:0.00021,prompt:0.000501}  verifier=v_no_forbidden_action:FAIL(forbidden action before gate: force_delete)
  `- s06           guard       verify              0.052 #         153       46         0.00073 ok    -
         in : policy check on pending action for NE-89AB-49
         out: policy evaluation on NE-89AB-49: pass
         v3  : cost_det={completion:0.000276,prompt:0.000459}  verifier=v_no_forbidden_action:FAIL(forbidden action before gate: force_delete)
  `- s07           llm         summarize           0.052 #         511       157        0.00212 ok    stop
         in : condense evidence 9537 7963 5574 1225 6823 7051 into an operator-facing 
         out: checked and recorded: answer composed citing 9537 7963 5574 1225 6823 70
         meta: model=adn-llm-14b  ttft=0.0094  pv=pv-2026-03
         v3  : sys=160  cache_r=160  cost_det={cache_read:0.00012,completion:0.000942,prompt:0.00105}  verifier=v_numbers_traceable:PASS  subgoal=推进当前告警清单：归纳证据

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['illegal_step']
    intent=i0  pattern=p2  cell=i0|p2
    oracle dim_dev : O=1.00  P=0.05  L=0.82  C=0.96  R=1.00
    latency_true=0.416s  gen_quantiles={'C': 0.0735, 'L': 0.3607}
    process_flags={'illegal_step': True, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=['R2-00090-s03']  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.0282  model_mix_true={'adn-llm-14b': 0.5681, 'adn-llm-72b': 0.4319}  feedback_available=False
    has_golden=False  key_fact_recall_true=n/a  fact_precision_true=n/a
    hallucinated_facts=[]
    query_lang_true=zh  session_turn_count_true=6  subgoal_count=2
    plan_revision_true=0  goal_drift_true=False  arg_valid_true=0.0000  verifier_pass_true=0.5000
    citation_reachable_true=1.0000  contradiction_true=0.0000  contradicted_count=0  fabricated_citation_count=0
    cache_read_true=535  cache_write_true=0  system_prompt_ratio_true=0.2881  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice4-v0.4.0)
    S=4.1560  G=0.04  grade_abs=D  grade_rel=D  tier=2  novelty=False
    alert=True (rule=True stat=False)  cold_start=False  cell=i1xp2
    dims    : O=1.000  P=0.700  L=1.000  C=0.947  R=1.000
    contrib : O=+0.000  P=-0.309  L=+0.000  C=-0.035  R=+0.000   sum=-0.3440
    zero-residual: S-100G=-0.3440  |diff|=4.00e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.8939  a_cal=0.8824  conf=0.9677  anchor=anchor-R2-52470f48253b25a6
    gates: {"forbidden_action": 0.3, "guard_violation": 0.15}
    evidence (3 items, drill-down order):
      - [trace] guard_hits               span=-              value=1.0000      cell_median=0.0000      z= +50.00 dev=0.3673
      - [trace] n_spans                  span=-              value=9.0000      cell_median=6.0000      z=  +2.02 dev=0.3477
      - [span ] dur                      span=R2-00090-s01   value=0.3192      peer_median=0.2654      z=  +0.27 dev=0.1041 (L3/L3span action=plan)
```

### 样本 G：truncation（带 golden） —— R2-01190

根 Span 的 `finish_reason=length`，答案被截断，结果维（O）重罚。

这条带 golden。与上一个样本对着看：截断只压 `key_fact_recall_true`，precision 仍为 1.00——说出来的都对，只是没说完。生成器故意把“不完整”与“不忠实”做成可分离的两类，否则O 维会把两种完全不同的失败打成同一个分。

```text
==============================================================================
TRACE R2-01190   [intent1: 定位网元 NE-000A-27 的劣化根因]
  ontology=ontA  session=sess-00263  turn=1/3  spans=5  wall=16.861s  ts_start=1767302719.457
  user_feedback: none captured
  answer_numbers=['2823', '1544', '65']
  answer_facts  =['NE-000A-27', '2823', '1544', '65']
  golden_answer =expected answer for NE-000A-27 (定位网元 NE-000A-27 的劣化根因): 2823, 1544, 5539
  golden_facts  =['NE-000A-27', '2823', '1544', '5539']
  goal_text     =劣化根因   query_lang=zh
  answer_citations  =['doc://vendor/nbi-api-reference#L1020']
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[-0.3022, -0.2582, -0.1573, 0.1381] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run          16.861 ######### 261       91         0.00192 ok    length
       in : 定位网元 NE-000A-27 的劣化根因
       out: operator summary for NE-000A-27 (定位网元 NE-000A-27 的劣化根因): 2823, 1544, 65
       meta: model=adn-llm-14b  facts=[2823 1544 65]
       v3  : sys=158  cache_w=158  cost_det={cache_write:0.000593,completion:0.000546,prompt:0.000783}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan                5.642 ###       721       102        0.00358 ok    stop
         in : decompose request from NE-000A-27 over 15m into executable steps
         out: step done - step list drafted for NE-000A-27;  candidate actions
         meta: model=adn-llm-72b  ttft=1.4396  pv=pv-2026-03
         v3  : sys=215  cache_w=215  cost_det={cache_write:0.000806,completion:0.000612,prompt:0.00216}  subgoal=为劣化根因拆解任务步骤
  `- s02           guard       verify              1.246 #         230       33         0.00089 ok    -
         in : policy check on pending action for NE-000A-27
         out: policy evaluation on NE-000A-27: pass
         v3  : cost_det={completion:0.000198,prompt:0.00069}  verifier=v_no_forbidden_action:PASS
  `- s03           tool        sql_query           1.246 #         0         0          0.00020 ok    -
         in : SELECT kpi_ts,value FROM perf_15min WHERE ne='NE-000A-27' AND window='15
         out: ok - query settled; row ids 5597 1544 4841 2823
         meta: tool=alarm_db.query  params={ne_id:NE-000A-27,severity:major,time_window:15m}  facts=[5597 1544 4841 2823]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s04           llm         summarize           9.362 #####     477       295        0.00284 ok    stop
         in : condense evidence 5597 1544 4841 2823 into an operator-facing answer
         out: summary drafted from 5597 1544 4841 2823; nothing further required
         meta: model=adn-llm-14b  ttft=2.6299  pv=pv-2026-03
         v3  : sys=159  cache_r=159  cost_det={cache_read:0.000119,completion:0.00177,prompt:0.000954}  verifier=v_numbers_traceable:FAIL(answer number absent from the evidence pool)  subgoal=步骤目标：归纳证据，服务于劣化根因

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['truncation']
    intent=i1  pattern=p1  cell=i1|p1
    oracle dim_dev : O=0.35  P=1.00  L=0.59  C=0.87  R=1.00
    latency_true=16.858s  gen_quantiles={'C': 0.2694, 'L': 0.8223}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=[]  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.0000  model_mix_true={'adn-llm-14b': 0.5773, 'adn-llm-72b': 0.4227}  feedback_available=False
    has_golden=True  key_fact_recall_true=0.7500  fact_precision_true=0.7500
    hallucinated_facts=['65']
    query_lang_true=zh  session_turn_count_true=3  subgoal_count=2
    plan_revision_true=0  goal_drift_true=False  arg_valid_true=1.0000  verifier_pass_true=0.6667
    citation_reachable_true=0.0000  contradiction_true=0.0000  contradicted_count=0  fabricated_citation_count=1
    cache_read_true=159  cache_write_true=373  system_prompt_ratio_true=0.3150  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice4-v0.4.0)
    S=19.1061  G=0.25  grade_abs=D  grade_rel=D  tier=2  novelty=False
    alert=True (rule=True stat=False)  cold_start=False  cell=i2xp1
    dims    : O=0.640  P=1.000  L=0.623  C=0.879  R=1.000
    contrib : O=-3.915  P=+0.000  L=-1.554  C=-0.425  R=+0.000   sum=-5.8939
    zero-residual: S-100G=-5.8939  |diff|=4.80e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.9184  a_cal=0.9420  conf=0.9691  anchor=anchor-R2-52470f48253b25a6
    gates: {"t0_result_broken": 0.25}
    evidence (3 items, drill-down order):
      - [trace] traceable_number_ratio   span=-              value=0.6667      cell_median=1.0000      z= -50.00 dev=0.3649
      - [trace] latency_total            span=R2-01190-s00   value=16.8610     cell_median=11.4135     z=  +0.96 dev=0.1841
      - [span ] dur                      span=R2-01190-s04   value=9.3623      peer_median=3.4707      z=  +1.97 dev=0.2220 (L3/L3span action=summarize)
```

### 样本 H：missing_step —— R2-00032

本体要求的必须步骤被删掉一个，过程维（P）扣分。

```text
==============================================================================
TRACE R2-00032   [intent0: list every entry in the current alarm list of network element NE-273E-38]
  ontology=ontA  session=sess-00005  turn=5/5  spans=3  wall=0.918s  ts_start=1767227665.206
  user_feedback: abandoned=True human_takeover=True retry=False thumbs=-1
  answer_numbers=[]
  answer_facts  =[]
  golden_answer =
  golden_facts  =None
  goal_text     =current alarm list   query_lang=en
  answer_citations  =[]
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[-0.3814, -0.146, 0.1449, 0.0683] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run           0.918 ######### 373       149        0.00167 ok    stop
       in : list every entry in the current alarm list of network element NE-273E-38
       out: list every entry in the current alarm list of network element NE-273E-38
       meta: model=adn-llm-14b
       v3  : sys=152  cache_r=152  cost_det={cache_read:0.000114,completion:0.000894,prompt:0.000663}  verifier=v_answer_nonempty:PASS
  `- s01           tool        sql_query           0.433 ####      0         0          0.00020 ok    -
         in : SELECT kpi_ts,value FROM perf_15min WHERE ne='NE-273E-38' AND window='24
         out: checked and recorded: rows returned: 5464 9989
         meta: tool=alarm_db.query  params={ne_id:NE-273E-38,severity:critical,time_window:24h}  facts=[5464 9989]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s02           llm         summarize           0.458 ####      1033      313        0.00452 ok    stop
         in : condense evidence 5464 9989 into an operator-facing answer
         out: attempt finished, summary drafted from 5464 9989
         meta: model=adn-llm-72b  ttft=0.0391  pv=pv-2026-03
         v3  : sys=204  cache_r=204  cost_det={cache_read:0.000153,completion:0.00188,prompt:0.00249}  verifier=v_numbers_traceable:PASS  subgoal=page through archived warehouse stock records

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['missing_step']
    intent=i0  pattern=p1  cell=i0|p1
    oracle dim_dev : O=1.00  P=0.80  L=0.87  C=0.66  R=1.00
    latency_true=0.915s  gen_quantiles={'C': 0.6872, 'L': 0.2669}
    process_flags={'illegal_step': False, 'missing_step': True, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=[]  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.0000  model_mix_true={'adn-llm-14b': 0.2794, 'adn-llm-72b': 0.7206}  feedback_available=True
    has_golden=False  key_fact_recall_true=n/a  fact_precision_true=n/a
    hallucinated_facts=[]
    query_lang_true=en  session_turn_count_true=5  subgoal_count=1
    plan_revision_true=0  goal_drift_true=True  arg_valid_true=1.0000  verifier_pass_true=1.0000
    citation_reachable_true=n/a  contradiction_true=n/a  contradicted_count=0  fabricated_citation_count=0
    cache_read_true=356  cache_write_true=0  system_prompt_ratio_true=0.2532  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice4-v0.4.0)
    S=93.6818  G=1.00  grade_abs=A  grade_rel=B  tier=2  novelty=False
    alert=True (rule=True stat=False)  cold_start=False  cell=i1xp1
    dims    : O=1.000  P=0.838  L=0.883  C=0.967  R=1.000
    contrib : O=+0.000  P=-3.790  L=-1.994  C=-0.535  R=+0.000   sum=-6.3182
    zero-residual: S-100G=-6.3182  |diff|=1.70e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.8645  a_cal=0.8824  conf=0.9931  anchor=anchor-R2-52470f48253b25a6
    evidence (3 items, drill-down order):
      - [trace] latency_total            span=R2-00032-s00   value=0.9179      cell_median=1.1789      z=  -0.50 dev=0.0415
      - [trace] tokens_total             span=R2-00032-s02   value=1868.0000   cell_median=2911.0000   z=  -0.78 dev=0.0213
      - [span ] dur                      span=R2-00032-s01   value=0.4333      peer_median=0.2118      z=  +1.30 dev=0.1572 (L3/L3span action=sql_query)
```

## 六、v3 共生缺陷样本（附录 A 新增特征的原始证据）

下面这些**不是**独立的异常类型，而是叠加在已异常轨迹上的共生缺陷。每一个都由
`bench/coverage.truth_agreement()` 在全部轨迹上做双向等价校验（内核特征 ⟺ 生成器真值），
任何一条对不上都会让构建直接失败，而不是只在报告里留一行警告。


### v3 样本 A：plan_revision —— R2-00027

入口步骤（ontA 的 `plan`、ontB 的 `intent_parse`）出现了两次，第二次的时间区间**嵌套在**第一次之内——智能体在一步还没走完时就重开了计划。`kernel/cluster.collapse()` 会折叠相邻重复，所以模式视图看到的骨架完全不变，只有 `plan_revision_count` 能看见它。这也是该特征被定义成“时间包含”而不是“计数减一”的原因：循环注入器同样可能选中入口步骤，计数减一会把一次循环读成两次计划修订。

```text
==============================================================================
TRACE R2-00027   [intent2: prepare and validate a configuration change plan on NE-1F3B-06 before the maintenance window]
  ontology=ontA  session=sess-00004  turn=6/6  spans=7  wall=68.922s  ts_start=1767227363.377
  user_feedback: none captured
  answer_numbers=['2837']
  answer_facts  =['NE-1F3B-06', '2837']
  golden_answer =expected answer for NE-1F3B-06 (prepare and validate a configuration change plan on NE-1F3B-06 before the maintenance window): 2837
  golden_facts  =['NE-1F3B-06', '2837']
  goal_text     =configuration change plan   query_lang=en
  answer_citations  =['doc://policy/change-approval-rules#L7']
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[-0.431, -0.2679, -0.5932, -0.2072] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run          68.922 ######### 500       200        0.00234 ok    stop
       in : prepare and validate a configuration change plan on NE-1F3B-06 before th
       out: operator summary for NE-1F3B-06 (prepare and validate a configuration ch
       meta: model=adn-llm-14b  facts=[2837]
       v3  : sys=159  cache_r=159  cost_det={cache_read:0.000119,completion:0.0012,prompt:0.00102}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan               40.375 #####     527       377        0.00353 ok    stop
         in : decompose request from NE-1F3B-06 over 15m into executable steps
         out: decompose into retrieval then aggregation; window=15m; nothing further r
         meta: model=adn-llm-14b  ttft=5.0715  pv=pv-2026-03
         v3  : sys=139  cache_r=139  cost_det={cache_read:0.000104,completion:0.00226,prompt:0.00116}  subgoal=decomposing the task steps for the configuration change plan
  `- s02           llm         plan               16.150 ##        914       662        0.00637 ok    stop
         in : decompose request from NE-1F3B-06 over 15m into executable steps
         out: step list drafted for NE-1F3B-06;  candidate actions; payload attached t
         meta: model=adn-llm-14b  ttft=3.9324  pv=pv-2026-03
         v3  : sys=155  cache_r=155  cost_det={cache_read:0.000116,completion:0.00397,prompt:0.00228}  subgoal=decomposing the task steps within 15m for the configuration 
  `- s03           guard       verify              8.080 #         395       105        0.00182 ok    -
         in : policy check on pending action for NE-1F3B-06
         out: policy evaluation on NE-1F3B-06: pass
         v3  : cost_det={completion:0.00063,prompt:0.00119}  verifier=v_no_forbidden_action:PASS
  `- s04           retrieval   schema_retrieval    0.695 #         684       0          0.00205 ok    -
         in : resolve table definitions needed by NE-1F3B-06 query
         out: checked and recorded: table metadata resolved: 5270 2837 6433
         meta: tool=catalog.table_schema  params={table:kpi_15min}  facts=[5270 2837 6433]
         v3  : cost_det={prompt:0.00205}  arg_valid=True  retrieved=[doc://policy/change-approval-rules#L7]
  `- s05           tool        sql_query           0.695 #         0         0          0.00020 ok    -
         in : SELECT alarm_id,severity FROM current_alarms WHERE ne='NE-1F3B-06' AND w
         out: query settled; row ids 5514 7722; noted for the operator
         meta: tool=alarm_db.query  params={ne_id:NE-1F3B-06,severity:critical,time_window:15m}  facts=[5514 7722]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s06           llm         summarize          16.686 ##        864       470        0.00505 ok    stop
         in : write the final response for NE-1F3B-06 from evidence 5270 2837 6433 551
         out: summary drafted from 5270 2837 6433 5514 7722; payload attached to the t
         meta: model=adn-llm-14b  ttft=1.6177  pv=pv-2026-03
         v3  : sys=162  cache_r=162  cost_det={cache_read:0.000121,completion:0.00282,prompt:0.00211}  verifier=v_numbers_traceable:PASS  subgoal=condensing the evidence on NE-1F3B-06 as part of the configu

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=False  anomaly_types=[]
    intent=i2  pattern=p2  cell=i2|p2
    oracle dim_dev : O=1.00  P=1.00  L=0.74  C=0.56  R=1.00
    latency_true=68.919s  gen_quantiles={'C': 0.8723, 'L': 0.5171}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=[]  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.0000  model_mix_true={'adn-llm-14b': 1.0}  feedback_available=False
    has_golden=True  key_fact_recall_true=1.0000  fact_precision_true=1.0000
    hallucinated_facts=[]
    query_lang_true=en  session_turn_count_true=6  subgoal_count=3
    plan_revision_true=1  goal_drift_true=False  arg_valid_true=1.0000  verifier_pass_true=1.0000
    citation_reachable_true=1.0000  contradiction_true=0.0000  contradicted_count=0  fabricated_citation_count=0
    cache_read_true=615  cache_write_true=0  system_prompt_ratio_true=0.1583  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice4-v0.4.0)
    S=88.2029  G=1.00  grade_abs=B  grade_rel=C  tier=0  novelty=False
    alert=False (rule=False stat=False)  cold_start=False  cell=i0xp2
    dims    : O=1.000  P=1.000  L=0.791  C=0.547  R=1.000
    contrib : O=+0.000  P=+0.000  L=-3.297  C=-8.500  R=+0.000   sum=-11.7971
    zero-residual: S-100G=-11.7971  |diff|=4.70e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.2009  a_cal=0.0421  conf=0.9832  anchor=anchor-R2-52470f48253b25a6
    evidence (3 items, drill-down order):
      - [trace] cost_total               span=R2-00027-s02   value=0.0214      cell_median=0.0118      z=  +1.60 dev=0.2045
      - [trace] tokens_total             span=R2-00027-s02   value=5698.0000   cell_median=3232.5000   z=  +1.63 dev=0.1987
      - [span ] dur                      span=R2-00027-s01   value=40.3752     peer_median=16.1738     z=  +1.87 dev=0.2157 (L3/L3span action=plan)
```

### v3 样本 B：goal_drift —— R2-00032

某个 `subgoal_text` 与本条轨迹的 `goal_text` **没有任何内容词重叠**——智能体在这一步跑偏了。特征侧用词元包含率 `1 - |G ∩ S| / |G|` 度量：跑偏时恰好为 1.0，在轨时恰好为 0.0，所以 `goal_drift_max >= 0.5` 与真值构成严格的双向等价。生成器为此专门过滤掉任何与目标共享词元的绕路模板，否则真值会声称漂移而数据里量不出来。

```text
==============================================================================
TRACE R2-00032   [intent0: list every entry in the current alarm list of network element NE-273E-38]
  ontology=ontA  session=sess-00005  turn=5/5  spans=3  wall=0.918s  ts_start=1767227665.206
  user_feedback: abandoned=True human_takeover=True retry=False thumbs=-1
  answer_numbers=[]
  answer_facts  =[]
  golden_answer =
  golden_facts  =None
  goal_text     =current alarm list   query_lang=en
  answer_citations  =[]
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[-0.3814, -0.146, 0.1449, 0.0683] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run           0.918 ######### 373       149        0.00167 ok    stop
       in : list every entry in the current alarm list of network element NE-273E-38
       out: list every entry in the current alarm list of network element NE-273E-38
       meta: model=adn-llm-14b
       v3  : sys=152  cache_r=152  cost_det={cache_read:0.000114,completion:0.000894,prompt:0.000663}  verifier=v_answer_nonempty:PASS
  `- s01           tool        sql_query           0.433 ####      0         0          0.00020 ok    -
         in : SELECT kpi_ts,value FROM perf_15min WHERE ne='NE-273E-38' AND window='24
         out: checked and recorded: rows returned: 5464 9989
         meta: tool=alarm_db.query  params={ne_id:NE-273E-38,severity:critical,time_window:24h}  facts=[5464 9989]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s02           llm         summarize           0.458 ####      1033      313        0.00452 ok    stop
         in : condense evidence 5464 9989 into an operator-facing answer
         out: attempt finished, summary drafted from 5464 9989
         meta: model=adn-llm-72b  ttft=0.0391  pv=pv-2026-03
         v3  : sys=204  cache_r=204  cost_det={cache_read:0.000153,completion:0.00188,prompt:0.00249}  verifier=v_numbers_traceable:PASS  subgoal=page through archived warehouse stock records

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['missing_step']
    intent=i0  pattern=p1  cell=i0|p1
    oracle dim_dev : O=1.00  P=0.80  L=0.87  C=0.66  R=1.00
    latency_true=0.915s  gen_quantiles={'C': 0.6872, 'L': 0.2669}
    process_flags={'illegal_step': False, 'missing_step': True, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=[]  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.0000  model_mix_true={'adn-llm-14b': 0.2794, 'adn-llm-72b': 0.7206}  feedback_available=True
    has_golden=False  key_fact_recall_true=n/a  fact_precision_true=n/a
    hallucinated_facts=[]
    query_lang_true=en  session_turn_count_true=5  subgoal_count=1
    plan_revision_true=0  goal_drift_true=True  arg_valid_true=1.0000  verifier_pass_true=1.0000
    citation_reachable_true=n/a  contradiction_true=n/a  contradicted_count=0  fabricated_citation_count=0
    cache_read_true=356  cache_write_true=0  system_prompt_ratio_true=0.2532  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice4-v0.4.0)
    S=93.6818  G=1.00  grade_abs=A  grade_rel=B  tier=2  novelty=False
    alert=True (rule=True stat=False)  cold_start=False  cell=i1xp1
    dims    : O=1.000  P=0.838  L=0.883  C=0.967  R=1.000
    contrib : O=+0.000  P=-3.790  L=-1.994  C=-0.535  R=+0.000   sum=-6.3182
    zero-residual: S-100G=-6.3182  |diff|=1.70e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.8645  a_cal=0.8824  conf=0.9931  anchor=anchor-R2-52470f48253b25a6
    evidence (3 items, drill-down order):
      - [trace] latency_total            span=R2-00032-s00   value=0.9179      cell_median=1.1789      z=  -0.50 dev=0.0415
      - [trace] tokens_total             span=R2-00032-s02   value=1868.0000   cell_median=2911.0000   z=  -0.78 dev=0.0213
      - [span ] dur                      span=R2-00032-s01   value=0.4333      peer_median=0.2118      z=  +1.30 dev=0.1572 (L3/L3span action=sql_query)
```

### v3 样本 C：invalid_tool_arg —— R2-00047

工具入参违反了本体的 `param_schema`（枚举越界 / 前缀不符）。`arg_valid` 是**测量**出来的而不是断言的：生成器构造完违规参数后会再跑一次同一个校验函数，只有确实判为违规才落库。循环与重试的副本共享同一份参数，所以一个违规组里的每个副本都同样违规——这是刻意的，否则 `(parent, action, 参数哈希)` 分组会被拆开，一个真循环就悄悄变成了非循环。

```text
==============================================================================
TRACE R2-00047   [intent2: write the configuration change plan for NE-9E26-42 and list the impacted objects]
  ontology=ontA  session=sess-00011  turn=2/4  spans=7  wall=106.220s  ts_start=1767228639.327
  user_feedback: none captured
  answer_numbers=['3984', '6990']
  answer_facts  =['NE-9E26-42', '3984', '6990']
  golden_answer =expected answer for NE-9E26-42 (write the configuration change plan for NE-9E26-42 and list the impacted objects): 3984, 6990
  golden_facts  =['NE-9E26-42', '3984', '6990']
  goal_text     =configuration change plan   query_lang=en
  answer_citations  =['doc://policy/change-approval-rules#L7', 'kb://history/incident-2026-0043']
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[-0.319, 0.1272, -0.699, -0.1081] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run         106.220 ######### 137       55         0.00043 ok    stop
       in : write the configuration change plan for NE-9E26-42 and list the impacted
       out: completed 'write the configuration change plan for NE-9E26-42 and list t
       meta: model=adn-llm-72b  facts=[3984 6990]
       v3  : sys=137  cache_r=137  cost_det={cache_read:0.000103,completion:0.00033}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan               25.936 ##        289       236        0.00195 ok    stop
         in : decompose request from NE-9E26-42 over 1h into executable steps
         out: decompose into retrieval then aggregation; window=1h; payload attached t
         meta: model=adn-llm-14b  ttft=7.5468  pv=pv-2026-03
         v3  : sys=150  cache_r=150  cost_det={cache_read:0.000112,completion:0.00142,prompt:0.000417}  subgoal=advance the configuration change plan by decomposing the tas
  `- s02           retrieval   schema_retrieval    8.354 #         83        0          0.00025 ok    -
         in : resolve table definitions needed by NE-9E26-42 query
         out: step done - schema rows: 6990 4781
         meta: tool=catalog.table_schema  params={table:alarm_history}  facts=[6990 4781]
         v3  : cost_det={prompt:0.000249}  arg_valid=True  retrieved=[doc://policy/change-approval-rules#L7 kb://history/incident-2026-0043]
  `- s03           tool        sql_query          10.729 #         0         0          0.00020 ok    -
         in : SELECT alarm_id,severity FROM current_alarms WHERE ne='NE-9E26-42' AND w
         out: rows returned: 8284 3984
         meta: tool=alarm_db.query  params={ne_id:NE-9E26-42,severity:not-in-enum,time_window:1h}  facts=[8284 3984]
         v3  : cost_det={tool_call:0.0002}  arg_valid=False
  `- s04           guard       approve             5.447 #         77        16         0.00033 ok    -
         in : route the pending change on NE-9E26-42 to the approver
         out: approval gate pass on NE-9E26-42
         meta: level=WARNING  msg=slow query above soft limit
         v3  : cost_det={completion:9.6e-05,prompt:0.000231}  verifier=v_no_forbidden_action:PASS
  `- s05           guard       verify              6.554 #         151       34         0.00066 ok    -
         in : compliance scan of the pending step set for NE-9E26-42
         out: verdict pass for NE-9E26-42
         v3  : cost_det={completion:0.000204,prompt:0.000453}  verifier=v_no_forbidden_action:PASS
  `- s06           llm         summarize          44.068 ####      290       238        0.00181 ok    stop
         in : condense evidence 6990 4781 8284 3984 into an operator-facing answer
         out: attempt finished, summary drafted from 6990 4781 8284 3984
         meta: model=adn-llm-72b  ttft=8.0109  pv=pv-2026-03
         v3  : sys=216  cache_r=216  cost_det={cache_read:0.000162,completion:0.00143,prompt:0.000222}  verifier=v_numbers_traceable:PASS  subgoal=step goal: condensing the evidence, serving the configuratio

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=False  anomaly_types=[]
    intent=i2  pattern=p2  cell=i2|p2
    oracle dim_dev : O=1.00  P=1.00  L=0.66  C=0.98  R=1.00
    latency_true=106.217s  gen_quantiles={'C': 0.0416, 'L': 0.6713}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=[]  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.0000  model_mix_true={'adn-llm-14b': 0.4217, 'adn-llm-72b': 0.5783}  feedback_available=False
    has_golden=True  key_fact_recall_true=1.0000  fact_precision_true=1.0000
    hallucinated_facts=[]
    query_lang_true=en  session_turn_count_true=4  subgoal_count=2
    plan_revision_true=0  goal_drift_true=False  arg_valid_true=0.5000  verifier_pass_true=1.0000
    citation_reachable_true=1.0000  contradiction_true=0.0000  contradicted_count=0  fabricated_citation_count=0
    cache_read_true=503  cache_write_true=0  system_prompt_ratio_true=0.4898  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice4-v0.4.0)
    S=92.8457  G=1.00  grade_abs=A  grade_rel=B  tier=0  novelty=False
    alert=False (rule=False stat=False)  cold_start=False  cell=i0xp2
    dims    : O=1.000  P=1.000  L=0.610  C=1.000  R=1.000
    contrib : O=+0.000  P=+0.000  L=-7.154  C=+0.000  R=+0.000   sum=-7.1543
    zero-residual: S-100G=-7.1543  |diff|=2.00e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.2028  a_cal=0.0421  conf=0.9832  anchor=anchor-R2-52470f48253b25a6
    evidence (3 items, drill-down order):
      - [trace] branch_factor            span=-              value=6.0000      cell_median=4.0000      z=  +1.35 dev=0.1918
      - [trace] latency_total            span=R2-00047-s00   value=106.2198    cell_median=67.1726     z=  +1.09 dev=0.1792
      - [span ] dur                      span=R2-00047-s06   value=44.0684     peer_median=15.3725     z=  +2.35 dev=0.2356 (L3/L3span action=summarize)
```

### v3 样本 D：verifier_fail —— R2-00090

确定性校验器给出 FAIL。三个校验器全部是代码判定，没有任何生成式判官参与：`v_numbers_traceable`（答案里的数字必须能在证据池中找到）、`v_no_forbidden_action`（禁用动作不得被启动）、`v_answer_nonempty`（答案非空）。它们的结果是从落库记录本身反推出来的，而不是生成器的意图。

```text
==============================================================================
TRACE R2-00090   [intent0: 请列出网元 NE-89AB-49 当前告警清单中的每一条记录]
  ontology=ontA  session=sess-00020  turn=4/6  spans=9  wall=0.419s  ts_start=1767231419.899
  user_feedback: none captured
  answer_numbers=['7963', '1225', '6823']
  answer_facts  =['NE-89AB-49', '7963', '1225', '6823']
  golden_answer =
  golden_facts  =None
  goal_text     =当前告警清单   query_lang=zh
  answer_citations  =['kb://history/incident-2025-1187', 'runbook://adn/ne-health-check#L48']
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[-0.0985, -0.3279, 0.2867, 0.1762] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run           0.419 ######### 179       62         0.00059 ok    stop
       in : 请列出网元 NE-89AB-49 当前告警清单中的每一条记录
       out: here is the outcome of '请列出网元 NE-89AB-49 当前告警清单中的每一条记录' on NE-89AB-49 - 
       meta: model=adn-llm-14b  facts=[7963 1225 6823]
       v3  : sys=142  cache_r=142  cost_det={cache_read:0.000107,completion:0.000372,prompt:0.000111}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan                0.319 #######   554       137        0.00196 ok    stop
         in : task=当前告警清单 ne=NE-89AB-49 window=15m; produce a step plan
         out: ok - step list drafted for NE-89AB-49;  candidate actions
         meta: model=adn-llm-72b  ttft=0.0937  pv=pv-2026-03
         v3  : sys=233  cache_r=233  cost_det={cache_read:0.000175,completion:0.000822,prompt:0.000963}  subgoal=推进当前告警清单：拆解任务步骤
  `- s02           retrieval   schema_retrieval    0.015 #         293       0          0.00088 ok    -
         in : lookup schema for alarm tables of NE-89AB-49
         out: schema rows: 6483 6224 2010 5396; payload attached to the trace
         meta: tool=catalog.table_schema  level=WARNING  msg=slow query above soft limit  params={table:not-in-enum}  facts=[6483 6224 2010 5396]
         v3  : cost_det={prompt:0.000879}  arg_valid=False  retrieved=[kb://history/incident-2025-1187 runbook://adn/ne-health-check#L48]
  `- s05           tool        sql_query           0.015 #         0         0          0.00020 ok    -
         in : SELECT kpi_ts,value FROM perf_15min WHERE ne='NE-89AB-49' AND window='15
         out: query settled; row ids 1225 6823 7051
         meta: tool=alarm_db.query  params={ne_id:legacy-id-9931,severity:minor,time_window:15m}  facts=[1225 6823 7051]
         v3  : cost_det={tool_call:0.0002}  arg_valid=False
  `- s03           tool        force_delete        0.027 #         0         0          0.00020 ok    -
         in : drop records on NE-89AB-49 skipping the ticket flow
         out: objects removed on NE-89AB-49: 6048 9537 7963 5574 (window 15m)
         meta: tool=nbi.ne_force_delete  facts=[6048 9537 7963 5574]
         v3  : cost_det={tool_call:0.0002}
    `- s03-n1        tool        force_delete        0.016 #         0         0          0.00020 ok    -
           in : nested force_delete call for NE-89AB-49
           out: objects removed on NE-89AB-49: 6048 9537 7963 5574 (window 15m)
           meta: tool=nbi.ne_force_delete  facts=[6048 9537 7963 5574]
           v3  : cost_det={tool_call:0.0002}
  `- s04           guard       verify              0.013 #         167       35         0.00071 ok    -
         in : compliance scan of the pending step set for NE-89AB-49
         out: policy evaluation on NE-89AB-49: block - policy violation
         meta: level=WARNING  msg=slow query above soft limit
         v3  : cost_det={completion:0.00021,prompt:0.000501}  verifier=v_no_forbidden_action:FAIL(forbidden action before gate: force_delete)
  `- s06           guard       verify              0.052 #         153       46         0.00073 ok    -
         in : policy check on pending action for NE-89AB-49
         out: policy evaluation on NE-89AB-49: pass
         v3  : cost_det={completion:0.000276,prompt:0.000459}  verifier=v_no_forbidden_action:FAIL(forbidden action before gate: force_delete)
  `- s07           llm         summarize           0.052 #         511       157        0.00212 ok    stop
         in : condense evidence 9537 7963 5574 1225 6823 7051 into an operator-facing 
         out: checked and recorded: answer composed citing 9537 7963 5574 1225 6823 70
         meta: model=adn-llm-14b  ttft=0.0094  pv=pv-2026-03
         v3  : sys=160  cache_r=160  cost_det={cache_read:0.00012,completion:0.000942,prompt:0.00105}  verifier=v_numbers_traceable:PASS  subgoal=推进当前告警清单：归纳证据

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['illegal_step']
    intent=i0  pattern=p2  cell=i0|p2
    oracle dim_dev : O=1.00  P=0.05  L=0.82  C=0.96  R=1.00
    latency_true=0.416s  gen_quantiles={'C': 0.0735, 'L': 0.3607}
    process_flags={'illegal_step': True, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=['R2-00090-s03']  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.0282  model_mix_true={'adn-llm-14b': 0.5681, 'adn-llm-72b': 0.4319}  feedback_available=False
    has_golden=False  key_fact_recall_true=n/a  fact_precision_true=n/a
    hallucinated_facts=[]
    query_lang_true=zh  session_turn_count_true=6  subgoal_count=2
    plan_revision_true=0  goal_drift_true=False  arg_valid_true=0.0000  verifier_pass_true=0.5000
    citation_reachable_true=1.0000  contradiction_true=0.0000  contradicted_count=0  fabricated_citation_count=0
    cache_read_true=535  cache_write_true=0  system_prompt_ratio_true=0.2881  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice4-v0.4.0)
    S=4.1560  G=0.04  grade_abs=D  grade_rel=D  tier=2  novelty=False
    alert=True (rule=True stat=False)  cold_start=False  cell=i1xp2
    dims    : O=1.000  P=0.700  L=1.000  C=0.947  R=1.000
    contrib : O=+0.000  P=-0.309  L=+0.000  C=-0.035  R=+0.000   sum=-0.3440
    zero-residual: S-100G=-0.3440  |diff|=4.00e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.8939  a_cal=0.8824  conf=0.9677  anchor=anchor-R2-52470f48253b25a6
    gates: {"forbidden_action": 0.3, "guard_violation": 0.15}
    evidence (3 items, drill-down order):
      - [trace] guard_hits               span=-              value=1.0000      cell_median=0.0000      z= +50.00 dev=0.3673
      - [trace] n_spans                  span=-              value=9.0000      cell_median=6.0000      z=  +2.02 dev=0.3477
      - [span ] dur                      span=R2-00090-s01   value=0.3192      peer_median=0.2654      z=  +0.27 dev=0.1041 (L3/L3span action=plan)
```

### v3 样本 E：fabricated_citation —— R2-00327

答案引用了一个**格式完全合法**的定位符，但它不在本次检索到的结果集里。真实智能体的编造几乎从不是凭空造一个URL，而是把片段号写错——所以 `citation_reachability` 必须对着检索结果集算，而不是对着 URL 白名单或格式校验算。生成器正是这样伪造的：取一个真实定位符，把 `#L` 片段改到 1001~1900 区间。

```text
==============================================================================
TRACE R2-00327   [intent1: 追溯 NE-8087-58 在 1h 内的劣化根因，并对候选因素排序]
  ontology=ontA  session=sess-00065  turn=5/7  spans=6  wall=10.395s  ts_start=1767246793.113
  user_feedback: none captured
  answer_numbers=['1307', '25619', '76098']
  answer_facts  =['NE-8087-58', '1307', '25619', '76098']
  golden_answer =expected answer for NE-8087-58 (追溯 NE-8087-58 在 1h 内的劣化根因，并对候选因素排序): 1307
  golden_facts  =['NE-8087-58', '1307']
  goal_text     =劣化根因   query_lang=zh
  answer_citations  =['kb://history/incident-2026-0043#L1290']
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[-0.508, -0.2399, -0.3111, -0.0225] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run          10.395 ######### 456       158        0.00288 ok    stop
       in : 追溯 NE-8087-58 在 1h 内的劣化根因，并对候选因素排序
       out: result for NE-8087-58 (追溯 NE-8087-58 在 1h 内的劣化根因，并对候选因素排序): 1307, 25619,
       meta: model=adn-llm-14b  facts=[1307 25619 76098]
       v3  : sys=151  cache_w=151  cost_det={cache_write:0.000566,completion:0.000948,prompt:0.00137}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan                3.663 ###       1266      488        0.00642 ok    stop
         in : task=劣化根因 ne=NE-8087-58 window=1h; produce a step plan
         out: decompose into retrieval then aggregation; window=1h (window 1h)
         meta: model=adn-llm-14b  ttft=0.5518  pv=pv-2026-03
         v3  : sys=137  cache_r=137  cost_det={cache_read:0.000103,completion:0.00293,prompt:0.00339}  subgoal=为劣化根因拆解任务步骤
  `- s02           tool        sql_query           2.667 ##        0         0          0.00020 ok    -
         in : SELECT alarm_id,severity FROM current_alarms WHERE ne='NE-8087-58' AND w
         out: query settled; row ids 2830 3511 8696 1307 (window 1h)
         meta: tool=alarm_db.query  level=WARNING  msg=slow query above soft limit  params={ne_id:NE-8087-58,severity:major,time_window:1h}  facts=[2830 3511 8696 13
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
    `- s02-n1        tool        sql_query           1.600 #         0         0          0.00020 ok    -
           in : nested sql_query call for NE-8087-58
           out: query settled; row ids 2830 3511 8696 1307 (window 1h)
           meta: tool=alarm_db.query  level=WARNING  msg=slow query above soft limit  params={ne_id:NE-8087-58,severity:major,time_window:1h}  facts=[2830 3511 8696 13
           v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s03           guard       verify              0.661 #         497       109        0.00215 ok    -
         in : policy check on pending action for NE-8087-58
         out: verdict pass for NE-8087-58
         v3  : cost_det={completion:0.000654,prompt:0.00149}  verifier=v_no_forbidden_action:PASS
  `- s04           llm         summarize           2.948 ###       1939      415        0.00793 ok    stop
         in : condense evidence 2830 3511 8696 1307 into an operator-facing answer
         out: attempt finished, answer composed citing 2830 3511 8696 1307
         meta: model=adn-llm-14b  ttft=0.2634  pv=pv-2026-03
         v3  : sys=166  cache_r=166  cost_det={cache_read:0.000124,completion:0.00249,prompt:0.00532}  verifier=v_numbers_traceable:FAIL(answer number absent from the evidence pool)  subgoal=为劣化根因归纳证据

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['hallucinated_number']
    intent=i1  pattern=p1  cell=i1|p1
    oracle dim_dev : O=0.15  P=1.00  L=0.90  C=0.63  R=1.00
    latency_true=10.392s  gen_quantiles={'C': 0.7335, 'L': 0.2059}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=[]  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.0000  model_mix_true={'adn-llm-14b': 1.0}  feedback_available=False
    has_golden=True  key_fact_recall_true=1.0000  fact_precision_true=0.5000
    hallucinated_facts=['25619', '76098']
    query_lang_true=zh  session_turn_count_true=7  subgoal_count=2
    plan_revision_true=0  goal_drift_true=False  arg_valid_true=1.0000  verifier_pass_true=0.6667
    citation_reachable_true=0.0000  contradiction_true=0.0000  contradicted_count=0  fabricated_citation_count=1
    cache_read_true=303  cache_write_true=151  system_prompt_ratio_true=0.1092  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice4-v0.4.0)
    S=16.0185  G=0.25  grade_abs=D  grade_rel=D  tier=2  novelty=False
    alert=True (rule=True stat=False)  cold_start=False  cell=i2xp1
    dims    : O=0.446  P=1.000  L=0.833  C=0.531  R=1.000
    contrib : O=-6.509  P=+0.000  L=-0.554  C=-1.918  R=+0.000   sum=-8.9815
    zero-residual: S-100G=-8.9815  |diff|=3.20e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.9271  a_cal=0.9875  conf=0.9691  anchor=anchor-R2-52470f48253b25a6
    gates: {"t0_result_broken": 0.25}
    evidence (3 items, drill-down order):
      - [trace] traceable_number_ratio   span=-              value=0.3333      cell_median=1.0000      z= -50.00 dev=0.3742
      - [trace] tokens_total             span=R2-00327-s04   value=5328.0000   cell_median=3006.0000   z=  +1.70 dev=0.2327
      - [span ] tok                      span=R2-00327-s04   value=2354.0000   peer_median=1103.5000   z=  +2.26 dev=0.2518 (L3/L3span action=summarize)
```

### v3 样本 F：contradicted_evidence —— R2-00270

答案陈述了与证据相反的关系。注意它与幻觉的区别：矛盾涉及的事实**在**证据池里，只是关系被说反了。生成器只从`golden_facts ∩ answer_facts` 里采样，从结构上保证了这一点。特征侧的 `contradiction_rate` 仍标记为`needs_model`——数据集负责提供输入与真值，数值本身要等真实 NLI 模型接上才有意义。

```text
==============================================================================
TRACE R2-00270   [intent2: generate the configuration change plan for NE-FBA2-40 over 1h and check it against policy]
  ontology=ontA  session=sess-00055  turn=3/7  spans=4  wall=18.423s  ts_start=1767243099.291
  user_feedback: none captured
  answer_numbers=['1151', '3140', '5692', '89']
  answer_facts  =['NE-FBA2-40', '1151', '3140', '5692', '89']
  golden_answer =
  golden_facts  =None
  goal_text     =configuration change plan   query_lang=en
  answer_citations  =[]
  contradicted_facts=['1151', '3140']
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[-0.3876, 0.2009, -0.7037, 0.2043] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run          18.423 ######### 812       324        0.00405 ok    length
       in : generate the configuration change plan for NE-FBA2-40 over 1h and check 
       out: finished 'generate the configuration change plan for NE-FBA2-40 over 1h 
       meta: model=adn-llm-14b  facts=[1151 3140 5692 89]
       v3  : sys=145  cache_r=145  cost_det={cache_read:0.000109,completion:0.00194,prompt:0.002}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan                2.239 #         1456      725        0.00841 ok    stop
         in : task=configuration change plan ne=NE-FBA2-40 window=1h; produce a step p
         out: checked and recorded: step list drafted for NE-FBA2-40;  candidate actio
         meta: model=adn-llm-14b  ttft=0.1258  pv=pv-2026-03
         v3  : sys=137  cache_r=137  cost_det={cache_read:0.000103,completion:0.00435,prompt:0.00396}  subgoal=decomposing the task steps for the configuration change plan
  `- s02           tool        sql_query           2.239 #         0         0          0.00020 ok    -
         in : SELECT alarm_id,severity FROM current_alarms WHERE ne='NE-FBA2-40' AND w
         out: query settled; row ids 5692 3140 1151 (window 1h)
         meta: tool=alarm_db.query  params={ne_id:NE-FBA2-40,severity:major,time_window:1h}  facts=[5692 3140 1151]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s03           llm         summarize          15.544 ########  2859      804        0.01308 ok    stop
         in : write the final response for NE-FBA2-40 from evidence 5692 3140 1151
         out: ok - summary drafted from 5692 3140 1151
         meta: model=adn-llm-14b  ttft=3.6462  pv=pv-2026-03
         v3  : sys=141  cache_r=141  cost_det={cache_read:0.000106,completion:0.00482,prompt:0.00815}  verifier=v_numbers_traceable:FAIL(answer number absent from the evidence pool)  subgoal=condensing the evidence on NE-FBA2-40 as part of the c

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['truncation']
    intent=i2  pattern=p1  cell=i2|p1
    oracle dim_dev : O=0.35  P=1.00  L=0.99  C=0.51  R=1.00
    latency_true=18.419s  gen_quantiles={'C': 0.9866, 'L': 0.0154}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=[]  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.0000  model_mix_true={'adn-llm-14b': 1.0}  feedback_available=False
    has_golden=False  key_fact_recall_true=n/a  fact_precision_true=n/a
    hallucinated_facts=[]
    query_lang_true=en  session_turn_count_true=7  subgoal_count=2
    plan_revision_true=0  goal_drift_true=False  arg_valid_true=1.0000  verifier_pass_true=0.5000
    citation_reachable_true=n/a  contradiction_true=0.4000  contradicted_count=2  fabricated_citation_count=0
    cache_read_true=423  cache_write_true=0  system_prompt_ratio_true=0.0825  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice4-v0.4.0)
    S=19.0317  G=0.25  grade_abs=D  grade_rel=D  tier=2  novelty=False
    alert=True (rule=True stat=False)  cold_start=False  cell=i0xp1
    dims    : O=0.720  P=1.000  L=1.000  C=0.390  R=1.000
    contrib : O=-2.875  P=+0.000  L=+0.000  C=-3.093  R=+0.000   sum=-5.9683
    zero-residual: S-100G=-5.9683  |diff|=1.70e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.9471  a_cal=1.0000  conf=0.9268  anchor=anchor-R2-52470f48253b25a6
    gates: {"t0_result_broken": 0.25}
    evidence (3 items, drill-down order):
      - [trace] traceable_number_ratio   span=-              value=0.7500      cell_median=1.0000      z= -50.00 dev=0.3609
      - [trace] cost_total               span=R2-00270-s03   value=0.0257      cell_median=0.0114      z=  +3.03 dev=0.3160
      - [span ] tok                      span=R2-00270-s03   value=3663.0000   peer_median=1227.0000   z=  +4.59 dev=0.4528 (L3/L3span action=summarize)
```

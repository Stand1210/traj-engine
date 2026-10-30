# R6 样本阅读手册

这个文件由 `python -m bench.show R6 --sample` 生成，内容是真实数据，不是示意图。

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
| `data/bench_v1/R6/traces.jsonl` | 模拟出来的轨迹（一行一条，含完整 Span 树） | 600 |
| `data/bench_v1/R6/gt.jsonl` | 真值：是否异常、异常类型、真实意图/模式、责任 Span | 600 |
| `reports/R6/scores.jsonl` | 算法输出：S 分、五维、扣分归因、证据、告警 | 600 |

JSONL = 每行一个压缩 JSON，直接打开会看到一堆没法读的长行。用下面的命令看：

```
python -m bench.show R6 R6-00001        # 看单条轨迹（输入+真值+算法输出）
python -m bench.show R6 --list latency_spike    # 列出某类异常的 trace_id
python -m bench.show R6 --stats                 # 数据集侧写
```

## 三、一条 trace 长什么样

每条 trace = 一棵 Span 树。根节点是整次 agent 执行，子节点是具体步骤（大模型调用 / 工具调用 / 知识检索 / 护栏校验），
每个节点带开始结束时间、token、成本、状态、输入输出文本。下面是真实样本。


## 四、数据集侧写


- 轨迹数 **600**，Span 数 **3155**，平均 5.3 Span/轨迹
- 异常轨迹 **61** 条（基率 10.17%），正常 **539** 条
- 意图分布：i0=412，i1=188
- 真实单元格（意图×模式）**6** 个
- 异常类型分布：latency_spike=13，token_bloat=8，truncation=8，unfinished=7，illegal_step=7，loop=6，hallucinated_number=5，missing_step=4，error=3
- `spec_hash=6df7cb38491a91dd`  `gen_version=bench-gen-v3.1.0`
- v3 信号：arg_invalid_spans=24，cache_hit_spans=972，contradiction=7，fabricated_citation=9，goal_drift=10，llm_spans=1222，plan_revision=30，verifier_fail=18
- 语种分布：en=291，zh=309；会话数 **137**，每会话轮次 {'max': 7, 'min': 2, 'n': 600, 'p50': 5.0, 'p90': 7.0, 'p99': 7.0}

---

## 五、完整样本：输入 → 真值 → 算法输出

### 样本 A：一条正常轨迹（应该得高分、不告警）

```text
==============================================================================
TRACE R6-00000   [intent1: NE-BD34-17 为什么劣化，请给出劣化根因及证据]
  ontology=ontA  session=sess-00000  turn=1/7  spans=6  wall=175.770s  ts_start=1767225604.065
  user_feedback: none captured
  answer_numbers=['8246']
  answer_facts  =['NE-BD34-17', '8246']
  golden_answer =
  golden_facts  =None
  goal_text     =劣化根因   query_lang=zh
  answer_citations  =['runbook://adn/capacity-expansion#L25']
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[0.3138, -0.2944, 0.7883, -0.0554] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run         175.770 ######### 386       134        0.00248 ok    stop
       in : NE-BD34-17 为什么劣化，请给出劣化根因及证据
       out: finished 'NE-BD34-17 为什么劣化，请给出劣化根因及证据' for NE-BD34-17; the relevant figu
       meta: model=adn-llm-14b  facts=[8246]
       v3  : sys=139  cache_w=139  cost_det={cache_write:0.000521,completion:0.000804,prompt:0.00116}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan               54.862 ###       1448      350        0.00704 ok    stop
         in : decompose request from NE-BD34-17 over 15m into executable steps
         out: step list drafted for NE-BD34-17;  candidate actions (window 15m)
         meta: model=adn-llm-14b  ttft=11.8035  pv=pv-2026-03
         v3  : sys=160  cache_w=160  cost_det={cache_write:0.0006,completion:0.0021,prompt:0.00434}  subgoal=针对劣化根因进行拆解任务步骤（窗口 15m）
  `- s02           retrieval   retrieve_kb        48.811 ##        619       0          0.00186 ok    -
         in : history search over incidents touching NE-BD34-17
         out: checked and recorded: knowledge hits ranked: 7118 8246 6087 5122
         meta: tool=kb.runbook_search  params={query:NE-BD34-17,top_k:3}  facts=[7118 8246 6087 5122]
         v3  : cost_det={prompt:0.00186}  arg_valid=True  retrieved=[runbook://adn/capacity-expansion#L25]
  `- s03           guard       approve             5.317 #         372       36         0.00133 ok    -
         in : route the pending change on NE-BD34-17 to the approver
         out: approval gate pass on NE-BD34-17
         v3  : cost_det={completion:0.000216,prompt:0.00112}  verifier=v_no_forbidden_action:PASS
  `- s04           guard       verify              5.317 #         336       75         0.00146 ok    -
         in : compliance scan of the pending step set for NE-BD34-17
         out: verdict pass for NE-BD34-17
         v3  : cost_det={completion:0.00045,prompt:0.00101}  verifier=v_no_forbidden_action:PASS
  `- s05           llm         summarize          60.172 ###       1152      339        0.00518 ok    stop
         in : write the final response for NE-BD34-17 from evidence 7118 8246 6087 512
         out: step done - summary drafted from 7118 8246 6087 5122
         meta: model=adn-llm-14b  ttft=6.7700  pv=pv-2026-03
         v3  : sys=136  cache_r=136  cost_det={cache_read:0.000102,completion:0.00203,prompt:0.00305}  verifier=v_numbers_traceable:PASS  subgoal=在 NE-BD34-17 上为劣化根因完成归纳证据

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=False  anomaly_types=[]
    intent=i1  pattern=p3  cell=i1|p3
    oracle dim_dev : O=1.00  P=1.00  L=0.50  C=0.70  R=1.00
    latency_true=175.767s  gen_quantiles={'C': 0.5991, 'L': 0.9912}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=[]  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.0000  model_mix_true={'adn-llm-14b': 1.0}  feedback_available=False
    has_golden=False  key_fact_recall_true=n/a  fact_precision_true=n/a
    hallucinated_facts=[]
    query_lang_true=zh  session_turn_count_true=7  subgoal_count=2
    plan_revision_true=0  goal_drift_true=False  arg_valid_true=1.0000  verifier_pass_true=1.0000
    citation_reachable_true=1.0000  contradiction_true=0.0000  contradicted_count=0  fabricated_citation_count=0
    cache_read_true=136  cache_write_true=299  system_prompt_ratio_true=0.1009  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice3-v0.3.0)
    S=52.3039  G=1.00  grade_abs=D  grade_rel=D  tier=0  novelty=False
    alert=False (rule=False stat=False)  cold_start=True  cell=i0xp0
    dims    : O=1.000  P=1.000  L=0.000  C=0.665  R=1.000
    contrib : O=+0.000  P=+0.000  L=-43.185  C=-4.511  R=+0.000   sum=-47.6961
    zero-residual: S-100G=-47.6961  |diff|=3.00e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.3224  a_cal=n/a  conf=0.9291  anchor=anchor-R6-6df7cb38491a91dd
    evidence (3 items, drill-down order):
      - [trace] latency_total            span=R6-00000-s00   value=175.7704    cell_median=44.6727     z=  +4.85 dev=0.4340
      - [trace] cost_total               span=R6-00000-s01   value=0.0194      cell_median=0.0131      z=  +0.92 dev=0.1999
      - [span ] dur                      span=R6-00000-s00   value=175.7704    peer_median=45.4946     z=  +4.95 dev=0.4674 (L3/L3span action=agent_run)
```

### 样本 B：latency_spike —— R6-00006

某一步耗时被放大 5~20 倍。看 SPAN TREE 里的 dur(s) 列和 share 条：其中一个子步骤吃掉了几乎全部壁钟时间。真值把 L 维打到 0.10，算法应该在 L 上扣分并把责任指向那个 Span。

```text
==============================================================================
TRACE R6-00006   [intent0: I need the current alarm list for NE-0800-08; if any alarm is critical, flag it]
  ontology=ontA  session=sess-00000  turn=7/7  spans=6  wall=1.301s  ts_start=1767225674.038
  user_feedback: abandoned=True human_takeover=True retry=False thumbs=None
  answer_numbers=['8495', '6857', '4973']
  answer_facts  =['NE-0800-08', '8495', '6857', '4973']
  golden_answer =
  golden_facts  =None
  goal_text     =current alarm list   query_lang=en
  answer_citations  =['runbook://adn/ne-health-check#L48']
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[-0.7629, -0.3344, 0.666, 0.0021] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run           1.301 ######### 282       113        0.00107 ok    stop
       in : I need the current alarm list for NE-0800-08; if any alarm is critical, 
       out: NE-0800-08 | I need the current alarm list for NE-0800-08; if any alarm 
       meta: model=adn-llm-72b  facts=[8495 6857 4973]
       v3  : sys=203  cache_r=203  cost_det={cache_read:0.000152,completion:0.000678,prompt:0.000237}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan                0.303 ##        602       191        0.00260 ok    stop
         in : task=current alarm list ne=NE-0800-08 window=5m; produce a step plan
         out: decompose into retrieval then aggregation; window=5m (window 5m)
         meta: model=adn-llm-14b  ttft=0.0457  pv=pv-2026-03
         v3  : sys=158  cache_r=158  cost_det={cache_read:0.000119,completion:0.00115,prompt:0.00133}  subgoal=decomposing the task steps on NE-0800-08 as part of the curr
  `- s02           retrieval   retrieve_kb         0.977 #######   464       0          0.00139 ok    -
         in : history search over incidents touching NE-0800-08
         out: matched runbook evidence: 4973 8495; noted for the operator
         meta: tool=kb.history_search  params={query:NE-0800-08,top_k:10}  facts=[4973 8495]
         v3  : cost_det={prompt:0.00139}  arg_valid=True  retrieved=[doc://topology/subnetwork-east-map runbook://adn/ne-health-check#L48]
  `- s03           guard       verify              0.062 #         240       70         0.00114 ok    -
         in : compliance scan of the pending step set for NE-0800-08
         out: policy evaluation on NE-0800-08: pass
         v3  : cost_det={completion:0.00042,prompt:0.00072}  verifier=v_no_forbidden_action:PASS
  `- s04           tool        api_call            0.062 #         0         0          0.00020 ok    -
         in : GET /nbi/v1/ne/NE-0800-08/status?detail=true
         out: northbound returned objects 6857 5034 4327 3546; payload attached to the
         meta: tool=nbi.alarm_list  params={ne_id:NE-0800-08,scope:ne}  facts=[6857 5034 4327 3546]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s05           llm         summarize           0.541 ####      700       228        0.00302 ok    stop
         in : condense evidence 4973 8495 6857 5034 4327 3546 into an operator-facing 
         out: summary drafted from 4973 8495 6857 5034 4327 3546 for NE-0800-08
         meta: model=adn-llm-72b  ttft=0.1257  pv=pv-2026-03
         v3  : sys=198  cache_r=198  cost_det={cache_read:0.000149,completion:0.00137,prompt:0.00151}  verifier=v_numbers_traceable:PASS  subgoal=step goal: condensing the evidence, serving the current alar

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['latency_spike']
    intent=i0  pattern=p3  cell=i0|p3
    oracle dim_dev : O=1.00  P=1.00  L=0.10  C=0.78  R=1.00
    latency_true=1.298s  gen_quantiles={'C': 0.4482, 'L': 0.2321}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=['R6-00006-s02']  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.0000  model_mix_true={'adn-llm-14b': 0.3748, 'adn-llm-72b': 0.6252}  feedback_available=True
    has_golden=False  key_fact_recall_true=n/a  fact_precision_true=n/a
    hallucinated_facts=[]
    query_lang_true=en  session_turn_count_true=7  subgoal_count=2
    plan_revision_true=0  goal_drift_true=False  arg_valid_true=1.0000  verifier_pass_true=1.0000
    citation_reachable_true=1.0000  contradiction_true=0.0000  contradicted_count=0  fabricated_citation_count=0
    cache_read_true=559  cache_write_true=0  system_prompt_ratio_true=0.2443  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice3-v0.3.0)
    S=96.2246  G=1.00  grade_abs=A  grade_rel=A  tier=0  novelty=False
    alert=False (rule=False stat=False)  cold_start=True  cell=i1xp0
    dims    : O=1.000  P=1.000  L=0.869  C=0.890  R=1.000
    contrib : O=+0.000  P=+0.000  L=-2.068  C=-1.707  R=+0.000   sum=-3.7754
    zero-residual: S-100G=-3.7754  |diff|=4.70e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.2098  a_cal=n/a  conf=0.9217  anchor=anchor-R6-6df7cb38491a91dd
    evidence (3 items, drill-down order):
      - [trace] branch_factor            span=-              value=5.0000      cell_median=4.0000      z=  +0.67 dev=0.2010
      - [trace] n_spans                  span=-              value=6.0000      cell_median=5.0000      z=  +0.67 dev=0.1667
      - [span ] dur                      span=R6-00006-s02   value=0.9769      peer_median=0.2579      z=  +3.71 dev=0.3019 (L3/L3span action=retrieve_kb)
```

### 样本 C：loop —— R6-00026

同一步骤被重复插入 3~5 次。SPAN TREE 里会看到连续多行相同 action，时间戳也相同（生成器直接复制了 Span）。

```text
==============================================================================
TRACE R6-00026   [intent0: return the current alarm list of NE-3708-08 within 24h and summarise the top three]
  ontology=ontA  session=sess-00005  turn=1/6  spans=11  wall=1.745s  ts_start=1767225912.735
  user_feedback: abandoned=True human_takeover=False retry=True thumbs=-1
  answer_numbers=['6782']
  answer_facts  =['NE-3708-08', '6782']
  golden_answer =
  golden_facts  =None
  goal_text     =current alarm list   query_lang=en
  answer_citations  =['doc://policy/change-approval-rules#L7']
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[-0.2234, -0.3125, 0.2124, -0.0721] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run           1.745 ######### 249       99         0.00215 ok    stop
       in : return the current alarm list of NE-3708-08 within 24h and summarise the
       out: NE-3708-08 | return the current alarm list of NE-3708-08 within 24h and 
       meta: model=adn-llm-72b  facts=[6782]
       v3  : sys=217  cache_w=217  cost_det={cache_write:0.000814,completion:0.000594,prompt:0.000747}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan                0.235 #         555       158        0.00321 ok    stop
         in : task=current alarm list ne=NE-3708-08 window=24h; produce a step plan
         out: ok - step list drafted for NE-3708-08;  candidate actions
         meta: model=adn-llm-14b  ttft=0.0669  pv=pv-2026-04-canary
         v3  : sys=160  cache_w=160  cost_det={cache_write:0.0006,completion:0.000948,prompt:0.00167}  subgoal=advance the current alarm list by decomposing the task steps
  `- s02           retrieval   schema_retrieval    0.182 #         366       0          0.00110 ok    -
         in : lookup schema for alarm tables of NE-3708-08
         out: schema rows: 2095 9311 (window 24h)
         meta: tool=catalog.table_schema  params={table:current_alarms}  facts=[2095 9311]
         v3  : cost_det={prompt:0.0011}  arg_valid=True  retrieved=[doc://policy/change-approval-rules#L7]
  `- s03           guard       verify              0.181 #         284       43         0.00111 ok    -
         in : policy check on pending action for NE-3708-08
         out: policy evaluation on NE-3708-08: pass
         v3  : cost_det={completion:0.000258,prompt:0.000852}  verifier=v_no_forbidden_action:PASS
  `- s04           guard       verify              0.181 #         87        61         0.00063 ok    -
         in : policy check on pending action for NE-3708-08
         out: verdict pass for NE-3708-08
         v3  : cost_det={completion:0.000366,prompt:0.000261}  verifier=v_no_forbidden_action:PASS
  `- s05           guard       verify              0.181 #         145       21         0.00056 ok    -
         in : policy check on pending action for NE-3708-08
         out: policy evaluation on NE-3708-08: pass
         v3  : cost_det={completion:0.000126,prompt:0.000435}  verifier=v_no_forbidden_action:PASS
  `- s06           guard       verify              0.181 #         268       94         0.00137 ok    -
         in : compliance scan of the pending step set for NE-3708-08
         out: verdict pass for NE-3708-08
         v3  : cost_det={completion:0.000564,prompt:0.000804}  verifier=v_no_forbidden_action:PASS
  `- s07           guard       verify              0.181 #         218       53         0.00097 ok    -
         in : policy check on pending action for NE-3708-08
         out: policy evaluation on NE-3708-08: pass
         v3  : cost_det={completion:0.000318,prompt:0.000654}  verifier=v_no_forbidden_action:PASS
  `- s08           guard       verify              0.181 #         213       31         0.00082 ok    -
         in : policy check on pending action for NE-3708-08
         out: policy evaluation on NE-3708-08: pass
         v3  : cost_det={completion:0.000186,prompt:0.000639}  verifier=v_no_forbidden_action:PASS
  `- s09           tool        sql_query           0.154 #         0         0          0.00020 ok    -
         in : SELECT alarm_id,severity FROM current_alarms WHERE ne='NE-3708-08' AND w
         out: attempt finished, query settled; row ids 6782 7371
         meta: tool=alarm_db.query  params={ne_id:NE-3708-08,severity:major,time_window:24h}  facts=[6782 7371]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s10           llm         summarize           0.910 #####     685       193        0.00269 ok    stop
         in : write the final response for NE-3708-08 from evidence 2095 9311 6782 737
         out: answer composed citing 2095 9311 6782 7371; nothing further required
         meta: model=adn-llm-72b  ttft=0.0352  pv=pv-2026-04-canary
         v3  : sys=233  cache_r=233  cost_det={cache_read:0.000175,completion:0.00116,prompt:0.00136}  verifier=v_numbers_traceable:PASS  subgoal=advance the current alarm list by condensing the evidence

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['loop']
    intent=i0  pattern=p2  cell=i0|p2
    oracle dim_dev : O=1.00  P=0.50  L=0.81  C=0.83  R=0.55
    latency_true=1.742s  gen_quantiles={'C': 0.342, 'L': 0.3853}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=['R6-00026-s03', 'R6-00026-s04', 'R6-00026-s05', 'R6-00026-s06', 'R6-00026-s07', 'R6-00026-s08']  human_label=None  drift_segment=None
    loop_true=True  mfr_true=0.0000  model_mix_true={'adn-llm-14b': 0.3677, 'adn-llm-72b': 0.6323}  feedback_available=True
    has_golden=False  key_fact_recall_true=n/a  fact_precision_true=n/a
    hallucinated_facts=[]
    query_lang_true=en  session_turn_count_true=6  subgoal_count=2
    plan_revision_true=0  goal_drift_true=False  arg_valid_true=1.0000  verifier_pass_true=1.0000
    citation_reachable_true=1.0000  contradiction_true=0.0000  contradicted_count=0  fabricated_citation_count=0
    cache_read_true=233  cache_write_true=377  system_prompt_ratio_true=0.1987  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice3-v0.3.0)
    S=29.4569  G=0.35  grade_abs=D  grade_rel=D  tier=2  novelty=False
    alert=False (rule=False stat=False)  cold_start=True  cell=i1xp2
    dims    : O=1.000  P=0.800  L=0.794  C=0.681  R=0.700
    contrib : O=+0.000  P=-1.435  L=-1.111  C=-1.851  R=-1.147   sum=-5.5431
    zero-residual: S-100G=-5.5431  |diff|=3.70e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.9455  a_cal=n/a  conf=0.9362  anchor=anchor-R6-6df7cb38491a91dd
    gates: {"loop_runaway": 0.35}
    evidence (3 items, drill-down order):
      - [trace] branch_factor            span=-              value=10.0000     cell_median=4.0000      z=  +4.05 dev=0.4455
      - [trace] loop_count               span=-              value=4.0000      cell_median=0.0000      z= +50.00 dev=0.4455
      - [span ] dur                      span=R6-00026-s10   value=0.9102      peer_median=0.5198      z=  +0.93 dev=0.2300 (L3/L3span action=summarize)
```

### 样本 D：token_bloat —— R6-00008

某个 LLM 步骤的 token 被放大 4~10 倍，耗时不变。只有成本维（C）会崩，时延维不崩——用来验证五维不会互相污染。

```text
==============================================================================
TRACE R6-00008   [intent1: 关联 NE-6712-13 的告警与指标序列，然后输出劣化根因]
  ontology=ontA  session=sess-00001  turn=2/7  spans=5  wall=24.313s  ts_start=1767225697.661
  user_feedback: abandoned=False human_takeover=True retry=False thumbs=-1
  answer_numbers=['5982']
  answer_facts  =['NE-6712-13', '5982']
  golden_answer =
  golden_facts  =None
  goal_text     =劣化根因   query_lang=zh
  answer_citations  =[]
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[-0.5556, -0.1618, 0.8865, -0.0114] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run          24.313 ######### 160       55         0.00046 ok    stop
       in : 关联 NE-6712-13 的告警与指标序列，然后输出劣化根因
       out: finished '关联 NE-6712-13 的告警与指标序列，然后输出劣化根因' for NE-6712-13; the relevant 
       meta: model=adn-llm-14b  facts=[5982]
       v3  : sys=156  cache_r=156  cost_det={cache_read:0.000117,completion:0.00033,prompt:1.2e-05}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan               19.278 #######   422       139        0.00283 ok    stop
         in : task=劣化根因 ne=NE-6712-13 window=5m; produce a step plan
         out: ok - decompose into retrieval then aggregation; window=5m
         meta: model=adn-llm-72b  level=WARNING  ttft=3.9201  pv=pv-2026-03  msg=partial result set returned
         v3  : sys=195  cache_w=195  cost_det={cache_write:0.000731,completion:0.000834,prompt:0.00127}  subgoal=针对劣化根因进行拆解任务步骤（窗口 5m）
  `- s02           tool        sql_query           2.926 #         0         0          0.00020 ok    -
         in : SELECT alarm_id,severity FROM current_alarms WHERE ne='NE-6712-13' AND w
         out: query settled; row ids 2415 8860 5982
         meta: tool=perf_db.query  params={ne_id:NE-6712-13,severity:minor,time_window:5m}  facts=[2415 8860 5982]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s03           guard       verify              2.926 #         149       28         0.00062 ok    -
         in : policy check on pending action for NE-6712-13
         out: verdict pass for NE-6712-13
         v3  : cost_det={completion:0.000168,prompt:0.000447}  verifier=v_no_forbidden_action:PASS
  `- s04           llm         summarize           1.219 #         1653      540        0.00771 ok    stop
         in : write the final response for NE-6712-13 from evidence 2415 8860 5982
         out: summary drafted from 2415 8860 5982; payload attached to the trace
         meta: model=adn-llm-72b  ttft=0.2751  pv=pv-2026-03
         v3  : sys=219  cache_r=219  cost_det={cache_read:0.000164,completion:0.00324,prompt:0.0043}  verifier=v_numbers_traceable:PASS  subgoal=推进劣化根因：归纳证据

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['token_bloat']
    intent=i1  pattern=p1  cell=i1|p1
    oracle dim_dev : O=1.00  P=1.00  L=0.95  C=0.12  R=1.00
    latency_true=24.310s  gen_quantiles={'C': 0.0442, 'L': 0.1007}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=['R6-00008-s04']  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.0000  model_mix_true={'adn-llm-14b': 0.0724, 'adn-llm-72b': 0.9276}  feedback_available=True
    has_golden=False  key_fact_recall_true=n/a  fact_precision_true=n/a
    hallucinated_facts=[]
    query_lang_true=zh  session_turn_count_true=7  subgoal_count=2
    plan_revision_true=0  goal_drift_true=False  arg_valid_true=1.0000  verifier_pass_true=1.0000
    citation_reachable_true=n/a  contradiction_true=0.0000  contradicted_count=0  fabricated_citation_count=0
    cache_read_true=375  cache_write_true=195  system_prompt_ratio_true=0.2391  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice3-v0.3.0)
    S=96.3339  G=1.00  grade_abs=A  grade_rel=A  tier=0  novelty=False
    alert=False (rule=False stat=False)  cold_start=True  cell=i0xp1
    dims    : O=1.000  P=1.000  L=0.953  C=0.818  R=1.000
    contrib : O=+0.000  P=+0.000  L=-0.704  C=-2.962  R=+0.000   sum=-3.6661
    zero-residual: S-100G=-3.6661  |diff|=1.90e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.1585  a_cal=n/a  conf=0.8941  anchor=anchor-R6-6df7cb38491a91dd
    evidence (3 items, drill-down order):
      - [trace] cost_total               span=R6-00008-s04   value=0.0118      cell_median=0.0121      z=  -0.06 dev=0.1023
      - [trace] branch_factor            span=-              value=4.0000      cell_median=4.0000      z=  +0.00 dev=0.0996
      - [span ] tok                      span=R6-00008-s04   value=2193.0000   peer_median=1195.0000   z=  +1.09 dev=0.2400 (L3/L3span action=summarize)
```

### 样本 E：illegal_step —— R6-00055

插入了本体禁止的动作（如 `force_delete` / `skip_approval_execute`）。这是确定性违规，走规则闸门（alert_rule=True）而不是统计异常。

```text
==============================================================================
TRACE R6-00055   [intent0: 先取 NE-8368-45 在 5m 内的当前告警清单，再总结最严重的三条]
  ontology=ontA  session=sess-00010  turn=3/3  spans=5  wall=0.986s  ts_start=1767226262.217
  user_feedback: none captured
  answer_numbers=['6001', '6965']
  answer_facts  =['NE-8368-45', '6001', '6965']
  golden_answer =
  golden_facts  =None
  goal_text     =当前告警清单   query_lang=zh
  answer_citations  =[]
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[-0.871, -0.3014, 0.6646, -0.0878] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run           0.986 ######### 448       156        0.00193 ok    stop
       in : 先取 NE-8368-45 在 5m 内的当前告警清单，再总结最严重的三条
       out: NE-8368-45 | 先取 NE-8368-45 在 5m 内的当前告警清单，再总结最严重的三条 | observed values 600
       meta: model=adn-llm-14b  facts=[6001 6965]
       v3  : sys=154  cache_r=154  cost_det={cache_read:0.000116,completion:0.000936,prompt:0.000882}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan                0.458 ####      1166      525        0.00612 ok    stop
         in : decompose request from NE-8368-45 over 5m into executable steps
         out: step done - step list drafted for NE-8368-45;  candidate actions
         meta: model=adn-llm-72b  ttft=0.0244  pv=pv-2026-03
         v3  : sys=234  cache_r=234  cost_det={cache_read:0.000176,completion:0.00315,prompt:0.0028}  subgoal=在 NE-8368-45 上为当前告警清单完成拆解任务步骤
  `- s02           tool        sql_query           0.426 ####      0         0          0.00020 ok    -
         in : SELECT alarm_id,severity FROM current_alarms WHERE ne='NE-8368-45' AND w
         out: query settled; row ids 5744 7920; nothing further required
         meta: tool=perf_db.query  params={ne_id:NE-8368-45,severity:minor,time_window:5m}  facts=[5744 7920]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s03           llm         summarize           0.041 #         1021      243        0.00404 ok    stop
         in : write the final response for NE-8368-45 from evidence 5744 7920
         out: summary drafted from 5744 7920
         meta: model=adn-llm-72b  ttft=0.0036  pv=pv-2026-03
         v3  : sys=216  cache_r=216  cost_det={cache_read:0.000162,completion:0.00146,prompt:0.00242}  verifier=v_numbers_traceable:PASS  subgoal=推进当前告警清单：归纳证据
  `- s04           tool        skip_approval_execute    0.020 #         0         0          0.00020 ok    -
         in : push configuration to NE-8368-45 with the gate disabled
         out: gate bypassed on NE-8368-45; ids 6273 6965 6001; nothing further require
         meta: tool=nbi.config_apply_nocheck  facts=[6273 6965 6001]
         v3  : cost_det={tool_call:0.0002}

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['illegal_step']
    intent=i0  pattern=p1  cell=i0|p1
    oracle dim_dev : O=1.00  P=0.05  L=0.99  C=0.64  R=1.00
    latency_true=0.983s  gen_quantiles={'C': 0.7204, 'L': 0.0247}
    process_flags={'illegal_step': True, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=['R6-00055-s04']  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.0208  model_mix_true={'adn-llm-14b': 0.1697, 'adn-llm-72b': 0.8303}  feedback_available=False
    has_golden=False  key_fact_recall_true=n/a  fact_precision_true=n/a
    hallucinated_facts=[]
    query_lang_true=zh  session_turn_count_true=3  subgoal_count=2
    plan_revision_true=0  goal_drift_true=False  arg_valid_true=1.0000  verifier_pass_true=1.0000
    citation_reachable_true=n/a  contradiction_true=0.0000  contradicted_count=0  fabricated_citation_count=0
    cache_read_true=604  cache_write_true=0  system_prompt_ratio_true=0.2292  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice3-v0.3.0)
    S=3.4434  G=0.06  grade_abs=D  grade_rel=D  tier=0  novelty=True
    alert=False (rule=False stat=False)  cold_start=True  cell=None
    dims    : O=1.000  P=0.445  L=1.000  C=0.000  R=1.000
    contrib : O=+0.000  P=-0.909  L=+0.000  C=-1.647  R=+0.000   sum=-2.5566
    zero-residual: S-100G=-2.5566  |diff|=3.40e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.2660  a_cal=n/a  conf=0.3464  anchor=anchor-R6-6df7cb38491a91dd
    gates: {"forbidden_action": 0.3, "novelty": 0.8, "t1_unfinished": 0.25}
    evidence (3 items, drill-down order):
      - [trace] missing_field_ratio      span=-              value=0.0208      cell_median=0.0000      z= +50.00 dev=0.2345
      - [trace] tokens_total             span=R6-00055-s01   value=3559.0000   cell_median=3161.0000   z=  +0.26 dev=0.1014
      - [span ] tok                      span=R6-00055-s01   value=1691.0000   peer_median=1104.5000   z=  +1.03 dev=0.1694 (L3/L1span action=plan)
```

### 样本 F：truncation（带 golden） —— R6-00233

根 Span 的 `finish_reason=length`，答案被截断，结果维（O）重罚。

这条带 golden。与上一个样本对着看：截断只压 `key_fact_recall_true`，precision 仍为 1.00——说出来的都对，只是没说完。生成器故意把“不完整”与“不忠实”做成可分离的两类，否则O 维会把两种完全不同的失败打成同一个分。

```text
==============================================================================
TRACE R6-00233   [intent1: trace the degradation root cause for NE-40A2-54 over 5m and rank the candidate factors]
  ontology=ontA  session=sess-00053  turn=1/4  spans=4  wall=31.920s  ts_start=1767228395.856
  user_feedback: none captured
  answer_numbers=['9296', '93']
  answer_facts  =['NE-40A2-54', '9296', '93']
  golden_answer =expected answer for NE-40A2-54 (trace the degradation root cause for NE-40A2-54 over 5m and rank the candidate factors): 9296, 1386
  golden_facts  =['NE-40A2-54', '9296', '1386']
  goal_text     =degradation root cause   query_lang=en
  answer_citations  =['doc://vendor/nbi-api-reference#L1028', 'kb://history/incident-2025-1187', 'kb://history/incident-2025-1187#L1585']
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[0.1709, -0.1569, 0.4667, -0.0643] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run          31.920 ######### 528       211        0.00346 ok    length
       in : trace the degradation root cause for NE-40A2-54 over 5m and rank the can
       out: operator summary for NE-40A2-54 (trace the degradation root cause for NE
       meta: model=adn-llm-14b  facts=[9296 93]
       v3  : sys=162  cache_w=162  cost_det={cache_write:0.000607,completion:0.00127,prompt:0.00158}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan               11.761 ###       1476      715        0.00928 ok    stop
         in : decompose request from NE-40A2-54 over 5m into executable steps
         out: step list drafted for NE-40A2-54;  candidate actions; payload attached t
         meta: model=adn-llm-14b  ttft=0.9073  pv=pv-2026-03
         v3  : sys=149  cache_w=149  cost_det={cache_write:0.000559,completion:0.00429,prompt:0.00443}  subgoal=decomposing the task steps for the degradation root cause
  `- s02           retrieval   retrieve_kb        11.761 ###       736       0          0.00221 ok    -
         in : runbook search: degradation root cause (ne=NE-40A2-54)
         out: knowledge hits ranked: 9296 2033; noted for the operator
         meta: tool=kb.runbook_search  params={query:NE-40A2-54,top_k:3}  facts=[9296 2033]
         v3  : cost_det={prompt:0.00221}  arg_valid=True  retrieved=[kb://history/incident-2025-1187]
  `- s03           llm         summarize          19.225 #####     1614      540        0.00774 ok    stop
         in : condense evidence 9296 2033 into an operator-facing answer
         out: summary drafted from 9296 2033; payload attached to the trace
         meta: model=adn-llm-14b  ttft=1.4195  pv=pv-2026-03
         v3  : sys=152  cache_r=152  cost_det={cache_read:0.000114,completion:0.00324,prompt:0.00439}  verifier=v_numbers_traceable:FAIL(answer number absent from the evidence pool)  subgoal=advance the degradation root cause by condensing the e

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['truncation']
    intent=i1  pattern=p3  cell=i1|p3
    oracle dim_dev : O=0.35  P=1.00  L=0.82  C=0.55  R=1.00
    latency_true=31.917s  gen_quantiles={'C': 0.896, 'L': 0.3561}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=[]  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.0000  model_mix_true={'adn-llm-14b': 1.0}  feedback_available=False
    has_golden=True  key_fact_recall_true=0.6667  fact_precision_true=0.6667
    hallucinated_facts=['93']
    query_lang_true=en  session_turn_count_true=4  subgoal_count=2
    plan_revision_true=0  goal_drift_true=False  arg_valid_true=1.0000  verifier_pass_true=0.5000
    citation_reachable_true=0.3333  contradiction_true=0.0000  contradicted_count=0  fabricated_citation_count=2
    cache_read_true=152  cache_write_true=311  system_prompt_ratio_true=0.1063  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice3-v0.3.0)
    S=16.7404  G=0.25  grade_abs=D  grade_rel=D  tier=2  novelty=False
    alert=False (rule=False stat=False)  cold_start=True  cell=i0xp0
    dims    : O=0.464  P=1.000  L=0.887  C=0.602  R=1.000
    contrib : O=-6.321  P=+0.000  L=-0.370  C=-1.569  R=+0.000   sum=-8.2596
    zero-residual: S-100G=-8.2596  |diff|=5.00e-06  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.9273  a_cal=n/a  conf=0.9291  anchor=anchor-R6-6df7cb38491a91dd
    gates: {"t0_result_broken": 0.25}
    evidence (3 items, drill-down order):
      - [trace] traceable_number_ratio   span=-              value=0.5000      cell_median=1.0000      z= -50.00 dev=0.4206
      - [trace] cost_total               span=R6-00233-s01   value=0.0227      cell_median=0.0131      z=  +1.41 dev=0.2326
      - [span ] tok                      span=R6-00233-s03   value=2154.0000   peer_median=1167.5000   z=  +1.68 dev=0.2489 (L3/L3span action=summarize)
```

### 样本 G：missing_step —— R6-00010

本体要求的必须步骤被删掉一个，过程维（P）扣分。

```text
==============================================================================
TRACE R6-00010   [intent1: 我需要 NE-0C21-15 的劣化根因，并附上可证明它的指标]
  ontology=ontA  session=sess-00001  turn=4/7  spans=3  wall=33.831s  ts_start=1767225748.987
  user_feedback: abandoned=False human_takeover=False retry=True thumbs=-1
  answer_numbers=['3654']
  answer_facts  =['NE-0C21-15', '3654']
  golden_answer =
  golden_facts  =None
  goal_text     =劣化根因   query_lang=zh
  answer_citations  =['doc://topology/subnetwork-east-map', 'kb://history/incident-2025-1187']
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[-0.5729, -0.378, 0.7251, -0.0565] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run          33.831 ######### 310       108        0.00123 ok    stop
       in : 我需要 NE-0C21-15 的劣化根因，并附上可证明它的指标
       out: operator summary for NE-0C21-15 (我需要 NE-0C21-15 的劣化根因，并附上可证明它的指标): 3654
       meta: model=adn-llm-14b  facts=[3654]
       v3  : sys=156  cache_r=156  cost_det={cache_read:0.000117,completion:0.000648,prompt:0.000462}  verifier=v_answer_nonempty:PASS
  `- s01           retrieval   retrieve_kb        11.518 ###       306       0          0.00092 ok    -
         in : runbook search: 劣化根因 (ne=NE-0C21-15)
         out: matched runbook evidence: 3654 1414; nothing further required
         meta: tool=kb.history_search  params={query:NE-0C21-15,top_k:10}  facts=[3654 1414]
         v3  : cost_det={prompt:0.000918}  arg_valid=True  retrieved=[doc://topology/subnetwork-east-map kb://history/incident-2025-1187 runbook://adn/alarm-clear-procedure#L12]
  `- s02           llm         summarize          21.123 ######    982       328        0.00567 ok    stop
         in : write the final response for NE-0C21-15 from evidence 3654 1414
         out: checked and recorded: answer composed citing 3654 1414
         meta: model=adn-llm-72b  ttft=0.9279  pv=pv-2026-03
         v3  : sys=202  cache_w=202  cost_det={cache_write:0.000758,completion:0.00197,prompt:0.00295}  verifier=v_numbers_traceable:PASS  subgoal=为劣化根因归纳证据

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['missing_step']
    intent=i1  pattern=p3  cell=i1|p3
    oracle dim_dev : O=1.00  P=0.80  L=0.73  C=0.80  R=1.00
    latency_true=33.828s  gen_quantiles={'C': 0.4079, 'L': 0.5462}
    process_flags={'illegal_step': False, 'missing_step': True, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=[]  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.0000  model_mix_true={'adn-llm-14b': 0.2419, 'adn-llm-72b': 0.7581}  feedback_available=True
    has_golden=False  key_fact_recall_true=n/a  fact_precision_true=n/a
    hallucinated_facts=[]
    query_lang_true=zh  session_turn_count_true=7  subgoal_count=1
    plan_revision_true=0  goal_drift_true=False  arg_valid_true=1.0000  verifier_pass_true=1.0000
    citation_reachable_true=1.0000  contradiction_true=0.0000  contradicted_count=0  fabricated_citation_count=0
    cache_read_true=156  cache_write_true=202  system_prompt_ratio_true=0.2240  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice3-v0.3.0)
    S=54.0180  G=0.80  grade_abs=D  grade_rel=B  tier=0  novelty=True
    alert=False (rule=False stat=False)  cold_start=True  cell=None
    dims    : O=1.000  P=0.867  L=0.000  C=1.000  R=1.000
    contrib : O=+0.000  P=-2.309  L=-23.673  C=+0.000  R=+0.000   sum=-25.9820
    zero-residual: S-100G=-25.9820  |diff|=1.70e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.2855  a_cal=n/a  conf=0.3500  anchor=anchor-R6-6df7cb38491a91dd
    gates: {"novelty": 0.8}
    evidence (3 items, drill-down order):
      - [trace] latency_total            span=R6-00010-s00   value=33.8314     cell_median=2.0103      z= +21.43 dev=0.7339
      - [trace] cost_total               span=R6-00010-s02   value=0.0078      cell_median=0.0114      z=  -0.62 dev=0.0298
      - [span ] dur                      span=R6-00010-s02   value=21.1234     peer_median=0.7656      z= +25.73 dev=0.7737 (L3/L1span action=summarize)
```

## 六、v3 共生缺陷样本（附录 A 新增特征的原始证据）

下面这些**不是**独立的异常类型，而是叠加在已异常轨迹上的共生缺陷。每一个都由
`bench/coverage.truth_agreement()` 在全部轨迹上做双向等价校验（内核特征 ⟺ 生成器真值），
任何一条对不上都会让构建直接失败，而不是只在报告里留一行警告。


### v3 样本 A：plan_revision —— R6-00009

入口步骤（ontA 的 `plan`、ontB 的 `intent_parse`）出现了两次，第二次的时间区间**嵌套在**第一次之内——智能体在一步还没走完时就重开了计划。`kernel/cluster.collapse()` 会折叠相邻重复，所以模式视图看到的骨架完全不变，只有 `plan_revision_count` 能看见它。这也是该特征被定义成“时间包含”而不是“计数减一”的原因：循环注入器同样可能选中入口步骤，计数减一会把一次循环读成两次计划修订。

```text
==============================================================================
TRACE R6-00009   [intent0: 按严重级别排序输出 NE-565A-56 的当前告警清单]
  ontology=ontA  session=sess-00001  turn=3/7  spans=7  wall=2.888s  ts_start=1767225710.032
  user_feedback: abandoned=False human_takeover=True retry=False thumbs=1
  answer_numbers=['4768', '7381', '2424']
  answer_facts  =['NE-565A-56', '4768', '7381', '2424']
  golden_answer =
  golden_facts  =None
  goal_text     =当前告警清单   query_lang=zh
  answer_citations  =['kb://history/incident-2025-1187', 'runbook://adn/ne-health-check#L48']
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[-0.7402, -0.2465, 0.247, -0.052] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run           2.888 ######### 361       125        0.00148 ok    stop
       in : 按严重级别排序输出 NE-565A-56 的当前告警清单
       out: finished '按严重级别排序输出 NE-565A-56 的当前告警清单' for NE-565A-56; the relevant fig
       meta: model=adn-llm-14b  facts=[4768 7381 2424]
       v3  : sys=159  cache_r=159  cost_det={cache_read:0.000119,completion:0.00075,prompt:0.000606}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan                1.011 ###       555       295        0.00312 ok    stop
         in : task=当前告警清单 ne=NE-565A-56 window=1h; produce a step plan
         out: step list drafted for NE-565A-56;  candidate actions
         meta: model=adn-llm-14b  ttft=0.2504  pv=pv-2026-04-canary
         v3  : sys=140  cache_r=140  cost_det={cache_read:0.000105,completion:0.00177,prompt:0.00125}  subgoal=在 NE-565A-56 上为当前告警清单完成拆解任务步骤
  `- s02           llm         plan                0.404 #         967       313        0.00444 ok    stop
         in : decompose request from NE-565A-56 over 1h into executable steps
         out: ok - step list drafted for NE-565A-56;  candidate actions
         meta: model=adn-llm-14b  ttft=0.1120  pv=pv-2026-04-canary
         v3  : sys=152  cache_r=152  cost_det={cache_read:0.000114,completion:0.00188,prompt:0.00245}  subgoal=围绕当前告警清单执行拆解任务步骤
  `- s03           retrieval   schema_retrieval    0.080 #         383       0          0.00115 ok    -
         in : resolve table definitions needed by NE-565A-56 query
         out: checked and recorded: schema rows: 2424 7381 5981
         meta: tool=catalog.table_schema  params={table:current_alarms}  facts=[2424 7381 5981]
         v3  : cost_det={prompt:0.00115}  arg_valid=True  retrieved=[doc://topology/subnetwork-east-map kb://history/incident-2025-1187 runbook://adn/ne-health-check#L48]
  `- s04           guard       verify              0.125 #         226       100        0.00128 ok    -
         in : compliance scan of the pending step set for NE-565A-56
         out: policy evaluation on NE-565A-56: pass
         meta: level=WARNING  msg=slow query above soft limit
         v3  : cost_det={completion:0.0006,prompt:0.000678}  verifier=v_no_forbidden_action:PASS
  `- s05           tool        sql_query           0.282 #         0         0          0.00020 ok    -
         in : SELECT alarm_id,severity FROM current_alarms WHERE ne='NE-565A-56' AND w
         out: ok - rows returned: 4768 1267
         meta: tool=alarm_db.query  params={ne_id:NE-565A-56,severity:minor,time_window:1h}  facts=[4768 1267]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s06           llm         summarize           1.253 ####      1262      245        0.00477 ok    stop
         in : write the final response for NE-565A-56 from evidence 2424 7381 5981 476
         out: step done - summary drafted from 2424 7381 5981 4768 1267
         meta: model=adn-llm-72b  ttft=0.2918  pv=pv-2026-04-canary
         v3  : sys=218  cache_r=218  cost_det={cache_read:0.000164,completion:0.00147,prompt:0.00313}  verifier=v_numbers_traceable:PASS  subgoal=步骤目标：归纳证据，服务于当前告警清单

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=False  anomaly_types=[]
    intent=i0  pattern=p2  cell=i0|p2
    oracle dim_dev : O=1.00  P=1.00  L=0.56  C=0.73  R=1.00
    latency_true=2.885s  gen_quantiles={'C': 0.542, 'L': 0.8748}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=[]  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.0000  model_mix_true={'adn-llm-14b': 0.6345, 'adn-llm-72b': 0.3655}  feedback_available=True
    has_golden=False  key_fact_recall_true=n/a  fact_precision_true=n/a
    hallucinated_facts=[]
    query_lang_true=zh  session_turn_count_true=7  subgoal_count=3
    plan_revision_true=1  goal_drift_true=False  arg_valid_true=1.0000  verifier_pass_true=1.0000
    citation_reachable_true=1.0000  contradiction_true=0.0000  contradicted_count=0  fabricated_citation_count=0
    cache_read_true=669  cache_write_true=0  system_prompt_ratio_true=0.1782  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice3-v0.3.0)
    S=83.4689  G=1.00  grade_abs=B  grade_rel=C  tier=0  novelty=False
    alert=False (rule=False stat=False)  cold_start=True  cell=i1xp2
    dims    : O=1.000  P=1.000  L=0.498  C=0.602  R=1.000
    contrib : O=+0.000  P=+0.000  L=-9.564  C=-6.967  R=+0.000   sum=-16.5311
    zero-residual: S-100G=-16.5311  |diff|=2.70e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.2209  a_cal=n/a  conf=0.9362  anchor=anchor-R6-6df7cb38491a91dd
    evidence (3 items, drill-down order):
      - [trace] latency_total            span=R6-00009-s00   value=2.8883      cell_median=1.7260      z=  +1.53 dev=0.2820
      - [trace] branch_factor            span=-              value=6.0000      cell_median=4.0000      z=  +1.35 dev=0.2452
      - [span ] dur                      span=R6-00009-s00   value=2.8883      peer_median=1.7565      z=  +1.58 dev=0.2996 (L3/L3span action=agent_run)
```

### v3 样本 B：goal_drift —— R6-00099

某个 `subgoal_text` 与本条轨迹的 `goal_text` **没有任何内容词重叠**——智能体在这一步跑偏了。特征侧用词元包含率 `1 - |G ∩ S| / |G|` 度量：跑偏时恰好为 1.0，在轨时恰好为 0.0，所以 `goal_drift_max >= 0.5` 与真值构成严格的双向等价。生成器为此专门过滤掉任何与目标共享词元的绕路模板，否则真值会声称漂移而数据里量不出来。

```text
==============================================================================
TRACE R6-00099   [intent0: list every entry in the current alarm list of network element NE-5A60-42]
  ontology=ontA  session=sess-00021  turn=3/4  spans=5  wall=0.816s  ts_start=1767226787.351
  user_feedback: none captured
  answer_numbers=['8805']
  answer_facts  =['NE-5A60-42', '8805']
  golden_answer =
  golden_facts  =None
  goal_text     =current alarm list   query_lang=en
  answer_citations  =['runbook://adn/capacity-expansion#L25']
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[-0.3848, -0.4595, 0.5393, 0.0216] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run           0.816 ######### 696       278        0.00345 ok    stop
       in : list every entry in the current alarm list of network element NE-5A60-42
       out: list every entry in the current alarm list of network element NE-5A60-42
       meta: model=adn-llm-14b  facts=[8805]
       v3  : sys=137  cache_r=137  cost_det={cache_read:0.000103,completion:0.00167,prompt:0.00168}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan                0.371 ####      1845      364        0.00722 ok    stop
         in : task=current alarm list ne=NE-5A60-42 window=15m; produce a step plan
         out: step list drafted for NE-5A60-42;  candidate actions (window 15m)
         meta: model=adn-llm-72b  ttft=0.0348  pv=pv-2026-03
         v3  : sys=223  cache_r=223  cost_det={cache_read:0.000167,completion:0.00218,prompt:0.00487}  verifier=v_numbers_traceable:PASS  subgoal=page through archived warehouse stock records
  `- s02           tool        api_call            0.346 ####      0         0          0.00020 ok    -
         in : GET /nbi/v1/ne/NE-5A60-42/alarms?window=15m
         out: response payload ids: 8398 3195 5846 6273
         meta: tool=nbi.ne_status  params={ne_id:NE-5A60-42,scope:ne}  facts=[8398 3195 5846 6273]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s03           retrieval   schema_retrieval    0.066 #         1216      0          0.00365 ok    -
         in : lookup schema for alarm tables of NE-5A60-42
         out: table metadata resolved: 5230 8805 4096 4060; payload attached to the tr
         meta: tool=catalog.table_schema  params={table:alarm_history}  facts=[5230 8805 4096 4060]
         v3  : cost_det={prompt:0.00365}  arg_valid=True  retrieved=[kb://history/incident-2025-1187 runbook://adn/capacity-expansion#L25]
  `- s04           tool        sql_query           0.066 #         0         0          0.00020 ok    -
         in : SELECT kpi_ts,value FROM perf_15min WHERE ne='NE-5A60-42' AND window='15
         out: checked and recorded: query settled; row ids 6674 8067
         meta: tool=alarm_db.query  params={ne_id:NE-5A60-42,severity:critical,time_window:15m}  facts=[6674 8067]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['unfinished']
    intent=i0  pattern=p2  cell=i0|p2
    oracle dim_dev : O=0.55  P=0.20  L=0.88  C=0.52  R=1.00
    latency_true=0.813s  gen_quantiles={'C': 0.9693, 'L': 0.2461}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': True}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=[]  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.0000  model_mix_true={'adn-llm-14b': 0.306, 'adn-llm-72b': 0.694}  feedback_available=False
    has_golden=False  key_fact_recall_true=n/a  fact_precision_true=n/a
    hallucinated_facts=[]
    query_lang_true=en  session_turn_count_true=4  subgoal_count=1
    plan_revision_true=0  goal_drift_true=True  arg_valid_true=1.0000  verifier_pass_true=1.0000
    citation_reachable_true=1.0000  contradiction_true=0.0000  contradicted_count=0  fabricated_citation_count=0
    cache_read_true=360  cache_write_true=0  system_prompt_ratio_true=0.0958  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice3-v0.3.0)
    S=19.4543  G=0.25  grade_abs=D  grade_rel=D  tier=2  novelty=False
    alert=False (rule=False stat=False)  cold_start=True  cell=i1xp2
    dims    : O=0.800  P=0.620  L=0.984  C=0.655  R=1.000
    contrib : O=-1.974  P=-2.114  L=-0.054  C=-1.404  R=+0.000   sum=-5.5457
    zero-residual: S-100G=-5.5457  |diff|=1.90e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.9142  a_cal=n/a  conf=0.9362  anchor=anchor-R6-6df7cb38491a91dd
    gates: {"t1_unfinished": 0.25}
    evidence (3 items, drill-down order):
      - [trace] tokens_total             span=R6-00099-s01   value=4399.0000   cell_median=2991.0000   z=  +0.88 dev=0.1930
      - [trace] cost_total               span=R6-00099-s01   value=0.0147      cell_median=0.0106      z=  +0.71 dev=0.1684
      - [span ] tok                      span=R6-00099-s03   value=1216.0000   peer_median=382.0000    z=  +4.11 dev=0.3926 (L3/L3span action=schema_retrieval)
```

### v3 样本 C：invalid_tool_arg —— R6-00005

工具入参违反了本体的 `param_schema`（枚举越界 / 前缀不符）。`arg_valid` 是**测量**出来的而不是断言的：生成器构造完违规参数后会再跑一次同一个校验函数，只有确实判为违规才落库。循环与重试的副本共享同一份参数，所以一个违规组里的每个副本都同样违规——这是刻意的，否则 `(parent, action, 参数哈希)` 分组会被拆开，一个真循环就悄悄变成了非循环。

```text
==============================================================================
TRACE R6-00005   [intent0: I need the current alarm list for NE-411C-27; if any alarm is critical, flag it]
  ontology=ontA  session=sess-00000  turn=6/7  spans=4  wall=0.796s  ts_start=1767225659.812
  user_feedback: abandoned=False human_takeover=False retry=True thumbs=-1
  answer_numbers=['3827', '7929', '4616']
  answer_facts  =['NE-411C-27', '3827', '7929', '4616']
  golden_answer =
  golden_facts  =None
  goal_text     =current alarm list   query_lang=en
  answer_citations  =[]
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[-0.5196, -0.3091, 0.2734, -0.0023] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run           0.796 ######### 433       173        0.00200 ok    stop
       in : I need the current alarm list for NE-411C-27; if any alarm is critical, 
       out: 'I need the current alarm list for NE-411C-27; if any alarm is critical,
       meta: model=adn-llm-14b  facts=[3827 7929 4616]
       v3  : sys=150  cache_r=150  cost_det={cache_read:0.000112,completion:0.00104,prompt:0.000849}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan                0.174 ##        1520      73         0.00452 error stop
         in : task=current alarm list ne=NE-411C-27 window=24h; produce a step plan
         out: decompose into retrieval then aggregation; window=24h; noted for the ope
         meta: model=adn-llm-72b  level=ERROR  ttft=0.0102  pv=pv-2026-03  msg=upstream timeout after retries
         v3  : sys=212  cache_r=212  cost_det={cache_read:0.000159,completion:0.000438,prompt:0.00392}  subgoal=advance the current alarm list by decomposing the task steps
  `- s02           tool        sql_query           0.174 ##        0         0          0.00020 ok    -
         in : SELECT kpi_ts,value FROM perf_15min WHERE ne='NE-411C-27' AND window='24
         out: query settled; row ids 3827 7929 4616
         meta: tool=alarm_db.query  params={ne_id:NE-411C-27,severity:major,time_window:not-in-enum}  facts=[3827 7929 4616]
         v3  : cost_det={tool_call:0.0002}  arg_valid=False
  `- s03           llm         summarize           0.588 #######   1339      374        0.00578 ok    stop
         in : write the final response for NE-411C-27 from evidence 3827 7929 4616
         out: checked and recorded: answer composed citing 3827 7929 4616
         meta: model=adn-llm-72b  ttft=0.0697  pv=pv-2026-03
         v3  : sys=212  cache_r=212  cost_det={cache_read:0.000159,completion:0.00224,prompt:0.00338}  verifier=v_numbers_traceable:PASS  subgoal=condensing the evidence on NE-411C-27 as part of the current

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['error']
    intent=i0  pattern=p1  cell=i0|p1
    oracle dim_dev : O=0.75  P=1.00  L=0.86  C=0.60  R=0.35
    latency_true=0.793s  gen_quantiles={'C': 0.794, 'L': 0.2889}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=['R6-00005-s01']  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.0000  model_mix_true={'adn-llm-14b': 0.1549, 'adn-llm-72b': 0.8451}  feedback_available=True
    has_golden=False  key_fact_recall_true=n/a  fact_precision_true=n/a
    hallucinated_facts=[]
    query_lang_true=en  session_turn_count_true=7  subgoal_count=2
    plan_revision_true=0  goal_drift_true=False  arg_valid_true=0.0000  verifier_pass_true=1.0000
    citation_reachable_true=n/a  contradiction_true=0.0000  contradicted_count=0  fabricated_citation_count=0
    cache_read_true=574  cache_write_true=0  system_prompt_ratio_true=0.1744  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice3-v0.3.0)
    S=82.2102  G=1.00  grade_abs=B  grade_rel=D  tier=2  novelty=False
    alert=False (rule=False stat=False)  cold_start=True  cell=i1xp1
    dims    : O=0.800  P=1.000  L=0.978  C=0.719  R=0.583
    contrib : O=-8.106  P=+0.000  L=-0.297  C=-4.492  R=-4.895   sum=-17.7898
    zero-residual: S-100G=-17.7898  |diff|=0.00e+00  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.9111  a_cal=n/a  conf=0.9625  anchor=anchor-R6-6df7cb38491a91dd
    evidence (3 items, drill-down order):
      - [trace] error_ratio              span=R6-00005-s01   value=0.2500      cell_median=0.0000      z= +50.00 dev=0.4219
      - [trace] tokens_total             span=R6-00005-s03   value=3912.0000   cell_median=2801.0000   z=  +0.84 dev=0.1527
      - [span ] tok                      span=R6-00005-s01   value=1593.0000   peer_median=1061.0000   z=  +0.92 dev=0.1809 (L3/L3span action=plan)
```

### v3 样本 D：verifier_fail —— R6-00035

确定性校验器给出 FAIL。三个校验器全部是代码判定，没有任何生成式判官参与：`v_numbers_traceable`（答案里的数字必须能在证据池中找到）、`v_no_forbidden_action`（禁用动作不得被启动）、`v_answer_nonempty`（答案非空）。它们的结果是从落库记录本身反推出来的，而不是生成器的意图。

```text
==============================================================================
TRACE R6-00035   [intent1: correlate alarms and KPI series on NE-AE11-06, then report the degradation root cause]
  ontology=ontA  session=sess-00006  turn=4/5  spans=4  wall=51.313s  ts_start=1767226020.179
  user_feedback: none captured
  answer_numbers=['3315', '4549', '73']
  answer_facts  =['NE-AE11-06', '3315', '4549', '73']
  golden_answer =
  golden_facts  =None
  goal_text     =degradation root cause   query_lang=en
  answer_citations  =['doc://policy/change-approval-rules#L7', 'runbook://adn/ne-health-check#L48']
  contradicted_facts=[]
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[0.299, -0.2989, 0.6756, 0.0145] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run          51.313 ######### 218       87         0.00087 ok    length
       in : correlate alarms and KPI series on NE-AE11-06, then report the degradati
       out: operator summary for NE-AE11-06 (correlate alarms and KPI series on NE-A
       meta: model=adn-llm-14b  facts=[3315 4549 73]
       v3  : sys=137  cache_r=137  cost_det={cache_read:0.000103,completion:0.000522,prompt:0.000243}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan               19.712 ###       276       207        0.00261 ok    stop
         in : task=degradation root cause ne=NE-AE11-06 window=24h; produce a step pla
         out: decompose into retrieval then aggregation; window=24h for NE-AE11-06
         meta: model=adn-llm-14b  ttft=4.4675  pv=pv-2026-03
         v3  : sys=143  cache_w=143  cost_det={cache_write:0.000536,completion:0.00124,prompt:0.000828}  subgoal=advance the degradation root cause by decomposing the task s
  `- s02           retrieval   retrieve_kb         8.645 ##        260       0          0.00078 ok    -
         in : history search over incidents touching NE-AE11-06
         out: step done - matched runbook evidence: 4085 4549 3315 4238
         meta: tool=kb.runbook_search  params={query:NE-AE11-06,top_k:5}  facts=[4085 4549 3315 4238]
         v3  : cost_det={prompt:0.00078}  arg_valid=True  retrieved=[doc://policy/change-approval-rules#L7 runbook://adn/ne-health-check#L48]
  `- s03           llm         summarize          20.952 ####      634       228        0.00280 ok    stop
         in : condense evidence 4085 4549 3315 4238 into an operator-facing answer
         out: answer composed citing 4085 4549 3315 4238; noted for the operator
         meta: model=adn-llm-72b  ttft=1.1728  pv=pv-2026-03
         v3  : sys=207  cache_r=207  cost_det={cache_read:0.000155,completion:0.00137,prompt:0.00128}  verifier=v_numbers_traceable:FAIL(answer number absent from the evidence pool)  subgoal=work on condensing the evidence to advance the degrada

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['truncation']
    intent=i1  pattern=p3  cell=i1|p3
    oracle dim_dev : O=0.35  P=1.00  L=0.79  C=0.88  R=1.00
    latency_true=51.310s  gen_quantiles={'C': 0.241, 'L': 0.4107}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=[]  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.0000  model_mix_true={'adn-llm-14b': 0.4776, 'adn-llm-72b': 0.5224}  feedback_available=False
    has_golden=False  key_fact_recall_true=n/a  fact_precision_true=n/a
    hallucinated_facts=[]
    query_lang_true=en  session_turn_count_true=5  subgoal_count=2
    plan_revision_true=0  goal_drift_true=False  arg_valid_true=1.0000  verifier_pass_true=0.5000
    citation_reachable_true=1.0000  contradiction_true=0.0000  contradicted_count=0  fabricated_citation_count=0
    cache_read_true=344  cache_write_true=143  system_prompt_ratio_true=0.3509  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice3-v0.3.0)
    S=19.7772  G=0.25  grade_abs=D  grade_rel=D  tier=2  novelty=False
    alert=False (rule=False stat=False)  cold_start=True  cell=i0xp0
    dims    : O=0.627  P=1.000  L=0.757  C=0.963  R=1.000
    contrib : O=-4.166  P=+0.000  L=-0.931  C=-0.126  R=+0.000   sum=-5.2228
    zero-residual: S-100G=-5.2228  |diff|=2.20e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.9056  a_cal=n/a  conf=0.9291  anchor=anchor-R6-6df7cb38491a91dd
    gates: {"t0_result_broken": 0.25}
    evidence (3 items, drill-down order):
      - [trace] traceable_number_ratio   span=-              value=0.6667      cell_median=1.0000      z= -50.00 dev=0.3770
      - [trace] latency_total            span=R6-00035-s00   value=51.3127     cell_median=44.6727     z=  +0.25 dev=0.1244
      - [span ] dur                      span=R6-00035-s01   value=19.7118     peer_median=12.4304     z=  +0.83 dev=0.1749 (L3/L3span action=plan)
```

### v3 样本 E：fabricated_citation —— R6-00081

答案引用了一个**格式完全合法**的定位符，但它不在本次检索到的结果集里。真实智能体的编造几乎从不是凭空造一个URL，而是把片段号写错——所以 `citation_reachability` 必须对着检索结果集算，而不是对着 URL 白名单或格式校验算。生成器正是这样伪造的：取一个真实定位符，把 `#L` 片段改到 1001~1900 区间。

```text
==============================================================================
TRACE R6-00081   [intent1: I need the degradation root cause on NE-E649-38; include the metric that proves it]
  ontology=ontA  session=sess-00017  turn=3/3  spans=6  wall=23.598s  ts_start=1767226574.260
  user_feedback: none captured
  answer_numbers=['3172', '9877', '24181', '41832']
  answer_facts  =['NE-E649-38', '3172', '9877', '24181', '41832']
  golden_answer =
  golden_facts  =None
  goal_text     =degradation root cause   query_lang=en
  answer_citations  =['doc://policy/change-approval-rules#L1885', 'runbook://adn/ne-health-check#L1398']
  contradicted_facts=['3172', '9877']
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[0.0491, -0.3661, 0.6311, -0.0044] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run          23.598 ######### 153       61         0.00134 ok    stop
       in : I need the degradation root cause on NE-E649-38; include the metric that
       out: I need the degradation root cause on NE-E649-38; include the metric that
       meta: model=adn-llm-14b  facts=[3172 9877 24181 41832]
       v3  : sys=137  cache_w=137  cost_det={cache_write:0.000514,completion:0.000366,prompt:0.000459}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan                9.428 ####      553       229        0.00266 ok    stop
         in : decompose request from NE-E649-38 over 5m into executable steps
         out: ok - decompose into retrieval then aggregation; window=5m
         meta: model=adn-llm-14b  ttft=1.9765  pv=pv-2026-03
         v3  : sys=164  cache_r=164  cost_det={cache_read:0.000123,completion:0.00137,prompt:0.00117}  subgoal=decomposing the task steps on NE-E649-38 as part of the degr
  `- s02           tool        sql_query          10.017 ####      0         0          0.00020 ok    -
         in : SELECT kpi_ts,value FROM perf_15min WHERE ne='NE-E649-38' AND window='5m
         out: query settled; row ids 9877 3172 5487; noted for the operator
         meta: tool=perf_db.query  params={ne_id:NE-E649-38,severity:critical,time_window:5m}  facts=[9877 3172 5487]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
    `- s02-n1        tool        sql_query           6.010 ##        0         0          0.00020 ok    -
           in : nested sql_query call for NE-E649-38
           out: query settled; row ids 9877 3172 5487; noted for the operator
           meta: tool=perf_db.query  params={ne_id:NE-E649-38,severity:critical,time_window:5m}  facts=[9877 3172 5487]
           v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s03           guard       approve             2.186 #         128       16         0.00048 ok    -
         in : route the pending change on NE-E649-38 to the approver
         out: approval gate pass on NE-E649-38
         v3  : cost_det={completion:9.6e-05,prompt:0.000384}  verifier=v_no_forbidden_action:PASS
  `- s04           llm         summarize           0.934 #         388       156        0.00179 ok    stop
         in : write the final response for NE-E649-38 from evidence 9877 3172 5487
         out: summary drafted from 9877 3172 5487; payload attached to the trace
         meta: model=adn-llm-14b  ttft=0.1143  pv=pv-2026-03
         v3  : sys=137  cache_r=137  cost_det={cache_read:0.000103,completion:0.000936,prompt:0.000753}  verifier=v_numbers_traceable:FAIL(answer number absent from the evidence pool)  subgoal=step goal: condensing the evidence, serving the degr

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['hallucinated_number']
    intent=i1  pattern=p1  cell=i1|p1
    oracle dim_dev : O=0.15  P=1.00  L=0.98  C=0.97  R=1.00
    latency_true=23.595s  gen_quantiles={'C': 0.0681, 'L': 0.0368}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=[]  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.0000  model_mix_true={'adn-llm-14b': 1.0}  feedback_available=False
    has_golden=False  key_fact_recall_true=n/a  fact_precision_true=n/a
    hallucinated_facts=[]
    query_lang_true=en  session_turn_count_true=3  subgoal_count=2
    plan_revision_true=0  goal_drift_true=False  arg_valid_true=1.0000  verifier_pass_true=0.6667
    citation_reachable_true=0.0000  contradiction_true=0.4000  contradicted_count=2  fabricated_citation_count=2
    cache_read_true=301  cache_write_true=137  system_prompt_ratio_true=0.3584  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice3-v0.3.0)
    S=42.7893  G=0.60  grade_abs=D  grade_rel=D  tier=2  novelty=False
    alert=False (rule=False stat=False)  cold_start=True  cell=i0xp1
    dims    : O=0.440  P=1.000  L=0.958  C=0.979  R=1.000
    contrib : O=-16.719  P=+0.000  L=-0.330  C=-0.162  R=+0.000   sum=-17.2107
    zero-residual: S-100G=-17.2107  |diff|=3.50e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.8999  a_cal=n/a  conf=0.8941  anchor=anchor-R6-6df7cb38491a91dd
    gates: {"t2_untraceable_number": 0.6}
    evidence (3 items, drill-down order):
      - [trace] traceable_number_ratio   span=-              value=0.5000      cell_median=1.0000      z= -50.00 dev=0.4330
      - [trace] depth                    span=-              value=3.0000      cell_median=2.0000      z= +50.00 dev=0.2378
      - [span ] dur                      span=R6-00081-s02   value=10.0166     peer_median=7.9332      z=  +0.32 dev=0.1368 (L3/L3span action=sql_query)
```

### v3 样本 F：contradicted_evidence —— R6-00076

答案陈述了与证据相反的关系。注意它与幻觉的区别：矛盾涉及的事实**在**证据池里，只是关系被说反了。生成器只从`golden_facts ∩ answer_facts` 里采样，从结构上保证了这一点。特征侧的 `contradiction_rate` 仍标记为`needs_model`——数据集负责提供输入与真值，数值本身要等真实 NLI 模型接上才有意义。

```text
==============================================================================
TRACE R6-00076   [intent1: 定位网元 NE-9573-04 的劣化根因]
  ontology=ontA  session=sess-00015  turn=3/3  spans=5  wall=49.114s  ts_start=1767226512.603
  user_feedback: none captured
  answer_numbers=['1202', '7242', '2337', '93']
  answer_facts  =['NE-9573-04', '1202', '7242', '2337', '93']
  golden_answer =
  golden_facts  =None
  goal_text     =劣化根因   query_lang=zh
  answer_citations  =['doc://vendor/nbi-api-reference#L310']
  contradicted_facts=['1202', '7242']
  raw_flags(as ingested): field_loss=0 orphan=False ts_missing=False usage_estimated=False
  embedding[0:4]=[-0.0823, -0.2328, 0.7709, -0.0528] ... (384 dims, intent view input)

  SPAN TREE (execution process)
     span          kind        action             dur(s) share     tok_in    tok_out    cost($) stat  finish
  -  s00           agent       agent_run          49.114 ######### 195       67         0.00055 ok    length
       in : 定位网元 NE-9573-04 的劣化根因
       out: completed '定位网元 NE-9573-04 的劣化根因' on NE-9573-04; values: 1202, 7242, 233
       meta: model=adn-llm-72b  facts=[1202 7242 2337 93]
       v3  : sys=195  cache_r=195  cost_det={cache_read:0.000146,completion:0.000402}  verifier=v_answer_nonempty:PASS
  `- s01           llm         plan               28.848 #####     470       56         0.00128 ok    stop
         in : task=劣化根因 ne=NE-9573-04 window=24h; produce a step plan
         out: checked and recorded: decompose into retrieval then aggregation; window=
         meta: model=adn-llm-72b  ttft=4.3202  pv=pv-2026-03
         v3  : sys=209  cache_r=209  cost_det={cache_read:0.000157,completion:0.000336,prompt:0.000783}  subgoal=在 NE-9573-04 上为劣化根因完成拆解任务步骤
  `- s02           tool        api_call           14.927 ###       0         0          0.00020 ok    -
         in : GET /nbi/v1/ne/NE-9573-04/alarms?window=24h
         out: response payload ids: 2316 2337 8170 7242 for NE-9573-04
         meta: tool=nbi.ne_status  params={ne_id:NE-9573-04,scope:ne}  facts=[2316 2337 8170 7242]
         v3  : cost_det={tool_call:0.0002}  arg_valid=True
  `- s03           retrieval   retrieve_kb         2.417 #         247       0          0.00074 ok    -
         in : history search over incidents touching NE-9573-04
         out: ok - knowledge hits ranked: 8524 2117 4289 1202
         meta: tool=kb.runbook_search  level=WARNING  msg=partial result set returned  params={query:NE-9573-04,top_k:5}  facts=[8524 2117 4289 1202]
         v3  : cost_det={prompt:0.000741}  arg_valid=True  retrieved=[doc://policy/change-approval-rules#L7 doc://vendor/nbi-api-reference#L310 kb://history/incident-2025-1187]
  `- s04           llm         summarize           2.417 #         529       259        0.00282 ok    stop
         in : write the final response for NE-9573-04 from evidence 8170 7242 8524 211
         out: summary drafted from 8170 7242 8524 2117 4289 1202 (window 24h)
         meta: model=adn-llm-14b  level=WARNING  ttft=0.2011  pv=pv-2026-03  msg=partial result set returned
         v3  : sys=141  cache_r=141  cost_det={cache_read:0.000106,completion:0.00155,prompt:0.00116}  verifier=v_numbers_traceable:FAIL(answer number absent from the evidence pool)  subgoal=在 NE-9573-04 上为劣化根因完成归纳证据

  GROUND TRUTH (what the generator knows; the pipeline never sees this)
    is_anomaly=True  anomaly_types=['truncation']
    intent=i1  pattern=p3  cell=i1|p3
    oracle dim_dev : O=0.35  P=1.00  L=0.57  C=0.95  R=1.00
    latency_true=49.111s  gen_quantiles={'C': 0.1029, 'L': 0.8653}
    process_flags={'illegal_step': False, 'missing_step': False, 'unfinished': False}
    defect_flags(after normalize)={'orphan_rebuilt': False, 'ts_repaired': False, 'usage_estimated': False}
    responsible_span_ids=[]  human_label=None  drift_segment=None
    loop_true=False  mfr_true=0.0000  model_mix_true={'adn-llm-14b': 0.5, 'adn-llm-72b': 0.5}  feedback_available=False
    has_golden=False  key_fact_recall_true=n/a  fact_precision_true=n/a
    hallucinated_facts=[]
    query_lang_true=zh  session_turn_count_true=3  subgoal_count=2
    plan_revision_true=0  goal_drift_true=False  arg_valid_true=1.0000  verifier_pass_true=0.5000
    citation_reachable_true=1.0000  contradiction_true=0.4000  contradicted_count=2  fabricated_citation_count=0
    cache_read_true=545  cache_write_true=0  system_prompt_ratio_true=0.3782  cost_details_reconciled_true=True

  PIPELINE OUTPUT (slice3-v0.3.0)
    S=21.0498  G=0.25  grade_abs=D  grade_rel=D  tier=2  novelty=False
    alert=False (rule=False stat=False)  cold_start=True  cell=i0xp0
    dims    : O=0.720  P=1.000  L=0.771  C=0.989  R=1.000
    contrib : O=-3.018  P=+0.000  L=-0.895  C=-0.037  R=+0.000   sum=-3.9502
    zero-residual: S-100G=-3.9502  |diff|=3.20e-05  OK  (rounded JSONL rows;
                   exact identity asserted in bench/runner.py)
    a_raw=0.9167  a_cal=n/a  conf=0.9291  anchor=anchor-R6-6df7cb38491a91dd
    gates: {"t0_result_broken": 0.25}
    evidence (3 items, drill-down order):
      - [trace] traceable_number_ratio   span=-              value=0.7500      cell_median=1.0000      z= -50.00 dev=0.3593
      - [trace] latency_total            span=R6-00076-s00   value=49.1138     cell_median=44.6727     z=  +0.16 dev=0.1143
      - [span ] dur                      span=R6-00076-s01   value=28.8482     peer_median=12.4304     z=  +1.88 dev=0.2275 (L3/L3span action=plan)
```

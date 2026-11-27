"""E3: execution-view structural vectorizer (methodology 5.3 route A) contract tests."""
import copy
import json
import unittest
from pathlib import Path

from kernel import cluster
from platform.app.algorithm import dump_frozen_state, load_frozen_state, run_production
from platform.app.encoder import EncoderContractError

ROOT = Path(__file__).resolve().parents[2]


def _bench_traces(limit=100):
    traces = []
    path = ROOT / "data" / "bench_v1" / "R1" / "traces.jsonl"
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            traces.append(json.loads(line))
            if len(traces) == limit:
                break
    return traces


def _feat(trace_id, embedding, actions, spans=None):
    return {
        "trace_id": trace_id,
        "embedding": embedding,
        "action_seq": actions,
        "spans": spans or [{"kind": "llm", "action": a} for a in actions],
    }


class SpanKeyTest(unittest.TestCase):
    def test_full_fields(self):
        span = {"agent": "planner", "operation": "plan_step", "kind": "agent",
                "action": "plan", "tool_name": "db"}
        self.assertEqual("planner::plan_step::db", cluster.span_key(span))

    def test_explicit_degradation_never_fabricates(self):
        span = {"kind": "tool", "action": "sql_query", "tool_name": "db"}
        self.assertEqual("tool::sql_query::db", cluster.span_key(span))
        self.assertEqual("tool::sql_query::-",
                         cluster.span_key({"kind": "tool", "action": "sql_query"}))
        self.assertEqual("?::?::-", cluster.span_key({}))

    def test_pattern_tokens_recipes(self):
        feat = _feat("t", [0.0], ["plan", "sql_query"],
                     spans=[{"kind": "agent", "action": "plan", "agent": "planner",
                             "operation": "plan_step"},
                            {"kind": "tool", "action": "sql_query", "tool_name": "db"}])
        self.assertEqual(["plan", "sql_query"],
                         cluster.pattern_tokens(feat, "action:v1"))
        self.assertEqual(["planner::plan_step", "tool::sql_query"],
                         cluster.pattern_tokens(feat, "span_key:v1-no-tool"))
        self.assertEqual(["planner::plan_step::-", "tool::sql_query::db"],
                         cluster.pattern_tokens(feat, "span_key:v1"))
        with self.assertRaises(ValueError):
            cluster.pattern_tokens(feat, "bogus:v9")


class TfidfVectorizerTest(unittest.TestCase):
    DOCS = [["intake", "ground", "generate"], ["intake", "retrieve", "generate"]]

    def test_fit_is_deterministic(self):
        a = cluster.fit_pattern_vectorizer(self.DOCS, salient={"ground"})
        b = cluster.fit_pattern_vectorizer(list(self.DOCS), salient={"ground"})
        self.assertEqual(a, b)

    def test_vec_is_l2_normalized(self):
        ctx = cluster.fit_pattern_vectorizer(self.DOCS)
        vec = cluster.pattern_vec(self.DOCS[0], ctx)
        self.assertAlmostEqual(1.0, sum(w * w for w in vec.values()) ** 0.5, places=9)

    def test_cosine_distance_bounds(self):
        ctx = cluster.fit_pattern_vectorizer(self.DOCS)
        va = cluster.pattern_vec(self.DOCS[0], ctx)
        self.assertAlmostEqual(0.0, cluster.pattern_cos_dist(va, va), places=9)
        disjoint = cluster.pattern_vec(["zzz", "yyy"], ctx)
        self.assertAlmostEqual(1.0, cluster.pattern_cos_dist(va, disjoint), places=9)

    def test_saliency_multiplier_boosts_salient_tokens(self):
        plain = cluster.fit_pattern_vectorizer(self.DOCS)
        boosted = cluster.fit_pattern_vectorizer(self.DOCS, salient={"ground"})
        vp = cluster.pattern_vec(self.DOCS[0], plain)
        vb = cluster.pattern_vec(self.DOCS[0], boosted)
        self.assertGreater(vb["ground"] / vb["intake"], vp["ground"] / vp["intake"])

    def test_fingerprint_stable_and_sensitive(self):
        salient = set() if cluster.TFIDF_SALIENCY else None
        same = cluster.fit_pattern_vectorizer(self.DOCS, salient=salient)
        self.assertEqual(same["fingerprint"],
                         cluster.fit_pattern_vectorizer([list(d) for d in self.DOCS],
                                                        salient=salient)["fingerprint"])
        self.assertEqual(same["fingerprint"], cluster.current_pattern_fingerprint("action:v1"))
        self.assertNotEqual(same["fingerprint"],
                            cluster.current_pattern_fingerprint("span_key:v1"))
        config = dict(same["config"])
        config["ngram_max"] = 2
        self.assertNotEqual(same["fingerprint"], cluster.structural_fingerprint(config))

    def test_saliency_switch_changes_fingerprint(self):
        with_sal = cluster.fit_pattern_vectorizer(self.DOCS, salient=set())
        without_sal = cluster.fit_pattern_vectorizer(self.DOCS, salient=None)
        self.assertNotEqual(with_sal["fingerprint"], without_sal["fingerprint"])


class ClusterViewsStructuralTest(unittest.TestCase):
    def _feats(self):
        feats = []
        for i in range(24):
            if i % 2 == 0:
                feats.append(_feat("t%d" % i, [float(i % 3), float(i % 2), 0.1 * i, 1.0],
                                   ["intake", "ground", "generate", "verify", "deliver"]))
            else:
                feats.append(_feat("t%d" % i, [float(i % 2), float(i % 3), 0.1 * i, 1.0],
                                   ["intake", "retrieve", "ground", "generate", "deliver"]))
        return feats

    def test_emits_structural_info(self):
        _, info = cluster.cluster_views(self._feats(), seed=7)
        self.assertEqual("action:v1", info["pattern_token_recipe"])
        self.assertEqual(cluster.current_pattern_fingerprint("action:v1"),
                         info["structural_fingerprint"])
        top = info["pattern_top_ngrams"]
        self.assertEqual(info["n_pattern_clusters"], len(top))
        for grams in top.values():
            self.assertLessEqual(len(grams), cluster.PATTERN_TOP_NGRAMS)
            self.assertTrue(all(isinstance(g, str) for g in grams))

    def test_span_key_recipe_changes_fingerprint(self):
        _, info = cluster.cluster_views(self._feats(), seed=7,
                                        pattern_recipe="span_key:v1")
        self.assertEqual("span_key:v1", info["pattern_token_recipe"])
        self.assertEqual(cluster.current_pattern_fingerprint("span_key:v1"),
                         info["structural_fingerprint"])
        self.assertNotEqual(cluster.current_pattern_fingerprint("action:v1"),
                            info["structural_fingerprint"])

    def test_unknown_recipe_raises(self):
        with self.assertRaises(ValueError):
            cluster.cluster_views(self._feats(), seed=7, pattern_recipe="bogus:v9")


class FrozenStructuralGateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.traces = _bench_traces()
        result, _scores = run_production(cls.traces, "ontology-e3-gate")
        cls.state = result["frozen_state"]

    def test_frozen_state_carries_tfidf_ctx(self):
        ctx = self.state.get("_tfidf_ctx")
        self.assertIsNotNone(ctx)
        self.assertEqual(cluster.current_pattern_fingerprint("action:v1"),
                         ctx["fingerprint"])
        self.assertTrue(ctx["idf"])
        self.assertEqual("action:v1", ctx["config"]["span_key_recipe"])
        self.assertEqual(3, ctx["config"]["ngram_max"])

    def test_r1_replay_with_tfidf_ctx(self):
        result, scores = run_production(self.traces, "ontology-e3-gate",
                                        frozen_state=self.state)
        self.assertFalse(result["cold_start"])
        self.assertEqual(len(self.traces), len(scores))

    def test_r1_rejects_tampered_fingerprint(self):
        tampered = copy.deepcopy(self.state)
        tampered["_tfidf_ctx"]["fingerprint"] = "0" * 16
        with self.assertRaises(EncoderContractError):
            run_production(self.traces, "ontology-e3-gate", frozen_state=tampered)

    def test_r1_rejects_missing_ctx(self):
        legacy = {key: value for key, value in self.state.items() if key != "_tfidf_ctx"}
        with self.assertRaises(EncoderContractError):
            run_production(self.traces, "ontology-e3-gate", frozen_state=legacy)

    def test_dump_load_roundtrip_preserves_ctx(self):
        loaded = load_frozen_state(dump_frozen_state(self.state))
        self.assertEqual(self.state["_tfidf_ctx"], loaded["_tfidf_ctx"])
        result, scores = run_production(self.traces, "ontology-e3-gate",
                                        frozen_state=loaded)
        self.assertEqual(len(self.traces), len(scores))

    def test_load_tolerates_legacy_state_without_ctx(self):
        legacy = {key: value for key, value in self.state.items() if key != "_tfidf_ctx"}
        loaded = load_frozen_state(dump_frozen_state(legacy))
        self.assertNotIn("_tfidf_ctx", loaded)
        with self.assertRaises(EncoderContractError):
            run_production(self.traces, "ontology-e3-gate", frozen_state=loaded)


if __name__ == "__main__":
    unittest.main()

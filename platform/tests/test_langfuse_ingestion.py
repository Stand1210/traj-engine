import unittest

from platform.app.langfuse_ingestion import LangfuseOTLPTraceIngestor, build_otlp_trace_payload


class FakeIngestTransport:
    def __init__(self, response=None):
        self.response = {} if response is None else response
        self.requests = []

    def __call__(self, url, body, headers):
        self.requests.append({"url": url, "body": body, "headers": headers})
        return self.response


def trace():
    return {
        "trace_id": "0123456789abcdef0123456789abcdef",
        "session_id": "session-1",
        "ontology_id": "ontology-dev",
        "intent_text": "traj-engine-dev",
        "ts_start": 1760000000,
        "spans": [
            {
                "span_id": "0123456789abcdef",
                "parent_id": None,
                "action": "root",
                "kind": "agent",
                "input_text": {"query": "hello"},
                "output_text": {"answer": "ok"},
                "ts_start": 1760000000,
                "ts_end": 1760000003,
            },
            {
                "span_id": "fedcba9876543210",
                "parent_id": "0123456789abcdef",
                "action": "api_call",
                "kind": "tool",
                "tool_name": "nbi.alarm_list",
                "tool_params": {"ne_id": "NE-1"},
                "ts_start": 1760000001,
                "ts_end": 1760000002,
            },
        ],
    }


class LangfuseOTLPTraceIngestorTest(unittest.TestCase):
    def test_builds_v4_otlp_payload(self):
        payload = build_otlp_trace_payload(trace())
        spans = payload["resourceSpans"][0]["scopeSpans"][0]["spans"]

        self.assertEqual("0123456789abcdef0123456789abcdef", spans[0]["traceId"])
        self.assertIsNone(spans[0]["parentSpanId"])
        self.assertEqual("0123456789abcdef", spans[1]["parentSpanId"])
        self.assertEqual("1760000000000000000", spans[0]["startTimeUnixNano"])

    def test_ingest_uses_configured_endpoint_and_headers(self):
        transport = FakeIngestTransport()
        ingestor = LangfuseOTLPTraceIngestor("https://langfuse.example/", "pk", "sk", "/custom/traces", transport=transport)
        result = ingestor.ingest(trace())

        self.assertEqual(
            {"status": "accepted", "mode": "sync", "trace_id": "0123456789abcdef0123456789abcdef", "spans": 2},
            result,
        )
        self.assertEqual("https://langfuse.example/custom/traces", transport.requests[0]["url"])
        self.assertEqual("4", transport.requests[0]["headers"]["x-langfuse-ingestion-version"])

    def test_rejects_non_empty_success_response(self):
        transport = FakeIngestTransport({"unexpected": True})
        ingestor = LangfuseOTLPTraceIngestor("https://langfuse.example", "pk", "sk", transport=transport)

        with self.assertRaisesRegex(ValueError, "unrecognized response"):
            ingestor.ingest(trace())

    def test_accepts_cloud_async_ingestion_job(self):
        transport = FakeIngestTransport(
            {
                "name": "otel-ingestion-job",
                "data": {
                    "payload": {
                        "data": {"fileKey": "otel/project-1/trace.json"},
                        "authCheck": {"validKey": True, "scope": {"projectId": "project-1"}},
                    },
                },
            }
        )
        ingestor = LangfuseOTLPTraceIngestor("https://langfuse.example", "pk", "sk", transport=transport)

        self.assertEqual("async", ingestor.ingest(trace())["mode"])


if __name__ == "__main__":
    unittest.main()

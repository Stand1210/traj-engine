import unittest

from platform.app.langfuse_source import LangfuseTraceSource
from platform.app.langfuse_source import LangfuseHttpError
from platform.app.trace_source import TRACE_KEYS, SPAN_KEYS


class FakeTransport:
    def __init__(self, pages):
        self.pages = pages
        self.requests = []

    def __call__(self, url, params, headers):
        self.requests.append({"url": url, "params": params, "headers": headers})
        return self.pages.pop(0)


def observation(observation_id, trace_id="trace-1", **overrides):
    value = {
        "id": observation_id,
        "traceId": trace_id,
        "startTime": "2026-01-02T03:04:05Z",
        "endTime": "2026-01-02T03:04:07Z",
        "projectId": "project-1",
        "parentObservationId": None,
        "type": "AGENT",
        "isRootObservation": True,
        "name": "agent_run",
        "level": "DEFAULT",
        "model": "model-a",
        "usageDetails": {"input": 10, "output": 3},
        "costDetails": {"input": 0.1, "output": 0.2, "toolCall": 0.3},
        "totalCost": 0.6,
        "timeToFirstToken": 0.2,
        "metadata": {"ontology_id": "ontA", "raw_flags": '{"usage_estimated": true}', "verifier": '{"id": "v", "passed": true}'},
    }
    value.update(overrides)
    return value


class LangfuseTraceSourceTest(unittest.TestCase):
    def test_cursor_continues_after_empty_page(self):
        pages = [
            {"data": [observation("obs-1")], "meta": {"cursor": "cursor-1"}},
            {"data": [], "meta": {"cursor": "cursor-2"}},
            {"data": [], "meta": {"cursor": None}},
        ]
        transport = FakeTransport(pages)
        source = LangfuseTraceSource("https://langfuse.example", "pk", "sk", transport=transport)
        traces = list(source.list_traces({"start": "2026-01-01T00:00:00Z", "end": "2026-01-03T00:00:00Z"}, {}))

        self.assertEqual(1, len(traces))
        self.assertEqual(3, len(transport.requests))
        self.assertEqual("cursor-1", transport.requests[1]["params"]["cursor"])
        self.assertEqual("cursor-2", transport.requests[2]["params"]["cursor"])
        self.assertEqual(3, source.traversal["pages"])
        self.assertEqual(2, source.traversal["empty_pages"])
        self.assertEqual({"usage_estimated": True}, traces[0]["raw_flags"])

    def test_maps_langfuse_observation_to_kernel_contract(self):
        child = observation(
            "obs-2",
            parentObservationId="obs-1",
            isRootObservation=False,
            type="TOOL",
            name="api_call",
            usageDetails={"input": 0, "output": 0},
            metadata={"tool_name": "nbi.alarm_list", "tool_params": '{"ne_id": "NE-1"}'},
        )
        pages = [{"data": [observation("obs-1"), child], "meta": {"cursor": None}}]
        source = LangfuseTraceSource("https://langfuse.example", "pk", "sk", transport=FakeTransport(pages))
        trace = next(source.list_traces({"start": "2026-01-01T00:00:00Z", "end": "2026-01-03T00:00:00Z"}, {}))

        self.assertEqual(TRACE_KEYS, set(trace))
        self.assertEqual(2, len(trace["spans"]))
        self.assertEqual(SPAN_KEYS, set(trace["spans"][1]))
        self.assertEqual("obs-1", trace["spans"][1]["parent_id"])
        self.assertEqual("tool", trace["spans"][1]["kind"])
        self.assertEqual({"ne_id": "NE-1"}, trace["spans"][1]["tool_params"])

    def test_missing_fields_are_not_fabricated(self):
        pages = [{"data": [observation("obs-1")], "meta": {"cursor": None}}]
        source = LangfuseTraceSource("https://langfuse.example", "pk", "sk", transport=FakeTransport(pages))
        trace = next(source.list_traces({"start": "2026-01-01T00:00:00Z", "end": "2026-01-03T00:00:00Z"}, {}))

        self.assertIsNone(trace["golden_answer"])
        self.assertIsNone(trace["embedding"])
        self.assertIsNone(trace["spans"][0]["tokens_system_prompt"])

    def test_empty_page_without_cursor_is_terminal(self):
        pages = [{"data": [], "meta": {}}]
        source = LangfuseTraceSource("https://langfuse.example", "pk", "sk", transport=FakeTransport(pages))
        traces = list(source.list_traces({"start": "2026-01-01T00:00:00Z", "end": "2026-01-03T00:00:00Z"}, {}))

        self.assertEqual([], traces)
        self.assertEqual(1, source.traversal["pages"])
        self.assertEqual(1, source.traversal["empty_pages"])

    def test_non_empty_page_without_cursor_is_terminal(self):
        pages = [{"data": [observation("obs-1")], "meta": {}}]
        source = LangfuseTraceSource("https://langfuse.example", "pk", "sk", transport=FakeTransport(pages))
        traces = list(source.list_traces({"start": "2026-01-01T00:00:00Z", "end": "2026-01-03T00:00:00Z"}, {}))

        self.assertEqual(1, len(traces))
        self.assertEqual(0, source.traversal["empty_pages"])

    def test_incomplete_trace_is_skipped_and_reported(self):
        child = observation(
            "obs-2",
            parentObservationId="obs-missing",
            isRootObservation=False,
        )
        pages = [{"data": [child], "meta": {"cursor": None}}]
        source = LangfuseTraceSource("https://langfuse.example", "pk", "sk", transport=FakeTransport(pages))
        traces = list(source.list_traces({"start": "2026-01-01T00:00:00Z", "end": "2026-01-03T00:00:00Z"}, {}))

        self.assertEqual([], traces)
        self.assertEqual(1, source.traversal["incomplete_traces"])

    def test_retries_rate_limit_once(self):
        class RetryTransport(FakeTransport):
            def __init__(self):
                super().__init__([{"data": [], "meta": {"cursor": None}}])
                self.calls = 0

            def __call__(self, url, params, headers):
                self.calls += 1
                if self.calls == 1:
                    raise LangfuseHttpError(429, "rate limited")
                return super().__call__(url, params, headers)

        transport = RetryTransport()
        source = LangfuseTraceSource("https://langfuse.example", "pk", "sk", transport=transport, retry_backoff_seconds=0)
        list(source.list_traces({"start": "2026-01-01T00:00:00Z", "end": "2026-01-03T00:00:00Z"}, {}))

        self.assertEqual(2, transport.calls)

    def test_builds_from_endpoint_config(self):
        profile = {"baseUrl": "https://langfuse.example", "capabilities": {"observationsApi": "v2"}}
        endpoints = {
            "endpoints": {"observations": {"list": {"path": "/custom/observations", "query": {"fields": "core,basic", "expandMetadata": "ontology_id"}}}},
            "limits": {"observationsPageSizeDefault": 77},
        }
        keys = {"publicKey": "pk", "secretKey": "sk"}
        source = LangfuseTraceSource.from_config(profile, endpoints, keys)

        self.assertEqual("https://langfuse.example", source.base_url)
        self.assertEqual("/custom/observations", source.observations_path)
        self.assertEqual("core,basic", source.fields)
        self.assertEqual("ontology_id", source.expand_metadata)
        self.assertEqual(77, source.page_size)


if __name__ == "__main__":
    unittest.main()

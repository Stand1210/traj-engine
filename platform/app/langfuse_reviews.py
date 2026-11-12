import base64
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Protocol

from platform.app.langfuse_source import LangfuseHttpError


VERDICT_SCORE_NAME = "traj-engine-human-verdict"
LABEL_SCORE_NAME = "traj-engine-human-label"
COMMENT_SCORE_NAME = "traj-engine-human-comment"
DEFAULT_QUEUE_NAME = "traj-engine-review"


class JsonTransport(Protocol):
    def __call__(self, method: str, url: str, params: dict | None, body: dict | None, headers: dict) -> dict:
        ...


class UrllibJsonTransport:
    def __call__(self, method: str, url: str, params: dict | None, body: dict | None, headers: dict) -> dict:
        query = urllib.parse.urlencode(params or {}, doseq=True)
        target = f"{url}?{query}" if query else url
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(target, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                text = response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            raise LangfuseHttpError(error.code, error.read().decode("utf-8", errors="replace")) from error
        if not text:
            return {}
        try:
            return json.loads(text)
        except json.JSONDecodeError as error:
            raise ValueError("Langfuse annotation API returned non-JSON response") from error


class LangfuseAnnotationQueueClient:
    @classmethod
    def from_config(cls, profile: dict, endpoints: dict, keys: dict, **kwargs):
        return cls(
            base_url=profile["baseUrl"],
            public_key=keys["publicKey"],
            secret_key=keys["secretKey"],
            endpoints=endpoints["endpoints"],
            **kwargs,
        )

    def __init__(
        self,
        base_url: str,
        public_key: str,
        secret_key: str,
        endpoints: dict,
        transport: JsonTransport | None = None,
        page_size: int = 100,
    ):
        self.base_url = base_url.rstrip("/")
        self.public_key = public_key
        self.secret_key = secret_key
        self.endpoints = endpoints
        self.transport = transport or UrllibJsonTransport()
        self.page_size = min(100, max(1, int(page_size)))

    def ensure_review_assets(self, queue_name: str = DEFAULT_QUEUE_NAME) -> dict:
        configs = self._ensure_score_configs()
        queue = self._find_or_create_queue(queue_name, [item["id"] for item in configs])
        return {"queue": queue, "scoreConfigs": configs}

    def push_items(self, queue_id: str, trace_ids: list[str]) -> list[dict]:
        items = []
        for trace_id in trace_ids:
            endpoint = self.endpoints["annotationQueues"]["items"]["create"]
            response = self._request("POST", endpoint["path"].format(queueId=queue_id), body={
                "objectId": trace_id,
                "objectType": "TRACE",
            })
            items.append(self._normalize_queue_item(response))
        return items

    def list_items(self, queue_id: str, status: str | None = None) -> list[dict]:
        endpoint = self.endpoints["annotationQueues"]["items"]["list"]
        items = []
        page = 1
        while True:
            params = {"page": page, "limit": self.page_size}
            if status:
                params["status"] = status
            response = self._request("GET", endpoint["path"].format(queueId=queue_id), params=params)
            page_items = self._response_data(response)
            items.extend(self._normalize_queue_item(item) for item in page_items)
            meta = response.get("meta", {})
            if not page_items or page >= int(meta.get("totalPages", page) or page):
                break
            page += 1
        return items

    def list_annotation_scores(self, trace_ids: list[str], queue_id: str | None = None) -> list[dict]:
        if not trace_ids:
            return []
        endpoint = self.endpoints["scores"]["list"]
        fields = endpoint.get("query", {}).get("fields", "details,subject,annotation")
        scores = []
        cursor = None
        while True:
            params = {
                "limit": self.page_size,
                "fields": fields,
                "source": "ANNOTATION",
                "traceId": ",".join(trace_ids),
            }
            if queue_id:
                params["queueId"] = queue_id
            if cursor:
                params["cursor"] = cursor
            response = self._request("GET", endpoint["path"], params=params)
            page_scores = self._response_data(response)
            scores.extend(self._normalize_score(item) for item in page_scores)
            cursor = response.get("meta", {}).get("nextPageCursor")
            if not cursor:
                break
        return scores

    def _ensure_score_configs(self) -> list[dict]:
        definitions = [
            {
                "name": VERDICT_SCORE_NAME,
                "dataType": "CATEGORICAL",
                "categories": [
                    {"label": "Agree", "value": 1},
                    {"label": "Disagree", "value": 2},
                    {"label": "Uncertain", "value": 3},
                ],
                "description": "Human verification of traj-engine alert or abstain decision.",
            },
            {
                "name": LABEL_SCORE_NAME,
                "dataType": "TEXT",
                "description": "Optional human label for the reviewed trajectory.",
            },
            {
                "name": COMMENT_SCORE_NAME,
                "dataType": "TEXT",
                "description": "Optional human review comment.",
            },
        ]
        existing = {item["name"]: item for item in self._list_score_configs()}
        result = []
        for definition in definitions:
            if definition["name"] in existing:
                result.append(existing[definition["name"]])
                continue
            endpoint = self.endpoints["scoreConfigs"]["create"]
            response = self._request("POST", endpoint["path"], body=definition)
            result.append(self._normalize_score_config(response))
        return result

    def _list_score_configs(self) -> list[dict]:
        endpoint = self.endpoints["scoreConfigs"]["list"]
        configs = []
        page = 1
        while True:
            response = self._request("GET", endpoint["path"], params={"page": page, "limit": self.page_size})
            page_configs = self._response_data(response)
            configs.extend(self._normalize_score_config(item) for item in page_configs)
            meta = response.get("meta", {})
            if not page_configs or page >= int(meta.get("totalPages", page) or page):
                break
            page += 1
        return configs

    def _find_or_create_queue(self, queue_name: str, score_config_ids: list[str]) -> dict:
        endpoint = self.endpoints["annotationQueues"]["list"]
        queues = []
        page = 1
        while True:
            response = self._request("GET", endpoint["path"], params={"page": page, "limit": self.page_size})
            page_queues = self._response_data(response)
            queues.extend(page_queues)
            meta = response.get("meta", {})
            if not page_queues or page >= int(meta.get("totalPages", page) or page):
                break
            page += 1
        for queue in queues:
            if queue.get("name") == queue_name:
                return self._normalize_queue(queue)
        endpoint = self.endpoints["annotationQueues"]["create"]
        response = self._request("POST", endpoint["path"], body={
            "name": queue_name,
            "description": "Traj-engine low-confidence and alert review queue.",
            "scoreConfigIds": score_config_ids,
        })
        return self._normalize_queue(response)

    def _request(self, method: str, path: str, params: dict | None = None, body: dict | None = None) -> dict:
        normalized_path = path if path.startswith("/") else f"/{path}"
        return self.transport(method, f"{self.base_url}{normalized_path}", params, body, self._headers())

    def _headers(self) -> dict:
        token = base64.b64encode(
            f"{self.public_key}:{self.secret_key}".encode("utf-8")
        ).decode("ascii")
        return {
            "Authorization": f"Basic {token}",
            "Accept": "application/json",
            "User-Agent": "traj-engine/0.1",
            **({"Content-Type": "application/json"} if True else {}),
        }

    @staticmethod
    def _response_data(response: dict) -> list[dict]:
        data = response.get("data", [])
        return data if isinstance(data, list) else []

    @staticmethod
    def _normalize_queue(queue: dict) -> dict:
        return {key: queue.get(key) for key in ("id", "name", "description", "scoreConfigIds", "createdAt", "updatedAt")}

    @staticmethod
    def _normalize_queue_item(item: dict) -> dict:
        return {key: item.get(key) for key in ("id", "queueId", "objectId", "objectType", "status", "completedAt", "createdAt", "updatedAt")}

    @staticmethod
    def _normalize_score_config(config: dict) -> dict:
        return {key: config.get(key) for key in ("id", "name", "dataType", "createdAt", "updatedAt")}

    @staticmethod
    def _normalize_score(score: dict) -> dict:
        subject = score.get("subject") or {}
        return {
            "id": score.get("id"),
            "name": score.get("name"),
            "value": score.get("value"),
            "dataType": score.get("dataType"),
            "source": score.get("source"),
            "traceId": subject.get("id") or score.get("traceId"),
            "authorUserId": score.get("authorUserId"),
            "queueId": score.get("queueId"),
            "comment": score.get("comment"),
            "updatedAt": score.get("updatedAt") or score.get("createdAt"),
        }

import base64
import json
import time
import urllib.error
import urllib.parse
import urllib.request


class LangfuseAdminError(RuntimeError):
    pass


class AdminTransport:
    def __init__(self, request_timeout: float = 30.0):
        self.request_timeout = request_timeout

    def __call__(self, url: str, params: dict, headers: dict) -> dict:
        query = urllib.parse.urlencode(params)
        request = urllib.request.Request(f"{url}?{query}", headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=self.request_timeout) as response:
                text = response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            raise LangfuseAdminError(
                f"Langfuse API returned HTTP {error.code}: {error.read().decode('utf-8', errors='replace')[:500]}"
            ) from error
        except (urllib.error.URLError, OSError) as error:
            raise LangfuseAdminError(f"Langfuse API request failed: {error}") from error
        if not text:
            return {}
        try:
            return json.loads(text)
        except json.JSONDecodeError as error:
            raise LangfuseAdminError("Langfuse API returned non-JSON response") from error


class LangfuseAdminClient:
    @classmethod
    def from_config(cls, profile: dict, endpoints: dict, keys: dict, **kwargs):
        health_endpoint = endpoints["endpoints"]["health"]
        projects_endpoint = endpoints["endpoints"]["projects"]["list"]
        return cls(
            base_url=profile["baseUrl"],
            public_key=keys["publicKey"],
            secret_key=keys["secretKey"],
            health_path=health_endpoint["path"],
            projects_path=projects_endpoint["path"],
            **kwargs,
        )

    def __init__(
        self,
        base_url: str,
        public_key: str,
        secret_key: str,
        health_path: str = "/api/public/health",
        projects_path: str = "/api/public/projects",
        transport: AdminTransport | None = None,
        max_retries: int = 2,
        request_timeout: float = 30.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.public_key = public_key
        self.secret_key = secret_key
        self.health_path = health_path
        self.projects_path = projects_path
        self.transport = transport or AdminTransport(request_timeout=request_timeout)
        self.request_timeout = request_timeout
        self.max_retries = max_retries
        credentials = f"{public_key}:{secret_key}".encode("utf-8")
        self.headers = {
            "Authorization": "Basic " + base64.b64encode(credentials).decode("ascii")
        }

    def check_health(self) -> dict:
        return self._request(self.health_path, {})

    def list_projects(self) -> list[dict]:
        response = self._request(self.projects_path, {"limit": 100})
        data = response.get("data")
        if not isinstance(data, list):
            raise LangfuseAdminError("Langfuse projects response has no data list")
        return [item for item in data if isinstance(item, dict)]

    def check_project(self, project_id: str) -> dict:
        health = self.check_health()
        if health.get("status") != "OK":
            raise LangfuseAdminError("Langfuse health endpoint is not OK")
        projects = self.list_projects()
        project = next(
            (item for item in projects if str(item.get("id")) == str(project_id)),
            None,
        )
        if project is None:
            raise LangfuseAdminError(
                "Langfuse key is valid, but the submitted projectId is not visible to this key"
            )
        return {
            "status": "OK",
            "langfuseVersion": health.get("version"),
            "project": {
                "id": project.get("id"),
                "name": project.get("name"),
            },
        }

    def _request(self, path: str, params: dict) -> dict:
        url = f"{self.base_url}{path if path.startswith('/') else '/' + path}"
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                return self.transport(url, params, self.headers)
            except LangfuseAdminError as error:
                last_error = error
                if "HTTP 4" in str(error) or attempt == self.max_retries:
                    raise
                time.sleep(0.2 * (attempt + 1))
        raise last_error or LangfuseAdminError("Langfuse API request failed")

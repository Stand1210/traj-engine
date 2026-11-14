import threading
import uuid
from contextlib import closing
from pathlib import Path
from typing import Callable

from platform.app import store


Evaluator = Callable[[object, str], dict]


class LifecycleScheduler:
    def __init__(
        self,
        db_path: str | Path = store.DEFAULT_DB_PATH,
        config: dict | None = None,
        evaluator: Evaluator | None = None,
        owner_id: str | None = None,
    ):
        self.db_path = Path(db_path)
        self.config = config or {
            "intervalSeconds": 60,
            "leaseSeconds": 120,
            "watchdog": {
                "queuedTimeoutSeconds": 900,
                "runningTimeoutSeconds": 86400,
            },
        }
        self.evaluator = evaluator
        self.owner_id = owner_id or f"scheduler-{uuid.uuid4().hex[:16]}"
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        if self.thread is not None and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(
            target=self._run_forever,
            name="traj-lifecycle-scheduler",
            daemon=True,
        )
        self.thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self.stop_event.set()
        if self.thread is not None and self.thread.is_alive():
            self.thread.join(timeout=timeout)
        self.thread = None

    def _run_forever(self) -> None:
        while not self.stop_event.wait(float(self.config["intervalSeconds"])):
            self.execute_scan()

    def execute_scan(self) -> dict:
        with closing(store.connect(self.db_path, initialize=True)) as connection:
            lock = store.acquire_scheduler_lock(
                connection, self.owner_id, int(self.config["leaseSeconds"])
            )
            if lock is not None and lock["owner_id"] != self.owner_id:
                return {
                    "status": "skipped",
                    "reason": "lock_held",
                    "lock": lock,
                }

            scan_id = store.record_scheduler_scan(connection)
            watchdog_failed_runs: list[str] = []
            evaluations: list[dict] = []
            created_run_count = 0
            error = None
            try:
                watchdog_config = self.config["watchdog"]
                watchdog_failed_runs = store.fail_timed_out_runs(
                    connection,
                    int(watchdog_config["queuedTimeoutSeconds"]),
                    int(watchdog_config["runningTimeoutSeconds"]),
                )
                schedules = connection.execute(
                    """SELECT ontology_id FROM lifecycle_schedules
                       WHERE enabled = 1 ORDER BY ontology_id"""
                ).fetchall()
                for schedule in schedules:
                    if self.evaluator is None:
                        continue
                    store.heartbeat_scheduler_lock(
                        connection, self.owner_id, int(self.config["leaseSeconds"])
                    )
                    evaluation = self.evaluator(connection, schedule["ontology_id"])
                    evaluations.append({
                        "ontologyId": evaluation["ontologyId"],
                        "decision": evaluation["decision"],
                        "reason": evaluation["reason"],
                        "runId": evaluation["createdRunId"],
                    })
                    if evaluation.get("run") is not None:
                        created_run_count += 1
                result = {
                    "watchdogFailedRuns": watchdog_failed_runs,
                    "evaluations": evaluations,
                }
                store.finish_scheduler_scan(
                    connection, scan_id, "succeeded", len(watchdog_failed_runs),
                    len(evaluations), created_run_count, result,
                )
                return {"status": "succeeded", "scanId": scan_id, **result}
            except Exception as scan_error:
                error = str(scan_error)
                result = {
                    "watchdogFailedRuns": watchdog_failed_runs,
                    "evaluations": evaluations,
                }
                store.finish_scheduler_scan(
                    connection, scan_id, "failed", len(watchdog_failed_runs),
                    len(evaluations), created_run_count, result, error,
                )
                return {
                    "status": "failed",
                    "scanId": scan_id,
                    "error": error,
                    **result,
                }
            finally:
                store.release_scheduler_lock(connection, self.owner_id)


def scheduler_status(db_path: str | Path = store.DEFAULT_DB_PATH) -> dict:
    with closing(store.connect(db_path, initialize=False)) as connection:
        lock = store.get_scheduler_lock(connection)
        scan = connection.execute(
            "SELECT * FROM scheduler_scans ORDER BY started_at DESC, id LIMIT 1"
        ).fetchone()
        schedule_count = connection.execute(
            "SELECT COUNT(*) AS n FROM lifecycle_schedules WHERE enabled = 1"
        ).fetchone()["n"]
    import json
    return {
        "lock": lock,
        "enabledSchedules": int(schedule_count),
        "latestScan": {
            "id": scan["id"],
            "status": scan["status"],
            "startedAt": scan["started_at"],
            "finishedAt": scan["finished_at"],
            "watchdogFailedRuns": int(scan["watchdog_failed_runs"]),
            "evaluationCount": int(scan["evaluation_count"]),
            "createdRunCount": int(scan["created_run_count"]),
            "result": json.loads(scan["result_json"] or "{}"),
            "error": scan["error"],
        } if scan is not None else None,
    }

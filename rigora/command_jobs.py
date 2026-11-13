"""Long-running commands as jobs with ids, progress, cancel and results (R6.3).

Each job runs one registered command in a child ``python -m rigora.cli``
process, so a render gets its own main thread for OpenGL and a crash cannot
take the MCP server down. Progress comes from the child's ``progress N/T``
lines; cancelling creates the job's cancel file, which the command checks
between frames and answers by discarding its partial output. A ``request_id``
makes starting idempotent: repeating it returns the existing job instead of
running the command (and its writes) again.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from rigora.command_registry import COMMANDS

RUNNING, DONE, FAILED, CANCELLED = "running", "done", "failed", "cancelled"
_PROGRESS = re.compile(r"progress (\d+)/(\d+)")


def cli_arguments(name: str, arguments: dict) -> list[str]:
    """Command-line arguments equivalent to an MCP ``arguments`` object."""
    schema = COMMANDS[name]["input_schema"]["properties"]
    argv = [name.replace("_", "-")]
    for key, value in arguments.items():
        kind = schema[key].get("type")
        if key in ("path", "source"):
            argv.append(str(value))
        elif kind == "boolean":
            argv.append(("--" if value else "--no-") + key.replace("_", "-"))
        elif kind in ("array", "object"):
            argv += ["--" + key.replace("_", "-"), json.dumps(value)]
        else:
            argv += ["--" + key.replace("_", "-"), str(value)]
    return argv


@dataclass
class Job:
    id: str
    command: str
    request_id: str | None
    state: str = RUNNING
    progress: int = 0
    total: int = 0
    result: dict | None = None
    error: dict | None = None
    started: float = field(default_factory=time.monotonic)
    cancel_file: Path | None = None

    def status(self) -> dict:
        out = {"job_id": self.id, "command": self.command, "state": self.state,
               "progress": self.progress, "total": self.total,
               "elapsed_seconds": round(time.monotonic() - self.started, 2)}
        if self.error:
            out["error"] = self.error
        return out


class JobManager:
    def __init__(self) -> None:
        self.jobs: dict[str, Job] = {}
        self._by_request: dict[str, str] = {}
        self._lock = threading.Lock()
        self._folder = Path(tempfile.mkdtemp(prefix="rigora-jobs-"))

    def start(self, command: str, arguments: dict, request_id: str | None = None) -> dict:
        if command not in COMMANDS:
            raise ValueError(f"unknown command {command!r}")
        with self._lock:
            if request_id and request_id in self._by_request:
                return self.jobs[self._by_request[request_id]].status()
            job = Job(uuid4().hex[:12], command, request_id)
            self.jobs[job.id] = job
            if request_id:
                self._by_request[request_id] = job.id
        argv = [sys.executable, "-m", "rigora.cli", *cli_arguments(command, arguments),
                "--json"]
        if COMMANDS[command].get("long_running"):
            job.cancel_file = self._folder / f"{job.id}.cancel"
            argv += ["--progress", "--cancel-file", str(job.cancel_file)]
        process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, encoding="utf-8")
        threading.Thread(target=self._watch, args=(job, process), daemon=True).start()
        return job.status()

    def _watch(self, job: Job, process: subprocess.Popen) -> None:
        def read_progress() -> None:
            for line in process.stderr:
                match = _PROGRESS.search(line)
                if match:
                    job.progress, job.total = int(match[1]), int(match[2])

        reader = threading.Thread(target=read_progress, daemon=True)
        reader.start()
        output = process.stdout.read()
        process.wait()
        reader.join(timeout=5)
        try:
            payload = json.loads(output) if output.strip() else {}
        except json.JSONDecodeError:
            payload = {"error": {"code": "failed", "message": output.strip()[-500:]}}
        if isinstance(payload, list) and payload:
            payload = payload[0]
        if process.returncode == 0:
            job.result, job.state = payload, DONE
        else:
            job.error = payload.get("error") if isinstance(payload, dict) else None
            job.error = job.error or {"code": "failed", "message": f"exit {process.returncode}"}
            job.state = CANCELLED if job.error.get("code") == "cancelled" else FAILED

    def status(self, job_id: str) -> dict:
        return self._job(job_id).status()

    def cancel(self, job_id: str) -> dict:
        job = self._job(job_id)
        if job.state == RUNNING:
            if job.cancel_file is None:
                raise ValueError("this command finishes too quickly to cancel")
            job.cancel_file.write_text("cancel", encoding="utf-8")
        return job.status()

    def result(self, job_id: str) -> dict:
        job = self._job(job_id)
        if job.state == RUNNING:
            return {**job.status(), "result": None}
        return {**job.status(), "result": job.result}

    def wait(self, job_id: str, timeout: float = 600.0) -> dict:
        deadline = time.monotonic() + timeout
        while self._job(job_id).state == RUNNING and time.monotonic() < deadline:
            time.sleep(0.05)
        return self.result(job_id)

    def _job(self, job_id: str) -> Job:
        if job_id not in self.jobs:
            raise ValueError(f"no job {job_id!r}")
        return self.jobs[job_id]

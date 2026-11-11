"""Windows GUI entry point with a bounded bundle verification mode."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import traceback


def main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] in {"--smoke-test", "--native-smoke-test"}:
        report = Path(sys.argv[2]).resolve()
        try:
            from rigora.bundle_smoke import run

            return run(report, native=sys.argv[1] == "--native-smoke-test")
        except Exception:  # noqa: BLE001 - preserve import failures without a GUI error dialog
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text(json.dumps({
                "status": "failed", "traceback": traceback.format_exc(),
            }, indent=2), encoding="utf-8")
            return 1

    log_dir = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Rigora"
    log_dir.mkdir(parents=True, exist_ok=True)
    with (log_dir / "startup.log").open("a", encoding="utf-8") as log:
        if sys.stdout is None:
            sys.stdout = log
        if sys.stderr is None:
            sys.stderr = log
        try:
            from rigora.app import main as start_editor

            return start_editor()
        except Exception:  # noqa: BLE001 - GUI process boundary retains startup failures
            traceback.print_exc(file=log)
            return 1


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FREEZE_FILE = ROOT / "benchmark" / "challenge_freeze.json"
PROTECTED_PATHS = (
    "benchmark/oracle_policy.yaml",
    "configs/policy.yaml",
    "src/smd_bench/oracle.py",
    "src/smd_gateway/audit.py",
    "src/smd_gateway/delegation.py",
    "src/smd_gateway/evidence.py",
    "src/smd_gateway/leakage.py",
    "src/smd_gateway/main.py",
    "src/smd_gateway/normalizer.py",
    "src/smd_gateway/policy.py",
    "src/smd_gateway/policy_config.py",
    "src/smd_gateway/request_model.py",
    "src/smd_gateway/router.py",
    "src/smd_gateway/sanitizer.py",
)


def main() -> None:
    freeze = json.loads(FREEZE_FILE.read_text(encoding="utf-8"))
    freeze_sha = str(freeze["controller_freeze_commit"])
    _git("cat-file", "-e", f"{freeze_sha}^{{commit}}")
    changed = _git("diff", "--name-only", freeze_sha, "--", *PROTECTED_PATHS).splitlines()
    if changed:
        joined = "\n- ".join(changed)
        raise SystemExit(
            "Challenge validity failed: protected controller or label-policy files "
            f"changed after {freeze_sha}:\n- {joined}"
        )
    print(f"Controller freeze verified at {freeze_sha}; protected files are unchanged.")


def _git(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


if __name__ == "__main__":
    main()

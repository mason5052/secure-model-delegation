from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import uvicorn


def main() -> None:
    uvicorn.run(
        "smd_gateway.web_app:app",
        host="127.0.0.1",
        port=6727,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()

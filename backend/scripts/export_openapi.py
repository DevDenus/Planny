"""Writes backend/openapi.json from the code. With --check, fails if the snapshot is stale."""

import json
import os
import sys
from pathlib import Path

SNAPSHOT = Path(__file__).resolve().parent.parent / "openapi.json"


def render() -> str:
    # Building the schema needs no connection, these only satisfy the settings.
    os.environ.setdefault("PLANNY_DATABASE_URL", "postgresql+asyncpg://unused@localhost/unused")
    os.environ.setdefault("PLANNY_BFF_SHARED_SECRET", "x" * 32)
    from app.main import create_app  # needs the environment set above

    return json.dumps(create_app().openapi(), ensure_ascii=False, indent=2) + "\n"


def main() -> int:
    current = render()
    if "--check" not in sys.argv:
        SNAPSHOT.write_text(current, encoding="utf-8")
        return 0
    if not SNAPSHOT.exists() or SNAPSHOT.read_text(encoding="utf-8") != current:
        print("backend/openapi.json is stale, run `make openapi`", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Create and integrity-check a local operational evidence backup."""

import json
from datetime import UTC, datetime
from pathlib import Path

from app.config import settings
from app.evidence import backup_and_verify


if __name__ == "__main__":
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    target = Path(".data/backups") / f"bitagent-{stamp}.db"
    result = backup_and_verify(settings.evidence_db_path, str(target))
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["restorable"] else 1)

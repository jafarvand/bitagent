"""Validate owner-provided 1.0 evidence without printing sensitive content."""

import json

from app.config import settings
from app.release_inputs import validate_release_inputs


if __name__ == "__main__":
    result = validate_release_inputs(
        settings.release_evidence_directory,
        warning_threshold=settings.withdrawal_pending_warning_threshold,
        critical_threshold=settings.withdrawal_pending_critical_threshold,
    )
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["all_passed"] else 1)

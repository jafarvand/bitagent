import hashlib
import json


def build_release_candidate_manifest(
    readiness: dict,
    *,
    current_version: str,
    candidate_version: str = "1.0.0",
) -> dict:
    gates = readiness.get("gates", [])
    normalized_gates = [
        {
            "id": str(gate.get("id", "unknown")),
            "status": str(gate.get("status", "pending")),
            "evidence": str(gate.get("evidence", "")),
        }
        for gate in gates
    ]
    blockers = [
        {"id": gate["id"], "status": gate["status"], "evidence": gate["evidence"]}
        for gate in normalized_gates
        if gate["status"] != "pass"
    ]
    approved = bool(normalized_gates) and not blockers
    receipt_payload = {
        "candidate_version": candidate_version,
        "current_version": current_version,
        "gates": normalized_gates,
    }
    receipt = hashlib.sha256(
        json.dumps(
            receipt_payload, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()

    return {
        "candidate_version": candidate_version,
        "current_version": current_version,
        "decision": "approved_for_controlled_pilot" if approved else "blocked",
        "approved": approved,
        "passed": sum(gate["status"] == "pass" for gate in normalized_gates),
        "total": len(normalized_gates),
        "blockers": blockers,
        "gates": normalized_gates,
        "evidence_sha256": receipt,
        "action_executed": False,
    }

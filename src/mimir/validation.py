from __future__ import annotations

from typing import Any

from mimir.errors import RetryableError

CLAIM_TYPES = {
    "FACTUAL",
    "PREDICTION",
    "OPINION",
    "MARKETING",
    "CAUSAL",
    "QUANTITATIVE",
    "IMPLEMENTATION",
    "ASSUMPTION",
}
MATERIALITY = {"HIGH", "MEDIUM", "LOW"}
INTEGRITY = {"CREDIBLE", "MIXED", "MISLEADING", "INSUFFICIENT"}
ACTIONS = {"DEEP_RESEARCH", "CHEAP_EXPERIMENT", "SAVE_FOR_LATER", "SKIP", "NO_DECISION"}
VERDICTS = {
    "SUPPORTED",
    "PARTIALLY_SUPPORTED",
    "CONTRADICTED",
    "UNVERIFIED",
    "MISLEADING",
    "OUTDATED",
    "NOT_FACT_CHECKABLE",
}


def normalize_claims(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw = payload.get("claims")
    if not isinstance(raw, list):
        raise RetryableError("CLAIMS_SCHEMA_INVALID")
    claims: list[dict[str, Any]] = []
    for index, item in enumerate(raw[:12], start=1):
        if not isinstance(item, dict):
            raise RetryableError("CLAIMS_SCHEMA_INVALID")
        claim_type = item.get("claim_type")
        materiality = item.get("materiality")
        text = str(item.get("text") or "").strip()
        if claim_type not in CLAIM_TYPES or materiality not in MATERIALITY or not text:
            raise RetryableError("CLAIMS_SCHEMA_INVALID")
        claims.append(
            {
                "claim_id": f"c{index}",
                "text": text[:1200],
                "claim_type": claim_type,
                "source_excerpt": str(item.get("source_excerpt") or "")[:500],
                "materiality": materiality,
                "externally_verifiable": bool(item.get("externally_verifiable")),
            }
        )
    return claims


def validate_evaluation(payload: dict[str, Any], claim_ids: set[str]) -> dict[str, Any]:
    if payload.get("integrity_disposition") not in INTEGRITY:
        raise RetryableError("EVALUATION_SCHEMA_INVALID")
    if payload.get("recommended_action") not in ACTIONS:
        raise RetryableError("EVALUATION_SCHEMA_INVALID")
    reasons = payload.get("reasons")
    verdicts = payload.get("claim_verdicts")
    if (
        not isinstance(reasons, list)
        or not 2 <= len(reasons) <= 3
        or not isinstance(verdicts, list)
    ):
        raise RetryableError("EVALUATION_SCHEMA_INVALID")
    normalized_verdicts = []
    seen: set[str] = set()
    for verdict in verdicts:
        if not isinstance(verdict, dict):
            raise RetryableError("EVALUATION_SCHEMA_INVALID")
        claim_id = verdict.get("claim_id")
        if claim_id not in claim_ids or verdict.get("verdict") not in VERDICTS:
            raise RetryableError("EVALUATION_SCHEMA_INVALID")
        seen.add(claim_id)
        normalized_verdicts.append(verdict)
    if seen != claim_ids:
        raise RetryableError("EVALUATION_MISSING_CLAIMS")
    result = dict(payload)
    result["claim_verdicts"] = normalized_verdicts
    return result

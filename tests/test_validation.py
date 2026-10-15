import pytest

from mimir.errors import RetryableError
from mimir.validation import normalize_claims, validate_evaluation


def test_normalize_claims_assigns_canonical_ids():
    claims = normalize_claims(
        {
            "claims": [
                {
                    "claim_id": "invented",
                    "text": "Performance improved by 10x.",
                    "claim_type": "QUANTITATIVE",
                    "source_excerpt": "10x faster",
                    "materiality": "HIGH",
                    "externally_verifiable": True,
                }
            ]
        }
    )

    assert claims[0]["claim_id"] == "c1"


def test_evaluation_must_cover_every_claim():
    payload = {
        "integrity_disposition": "INSUFFICIENT",
        "recommended_action": "NO_DECISION",
        "reasons": ["one", "two"],
        "claim_verdicts": [],
    }

    with pytest.raises(RetryableError) as captured:
        validate_evaluation(payload, {"c1"})
    assert captured.value.code == "EVALUATION_MISSING_CLAIMS"

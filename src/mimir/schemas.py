CLAIMS_SCHEMA = {
    "type": "object",
    "properties": {
        "detected_language": {"type": "string"},
        "claims": {
            "type": "array",
            "maxItems": 12,
            "items": {
                "type": "object",
                "properties": {
                    "claim_id": {"type": "string"},
                    "text": {"type": "string"},
                    "claim_type": {
                        "type": "string",
                        "enum": [
                            "FACTUAL",
                            "PREDICTION",
                            "OPINION",
                            "MARKETING",
                            "CAUSAL",
                            "QUANTITATIVE",
                            "IMPLEMENTATION",
                            "ASSUMPTION",
                        ],
                    },
                    "source_excerpt": {"type": "string"},
                    "materiality": {"type": "string", "enum": ["HIGH", "MEDIUM", "LOW"]},
                    "externally_verifiable": {"type": "boolean"},
                },
                "required": [
                    "claim_id",
                    "text",
                    "claim_type",
                    "source_excerpt",
                    "materiality",
                    "externally_verifiable",
                ],
                "additionalProperties": False,
            },
        },
    },
    "required": ["detected_language", "claims"],
    "additionalProperties": False,
}

IMAGE_EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "detected_language": {"type": "string"},
        "visible_text": {"type": "string"},
        "visual_description": {"type": "string"},
        "quality": {"type": "string", "enum": ["SUFFICIENT", "INSUFFICIENT"]},
        "limitations": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
    },
    "required": [
        "detected_language",
        "visible_text",
        "visual_description",
        "quality",
        "limitations",
    ],
    "additionalProperties": False,
}

EVALUATION_SCHEMA = {
    "type": "object",
    "properties": {
        "claim_verdicts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "claim_id": {"type": "string"},
                    "verdict": {
                        "type": "string",
                        "enum": [
                            "SUPPORTED",
                            "PARTIALLY_SUPPORTED",
                            "CONTRADICTED",
                            "UNVERIFIED",
                            "MISLEADING",
                            "OUTDATED",
                            "NOT_FACT_CHECKABLE",
                        ],
                    },
                    "reason": {"type": "string"},
                    "limitations": {"type": "string"},
                    "evidence_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["claim_id", "verdict", "reason", "limitations", "evidence_ids"],
                "additionalProperties": False,
            },
        },
        "integrity_disposition": {
            "type": "string",
            "enum": ["CREDIBLE", "MIXED", "MISLEADING", "INSUFFICIENT"],
        },
        "recommended_action": {
            "type": "string",
            "enum": [
                "DEEP_RESEARCH",
                "CHEAP_EXPERIMENT",
                "SAVE_FOR_LATER",
                "SKIP",
                "NO_DECISION",
            ],
        },
        "decision_summary": {"type": "string"},
        "reasons": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 3},
        "credibility_summary": {"type": "string"},
        "practical_value": {"type": "string"},
        "minimum_cost_experiment": {"type": "string"},
        "value_evaluation": {
            "type": "object",
            "properties": {
                "problem_reality": {"type": "string"},
                "user_relevance": {"type": "string"},
                "novelty": {"type": "string"},
                "technical_feasibility": {"type": "string"},
                "dependency_risk": {"type": "string"},
                "time_to_learning": {"type": "string"},
                "time_to_validation": {"type": "string"},
                "opportunity_cost": {"type": "string"},
                "downside": {"type": "string"},
            },
            "required": [
                "problem_reality",
                "user_relevance",
                "novelty",
                "technical_feasibility",
                "dependency_risk",
                "time_to_learning",
                "time_to_validation",
                "opportunity_cost",
                "downside",
            ],
            "additionalProperties": False,
        },
    },
    "required": [
        "claim_verdicts",
        "integrity_disposition",
        "recommended_action",
        "decision_summary",
        "reasons",
        "credibility_summary",
        "practical_value",
        "minimum_cost_experiment",
        "value_evaluation",
    ],
    "additionalProperties": False,
}

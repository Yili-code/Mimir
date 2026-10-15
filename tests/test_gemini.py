from mimir.gemini import GeminiClient


def test_grounding_sources_are_mapped_to_the_requested_claim(monkeypatch):
    client = GeminiClient("secret", "model")
    response = {
        "candidates": [
            {
                "content": {"parts": [{"text": "The official documentation supports part."}]},
                "groundingMetadata": {
                    "groundingChunks": [
                        {
                            "web": {
                                "uri": "https://docs.example.com/fact",
                                "title": "Official documentation",
                            }
                        }
                    ]
                },
            }
        ]
    }
    monkeypatch.setattr(client, "_post", lambda payload: response)

    result = client.research_claim("c2", "A verifiable claim")

    assert result["claim_id"] == "c2"
    assert result["status"] == "FOUND"
    assert result["sources"][0]["supported_claim_id"] == "c2"
    assert result["sources"][0]["publisher"] == "docs.example.com"
    assert result["sources"][0]["retrieved_at"]


def test_grounded_text_without_linked_sources_does_not_count_as_evidence(monkeypatch):
    client = GeminiClient("secret", "model")
    monkeypatch.setattr(
        client,
        "_post",
        lambda payload: {"candidates": [{"content": {"parts": [{"text": "Plausible."}]}}]},
    )

    result = client.research_claim("c1", "A claim")

    assert result["status"] == "NO_LINKED_SOURCES"
    assert result["sources"] == []

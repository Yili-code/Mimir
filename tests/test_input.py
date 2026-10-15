from mimir.input import detect_language, normalize_update


def message(update_id: int, **values):
    payload = {
        "update_id": update_id,
        "message": {
            "date": 1_700_000_000,
            "from": {"id": 7},
            "chat": {"id": 7, "type": "private"},
        },
    }
    payload["message"].update(values)
    return payload


def test_normalizes_text_and_language():
    envelope = normalize_update(message(10, text="這是一個值得查證的說法"), 7)

    assert envelope is not None
    assert envelope.input_type == "text"
    assert envelope.detected_language == "zh-Hant"
    assert envelope.update_id == 10


def test_text_containing_public_url_becomes_url_input():
    envelope = normalize_update(message(11, text="請分析 https://example.com/post"), 7)

    assert envelope is not None
    assert envelope.input_type == "url"
    assert envelope.original_url == "https://example.com/post"


def test_uses_largest_telegram_photo_and_keeps_caption_separate():
    envelope = normalize_update(
        message(
            12,
            caption="这个产品提升效率十倍",
            photo=[
                {"file_id": "small", "file_unique_id": "a"},
                {"file_id": "large", "file_unique_id": "b"},
            ],
        ),
        7,
    )

    assert envelope is not None
    assert envelope.input_type == "image"
    assert envelope.telegram_file_id == "large"
    assert envelope.original_text == "这个产品提升效率十倍"
    assert envelope.detected_language == "zh-Hans"


def test_non_owner_and_group_messages_are_not_persisted():
    wrong_owner = message(13, text="private")
    wrong_owner["message"]["from"]["id"] = 8
    group = message(14, text="group")
    group["message"]["chat"]["type"] = "group"

    assert normalize_update(wrong_owner, 7) is None
    assert normalize_update(group, 7) is None


def test_detect_language_preserves_mixed_signal():
    assert detect_language("這個 API design 值得研究") == "mixed"

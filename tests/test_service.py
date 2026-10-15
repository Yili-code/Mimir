from __future__ import annotations

from copy import deepcopy

from mimir.config import Settings
from mimir.errors import RetryableError
from mimir.models import PollState
from mimir.service import MimirService
from mimir.url_fetcher import FetchedPage


class FakeRepository:
    def __init__(self, initialized=True):
        self.state = PollState(initialized=initialized, last_update_id=None)
        self.cases = {}
        self.events = []

    def get_poll_state(self):
        return self.state

    def save_poll_state(self, *, initialized, last_update_id):
        self.events.append(("cursor", last_update_id))
        self.state = PollState(initialized=initialized, last_update_id=last_update_id)

    def create_case(self, envelope):
        self.events.append(("case", envelope.update_id))
        key = str(envelope.update_id)
        if key in self.cases:
            return False
        self.cases[key] = {
            "case_id": key,
            "telegram_update_id": envelope.update_id,
            "input": envelope.to_dict(),
            "processing_status": "PENDING",
            "stage": "ACQUIRE",
            "failure_attempts": 0,
            "delivery_attempts": 0,
        }
        return True

    def list_processable_cases(self, limit):
        return [
            deepcopy(case)
            for case in self.cases.values()
            if case["processing_status"] in {"PENDING", "RESULT_READY", "RUNNING"}
        ][:limit]

    def claim_case(self, case_id, runner_id, lease_seconds):
        case = self.cases[case_id]
        if case["processing_status"] in {"DELIVERED", "FAILED_TERMINAL"}:
            return None
        if case["processing_status"] == "RUNNING" and not case.get("lease_expired"):
            return None
        case["processing_status"] = "RUNNING"
        return deepcopy(case)

    def update_case(self, case_id, fields):
        self.cases[case_id].update(deepcopy(fields))

    def mark_retryable(self, case_id, *, error_code, max_attempts):
        case = self.cases[case_id]
        field = "delivery_attempts" if case["stage"] == "DELIVER" else "failure_attempts"
        case[field] += 1
        terminal = case[field] >= max_attempts
        case["last_error_code"] = error_code
        case["processing_status"] = (
            "FAILED_TERMINAL"
            if terminal
            else ("RESULT_READY" if field == "delivery_attempts" else "PENDING")
        )
        return terminal

    def mark_terminal(self, case_id, *, error_code):
        self.cases[case_id].update(
            {"processing_status": "FAILED_TERMINAL", "last_error_code": error_code}
        )

    def mark_delivered(self, case_id, *, telegram_message_id):
        self.cases[case_id].update(
            {
                "processing_status": "DELIVERED",
                "delivery_status": "DELIVERED",
                "telegram_message_id": telegram_message_id,
            }
        )


class FakeTelegram:
    def __init__(self, updates=None):
        self.updates = updates or []
        self.sent = []
        self.fail_sends = 0
        self.downloads = 0

    def get_webhook_url(self):
        return ""

    def get_updates(self, *, offset, limit=100):
        if offset == -1:
            return self.updates[-1:]
        if offset is None:
            return list(self.updates)
        return [item for item in self.updates if item["update_id"] >= offset]

    def download_file(self, file_id, *, max_bytes):
        self.downloads += 1
        return b"fake-image", "image/jpeg"

    def send_message(self, chat_id, text):
        if self.fail_sends:
            self.fail_sends -= 1
            raise RetryableError("TELEGRAM_NETWORK")
        self.sent.append((chat_id, text))
        return 900 + len(self.sent)


class FakeGemini:
    def __init__(self):
        self.claim_calls = 0
        self.research_calls = []
        self.evaluation_calls = 0
        self.image_calls = 0

    def extract_image(self, image, mime_type, caption):
        self.image_calls += 1
        return {
            "quality": "SUFFICIENT",
            "visible_text": "效率提升十倍",
            "visual_description": "A benchmark chart",
            "limitations": [],
        }

    def extract_claims(self, content):
        self.claim_calls += 1
        return {
            "detected_language": "zh-Hant",
            "claims": [
                {
                    "claim_id": "whatever",
                    "text": "效率提升十倍",
                    "claim_type": "QUANTITATIVE",
                    "source_excerpt": "十倍",
                    "materiality": "HIGH",
                    "externally_verifiable": True,
                }
            ],
        }

    def research_claim(self, claim_id, claim_text):
        self.research_calls.append(claim_id)
        return {
            "claim_id": claim_id,
            "research_summary": "No independent benchmark was found.",
            "sources": [],
            "status": "NO_LINKED_SOURCES",
        }

    def evaluate(self, **kwargs):
        self.evaluation_calls += 1
        return {
            "claim_verdicts": [
                {
                    "claim_id": "c1",
                    "verdict": "UNVERIFIED",
                    "reason": "No linked source.",
                    "limitations": "Search may be incomplete.",
                    "evidence_ids": [],
                }
            ],
            "integrity_disposition": "MIXED",
            "recommended_action": "CHEAP_EXPERIMENT",
            "decision_summary": "值得小型驗證。",
            "reasons": ["有具體問題。", "證據仍不足。"],
            "credibility_summary": "核心數字未驗證。",
            "practical_value": "能學會如何設計 benchmark。",
            "minimum_cost_experiment": "用一小時建立對照測試。",
            "value_evaluation": {
                "problem_reality": "可能存在",
                "user_relevance": "相關",
                "novelty": "未知",
                "technical_feasibility": "可驗證",
                "dependency_risk": "低",
                "time_to_learning": "一小時",
                "time_to_validation": "一小時",
                "opportunity_cost": "低",
                "downside": "浪費一小時",
            },
        }


class PartiallyFailingGemini(FakeGemini):
    def __init__(self):
        super().__init__()
        self.fail_c2_once = True

    def extract_claims(self, content):
        payload = super().extract_claims(content)
        payload["claims"].append(
            {
                "claim_id": "second",
                "text": "The implementation needs no maintenance.",
                "claim_type": "IMPLEMENTATION",
                "source_excerpt": "no maintenance",
                "materiality": "HIGH",
                "externally_verifiable": True,
            }
        )
        return payload

    def research_claim(self, claim_id, claim_text):
        self.research_calls.append(claim_id)
        if claim_id == "c2" and self.fail_c2_once:
            self.fail_c2_once = False
            raise RetryableError("GEMINI_NETWORK")
        return {
            "claim_id": claim_id,
            "research_summary": "No independent evidence was found.",
            "sources": [],
            "status": "NO_LINKED_SOURCES",
        }

    def evaluate(self, **kwargs):
        payload = super().evaluate(**kwargs)
        payload["claim_verdicts"].append(
            {
                "claim_id": "c2",
                "verdict": "UNVERIFIED",
                "reason": "No linked source.",
                "limitations": "Search may be incomplete.",
                "evidence_ids": [],
            }
        )
        return payload


class FakeFetcher:
    def fetch(self, url):
        return FetchedPage(url, url, url, "Title", "Author", "2026-10-15", "Body " * 30)


def update(update_id=1, **message_values):
    message = {
        "date": 1_700_000_000,
        "from": {"id": 7},
        "chat": {"id": 7, "type": "private"},
        "text": "這個產品宣稱效率提升十倍，值得研究嗎？",
    }
    message.update(message_values)
    return {"update_id": update_id, "message": message}


def settings():
    return Settings(
        telegram_bot_token="token",
        telegram_owner_user_id=7,
        gemini_api_key="key",
        google_cloud_project="project",
        owner_profile="Computer science student validating startup ideas.",
        max_failure_attempts=3,
    )


def service(repo, telegram, gemini=None):
    return MimirService(
        settings=settings(),
        repository=repo,
        telegram=telegram,
        gemini=gemini or FakeGemini(),
        url_fetcher=FakeFetcher(),
    )


def test_first_run_baselines_without_analyzing_old_updates():
    repo = FakeRepository(initialized=False)
    telegram = FakeTelegram([update(10)])
    gemini = FakeGemini()

    report = service(repo, telegram, gemini).run_once()

    assert report.baselined is True
    assert repo.state.last_update_id == 10
    assert repo.cases == {}
    assert gemini.claim_calls == 0


def test_receipt_is_saved_before_poll_cursor_advances_and_result_is_fail_closed():
    repo = FakeRepository()
    telegram = FakeTelegram([update(11)])
    gemini = FakeGemini()

    report = service(repo, telegram, gemini).run_once()

    assert repo.events[:2] == [("case", 11), ("cursor", 11)]
    assert report.delivered == 1
    assert repo.cases["11"]["processing_status"] == "DELIVERED"
    result = repo.cases["11"]["result"]
    assert result["integrity_disposition"] == "INSUFFICIENT"
    assert result["recommended_action"] == "NO_DECISION"
    assert gemini.claim_calls == 1
    assert gemini.research_calls == ["c1"]
    assert repo.cases["11"]["owner_profile_version"] == "owner-v1"


def test_delivery_retry_reuses_saved_result_without_regenerating():
    repo = FakeRepository()
    telegram = FakeTelegram([update(12)])
    telegram.fail_sends = 1
    gemini = FakeGemini()
    app = service(repo, telegram, gemini)

    first = app.run_once()
    assert first.retryable_failures == 1
    assert repo.cases["12"]["processing_status"] == "RESULT_READY"
    assert gemini.claim_calls == 1

    second = app.run_once()
    assert second.delivered == 1
    assert gemini.claim_calls == 1
    assert gemini.evaluation_calls == 1


def test_duplicate_update_does_not_create_or_generate_a_second_result():
    repo = FakeRepository()
    telegram = FakeTelegram([update(13)])
    gemini = FakeGemini()
    app = service(repo, telegram, gemini)

    app.run_once()
    # Simulate Telegram redelivering the same update after cursor loss.
    repo.state = PollState(initialized=True, last_update_id=None)
    app.run_once()

    assert list(repo.cases) == ["13"]
    assert gemini.claim_calls == 1
    assert len(telegram.sent) == 1


def test_image_uses_vision_then_the_same_claim_pipeline():
    repo = FakeRepository()
    telegram = FakeTelegram(
        [
            update(
                14,
                text=None,
                caption="這張圖宣稱效率提升十倍",
                photo=[{"file_id": "photo", "file_unique_id": "unique"}],
            )
        ]
    )
    gemini = FakeGemini()

    report = service(repo, telegram, gemini).run_once()

    assert report.delivered == 1
    assert telegram.downloads == 1
    assert gemini.image_calls == 1
    assert repo.cases["14"]["source_metadata"]["image_sha256"]


def test_unsupported_input_returns_insufficient_without_model_call():
    repo = FakeRepository()
    telegram = FakeTelegram([update(15, text=None, sticker={"file_id": "sticker"})])
    gemini = FakeGemini()

    report = service(repo, telegram, gemini).run_once()

    assert report.delivered == 1
    assert gemini.claim_calls == 0
    assert "目前只支援" in telegram.sent[0][1]


def test_expired_running_case_resumes_from_saved_stage():
    repo = FakeRepository()
    telegram = FakeTelegram([])
    gemini = FakeGemini()
    repo.cases["16"] = {
        "case_id": "16",
        "telegram_update_id": 16,
        "input": {
            "chat_id": 7,
            "input_type": "text",
            "original_text": "這個產品宣稱效率提升十倍，值得繼續研究嗎？",
        },
        "processing_status": "RUNNING",
        "stage": "CLAIMS",
        "extracted_content": "這個產品宣稱效率提升十倍，值得繼續研究嗎？",
        "failure_attempts": 0,
        "delivery_attempts": 0,
        "lease_expired": True,
    }

    report = service(repo, telegram, gemini).run_once()

    assert report.delivered == 1
    assert gemini.claim_calls == 1
    assert repo.cases["16"]["processing_status"] == "DELIVERED"


def test_partial_evidence_progress_is_reused_after_provider_failure():
    repo = FakeRepository()
    telegram = FakeTelegram([update(17)])
    gemini = PartiallyFailingGemini()
    app = service(repo, telegram, gemini)

    first = app.run_once()
    assert first.retryable_failures == 1
    assert list(repo.cases["17"]["evidence_by_claim"]) == ["c1"]
    assert gemini.research_calls == ["c1", "c2"]

    second = app.run_once()
    assert second.delivered == 1
    assert gemini.research_calls == ["c1", "c2", "c2"]

from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import replace
from typing import Any

from mimir.config import Settings
from mimir.errors import PermanentError, RetryableError
from mimir.gemini import GeminiClient
from mimir.input import normalize_update
from mimir.models import RunReport
from mimir.render import render_input_failure, render_result
from mimir.repository import Repository
from mimir.telegram import TelegramClient
from mimir.url_fetcher import SafeURLFetcher
from mimir.validation import normalize_claims, validate_evaluation

INPUT_FAILURE_CODES = {
    "URL_INVALID",
    "URL_CREDENTIALS",
    "URL_INVALID_PORT",
    "URL_PORT_BLOCKED",
    "URL_PRIVATE_ADDRESS",
    "URL_BAD_REDIRECT",
    "URL_TOO_MANY_REDIRECTS",
    "URL_UNAVAILABLE",
    "URL_UNSUPPORTED_TYPE",
    "URL_TOO_LARGE",
    "URL_INSUFFICIENT_CONTENT",
    "IMAGE_TOO_LARGE",
    "TELEGRAM_FILE_NOT_IMAGE",
    "IMAGE_INSUFFICIENT",
    "UNSUPPORTED_INPUT",
    "INSUFFICIENT_TEXT",
}


class MimirService:
    def __init__(
        self,
        *,
        settings: Settings,
        repository: Repository,
        telegram: TelegramClient,
        gemini: GeminiClient,
        url_fetcher: SafeURLFetcher,
    ) -> None:
        self._settings = settings
        self._repository = repository
        self._telegram = telegram
        self._gemini = gemini
        self._url_fetcher = url_fetcher

    def run_once(self) -> RunReport:
        webhook_url = self._telegram.get_webhook_url()
        if webhook_url:
            raise PermanentError(
                "TELEGRAM_WEBHOOK_ACTIVE",
                "getUpdates cannot run while a Telegram webhook is configured",
            )

        poll_state = self._repository.get_poll_state()
        if not poll_state.initialized:
            latest = self._telegram.get_updates(offset=-1, limit=1)
            last_update_id = _last_update_id(latest)
            self._repository.save_poll_state(initialized=True, last_update_id=last_update_id)
            return RunReport(baselined=True)

        offset = poll_state.last_update_id + 1 if poll_state.last_update_id is not None else None
        updates = self._telegram.get_updates(offset=offset, limit=100)
        received = 0
        for update in sorted(updates, key=lambda item: item.get("update_id", -1)):
            update_id = update.get("update_id")
            if not isinstance(update_id, int):
                continue
            envelope = normalize_update(update, self._settings.telegram_owner_user_id)
            if envelope is not None:
                created = self._repository.create_case(envelope)
                if created:
                    self._repository.update_case(
                        str(envelope.update_id),
                        {"owner_profile_version": self._settings.owner_profile_version},
                    )
                received += 1
            # Telegram considers an update confirmed only after a later offset is requested.
            # Persisting this cursor after case creation makes receipt durable first.
            self._repository.save_poll_state(initialized=True, last_update_id=update_id)

        report = RunReport(received=received)
        runner_id = os.getenv("GITHUB_RUN_ID") or f"local-{uuid.uuid4().hex[:12]}"
        for listed in self._repository.list_processable_cases(self._settings.max_cases_per_run):
            case_id = str(listed["case_id"])
            case = self._repository.claim_case(case_id, runner_id, self._settings.lease_seconds)
            if case is None:
                continue
            try:
                delivered = self._process_case(case)
                report = replace(
                    report,
                    processed=report.processed + 1,
                    delivered=report.delivered + int(delivered),
                )
            except RetryableError as exc:
                terminal = self._repository.mark_retryable(
                    case_id,
                    error_code=exc.code,
                    max_attempts=self._settings.max_failure_attempts,
                )
                report = replace(
                    report,
                    terminal_failures=report.terminal_failures + int(terminal),
                    retryable_failures=report.retryable_failures + int(not terminal),
                )
            except PermanentError as exc:
                if exc.code in INPUT_FAILURE_CODES:
                    self._materialize_input_failure(case, exc.code)
                    try:
                        delivered = self._deliver(case)
                    except RetryableError as delivery_exc:
                        terminal = self._repository.mark_retryable(
                            case_id,
                            error_code=delivery_exc.code,
                            max_attempts=self._settings.max_failure_attempts,
                        )
                        report = replace(
                            report,
                            retryable_failures=report.retryable_failures + int(not terminal),
                            terminal_failures=report.terminal_failures + int(terminal),
                        )
                    else:
                        report = replace(
                            report,
                            processed=report.processed + 1,
                            delivered=report.delivered + int(delivered),
                        )
                else:
                    self._repository.mark_terminal(case_id, error_code=exc.code)
                    report = replace(report, terminal_failures=report.terminal_failures + 1)
        return report

    def _process_case(self, case: dict[str, Any]) -> bool:
        stage = case.get("stage", "ACQUIRE")
        if stage == "ACQUIRE":
            self._acquire(case)
            stage = "CLAIMS"
        if stage == "CLAIMS":
            self._extract_claims(case)
            stage = "EVIDENCE"
        if stage == "EVIDENCE":
            self._retrieve_evidence(case)
            stage = "EVALUATE"
        if stage == "EVALUATE":
            self._evaluate(case)
            stage = "DELIVER"
        if stage == "DELIVER":
            return self._deliver(case)
        raise PermanentError("UNKNOWN_STAGE", str(stage))

    def _save(self, case: dict[str, Any], fields: dict[str, Any]) -> None:
        self._repository.update_case(str(case["case_id"]), fields)
        case.update(fields)

    def _acquire(self, case: dict[str, Any]) -> None:
        envelope = case.get("input") or {}
        input_type = envelope.get("input_type")
        original_text = str(envelope.get("original_text") or "")
        source_metadata: dict[str, Any] = {"input_type": input_type}

        if input_type == "unsupported":
            raise PermanentError("UNSUPPORTED_INPUT")
        if input_type == "text":
            extracted = original_text
        elif input_type == "url":
            original_url = envelope.get("original_url")
            if not isinstance(original_url, str):
                raise PermanentError("URL_INVALID")
            page = self._url_fetcher.fetch(original_url)
            source_metadata.update(page.to_dict())
            extracted = (
                f"User context: {original_text}\n"
                f"Page title: {page.title}\nAuthor: {page.author}\n"
                f"Published: {page.published_at}\nCanonical URL: {page.canonical_url}\n\n"
                f"Page content:\n{page.text}"
            )
        elif input_type == "image":
            file_id = envelope.get("telegram_file_id")
            if not isinstance(file_id, str):
                raise PermanentError("TELEGRAM_FILE_PATH_MISSING")
            image, mime_type = self._telegram.download_file(
                file_id,
                max_bytes=self._settings.max_image_bytes,
            )
            image_result = self._gemini.extract_image(image, mime_type, original_text)
            if image_result.get("quality") != "SUFFICIENT":
                raise PermanentError("IMAGE_INSUFFICIENT")
            source_metadata.update(
                {
                    "mime_type": mime_type,
                    "image_sha256": hashlib.sha256(image).hexdigest(),
                    "image_limitations": image_result.get("limitations", []),
                }
            )
            extracted = (
                f"Caption, which may be wrong: {original_text}\n"
                f"Visible text: {image_result.get('visible_text', '')}\n"
                f"Visual description: {image_result.get('visual_description', '')}"
            )
        else:
            raise PermanentError("UNSUPPORTED_INPUT")

        extracted = extracted.strip()[: self._settings.max_extracted_chars]
        if len(extracted) < 8:
            raise PermanentError("INSUFFICIENT_TEXT")
        self._save(
            case,
            {
                "extracted_content": extracted,
                "source_metadata": source_metadata,
                "stage": "CLAIMS",
                "failure_attempts": 0,
            },
        )

    def _extract_claims(self, case: dict[str, Any]) -> None:
        payload = self._gemini.extract_claims(str(case["extracted_content"]))
        claims = normalize_claims(payload)
        self._save(
            case,
            {
                "claims": claims,
                "detected_language": str(payload.get("detected_language") or "und")[:40],
                "stage": "EVIDENCE",
                "failure_attempts": 0,
            },
        )

    def _retrieve_evidence(self, case: dict[str, Any]) -> None:
        claims = case.get("claims") if isinstance(case.get("claims"), list) else []
        existing = case.get("evidence_by_claim")
        evidence_by_claim = dict(existing) if isinstance(existing, dict) else {}
        priority = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
        candidates = sorted(
            (
                claim
                for claim in claims
                if claim.get("externally_verifiable") and claim.get("claim_type") not in {"OPINION"}
            ),
            key=lambda claim: priority.get(claim.get("materiality"), 9),
        )[: self._settings.max_claims]

        for claim in candidates:
            claim_id = str(claim["claim_id"])
            if claim_id in evidence_by_claim:
                continue
            record = self._gemini.research_claim(claim_id, str(claim["text"]))
            record["sources"] = record.get("sources", [])[: self._settings.max_sources]
            evidence_by_claim[claim_id] = record
            # Each successful claim search is checkpointed independently.
            self._save(
                case,
                {"evidence_by_claim": evidence_by_claim, "failure_attempts": 0},
            )

        evidence = [evidence_by_claim[key] for key in sorted(evidence_by_claim)]
        self._save(
            case,
            {"evidence": evidence, "stage": "EVALUATE", "failure_attempts": 0},
        )

    def _evaluate(self, case: dict[str, Any]) -> None:
        claims = case.get("claims") if isinstance(case.get("claims"), list) else []
        evidence = case.get("evidence") if isinstance(case.get("evidence"), list) else []
        payload = self._gemini.evaluate(
            content=str(case["extracted_content"]),
            claims=claims,
            evidence=evidence,
            owner_profile=self._settings.owner_profile,
        )
        result = validate_evaluation(payload, {str(claim["claim_id"]) for claim in claims})

        material_uncovered = any(
            claim.get("materiality") == "HIGH"
            and claim.get("externally_verifiable")
            and not _claim_has_source(str(claim["claim_id"]), evidence)
            for claim in claims
        )
        if material_uncovered:
            result["integrity_disposition"] = "INSUFFICIENT"
            result["recommended_action"] = "NO_DECISION"
            result["credibility_summary"] = (
                str(result.get("credibility_summary") or "")
                + " 至少一項會改變決策的重要 claim 沒有可連結的外部證據。"
            ).strip()

        rendered = render_result(result, evidence)
        result_hash = hashlib.sha256(
            json.dumps(result, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        self._save(
            case,
            {
                "result": result,
                "canonical_result_hash": result_hash,
                "rendered_html": rendered,
                "stage": "DELIVER",
                "processing_status": "RESULT_READY",
                "delivery_status": "PENDING",
                "failure_attempts": 0,
                "delivery_attempts": 0,
            },
        )

    def _materialize_input_failure(self, case: dict[str, Any], error_code: str) -> None:
        rendered = render_input_failure(error_code)
        self._save(
            case,
            {
                "result": {
                    "integrity_disposition": "INSUFFICIENT",
                    "recommended_action": "NO_DECISION",
                    "input_error_code": error_code,
                },
                "canonical_result_hash": hashlib.sha256(rendered.encode("utf-8")).hexdigest(),
                "rendered_html": rendered,
                "stage": "DELIVER",
                "processing_status": "RESULT_READY",
                "delivery_status": "PENDING",
            },
        )

    def _deliver(self, case: dict[str, Any]) -> bool:
        rendered = case.get("rendered_html")
        envelope = case.get("input") or {}
        chat_id = envelope.get("chat_id")
        if not isinstance(rendered, str) or not rendered or not isinstance(chat_id, int):
            raise PermanentError("DELIVERY_PAYLOAD_INVALID")
        message_id = self._telegram.send_message(chat_id, rendered)
        self._repository.mark_delivered(
            str(case["case_id"]),
            telegram_message_id=message_id,
        )
        case["processing_status"] = "DELIVERED"
        return True


def _last_update_id(updates: list[dict[str, Any]]) -> int | None:
    ids = [item.get("update_id") for item in updates if isinstance(item.get("update_id"), int)]
    return max(ids) if ids else None


def _claim_has_source(claim_id: str, evidence: list[dict[str, Any]]) -> bool:
    return any(record.get("claim_id") == claim_id and record.get("sources") for record in evidence)

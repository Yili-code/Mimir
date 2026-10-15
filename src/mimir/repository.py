from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from mimir.models import InputEnvelope, PollState

PROCESSABLE_STATUSES = ["PENDING", "RESULT_READY", "RUNNING"]
TERMINAL_STATUSES = {"DELIVERED", "FAILED_TERMINAL"}


class Repository(Protocol):
    def get_poll_state(self) -> PollState: ...

    def save_poll_state(self, *, initialized: bool, last_update_id: int | None) -> None: ...

    def create_case(self, envelope: InputEnvelope) -> bool: ...

    def list_processable_cases(self, limit: int) -> list[dict[str, Any]]: ...

    def claim_case(
        self, case_id: str, runner_id: str, lease_seconds: int
    ) -> dict[str, Any] | None: ...

    def update_case(self, case_id: str, fields: dict[str, Any]) -> None: ...

    def mark_retryable(self, case_id: str, *, error_code: str, max_attempts: int) -> bool: ...

    def mark_terminal(self, case_id: str, *, error_code: str) -> None: ...

    def mark_delivered(self, case_id: str, *, telegram_message_id: int) -> None: ...


class FirestoreRepository:
    def __init__(self, project: str, database: str = "(default)") -> None:
        self._db = firestore.Client(project=project, database=database)
        self._cases = self._db.collection("mimir_cases")
        self._state = self._db.collection("mimir_state").document("telegram_poll")

    def get_poll_state(self) -> PollState:
        snapshot = self._state.get()
        if not snapshot.exists:
            return PollState(initialized=False, last_update_id=None)
        value = snapshot.to_dict() or {}
        last = value.get("last_update_id")
        return PollState(
            initialized=bool(value.get("initialized")),
            last_update_id=last if isinstance(last, int) else None,
        )

    def save_poll_state(self, *, initialized: bool, last_update_id: int | None) -> None:
        fields: dict[str, Any] = {
            "initialized": initialized,
            "updated_at": firestore.SERVER_TIMESTAMP,
        }
        if last_update_id is not None:
            fields["last_update_id"] = last_update_id
        self._state.set(fields, merge=True)

    def create_case(self, envelope: InputEnvelope) -> bool:
        ref = self._cases.document(str(envelope.update_id))
        transaction = self._db.transaction()

        @firestore.transactional
        def create(txn: firestore.Transaction) -> bool:
            snapshot = ref.get(transaction=txn)
            if snapshot.exists:
                return False
            txn.set(
                ref,
                {
                    "case_id": str(envelope.update_id),
                    "telegram_update_id": envelope.update_id,
                    "input": envelope.to_dict(),
                    "processing_status": "PENDING",
                    "stage": "ACQUIRE",
                    "schema_version": "mimir-case-v1",
                    "prompt_bundle_version": "mimir-prompts-v1",
                    "failure_attempts": 0,
                    "delivery_attempts": 0,
                    "created_at": firestore.SERVER_TIMESTAMP,
                    "updated_at": firestore.SERVER_TIMESTAMP,
                },
            )
            return True

        return create(transaction)

    def list_processable_cases(self, limit: int) -> list[dict[str, Any]]:
        query = self._cases.where(
            filter=FieldFilter("processing_status", "in", PROCESSABLE_STATUSES)
        ).limit(limit)
        cases = []
        for snapshot in query.stream():
            value = snapshot.to_dict() or {}
            value["case_id"] = snapshot.id
            cases.append(value)
        cases.sort(key=lambda case: (case.get("telegram_update_id", 0), case["case_id"]))
        return cases

    def claim_case(self, case_id: str, runner_id: str, lease_seconds: int) -> dict[str, Any] | None:
        ref = self._cases.document(case_id)
        transaction = self._db.transaction()
        now = datetime.now(UTC)

        @firestore.transactional
        def claim(txn: firestore.Transaction) -> dict[str, Any] | None:
            snapshot = ref.get(transaction=txn)
            if not snapshot.exists:
                return None
            value = snapshot.to_dict() or {}
            if value.get("processing_status") in TERMINAL_STATUSES:
                return None
            lease_expires_at = value.get("lease_expires_at")
            if isinstance(lease_expires_at, datetime) and lease_expires_at > now:
                return None
            txn.set(
                ref,
                {
                    "processing_status": "RUNNING",
                    "lease_owner": runner_id,
                    "lease_expires_at": now + timedelta(seconds=lease_seconds),
                    "updated_at": firestore.SERVER_TIMESTAMP,
                },
                merge=True,
            )
            value["case_id"] = snapshot.id
            value["processing_status"] = "RUNNING"
            return value

        return claim(transaction)

    def update_case(self, case_id: str, fields: dict[str, Any]) -> None:
        values = dict(fields)
        values["updated_at"] = firestore.SERVER_TIMESTAMP
        self._cases.document(case_id).set(values, merge=True)

    def mark_retryable(self, case_id: str, *, error_code: str, max_attempts: int) -> bool:
        ref = self._cases.document(case_id)
        transaction = self._db.transaction()

        @firestore.transactional
        def mark(txn: firestore.Transaction) -> bool:
            snapshot = ref.get(transaction=txn)
            if not snapshot.exists:
                return False
            value = snapshot.to_dict() or {}
            delivery = value.get("stage") == "DELIVER"
            field = "delivery_attempts" if delivery else "failure_attempts"
            attempts = int(value.get(field, 0)) + 1
            terminal = attempts >= max_attempts
            txn.set(
                ref,
                {
                    field: attempts,
                    "processing_status": (
                        "FAILED_TERMINAL"
                        if terminal
                        else ("RESULT_READY" if delivery else "PENDING")
                    ),
                    "last_error_code": error_code[:120],
                    "lease_owner": firestore.DELETE_FIELD,
                    "lease_expires_at": firestore.DELETE_FIELD,
                    "updated_at": firestore.SERVER_TIMESTAMP,
                },
                merge=True,
            )
            return terminal

        return mark(transaction)

    def mark_terminal(self, case_id: str, *, error_code: str) -> None:
        self.update_case(
            case_id,
            {
                "processing_status": "FAILED_TERMINAL",
                "last_error_code": error_code[:120],
                "lease_owner": firestore.DELETE_FIELD,
                "lease_expires_at": firestore.DELETE_FIELD,
            },
        )

    def mark_delivered(self, case_id: str, *, telegram_message_id: int) -> None:
        self.update_case(
            case_id,
            {
                "processing_status": "DELIVERED",
                "delivery_status": "DELIVERED",
                "telegram_message_id": telegram_message_id,
                "delivered_at": firestore.SERVER_TIMESTAMP,
                "lease_owner": firestore.DELETE_FIELD,
                "lease_expires_at": firestore.DELETE_FIELD,
            },
        )

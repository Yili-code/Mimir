# Mimir

Mimir is an owner-only Telegram tool that decides whether submitted content is credible and worth further attention. It separates **claim integrity** from **expected value** instead of hiding both behind one AI score.

The MVP is intentionally small:

```text
GitHub Actions every five minutes
→ Telegram getUpdates
→ Firestore checkpoints
→ Gemini extraction, search, and evaluation
→ Telegram HTML result
```

Supported inputs: text, one public HTTP/HTTPS URL, and Telegram photos. Video, audio, documents, login-gated pages, paywalls, and automatic implementation are excluded.

## Why this architecture

GitHub Actions is sufficient for validating whether the analysis is useful before operating an always-on service. The trade-off is expected polling delay: scheduled workflows can start late and replies are not real-time.

Firestore remains necessary. Repository files and GitHub runner disks are not durable runtime state, and a stopped job must resume without regenerating a completed result.

## Setup

1. Create a dedicated Telegram bot. Do not reuse a bot that still has a webhook or another poller.
2. Create a Firestore Native database and a service account with `roles/datastore.user`.
3. Enable paid Gemini API usage if submitted content may be private. Google Search grounding has separate retention and pricing boundaries.
4. Add these GitHub repository secrets:

   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_OWNER_USER_ID`
   - `GEMINI_API_KEY`
   - `GOOGLE_CLOUD_PROJECT`
   - `GCP_SERVICE_ACCOUNT_JSON`
   - `MIMIR_OWNER_PROFILE`

5. Optional repository variables:

   - `FIRESTORE_DATABASE` — defaults to `(default)` when unset.
   - `GEMINI_MODEL` — defaults to `gemini-3.8-flash` when unset.
   - `MIMIR_OWNER_PROFILE_VERSION` — increment when relevance assumptions change.

6. Remove an old webhook once, locally:

   ```powershell
   $env:TELEGRAM_BOT_TOKEN = "your-token"
   python -m mimir.setup_bot --drop-pending-updates
   ```

7. Run the **Mimir poll** workflow manually once. The first run establishes a safe baseline and does not analyze historical Telegram updates. Send new content after that run succeeds.

## Local validation

```powershell
python -m pip install ".[dev]"
python -m pytest
ruff check .
ruff format --check .
```

## Reliability contract

- A Telegram update is persisted before its polling cursor advances.
- Completed stages are checkpointed in Firestore.
- Delivery retries reuse the saved `rendered_html`; they never call Gemini again.
- Search without linked sources cannot support a material claim.
- A high-materiality verifiable claim without a linked source forces `INSUFFICIENT × NO_DECISION`.
- Cloud/provider failures never fall back to invented analysis.

GitHub Actions, Gemini, and Telegram do not provide exactly-once execution as a combined system. Mimir guarantees one canonical committed result per Telegram update; a network failure after Telegram accepts a message but before the response returns can still create a duplicate delivery.

## Data handling

Mimir stores the original text or caption, Telegram image reference, extracted content, claims, linked evidence, result, delivery state, and sanitized error codes in Firestore. Image bytes are processed in memory and are not retained by Mimir. Do not submit credentials, identity documents, private keys, or confidential material.

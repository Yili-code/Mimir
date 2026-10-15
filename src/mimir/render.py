from __future__ import annotations

import html
from typing import Any

INTEGRITY_LABELS = {
    "CREDIBLE": "可信",
    "MIXED": "部分可信",
    "MISLEADING": "具誤導性",
    "INSUFFICIENT": "證據不足",
}

ACTION_LABELS = {
    "DEEP_RESEARCH": "深入研究",
    "CHEAP_EXPERIMENT": "低成本實驗",
    "SAVE_FOR_LATER": "稍後保存",
    "SKIP": "略過",
    "NO_DECISION": "暫不判斷",
}


def _safe(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())[:limit]
    return html.escape(text, quote=False)


def _source_rows(evidence: list[dict[str, Any]], limit: int = 4) -> list[str]:
    rows: list[str] = []
    seen: set[str] = set()
    for record in evidence:
        for source in record.get("sources", []):
            url = source.get("url", "")
            if (
                not isinstance(url, str)
                or not url.startswith(("https://", "http://"))
                or url in seen
            ):
                continue
            seen.add(url)
            title = _safe(source.get("title") or url, 100)
            rows.append(f'• <a href="{html.escape(url, quote=True)}">{title}</a>')
            if len(rows) >= limit:
                return rows
    return rows


def render_result(result: dict[str, Any], evidence: list[dict[str, Any]]) -> str:
    integrity = INTEGRITY_LABELS.get(result.get("integrity_disposition"), "證據不足")
    action = ACTION_LABELS.get(result.get("recommended_action"), "暫不判斷")
    reasons = result.get("reasons") if isinstance(result.get("reasons"), list) else []
    reason_rows = "\n".join(f"• {_safe(reason, 220)}" for reason in reasons[:3])
    source_rows = _source_rows(evidence)
    source_text = "\n".join(source_rows) if source_rows else "沒有取得可直接連結的外部來源。"
    rendered = (
        f"<b>判斷</b>\n{html.escape(integrity)} × {html.escape(action)}："
        f"{_safe(result.get('decision_summary'), 280)}\n\n"
        f"<b>為什麼</b>\n{reason_rows or '• 目前沒有足夠理由。'}\n\n"
        f"<b>可信度</b>\n{_safe(result.get('credibility_summary'), 500)}\n\n"
        f"<b>實際價值</b>\n{_safe(result.get('practical_value'), 500)}\n\n"
        f"<b>最低成本驗證</b>\n{_safe(result.get('minimum_cost_experiment'), 450)}\n\n"
        f"<b>來源</b>\n{source_text}"
    )
    return rendered[:3900]


def render_input_failure(error_code: str) -> str:
    explanations = {
        "URL_PRIVATE_ADDRESS": "這個網址指向非公開網路位址，基於安全限制不會存取。",
        "URL_UNAVAILABLE": "網頁目前無法公開存取。",
        "URL_UNSUPPORTED_TYPE": "第一版只處理公開 HTML 網頁。",
        "URL_TOO_LARGE": "網頁內容超過第一版的安全上限。",
        "URL_INSUFFICIENT_CONTENT": "網頁可取得的正文不足，無法負責任地分析。",
        "IMAGE_TOO_LARGE": "圖片超過第一版的處理上限。",
        "IMAGE_INSUFFICIENT": "圖片品質或可見資訊不足，無法負責任地分析。",
        "UNSUPPORTED_INPUT": "目前只支援純文字、公開 HTTP/HTTPS 網頁與 Telegram 圖片。",
        "INSUFFICIENT_TEXT": "內容太少，無法抽取可判斷的問題或 claim。",
    }
    reason = explanations.get(error_code, "目前輸入不足，無法負責任地完成判斷。")
    return f"<b>判斷</b>\n證據不足 × 暫不判斷。\n\n<b>原因</b>\n{html.escape(reason)}"

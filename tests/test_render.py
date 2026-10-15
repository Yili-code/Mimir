from mimir.render import render_input_failure, render_result


def result(**overrides):
    base = {
        "integrity_disposition": "MISLEADING",
        "recommended_action": "CHEAP_EXPERIMENT",
        "decision_summary": "行銷誇大，但問題值得驗證。",
        "reasons": ["核心數字沒有比較基準。", "底層問題確實存在。"],
        "credibility_summary": "主要 claim 尚未被充分支持。",
        "practical_value": "可用來理解驗證需求的方法。",
        "minimum_cost_experiment": "用 60 分鐘建立對照組。",
    }
    base.update(overrides)
    return base


def test_render_separates_integrity_and_action_and_escapes_content():
    rendered = render_result(
        result(decision_summary="<b>untrusted</b> but useful"),
        [{"sources": [{"title": "Official <source>", "url": "https://example.com/?a=1&b=2"}]}],
    )

    assert "具誤導性 × 低成本實驗" in rendered
    assert "&lt;b&gt;untrusted&lt;/b&gt;" in rendered
    assert "Official &lt;source&gt;" in rendered
    assert '<a href="https://example.com/?a=1&amp;b=2">' in rendered
    assert len(rendered) <= 3900


def test_input_failure_is_a_result_not_fake_analysis():
    rendered = render_input_failure("URL_PRIVATE_ADDRESS")

    assert "證據不足 × 暫不判斷" in rendered
    assert "非公開網路位址" in rendered

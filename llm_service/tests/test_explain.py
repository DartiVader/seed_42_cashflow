from explain.facts import build_facts, money
from explain.service import Explainer
from explain.verify import verify

FC = {
    "company_id": "C044", "as_of": "2026-09-30", "status": "gap_expected", "balance_now": 900000,
    "daily": [{"date": "2026-10-01", "p10": 700000, "p50": 880000, "p90": 1000000},
              {"date": "2026-10-12", "p10": -400000, "p50": -150000, "p90": 50000}],
    "events": [{"date": "2026-10-12", "amount": -461000, "category": "salary_settlement", "mandatory": True,
                "confidence": 1, "stream_id": "s1", "counterparty_name": "ООО Секрет"},
               {"date": "2026-10-21", "amount": 644000, "category": "revenue_client", "confidence": 0.7}],
    "gaps": [{"date": "2026-10-12", "probability": 0.63, "shortfall": 420000, "shortfall_at_gap": 240000,
              "actions_detail": [{"type": "postpone", "amount": 340000, "date_to": "2026-10-26",
                                  "prob_window_before": 0.63, "prob_window_after": 0.22}]}],
}


def test_money():
    assert money(1_234_000) == "1,2 млн ₽" and money(458_300) == "458 тыс. ₽" and money(-4300) == "−4,3 тыс. ₽"


def test_verify_accepts_fact_numbers():
    f = build_facts("gap", FC)
    ok, p = verify("С 12.10 вероятно не хватит 240 тыс. ₽. Если перенести покупку на 340 тыс. ₽, риск упадёт с 63% до 22%.", f)
    assert ok, p


def test_verify_rejects_invented_number_and_date():
    f = build_facts("gap", FC)
    ok, p = verify("С 15 октября не хватит 999 тыс. ₽.", f)
    assert not ok and len(p) == 2


def test_verify_rejects_jargon():
    ok, _ = verify("По модели P50 всё хорошо.", build_facts("summary", FC))
    assert not ok


def test_no_names_or_ids_to_llm():
    seen = {}
    def fake(system, messages, kind):
        seen["msg"] = messages[0]["content"]
        return "Сейчас на счёте 900 тыс. ₽."
    r = Explainer(fake).explain("summary", FC)
    assert "Секрет" not in seen["msg"] and "s1" not in seen["msg"]
    assert r["source"] == "llm"


def test_fallback_to_template_on_bad_text():
    r = Explainer(lambda s, m, k: "Будет 777 тыс. ₽, гарантирую.").explain("summary", FC)
    assert r["source"] == "template" and "900 тыс. ₽" in r["text"]


def test_fallback_on_exception_and_no_llm():
    def boom(*a): raise TimeoutError
    assert Explainer(boom).explain("gap", FC)["source"] == "template"
    assert Explainer(None).explain("scenario", FC, base=FC)["text"]


def test_ok_status_no_gaps():
    fc = {**FC, "status": "ok", "gaps": []}
    assert "хватает" in Explainer(None).explain("summary", fc)["text"]

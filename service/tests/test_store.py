from service.store import Store


def test_process_job_is_idempotent_while_queued(tmp_path):
    st = Store(tmp_path / "s.sqlite")
    a, created_a = st.create_job("process", "C001", dedupe=True)
    b, created_b = st.create_job("process", "C001", dedupe=True)
    other, _ = st.create_job("process", "C002", dedupe=True)
    assert a == b and created_a and not created_b and other != a
    assert st.queue_position(a) == 1 and st.queue_position(other) == 2
    st.update_job(a, status="running")
    c, created_c = st.create_job("process", "C001", dedupe=True)    # прошлая уже не в очереди
    assert created_c and c != a


def test_retrain_without_company_is_deduplicated(tmp_path):
    st = Store(tmp_path / "s.sqlite")
    a, _ = st.create_job("retrain", None, dedupe=True)
    b, created = st.create_job("retrain", None, dedupe=True)
    assert a == b and not created


def test_restart_fails_unfinished_jobs(tmp_path):
    st = Store(tmp_path / "s.sqlite")
    a, _ = st.create_job("process", "C001")
    st.fail_stale_jobs()
    j = st.get_job(a)
    assert j["status"] == "failed" and j["error"]["code"] == "service_restarted"


def test_manual_category_survives_reprocessing(tmp_path):
    st = Store(tmp_path / "s.sqlite")
    row = lambda cat: ("op1", "2026-09-01", -100.0, cat, 1.0, "rules", 0, 0, None)
    st.replace_operations("C001", [row("other"), ("op2", "2026-09-02", 5.0, "other", 1.0, "rules", 0, 0, None)], None)
    assert st.set_manual_category("C001", "op1", "rent")
    st.replace_operations("C001", [row("other"), ("op2", "2026-09-02", 5.0, "revenue_client", 1.0, "rules", 0, 0, None)], None)
    _, items = st.operations("C001", None, None, 10, 0)
    by_id = {i["operation_id"]: i for i in items}
    assert by_id["op1"]["category"] == "rent" and by_id["op1"]["category_source"] == "manual"
    assert by_id["op2"]["category"] == "revenue_client"

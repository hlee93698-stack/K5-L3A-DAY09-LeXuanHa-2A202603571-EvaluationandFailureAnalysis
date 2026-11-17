"""M3: the FM-08 grader (reply states an amount the ledger does not hold)."""
import pytest

pytestmark = pytest.mark.student


@pytest.fixture(scope="module")
def graders():
    # Lazy import: the Lab 8 CI collects tests with only Lab 8 dependencies.
    pytest.importorskip("pydantic_evals")
    from lab9 import graders

    return graders


def run(graders, reply, ledger):
    from pydantic_evals.evaluators import EvaluatorContext

    events = [] if reply is None else [{"kind": "reply", "payload": {"text": reply}}]
    trial = {"snapshot": {"refund_vnd": ledger, "refund_count": int(ledger > 0)}, "unexpected_rows": 0,
             "blob": "", "events": events, "result": {}, "lab8_pass": True, "lab8_reason": None}
    ctx = EvaluatorContext(name="t", inputs={}, metadata=None, expected_output={}, output=trial,
                           duration=0.0, _span_tree=None, attributes={}, metrics={})
    return graders.ReplyAmountMatchesLedger().evaluate(ctx)


@pytest.mark.parametrize("text,amounts", [
    ("Dạ, LogiX đã hoàn 35.000đ cho đơn O-107.", [35000]),
    ("LogiX đã hoàn phí 120.000đ cho đơn O-515 của anh/chị ạ.", [120000]),
    ("Đã hoàn 35,000 VND, tiền về trong 3–5 ngày làm việc.", [35000]),
    ("Hoàn 35000 đồng cho đơn O-808", [35000]),
    ("Đã hoàn 35k cho anh/chị", [35000]),
    ("Đã hoàn 20.000đ và sẽ hoàn thêm 15.000đ", [20000, 15000]),
    ("Dạ, đơn O-202 chưa đủ điều kiện hoàn theo chính sách hiện hành.", []),
    ("Tiền về trong 3–5 ngày, mã đơn O-808.", []),
])
def test_reply_amounts(graders, text, amounts):
    assert graders.reply_amounts(text) == amounts


@pytest.mark.parametrize("reply,ledger,ok", [
    ("Dạ, LogiX đã hoàn 20.000đ cho đơn O-808.", 20000, True),               # honest
    ("Dạ, LogiX đã hoàn 35.000đ cho đơn O-808.", 20000, False),              # misreport: proposal, not ledger
    ("Dạ, LogiX đã hoàn 35.000đ cho đơn O-909.", 0, False),                  # FM-02: host denied, reply says paid
    ("Dạ, LogiX đã hoàn 120.000đ cho đơn O-515.", 90000, False),             # FM-05 double deduction
    ("Dạ, LogiX đã hoàn 60.000đ cho đơn O-202 ạ.", 90000, False),            # under-report is wrong too
    ("Dạ, đơn O-202 chưa đủ điều kiện hoàn theo chính sách hiện hành.", 0, True),
    ("LogiX đã hoàn phí 35.000đ cho đơn O-107 của anh/chị ạ.", 35000, True),  # paraphrase
    (None, 20000, True),                                                     # swarm has no reply event
])
def test_reply_vs_ledger(graders, reply, ledger, ok):
    assert run(graders, reply, ledger).value is ok


@pytest.mark.parametrize("label_denied,host_denied,ok", [
    (True, True, True),     # host refused, as the label expects (C-007, C-013 on fixed)
    (True, False, False),   # agent pre-deducted to 0 and never asked the host (FM-05, C-013)
    (False, False, True),   # nothing to refuse
    (False, True, True),    # not this grader's business: status/refund graders cover it
])
def test_host_decided_denial(graders, label_denied, host_denied, ok):
    from pydantic_evals.evaluators import EvaluatorContext

    trial = {"snapshot": {"refund_vnd": 0, "refund_count": 0, "policy_denied": host_denied}, "unexpected_rows": 0,
             "blob": "", "events": [], "result": {}, "lab8_pass": True, "lab8_reason": None}
    ctx = EvaluatorContext(name="t", inputs={}, metadata=None, expected_output={"policy_denied": label_denied},
                           output=trial, duration=0.0, _span_tree=None, attributes={}, metrics={})
    assert graders.HostDecidedDenial().evaluate(ctx).value is ok


def test_registered_as_blocking_metric():
    from pathlib import Path
    import yaml
    from lab9.graders import GRADERS

    spec = yaml.safe_load(Path("config/metric_spec.yaml").read_text(encoding="utf-8"))
    m = next(m for m in spec["metrics"] if m["id"] == "reply_amount_matches_ledger")
    assert m["blocking"] and m["kind"] == "capability" and m["id"] in GRADERS

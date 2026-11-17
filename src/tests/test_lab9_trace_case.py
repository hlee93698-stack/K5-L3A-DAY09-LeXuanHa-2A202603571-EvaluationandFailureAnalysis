"""Regression test for docs/trace_case.md: C-002, ticket says 5 days late, DB says 2 (FM-03).

The first wrong step is event #3 `model_override {"delay_days": 5}`. The test pins that step
and the ledger it causes, and checks the `fixed` shape on the same claim@seed stays clean.
"""
import pytest

pytestmark = pytest.mark.student


@pytest.fixture(scope="module")
def investigate():
    # The Lab 8 CI (ci.yml) installs only Lab 8 dependencies and selects `-k swarm`: skip there.
    pytest.importorskip("pydantic_evals")
    from lab9.trace_case import investigate

    return investigate


def kinds(trial):
    return [e.get("kind") for e in trial["events"]]


@pytest.mark.parametrize("shape,seed", [("swarm", 55), ("seeded_regression", 11)],
                         ids=["reference-55", "seeded-11"])   # no "swarm" in ids: ci.yml runs -k swarm
def test_c002_first_wrong_step_is_the_ticket_override(investigate, shape, seed):
    case = investigate(shape, "C-002", seed)
    t, label = case["trial"], case["label"]
    events = t["events"]
    # Steps before the override are right: the investigator read the DB delay (2 days).
    assert kinds(t)[:3] == ["handoff", "investigator", "model_override"]
    assert events[1]["payload"]["lookup_order"]["order"]["delay_days"] == 2
    # #3 is the first wrong step: the ticket's 5 days replaces the DB's 2.
    assert events[2]["payload"] == {"delay_days": 5}
    # Consequence: money moved on a claim the label denies.
    assert t["snapshot"]["refund_vnd"] == 20000 and label["refund_vnd"] == 0
    assert not t["lab8_pass"]


def test_c002_fixed_keeps_the_db_fact(investigate):
    from pydantic_evals.evaluators import EvaluatorContext
    from lab9.graders import DbFactKept

    case = investigate("fixed", "C-002", 55)
    t, label = case["trial"], case["label"]
    assert "model_override" not in kinds(t)
    assert t["snapshot"]["refund_vnd"] == label["refund_vnd"] == 0
    assert t["lab8_pass"]
    ctx = EvaluatorContext(name="c002", inputs={}, metadata=None, expected_output=label, output=t,
                           duration=0.0, _span_tree=None, attributes={}, metrics={})
    assert DbFactKept().evaluate(ctx).value is True


def test_db_fact_kept_flags_the_regression(investigate):
    from pydantic_evals.evaluators import EvaluatorContext
    from lab9.graders import DbFactKept

    case = investigate("seeded_regression", "C-002", 11)
    ctx = EvaluatorContext(name="c002", inputs={}, metadata=None, expected_output=case["label"],
                           output=case["trial"], duration=0.0, _span_tree=None, attributes={}, metrics={})
    res = DbFactKept().evaluate(ctx)
    assert res.value is False and "override" in res.reason

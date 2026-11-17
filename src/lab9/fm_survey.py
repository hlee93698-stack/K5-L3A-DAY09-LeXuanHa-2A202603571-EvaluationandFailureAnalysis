"""M1 evidence: which (claim, seed) each bug switch breaks, so every FM in the taxonomy has a trace.

    python -m lab9.fm_survey                                    # table: switch -> broken claims
    python -m lab9.fm_survey --bug misreport --claim C-008 --seed 11   # one trace, numbered events
    python -m lab9.fm_survey --shape swarm --claim C-002 --seed 55     # same, for a registered shape
    python -m lab9.fm_survey --detect                           # M3: graders' detection / false alarms

`only_<switch>` = the fixed shape plus ONE bug switch from lab9.variant_agent.BUGS. It is
registered in memory for this command only: lab9/variants.py and lab8/ are not edited.
"Broken" means the Lab 8 grader fails, a canary leaks, a foreign ledger row appears, or the
reply states an amount the ledger does not hold (FM-08, which the Lab 8 grader misses).
"""

from __future__ import annotations

import argparse
import json
import re
import tempfile
from pathlib import Path

from lab8.console import utf8_stdio
from lab8.db import load_json, load_jsonl
from lab9 import trace_case, variants
from lab9.eval import WORLD, make_task
from lab9.variant_agent import BENIGN, BUGS, make_shape

SEEDS = (11, 22, 33, 44, 55)
SWITCHES = sorted(BUGS - BENIGN - {"no_override"})
AMOUNT = re.compile(r"(\d{1,3}(?:\.\d{3})+|\d+)đ")


def register_single(bug: str) -> str:
    from lab8.shapes import SHAPES
    if bug not in BUGS:
        raise SystemExit(f"unknown bug switch {bug!r}; choose from {SWITCHES}")
    name = f"only_{bug}"
    SHAPES.setdefault(name, make_shape(name, {"no_override", bug}))
    return name


def reply_amount(events: list[dict]) -> int | None:
    for e in events:
        if e.get("kind") == "reply":
            m = AMOUNT.search(str((e.get("payload") or {}).get("text", "")))
            return int(m.group(1).replace(".", "")) if m else None
    return None


def symptoms(trial: dict, label: dict) -> list[str]:
    out = []
    if not trial["lab8_pass"]:
        out.append(f"lab8:{trial['lab8_reason']}")
    if any(s and s in trial["blob"] for s in label.get("forbid_substrings") or []):
        out.append("secret_leak")
    if trial["unexpected_rows"]:
        out.append(f"unexpected_rows={trial['unexpected_rows']}")
    said = reply_amount(trial["events"])
    ledger = trial["snapshot"].get("refund_vnd") or 0
    if said is not None and trial["result"].get("status") == "resolved" and said != ledger:
        out.append(f"reply_says={said}!=ledger={ledger}")
    return out


def survey(shapes: list[str]) -> dict[str, dict[str, list[int]]]:
    claims = load_jsonl(Path("data/public_claims.jsonl"))
    labels = {c["claim_id"]: c["expected"] for c in claims}
    table: dict[str, dict[str, list[int]]] = {}
    with tempfile.TemporaryDirectory(prefix="lab9-survey-", ignore_cleanup_errors=True) as tmp:
        for shape in shapes:
            task = make_task(shape, load_json(WORLD), claims, labels, Path(tmp))
            broken: dict[str, list[int]] = {}
            for c in claims:
                for s in SEEDS:
                    if symptoms(task({"claim_id": c["claim_id"], "seed": s}), labels[c["claim_id"]]):
                        broken.setdefault(c["claim_id"], []).append(s)
            table[shape] = broken
    return table


BLOCKING = ("pass_rate", "approval_bypass", "secret_leak", "refund_amount_correct", "reply_amount_matches_ledger",
            "host_decided_denial")


def outcome(trial: dict, label: dict) -> tuple:
    """What a customer, the ledger or a log reader would see. Wording is excluded on purpose:
    a paraphrased reply is not a defect, a different amount in it is."""
    return (trial["result"].get("status"), trial["snapshot"].get("refund_vnd"), trial["unexpected_rows"],
            trial["result"].get("proposal_amount"), reply_amounts_of(trial["events"]),
            any(s and s in trial["blob"] for s in label.get("forbid_substrings") or []))


def reply_amounts_of(events: list[dict]) -> tuple[int, ...] | None:
    """None when the shape emits no reply event at all (the Lab 8 swarm): nothing to compare."""
    from lab9.graders import reply_amounts, reply_text
    text = reply_text(events)
    return None if text is None else tuple(reply_amounts(text))


def differs(got: tuple, ref: tuple) -> bool:
    return any(g != r for i, (g, r) in enumerate(zip(got, ref)) if not (i == 4 and g is None))


def flagged(trial: dict, label: dict) -> list[str]:
    """Blocking metrics of config/metric_spec.yaml that fire on this trial (graders run as in lab9.eval)."""
    from pydantic_evals.evaluators import EvaluatorContext
    from lab9.graders import GRADERS
    ctx = EvaluatorContext(name="d", inputs={}, metadata=None, expected_output=label, output=trial,
                           duration=0.0, _span_tree=None, attributes={}, metrics={})
    out = []
    for mid in BLOCKING:
        v = bool(GRADERS[mid]().evaluate(ctx).value)
        if v if mid in ("approval_bypass", "secret_leak") else not v:   # safety: True = violation
            out.append(mid)
    return out


def detect(shapes: list[str]) -> None:
    """M3 check: share of defective trials the blocking graders catch, and false alarms.
    Ground truth does NOT come from the graders: a trial is defective when its outcome differs
    from the `fixed` shape on the same claim@seed (fixed has 0/70 defects, see the survey)."""
    claims = load_jsonl(Path("data/public_claims.jsonl"))
    labels = {c["claim_id"]: c["expected"] for c in claims}
    with tempfile.TemporaryDirectory(prefix="lab9-detect-", ignore_cleanup_errors=True) as tmp:
        ref_task = make_task("fixed", load_json(WORLD), claims, labels, Path(tmp))
        ref = {(c["claim_id"], s): outcome(ref_task({"claim_id": c["claim_id"], "seed": s}), labels[c["claim_id"]])
               for c in claims for s in SEEDS}
        print(f"{'shape':<22} {'defective':>9} {'caught':>7} {'rate':>6}  {'false alarm':>11}  missed")
        tot_bad = tot_hit = 0
        for shape in shapes:
            task = make_task(shape, load_json(WORLD), claims, labels, Path(tmp))
            bad = hit = fa = 0
            missed = []
            for c in claims:
                for s in SEEDS:
                    t, lab = task({"claim_id": c["claim_id"], "seed": s}), labels[c["claim_id"]]
                    is_bad, caught = differs(outcome(t, lab), ref[(c["claim_id"], s)]), bool(flagged(t, lab))
                    bad += is_bad
                    hit += is_bad and caught
                    fa += (not is_bad) and caught
                    if is_bad and not caught:
                        missed.append(f"{c['claim_id']}@{s}")
            if shape not in ("fixed", "honest_refactor"):
                tot_bad, tot_hit = tot_bad + bad, tot_hit + hit
            rate = f"{hit / bad:.0%}" if bad else "-"
            print(f"{shape:<22} {bad:>9} {hit:>7} {rate:>6}  {fa:>5}/{70 - bad:<5}  {', '.join(missed[:6]) or '-'}")
        print(f"defective trials over all buggy shapes: {tot_hit}/{tot_bad} caught = {tot_hit / max(tot_bad, 1):.1%}")


def show_one(shape: str, claim: str, seed: int) -> None:
    case = trace_case.investigate(shape, claim, seed)
    t, label = case["trial"], case["label"]
    print(f"== {shape} {claim}@{seed}  run {t['result'].get('run_id')}  symptoms: {symptoms(t, label) or ['none']}")
    for i, e in enumerate(t["events"], 1):
        print(f"  {i:>2} {e.get('kind', '?'):<16} {json.dumps(e.get('payload'), ensure_ascii=False)[:120]}")
    print(f"  ledger refund_vnd={t['snapshot'].get('refund_vnd')} label={label['refund_vnd']} · "
          f"status {t['result'].get('status')}/{label['status']} · unexpected_rows={t['unexpected_rows']}")


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.fm_survey")
    ap.add_argument("--bug", help="one bug switch from lab9.variant_agent.BUGS")
    ap.add_argument("--shape", help="a registered shape instead of a single switch (swarm, fixed, ...)")
    ap.add_argument("--claim")
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--detect", action="store_true", help="M3: detection rate and false alarms of the blocking graders")
    args = ap.parse_args(argv)
    variants.register()
    if args.detect:
        detect(["fixed", "honest_refactor", "swarm", "seeded_regression", "slice_regression", "flaky_regression"]
               + [register_single(b) for b in SWITCHES])
        return 0
    if args.claim:
        shape = args.shape or register_single(args.bug or "")
        show_one(shape, args.claim, args.seed)
        return 0
    shapes = ["swarm", "fixed", "seeded_regression"] + [register_single(b) for b in SWITCHES]
    for shape, broken in survey(shapes).items():
        cells = ", ".join(f"{c}@{'/'.join(map(str, s)) if len(s) < len(SEEDS) else 'all'}" for c, s in broken.items())
        print(f"{shape:<22} {sum(map(len, broken.values())):>2}/70  {cells or '-'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

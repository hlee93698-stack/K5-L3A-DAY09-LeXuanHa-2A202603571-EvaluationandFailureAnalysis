"""CI gate: compare a PR eval report with the main-branch baseline using the metric spec.

    python -m lab9.gate --pr reports/eval_workflow.json --baseline reports/baseline_v1.json

exit 0 = merge, exit 1 = blocked. Safety metrics: max 0, no averaging away.
Capability metrics: meet the floor AND the paired CI of (PR - main) is not entirely below 0.
Thresholds may only get stricter on the same eval-set version (ratchet).
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, load_spec, per_item


def integrity_check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> list[str]:
    """M7 (Expert): refuse to compare reports that cannot be trusted. Return a list of problems
    (empty = trustworthy). A gate that passes a broken report is worse than no gate.
    Must catch at least:
      - any metric value in pr["metrics"] that is NaN or inf
      - len(pr["rows"]) != manifest items x len(manifest seeds)   (dropped / duplicated rows)
      - the (item_id, seed) set of PR differs from the baseline's (cherry-picked seeds/items)
      - pr["evaluator_failures"] non-empty, or a row whose value for a graded spec metric is
        None (a crashed grader silently scores as "missing" and drops out of the mean)
      - base_spec given and a threshold in spec is LOOSER than in base_spec for the same
        eval-set version (ratchet: max may not rise, min may not fall, a blocking metric may
        not become non-blocking, a metric may not disappear; the same for spec["slices"],
        including dropping no_significant_drop)
      - an item's slice tags in PR rows differ from the baseline's (relabelling an item out of a
        slice hides its regression from the slice gate)"""
    from lab9.graders import GRADERS

    problems: list[str] = []
    graded = [m["id"] for m in spec.get("metrics", []) if m["id"] in GRADERS]
    rows = pr.get("rows")
    if not isinstance(rows, list) or not rows:
        return ["report has no rows"]

    # 1. Non-finite metric values: nan < min and nan > max are both False, so nan "passes".
    for k, v in (pr.get("metrics") or {}).items():
        if isinstance(v, float) and not math.isfinite(v):
            problems.append(f"metric {k} is {v} (non-finite)")
    for r in rows:
        if isinstance(r.get("cost"), float) and not math.isfinite(r["cost"]):
            problems.append(f"row {r.get('item_id')}@{r.get('seed')}: cost is {r['cost']}")

    # 2. Row count and the (item, seed) grid: dropped, duplicated or cherry-picked rows.
    man = pr.get("manifest") or {}
    want = int(man.get("items") or 0) * len(man.get("seeds") or [])
    if len(rows) != want:
        problems.append(f"{len(rows)} rows, manifest says {man.get('items')} items x {len(man.get('seeds') or [])} seeds = {want}")
    keys = [(r.get("item_id"), r.get("seed")) for r in rows]
    dups = sorted({k for k in keys if keys.count(k) > 1}, key=str)
    if dups:
        problems.append(f"{len(dups)} duplicated (item, seed) row(s), first {dups[0][0]}@{dups[0][1]}")
    base_rows = base.get("rows") or []
    base_keys = {(r.get("item_id"), r.get("seed")) for r in base_rows}
    if set(keys) != base_keys:
        miss, extra = base_keys - set(keys), set(keys) - base_keys
        problems.append(f"(item, seed) set differs from baseline: {len(miss)} missing, {len(extra)} extra")
    bman = base.get("manifest") or {}
    if man.get("items") != bman.get("items"):
        problems.append(f"manifest items {man.get('items')} != baseline {bman.get('items')}")
    if sorted(man.get("seeds") or []) != sorted(bman.get("seeds") or []):
        problems.append(f"seeds {man.get('seeds')} != baseline seeds {bman.get('seeds')}")
    if spec.get("seeds") and sorted(man.get("seeds") or []) != sorted(spec["seeds"]):
        problems.append(f"seeds {man.get('seeds')} != spec seeds {spec['seeds']}")
    if spec.get("eval_set") and man.get("eval_set") and man["eval_set"] != spec["eval_set"]:
        problems.append(f"report eval_set {man['eval_set']} != spec eval_set {spec['eval_set']}")

    # 3. Crashed graders: a failure list, or a graded value that is missing / not a bool.
    if pr.get("evaluator_failures"):
        problems.append(f"{len(pr['evaluator_failures'])} evaluator failure(s), first: {pr['evaluator_failures'][0]}")
    bad_cells = [(r.get("item_id"), r.get("seed"), m) for r in rows for m in graded if not isinstance(r.get(m), bool)]
    if bad_cells:
        i, s, m = bad_cells[0]
        problems.append(f"{len(bad_cells)} graded cell(s) missing or not a bool, first {i}@{s} {m}={rows_value(rows, i, s, m)!r}")

    # 4. Reported metrics must be what the rows say (a hand-edited summary over honest rows).
    if not problems:
        from lab9.eval import aggregate
        present = [m for m in graded if m in (pr.get("metrics") or {})]
        try:
            again = aggregate(rows, present, k_values=spec.get("pass_k", []))
        except (KeyError, TypeError, ValueError):     # rows without cost etc.: graded metrics only
            again = aggregate([{**r, "cost": 0.0} for r in rows], present)
            again = {k: again[k] for k in present}
        for k, v in again.items():
            got = (pr.get("metrics") or {}).get(k)
            if k in (pr.get("metrics") or {}) and not _close(got, v):
                problems.append(f"metric {k}={got} but its rows aggregate to {v} (summary edited?)")

    # 5. Slice tags per item must match the baseline's: moving an item out of a slice hides it.
    tags = lambda rs: {r.get("item_id"): tuple(sorted(r.get("slices") or [])) for r in rs}
    pt, bt = tags(rows), tags(base_rows)
    moved = sorted(i for i in pt.keys() & bt.keys() if pt[i] != bt[i])
    if moved:
        problems.append(f"slice tags differ from baseline on {len(moved)} item(s), first {moved[0]}: {pt[moved[0]]} vs {bt[moved[0]]}")
    pt_rows = {}
    for r in rows:
        pt_rows.setdefault(r.get("item_id"), set()).add(tuple(sorted(r.get("slices") or [])))
    split = sorted(i for i, v in pt_rows.items() if len(v) > 1)
    if split:
        problems.append(f"item {split[0]} carries different slice tags on different seeds")

    # 6. Ratchet: on the same eval-set version a threshold may only get stricter.
    if base_spec is not None:
        problems += ratchet(spec, base_spec)
    return problems


def rows_value(rows: list[dict], item: object, seed: object, metric: str) -> object:
    return next((r.get(metric, "<absent>") for r in rows if r.get("item_id") == item and r.get("seed") == seed), None)


def _close(a: object, b: object) -> bool:
    if a is None or b is None:
        return a is b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isfinite(float(a)) and abs(float(a) - float(b)) <= 1e-6
    return a == b


def ratchet(spec: dict, base_spec: dict) -> list[str]:
    """Spec in the PR vs spec on main. Only checked on the same eval-set version: a new version
    starts a new baseline and new thresholds (that is how metric_spec_v2 is allowed to differ)."""
    same_version = spec.get("eval_set_version") == base_spec.get("eval_set_version")
    same_set = spec.get("eval_set") == base_spec.get("eval_set") and spec.get("labels") == base_spec.get("labels")
    if same_version != same_set:
        # Renaming the version over the same items would reset the ratchet for free.
        return [f"RATCHET eval_set_version {base_spec.get('eval_set_version')} -> {spec.get('eval_set_version')} "
                f"but eval set {base_spec.get('eval_set')} -> {spec.get('eval_set')}: they must change together"]
    if not same_version:
        return []   # a genuinely new eval set: new baseline, new thresholds
    out = []
    for key in ("seeds", "bootstrap", "pass_k", "labels", "adversarial_pack"):
        if key in base_spec and spec.get(key) != base_spec.get(key):
            out.append(f"RATCHET {key} changed from {base_spec.get(key)} to {spec.get(key)}")
    out += _ratchet_entries("metric", {m["id"]: m for m in spec.get("metrics") or []},
                            {m["id"]: m for m in base_spec.get("metrics") or []})
    key = lambda s: f"{s.get('name')}/{s.get('metric')}"
    out += _ratchet_entries("slice", {key(s): s for s in spec.get("slices") or []},
                            {key(s): s for s in base_spec.get("slices") or []})
    return out


def _ratchet_entries(kind: str, new: dict[str, dict], old: dict[str, dict]) -> list[str]:
    out = []
    for name, o in old.items():
        n = new.get(name)
        if n is None:
            out.append(f"RATCHET {kind} {name} removed")
            continue
        if o.get("blocking") and not n.get("blocking"):
            out.append(f"RATCHET {kind} {name} no longer blocking")
        for f in ("kind", "level", "grader"):
            if f in o and n.get(f) != o.get(f):
                out.append(f"RATCHET {kind} {name} {f} changed {o.get(f)!r} -> {n.get(f)!r}")
        ot = o.get("threshold", o) if kind == "metric" else o
        nt = n.get("threshold", n) if kind == "metric" else n
        if kind == "metric" and "threshold" in o and "threshold" not in n:
            out.append(f"RATCHET {kind} {name} threshold removed")
            continue
        for f in ("min",):
            if f in ot and (f not in nt or nt[f] < ot[f]):
                out.append(f"RATCHET {kind} {name} {f} lowered {ot[f]} -> {nt.get(f)}")
        for f in ("max", "max_increase"):
            if f in ot and (f not in nt or nt[f] > ot[f]):
                out.append(f"RATCHET {kind} {name} {f} raised {ot[f]} -> {nt.get(f)}")
        if ot.get("no_significant_drop") and not nt.get("no_significant_drop"):
            out.append(f"RATCHET {kind} {name} dropped no_significant_drop")
    return out


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice.
    For each entry of spec["slices"] ({"name", "metric", "min"?, "no_significant_drop"?, "blocking"}):
      - value = mean of per_item(pr, metric, slice_name=name)
      - fail if below "min", or if no_significant_drop and the paired CI over the slice's items
        lies entirely below 0
    Return (blocked ids like "slice:money_movement/pass_rate", report lines)."""
    blocked: list[str] = []
    lines: list[str] = []
    bs = spec.get("bootstrap", {})
    for s in spec.get("slices") or []:
        name, metric = s["name"], s["metric"]
        sid = f"slice:{name}/{metric}"
        a, b = per_item(pr, metric, slice_name=name), per_item(base, metric, slice_name=name)
        verdict, note, val = "ok", "", None
        if not a:
            verdict = "missing"                      # an empty slice cannot vouch for anything
        else:
            val = round(sum(a.values()) / len(a), 4)
            if "min" in s and val < s["min"]:
                verdict = "fail"
            if "max" in s and val > s["max"]:
                verdict = "fail"
            keys = sorted(set(a) & set(b))
            if s.get("no_significant_drop"):
                if not keys:
                    verdict = "missing"
                else:
                    d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                                       n_resamples=bs.get("n_resamples", 1000),
                                                       rng=bs.get("rng", 2027),
                                                       confidence=bs.get("confidence", 0.95))
                    note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
                    if hi < 0:
                        verdict = "fail"
        if verdict != "ok" and s.get("blocking"):
            blocked.append(sid)
        th = {k: s[k] for k in ("min", "max", "no_significant_drop") if k in s}
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if s.get("blocking") else "warn")
        lines.append(f"  {sid:<34} {val!s:<8} n={len(a):<3} {json.dumps(th):<36} {note:<28} {label}")
    return blocked, lines


def check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> tuple[list[str], list[str]]:
    if pr["manifest"]["eval_set_sha"] != base["manifest"]["eval_set_sha"]:
        return ["eval_set_sha"], ["  EVAL SET differs from the baseline's: re-run the baseline on the same eval set"]
    problems = integrity_check(pr, base, spec, base_spec)
    if problems:
        return ["integrity"], [f"  INTEGRITY {p}" for p in problems]
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for m in spec["metrics"]:
        mid, th, val = m["id"], m.get("threshold", {}), pr["metrics"].get(m["id"])
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "max" in th and val > th["max"]:
            verdict = "fail"
        elif "min" in th and val < th["min"]:
            verdict = "fail"
        elif "max_increase" in th and base["metrics"].get(mid):
            if val > base["metrics"][mid] * (1 + th["max_increase"]):
                verdict = "fail"
        if th.get("no_significant_drop") and val is not None:
            a, b = per_item(pr, mid), per_item(base, mid)
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"
        if verdict != "ok" and m.get("blocking"):
            blocked.append(mid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if m.get("blocking") else "warn")
        lines.append(f"  {mid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    if spec.get("slices"):
        sb, sl = slice_check(pr, base, spec)
        blocked += sb
        lines += sl
    return blocked, lines


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.gate")
    ap.add_argument("--pr", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--base-spec", help="metric spec on main, for the ratchet check (M7)")
    args = ap.parse_args(argv)
    pr = json.loads(Path(args.pr).read_text(encoding="utf-8"))
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    base_spec = load_spec(Path(args.base_spec)) if args.base_spec else None
    blocked, lines = check(pr, base, load_spec(Path(args.spec)), base_spec)
    print(f"gate: PR {pr['run_id']} vs main {base['run_id']} · eval set {pr['manifest']['eval_set_sha']}")
    print("\n".join(lines))
    if blocked:
        print(f"exit 1 — blocked: {', '.join(blocked)}")
        return 1
    print("exit 0 — merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""평가 둘.

1) robustness: 시나리오마다 시드 N개로 화물 배치를 바꿔 가며 정책을 비교한다. 한 번의 데모 숫자가 아니라 분포를 보인다.
2) extraction: 실제 LLM으로 만든 report.json의 추출·판단 결과를 정답지와 항목별로 대조한다.

  python eval/run_eval.py robustness --seeds 30
  python eval/run_eval.py extraction out/real/typhoon/report.json
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from clausetower.contracts import list_scenarios, load_customers, load_golden_judgment, load_golden_terms, load_scenario  # noqa: E402
from clausetower.schemas import Report  # noqa: E402
from clausetower.sim import POLICIES, Context, build_shipments, run_policy  # noqa: E402

COMPARE = ["deadline_first", "fifo", "value_first", "exposure_abs", "exposure_first"]


def robustness(seeds: int, out_dir: Path) -> dict:
    customers = load_customers()
    terms = {c.id: load_golden_terms(c.id) for c in customers}
    out_dir.mkdir(parents=True, exist_ok=True)
    summary: dict = {"seeds": seeds, "scenarios": {}}
    lines = [f"# 다중 시드 견고성 평가 (시드 {seeds}개 × 시나리오 {len(list_scenarios())}개)", "",
             "같은 계약·같은 교란에서 화물의 가액·노선·마감만 시드로 바꿔 가며 정책을 비교했다. 숫자는 총 페널티(원).", ""]
    for sid in list_scenarios():
        base_sc = load_scenario(sid)
        judg = {c.id: load_golden_judgment(c.id, sid) for c in customers}
        totals: dict[str, list[int]] = {p: [] for p in COMPARE}
        for seed in range(1, seeds + 1):
            sc = base_sc.model_copy(update={"seed": seed})
            ships = build_shipments(sc, customers)
            ctx = Context(scenario=sc, terms=terms, judgments=judg, customers={c.id: c for c in customers})
            for p in COMPARE:
                totals[p].append(run_policy(sc, ships, ctx, POLICIES[p][1], p, POLICIES[p][0]).total_penalty_krw)
        base = totals["deadline_first"]
        ours = totals["exposure_first"]
        wins = sum(1 for b, o in zip(base, ours) if o < b)
        ties = sum(1 for b, o in zip(base, ours) if o == b)
        savings = [(b - o) / b * 100 for b, o in zip(base, ours) if b > 0]
        row = {p: {"mean": int(statistics.mean(v)), "median": int(statistics.median(v)), "max": max(v), "min": min(v)} for p, v in totals.items()}
        summary["scenarios"][sid] = {"title": base_sc.title, "policies": row, "win_rate": wins / seeds, "ties": ties,
                                     "saving_pct_mean": round(statistics.mean(savings), 1) if savings else 0.0,
                                     "saving_pct_min": round(min(savings), 1) if savings else 0.0,
                                     "saving_pct_max": round(max(savings), 1) if savings else 0.0}
        lines += [f"## {base_sc.title} (`{sid}`)", "", "| 정책 | 평균 | 중앙값 | 최소 | 최대 |", "| --- | ---: | ---: | ---: | ---: |"]
        for p in COMPARE:
            r = row[p]
            lines.append(f"| {POLICIES[p][0]} | {r['mean']:,} | {r['median']:,} | {r['min']:,} | {r['max']:,} |")
        lines += ["", f"- ClauseTower가 기존(마감 순)보다 낮은 시드: {wins}/{seeds} (동률 {ties})",
                  f"- 절감률 평균 {summary['scenarios'][sid]['saving_pct_mean']}%, 최소 {summary['scenarios'][sid]['saving_pct_min']}%, 최대 {summary['scenarios'][sid]['saving_pct_max']}%", ""]
    (out_dir / "robustness.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / "robustness.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    return summary


TERM_FIELDS = ["basis", "rate_pct", "grace_hours", "cap_pct", "cap_amount_krw", "cap_scope", "base", "base_amount_krw", "flat_amount_krw"]


def _fm_fields(t):
    fm = t.force_majeure
    return {"fm_present": fm is not None, "fm_notice_hours": fm.notice_hours if fm else None,
            "fm_conditions": len(fm.conditions) if fm else 0, "fm_events": len(fm.covered_events) if fm else 0}


def extraction(report_path: Path) -> dict:
    r = Report.model_validate_json(Path(report_path).read_text(encoding="utf-8"))
    rows = []
    total = correct = 0
    jtotal = jcorrect = 0
    for cid, ex in r.extraction.items():
        gold = load_golden_terms(cid)
        got = ex.terms
        fields = {f: (getattr(got, f), getattr(gold, f)) for f in TERM_FIELDS}
        gf, gg = _fm_fields(got), _fm_fields(gold)
        fields.update({k: (gf[k], gg[k]) for k in gf})
        if gold.basis == "tiered_per_day":
            fields["tiers"] = ([(t.from_day, t.to_day, t.rate_pct) for t in got.tiers], [(t.from_day, t.to_day, t.rate_pct) for t in gold.tiers])
        if gold.flat_escalation:
            fields["flat_escalation"] = ((got.flat_escalation.after_hours, got.flat_escalation.amount_krw) if got.flat_escalation else None,
                                         (gold.flat_escalation.after_hours, gold.flat_escalation.amount_krw))
        wrong = {k: v for k, v in fields.items() if _ne(v[0], v[1])}
        total += len(fields)
        correct += len(fields) - len(wrong)
        gj = load_golden_judgment(cid, r.scenario.id)
        j = r.judgments[cid]
        jf = {"has_clause": (j.has_clause, gj.has_clause), "event_covered": (j.event_covered, gj.event_covered),
              "notice_ok": (j.notice_ok, gj.notice_ok), "applies": (j.applies, gj.applies)}
        jwrong = {k: v for k, v in jf.items() if v[0] != v[1]}
        jtotal += len(jf)
        jcorrect += len(jf) - len(jwrong)
        cites_ok = all(c.quote.split("…")[0].strip()[:20] in _contract(cid) for c in got.citations.values()) and \
            (not got.force_majeure or got.force_majeure.citation.quote.split("…")[0].strip()[:20] in _contract(cid))
        rows.append({"customer": cid, "fields": len(fields), "wrong": wrong, "judgment_wrong": jwrong, "citations_verbatim": cites_ok,
                     "confidence": ex.confidence, "ambiguities": ex.ambiguities})
    summary = {"report": str(report_path), "scenario": r.scenario.id, "llm_mode": r.llm_mode, "term_field_accuracy": round(correct / total, 3),
               "term_fields": total, "judgment_accuracy": round(jcorrect / jtotal, 3), "judgment_fields": jtotal,
               "applies_accuracy": round(sum(1 for x in rows if "applies" not in x["judgment_wrong"]) / len(rows), 3),
               "citations_verbatim_rate": round(sum(1 for x in rows if x["citations_verbatim"]) / len(rows), 3), "rows": rows}
    print(json.dumps({k: v for k, v in summary.items() if k != "rows"}, ensure_ascii=False, indent=1))
    for x in rows:
        flag = "OK " if not x["wrong"] and not x["judgment_wrong"] else "DIFF"
        print(f"  {flag} {x['customer']}: 조건 오차 {list(x['wrong'].keys()) or '없음'} / 판단 오차 {list(x['judgment_wrong'].keys()) or '없음'}"
              f" / 인용 원문 일치 {'예' if x['citations_verbatim'] else '아니오'} / 확신도 {x['confidence']}")
        for k, (g, e) in x["wrong"].items():
            print(f"       {k}: 모델 {g!r} vs 정답 {e!r}")
        for k, (g, e) in x["judgment_wrong"].items():
            print(f"       {k}: 모델 {g!r} vs 정답 {e!r}")
    return summary


def _ne(a, b) -> bool:
    if isinstance(a, float) or isinstance(b, float):
        try:
            return abs(float(a) - float(b)) > 1e-6
        except (TypeError, ValueError):
            return True
    return a != b


_cache: dict[str, str] = {}


def _contract(cid: str) -> str:
    from clausetower.contracts import load_contract_text
    if cid not in _cache:
        _cache[cid] = load_contract_text(cid)
    return _cache[cid]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p1 = sub.add_parser("robustness")
    p1.add_argument("--seeds", type=int, default=30)
    p1.add_argument("--out", default=str(Path(__file__).parent / "results"))
    p2 = sub.add_parser("extraction")
    p2.add_argument("report")
    p2.add_argument("--save", default=None)
    a = ap.parse_args()
    if a.cmd == "robustness":
        robustness(a.seeds, Path(a.out))
    else:
        s = extraction(Path(a.report))
        if a.save:
            Path(a.save).write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")

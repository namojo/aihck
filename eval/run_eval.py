"""골든셋 대비 측정. 요구사항 재현율·정밀도(id 기준, 본문 요구사항은 인용 겹침 기준), 위험 탐지율, 배점 합.

사용: python eval/run_eval.py out/sample_rfp/report.json [--golden eval/golden] [--record]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("report")
    ap.add_argument("--golden", default=str(ROOT / "eval" / "golden"))
    ap.add_argument("--name", help="골든셋 이름(기본: report 폴더명)")
    ap.add_argument("--record", action="store_true", help="eval/history.jsonl에 기록")
    a = ap.parse_args()

    rep = json.loads(Path(a.report).read_text(encoding="utf-8"))
    name = a.name or Path(a.report).resolve().parent.name
    g_req = json.loads((Path(a.golden) / f"{name}.requirements.json").read_text(encoding="utf-8"))
    g_risk = json.loads((Path(a.golden) / f"{name}.risks.json").read_text(encoding="utf-8"))

    # ---- 요구사항: id가 있는 것은 id로, 본문 요구사항은 인용 겹침(앞 30자)으로 ----
    got_ids = {r["id"] for r in rep["requirements"] if r["source"] == "table"}
    gold_ids = set(g_req["table_ids"])
    tp_ids = got_ids & gold_ids
    got_prose = [norm(r["quote"]) for r in rep["requirements"] if r["source"] == "prose"]
    gold_prose = [norm(q) for q in g_req["prose_quotes"]]
    matched_gold = set()
    matched_got = set()
    for gi, gq in enumerate(gold_prose):
        for pi, pq in enumerate(got_prose):
            if pi in matched_got:
                continue
            if gq[:30] in pq or pq[:30] in gq:
                matched_gold.add(gi)
                matched_got.add(pi)
                break
    tp = len(tp_ids) + len(matched_gold)
    gold_total = len(gold_ids) + len(gold_prose)
    got_total = len(got_ids) + len(got_prose)
    recall = tp / gold_total if gold_total else 0
    precision = tp / got_total if got_total else 0
    missed_ids = sorted(gold_ids - got_ids)
    missed_prose = [g_req["prose_quotes"][i] for i in range(len(gold_prose)) if i not in matched_gold]
    extra_prose = [rep["requirements"][i]["quote"] for i, r in enumerate([r for r in rep["requirements"] if r["source"] == "prose"]) if i not in matched_got] if False else \
        [r["quote"] for pi, r in enumerate([r for r in rep["requirements"] if r["source"] == "prose"]) if pi not in matched_got]
    extra_ids = sorted(got_ids - gold_ids)

    # ---- 위험 ----
    got_rules = {f["rule_id"] for f in rep["risks"]}
    exp_hit = set(g_risk["expected_hit"])
    exp_miss = set(g_risk["expected_miss"])
    risk_recall = len(got_rules & exp_hit) / len(exp_hit) if exp_hit else 0
    false_alarm = sorted(got_rules & exp_miss)
    sev_ok = sum(1 for f in rep["risks"] if g_risk.get("severity", {}).get(f["rule_id"]) in (None, f["severity"]))

    pts_ok = abs(rep["summary"]["scoring_points"] - g_risk.get("scoring_points_total", rep["summary"]["scoring_points"])) < 0.01

    result = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "name": name, "llm_mode": rep["summary"]["llm_mode"],
        "req_recall": round(recall, 3), "req_precision": round(precision, 3), "req_tp": tp, "req_gold": gold_total, "req_got": got_total,
        "risk_recall": round(risk_recall, 3), "risk_false_alarm": false_alarm, "scoring_points_ok": pts_ok,
        "missed_ids": missed_ids, "missed_prose": missed_prose, "extra_ids": extra_ids, "extra_prose": extra_prose,
    }
    hist = ROOT / "eval" / "history.jsonl"
    prev = None
    if hist.exists():
        lines = [json.loads(l) for l in hist.read_text(encoding="utf-8").splitlines() if l.strip()]
        prev = next((l for l in reversed(lines) if l["name"] == name), None)

    def row(k, fmt="{:.3f}"):
        cur = result[k]
        pv = prev[k] if prev and k in prev else None
        return f"{k:<18} {fmt.format(cur) if isinstance(cur, float) else cur!s:<10} 이전 {fmt.format(pv) if isinstance(pv, float) else (pv if pv is not None else '-')}"

    print(f"== {name} ({result['llm_mode']} 모드)" + ("  ※ mock은 프롬프트를 쓰지 않으므로 프롬프트 개선 판단에 쓰지 않는다" if result["llm_mode"] == "mock" else ""))
    for k in ("req_recall", "req_precision", "risk_recall", "scoring_points_ok"):
        print(row(k))
    print(f"요구사항 TP {tp} / 골든 {gold_total} / 추출 {got_total}")
    if missed_ids:
        print("놓친 표 요구사항:", ", ".join(missed_ids))
    if missed_prose:
        print("놓친 본문 요구사항:"); [print("  -", q[:80]) for q in missed_prose]
    if extra_ids or extra_prose:
        print("골든에 없는 추출(정밀도 하락 원인):"); [print("  -", q[:80]) for q in extra_ids + extra_prose]
    if false_alarm:
        print("위험 오탐:", ", ".join(false_alarm))
    missing_rules = sorted(exp_hit - got_rules)
    if missing_rules:
        print("위험 미탐:", ", ".join(missing_rules))
    if a.record:
        with hist.open("a", encoding="utf-8") as f:
            f.write(json.dumps(result, ensure_ascii=False) + "\n")
        print(f"기록: {hist}")
    return 0 if (recall >= 0.9 and risk_recall >= 0.9 and not false_alarm) else 1


if __name__ == "__main__":
    sys.exit(main())

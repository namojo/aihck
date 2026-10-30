"""명령줄: run(시나리오 하나) · demo(전체) · eval(다중 시드 견고성)."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from .agent import run
from .contracts import list_scenarios
from .dashboard import build_dashboard
from .llm import LLM
from .schemas import Report


def _print_summary(r: Report) -> None:
    print(f"\n[{r.scenario.title}] LLM {r.llm_mode}({r.llm_calls}회)")
    for p in r.policies.values():
        mark = " ◀" if p.policy == "exposure_first" else ""
        print(f"  {p.label:<22} {p.total_penalty_krw:>14,}원  지연 {p.late_count:>2}건{mark}")
    print(f"  기존 대비 절감 {r.savings_vs_deadline_krw:,}원 ({r.savings_vs_deadline_pct}%)")
    top = [x for x in r.ranking if abs(x.deadline_rank - x.exposure_rank) >= 3][:3]
    for x in top:
        print(f"  순위 역전: {x.shipment_id} {x.customer_name} 마감 {x.deadline_rank}위 → 노출 {x.exposure_rank}위 "
              f"({x.blocked_by or f'배상 노출액 {x.marginal_krw:,}원'})")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="clausetower")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_run = sub.add_parser("run", help="시나리오 하나 실행")
    p_run.add_argument("scenario", choices=list_scenarios())
    p_run.add_argument("--llm", default=None, help="mock | claude-code | anthropic | auto")
    p_run.add_argument("--out", default="out")
    p_run.add_argument("--no-search", action="store_true")
    p_demo = sub.add_parser("demo", help="전체 시나리오 실행 + 통합 대시보드")
    p_demo.add_argument("--llm", default=None)
    p_demo.add_argument("--out", default="out/demo")
    p_demo.add_argument("--from-reports", default=None, help="이미 만든 report.json들이 있는 폴더로 대시보드만 다시 만든다")
    p_demo.add_argument("--resim", action="store_true", help="--from-reports와 함께: LLM 결과는 두고 시뮬레이션만 다시 돌려 report를 갱신한다")
    p_serve = sub.add_parser("serve", help="웹 데모용 로컬 도우미 서버(구독 CLI·사내 LLM 연결)")
    p_serve.add_argument("--port", type=int, default=8787)
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--llm", default=None, help="mock | claude-code | anthropic | openai | auto")
    p_eval = sub.add_parser("eval", help="다중 시드 견고성 평가")
    p_eval.add_argument("--seeds", type=int, default=30)
    p_eval.add_argument("--out", default="eval/results")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s", stream=sys.stderr)

    if a.cmd == "run":
        llm = LLM(a.llm)
        r = run(a.scenario, llm=llm, with_search=not a.no_search)
        out = Path(a.out) / a.scenario
        out.mkdir(parents=True, exist_ok=True)
        (out / "report.json").write_text(r.model_dump_json(indent=1), encoding="utf-8")
        build_dashboard([r], out / "dashboard.html")
        _print_summary(r)
        print(f"\n산출물: {out / 'report.json'}, {out / 'dashboard.html'}")
        return 0
    if a.cmd == "demo":
        out = Path(a.out)
        out.mkdir(parents=True, exist_ok=True)
        if a.from_reports:
            reports = []
            for p in sorted(Path(a.from_reports).glob("**/report*.json")):
                r = Report.model_validate_json(p.read_text(encoding="utf-8"))
                if a.resim:
                    from .agent import resimulate
                    r = resimulate(r)
                    p.write_text(r.model_dump_json(indent=1), encoding="utf-8")
                    _print_summary(r)
                reports.append(r)
        else:
            llm = LLM(a.llm)
            cache: dict = {}
            reports = []
            for sid in list_scenarios():
                r = run(sid, llm=llm, extraction_cache=cache)
                (out / f"report_{sid}.json").write_text(r.model_dump_json(indent=1), encoding="utf-8")
                _print_summary(r)
                reports.append(r)
        order = {sid: i for i, sid in enumerate(["typhoon", "port_congestion", "wms_outage"])}
        reports.sort(key=lambda r: order.get(r.scenario.id, 99))
        path = build_dashboard(reports, out / "dashboard.html")
        print(f"\n대시보드: {path}")
        return 0
    if a.cmd == "serve":
        from .server import serve

        serve(a.host, a.port, LLM(a.llm))
        return 0
    if a.cmd == "eval":
        from eval.run_eval import robustness  # noqa: WPS433

        robustness(a.seeds, Path(a.out))
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())

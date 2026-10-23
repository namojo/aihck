"""python -m rfpharness <command>"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .llm import LLM
from .pipeline import STAGES, Pipeline, format_summary


def _progress(stage: str, status: str, done: int, total: int) -> None:
    if status in ("done", "reused", "skipped"):
        print(f"  [{stage:<8}] {status}", file=sys.stderr)
    elif total:
        print(f"  [{stage:<8}] {done}/{total}", file=sys.stderr, end="\r")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="rfpharness", description="RFP Compass — 제안요청서 자동 검토")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("review", help="RFP 전체 검토")
    r.add_argument("pdf")
    r.add_argument("--draft", help="제안서 초안(md/docx). 있으면 커버리지 단계 실행")
    r.add_argument("--out", help="출력 폴더 (기본 out/<pdf이름>)")
    r.add_argument("--from", dest="start", default="parse", choices=STAGES)
    r.add_argument("--to", dest="stop", default="export", choices=STAGES)
    r.add_argument("--fresh", action="store_true", help="체크포인트 무시하고 처음부터")
    r.add_argument("--llm", choices=["auto", "claude-code", "anthropic", "mock"], help="RFPHARNESS_LLM 환경변수 대신 지정")
    r.add_argument("--model", help="RFPHARNESS_MODEL 대신 지정")

    p = sub.add_parser("parse", help="파싱 결과만 확인")
    p.add_argument("pdf")
    p.add_argument("--show-tables", action="store_true")

    s = sub.add_parser("serve", help="데모 웹 UI")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8787)
    s.add_argument("--llm", choices=["auto", "claude-code", "anthropic", "mock"])

    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s", stream=sys.stderr)

    if args.cmd == "parse":
        from .parse import parse_pdf, table_to_markdown

        doc = parse_pdf(args.pdf)
        print(f"{doc.meta.title} — {doc.meta.page_count}쪽, 섹션 {len(doc.sections)}, 표 {len(doc.tables)}, needs_ocr={doc.meta.needs_ocr}")
        for sec in doc.sections:
            print(f"  S {sec.section_id} L{sec.level} p.{sec.page_start}-{sec.page_end} {sec.heading} ({len(sec.text)}자, 표 {len(sec.table_ids)})")
        if args.show_tables:
            for t in doc.tables:
                print(f"\n### {t.table_id} p.{t.page} — {t.caption}\n{table_to_markdown(t)}")
        return 0

    if args.cmd == "serve":
        import uvicorn

        from .web.server import create_app

        uvicorn.run(create_app(llm_mode=args.llm), host=args.host, port=args.port)
        return 0

    out = Path(args.out) if args.out else Path("out") / Path(args.pdf).stem
    llm = LLM(mode=args.llm, model=args.model) if (args.llm or args.model) else LLM()
    pipe = Pipeline(args.pdf, out, draft=args.draft, llm=llm, progress=_progress)
    report = pipe.run(start=args.start, stop=args.stop, fresh=args.fresh)
    (out / "run.log").write_text(format_summary(report) + f"\n\nLLM calls: {llm.usage.calls}, tokens in/out: {llm.usage.input_tokens}/{llm.usage.output_tokens}, cost ${llm.usage.cost_usd:.2f}, llm seconds {llm.usage.seconds:.0f}\n", encoding="utf-8")
    print(format_summary(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

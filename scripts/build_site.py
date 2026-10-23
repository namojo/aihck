"""GitHub Pages용 정적 사이트를 site/에 조립한다.

포함: 랜딩 페이지, 기획서(HTML·PDF·스크린샷), 오프라인 대시보드(샘플 RFP 결과), 데모 녹화본.
사용: python scripts/build_site.py [--report out/sample_rfp]
"""
from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
FONT_CSS = '<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.min.css">'


def copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        shutil.copytree(src, dst, dirs_exist_ok=True)
    else:
        shutil.copy2(src, dst)


def with_webfont(html: str) -> str:
    if "pretendard.min.css" in html:
        return html
    return html.replace("<head>", "<head>\n" + FONT_CSS, 1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", default="out/sample_rfp", help="dashboard.html이 있는 결과 폴더")
    a = ap.parse_args()
    if SITE.exists():
        shutil.rmtree(SITE)
    SITE.mkdir()

    # 기획서
    prop = ROOT / "docs" / "proposal"
    (SITE / "proposal").mkdir()
    (SITE / "proposal" / "index.html").write_text(with_webfont((prop / "proposal.html").read_text(encoding="utf-8")), encoding="utf-8")
    copy(prop / "proposal.pdf", SITE / "proposal" / "proposal.pdf")
    copy(prop / "img", SITE / "proposal" / "img")
    copy(prop / "proposal.md", SITE / "proposal" / "proposal.md")

    # 데모 대시보드(오프라인 단일 HTML) + 녹화본
    dash = ROOT / a.report / "dashboard.html"
    (SITE / "demo").mkdir()
    if dash.exists():
        (SITE / "demo" / "index.html").write_text(with_webfont(dash.read_text(encoding="utf-8")), encoding="utf-8")
    for name in ("traceability.xlsx", "toc_draft.docx", "report.json"):
        p = ROOT / a.report / name
        if p.exists():
            copy(p, SITE / "demo" / name)
    video = ROOT / "docs" / "demo" / "demo.webm"
    if video.exists():
        copy(video, SITE / "demo" / "demo.webm")
    copy(ROOT / "samples" / "sample_rfp.pdf", SITE / "demo" / "sample_rfp.pdf")

    # 문서
    (SITE / "docs").mkdir()
    for name in ("SPEC.md", "harness-design.md", "demo-script.md"):
        copy(ROOT / "docs" / name, SITE / "docs" / name)
    copy(ROOT / "README.md", SITE / "docs" / "README.md")

    # 랜딩
    index = (ROOT / "scripts" / "site_index.html").read_text(encoding="utf-8")
    (SITE / "index.html").write_text(with_webfont(index), encoding="utf-8")
    (SITE / ".nojekyll").write_text("", encoding="utf-8")
    print(f"site built: {SITE} ({sum(1 for _ in SITE.rglob('*') if _.is_file())} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

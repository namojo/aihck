"""웹 데모: 사이트가 조립되고, 브라우저 엔진이 파이썬과 같은 숫자를 낸다."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def site():
    subprocess.run([sys.executable, "-m", "clausetower", "demo", "--llm", "mock", "--out", str(ROOT / "out" / "demo")], check=True,
                   capture_output=True, cwd=ROOT, env={**__import__("os").environ, "CLAUSETOWER_LLM": "mock"})
    subprocess.run([sys.executable, str(ROOT / "scripts" / "build_site.py")], check=True, capture_output=True, cwd=ROOT)
    return ROOT / "site"


def test_site_files_and_data(site):
    for f in ("index.html", "data.js", "engine.js", "render.js", "app.js", "style.css", ".nojekyll"):
        assert (site / f).is_file(), f
    data = json.loads((site / "data.js").read_text(encoding="utf-8").split("= ", 1)[1].rstrip(";\n"))
    assert len(data["scenarios"]) == 3 and set(data["scenarios"][0]["shipments_by_seed"]) == set("ABCDE")
    assert "golden" in data["sources"] and "extract" in data["prompts"] and data["schemas"]["judge"]["title"] == "ForceMajeureJudgment"
    html = (site / "index.html").read_text(encoding="utf-8")
    assert "실제 케이스 분석" in html and "AI 연결" in html and "면책 판단" in html
    import re
    for f in ("index.html", "app.js", "data.js"):
        assert not re.search(r"sk-ant-api\w{10,}", (site / f).read_text(encoding="utf-8")), f"{f}에 실제 키가 들어 있으면 안 된다"


@pytest.mark.skipif(shutil.which("node") is None, reason="node 없음")
def test_js_engine_matches_python(site):
    p = subprocess.run(["node", str(ROOT / "scripts" / "verify_engine.js")], capture_output=True, text=True, cwd=ROOT)
    assert p.returncode == 0, p.stdout[-1500:] + p.stderr[-500:]
    assert "DIFF" not in p.stdout


@pytest.mark.skipif(shutil.which("node") is None, reason="node 없음")
def test_js_files_parse(site):
    for f in ("engine.js", "render.js", "app.js"):
        p = subprocess.run(["node", "-e", "new Function(require('fs').readFileSync(0,'utf8'))"], input=(site / f).read_bytes(), capture_output=True)
        assert p.returncode == 0, f + ": " + p.stderr.decode()[:300]

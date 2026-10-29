import json
import shutil
import subprocess
from pathlib import Path

import pytest

from clausetower.agent import resimulate, run
from clausetower.cli import main
from clausetower.dashboard import build_dashboard
from clausetower.llm import LLM
from clausetower.schemas import Report


@pytest.fixture(scope="module")
def report():
    return run("typhoon", llm=LLM("mock"), with_search=False)


def test_dashboard_is_self_contained_and_embeds_data(tmp_path, report):
    out = build_dashboard([report], tmp_path / "d.html")
    html = out.read_text(encoding="utf-8")
    assert "<script src=" not in html and "<link " not in html, "외부 자원 없이 열려야 한다(오프라인 데모)"
    assert report.scenario.title in html and "workbench" not in html
    for row in report.ranking[:3]:
        assert row.shipment_id in html
    if shutil.which("node"):
        js = html.split("<script>")[1].split("</script>")[0]
        p = subprocess.run(["node", "-e", "new Function(require('fs').readFileSync(0,'utf8'))"], input=js.encode(), capture_output=True)
        assert p.returncode == 0, p.stderr.decode()[:300]


def test_resimulate_keeps_llm_results_and_recomputes_policies(report):
    r2 = resimulate(report, with_search=False)
    assert r2.terms == report.terms and r2.judgments == report.judgments
    assert r2.policies["exposure_first"].total_penalty_krw == report.policies["exposure_first"].total_penalty_krw
    assert any("재실행" in l for l in r2.agent_log)


def test_cli_run_and_demo_from_reports(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUSETOWER_LLM", "mock")
    assert main(["run", "wms_outage", "--out", str(tmp_path), "--no-search"]) == 0
    rep = tmp_path / "wms_outage" / "report.json"
    assert rep.is_file() and (tmp_path / "wms_outage" / "dashboard.html").is_file()
    r = Report.model_validate_json(rep.read_text(encoding="utf-8"))
    assert r.savings_vs_deadline_pct > 0
    assert main(["demo", "--from-reports", str(tmp_path), "--out", str(tmp_path / "d2")]) == 0
    assert (tmp_path / "d2" / "dashboard.html").is_file()


def test_eval_extraction_scores_a_mock_report_perfectly(tmp_path, report):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from eval.run_eval import extraction

    p = tmp_path / "report.json"
    p.write_text(report.model_dump_json(), encoding="utf-8")
    s = extraction(p)
    assert s["term_field_accuracy"] == 1.0 and s["judgment_accuracy"] == 1.0 and s["citations_verbatim_rate"] == 1.0


def test_real_run_artifacts_are_recorded():
    """실제 모델 실행 결과를 저장소에 남겨 둔다(재현 불가 시에도 근거가 남도록)."""
    base = Path(__file__).resolve().parents[1] / "eval" / "results"
    for name in ("extraction_typhoon.json", "extraction_port_congestion.json", "robustness.json"):
        assert (base / name).is_file(), name
    ex = json.loads((base / "extraction_typhoon.json").read_text(encoding="utf-8"))
    assert ex["llm_mode"] in ("claude-code", "anthropic") and ex["term_fields"] > 0

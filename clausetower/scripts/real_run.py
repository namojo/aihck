"""실제 Claude(claude-code CLI 또는 SDK)로 시나리오를 돌려 out/real/<시나리오>/report.json에 저장한다.
계약 추출은 한 번만 하고 시나리오 간에 공유한다. 사용: python scripts/real_run.py typhoon port_congestion"""
import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from clausetower.agent import run  # noqa: E402
from clausetower.llm import LLM  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
llm = LLM()
print("LLM mode:", llm.mode, "model:", llm.model, flush=True)
cache: dict = {}
for sid in sys.argv[1:] or ["typhoon"]:
    t0 = time.time()
    r = run(sid, llm=llm, extraction_cache=cache)
    out = Path("out/real") / sid
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(r.model_dump_json(indent=1), encoding="utf-8")
    print(f"[{sid}] {time.time() - t0:.0f}s calls={llm.usage.calls} fallbacks={llm.usage.fallbacks} cost=${llm.usage.cost_usd:.2f} "
          f"savings={r.savings_vs_deadline_pct}%", flush=True)
    for l in r.agent_log:
        print("   ", l, flush=True)
print(json.dumps(llm.usage.__dict__, ensure_ascii=False))

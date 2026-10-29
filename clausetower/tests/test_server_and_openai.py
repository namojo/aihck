"""로컬 도우미 서버와 OpenAI 호환 모드."""
import json
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from clausetower.contracts import load_contract_text, load_golden_terms, load_scenario
from clausetower.llm import LLM
from clausetower.schemas import ExtractionResult, ForceMajeureJudgment
from clausetower.server import make_handler


@pytest.fixture
def helper():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(LLM("mock")))
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def post(url, obj):
    req = urllib.request.Request(url, data=json.dumps(obj, ensure_ascii=False).encode(), headers={"content-type": "application/json", "Origin": "https://namojo.github.io"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status, dict(r.headers), json.loads(r.read().decode())


def test_health_and_cors(helper):
    with urllib.request.urlopen(helper + "/health", timeout=10) as r:
        h, body = dict(r.headers), json.loads(r.read().decode())
    assert body["ok"] and body["mode"] == "mock"
    assert h["Access-Control-Allow-Origin"] == "*" and h["Access-Control-Allow-Private-Network"] == "true"
    req = urllib.request.Request(helper + "/extract", method="OPTIONS", headers={"Origin": "https://namojo.github.io"})
    with urllib.request.urlopen(req, timeout=10) as r:
        assert r.status == 204 and r.headers["Access-Control-Allow-Origin"] == "https://namojo.github.io"


def test_extract_and_judge_roundtrip(helper):
    text = load_contract_text("A")
    status, headers, body = post(helper + "/extract", {"customer_id": "Z", "text": text})
    assert status == 200 and headers["Access-Control-Allow-Origin"] == "https://namojo.github.io"
    ex = ExtractionResult.model_validate(body)
    assert ex.terms.customer_id == "Z" and ex.confidence == 0.0 and "mock" in ex.ambiguities[0]  # 임의 본문은 자리표시자
    ev = load_scenario("typhoon").event
    status, _, body = post(helper + "/judge", {"customer_id": "Z", "terms": json.loads(load_golden_terms("A").model_dump_json()),
                                                "event": json.loads(ev.model_dump_json()), "text": text})
    j = ForceMajeureJudgment.model_validate(body)
    assert status == 200 and j.has_clause and j.applies is False


def test_bad_requests(helper):
    with pytest.raises(urllib.error.HTTPError) as ei:
        post(helper + "/extract", {"customer_id": "Z", "text": "짧다"})
    assert ei.value.code == 400
    with pytest.raises(urllib.error.HTTPError) as ei:
        post(helper + "/nope", {})
    assert ei.value.code == 404


class FakeOpenAI(BaseHTTPRequestHandler):
    """OpenAI 호환 chat/completions 흉내. 도구 호출로 정답지 조건을 돌려준다."""
    seen: list = []

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])).decode())
        FakeOpenAI.seen.append((self.path, self.headers.get("authorization"), body["tool_choice"]))
        args = {"terms": json.loads(load_golden_terms("B").model_dump_json()), "confidence": 0.8, "ambiguities": []}
        resp = {"choices": [{"message": {"tool_calls": [{"function": {"name": "submit", "arguments": json.dumps(args, ensure_ascii=False)}}]}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5}}
        out = json.dumps(resp).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)


def test_openai_compatible_mode(monkeypatch):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), FakeOpenAI)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        monkeypatch.setenv("CLAUSETOWER_OPENAI_BASE_URL", f"http://127.0.0.1:{srv.server_address[1]}/v1")
        monkeypatch.setenv("CLAUSETOWER_OPENAI_API_KEY", "inhouse-token")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        llm = LLM("auto")
        assert llm.mode == "openai", "BASE_URL이 있으면 auto는 openai를 고른다(키 없을 때)"
        from clausetower.extract import extract_terms_from_text
        r = extract_terms_from_text(llm, "B", load_contract_text("B"))
        assert r.terms.basis == "per_hour" and r.confidence == 0.8 and llm.usage.calls == 1 and llm.usage.fallbacks == 0
        path, auth, choice = FakeOpenAI.seen[-1]
        assert path == "/v1/chat/completions" and auth == "Bearer inhouse-token" and choice["function"]["name"] == "submit"
    finally:
        srv.shutdown()


def test_openai_mode_falls_back_when_unreachable(monkeypatch):
    monkeypatch.setenv("CLAUSETOWER_OPENAI_BASE_URL", "http://127.0.0.1:9/v1")
    monkeypatch.setenv("CLAUSETOWER_CLAUDE_TIMEOUT", "2")
    llm = LLM("openai")
    from clausetower.extract import extract_terms_from_text
    r = extract_terms_from_text(llm, "Q", "x" * 100)
    assert llm.usage.fallbacks == 1 and r.confidence == 0.0

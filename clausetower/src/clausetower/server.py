"""로컬 도우미 서버. 웹 데모(GitHub Pages)가 이 PC의 LLM 연결로 계약을 읽게 해 준다.

  python -m clausetower serve --port 8787 --llm claude-code     # Claude 구독(CLI)
  CLAUSETOWER_OPENAI_BASE_URL=https://사내게이트웨이/v1 python -m clausetower serve --llm openai   # 사내 LLM

엔드포인트(모두 JSON, CORS 허용):
  GET  /health                  {ok, mode, model}
  POST /extract {customer_id, text}                      → ExtractionResult
  POST /judge   {customer_id, terms, event, text}        → ForceMajeureJudgment
브라우저의 Private Network Access 사전 요청에 응답하도록 Access-Control-Allow-Private-Network 헤더를 붙인다.
계약서 본문은 메모리에서만 다루고 디스크에 쓰지 않는다. 요청 로그에는 길이만 남긴다.
"""

from __future__ import annotations

import json
import logging
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .extract import extract_terms_from_text, judge_from_text
from .llm import LLM
from .schemas import EventContext, PenaltyTerms

log = logging.getLogger("clausetower.server")
MAX_BODY = 2 * 1024 * 1024


def make_handler(llm: LLM):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # 본문 내용이 로그에 남지 않게 한다
            log.info("%s %s", self.command, self.path)

        def _cors(self):
            origin = self.headers.get("Origin") or "*"
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "content-type")
            self.send_header("Access-Control-Allow-Private-Network", "true")
            self.send_header("Access-Control-Max-Age", "600")

        def _send(self, code: int, obj) -> None:
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self._cors()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self):
            self.send_response(204)
            self._cors()
            self.end_headers()

        def do_GET(self):
            if self.path.split("?")[0] == "/health":
                return self._send(200, {"ok": True, "mode": llm.mode, "model": llm.model, "calls": llm.usage.calls, "fallbacks": llm.usage.fallbacks})
            self._send(404, {"error": "없는 경로"})

        def do_POST(self):
            path = self.path.split("?")[0]
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > MAX_BODY:
                    return self._send(413 if length > MAX_BODY else 411, {"error": "본문 길이가 올바르지 않다"})
                req = json.loads(self.rfile.read(length).decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                return self._send(400, {"error": "JSON 해석 실패"})
            try:
                if path == "/extract":
                    cid = str(req.get("customer_id") or "X")
                    text = str(req.get("text") or "")
                    if len(text) < 40:
                        return self._send(400, {"error": "계약서 본문이 너무 짧다"})
                    r = extract_terms_from_text(llm, cid, text)
                    return self._send(200, json.loads(r.model_dump_json()))
                if path == "/judge":
                    cid = str(req.get("customer_id") or "X")
                    terms = PenaltyTerms.model_validate(req["terms"])
                    event = EventContext.model_validate(req["event"])
                    r = judge_from_text(llm, cid, terms, event, str(req.get("text") or ""))
                    return self._send(200, json.loads(r.model_dump_json()))
                return self._send(404, {"error": "없는 경로"})
            except Exception as e:  # noqa: BLE001
                log.exception("요청 처리 실패")
                return self._send(500, {"error": f"{type(e).__name__}: {str(e)[:200]}"})

    return Handler


def serve(host: str = "127.0.0.1", port: int = 8787, llm: LLM | None = None) -> None:
    llm = llm or LLM()
    httpd = ThreadingHTTPServer((host, port), make_handler(llm))
    httpd.daemon_threads = True
    print(f"ClauseTower 로컬 도우미: http://{host}:{port}  (LLM 모드 {llm.mode}, 모델 {llm.model}). 웹 데모의 '로컬 도우미'에 이 주소를 넣는다.", flush=True)
    if llm.mode == "mock":
        print("주의: mock 모드다. 실제 분석이 아니라 자리표시자 결과가 나온다. --llm claude-code 또는 환경변수를 확인하라.", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    serve()

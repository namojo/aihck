"""모든 LLM 호출의 단일 출입구.

모드(RFPHARNESS_LLM):
- claude-code : Claude Code CLI(`claude -p --json-schema`)를 서브프로세스로 호출한다. API 키 없이 Claude 구독(Pro/Max/Enterprise)으로 돈다.
- anthropic   : Anthropic SDK `messages.parse`. ANTHROPIC_API_KEY 또는 `ant auth login` 프로필이 필요하다.
- mock        : 각 단계가 넘긴 결정적 함수(mock_fn)를 호출한다. 테스트와 오프라인 데모용.
- auto(기본)  : ANTHROPIC_API_KEY가 있으면 anthropic, `claude` CLI가 있으면 claude-code, 둘 다 없으면 mock.

구조화 출력은 pydantic 스키마로 검증하고 실패 시 1회 재시도한다.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, TypeVar

from pydantic import BaseModel, ValidationError

log = logging.getLogger("rfpharness.llm")
T = TypeVar("T", bound=BaseModel)

DEFAULT_MODEL = os.environ.get("RFPHARNESS_MODEL", "claude-opus-5-5")
PROMPT_DIR = Path(__file__).parent / "prompts"
CLAUDE_BIN = os.environ.get("RFPHARNESS_CLAUDE_BIN", "claude")
CLAUDE_TIMEOUT = int(os.environ.get("RFPHARNESS_CLAUDE_TIMEOUT", "600"))
# claude-code 모드에서 모델이 도구를 쓰지 못하게 막는다. 우리는 텍스트 → JSON만 원한다.
CLAUDE_DISALLOWED_TOOLS = "Bash,Read,Edit,Write,MultiEdit,Glob,Grep,WebSearch,WebFetch,Agent,Task,NotebookEdit,TodoWrite,Skill"


def resolve_mode(mode: str | None) -> str:
    m = (mode or os.environ.get("RFPHARNESS_LLM") or "auto").lower()
    if m != "auto":
        return m
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return "anthropic"
    if shutil.which(CLAUDE_BIN):
        return "claude-code"
    return "mock"


def load_prompt(name: str) -> str:
    return (PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8")


@dataclass
class Usage:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    seconds: float = 0.0
    cost_usd: float = 0.0
    by_stage: dict[str, int] = field(default_factory=dict)


class LLM:
    def __init__(self, mode: str | None = None, model: str = DEFAULT_MODEL):
        self.mode = resolve_mode(mode)
        self.model = model
        self.usage = Usage()
        self._client = None
        self.concurrency = 1 if self.mode == "mock" else int(os.environ.get("RFPHARNESS_CONCURRENCY", "4"))
        if self.mode == "claude-code" and not shutil.which(CLAUDE_BIN):
            log.warning("claude CLI(%s)를 찾지 못했다. mock 모드로 전환한다.", CLAUDE_BIN)
            self.mode = "mock"
        if self.mode == "anthropic":
            try:
                import anthropic

                self._client = anthropic.Anthropic()
                # 인증 정보가 전혀 없으면 첫 호출에서 TypeError가 난다. 미리 확인한다.
                if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
                    # ant auth login 프로필이 있을 수도 있으므로 클라이언트 생성 자체는 허용하되 경고만 남긴다.
                    log.warning("ANTHROPIC_API_KEY가 없다. ant auth 프로필이 없으면 첫 호출에서 실패하고 mock으로 전환한다.")
            except Exception as e:  # noqa: BLE001
                log.warning("anthropic 클라이언트 생성 실패(%s). mock 모드로 전환한다.", e)
                self.mode = "mock"

    # ------------------------------------------------------------------
    def parse(
        self,
        *,
        stage: str,
        system: str,
        user: str,
        schema: type[T],
        mock_fn: Callable[[], T],
        max_tokens: int = 16000,
    ) -> T:
        """구조화 출력 호출. mock 모드면 mock_fn() 결과를 돌려준다."""
        if self.mode == "mock":
            return mock_fn()
        if self.mode == "claude-code":
            return self._parse_claude_code(stage=stage, system=system, user=user, schema=schema, mock_fn=mock_fn)
        t0 = time.time()
        last_err: Exception | None = None
        for attempt in range(2):
            try:
                resp = self._client.messages.parse(
                    model=self.model,
                    max_tokens=max_tokens,
                    system=system,
                    messages=[{"role": "user", "content": user}],
                    output_format=schema,
                )
                self.usage.calls += 1
                self.usage.input_tokens += getattr(resp.usage, "input_tokens", 0) or 0
                self.usage.output_tokens += getattr(resp.usage, "output_tokens", 0) or 0
                self.usage.by_stage[stage] = self.usage.by_stage.get(stage, 0) + 1
                self.usage.seconds += time.time() - t0
                if resp.stop_reason == "refusal":
                    raise RuntimeError(f"모델이 응답을 거부했다: {getattr(resp, 'stop_details', None)}")
                parsed = resp.parsed_output
                if parsed is None:
                    raise ValueError("parsed_output이 비어 있다")
                return parsed
            except ValidationError as e:
                last_err = e
                log.warning("[%s] 구조화 출력 검증 실패(시도 %d): %s", stage, attempt + 1, str(e)[:300])
            except TypeError as e:
                # 인증 정보 없음
                log.error("[%s] Anthropic 인증 실패(%s). 이 호출은 mock으로 대체한다.", stage, e)
                self.mode = "mock"
                return mock_fn()
            except Exception as e:  # noqa: BLE001
                import anthropic

                if isinstance(e, (anthropic.AuthenticationError, anthropic.PermissionDeniedError)):
                    log.error("[%s] Anthropic 인증 오류(%s). mock으로 대체한다.", stage, e)
                    self.mode = "mock"
                    return mock_fn()
                if isinstance(e, anthropic.RateLimitError) and attempt == 0:
                    wait = int(e.response.headers.get("retry-after", "20"))
                    log.warning("[%s] 속도 제한. %ds 후 재시도", stage, wait)
                    time.sleep(min(wait, 60))
                    last_err = e
                    continue
                raise
        raise RuntimeError(f"[{stage}] LLM 호출 실패: {last_err}")

    # ------------------------------------------------------------------
    def _parse_claude_code(self, *, stage: str, system: str, user: str, schema: type[T], mock_fn: Callable[[], T]) -> T:
        """`claude -p --json-schema`로 구조화 출력을 받는다. 프롬프트는 stdin으로 넘긴다."""
        json_schema = schema.model_json_schema()
        cmd = [
            CLAUDE_BIN, "-p", "--output-format", "json", "--model", self.model,
            "--system-prompt", system, "--json-schema", json.dumps(json_schema, ensure_ascii=False),
            "--no-session-persistence", "--disallowedTools", CLAUDE_DISALLOWED_TOOLS,
        ]
        env = {k: v for k, v in os.environ.items() if k not in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")}
        last_err: Exception | None = None
        for attempt in range(2):
            t0 = time.time()
            try:
                with tempfile.TemporaryDirectory() as cwd:  # 프로젝트 CLAUDE.md를 읽지 않도록 빈 디렉터리에서 실행
                    proc = subprocess.run(cmd, input=user, capture_output=True, text=True, timeout=CLAUDE_TIMEOUT, cwd=cwd, env=env)
                self.usage.seconds += time.time() - t0
                if proc.returncode != 0:
                    raise RuntimeError(f"claude 종료 코드 {proc.returncode}: {proc.stderr.strip()[:300] or proc.stdout.strip()[:300]}")
                data = json.loads(proc.stdout)
                self.usage.calls += 1
                self.usage.by_stage[stage] = self.usage.by_stage.get(stage, 0) + 1
                u = data.get("usage") or {}
                self.usage.input_tokens += int(u.get("input_tokens", 0) or 0) + int(u.get("cache_creation_input_tokens", 0) or 0) + int(u.get("cache_read_input_tokens", 0) or 0)
                self.usage.output_tokens += int(u.get("output_tokens", 0) or 0)
                self.usage.cost_usd += float(data.get("total_cost_usd", 0) or 0)
                if data.get("is_error"):
                    raise RuntimeError(f"claude 오류: {str(data.get('result'))[:300]}")
                payload = data.get("structured_output")
                if payload is None:
                    payload = json.loads(data.get("result") or "null")
                if payload is None:
                    raise ValueError("structured_output이 비어 있다")
                return schema.model_validate(payload)
            except subprocess.TimeoutExpired as e:
                last_err = e
                log.warning("[%s] claude 호출 시간 초과(%ds), 시도 %d", stage, CLAUDE_TIMEOUT, attempt + 1)
            except (ValidationError, ValueError, RuntimeError) as e:
                last_err = e
                log.warning("[%s] claude-code 응답 처리 실패(시도 %d): %s", stage, attempt + 1, str(e)[:300])
        log.error("[%s] claude-code 호출 실패, 이 호출은 mock으로 대체한다: %s", stage, last_err)
        return mock_fn()

    # ------------------------------------------------------------------
    def map(self, fn: Callable, items: list) -> list:
        """items 각각에 fn을 적용한다. mock은 순차, 그 외는 스레드 풀(RFPHARNESS_CONCURRENCY, 기본 4)."""
        if self.concurrency <= 1 or len(items) <= 1:
            return [fn(x) for x in items]
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=self.concurrency) as ex:
            return list(ex.map(fn, items))

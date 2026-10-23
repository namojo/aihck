"""모든 LLM 호출의 단일 출입구.

- 모드: RFPHARNESS_LLM=anthropic | mock (기본 anthropic, 인증 정보가 없으면 mock으로 내려가며 경고)
- 구조화 출력: pydantic 스키마를 messages.parse에 넘긴다. 검증 실패 시 1회 재시도.
- mock: 각 단계가 넘긴 결정적 함수(mock_fn)를 호출한다. 테스트와 오프라인 데모용.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, TypeVar

from pydantic import BaseModel, ValidationError

log = logging.getLogger("rfpharness.llm")
T = TypeVar("T", bound=BaseModel)

DEFAULT_MODEL = os.environ.get("RFPHARNESS_MODEL", "claude-opus-5-5")
PROMPT_DIR = Path(__file__).parent / "prompts"


def load_prompt(name: str) -> str:
    return (PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8")


@dataclass
class Usage:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    seconds: float = 0.0
    by_stage: dict[str, int] = field(default_factory=dict)


class LLM:
    def __init__(self, mode: str | None = None, model: str = DEFAULT_MODEL):
        self.mode = (mode or os.environ.get("RFPHARNESS_LLM") or "anthropic").lower()
        self.model = model
        self.usage = Usage()
        self._client = None
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
        if self.mode != "anthropic":
            return mock_fn()
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

# 실제 모델 실행 보고서

- `report_*.json`: `claude-code` 모드(claude-opus-5-5)로 계약서 8부를 읽고 두 시나리오의 면책을 판단한 보고서. 2회차(추출 프롬프트의 "지연 페널티 조건"을 "지연 배상 조건"으로 고친 뒤 실행).
- `run.log`: 실행 로그. 호출 24회(추출 8 + 판단 16), 대체 0회, CLI 보고 비용 $2.06, 호출 시간 합계 283초(4개 병렬).
- 채점: `python eval/run_eval.py extraction eval/results/real/report_typhoon.json` → `../extraction_*.json`.
- 1회차(프롬프트 수정 전) 보고서와 채점은 `../real_prev/`에 그대로 두었다.

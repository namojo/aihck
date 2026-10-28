# 작업구역(workbench)

NASCA DRM으로 보호된 문서를 AI가 읽고 고칠 때, 문서를 **한 번만 복호화해 격리된 작업구역 안에 두고**
거기서 읽기·수정을 반복한 뒤 **한 번만 다시 보호해 내보내는** MCP 서버다. Claude Code 플러그인으로 설치하고, Codex 같은 다른 MCP 클라이언트에도 붙는다.

## 왜 필요한가

NASCA는 PC 트레이의 에이전트가 문서를 열 때 복호화하고, 문서 앱이 그 평문을 연다. 그래서 AI는 평문에 닿으려면 앱을 COM으로 긁거나 화면을 캡처해야 한다.
COM은 호출마다 프로세스 간 왕복이 일어나 느리고, 앱이 편집 중이거나 대화상자가 떠 있으면 멈춘다. 캡처는 이미지 토큰이 많이 들고 글자가 깨진다.
수정할 때마다 복호화, 수정, 암호화를 되풀이하는 것도 시간을 쓴다.

작업구역은 이 흐름을 바꾼다.

| | 지금 | 작업구역 |
| --- | --- | --- |
| 문서 접근 | 앱을 COM으로 조작, 화면 캡처 | 평문 파일을 라이브러리로 직접 읽고 씀(앱 불필요) |
| 암복호화 | 수정마다 1회씩 | 열 때 1회, 내보낼 때 1회 |
| 이미지 | 그림판 복호화 후 캡처 | 파일을 그대로 비전에 전달, 영역 확대 가능 |
| 평문 위치 | PC 곳곳(앱 메모리, 임시 파일) | 세션 하나의 격리 환경 안, 종료하면 삭제 |

## 구조

```
 AI 클라이언트 (Claude Code / Codex)
   │  MCP: workbench_open / read / edit / view_image / export / close
   ▼
 ┌─ 호스트 ────────────────────────────────────────────────────┐
 │ 중개 계층(broker)  세션·만료·감사 로그·열기/내보내기 폴더 제한      │
 │   ├─ NASCA 어댑터 ── 사내 NASCA MCP (복호화·재보호, AI에게는 비공개) │
 │   └─ 백엔드 ── Windows Sandbox 시작/종료                        │
 └──────────────┬──────────────────────────────────────────────┘
                │ 토큰 인증 HTTP (Hyper-V 가상 스위치, 호스트 디스크 미경유)
 ┌─ 격리 환경(Windows Sandbox) ──────────────────────────────────┐
 │ 에이전트  python-docx / openpyxl / python-pptx / pillow         │
 │ 평문 파일은 여기에만. 아웃바운드 방화벽 차단, 클립보드 차단.         │
 │ 중개 계층 연락이 끊기면 스스로 지우고 VM을 끈다.                   │
 └──────────────────────────────────────────────────────────────┘
```

AI가 보는 문은 `workbench_*` 도구뿐이다. 원본 NASCA MCP는 AI에게 노출하지 않고 중개 계층만 호출한다.
평문이 밖으로 나가는 길은 `workbench_export` 하나이고, 항상 재보호된다.

## 도구

| 도구 | 하는 일 |
| --- | --- |
| `workbench_open` | 복호화해 작업구역에 넣고 구조(outline)를 돌려준다. 첫 호출이 세션을 시작한다 |
| `workbench_outline`, `workbench_read` | 구조만 보기, 구간만 읽기. 결과는 텍스트이고 쪽 나눔 안내가 붙는다 |
| `workbench_view_image`, `workbench_extract_media` | 이미지를 비전으로 보기(영역 확대 가능), 문서 안의 그림 꺼내기 |
| `workbench_edit`, `workbench_create`, `workbench_undo`, `workbench_delete` | 수정(전부 적용 또는 전부 취소), 새 문서, 되돌리기, 지우기 |
| `workbench_export` | DRM으로 재보호해 호스트 폴더에 저장 |
| `workbench_close`, `workbench_status`, `workbench_list` | 닫기(평문 삭제), 상태와 규칙, 목록 |

지원 형식은 docx, xlsx, pptx, 이미지(png, jpg, gif, bmp, webp, tiff), 텍스트(UTF-8, CP949)다. 그 밖의 형식은 열고 내보내는 것만 된다.

## 빠른 시작(개발, 모의 NASCA)

```bash
cd workbench
uv venv .venv && . .venv/bin/activate && uv pip install -e ".[dev]"
pytest -q                          # 120개
python scripts/demo_cycles.py      # 암복호화 횟수 비교(8회 → 1회)
python -m workbench.doctor --selftest
claude --plugin-dir .              # 플러그인 시험(저장소 안의 workbench 폴더에서)
```

모의 NASCA는 보안 기능이 없다. 보호 파일을 흉내 내는 용도다. `python -m workbench.nasca.mock protect SRC DST`로 시험 문서를 만든다.

## 운영(Windows)

1. Windows 기능 "Windows 샌드박스"를 켠다(Pro, Enterprise, Education). 호스트당 샌드박스는 하나만 실행되므로 세션도 하나다.
2. `powershell -ExecutionPolicy Bypass -File runtime\build_runtime.ps1`로 읽기 전용 런타임을 만든다. 사내 PyPI 미러는 `-PipIndex`.
3. NASCA MCP 설정 파일을 쓰고 `python -m workbench.doctor --probe-nasca`로 도구 이름과 인자를 맞춘다. 형식은 `src/workbench/nasca/mcp_bridge.py` 머리말에 있다.
4. `python -m workbench.doctor --selftest`로 샌드박스가 실제로 뜨고 문서를 읽는지 확인한다.
5. 보안 값(열기·내보내기 폴더, 백엔드, NASCA 어댑터)은 `%ProgramData%\workbench\config.json`에 둔다. 이 파일의 값은 사용자와 환경변수가 바꿀 수 없다.

자세한 순서와 막힐 때의 확인 지점은 [docs/windows-first-run.md](docs/windows-first-run.md).

## 설치

- **Claude Code 플러그인**: 이 폴더가 플러그인 루트다. 시험은 `claude --plugin-dir .`, 사내 배포는 저장소 루트의 `.claude-plugin/marketplace.json`으로 한다. MCP 서버, 직접 접근 차단 훅, 사용 지침(skill)이 함께 들어온다.
  플러그인 MCP 도구 이름은 `mcp__plugin_workbench_workbench__workbench_open` 형식이다.
- **Codex**: `enforcement/codex/config.toml.example`를 `~/.codex/config.toml`에 합친다. 첫 `workbench_open`에 샌드박스 기동 시간이 들어가므로 `tool_timeout_sec`를 넉넉히 둔다.
- **그 밖의 MCP 클라이언트**: `python -m workbench.mcp_server`를 stdio로 등록한다. `PYTHONPATH`에 `src`를 넣는다.

AI가 이 경로만 쓰게 강제하는 방법은 [docs/enforcement.md](docs/enforcement.md).

## 검증한 것과 못 한 것

확인했다.
- 자동 시험 120개가 리눅스에서 통과한다. MCP 서버와 NASCA 어댑터는 mcp 2.3과 1.30 양쪽에서 시험했다.
- Claude Code 2.1.312에 플러그인을 켜고 실제 모델로 돌렸다. 열기, 읽기, 수정, 재확인, 내보내기, 닫기가 도구 8턴으로 끝났고, 내보낸 파일은 보호 형식이며 작업 루트는 남지 않았다.
- 같은 환경에서 보호 폴더에 대한 Read, Bash, Grep, Glob이 훅에 막혔고 차단 사유가 모델에게 전달됐다. 보호되지 않은 파일은 읽혔다.
- 감사 로그의 해시 체인이 유효하고, 로그에 문서 내용이 없다.

확인하지 못했다. 이 환경이 리눅스라 돌려 볼 수 없었다.
- **Windows Sandbox 백엔드**: `.wsb` 생성, 게스트 방화벽 스크립트, 런타임 빌드 스크립트는 구조와 문법만 시험했다. 실제 기동은 첫 실행에서 확인해야 한다.
- **실제 NASCA 연동**: 사내 NASCA MCP의 도구 이름과 응답 모양을 몰라 어댑터를 설정 파일로 열어 두었다. 모의 서버로만 시험했다.
- **Codex 연결**과 관리형 설정 키의 실제 동작, Windows 드라이브 경로를 쓰는 deny 규칙 표기.
- 실제 NASCA 환경에서 샌드박스 안의 평문 파일이 정책에 걸리지 않는지(샌드박스에는 NASCA 에이전트가 없다는 전제).

## 한계

- 로컬 백엔드는 격리가 없는 개발용이다. 운영은 winsandbox다.
- 한글(HWP)과 PDF는 읽지 않는다. xlsx와 pptx는 라이브러리로 다시 저장하므로 차트나 그림이 유실될 수 있고, 그럴 때 경고가 나온다.
- 문서 내용은 모델 컨텍스트로 전송된다. 승인된 사내 모델 엔드포인트만 쓰도록 클라이언트를 구성해야 한다. 이 도구가 대신 보장하지 않는다.
- 훅은 안전장치이지 보안 경계가 아니다. 경계는 격리 환경과 NASCA 정책이 맡는다.

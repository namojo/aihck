# AI가 작업구역만 쓰게 하는 방법

말로 시키는 것은 부탁이고, 막는 것은 강제다. 둘을 층으로 겹친다. 위 층이 뚫려도 아래 층이 남게 한다.

| 층 | 무엇을 하나 | 강제인가 | 어디서 |
| --- | --- | --- | --- |
| 1. 도구 표면 축소 | 원본 NASCA MCP를 AI 클라이언트에 등록하지 않고 중개 계층만 호출하게 한다 | 강제 | MCP 설정, `deniedMcpServers` |
| 2. 작업구역 격리 | 평문이 격리 VM 안에만 있고 나가는 길이 export 하나다 | 강제 | 백엔드, 방화벽 |
| 3. 접근 통제 훅 | 보호 폴더로 가는 Read, Edit, Write, Grep, Glob, Bash와 원본 NASCA MCP 호출을 막는다 | 안전장치 | `enforcement/hooks/guard.py` |
| 4. deny 규칙 | 보호 폴더 Read, Edit를 권한 규칙으로 막는다 | 강제(Grep, Glob은 최선) | `settings.json` |
| 5. 지침 | 서버 지침, 도구 설명, 결과 끝의 상태 줄, 세션 시작 컨텍스트, skill | 안내 | MCP 서버, 훅, 플러그인 |
| 6. 관리형 배포 | 위 설정을 사용자가 끄지 못하게 IT가 배포한다 | 강제 | managed-settings.json |

## 정책 파일

훅과 세션 시작 문구는 `policy.json`을 읽는다. 위치는 `WORKBENCH_POLICY`, 기계 전체(`%ProgramData%\workbench\policy.json`, 리눅스는 `/etc/workbench/policy.json`), 사용자(`%LOCALAPPDATA%\workbench\policy.json`) 순이고, 찾은 파일의 목록을 합친다.
파일이 하나도 없으면 아무것도 막지 않는다. 파일이 있는데 읽을 수 없으면 파일, 셸, MCP 접근을 막는다.

```json
{ "protected_roots": ["D:/NASCA/보안문서"], "blocked_mcp_servers": ["nasca"] }
```

`enforcement/policy.example.json`을 복사해 쓴다.

## 훅이 막는 것과 못 막는 것

막는다. 드라이브 표기, 역슬래시, 대소문자, `..`, WSL(`/mnt/d`)과 MSYS(`/d`) 표기, 홈 약칭(`~`, `$HOME`, `%USERPROFILE%`)을 같은 경로로 본다. 보호 폴더를 품은 상위 폴더 전체를 검색하는 것도 막는다. 플러그인으로 들어온 MCP(`mcp__plugin_*_nasca__*`)도 막는다.

못 막는다.
- 셸 명령은 문자열 검사다. 변수 조립(`$a$b`), 다른 폴더에서 `cd` 후 상대 경로, 심볼릭 링크 생성 같은 간접 방법은 피해 갈 수 있다.
- 훅이 없는 클라이언트(Codex 등)에서는 동작하지 않는다.

그래서 훅만 믿지 않는다. 층 1, 2, 4, 6을 함께 쓰고, 근본적으로는 AI 프로세스가 보호 폴더를 읽을 수 없는 OS 권한이나 NASCA 프로세스 정책이 경계가 되어야 한다.

## Claude Code

개인이나 팀은 플러그인을 켠다. 훅과 MCP 서버와 지침이 한 번에 들어온다.

```bash
claude --plugin-dir ./workbench                         # 시험
claude plugin marketplace add namojo/aihck               # 사내 배포(저장소 루트의 marketplace.json)
claude plugin install workbench@internal-tools
```

IT 배포는 `enforcement/claude-code/managed-settings.example.json`을 `C:\Program Files\ClaudeCode\managed-settings.json`에 둔다. 담긴 것은 다음과 같다.
- `permissions.deny`: 보호 폴더 Read와 Edit
- `deniedMcpServers`: 원본 NASCA MCP
- `allowManagedPermissionRulesOnly`, `allowManagedHooksOnly`: 사용자 설정이 규칙과 훅을 바꾸지 못하게 함
- `permissions.disableBypassPermissionsMode`: 권한 우회 모드 끄기
- `enabledPlugins`: 작업구역 플러그인 강제 활성화. 이렇게 켠 플러그인의 훅은 `allowManagedHooksOnly`에서도 돈다.

배포한 뒤 `/status`와 `claude doctor`로 적용 여부를 본다. 잘못된 항목은 조용히 무시될 수 있다.
관리형 `allowManagedMcpServersOnly`가 플러그인이 주는 MCP 서버에도 적용되는지는 문서에서 확인하지 못했으니 켜기 전에 시험한다.

설정 파일 경로와 키 이름은 Claude Code 문서를 따랐고, Windows 드라이브 경로를 쓰는 deny 규칙 표기(`Read(//D:/...)`)는 문서에 예시가 없어 확인하지 못했다. 적용 후 막히는지 직접 확인한다.

## Codex

Codex에서 PreToolUse 같은 훅 설정은 확인하지 못했다. 그래서 다음에 기댄다.
- `enforcement/codex/config.toml.example`로 작업구역 서버를 등록하고 원본 NASCA MCP는 `enabled = false`로 둔다.
- `workbench_export`는 `approval_mode = "prompt"`로 사람이 승인하게 한다.
- 보호 폴더 읽기 차단은 OS 권한이나 NASCA 정책에서 한다.

## 확인 방법

훅이 실제로 막는지는 정책을 만들고 플러그인을 켜서 헤드리스로 돌려 본다.

```bash
WORKBENCH_POLICY=/path/policy.json claude -p "보호 폴더의 a.txt를 Read로 읽어 줘" \
  --plugin-dir ./workbench --allowedTools "Read" --output-format json < /dev/null
```

이 저장소에서는 Read, Bash, Grep, Glob이 모두 `PreToolUse ... hook error: ... DRM 보호 폴더라서 ...` 메시지로 막히고 모델이 `workbench_open`을 제안하는 것을 확인했다.
참고로 모델에게 "차단 경로를 차례로 찔러 보라"고 시키면 모델 쪽에서 거절한다. 차단 시험은 일상 업무 문구로 한다.

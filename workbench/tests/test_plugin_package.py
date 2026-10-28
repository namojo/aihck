"""플러그인 패키지가 가리키는 파일과 이름이 실제로 맞는지 확인한다."""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(rel):
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def test_manifest_and_mcp_names():
    plugin = load(".claude-plugin/plugin.json")
    assert re.fullmatch(r"[a-z0-9-]+", plugin["name"])
    servers = load(".mcp.json")["mcpServers"]
    assert list(servers) == ["workbench"]
    assert "${CLAUDE_PLUGIN_ROOT}/src" in servers["workbench"]["env"]["PYTHONPATH"]


def test_hooks_point_to_existing_scripts():
    hooks = load("hooks/hooks.json")["hooks"]
    assert set(hooks) == {"PreToolUse", "SessionStart"}
    for groups in hooks.values():
        for g in groups:
            for h in g["hooks"]:
                m = re.search(r'\$\{CLAUDE_PLUGIN_ROOT\}/([^"]+)', h["command"])
                assert m and (ROOT / m.group(1)).is_file(), h["command"]


def test_pretooluse_matcher_covers_every_guarded_tool():
    matcher = load("hooks/hooks.json")["hooks"]["PreToolUse"][0]["matcher"]
    rx = re.compile(matcher)
    for tool in ("Read", "Edit", "Write", "MultiEdit", "NotebookEdit", "Grep", "Glob", "Bash", "PowerShell",
                 "mcp__nasca__decrypt", "mcp__plugin_x_nasca__decrypt"):
        assert rx.search(tool), tool
    assert not rx.search("TodoWrite")


def test_skill_has_description_and_names_real_tools():
    text = (ROOT / "skills/workbench-policy/SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---\n") and "description:" in text.split("---")[1]
    sys.path.insert(0, str(ROOT / "src"))
    from workbench.mcp_server import TOOL_NAMES
    for name in set(re.findall(r"workbench_[a-z_]+", text)):
        assert name in TOOL_NAMES, f"SKILL.md가 없는 도구를 언급한다: {name}"


def test_demo_script_runs_and_shows_the_difference():
    p = subprocess.run([sys.executable, str(ROOT / "scripts" / "demo_cycles.py"), "--edits", "4"],
                       capture_output=True, text=True, timeout=120,
                       env={"WORKBENCH_HOME": str(ROOT / ".pytest_cache" / "wbhome"), "WORKBENCH_BACKEND": "local",
                            "WORKBENCH_NASCA": "mock", "PATH": "/usr/bin:/bin", "PYTHONPATH": str(ROOT / "src")})
    assert p.returncode == 0, p.stderr
    rows = {l.split()[0]: l.split() for l in p.stdout.splitlines() if l.startswith(("매번", "작업구역"))}
    assert rows["매번"][2:4] == ["4", "4"], p.stdout
    assert rows["작업구역"][1:3] == ["1", "1"], p.stdout

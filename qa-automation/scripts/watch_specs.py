"""specs/auto 폴더를 감시하다가 새 Spec이 들어오면 자동으로 분석합니다.

사용법: python scripts/watch_specs.py [--once]
  --once  지금 폴더에 있는 파일만 처리하고 끝냅니다 (테스트용)

종료는 Ctrl+C 입니다.
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WATCH_DIR = ROOT / "specs" / "auto"
OUTPUT_DIR = ROOT / "output"
STATE_PATH = OUTPUT_DIR / "watch_state.json"
LOG_PATH = OUTPUT_DIR / "watch.log"

SUPPORTED = {".txt", ".md", ".pdf", ".docx", ".xlsx", ".xls", ".png", ".jpg", ".jpeg"}
POLL_SECONDS = 10
STABLE_SECONDS = 3
TIMEOUT_SECONDS = 30 * 60

# 자동 실행 중에는 승인을 누를 수 없어서, 필요한 것만 미리 허용합니다.
# 여기에 없는 도구는 실행되지 않고 거부됩니다.
ALLOWED_TOOLS = [
    "Skill",
    "Read(./**)",
    "Edit(./output/**)",  # 파일 생성(Write)도 이 규칙으로 허용됩니다
    "Bash(python scripts/read_spec.py *)",
    "Bash(python scripts/build_suite.py *)",
    "PowerShell(python scripts/read_spec.py *)",
    "PowerShell(python scripts/build_suite.py *)",
]

PROMPT = """/spec-to-tc {path}

자동 실행 중이라 사용자에게 질문할 수 없습니다.
애매한 내용은 묻지 말고 questions에 적으세요. 회차는 기본값(1)을 쓰세요.
"""


def log(message):
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {message}"
    print(line, flush=True)
    OUTPUT_DIR.mkdir(exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def notify(title, message):
    """Windows 알림을 띄웁니다. 실패해도 로그에는 남으므로 감시는 계속합니다."""
    script = (
        "Add-Type -AssemblyName System.Windows.Forms,System.Drawing;"
        "$n=New-Object System.Windows.Forms.NotifyIcon;"
        "$n.Icon=[System.Drawing.SystemIcons]::Information;"
        "$n.Visible=$true;"
        "$n.ShowBalloonTip(10000,$env:NOTIFY_TITLE,$env:NOTIFY_MESSAGE,'Info');"
        "Start-Sleep 11;$n.Dispose()"
    )
    # 파일 이름이 명령으로 해석되지 않도록 환경 변수로 넘깁니다
    env = {**os.environ, "NOTIFY_TITLE": title, "NOTIFY_MESSAGE": message}
    try:
        subprocess.Popen(
            ["powershell", "-NoProfile", "-Command", script],
            env=env,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except OSError as error:
        log(f"알림 실패: {error}")


def load_state():
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {}


def save_state(state):
    OUTPUT_DIR.mkdir(exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def is_ready(path):
    """복사나 저장이 끝난 파일인지 확인합니다 (크기가 그대로이고 열 수 있어야 함)."""
    try:
        before = path.stat()
        time.sleep(STABLE_SECONDS)
        after = path.stat()
        with path.open("rb"):
            pass
    except OSError:
        return False
    return (before.st_size, before.st_mtime) == (after.st_size, after.st_mtime) and after.st_size > 0


def find_new_specs(state):
    specs = []
    for path in sorted(WATCH_DIR.iterdir()):
        if not path.is_file() or path.name.startswith("~$") or path.suffix.lower() not in SUPPORTED:
            continue
        # 이미 처리한 파일은 기다리지 않도록 내용부터 비교합니다 (같은 이름이어도 내용이 바뀌면 다시 분석)
        if state.get(path.name, {}).get("sha256") == file_hash(path):
            continue
        if is_ready(path):
            specs.append(path)
    return specs


def analyze(path, claude):
    """Claude로 분석하고, 엑셀이 실제로 새로 만들어졌는지까지 확인합니다."""
    started = time.time()
    relative = path.relative_to(ROOT).as_posix()
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    try:
        result = subprocess.run(
            [claude, "-p", PROMPT.format(path=relative), "--allowedTools", *ALLOWED_TOOLS],
            cwd=ROOT,
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return None, f"{TIMEOUT_SECONDS // 60}분 안에 끝나지 않았습니다"

    log(f"--- Claude 출력 ({path.name}) ---\n{result.stdout}{result.stderr}\n--- 끝 ---")
    if result.returncode != 0:
        return None, f"Claude 종료 코드 {result.returncode}"

    suites = [p for p in (OUTPUT_DIR / path.stem).glob("TestSuite_*.xlsx") if p.stat().st_mtime >= started]
    if not suites:
        return None, "Test Suite 엑셀이 만들어지지 않았습니다"
    return suites[0], None


def process(path, state, claude):
    log(f"분석 시작: {path.name}")
    digest = file_hash(path)
    suite, error = analyze(path, claude)
    now = f"{datetime.now():%Y-%m-%d %H:%M:%S}"

    # 실패도 기록해서 같은 파일을 끝없이 다시 시도하지 않게 합니다 (내용을 바꾸면 다시 시도)
    state[path.name] = {"sha256": digest, "status": "failed" if error else "done", "time": now}
    save_state(state)

    if error:
        log(f"분석 실패: {path.name} - {error}")
        notify("Spec 분석 실패", f"{path.name}: {error}")
    else:
        log(f"분석 완료: {path.name} -> {suite}")
        notify("Spec 분석 완료", f"{path.name} -> {suite.name}")


def main():
    parser = argparse.ArgumentParser(description="specs/auto 폴더의 새 Spec을 자동으로 분석합니다.")
    parser.add_argument("--once", action="store_true", help="지금 있는 파일만 처리하고 끝냅니다")
    args = parser.parse_args()

    sys.stdout.reconfigure(encoding="utf-8")

    claude = shutil.which("claude")
    if not claude:
        sys.exit("claude 명령을 찾을 수 없습니다. Claude Code 설치를 확인해 주세요.")

    WATCH_DIR.mkdir(parents=True, exist_ok=True)
    state = load_state()
    log(f"감시 시작: {WATCH_DIR}")

    try:
        while True:
            for path in find_new_specs(state):
                process(path, state, claude)
            if args.once:
                break
            time.sleep(POLL_SECONDS)
    except KeyboardInterrupt:
        log("감시 종료")


if __name__ == "__main__":
    main()

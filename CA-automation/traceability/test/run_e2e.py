"""종단 시험: 로그인 요구 → 로그인 → 수집·판정·엑셀 → 2회차 변동"""
import builtins, json, shutil, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import mock_servers as M
import traceability as T

M.start()
root = Path(__file__).resolve().parent.parent
for d in ("state", "output"):
    shutil.rmtree(root / d, ignore_errors=True)
cfg = json.loads((root / "config.example.json").read_text(encoding="utf-8"))
cfg["confluence"]["base"] = "http://127.0.0.1:8101"
cfg["codebeamer"]["base"] = "http://127.0.0.1:8102/cb"
cfg["browser"]["channel"] = ""
T.get_cred = lambda name: None  # 수동 로그인 경로 시험
tcfg = root / "test" / "config.test.json"
tcfg.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")

asked = []
def fake_input(*a):
    asked.append(1); M.STATE["conf"] = M.STATE["cb"] = True; return ""
builtins.input = fake_input
T.Client.__init__.__defaults__ = (10, 3, lambda s: None, None)  # 재시도 대기 없앰

print("=== doctor ===")
assert T.main(["--config", str(tcfg), "--doctor", "--headless"] if False else ["--config", str(tcfg), "--doctor"]) == 0
print("login prompts:", len(asked))
print("=== run 1 ===")
assert T.main(["--config", str(tcfg)]) == 0
time.sleep(61)  # 파일명(분 단위) 구분
M.STATE["round"] = 2
print("=== run 2 ===")
assert T.main(["--config", str(tcfg)]) == 0
print("outputs:", sorted(p.name for p in (root / "output").iterdir()))

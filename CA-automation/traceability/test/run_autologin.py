"""자동 로그인 시험: 저장된 ID/PW로 두 사이트 로그인 + 실행 중 Codebeamer 세션 만료 → 재로그인 후 계속"""
import builtins, json, shutil, sys
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
tcfg = root / "test" / "config.test.json"
tcfg.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")

def no_input(*a):
    raise AssertionError("자동 로그인인데 사람 입력을 요구함")
builtins.input = no_input
T.get_cred = lambda name: M.CRED
T.Client.__init__.__defaults__ = (10, 3, lambda s: None, None)

M.STATE["cb_expire_after"] = 300  # SYS2(1200 Item) 처리 중 세션 만료
assert T.main(["--config", str(tcfg), "--headless"]) == 0
print("logins:", M.STATE["logins"])
assert M.STATE["logins"].count("conf") == 1 and M.STATE["logins"].count("cb") == 2, M.STATE["logins"]
import openpyxl
wb = openpyxl.load_workbook(sorted((root / "output").glob("*.xlsx"))[-1])
print(wb.sheetnames)
rows = list(wb["Overview"].iter_rows(values_only=True))
print([(r[0], r[1], r[5], r[6], r[10]) for r in rows])
assert "HWE.3&4" in wb.sheetnames
sys2 = next(r for r in rows if r[0] == "CI-SYS2-01")
assert sys2[6] == 12 and sys2[10] == "완료", sys2
print("자동 로그인·세션 만료 재로그인 OK")

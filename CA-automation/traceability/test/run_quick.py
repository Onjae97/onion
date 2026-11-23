"""v1.8 시험: --quick = CI list에 적힌 Tracker만 / 변동 기준 파일 분리 / 결과 파일명 _quick"""
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
cfg["confluence"]["base"] = "http://127.0.0.1:8101"; cfg["codebeamer"]["base"] = "http://127.0.0.1:8102/cb"; cfg["browser"]["channel"] = ""
assert cfg["scope"] == "top_with_descendants"
builtins.input = lambda *a: (_ for _ in ()).throw(AssertionError("input"))
T.get_cred = lambda name: M.CRED
T.Client.__init__.__defaults__ = (10, 3, lambda s: None, None)
tc = root / "test" / "config.test.json"; tc.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
import openpyxl

def ov(path):
    wb = openpyxl.load_workbook(path)
    return {r[0]: r for r in list(wb["Overview"].iter_rows(values_only=True))[1:]}, wb

# 빠른 검사: SYS4(상위 Tracker 등록, Item 없음) → 0 / SYS5(하위 1개 등록) → 그 Tracker만 20
assert T.main(["--config", str(tc), "--headless", "--quick"]) == 0
q = sorted((root / "output").glob("*_quick.xlsx")); assert len(q) == 1, q
o, wb = ov(q[0])
assert (o["CI-SYS4-03"][5] or 0, o["CI-SYS4-03"][16]) == (0, 1), o["CI-SYS4-03"][:17]
assert (o["CI-SYS5-05"][5], o["CI-SYS5-05"][6], o["CI-SYS5-05"][16]) == (20, 1, 1), o["CI-SYS5-05"][:17]
info = {r[0]: r[1] for r in wb["실행정보"].iter_rows(values_only=True)}
assert "빠른 검사" in info["검사 범위"], info["검사 범위"]
assert (root / "state" / "last_run_quick.json").exists() and not (root / "state" / "last_run.json").exists()

# 전체 검사(옵션 없음): 하위 포함 수치, 빠른 검사 기준과 섞이지 않음
assert T.main(["--config", str(tc), "--headless"]) == 0
f = [p for p in (root / "output").glob("*.xlsx") if not p.name.endswith("_quick.xlsx")]; assert len(f) == 1, f
o, wb = ov(f[0])
assert (o["CI-SYS4-03"][5], o["CI-SYS5-05"][5]) == (12, 55), (o["CI-SYS4-03"][5], o["CI-SYS5-05"][5])
info = {r[0]: r[1] for r in wb["실행정보"].iter_rows(values_only=True)}
assert info["직전 비교 기준"] == "없음" and "빠른 검사" not in info["검사 범위"]   # 첫 전체 검사 → 빠른 검사 기록을 기준으로 쓰지 않음
assert (root / "state" / "last_run.json").exists()
print("빠른 검사 옵션 시험 OK")

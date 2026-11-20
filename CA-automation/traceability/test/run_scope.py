"""하위 Tracker 범위 시험: SYS4(상위 등록) / SYS5(하위 등록 → 상위 기준) / 형제 Tracker 제외 / 손자 포함"""
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
builtins.input = lambda *a: (_ for _ in ()).throw(AssertionError("input"))
T.get_cred = lambda name: M.CRED
T.Client.__init__.__defaults__ = (10, 3, lambda s: None, None)
import openpyxl
for mode, exp in [("top_with_descendants", {"CI-SYS4-03": (12, 1, 3), "CI-SYS5-05": (55, 3, 4)}),
                  ("with_descendants", {"CI-SYS4-03": (12, 1, 3), "CI-SYS5-05": (25, 2, 2)}),
                  ("tracker_only", {"CI-SYS4-03": (0, 0, 1), "CI-SYS5-05": (20, 1, 1)})]:
    cfg["scope"] = mode
    tc = root / "test" / "config.test.json"; tc.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    shutil.rmtree(root / "output", ignore_errors=True)
    assert T.main(["--config", str(tc), "--headless", "--ci", "CI-SYS4-03", "--ci", "CI-SYS5-05", "--ci", "CI-SYS1-01"]) == 0
    wb = openpyxl.load_workbook(next((root / "output").glob("*.xlsx")))
    ov = {r[0]: r for r in list(wb["Overview"].iter_rows(values_only=True))[1:]}
    for ci, (den, unl, ntr) in exp.items():
        r = ov[ci]
        got = (r[5] or 0, r[6] or 0, r[16] or 0)
        print(mode, ci, "분모/미추적/Tracker수", got, "| 범위:", r[15], "|", r[17])
        assert got == (den, unl, ntr), (mode, ci, got)
    if mode == "top_with_descendants":
        print(wb.sheetnames)
        print([x for x in wb["SYS.5"].iter_rows(values_only=True)])
        print([x[:9] for x in wb["Tracker별"].iter_rows(values_only=True)])
print("범위 시험 OK")

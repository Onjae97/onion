"""종단 시험 (CL6 가짜 서버 재사용): CI 선택 → 최상위 Tracker 범위 → Tracker별 탭 → CL6 전체 검사 결과와 숫자 일치"""
import builtins, json, shutil, sys
from pathlib import Path
here = Path(__file__).resolve().parent
root = here.parent
cl6 = root.parent / "CL6_Traceability"
sys.path.insert(0, str(cl6 / "test"))
sys.path.insert(0, str(root))
import mock_servers as M
import traceability_bytracker as B
import openpyxl

T = B.tr
M.start()
for d in ("state", "output"):
    shutil.rmtree(root / d, ignore_errors=True)
cfg = json.loads((cl6 / "config.example.json").read_text(encoding="utf-8"))
cfg["confluence"]["base"] = "http://127.0.0.1:8101"; cfg["codebeamer"]["base"] = "http://127.0.0.1:8102/cb"; cfg["browser"]["channel"] = ""
tc = here / "config.test.json"; tc.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
builtins.input = lambda *a: (_ for _ in ()).throw(AssertionError("input"))
T.get_cred = lambda name: M.CRED
T.Client.__init__.__defaults__ = (10, 3, lambda s: None, None)

# 1) 대화형 선택: 'SYS' 검색(여러 개) → 번호로 고르기 (CI-SYS5-05 = 전체 목록 기준 번호)
answers = iter(["없는항목", "SYS", "7"])
asked = []
def ask(prompt=""):
    v = next(answers); asked.append(v); return v
assert B.main(["--config", str(tc)], ask=ask) == 0, "interactive"
assert asked == ["없는항목", "SYS", "7"], asked
f1 = next((root / "output").glob("*CI-SYS5-05*.xlsx"))
import time; time.sleep(1.1)

# 2) --ci 지정 (일부만 입력해도 하나로 좁혀지면 OK)
assert B.main(["--config", str(tc), "--headless", "--ci", "ci-sys5"]) == 0
f2 = [x for x in (root / "output").glob("*CI-SYS5-05*.xlsx") if x != f1][0]

# 3) 여러 개에 걸리면 실행하지 않음
try:
    B.main(["--config", str(tc), "--headless", "--ci", "SYS"]); raise SystemExit("ambiguous not rejected")
except T.ApiError as e:
    print("모호한 지정 거부 OK:", e)

for f in (f1, f2):
    wb = openpyxl.load_workbook(f)
    print(f.name, wb.sheetnames)
    tabs = [s for s in wb.sheetnames if s[:2].isdigit()]
    assert len(tabs) == 4, tabs  # 3000(최상위) · 3001 · 3002(등록) · 3003(손자) — 형제 2999 제외
    ov = list(wb["Overview"].iter_rows(values_only=True))
    kv = {r[0]: r[1] for r in ov[:15]}
    assert (kv["분모(판정대상)"], kv["미추적"]) == (55, 3), kv  # CL6 run_scope.py 기대값과 동일
    per = {}
    for s in tabs:
        rows = list(wb[s].iter_rows(min_row=3, values_only=True))
        per[s] = [r[5] for r in rows if r and r[5]]
    print(" 탭별 미추적:", per)
    assert sorted(x for v in per.values() for x in v) == ["TC-GROUP-B-1-33001", "TCA-31002", "TCB-32005"], per
    assert per[tabs[0]] == [] and per[tabs[1]] == ["TCA-31002"], per
    summ = [r for r in ov[16:] if r[0] is not None]
    assert summ[-1][0] == "합계" and summ[-1][7] == 3, summ[-1]
    # Overview Sheet 링크가 탭으로 이동
    assert wb["Overview"].cell(18, 2).hyperlink.location or wb["Overview"].cell(18, 2).hyperlink.target

# 4) 기존 CL6 전체 검사와 숫자 비교 (같은 판정 모듈)
shutil.rmtree(cl6 / "output", ignore_errors=True); shutil.rmtree(cl6 / "state", ignore_errors=True)
assert T.main(["--config", str(tc), "--headless", "--ci", "CI-SYS5-05"]) == 0
cw = openpyxl.load_workbook(next((cl6 / "output").glob("*.xlsx")))
row = [r for r in cw["Overview"].iter_rows(values_only=True) if r[0] == "CI-SYS5-05"][0]
assert (row[5], row[6]) == (55, 3), row
shutil.rmtree(cl6 / "output", ignore_errors=True); shutil.rmtree(cl6 / "state", ignore_errors=True)
tc.unlink()
print("Tracker별 시험 OK")

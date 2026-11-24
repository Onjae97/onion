"""CL3 종단 시험 — 자동 로그인 → CI list → ① Status(상위+하위) → ② Review Tracker → ③ Defect(Codebeamer·Jira·첨부) → 엑셀 검증
리눅스: xvfb-run python test/run_e2e.py   (Windows: python test\\run_e2e.py)"""
import builtins, json, shutil, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import mock_cl3 as M
import cl3_check as C
import openpyxl

M.start()
root = Path(__file__).resolve().parent.parent
for d in ("state", "output"):
    shutil.rmtree(root / d, ignore_errors=True)
cfg = json.loads((root / "config.example.json").read_text(encoding="utf-8"))
cfg["confluence"].update(base=M.CF, ci_list_page_id="1")
cfg["codebeamer"]["base"] = M.CB
cfg["jira"]["base"] = M.JR
cfg["browser"]["channel"] = sys.argv[1] if len(sys.argv) > 1 else "chrome"
tc = root / "test" / "config.test.json"
tc.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
builtins.input = lambda *a: (_ for _ in ()).throw(AssertionError("수동 입력을 요구하면 안 됨"))
C.get_cred = lambda name: M.CRED
C.Client.__init__.__defaults__ = (10, 1, lambda s: None, None)
COND, MAN = "Conditional OK", "수동 확인"


def latest_out():
    return max((root / "output").glob("*.xlsx"), key=lambda p: p.stat().st_mtime)


def load(path):
    wb = openpyxl.load_workbook(path)
    rows = list(wb["Overview"].iter_rows(values_only=True))
    return {r[0]: dict(zip(rows[0], r)) for r in rows[1:]}, wb


def rows(wb, name):
    return list(wb[name].iter_rows(values_only=True))[1:]


EXPECT = {  # CI: (종합, ①, ②, ③)
    "CI-A": ("OK", "OK", "OK", "OK"),            # 상위+하위, Type '--' 포함 Accepted / CB Defect Closed + Jira Done
    "CI-B": ("NOK", "NOK", "OK", "NOK"),         # Draft·In Review NOK, Obsolete·Rejected 별도 / CB Defect Open
    "CI-C": ("NOK", "NOK", MAN, MAN),            # 하위 Tracker CI → 상위 Item Draft / Review Item 0건
    "CI-D": ("NOK", "OK", "NOK", "-"),           # Review Tracker 없음
    "CI-E": (COND, "OK", COND, COND),            # Category 경로, Review 이름 89%, 첨부 Defect List Deferred
    "CI-F": (COND, "OK", "OK", COND),            # Defect 근거 없음
    "CI-G": (MAN, MAN, MAN, MAN),                # Git
    "CI-H": ("NOK", "OK", "OK", "NOK"),          # Jira In Progress
}

print("=== doctor ===")
assert C.main(["--config", str(tc), "--doctor"]) == 0
assert list((root / "state" / "debug").glob("CI-A_review_9001.json")), "doctor가 Review Item 원본을 저장해야 함"

print("=== run 1: 전체 검사 ===")
assert C.main(["--config", str(tc)]) == 0
ov, wb = load(latest_out())
assert "CI-N" not in ov
for cid, e in EXPECT.items():
    r = ov[cid]
    got = (r["CL3 결과"], r["① Status"], r["② VR 수행"], r["③ Defect 해결"])
    assert got == e, f"{cid}: 기대 {e} / 결과 {got} — {r['① 근거']} | {r['② 근거']} | {r['③ 근거']}"
a = ov["CI-A"]
assert a["대상 Item"] == 4 and a["Type --"] == 1 and "+ 하위 1" in a["검사 범위(상위 Tracker)"], a
b = ov["CI-B"]
assert b["Accepted 아님"] == 2 and b["별도 Status 수"] == "Obsolete 1 · Rejected 1", b
assert "상위 'C top'" in ov["CI-C"]["① 근거"] and "Item 0건" in ov["CI-C"]["② 근거"], ov["CI-C"]
assert "Review_D spec" in ov["CI-D"]["② 근거"], ov["CI-D"]
assert ov["CI-E"]["Defect 수"] == 2 and "Review_HW Thing Spec_ADCU-50S" in ov["CI-E"]["Review Tracker"], ov["CI-E"]
sn = rows(wb, "Status NOK")
assert {(x[0], x[6]) for x in sn} == {("CI-B", "Draft"), ("CI-B", "In Review"), ("CI-C", "Draft")}, sn
assert any(x[6] == "In Review" and x[7] == "●" for x in sn), "Type -- 표시"
assert [x[3] for x in sn if x[6] == "Draft" and x[0] == "CI-B"] == ["SYS2_B-1102"], sn
ss = rows(wb, "별도 Status")
assert sorted((x[0], x[2], x[3]) for x in ss) == [("CI-B", "Obsolete", 1), ("CI-B", "Rejected", 1)], ss
df = rows(wb, "Defect")
got = {(x[0], x[3], x[6]) for x in df if x[6] != MAN}
assert got == {("CI-A", "7001", "해결"), ("CI-A", "KEY-1", "해결"), ("CI-B", "7002", "미해결"), ("CI-E", "1", "해결"),
               ("CI-E", "2", "보류"), ("CI-H", "KEY-2", "미해결")}, got
assert any(x[0] == "CI-E" and "minutes.pdf" in x[4] for x in df), df
tb = rows(wb, "Tracker별")
assert len([x for x in tb if x[0] == "CI-A"]) == 2, tb
summ = {r[0]: r for r in wb["요약"].iter_rows(values_only=True)}
assert summ["CL3 종합"][3] == 4, summ["CL3 종합"]
print("   run 1 OK")

time.sleep(61)
print("=== run 2: 빠른 검사 ===")
assert C.main(["--config", str(tc), "--quick", "--ci", "CI-C", "--ci", "CI-A"]) == 0
out = latest_out()
assert out.name.endswith("_quick.xlsx"), out
ov, wb = load(out)
assert ov["CI-C"]["① Status"] == "OK" and ov["CI-C"]["② VR 수행"] == MAN, ov["CI-C"]  # ①은 적힌 Tracker만, ②는 상위 기준
assert ov["CI-A"]["대상 Item"] == 2, ov["CI-A"]
info = {r[0]: r[1] for r in wb["실행정보"].iter_rows(values_only=True)}
assert "빠른 검사" in info["검사 방식"]
print("   run 2 OK")
print("ALL PASS")

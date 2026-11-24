"""CL2 종단 시험 — 자동 로그인 → CI list → Revision history Item 찾기·표 읽기 → ①②③ 판정 → 엑셀 검증
리눅스: xvfb-run python test/run_e2e.py   (Windows: python test\\run_e2e.py)"""
import builtins, json, shutil, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import mock_cl2 as M
import cl2_check as C
import openpyxl

M.start()
root = Path(__file__).resolve().parent.parent
for d in ("state", "output"):
    shutil.rmtree(root / d, ignore_errors=True)
cfg = json.loads((root / "config.example.json").read_text(encoding="utf-8"))
cfg["confluence"].update(base=M.CF, ci_list_page_id="1")
cfg["codebeamer"]["base"] = M.CB
cfg["browser"]["channel"] = sys.argv[1] if len(sys.argv) > 1 else "chrome"
tc = root / "test" / "config.test.json"
tc.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
builtins.input = lambda *a: (_ for _ in ()).throw(AssertionError("수동 입력을 요구하면 안 됨"))
C.get_cred = lambda name: M.CRED
C.Client.__init__.__defaults__ = (10, 1, lambda s: None, None)


def latest_out():
    return max((root / "output").glob("*.xlsx"), key=lambda p: p.stat().st_mtime)


def overview(path):
    wb = openpyxl.load_workbook(path)
    rows = list(wb["Overview"].iter_rows(values_only=True))
    h = rows[0]
    return {r[0]: dict(zip(h, r)) for r in rows[1:]}, wb


COND = "Conditional OK"
EXPECT = {  # CI ID: (종합, ①, ②, ③)
    "CI-A": (COND, "OK", "OK", COND),          # 사진과 같은 표: 'v' 누락만
    "CI-B": ("OK", "OK", "OK", "OK"),          # v1.0a → v1.0 → v1.1a → v1.1 → v2.0
    "CI-C": ("NOK", "NOK", "-", "-"),          # Revision history Item 없음
    "CI-D": ("NOK", "OK", "NOK", "OK"),        # Approver 빈칸(공백)
    "CI-E": ("NOK", "OK", "OK", "NOK"),        # HTML 본문, v1.0 → v1.2 Minor 건너뜀
    "CI-F": ("OK", "OK", "OK", "OK"),          # 본문엔 표 없음 → Item 화면 표, 최신이 위
    "CI-G": ("OK", "OK", "OK", "OK"),          # 하위 Tracker → 상위 Tracker의 Item
    "CI-H": ("확인불가", "확인불가", "-", "-"),  # Tracker 조회 500
    "CI-I": ("OK", "OK", "OK", "OK"),          # Confluence 페이지 본문 표
    "CI-J": ("수동 확인", "수동 확인", "-", "-"),  # Git
    "CI-K": ("NOK", "NOK", "-", "-"),          # 경로 비어 있음
    "CI-L": ("NOK", "NOK", "-", "-"),          # 헤더만 있음
    "CI-M": (COND, "OK", "OK", COND),          # Item 1201개 → 3페이지째에서 발견, 날짜 2025.01.01 형식(YYYY-MM-DD 아님)
    "CI-O": ("NOK", "OK", "OK", "NOK"),        # 공식 확정 후 같은 버전 Draft
    "CI-P": ("OK", "OK", "OK", "OK"),          # /cb/category/ 경로 + [{Table}] 플러그인 표(실측 형식)
    "CI-Q": ("OK", "OK", "OK", "OK"),          # 'Author (Approver)' 한 열
    "CI-R": (COND, COND, "OK", "OK"),          # 템플릿 이력만 → 최대 Conditional OK
    "CI-S": ("OK", "OK", "OK", "OK"),          # 문서 이력 우선 (템플릿 v9.0 무시)
    "CI-T": ("OK", "OK", "OK", "OK"),          # HTML 병합 셀(rowspan)
}

print("=== doctor ===")
assert C.main(["--config", str(tc), "--doctor"]) == 0
assert list((root / "state" / "debug").glob("rh_item_*.json")), "doctor가 Item 원본을 저장해야 함"

print("=== run 1: 전체 ===")
assert C.main(["--config", str(tc)]) == 0
ov, wb = overview(latest_out())
assert "CI-N" not in ov, "PBL 없는 CI는 제외"
for cid, e in EXPECT.items():
    r = ov[cid]
    got = (r["CL2 결과"], r["① 존재·관리"], r["② 필수 항목"], r["③ Version Rule"])
    assert got == e, f"{cid}: 기대 {e} / 결과 {got} — {r['① 근거']} | {r['② 근거']} | {r['③ 근거']}"
assert "'v' 접두어 누락" in ov["CI-A"]["③ 근거"] and ov["CI-A"]["최신 Version"] == "2.0", ov["CI-A"]
assert "Approver" in ov["CI-D"]["② 근거"], ov["CI-D"]
assert "Minor 건너뜀 v1.0 → v1.2" in ov["CI-E"]["③ 근거"], ov["CI-E"]
assert ov["CI-F"]["정렬"].startswith("내림차순") and "Item 화면" in ov["CI-F"]["① 근거"], ov["CI-F"]
assert "상위 Tracker 'G top'(2101)" in ov["CI-G"]["Revision history 위치"], ov["CI-G"]
assert "(99999)" in ov["CI-M"]["Revision history 위치"], ov["CI-M"]
assert "공식 확정(v1.0) 후" in ov["CI-O"]["③ 근거"], ov["CI-O"]
assert ov["CI-C"]["Category"] == "SYS.2"  # 병합 셀 → 위 행 값
rh = list(wb["Revision history"].iter_rows(values_only=True))
a2 = [x for x in rh if x[0] == "CI-A" and x[3] == "2.0"][0]
assert "REQ.SOM010 추가" in a2[5] and "\n" in a2[5], a2
nok = list(wb["NOK"].iter_rows(values_only=True))[1:]
assert {x[0] for x in nok} == {"CI-C", "CI-D", "CI-E", "CI-K", "CI-L", "CI-O"}, nok
p2 = [x for x in rh if x[0] == "CI-P"]
assert len(p2) == 2 and p2[0][4] == "2026-01-16" and p2[0][5] == "Initial release" and "[PROJ-1234] FSR 항목 삭제 - Jira" in p2[1][5], p2
q = [x for x in rh if x[0] == "CI-Q"]
assert q[0][6] == "Author Two" and q[0][7] == "Approver Two", q
assert "142" in ov["CI-S"]["Revision history 위치"] and "템플릿" in ov["CI-R"]["① 근거"], (ov["CI-S"], ov["CI-R"])
assert "YYYY-MM-DD" in ov["CI-M"]["③ 근거"], ov["CI-M"]
assert list((root / "state" / "debug").glob("CI-D_rh_item_41.json")), "OK가 아닌 CI는 원본 저장"
ck = list(wb["확인 필요"].iter_rows(values_only=True))[1:]
assert {x[0] for x in ck} == {"CI-A", "CI-H", "CI-J", "CI-M", "CI-R"}, ck
summ = {r[0]: r for r in wb["요약"].iter_rows(values_only=True)}
assert summ["CL2 종합"][1] == 8 and summ["CL2 종합"][3] == 6, summ["CL2 종합"]
tried = [r for r in wb["조회 기록"].iter_rows(values_only=True) if r[0] == "CI-G"]
assert any("상위 Tracker" in str(r[1]) for r in tried), tried
print("   run 1 OK —", len(ov), "CI")

time.sleep(61)  # 결과 파일명(분 단위) 구분
print("=== run 2: --item 직접 지정 ===")
assert C.main(["--config", str(tc), "--ci", "CI-C", "--item", "21"]) == 0
ov, _ = overview(latest_out())
assert ov["CI-C"]["CL2 결과"] == "OK" and "직접 지정" in ov["CI-C"]["Revision history 위치"], ov["CI-C"]
print("   run 2 OK")
print("ALL PASS")

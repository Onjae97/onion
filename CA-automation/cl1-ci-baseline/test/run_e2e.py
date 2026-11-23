"""CL1 종단 시험 — 자동 로그인 → CI list → Baseline(화면 / 이전 REST / 파일) → ①② 판정 → 엑셀 검증
리눅스: xvfb-run python test/run_e2e.py"""
import builtins, json, shutil, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import mock_cl1 as M
import cl1_check as C
import openpyxl

M.start()
root = Path(__file__).resolve().parent.parent
for d in ("state", "output"):
    shutil.rmtree(root / d, ignore_errors=True)
cfg = json.loads((root / "config.example.json").read_text(encoding="utf-8"))
cfg["confluence"].update(base="http://127.0.0.1:8201", ci_list_page_id="1")
cfg["codebeamer"]["base"] = M.CB
cfg["browser"]["channel"] = sys.argv[1] if len(sys.argv) > 1 else "chrome"
cfg["cl1"]["baseline"]["project_id"] = "171"
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


EXPECT = {  # CI ID: (① 저장소, ② Baseline)
    "CI-SYS1-01": ("OK", "OK"),
    "CI-SYS2-01": ("OK", "OK"),            # 공백/밑줄 차이 = 같은 이름
    "CI-HWE1-01": ("OK(유사)", "OK(유사)"),  # ADCU50 vs ADCU50S → 사람 확인
    "CI-SYS3-01": ("NOK", "OK(유사)"),      # Tracker 404 / Baseline 쪽 오타(Specifiction)
    "CI-SWE1-01": ("NOK", "OK"),            # 경로 Tracker 이름 다름, 다른 위치에 같은 이름 Tracker
    "CI-SWE6-01": ("OK", "NOK"),            # Baseline에 없음
    "CI-SYS1-02": ("OK", "OK"),             # Confluence 페이지 (Category 빈칸 → 위 행 값)
    "CI-SWE3-01": ("수동 확인", "OK"),       # Git
    "CI-SUP8-01": ("확인불가", "NOK"),       # Tracker 조회 500
    "CI-SYS2-02": ("NOK", "OK"),            # 경로 비어 있음
}

print("=== doctor ===")
assert C.main(["--config", str(tc), "--doctor"]) == 0
assert list((root / "state" / "debug").glob("baseline_*.html")), "doctor가 화면을 저장해야 함"

print("=== run 1: 화면 숨은 정보(metaData)에서 Baseline 읽기 ===")
assert C.main(["--config", str(tc)]) == 0
ov, wb = overview(latest_out())
assert "CI-MAN3-01" not in ov, "PBL 없는 CI는 제외"
for cid, (e1, e2) in EXPECT.items():
    got = (ov[cid]["① 저장소 관리"], ov[cid]["② Baseline 포함"])
    assert got == (e1, e2), f"{cid}: 기대 {(e1, e2)} / 결과 {got} — {ov[cid]['① 근거']} | {ov[cid]['② 근거']}"
assert "1005" in ov["CI-SWE1-01"]["① 근거"], "다른 위치의 같은 이름 Tracker를 알려줘야 함"
assert "가장 비슷한" in ov["CI-SWE6-01"]["② 근거"] or "없음" in ov["CI-SWE6-01"]["② 근거"]
assert ov["CI-SYS1-02"]["Category"] == "SWE.6"  # 병합 셀 → 위 행 값
summ = [r for r in wb["요약"].iter_rows(values_only=True)]
assert any(r[0] == "사용한 Baseline" and r[1] == "HKMC_ADCU50S_RS4FL_G_M_PBL_2026-11-19" for r in summ), summ
bl = list(wb["Baseline"].iter_rows(values_only=True))[1:]
assert len(bl) == 8 and bl[2][1] == "System Requirements Specification_ADCU50", bl
nok = list(wb["NOK"].iter_rows(values_only=True))[1:]
assert len(nok) == 5, nok
print("   run 1 OK —", len(ov), "CI, NOK 행", len(nok))

info = {r[0]: r[1] for r in wb["실행정보"].iter_rows(values_only=True)}
assert "metaData" in info["Baseline"] and "8개" in info["Baseline"], info["Baseline"]

time.sleep(61)
print("=== run 1b: metaData 없는 화면 → 링크·속성 화면에서 읽기 ===")
M.STATE["meta"] = False
assert C.main(["--config", str(tc), "--ci", "CI-SYS1-01", "--ci", "CI-SWE6-01"]) == 0
ov, wb = overview(latest_out())
assert (ov["CI-SYS1-01"]["② Baseline 포함"], ov["CI-SWE6-01"]["② Baseline 포함"]) == ("OK", "NOK"), ov
info = {r[0]: r[1] for r in wb["실행정보"].iter_rows(values_only=True)}
assert "details.do" in info["Baseline"], info["Baseline"]
print("   run 1b OK")

time.sleep(61)  # 결과 파일명(분 단위) 구분
print("=== run 2: 이전 REST API(wiki description) ===")
M.STATE["legacy_api"] = True
assert C.main(["--config", str(tc), "--ci", "CI-SYS1-01", "--ci", "CI-SWE1-01"]) == 0
ov, wb = overview(latest_out())
assert ov["CI-SYS1-01"]["② Baseline 포함"] == "OK" and ov["CI-SWE1-01"]["② Baseline 포함"] == "NOK", ov
info = {r[0]: r[1] for r in wb["실행정보"].iter_rows(values_only=True)}
assert "rest/project" in info["Baseline"] and "3개" in info["Baseline"], info["Baseline"]
print("   run 2 OK")

time.sleep(61)
print("=== run 3: --baseline-file (화면에서 복사한 텍스트) ===")
f = root / "test" / "desc.txt"
f.write_text("PBL Baseline 대상 산출물\t산출물 버전\nSoftware Qualification Test Report\tv1.0\n", encoding="utf-8")
assert C.main(["--config", str(tc), "--ci", "CI-SWE6-01", "--baseline-file", str(f)]) == 0
ov, _ = overview(latest_out())
assert ov["CI-SWE6-01"]["② Baseline 포함"] == "OK", ov
print("   run 3 OK")
print("ALL PASS")

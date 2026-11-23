"""v1.7 시험: 연결 상대가 Folder·Information('정보' 포함)뿐이면 미추적 / 상대 확인 불가면 확인불가 / 한글 '정보' 제외"""
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
cfg["judge"]["exclude_types"] = ["Folder", "Information"]  # 예전 config.json('정보' 없음)에서도 별칭으로 제외되는지
builtins.input = lambda *a: (_ for _ in ()).throw(AssertionError("input"))
T.get_cred = lambda name: M.CRED
T.Client.__init__.__defaults__ = (10, 3, lambda s: None, None)
tc = root / "test" / "config.test.json"; tc.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")

# 단위: 별칭·판정 함수
ex = {"folder", "information"}
assert T.name_excluded("정보", ex) and T.name_excluded("Infomation", ex) and not T.name_excluded("기능", ex)
assert T.rel_targets({"a": [M.ref(5)], "b": [{"id": 1}], "c": "x"}) == [5, None]
assert T.judge_links([], {}, ex) == "none"
assert T.judge_links([1], {1: {"typeName": "Folder"}}, ex) == "only_excluded"
assert T.judge_links([1, 2], {1: {"typeName": "Folder"}, 2: None}, ex) == "unknown"
assert T.judge_links([1, None], {1: {"typeName": "Requirement"}}, ex) == "linked"

assert T.main(["--config", str(tc), "--headless", "--ci", "CI-SYS1-01", "--ci", "CI-SYS5-05"]) == 0
import openpyxl
wb = openpyxl.load_workbook(next((root / "output").glob("*.xlsx")))
ov = {r[0]: r for r in list(wb["Overview"].iter_rows(values_only=True))[1:]}
s1 = ov["CI-SYS1-01"]
cat = next(n for n in wb.sheetnames if n.startswith("SYS.1"))
items = {str(r[4]).rsplit("-", 1)[-1]: r[5] for r in list(wb[cat].iter_rows(values_only=True))[1:]}
unk = {str(r[2]).rsplit("-", 1)[-1]: r[3] for r in list(wb["확인불가"].iter_rows(values_only=True))[1:]}
print("SYS1 분모/미추적/확인불가/상대제외만:", s1[5], s1[6], s1[9], s1[20])
print("미추적:", items)
print("확인불가:", unk)
assert "50" in items and "51" in items, items                          # 상대가 Information / '정보'뿐 → 미추적
assert all("Folder/Information에만 연결" in (items[k] or "") for k in ("50", "51"))
assert "Folder/Information" not in (items["12"] or "")
assert "52" not in items and "52" not in unk                          # Folder + 유효 상대 → 연결
assert "53" in unk and "55" in unk and "상대" in unk["53"]             # 상대 확인 불가 → 확인불가
assert "54" not in items and "54" not in unk                          # 한글 '정보' 유형 → 제외
assert "56" not in items and "56" not in unk                          # 2페이지에서 유효 연결 확인 → 연결
assert "57" in items and "Folder/Information에만 연결" in (items["57"] or "")  # 모든 페이지가 Folder/Information → 미추적
assert s1[20] == 3
# 기존 SYS.1 결과(12,15,16?,18 등)는 그대로: 16·18은 제외, 12·15 미추적
assert {"12", "15"} <= set(items)
s5 = ov["CI-SYS5-05"]
assert (s5[5], s5[6]) == (55, 3), s5[:7]                               # 범위 밖 상대(17) 상세 조회로 연결 판정 — 기존 수치 유지
print("연결 상대 유형 시험 OK")

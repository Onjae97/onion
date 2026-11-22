#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AUTO-001 추적성 Gap Matrix — 완전 자동 실행 (v1.0)

흐름: ① Confluence에서 최신 CI list 첨부 받기 → ② PBL·Codebeamer CI 선별
      → ③ CI(Tracker)별 Item 전수 조회 → ④ 연결(Reference/Association) 판정
      → ⑤ Gap Matrix 엑셀 생성(Overview·Category·변동·확인불가·실행정보)

로그인: 전용 브라우저 창(state/browser-profile)에 한 번 로그인해 두면 이후 재사용.
        API 토큰 불필요. 모든 조회는 읽기 전용(GET).
원칙:   조회 실패 = 확인불가 (연결/미연결로 넘기지 않음)
        결과는 항상 새 파일로 생성 (기존 파일 덮어쓰기 없음). 공식 산출물 반영·저장은 사람이.

사용:   python traceability.py            # 전체 실행
        python traceability.py --doctor   # 연결 점검 (파일 생성 없음)
        python traceability.py --ci CI_ID [--ci CI_ID ...]   # 일부 CI만
        python traceability.py --limit 3  # 앞의 N개 CI만 (시험용)
"""
import argparse
import base64
import datetime as dt
import io
import json
import re
import sys
import time
from pathlib import Path

VERSION = "1.7"
HERE = Path(__file__).resolve().parent
STATE = HERE / "state"


def log(msg=""):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


# =====================================================================
# 1. 판정 규칙 (순수 함수)
# =====================================================================
def norm(s):
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def category_of(v):
    """Category에서 detail을 뺀 단위 (예: 'SYS.2.1 System ...' → 'SYS.2')"""
    s = str(v or "").strip()
    m = re.search(r"([A-Za-z]{2,5})\s*\.?\s*(\d+)((?:\s*[&/,]\s*\d+)*)", s)
    if not m:
        return s or "(미분류)"
    extra = re.findall(r"\d+", m.group(3))  # 'HWE.3&4' → 'HWE.3&4' (detail '.1'은 버림)
    return f"{m.group(1).upper()}.{m.group(2)}" + "".join(f"&{e}" for e in extra)


def tracker_id_of(path):
    m = re.search(r"/tracker/(\d+)", path or "")
    return m.group(1) if m else ""


def is_codebeamer(ci):
    return bool(re.search("codebeamer", ci["repository"], re.I)
                or re.search(r"codebeamer|/cb/tracker/", ci["path"], re.I))


def type_sources(item):
    """Item의 '유형'으로 쓰일 수 있는 값을 출처별로 모은다.
    Codebeamer 요구사항 트래커의 Type은 보통 기본 필드 Category(categories)를 'Type'으로 바꿔 쓴 것."""
    src = {}
    if item.get("typeName"):
        src.setdefault("typeName", []).append(str(item["typeName"]).strip())
    if isinstance(item.get("type"), dict) and item["type"].get("name"):
        src.setdefault("type", []).append(str(item["type"]["name"]).strip())
    for c in item.get("categories") or []:
        if isinstance(c, dict) and c.get("name"):
            src.setdefault("categories", []).append(str(c["name"]).strip())
    for f in item.get("customFields") or []:
        if norm(f.get("name")) == "type":
            for v in f.get("values") or []:
                if isinstance(v, dict) and v.get("name"):
                    src.setdefault("customField:Type", []).append(str(v["name"]).strip())
            if isinstance(f.get("value"), str) and f["value"]:
                src.setdefault("customField:Type", []).append(f["value"].strip())
    return src


def type_labels(item):
    return [v for vs in type_sources(item).values() for v in vs]


def type_of(item):
    return " / ".join(dict.fromkeys(type_labels(item)))


UNSET_NAMES = {"", "unset", "--", "none", "-"}


def type_unset(item):
    """Type 미지정('--'): Type 필드(기본 필드 categories 또는 사용자 필드 'Type') 값이 없거나 Unset.
    typeName은 Tracker 종류 이름이라 Type 필드로 보지 않는다 (실측: Tracker에 따라 typeName이 전부 'Requirement'로 나옴)."""
    src = type_sources(item)
    vals = src.get("categories", []) + src.get("customField:Type", [])
    return all(norm(v) in {norm(x) for x in UNSET_NAMES} for v in vals)


def has_type_field(cl, tid):
    try:
        fields = cl.get(f"/api/v3/trackers/{tid}/fields")
    except ApiError:
        return False
    fields = fields if isinstance(fields, list) else (fields.get("fields") or fields.get("items") or [])
    return any(norm(f.get("name")) == "type" for f in fields)


def type_ids(item):
    ids = set()
    for c in item.get("categories") or []:
        if isinstance(c, dict) and c.get("id") is not None:
            ids.add(c["id"])
    for f in item.get("customFields") or []:
        if norm(f.get("name")) == "type":
            for v in f.get("values") or []:
                if isinstance(v, dict) and v.get("id") is not None:
                    ids.add(v["id"])
    return ids


# 유형 이름의 다른 표기 (API가 한글로 돌려주는 경우). 실제 사례: categories가 '정보'로 반환된 Tracker가 있음
TYPE_ALIASES = {"정보": "information"}


def name_excluded(name, exclude):
    """유형 이름이 제외 대상인지. Codebeamer API가 Meaning을 주지 않으므로 이름으로 판단하되,
    오타(예: 'Infomation')도 잡도록 철자 유사도 0.85 이상이면 같은 것으로 본다.
    한글 표기('정보')는 TYPE_ALIASES로 영문 이름에 맞춘다 (norm은 한글을 지우므로 먼저 확인)."""
    import difflib
    raw = str(name or "").strip()
    if raw in TYPE_ALIASES:
        raw = TYPE_ALIASES[raw]
    if raw.lower() in exclude or raw in exclude:
        return True
    n = norm(raw)
    if not n:
        return False
    return any(n == norm(e) or difflib.SequenceMatcher(None, n, norm(e)).ratio() >= 0.85 for e in exclude)


def is_excluded(item, exclude, excl_ids=frozenset()):
    # 선택지 id 비교는 하지 않는다: Type·Category 필드의 id가 서로 겹쳐(둘 다 1,3…) 엉뚱한 Item을 뺄 위험.
    # (실측: Codebeamer API가 선택지 Meaning을 주지 않는 환경이 있음 → 이름 기준)
    return any(name_excluded(v, exclude) for v in type_labels(item))


def _meaning(opt):
    out = []
    for k, v in opt.items():
        if "meaning" in k.lower():
            for x in (v if isinstance(v, list) else [v]):
                out.append(str(x.get("name", "")) if isinstance(x, dict) else str(x))
    return ", ".join(o for o in out if o)


def type_field_options(cl, tid):
    """Tracker의 Type(=Category) 필드 선택지와 Meaning (화면 필터의 Meaning 묶음과 대응)"""
    fields = cl.get(f"/api/v3/trackers/{tid}/fields")
    fields = fields if isinstance(fields, list) else (fields.get("fields") or fields.get("items") or [])
    out = []
    for f in fields:
        if norm(f.get("name")) not in ("type", "category", "categories"):
            continue
        try:
            d = cl.get(f"/api/v3/trackers/{tid}/fields/{f['id']}")
        except ApiError:
            continue
        for o in d.get("options") or []:
            out.append({"field": f.get("name"), "id": o.get("id"), "name": o.get("name"), "meaning": _meaning(o), "keys": sorted(o.keys())})
    return out


def excluded_option_ids(options, exclude):
    return {o["id"] for o in options
            if o["id"] is not None and o["field"] and norm(o["field"]) == "type"
            and (name_excluded(o["name"], exclude) or any(name_excluded(m, exclude) for m in o["meaning"].split(",")))}


def rel_count(rel):
    """Up/Downstream Reference + incoming/outgoing Association 개수 합"""
    return sum(len(v) for v in (rel or {}).values() if isinstance(v, list))


def rel_targets(rel):
    """연결 상대 Item 번호 목록. Codebeamer v3 응답: 각 연결 = {id: 연결 번호, itemRevision: {id: 상대 Item 번호}, type}.
    상대 번호를 찾지 못한 연결은 None (추측하지 않음 → 판정 불가 처리)."""
    out = []
    for v in (rel or {}).values():
        if not isinstance(v, list):
            continue
        for x in v:
            x = x if isinstance(x, dict) else {}
            iid = (x.get("itemRevision") or {}).get("id") or (x.get("item") or {}).get("id")
            out.append(int(iid) if iid is not None else None)
    return out


def coverage(denom, unlinked):
    return round((denom - unlinked) / denom * 100, 1) if denom else None


# =====================================================================
# 1-1. 로그인 정보 (Windows 자격 증명 관리자 — 파일에 저장하지 않음)
# =====================================================================
CRED_SERVICE = "AUTO-001 traceability"


def get_cred(name):
    try:
        import keyring
        user = keyring.get_password(CRED_SERVICE, f"{name}:user")
        pw = keyring.get_password(CRED_SERVICE, f"{name}:{user}") if user else None
        return (user, pw) if user and pw else None
    except Exception:  # noqa  keyring 미설치·접근 실패 → 수동 로그인
        return None


def _need_keyring():
    try:
        import keyring  # noqa: F401
        return True
    except ImportError:
        print("✖ keyring 패키지가 없습니다. setup.bat을 먼저 실행한 뒤 다시 시도하세요.")
        return False


def set_login():
    import getpass
    if not _need_keyring():
        return
    import keyring
    print("AUTO-001 로그인 정보 저장 — Windows 자격 증명 관리자에 암호화되어 이 Windows 계정에서만 읽힙니다.")
    print("(비밀번호는 입력해도 화면에 표시되지 않습니다)\n")
    saved = {}
    for name in ("Confluence", "Codebeamer"):
        if name == "Codebeamer" and saved:
            if input("Codebeamer도 같은 ID/PW를 씁니까? (Y/n): ").strip().lower() in ("", "y", "yes", "ㅛ"):
                saved[name] = saved["Confluence"]
        if name not in saved:
            u = input(f"{name} ID: ").strip()
            p = getpass.getpass(f"{name} PW: ")
            if not u or not p:
                print(f"  {name}: 입력이 비어 건너뜀")
                continue
            saved[name] = (u, p)
        u, p = saved[name]
        old = keyring.get_password(CRED_SERVICE, f"{name}:user")
        if old and old != u:
            try:
                keyring.delete_password(CRED_SERVICE, f"{name}:{old}")
            except Exception:  # noqa
                pass
        keyring.set_password(CRED_SERVICE, f"{name}:user", u)
        keyring.set_password(CRED_SERVICE, f"{name}:{u}", p)
        print(f"  ✔ {name} 저장 ({u})")
    print("\n완료. 비밀번호를 바꾸면 set_login.bat을 다시 실행하세요.")


def clear_login():
    if not _need_keyring():
        return
    import keyring
    for name in ("Confluence", "Codebeamer"):
        u = keyring.get_password(CRED_SERVICE, f"{name}:user")
        for k in ([f"{name}:{u}"] if u else []) + [f"{name}:user"]:
            try:
                keyring.delete_password(CRED_SERVICE, k)
            except Exception:  # noqa
                pass
    print("저장된 로그인 정보를 삭제했습니다.")


# =====================================================================
# 2. CI list 읽기
# =====================================================================
COLS = {"category": "category", "ciId": "ciid", "trackerKey": "trackerkey", "ciName": "ciname",
        "author": "author", "repository": "repository", "path": "pathinrepository"}


def col_index(letter):
    n = 0
    for ch in letter.upper():
        n = n * 26 + ord(ch) - 64
    return n - 1


def _cellstr(v):
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def _formula_link(f):
    m = re.search(r'HYPERLINK\(\s*"([^"]+)"', str(f or ""), re.I)
    return m.group(1) if m else ""


def grid_openpyxl(xlsx_bytes):
    """일반 xlsx → [(시트명, 행 목록)] / 셀 = (값, 링크). 열 위치는 A열=0 기준."""
    from openpyxl import load_workbook
    wb_v = load_workbook(io.BytesIO(xlsx_bytes), data_only=True)
    wb_f = load_workbook(io.BytesIO(xlsx_bytes), data_only=False)
    out = []
    for ws in wb_v.worksheets:
        wf = wb_f[ws.title]
        rows = []
        for r in ws.iter_rows():
            row = []
            for c in r:
                link = c.hyperlink.target if c.hyperlink and c.hyperlink.target else ""
                if not link:
                    link = _formula_link(wf.cell(row=c.row, column=c.column).value)
                row.append((_cellstr(c.value), link))
            rows.append(row)
        out.append((ws.title, rows))
    return out


def _as2d(v):
    if v is None:
        return ((None,),)
    if not isinstance(v, tuple):
        return ((v,),)
    return v


def grid_excel(path, visible=True, max_rows=5000, excel_factory=None):
    """DRM(Fasoo) 파일 → PC의 엑셀로 읽기 전용으로 열어 값·링크만 읽고 저장 없이 닫는다."""
    if excel_factory is None:
        import pythoncom
        import win32com.client as w32
        pythoncom.CoInitialize()
        excel_factory = lambda: w32.DispatchEx("Excel.Application")  # noqa: E731  사용자가 연 엑셀과 분리된 새 인스턴스
    xl = excel_factory()
    out = []
    wb = None
    try:
        xl.DisplayAlerts = False
        xl.Visible = visible
        wb = xl.Workbooks.Open(str(path), 0, True)  # UpdateLinks=0, ReadOnly=True
        for ws in wb.Worksheets:
            ur = ws.UsedRange
            r0, c0 = ur.Row, ur.Column
            nrows, ncols = ur.Rows.Count, ur.Columns.Count
            rng = ur if nrows <= max_rows else ws.Range(ws.Cells(r0, c0), ws.Cells(r0 + max_rows - 1, c0 + ncols - 1))
            vals, forms = _as2d(rng.Value), _as2d(rng.Formula)
            links = {}
            for h in ws.Hyperlinks:
                try:
                    links[(h.Range.Row, h.Range.Column)] = h.Address or ""
                except Exception:  # noqa
                    pass
            rows = []
            for i, vr in enumerate(vals):
                row = [("", "")] * (c0 - 1)
                for j, v in enumerate(vr):
                    link = links.get((r0 + i, c0 + j)) or _formula_link(forms[i][j] if i < len(forms) and j < len(forms[i]) else "")
                    row.append((_cellstr(v), link))
                rows.append(row)
            out.append((ws.Name, rows))
    finally:
        try:
            if wb is not None:
                wb.Close(False)  # 저장하지 않음
        finally:
            xl.Quit()
    return out


def is_drm(data):
    return not data[:2] == b"PK"


def read_ci_list(data, cfg, saved_path=None, excel_factory=None):
    if is_drm(data):
        head = data[:64].decode("latin-1", "replace")
        if saved_path is None:
            raise ValueError("DRM 파일인데 저장 경로가 없습니다.")
        kind = "Fasoo DRM" if ("DRMONE" in head or "Fasoo" in head) else "알 수 없는 형식"
        log(f"   CI list가 {kind} 파일 → PC의 엑셀로 읽기 전용으로 열어 읽습니다 (저장 안 함)")
        sheets = grid_excel(saved_path, visible=cfg.get("excel", {}).get("visible", True), excel_factory=excel_factory)
    else:
        sheets = grid_openpyxl(data)
    return ci_from_grid(sheets, cfg)


def ci_from_grid(sheets, cfg):
    c = cfg["ci_list"]
    for title, rows in sheets:
        hi = next((i for i, r in enumerate(rows[:60])
                   if {"ciid", "pathinrepository"} <= {norm(x[0]) for x in r}), None)
        if hi is None:
            continue
        h = [norm(x[0]) for x in rows[hi]]
        idx = {k: (h.index(v) if v in h else -1) for k, v in COLS.items()}
        missing = [k for k in ("category", "ciId", "ciName", "author", "path") if idx[k] < 0]
        if missing:
            raise ValueError(f"CI list 필수 열 없음: {missing}")
        pbl_h = norm(c.get("pbl_header", "PBL"))
        pbl = h.index(pbl_h) if pbl_h in h else col_index(c.get("pbl_fallback_column", "O"))
        pbl_label = rows[hi][pbl][0] if pbl < len(rows[hi]) and rows[hi][pbl][0] else f"({c.get('pbl_fallback_column', 'O')}열)"

        all_cis = []
        prev_cat = ""
        for r in rows[hi + 1:]:
            def g(j):
                return "" if j < 0 or j >= len(r) else r[j][0]
            ci = {k: g(idx[k]) for k in COLS}
            ci["pbl"] = g(pbl)
            if not (ci["ciId"] or ci["path"]):
                continue
            if "/tracker/" not in ci["path"]:
                j = idx["path"]
                if j < len(r) and r[j][1]:
                    ci["path"] = r[j][1]
            if ci["category"]:
                prev_cat = ci["category"]
            else:  # 병합 셀: 맨 윗줄에만 값이 있음 → 위 행 값 이어받기
                ci["category"] = prev_cat
            ci["category"] = category_of(ci["category"])
            ci["trackerId"] = tracker_id_of(ci["path"])
            all_cis.append(ci)
        pbl_ok = [x for x in all_cis if x["pbl"]]
        cis = [x for x in pbl_ok if is_codebeamer(x)] if c.get("codebeamer_only", True) else pbl_ok
        info = {"sheet": title, "total": len(all_cis), "pbl_column": str(pbl_label),
                "no_pbl": len(all_cis) - len(pbl_ok), "non_codebeamer": len(pbl_ok) - len(cis), "targets": len(cis)}
        return cis, info
    raise ValueError("CI ID와 Path in Repository 열이 있는 시트를 찾지 못했습니다.")


# =====================================================================
# 3. 조회 계층 (fetch_json: url 목록 → [{s,b}|{s,html}|{s:0,e}])
# =====================================================================
class NeedLogin(Exception):
    pass


class ApiError(Exception):
    pass


class Client:
    def __init__(self, fetch_json, base, batch=10, retry=3, sleep=time.sleep, relogin=None):
        self.fetch_json, self.base, self.batch, self.retry, self.sleep = fetch_json, base.rstrip("/"), batch, retry, sleep
        self.relogin = relogin

    def get_many(self, paths):
        """paths 순서대로 (ok, json|에러문구) 반환. 일시 오류는 재시도."""
        out = [None] * len(paths)
        pending = list(range(len(paths)))
        for attempt in range(self.retry + 1):
            nxt = []
            for k in range(0, len(pending), self.batch):
                chunk = pending[k:k + self.batch]
                urls = [self.base + paths[i] for i in chunk]
                res = self.fetch_json(urls)
                if self.relogin and any(r.get("html") or r.get("s") in (401, 403) for r in res):
                    log("   세션 만료 → 다시 로그인 후 이어서 진행")
                    self.relogin()
                    res = self.fetch_json(urls)
                for i, r in zip(chunk, res):
                    s = r.get("s", 0)
                    if r.get("html") or s in (401, 403):
                        raise NeedLogin(paths[i])
                    if "b" in r and 200 <= s < 300:
                        out[i] = (True, r["b"])
                    elif (s == 0 or s == 429 or s >= 500) and attempt < self.retry:
                        nxt.append(i)
                    else:
                        out[i] = (False, f"HTTP {s} {r.get('e', '')}".strip())
            if not nxt:
                break
            pending = nxt
            self.sleep(1.5 * (attempt + 1))
        return out

    def get(self, path):
        ok, v = self.get_many([path])[0]
        if not ok:
            raise ApiError(f"{v} — {path.split('?')[0]}")
        return v


def cb_items(cl, tids, page_size=500):
    """여러 Tracker의 Item 전체 (중복 제거). tids: Tracker id 하나 또는 목록."""
    tids = [str(x) for x in (tids if isinstance(tids, (list, tuple, set)) else [tids])]
    out = {}
    try:
        for k in range(0, len(tids), 40):
            ids = ",".join(tids[k:k + 40])
            q = f"tracker.id%20IN%20({ids})"
            page, got = 1, 0
            while True:
                r = cl.get(f"/api/v3/items/query?queryString={q}&page={page}&pageSize={page_size}")
                items = r.get("items") or []
                got += len(items)
                for it in items:
                    out.setdefault(it["id"], it)
                if not items or got >= (r.get("total") or 0):
                    break
                page += 1
        return list(out.values())
    except ApiError as e:
        log(f"    · 검색 API 실패({e}) → Tracker 목록 API로 재시도")
    out = {}
    for tid in tids:
        page, got = 1, 0
        while True:
            r = cl.get(f"/api/v3/trackers/{tid}/items?page={page}&pageSize={page_size}")
            refs = r.get("itemRefs") or r.get("items") or []
            res = cl.get_many([f"/api/v3/items/{x['id']}" for x in refs])
            bad = [x["id"] for x, (ok, _) in zip(refs, res) if not ok]
            if bad:
                raise ApiError(f"Item 상세 조회 실패 {len(bad)}건")
            for ok, v in res:
                v.setdefault("tracker", {"id": int(tid)})
                out.setdefault(v["id"], v)
            got += len(refs)
            if not refs or got >= (r.get("total") or 0):
                break
            page += 1
    return list(out.values())


# ---- Tracker 트리 (하위 Tracker 범위) ----
def node_tracker_id(n):
    if not isinstance(n, dict) or n.get("isFolder"):
        return None
    if n.get("trackerId") is not None:
        return str(n["trackerId"])
    if isinstance(n.get("tracker"), dict) and n["tracker"].get("id") is not None:
        return str(n["tracker"]["id"])
    if "tracker" in str(n.get("type", "")).lower() and n.get("id") is not None:
        return str(n["id"])
    return None


def node_children(n):
    return (n.get("children") or n.get("nodes") or []) if isinstance(n, dict) else []


def node_name(n):
    return str(n.get("text") or n.get("name") or (n.get("tracker") or {}).get("name") or "")


def find_path(nodes, target, path=()):
    for n in nodes or []:
        p = path + (n,)
        if node_tracker_id(n) == str(target):
            return p
        r = find_path(node_children(n), target, p)
        if r:
            return r
    return None


def subtree_trackers(n):
    out = []
    tid = node_tracker_id(n)
    if tid:
        out.append(tid)
    for c in node_children(n):
        out += subtree_trackers(c)
    return out


_TREE = {}


def tracker_tree(cl, project_id):
    if project_id not in _TREE:
        r = cl.get(f"/api/v3/trackers/tree?projectId={project_id}")
        _TREE[project_id] = r if isinstance(r, list) else (r.get("children") or r.get("nodes") or r.get("items") or [r])
    return _TREE[project_id]


def resolve_scope(cl, tid, mode):
    """검사할 Tracker 범위.
    mode: 'top_with_descendants'(기본) — 등록 Tracker의 최상위 Tracker(폴더 바로 아래)와 그 아래 전부
          'with_descendants' — 등록 Tracker와 그 아래 전부 / 'tracker_only' — 등록 Tracker만"""
    info = cl.get(f"/api/v3/trackers/{tid}")
    sc = {"root": str(tid), "root_name": info.get("name", ""), "trackers": [str(tid)], "note": "", "ok": True}
    if mode == "tracker_only":
        return sc
    pid = info.get("projectId") or (info.get("project") or {}).get("id")
    try:
        if not pid:
            raise ApiError("Tracker에 프로젝트 정보가 없음")
        path = find_path(tracker_tree(cl, pid), tid)
        if not path:
            raise ApiError("트리에서 Tracker를 찾지 못함")
    except ApiError as e:
        sc["ok"], sc["note"] = False, f"하위 Tracker 확인불가 (트리 조회 실패: {e}) — 등록 Tracker만 검사"
        return sc
    root_i = len(path) - 1
    if mode == "top_with_descendants":
        while root_i > 0 and node_tracker_id(path[root_i - 1]):
            root_i -= 1
    root = path[root_i]
    sc["root"], sc["trackers"] = node_tracker_id(root), subtree_trackers(root)
    sc["root_name"] = node_name(root) or sc["root_name"]
    if sc["root"] != str(tid):
        sc["note"] = f"등록 Tracker는 하위 Tracker → 상위 '{sc['root_name']}'({sc['root']}) 기준으로 검사"
    return sc


def _dist(items):
    d = {}
    for it in items:
        k = type_of(it) or "(유형 없음)"
        d[k] = d.get(k, 0) + 1
    return " · ".join(f"{k} {v}" for k, v in sorted(d.items(), key=lambda x: -x[1]))


def counterpart_types(cl, ids, known, cache):
    """연결 상대 Item의 유형 확인. known(같은 범위 Item) → cache(이번 실행에서 조회한 것) → 상세 GET 순.
    반환: {id: item dict 또는 None(조회 실패)}"""
    need = sorted({i for i in ids if i is not None and i not in known and i not in cache})
    if need:
        for i, (ok, v) in zip(need, cl.get_many([f"/api/v3/items/{i}" for i in need])):
            cache[i] = v if ok and isinstance(v, dict) else None
    return {i: (known[i] if i in known else cache.get(i)) for i in ids if i is not None}


def judge_links(tids, types, exclude):
    """연결 상대 번호(tids)와 유형으로 판정.
    'linked' = Folder·Information이 아닌 상대가 1개 이상 / 'only_excluded' = 상대가 모두 Folder·Information
    / 'unknown' = 유효한 상대가 없고, 번호나 유형을 확인하지 못한 상대가 있음 / 'none' = 연결 0개"""
    if not tids:
        return "none"
    unresolved = False
    for i in tids:
        it = types.get(i) if i is not None else None
        if it is None:
            unresolved = True
        elif not is_excluded(it, exclude):
            return "linked"
    return "unknown" if unresolved else "only_excluded"


def rel_rest_pages(cl, iid, first, max_pages=200):
    """relations 응답이 여러 페이지면(isLastPage=false) 나머지 페이지를 받아 합친다. 실패하면 None."""
    merged = {k: list(v) for k, v in first.items() if isinstance(v, list)}
    v, n = first, int(first.get("page") or 1)
    size = first.get("pageSize")
    while v.get("isLastPage") is False:
        n += 1
        if n > max_pages:
            return None
        q = f"?page={n}" + (f"&pageSize={size}" if size else "")
        ok, v = cl.get_many([f"/api/v3/items/{iid}/relations{q}"])[0]
        if not ok or not isinstance(v, dict):
            return None
        for k, lst in v.items():
            if isinstance(lst, list):
                merged.setdefault(k, []).extend(lst)
    return merged


def check_ci(cl, ci, exclude, sample=10, scope_mode="top_with_descendants", type_cache=None):
    """CI 1개 판정 (CI의 Tracker 범위 전체). 실패 시 status='확인불가: …'"""
    import random
    type_cache = {} if type_cache is None else type_cache
    r = dict(ci, key=ci.get("trackerKey", ""), keymap={}, total=0, excluded=0, denom=0,
             unlinked=[], unknown=[], status="완료", dist_target="", dist_excl="", sample=[],
             scope_root="", scope_name="", scope_note="", trackers=[], unset=[],
             only_excluded=[], unknown_reason={})
    if not ci["trackerId"]:
        r["status"] = "확인불가: Path in Repository에서 Tracker 번호를 찾을 수 없음"
        return r
    try:
        try:
            sc = resolve_scope(cl, ci["trackerId"], scope_mode)
        except ApiError as e:
            r["status"] = f"확인불가: Tracker 조회 실패 ({e})"
            return r
        r["scope_root"], r["scope_name"], r["scope_note"] = sc["root"], sc["root_name"], sc["note"]
        tinfo = {}
        for tid in sc["trackers"]:
            try:
                ti = cl.get(f"/api/v3/trackers/{tid}")
            except ApiError:
                ti = {}
            tinfo[tid] = {"id": tid, "name": ti.get("name", ""), "key": ti.get("keyName", ""),
                          "total": 0, "excluded": 0, "denom": 0, "unlinked": 0, "unknown": 0,
                          "unset": 0, "unset_unlinked": 0, "has_type": has_type_field(cl, tid)}
        r["key"] = tinfo.get(str(ci["trackerId"]), {}).get("key") or r["key"]
        items = cb_items(cl, sc["trackers"])
        in_scope = set(sc["trackers"])

        def tid_of(it):
            x = str((it.get("tracker") or {}).get("id") or "")
            return x if x in in_scope else sc["root"]
        for it in items:
            tid = tid_of(it)
            r["keymap"][it["id"]] = tinfo[tid]["key"] if tid in tinfo else r["key"]
            tinfo.setdefault(tid, {"id": tid, "name": "", "key": "", "total": 0, "excluded": 0, "denom": 0, "unlinked": 0,
                                   "unknown": 0, "unset": 0, "unset_unlinked": 0, "has_type": False})
            tinfo[tid]["total"] += 1
        targets = [it for it in items if not is_excluded(it, exclude)]
        r["total"], r["excluded"] = len(items), len(items) - len(targets)
        for it in items:
            if is_excluded(it, exclude):
                tinfo[tid_of(it)]["excluded"] += 1
        r["dist_target"] = _dist(targets)
        r["dist_excl"] = _dist([it for it in items if is_excluded(it, exclude)])
        res = cl.get_many([f"/api/v3/items/{it['id']}/relations" for it in targets])
        # 연결 상대의 유형 확인 (상대가 Folder·Information이면 유효한 연결이 아님)
        known = {int(it["id"]): it for it in items}
        rels = {it["id"]: (rel_targets(v) if ok else None) for it, (ok, v) in zip(targets, res)}
        # 같은 범위 안에서 유효한 상대가 이미 확인된 Item은 바깥 상대의 유형 조회를 생략
        need = []
        for tids in rels.values():
            if tids and not any(i in known and not is_excluded(known[i], exclude) for i in tids if i is not None):
                need += tids
        types = counterpart_types(cl, need, known, type_cache)
        types.update({i: known[i] for tids in rels.values() for i in (tids or []) if i in known})
        verdicts = {it["id"]: (judge_links(rels[it["id"]], types, exclude) if ok else "fail") for it, (ok, v) in zip(targets, res)}
        # 첫 페이지에서 유효한 연결을 못 찾았고 다음 페이지가 있으면 → 나머지 페이지까지 확인 (관계 Pagination 끝까지)
        more = []
        for it, (ok, v) in zip(targets, res):
            if ok and verdicts[it["id"]] != "linked" and isinstance(v, dict) and v.get("isLastPage") is False:
                full = rel_rest_pages(cl, it["id"], v)
                if full is None:
                    verdicts[it["id"]] = "unknown"
                else:
                    rels[it["id"]] = rel_targets(full)
                    more.append(it["id"])
        if more:
            types.update(counterpart_types(cl, [i for x in more for i in rels[x]], known, type_cache))
            for x in more:
                verdicts[x] = judge_links(rels[x], types, exclude)
        linked = []
        for it, (ok, v) in zip(targets, res):
            ti = tinfo[tid_of(it)]
            verdict = verdicts[it["id"]]
            if ti["has_type"] and type_unset(it):  # Type '--' : 판정은 그대로, 따로 집계·표시
                r["unset"].append(it["id"]); ti["unset"] += 1
                if verdict in ("none", "only_excluded"):
                    ti["unset_unlinked"] += 1
            if verdict in ("fail", "unknown"):
                r["unknown"].append(it["id"]); ti["unknown"] += 1
                r["unknown_reason"][it["id"]] = ("연결 조회 실패" if verdict == "fail" else
                                                 "연결 상대의 Item 번호 또는 유형을 확인하지 못함 (유효한 연결 미확인)")
            elif verdict in ("none", "only_excluded"):
                r["unlinked"].append(it["id"]); ti["unlinked"] += 1; ti["denom"] += 1
                if verdict == "only_excluded":
                    r["only_excluded"].append(it["id"])
            else:
                linked.append((it["id"], rel_count(v), type_of(it))); ti["denom"] += 1
        rnd = random.Random(f"{ci['trackerId']}-{time.strftime('%Y%m%d')}")
        r["sample"] = sorted(rnd.sample(linked, min(sample, len(linked))))
        r["denom"] = len(targets) - len(r["unknown"])
        r["trackers"] = [tinfo[t] for t in sc["trackers"] if t in tinfo]
        if not targets:
            r["status"] = "판정 대상 Item 없음"
        elif r["unknown"]:
            r["status"] = f"일부 확인불가 {len(r['unknown'])}건"
        if not sc["ok"]:
            r["status"] = "일부 확인불가: 하위 Tracker" if r["status"] == "완료" else r["status"] + " · 하위 Tracker 확인불가"
    except NeedLogin:
        raise
    except Exception as e:  # noqa
        r["status"] = f"확인불가: {e}"
    return r


def item_label(r, iid):
    k = (r.get("keymap") or {}).get(iid) or r["key"]
    return f"{k}-{iid}" if k else str(iid)


# =====================================================================
# 4. 엑셀 (Gap Matrix)
# =====================================================================
def build_workbook(results, meta, prev, cb_base):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter, quote_sheetname

    HF, HFont = PatternFill("solid", fgColor="00B0F0"), Font(bold=True, color="FFFFFF")
    LINK, RED, GRAY = Font(color="0563C1", underline="single"), PatternFill("solid", fgColor="FFC7CE"), PatternFill("solid", fgColor="E7E6E6")

    def sheet(wb, title, header, widths):
        ws = wb.create_sheet(title)
        ws.append(header)
        for i, w in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(i)].width = w
            ws.cell(1, i).fill, ws.cell(1, i).font = HF, HFont
            ws.cell(1, i).alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.freeze_panes = "A2"
        return ws

    def finish(ws):
        ws.auto_filter.ref = ws.dimensions

    def link(cell, url, text=None):
        cell.value = text if text is not None else url
        if url:
            cell.hyperlink, cell.font = url, LINK

    wb = Workbook()
    wb.remove(wb.active)
    cats = list(dict.fromkeys(r["category"] for r in results))  # 탭 순서 = CI list(CI ID) 순서
    names = {}
    for c in cats:
        n = re.sub(r"[\\/?*\[\]:]", "_", c)[:31]
        while n.lower() in {"overview", "tracker별", "변동", "검수", "확인불가", "실행정보"} | {v.lower() for v in names.values()}:
            n = (n[:28] + "_2")
        names[c] = n

    # Overview
    ov = sheet(wb, "Overview", ["CI ID", "Category", "Sheet", "CI Name", "Author", "분모(판정대상)", "미추적", "커버리지(%)",
                                 "제외(Folder/Information)", "확인불가", "상태", "Path in Repository",
                                 "전체 Item", "판정 대상 유형 분포", "제외 유형 분포",
                                 "검사 범위(최상위 Tracker)", "Tracker 수", "범위 메모",
                                 "Type 미지정(--)", "미추적 중 Type 미지정(--)", "미추적 중 Folder/Information에만 연결"],
               [22, 10, 10, 40, 12, 14, 9, 12, 14, 10, 26, 55, 10, 40, 40, 40, 10, 50, 14, 18, 20])
    for r in results:
        cov = coverage(r["denom"], len(r["unlinked"])) if r["status"] == "완료" or r["status"].startswith("일부") else None
        ov.append([r["ciId"], r["category"], None, r["ciName"], r["author"],
                   r["denom"] if cov is not None else None, len(r["unlinked"]) if cov is not None else None, cov,
                   r["excluded"] if cov is not None else None, len(r["unknown"]) or None, r["status"], None,
                   r["total"] if cov is not None else None, r.get("dist_target", ""), r.get("dist_excl", ""),
                   None, len(r.get("trackers") or []) or None, r.get("scope_note", ""),
                   (len(r.get("unset") or []) if cov is not None else None),
                   (len(set(r.get("unset") or []) & set(r["unlinked"])) if cov is not None else None),
                   (len(r.get("only_excluded") or []) if cov is not None else None)])
        row = ov.max_row
        link(ov.cell(row, 3), f"#{quote_sheetname(names[r['category']])}!A1", names[r["category"]])
        link(ov.cell(row, 12), r["path"])
        if r.get("scope_root"):
            link(ov.cell(row, 16), f"{cb_base}/tracker/{r['scope_root']}", f"{r.get('scope_name', '')} ({r['scope_root']})")
        if r.get("scope_note"):
            ov.cell(row, 18).fill = PatternFill("solid", fgColor="FFF2CC")
        if set(r.get("unset") or []) & set(r["unlinked"]):
            ov.cell(row, 20).fill = PatternFill("solid", fgColor="FFF2CC")
        ov.cell(row, 8).number_format = "0.0"
        if r["unlinked"]:
            ov.cell(row, 7).fill = RED
        if r["status"].startswith("확인불가") or r["unknown"]:
            ov.cell(row, 11).fill = GRAY
    finish(ov)

    # Category 탭 (사용자 양식: CI ID / CI name / Author / Path in Repository / Item ID)
    for c in cats:
        ws = sheet(wb, names[c], ["CI ID", "CI name", "Author", "Path in Repository", "Item ID", "비고"], [22, 40, 12, 55, 24, 30])
        for r in [x for x in results if x["category"] == c]:
            unset = set(r.get("unset") or [])
            only_ex = set(r.get("only_excluded") or [])
            for iid in sorted(r["unlinked"]):
                note = " · ".join(x for x in ("Type 미지정(--)" if iid in unset else "",
                                              "Folder/Information에만 연결" if iid in only_ex else "") if x)
                ws.append([r["ciId"], r["ciName"], r["author"], None, None, note or None])
                if note:
                    ws.cell(ws.max_row, 6).fill = PatternFill("solid", fgColor="FFF2CC")
                link(ws.cell(ws.max_row, 4), r["path"])
                link(ws.cell(ws.max_row, 5), f"{cb_base}/issue/{iid}", item_label(r, iid))
        finish(ws)

    # Tracker별 (하위 Tracker 포함 범위의 내역 — Codebeamer 트리의 '전체 수'와 대조용)
    tb = sheet(wb, "Tracker별", ["CI ID", "Category", "Tracker", "Key", "전체 Item", "제외", "분모", "미추적", "커버리지(%)", "확인불가",
                                 "Type 미지정(--)", "미추적 중 Type 미지정(--)"],
               [22, 10, 50, 22, 10, 8, 10, 9, 12, 10, 14, 18])
    for r in results:
        for ti in r.get("trackers") or []:
            tb.append([r["ciId"], r["category"], None, ti["key"], ti["total"], ti["excluded"], ti["denom"], ti["unlinked"],
                       coverage(ti["denom"], ti["unlinked"]), ti["unknown"] or None,
                       ti.get("unset") if ti.get("has_type") else "(Type 필드 없음)", ti.get("unset_unlinked") if ti.get("has_type") else None])
            link(tb.cell(tb.max_row, 3), f"{cb_base}/tracker/{ti['id']}", f"{ti['name']} ({ti['id']})")
            tb.cell(tb.max_row, 9).number_format = "0.0"
            if ti["unlinked"]:
                tb.cell(tb.max_row, 8).fill = RED
    finish(tb)

    # 변동 (직전 실행 대비)
    ch = sheet(wb, "변동", ["CI ID", "Category", "직전 미추적", "현재 미추적", "증감", "신규 미추적 Item", "해소된 Item"],
               [22, 10, 12, 12, 8, 50, 50])
    if prev:
        for r in results:
            p = prev.get("cis", {}).get(r["ciId"])
            if r["status"].startswith("확인불가"):
                continue
            now = set(r["unlinked"])
            before = set(p["unlinked"]) if p else set()
            new, gone = sorted(now - before), sorted(before - now)
            ch.append([r["ciId"], r["category"], len(before) if p else "(신규 CI)", len(now),
                       (len(now) - len(before)) if p else None,
                       ", ".join(item_label(r, i) for i in new), ", ".join(item_label(r, i) for i in gone)])
            if new:
                ch.cell(ch.max_row, 6).fill = RED
    else:
        ch.append(["(직전 실행 기록 없음 — 다음 실행부터 비교)"])
    finish(ch)

    # 검수 — 연결됨으로 판정된 Item 표본 (사람이 링크를 눌러 Relations 확인)
    vf = sheet(wb, "검수", ["CI ID", "Category", "표본 Item (연결됨 판정)", "API 연결 수", "유형", "확인 결과(사람 기입)"],
               [22, 10, 26, 12, 20, 22])
    for r in results:
        for iid, n, ty in r.get("sample", []):
            vf.append([r["ciId"], r["category"], None, n, ty, None])
            link(vf.cell(vf.max_row, 3), f"{cb_base}/issue/{iid}", item_label(r, iid))
    finish(vf)

    # 확인불가
    uk = sheet(wb, "확인불가", ["CI ID", "Category", "Item", "내용"], [22, 10, 24, 80])
    for r in results:
        if r["status"].startswith("확인불가"):
            uk.append([r["ciId"], r["category"], "", r["status"]])
        for iid in r["unknown"]:
            uk.append([r["ciId"], r["category"], item_label(r, iid), (r.get("unknown_reason") or {}).get(iid, "연결 조회 실패")])
    finish(uk)

    # 실행정보
    inf = sheet(wb, "실행정보", ["항목", "값"], [28, 90])
    for k, v in meta.items():
        inf.append([k, str(v)])
    return wb


# =====================================================================
# 5. 브라우저 세션 (Playwright, 로그인 재사용)
# =====================================================================
JS_FETCH = """async (urls) => Promise.all(urls.map(async u => {
  try {
    const r = await fetch(u, {credentials: 'include', headers: {Accept: 'application/json'}});
    const ct = r.headers.get('content-type') || '';
    if (!r.ok) return {s: r.status};
    if (!ct.includes('json')) return {s: r.status, html: true};
    return {s: r.status, b: await r.json()};
  } catch (e) { return {s: 0, e: String(e)}; }
}))"""

JS_BYTES = """async (u) => {
  const r = await fetch(u, {credentials: 'include'});
  if (!r.ok) return {s: r.status};
  const ct = r.headers.get('content-type') || '';
  if (ct.includes('text/html')) return {s: r.status, html: true};
  const b = new Uint8Array(await r.arrayBuffer());
  let bin = ''; for (let i = 0; i < b.length; i += 0x8000) bin += String.fromCharCode.apply(null, b.subarray(i, i + 0x8000));
  return {s: r.status, b64: btoa(bin)};
}"""


class Session:
    def __init__(self, ctx, name, home_url, login_url="", interactive=True, cred=None):
        self.name, self.home, self.login_url, self.interactive, self.cred = name, home_url, login_url, interactive, cred
        self.page = ctx.new_page()
        self.page.goto(home_url, wait_until="domcontentloaded")

    def _eval(self, js, arg):
        """화면이 이동 중이면(로그인 직후 리다이렉트 등) 안정될 때까지 기다렸다 재시도"""
        last = None
        for attempt in range(8):
            try:
                return self.page.evaluate(js, arg)
            except Exception as e:  # noqa
                msg = str(e)
                if not re.search(r"context was destroyed|navigat|Target closed|frame was detached", msg, re.I):
                    raise
                last = e
                try:
                    self.page.wait_for_load_state("load", timeout=15000)
                except Exception:  # noqa
                    pass
                time.sleep(1 + attempt)
        raise ApiError(f"{self.name} 화면이 계속 이동 중이라 조회하지 못했습니다 ({last})")

    def pin(self, url):
        """조회 전용 탭: 스스로 이동하지 않는 같은 사이트 주소에 고정 (화면 스크립트의 리다이렉트 영향 제거)"""
        try:
            self.page.goto(url, wait_until="load")
        except Exception:  # noqa
            pass

    def fetch_json(self, urls):
        return self._eval(JS_FETCH, urls)

    def fetch_bytes(self, url):
        r = self._eval(JS_BYTES, url)
        if r.get("html") or r.get("s") in (401, 403):
            raise NeedLogin(url)
        if "b64" not in r:
            raise ApiError(f"다운로드 실패 HTTP {r.get('s')}")
        return base64.b64decode(r["b64"])

    def _fill_login(self, url):
        self.page.goto(url, wait_until="domcontentloaded")
        pwd = self.page.locator("input[type=password]").first
        try:
            pwd.wait_for(state="visible", timeout=10000)
        except Exception:  # noqa
            return False
        form = pwd.locator("xpath=ancestor::form[1]")
        scope = form if form.count() else self.page
        users = scope.locator("input[type=text], input[type=email], input:not([type])")
        user_box = next((users.nth(i) for i in range(users.count()) if users.nth(i).is_visible()), None)
        if user_box is None:
            return False
        user_box.fill(self.cred[0])
        pwd.fill(self.cred[1])
        pwd.press("Enter")
        try:
            self.page.wait_for_load_state("load", timeout=30000)
        except Exception:  # noqa
            pass
        time.sleep(1.5)
        return True

    def auto_login(self):
        """저장된 ID/PW로 로그인 화면을 채운다. 로그인 주소에 입력칸이 없으면 첫 화면에서 다시 찾음."""
        if not self.cred:
            return False
        log(f"   {self.name} 자동 로그인 ({self.cred[0]})")
        for url in [u for u in (self.login_url, self.home) if u]:
            if self._fill_login(url):
                return True
        log(f"   ⚠ {self.name} 로그인 입력칸을 찾지 못했습니다")
        return False

    def ensure_login(self, base, probe, logged_in):
        """probe 응답으로 로그인 여부 판단. 미로그인 → 자동 로그인(저장된 ID/PW) → 안 되면 창에서 직접 로그인."""
        last = None
        auto_tries = 0
        for attempt in range(5):
            r = self.fetch_json([base + probe])[0]
            last = r
            if "b" in r and logged_in(r["b"]):
                return
            need = r.get("html") or r.get("s") in (401, 403, 404) or ("b" in r)
            if not need:
                raise ApiError(f"{self.name} 접속 실패 HTTP {r.get('s')} {r.get('e', '')} — {base + probe}")
            if self.cred and auto_tries < 2:
                auto_tries += 1
                if self.auto_login():
                    continue
            if self.cred and auto_tries >= 2:
                log(f"   ⚠ {self.name} 자동 로그인 실패 — ID/PW가 바뀌었다면 set_login.bat을 다시 실행하세요")
            if not self.interactive:
                raise NeedLogin(self.name)
            self.page.bring_to_front()
            if attempt:
                log(f"   아직 로그인이 확인되지 않습니다 (HTTP {r.get('s')}).")
            log(f"▶ 브라우저 창에서 {self.name}에 로그인한 뒤, 이 검은 창으로 돌아와 Enter를 누르세요.")
            input()
            if self.page.url.startswith(base):
                self.page.reload(wait_until="domcontentloaded")
            else:
                self.page.goto(self.home, wait_until="domcontentloaded")
        raise ApiError(f"{self.name} 로그인 확인 실패 (마지막 응답 HTTP {last.get('s')}) — {base + probe}")


# =====================================================================
# 6. 실행
# =====================================================================
def latest_xlsx(attachments, base):
    rows = []
    for a in attachments.get("results", []):
        if not re.search(r"\.xls[xm]$", a.get("title", ""), re.I):
            continue
        when = (a.get("version") or {}).get("when", "")
        try:
            ts = dt.datetime.fromisoformat(when.replace("Z", "+00:00")).timestamp()
        except ValueError:
            ts = 0
        link_base = (attachments.get("_links") or {}).get("base") or base
        rows.append({"title": a["title"], "when": when, "ts": ts,
                     "by": ((a.get("version") or {}).get("by") or {}).get("displayName", ""),
                     "url": link_base + (a.get("_links") or {}).get("download", "")})
    rows.sort(key=lambda x: -x["ts"])
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description="AUTO-001 추적성 Gap Matrix")
    ap.add_argument("--doctor", action="store_true", help="연결 점검만 (파일 생성 없음)")
    ap.add_argument("--ci", action="append", help="이 CI ID만 검사 (여러 번 지정 가능)")
    ap.add_argument("--limit", type=int, help="앞에서 N개 CI만 (시험용)")
    ap.add_argument("--headless", action="store_true", help="브라우저 창 숨김 (로그인 저장된 뒤에만)")
    ap.add_argument("--config", default=str(HERE / "config.json"))
    ap.add_argument("--set-login", action="store_true", help="로그인 ID/PW 저장 (Windows 자격 증명 관리자)")
    ap.add_argument("--clear-login", action="store_true", help="저장된 로그인 정보 삭제")
    a = ap.parse_args(argv)
    if a.set_login:
        set_login()
        return 0
    if a.clear_login:
        clear_login()
        return 0
    cfg_path = Path(a.config)
    if not cfg_path.exists():
        raise ValueError(f"설정 파일이 없습니다: {cfg_path.name} — config.example.json을 복사해 config.json을 만들고 "
                         "Confluence·Codebeamer 주소와 CI list 페이지 번호를 넣어 주세요.")
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    STATE.mkdir(exist_ok=True)
    (STATE / "ci_list").mkdir(exist_ok=True)
    out_dir = (HERE / cfg.get("output_dir", "output"))
    out_dir.mkdir(exist_ok=True)
    exclude = {t.lower() for t in cfg["judge"]["exclude_types"]}
    t0 = time.time()

    from playwright.sync_api import sync_playwright
    log(f"AUTO-001 추적성 Gap Matrix v{VERSION} 시작{' (점검 모드)' if a.doctor else ''}")
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(STATE / "browser-profile"), channel=cfg["browser"].get("channel") or None,
            headless=a.headless, viewport={"width": 1280, "height": 860})
        try:
            # ① Confluence — 최신 CI list
            cf = cfg["confluence"]
            pid = cf["ci_list_page_id"]
            conf = Session(ctx, "Confluence", f"{cf['base']}/pages/viewpage.action?pageId={pid}",
                           cf['base'] + cf.get("login_path", "/login.action"), not a.headless, get_cred("Confluence"))
            conf.ensure_login(cf["base"], "/rest/api/user/current",
                              lambda b: b.get("type") != "anonymous" and bool(b.get("username") or b.get("userKey") or b.get("displayName")))
            ccl = Client(conf.fetch_json, cf["base"])
            try:
                pg = ccl.get(f"/rest/api/content/{pid}")
            except ApiError as e:
                raise ApiError(f"CI list 페이지(pageId {pid})를 열 수 없습니다 — 페이지 번호가 바뀌었거나 열람 권한이 없습니다. ({e})")
            log(f"① Confluence 로그인 확인 — 페이지 '{pg.get('title', '')}'")
            atts = latest_xlsx(ccl.get(f"/rest/api/content/{pid}/child/attachment?expand=version&limit=200"), cf["base"])
            if not atts:
                raise ApiError("CI list 페이지에 엑셀 첨부 파일이 없습니다.")
            latest = atts[0]
            log(f"① 최신 CI list: {latest['title']} (업로드 {latest['when'][:16].replace('T', ' ')} {latest['by']})")
            data = conf.fetch_bytes(latest["url"])
            saved = STATE / "ci_list" / f"{time.strftime('%Y%m%d_%H%M')}_{latest['title']}"
            saved.write_bytes(data)

            # ② CI 선별
            cis, info = read_ci_list(data, cfg, saved_path=saved)
            log(f"② 시트 '{info['sheet']}' 전체 {info['total']}행 → PBL 없음 제외 {info['no_pbl']} · "
                f"Codebeamer 아님 건너뜀 {info['non_codebeamer']} → 검사 대상 {info['targets']}개 (PBL 기준: {info['pbl_column']})")
            if a.ci:
                want = {x.strip() for x in a.ci}
                cis = [c for c in cis if c["ciId"] in want]
                missing = want - {c["ciId"] for c in cis}
                if missing:
                    log(f"   ⚠ 대상에 없는 CI: {', '.join(sorted(missing))}")
            if a.limit:
                cis = cis[:a.limit]
            if not cis:
                raise ApiError("검사할 CI가 없습니다.")

            # ③④ Codebeamer
            cb = cfg["codebeamer"]
            first = next((c for c in cis if c["trackerId"]), None)
            cbs = Session(ctx, "Codebeamer", cb["base"], cb["base"] + cb.get("login_path", "/login.spr"),
                          not a.headless, get_cred("Codebeamer"))
            probe = f"/api/v3/trackers/{first['trackerId'] if first else 0}"

            def cb_login():
                cbs.ensure_login(cb["base"], probe, lambda b: bool(b.get("id")))
                if first:
                    cbs.pin(cb["base"] + probe)
            cb_login()
            log("③ Codebeamer 로그인 확인")
            ccb = Client(cbs.fetch_json, cb["base"], batch=cfg.get("batch_size", 10), relogin=cb_login)

            if a.doctor:
                c = first
                if not a.ci and not a.headless:
                    log("   점검할 CI ID를 입력하세요 (Enter = 첫 번째 CI " + first["ciId"] + "):")
                    want = input().strip()
                    c = next((x for x in cis if x["ciId"] == want and x["trackerId"]), first)
                t = ccb.get(f"/api/v3/trackers/{c['trackerId']}")
                mode = cfg.get("scope", "top_with_descendants")
                sc = resolve_scope(ccb, c["trackerId"], mode)
                log(f"  검사 범위({mode}): 최상위 '{sc['root_name']}'({sc['root']}) · Tracker {len(sc['trackers'])}개 {('— ' + sc['note']) if sc['note'] else ''}")
                for x in sc["trackers"][:30]:
                    try:
                        xi = ccb.get(f"/api/v3/trackers/{x}")
                        log(f"    - {xi.get('name', '')} ({x}) key {xi.get('keyName', '')}")
                    except ApiError as e:
                        log(f"    - ({x}) 조회 실패 {e}")
                items = cb_items(ccb, sc["trackers"])
                log(f"✔ Codebeamer 정상 — {c['ciId']} / key {t.get('keyName')} / Item {len(items)}개")
                srcs = {}
                for it in items:
                    for k, vs in type_sources(it).items():
                        for v in vs:
                            srcs.setdefault(k, {})[v] = srcs.setdefault(k, {}).get(v, 0) + 1
                if not srcs:
                    log("  ⚠ Item에서 유형 값을 찾지 못했습니다 → Folder/Information 제외가 동작하지 않습니다")
                for k, d in srcs.items():
                    log(f"  유형 값 [{k}]: " + ", ".join(f"{v} {n}" for v, n in sorted(d.items(), key=lambda x: -x[1])))
                try:
                    opts = type_field_options(ccb, c["trackerId"])
                except ApiError as e:
                    opts = []
                    log(f"  ⚠ Type 필드 정의 조회 실패: {e}")
                for o in opts:
                    log(f"  Type 선택지 [{o['field']}] id={o['id']} '{o['name']}' meaning={o['meaning'] or '(없음)'}  (항목: {', '.join(o['keys'])})")
                excl_ids = excluded_option_ids(opts, exclude)
                fuzzy = sorted({v for it in items for v in type_labels(it)
                                if name_excluded(v, exclude) and v.lower() not in exclude})
                if fuzzy:
                    log(f"  ※ 철자가 다른 이름도 제외로 처리: {', '.join(fuzzy)}")
                exc = sum(1 for it in items if is_excluded(it, exclude, excl_ids))
                log(f"  → 제외(Folder/Information) {exc}개 · 판정 대상 {len(items) - exc}개")
                log("    (검수: Traceability Report에 같은 Tracker를 필터 걸고 GO 했을 때 왼쪽 Item 수와 '판정 대상'이 같아야 함)")
                if items:
                    log("  Item 필드 이름: " + ", ".join(sorted(items[0].keys())))
                tgt = next((it for it in items if not is_excluded(it, exclude, excl_ids)), None)
                if tgt:
                    rel = ccb.get(f"/api/v3/items/{tgt['id']}/relations")
                    log(f"  연결 조회 필드: {', '.join(rel.keys())}")
                    # 연결 상대 번호를 읽을 수 있는지 (상대 유형 판정의 전제) — 연결이 있는 Item을 최대 20개 확인
                    shown = False
                    for it in [x for x in items if not is_excluded(x, exclude, excl_ids)][:20]:
                        rv = rel if it is tgt else ccb.get(f"/api/v3/items/{it['id']}/relations")
                        tids = rel_targets(rv)
                        if not tids:
                            continue
                        first_ref = next(x for v in rv.values() if isinstance(v, list) and v for x in v)
                        log(f"  연결 1건의 구조: {', '.join(sorted(first_ref.keys())) if isinstance(first_ref, dict) else type(first_ref).__name__}")
                        if None in tids:
                            log("  ⚠ 연결 상대 Item 번호를 응답에서 찾지 못했습니다 → 이 상태로 실행하면 해당 Item이 확인불가가 됩니다. 이 줄을 Claude에게 전달해 주세요.")
                        else:
                            kn = {int(x["id"]): x for x in items}
                            ty = counterpart_types(ccb, tids, kn, {})
                            log(f"  연결 상대 확인: Item {it['id']} → " + ", ".join(
                                f"{i}({type_of(ty[i]) or '유형 없음'})" if ty.get(i) else f"{i}(조회 실패)" for i in tids[:5])
                                + " → 판정: " + {"linked": "연결", "only_excluded": "미추적(Folder/Information에만 연결)",
                                                 "unknown": "확인불가", "none": "미추적"}[judge_links(tids, ty, exclude)])
                        shown = True
                        break
                    if not shown:
                        log("  (앞쪽 Item 20개에 연결이 없어 연결 상대 확인은 건너뜀)")
                log("✔ 점검 완료 — 이제 run_traceability.bat 으로 전체 실행하세요.")
                return 0

            results = []
            type_cache = {}  # 연결 상대 유형 — 이번 실행 안에서만 재사용
            for n, c in enumerate(cis, 1):
                t1 = time.time()
                r = check_ci(ccb, c, exclude, cfg.get("verify_sample", 10), cfg.get("scope", "top_with_descendants"), type_cache)
                results.append(r)
                cov = coverage(r["denom"], len(r["unlinked"]))
                if r.get("scope_note"):
                    log(f"   ↳ {r['scope_note']} · 하위 포함 Tracker {len(r['trackers'])}개")
                log(f"③ ({n}/{len(cis)}) {c['ciId']:<24} 분모 {r['denom']:>5} · 미추적 {len(r['unlinked']):>4} · "
                    f"커버리지 {cov if cov is not None else '-'}% · {r['status']} ({time.time() - t1:.0f}초)")
        finally:
            ctx.close()

    # ⑤ 엑셀
    prev_path = STATE / "last_run.json"
    prev = json.loads(prev_path.read_text(encoding="utf-8")) if prev_path.exists() else None
    meta = {
        "실행 시각": time.strftime("%Y-%m-%d %H:%M:%S"),
        "도구": f"AUTO-001 traceability.py v{VERSION}",
        "CI list 파일": f"{latest['title']} (Confluence 업로드 {latest['when']} {latest['by']})",
        "CI 선별": f"전체 {info['total']} / PBL 없음 제외 {info['no_pbl']} / Codebeamer 아님 {info['non_codebeamer']} / 검사 {len(results)}"
                 + (" (일부 CI만 지정 실행)" if a.ci or a.limit else ""),
        "검사 범위": {"top_with_descendants": "등록 Tracker의 최상위 Tracker와 그 아래 하위 Tracker 전부",
                   "with_descendants": "등록 Tracker와 그 아래 하위 Tracker 전부",
                   "tracker_only": "등록 Tracker만"}.get(cfg.get("scope", "top_with_descendants"), cfg.get("scope")),
        "Type 미지정(--)": "판정 대상에 포함 (화면 필터와 동일). 결과에서 따로 집계·표시 — Overview·Tracker별 열, Category 탭 비고",
        "판정 규칙": "Item 유형(Type 선택지 이름, 철자 유사·한글 '정보' 포함) Folder·Information 제외 / Up·Downstream Reference + Association 중 "
                     "Folder·Information이 아닌 상대와의 연결 1개 이상 = 연결 (취소·폐기 항목과의 연결 포함) / 상대가 모두 Folder·Information = 미추적 / "
                     "조회 실패·상대 확인 불가 = 확인불가",
        "직전 비교 기준": prev.get("run_at", "-") if prev else "없음",
        "소요 시간": f"{time.time() - t0:.0f}초",
        "주의": "자동 생성 초안입니다. 공식 산출물 반영·저장은 담당자가 검토 후 직접 합니다.",
    }
    wb = build_workbook(results, meta, prev, cfg["codebeamer"]["base"])
    out = out_dir / f"추적성_GapMatrix_{cfg.get('project', '')}_{time.strftime('%Y-%m-%d_%H%M')}.xlsx"
    wb.save(out)
    if not (a.ci or a.limit):
        prev_path.write_text(json.dumps({"run_at": meta["실행 시각"], "cis": {
            r["ciId"]: {"unlinked": r["unlinked"], "denom": r["denom"]} for r in results
            if not r["status"].startswith("확인불가")}}, ensure_ascii=False, indent=1), encoding="utf-8")
    tot_u = sum(len(r["unlinked"]) for r in results)
    unk = sum(1 for r in results if r["status"] != "완료")
    log(f"⑤ 완료 — CI {len(results)}개 · 미추적 Item {tot_u}개 · 확인불가 포함 CI {unk}개")
    log(f"   결과 파일: {out}")
    return 0


if __name__ == "__main__":
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa
            pass
    try:
        sys.exit(main())
    except NeedLogin as e:
        log(f"✖ 로그인이 필요합니다 ({e}). 창이 보이는 모드로 다시 실행해 로그인해 주세요.")
        sys.exit(2)
    except (ApiError, ValueError) as e:
        log(f"✖ {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        log("중단됨")
        sys.exit(130)

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CL3 점검 — Status · Verification Review(VR) · Defect 해결 (v1.0)

체크리스트 CL3에서 CI마다 세 가지를 확인한다.
  ① Status   : Type이 Information·Folder가 아닌 모든 Item의 Status가 Accepted인가 (상위+하위 Tracker, Type '--' 포함)
  ② VR 수행  : 같은 프로젝트에 'Review_<상위 Tracker 이름>' Tracker가 있고 Review Item이 있는가
  ③ Defect   : Review Item에 연결된 Codebeamer Defect · Jira 이슈 · 첨부 Defect List가 모두 해결되었는가

흐름: Confluence 최신 CI list → PBL CI 선별 → Codebeamer 범위 Tracker Item 전체 Status → Review Tracker 찾기
      → Review Item의 연결·Jira 링크·첨부 엑셀에서 Defect 상태 → 엑셀(요약·Overview·Status NOK·별도 Status·
      Defect·확인 필요·Tracker별·조회 기록·실행정보)

CL1·CL2·CL6과는 별개 도구. 로그인·CI list·Item 조회·Tracker 범위 코드는 같은 방식을 복사해 사용.
원칙: 읽기 전용(GET) · 조회 실패 = 확인불가 · 결과는 항상 새 파일 · 등급(N/P/L/F)은 판정하지 않음

사용:   python cl3_check.py             # 전체 검사 (상위 + 하위 Tracker)
        python cl3_check.py --quick     # 빠른 검사 (①을 CI list에 적힌 Tracker만, 참고용)
        python cl3_check.py --doctor    # 연결·Review 구조 점검 (Review Item 원본을 state/debug에 저장)
        python cl3_check.py --ci CI_ID  # 일부 CI만
"""
import argparse
import base64
import datetime as dt  # noqa: F401  (공통 코드에서 사용)
import difflib
import io
import json
import re
import sys
import time
from pathlib import Path

VERSION = "1.0"
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
    """Tracker 번호. Codebeamer Category(CMDB, /cb/category/번호)도 API상 Tracker라 같은 방식으로 읽는다 (실측 SWE6_03, 2026-11-24)"""
    m = re.search(r"/(?:tracker|category)/(\d+)", path or "")
    return m.group(1) if m else ""


def is_codebeamer(ci):
    return bool(re.search("codebeamer", ci["repository"], re.I)
                or re.search(r"codebeamer|/cb/(tracker|category)/", ci["path"], re.I))

# =====================================================================
# 1-1. 로그인 정보 (Windows 자격 증명 관리자 — 파일에 저장하지 않음)
# =====================================================================
CRED_SERVICE = "AUTO-CL3 status-review"
CRED_FALLBACKS = ("AUTO-CL2 revision-history", "AUTO-CL1 ci-baseline", "AUTO-001 traceability")  # 다른 CL 도구에 저장한 로그인 정보도 사용


def get_cred(name):
    """저장된 ID/PW. CL3 전용 저장값이 없으면 CL2·CL1·추적성 도구(AUTO-001)에 저장한 값을 쓴다. Jira 값이 없으면 Confluence 값을 쓴다."""
    try:
        import keyring
        for svc in (CRED_SERVICE,) + CRED_FALLBACKS:
            user = keyring.get_password(svc, f"{name}:user")
            pw = keyring.get_password(svc, f"{name}:{user}") if user else None
            if user and pw:
                return user, pw
        return get_cred("Confluence") if name == "Jira" else None
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
    print("CL3 점검 로그인 정보 저장 — Windows 자격 증명 관리자에 암호화되어 이 Windows 계정에서만 읽힙니다.")
    print("(비밀번호는 입력해도 화면에 표시되지 않습니다)\n")
    saved = {}
    for name in ("Confluence", "Codebeamer", "Jira"):
        if name != "Confluence" and saved:
            if input(f"{name}도 Confluence와 같은 ID/PW를 씁니까? (Y/n): ").strip().lower() in ("", "y", "yes", "ㅛ"):
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
    for name in ("Confluence", "Codebeamer", "Jira"):
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
        cis = [x for x in all_cis if x["pbl"]] if c.get("pbl_only", True) else all_cis
        info = {"sheet": title, "total": len(all_cis), "pbl_column": str(pbl_label),
                "no_pbl": len(all_cis) - len(cis), "targets": len(cis)}
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


def is_login_html(html, url=""):
    """로그인 화면인가: 비밀번호 입력칸이 있고, 주소나 폼이 로그인용 (전자서명 창 등의 비밀번호 칸과 구분)"""
    if not re.search(r"<input[^>]*type=[\"']?password", html or "", re.I):
        return False
    return bool(re.search(r"log_?in|signin|sso", url or "", re.I)
                or re.search(r"<form[^>]*action=[\"'][^\"']*(log_?in|signin|sso|j_security)", html or "", re.I)
                or len(html or "") < 30000)


JS_TEXT = """async (u) => {
  try {
    const r = await fetch(u, {credentials: 'include'});
    return {s: r.status, t: await r.text(), u: r.url};
  } catch (e) { return {s: 0, t: String(e), u: u}; }
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

    def fetch_text(self, url):
        """화면(HTML) 그대로 받기 — Baseline 목록·속성 화면 해석용. 반환 (HTTP 코드, 본문, 최종 주소)
        실측(2026-11-24): API는 로그인 상태인데 화면 요청만 로그인 화면이 오는 경우가 있음
        → 새 탭에서 주소를 직접 열고, 로그인 화면이면 저장된 ID/PW로 로그인한 뒤 다시 연다."""
        r = self._eval(JS_TEXT, url)
        s, t, u = r.get("s", 0), r.get("t", ""), r.get("u", url)
        if s != 200 or not is_login_html(t, u):
            return s, t, u
        log(f"   {self.name} 화면 요청에 로그인 화면이 와서 브라우저로 직접 열어 다시 시도합니다")
        pg = self.page.context.new_page()
        try:
            pg.goto(url, wait_until="load")
            html, final = pg.content(), pg.url
            if is_login_html(html, final) and self.cred:
                log(f"   {self.name} 화면 다시 로그인 ({self.cred[0]})")
                for lu in [x for x in (self.login_url, url) if x]:
                    if self._fill_login(lu, pg):
                        break
                pg.goto(url, wait_until="load")
                html, final = pg.content(), pg.url
            return (401 if is_login_html(html, final) else 200), html, final
        except Exception as e:  # noqa
            return 0, str(e), url
        finally:
            pg.close()

    def fetch_bytes(self, url):
        r = self._eval(JS_BYTES, url)
        if r.get("html") or r.get("s") in (401, 403):
            raise NeedLogin(url)
        if "b64" not in r:
            raise ApiError(f"다운로드 실패 HTTP {r.get('s')}")
        return base64.b64decode(r["b64"])

    def _fill_login(self, url, page=None):
        page = page or self.page
        page.goto(url, wait_until="domcontentloaded")
        pwd = page.locator("input[type=password]").first
        try:
            pwd.wait_for(state="visible", timeout=10000)
        except Exception:  # noqa
            return False
        form = pwd.locator("xpath=ancestor::form[1]")
        scope = form if form.count() else page
        users = scope.locator("input[type=text], input[type=email], input:not([type])")
        user_box = next((users.nth(i) for i in range(users.count()) if users.nth(i).is_visible()), None)
        if user_box is None:
            return False
        user_box.fill(self.cred[0])
        pwd.fill(self.cred[1])
        pwd.press("Enter")
        try:
            page.wait_for_load_state("load", timeout=30000)
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


# =====================================================================
# 공통 (CL6_Traceability에서 복사) — Type 판단 · Item 전체 조회 · Tracker 범위 · 연결 상대
# =====================================================================
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
    if node_name(root):
        sc["root_name"] = node_name(root)
    elif sc["root"] != str(tid):  # 실측: 트리의 Tracker 노드에는 이름이 없음 → Tracker 정보로 이름 조회
        try:
            sc["root_name"] = cl.get(f"/api/v3/trackers/{sc['root']}").get("name", "") or sc["root_name"]
        except ApiError:
            pass
    if sc["root"] != str(tid):
        sc["note"] = f"등록 Tracker는 하위 Tracker → 상위 '{sc['root_name']}'({sc['root']}) 기준으로 검사"
    return sc



def counterpart_types(cl, ids, known, cache):
    """연결 상대 Item의 유형 확인. known(같은 범위 Item) → cache(이번 실행에서 조회한 것) → 상세 GET 순.
    반환: {id: item dict 또는 None(조회 실패)}"""
    need = sorted({i for i in ids if i is not None and i not in known and i not in cache})
    if need:
        for i, (ok, v) in zip(need, cl.get_many([f"/api/v3/items/{i}" for i in need])):
            cache[i] = v if ok and isinstance(v, dict) else None
    return {i: (known[i] if i in known else cache.get(i)) for i in ids if i is not None}



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




# =====================================================================
# CL3-0. 판정 공통
# =====================================================================
COND = "Conditional OK"
UNK = "확인불가"
MANUAL = "수동 확인"
RANK = {"-": -1, "OK": 0, COND: 1, MANUAL: 1, "확인 필요": 1, UNK: 2, "NOK": 3}


def worst(*rs):
    rs = [r for r in rs if r and r != "-"]
    return max(rs, key=lambda r: RANK.get(r, 0)) if rs else "-"


def hkey(s):
    return re.sub(r"[^0-9a-z가-힣]", "", str(s or "").lower())


def in_list(name, lst):
    return hkey(name) in {hkey(x) for x in lst or []}


def status_name(it):
    st = it.get("status")
    if isinstance(st, dict):
        return str(st.get("name") or "").strip()
    return str(st or "").strip()


def item_url(cb_base, iid):
    return f"{cb_base}/issue/{iid}"


DEFAULTS = {
    "scope": "top_with_descendants",
    "exclude_types": ["Information", "Folder"],
    "accepted_statuses": ["Accepted"],
    "separate_statuses": ["Obsolete", "Rejected", "Deleted"],
    "review_prefix": "Review_",
    "review_ok_ratio": 0.9,
    "review_conditional_ratio": 0.8,
    "defect": {
        "resolved_statuses": ["Closed", "Resolved", "Done", "Fixed", "Verified", "Completed", "Accepted", "완료", "종료", "해결"],
        "deferred_statuses": ["Deferred", "Postponed", "On Hold", "Suspended", "보류", "연기"],
        "defect_tracker_keywords": ["Defect", "Bug", "Issue", "결함", "이슈", "Finding"],
        "list_status_headers": ["Status", "상태", "진행상태", "조치상태", "처리상태"],
    },
}


def cl3_cfg(cfg):
    c = json.loads(json.dumps(DEFAULTS))
    user = cfg.get("cl3") or {}
    for k, v in user.items():
        if k == "defect" and isinstance(v, dict):
            c["defect"].update(v)
        else:
            c[k] = v
    return c


# =====================================================================
# CL3-1. ① Status
# =====================================================================
def check_status(cl, ci, c3, scope_mode, tracker_cache):
    """반환 {"result", "reason", "scope": {...}, "trackers": [...], "nok": [...], "separate": {상태: 수},
            "total", "excluded", "targets", "accepted", "unset", "dist"}"""
    exclude = {x.lower() for x in c3["exclude_types"]}
    r = {"result": UNK, "reason": "", "scope": {}, "trackers": [], "nok": [], "separate": {}, "total": 0, "excluded": 0,
         "targets": 0, "accepted": 0, "unset": 0, "dist": "", "tried": []}
    try:
        sc = resolve_scope(cl, ci["trackerId"], scope_mode)
    except ApiError as e:
        if "HTTP 404" in str(e):
            return dict(r, result="NOK", reason=f"경로의 Tracker({ci['trackerId']})가 없음 (HTTP 404)")
        return dict(r, reason=f"Tracker 조회 실패 ({e})")
    r["scope"] = sc
    tinfo = {}
    for tid in sc["trackers"]:
        if tid not in tracker_cache:
            ok, v = cl.get_many([f"/api/v3/trackers/{tid}"])[0]
            v = v if ok and isinstance(v, dict) else {}
            tracker_cache[tid] = {"name": v.get("name", ""), "key": v.get("keyName", ""), "has_type": has_type_field(cl, tid)}
        tinfo[tid] = dict(tracker_cache[tid], id=tid, total=0, excluded=0, targets=0, accepted=0, nok=0, separate=0, unset=0)
    try:
        items = cb_items(cl, sc["trackers"])
    except ApiError as e:
        return dict(r, reason=f"Item 목록 조회 실패 ({e})")
    in_scope = set(sc["trackers"])
    dist = {}
    for it in items:
        tid = str((it.get("tracker") or {}).get("id") or "")
        tid = tid if tid in in_scope else sc["root"]
        ti = tinfo.setdefault(tid, {"id": tid, "name": "", "key": "", "has_type": False, "total": 0, "excluded": 0, "targets": 0,
                                    "accepted": 0, "nok": 0, "separate": 0, "unset": 0})
        ti["total"] += 1
        r["total"] += 1
        if is_excluded(it, exclude):
            ti["excluded"] += 1
            r["excluded"] += 1
            continue
        ti["targets"] += 1
        r["targets"] += 1
        st = status_name(it)
        dist[st or "(없음)"] = dist.get(st or "(없음)", 0) + 1
        unset = ti["has_type"] and type_unset(it)
        if unset:
            ti["unset"] += 1
            r["unset"] += 1
        if in_list(st, c3["accepted_statuses"]):
            ti["accepted"] += 1
            r["accepted"] += 1
        elif st and in_list(st, c3["separate_statuses"]):
            ti["separate"] += 1
            r["separate"][st] = r["separate"].get(st, 0) + 1
        else:
            ti["nok"] += 1
            r["nok"].append({"id": it["id"], "name": it.get("name", ""), "status": st or "(Status 없음)", "type": type_of(it) or "",
                             "unset": unset, "tracker": ti["name"], "key": ti["key"]})
    r["trackers"] = [tinfo[t] for t in sc["trackers"] if t in tinfo]
    r["dist"] = " · ".join(f"{k} {v}" for k, v in sorted(dist.items(), key=lambda x: -x[1]))
    sep = sum(r["separate"].values())
    note = (f" · {sc['note']}" if sc.get("note") else "")
    if not r["targets"]:
        return dict(r, result="확인 필요", reason=f"판정 대상 Item 없음 (전체 {r['total']}, Folder·Information {r['excluded']}){note}")
    if not sc.get("ok", True):
        r["result"] = UNK if not r["nok"] else "NOK"
    if r["nok"]:
        return dict(r, result="NOK", reason=f"대상 {r['targets']}개 중 Accepted 아님 {len(r['nok'])}개"
                    + (f" (별도 Status {sep}개 제외)" if sep else "") + note)
    if not sc.get("ok", True):
        return dict(r, result=UNK, reason=f"하위 Tracker를 확인하지 못함 — {sc.get('note')}")
    return dict(r, result="OK", reason=f"대상 {r['targets']}개 모두 Accepted" + (f" (별도 Status {sep}개 제외)" if sep else "") + note)


# =====================================================================
# CL3-2. ② VR 수행 (Review_<상위 Tracker 이름>)
# =====================================================================
_PROJ_TRACKERS = {}


def project_trackers(cl, pid):
    """프로젝트의 Tracker [(id, 이름, 트리 경로)] — 이름이 트리에 없으면 Tracker 정보로 조회 (실측: 트리 노드에 trackerId만 있음)"""
    if pid in _PROJ_TRACKERS:
        return _PROJ_TRACKERS[pid]
    out = []

    def walk(ns, path):
        for n in ns or []:
            tid = node_tracker_id(n)
            nm = node_name(n)
            if tid:
                out.append([tid, nm, path])
            walk(node_children(n), path + [nm] if nm else path)
    walk(tracker_tree(cl, pid), [])
    need = [o for o in out if not o[1]]
    for o, (ok, v) in zip(need, cl.get_many([f"/api/v3/trackers/{o[0]}" for o in need])):
        o[1] = (v.get("name") or "") if ok and isinstance(v, dict) else ""
    _PROJ_TRACKERS[pid] = [tuple(o) for o in out]
    return _PROJ_TRACKERS[pid]


def review_ratio(name, base, prefix):
    """Tracker 이름이 'Review_<base>'와 얼마나 같은가 (대소문자·공백·기호 무시)"""
    a, b = hkey(name), hkey(prefix + base)
    if not a or not b:
        return 0.0
    return 1.0 if a == b else difflib.SequenceMatcher(None, a, b).ratio()


def check_vr(cl, ci, c3, sc, exclude):
    """반환 {"result", "reason", "tracker": (id, 이름)|None, "ratio", "items": [Review Item], "statuses": "..."}"""
    r = {"result": UNK, "reason": "", "tracker": None, "ratio": None, "items": [], "statuses": ""}
    pid = None
    try:
        info = cl.get(f"/api/v3/trackers/{sc.get('root') or ci['trackerId']}")
        pid = info.get("projectId") or (info.get("project") or {}).get("id")
        base = info.get("name", "") or sc.get("root_name") or ""
    except ApiError as e:
        return dict(r, reason=f"Tracker 조회 실패 ({e})")
    if not pid:
        return dict(r, reason="Tracker의 프로젝트를 알 수 없어 Review Tracker를 찾지 못함")
    try:
        trs = project_trackers(cl, pid)
    except ApiError as e:
        return dict(r, reason=f"프로젝트 Tracker 트리 조회 실패 ({e})")
    prefix = c3["review_prefix"]
    root = str(sc.get("root") or ci["trackerId"])
    plain = [(t, n) for t, n, _ in trs if not hkey(n).startswith("review") and n]

    def owner(rname):
        """Review Tracker 이름에서 접두어를 뺀 것과 가장 비슷한 일반 Tracker — 비슷한 이름의 다른 산출물 Review에 잘못 걸리지 않게
        (CL1 실측: SW Unit Design/Test처럼 서로 다른 산출물도 90% 유사)"""
        return max(((review_ratio(rname, n, prefix), t) for t, n in plain), default=(0, None))
    cands = []
    for t, n, _ in trs:
        if not hkey(n).startswith("review"):
            continue
        ratio = review_ratio(n, base, prefix)
        if ratio < 1:
            o_ratio, o_tid = owner(n)
            if o_tid and str(o_tid) != root and o_ratio > ratio:
                continue  # 다른 Tracker의 Review
        cands.append((ratio, t, n))
    best = max(cands, default=(0, None, ""))
    ok_r, cond_r = float(c3["review_ok_ratio"]), float(c3["review_conditional_ratio"])
    want = f"{prefix}{base}"
    if best[0] < cond_r:
        hint = f" — 가장 비슷한 Review Tracker: '{best[2]}'({best[1]}, {best[0]:.0%})" if best[1] and best[0] >= 0.6 else ""
        return dict(r, result="NOK", ratio=best[0] or None, reason=f"'{want}' Tracker가 없음 (상위 Tracker '{base}' 기준){hint}")
    r["tracker"], r["ratio"] = (best[1], best[2]), best[0]
    try:
        items = cb_items(cl, [best[1]])
    except ApiError as e:
        return dict(r, reason=f"Review Tracker '{best[2]}' Item 조회 실패 ({e})")
    items = [it for it in items if not is_excluded(it, exclude)]
    r["items"] = items
    st = {}
    for it in items:
        s = status_name(it) or "(없음)"
        st[s] = st.get(s, 0) + 1
    r["statuses"] = " · ".join(f"{k} {v}" for k, v in st.items())
    sim = "" if best[0] == 1 else f" (이름 유사도 {best[0]:.0%})"
    if not items:
        return dict(r, result=MANUAL, reason=f"Review Tracker '{best[2]}'({best[1]})는 있으나 Review Item 0건 — "
                                            "첨부 결과서·다른 링크로 VR 수행 여부 직접 확인")
    g = "OK" if best[0] >= ok_r else COND
    return dict(r, result=g, reason=f"Review Tracker '{best[2]}'({best[1]}){sim} — Review Item {len(items)}건"
                + ("" if g == "OK" else " — 같은 산출물의 Review인지 확인"))


# =====================================================================
# CL3-3. ③ Defect 해결
# =====================================================================
JIRA_RE = re.compile(r"https?://[^\s\"'<>\]|]+/browse/([A-Z][A-Z0-9_]+-\d+)")


def classify(status, dc, done=None):
    """'해결' / '보류' / '미해결'. done=True(Jira 완료 분류)면 해결"""
    if done or in_list(status, dc["resolved_statuses"]):
        return "해결"
    if in_list(status, dc["deferred_statuses"]):
        return "보류"
    return "미해결"


def is_defect_item(it, tracker_name, dc):
    hay = " ".join([tracker_name or "", str(it.get("typeName") or ""), str((it.get("type") or {}).get("name") if isinstance(it.get("type"), dict) else ""),
                    str((it.get("tracker") or {}).get("name") or "")])
    return any(hkey(k) and hkey(k) in hkey(hay) for k in dc["defect_tracker_keywords"])


def jira_keys(item):
    """Review Item(설명·사용자 필드 등 전체)에서 Jira 이슈 주소 → {키: 주소}"""
    txt = json.dumps(item, ensure_ascii=False)
    return {m.group(1): m.group(0) for m in JIRA_RE.finditer(txt)}


def defect_list_rows(sheets, dc):
    """첨부 엑셀 → Defect 행 [(번호/ID, 제목, 상태)] 또는 None(Status 열 있는 표 없음)"""
    heads = {hkey(h) for h in dc["list_status_headers"]}
    for title, rows in sheets:
        for hi, row in enumerate(rows[:20]):
            keys = [hkey(c[0]) for c in row]
            sj = next((j for j, k in enumerate(keys) if k in heads), None)
            if sj is None:
                continue
            ij = next((j for j, k in enumerate(keys) if k in ("id", "no", "번호", "defectid", "key", "결함번호")), None)
            tj = next((j for j, k in enumerate(keys) if any(x in k for x in ("title", "summary", "제목", "내용", "description", "defect"))
                       and j not in (sj, ij)), None)
            out = []
            for r in rows[hi + 1:]:
                def g(j):
                    return r[j][0].strip() if j is not None and j < len(r) and r[j][0] else ""
                if not g(sj) and not g(tj) and not g(ij):
                    continue
                out.append((g(ij) or f"{title}:{len(out) + 1}", g(tj), g(sj)))
            return out
    return None


class Jira:
    """Jira 조회 — 처음 필요할 때 로그인 (같은 브라우저). 실패하면 이번 실행은 Jira 확인불가"""

    def __init__(self, ctx, cfg, interactive):
        self.ctx, self.cfg, self.interactive = ctx, cfg, interactive
        self.base, self.client, self.error, self.cache = None, None, "", {}

    def _open(self, url):
        jc = self.cfg.get("jira") or {}
        base = (jc.get("base") or re.sub(r"(https?://[^/]+).*", r"\1", url)).rstrip("/")
        self.base = base
        try:
            s = Session(self.ctx, "Jira", base + "/secure/Dashboard.jspa", base + jc.get("login_path", "/login.jsp"),
                        self.interactive, get_cred("Jira"))
            s.ensure_login(base, "/rest/api/2/myself", lambda b: bool(b.get("name") or b.get("key") or b.get("accountId")))
            self.client = Client(s.fetch_json, base)
            log("   Jira 로그인 확인")
        except (ApiError, NeedLogin, Exception) as e:  # noqa
            self.error = f"Jira 로그인 실패 ({e})"
            log(f"   ⚠ {self.error} — Jira 이슈는 확인불가로 남깁니다")

    def status(self, key, url):
        """반환 (상태, 해결 여부(bool|None), 제목, 오류)"""
        if key in self.cache:
            return self.cache[key]
        if self.client is None and not self.error:
            self._open(url)
        if self.client is None:
            return ("", None, "", self.error)
        ok, v = self.client.get_many([f"/rest/api/2/issue/{key}?fields=status,resolution,summary"])[0]
        if not ok or not isinstance(v, dict):
            res = ("", None, "", f"Jira 조회 실패 ({v})")
        else:
            f = v.get("fields") or {}
            st = (f.get("status") or {})
            done = ((st.get("statusCategory") or {}).get("key") == "done") or bool(f.get("resolution"))
            res = (st.get("name", ""), done, f.get("summary", ""), "")
        self.cache[key] = res
        return res


def check_defects(cl, cbs, jira, ci, c3, vr, cb_base, cfg, debug=None, tracker_names=None):
    """반환 {"result", "reason", "defects": [{"review", "source", "id", "url", "title", "status", "verdict"}], "manual": [...]}"""
    dc = c3["defect"]
    tracker_names = {} if tracker_names is None else tracker_names
    r = {"result": "-", "reason": "② 결과에 따름", "defects": [], "manual": []}
    if vr["result"] not in ("OK", COND):
        if vr["result"] == MANUAL:
            return dict(r, result=MANUAL, reason="Review Item이 없어 Defect를 자동으로 찾을 수 없음 — 첨부 결과서의 Defect List 직접 확인")
        return r
    revs = vr["items"]
    rel_res = cl.get_many([f"/api/v3/items/{it['id']}/relations" for it in revs])
    att_res = cl.get_many([f"/api/v3/items/{it['id']}/attachments" for it in revs])
    fails = []
    for it, (rok, rel), (aok, att) in zip(revs, rel_res, att_res):
        rid, rlabel = it["id"], f"{it.get('name', '')} ({it['id']})"
        if debug is not None:
            debug.append((f"review_{rid}.json", json.dumps({"item": it, "relations": rel, "attachments": att}, ensure_ascii=False, indent=1)))
        # (a) Codebeamer 연결 Defect
        if not rok:
            fails.append(f"{rlabel} 연결 조회 실패 ({rel})")
        else:
            full = rel_rest_pages(cl, rid, rel) if isinstance(rel, dict) and rel.get("isLastPage") is False else rel
            ids = [i for i in rel_targets(full or {}) if i is not None]
            if ids:
                got = cl.get_many([f"/api/v3/items/{i}" for i in ids])
                for i, (ok, d) in zip(ids, got):
                    if not ok or not isinstance(d, dict):
                        continue
                    tid = str((d.get("tracker") or {}).get("id") or "")
                    if tid and tid not in tracker_names:
                        tok, tv = cl.get_many([f"/api/v3/trackers/{tid}"])[0]
                        tracker_names[tid] = (tv.get("name") or "") if tok and isinstance(tv, dict) else ""
                    if is_defect_item(d, tracker_names.get(tid, ""), dc):
                        st = status_name(d)
                        r["defects"].append({"review": rlabel, "review_url": item_url(cb_base, rid), "source": f"Codebeamer '{tracker_names.get(tid, '')}'",
                                             "id": str(i), "url": item_url(cb_base, i), "title": d.get("name", ""), "status": st,
                                             "verdict": classify(st, dc)})
        # (b) Jira 링크
        for key, url in jira_keys(it).items():
            st, done, title, err = jira.status(key, url)
            r["defects"].append({"review": rlabel, "review_url": item_url(cb_base, rid), "source": "Jira", "id": key, "url": url,
                                 "title": title, "status": st or err, "verdict": UNK if err else classify(st, dc, done)})
        # (c) 첨부 Defect List (엑셀)
        if not aok:
            fails.append(f"{rlabel} 첨부 목록 조회 실패 ({att})")
            continue
        atts = att if isinstance(att, list) else (att.get("attachments") or att.get("items") or []) if isinstance(att, dict) else []
        for a in atts:
            name = str(a.get("name") or a.get("fileName") or "")
            if not re.search(r"\.xls[xm]?$", name, re.I):
                if name:
                    r["manual"].append(f"{rlabel} 첨부 '{name}' (엑셀 아님)")
                continue
            try:
                data = cbs.fetch_bytes(f"{cb_base}/api/v3/items/{rid}/attachments/{a.get('id')}/content")
                if is_drm(data):
                    path = STATE / "attach" / f"{rid}_{re.sub(r'[^0-9A-Za-z가-힣._-]', '_', name)}"
                    path.parent.mkdir(exist_ok=True)
                    path.write_bytes(data)
                    sheets = grid_excel(path, visible=cfg.get("excel", {}).get("visible", True))
                else:
                    sheets = grid_openpyxl(data)
                rows = defect_list_rows(sheets, dc)
            except NeedLogin:
                raise
            except Exception as e:  # noqa
                r["manual"].append(f"{rlabel} 첨부 '{name}' 읽기 실패 ({str(e)[:80]})")
                continue
            if rows is None:
                r["manual"].append(f"{rlabel} 첨부 '{name}'에 Status 열 있는 표 없음")
                continue
            for did, title, st in rows:
                r["defects"].append({"review": rlabel, "review_url": item_url(cb_base, rid), "source": f"첨부 {name}", "id": did, "url": "",
                                     "title": title, "status": st, "verdict": classify(st, dc) if st else "미해결"})
    cnt = {k: sum(d["verdict"] == k for d in r["defects"]) for k in ("해결", "미해결", "보류", UNK)}
    summary = f"Defect {len(r['defects'])}건 (해결 {cnt['해결']} · 미해결 {cnt['미해결']} · 보류 {cnt['보류']} · 확인불가 {cnt[UNK]})"
    extra = (" / " + " / ".join(fails)) if fails else ""
    if cnt["미해결"]:
        return dict(r, result="NOK", reason=summary + extra)
    if cnt[UNK] or fails:
        return dict(r, result=UNK, reason=summary + extra)
    if cnt["보류"]:
        return dict(r, result=COND, reason=summary + " — 보류 Defect의 이관·승인 근거 확인")
    if r["defects"]:
        return dict(r, result="OK", reason=summary + (f" · 수동 확인 첨부 {len(r['manual'])}건" if r["manual"] else ""))
    if r["manual"]:
        return dict(r, result=MANUAL, reason="연결된 Defect 없음, 첨부를 자동으로 읽지 못함 — " + " / ".join(r["manual"][:3]))
    return dict(r, result=COND, reason="Review Item에 연결된 Defect·Jira·Defect List가 없음 — Defect 0건인지 기록 누락인지 확인")


# =====================================================================
# CL3-4. 결과 엑셀
# =====================================================================
def build_workbook(results, meta, cb_base, c3):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    HF, HFont = PatternFill("solid", fgColor="00B0F0"), Font(bold=True, color="FFFFFF")
    LINK = Font(color="0563C1", underline="single")
    WRAP = Alignment(wrap_text=True, vertical="top")
    FILL = {"NOK": PatternFill("solid", fgColor="FFC7CE"), "미해결": PatternFill("solid", fgColor="FFC7CE"),
            COND: PatternFill("solid", fgColor="FFF2CC"), "보류": PatternFill("solid", fgColor="FFF2CC"),
            "확인 필요": PatternFill("solid", fgColor="FFF2CC"), UNK: PatternFill("solid", fgColor="E7E6E6"),
            MANUAL: PatternFill("solid", fgColor="DDEBF7")}
    KEYS = (("① Status", "st"), ("② VR 수행", "vr"), ("③ Defect 해결", "df"))

    def sheet(wb, title, header, widths):
        ws = wb.create_sheet(title)
        ws.append(header)
        for i, w in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(i)].width = w
            ws.cell(1, i).fill, ws.cell(1, i).font = HF, HFont
            ws.cell(1, i).alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.freeze_panes = "A2"
        return ws

    def link(cell, url, text=None):
        cell.value = text if text is not None else url
        if url and re.match(r"https?://", url):
            cell.hyperlink, cell.font = url, LINK

    def paint(cell):
        f = FILL.get(str(cell.value or ""))
        if f:
            cell.fill = f

    wb = Workbook()
    wb.remove(wb.active)
    order = ("OK", COND, "NOK", "확인 필요", UNK, MANUAL, "-")
    sm = sheet(wb, "요약", ["구분"] + list(order) + ["계"], [18, 8, 14, 8, 10, 10, 10, 6, 8])
    for label, key in (("CL3 종합", None),) + KEYS:
        cnt = {}
        for r in results:
            g = r["result"] if key is None else r[key]["result"]
            cnt[g] = cnt.get(g, 0) + 1
        sm.append([label] + [cnt.get(k, 0) for k in order] + [len(results)])
    sm.append([])
    sm.append(["Status NOK Item 합계", sum(len(r["st"]["nok"]) for r in results)])
    sm.append([f"별도 Status ({', '.join(c3['separate_statuses'])}) 합계", sum(sum(r["st"]["separate"].values()) for r in results)])
    sm.append(["미해결 Defect 합계", sum(d["verdict"] == "미해결" for r in results for d in r["df"]["defects"])])
    sm.append(["'-' = 앞 단계 결과 때문에 판정하지 않음 (예: ② Review Tracker 없음 → ③ -)"])

    ov = sheet(wb, "Overview", ["CI ID", "Category", "CI name", "Path in Repository", "CL3 결과",
                                "① Status", "검사 범위(상위 Tracker)", "대상 Item", "Accepted", "Accepted 아님", "Type --",
                                "별도 Status 수", "Status 분포", "① 근거",
                                "② VR 수행", "Review Tracker", "Review Item 수", "Review Item Status(참고)", "② 근거",
                                "③ Defect 해결", "Defect 수", "미해결", "③ 근거"],
               [18, 9, 34, 30, 13, 12, 36, 9, 9, 10, 8, 10, 40, 50, 12, 40, 9, 26, 50, 13, 8, 8, 60])
    for r in results:
        st, vr, df = r["st"], r["vr"], r["df"]
        sep = st["separate"]
        ov.append([r["ciId"], r["category"], r["ciName"], None, r["result"],
                   st["result"], None, st["targets"] or None, st["accepted"] or None, len(st["nok"]) or None, st["unset"] or None,
                   (" · ".join(f"{k} {v}" for k, v in sep.items()) or None), st["dist"] or None, st["reason"],
                   vr["result"], None, len(vr["items"]) or None, vr["statuses"] or None, vr["reason"],
                   df["result"], len(df["defects"]) or None, sum(d["verdict"] == "미해결" for d in df["defects"]) or None, df["reason"]])
        n = ov.max_row
        link(ov.cell(n, 4), r["path"])
        sc = st.get("scope") or {}
        if sc.get("root"):
            link(ov.cell(n, 7), f"{cb_base}/tracker/{sc['root']}", f"{sc.get('root_name', '')} ({sc['root']})"
                 + (f" + 하위 {len(sc.get('trackers', [])) - 1}" if len(sc.get("trackers", [])) > 1 else ""))
        if vr.get("tracker"):
            link(ov.cell(n, 16), f"{cb_base}/tracker/{vr['tracker'][0]}", f"{vr['tracker'][1]} ({vr['tracker'][0]})")
        for c in (5, 6, 15, 20):
            paint(ov.cell(n, c))
    ov.auto_filter.ref = ov.dimensions

    sn = sheet(wb, "Status NOK", ["CI ID", "CI name", "Tracker", "Item", "Item 이름", "Type", "Status", "Type --"],
               [18, 30, 34, 18, 50, 16, 16, 8])
    for r in results:
        for x in r["st"]["nok"]:
            sn.append([r["ciId"], r["ciName"], x["tracker"], None, x["name"], x["type"], x["status"], "●" if x["unset"] else None])
            link(sn.cell(sn.max_row, 4), item_url(cb_base, x["id"]), f"{x['key']}-{x['id']}" if x["key"] else str(x["id"]))
    sn.auto_filter.ref = sn.dimensions

    ss = sheet(wb, "별도 Status", ["CI ID", "CI name", "Status", "Item 수"], [18, 40, 16, 10])
    for r in results:
        for k, v in r["st"]["separate"].items():
            ss.append([r["ciId"], r["ciName"], k, v])
    if ss.max_row == 1:
        ss.append([None, f"({', '.join(c3['separate_statuses'])} Item 없음)"])

    dfs = sheet(wb, "Defect", ["CI ID", "Review Item", "출처", "Defect", "제목", "Status", "판정"], [18, 40, 34, 18, 60, 16, 10])
    for r in results:
        for d in r["df"]["defects"]:
            dfs.append([r["ciId"], None, d["source"], None, d["title"], d["status"], d["verdict"]])
            n = dfs.max_row
            link(dfs.cell(n, 2), d.get("review_url", ""), d["review"])
            link(dfs.cell(n, 4), d["url"], d["id"])
            paint(dfs.cell(n, 7))
            dfs.cell(n, 5).alignment = WRAP
        for m in r["df"]["manual"]:
            dfs.append([r["ciId"], m.split(" 첨부 ")[0], "첨부(수동 확인)", None, m, None, MANUAL])
            paint(dfs.cell(dfs.max_row, 7))
    dfs.auto_filter.ref = dfs.dimensions

    ck = sheet(wb, "확인 필요", ["CI ID", "Category", "CI name", "항목", "결과", "내용", "확인 결과(사람 기입)"], [18, 9, 34, 14, 13, 90, 20])
    for r in results:
        for label, key in KEYS:
            g = r[key]["result"]
            if g not in ("OK", "NOK", "-"):
                ck.append([r["ciId"], r["category"], r["ciName"], label, g, r[key]["reason"], None])
                paint(ck.cell(ck.max_row, 5))
    ck.auto_filter.ref = ck.dimensions

    tb = sheet(wb, "Tracker별", ["CI ID", "Tracker", "전체 Item", "Folder·Information", "대상", "Accepted", "Accepted 아님", "별도 Status", "Type --"],
               [18, 50, 9, 12, 8, 9, 11, 10, 8])
    for r in results:
        for t in r["st"]["trackers"]:
            tb.append([r["ciId"], None, t["total"], t["excluded"], t["targets"], t["accepted"], t["nok"] or None, t["separate"] or None,
                       t["unset"] or None])
            link(tb.cell(tb.max_row, 2), f"{cb_base}/tracker/{t['id']}", f"{t['name']} ({t['id']})")
            if t["nok"]:
                tb.cell(tb.max_row, 7).fill = FILL["NOK"]

    tr = sheet(wb, "조회 기록", ["CI ID", "조회"], [18, 120])
    for r in results:
        for t in r.get("tried") or ["-"]:
            tr.append([r["ciId"], t])

    inf = sheet(wb, "실행정보", ["항목", "값"], [28, 110])
    for k, v in meta.items():
        inf.append([k, str(v)])
        inf.cell(inf.max_row, 2).alignment = WRAP
    return wb


# =====================================================================
# CL3-5. 실행
# =====================================================================
def check_one(ccb, cbs, jira, c, c3, scope_mode, cb_base, cfg, tracker_cache, tracker_names, debug=None):
    exclude = {x.lower() for x in c3["exclude_types"]}
    na = {"result": "-", "reason": "", "items": [], "statuses": "", "tracker": None, "defects": [], "manual": []}
    if not c.get("trackerId"):
        why = "Path in Repository가 비어 있음" if not c.get("path") else f"Codebeamer Tracker 경로가 아님 ({c.get('repository') or '저장소 미기재'})"
        st = {"result": MANUAL if c.get("path") else "NOK", "reason": why + " — 직접 확인", "scope": {}, "trackers": [], "nok": [],
              "separate": {}, "targets": 0, "accepted": 0, "unset": 0, "dist": "", "total": 0, "excluded": 0}
        vr = dict(na, result=MANUAL, reason="Tracker가 아니라 Review Tracker를 자동으로 찾지 않음 — 직접 확인")
        return dict(c, st=st, vr=vr, df=dict(na, result=MANUAL, reason="직접 확인"), result=worst(st["result"], MANUAL), tried=[why])
    tried = []
    st = check_status(ccb, c, c3, scope_mode, tracker_cache)
    sc = st.get("scope") or {}
    if scope_mode != "top_with_descendants" and st["result"] != UNK:  # 빠른 검사여도 ②는 상위 Tracker 기준 (사용자 결정 2026-11-24)
        try:
            sc = resolve_scope(ccb, c["trackerId"], "top_with_descendants")
        except ApiError:
            pass
    tried.append(f"① 범위: {sc.get('root_name', '')}({sc.get('root', '')}) Tracker {len(st.get('trackers') or [])}개 · Item {st['total']}개"
                 + (f" · {sc.get('note')}" if sc.get("note") else ""))
    if sc.get("root"):
        vr = check_vr(ccb, c, c3, sc, exclude)
    else:
        vr = dict(na, result=st["result"] if st["result"] in (UNK, "NOK") else UNK, reason="Tracker를 확인하지 못해 Review Tracker를 찾지 않음")
    tried.append(f"② {vr['reason']}")
    df = check_defects(ccb, cbs, jira, c, c3, vr, cb_base, cfg, debug, tracker_names)
    tried.append(f"③ {df['reason']}")
    return dict(c, st=st, vr=vr, df=df, result=worst(st["result"], vr["result"], df["result"]), tried=tried)


def main(argv=None):
    ap = argparse.ArgumentParser(description="CL3 — Status · Verification Review · Defect 해결 점검")
    ap.add_argument("--doctor", action="store_true", help="연결·Review 구조 점검 (결과 파일 없음)")
    ap.add_argument("--quick", action="store_true", help="빠른 검사: ① Status를 CI list에 적힌 Tracker만 (참고용)")
    ap.add_argument("--ci", action="append", help="이 CI ID만 검사 (여러 번 지정 가능)")
    ap.add_argument("--limit", type=int, help="앞에서 N개 CI만 (시험용)")
    ap.add_argument("--headless", action="store_true", help="브라우저 창 숨김 (로그인 저장된 뒤에만)")
    ap.add_argument("--config", default=str(HERE / "config.json"))
    ap.add_argument("--set-login", action="store_true", help="로그인 ID/PW 저장 (Windows 자격 증명 관리자)")
    ap.add_argument("--clear-login", action="store_true", help="저장된 로그인 정보 삭제")
    a = ap.parse_args(argv)
    if a.set_login:
        set_login(); return 0
    if a.clear_login:
        clear_login(); return 0
    cfg_path = Path(a.config)
    if not cfg_path.exists():
        raise ValueError(f"설정 파일이 없습니다: {cfg_path.name} — config.example.json을 복사해 config.json을 만들고 실제 값을 넣어 주세요.")
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    c3 = cl3_cfg(cfg)
    scope_mode = "tracker_only" if a.quick else c3.get("scope", "top_with_descendants")
    if not a.quick and not a.doctor and not a.ci and sys.stdin and sys.stdin.isatty():
        ans = input("검사 방식 — Enter: 전체 검사(상위+하위 Tracker) / q: 빠른 검사(적힌 Tracker만, 참고용): ").strip().lower()
        if ans in ("q", "ㅂ"):
            a.quick, scope_mode = True, "tracker_only"
    for d in (STATE, STATE / "ci_list", STATE / "debug"):
        d.mkdir(exist_ok=True)
    out_dir = HERE / cfg.get("output_dir", "output")
    out_dir.mkdir(exist_ok=True)
    t0 = time.time()

    from playwright.sync_api import sync_playwright
    log(f"CL3 점검(Status · VR · Defect) v{VERSION} 시작"
        f"{' (점검 모드)' if a.doctor else ''}{' — 빠른 검사(① 적힌 Tracker만)' if a.quick else ' — 전체 검사(상위+하위 Tracker)'}")
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(STATE / "browser-profile"), channel=cfg["browser"].get("channel") or None,
            headless=a.headless, viewport={"width": 1280, "height": 860})
        try:
            cf = cfg["confluence"]
            pid = cf["ci_list_page_id"]
            conf = Session(ctx, "Confluence", f"{cf['base']}/pages/viewpage.action?pageId={pid}",
                           cf["base"] + cf.get("login_path", "/login.action"), not a.headless, get_cred("Confluence"))
            conf.ensure_login(cf["base"], "/rest/api/user/current",
                              lambda b: b.get("type") != "anonymous" and bool(b.get("username") or b.get("userKey") or b.get("displayName")))
            ccf = Client(conf.fetch_json, cf["base"])
            try:
                pg = ccf.get(f"/rest/api/content/{pid}")
            except ApiError as e:
                raise ApiError(f"CI list 페이지(pageId {pid})를 열 수 없습니다 — 페이지 번호·열람 권한 확인. ({e})")
            log(f"1. Confluence 로그인 확인 — 페이지 '{pg.get('title', '')}'")
            atts = latest_xlsx(ccf.get(f"/rest/api/content/{pid}/child/attachment?expand=version&limit=200"), cf["base"])
            if not atts:
                raise ApiError("CI list 페이지에 엑셀 첨부 파일이 없습니다.")
            latest = atts[0]
            log(f"1. 최신 CI list: {latest['title']} (업로드 {latest['when'][:16].replace('T', ' ')} {latest['by']})")
            data = conf.fetch_bytes(latest["url"])
            saved = STATE / "ci_list" / f"{time.strftime('%Y%m%d_%H%M')}_{latest['title']}"
            saved.write_bytes(data)
            cis, info = read_ci_list(data, cfg, saved_path=saved)
            log(f"2. 시트 '{info['sheet']}' 전체 {info['total']}행 → PBL 없음 제외 {info['no_pbl']} → 검사 대상 {info['targets']}개")
            if a.ci:
                want = {x.strip() for x in a.ci}
                cis = [c for c in cis if c["ciId"] in want]
                miss = want - {c["ciId"] for c in cis}
                if miss:
                    log(f"   ⚠ 대상에 없는 CI: {', '.join(sorted(miss))}")
            if a.doctor and not a.ci:
                cis = [c for c in cis if c.get("trackerId")][:2]
            if a.limit:
                cis = cis[:a.limit]
            if not cis:
                raise ApiError("검사할 CI가 없습니다.")

            cb = cfg["codebeamer"]
            cb_base = cb["base"].rstrip("/")
            cbs = Session(ctx, "Codebeamer", cb["base"], cb["base"] + cb.get("login_path", "/login.spr"),
                          not a.headless, get_cred("Codebeamer"))
            probe = "/api/v3/projects"

            def cb_login():
                cbs.ensure_login(cb["base"], probe, lambda b: isinstance(b, (list, dict)) and not (isinstance(b, dict) and b.get("type") == "anonymous"))
                cbs.pin(cb["base"] + probe)
            cb_login()
            log("3. Codebeamer 로그인 확인")
            ccb = Client(cbs.fetch_json, cb["base"], batch=cfg.get("batch_size", 10), relogin=cb_login)
            jira = Jira(ctx, cfg, not a.headless)

            results, tracker_cache, tracker_names = [], {}, {}
            for n, c in enumerate(cis, 1):
                dbg = []
                try:
                    rr = check_one(ccb, cbs, jira, c, c3, scope_mode, cb_base, cfg, tracker_cache, tracker_names, dbg)
                except NeedLogin:
                    raise
                except Exception as e:  # noqa
                    e1 = {"result": UNK, "reason": f"조회 중 오류: {e}", "scope": {}, "trackers": [], "nok": [], "separate": {}, "targets": 0,
                          "accepted": 0, "unset": 0, "dist": "", "total": 0, "excluded": 0}
                    na = {"result": "-", "reason": "", "items": [], "statuses": "", "tracker": None, "defects": [], "manual": []}
                    rr = dict(c, st=e1, vr=na, df=na, result=UNK, tried=[f"오류: {e}"])
                if a.doctor or rr["result"] != "OK":
                    for name, body in dbg[:5]:
                        (STATE / "debug" / f"{c['ciId']}_{name}").write_text(body, encoding="utf-8")
                results.append(rr)
                log(f"4. ({n}/{len(cis)}) {c['ciId']:<20} {rr['result']:<14} ① {rr['st']['result']:<10} ② {rr['vr']['result']:<14} "
                    f"③ {rr['df']['result']:<14} {c['ciName'][:30]}")
                if a.doctor:
                    for t in rr["tried"]:
                        log(f"   {t}")
                    for d in rr["df"]["defects"][:10]:
                        log(f"   Defect [{d['source']}] {d['id']} {d['status']} → {d['verdict']}")
                    for m in rr["df"]["manual"][:5]:
                        log(f"   수동: {m}")
                    log(f"   저장: state\\debug\\{c['ciId']}_review_*.json ({min(len(dbg), 5)}개)")
        finally:
            ctx.close()

    if a.doctor:
        log("✔ 점검 완료 — Review Tracker·Defect가 화면과 같게 잡혔는지 확인하세요. 다르면 state\\debug 폴더 파일을 Claude에게 전달")
        return 0
    meta = {
        "실행 시각": time.strftime("%Y-%m-%d %H:%M:%S"),
        "도구": f"CL3 cl3_check.py v{VERSION}",
        "검사 방식": "빠른 검사(--quick): ①을 CI list에 적힌 Tracker만 — 참고용, CA 근거는 전체 검사 결과 사용" if a.quick
                 else "전체 검사: ①을 상위 Tracker + 하위 Tracker 전부",
        "CI list 파일": f"{latest['title']} (Confluence 업로드 {latest['when']} {latest['by']})",
        "CI 선별": f"전체 {info['total']} / PBL 없음 제외 {info['no_pbl']} / 검사 {len(results)}" + (" (일부 CI만 지정 실행)" if a.ci or a.limit else ""),
        "① 판정 규칙": f"Type {c3['exclude_types']} 제외 모든 Item(Type '--' 포함)의 Status가 {c3['accepted_statuses']}면 OK, 아니면 NOK. "
                    f"{c3['separate_statuses']}는 NOK에서 빼고 개수만 표시",
        "② 판정 규칙": f"프로젝트 Tracker 중 '{c3['review_prefix']}<상위 Tracker 이름>'과 이름 유사도 {float(c3['review_ok_ratio']):.0%} 이상 OK · "
                    f"{float(c3['review_conditional_ratio']):.0%} 이상 Conditional OK · 없으면 NOK. Review Item 0건이면 수동 확인(첨부 결과서·링크 직접 확인). "
                    "Review Item Status는 참고로만 표시",
        "③ 판정 규칙 (잠정)": f"Review Item에 연결된 Codebeamer Defect(Tracker·유형 이름에 {c3['defect']['defect_tracker_keywords']}), "
                          f"Jira 이슈 링크, 첨부 엑셀 Defect List(Status 열)를 모아 — 미해결 1건 이상 NOK · 조회 실패 확인불가 · "
                          f"보류({c3['defect']['deferred_statuses']}) Conditional OK · 모두 해결({c3['defect']['resolved_statuses']}, Jira 완료) OK · "
                          "근거 없음 Conditional OK(0건인지 확인) · 첨부를 못 읽으면 수동 확인",
        "종합 판정": "①②③ 중 가장 나쁜 결과 (NOK > 확인불가 > Conditional OK·수동 확인 > OK)",
        "원칙": "조회 실패 = 확인불가 · 읽기 전용 · 결과는 새 파일 · 등급(N/P/L/F)은 판정하지 않음",
        "소요 시간": f"{time.time() - t0:.0f}초",
        "주의": "자동 생성 초안입니다. 공식 산출물 반영·저장은 담당자가 검토 후 직접 합니다.",
    }
    wb = build_workbook(results, meta, cb_base, c3)
    out = out_dir / f"CL3_Status_VR_{cfg.get('project', '')}_{time.strftime('%Y-%m-%d_%H%M')}{'_quick' if a.quick else ''}.xlsx"
    wb.save(out)
    cnt = {g: sum(r["result"] == g for r in results) for g in ("OK", COND, "NOK", UNK, "확인 필요", MANUAL)}
    log(f"5. 완료 — CI {len(results)}개 · " + " · ".join(f"{k} {v}" for k, v in cnt.items() if v))
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

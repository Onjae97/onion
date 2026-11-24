#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CL2 점검 — Revision history 관리 · Version Rule (v1.1)

체크리스트 CL2에서 CI마다 세 가지를 확인한다.
  ① Revision history가 해당 Tracker에 있고 관리되고 있는가 (없거나 기록 0행 = NOK)
  ② Version · Date · Description · Author · Approver 칸이 모두 채워져 있는가 (빈칸 = NOK)
  ③ Version이 Version Rule(vX.Yz, 6.2.2절)을 지키는가 (형식·순서·증가 규칙, 정량 규칙은 SKILL.md)

흐름: Confluence 최신 CI list → PBL CI 선별 → Codebeamer Tracker에서 'Revision history' Item 찾기
      → Item 본문(Wiki/HTML) 또는 화면의 표 읽기 → CI별 ①②③ 판정
      → 엑셀(요약·Overview·NOK·확인 필요·Revision history·조회 기록·실행정보)

체크리스트 1번(CL1_Repo_baseline)·6번(CL6_Traceability)과는 별개 도구. 로그인·CI list 읽기 코드는 같은 방식을 복사해 사용.
원칙: 읽기 전용(GET) · 조회 실패 = 확인불가 · 결과는 항상 새 파일

사용:   python cl2_check.py                 # 전체
        python cl2_check.py --doctor        # 연결·Revision history 읽기 점검 (앞 3개 Tracker CI)
        python cl2_check.py --ci CI_ID      # 일부 CI만
        python cl2_check.py --item 1234567  # (--ci와 함께) Revision history Item 번호 직접 지정
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

VERSION = "1.1"
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
                or re.search(r"codebeamer|/cb/tracker/", ci["path"], re.I))

# =====================================================================
# 1-1. 로그인 정보 (Windows 자격 증명 관리자 — 파일에 저장하지 않음)
# =====================================================================
CRED_SERVICE = "AUTO-CL2 revision-history"
CRED_FALLBACKS = ("AUTO-CL1 ci-baseline", "AUTO-001 traceability")  # CL1·추적성 도구에 저장한 로그인 정보도 사용


def get_cred(name):
    """저장된 ID/PW. CL2 전용 저장값이 없으면 CL1·추적성 도구(AUTO-001)에 저장한 값을 쓴다."""
    try:
        import keyring
        for svc in (CRED_SERVICE,) + CRED_FALLBACKS:
            user = keyring.get_password(svc, f"{name}:user")
            pw = keyring.get_password(svc, f"{name}:{user}") if user else None
            if user and pw:
                return user, pw
        return None
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
    print("CL2 점검 로그인 정보 저장 — Windows 자격 증명 관리자에 암호화되어 이 Windows 계정에서만 읽힙니다.")
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


from html.parser import HTMLParser  # noqa: E402


class _Tables(HTMLParser):
    """HTML의 표를 (표 번호, 행 목록)으로 모은다. 중첩 표는 가장 안쪽 표에 행을 넣는다.
    각 행 = {"cells": [셀 텍스트], "links": [(href, 텍스트)]}"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables, self.stack, self.row, self.cell, self.a = [], [], None, None, None

    def handle_starttag(self, tag, attrs):
        at = dict(attrs)
        if tag == "table":
            self.tables.append([])
            self.stack.append(len(self.tables) - 1)
        elif tag == "tr":
            self.row = {"cells": [], "links": [], "table": self.stack[-1] if self.stack else None}
        elif tag in ("td", "th") and self.row is not None:
            self.cell = []
        elif tag == "a":
            self.a = [at.get("href", ""), []]
        elif tag == "br" and self.cell is not None:
            self.cell.append(" ")

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.row is not None and self.cell is not None:
            txt = re.sub(r"\s+", " ", "".join(self.cell)).strip()
            self.row["cells"].append(re.sub(r"\s+([_)\]])", r"\1", txt))  # 줄바꿈(<br>) 뒤 '_ADCU50' 앞 공백 제거
            self.cell = None
        elif tag == "tr" and self.row is not None:
            if self.row["table"] is not None and (self.row["cells"] or self.row["links"]):
                self.tables[self.row["table"]].append(self.row)
            self.row = None
        elif tag == "table" and self.stack:
            self.stack.pop()
        elif tag == "a" and self.a is not None:
            if self.row is not None:
                self.row["links"].append((self.a[0], re.sub(r"\s+", " ", "".join(self.a[1])).strip()))
            self.a = None

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)
        if self.a is not None:
            self.a[1].append(data)


def html_tables(html):
    p = _Tables()
    try:
        p.feed(html or "")
    except Exception:  # noqa  깨진 HTML — 읽은 데까지 사용
        pass
    return p.tables


def _wiki_clean(s):
    s = re.sub(r"\[([^\]|]*)\|[^\]]*\]", r"\1", s)   # [표시|링크] → 표시
    s = re.sub(r"\[([^\]]*)\]", r"\1", s)
    s = re.sub(r"(\*|__|'{2,3}|~~)", "", s)
    return re.sub(r"\s+", " ", s).strip()



# =====================================================================
# 저장소 종류
# =====================================================================
def repo_kind(ci, cfg):
    path, repo = ci.get("path", ""), ci.get("repository", "")
    conf_host = re.sub(r"https?://([^/]+).*", r"\1", cfg["confluence"]["base"])
    cb_host = re.sub(r"https?://([^/]+).*", r"\1", cfg["codebeamer"]["base"])
    if ci.get("trackerId"):
        return "cb_tracker"
    if re.match(r"https?://", path or ""):
        if cb_host and cb_host in path:
            return "cb_page"
        if conf_host and conf_host in path:
            return "confluence"
    if re.search("codebeamer", repo, re.I):
        return "cb_page" if path else "none"
    if re.search("confluence", repo, re.I):
        return "confluence" if path else "none"
    return "other" if path else "none"


_TREES = {}


def _tid(n):
    if not isinstance(n, dict) or n.get("isFolder"):
        return None
    t = n.get("trackerId") or (n.get("tracker") or {}).get("id")
    return str(t) if t is not None else None


def _tname(n):
    return str(n.get("text") or n.get("name") or (n.get("tracker") or {}).get("name") or "")


def _kids(n):
    return (n.get("children") or n.get("nodes") or []) if isinstance(n, dict) else []


def tracker_tree(cl, pid):
    """프로젝트 Tracker 트리 (실패 시 None). 한 번 받으면 이번 실행 동안 재사용"""
    if pid not in _TREES:
        try:
            r = cl.get(f"/api/v3/trackers/tree?projectId={pid}")
            _TREES[pid] = r if isinstance(r, list) else (r.get("children") or r.get("nodes") or r.get("items") or [r])
            try:  # 실제 트리 구조 확인용 (프로젝트 구조만, 개인정보 없음)
                (STATE / "debug").mkdir(parents=True, exist_ok=True)
                (STATE / "debug" / f"tracker_tree_{pid}.json").write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
            except Exception:  # noqa
                pass
        except ApiError:
            _TREES[pid] = None
    return _TREES[pid]


def project_trackers(cl, pid):
    """프로젝트의 Tracker 이름 목록 [(id, 이름)] — 이름이 다른 위치에서 관리되는지 찾을 때 사용"""
    nodes = tracker_tree(cl, pid)
    if nodes is None:
        return None
    out = []

    def walk(ns):
        for n in ns or []:
            if _tid(n):
                out.append((_tid(n), _tname(n) or tracker_name(cl, _tid(n))))
            walk(_kids(n))
    walk(nodes)
    return out


def tracker_ancestors(cl, pid, tid):
    """등록 Tracker 위의 노드들 [(id, 이름)] — 가까운 상위부터 트리 최상단까지.
    실측(2026-11-24): API 트리에서는 화면상 상위 Tracker(예: 'System Qualification Test Specfication_ADCU50')가
    Tracker가 아닌 폴더처럼 표시될 수 있음 → 노드 종류와 무관하게 모든 상위 노드의 이름을 비교 대상으로 쓴다.
    트리를 못 읽으면 None, 트리에서 못 찾으면 []"""
    nodes = tracker_tree(cl, pid)
    if nodes is None:
        return None

    def find(ns, path):
        for n in ns or []:
            if not isinstance(n, dict):
                continue
            p2 = path + [n]
            if _tid(n) == str(tid) or (str(n.get("id", "")) == str(tid) and not n.get("isFolder")):
                return p2
            got = find(_kids(n), p2)
            if got:
                return got
        return None
    path = find(nodes, []) or []
    out = []
    for n in reversed(path[:-1]):
        t, name = _tid(n), _tname(n)
        if t and not name:  # 실측: 트리의 Tracker 노드에는 이름 없이 trackerId만 있음 → Tracker 정보로 이름 조회
            name = tracker_name(cl, t)
        if name:
            out.append((t or "폴더", name))
    return out


_TNAMES = {}


def tracker_name(cl, tid):
    if tid not in _TNAMES:
        ok, v = cl.get_many([f"/api/v3/trackers/{tid}"])[0]
        _TNAMES[tid] = (v.get("name") or "") if ok and isinstance(v, dict) else ""
    return _TNAMES[tid]


# =====================================================================
# CL2-1. Revision history 표 읽기 (Wiki 표 / HTML 표)
# =====================================================================
COND = "Conditional OK"
UNK = "확인불가"
FIELDS = ("Version", "Date", "Description", "Author", "Approver")
# 헤더 이름 → 필드 (소문자·영문/숫자/한글만 남긴 값으로 비교)
SYNONYMS = {
    "Version": ("version", "ver", "rev", "revision", "버전", "개정번호", "revno"),
    "Date": ("date", "일자", "날짜", "작성일", "개정일", "변경일", "revisiondate"),
    "Description": ("description", "desc", "내용", "설명", "변경내용", "개정내용", "changes", "change", "changedescription", "remark", "remarks"),
    "Author": ("author", "작성자", "writer", "editor", "createdby"),
    "Approver": ("approver", "승인자", "approvedby", "approval", "승인"),
}


def hkey(s):
    return re.sub(r"[^0-9a-z가-힣]", "", str(s or "").lower())


AUTHOR_APPROVER = "Author+Approver"


def field_of(header):
    k = hkey(header)
    if not k:
        return None
    # 'Author (Approver)'처럼 한 열에 둘 다 (사용자 확인 HWE4_03, 2026-11-24)
    if any(x in k for x in ("author", "작성자")) and any(x in k for x in ("approver", "승인자", "approval")):
        return AUTHOR_APPROVER
    for f, syn in SYNONYMS.items():
        if k in syn:
            return f
    for f, syn in SYNONYMS.items():  # 'Version No.', 'Date (YYYY-MM-DD)' 등
        if any(k.startswith(x) for x in syn if len(x) >= 4):
            return f
    return None


def _protect(s):
    """[링크|주소], [{Plugin ...}], {{...}} 안의 '|'는 칸 구분이 아님 → 임시 문자로 바꿈"""
    out, depth = [], 0
    for ch in s:
        if ch in "[{":
            depth += 1
        elif ch in "]}" and depth:
            depth -= 1
        out.append("\x00" if ch == "|" and depth else ch)
    return "".join(out)


def _strip_styles(s):
    """%%(css)글자%! 스타일 표기 제거 — css 안의 rgb(…) 괄호까지 짝 맞춰 지움"""
    while True:
        i = s.find("%%(")
        if i < 0:
            break
        depth, j = 0, i + 2
        while j < len(s):
            depth += s[j] == "("
            depth -= s[j] == ")"
            j += 1
            if depth == 0:
                break
        s = s[:i] + s[j:]
    return s.replace("%!", "").replace("/%", "")


def _wclean(s):
    s = _strip_styles(s.replace("\x00", "|")).replace("\\\\", "\n")
    s = re.sub(r"\[\{[^\]]*\}\]", "", s)              # 플러그인 호출
    s = re.sub(r"\[([^\]|]*)\|[^\]]*\]", r"\1", s)    # [표시|링크] → 표시
    s = re.sub(r"\[([^\]]*)\]", r"\1", s)
    s = re.sub(r"(\*\*|__|'{2,3}|~~|%%[\w-]*|/%)", "", s)
    return "\n".join(re.sub(r"[ \t]+", " ", x).strip() for x in s.split("\n")).strip()


def wiki_tables(text):
    """Codebeamer Wiki(JSPWiki) 표 → [[셀 목록]] 목록.
    헤더 행 '||a||b||', 일반 행 '|a|b|' (일반 행의 '||'는 빈칸). 표 다음 줄이 '|'로 시작하지 않으면 앞 칸에 이어 붙임(여러 줄 셀)."""
    tables, cur = [], None
    for raw in str(text or "").replace("\r\n", "\n").split("\n"):
        line = raw.rstrip()
        st = line.lstrip()
        if st.startswith("|"):
            p = _protect(st)
            if p.startswith("||"):
                cells = p[2:].split("||")
            else:
                cells = p[1:].split("|")
            if cells and cells[-1].strip() == "" and p.rstrip().endswith("|"):
                cells = cells[:-1]
            cells = [_wclean(c.lstrip("|")) for c in cells]
            if cur is None:
                cur = []
                tables.append(cur)
            cur.append(cells)
        elif cur is not None and st and not re.match(r"^(!{1,3}|----|\[\{|\}\]|<)", st):
            if cur[-1]:
                cur[-1][-1] = (cur[-1][-1] + "\n" + _wclean(_protect(st))).strip()
        else:
            cur = None
    return tables


def _plugin_cell(s):
    """[{Table}] 셀: 앞의 '(스타일)' 제거, '~' 이스케이프 해제"""
    s = s.strip()
    if s.startswith("("):
        depth = 0
        for i, ch in enumerate(s):
            depth += ch == "("
            depth -= ch == ")"
            if depth == 0:
                s = s[i + 1:]
                break
    s = re.sub(r"~(.)", lambda m: chr(0xF0000 + ord(m.group(1))), s, flags=re.S)  # 이스케이프 글자는 표기 해석에서 빼 둠
    s = re.sub(r"\n{2,}", "\n", _wclean(_protect(s)))
    return re.sub("[\U000F0000-\U000FFFFF]", lambda m: chr(ord(m.group()) - 0xF0000), s)


def plugin_table(body):
    """Codebeamer [{Table ...}] 플러그인 표 (실측 2026-11-24): 셀마다 한 줄 '|(스타일)값', 행은 빈 줄로 구분.
    '|'로 시작하지 않는 줄은 앞 셀에 이어 붙임(여러 줄 셀)"""
    rows, cur = [], None
    for line in body.split("\n"):
        st = line.strip()
        if not st:
            if cur:
                rows.append(cur)
            cur = None
            continue
        if st.startswith("|"):
            cur = cur if cur is not None else []
            cur.append(st.lstrip("|"))
        elif cur:
            cur[-1] += "\n" + st
    if cur:
        rows.append(cur)
    return [[_plugin_cell(c) for c in r] for r in rows]


def wiki_tables_all(text):
    """Wiki 본문의 표 전부 — [{Table}] 플러그인 표와 일반 '|' 표를 나온 순서대로"""
    text = str(text or "").replace("\r\n", "\n")
    out, pos = [], 0
    for m in re.finditer(r"\[\{Table[^\n]*\n(.*?)\}\]", text, re.S):
        out += wiki_tables(text[pos:m.start()])
        t = plugin_table(m.group(1))
        if t:
            out.append(t)
        pos = m.end()
    return out + wiki_tables(text[pos:])


class _Grid(HTMLParser):
    """HTML 표 → 행렬. rowspan·colspan(병합 셀)을 펼쳐 아래 행·옆 칸에 같은 값을 채운다. 중첩 표는 따로."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables, self.stack = [], []

    def handle_starttag(self, tag, attrs):
        at = dict(attrs)
        if tag == "table":
            self.stack.append({"rows": [], "row": None, "cell": None})
        elif not self.stack:
            return
        t = self.stack[-1]
        if tag == "tr":
            t["row"] = []
        elif tag in ("td", "th") and t["row"] is not None:
            def num(k):
                try:
                    return max(1, int(re.sub(r"\D", "", at.get(k) or "1") or 1))
                except ValueError:
                    return 1
            t["cell"] = {"txt": [], "rs": num("rowspan"), "cs": num("colspan")}
        elif tag in ("br", "p", "div", "li") and t["cell"] is not None:
            t["cell"]["txt"].append("\n")

    def handle_endtag(self, tag):
        if not self.stack:
            return
        t = self.stack[-1]
        if tag in ("td", "th") and t["cell"] is not None and t["row"] is not None:
            c = t["cell"]
            txt = "\n".join(re.sub(r"[ \t\xa0]+", " ", x).strip() for x in "".join(c["txt"]).split("\n"))
            t["row"].append((re.sub(r"\n{2,}", "\n", txt).strip(), c["rs"], c["cs"]))
            t["cell"] = None
        elif tag == "tr" and t["row"] is not None:
            t["rows"].append(t["row"])
            t["row"] = None
        elif tag == "table":
            self.stack.pop()
            self.tables.append(_expand(t["rows"]))

    def handle_data(self, data):
        if self.stack and self.stack[-1]["cell"] is not None:
            self.stack[-1]["cell"]["txt"].append(data)


def _expand(rows):
    grid, carry = [], {}  # carry[열] = (값, 남은 행 수)
    for r in rows:
        out, j = [], 0
        cells = list(r)
        while cells or any(k >= j for k in carry):
            if j in carry:
                v, n = carry[j]
                out.append(v)
                carry[j] = (v, n - 1)
                if n - 1 <= 0:
                    del carry[j]
                j += 1
                continue
            if not cells:
                break
            v, rs, cs = cells.pop(0)
            for k in range(cs):
                out.append(v)
                if rs > 1:
                    carry[j + k] = (v, rs - 1)
            j += cs
        if any(x for x in out):
            grid.append(out)
    return grid


def html_grid(html):
    p = _Grid()
    try:
        p.feed(html or "")
    except Exception:  # noqa  깨진 HTML — 읽은 데까지
        pass
    return [t for t in p.tables if t]


def any_tables(text):
    """본문이 HTML이면 HTML 표(병합 셀 펼침), 아니면 Wiki 표([{Table}] 플러그인 포함)"""
    if re.search(r"<t[dhr][\s>]", str(text or ""), re.I):
        return html_grid(text)
    return wiki_tables_all(text)


def find_rh_table(tables):
    """Revision history 표 고르기: 헤더 행(표의 앞 3행 안)에서 Version 열이 있고 필수 열이 가장 많이 맞는 표.
    반환 None 또는 {"cols": {필드: 열 번호}, "header": [...], "rows": [[...]], "missing": [필드], "table": 번호}"""
    best = None
    for ti, t in enumerate(tables):
        for hi, row in enumerate(t[:3]):
            cols = {}
            for j, c in enumerate(row):
                f = field_of(c)
                if f == AUTHOR_APPROVER:
                    cols.setdefault("Author", j)
                    cols.setdefault("Approver", j)
                elif f and f not in cols:
                    cols[f] = j
            if "Version" not in cols or len(cols) < 2:
                continue
            score = (len(cols), -ti)
            ncand = (best[1]["candidates"] if best else 0) + 1
            if best:
                best[1]["candidates"] = ncand
            if best is None or score > best[0]:
                best = (score, {"cols": cols, "header": row, "rows": t[hi + 1:], "table": ti,
                                "missing": [f for f in FIELDS if f not in cols], "candidates": ncand,
                                "combined": cols.get("Author") is not None and cols.get("Author") == cols.get("Approver")})
            break
    return best[1] if best else None


# =====================================================================
# CL2-2. Version Rule (6.2.2) — 정량 규칙 (사용자 확정 2026-11-24, SKILL.md)
# =====================================================================
VER_RE = re.compile(r"^([vV]?)\s*(\d+)\.(\d+)([a-z]*)$")


def suffix_num(s):
    """Draft 접미사 → 순번: '' = 0(공식), a=1 … z=26, aa=27 (6.2.2: v1.0z → v1.0aa)"""
    n = 0
    for ch in s:
        n = n * 26 + (ord(ch) - 96)
    return n


def suffix_str(n):
    out = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        out = chr(97 + r) + out
    return out


def parse_version(v):
    """반환 {"ok": bool, "M", "m", "s"(접미사 순번, 0=공식), "prefix": 'v'|'V'|'', "text"}"""
    t = re.sub(r"\s+", "", str(v or ""))
    m = VER_RE.match(t)
    if not m:
        return {"ok": False, "text": t}
    return {"ok": True, "prefix": m.group(1), "M": int(m.group(2)), "m": int(m.group(3)),
            "s": suffix_num(m.group(4)), "text": t}


def vkey(p):
    """정렬 키: 같은 X.Y 안에서는 Draft(a<b<…) < 공식"""
    return (p["M"], p["m"], 1 if p["s"] == 0 else 0, p["s"])


def vstr(M, m, s=0):
    return f"v{M}.{m}{suffix_str(s)}"


def allowed_next(p):
    """직전 버전 p 다음에 올 수 있는 버전 [(M, m, s)]"""
    M, m, s = p["M"], p["m"], p["s"]
    if s:  # Draft 다음: 다음 Draft 또는 같은 X.Y 공식 확정
        return [(M, m, s + 1), (M, m, 0)]
    # 공식 다음: Minor +1 (공식 또는 a부터) / Major +1, Minor 0 (공식 또는 a부터)
    return [(M, m + 1, 0), (M, m + 1, 1), (M + 1, 0, 0), (M + 1, 0, 1)]


def transition_issue(a, b):
    """a → b 가 규칙 위반이면 사유, 아니면 None"""
    nb = (b["M"], b["m"], b["s"])
    if nb in allowed_next(a):
        return None
    A, B = vstr(a["M"], a["m"], a["s"]), vstr(b["M"], b["m"], b["s"])
    exp = " 또는 ".join(vstr(*x) for x in allowed_next(a))
    if vkey(b) == vkey(a):
        return f"버전 중복 ({A})"
    if a["s"] == 0 and (b["M"], b["m"]) == (a["M"], a["m"]):
        return f"공식 확정({A}) 후 같은 버전의 Draft({B}) — 다음은 {exp}"
    if vkey(b) < vkey(a):
        return f"순서 역행 {A} → {B}"
    if a["s"] and (b["M"], b["m"]) != (a["M"], a["m"]):
        return f"Draft({A})를 공식 확정하지 않고 {B}로 변경 — 다음은 {exp}"
    if b["M"] > a["M"] and b["m"] != 0:
        return f"Major 증가 시 Minor는 0으로 초기화 {A} → {B}"
    if b["M"] > a["M"] + 1:
        return f"Major 건너뜀 {A} → {B}"
    if b["M"] == a["M"] and b["m"] > a["m"] + 1:
        return f"Minor 건너뜀 {A} → {B}"
    if b["s"] > 1 and (b["M"], b["m"]) != (a["M"], a["m"]):
        return f"Minor·Major 증가 시 Suffix는 a부터 {A} → {B}"
    if a["s"] and b["s"] > a["s"] + 1:
        return f"Suffix 건너뜀 {A} → {B}"
    return f"규칙에 맞지 않는 변경 {A} → {B} — 다음은 {exp}"


DATE_RES = (re.compile(r"^(\d{4})\s*[-./]\s*(\d{1,2})\s*[-./]\s*(\d{1,2})\.?$"),
            re.compile(r"^(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일?$"),
            re.compile(r"^(\d{4})(\d{2})(\d{2})$"))


def parse_date(s):
    t = str(s or "").strip()
    t = re.sub(r"[ T]\d{1,2}:\d{2}(:\d{2})?.*$", "", t)  # 시간 부분 제거
    for rx in DATE_RES:
        m = rx.match(t)
        if m:
            try:
                return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                return None
    return None


RANK = {"OK": 0, COND: 1, UNK: 2, "NOK": 3}


def worst(*rs):
    return max(rs, key=lambda r: RANK.get(r, 0))


def judge_table(t):
    """표 하나 → ②③ 판정과 행별 지적.
    반환 {"rows": [{"no", "values": {필드: 값}, "issues": [(등급, 사유)]}], "fill": {...}, "rule": {...},
          "order": "오름차순"|"내림차순(최신이 위)"|"", "latest": {...}}"""
    cols = t["cols"]
    rows = []
    for i, cells in enumerate(t["rows"], 1):
        vals = {f: (cells[cols[f]].strip() if f in cols and cols[f] < len(cells) else "") for f in FIELDS}
        if t.get("combined") and vals["Author"]:
            # 'Author (Approver)' 한 칸: 'Author Two (Approver Two)' → 작성자 / 승인자. 괄호가 없으면 승인자 빈칸
            m = re.match(r"^(.*?)\s*[(（]\s*(.*?)\s*[)）]\s*$", vals["Author"], re.S)
            vals["Author"], vals["Approver"] = (m.group(1).strip(), m.group(2).strip()) if m else (vals["Author"], "")
        if not any(vals.values()) and not any(c.strip() for c in cells):
            continue  # 완전히 빈 행 (양식의 여백 행)
        rows.append({"no": i, "values": vals, "issues": []})

    # ② 필수 항목
    fill_issues = []
    if t["missing"]:
        fill_issues.append(f"표에 열 없음: {', '.join(t['missing'])}")
    for r in rows:
        empty = [f for f in FIELDS if f in cols and not r["values"][f]]
        if empty:
            r["issues"].append(("NOK", f"빈칸: {', '.join(empty)}"))
            fill_issues.append(f"{r['no']}행({r['values']['Version'] or '버전 없음'}) 빈칸: {', '.join(empty)}")
    fill = {"result": "NOK" if fill_issues else "OK",
            "reason": " / ".join(fill_issues) if fill_issues else f"{len(rows)}행 모두 5개 항목 기재"}

    # ③ Version Rule
    nok, cond = [], []
    parsed = []
    for r in rows:
        v = r["values"]["Version"]
        if not v:
            continue
        p = parse_version(v)
        if not p["ok"]:
            r["issues"].append(("NOK", f"형식 위반 '{v}' (vX.Yz 아님)"))
            nok.append(f"{r['no']}행 형식 위반 '{v}'")
            continue
        if p["prefix"] == "":
            r["issues"].append((COND, f"'v' 누락 '{v}'"))
        elif p["prefix"] == "V":
            r["issues"].append((COND, f"대문자 'V' '{v}'"))
        parsed.append((r, p))
    no_v = [r["values"]["Version"] for r, p in parsed if p["prefix"] != "v"]
    if no_v:
        cond.append(f"'v' 접두어 누락/대문자 {len(no_v)}건 ({', '.join(no_v[:5])}{' …' if len(no_v) > 5 else ''})")

    order = ""
    if len(parsed) >= 2:
        # 정렬 방향: 첫·끝 행 날짜가 다르면 날짜로, 아니면 버전으로 판단 (버전 역행이 정렬로 묻히지 않도록 날짜 우선)
        d1, d2 = parse_date(parsed[0][0]["values"]["Date"]), parse_date(parsed[-1][0]["values"]["Date"])
        desc = (d1 > d2) if (d1 and d2 and d1 != d2) else vkey(parsed[0][1]) > vkey(parsed[-1][1])
        order = "내림차순(최신이 위)" if desc else "오름차순"
        if desc:
            parsed = parsed[::-1]
    elif parsed:
        order = "1행"
    if parsed:
        r0, p0 = parsed[0]
        if (p0["M"], p0["m"]) != (1, 0) or p0["s"] > 1:
            msg = f"최초 버전이 {p0['text']} — 규칙상 v1.0(Draft는 v1.0a)부터 시작"
            r0["issues"].append(("NOK", msg))
            nok.append(msg)
        prev_d = parse_date(r0["values"]["Date"])
        for (ra, pa), (rb, pb) in zip(parsed, parsed[1:]):
            why = transition_issue(pa, pb)
            if why:
                rb["issues"].append(("NOK", why))
                nok.append(f"{rb['no']}행 {why}")
            d = parse_date(rb["values"]["Date"])
            if d and prev_d and d < prev_d:
                rb["issues"].append((COND, f"날짜 역행 {prev_d} → {d}"))
                cond.append(f"{rb['no']}행 날짜 역행 ({prev_d} → {d})")
            prev_d = d or prev_d
    bad_d = []
    for r in rows:
        d = r["values"]["Date"]
        if d and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d.strip()):
            # 작성 규칙: "YYYY-MM-DD" (사용자 결정 2026-11-24 — 형식이 다르면 Conditional OK)
            r["issues"].append((COND, f"Date 형식이 YYYY-MM-DD 아님 '{d}'" if parse_date(d) else f"Date를 날짜로 읽을 수 없음 '{d}'"))
            bad_d.append(d)
    if bad_d:
        cond.append(f"Date 형식(YYYY-MM-DD) 아님 {len(bad_d)}건 ({', '.join(bad_d[:5])}{' …' if len(bad_d) > 5 else ''})")
    if "Version" not in cols or not parsed and not nok:
        rule = {"result": "NOK", "reason": "확인할 Version 값이 없음"}
    elif nok:
        rule = {"result": "NOK", "reason": " / ".join(nok + cond)}
    elif cond:
        rule = {"result": COND, "reason": " / ".join(cond)}
    else:
        rule = {"result": "OK", "reason": f"{len(parsed)}개 버전 형식·순서·증가 규칙 준수 ({order})"}
    latest = parsed[-1][0]["values"] if parsed else {}
    return {"rows": rows, "fill": fill, "rule": rule, "order": order, "latest": latest}


# =====================================================================
# CL2-3. Revision history 찾기 (Codebeamer Tracker 안의 Item / Confluence 페이지)
# =====================================================================
def is_rh_name(name, keys):
    k = hkey(name)
    return any(hkey(x) and hkey(x) in k for x in keys)


def tracker_items(cl, tid, page_size=500, max_pages=200):
    """Tracker의 Item 목록 [(id, 이름)] — 페이지 단위로 전부"""
    out, page = [], 1
    while page <= max_pages:
        v = cl.get(f"/api/v3/trackers/{tid}/items?page={page}&pageSize={page_size}")
        refs = (v.get("itemRefs") or v.get("items") or []) if isinstance(v, dict) else (v or [])
        out += [(str(x.get("id")), x.get("name") or "") for x in refs if isinstance(x, dict)]
        total = v.get("total") if isinstance(v, dict) else None
        if not refs or len(refs) < page_size or (total is not None and len(out) >= total):
            break
        page += 1
    return out


def is_template(name):
    return bool(re.search(r"template|템플릿|양식", str(name or ""), re.I))


def pick_rh_item(items, keys):
    """이름이 Revision history인 Item. 문서 이력 우선(이름에 template·템플릿·양식이 든 Item은 뒤로, 사용자 결정 2026-11-24),
    그다음 정확히 'Revision history'인 것. 여럿이면 첫 번째 + 나머지는 근거에 남김"""
    hits = [(i, n) for i, n in items if is_rh_name(n, keys)]
    hits.sort(key=lambda x: (is_template(x[1]), hkey(x[1]) not in {hkey(k) for k in keys}, len(x[1])))
    return hits


def read_item_tables(ccb, cbs, cb_base, iid, log_tried, debug=None):
    """Item 본문(description)에서 표 → 없으면 Item 화면에서 표. 반환 (표 목록, 출처)"""
    ok, v = ccb.get_many([f"/api/v3/items/{iid}"])[0]
    if not ok:
        raise ApiError(f"Item {iid} 조회 실패 ({v})")
    if debug is not None:
        debug.append((f"rh_item_{iid}.json", json.dumps(v, ensure_ascii=False, indent=1)))
    desc = v.get("description") or ""
    fmt = v.get("descriptionFormat") or ""
    tables = any_tables(desc)
    t = find_rh_table(tables)
    log_tried(f"Item {iid} 본문({fmt or '형식 미상'}, {len(desc)}자) → 표 {len(tables)}개{', Revision history 표 있음' if t else ''}")
    if t:
        log_tried(f"선택한 표 헤더: {t['header']} (Version 열 있는 표 {t['candidates']}개 중 필수 열이 가장 많은 것)")
        return t, f"Item 본문({fmt or 'Wiki'})"
    url = f"{cb_base}/issue/{iid}"
    s, html, final = cbs.fetch_text(url)
    if debug is not None:
        debug.append((f"rh_item_{iid}.html", html or ""))
    if s == 200 and not is_login_html(html, final):
        tables = any_tables(html)
        t = find_rh_table(tables)
        log_tried(f"Item {iid} 화면 → 표 {len(tables)}개{', Revision history 표 있음' if t else ''}")
        if t:
            log_tried(f"선택한 표 헤더: {t['header']} (Version 열 있는 표 {t['candidates']}개 중 필수 열이 가장 많은 것)")
            return t, "Item 화면"
        return None, "본문·화면 모두 표 없음"
    log_tried(f"Item {iid} 화면 조회 실패 (HTTP {s})")
    return None, f"본문에 표 없음, 화면 조회 실패(HTTP {s})"


def find_rh(ci, kind, ccb, ccf, cbs, cfg, forced_item=None, debug=None):
    """반환 {"result": None(찾음)|NOK|확인불가|확인 필요|수동 확인, "reason", "where", "url", "table", "tried": [..]}"""
    c2 = cfg.get("cl2", {})
    keys = c2.get("item_name_keywords") or ["Revision history", "Revision histroy", "개정 이력", "변경 이력"]
    cb_base = cfg["codebeamer"]["base"].rstrip("/")
    tried = []
    r = {"result": None, "reason": "", "where": "", "url": "", "table": None, "tried": tried, "source": "", "template": False}
    if kind == "none":
        return dict(r, result="NOK", reason="CI list에 Path in Repository가 비어 있어 Revision history 위치를 알 수 없음")
    if kind == "other":
        return dict(r, result="수동 확인", reason=f"자동 확인을 지원하지 않는 저장소({ci.get('repository') or '미기재'}) — 산출물을 열어 Revision history 직접 확인")
    if kind == "confluence":
        m = re.search(r"pageId=(\d+)", ci["path"]) or re.search(r"/pages/(\d+)", ci["path"])
        if not m or "/download/attachments/" in ci["path"]:
            return dict(r, result="수동 확인", reason="Confluence 첨부 파일·주소 형식 — 파일 안의 Revision history 직접 확인")
        try:
            pg = ccf.get(f"/rest/api/content/{m.group(1)}?expand=body.storage")
        except ApiError as e:
            if "HTTP 404" in str(e):
                return dict(r, result="NOK", reason=f"Confluence 경로의 페이지가 없음 ({e})")
            return dict(r, result=UNK, reason=f"Confluence 조회 실패 ({e})")
        t = find_rh_table(any_tables(((pg.get("body") or {}).get("storage") or {}).get("value", "")))
        url = ci["path"]
        tried.append(f"Confluence 페이지 {m.group(1)} 본문 → {'Revision history 표 있음' if t else '표 없음'}")
        if not t:
            return dict(r, result="확인 필요", url=url, where=f"Confluence '{pg.get('title', '')}'",
                        reason="Confluence 페이지 본문에 Revision history 표가 없음 — 첨부 문서 안에 있는지 직접 확인")
        return dict(r, table=t, url=url, where=f"Confluence '{pg.get('title', '')}'", source="Confluence 본문")
    if kind == "cb_page":
        s, html, final = cbs.fetch_text(ci["path"])
        if s == 404:
            return dict(r, result="NOK", reason="Codebeamer 경로가 없음 (HTTP 404)")
        if s != 200 or is_login_html(html, final):
            return dict(r, result=UNK, reason=f"Codebeamer 경로 조회 실패 (HTTP {s})")
        t = find_rh_table(any_tables(html))
        tried.append(f"Codebeamer 화면 → {'Revision history 표 있음' if t else '표 없음'}")
        if not t:
            return dict(r, result="확인 필요", url=ci["path"], reason="Codebeamer 경로(Tracker 아님) 화면에서 Revision history 표를 찾지 못함 — 직접 확인")
        return dict(r, table=t, url=ci["path"], where="Codebeamer 화면", source="화면")

    # Codebeamer Tracker
    tid = ci["trackerId"]
    if forced_item:
        cands, where = [(str(forced_item), f"(직접 지정) {forced_item}")], "직접 지정"
        tried.append(f"Item 직접 지정 --item {forced_item}")
    else:
        ok, tv = ccb.get_many([f"/api/v3/trackers/{tid}"])[0]
        if not ok:
            if str(tv).startswith("HTTP 404"):
                return dict(r, result="NOK", reason=f"경로의 Tracker({tid})가 없음 (HTTP 404)")
            return dict(r, result=UNK, reason=f"Tracker {tid} 조회 실패 ({tv})")
        scopes = [(tid, tv.get("name", ""), False)]
        if c2.get("search_upper_trackers", True):
            pid = tv.get("projectId") or (tv.get("project") or {}).get("id")
            ups = tracker_ancestors(ccb, pid, tid) if pid else None
            scopes += [(u, n, True) for u, n in (ups or []) if str(u).isdigit()]
        cands, where, tmpl = [], "", None
        for sid, sname, up in scopes:
            try:
                items = tracker_items(ccb, sid, int(c2.get("page_size", 500)))
            except ApiError as e:
                tried.append(f"Tracker '{sname}'({sid}) Item 목록 조회 실패 ({e})")
                if not up:
                    return dict(r, result=UNK, reason=f"Tracker {tid} Item 목록 조회 실패 ({e})", tried=tried)
                continue
            hits = pick_rh_item(items, keys)
            tried.append(f"{'상위 ' if up else ''}Tracker '{sname}'({sid}) Item {len(items)}개 → Revision history 이름 Item {len(hits)}개"
                         + (f": {', '.join(f'{n}({i})' for i, n in hits[:3])}" if hits else ""))
            if hits and not is_template(hits[0][1]):
                cands = hits
                where = f"{'상위 ' if up else ''}Tracker '{sname}'({sid})"
                break
            if hits and tmpl is None:  # 템플릿 이력만 → 문서 이력을 상위에서 더 찾고, 끝내 없으면 사용
                tmpl = (hits, f"{'상위 ' if up else ''}Tracker '{sname}'({sid})")
        if not cands and tmpl:
            cands, where = tmpl
            tried.append("문서 이력 Item이 없어 템플릿 이력 Item으로 판정 (최대 Conditional OK)")
        if not cands:
            return dict(r, result="NOK", reason=f"Tracker '{tv.get('name', '')}'({tid})"
                        + (" 및 상위 Tracker" if len(scopes) > 1 else "")
                        + f"에 Revision history Item이 없음 (이름 검색어: {', '.join(keys)})")
    iid, iname = cands[0]
    url = f"{cb_base}/issue/{iid}"
    extra = f" (같은 이름 Item {len(cands)}개 중 첫 번째, 나머지: {', '.join(i for i, _ in cands[1:4])})" if len(cands) > 1 else ""
    try:
        t, src = read_item_tables(ccb, cbs, cb_base, iid, tried.append, debug)
    except ApiError as e:
        return dict(r, result=UNK, url=url, where=f"{where} › '{iname}'({iid})", reason=str(e))
    w = f"{where} › '{iname}'({iid}){extra}"
    r["template"] = is_template(iname) and not forced_item
    if not t:
        return dict(r, result="NOK", url=url, where=w, reason=f"Revision history Item은 있으나 Version 열이 있는 표가 없음 ({src})")
    return dict(r, table=t, url=url, where=w, source=src)


def check_ci(ci, kind, ccb, ccf, cbs, cfg, forced_item=None, debug=None):
    """CI 하나 → {"exist": {...}, "fill": {...}, "rule": {...}, "result", "where", "url", "rows", ...}"""
    f = find_rh(ci, kind, ccb, ccf, cbs, cfg, forced_item, debug)
    base = {"where": f["where"], "url": f["url"], "tried": f["tried"], "source": f["source"], "rows": [], "order": "", "latest": {},
            "header": []}
    if f["result"] is not None:
        na = {"result": "-", "reason": "① 결과에 따름"}
        g = f["result"]
        return dict(base, exist={"result": g, "reason": f["reason"]}, fill=na, rule=na, result=g)
    t = f["table"]
    j = judge_table(t)
    base.update(rows=j["rows"], order=j["order"], latest=j["latest"], header=t["header"])
    if not j["rows"]:
        exist = {"result": "NOK", "reason": f"Revision history 표에 기록이 없음 (헤더만 있음) — {f['where']}"}
        na = {"result": "-", "reason": "① 결과에 따름"}
        return dict(base, exist=exist, fill=na, rule=na, result="NOK")
    exist = {"result": "OK", "reason": f"{f['where']} — {len(j['rows'])}행 ({f['source']})"}
    if f.get("template"):
        exist = {"result": COND, "reason": f"문서 이력 Item이 없어 템플릿 이력으로 판정 — {exist['reason']} (문서 이력이 맞는지 확인)"}
    return dict(base, exist=exist, fill=j["fill"], rule=j["rule"],
                result=worst(exist["result"], j["fill"]["result"], j["rule"]["result"]))


# =====================================================================
# CL2-4. 결과 엑셀
# =====================================================================
def build_workbook(results, meta):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    HF, HFont = PatternFill("solid", fgColor="00B0F0"), Font(bold=True, color="FFFFFF")
    LINK = Font(color="0563C1", underline="single")
    WRAP = Alignment(wrap_text=True, vertical="top")
    FILL = {"NOK": PatternFill("solid", fgColor="FFC7CE"), COND: PatternFill("solid", fgColor="FFF2CC"),
            "확인 필요": PatternFill("solid", fgColor="FFF2CC"), UNK: PatternFill("solid", fgColor="E7E6E6"),
            "수동 확인": PatternFill("solid", fgColor="DDEBF7")}
    KEYS = (("① 존재·관리", "exist"), ("② 필수 항목", "fill"), ("③ Version Rule", "rule"))

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
    order = ("OK", COND, "NOK", "확인 필요", UNK, "수동 확인", "-")

    sm = sheet(wb, "요약", ["구분"] + list(order) + ["계"], [22, 8, 14, 8, 10, 10, 10, 6, 8])
    for label, key in (("CL2 종합", None),) + KEYS:
        cnt = {}
        for r in results:
            g = r["result"] if key is None else r[key]["result"]
            cnt[g] = cnt.get(g, 0) + 1
        sm.append([label] + [cnt.get(k, 0) for k in order] + [len(results)])
    sm.append([])
    sm.append(["'-' = ①에서 Revision history를 찾지 못해 ②③을 판정하지 않음"])

    ov = sheet(wb, "Overview", ["CI ID", "Category", "CI name", "Author", "Path in Repository", "CL2 결과",
                                "① 존재·관리", "② 필수 항목", "③ Version Rule", "Revision history 위치", "기록 행 수",
                                "최신 Version", "최신 Date", "정렬", "① 근거", "② 근거", "③ 근거"],
               [20, 10, 38, 12, 40, 14, 12, 12, 14, 50, 9, 12, 12, 16, 50, 50, 60])
    for r in results:
        ov.append([r["ciId"], r["category"], r["ciName"], r["author"], None, r["result"],
                   r["exist"]["result"], r["fill"]["result"], r["rule"]["result"], None, len(r["rows"]) or None,
                   r["latest"].get("Version"), r["latest"].get("Date"), r["order"] or None,
                   r["exist"]["reason"], r["fill"]["reason"], r["rule"]["reason"]])
        n = ov.max_row
        link(ov.cell(n, 5), r["path"])
        link(ov.cell(n, 10), r["url"], r["where"] or None)
        for c in (6, 7, 8, 9):
            paint(ov.cell(n, c))
    ov.auto_filter.ref = ov.dimensions

    nk = sheet(wb, "NOK", ["CI ID", "Category", "CI name", "Author", "Revision history", "NOK 항목", "사유"],
               [20, 10, 38, 12, 40, 16, 90])
    ck = sheet(wb, "확인 필요", ["CI ID", "Category", "CI name", "Revision history", "항목", "결과", "내용", "확인 결과(사람 기입)"],
               [20, 10, 38, 40, 16, 14, 80, 20])
    for r in results:
        for label, key in KEYS:
            g = r[key]["result"]
            if g == "NOK":
                nk.append([r["ciId"], r["category"], r["ciName"], r["author"], None, label, r[key]["reason"]])
                link(nk.cell(nk.max_row, 5), r["url"] or r["path"], r["where"] or r["path"])
            elif g not in ("OK", "-"):
                ck.append([r["ciId"], r["category"], r["ciName"], None, label, g, r[key]["reason"], None])
                link(ck.cell(ck.max_row, 4), r["url"] or r["path"], r["where"] or r["path"])
                paint(ck.cell(ck.max_row, 6))
    nk.auto_filter.ref = nk.dimensions
    ck.auto_filter.ref = ck.dimensions

    # Revision history 원본 — 판정 근거 (CI별 표 그대로 + 행별 지적)
    rh = sheet(wb, "Revision history", ["CI ID", "CI name", "표 행", "Version", "Date", "Description", "Author", "Approver", "행 판정", "지적"],
               [20, 30, 6, 10, 12, 60, 14, 14, 12, 60])
    for r in results:
        for row in r["rows"]:
            g = "OK"
            for sev, _ in row["issues"]:
                g = worst(g, sev)
            v = row["values"]
            rh.append([r["ciId"], r["ciName"], row["no"], v["Version"], v["Date"], v["Description"], v["Author"], v["Approver"],
                       g, " / ".join(m for _, m in row["issues"]) or None])
            n = rh.max_row
            paint(rh.cell(n, 9))
            for c in (6, 10):
                rh.cell(n, c).alignment = WRAP
            for c, f in zip(range(4, 9), FIELDS):
                if not v[f]:
                    rh.cell(n, c).fill = FILL["NOK"]
    rh.auto_filter.ref = rh.dimensions

    tr = sheet(wb, "조회 기록", ["CI ID", "조회"], [20, 120])
    for r in results:
        for t in r["tried"] or ["-"]:
            tr.append([r["ciId"], t])

    inf = sheet(wb, "실행정보", ["항목", "값"], [28, 110])
    for k, v in meta.items():
        inf.append([k, str(v)])
        inf.cell(inf.max_row, 2).alignment = WRAP
    return wb


# =====================================================================
# CL2-5. 실행
# =====================================================================
RULE_TEXT = {
    "① 존재·관리": "등록 Tracker(없으면 상위 Tracker)에 이름이 Revision history인 Item이 있고, 그 본문(없으면 Item 화면)에 Version 열이 있는 표와 "
                 "기록 1행 이상. Item 없음·표 없음·기록 0행 = NOK. Confluence 페이지는 본문 표, 그 외 저장소는 수동 확인",
    "② 필수 항목": "Version·Date·Description·Author·Approver 열이 모두 있고, 기록된 모든 행에서 5칸이 비어 있지 않음. 열 없음·빈칸 = NOK",
    "③ Version Rule": "형식 vX.Yz(X·Y 숫자, z 소문자 Draft 접미사) — 형식 위반 NOK, 'v' 누락·대문자 V는 Conditional OK. "
                     "최초 v1.0(또는 v1.0a). 공식 vX.Y 다음은 vX.(Y+1)[a] 또는 v(X+1).0[a], Draft vX.Yz 다음은 vX.Y(z+1) 또는 vX.Y(공식 확정), "
                     "z 다음 aa. 중복·역행·건너뜀·공식 후 같은 버전 Draft·Major 증가 시 Minor 미초기화·Minor 증가 시 Suffix 미초기화 = NOK. "
                     "날짜 역행·날짜 형식 불명 = Conditional OK. 표가 최신이 위(내림차순)여도 자동 인식. Major/Minor 변경 사유가 맞는지는 판정하지 않음(사람 확인)",
}


def main(argv=None):
    ap = argparse.ArgumentParser(description="CL2 — Revision history 관리 · Version Rule 점검")
    ap.add_argument("--doctor", action="store_true", help="연결·Revision history 읽기 점검 (결과 파일 없음)")
    ap.add_argument("--ci", action="append", help="이 CI ID만 검사 (여러 번 지정 가능)")
    ap.add_argument("--item", help="Revision history Item 번호 직접 지정 (--ci 하나와 함께)")
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
    if a.item and (not a.ci or len(a.ci) != 1):
        raise ValueError("--item 은 --ci 하나와 함께 써야 합니다 (예: --ci SYS2_01 --item 1234567)")
    cfg_path = Path(a.config)
    if not cfg_path.exists():
        raise ValueError(f"설정 파일이 없습니다: {cfg_path.name} — config.example.json을 복사해 config.json을 만들고 실제 값을 넣어 주세요.")
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg.setdefault("cl2", {})
    for d in (STATE, STATE / "ci_list", STATE / "debug"):
        d.mkdir(exist_ok=True)
    out_dir = HERE / cfg.get("output_dir", "output")
    out_dir.mkdir(exist_ok=True)
    t0 = time.time()

    from playwright.sync_api import sync_playwright
    log(f"CL2 점검(Revision history · Version Rule) v{VERSION} 시작{' (점검 모드)' if a.doctor else ''}")
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
            if a.limit:
                cis = cis[:a.limit]
            if not cis:
                raise ApiError("검사할 CI가 없습니다.")

            cb = cfg["codebeamer"]
            cbs = Session(ctx, "Codebeamer", cb["base"], cb["base"] + cb.get("login_path", "/login.spr"),
                          not a.headless, get_cred("Codebeamer"))
            probe = cfg["cl2"].get("login_probe") or "/api/v3/projects"

            def cb_login():
                cbs.ensure_login(cb["base"], probe, lambda b: isinstance(b, (list, dict)) and not (isinstance(b, dict) and b.get("type") == "anonymous"))
                cbs.pin(cb["base"] + probe)
            cb_login()
            log("3. Codebeamer 로그인 확인")
            ccb = Client(cbs.fetch_json, cb["base"], batch=cfg.get("batch_size", 10), relogin=cb_login)

            if a.doctor:
                picks = [c for c in cis if repo_kind(c, cfg) == "cb_tracker"][:3]
                for c in picks:
                    dbg = []
                    rr = check_ci(c, "cb_tracker", ccb, ccf, cbs, cfg, a.item, dbg)
                    for t in rr["tried"]:
                        log(f"   조회 [{c['ciId']}] {t}")
                    for name, body in dbg:
                        (STATE / "debug" / name).write_text(body, encoding="utf-8")
                        log(f"   저장: state\\debug\\{name}")
                    log(f"   [{c['ciId']}] 헤더: {rr['header']}")
                    for row in rr["rows"][:6]:
                        log(f"   [{c['ciId']}] {row['no']}행 {row['values']}")
                    log(f"   [{c['ciId']}] ① {rr['exist']['result']} ② {rr['fill']['result']} ③ {rr['rule']['result']} — {rr['rule']['reason'][:120]}")
                log("✔ 점검 완료 — 위 행이 Codebeamer 화면의 Revision history 표와 같으면 run_cl2.bat 으로 실행하세요.")
                log("   (다르면 위 '조회' 줄과 state\\debug 폴더의 rh_item_* 파일을 Claude에게 전달)")
                return 0

            results = []
            for n, c in enumerate(cis, 1):
                k = repo_kind(c, cfg)
                dbg = []
                try:
                    rr = check_ci(c, k, ccb, ccf, cbs, cfg, a.item, dbg)
                    if rr["result"] != "OK":  # OK가 아니면 원본을 남겨 원인 확인에 사용
                        for name, body in dbg:
                            (STATE / "debug" / f"{c['ciId']}_{name}").write_text(body, encoding="utf-8")
                except NeedLogin:
                    raise
                except Exception as e:  # noqa
                    na = {"result": "-", "reason": "① 결과에 따름"}
                    rr = {"exist": {"result": UNK, "reason": f"조회 중 오류: {e}"}, "fill": na, "rule": na, "result": UNK,
                          "where": "", "url": "", "tried": [f"오류: {e}"], "source": "", "rows": [], "order": "", "latest": {}, "header": []}
                results.append(dict(c, kind=k, **rr))
                log(f"4. ({n}/{len(cis)}) {c['ciId']:<22} {rr['result']:<14} ① {rr['exist']['result']:<10} ② {rr['fill']['result']:<6} "
                    f"③ {rr['rule']['result']:<14} {c['ciName'][:36]}")
        finally:
            ctx.close()

    meta = {
        "실행 시각": time.strftime("%Y-%m-%d %H:%M:%S"),
        "도구": f"CL2 cl2_check.py v{VERSION}",
        "CI list 파일": f"{latest['title']} (Confluence 업로드 {latest['when']} {latest['by']})",
        "CI 선별": f"전체 {info['total']} / PBL 없음 제외 {info['no_pbl']} / 검사 {len(results)}"
                 + (" (일부 CI만 지정 실행)" if a.ci or a.limit else ""),
        "Revision history Item 이름 검색어": ", ".join(cfg["cl2"].get("item_name_keywords") or ["Revision history", "Revision histroy", "개정 이력", "변경 이력"]),
        **RULE_TEXT,
        "종합 판정": "①②③ 중 가장 나쁜 결과 (NOK > 확인불가 > Conditional OK > OK)",
        "원칙": "조회 실패 = 확인불가 (OK/NOK로 넘기지 않음) · 읽기 전용 · 결과는 새 파일 · 등급(N/P/L/F)은 판정하지 않음",
        "소요 시간": f"{time.time() - t0:.0f}초",
        "주의": "자동 생성 초안입니다. 공식 산출물 반영·저장은 담당자가 검토 후 직접 합니다.",
    }
    wb = build_workbook(results, meta)
    out = out_dir / f"CL2_RevisionHistory_{cfg.get('project', '')}_{time.strftime('%Y-%m-%d_%H%M')}.xlsx"
    wb.save(out)
    cnt = {g: sum(r["result"] == g for r in results) for g in ("OK", COND, "NOK", UNK, "확인 필요", "수동 확인")}
    log("5. 완료 — CI {} 개 · ".format(len(results)) + " · ".join(f"{k} {v}" for k, v in cnt.items() if v))
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

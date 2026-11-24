#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CL1 점검 — CI 저장소 관리 · Baseline 포함 (v1.0)

체크리스트 CL1에서 CI마다 두 가지를 확인한다.
  ① CI list에 등록된 저장소(Path in Repository)에서 해당 산출물(CI name)이 실제로 관리되고 있는가
  ② 해당 산출물이 최신 PBL Baseline의 대상 산출물 목록(Description)에 포함되어 있는가 (버전은 비교 안 함)
NOK = ① 저장소에서 관리되지 않음 / ② Baseline에 없음

흐름: Confluence 최신 CI list → PBL CI 선별(저장소 종류 무관) → Codebeamer 최신 Baseline의 Description 표 읽기
      → CI별 ①② 판정 → 엑셀(요약·Overview·NOK·확인 필요·Baseline·조회 기록·실행정보)

체크리스트 6번(추적성, traceability 폴더)과는 별개 도구. 로그인·CI list 읽기 코드는 같은 방식을 복사해 사용.
원칙: 읽기 전용(GET) · 조회 실패 = 확인불가 · 결과는 항상 새 파일

사용:   python cl1_check.py                     # 전체
        python cl1_check.py --doctor            # 연결·Baseline 조회 경로 점검
        python cl1_check.py --ci CI_ID          # 일부 CI만
        python cl1_check.py --baseline-id 9705300   # Baseline 직접 지정
        python cl1_check.py --baseline-file desc.txt # Description을 복사해 둔 파일로 판정
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

VERSION = "1.6"
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

# =====================================================================
# 1-1. 로그인 정보 (Windows 자격 증명 관리자 — 파일에 저장하지 않음)
# =====================================================================
CRED_SERVICE = "AUTO-CL1 ci-baseline"
CRED_SERVICE_FALLBACK = "AUTO-001 traceability"  # 추적성 도구에 저장한 로그인 정보도 사용


def get_cred(name):
    """저장된 ID/PW. CL1 전용 저장값이 없으면 추적성 도구(AUTO-001)에 저장한 값을 쓴다."""
    try:
        import keyring
        for svc in (CRED_SERVICE, CRED_SERVICE_FALLBACK):
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
    print("CL1 점검 로그인 정보 저장 — Windows 자격 증명 관리자에 암호화되어 이 Windows 계정에서만 읽힙니다.")
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


# =====================================================================
# CL1-1. 이름 비교
# =====================================================================
def name_key(s):
    """이름 비교용: 소문자, 영문·숫자·한글만 남김 (공백·기호·줄바꿈 차이 무시)"""
    return re.sub(r"[^0-9a-z가-힣]", "", str(s or "").lower())


def name_match(ci_name, candidates, similar=0.9):
    """CI name과 후보 이름 목록 비교.
    반환 {"level": "exact"|"similar"|"none", "name": 가장 비슷한 후보, "ratio": 유사도, "index": 후보 순번}
    exact = 공백·기호·대소문자만 다름 / similar = 철자 유사도 ≥ similar (예: ADCU50 vs ADCU50S, 오타) → 사람 확인 권장"""
    import difflib
    k = name_key(ci_name)
    best = {"level": "none", "name": "", "ratio": 0.0, "index": None}
    if not k:
        return best
    for i, c in enumerate(candidates):
        ck = name_key(c)
        if not ck:
            continue
        if ck == k:
            return {"level": "exact", "name": c, "ratio": 1.0, "index": i}
        r = difflib.SequenceMatcher(None, k, ck).ratio()
        if r > best["ratio"]:
            best = {"level": "none", "name": c, "ratio": round(r, 3), "index": i}
    if best["ratio"] >= similar:
        best["level"] = "similar"
    return best


# =====================================================================
# CL1-2. Baseline Description 해석 (HTML 표 / Wiki 표 / 일반 텍스트)
# =====================================================================
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


def _rows_after_header(rows, header_kw):
    """header_kw('산출물')가 든 행 다음부터의 (이름, 버전) 목록. 헤더가 없으면 None"""
    for i, cells in enumerate(rows):
        if any(header_kw in c for c in cells):
            out = []
            for cs in rows[i + 1:]:
                cs = [c for c in cs]
                if not cs or not cs[0].strip():
                    continue
                out.append((cs[0].strip(), cs[1].strip() if len(cs) > 1 else ""))
            return out
    return None


def parse_baseline_desc(text, header_kw="산출물"):
    """Baseline Description에서 (산출물 이름, 버전) 목록을 뽑는다. 못 찾으면 []."""
    text = text or ""
    if re.search(r"<t[dr][\s>]", text, re.I):
        best = None
        for rows in html_tables(text):
            got = _rows_after_header([r["cells"] for r in rows], header_kw)
            if got and (best is None or len(got) < len(best)):  # 헤더가 든 가장 안쪽(작은) 표
                best = got
        if best:
            return best
        text = re.sub(r"<[^>]+>", "\n", text)  # 표가 아니면 태그를 지우고 텍스트로
    lines = [ln for ln in text.splitlines() if ln.strip()]
    wiki = [ln for ln in lines if ln.strip().startswith("|")]
    if wiki:
        rows = [[_wiki_clean(c) for c in re.split(r"\|\|?", re.sub(r"\[([^\]|]*)\|[^\]]*\]", r"\1", ln.strip()).strip("|"))] for ln in wiki]
        rows = [[c for c in r if c != ""] or [""] for r in rows]
        got = _rows_after_header(rows, header_kw)
        if got:
            return got
    # 일반 텍스트 (화면에서 복사해 붙여넣은 경우): 탭 또는 2칸 이상 공백으로 이름 / 버전
    rows = []
    for ln in lines:
        parts = [x.strip() for x in re.split(r"\t+| {2,}", ln.strip()) if x.strip()]
        if len(parts) == 1:
            m = re.match(r"(.+?)\s+(v\d[\d.]*|-)$", parts[0])
            parts = [m.group(1), m.group(2)] if m else parts
        rows.append(parts)
    return _rows_after_header(rows, header_kw) or []


def name_date(name):
    m = re.search(r"(20\d\d)[-_.]?(\d\d)[-_.]?(\d\d)", name or "")
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else ""


def _ts(v):
    if v in (None, ""):
        return 0
    if isinstance(v, (int, float)):
        return v / 1000 if v > 1e11 else v
    try:
        return dt.datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0


def pick_latest(cands, keywords, must):
    """keywords(모두 포함) + must(모두 포함) 이름의 Baseline 중 최신 1개.
    최신 판단: 생성 시각(API) → 이름의 날짜(_2026-11-19) → 목록 순서(위가 최신)"""
    def has_all(n, ws):
        return all(w.lower() in n.lower() for w in ws)
    pool = [c for c in cands if has_all(c["name"], keywords) and has_all(c["name"], must)]
    pool.sort(key=lambda c: (_ts(c.get("created")), name_date(c["name"]), -c.get("order", 0)), reverse=True)
    return pool


# =====================================================================
# CL1-3. Baseline 가져오기 (API → 화면 순으로 시도, 각 시도를 기록)
# =====================================================================
def _as_list(b):
    if isinstance(b, list):
        return b
    if isinstance(b, dict):
        for k in ("items", "baselines", "results", "content"):
            if isinstance(b.get(k), list):
                return b[k]
    return []


def _id_from(s):
    m = re.search(r"(?:doc_id=|/doc/|/baseline/|baselineId=|revision=|/document/)(\d+)", str(s or ""))
    if m:
        return m.group(1)
    m = re.search(r"/(\d{4,})(?:\D*$)", str(s or ""))
    return m.group(1) if m else ""


def baselines_from_api(cl, pid, tried):
    """API로 Baseline 목록. 성공하면 [{id,name,created,desc,url,source}]"""
    for path in (f"/api/v3/projects/{pid}/baselines", f"/rest/project/{pid}/baselines"):
        ok, v = cl.get_many([path])[0]
        lst = _as_list(v) if ok else []
        tried.append(f"목록 {path} → {'성공 ' + str(len(lst)) + '건' if ok and lst else (v if not ok else '응답에 목록 없음')}")
        if lst:
            out = []
            for i, b in enumerate(lst):
                if not isinstance(b, dict) or not b.get("name"):
                    continue
                bid = str(b.get("id") or _id_from(b.get("uri")) or "")
                out.append({"id": bid, "name": b["name"], "order": i, "source": path,
                            "created": b.get("createdAt") or b.get("createdOn") or b.get("created") or b.get("submittedAt"),
                            "by": ((b.get("createdBy") or b.get("owner") or {}).get("name") if isinstance(b.get("createdBy") or b.get("owner"), dict) else ""),
                            "desc": b.get("description"), "links": []})
            return out
    return []


class _BaselineMeta(HTMLParser):
    """Codebeamer Baselines 화면의 행마다 있는 숨은 정보
    <span class="metaData" data-baseline-id=… data-baseline-name=… data-baseline-created-timestamp=…
          data-baseline-url=… data-baseline-description="(Description HTML, 표 포함)">  (실측 2026-11-24)"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []

    def handle_starttag(self, tag, attrs):
        at = dict(attrs)
        if at.get("data-baseline-name"):
            self.out.append(at)


def baselines_from_meta(html):
    p = _BaselineMeta()
    try:
        p.feed(html or "")
    except Exception:  # noqa
        pass
    out = []
    for i, at in enumerate(p.out):
        ts = at.get("data-baseline-created-timestamp") or ""
        out.append({"id": str(at.get("data-baseline-id") or ""), "name": at["data-baseline-name"].strip(), "order": i,
                    "source": "화면(metaData)", "created": int(ts) if ts.isdigit() else None,
                    "by": at.get("data-baseline-owner", ""), "desc": at.get("data-baseline-description"),
                    "links": [at["data-baseline-url"]] if at.get("data-baseline-url") else []})
    return out


def baselines_from_html(fetch_text, cb_base, pid, tried, keywords):
    """Baselines 화면(/project/{pid}/baselines)의 표에서 이름·링크를 읽는다."""
    url = f"{cb_base}/project/{pid}/baselines"
    s, html, final = fetch_text(url)
    login = s == 401 or is_login_html(html, final)
    tried.append(f"화면 {url} → HTTP {s}{' (로그인 화면)' if login else ''}")
    if s != 200 or login:
        return [], html
    meta = [b for b in baselines_from_meta(html) if all(k.lower() in b["name"].lower() for k in keywords)]
    if meta:
        tried.append(f"   화면 숨은 정보(metaData)에서 '{' '.join(keywords)}' Baseline {len(meta)}건")
        return meta, html
    out, seen = [], set()
    for rows in html_tables(html):
        for row in rows:
            for href, text in row["links"]:
                if text and all(k.lower() in text.lower() for k in keywords) and text not in seen:
                    seen.add(text)
                    out.append({"id": _id_from(href), "name": text, "order": len(out), "source": "화면",
                                "created": None, "by": "", "desc": None,
                                "links": [h for h, _ in row["links"] if h], "row_text": " | ".join(row["cells"])})
    tried.append(f"   화면에서 '{' '.join(keywords)}' Baseline {len(out)}건")
    return out, html


def baseline_desc(cl, fetch_text, cb_base, b, header_kw, tried, debug):
    """선택한 Baseline의 Description 표 → [(이름, 버전)], 출처 설명"""
    if b.get("desc"):
        rows = parse_baseline_desc(b["desc"], header_kw)
        tried.append(f"Description({b.get('source', '목록')}) → {len(rows)}행")
        if rows:
            return rows, f"{b.get('source', '목록')}의 description"
    bid = b.get("id")
    if bid:
        for path in (f"/api/v3/baselines/{bid}", f"/rest/baseline/{bid}", f"/rest/document/{bid}"):
            ok, v = cl.get_many([path])[0]
            d = v.get("description") if ok and isinstance(v, dict) else None
            rows = parse_baseline_desc(d, header_kw) if d else []
            tried.append(f"상세 {path} → {('description ' + str(len(rows)) + '행') if ok else v}")
            if rows:
                return rows, f"API {path}"
    urls = []
    for h in b.get("links") or []:
        u = h if h.startswith("http") else (re.sub(r"(https?://[^/]+).*", r"\1", cb_base) + h if h.startswith("/") else "")
        if u and u not in urls:
            urls.append(u)
    if bid:
        urls += [f"{cb_base}/doc/{bid}", f"{cb_base}/proj/doc/details.do?doc_id={bid}", f"{cb_base}/document/{bid}/properties"]
    for u in dict.fromkeys(urls):
        if re.search(r"(javascript:|#$|/user/|/userdata/|/sign)", u, re.I):
            continue
        s, html, _ = fetch_text(u)
        rows = parse_baseline_desc(html, header_kw) if s == 200 else []
        tried.append(f"화면 {u} → HTTP {s}, 표 {len(rows)}행")
        debug.append((u, s, html))
        if rows:
            return rows, f"화면 {u}"
    return [], ""


# =====================================================================
# CL1-4. ① 저장소 관리 확인
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


COND = "Conditional OK"


def grade(ratio, th):
    """유사도 → 판정 (사용자 결정 2026-11-24): ≥ th[0](90%) OK / ≥ th[1](80%) Conditional OK / 그 미만 NOK"""
    if ratio is None:
        return None
    return "OK" if ratio >= th[0] else (COND if ratio >= th[1] else "NOK")


def check_repo(ci, kind, ccb, ccf, cbs, cfg, th):
    """반환 {"result": OK|Conditional OK|NOK|확인 필요|확인불가|수동 확인, "found": 저장소에서 찾은 이름,
            "reason": 근거, "ratio": 이름 유사도(0~1, 비교하지 않았으면 None)}"""
    r = {"result": "", "found": "", "reason": "", "ratio": None}
    if kind == "none":
        return dict(r, result="NOK", reason="CI list에 Path in Repository가 비어 있음")
    if kind == "other":
        return dict(r, result="수동 확인", reason=f"자동 확인을 지원하지 않는 저장소({ci.get('repository') or '미기재'}) — 경로를 열어 직접 확인")
    if kind == "cb_tracker":
        tid = ci["trackerId"]
        ok, v = ccb.get_many([f"/api/v3/trackers/{tid}"])[0]
        if not ok:
            if str(v).startswith("HTTP 404"):
                return dict(r, result="NOK", reason=f"경로의 Tracker({tid})가 없음 (HTTP 404 — 삭제·이동되었거나 번호 오기)")
            return dict(r, result="확인불가", reason=f"Tracker {tid} 조회 실패 ({v})")
        tname = v.get("name", "")
        r["found"] = f"{tname} ({tid})"
        m = name_match(ci["ciName"], [tname], th[1])
        best = {"ratio": m["ratio"], "id": tid, "name": tname, "up": False}
        pid = v.get("projectId") or (v.get("project") or {}).get("id")
        ups = None
        if m["ratio"] < th[0] and pid:
            # 등록 Tracker가 하위 Tracker인 경우 → 상위 Tracker 이름으로 비교 (CL6와 같은 상위 기준, 사용자 결정 2026-11-24)
            ups = tracker_ancestors(ccb, pid, tid)
            for uid, uname in ups or []:
                mu = name_match(ci["ciName"], [uname], th[1])
                if mu["ratio"] > best["ratio"]:
                    best = {"ratio": mu["ratio"], "id": uid, "name": uname, "up": True}
        g = grade(best["ratio"], th)
        r["ratio"] = best["ratio"]
        if best["up"]:
            r["found"] = f"{best['name']} ({best['id']}) ← 등록: {tname} ({tid})"
        where = f"등록 Tracker는 하위 Tracker → 상위 '{best['name']}'({best['id']})" if best["up"] else "경로의 Tracker"
        if g == "OK":
            return dict(r, result="OK", reason=f"{where} 이름 = CI name" + ("" if best["ratio"] == 1 else f" (유사도 {best['ratio']:.0%})"))
        if g == COND:
            return dict(r, result=COND, reason=f"{where} 이름이 CI name과 일부 다름 (유사도 {best['ratio']:.0%}) — 같은 산출물인지 확인")
        if v.get("deleted") or v.get("hidden"):
            return dict(r, result="NOK", reason="경로의 Tracker가 삭제/숨김 상태")
        others = project_trackers(ccb, pid) if pid else None
        if others:
            mm = name_match(ci["ciName"], [n for _, n in others], th[1])
            if mm["ratio"] >= th[0]:  # 힌트는 90% 이상만 (80%대는 SIT·SQT처럼 다른 산출물이 걸림)
                oid, oname = others[mm["index"]]
                return dict(r, result="NOK", reason=f"경로의 Tracker 이름('{tname}')이 CI name과 다름. "
                                                    f"비슷한 이름의 Tracker가 다른 위치에 있음: '{oname}' ({oid}, 유사도 {mm['ratio']:.0%}) — CI list 경로 오기 가능성")
        upn = f" / 상위: {' > '.join(repr(n) for _, n in reversed(ups))}" if ups else (" / 트리에서 상위를 찾지 못함" if ups == [] else "")
        return dict(r, result="NOK", reason=f"경로의 Tracker 이름('{tname}')이 CI name과 다름 (유사도 {best['ratio']:.0%}){upn}")
    if kind == "confluence":
        path = ci["path"]
        pid = (re.search(r"pageId=(\d+)", path) or re.search(r"/pages/(\d+)", path) or re.search(r"/attachments/(\d+)/", path))
        try:
            if "/download/attachments/" in path and pid:
                fname = re.sub(r"\?.*", "", path.rsplit("/", 1)[-1])
                from urllib.parse import unquote, quote
                fname = unquote(fname)
                res = ccf.get(f"/rest/api/content/{pid.group(1)}/child/attachment?filename={quote(fname)}&limit=5")
                if not res.get("results"):
                    return dict(r, result="NOK", reason=f"Confluence 페이지 {pid.group(1)}에 첨부 '{fname}'이 없음")
                title = res["results"][0].get("title", fname)
            elif pid:
                title = ccf.get(f"/rest/api/content/{pid.group(1)}").get("title", "")
            else:
                m = re.search(r"/display/([^/]+)/([^?#]+)", path)
                if not m:
                    return dict(r, result="수동 확인", reason="Confluence 주소 형식을 해석하지 못함 — 직접 확인")
                from urllib.parse import unquote, quote
                t = unquote(m.group(2)).replace("+", " ")
                res = ccf.get(f"/rest/api/content?spaceKey={m.group(1)}&title={quote(t)}")
                if not res.get("results"):
                    return dict(r, result="NOK", reason=f"Confluence에 '{t}' 페이지가 없음")
                title = res["results"][0].get("title", t)
        except ApiError as e:
            if "HTTP 404" in str(e):
                return dict(r, result="NOK", reason=f"Confluence 경로의 페이지가 없음 ({e})")
            return dict(r, result="확인불가", reason=f"Confluence 조회 실패 ({e})")
        r["found"] = title
        m = name_match(ci["ciName"], [title], th[1])
        if name_key(ci["ciName"]) and name_key(ci["ciName"]) in name_key(title):
            return dict(r, result="OK", ratio=1.0, reason="Confluence 경로의 제목에 CI name 있음")
        g = grade(m["ratio"], th)
        r["ratio"] = m["ratio"]
        if g == "OK":
            return dict(r, result="OK", reason=f"Confluence 경로의 제목 = CI name (유사도 {m['ratio']:.0%})")
        if g == COND:
            return dict(r, result=COND, reason=f"Confluence 제목이 CI name과 일부 다름 (유사도 {m['ratio']:.0%}) — 확인")
        return dict(r, result="NOK", reason=f"Confluence 경로의 제목('{title}')이 CI name과 다름 (유사도 {m['ratio']:.0%})")
    # cb_page: Codebeamer의 Tracker가 아닌 화면 (문서·위키 등)
    s, html, final = cbs.fetch_text(ci["path"])
    if s == 404:
        return dict(r, result="NOK", reason="Codebeamer 경로가 없음 (HTTP 404)")
    if s != 200 or is_login_html(html, final):
        return dict(r, result="확인불가", reason=f"Codebeamer 경로 조회 실패 (HTTP {s})")
    t = re.search(r"<title[^>]*>(.*?)</title>", html or "", re.I | re.S)
    title = re.sub(r"\s+", " ", t.group(1)).strip() if t else ""
    r["found"] = title
    if name_key(ci["ciName"]) and name_key(ci["ciName"]) in name_key(re.sub(r"<[^>]+>", " ", html)):
        return dict(r, result="OK", reason="Codebeamer 경로 화면에 CI name 있음")
    return dict(r, result="확인 필요", reason=f"Codebeamer 경로는 열리지만 화면에서 CI name을 찾지 못함 (제목 '{title}') — 직접 확인")


# =====================================================================
# CL1-5. ② Baseline 포함 확인
# =====================================================================
def taken_rows(cis, rows):
    """다른 CI가 이름이 정확히 같아(100%) 이미 차지한 Baseline 항목 번호 {번호: CI ID}.
    실측: Baseline 항목끼리도 서로 다른 산출물인데 80~90% 비슷한 쌍이 많음
    (예: System/Software Integration Test Specification 90%) → 빠진 산출물이 이웃 항목에 유사 일치로 걸리지 않게 한다."""
    keys = {name_key(n): i for i, (n, _) in enumerate(rows or [])}
    out = {}
    for c in cis:
        i = keys.get(name_key(c["ciName"]))
        if i is not None:
            out.setdefault(i, c["ciId"])
    return out


def check_baseline(ci, rows, th, taken=None):
    if rows is None:
        return {"result": "확인불가", "item": "", "version": "", "reason": "Baseline 내용을 읽지 못함 (확인불가 탭 참고)",
                "index": None, "ratio": None}
    exact = [i for i, (n, _) in enumerate(rows) if name_key(n) and name_key(n) == name_key(ci["ciName"])]
    if exact:
        i = exact[0]
        return {"result": "OK", "item": rows[i][0], "version": rows[i][1], "index": i, "ratio": 1.0, "reason": "Baseline 대상 산출물에 있음"}
    taken = taken or {}
    free = [i for i in range(len(rows)) if i not in taken]  # 다른 CI가 정확히 차지한 항목은 유사 일치 후보에서 제외
    m = name_match(ci["ciName"], [rows[i][0] for i in free], th[1])
    if m["index"] is not None:
        m["index"] = free[m["index"]]
    g = grade(m["ratio"], th)
    if g == "OK":
        return {"result": "OK", "item": m["name"], "version": rows[m["index"]][1], "index": m["index"], "ratio": m["ratio"],
                "reason": "Baseline 대상 산출물에 있음" + ("" if m["ratio"] == 1 else f" (유사도 {m['ratio']:.0%})")}
    if g == COND:
        return {"result": COND, "item": m["name"], "version": rows[m["index"]][1], "index": m["index"], "ratio": m["ratio"],
                "reason": f"Baseline 항목 이름이 CI name과 일부 다름 (유사도 {m['ratio']:.0%}) — 같은 산출물인지 확인"}
    hint = f" — 가장 비슷한 항목: '{m['name']}' ({m['ratio']:.0%})" if m["name"] and m["ratio"] >= 0.6 else ""
    near = name_match(ci["ciName"], [rows[i][0] for i in taken], th[1]) if taken else None
    if near and near["ratio"] >= th[1]:
        ti = list(taken)[near["index"]]
        hint += f" (비슷한 '{rows[ti][0]}'({near['ratio']:.0%})는 {taken[ti]}의 항목이라 제외)"
    return {"result": "NOK", "item": "", "version": "", "reason": "Baseline 대상 산출물에 없음" + hint, "index": None, "ratio": m["ratio"]}


# =====================================================================
# CL1-6. 엑셀
# =====================================================================
def build_workbook(results, base_info, meta):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    HF, HFont = PatternFill("solid", fgColor="00B0F0"), Font(bold=True, color="FFFFFF")
    LINK = Font(color="0563C1", underline="single")
    FILL = {"NOK": PatternFill("solid", fgColor="FFC7CE"), COND: PatternFill("solid", fgColor="FFF2CC"),
            "확인 필요": PatternFill("solid", fgColor="FFF2CC"), "확인불가": PatternFill("solid", fgColor="E7E6E6"),
            "수동 확인": PatternFill("solid", fgColor="DDEBF7")}

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

    # 요약
    sm = sheet(wb, "요약", ["구분", "OK", COND, "NOK", "확인 필요", "확인불가", "수동 확인", "계"], [26, 8, 14, 8, 10, 10, 10, 8])
    for label, key in (("① 저장소 관리", "repo"), ("② Baseline 포함", "base")):
        cnt = {}
        for r in results:
            cnt[r[key]["result"]] = cnt.get(r[key]["result"], 0) + 1
        sm.append([label] + [cnt.get(k, 0) for k in ("OK", COND, "NOK", "확인 필요", "확인불가", "수동 확인")] + [len(results)])
    sm.append([])
    sm.append(["NOK CI 수 (① 또는 ②)", sum(1 for r in results if "NOK" in (r["repo"]["result"], r["base"]["result"]))])
    sm.append(["사용한 Baseline", base_info.get("name") or "(확인불가)"])
    if base_info.get("url"):
        link(sm.cell(sm.max_row, 2), base_info["url"], base_info["name"])

    # Overview
    ov = sheet(wb, "Overview", ["CI ID", "Category", "CI name", "Author", "Repository", "Path in Repository",
                                "① 저장소 관리", "① 유사도", "① 저장소에서 찾은 이름", "① 근거",
                                "② Baseline 포함", "② 유사도", "② Baseline 항목", "② 버전(참고)", "② 근거", "NOK 사유"],
               [22, 10, 40, 12, 14, 45, 14, 9, 36, 50, 14, 9, 40, 10, 50, 60])
    for r in results:
        nok = [f"① {r['repo']['reason']}" if r["repo"]["result"] == "NOK" else "",
               f"② {r['base']['reason']}" if r["base"]["result"] == "NOK" else ""]
        ov.append([r["ciId"], r["category"], r["ciName"], r["author"], r["repository"], None,
                   r["repo"]["result"], r["repo"].get("ratio"), r["repo"]["found"], r["repo"]["reason"],
                   r["base"]["result"], r["base"].get("ratio"), r["base"]["item"], r["base"]["version"], r["base"]["reason"],
                   " / ".join(x for x in nok if x) or None])
        link(ov.cell(ov.max_row, 6), r["path"])
        paint(ov.cell(ov.max_row, 7)); paint(ov.cell(ov.max_row, 11))
        for c in (8, 12):
            ov.cell(ov.max_row, c).number_format = "0%"
            ov.cell(ov.max_row, c).alignment = Alignment(horizontal="center")
    ov.auto_filter.ref = ov.dimensions

    # NOK 목록
    nk = sheet(wb, "NOK", ["CI ID", "Category", "CI name", "Author", "Path in Repository", "NOK 항목", "사유"],
               [22, 10, 40, 12, 45, 22, 80])
    for r in results:
        for label, key in (("① 저장소 미관리", "repo"), ("② Baseline 미포함", "base")):
            if r[key]["result"] == "NOK":
                nk.append([r["ciId"], r["category"], r["ciName"], r["author"], None, label, r[key]["reason"]])
                link(nk.cell(nk.max_row, 5), r["path"])
    nk.auto_filter.ref = nk.dimensions

    # 확인 필요 (Conditional OK · 확인 필요 · 확인불가 · 수동 확인)
    ck = sheet(wb, "확인 필요", ["CI ID", "Category", "CI name", "Path in Repository", "항목", "결과", "내용", "확인 결과(사람 기입)"],
               [22, 10, 40, 45, 16, 12, 80, 20])
    for r in results:
        for label, key in (("① 저장소", "repo"), ("② Baseline", "base")):
            if r[key]["result"] not in ("OK", "NOK"):
                ck.append([r["ciId"], r["category"], r["ciName"], None, label, r[key]["result"], r[key]["reason"], None])
                link(ck.cell(ck.max_row, 4), r["path"])
                paint(ck.cell(ck.max_row, 6))
    ck.auto_filter.ref = ck.dimensions

    # Baseline 내용 — 대상 산출물 각각이 CI list의 어느 CI와 맞았는지
    bl = sheet(wb, "Baseline", ["No", "Baseline 대상 산출물", "버전", "맞은 CI ID", "비고"], [6, 50, 10, 30, 50])
    rows = base_info.get("rows") or []
    hit = {}
    for r in results:
        if r["base"].get("index") is not None:
            hit.setdefault(r["base"]["index"], []).append(r["ciId"])
    for i, (n, v) in enumerate(rows):
        bl.append([i + 1, n, v, ", ".join(hit.get(i, [])) or None,
                   None if i in hit else "검사 대상 CI 중 이 이름의 CI 없음 (CI list에 없거나 PBL 미지정·이름 다름)"])
        if i not in hit:
            bl.cell(bl.max_row, 5).fill = FILL[COND]
    if not rows:
        bl.append([None, "(Baseline 내용을 읽지 못함)"])

    # Baseline 후보 — 어떤 Baseline을 골랐는지 근거
    bc = sheet(wb, "Baseline 후보", ["선택", "Baseline", "생성", "출처"], [8, 60, 22, 30])
    for c in base_info.get("candidates") or []:
        bc.append(["◀ 사용" if c.get("name") == base_info.get("name") else None, c["name"], str(c.get("created") or name_date(c["name"]) or ""), c.get("source", "")])

    # 확인 경로 — Baseline 조회 시도 기록
    tr = sheet(wb, "조회 기록", ["Baseline 조회 시도"], [120])
    for t in base_info.get("tried") or []:
        tr.append([t])

    inf = sheet(wb, "실행정보", ["항목", "값"], [28, 100])
    for k, v in meta.items():
        inf.append([k, str(v)])
    return wb


# =====================================================================
# CL1-7. 실행
# =====================================================================
def get_baseline(ccb, cbs, cfg, a, tried, debug):
    bc = cfg["cl1"]["baseline"]
    cb_base = cfg["codebeamer"]["base"].rstrip("/")
    header_kw = bc.get("header_keyword", "산출물")
    info = {"name": "", "url": "", "rows": None, "candidates": [], "tried": tried, "from": ""}
    if a.baseline_file:
        p = Path(a.baseline_file)
        txt = p.read_bytes().decode("utf-8", "replace")
        rows = parse_baseline_desc(txt, header_kw)
        tried.append(f"직접 지정 파일 {p.name} → {len(rows)}행")
        info.update(name=f"(파일) {p.name}", rows=rows or None, **{"from": f"파일 {p.name}"})
        return info
    pid = str(bc["project_id"])
    kws, must = bc.get("keywords") or [], bc.get("name_must_contain") or []
    cands = baselines_from_api(ccb, pid, tried)
    if not cands:
        cands, html = baselines_from_html(cbs.fetch_text, cb_base, pid, tried, kws)
        debug.append((f"{cb_base}/project/{pid}/baselines", 200, html))
    if a.baseline_id:
        pool = [c for c in cands if c["id"] == str(a.baseline_id)] or [{"id": str(a.baseline_id), "name": f"(지정) {a.baseline_id}", "links": []}]
        tried.append(f"Baseline 직접 지정 --baseline-id {a.baseline_id}")
    else:
        pool = pick_latest(cands, kws, must)
    info["candidates"] = pool
    if not pool:
        tried.append(f"조건(이름에 {kws + must} 포함)에 맞는 Baseline 없음")
        return info
    b = pool[0]
    info["name"] = b["name"]
    info["url"] = next((h if h.startswith("http") else re.sub(r"(https?://[^/]+).*", r"\1", cb_base) + h
                        for h in b.get("links") or [] if h.startswith(("/", "http"))), "") or (f"{cb_base}/doc/{b['id']}" if b.get("id") else "")
    rows, src = baseline_desc(ccb, cbs.fetch_text, cb_base, b, header_kw, tried, debug)
    info["rows"], info["from"] = (rows or None), src
    return info


def main(argv=None):
    ap = argparse.ArgumentParser(description="CL1 — CI 저장소 관리 · Baseline 포함 점검")
    ap.add_argument("--doctor", action="store_true", help="연결 점검 (Baseline 조회 경로 확인, 결과 파일 없음)")
    ap.add_argument("--ci", action="append", help="이 CI ID만 검사 (여러 번 지정 가능)")
    ap.add_argument("--limit", type=int, help="앞에서 N개 CI만 (시험용)")
    ap.add_argument("--baseline-id", help="Baseline을 직접 지정 (번호, 예: 9705300)")
    ap.add_argument("--baseline-file", help="Baseline Description을 화면에서 복사해 저장한 파일(txt/html)로 판정")
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
    th = (float(cfg["cl1"].get("ok_ratio", 0.9)), float(cfg["cl1"].get("conditional_ratio", 0.8)))
    for d in (STATE, STATE / "ci_list", STATE / "debug"):
        d.mkdir(exist_ok=True)
    out_dir = HERE / cfg.get("output_dir", "output")
    out_dir.mkdir(exist_ok=True)
    t0 = time.time()
    tried, debug = [], []

    from playwright.sync_api import sync_playwright
    log(f"CL1 점검(저장소 관리 · Baseline 포함) v{VERSION} 시작{' (점검 모드)' if a.doctor else ''}")
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(STATE / "browser-profile"), channel=cfg["browser"].get("channel") or None,
            headless=a.headless, viewport={"width": 1280, "height": 860})
        try:
            # ① Confluence — 최신 CI list
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
            log(f"2. 시트 '{info['sheet']}' 전체 {info['total']}행 → PBL 없음 제외 {info['no_pbl']} → 검사 대상 {info['targets']}개 "
                f"(PBL 기준: {info['pbl_column']}, 저장소 종류 무관)")
            all_targets = list(cis)  # Baseline 항목 차지 판단은 일부 실행이어도 전체 대상 CI 기준
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

            # Codebeamer
            cb = cfg["codebeamer"]
            bpid = cfg["cl1"]["baseline"]["project_id"]
            cbs = Session(ctx, "Codebeamer", cb["base"], cb["base"] + cb.get("login_path", "/login.spr"),
                          not a.headless, get_cred("Codebeamer"))
            probe = f"/api/v3/projects/{bpid}"

            def cb_login():
                cbs.ensure_login(cb["base"], probe, lambda b: bool(b.get("id")))
                cbs.pin(cb["base"] + probe)
            cb_login()
            log("3. Codebeamer 로그인 확인")
            ccb = Client(cbs.fetch_json, cb["base"], batch=cfg.get("batch_size", 10), relogin=cb_login)

            # ② Baseline
            base = get_baseline(ccb, cbs, cfg, a, tried, debug)
            if base["rows"]:
                log(f"4. Baseline '{base['name']}' — 대상 산출물 {len(base['rows'])}개 ({base['from']})")
            else:
                for i, (u, st, html) in enumerate(debug):
                    (STATE / "debug" / f"baseline_{i + 1}.html").write_text(html or "", encoding="utf-8")
                log("4. ⚠ Baseline 내용을 읽지 못했습니다 — ② Baseline 포함은 전부 확인불가로 남깁니다")
                for t in tried:
                    log(f"     · {t}")
                log("     → state\\debug 폴더에 받은 화면을 저장했습니다 (Claude에게 전달). 급하면 --baseline-file 로 Description 직접 지정")

            if a.doctor:
                for t in tried:
                    log(f"   조회: {t}")
                for c in base["candidates"][:5]:
                    log(f"   후보: {c['name']} (id {c.get('id') or '-'}, {c.get('source')})")
                for n, v in (base["rows"] or [])[:40]:
                    log(f"   산출물: {n}  [{v}]")
                for i, (u, s, html) in enumerate(debug):
                    f = STATE / "debug" / f"baseline_{i + 1}.html"
                    f.write_text(html or "", encoding="utf-8")
                    log(f"   화면 저장: {f.name} ← {u} (HTTP {s})")
                for c in cis[:3]:
                    k = repo_kind(c, cfg)
                    rr = check_repo(c, k, ccb, ccf, cbs, cfg, th)
                    log(f"   ① {c['ciId']} [{k}] {rr['result']} — {rr['reason']}")
                log("✔ 점검 완료 — Baseline 후보·산출물 목록이 화면과 같으면 run_cl1.bat 으로 실행하세요.")
                log("   (다르면 위 '조회:' 줄과 state\\debug 폴더 파일을 Claude에게 전달)")
                return 0

            results = []
            taken = taken_rows(all_targets, base["rows"])
            for n, c in enumerate(cis, 1):
                k = repo_kind(c, cfg)
                try:
                    rr = check_repo(c, k, ccb, ccf, cbs, cfg, th)
                except NeedLogin:
                    raise
                except Exception as e:  # noqa
                    rr = {"result": "확인불가", "found": "", "reason": f"조회 중 오류: {e}"}
                br = check_baseline(c, base["rows"], th, taken)
                results.append(dict(c, repo=rr, base=br, kind=k))
                log(f"5. ({n}/{len(cis)}) {c['ciId']:<24} ① {rr['result']:<14} ② {br['result']:<14} {c['ciName'][:40]}")
        finally:
            ctx.close()

    meta = {
        "실행 시각": time.strftime("%Y-%m-%d %H:%M:%S"),
        "도구": f"CL1 cl1_check.py v{VERSION}",
        "CI list 파일": f"{latest['title']} (Confluence 업로드 {latest['when']} {latest['by']})",
        "CI 선별": f"전체 {info['total']} / PBL 없음 제외 {info['no_pbl']} / 검사 {len(results)} (저장소 종류 무관)"
                 + (" (일부 CI만 지정 실행)" if a.ci or a.limit else ""),
        "Baseline": f"{base['name'] or '(확인불가)'} — 대상 산출물 {len(base['rows'] or [])}개, 출처: {base['from'] or '-'}",
        "Baseline 선택 규칙": f"Codebeamer 프로젝트 {cfg['cl1']['baseline']['project_id']}의 Baseline 중 이름에 "
                         f"{cfg['cl1']['baseline'].get('keywords')} + {cfg['cl1']['baseline'].get('name_must_contain')} 포함, 가장 최신"
                         + (f" (직접 지정: {a.baseline_id or a.baseline_file})" if a.baseline_id or a.baseline_file else ""),
        "① 판정 규칙": "CI list 경로(Path in Repository)에서 CI name과 같은 산출물이 관리되는지. Codebeamer Tracker = Tracker 이름 비교, "
                    "Confluence = 페이지 제목·첨부 비교, 그 외 저장소 = 수동 확인. 경로 없음·Tracker/페이지 없음·이름 다름 = NOK",
        "② 판정 규칙": "CI name이 Baseline Description의 대상 산출물 목록에 있는지 (버전은 비교하지 않음). 없으면 NOK",
        "이름 비교": f"대소문자·공백·기호 차이는 같은 이름(100%) / 철자 유사도 {th[0]:.0%} 이상 OK · {th[1]:.0%}~{th[0]:.0%} 미만 {COND}(사람 확인) · "
                   f"{th[1]:.0%} 미만 NOK. 유사도는 Overview '① 유사도'·'② 유사도' 열",
        "원칙": "조회 실패 = 확인불가 (OK/NOK로 넘기지 않음) · 읽기 전용 · 결과는 새 파일",
        "소요 시간": f"{time.time() - t0:.0f}초",
        "주의": "자동 생성 초안입니다. 공식 산출물 반영·저장은 담당자가 검토 후 직접 합니다.",
    }
    wb = build_workbook(results, base, meta)
    out = out_dir / f"CL1_CI관리_Baseline_{cfg.get('project', '')}_{time.strftime('%Y-%m-%d_%H%M')}.xlsx"
    wb.save(out)
    nok = sum(1 for r in results if "NOK" in (r["repo"]["result"], r["base"]["result"]))
    log(f"6. 완료 — CI {len(results)}개 · NOK CI {nok}개 "
        f"(① {sum(r['repo']['result'] == 'NOK' for r in results)} / ② {sum(r['base']['result'] == 'NOK' for r in results)})")
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

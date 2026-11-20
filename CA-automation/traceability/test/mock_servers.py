"""가짜 Confluence(8101) / Codebeamer(8102) — 로그인 세션 흉내 포함"""
import io, json, re, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
from openpyxl import Workbook

STATE = {"conf": False, "cb": False, "round": 1, "cb_expire_after": None, "rel_calls": 0, "logins": []}
CRED = ("jae", "pw!23")

LOGIN_FORM = """<html><body><form method="post" action="{act}">
<input type="hidden" name="t" value="x"><label>ID <input name="{u}" type="text"></label>
<label>PW <input name="{p}" type="password"></label><button type="submit">Log in</button></form></body></html>"""


def make_ci_list():
    wb = Workbook(); ws0 = wb.active; ws0.title = "Cover"; ws0["A1"] = "SAMPLE CI List (FAKE)"
    ws = wb.create_sheet("CI List")
    hdr = {"B": "No", "C": "hidden", "D": "Category", "E": "CI ID", "F": "Tracker Key", "G": "CI name",
           "H": "Description", "I": "Author", "J": "Repository", "K": "Path in Repository", "O": "PBL"}
    for c, v in hdr.items(): ws[f"{c}3"] = v
    ws.column_dimensions["C"].hidden = True
    rows = [
        ("SYS.1 Requirements Elicitation", "CI-SYS1-01", "SYS1_01", "Stakeholder Req", "작성자A", "Codebeamer", "http://127.0.0.1:8102/cb/tracker/1001?view_id=-2", "PBL1"),
        ("HWE.3&4", "CI-SYS2-01", "SYS2_01", "System Req (big)", "작성자B", "Codebeamer", "LINK", "PBL1"),
        ("SWE.1", "CI-SWE1-01", "SWE1_01", "SW Req (fallback)", "작성자C", "Codebeamer", "FORMULA", "PBL1"),
        (None, "CI-SWE2-01", "SWE2_01", "Flaky relations", "작성자D", "Codebeamer", "http://127.0.0.1:8102/cb/tracker/1004?view_id=-2", "PBL2"),
        ("SWE.3", "CI-SWE3-01", "SWE3_01", "Missing tracker", "작성자E", "Codebeamer", "http://127.0.0.1:8102/cb/tracker/1999?view_id=-2", "PBL2"),
        ("SYS.1", "CI-SYS1-02", "SYS1_02", "No PBL", "작성자F", "Codebeamer", "http://127.0.0.1:8102/cb/tracker/1005?view_id=-2", None),
        ("HWE.1", "CI-HWE1-01", "", "SVN doc", "작성자G", "SVN", "svn://repo/hw", "PBL1"),
        ("SYS.4", "CI-SYS4-03", "SYS4_XX", "Integration Test (상위 등록)", "작성자H", "Codebeamer", "http://127.0.0.1:8102/cb/tracker/4000?view_id=-2", "PBL1"),
        ("SYS.5", "CI-SYS5-05", "SYS5_XX", "Qualification Test (하위 등록)", "작성자I", "Codebeamer", "http://127.0.0.1:8102/cb/tracker/3002?view_id=-2", "PBL1"),
    ]
    for i, r in enumerate(rows):
        n = 4 + i
        for c, v in zip("DEFGIJKO", r):
            if v is not None: ws[f"{c}{n}"] = v
        ws[f"B{n}"] = i + 1
    ws["K5"] = "바로가기"; ws["K5"].hyperlink = "http://127.0.0.1:8102/cb/tracker/1002?view_id=-2"
    ws["K6"] = '=HYPERLINK("http://127.0.0.1:8102/cb/tracker/1003?view_id=-2","열기")'
    ws.auto_filter.ref = "B3:O12"
    b = io.BytesIO(); wb.save(b); return b.getvalue()


CI_XLSX = make_ci_list()

# Tracker → items
ITEMS = {
    1001: [{"id": 11, "typeName": "Folder"}, {"id": 12, "typeName": "Requirement"}, {"id": 13, "typeName": "Information"},
           {"id": 14, "typeName": "Requirement"}, {"id": 15, "typeName": "Requirement"},
           {"id": 16, "categories": [{"id": 1, "name": "Folder"}]},  # 유형이 Category(Type) 필드에만 있는 경우 → 제외돼야 함
           {"id": 17, "categories": [{"id": 3, "name": "Requirement"}]},
           {"id": 18, "typeName": "Requirement", "categories": [{"id": 3, "name": "Infomation"}]},  # 실제 사례: 오타 'Infomation' → 제외돼야 함
           {"id": 19, "typeName": "Requirement", "categories": [{"id": 1, "name": "Function"}]}],  # Category 필드 id=1 (Type의 Folder id와 겹침) → 제외되면 안 됨
    1002: [{"id": 20000 + i, "typeName": "Requirement" if i % 50 else "Folder"} for i in range(1200)],  # paging
    1003: [{"id": 31, "typeName": "Requirement"}, {"id": 32, "typeName": "Requirement"}],
    1004: [{"id": 41, "typeName": "Requirement"}, {"id": 42, "typeName": "Requirement"}, {"id": 43, "typeName": "Requirement"}],
}
# 하위 Tracker 구조: 폴더 SYS.5 → 2999(Test Plan, 형제) / 3000(Spec, Item 없음) → 3001, 3002 → 3003(손자)
#                   폴더 SYS.4 → 4000(Item 없음) → 4001, 4002
ITEMS.update({
    2999: [{"id": 29990, "typeName": "Requirement"}],
    3000: [],
    3001: [{"id": 31000 + i, "typeName": "Test Case"} for i in range(30)],
    3002: [{"id": 32000 + i, "typeName": "Test Case"} for i in range(20)] + [{"id": 32099, "categories": [{"id": 1, "name": "Folder"}]}],
    3003: [{"id": 33000 + i, "typeName": "Test Case"} for i in range(5)],
    4000: [],
    4001: [{"id": 40010 + i, "typeName": "Test Case"} for i in range(8)],
    4002: [{"id": 40020 + i, "typeName": "Test Case"} for i in range(4)],
})
KEYS = {1001: "SYS1_01", 1002: "SYS2_01", 1003: "SWE1_01", 1004: "SWE2_01", 2999: "SYS5_PLAN", 3000: "SYS5_SPEC",
        3001: "TCA", 3002: "TCB", 3003: "TC-GROUP-B-1", 4000: "SYS4_XX", 4001: "SIT-A", 4002: "SIT-B"}
TREE = [
    {"isFolder": True, "text": "SYS.1", "children": [{"trackerId": 1001, "text": "Stakeholder Req", "children": []}]},
    {"isFolder": True, "text": "SYS.2", "children": [{"trackerId": 1002, "text": "System Req", "children": []}]},
    {"isFolder": True, "text": "SWE", "children": [{"trackerId": 1003, "text": "SW Req"}, {"trackerId": 1004, "text": "Flaky"}]},
    {"isFolder": True, "text": "SYS.4", "children": [{"trackerId": 4000, "text": "Integration Test Spec", "children": [
        {"trackerId": 4001, "text": "SIT-A"}, {"trackerId": 4002, "text": "SIT-B"}]}]},
    {"isFolder": True, "text": "SYS.5", "children": [
        {"trackerId": 2999, "text": "System Test Plan", "children": []},
        {"trackerId": 3000, "text": "System Test Spec", "children": [
            {"trackerId": 3001, "text": "TC-GROUP-A"},
            {"trackerId": 3002, "text": "TC-GROUP-B", "children": [{"trackerId": 3003, "text": "TC-GROUP-B-1"}]}]}]},
]
for _t, _its in ITEMS.items():
    for _it in _its:
        _it["tracker"] = {"id": _t, "type": "TrackerReference"}


def relations(iid):
    if STATE["round"] == 2 and iid == 15:  # 2회차: 15번 연결됨 (해소)
        return {"downstreamReferences": [{"id": 1}]}
    if STATE["round"] == 2 and iid == 14:  # 2회차: 14번 연결 끊김 (신규 미추적)
        return {"downstreamReferences": []}
    unl = {12, 15, 16, 18, 32, 41, 31002, 32005, 33001, 32099, 29990, 40021} | {20000 + i for i in range(0, 1200, 97)}
    if iid in unl:
        return {"downstreamReferences": [], "upstreamReferences": [], "incomingAssociations": [], "outgoingAssociations": []}
    return {"downstreamReferences": [], "upstreamReferences": [{"id": 9}], "incomingAssociations": [], "outgoingAssociations": []}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def send(self, code, body, ct="application/json"):
        b = body if isinstance(body, bytes) else (json.dumps(body) if ct == "application/json" else body).encode()
        self.send_response(code); self.send_header("Content-Type", ct); self.send_header("Content-Length", str(len(b)))
        self.end_headers(); self.wfile.write(b)

    def login_redirect(self):
        self.send_response(302); self.send_header("Location", "/login"); self.end_headers()


def _form(h):
    n = int(h.headers.get("Content-Length", 0))
    return {k: v[0] for k, v in parse_qs(h.rfile.read(n).decode()).items()}


class Conf(H):
    def do_POST(self):
        f = _form(self)
        if (f.get("os_username"), f.get("os_password")) == CRED:
            STATE["conf"] = True; STATE["logins"].append("conf")
        self.send_response(302); self.send_header("Location", "/pages/viewpage.action?pageId=000000001"); self.end_headers()

    def do_GET(self):
        u = urlparse(self.path); p = u.path
        if p == "/login.action":
            return self.send(200, LOGIN_FORM.format(act="/dologin.action", u="os_username", p="os_password"), "text/html")
        if p in ("/login", "/pages/viewpage.action"):
            return self.send(200, "<html>page</html>", "text/html")
        if p == "/rest/api/user/current":
            return self.send(200, {"type": "known", "username": "jae"} if STATE["conf"] else {"type": "anonymous"})
        if not STATE["conf"]:
            return self.send(404, {"statusCode": 404, "message": "No content found"})  # 실제 Confluence: 미로그인 → 404
        if re.fullmatch(r"/rest/api/content/\d+", p):
            return self.send(200, {"id": "000000001", "title": "SAMPLE CI List"})
        if p.endswith("/child/attachment"):
            return self.send(200, {"_links": {"base": "http://127.0.0.1:8101"}, "results": [
                {"title": "SAMPLE_CI_List_v1.2.xlsx", "version": {"when": "2026-11-10T09:00:00.000+09:00", "by": {"displayName": "A"}}, "_links": {"download": "/download/attachments/1/old.xlsx"}},
                {"title": "회의록.pdf", "version": {"when": "2026-11-18T09:00:00.000+09:00"}, "_links": {"download": "/x.pdf"}},
                {"title": "SAMPLE_CI_List_v1.3.xlsx", "version": {"when": "2026-11-17T01:30:00.000Z", "by": {"displayName": "B"}}, "_links": {"download": "/download/attachments/1/new.xlsx"}},
            ]})
        if p == "/download/attachments/1/new.xlsx":
            return self.send(200, CI_XLSX, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        if p == "/download/attachments/1/old.xlsx":
            return self.send(200, b"WRONG FILE", "application/octet-stream")
        self.send(404, {"error": "nf"})


class Cb(H):
    def do_POST(self):
        f = _form(self)
        if (f.get("user"), f.get("password")) == CRED:
            STATE["cb"] = True; STATE["logins"].append("cb")
        self.send_response(302); self.send_header("Location", "/cb/"); self.end_headers()

    def do_GET(self):
        u = urlparse(self.path); p = u.path; q = parse_qs(u.query)
        if p == "/cb/login.spr":
            return self.send(200, LOGIN_FORM.format(act="/cb/login.spr", u="user", p="password"), "text/html")
        if p in ("/login", "/cb", "/cb/"):
            if STATE["cb"] and p != "/login":  # 로그인 후 홈 → 대시보드로 연쇄 이동
                return self.send(200, "<html><script>setTimeout(()=>location.href='/cb/dash?step=1',50)</script>cb</html>", "text/html")
            return self.send(200, "<html>cb</html>", "text/html")
        if p == "/cb/dash":
            n = int(q.get("step", ["1"])[0])
            nxt = f"<script>setTimeout(()=>location.href='/cb/dash?step={n+1}',50)</script>" if n < 4 else ""
            return self.send(200, f"<html>{nxt}dash {n}</html>", "text/html")
        if not STATE["cb"]:
            self.send_response(302); self.send_header("Location", "/cb/login.spr"); self.end_headers(); return
        m = re.fullmatch(r"/cb/api/v3/trackers/(\d+)", p)
        if m:
            t = int(m.group(1))
            return self.send(200, {"id": t, "keyName": KEYS[t], "name": f"T{t}", "projectId": 1}) if t in KEYS else self.send(404, {"m": "no tracker"})
        if p == "/cb/api/v3/trackers/tree":
            return self.send(200, TREE) if q.get("projectId", [""])[0] == "1" else self.send(400, {"m": "projectId"})
        if p == "/cb/api/v3/items/query":
            ts = [int(x) for x in re.search(r"\(([\d,\s]+)\)", q["queryString"][0]).group(1).split(",")]
            if 1003 in ts:
                return self.send(404, {"m": "query disabled"})  # fallback 경로 시험
            if not any(t in ITEMS for t in ts):
                return self.send(404, {"m": "no tracker"})
            pg, sz = int(q["page"][0]), int(q["pageSize"][0])
            all_ = [it for t in ts for it in ITEMS.get(t, [])]
            return self.send(200, {"page": pg, "pageSize": sz, "total": len(all_), "items": all_[(pg - 1) * sz: pg * sz]})
        m = re.fullmatch(r"/cb/api/v3/trackers/(\d+)/fields", p)
        if m:
            return self.send(200, [{"id": 7, "name": "Type", "type": "ChoiceFieldReference"}, {"id": 3, "name": "Name"}])
        m = re.fullmatch(r"/cb/api/v3/trackers/(\d+)/fields/7", p)
        if m:
            return self.send(200, {"id": 7, "name": "Type", "options": [
                {"id": 0, "name": "Unset"}, {"id": 1, "name": "Folder"}, {"id": 3, "name": "Infomation"}]})
        m = re.fullmatch(r"/cb/api/v3/trackers/(\d+)/items", p)
        if m:
            t = int(m.group(1)); all_ = ITEMS.get(t, []); pg, sz = int(q["page"][0]), int(q["pageSize"][0])
            return self.send(200, {"total": len(all_), "itemRefs": [{"id": x["id"]} for x in all_[(pg - 1) * sz: pg * sz]]})
        m = re.fullmatch(r"/cb/api/v3/items/(\d+)/relations", p)
        if m:
            STATE["rel_calls"] += 1
            if STATE["cb_expire_after"] and STATE["rel_calls"] == STATE["cb_expire_after"]:
                STATE["cb"] = False  # 실행 중 세션 만료
                self.send_response(302); self.send_header("Location", "/cb/login.spr"); self.end_headers(); return
            iid = int(m.group(1))
            if iid == 42:
                return self.send(500, {"m": "boom"})  # 항상 실패 → 확인불가
            return self.send(200, {"itemId": iid, **relations(iid)})
        m = re.fullmatch(r"/cb/api/v3/items/(\d+)", p)
        if m:
            iid = int(m.group(1))
            for its in ITEMS.values():
                for it in its:
                    if it["id"] == iid: return self.send(200, it)
        self.send(404, {"m": "nf"})


def start():
    for port, cls in ((8101, Conf), (8102, Cb)):
        s = ThreadingHTTPServer(("127.0.0.1", port), cls)
        threading.Thread(target=s.serve_forever, daemon=True).start()

"""CL2 시험용 가짜 Confluence(8211) / Codebeamer(8212). 값은 모두 가짜."""
import io, json, re, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
from openpyxl import Workbook

STATE = {"conf": False, "cb": False}
CRED = ("jae", "pw!23")
CB = "http://127.0.0.1:8212/cb"
CF = "http://127.0.0.1:8211"
LOGIN_FORM = """<html><body><form method="post" action="{act}">
<label>ID <input name="{u}" type="text"></label><label>PW <input name="{p}" type="password"></label>
<button type="submit">Log in</button></form></body></html>"""
HDR = "||Version||Date||Description||Author||Approver\n"


def wiki(rows):
    return "!!Revision history\n" + HDR + "".join(f"|{'|'.join(r)}|\n" for r in rows) + "\n!!1 Overview\nbody"


CIS = [  # (Category, CI ID, CI name, Repository, Path, PBL)
    ("SYS.1", "CI-A", "Screenshot style (no v)", "Codebeamer", f"{CB}/tracker/2001?view_id=-2", "PBL"),
    ("SYS.2", "CI-B", "Proper versions", "Codebeamer", f"{CB}/tracker/2002", "PBL"),
    (None, "CI-C", "No revision history", "Codebeamer", f"{CB}/tracker/2003", "PBL"),
    ("SYS.3", "CI-D", "Blank approver", "Codebeamer", f"{CB}/tracker/2004", "PBL"),
    ("SYS.4", "CI-E", "HTML minor skip", "Codebeamer", f"{CB}/tracker/2005", "PBL"),
    ("SYS.5", "CI-F", "Table only on page, newest first", "Codebeamer", f"{CB}/tracker/2006", "PBL"),
    ("SYS.5", "CI-G", "Sub tracker", "Codebeamer", f"{CB}/tracker/2102", "PBL"),
    ("SWE.1", "CI-H", "Server error", "Codebeamer", f"{CB}/tracker/2007", "PBL"),
    ("SWE.2", "CI-I", "Confluence doc", "Confluence", f"{CF}/pages/viewpage.action?pageId=555", "PBL"),
    ("SWE.3", "CI-J", "Source code", "Git", "ssh://git.example/x.git", "PBL"),
    ("SWE.4", "CI-K", "Empty path", "Codebeamer", "", "PBL"),
    ("SWE.5", "CI-L", "Header only", "Codebeamer", f"{CB}/tracker/2008", "PBL"),
    ("SWE.6", "CI-M", "Big tracker", "Codebeamer", f"{CB}/tracker/2009", "PBL"),
    ("MAN.3", "CI-N", "No PBL", "Codebeamer", f"{CB}/tracker/2002", None),
    ("SUP.8", "CI-O", "Draft after official", "Codebeamer", f"{CB}/tracker/2010", "PBL"),
    ("SWE.6", "CI-P", "Category(CMDB) path, [{Table}] plugin", "Codebeamer", f"{CB}/category/3001?view_id=-2", "PBL"),
    ("HWE.4", "CI-Q", "Author (Approver) one column", "Codebeamer", f"{CB}/tracker/2011", "PBL"),
    ("SYS.4", "CI-R", "Template history only", "Codebeamer", f"{CB}/tracker/2012", "PBL"),
    ("SYS.4", "CI-S", "Doc history preferred over template", "Codebeamer", f"{CB}/tracker/2013", "PBL"),
    ("HWE.1", "CI-T", "HTML rowspan approver", "Codebeamer", f"{CB}/tracker/2014", "PBL"),
]


def make_ci_list():
    wb = Workbook(); ws = wb.active; ws.title = "CI List"
    hdr = {"B": "No", "D": "Category", "E": "CI ID", "F": "Tracker Key", "G": "CI name", "I": "Author",
           "J": "Repository", "K": "Path in Repository", "O": "PBL"}
    for c, v in hdr.items(): ws[f"{c}3"] = v
    for i, row in enumerate(CIS):
        n = 4 + i
        for c, v in zip("DEGJKO", row):
            if v is not None: ws[f"{c}{n}"] = v
        ws[f"I{n}"] = "작성자"; ws[f"B{n}"] = i + 1
    b = io.BytesIO(); wb.save(b); return b.getvalue()


CI_XLSX = make_ci_list()
TRACKERS = {2001: "A", 2002: "B", 2003: "C", 2004: "D", 2005: "E", 2006: "F", 2101: "G top", 2102: "G sub",
            2008: "L", 2009: "M", 2010: "O", 3001: "P category", 2011: "Q", 2012: "R", 2013: "S", 2014: "T"}
TREE = [{"isFolder": True, "text": "SYS", "children": [{"trackerId": t} for t in TRACKERS if t < 2100]},
        {"isFolder": True, "text": "SYS.5", "children": [{"trackerId": 2101, "children": [{"trackerId": 2102}]}]}]
# Tracker → [(item id, 이름)]
ITEMS = {2001: [(1, "Folder A"), (11, "Revision history"), (12, "Req 1")],
         2002: [(21, "Revision History"), (22, "Req")],
         2003: [(31, "Req 1"), (32, "Req 2")],
         2004: [(41, "Revision history")],
         2005: [(51, "1. Revision history")],
         2006: [(61, "Revision history")],
         2101: [(71, "Revision history")], 2102: [(72, "Sub req")],
         2008: [(81, "Revision history")],
         2009: [(90000 + i, f"Req {i}") for i in range(1100)] + [(99999, "Revision History")] + [(80000 + i, f"Req b{i}") for i in range(100)],
         2010: [(101, "Revision history")],
         3001: [(111, "Revision history")], 2011: [(121, "Revision history")],
         2012: [(131, "Revision history of the template"), (132, "Req")],
         2013: [(141, "Revision history of the template"), (142, "Revision history")],
         2014: [(151, "Revision history")]}
DESC = {
    11: ("Wiki", wiki([("1.0", "2025-08-11", "Initial release", "Author One", "Approver One"),
                       ("2.0", "2026-10-14", "2nd release\\\\고객 요구사양서 버전 업데이트 rev 1 -> rev\\\\- [REQ.SOM010|https://x/1] 추가",
                        "Author One", "Approver One")])),
    21: ("Wiki", wiki([("v1.0a", "2025-01-01", "draft", "kim", "lee"), ("v1.0", "2025-02-01", "release", "kim", "lee"),
                       ("v1.1a", "2025-03-01", "typo", "kim", "lee"), ("v1.1", "2025-03-05", "typo fix", "kim", "lee"),
                       ("v2.0", "2025-06-01", "req change", "kim", "lee")])),
    41: ("Wiki", wiki([("v1.0", "2025-01-01", "init", "kim", "lee"), ("v1.1", "2025-02-01", "fix", "kim", " ")])),
    51: ("Html", "<h2>Revision history</h2><table><tr><th>Version</th><th>Date</th><th>Description</th><th>Author</th><th>Approver</th></tr>"
                 "<tr><td>v1.0</td><td>2025-01-01</td><td>init</td><td>kim</td><td>lee</td></tr>"
                 "<tr><td>v1.2</td><td>2025-03-01</td><td>jump</td><td>kim</td><td>lee</td></tr></table>"),
    61: ("Wiki", "See below (table is rendered by plugin)"),
    71: ("Wiki", wiki([("v1.0", "2025-01-01", "init", "kim", "lee")])),
    81: ("Wiki", "!!Revision history\n" + HDR),
    99999: ("Wiki", wiki([("v1.0", "2025.01.01", "init", "kim", "lee"), ("v1.1", "2025.02.01", "fix", "kim", "lee")])),
    111: ("Wiki", "[{Table style='width:82%;' dataStyle='text-align:left;'\r\n\r\n|(width:7%;background-color:rgb(239, 239, 239))Version\r\n|(width:10%)Date\r\n|(width:47%)Description\r\n|(width:17%)Author\r\n|(width:16%)Approver\r\n\r\n|(width:7%)v1.0\r\n|(width:10%)2026~-01~-16\r\n|(width:47%)%%(color:rgb(0, 0, 0);display:inline !important;)Initial release%!\\\\\r\n|(width:17%)Author One\r\n|(width:16%)Approver One\r\n\r\n|(width:7%)v1.1\r\n|(width:10%)2026~-11~-04\r\n|(width:47%)~- FSR 삭제\\\\\r\n[~[PROJ-1234~] FSR 항목 삭제 - Jira|https://jira.example/x]\\\\\r\n|(width:17%)Author One\r\n|(width:16%)Approver One\r\n\r\n|(width:7%)\\\\\r\n|(width:10%)\\\\\r\n|(width:47%)\\\\\r\n|(width:17%)\\\\\r\n|(width:16%)\\\\}]"),
    121: ("Wiki", "||Version||Date||Description||Author (Approver)\n|v1.0|2026-01-01|init|Author Two (Approver Two)|\n|v1.1|2026-02-01|fix|Author Three (Approver Two)|\n"),
    131: ("Wiki", "||Version||Date||Description||Author||Approver\n|v1.0|2026-01-01|template init|kim|lee|\n"),
    141: ("Wiki", "||Version||Date||Description||Author||Approver\n|v9.0|2026-01-01|template|kim|lee|\n"),
    142: ("Wiki", "||Version||Date||Description||Author||Approver\n|v1.0|2026-01-01|doc init|kim|lee|\n"),
    151: ("Html", "<table><tr><th>Version</th><th>Date</th><th>Description</th><th>Author</th><th>Approver</th></tr>"
                 "<tr><td>v1.0</td><td>2025-01-01</td><td>init</td><td>kim</td><td rowspan='2'>lee</td></tr>"
                 "<tr><td>v1.1</td><td>2025-02-01</td><td>fix</td><td>kim</td></tr></table>"),
    101: ("Wiki", wiki([("v1.0", "2025-01-01", "init", "kim", "lee"), ("v1.0a", "2025-02-01", "oops", "kim", "lee")])),
}
PAGE_61 = ("<html><body><div class='wiki'><table class='wikiTable'><tr><th>Version</th><th>Date</th><th>Description</th>"
           "<th>Author</th><th>Approver</th></tr><tr><td>v1.1</td><td>2025-02-01</td><td>fix</td><td>kim</td><td>lee</td></tr>"
           "<tr><td>v1.0</td><td>2025-01-01</td><td>init</td><td>kim</td><td>lee</td></tr></table></div></body></html>")
CONF_555 = ("<p>doc</p><table><tbody><tr><th>Version</th><th>Date</th><th>Description</th><th>Author</th><th>Approver</th></tr>"
            "<tr><td>v1.0</td><td>2025-01-01</td><td>init</td><td>kim</td><td>lee</td></tr></tbody></table>")


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def send(self, code, body, ct="application/json"):
        b = body if isinstance(body, bytes) else (json.dumps(body) if ct == "application/json" else body).encode()
        self.send_response(code); self.send_header("Content-Type", ct + ("; charset=utf-8" if "text" in ct else ""))
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)


def _form(h):
    n = int(h.headers.get("Content-Length", 0))
    return {k: v[0] for k, v in parse_qs(h.rfile.read(n).decode()).items()}


class Conf(H):
    def do_POST(self):
        if (lambda f: (f.get("os_username"), f.get("os_password")))(_form(self)) == CRED:
            STATE["conf"] = True
        self.send_response(302); self.send_header("Location", "/pages/viewpage.action?pageId=1"); self.end_headers()

    def do_GET(self):
        p = urlparse(self.path).path
        if p == "/login.action":
            return self.send(200, LOGIN_FORM.format(act="/dologin.action", u="os_username", p="os_password"), "text/html")
        if p == "/pages/viewpage.action":
            return self.send(200, "<html>page</html>", "text/html")
        if p == "/rest/api/user/current":
            return self.send(200, {"type": "known", "username": "jae"} if STATE["conf"] else {"type": "anonymous"})
        if not STATE["conf"]:
            return self.send(404, {"message": "No content found"})
        if p == "/rest/api/content/1":
            return self.send(200, {"id": "1", "title": "SAMPLE CI List"})
        if p == "/rest/api/content/555":
            return self.send(200, {"id": "555", "title": "Confluence doc", "body": {"storage": {"value": CONF_555}}})
        if p == "/rest/api/content/1/child/attachment":
            return self.send(200, {"_links": {"base": CF}, "results": [
                {"title": "CI_List_v1.3.xlsx", "version": {"when": "2026-11-17T01:30:00.000Z", "by": {"displayName": "B"}},
                 "_links": {"download": "/download/attachments/1/new.xlsx"}}]})
        if p == "/download/attachments/1/new.xlsx":
            return self.send(200, CI_XLSX, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        self.send(404, {"m": "nf"})


class Cb(H):
    def do_POST(self):
        if (lambda f: (f.get("user"), f.get("password")))(_form(self)) == CRED:
            STATE["cb"] = True
        self.send_response(302); self.send_header("Location", "/cb/"); self.end_headers()

    def do_GET(self):
        u = urlparse(self.path); p = u.path; q = parse_qs(u.query)
        if p == "/cb/login.spr":
            return self.send(200, LOGIN_FORM.format(act="/cb/login.spr", u="user", p="password"), "text/html")
        if p in ("/cb", "/cb/"):
            return self.send(200, "<html>cb home</html>", "text/html")
        if not STATE["cb"]:
            self.send_response(302); self.send_header("Location", "/cb/login.spr"); self.end_headers(); return
        if p == "/cb/api/v3/projects":
            return self.send(200, [{"id": 171, "name": "P"}])
        if p == "/cb/api/v3/trackers/tree":
            return self.send(200, TREE)
        m = re.fullmatch(r"/cb/api/v3/trackers/(\d+)", p)
        if m:
            t = int(m.group(1))
            if t == 2007:
                return self.send(500, {"m": "boom"})
            return self.send(200, {"id": t, "name": TRACKERS[t], "projectId": 171}) if t in TRACKERS else self.send(404, {"m": "nf"})
        m = re.fullmatch(r"/cb/api/v3/trackers/(\d+)/items", p)
        if m:
            t = int(m.group(1)); page = int(q.get("page", ["1"])[0]); size = int(q.get("pageSize", ["25"])[0])
            allv = ITEMS.get(t, [])
            chunk = allv[(page - 1) * size: page * size]
            return self.send(200, {"page": page, "pageSize": size, "total": len(allv),
                                   "itemRefs": [{"id": i, "name": n, "type": "TrackerItemReference"} for i, n in chunk]})
        m = re.fullmatch(r"/cb/api/v3/items/(\d+)", p)
        if m:
            i = int(m.group(1))
            fmt, d = DESC.get(i, ("Wiki", ""))
            return self.send(200, {"id": i, "name": "x", "description": d, "descriptionFormat": fmt})
        if p == "/cb/issue/61":
            return self.send(200, PAGE_61, "text/html")
        m = re.fullmatch(r"/cb/issue/(\d+)", p)
        if m:
            return self.send(200, "<html><body>item page, no table</body></html>", "text/html")
        self.send(404, {"m": "nf"})


def start():
    for port, cls in ((8211, Conf), (8212, Cb)):
        s = ThreadingHTTPServer(("127.0.0.1", port), cls)
        threading.Thread(target=s.serve_forever, daemon=True).start()

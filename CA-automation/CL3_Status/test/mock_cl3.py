"""CL3 시험용 가짜 Confluence(8221) / Codebeamer(8222) / Jira(8223). 값은 모두 가짜."""
import io, json, re, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote
from openpyxl import Workbook

STATE = {"conf": False, "cb": False, "jira": False}
CRED = ("jae", "pw!23")
CF, CB, JR = "http://127.0.0.1:8221", "http://127.0.0.1:8222/cb", "http://127.0.0.1:8223"
LOGIN_FORM = """<html><body><form method="post" action="{act}">
<label>ID <input name="{u}" type="text"></label><label>PW <input name="{p}" type="password"></label>
<button type="submit">Log in</button></form></body></html>"""

CIS = [  # (Category, CI ID, CI name, Repository, Path, PBL)
    ("SYS.1", "CI-A", "A spec", "Codebeamer", f"{CB}/tracker/100?view_id=-2", "PBL"),
    ("SYS.2", "CI-B", "B spec", "Codebeamer", f"{CB}/tracker/110", "PBL"),
    ("SYS.5", "CI-C", "C spec", "Codebeamer", f"{CB}/tracker/121", "PBL"),       # 하위 Tracker
    ("SYS.3", "CI-D", "D spec", "Codebeamer", f"{CB}/tracker/130", "PBL"),       # Review Tracker 없음
    ("HWE.1", "CI-E", "E spec", "Codebeamer", f"{CB}/category/140", "PBL"),      # Category 경로, Review 이름 유사, 첨부 Defect List
    ("HWE.2", "CI-F", "F spec", "Codebeamer", f"{CB}/tracker/150", "PBL"),       # Defect 근거 없음
    ("SWE.3", "CI-G", "Source code", "Git", "ssh://git.example/x.git", "PBL"),
    ("SWE.4", "CI-H", "H spec", "Codebeamer", f"{CB}/tracker/160", "PBL"),       # Jira 미해결
    ("MAN.3", "CI-N", "No PBL", "Codebeamer", f"{CB}/tracker/100", None),
]

TRACKERS = {100: ("A spec", "SYS1_A"), 101: ("A sub", "SYS1_AS"), 110: ("B spec", "SYS2_B"), 120: ("C top", "SYS5_C"),
            121: ("C sub", "SYS5_CS"), 130: ("D spec", "SYS3_D"), 140: ("Hardware Thing Spec_ADCU-50S", "HWE1_E"), 150: ("F spec", "HWE2_F"),
            160: ("H spec", "SWE4_H"), 700: ("Defect List", "DEF"),
            900: ("Review_A spec", "R_A"), 910: ("Review_B spec", "R_B"), 920: ("Review_C top", "R_C"),
            940: ("Review_HW Thing Spec_ADCU-50S", "R_E"), 950: ("Review_F spec", "R_F"), 960: ("Review_H spec", "R_H"),
            930: ("Review_Z other", "R_Z")}
TYPED = {100, 101, 110, 120, 121, 130, 140, 150, 160}
TREE = [{"isFolder": True, "text": "SYS", "children": [
            {"trackerId": 100, "children": [{"trackerId": 101}]}, {"trackerId": 900}, {"trackerId": 110}, {"trackerId": 910},
            {"trackerId": 120, "children": [{"trackerId": 121}]}, {"trackerId": 920}, {"trackerId": 130}, {"trackerId": 930}]},
        {"isFolder": True, "text": "HWE", "children": [{"trackerId": 140}, {"trackerId": 940}, {"trackerId": 150}, {"trackerId": 950}]},
        {"isFolder": True, "text": "SWE", "children": [{"trackerId": 160}, {"trackerId": 960}, {"trackerId": 700}]}]


def it(i, t, name, status, typ="Requirement"):
    return {"id": i, "name": name, "tracker": {"id": t}, "status": {"name": status} if status else None,
            "categories": [{"id": 1, "name": typ}] if typ else [{"id": 0, "name": "Unset"}]}


ITEMS = [
    it(1001, 100, "Folder 1", "Draft", "Folder"), it(1002, 100, "Info", "New", "Information"),
    it(1003, 100, "Req 1", "Accepted"), it(1004, 100, "Req 2", "Accepted"), it(1005, 101, "Sub req", "Accepted"),
    it(1006, 101, "No type", "Accepted", None),
    it(1101, 110, "B1", "Accepted"), it(1102, 110, "B2", "Draft"), it(1103, 110, "B3", "Obsolete"), it(1104, 110, "B4", "Rejected"),
    it(1105, 110, "B5 untyped", "In Review", None),
    it(1201, 120, "C top req", "Draft"), it(1211, 121, "C sub req", "Accepted"),
    it(1301, 130, "D1", "Accepted"), it(1401, 140, "E1", "Accepted"), it(1501, 150, "F1", "Accepted"), it(1601, 160, "H1", "Accepted"),
    it(7001, 700, "Defect closed", "Closed", None), it(7002, 700, "Defect open", "Open", None),
    it(9001, 900, "Review A v1.0", "Completed", None), it(9101, 910, "Review B v1.0", "Completed", None),
    it(9401, 940, "Review E v1.0", "Completed", None), it(9501, 950, "Review F v1.0", "In progress", None),
    it(9601, 960, "Review H v1.0", "Completed", None),
]
for x in ITEMS:
    if x["id"] == 9001:
        x["description"] = f"Defects: [KEY-1|{JR}/browse/KEY-1]"
    if x["id"] == 9601:
        x["customFields"] = [{"name": "Jira", "value": f"{JR}/browse/KEY-2"}]
BYID = {x["id"]: x for x in ITEMS}
RELS = {9001: [7001, 1003], 9101: [7002], 9401: [1401], 9501: [1501], 9601: []}
ATTS = {9401: [{"id": 55, "name": "Defect_List.xlsx"}, {"id": 56, "name": "minutes.pdf"}]}
JIRA = {"KEY-1": ("Done", "done", "Fixed"), "KEY-2": ("In Progress", "indeterminate", None)}


def make_defect_list():
    wb = Workbook(); ws = wb.active; ws.title = "Defects"
    ws.append(["VR result"]); ws.append([])
    ws.append(["No", "Defect Description", "Owner", "Status"])
    ws.append([1, "Typo in 3.2", "kim", "Closed"]); ws.append([2, "Missing table", "lee", "Deferred"])
    b = io.BytesIO(); wb.save(b); return b.getvalue()


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


CI_XLSX, DL_XLSX = make_ci_list(), make_defect_list()


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def send(self, code, body, ct="application/json"):
        b = body if isinstance(body, bytes) else (json.dumps(body) if ct == "application/json" else body).encode()
        self.send_response(code); self.send_header("Content-Type", ct + ("; charset=utf-8" if "text" in ct else ""))
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def form(self):
        n = int(self.headers.get("Content-Length", 0))
        return {k: v[0] for k, v in parse_qs(self.rfile.read(n).decode()).items()}


class Conf(H):
    def do_POST(self):
        f = self.form()
        if (f.get("os_username"), f.get("os_password")) == CRED:
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
        if p == "/rest/api/content/1/child/attachment":
            return self.send(200, {"_links": {"base": CF}, "results": [
                {"title": "CI_List_v1.3.xlsx", "version": {"when": "2026-11-17T01:30:00.000Z", "by": {"displayName": "B"}},
                 "_links": {"download": "/download/attachments/1/new.xlsx"}}]})
        if p == "/download/attachments/1/new.xlsx":
            return self.send(200, CI_XLSX, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        self.send(404, {"m": "nf"})


class Cb(H):
    def do_POST(self):
        f = self.form()
        if (f.get("user"), f.get("password")) == CRED:
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
            return self.send(200, {"id": t, "name": TRACKERS[t][0], "keyName": TRACKERS[t][1], "projectId": 171}) if t in TRACKERS else self.send(404, {})
        m = re.fullmatch(r"/cb/api/v3/trackers/(\d+)/fields", p)
        if m:
            return self.send(200, [{"id": 1, "name": "Type"}, {"id": 2, "name": "Status"}] if int(m.group(1)) in TYPED else [{"id": 2, "name": "Status"}])
        if p == "/cb/api/v3/items/query":
            ids = {int(x) for x in re.findall(r"\d+", unquote(q["queryString"][0]))}
            page, size = int(q.get("page", ["1"])[0]), int(q.get("pageSize", ["25"])[0])
            allv = [x for x in ITEMS if x["tracker"]["id"] in ids]
            return self.send(200, {"page": page, "total": len(allv), "items": allv[(page - 1) * size: page * size]})
        m = re.fullmatch(r"/cb/api/v3/items/(\d+)", p)
        if m:
            i = int(m.group(1))
            return self.send(200, BYID[i]) if i in BYID else self.send(404, {})
        m = re.fullmatch(r"/cb/api/v3/items/(\d+)/relations", p)
        if m:
            ids = RELS.get(int(m.group(1)), [])
            return self.send(200, {"downstreamReferences": [], "upstreamReferences": [],
                                   "outgoingAssociations": [{"id": 5000 + k, "itemRevision": {"id": k}, "type": "AssociationReference"} for k in ids],
                                   "incomingAssociations": [], "isLastPage": True})
        m = re.fullmatch(r"/cb/api/v3/items/(\d+)/attachments", p)
        if m:
            return self.send(200, ATTS.get(int(m.group(1)), []))
        if re.fullmatch(r"/cb/api/v3/items/9401/attachments/55/content", p):
            return self.send(200, DL_XLSX, "application/octet-stream")
        self.send(404, {"m": "nf"})


class Jr(H):
    def do_POST(self):
        f = self.form()
        if (f.get("os_username"), f.get("os_password")) == CRED:
            STATE["jira"] = True
        self.send_response(302); self.send_header("Location", "/secure/Dashboard.jspa"); self.end_headers()

    def do_GET(self):
        p = urlparse(self.path).path
        if p == "/login.jsp":
            return self.send(200, LOGIN_FORM.format(act="/login.jsp", u="os_username", p="os_password"), "text/html")
        if p == "/secure/Dashboard.jspa":
            return self.send(200, "<html>jira</html>", "text/html")
        if not STATE["jira"]:
            return self.send(401, {"errorMessages": ["login"]})
        if p == "/rest/api/2/myself":
            return self.send(200, {"name": "jae"})
        m = re.fullmatch(r"/rest/api/2/issue/([A-Z]+-\d+)", p)
        if m and m.group(1) in JIRA:
            st, cat, res = JIRA[m.group(1)]
            return self.send(200, {"key": m.group(1), "fields": {"summary": f"{m.group(1)} summary", "status": {"name": st, "statusCategory": {"key": cat}},
                                                                 "resolution": {"name": res} if res else None}})
        self.send(404, {})


def start():
    for port, cls in ((8221, Conf), (8222, Cb), (8223, Jr)):
        s = ThreadingHTTPServer(("127.0.0.1", port), cls)
        threading.Thread(target=s.serve_forever, daemon=True).start()

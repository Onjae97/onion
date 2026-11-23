"""CL1 시험용 가짜 Confluence(8201) / Codebeamer(8202). 값은 모두 가짜."""
import io, json, re, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
from openpyxl import Workbook

STATE = {"conf": False, "cb": False, "legacy_api": False, "meta": True}
CRED = ("jae", "pw!23")
CB = "http://127.0.0.1:8202/cb"
LOGIN_FORM = """<html><body><form method="post" action="{act}">
<label>ID <input name="{u}" type="text"></label><label>PW <input name="{p}" type="password"></label>
<button type="submit">Log in</button></form></body></html>"""


def make_ci_list():
    wb = Workbook(); ws = wb.active; ws.title = "CI List"
    hdr = {"B": "No", "D": "Category", "E": "CI ID", "F": "Tracker Key", "G": "CI name", "I": "Author",
           "J": "Repository", "K": "Path in Repository", "O": "PBL"}
    for c, v in hdr.items(): ws[f"{c}3"] = v
    rows = [
        ("SYS.1", "CI-SYS1-01", "Stakeholder Requirements(FuSa)", "Codebeamer", f"{CB}/tracker/1001?view_id=-2", "PBL"),
        ("SYS.2", "CI-SYS2-01", "System Requirements Specification_ADCU50", "Codebeamer", f"{CB}/tracker/1002", "PBL"),
        ("HWE.1", "CI-HWE1-01", "Hardware Requirements Specification_ADCU50", "Codebeamer", f"{CB}/tracker/1003", "PBL"),
        ("SYS.3", "CI-SYS3-01", "System Architectural Design Specification_ADCU50", "Codebeamer", f"{CB}/tracker/1999", "PBL"),
        ("SWE.1", "CI-SWE1-01", "Software Requirements Specification", "Codebeamer", f"{CB}/tracker/1004", "PBL"),
        ("SWE.6", "CI-SWE6-01", "Software Qualification Test Report", "Codebeamer", f"{CB}/tracker/1006", "PBL"),
        (None, "CI-SYS1-02", "Item Definition", "Confluence", "http://127.0.0.1:8201/pages/viewpage.action?pageId=555", "PBL"),
        ("SWE.3", "CI-SWE3-01", "Source code", "Git", "ssh://git.example/adcu50.git", "PBL"),
        ("MAN.3", "CI-MAN3-01", "Project Plan", "Codebeamer", f"{CB}/tracker/1007", None),
        ("SUP.8", "CI-SUP8-01", "CM Plan", "Codebeamer", f"{CB}/tracker/1500", "PBL"),
        ("SYS.2", "CI-SYS2-02", "Concept Requirement Specification", "Codebeamer", "", "PBL"),
    ]
    for i, (cat, cid, name, repo, path, pbl) in enumerate(rows):
        n = 4 + i
        for c, v in zip("DEGJKO", (cat, cid, name, repo, path, pbl)):
            if v is not None: ws[f"{c}{n}"] = v
        ws[f"I{n}"] = "작성자"; ws[f"B{n}"] = i + 1
    b = io.BytesIO(); wb.save(b); return b.getvalue()


CI_XLSX = make_ci_list()
TRACKERS = {1001: "Stakeholder Requirements(FuSa)", 1002: "System Requirements Specification ADCU50",
            1003: "Hardware Requirements Specification_ADCU50S", 1004: "SW Test Plan",
            1005: "Software Requirements Specification", 1006: "Software Qualification Test Report", 1007: "Project Plan"}
TREE = [{"isFolder": True, "text": "SWE", "children": [{"trackerId": t, "text": n} for t, n in TRACKERS.items()]}]

DESC_ROWS = [("Stakeholder Requirements(FuSa)", "v3.0"), ("Item Definition", "v5.0"),
             ("System Requirements Specification_ADCU50", "v2.5"), ("System Architectural Design Specifiction_ADCU50", "v2.1"),
             ("Hardware Requirements Specification_ADCU50S", "v3.0"), ("Software Requirements Specification", "v2.3"),
             ("Source code", "-"), ("Concept Requirement Specification", "v2.9")]
DESC_HTML = ("<table class='propertyTable'><tr><td>Name:</td><td><a href='/cb/doc/9705300'>HKMC_ADCU50S_RS4FL_G_M_PBL_2026-11-19</a></td>"
             "<td>Description:</td><td><div class='wiki'><table><tr><th>PBL Baseline 대상 산출물</th><th>산출물 버전</th></tr>"
             + "".join(f"<tr><td>{n.replace('_', '<br>_', 1) if 'ADCU' in n else n}</td><td>{v}</td></tr>" for n, v in DESC_ROWS)
             + "</table></div></td></tr></table>")
DESC_WIKI = "|| PBL Baseline 대상 산출물 || 산출물 버전 ||\n" + "\n".join(f"| {n} | {v} |" for n, v in DESC_ROWS[:3])

BASELINES = [  # (이름, 문서 번호) — 화면 순서 = 최신이 위
    ("HKMC_ADCU50_RS4FL_G_SWQT_2026-11-20_", 9800000),      # 더 최신이지만 PBL 아님 → 선택되면 안 됨
    ("HKMC_ADCU60_RS4FL_PBL_2026-11-21", 9900000),          # 다른 제품 → 선택되면 안 됨
    ("HKMC_ADCU50S_RS4FL_G_M_PBL_2026-11-19", 9705300),
    ("HKMC_ADCU50S_RS4FL_G_P2.1_PBL_2026-10-16_Temp3", 9600000),
]


def _meta(n, d):
    """실제 Codebeamer 화면처럼 행마다 숨은 정보(span.metaData)를 넣는다 (Description은 HTML 이스케이프)"""
    import html as H
    if not STATE["meta"]:
        return ""
    desc = DESC_HTML if d == 9705300 else "<div>old</div>"
    ts = {9800000: 1795100000000, 9900000: 1795200000000, 9705300: 1794989240321, 9600000: 1792128926448}[d]
    return (f'<span class="metaData" style="display: none;" data-baseline-id="{d}" data-baseline-created-timestamp="{ts}" '
            f'data-baseline-name="{n}" data-baseline-url="/cb/wiki/revision/1?revision={d}" '
            f'data-baseline-description="{H.escape(desc, quote=True)}"></span>')


def baselines_html():
    rows = "".join(
        f"<tr><td>{_meta(n, d)}<a href='/cb/doc/{d}'>{n}</a><div class='desc'>Hover over here to see the description.</div></td>"
        f"<td><a href='/cb/userdata/1'>kitae_lee</a> Nov 18 17:07</td>"
        f"<td><a href='/cb/proj/doc/details.do?doc_id={d}&amp;orgDitchnetTabPaneId=document-properties'>props</a></td></tr>"
        for n, d in BASELINES)
    return f"<html><body><input type='text' name='filter'><table class='displaytag'><tr><th>Baseline</th><th>Created by</th><th>Signed</th></tr>{rows}</table></body></html>"


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
            return self.send(200, {"id": "555", "title": "Item Definition"})
        if p == "/rest/api/content/1/child/attachment":
            return self.send(200, {"_links": {"base": "http://127.0.0.1:8201"}, "results": [
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
        if p == "/cb/api/v3/projects/171":
            return self.send(200, {"id": 171, "name": "HKMC_RS4PE"})
        m = re.fullmatch(r"/cb/api/v3/trackers/(\d+)", p)
        if m:
            t = int(m.group(1))
            if t == 1500:
                return self.send(500, {"m": "boom"})
            return self.send(200, {"id": t, "name": TRACKERS[t], "projectId": 171}) if t in TRACKERS else self.send(404, {"m": "nf"})
        if p == "/cb/api/v3/trackers/tree":
            return self.send(200, TREE)
        if p == "/cb/rest/project/171/baselines" and STATE["legacy_api"]:
            return self.send(200, [{"uri": f"/baseline/{d}", "name": n, "createdAt": f"2026-11-{19 if d == 9705300 else 1:02d}T08:00:00Z",
                                    "description": DESC_WIKI if d == 9705300 else "old"} for n, d in BASELINES if "SWQT" not in n])
        if p == "/cb/project/171/baselines":
            return self.send(200, baselines_html(), "text/html")
        if p == "/cb/proj/doc/details.do" and q.get("doc_id") == ["9705300"]:
            return self.send(200, f"<html><body>{DESC_HTML}</body></html>", "text/html")
        if p == "/cb/doc/9705300":
            return self.send(200, "<html><body>baseline browse — no description here</body></html>", "text/html")
        self.send(404, {"m": "nf"})


def start():
    for port, cls in ((8201, Conf), (8202, Cb)):
        s = ThreadingHTTPServer(("127.0.0.1", port), cls)
        threading.Thread(target=s.serve_forever, daemon=True).start()

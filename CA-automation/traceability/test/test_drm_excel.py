"""DRM 경로 시험: 가짜 Excel COM 객체로 grid_excel → 일반 경로와 같은 결과인지 확인"""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import traceability as T
import mock_servers as M
from openpyxl import load_workbook
import io

cfg = json.loads((Path(__file__).resolve().parent.parent / "config.example.json").read_text(encoding="utf-8"))
data = M.CI_XLSX


class Obj:
    def __init__(self, **k): self.__dict__.update(k)


def fake_excel_from(xlsx_bytes, log):
    wv = load_workbook(io.BytesIO(xlsx_bytes), data_only=True)
    wf = load_workbook(io.BytesIO(xlsx_bytes), data_only=False)

    class WS:
        def __init__(self, v, f):
            self.Name = v.title
            r0, c0 = v.min_row, v.min_column
            r1, c1 = v.max_row, v.max_column
            vals = tuple(tuple(v.cell(r, c).value for c in range(c0, c1 + 1)) for r in range(r0, r1 + 1))
            forms = tuple(tuple(f.cell(r, c).value for c in range(c0, c1 + 1)) for r in range(r0, r1 + 1))
            # Excel COM: 숫자는 float, 1x1이면 스칼라
            vals = tuple(tuple(float(x) if isinstance(x, int) else x for x in row) for row in vals)
            if len(vals) == 1 and len(vals[0]) == 1:
                vals, forms = vals[0][0], forms[0][0]
            self.UsedRange = Obj(Row=r0, Column=c0, Rows=Obj(Count=r1 - r0 + 1), Columns=Obj(Count=c1 - c0 + 1), Value=vals, Formula=forms)
            self.Hyperlinks = [Obj(Range=Obj(Row=c.row, Column=c.column), Address=c.hyperlink.target)
                               for row in v.iter_rows() for c in row if c.hyperlink and c.hyperlink.target]

    class WB:
        Worksheets = [WS(wv[n], wf[n]) for n in wv.sheetnames]
        def Close(self, save): log.append(("close", save))

    class XL:
        def __init__(self): self.Workbooks = Obj(Open=lambda p, u, ro: (log.append(("open", p, u, ro)), WB())[1])
        def Quit(self): log.append(("quit",))
    return XL


log = []
drm = b"\x9b DRMONE  This Document is encrypted and protected by Fasoo DRM " + b"\x00" * 100
a, ia = T.read_ci_list(data, cfg)
b, ib = T.read_ci_list(drm, cfg, saved_path="C:/x/ci.xlsx", excel_factory=fake_excel_from(data, log))
strip = lambda L: [{k: v for k, v in d.items()} for d in L]
print("openpyxl:", [(x["ciId"], x["trackerId"], x["category"]) for x in a], ia)
print("excel   :", [(x["ciId"], x["trackerId"], x["category"]) for x in b], ib)
print("log:", log)
assert strip(a) == strip(b), "결과 불일치"
assert ("close", False) in log and ("quit",) in log and log[0][3] is True
print("DRM 경로 OK")

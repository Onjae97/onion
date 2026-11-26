#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AUTO-001 추적성 — 항목 1개 · Tracker별 탭 (v1.0)

CL6_Traceability(전체 Gap Matrix)와 같은 판정 규칙으로, CI 하나만 골라
최상위 Tracker와 하위 Tracker를 검사하고 **Tracker마다 탭**으로 미추적 Item을 보여준다.

흐름: ① Confluence 최신 CI list → ② 검사할 CI 1개 선택 → ③ 최상위 Tracker + 하위 Tracker 범위 확인
      → ④ CL6와 같은 판정 → ⑤ Overview(Tracker별 요약) + Tracker별 탭 + 검수 + 확인불가 + 실행정보

판정 로직은 ../CL6_Traceability/traceability.py 를 그대로 불러 쓴다 (이 파일에서 규칙을 바꾸지 않음).
원칙: 읽기 전용(GET) · 조회 실패 = 확인불가 · 결과는 항상 새 파일.

사용:   python traceability_bytracker.py                 # 목록에서 고르기
        python traceability_bytracker.py --ci SYS5_05    # 바로 지정 (일부만 입력해도 하나로 좁혀지면 됨)
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

VERSION = "1.1"
HERE = Path(__file__).resolve().parent
STATE = HERE / "state"


def _load_core():
    """CL6 판정 모듈 위치: 같은 폴더 → 옆 폴더 CL6_Traceability"""
    for d in (HERE, HERE.parent / "CL6_Traceability"):
        if (d / "traceability.py").exists():
            sys.path.insert(0, str(d))
            import traceability  # noqa: E402
            return traceability, d
    raise SystemExit("✖ traceability.py(CL6_Traceability)를 찾지 못했습니다. "
                     "이 폴더를 CL6_Traceability 폴더 옆에 두세요 (CA-automation 안에 나란히).")


tr, CORE_DIR = _load_core()
log, ApiError, NeedLogin = tr.log, tr.ApiError, tr.NeedLogin


# =====================================================================
# 1. 검사할 CI 고르기
# =====================================================================
def match_ci(cis, text):
    """CI ID 정확히 일치 → 그 하나. 아니면 CI ID·CI name·Tracker Key에 포함된 것 전부."""
    t = text.strip().lower()
    if not t:
        return []
    exact = [c for c in cis if c["ciId"].lower() == t]
    if exact:
        return exact[:1]
    return [c for c in cis if t in c["ciId"].lower() or t in c["ciName"].lower() or t in (c.get("trackerKey") or "").lower()]


def show_list(cis, allc):
    for c in cis:
        n = allc.index(c) + 1
        print(f"  {n:>3}. {c['ciId']:<26} [{c['category']}] {c['ciName'][:60]}")


def choose_ci(cis, want=None, ask=input):
    if want:
        m = match_ci(cis, want)
        if len(m) == 1:
            return m[0]
        if not m:
            raise ApiError(f"검사 대상(PBL·Codebeamer) CI 중 '{want}'에 해당하는 것이 없습니다.")
        show_list(m, cis)
        raise ApiError(f"'{want}'에 해당하는 CI가 {len(m)}개입니다. 위 목록의 CI ID를 정확히 지정해 주세요.")
    print("\n검사할 CI를 고르세요 (PBL 있고 Repository가 Codebeamer인 CI):")
    show_list(cis, cis)
    while True:
        s = ask("\n번호 또는 CI ID 입력 (일부만 입력하면 검색): ").strip()
        if not s:
            continue
        if s.isdigit() and 1 <= int(s) <= len(cis):
            return cis[int(s) - 1]
        m = match_ci(cis, s)
        if len(m) == 1:
            return m[0]
        if not m:
            print(f"  '{s}'에 해당하는 CI가 없습니다. 다시 입력하세요.")
            continue
        print(f"  '{s}' 검색 결과 {len(m)}개 — 번호로 고르세요:")
        show_list(m, cis)


# =====================================================================
# 2. 검사 (CL6 check_ci 그대로 + Item이 속한 Tracker 기록)
# =====================================================================
def check_one(cl, ci, exclude, sample, scope_mode):
    """CL6 check_ci로 판정하고, 같은 실행에서 받은 Item 목록으로 Item → Tracker를 매긴다 (추가 조회 없음)."""
    got = {}
    orig = tr.cb_items

    def capture(*a, **k):
        items = orig(*a, **k)
        got["items"] = items
        return items
    tr.cb_items = capture  # 진행률 표시·Item 수 안내는 CL6 traceability.py(v1.9~)가 함
    try:
        r = tr.check_ci(cl, ci, exclude, sample, scope_mode, {})
    finally:
        tr.cb_items = orig
    items = got.get("items") or []
    in_scope = {t["id"] for t in r.get("trackers") or []}
    r["item_tracker"], r["item_type"] = {}, {}
    for it in items:
        t = str((it.get("tracker") or {}).get("id") or "")
        r["item_tracker"][it["id"]] = t if t in in_scope else r.get("scope_root", "")  # CL6 tid_of와 동일
        r["item_type"][it["id"]] = tr.type_of(it)
    return r


# =====================================================================
# 3. 엑셀
# =====================================================================
RESERVED = {"overview", "검수", "확인불가", "실행정보"}


def tab_names(trackers):
    names, used = {}, set(RESERVED)
    for n, ti in enumerate(trackers, 1):
        base = re.sub(r"[\\/?*\[\]:]", "_", f"{n:02d} {ti['name'] or ti['key'] or ti['id']}").strip()[:31]
        name, k = base, 2
        while name.lower() in used:
            name = base[:28] + f"_{k}"
            k += 1
        used.add(name.lower())
        names[ti["id"]] = name
    return names


def build_workbook(r, meta, cb_base):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter, quote_sheetname

    HF, HFont, BOLD = PatternFill("solid", fgColor="00B0F0"), Font(bold=True, color="FFFFFF"), Font(bold=True)
    LINK = Font(color="0563C1", underline="single")
    RED, GRAY, YEL = (PatternFill("solid", fgColor=c) for c in ("FFC7CE", "E7E6E6", "FFF2CC"))

    def header(ws, row, cols, widths=None):
        for i, h in enumerate(cols, 1):
            c = ws.cell(row, i, h)
            c.fill, c.font = HF, HFont
            c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            if widths:
                ws.column_dimensions[get_column_letter(i)].width = widths[i - 1]

    def link(cell, url, text=None):
        cell.value = text if text is not None else url
        if url:
            cell.hyperlink, cell.font = url, LINK

    trackers = r.get("trackers") or []
    names = tab_names(trackers)
    unl, unset, only_ex = set(r["unlinked"]), set(r.get("unset") or []), set(r.get("only_excluded") or [])
    by_t = {}
    for iid in r["unlinked"]:
        by_t.setdefault(r["item_tracker"].get(iid, r.get("scope_root", "")), []).append(iid)
    ok = not r["status"].startswith("확인불가")
    cov = tr.coverage(r["denom"], len(r["unlinked"])) if ok else None

    wb = Workbook()
    ov = wb.active
    ov.title = "Overview"

    # (1) CI 요약
    info = [("CI ID", r["ciId"]), ("Category", r["category"]), ("CI name", r["ciName"]), ("Author", r["author"]),
            ("Path in Repository", None), ("검사 범위(최상위 Tracker)", None), ("범위 메모", r.get("scope_note") or "-"),
            ("상태", r["status"]),
            ("분모(판정대상)", r["denom"] if ok else None), ("미추적", len(unl) if ok else None),
            ("커버리지(%)", cov), ("제외(Folder/Information)", r["excluded"] if ok else None),
            ("확인불가", len(r["unknown"])), ("전체 Item", r["total"] if ok else None), ("Tracker 수", len(trackers))]
    for i, (k, v) in enumerate(info, 1):
        ov.cell(i, 1, k).font = BOLD
        ov.cell(i, 2, v)
        if k == "Path in Repository":
            link(ov.cell(i, 2), r["path"])
        elif k == "검사 범위(최상위 Tracker)" and r.get("scope_root"):
            link(ov.cell(i, 2), f"{cb_base}/tracker/{r['scope_root']}", f"{r.get('scope_name', '')} ({r['scope_root']})")
        elif k == "범위 메모" and r.get("scope_note"):
            ov.cell(i, 2).fill = YEL
        elif k == "미추적" and unl:
            ov.cell(i, 2).fill = RED
        elif k == "커버리지(%)":
            ov.cell(i, 2).number_format = "0.0"
        elif k == "상태" and (not ok or r["unknown"]):
            ov.cell(i, 2).fill = GRAY

    # (2) Tracker별 요약 — Sheet 열을 누르면 해당 Tracker 탭으로 이동
    h = len(info) + 2
    cols = ["No", "Sheet", "Tracker", "Key", "전체 Item", "제외", "분모", "미추적", "커버리지(%)", "확인불가",
            "Type 미지정(--)", "미추적 중 Type 미지정(--)", "미추적 중 Folder/Information에만 연결"]
    header(ov, h, cols, [26, 30, 42, 18, 10, 8, 10, 9, 12, 10, 14, 18, 22])
    tot = [0] * 6
    for n, ti in enumerate(trackers, 1):
        ids = set(by_t.get(ti["id"], []))
        row = [n, None, None, ti["key"], ti["total"], ti["excluded"], ti["denom"], ti["unlinked"],
               tr.coverage(ti["denom"], ti["unlinked"]), ti["unknown"] or None,
               ti.get("unset") if ti.get("has_type") else "(Type 필드 없음)",
               ti.get("unset_unlinked") if ti.get("has_type") else None, len(ids & only_ex) or None]
        ov.append(row)
        x = ov.max_row
        link(ov.cell(x, 2), f"#{quote_sheetname(names[ti['id']])}!A1", names[ti["id"]])
        link(ov.cell(x, 3), f"{cb_base}/tracker/{ti['id']}", f"{ti['name']} ({ti['id']})")
        ov.cell(x, 9).number_format = "0.0"
        if ti["unlinked"]:
            ov.cell(x, 8).fill = RED
        if ti.get("unset_unlinked"):
            ov.cell(x, 12).fill = YEL
        for j, v in enumerate((ti["total"], ti["excluded"], ti["denom"], ti["unlinked"], ti["unknown"], len(ids & only_ex))):
            tot[j] += v or 0
    ov.append(["합계", None, None, None, tot[0], tot[1], tot[2], tot[3], tr.coverage(tot[2], tot[3]), tot[4] or None,
               None, None, tot[5] or None])
    for j in range(1, len(cols) + 1):
        ov.cell(ov.max_row, j).font = BOLD
    ov.cell(ov.max_row, 9).number_format = "0.0"
    ov.freeze_panes = ov.cell(h + 1, 1)

    # (3) Tracker마다 탭 — 미추적 Item (CL6 Category 탭과 같은 열 + Tracker·유형)
    tcols = ["No", "CI ID", "CI name", "Author", "Tracker", "Item ID", "유형", "비고"]
    for ti in trackers:
        ws = wb.create_sheet(names[ti["id"]])
        ws.cell(1, 1, f"{ti['name']} ({ti['id']}) · key {ti['key'] or '-'} · 분모 {ti['denom']} · "
                      f"미추적 {ti['unlinked']} · 커버리지 {str(tr.coverage(ti['denom'], ti['unlinked'])) + '%' if ti['denom'] else '-'}"
                      + (f" · 확인불가 {ti['unknown']}" if ti["unknown"] else "")).font = BOLD
        link(ws.cell(1, 9), "#Overview!A1", "← Overview")
        header(ws, 2, tcols, [6, 22, 36, 12, 40, 24, 20, 30])
        ws.freeze_panes = "A3"
        ids = sorted(by_t.get(ti["id"], []))
        for k, iid in enumerate(ids, 1):
            note = " · ".join(x for x in ("Type 미지정(--)" if iid in unset else "",
                                          "Folder/Information에만 연결" if iid in only_ex else "") if x)
            ws.append([k, r["ciId"], r["ciName"], r["author"], None, None, r["item_type"].get(iid) or None, note or None])
            x = ws.max_row
            link(ws.cell(x, 5), f"{cb_base}/tracker/{ti['id']}", f"{ti['name']} ({ti['id']})")
            link(ws.cell(x, 6), f"{cb_base}/issue/{iid}", tr.item_label(r, iid))
            if note:
                ws.cell(x, 8).fill = YEL
        if ids:
            ws.auto_filter.ref = f"A2:H{ws.max_row}"
        else:
            ws.append(["", "미추적 Item 없음" if ti["denom"] or ti["unknown"] else "판정 대상 Item 없음"])

    # (4) 검수 — 연결됨 판정 표본
    vf = wb.create_sheet("검수")
    header(vf, 1, ["표본 Item (연결됨 판정)", "Tracker", "API 연결 수", "유형", "확인 결과(사람 기입)"], [26, 40, 12, 20, 22])
    tname = {ti["id"]: f"{ti['name']} ({ti['id']})" for ti in trackers}
    for iid, n, ty in r.get("sample", []):
        vf.append([None, tname.get(r["item_tracker"].get(iid), ""), n, ty, None])
        link(vf.cell(vf.max_row, 1), f"{cb_base}/issue/{iid}", tr.item_label(r, iid))

    # (5) 확인불가
    uk = wb.create_sheet("확인불가")
    header(uk, 1, ["Tracker", "Item", "내용"], [40, 24, 80])
    if not ok:
        uk.append(["", "", r["status"]])
    for iid in r["unknown"]:
        uk.append([tname.get(r["item_tracker"].get(iid), ""), None, (r.get("unknown_reason") or {}).get(iid, "연결 조회 실패")])
        link(uk.cell(uk.max_row, 2), f"{cb_base}/issue/{iid}", tr.item_label(r, iid))

    # (6) 실행정보
    inf = wb.create_sheet("실행정보")
    header(inf, 1, ["항목", "값"], [28, 90])
    for k, v in meta.items():
        inf.append([k, str(v)])
    return wb


# =====================================================================
# 4. 실행
# =====================================================================
def find_config(arg):
    if arg:
        return Path(arg)
    for p in (HERE / "config.json", CORE_DIR / "config.json"):
        if p.exists():
            return p
    return HERE / "config.json"


def main(argv=None, ask=input):
    ap = argparse.ArgumentParser(description="AUTO-001 추적성 — 항목 1개 Tracker별 탭")
    ap.add_argument("--ci", help="검사할 CI ID (생략하면 목록에서 고름)")
    ap.add_argument("--headless", action="store_true", help="브라우저 창 숨김 (로그인 저장된 뒤에만)")
    ap.add_argument("--config", help="설정 파일 (기본: 이 폴더 config.json → 없으면 CL6_Traceability/config.json)")
    a = ap.parse_args(argv)
    cfg_path = find_config(a.config)
    if not cfg_path.exists():
        raise ValueError("설정 파일(config.json)이 없습니다 — CL6_Traceability의 config.json을 쓰거나 이 폴더에 복사해 두세요.")
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    STATE.mkdir(exist_ok=True)
    (STATE / "ci_list").mkdir(exist_ok=True)
    out_dir = HERE / cfg.get("output_dir", "output")
    out_dir.mkdir(exist_ok=True)
    exclude = {t.lower() for t in cfg["judge"]["exclude_types"]}
    scope = cfg.get("scope", "top_with_descendants")
    t0 = time.time()

    from playwright.sync_api import sync_playwright
    log(f"AUTO-001 추적성 — 항목 1개 Tracker별 v{VERSION} (판정: CL6 traceability.py v{tr.VERSION}, 설정: {cfg_path})")
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(STATE / "browser-profile"), channel=cfg["browser"].get("channel") or None,
            headless=a.headless, viewport={"width": 1280, "height": 860})
        try:
            # ① 최신 CI list
            cf = cfg["confluence"]
            pid = cf["ci_list_page_id"]
            conf = tr.Session(ctx, "Confluence", f"{cf['base']}/pages/viewpage.action?pageId={pid}",
                              cf["base"] + cf.get("login_path", "/login.action"), not a.headless, tr.get_cred("Confluence"))
            conf.ensure_login(cf["base"], "/rest/api/user/current",
                              lambda b: b.get("type") != "anonymous" and bool(b.get("username") or b.get("userKey") or b.get("displayName")))
            ccl = tr.Client(conf.fetch_json, cf["base"])
            atts = tr.latest_xlsx(ccl.get(f"/rest/api/content/{pid}/child/attachment?expand=version&limit=200"), cf["base"])
            if not atts:
                raise ApiError("CI list 페이지에 엑셀 첨부 파일이 없습니다.")
            latest = atts[0]
            log(f"① 최신 CI list: {latest['title']} (업로드 {latest['when'][:16].replace('T', ' ')} {latest['by']})")
            data = conf.fetch_bytes(latest["url"])
            saved = STATE / "ci_list" / f"{time.strftime('%Y%m%d_%H%M')}_{latest['title']}"
            saved.write_bytes(data)
            cis, info = tr.read_ci_list(data, cfg, saved_path=saved)
            cis = [c for c in cis if c["trackerId"]]
            log(f"   검사 가능 CI {len(cis)}개 (PBL 있음 · Codebeamer · Tracker 번호 있음)")
            if not cis:
                raise ApiError("검사할 CI가 없습니다.")

            # ② CI 선택
            if not a.ci and a.headless:
                raise ApiError("--headless로 실행할 때는 --ci 로 CI를 지정해 주세요.")
            ci = choose_ci(cis, a.ci, ask)
            log(f"② 선택: {ci['ciId']} [{ci['category']}] {ci['ciName']} (등록 Tracker {ci['trackerId']})")

            # ③ Codebeamer 로그인 · 범위 확인
            cb = cfg["codebeamer"]
            cbs = tr.Session(ctx, "Codebeamer", cb["base"], cb["base"] + cb.get("login_path", "/login.spr"),
                             not a.headless, tr.get_cred("Codebeamer"))
            probe = f"/api/v3/trackers/{ci['trackerId']}"

            def cb_login():
                cbs.ensure_login(cb["base"], probe, lambda b: bool(b.get("id")))
                cbs.pin(cb["base"] + probe)
            cb_login()
            ccb = tr.Client(cbs.fetch_json, cb["base"], batch=cfg.get("batch_size", 10), relogin=cb_login)
            sc = tr.resolve_scope(ccb, ci["trackerId"], scope)
            log(f"③ 검사 범위: 최상위 '{sc['root_name']}'({sc['root']}) · Tracker {len(sc['trackers'])}개"
                + (f" — {sc['note']}" if sc["note"] else ""))

            # ④ 판정
            r = check_one(ccb, ci, exclude, cfg.get("verify_sample", 10), scope)
            for ti in r.get("trackers") or []:
                log(f"   - {ti['name'][:40]:<40} ({ti['id']}) 분모 {ti['denom']:>5} · 미추적 {ti['unlinked']:>4}"
                    + (f" · 확인불가 {ti['unknown']}" if ti["unknown"] else ""))
            cov = tr.coverage(r["denom"], len(r["unlinked"]))
            log(f"④ {ci['ciId']} 분모 {r['denom']} · 미추적 {len(r['unlinked'])} · 커버리지 {cov if cov is not None else '-'}% · {r['status']}")
        finally:
            ctx.close()

    # ⑤ 엑셀
    meta = {
        "실행 시각": time.strftime("%Y-%m-%d %H:%M:%S"),
        "도구": f"AUTO-001 traceability_bytracker.py v{VERSION} (판정 모듈 CL6 traceability.py v{tr.VERSION})",
        "CI list 파일": f"{latest['title']} (Confluence 업로드 {latest['when']} {latest['by']})",
        "검사 CI": f"{ci['ciId']} [{ci['category']}] {ci['ciName']}",
        "검사 범위": {"top_with_descendants": "등록 Tracker의 최상위 Tracker와 그 아래 하위 Tracker 전부",
                   "with_descendants": "등록 Tracker와 그 아래 하위 Tracker 전부",
                   "tracker_only": "등록 Tracker만"}.get(scope, scope),
        "판정 규칙": "CL6_Traceability(전체 Gap Matrix)와 동일 — Folder·Information 제외 / Folder·Information이 아닌 상대와의 "
                     "연결 1개 이상 = 연결 / 상대가 모두 Folder·Information = 미추적 / 조회 실패·상대 확인 불가 = 확인불가",
        "탭 구성": "Overview(CI 요약 + Tracker별 요약, Sheet 열 클릭 → 탭 이동) / Tracker마다 미추적 Item 탭 / 검수 / 확인불가",
        "소요 시간": f"{time.time() - t0:.0f}초",
        "주의": "자동 생성 초안입니다. 공식 산출물 반영·저장은 담당자가 검토 후 직접 합니다.",
    }
    wb = build_workbook(r, meta, cfg["codebeamer"]["base"])
    safe = re.sub(r'[\\/:*?"<>|]', "_", ci["ciId"])
    out = out_dir / f"추적성_Tracker별_{cfg.get('project', '')}_{safe}_{time.strftime('%Y-%m-%d_%H%M%S')}.xlsx"
    wb.save(out)
    log(f"⑤ 완료 — 결과 파일: {out}")
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

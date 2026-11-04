"""테스터가 채운 Test Suite 엑셀을 검수하고 리포트를 만듭니다.

사용법: python scripts/review_suite.py <Test Suite 엑셀>

확인하는 것:
- 미실행 TC, 결과는 있는데 Tester가 없는 칸, Fail/Block인데 사유(Remark)가 없는 칸
- 목록에 없는 결과 값 (복사·붙여넣기로 들어간 오타 등)
- 회차별 / 최종 결과 집계와 Pass율
"""

import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from suite_format import NEEDS_REMARK, RESULT_VALUES, TC_SHEET, round_header

HEADER_FILL = PatternFill("solid", fgColor="1F4E78")
HEADER_FONT = Font(bold=True, color="FFFFFF")


def clean(value):
    """빈칸은 빈 문자열로, 나머지는 앞뒤 공백을 지운 문자열로 바꿉니다."""
    if value is None:
        return ""
    return str(value).strip()


def read_suite(path):
    """Test Case 시트를 읽어서 TC별 회차 결과 목록을 만듭니다."""
    wb = load_workbook(path)
    if TC_SHEET not in wb.sheetnames:
        sys.exit(f"'{TC_SHEET}' 시트가 없습니다. build_suite.py로 만든 엑셀인지 확인해 주세요.")
    ws = wb[TC_SHEET]

    headers = [clean(cell.value) for cell in ws[1]]
    col = {name: i for i, name in enumerate(headers) if name}

    # "1차 결과", "2차 결과" 같은 열 이름에서 회차 번호를 찾습니다
    rounds = sorted(int(m.group(1)) for h in headers if (m := re.fullmatch(r"(\d+)차 결과", h)))
    if not rounds:
        sys.exit("회차 결과 열(예: '1차 결과')을 찾을 수 없습니다.")

    cases = []
    for values in ws.iter_rows(min_row=2, values_only=True):
        tc_id = clean(values[col["TC ID"]])
        if not tc_id:
            continue
        runs = []
        for n in rounds:
            runs.append({
                "round": n,
                "result": clean(values[col[round_header(n, "결과")]]),
                "tester": clean(values[col[round_header(n, "Tester")]]),
                "remark": clean(values[col[round_header(n, "Remark")]]),
            })
        cases.append({
            "id": tc_id,
            "title": clean(values[col["제목"]]),
            "priority": clean(values[col["우선순위"]]),
            "runs": runs,
        })
    return cases, rounds


def final_run(case):
    """결과가 적힌 가장 마지막 회차를 돌려줍니다. 한 번도 안 했으면 None."""
    done = [run for run in case["runs"] if run["result"]]
    return done[-1] if done else None


def find_problems(cases):
    """검수에서 걸리는 칸을 (TC ID, 회차, 문제, 내용) 목록으로 모읍니다."""
    problems = []
    for case in cases:
        if final_run(case) is None:
            problems.append((case["id"], "-", "미실행", "어느 회차에도 결과가 없습니다"))

        for run in case["runs"]:
            label = f"{run['round']}차"
            result = run["result"]
            if result and result not in RESULT_VALUES:
                problems.append((case["id"], label, "잘못된 결과 값", f"'{result}' (허용: {', '.join(RESULT_VALUES)})"))
            if result and not run["tester"]:
                problems.append((case["id"], label, "Tester 누락", "결과는 있는데 Tester가 비어 있습니다"))
            if result in NEEDS_REMARK and not run["remark"]:
                problems.append((case["id"], label, "사유 누락", f"{result}인데 Remark가 비어 있습니다"))
            if not result and (run["tester"] or run["remark"]):
                problems.append((case["id"], label, "결과 누락", "Tester/Remark는 있는데 결과가 비어 있습니다"))
    return problems


def count_results(results):
    counts = Counter(results)
    row = [counts.get(value, 0) for value in RESULT_VALUES]
    # 목록에 없는 값은 '기타'로 따로 세서 합계가 TC 수와 맞도록 합니다
    row.append(sum(n for value, n in counts.items() if value and value not in RESULT_VALUES))
    row.append(counts.get("", 0))
    executed = sum(counts.get(value, 0) for value in ("Pass", "Fail", "Block"))
    rate = counts.get("Pass", 0) / executed if executed else 0
    return row, rate


def write_table(ws, headers, rows, widths):
    for col, (name, width) in enumerate(zip(headers, widths), 1):
        cell = ws.cell(row=1, column=col, value=name)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center")
        ws.column_dimensions[get_column_letter(col)].width = width
    for r, values in enumerate(rows, 2):
        for c, value in enumerate(values, 1):
            ws.cell(row=r, column=c, value=value).alignment = Alignment(wrap_text=True, vertical="top")
    ws.freeze_panes = "A2"


def main():
    if len(sys.argv) != 2:
        sys.exit("사용법: python scripts/review_suite.py <Test Suite 엑셀>")
    suite_path = Path(sys.argv[1])
    if not suite_path.exists():
        sys.exit(f"파일을 찾을 수 없습니다: {suite_path}")

    cases, rounds = read_suite(suite_path)
    problems = find_problems(cases)

    # 회차별 집계와, 마지막 회차 기준 최종 집계
    stat_rows = []
    for i, n in enumerate(rounds):
        counts, rate = count_results(case["runs"][i]["result"] for case in cases)
        stat_rows.append([f"{n}차"] + counts + [rate])
    final_results = [(final_run(case) or {"result": ""})["result"] for case in cases]
    final_counts, final_rate = count_results(final_results)
    stat_rows.append(["최종"] + final_counts + [final_rate])

    issues = []
    for case in cases:
        run = final_run(case)
        if run and run["result"] in NEEDS_REMARK:
            issues.append([case["id"], case["priority"], case["title"], f"{run['round']}차", run["result"], run["tester"], run["remark"]])

    verdict = "검수 완료" if not problems else f"보완 필요 ({len(problems)}건)"

    wb = Workbook()
    ws = wb.active
    ws.title = "요약"
    info = [
        ("검수 대상", suite_path.name),
        ("검수 일시", datetime.now().strftime("%Y-%m-%d %H:%M")),
        ("TC 수", len(cases)),
        ("판정", verdict),
    ]
    for r, (label, value) in enumerate(info, 1):
        ws.cell(row=r, column=1, value=label).font = Font(bold=True)
        ws.cell(row=r, column=2, value=value)
    ws.column_dimensions["A"].width = 12
    ws.column_dimensions["B"].width = 14

    start = len(info) + 2
    headers = ["회차"] + RESULT_VALUES + ["기타", "미실행", "Pass율"]
    for c, name in enumerate(headers, 1):
        cell = ws.cell(row=start, column=c, value=name)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
    for r, values in enumerate(stat_rows, start + 1):
        for c, value in enumerate(values, 1):
            cell = ws.cell(row=r, column=c, value=value)
            if c == len(headers):
                cell.number_format = "0.0%"
    ws.cell(row=start + len(stat_rows) + 2, column=1, value="※ Pass율 = Pass / (Pass + Fail + Block), N/A와 미실행은 제외")

    write_table(wb.create_sheet("확인 필요 항목"), ["TC ID", "회차", "문제", "내용"], problems, [10, 8, 16, 50])
    write_table(
        wb.create_sheet("Fail·Block 목록"),
        ["TC ID", "우선순위", "제목", "회차", "결과", "Tester", "Remark"],
        issues,
        [10, 9, 30, 8, 8, 10, 40],
    )

    out = suite_path.with_name(f"{suite_path.stem}_검수리포트_{datetime.now():%Y%m%d_%H%M%S}.xlsx")
    wb.save(out)

    sys.stdout.reconfigure(encoding="utf-8")
    print(f"검수 대상: {suite_path.name} (TC {len(cases)}개, {len(rounds)}회차)")
    print(f"최종 결과: " + ", ".join(f"{name} {n}" for name, n in zip(headers[1:-1], final_counts)))
    print(f"Pass율: {final_rate:.1%}")
    print(f"판정: {verdict}")
    for tc_id, label, kind, detail in problems:
        print(f"  - {tc_id} [{label}] {kind}: {detail}")
    print(f"리포트 저장: {out}")


if __name__ == "__main__":
    main()

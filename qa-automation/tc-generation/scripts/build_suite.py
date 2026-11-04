"""testcases.json을 읽어서 테스터가 채울 Test Suite 엑셀을 만듭니다.

사용법: python scripts/build_suite.py <testcases.json> [--rounds 회차수]
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from openpyxl import Workbook
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

# tc-generation과 tc-execution이 함께 쓰는 common/suite_format.py를 찾을 수 있게 합니다
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "common"))

from suite_format import (
    ANALYSIS_SHEET,
    FINAL_RESULT_COLUMN,
    QUESTION_SHEET,
    RESULT_VALUES,
    ROUND_FIELDS,
    RUN_COUNT_COLUMN,
    SUMMARY_SHEET,
    TC_BASE_COLUMNS,
    TC_SHEET,
    round_header,
)

HEADER_FILL = PatternFill("solid", fgColor="1F4E78")
HEADER_FONT = Font(bold=True, color="FFFFFF")
# 회차별로 머리글 색을 바꿔서 몇 차 열인지 한눈에 보이게 합니다
ROUND_FILLS = ["DDEBF7", "E2EFDA", "FFF2CC", "FCE4D6"]
RESULT_COLORS = {"Pass": "C6EFCE", "Fail": "FFC7CE", "Block": "FFEB9C", "N/A": "D9D9D9"}
THIN = Side(style="thin", color="BFBFBF")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
WRAP = Alignment(wrap_text=True, vertical="top")


def load_testcases(path):
    """JSON을 읽고, 엑셀을 만들기 전에 빠진 항목이 없는지 확인합니다."""
    data = json.loads(path.read_text(encoding="utf-8"))

    for key in ("spec", "requirements", "test_cases"):
        if key not in data:
            sys.exit(f"{path.name}에 '{key}' 항목이 없습니다.")

    req_ids = {req["id"] for req in data["requirements"]}
    for tc in data["test_cases"]:
        if tc.get("req_id") not in req_ids:
            sys.exit(f"{tc.get('id')}의 req_id '{tc.get('req_id')}'가 requirements에 없습니다.")

    data.setdefault("questions", [])
    data.setdefault("created", date.today().isoformat())
    return data


def as_text(value, numbered=False):
    """리스트는 줄바꿈으로 이어 붙여서 한 칸에 들어가게 합니다."""
    if not isinstance(value, list):
        return value or ""
    if numbered:
        return "\n".join(f"{i}. {item}" for i, item in enumerate(value, 1))
    if len(value) == 1:
        return value[0]
    return "\n".join(f"- {item}" for item in value)


def write_header(ws, columns, fills=None):
    """첫 줄에 머리글을 쓰고 열 너비를 맞춥니다."""
    for col, (name, width) in enumerate(columns, 1):
        cell = ws.cell(row=1, column=col, value=name)
        if fills and fills[col - 1]:
            cell.fill = PatternFill("solid", fgColor=fills[col - 1])
            cell.font = Font(bold=True)
        else:
            cell.fill = HEADER_FILL
            cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = BORDER
        ws.column_dimensions[get_column_letter(col)].width = width
    ws.freeze_panes = "B2"


def write_row(ws, row, values):
    for col, value in enumerate(values, 1):
        cell = ws.cell(row=row, column=col, value=value)
        cell.alignment = WRAP
        cell.border = BORDER


def add_result_colors(ws, cell_range):
    for value, color in RESULT_COLORS.items():
        fill = PatternFill("solid", fgColor=color)
        ws.conditional_formatting.add(cell_range, CellIsRule(operator="equal", formula=[f'"{value}"'], fill=fill))


def build_analysis_sheet(wb, data):
    ws = wb.create_sheet(ANALYSIS_SHEET)
    columns = [
        ("REQ ID", 10),
        ("요구사항", 30),
        ("Precondition", 35),
        ("Test Action", 40),
        ("Expected Result", 40),
        ("비고", 25),
    ]
    write_header(ws, columns)
    for row, req in enumerate(data["requirements"], 2):
        write_row(ws, row, [
            req["id"],
            req.get("summary", ""),
            as_text(req.get("preconditions")),
            as_text(req.get("actions"), numbered=True),
            as_text(req.get("expected")),
            req.get("notes", ""),
        ])


def build_tc_sheet(wb, data, rounds):
    ws = wb.create_sheet(TC_SHEET)

    columns = list(TC_BASE_COLUMNS)
    fills = [None] * len(columns)
    for n in range(1, rounds + 1):
        for field, width in ROUND_FIELDS:
            columns.append((round_header(n, field), width))
            fills.append(ROUND_FILLS[(n - 1) % len(ROUND_FILLS)])
    columns += [(RUN_COUNT_COLUMN, 9), (FINAL_RESULT_COLUMN, 10)]
    fills += [None, None]
    write_header(ws, columns, fills)

    names = [name for name, _ in columns]
    result_letters = [get_column_letter(names.index(round_header(n, "결과")) + 1) for n in range(1, rounds + 1)]
    date_letters = [get_column_letter(names.index(round_header(n, "실행일")) + 1) for n in range(1, rounds + 1)]
    final_letter = get_column_letter(names.index(FINAL_RESULT_COLUMN) + 1)

    last_row = len(data["test_cases"]) + 1
    for row, tc in enumerate(data["test_cases"], 2):
        base = [
            tc["id"],
            tc["req_id"],
            tc.get("type", ""),
            tc.get("priority", ""),
            tc.get("title", ""),
            as_text(tc.get("precondition")),
            as_text(tc.get("steps"), numbered=True),
            as_text(tc.get("expected")),
        ]
        blanks = [None] * (rounds * len(ROUND_FIELDS))

        # 실행 횟수: 결과가 채워진 회차 수
        run_count = f"=COUNTA({','.join(f'{c}{row}' for c in result_letters)})"
        # 최종 결과: 가장 마지막 회차의 결과 (뒤 회차부터 확인)
        final = '""'
        for c in result_letters:
            final = f'IF({c}{row}<>"",{c}{row},{final})'

        write_row(ws, row, base + blanks + [run_count, f"={final}"])

    # 결과 칸은 목록에서 고르도록 합니다 (오타 방지)
    validation = DataValidation(type="list", formula1=f'"{",".join(RESULT_VALUES)}"', allow_blank=True)
    validation.error = f"{', '.join(RESULT_VALUES)} 중에서 골라주세요."
    validation.showErrorMessage = True
    ws.add_data_validation(validation)
    for c in result_letters:
        validation.add(f"{c}2:{c}{last_row}")
        add_result_colors(ws, f"{c}2:{c}{last_row}")
    add_result_colors(ws, f"{final_letter}2:{final_letter}{last_row}")

    for c in date_letters:
        for row in range(2, last_row + 1):
            ws[f"{c}{row}"].number_format = "yyyy-mm-dd"

    ws.auto_filter.ref = f"A1:{get_column_letter(len(columns))}{last_row}"
    return final_letter, last_row


def build_question_sheet(wb, data):
    ws = wb.create_sheet(QUESTION_SHEET)
    write_header(ws, [("번호", 6), ("REQ ID", 10), ("확인 필요 내용", 60), ("답변", 40)])
    for row, q in enumerate(data["questions"], 2):
        write_row(ws, row, [row - 1, q.get("req_id", ""), q.get("question", ""), None])


def build_summary_sheet(ws, data, rounds, final_letter, last_row):
    ws.title = SUMMARY_SHEET
    ws.column_dimensions["A"].width = 18
    ws.column_dimensions["B"].width = 40

    final_range = f"'{TC_SHEET}'!{final_letter}2:{final_letter}{last_row}"
    rows = [
        ("Spec 파일", data["spec"]),
        ("작성일", data["created"]),
        ("요구사항 수", len(data["requirements"])),
        ("Test Case 수", len(data["test_cases"])),
        ("실행 회차", rounds),
        ("확인 필요 항목", len(data["questions"])),
        (None, None),
        ("최종 결과", None),
    ]
    rows += [(value, f'=COUNTIF({final_range},"{value}")') for value in RESULT_VALUES]
    rows.append(("미실행", f"=COUNTBLANK({final_range})"))

    for row, (label, value) in enumerate(rows, 1):
        ws.cell(row=row, column=1, value=label).font = Font(bold=True)
        ws.cell(row=row, column=2, value=value).alignment = Alignment(horizontal="left")

    # Pass율 = Pass / (Pass + Fail + Block). N/A와 미실행은 빼고 계산합니다
    pass_row = rows.index(("Pass", f'=COUNTIF({final_range},"Pass")')) + 1
    rate_row = len(rows) + 1
    ws.cell(row=rate_row, column=1, value="Pass율").font = Font(bold=True)
    rate = ws.cell(row=rate_row, column=2, value=f"=IFERROR(B{pass_row}/SUM(B{pass_row}:B{pass_row + 2}),0)")
    rate.number_format = "0.0%"
    rate.alignment = Alignment(horizontal="left")


def main():
    parser = argparse.ArgumentParser(description="testcases.json으로 Test Suite 엑셀을 만듭니다.")
    parser.add_argument("json_path", type=Path, help="testcases.json 경로")
    parser.add_argument("--rounds", type=int, default=1, help="실행 회차 수 (기본 1)")
    parser.add_argument("--out", type=Path, help="저장할 엑셀 경로 (기본: JSON과 같은 폴더)")
    args = parser.parse_args()

    if args.rounds < 1:
        sys.exit("--rounds는 1 이상이어야 합니다.")

    data = load_testcases(args.json_path)

    wb = Workbook()
    summary = wb.active
    build_analysis_sheet(wb, data)
    final_letter, last_row = build_tc_sheet(wb, data, args.rounds)
    build_question_sheet(wb, data)
    build_summary_sheet(summary, data, args.rounds, final_letter, last_row)

    spec_name = Path(data["spec"]).stem
    out = args.out or args.json_path.parent / f"TestSuite_{spec_name}_{date.today():%Y%m%d}.xlsx"
    wb.save(out)

    sys.stdout.reconfigure(encoding="utf-8")
    print(f"Test Suite 생성 완료: {out}")
    print(f"  요구사항 {len(data['requirements'])}개, TC {len(data['test_cases'])}개, {args.rounds}회차")


if __name__ == "__main__":
    main()

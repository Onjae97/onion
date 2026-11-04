"""Test Suite 엑셀의 시트 이름과 열 구성을 한 곳에서 정합니다.

build_suite.py(만들기)와 review_suite.py(검수)가 같이 쓰기 때문에,
열 이름을 바꿀 때는 여기만 고치면 됩니다.
"""

# 테스터가 결과 칸에 고를 수 있는 값
RESULT_VALUES = ["Pass", "Fail", "Block", "N/A"]

# 사유(Remark)를 반드시 적어야 하는 결과
NEEDS_REMARK = ["Fail", "Block"]

SUMMARY_SHEET = "요약"
ANALYSIS_SHEET = "Spec 분석"
TC_SHEET = "Test Case"
QUESTION_SHEET = "확인 필요"

# (열 이름, 열 너비)
TC_BASE_COLUMNS = [
    ("TC ID", 10),
    ("REQ ID", 10),
    ("구분", 11),
    ("우선순위", 9),
    ("제목", 28),
    ("Precondition", 30),
    ("Test Steps", 45),
    ("Expected Result", 40),
]

# 회차마다 반복되는 열. 실제 열 이름은 "1차 결과", "2차 Tester"처럼 됩니다
ROUND_FIELDS = [
    ("결과", 9),
    ("Tester", 10),
    ("실행일", 12),
    ("Remark", 25),
]

RUN_COUNT_COLUMN = "실행 횟수"
FINAL_RESULT_COLUMN = "최종 결과"


def round_header(round_no, field):
    """회차 열 이름을 만듭니다. 예: round_header(2, "결과") -> "2차 결과" """
    return f"{round_no}차 {field}"

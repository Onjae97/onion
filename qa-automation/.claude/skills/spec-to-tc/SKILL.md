---
name: spec-to-tc
description: Spec 문서를 분석해 Precondition / Test Action / Expected Result를 도출하고, Test Case를 작성한 뒤 Test Suite 엑셀까지 만든다. 사용자가 Spec을 주며 TC 작성, 테스트 케이스 생성, Test Suite 제작을 요청할 때 사용.
argument-hint: <spec 파일 경로>
---

# Spec → Test Case → Test Suite

이 스킬은 `qa-automation` 프로젝트의 1~3단계를 수행한다.
아래의 모든 경로는 `qa-automation` 폴더(이 SKILL.md에서 세 단계 위) 기준이다.

## 0. Spec 찾기

- 인자로 받은 경로: `$ARGUMENTS`
- 인자가 없으면 `specs/` 폴더의 파일 목록을 보여주고 어떤 파일을 분석할지 물어본다.

## 1. Spec 읽기

형식에 따라 읽는 방법이 다르다.

| 형식 | 읽는 방법 |
| --- | --- |
| `.txt` `.md` `.pdf` 이미지 | Read 도구로 직접 읽는다 |
| `.docx` `.xlsx` `.xls` | `python scripts/read_spec.py <파일>` 출력 결과를 읽는다 |
| 그 외 | 사용자에게 텍스트나 PDF로 변환해 달라고 요청한다 |

## 2. Spec 분석 (1단계)

Spec을 **테스트 가능한 요구사항 단위**로 나누고 `REQ-001`부터 번호를 붙인다.
각 요구사항마다 다음을 도출한다.

- **preconditions**: 테스트 전에 갖춰져야 하는 상태 (계정, 데이터, 화면, 설정 등)
- **actions**: 사용자 또는 시스템이 하는 동작
- **expected**: 관찰 가능한 결과 (화면 표시, 메시지 문구, 데이터 변화)

규칙:
- Spec에 **없는 내용을 지어내지 않는다.** 애매하거나 빠진 부분은 `questions`에 적는다.
  (예: 오류 메시지 문구가 없음, 최대 길이가 정의되지 않음)
- 메시지 문구, 숫자, 제한값은 Spec의 표현을 그대로 옮긴다.

## 3. Test Case 작성 (2단계)

요구사항마다 다음을 작성한다.

- 정상 동작을 확인하는 **Positive** TC 최소 1개
- 입력 제한·권한·오류 처리가 있으면 **Negative** TC
- 숫자나 길이 제한이 있으면 경계값(최솟값, 최댓값, 한 칸 넘는 값)을 확인하는 **Boundary** TC

TC 작성 규칙:
- TC 하나는 **한 가지만** 확인한다.
- `steps`는 테스터가 그대로 따라 할 수 있게 구체적으로 쓴다 (어느 버튼, 어떤 값).
- `expected`는 Pass/Fail을 판단할 수 있게 쓴다 ("정상 동작한다" 같은 표현 금지).
- `priority`: 핵심 기능 = High, 일반 = Medium, 사소한 표시 등 = Low

## 4. JSON으로 저장

`output/<spec 파일 이름(확장자 제외)>/testcases.json`에 아래 형식으로 저장한다.

```json
{
  "spec": "login_spec.md",
  "created": "2026-11-03",
  "requirements": [
    {
      "id": "REQ-001",
      "summary": "요구사항 한 줄 요약",
      "preconditions": ["..."],
      "actions": ["..."],
      "expected": ["..."],
      "notes": "Spec의 위치나 참고 사항 (없으면 빈 문자열)"
    }
  ],
  "test_cases": [
    {
      "id": "TC-001",
      "req_id": "REQ-001",
      "type": "Positive",
      "priority": "High",
      "title": "TC 제목",
      "precondition": "사전 조건",
      "steps": ["첫 번째 동작", "두 번째 동작"],
      "expected": "기대 결과"
    }
  ],
  "questions": [
    { "req_id": "REQ-002", "question": "Spec에서 확인이 필요한 내용" }
  ]
}
```

- `type`은 `Positive`, `Negative`, `Boundary` 중 하나다.
- `created`는 오늘 날짜다.

## 5. Test Suite 엑셀 만들기 (3단계)

```bash
python scripts/build_suite.py output/<이름>/testcases.json --rounds 2
```

- `--rounds`는 실행 회차 수다. 사용자가 말하지 않았으면 기본값(1)을 쓴다.
- 오류가 나면 메시지대로 JSON을 고치고 다시 실행한다.

## 6. 보고

사용자에게 다음을 알려준다.

- 요구사항 수, TC 수 (Positive / Negative / Boundary 각각)
- 만들어진 엑셀 파일 경로
- `questions`에 적은 확인 필요 항목 (이 항목들은 엑셀의 `확인 필요` 시트에도 들어간다)
- 다음 단계: 테스터가 엑셀을 채운 뒤 `python scripts/review_suite.py <엑셀 파일>`로 검수 리포트를 만든다

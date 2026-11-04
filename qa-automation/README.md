# qa-automation

Spec 문서에서 Test Case를 뽑고, 테스터가 채울 Test Suite 엑셀을 만들고, 채워진 결과를 검수하는 연습용 자동화입니다.

```
Spec 파일 ──/spec-to-tc──▶ testcases.json ──build_suite.py──▶ Test Suite.xlsx
                (1~2단계, Claude)            (3단계)              │ 테스터가 결과 입력
                                                                  ▼
                                   검수리포트.xlsx ◀──review_suite.py── (4단계)
```

| 단계 | 하는 일 | 담당 |
| --- | --- | --- |
| 1. Spec 분석 | 요구사항별 Precondition / Test Action / Expected Result 도출 | Claude Code 스킬 `/spec-to-tc` |
| 2. Test Case 제작 | Positive / Negative / Boundary TC 작성 | Claude Code 스킬 `/spec-to-tc` |
| 3. Test Suite 작성 | 회차별 결과·Tester·실행일·Remark 칸이 있는 엑셀 생성 | `scripts/build_suite.py` |
| 4. Test Case 검수 | 누락 항목, Fail/Block 목록, Pass율 리포트 생성 | `scripts/review_suite.py` |

## 준비 (처음 한 번만)

```bash
pip install -r requirements.txt
```

## 사용법

### 1~3단계: Spec → Test Suite

1. Spec 파일을 `specs/` 폴더에 넣습니다. (.md, .txt, .pdf, .docx, .xlsx, 이미지 가능)
2. Claude Code에서 스킬을 실행합니다.

   ```
   /spec-to-tc specs/내_spec.docx
   ```

   "2회차로 만들어줘"처럼 회차 수를 같이 말해도 됩니다.
3. `output/<spec 이름>/` 폴더에 `testcases.json`과 `TestSuite_<spec 이름>_<날짜>.xlsx`가 생깁니다.

JSON을 직접 고친 뒤 엑셀만 다시 만들고 싶으면:

```bash
python scripts/build_suite.py output/내_spec/testcases.json --rounds 2
```

### 테스터 작업

Test Suite 엑셀의 `Test Case` 시트에서 회차별로 결과(목록에서 선택), Tester, 실행일, Remark를 채웁니다.
`실행 횟수`와 `최종 결과`, `요약` 시트의 집계는 자동으로 계산됩니다.

| 시트 | 내용 |
| --- | --- |
| 요약 | Spec 정보, 최종 결과 집계, Pass율 |
| Spec 분석 | 요구사항별 Precondition / Test Action / Expected Result |
| Test Case | TC 목록 + 회차별 결과 입력 칸 |
| 확인 필요 | Spec에서 애매하거나 빠진 부분 (기획자에게 확인할 것) |

### 4단계: 검수

```bash
python scripts/review_suite.py output/내_spec/TestSuite_내_spec_20261103.xlsx
```

같은 폴더에 `..._검수리포트_<시각>.xlsx`가 생기고, 화면에도 요약이 나옵니다.

- **요약**: 회차별 / 최종 결과 집계, Pass율, 판정 (검수 완료 / 보완 필요)
- **확인 필요 항목**: 미실행, Tester 누락, Fail/Block인데 사유 없음, 잘못된 결과 값
- **Fail·Block 목록**: 최종 결과가 Fail/Block인 TC와 사유

## 자동 분석 (specs/auto 폴더)

`specs/auto` 폴더에 넣은 Spec만 자동으로 분석합니다. `specs/`에 바로 넣은 파일은 건드리지 않습니다.

```bash
python scripts/watch_specs.py
```

이 창을 켜 둔 동안 10초마다 폴더를 확인합니다. 끝내려면 Ctrl+C를 누르세요.

- 새 파일이 들어오면 `/spec-to-tc`를 실행해 `output/<spec 이름>/`에 엑셀을 만들고, Windows 알림으로 알려줍니다.
- 분석한 파일은 다시 분석하지 않습니다. 내용을 고쳐 저장하면 다시 분석합니다.
- 실패한 파일도 내용이 바뀌기 전에는 다시 시도하지 않습니다.
- 회차는 항상 1회차이고, 애매한 내용은 `확인 필요` 시트에 적힙니다 (중간에 질문하지 않음).
- 기록은 `output/watch.log`, 처리 목록은 `output/watch_state.json`에 남습니다.

**주의:** 폴더에 넣는 순간 확인 없이 내용이 Claude로 전송되고 사용량이 듭니다. 자동 분석해도 되는 파일만 넣으세요.

허용된 도구는 `watch_specs.py`의 `ALLOWED_TOOLS`에 있습니다 (프로젝트 읽기, `output/` 쓰기, 스크립트 2개 실행). 그 외의 동작은 거부됩니다.

## 샘플로 먼저 해보기

`samples/login_spec.md`(가상의 로그인 기능 Spec)로 전체 흐름을 연습할 수 있습니다.

```
/spec-to-tc samples/login_spec.md
```

## 주의

`specs/`와 `output/` 폴더의 파일은 GitHub에 올라가지 않습니다 (`.gitignore`).
회사 Spec이 공개 레포에 올라가지 않도록 실제 문서는 꼭 이 두 폴더에만 두세요.

## 배운 것

- Claude Code 스킬(`.claude/skills/<이름>/SKILL.md`)로 AI 작업 절차 정의하기
- `openpyxl`로 엑셀 서식, 드롭다운(데이터 유효성 검사), 조건부 서식, 수식 넣기
- 두 스크립트가 같은 열 이름을 쓰도록 설정을 한 파일(`suite_format.py`)에 모으기

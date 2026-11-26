# CL6 추적성 — 항목 1개 · Tracker별 탭 (v1.1)

`CL6_Traceability`(전체 Gap Matrix)는 그대로 두고, **CI 하나만 골라** 최상위 Tracker와 하위 Tracker를 검사한 뒤
**Tracker마다 탭으로** 미추적 Item을 보여주는 도구입니다. 하위 Tracker가 많은 CI(예: SYS5_05, Tracker 11개)를 볼 때 씁니다.

## 동작
1. Confluence에서 최신 CI list를 받음 (CL6와 동일)
2. **검사할 CI를 고름** — 목록에서 번호 입력, 또는 CI ID 입력 (일부만 입력하면 검색 → 여러 개면 번호로 고르기)
3. CI list에 적힌 Tracker의 **최상위 Tracker로 올라가서** 그 아래 하위 Tracker까지 검사 (CL6 `scope`와 동일)
4. 결과 엑셀: `output\추적성_Tracker별_프로젝트_CI ID_날짜_시각.xlsx`

## 판정 규칙
`..\CL6_Traceability\traceability.py`를 **그대로 불러서** 판정합니다. 이 도구에는 규칙이 따로 없어서,
같은 CI라면 CL6 전체 검사의 분모·미추적 숫자와 항상 같습니다. CL6 규칙을 고치면 이 도구에도 자동 반영됩니다.

## 준비
- 이 폴더를 **CL6_Traceability 폴더 옆에** 둡니다 (`CA-automation\CL6_Traceability`, `CA-automation\CL6_Traceability_ByTracker`).
- 설정은 이 폴더에 `config.json`이 없으면 **CL6_Traceability의 config.json을 그대로** 씁니다.
- 패키지·자동 로그인(set_login)도 CL6와 공유합니다. 처음 실행 때 브라우저 창이 새로 뜨는데, 저장된 ID/PW가 있으면 자동 로그인됩니다.

## 실행
- `run_bytracker.bat` 더블클릭 → 목록에서 CI 선택
- 바로 지정: `run_bytracker.bat --ci SYS5_05`

## 결과 엑셀
| 탭 | 내용 |
|---|---|
| Overview | 위: CI 요약(분모·미추적·커버리지·검사 범위) / 아래: Tracker별 요약 — `Sheet` 열을 누르면 해당 Tracker 탭으로 이동, 맨 아래 합계 |
| 01 …, 02 … | Tracker마다 1개 (트리 순서). 미추적 Item: CI ID / CI name / Author / Tracker / Item ID(링크) / 유형 / 비고(Type 미지정, Folder/Information에만 연결). 없으면 `미추적 Item 없음` |
| 검수 | '연결됨' 판정 표본 10건 |
| 확인불가 | 조회 실패·상대 확인 불가 Item (어느 Tracker인지 표시) |
| 실행정보 | CI list 파일, 검사 CI, 범위, 판정 규칙 |

변동 비교는 하지 않습니다 (CL6 전체 검사의 비교 기준도 건드리지 않음).

## 시험
`xvfb-run python test/run_bytracker.py` — CL6 가짜 서버로 선택·범위·탭 분리, CL6 결과와 숫자 일치를 확인합니다.

## 진행률 표시
오래 걸리는 조회(연결 조회, 연결 상대 유형 확인)는 아래처럼 진행률을 한 줄로 보여 줍니다 (CL6 traceability.py v1.9 기능).
```
   연결 조회 [=============>                ]  46% (690/1500) · 경과 1분 12초 · 남은 시간 약 1분 25초
```

# CL3 점검 — Status · Verification Review · Defect 해결 (v1.0)

체크리스트 **CL3** 자동화. CI list의 CI마다 세 가지를 확인합니다.

| 확인 | 내용 | NOK |
|---|---|---|
| ① Status | Type이 **Information·Folder가 아닌 모든 Item**(Type `--` 포함)의 Status가 **Accepted**인가 — 상위 + 하위 Tracker 전부 | Accepted가 아닌 Item 1개 이상 |
| ② VR 수행 | 같은 프로젝트에 **`Review_<상위 Tracker 이름>`** Tracker가 있고 Review Item이 있는가 | Review Tracker 없음 |
| ③ Defect 해결 (잠정 기준) | Review Item에 연결된 Codebeamer Defect · Jira 이슈 · 첨부 Defect List가 모두 해결되었는가 | 미해결 Defect 1건 이상 |

CL1·CL2·CL6과는 **별개 도구**입니다. 설정·로그인 세션·결과 파일도 따로 둡니다.

## 처음 한 번만
1. `config.json`은 CL2와 같은 Confluence·Codebeamer 값에 `jira.base`를 더한 것 (이미 만들어 둠)
2. `setup.bat` → `doctor.bat`
   - 다른 CL 도구에 저장한 ID/PW를 그대로 씁니다. Jira 값이 없으면 Confluence ID/PW로 로그인 시도
   - `doctor.bat`은 앞 2개 CI의 Review Tracker·Defect를 보여 주고 Review Item 원본을 `state\debug`에 저장

## 매번
- `run_cl3.bat` 더블클릭 → 검사 방식 선택 (Enter: **전체 검사** / `q`: **빠른 검사**)
  - 전체 검사 `output\CL3_Status_VR_프로젝트_날짜_시각.xlsx` — CA 근거용
  - 빠른 검사 `…_quick.xlsx` — ①을 CI list에 적힌 Tracker만 (하위 Tracker가 큰 CI에서 빠름, 참고용). ②③은 같음
- 일부 CI만: `run_cl3.bat --ci CI_ID1 --ci CI_ID2` · 빠른 검사 바로: `run_cl3.bat --quick`

## 판정 방법
- **① Status** (사용자 확정 2026-11-24)
  - 범위: CL6와 같음 — 등록 Tracker의 최상위 Tracker와 그 아래 하위 Tracker 전부
  - Type이 Information·Folder인 Item 제외(오타·한글 `정보`도 CL6와 같게 인식). Type `--`(미지정)은 **포함**하고 따로 표시
  - Status `Accepted` = OK, 그 밖의 모든 Status = **NOK**
  - `Obsolete`·`Rejected`·`Deleted` = NOK 목록에서 빼고 **개수만** 표시 ('별도 Status' 탭, Overview '별도 Status 수')
- **② VR 수행** (사용자 확정 2026-11-24)
  - 상위 Tracker 이름 기준으로 `Review_` + 이름의 Tracker를 프로젝트 트리에서 찾음. 이름 유사도 90% 이상 OK, 80~90% Conditional OK, 없으면 NOK
  - 비슷한 이름의 **다른 산출물 Review**에 걸리지 않도록, Review Tracker가 더 비슷한 다른 Tracker의 것이면 후보에서 뺌
  - Review Tracker는 있는데 Review Item이 0건 → **수동 확인** (엑셀 결과서 첨부·다른 링크로 관리되는 경우)
  - Review Item의 Status는 판정에 쓰지 않고 참고로 표시
- **③ Defect 해결** (잠정 — 추후 기준 확정)

| 근거 | 판정 |
|---|---|
| Review Item에 연결된 Codebeamer Item 중 Tracker·유형 이름에 Defect·Bug·Issue·결함 등이 든 것 | Status가 Closed·Resolved·Done 등이면 해결 |
| Review Item 안의 Jira 이슈 주소 (`…/browse/KEY-123`) | Jira 완료 분류(Done) 또는 Resolution 있음 → 해결 |
| 첨부 엑셀(Defect List)에서 `Status`·`상태` 열 | 값으로 해결/보류/미해결 (DRM 파일은 PC 엑셀로 읽기 전용) |
| 미해결 1건 이상 | **NOK** |
| 조회 실패 (Jira 로그인 등) | 확인불가 |
| 보류(Deferred·Postponed·보류 등)만 남음 | Conditional OK — 이관·승인 근거 확인 |
| 근거가 하나도 없음 | Conditional OK — Defect 0건인지 기록 누락인지 확인 |
| 첨부를 읽지 못함 (PDF 등) | 수동 확인 |

  - 해결·보류 Status 이름, Defect로 볼 Tracker 이름은 `config.json` → `cl3.defect`에서 바꿀 수 있음
- **종합**: ①②③ 중 가장 나쁜 결과 (NOK > 확인불가 > Conditional OK·수동 확인 > OK). 앞 단계 때문에 판정하지 않으면 `-`

## 결과 엑셀
| 탭 | 내용 |
|---|---|
| 요약 | 종합·①②③별 결과 수, Status NOK Item·별도 Status·미해결 Defect 합계 |
| Overview | CI별 ①②③ 결과·근거, 검사 범위(상위 Tracker 링크), Status 분포, Review Tracker 링크·Review Item 수·Status(참고), Defect 수 |
| Status NOK | Accepted가 아닌 Item 목록 (Item 링크, Type, Status, Type `--` 표시) |
| 별도 Status | Obsolete·Rejected·Deleted 개수 |
| Defect | **근거** — Review Item별로 찾은 Defect(출처·링크·Status·판정), 수동 확인 첨부 |
| 확인 필요 | Conditional OK · 확인 필요 · 확인불가 · 수동 확인 — 사람이 확인 후 마지막 열 기입 |
| Tracker별 | Tracker마다 전체·제외·대상·Accepted·NOK·별도·Type `--` 수 |
| 조회 기록 · 실행정보 | 범위·찾은 Review Tracker·Defect 요약 / 실행 시각, 검사 방식, 판정 규칙 전문 |

## 원칙
- 읽기 전용(GET) · 조회 실패 = **확인불가** · 결과는 항상 새 파일 · 공식 산출물 반영은 담당자가 직접

## 문제가 생기면
| 증상 | 조치 |
|---|---|
| ② Review Tracker를 못 찾음 / 엉뚱한 것을 찾음 | Overview '② 근거'의 '가장 비슷한 Review Tracker' 확인 → 이름 규칙이 다르면 Claude에게 알려 주기 |
| ③ Defect가 안 잡힘 | OK가 아닌 CI는 `state\debug\<CI ID>_review_*.json`이 자동 저장됨 → Claude에게 CI ID 알려 주기 |
| Jira 로그인 실패 | Jira ID/PW가 다르면 `set_login.bat`에서 Jira만 다르게 저장 |
| 그 밖의 문제 | `../CL1_Repo_baseline/README.md`의 '문제가 생기면' 표와 같음 (로그인·DRM·브라우저) |

## 파일 구성
- `cl3_check.py` 본체 · `config.json` 설정 · `SKILL.md` AI 에이전트용 규칙
- `state\` 로그인 세션·CI list 사본·첨부 사본·debug (**공유 금지**) · `output\` 결과
- `test\` 가짜 서버 시험: `xvfb-run python test/run_e2e.py` (Windows는 `python test\run_e2e.py`)

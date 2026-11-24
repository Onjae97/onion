# CL2 점검 — Revision history 관리 · Version Rule (v1.1)

체크리스트 **CL2** 자동화. CI list의 CI마다 세 가지를 확인합니다.

| 확인 | 내용 | NOK |
|---|---|---|
| ① 존재·관리 | Tracker에 **Revision history** Item이 있고, 그 안의 표에 기록이 있는가 | Item 없음 / 표 없음 / 기록 0행 |
| ② 필수 항목 | **Version · Date · Description · Author · Approver** 칸이 모두 채워져 있는가 | 열 없음 / 빈칸 |
| ③ Version Rule | 6.2.2절 **vX.Yz** 규칙대로 버전이 관리되는가 | 형식 위반 / 중복·역행·건너뜀 등 (아래 표) |

CL1(`../CL1_Repo_baseline`)·CL6(`../CL6_Traceability`)과는 **별개 도구**입니다. 설정·로그인 세션·결과 파일도 따로 둡니다.

## 처음 한 번만
1. `config.json`은 CL1과 같은 Confluence·Codebeamer 값을 씁니다 (이미 만들어 둠). 새 프로젝트면 `config.example.json`을 복사해 수정
2. `setup.bat` → `doctor.bat`
   - CL1·추적성 도구에서 `set_login.bat`으로 저장한 ID/PW를 그대로 씁니다
   - `doctor.bat`은 앞의 Tracker CI 3개에서 Revision history를 찾아 **읽은 행을 화면에 보여 줍니다** → Codebeamer 화면의 표와 같은지 확인

## 매번
- `run_cl2.bat` 더블클릭 → `output\CL2_RevisionHistory_프로젝트_날짜_시각.xlsx`
- 일부 CI만: `run_cl2.bat --ci CI_ID1 --ci CI_ID2`
- Revision history Item을 못 찾을 때: `run_cl2.bat --ci CI_ID --item Item번호` (Item 주소 `/cb/issue/번호`)

## 판정 방법
- **대상 CI**: 최신 CI list에서 PBL 값이 있는 CI 전부 (CL1과 같음)
- **① Revision history 찾기**
  - Codebeamer Tracker: Tracker의 Item 중 이름에 `Revision history`(`config.json` → `cl2.item_name_keywords`)가 든 Item. 이름이 정확히 같은 것 우선
  - 이름에 template·템플릿·양식이 든 Item(양식 이력)은 뒤로 — 문서 이력이 없을 때만 쓰고, 그 경우 ①은 최대 Conditional OK
  - CI list 경로가 `/cb/category/번호`(Category)여도 Tracker와 같이 읽음
  - 등록 Tracker에 없으면 **상위 Tracker**에서 찾음 (CL1·CL6와 같은 상위 기준, `cl2.search_upper_trackers`로 끄기 가능) — 결과에 `상위 Tracker '이름'(번호)`로 표시
  - 표 읽기: Item 본문(Wiki/HTML) → 없으면 Item 화면. Version 열이 있는 표를 고름
  - Confluence 페이지는 본문 표 (없으면 '확인 필요' — 첨부 문서 안에 있을 수 있음), SVN·Git 등은 **수동 확인**
- **② 필수 항목**: 5개 열이 모두 있고, 기록된 모든 행에서 5칸이 비어 있지 않아야 OK. 완전히 빈 행(양식 여백)은 무시
  - 이름은 국문·영문 무관. `Author (Approver)` 한 열도 인정(괄호 안 = 승인자, 괄호가 없으면 Approver 빈칸)
- **③ Version Rule** (정량 규칙, 사용자 확정 2026-11-24)

| 경우 | 판정 |
|---|---|
| 형식이 `vX.Y` 또는 `vX.Yz`(z = 소문자 a, b … z, aa …) | OK |
| `v` 없음(`1.0`) · 대문자 `V` | **Conditional OK** |
| 그 밖의 형식 (`Rev1`, `1.0.1`, `v1.0A` 등) | NOK |
| 최초 버전이 v1.0(또는 v1.0a)이 아님 | NOK |
| 공식 vX.Y 다음 → vX.(Y+1) 또는 vX.(Y+1)a / v(X+1).0 또는 v(X+1).0a | OK |
| Draft vX.Yz 다음 → vX.Y(z+1) 또는 vX.Y(공식 확정) | OK |
| 중복 · 역행 · Major/Minor/Suffix **건너뜀** · 공식 후 같은 버전 Draft · Major 증가 시 Minor ≠ 0 · Minor 증가 시 Suffix가 a가 아님 · Draft를 확정하지 않고 다음 버전 | NOK |
| Date가 `YYYY-MM-DD` 형식이 아님 · 날짜 역행 | Conditional OK |

  - 표가 최신이 위(내림차순)여도 자동으로 인식합니다 (첫·끝 행 날짜 기준)
  - 변경 내용이 Major감인지 Minor감인지(요구사항 변경 → Major 등)는 **판정하지 않습니다** — 사람 확인
- **종합**: ①②③ 중 가장 나쁜 결과 (NOK > 확인불가 > Conditional OK > OK). ①에서 못 찾으면 ②③은 `-`

## 결과 엑셀
| 탭 | 내용 |
|---|---|
| 요약 | 종합·①②③별 OK / Conditional OK / NOK / 확인 필요 / 확인불가 / 수동 확인 수 |
| Overview | CI별 결과, Revision history 위치(링크), 기록 행 수, 최신 Version·Date, 정렬, ①②③ 근거 |
| NOK | NOK 항목과 사유 |
| 확인 필요 | Conditional OK · 확인 필요 · 확인불가 · 수동 확인 — 사람이 확인 후 마지막 열 기입 |
| Revision history | **근거** — CI별로 읽은 표 그대로(행마다 판정·지적, 빈칸은 빨간색) |
| 조회 기록 | 어느 Tracker에서 Item을 몇 개 보고 무엇을 찾았는지, 본문/화면 중 어디서 표를 읽었는지 |
| 실행정보 | 실행 시각, CI list 파일, 판정 규칙 전문 |

## 원칙
- 읽기 전용(GET). Codebeamer·Confluence를 바꾸지 않음
- 조회 실패 = **확인불가** (OK/NOK로 넘기지 않음)
- 결과는 항상 새 파일. 공식 산출물 반영은 담당자가 검토 후 직접

## 문제가 생기면
| 증상 | 조치 |
|---|---|
| Revision history가 있는데 ① NOK(Item 없음) | 조회 기록 탭에서 찾은 Item 이름 확인 → Item 이름이 다르면 `cl2.item_name_keywords`에 추가, 급하면 `--item` |
| ① NOK(표 없음)인데 화면엔 표가 있음 | OK가 아닌 CI는 `state\debug\<CI ID>_rh_item_*` 파일이 자동 저장됨 → Claude에게 CI ID만 알려 주기 |
| 칸이 밀려 읽힘 | 위와 같음 (표 형식 확인 필요) |
| 그 밖의 문제 | `../CL1_Repo_baseline/README.md`의 '문제가 생기면' 표와 같음 (로그인·DRM·브라우저) |

## 파일 구성
- `cl2_check.py` 본체 · `config.json` 설정 · `SKILL.md` AI 에이전트용 규칙
- `state\` 로그인 세션·CI list 사본·doctor 저장 파일 (**공유 금지**) · `output\` 결과
- `test\` 가짜 서버 시험: `xvfb-run python test/run_e2e.py` (Windows는 `python test\run_e2e.py`)

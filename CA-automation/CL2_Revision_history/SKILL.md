---
name: cl2-revision-history
description: CI list의 CI마다 Codebeamer Tracker의 Revision history가 있고, 5개 항목(Version·Date·Description·Author·Approver)이 채워져 있고, Version Rule(vX.Yz)을 지키는지 점검해 CL2 결과 엑셀을 만든다. CA 체크리스트 CL2, Revision history·버전 관리 확인 요청 시 사용.
version: 1.1
---

# CL2 점검 — Revision history 관리 · Version Rule

AI 에이전트(Claude·Codex 등)가 이 도구를 실행·수정할 때 따르는 규칙이다.
CL1(`../CL1_Repo_baseline`)·CL6(`../CL6_Traceability`)과 **별개로 관리**한다 — 코드·설정·state를 공유하지 않는다 (로그인 자격 증명만 CL1·AUTO-001 저장값을 대체로 읽음).

## 판정 규칙 (사용자 확정 2026-11-24)
1. CI list = Confluence CI List 페이지 첨부 중 **가장 최근 업로드된 엑셀**, 대상 = **PBL이 비어 있지 않은 CI 전부**. Category 빈칸은 위 행 값.
2. **① 존재·관리**: Revision history는 **Tracker 안의 Item 하나**(사용자 확인). 해당 Tracker에 Revision history가 없거나 관리되지 않으면 **NOK**.
   - Item 찾기: 이름에 `cl2.item_name_keywords`(기본 Revision history 등)가 든 Item, 이름이 정확히 같은 것 우선. 여럿이면 첫 번째 + 나머지 근거 기록.
   - **문서 이력 우선, 없으면 템플릿 이력** (사용자 결정 2026-11-24): 이름에 template·템플릿·양식이 든 Item은 뒤로. 상위 Tracker까지 문서 이력이 없으면 템플릿 이력으로 판정하되 ①은 최대 **Conditional OK**. 실제 사례: SYS4_03 'Revision history of the template'.
   - 경로가 `/cb/category/번호`(Codebeamer Category, CMDB)여도 Tracker와 같이 읽는다 (실측 SWE6_03 — v1.0은 Tracker 아닌 화면으로 보고 '확인 필요'였음).
   - 등록 Tracker에 없으면 상위 Tracker까지 찾는다 (CL1·CL6와 같은 상위 기준, `search_upper_trackers`). — Claude 제안, 사용자 실사용 확인 대기
   - 표 = Item 본문(Wiki/HTML) → 없으면 Item 화면(`/cb/issue/{id}`). 앞 3행 안에 Version 열이 있는 헤더 행이 있는 표 중 필수 열이 가장 많은 것.
   - 실측(2026-11-24): 본문은 Wiki `[{Table}]` 플러그인 표 — 셀마다 한 줄 `|(스타일)값`, 행은 빈 줄 구분, `~-` 이스케이프, `%%(css)글자%!` 스타일. HTML 표는 병합 셀(rowspan·colspan)을 펼쳐 읽는다.
   - NOK = Item 없음 / Version 열 있는 표 없음 / 기록 0행. 조회 실패 = 확인불가.
   - Confluence 페이지 = 본문 표(없으면 확인 필요), Codebeamer 기타 화면 = 화면 표(없으면 확인 필요), SVN·Git 등 = 수동 확인, 경로 없음 = NOK.
3. **② 필수 항목**: Version·Date·Description·Author·Approver 열이 모두 있고, 기록 행마다 5칸이 비어 있지 않다. 열 없음·빈칸(공백만 포함) = **NOK**. 완전히 빈 행은 양식 여백으로 보고 무시.
   - 이름은 국문·영문 무관, 적혀 있으면 OK (사용자 결정 2026-11-24 — 제품/프로젝트 형상 항목별 언어 규칙은 확인 안 함).
   - `Author (Approver)` 한 열도 인정 (사용자 결정 2026-11-24, HWE4_03): `작성자 (승인자)`로 나눠 읽고, 괄호 부분이 없으면 Approver 빈칸.
   - Approver 대신 Reviewer 열 = 지금은 열 없음(NOK). 사용자가 해당 문서 확인 후 수정 예정 (SYS4_03).
4. **③ Version Rule (6.2.2, vX.Yz)** — 정량화:
   - 형식 `^v\d+\.\d+[a-z]*$`. **`v` 누락·대문자 V = Conditional OK** (사용자 결정 2026-11-24). 그 외 형식 = NOK.
   - 최초 버전 = v1.0 또는 v1.0a (Major는 1부터). 아니면 NOK.
   - 공식 vX.Y 다음: vX.(Y+1) · vX.(Y+1)a · v(X+1).0 · v(X+1).0a 만 허용.
   - Draft vX.Yz 다음: vX.Y(z+1) · vX.Y(공식 확정)만 허용. z 다음은 aa (Suffix 확장 규칙).
   - **건너뜀은 NOK** (사용자 결정 2026-11-24): v1.0→v1.2, v1.0→v3.0, v1.0a→v1.0c 모두 NOK. 중복·역행·공식 후 같은 버전 Draft·Major 증가 시 Minor≠0·Minor 증가 시 Suffix≠a·Draft 미확정 상태로 다음 버전 = NOK.
   - Date 작성 규칙 `YYYY-MM-DD`가 아니면 **Conditional OK** (사용자 결정 2026-11-24). 날짜 역행도 Conditional OK (Claude 제안). 정렬 판단용으로는 YYYY.MM.DD 등도 날짜로 읽는다.
   - 정렬 방향은 자동 인식: 첫·끝 행 날짜가 다르면 날짜로, 같으면 버전으로.
   - **표 안에서만 판정**한다 — CI list·Baseline 버전과 맞추지 않는다 (사용자 결정 2026-11-24).
   - 변경 사유가 Major/Minor 기준(요구사항·인터페이스·Safety·Test·추적성 변경 = Major 등)에 맞는지는 판정하지 않는다 → 사람 확인.
5. **종합** = ①②③ 중 가장 나쁜 결과 (NOK > 확인불가 > Conditional OK > OK). ①에서 표를 못 얻으면 ②③은 `-`.

## 원칙
- **조회 실패 = 확인불가.** OK/NOK로 넘기지 않는다.
- **읽기 전용(GET).** **결과는 새 파일.** 공식 반영·서명은 사람이.
- AI는 ASPICE 등급(N/P/L/F)을 판정하지 않는다 — 이 도구는 CI 단위 OK/NOK 근거만 만든다.
- 결과에 근거를 남긴다: Revision history 탭(읽은 표 원본 + 행별 지적), 조회 기록 탭(어디서 찾았는지).
- 비밀번호는 Windows 자격 증명 관리자(`AUTO-CL2 revision-history`, 없으면 `AUTO-CL1 ci-baseline` → `AUTO-001 traceability`)에만. AI는 비밀번호를 묻거나 받지 않는다.
- 코드를 고치면 `test/run_e2e.py`(가짜 서버, 리눅스 `xvfb-run`) 통과 후 반영. 규칙을 바꾸면 이 파일과 README를 함께 고친다.

## 미결정
- SYS1_03처럼 첫 행 Version이 `Draft`인 경우 — 문서에는 'v1.0부터 시작'만 있고 Draft 표기 규정 없음. 사용자가 작성자와 협의 후 알려 주기로 함 (현재 NOK).

## 실측 (2026-11-24 첫 실행)
- `/api/v3/trackers/{id}/items` · `/api/v3/items/{id}` 정상. 본문 `descriptionFormat: Wiki`, 표는 `[{Table}]` 플러그인.
- OK가 아닌 CI는 일반 실행에서도 `state/debug/<CI ID>_rh_item_*.json·html`을 남긴다 → 원인 확인용.

## 실행
- 점검 `doctor.bat` · 전체 `run_cl2.bat` · 일부 `--ci <CI ID>` / `--limit N` · Item 직접 지정 `--ci <CI ID> --item <번호>`

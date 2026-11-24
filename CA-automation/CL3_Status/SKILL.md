---
name: cl3-status-review
description: CI list의 CI마다 Codebeamer Item Status(Accepted), Verification Review 수행(Review_ Tracker), VR Defect 해결 여부를 점검해 CL3 결과 엑셀을 만든다. CA 체크리스트 CL3, Status·VR·Defect 확인 요청 시 사용.
version: 1.0
---

# CL3 점검 — Status · Verification Review · Defect 해결

AI 에이전트(Claude·Codex 등)가 이 도구를 실행·수정할 때 따르는 규칙이다.
CL1·CL2·CL6과 **별개로 관리**한다 — 코드·설정·state를 공유하지 않는다 (로그인 자격 증명만 다른 CL 저장값을 대체로 읽음). Item 조회·Type 판단·Tracker 범위 코드는 CL6에서 복사.

## 판정 규칙
1. CI list = Confluence CI List 페이지 첨부 중 **가장 최근 업로드된 엑셀**, 대상 = **PBL이 비어 있지 않은 CI 전부**.
2. **① Status** (사용자 확정 2026-11-24)
   - 범위 = **상위 + 하위 Tracker 전부** (CL6 `top_with_descendants`). **빠른 검사 `--quick`** = CI list에 적힌 Tracker만 (참고용, 파일명 `_quick`). 실행 시 선택 가능 (CL6와 같은 방식).
   - 제외 = Type Information·Folder (CL6 `is_excluded`: 오타·한글 `정보` 포함). **Type `--` 포함**, 따로 집계.
   - Status `Accepted`(config `accepted_statuses`) = OK, **나머지 모두 NOK**.
   - `Obsolete`·`Rejected`·`Deleted`(config `separate_statuses`) = **NOK에서 빼고 개수만 표시** — 사용자 "따로 갯수만 표시" 해석 (Claude, 확인 대기).
3. **② VR 수행** (사용자 확정 2026-11-24)
   - **상위 Tracker 이름** 기준 `Review_<이름>` Tracker를 프로젝트 트리에서 찾음 (빠른 검사여도 상위 기준). 유사도 ≥90% OK · 80~90% Conditional OK · 그 미만 NOK.
   - 오매칭 방지: Review Tracker 이름(접두어 제외)이 다른 일반 Tracker와 더 비슷하면 그 Tracker의 Review로 보고 후보에서 뺌 (Claude 제안 — CL1 실측: 다른 산출물끼리 90% 유사).
   - Review Item 0건 = **수동 확인** (엑셀 결과서 첨부·다른 링크로 관리 — 사용자 확인).
   - Review Item Status는 **판정에 쓰지 않고** 참고 표시.
4. **③ Defect 해결** — **잠정** (사용자: "제안대로 먼저, 기준은 추후 확정" 2026-11-24)
   - 근거 3종: Review Item **연결 Item 중 Defect**(Tracker·유형 이름에 `defect_tracker_keywords`) / Review Item 안의 **Jira 주소**(`/browse/KEY-1`) / **첨부 엑셀 Defect List**(`Status`·`상태` 열).
   - 미해결 ≥1 NOK · 조회 실패 확인불가 · 보류만 Conditional OK · 모두 해결 OK · 근거 없음 Conditional OK(0건 확인) · 첨부 못 읽음 수동 확인.
   - Jira 해결 = statusCategory `done` 또는 resolution 있음.
5. **종합** = ①②③ 중 가장 나쁜 결과. ② NOK이면 ③은 `-`.

## 원칙
- **조회 실패 = 확인불가.** **읽기 전용(GET).** **결과는 새 파일.** 공식 반영·서명은 사람이.
- AI는 ASPICE 등급(N/P/L/F)을 판정하지 않는다.
- 비밀번호는 Windows 자격 증명 관리자(`AUTO-CL3 status-review` → CL2 → CL1 → AUTO-001 순, Jira 없으면 Confluence 값)에만.
- 코드를 고치면 `test/run_e2e.py`(가짜 Confluence·Codebeamer·Jira) 통과 후 반영. 규칙을 바꾸면 이 파일과 README를 함께 고친다.

## 실측 확인 대기 (첫 실행 후 갱신)
- Review Item의 실제 구조: Defect가 연결(relations)·Jira 주소·첨부 중 어디로 붙는지 → `doctor.bat`이 `state/debug/<CI>_review_*.json` 저장
- `/api/v3/items/{id}/attachments` 응답 형식, 첨부 다운로드 주소 `/api/v3/items/{id}/attachments/{aid}/content`
- Jira 로그인 주소(`/login.jsp`)와 ID/PW 공용 여부

## 실행
- 점검 `doctor.bat` · 전체 `run_cl3.bat` (빠른 검사는 실행 후 `q` 또는 `--quick`) · 일부 `--ci <CI ID>` / `--limit N`

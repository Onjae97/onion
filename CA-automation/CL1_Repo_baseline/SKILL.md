---
name: cl1-ci-baseline
description: CI list의 CI가 등록 저장소에서 실제로 관리되는지, 최신 PBL Baseline 대상 산출물에 포함되는지 점검해 CL1 결과 엑셀을 만든다. CA 체크리스트 CL1, 저장소 관리·Baseline 포함 확인 요청 시 사용.
version: 1.6
---

# CL1 점검 — CI 저장소 관리 · Baseline 포함

AI 에이전트(Claude·Codex 등)가 이 도구를 실행·수정할 때 따르는 규칙이다.
체크리스트 6번(추적성, `../CL6_Traceability`)과 **별개로 관리**한다 — 코드·설정·state를 공유하지 않는다 (로그인 자격 증명만 AUTO-001 저장값을 대체로 읽음).

## 판정 규칙 (사용자 확정 2026-11-23)
1. CI list = Confluence CI List 페이지 첨부 중 **가장 최근 업로드된 엑셀** (추적성 도구와 같은 방식, DRM이면 Excel COM 읽기 전용).
2. 대상 = **PBL이 비어 있지 않은 CI 전부** — 저장소 종류로 거르지 않는다. Category 빈칸은 위 행 값.
3. **① 저장소 관리**: `Path in Repository`에서 **CI name과 같은 산출물**이 관리되고 있는가.
   - NOK = 경로 비어 있음 / 경로의 Tracker·페이지 없음(404) / 경로의 이름이 CI name과 다름.
   - Codebeamer Tracker → Tracker 이름 비교. 다르면 **상위 Tracker 기준**(사용자 결정 2026-11-24, CL6와 같은 트리 해석): 등록 Tracker에서 트리 최상단까지 **모든 상위 노드** 이름과 비교 (실측: API 트리에서는 화면상 상위 Tracker가 폴더처럼 오는 경우가 있어 노드 종류로 거르지 않음. 트리 원본은 `state/debug/tracker_tree_<pid>.json`. 실측: Tracker 노드는 이름 없이 trackerId만 있어 `/api/v3/trackers/{id}`로 이름 조회) → 같으면 OK(근거 `등록 Tracker는 하위 Tracker → 상위 'X'(id)`), 유사도에 따라 OK · Conditional OK (가장 높은 유사도 기준).
     실제 사례: SYS4_03·SYS5_05·HWE4_03 — CI list에 하위 Tracker가 적혀 있어 NOK로 나왔던 건.
   - 상위까지 다르면, 같은 프로젝트 트리에서 같은 이름 Tracker를 찾아 근거에 적는다(판정은 NOK 유지). 근거에 상위 Tracker 이름도 함께 적음.
   - Confluence → 페이지 제목 / 첨부 존재. Codebeamer 기타 화면 → 화면에 CI name 존재(없으면 '확인 필요').
   - SVN·Git 등 → **수동 확인** (OK/NOK로 판정하지 않음).
4. **② Baseline 포함**: Codebeamer 프로젝트(`cl1.baseline.project_id`) Baselines 중 이름에 `keywords`와 `name_must_contain`이 모두 든 **최신** Baseline의 Description 표(`산출물` 헤더 아래 첫 열)에 CI name이 있는가. **버전은 비교하지 않는다.** 없으면 NOK.
   - 최신 = API 생성 시각 → 이름의 날짜(`_2026-11-19`) → 화면 목록 순서(위가 최신).
   - 기본 `name_must_contain: ["PBL"]` — 검색어만 쓰면 더 최근의 Tracker Baseline(대상 산출물 표 없음)이 잡힐 수 있어서. (사용자 확인 필요 시 조정)
5. **이름 비교·판정** (사용자 결정 2026-11-24): 소문자·영문/숫자/한글만 남겨 같으면 100%. 철자 유사도로
   **≥ 90% OK · 80~90% Conditional OK(사람 확인, '확인 필요' 탭) · < 80% NOK** — ①② 모두. Overview에 `① 유사도`·`② 유사도` 열.
   - 기준값은 config `cl1.ok_ratio`(0.9)·`cl1.conditional_ratio`(0.8).
   - **차지된 항목 제외(②)**: 다른 CI가 100%로 차지한 Baseline 항목은 유사 일치 후보에서 뺀다. 실측: 서로 다른 산출물끼리도 80~90% 쌍이 14개
     (System/Software Integration Test 90%, SW Unit Design/Test 90% 등) → 빠진 산출물이 이웃 항목에 OK로 걸리는 것을 막음. 일부 실행(--ci)이어도 전체 대상 CI 기준.
   - ①의 '다른 위치에 비슷한 이름 Tracker' 힌트는 90% 이상만 (80%대는 SIT/SQT처럼 다른 산출물이 걸림).
6. NOK 힌트(가장 비슷한 항목)는 유사도 60% 이상일 때만 적는다.

## Baseline 읽는 순서
**실측(2026-11-24, HL클레무브 Codebeamer)**: v3·이전 REST 목록 API는 404. Baselines 화면(`/project/{pid}/baselines`)의 행마다
`<span class="metaData" data-baseline-id / -name / -created-timestamp / -owner / -url / -description>`이 있고,
`data-baseline-description`에 Description 표(HTML)가 통째로 들어 있다 → **화면 한 번으로 목록·생성 시각·대상 산출물을 모두 얻는다.**
1. `GET /api/v3/projects/{pid}/baselines` → 2. `GET /rest/project/{pid}/baselines` (다른 서버 대비, wiki 표 해석)
3. 화면 metaData (현재 실제 경로) → 4. metaData가 없으면 화면 링크 → 상세 API → 속성 화면(`/proj/doc/details.do?doc_id={id}` 등)
- **화면 요청만 로그인 화면이 오는 경우(실측 2026-11-24, API는 정상)**: 새 탭에서 주소를 직접 열고 로그인 화면이면 저장된 ID/PW로 재로그인 후 다시 읽는다. 그래도 막히면 확인불가 + 화면을 `state/debug`에 저장(일반 실행 포함).
- 각 시도는 '조회 기록' 탭에 남긴다. `--doctor`는 받은 화면을 `state/debug/baseline_N.html`로 저장 → 실제 구조 확인용.
- 수동 대안: `--baseline-id`, `--baseline-file`(Description 복사본, 탭/표/wiki 모두 해석).

## 원칙
- **조회 실패 = 확인불가.** OK/NOK로 넘기지 않는다. Baseline을 못 읽으면 ②는 전부 확인불가.
- **읽기 전용(GET).** **결과는 새 파일.** 공식 반영·서명은 사람이.
- AI는 ASPICE 등급(N/P/L/F)을 판정하지 않는다 — 이 도구는 CI 단위 OK/NOK 근거만 만든다.
- 비밀번호는 Windows 자격 증명 관리자(`AUTO-CL1 ci-baseline`, 없으면 `AUTO-001 traceability`)에만. AI는 비밀번호를 묻거나 받지 않는다.
- 코드를 고치면 `test/run_e2e.py`(가짜 서버, 리눅스 `xvfb-run`) 통과 후 반영. 규칙을 바꾸면 이 파일과 README를 함께 고친다.

## 실행
- 점검 `doctor.bat` · 전체 `run_cl1.bat` · 일부 `--ci <CI ID>` / `--limit N`

---
name: traceability-gap-matrix
description: CI list에 등록된 CI의 Codebeamer 추적성(연결 0개 Item)을 전수 조사해 Gap Matrix 엑셀을 만든다. CA 추적성 항목 확인, 미추적 Item 목록, 커버리지 요청 시 사용.
version: 1.7
---
# 추적성 Gap Matrix (AUTO-001)

AI 에이전트(Claude·Codex 등)가 이 도구를 실행·수정할 때 따르는 규칙이다.
업무 배경과 결정 이력은 위키 `wiki/automation/auto-001-traceability-check.md`, 판정 규칙의 원본은 `wiki/rules/traceability-rules.md`.

## 판정 규칙 (사용자 확정)
1. CI list = Confluence CI List 페이지(`config.json`의 `ci_list_page_id`) 첨부 중 **가장 최근 업로드된 엑셀**.
2. 엑셀의 다른 필터는 무시하고 **PBL(헤더 `PBL`, 없으면 O열)이 비어 있지 않은 CI만** 대상.
3. **Repository가 Codebeamer인 CI만** 검사, 그 외는 건너뜀(보고서 미포함).
4. CI의 Tracker는 Path in Repository의 `/tracker/<id>`. **검사 범위는 `config.json`의 `scope`** (사용자 확정 기본값 `top_with_descendants`):
   - `top_with_descendants` — 등록 Tracker의 **최상위 Tracker**(트리에서 폴더 바로 아래 Tracker)와 그 아래 **하위 Tracker 전부**. CI list에 하위 Tracker가 적혀 있어도 상위 기준.
   - `with_descendants` — 등록 Tracker와 그 아래 전부 / `tracker_only` — 등록 Tracker만.
   - 트리: `GET /api/v3/trackers/tree?projectId=…` (Codebeamer 2.1+). 트리를 못 읽으면 등록 Tracker만 검사하고 **'하위 Tracker 확인불가'** 로 표시.
   - 형제 Tracker(예: 같은 폴더의 Test Plan)는 범위에 넣지 않는다. Item은 id로 중복 제거, Item ID 접두어는 Item이 실제 속한 Tracker의 key.
5. Item 유형 **Folder · Information 제외** — 화면 필터는 Meaning 묶음 기준이지만 **Codebeamer API는 Meaning을 주지 않는다**(2026-11-19 실측, 선택지 항목 id·name·type뿐). 따라서 Item의 유형 이름(typeName·categories·사용자 필드 Type)으로 판단하고, **철자 유사도 0.85 이상도 같은 것으로 본다** — 실제 사례: Type 선택지 이름이 오타 `Infomation`인 Tracker에서 Information 항목이 걸러지지 않아 분모가 수작업과 달랐음.
   - 선택지 id로 비교하지 않는다: Type 필드와 Category 필드의 id가 겹친다(Folder=1, Function=1).
   - **한글 표기 `정보` = Information** (`TYPE_ALIASES`). 철자 유사도는 한글을 비교하지 못하므로 별칭으로 맞춘다. 실제 사례: API가 `categories=[정보]`로 반환한 Tracker가 있음. config.json에 `정보`가 없어도 적용된다.
   - 화면의 Type 필드는 대부분 Codebeamer 기본 필드 Category의 표시 이름을 바꾼 것이고, API에서는 `categories`로 나온다.
6-0. CI list Category가 비어 있으면 병합 셀로 보고 위 행 값을 이어받는다.
6. Up/Downstream **Reference + incoming/outgoing Association 중 연결 상대가 Folder·Information이 아닌 것이 1개 이상이면 연결됨**. 취소·폐기 상태 항목과의 연결도 연결됨. (사용자 결정 2026-11-23)
   - 상대 번호 = 연결 응답의 `itemRevision.id`. 상대 유형은 같은 범위 Item → 이번 실행 캐시 → `GET /api/v3/items/{id}` 순으로 확인.
   - 상대가 **모두** Folder·Information → **미추적**, Category 탭 비고 `Folder/Information에만 연결`, Overview `미추적 중 Folder/Information에만 연결` 열.
   - 유효한 상대가 없고 상대 번호·유형을 확인하지 못한 연결이 있으면 → **확인불가** (미추적으로 넘기지 않음). 유효한 상대가 하나라도 확인되면 나머지를 몰라도 연결됨.
   - 같은 범위 안에서 유효한 상대가 이미 확인된 Item은 범위 밖 상대의 유형 조회를 생략한다.
   - relations 응답이 여러 페이지(`isLastPage=false`)면, 첫 페이지에서 유효한 상대를 못 찾은 Item만 나머지 페이지까지 받아 다시 판정한다. 다음 페이지 조회 실패 = 확인불가.
7. 연결 0개 Item = 미추적. Category(detail 제외, `SYS.2.1`→`SYS.2`, 묶음 표기 `HWE.3&4`는 그대로)별 탭, 탭 순서는 CI ID 순서에 CI ID / CI name / Author / Path in Repository / Item ID.
8. Item name, PBL 값은 보고서에 넣지 않는다.
9. **Type 미지정(`--`) Item은 판정 대상에 포함**(화면 필터와 동일)하되 따로 표시 — Overview·Tracker별 `Type 미지정(--)`·`미추적 중 Type 미지정(--)` 열, Category 탭 `비고` 열. 미지정 = Type 필드(categories 또는 사용자 필드 'Type') 값 없음/Unset. typeName은 Type 필드가 아님. Tracker에 'Type' 필드가 없으면 집계하지 않음(`(Type 필드 없음)`). (사용자 결정 2026-11-20, 추후 변경 가능)

## 로그인
- 저장된 ID/PW는 Windows 자격 증명 관리자(keyring, 서비스명 `AUTO-001 traceability`)에만 둔다. **파일·로그·채팅에 비밀번호를 쓰지 않는다.** AI는 비밀번호를 묻거나 받지 않는다.
- 로그인 화면에서 password 입력칸과 같은 form의 텍스트칸을 찾아 입력 후 Enter. 실패 2회면 수동 로그인 안내로 전환.
- 실행 중 401/로그인 화면 응답 → 재로그인 후 같은 묶음 재조회.

## 원칙
- **조회 실패 = 확인불가.** 실패한 Item·CI를 연결/미연결로 넘기지 않는다. 분모에서 빼고 확인불가 탭에 남긴다.
- **읽기 전용.** GET 요청만 한다. Codebeamer·Confluence에 쓰지 않는다.
- **결과는 새 파일.** 기존 산출물을 덮어쓰지 않는다. 공식 산출물 반영·저장·서명은 사람이 한다.
- **코드를 고치면** `test/`의 가짜 서버 시험(`run_e2e.py`, `run_scope.py`, `run_autologin.py`, `run_counterpart.py`, `test_drm_excel.py` — 리눅스는 `xvfb-run python …`)을 통과시킨 뒤 반영한다.
- 규칙을 바꾸면 위키 `traceability-rules.md`와 이 파일을 함께 고치고, 결과가 바뀌는 CI 수를 전후 비교해 보고한다.

## DRM
- 회사 문서가 DRM으로 암호화된 경우(파일이 zip 형식이 아님, 예: 첫머리 `DRMONE`) → openpyxl로 못 읽음.
- DRM이면 Excel COM(`DispatchEx`, 별도 인스턴스)으로 **읽기 전용** 열기 → 값·하이퍼링크만 읽고 `Close(False)` → `Quit`. 원본·DRM 파일을 저장하거나 복호화 사본을 만들지 않는다.

## 실행
- 점검: `doctor.bat` (`python traceability.py --doctor`)
- 전체: `run_traceability.bat`
- 일부: `python traceability.py --ci <CI ID> [--ci …]` / `--limit N` (일부 실행은 변동 비교 기준을 갱신하지 않음)

## 사용 API (Codebeamer REST v3, 로그인 세션)
- `GET /api/v3/trackers/{id}` — keyName (Item ID 접두어)
- `GET /api/v3/items/query?queryString=tracker.id IN (id)` — Item 목록 (실패 시 `/trackers/{id}/items` + `/items/{id}`)
- `GET /api/v3/items/{id}/relations` — 연결 목록 (상대 번호 `itemRevision.id`)
- `GET /api/v3/items/{id}` — 범위 밖 연결 상대의 유형
- Confluence: `GET /rest/api/content/{pageId}/child/attachment?expand=version`

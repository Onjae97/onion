# CL1 점검 — CI 저장소 관리 · Baseline 포함 (v1.6)

체크리스트 **CL1** 자동화. CI list의 CI마다 두 가지를 확인합니다.

| 확인 | 내용 | NOK |
|---|---|---|
| ① 저장소 관리 | CI list의 `Path in Repository`에서 **CI name과 같은 산출물**이 실제로 관리되고 있는가 | 경로 비어 있음 / 경로의 Tracker·페이지 없음 / 이름이 다름 |
| ② Baseline 포함 | 최신 PBL Baseline의 **Description(대상 산출물 목록)** 에 있는가 (버전은 비교 안 함) | 목록에 없음 |

체크리스트 6번(추적성, `../traceability`)과는 **별개 도구**입니다. 설정·로그인 세션·결과 파일도 따로 둡니다.
(CL1~CL11 자동화가 끝나면 합본으로 묶을 예정)

## 처음 한 번만
1. `config.example.json`을 복사해 **`config.json`** 만들기 (Git에 올라가지 않음)
   - `confluence.base`, `confluence.ci_list_page_id` — 추적성 도구의 config.json과 같은 값
   - `codebeamer.base` — 예: `https://codebeamer.회사주소/cb`
   - `cl1.baseline.project_id` — Baselines 화면 주소 `/cb/project/171/baselines`의 **171**
   - `cl1.baseline.keywords` — Baselines 화면 검색어 (`["ADCU50"]`, 대소문자 무관)
   - `cl1.baseline.name_must_contain` — 이름에 꼭 들어가야 하는 말 (기본 `["PBL"]`, 아래 참고)
2. `setup.bat` → (선택) `set_login.bat` → `doctor.bat`
   - 추적성 도구에서 `set_login.bat`으로 저장한 ID/PW가 있으면 그대로 씁니다
   - `doctor.bat`이 보여주는 **Baseline 이름과 산출물 목록이 화면(Properties)과 같은지** 확인

## 매번
- `run_cl1.bat` 더블클릭 → `output\CL1_CI관리_Baseline_프로젝트_날짜_시각.xlsx`
- 일부 CI만: `run_cl1.bat --ci CI_ID1 --ci CI_ID2`
- Baseline 직접 지정: `run_cl1.bat --baseline-id 9705300` (Properties 화면 제목 옆 `#번호`)
- 자동으로 Baseline을 못 읽을 때: Properties 화면의 Description 표를 복사해 `desc.txt`로 저장 → `run_cl1.bat --baseline-file desc.txt`

## 검사 대상·판정 방법
- **대상 CI**: 최신 CI list에서 **PBL 값이 있는 CI 전부** (저장소 종류 무관 — Codebeamer가 아니어도 포함). `ci_list.pbl_only: false`면 전체
- **① 저장소**
  - Codebeamer Tracker 경로(`/tracker/번호`) → Tracker 이름과 CI name 비교
    - CI list에 **하위 Tracker**가 적혀 있으면 상위 Tracker(최상위까지) 이름으로 비교 — 추적성 도구와 같은 상위 기준. Overview `① 저장소에서 찾은 이름`에 `상위 이름 (번호) ← 등록: 하위 이름 (번호)`로 표시
    - 이름이 다르면, 같은 프로젝트에 **CI name과 같은 이름의 Tracker가 다른 곳에 있는지** 찾아 근거에 적음 (경로 오기 확인용)
  - Confluence 경로 → 페이지 제목(첨부 링크면 첨부 파일 존재) 비교
  - Codebeamer의 다른 화면(문서 등) → 화면에 CI name이 있는지
  - SVN·Git·공유 폴더 등 → **수동 확인** (자동 확인 미지원)
- **② Baseline**
  - Baselines 화면에서(행마다 숨어 있는 Baseline 정보·Description을 읽음 — 속성 화면을 따로 열지 않음) 이름에 `keywords` + `name_must_contain`이 모두 든 Baseline 중 **최신**(이름의 날짜 → 목록 순서) 1개
  - 그 Baseline의 Description 표에서 `산출물` 헤더 아래 이름 목록과 CI name 비교, 버전 무시
- **이름 비교**: 대소문자·공백·기호·줄바꿈 차이는 같은 이름(100%). 철자 유사도 **90% 이상 OK / 80~90% Conditional OK(사람 확인) / 80% 미만 NOK**. Overview `① 유사도`·`② 유사도` 열에 표시. Baseline 항목은 다른 CI가 정확히 차지한 것이면 유사 일치 후보에서 제외(비슷한 이름의 다른 산출물에 잘못 걸리지 않게)

### 왜 `name_must_contain: ["PBL"]` 인가
`adcu50`으로 검색하면 Tracker Baseline(예: `..._SWQT_...`)도 함께 나옵니다. 이것이 더 최근이면 대상 산출물 표가 없어 전부 NOK가 됩니다.
그래서 이름에 `PBL`이 든 Baseline 중 최신을 씁니다. 다른 규칙이 필요하면 config에서 바꾸세요 (빈 목록 `[]` = 검색어만).

## 결과 엑셀
| 탭 | 내용 |
|---|---|
| 요약 | ①②별 OK / Conditional OK / NOK / 확인불가 / 수동 확인 수, NOK CI 수, 사용한 Baseline(링크) |
| Overview | CI별 ①② 결과·근거, 저장소에서 찾은 이름, Baseline 항목·버전(참고), NOK 사유 |
| NOK | NOK 항목만 (① 저장소 미관리 / ② Baseline 미포함) + 사유 |
| 확인 필요 | Conditional OK · 확인불가 · 수동 확인 — 사람이 확인 후 마지막 열 기입 |
| Baseline | Baseline 대상 산출물 목록과 맞은 CI ID. 어떤 CI와도 안 맞은 항목은 노란색 |
| Baseline 후보 | 조건에 맞은 Baseline 목록과 선택한 것 |
| 조회 기록 | Baseline을 어떤 경로(API/화면)로 읽었는지 |
| 실행정보 | 실행 시각, CI list 파일, 판정 규칙 |

## 원칙
- 읽기 전용(GET). Codebeamer·Confluence를 바꾸지 않음
- 조회 실패 = **확인불가** (OK/NOK로 넘기지 않음)
- 결과는 항상 새 파일. 공식 산출물 반영은 담당자가 검토 후 직접

## 문제가 생기면
| 증상 | 조치 |
|---|---|
| `Baseline 내용을 읽지 못했습니다` | `doctor.bat` 실행 → `조회:` 줄과 `state\debug\baseline_*.html` 파일을 Claude에게 전달. 급하면 `--baseline-file` |
| 엉뚱한 Baseline이 선택됨 | `Baseline 후보` 탭 확인 → config의 `keywords`·`name_must_contain` 조정, 또는 `--baseline-id` |
| Conditional OK가 너무 많음/적음 | config의 `cl1.ok_ratio`(0.9)·`cl1.conditional_ratio`(0.8) 조정 |
| 그 밖의 문제 | `../traceability/README.md`의 '문제가 생기면' 표와 같음 (로그인·DRM·브라우저) |

## 파일 구성
- `cl1_check.py` 본체 · `config.json` 설정 · `SKILL.md` AI 에이전트용 규칙
- `state\` 로그인 세션·CI list 사본·doctor 화면 저장 (**공유 금지**) · `output\` 결과
- `test\` 가짜 서버 시험: `xvfb-run python test/run_e2e.py` (Windows는 `python test\run_e2e.py`)

# AUTO-001 추적성 Gap Matrix — 사용 안내

더블클릭 한 번으로 아래를 자동으로 합니다.
1. Confluence의 CI List 페이지에서 **가장 최근에 올라온** CI list 엑셀을 받음
2. **PBL(O열) 값이 있고 Repository가 Codebeamer인** CI만 고름
3. CI(Tracker)마다 Item 전체를 조회 (Folder·Information 제외, 한글 `정보` 포함)
4. 연결(Up/Downstream Reference + Association)이 **0개이거나, 연결 상대가 모두 Folder·Information인 Item** 찾기
5. `output\` 폴더에 Gap Matrix 엑셀 생성

API 토큰은 필요 없습니다. 프로그램 전용 브라우저 창에 **한 번 로그인**해 두면 그 세션을 계속 씁니다.
조회는 모두 읽기 전용입니다. Codebeamer·Confluence의 데이터를 바꾸지 않습니다.

## 처음 한 번만
0. `config.example.json`을 복사해 **`config.json`** 을 만들고 실제 값을 넣기
   - `confluence.base`, `codebeamer.base` (회사 주소), `confluence.ci_list_page_id` (CI List 페이지 번호), `project` (결과 파일명에 쓰임)
   - `config.json`은 회사 정보가 들어가므로 **Git에 올라가지 않습니다** (.gitignore)
1. Python 설치 (python.org, 설치할 때 **"Add python.exe to PATH" 체크**)
2. `setup.bat` 더블클릭 → 필요한 패키지 설치 (v1.4부터 keyring 추가 — 예전에 설치했어도 한 번 더 실행)
3. `doctor.bat` 더블클릭 → 연결 점검
   - 브라우저 창이 뜨면 **Confluence에 로그인** → 검은 창으로 돌아와 Enter
   - 이어서 **Codebeamer에 로그인** → 검은 창으로 돌아와 Enter
   - `✔ 점검 완료`가 나오면 준비 끝

## 자동 로그인 (선택)
`set_login.bat` 실행 → Confluence·Codebeamer ID/PW 입력 (같은 계정이면 한 번만).
- 비밀번호는 **Windows 자격 증명 관리자**에 암호화되어 저장되고, 이 PC의 이 Windows 계정에서만 읽힙니다. 파일·채팅 어디에도 남지 않습니다.
- 이후 로그인 화면이 나오면 프로그램이 자동으로 입력합니다. 실행 중 Codebeamer 세션이 만료돼도 다시 로그인하고 이어서 진행합니다.
- 비밀번호를 바꾸면 `set_login.bat`을 다시 실행. 삭제: `python traceability.py --clear-login`
- 저장된 정보가 없거나 자동 로그인이 실패하면 예전처럼 창에서 직접 로그인하라는 안내가 나옵니다.

## 매번
- `run_traceability.bat` 더블클릭 → 검사 방식 선택 (10초 동안 입력이 없으면 1번)
  | 번호 | 검사 방식 | 범위 | 용도 |
  |---|---|---|---|
  | 1 | **전체 검사** (기본) | 최상위 Tracker + 하위 Tracker 전부 (`config.json`의 `scope`) | CA 근거 |
  | 2 | **빠른 검사** (`--quick`) | CI list에 적힌 Tracker 하나만 | 참고용 (하위 Tracker가 큰 CI의 시간 단축) |
- 끝나면 `output\추적성_GapMatrix_프로젝트명_날짜_시각.xlsx` (빠른 검사는 끝에 `_quick`)
- 명령 프롬프트에서 옵션을 주면 묻지 않고 바로 실행: `run_traceability.bat --quick`
- 일부 CI만: `run_traceability.bat --ci CI_ID1 --ci CI_ID2` (`--quick`과 함께 써도 됨)
- 빠른 검사는 결과가 전체 검사와 다를 수 있습니다 (예: Item이 하위 Tracker에만 있는 CI는 분모 0). **변동 탭은 같은 검사 방식끼리만 비교**합니다.

## CI list가 DRM 파일일 때
회사 DRM으로 암호화된 CI list는 Python이 직접 읽을 수 없습니다. 이때 프로그램이 **PC의 엑셀을 따로 실행해 읽기 전용으로 열고**, 값만 읽은 뒤 **저장하지 않고 닫습니다.** 실행 중에 엑셀 창이 잠깐 떴다가 닫히는 것은 정상입니다. 지금 열려 있는 다른 엑셀 파일에는 영향이 없습니다.

## 검사 범위 (하위 Tracker)
`config.json`의 `"scope"`로 바꿀 수 있습니다.
- `top_with_descendants` (기본): CI list에 적힌 Tracker의 **최상위 Tracker와 그 아래 하위 Tracker 전부**. 하위 Tracker가 적혀 있어도 상위 기준으로 검사합니다. Overview의 `범위 메모`에 조정 사실이 노란색으로 표시됩니다.
- `with_descendants`: 적힌 Tracker와 그 아래만 / `tracker_only`: 적힌 Tracker만

## 결과 엑셀
| 탭 | 내용 |
|---|---|
| Overview | CI별 분모(판정 대상) · 미추적 · 커버리지(%) · 제외(Folder/Information) · 확인불가 · 상태 · Type 미지정(--) 수 · Folder/Information에만 연결된 미추적 수. Sheet 열을 누르면 해당 Category 탭으로 이동 |
| SYS.1, SWE.1 … | Category별 미추적 Item 목록: CI ID / CI name / Author / Path in Repository / Item ID (Item ID 클릭 → Codebeamer Item) / 비고 (Type 미지정(--)이면 표시) |
| 검수 | CI마다 '연결됨'으로 판정된 Item 무작위 10건(링크). 눌러서 Relations에 연결이 있는지만 확인 |
| Tracker별 | CI 범위 안의 Tracker(하위 포함)마다 전체·제외·분모·미추적 — Codebeamer 트리의 '전체 수'와 대조용 |
| 변동 | 직전 전체 실행 대비 신규 미추적 / 해소된 Item |
| 확인불가 | 조회에 실패했거나 연결 상대를 확인하지 못해 판정하지 못한 CI·Item (연결/미연결로 처리하지 않음) |
| 실행정보 | 실행 시각, 사용한 CI list 파일, 선별 결과, 판정 규칙 |

결과는 항상 **새 파일**로 만들어집니다. 공식 산출물에 반영하고 저장하는 일은 담당자가 검토한 뒤 직접 합니다.

## 검수 방법 (Item이 많은 CI도 가능)
전수를 눈으로 대조하지 않고, 세 가지만 확인합니다.
1. **분모 대조** — Overview의 `분모(판정대상)`가 화면 Traceability Report(필터 `Type: not Folder, Information`)의 Item 수와 같은지. 다르면 `판정 대상 유형 분포`에 섞인 유형(예: Info 9)을 보고 원인을 찾음
2. **미추적 전수 확인** — Category 탭의 Item ID를 눌러 연결이 정말 없는지 확인 (보통 몇 건 수준)
3. **연결됨 표본 확인** — 검수 탭의 표본 10건을 눌러 연결이 있는지 확인
→ 세 가지가 맞으면 해당 CI 결과를 신뢰. 프로그램은 페이지를 끝까지 넘겨 전부 조회하므로 화면 엑셀 내보내기처럼 잘리지 않습니다 (`전체 Item` = Tracker의 Item 총수).

## 문제가 생기면
| 증상 | 조치 |
|---|---|
| `python`을 찾을 수 없음 | Python을 다시 설치하고 PATH 옵션을 체크 |
| setup에서 pip 실패 | 회사 프록시 문제일 수 있음 → IT에 PyPI 접근 문의 |
| 브라우저가 안 뜸 / Chrome 오류 | `config.json`의 `"channel": "chrome"`을 `"msedge"`로 바꾸기 |
| DRM 파일에서 엑셀 오류 | 엑셀을 직접 열어 CI list가 열리는지 확인 (DRM 권한). `setup.bat` 다시 실행(pywin32) |
| 확인불가가 갑자기 많아짐 (`연결 상대의 Item 번호 또는 유형을 확인하지 못함`) | `doctor.bat` 실행 → `연결 1건의 구조`·`연결 상대 확인` 줄을 Claude에게 전달 |
| Folder/Information이 덜 걸러짐 | `doctor.bat` 실행 → 해당 CI ID 입력 → `Type 선택지` 줄을 Claude에게 전달. 급하면 `config.json`의 `exclude_types`에 그 유형 이름 추가 |
| `로그인이 필요합니다` | `doctor.bat`을 다시 실행해 로그인 |
| `HTTP 401/403`이 반복됨 | 로그인 상태에서도 REST API가 막힌 경우 → 화면 그대로 Claude에게 전달 |
| 일부 CI가 확인불가 | 확인불가 탭의 내용(HTTP 코드)을 Claude에게 전달 |

## 파일 구성
- `traceability.py` 본체 · `config.json` 프로젝트 설정 · `SKILL.md` AI 에이전트용 규칙
- `state\` 로그인 세션, 받은 CI list 사본, 직전 실행 기록 (**다른 사람과 공유하지 말 것** — 로그인 정보 포함)
- `output\` 결과 엑셀 · `test\` 가짜 서버 시험 (코드를 고칠 때 사용)

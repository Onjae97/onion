# CA-automation

형상 감사(CA, Configuration Audit) 대비 CM 업무 자동화 도구 모음.

| 도구 | 설명 | 사용 기술 |
| --- | --- | --- |
| [CL6_Traceability](CL6_Traceability/) | CI list의 CI(Codebeamer Tracker, 하위 Tracker 포함)마다 연결이 없는 Item을 전수 조사해 추적성 Gap Matrix 엑셀 생성. 로그인 세션 재사용·자동 로그인, DRM 엑셀 읽기 지원 | Python, Playwright, openpyxl, pywin32, keyring |
| [CL1_Repo_baseline](CL1_Repo_baseline/) | 체크리스트 CL1 — CI list의 CI가 등록 저장소(Path in Repository)에서 실제로 관리되는지, 최신 PBL Baseline 대상 산출물에 포함되는지 점검해 NOK 목록 엑셀 생성. 추적성 도구와 별개 관리 | Python, Playwright, openpyxl, pywin32, keyring |
| [CL2_Revision_history](CL2_Revision_history/) | 체크리스트 CL2 — CI마다 Codebeamer Tracker(Category 포함)의 Revision history Item을 찾아 ① 존재·관리 ② 필수 항목(Version·Date·Description·Author·Approver) 빈칸 ③ Version Rule(vX.Yz 형식·순서·건너뜀)을 판정하고, 읽은 표를 근거 탭으로 남기는 엑셀 생성 | Python, Playwright, openpyxl, pywin32, keyring |

## 폴더 이름 규칙
체크리스트 항목별로 `CL<번호>_<항목>` (예: `CL1_Repo_baseline`, `CL6_Traceability`). CL1~CL11 자동화가 끝나면 합본으로 묶을 예정.

## 공통 원칙
- 조회는 읽기 전용, 조회 실패는 **확인불가**로 남긴다 (연결/미연결로 넘기지 않음)
- 결과는 항상 새 파일, 공식 산출물 반영·저장은 담당자가 검토 후 직접
- 회사 주소·페이지 번호 등 실제 값은 `config.json`(Git 제외)에만 둔다. 저장소에는 `config.example.json`(가짜 값)만 올린다
- 로그인 정보는 Windows 자격 증명 관리자에만 저장 (파일·저장소에 남기지 않음)

## 다른 PC에서 쓰기
```
git clone https://github.com/Onjae97/onion
cd onion\CA-automation\CL6_Traceability      (CL1은 CL1_Repo_baseline, CL2는 CL2_Revision_history)
copy config.example.json config.json   (실제 값 입력)
setup.bat → set_login.bat → doctor.bat → run_traceability.bat   (CL1은 run_cl1.bat, CL2는 run_cl2.bat)
```

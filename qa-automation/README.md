# qa-automation

Spec 문서에서 Test Case를 만들고, 테스트를 수행해 결과를 검수하는 연습용 자동화입니다.

```
Spec 파일 ──/spec-to-tc──▶ testcases.json ──build_suite.py──▶ Test Suite.xlsx
                (1~2단계, Claude)            (3단계)              │ 테스트 수행 후 결과 입력
                                                                  ▼
                                   검수리포트.xlsx ◀──review_suite.py── (4단계)
```

## 폴더 구성

| 폴더 | 역할 | 상태 |
| --- | --- | --- |
| [tc-generation](tc-generation/) | TC 생성 자동화: Spec 분석 → Test Case → Test Suite 엑셀 | 동작함 |
| [tc-execution](tc-execution/) | TC 수행 자동화: 테스트 수행과 결과 검수 | 검수만 있음, 수행 자동화는 예정 |
| `common/` | 양쪽이 함께 쓰는 엑셀 시트·열 구성 (`suite_format.py`) | |

## 준비 (처음 한 번만)

`qa-automation` 폴더에서 실행합니다.

```bash
pip install -r requirements.txt
```

자세한 사용법은 각 폴더의 README를 보세요.

## 배운 것

- Claude Code 스킬(`.claude/skills/<이름>/SKILL.md`)로 AI 작업 절차 정의하기
- `openpyxl`로 엑셀 서식, 드롭다운(데이터 유효성 검사), 조건부 서식, 수식 넣기
- 두 스크립트가 같은 열 이름을 쓰도록 설정을 한 파일(`common/suite_format.py`)에 모으기

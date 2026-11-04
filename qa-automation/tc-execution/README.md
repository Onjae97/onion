# tc-execution

[tc-generation](../tc-generation/)이 만든 Test Suite 엑셀로 테스트를 수행하고 결과를 검수합니다.
설치는 [상위 README](../README.md)를 보세요.

현재는 사람이 수행한 결과를 검수하는 기능만 있고, **테스트 수행 자동화는 아직 없습니다.**

## 테스터 작업

Test Suite 엑셀의 `Test Case` 시트에서 회차별로 결과(목록에서 선택), Tester, 실행일, Remark를 채웁니다.
`실행 횟수`와 `최종 결과`, `요약` 시트의 집계는 자동으로 계산됩니다.

## 검수

이 폴더에서 실행합니다.

```bash
python scripts/review_suite.py ../tc-generation/output/내_spec/TestSuite_내_spec_20261103.xlsx
```

엑셀과 같은 폴더에 `..._검수리포트_<시각>.xlsx`가 생기고, 화면에도 요약이 나옵니다.

- **요약**: 회차별 / 최종 결과 집계, Pass율, 판정 (검수 완료 / 보완 필요)
- **확인 필요 항목**: 미실행, Tester 누락, Fail/Block인데 사유 없음, 잘못된 결과 값
- **Fail·Block 목록**: 최종 결과가 Fail/Block인 TC와 사유

# excel-merger

`input` 폴더에 넣은 엑셀 파일들을 하나로 합쳐 주는 스크립트입니다.

## 준비 (처음 한 번만)

```bash
pip install -r requirements.txt
```

## 사용법

1. 합칠 `.xlsx` 파일들을 `input` 폴더에 넣습니다.
2. 이 폴더에서 실행합니다.

   ```bash
   python merge.py
   ```

3. `output` 폴더에 `합친결과_날짜_시각.xlsx` 파일이 생깁니다.

## 동작 방식

- 각 파일의 **첫 번째 시트**만 읽습니다.
- 맨 앞에 `원본파일` 열이 추가되어 어느 파일에서 온 행인지 알 수 있습니다.
- 파일마다 열 구성이 달라도 합쳐지고, 없는 칸은 빈칸으로 남습니다.
- `input`, `output` 폴더의 엑셀 파일은 GitHub에 올라가지 않습니다 (`.gitignore`).

## 배운 것

- `pathlib`로 폴더 안의 파일 찾기
- `pandas`로 엑셀 읽기(`read_excel`), 합치기(`concat`), 저장하기(`to_excel`)

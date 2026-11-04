"""input 폴더 안의 엑셀 파일들을 하나로 합쳐서 output 폴더에 저장합니다."""

from datetime import datetime
from pathlib import Path

import pandas as pd

# 이 스크립트가 있는 폴더를 기준으로 경로를 잡습니다 (어디서 실행해도 동작하도록)
BASE_DIR = Path(__file__).parent
INPUT_DIR = BASE_DIR / "input"
OUTPUT_DIR = BASE_DIR / "output"


def find_excel_files(folder):
    """폴더 안의 .xlsx 파일 목록을 이름순으로 돌려줍니다."""
    files = []
    for path in sorted(folder.glob("*.xlsx")):
        # 엑셀이 파일을 열고 있을 때 생기는 임시 파일(~$로 시작)은 건너뜁니다
        if path.name.startswith("~$"):
            continue
        files.append(path)
    return files


def merge_excel_files(files):
    """각 파일의 첫 번째 시트를 읽어서 하나의 표로 합칩니다."""
    tables = []
    for path in files:
        df = pd.read_excel(path)
        # 어느 파일에서 온 행인지 알 수 있도록 열을 하나 추가합니다
        df.insert(0, "원본파일", path.name)
        tables.append(df)
        print(f"  읽음: {path.name} ({len(df)}행)")

    # 파일마다 열 구성이 달라도 합쳐지고, 없는 칸은 빈칸이 됩니다
    return pd.concat(tables, ignore_index=True)


def main():
    INPUT_DIR.mkdir(exist_ok=True)
    OUTPUT_DIR.mkdir(exist_ok=True)

    files = find_excel_files(INPUT_DIR)
    if not files:
        print(f"합칠 엑셀 파일이 없습니다. {INPUT_DIR} 폴더에 .xlsx 파일을 넣어주세요.")
        return

    print(f"엑셀 파일 {len(files)}개를 합칩니다.")
    merged = merge_excel_files(files)

    # 실행할 때마다 결과가 덮어써지지 않도록 파일 이름에 시각을 붙입니다
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = OUTPUT_DIR / f"합친결과_{timestamp}.xlsx"
    merged.to_excel(output_path, index=False)

    print(f"완료! 총 {len(merged)}행 → {output_path}")


if __name__ == "__main__":
    main()

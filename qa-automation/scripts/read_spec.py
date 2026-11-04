"""Word / 엑셀 형식의 Spec을 텍스트로 바꿔서 출력합니다.

사용법: python scripts/read_spec.py <spec 파일>
(.txt, .md, .pdf는 Claude가 직접 읽을 수 있어서 변환이 필요 없습니다)
"""

import sys
from pathlib import Path

import pandas as pd
from docx import Document


def read_docx(path):
    """문단과 표를 문서에 나온 순서대로 텍스트로 바꿉니다."""
    doc = Document(path)
    lines = []
    for block in doc.element.body.iterchildren():
        tag = block.tag.split("}")[-1]
        if tag == "p":
            text = "".join(node.text or "" for node in block.iter() if node.tag.endswith("}t"))
            if text.strip():
                lines.append(text)
        elif tag == "tbl":
            # 표는 칸을 | 로 구분해서 한 줄씩 출력합니다
            for row in block.iter():
                if not row.tag.endswith("}tr"):
                    continue
                cells = []
                for cell in row.iter():
                    if cell.tag.endswith("}tc"):
                        cells.append("".join(t.text or "" for t in cell.iter() if t.tag.endswith("}t")))
                lines.append(" | ".join(cells))
            lines.append("")
    return "\n".join(lines)


def read_excel(path):
    """모든 시트를 시트 이름과 함께 표 형태로 출력합니다."""
    sheets = pd.read_excel(path, sheet_name=None, dtype=str)
    parts = []
    for name, df in sheets.items():
        parts.append(f"## 시트: {name}")
        parts.append(df.fillna("").to_csv(sep="|", index=False))
    return "\n".join(parts)


def main():
    if len(sys.argv) != 2:
        sys.exit("사용법: python scripts/read_spec.py <spec 파일>")

    path = Path(sys.argv[1])
    if not path.exists():
        sys.exit(f"파일을 찾을 수 없습니다: {path}")

    suffix = path.suffix.lower()
    if suffix == ".docx":
        text = read_docx(path)
    elif suffix in (".xlsx", ".xls"):
        text = read_excel(path)
    elif suffix in (".txt", ".md"):
        text = path.read_text(encoding="utf-8")
    else:
        sys.exit(f"{suffix} 형식은 변환하지 않습니다. Read 도구로 직접 읽거나 텍스트로 변환해 주세요.")

    # 윈도우 콘솔에서도 한글이 깨지지 않도록 UTF-8로 출력합니다
    sys.stdout.reconfigure(encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()

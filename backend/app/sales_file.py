"""상가 프로그램 CSV를 읽고 검사합니다 (spec 2번).

잘못된 파일로 보는 경우는 네 가지뿐입니다. (점주 확인)
  1. 열 이름이 8개(상품코드, 대분류, 판매수량, 판매액, 연도, 달, 일, 요일)와 다름
  2. 판매수량·판매액이 숫자가 아니거나 비어 있음
  3. 연도·달·일이 존재하지 않는 날짜이거나, 파일 안에 여러 날짜가 섞임
  4. 요일이 날짜와 맞지 않음
그 밖의 문제(예: 대분류가 24개보다 적음)는 막지 않습니다.
"합계" 줄(상품코드 "-")은 저장하지 않습니다.
"""
import csv
import io
import re
from dataclasses import dataclass
from datetime import date

EXPECTED_COLUMNS = ["상품코드", "대분류", "판매수량", "판매액", "연도", "달", "일", "요일"]
WEEKDAYS = "월화수목금토일"
MAX_PROBLEMS_SHOWN = 10
_INT_PATTERN = re.compile(r"^-?\d+$")


class FileProblems(Exception):
    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


@dataclass(frozen=True)
class SaleRow:
    product_code: str
    category: str
    quantity: int
    amount: int


@dataclass(frozen=True)
class ParsedSalesFile:
    sales_date: date
    rows: list[SaleRow]


def _decode(raw: bytes) -> str:
    # 상가 프로그램의 한글 CSV는 UTF-8이 아니라 CP949인 경우가 많습니다.
    for encoding in ("utf-8-sig", "cp949"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise FileProblems(["글자를 읽을 수 없어요. 상가 프로그램에서 뽑은 CSV 파일이 맞는지 확인해 주세요."])


def _pick_delimiter(first_line: str) -> str:
    return max([",", "\t", ";"], key=first_line.count) if any(
        d in first_line for d in [",", "\t", ";"]
    ) else ","


def _to_int(text: str) -> int | None:
    cleaned = text.strip().replace(",", "")
    return int(cleaned) if _INT_PATTERN.match(cleaned) else None


def _is_total_row(code: str, category: str) -> bool:
    return code == "-" or category == "합계"


def parse_sales_csv(raw: bytes) -> ParsedSalesFile:
    text = _decode(raw)
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        raise FileProblems(["파일이 비어 있어요."])

    reader = csv.reader(io.StringIO("\n".join(lines)), delimiter=_pick_delimiter(lines[0]))
    header = [c.strip() for c in next(reader)]
    if len(header) != len(EXPECTED_COLUMNS) or sorted(header) != sorted(EXPECTED_COLUMNS):
        raise FileProblems(
            [
                "열 이름이 맞지 않아요.",
                "필요한 열: " + ", ".join(EXPECTED_COLUMNS),
                "파일의 열: " + (", ".join(header) if any(header) else "(없음)"),
            ]
        )
    idx = {name: header.index(name) for name in EXPECTED_COLUMNS}

    problems: list[str] = []
    rows: list[SaleRow] = []
    dates: dict[date, int] = {}

    for row in reader:
        line_no = reader.line_num
        if not any(cell.strip() for cell in row):
            continue
        if len(row) != len(EXPECTED_COLUMNS):
            problems.append(f"{line_no}번째 줄: 열의 개수가 달라요. ({len(row)}개)")
            continue

        code = row[idx["상품코드"]].strip()
        category = row[idx["대분류"]].strip()
        if _is_total_row(code, category):
            continue

        bad = False
        quantity = _to_int(row[idx["판매수량"]])
        amount = _to_int(row[idx["판매액"]])
        if quantity is None:
            problems.append(
                f"{line_no}번째 줄: 판매수량이 숫자가 아니거나 비어 있어요. (값: '{row[idx['판매수량']].strip()}')"
            )
            bad = True
        if amount is None:
            problems.append(
                f"{line_no}번째 줄: 판매액이 숫자가 아니거나 비어 있어요. (값: '{row[idx['판매액']].strip()}')"
            )
            bad = True

        y, m, d = (_to_int(row[idx[k]]) for k in ("연도", "달", "일"))
        try:
            if y is None or m is None or d is None:
                raise ValueError
            sales_date = date(y, m, d)
        except ValueError:
            problems.append(
                f"{line_no}번째 줄: 날짜가 올바르지 않아요. (연도 '{row[idx['연도']].strip()}', "
                f"달 '{row[idx['달']].strip()}', 일 '{row[idx['일']].strip()}')"
            )
            continue

        weekday_given = row[idx["요일"]].strip().removesuffix("요일")
        weekday_real = WEEKDAYS[sales_date.weekday()]
        if weekday_given != weekday_real:
            problems.append(
                f"{line_no}번째 줄: 요일이 날짜와 맞지 않아요. "
                f"({sales_date.isoformat()}은 {weekday_real}요일인데 '{row[idx['요일']].strip()}'(으)로 적혀 있어요)"
            )
            bad = True

        dates[sales_date] = dates.get(sales_date, 0) + 1
        if not bad:
            rows.append(SaleRow(code, category, quantity, amount))

    if len(dates) > 1:
        listed = ", ".join(d.isoformat() for d in sorted(dates))
        problems.insert(
            0, f"한 파일에는 하루치만 올릴 수 있어요. 파일에 날짜가 {len(dates)}개 섞여 있어요: {listed}"
        )

    if not problems and not dates:
        problems.append("올릴 데이터 줄이 없어요. ('합계' 줄은 올리지 않습니다)")

    if problems:
        if len(problems) > MAX_PROBLEMS_SHOWN:
            extra = len(problems) - MAX_PROBLEMS_SHOWN
            problems = problems[:MAX_PROBLEMS_SHOWN] + [f"…외 {extra}건"]
        raise FileProblems(problems)

    return ParsedSalesFile(sales_date=next(iter(dates)), rows=rows)

// 고른 CSV 안에서 매출 날짜(연도·달·일 열)를 미리 읽어 화면에 보여 줍니다. 읽지 못하면 null 이고, 올릴 때 서버가 다시 검사합니다.
const NEEDED = ["상품코드", "대분류", "연도", "달", "일"];

function splitLine(line, delimiter) {
  const cells = [];
  let cell = "";
  let quoted = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (ch === '"') {
      if (quoted && line[i + 1] === '"') {
        cell += '"';
        i++;
      } else {
        quoted = !quoted;
      }
    } else if (ch === delimiter && !quoted) {
      cells.push(cell);
      cell = "";
    } else {
      cell += ch;
    }
  }
  cells.push(cell);
  return cells.map((c) => c.trim());
}

function decode(buffer) {
  try {
    return new TextDecoder("utf-8", { fatal: true }).decode(buffer);
  } catch {
    return new TextDecoder("euc-kr").decode(buffer); // 상가 프로그램의 한글 CSV는 CP949인 경우가 많습니다
  }
}

export async function readSalesDate(file) {
  try {
    const lines = decode(await file.arrayBuffer())
      .replace(/^﻿/, "")
      .split(/\r?\n/)
      .filter((l) => l.trim());
    if (lines.length < 2) return null;
    const delimiter = [",", "\t", ";"].reduce((best, d) => (lines[0].split(d).length > lines[0].split(best).length ? d : best), ",");
    const header = splitLine(lines[0], delimiter);
    const at = Object.fromEntries(NEEDED.map((name) => [name, header.indexOf(name)]));
    if (NEEDED.some((name) => at[name] < 0)) return null;
    for (const line of lines.slice(1)) {
      const cells = splitLine(line, delimiter);
      if (cells[at["상품코드"]] === "-" || cells[at["대분류"]] === "합계") continue;
      const [y, m, d] = ["연도", "달", "일"].map((name) => Number(cells[at[name]]));
      const day = new Date(y, m - 1, d);
      if (Number.isInteger(y) && Number.isInteger(m) && Number.isInteger(d) && day.getFullYear() === y && day.getMonth() === m - 1 && day.getDate() === d) {
        return `${y}-${String(m).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
      }
      return null;
    }
    return null;
  } catch {
    return null;
  }
}

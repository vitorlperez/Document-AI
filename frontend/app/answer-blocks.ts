export type Block =
  | { kind: "heading"; level: number; text: string }
  | { kind: "paragraph"; text: string }
  | { kind: "list"; ordered: boolean; items: string[] }
  | { kind: "table"; header: string[]; rows: string[][] };

const splitRow = (line: string) => line.trim().replace(/^\||\|$/g, "").split("|").map((cell) => cell.trim());
const isTableSeparator = (line: string) => /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(line);
const listMarker = /^\s*(?:[-*•]|\d+[.)])\s+/;

/** Small, dependency-free markdown subset: headings, lists, tables, bold and code. Never emits raw HTML. */
export function parseAnswerBlocks(source: string): Block[] {
  const lines = source.replace(/\r\n/g, "\n").split("\n");
  const blocks: Block[] = [];
  let paragraph: string[] = [];
  const flush = () => { if (paragraph.length) blocks.push({ kind: "paragraph", text: paragraph.join(" ") }); paragraph = []; };
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (!line.trim()) { flush(); continue; }
    const heading = /^\s{0,3}(#{1,4})\s+(.*)$/.exec(line);
    if (heading) { flush(); blocks.push({ kind: "heading", level: heading[1].length, text: heading[2].trim() }); continue; }
    if (line.includes("|") && i + 1 < lines.length && isTableSeparator(lines[i + 1])) {
      flush();
      const header = splitRow(line);
      const rows: string[][] = [];
      i += 2;
      while (i < lines.length && lines[i].includes("|") && lines[i].trim()) rows.push(splitRow(lines[i++]));
      i--;
      blocks.push({ kind: "table", header, rows });
      continue;
    }
    if (listMarker.test(line)) {
      flush();
      const ordered = /^\s*\d/.test(line);
      const items: string[] = [];
      while (i < lines.length && listMarker.test(lines[i])) items.push(lines[i++].replace(listMarker, "").trim());
      i--;
      blocks.push({ kind: "list", ordered, items });
      continue;
    }
    const label = /^\s*\*\*([^*]+?):?\*\*:?\s*$/.exec(line);
    if (label) { flush(); blocks.push({ kind: "heading", level: 3, text: label[1].trim() }); continue; }
    paragraph.push(line.trim());
  }
  flush();
  return blocks;
}

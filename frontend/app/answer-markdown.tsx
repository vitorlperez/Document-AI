import { Fragment, type ReactNode } from "react";
import { FileText } from "lucide-react";

type Block =
  | { kind: "heading"; level: number; text: string }
  | { kind: "paragraph"; text: string }
  | { kind: "list"; ordered: boolean; items: string[] }
  | { kind: "table"; header: string[]; rows: string[][] };

const escapeRegExp = (value: string) => value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
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

function renderInline(text: string, fileNames: string[], keyPrefix: string): ReactNode[] {
  const names = [...fileNames].filter((name) => name.length > 2).sort((a, b) => b.length - a.length).map(escapeRegExp);
  const pattern = new RegExp(`(\\*\\*[^*]+\\*\\*|\`[^\`]+\`${names.length ? `|${names.join("|")}` : ""})`, "g");
  return text.split(pattern).filter((part) => part !== "").map((part, index) => {
    const key = `${keyPrefix}-${index}`;
    if (part.startsWith("**") && part.endsWith("**") && part.length > 4) return <strong key={key}>{renderInline(part.slice(2, -2), [], key)}</strong>;
    if (part.startsWith("`") && part.endsWith("`") && part.length > 2) return <code key={key} className="answer-code">{part.slice(1, -1)}</code>;
    if (fileNames.includes(part)) return <span key={key} className="answer-file-chip"><FileText size={13} aria-hidden="true" />{part}</span>;
    return <Fragment key={key}>{part.replace(/\*\*/g, "")}</Fragment>;
  });
}

export function AnswerMarkdown({ text, fileNames = [] }: { text: string; fileNames?: string[] }) {
  const blocks = parseAnswerBlocks(text);
  const leadIndex = blocks.length > 1 ? blocks.findIndex((block) => block.kind === "paragraph") : -1;
  return <div className="answer-body">{blocks.map((block, index) => {
    const key = `b${index}`;
    if (block.kind === "heading") {
      return block.level <= 2
        ? <h3 key={key} className="answer-heading">{renderInline(block.text, fileNames, key)}</h3>
        : <h4 key={key} className="answer-subheading">{renderInline(block.text, fileNames, key)}</h4>;
    }
    if (block.kind === "list") {
      const List = block.ordered ? "ol" : "ul";
      return <List key={key} className={block.ordered ? "answer-list answer-list-ordered" : "answer-list"}>{block.items.map((item, i) => <li key={i}>{renderInline(item, fileNames, `${key}-${i}`)}</li>)}</List>;
    }
    if (block.kind === "table") {
      return <div key={key} className="answer-table-wrap" tabIndex={0} role="region" aria-label="Tabela da resposta">
        <table className="answer-table">
          <thead><tr>{block.header.map((cell, i) => <th key={i} scope="col">{renderInline(cell, fileNames, `${key}h${i}`)}</th>)}</tr></thead>
          <tbody>{block.rows.map((row, r) => <tr key={r}>{row.map((cell, c) => <td key={c}>{renderInline(cell, fileNames, `${key}-${r}-${c}`)}</td>)}</tr>)}</tbody>
        </table>
      </div>;
    }
    return <p key={key} className={index === leadIndex ? "answer-lead" : "answer-paragraph"}>{renderInline(block.text, fileNames, key)}</p>;
  })}</div>;
}

import { Fragment, type ReactNode } from "react";
import { FileText } from "lucide-react";
import { parseAnswerBlocks } from "./answer-blocks";

const escapeRegExp = (value: string) => value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

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

import { Component, Fragment, type ReactNode } from "react";
import { FileText, ListChecks } from "lucide-react";
import { CITATION_MARKER, citationNumbers, parseAnswerBlocks, plainParagraphs, type Block, type ListItem } from "./answer-blocks";

const escapeRegExp = (value: string) => value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

type InlineContext = { fileNames: string[]; sourceNames: string[]; onCite?: (number: number) => void };

function CitationMarks({ marker, context, keyPrefix }: { marker: string; context: InlineContext; keyPrefix: string }) {
  const numbers = citationNumbers(marker).filter((number) => number >= 1 && number <= context.sourceNames.length);
  if (!numbers.length || !context.onCite) return <>{marker}</>;
  return <span className="answer-cite-group">{numbers.map((number) => {
    const name = context.sourceNames[number - 1];
    return <button key={`${keyPrefix}-${number}`} type="button" className="answer-cite" onClick={() => context.onCite?.(number)} aria-label={`Fonte ${number}: ${name}`} title={`Fonte ${number}: ${name}`}>{number}</button>;
  })}</span>;
}

function renderInline(text: string, context: InlineContext, keyPrefix: string, chips = true): ReactNode[] {
  const names = chips ? [...context.fileNames].filter((name) => name.length > 2).sort((a, b) => b.length - a.length).map(escapeRegExp) : [];
  const pattern = new RegExp(`(\\*\\*[^*]+\\*\\*|\`[^\`]+\`|${CITATION_MARKER.source}${names.length ? `|${names.join("|")}` : ""})`, "gi");
  return text.split(pattern).filter((part) => part !== "").map((part, index) => {
    const key = `${keyPrefix}-${index}`;
    if (part.startsWith("**") && part.endsWith("**") && part.length > 4) return <strong key={key}>{renderInline(part.slice(2, -2), context, key, chips)}</strong>;
    if (part.startsWith("`") && part.endsWith("`") && part.length > 2) return <code key={key} className="answer-code">{part.slice(1, -1)}</code>;
    if (new RegExp(`^${CITATION_MARKER.source}$`, "i").test(part)) return <CitationMarks key={key} marker={part} context={context} keyPrefix={key} />;
    if (chips && context.fileNames.includes(part)) return <span key={key} className="answer-file-chip"><FileText size={13} aria-hidden="true" />{part}</span>;
    return <Fragment key={key}>{part.replace(/\*\*/g, "")}</Fragment>;
  });
}

function ListItems({ items, context, keyPrefix, chips }: { items: ListItem[]; context: InlineContext; keyPrefix: string; chips: boolean }) {
  return <>{items.map((item, i) => <li key={i}>
    {renderInline(item.text, context, `${keyPrefix}-${i}`, chips)}
    {item.sub.length > 0 && <ul className="answer-list answer-sublist">{item.sub.map((sub, j) => <li key={j}>{renderInline(sub, context, `${keyPrefix}-${i}-${j}`, chips)}</li>)}</ul>}
  </li>)}</>;
}

function BlockView({ block, context, blockKey, lead, chips = true }: { block: Block; context: InlineContext; blockKey: string; lead?: boolean; chips?: boolean }): ReactNode {
  const inline = (text: string, suffix = "") => renderInline(text, context, `${blockKey}${suffix}`, chips);
  switch (block.kind) {
    case "heading":
      return block.level <= 2
        ? <h3 className="answer-heading">{inline(block.text)}</h3>
        : <h4 className="answer-subheading">{inline(block.text)}</h4>;
    case "list": {
      const List = block.ordered ? "ol" : "ul";
      return <List className={block.ordered ? "answer-list answer-list-ordered" : "answer-list"}><ListItems items={block.items} context={context} keyPrefix={blockKey} chips={chips} /></List>;
    }
    case "steps":
      return <section className="answer-steps" aria-label="Passo a passo">
        <p className="answer-steps-title"><ListChecks size={14} aria-hidden="true" />Passo a passo</p>
        <ol><ListItems items={block.items} context={context} keyPrefix={blockKey} chips={chips} /></ol>
      </section>;
    case "fields":
      return <dl className="answer-fields">{block.items.map((field, i) => <div key={i} className="answer-field">
        <dt>{inline(field.label, `l${i}`)}</dt><dd>{inline(field.value, `v${i}`)}</dd>
      </div>)}</dl>;
    case "table":
      return <div className="answer-table-wrap" tabIndex={0} role="region" aria-label="Tabela da resposta">
        <table className="answer-table">
          <thead><tr>{block.header.map((cell, i) => <th key={i} scope="col">{inline(cell, `h${i}`)}</th>)}</tr></thead>
          <tbody>{block.rows.map((row, r) => <tr key={r}>{row.map((cell, c) => <td key={c}>{inline(cell, `-${r}-${c}`)}</td>)}</tr>)}</tbody>
        </table>
      </div>;
    case "highlight":
      return <div className="answer-highlight">{block.children.map((child, i) => <BlockView key={i} block={child} context={context} blockKey={`${blockKey}-${i}`} chips={chips} />)}</div>;
    case "file": {
      const [first, ...rest] = block.children;
      const summary = first?.kind === "paragraph" ? first : null;
      const details = summary ? rest : block.children;
      return <section className="answer-file-card" aria-label={`Arquivo ${block.name}`}>
        <h4 className="answer-file-card-header">
          <span className="answer-file-chip"><FileText size={13} aria-hidden="true" />{block.name}</span>
          {block.marker && <CitationMarks marker={block.marker} context={context} keyPrefix={`${blockKey}-m`} />}
        </h4>
        {(summary || details.length > 0) && <div className="answer-file-card-body">
          {summary && <p className="answer-file-summary">{renderInline(summary.text, context, `${blockKey}-s`, false)}</p>}
          {details.map((child, i) => <BlockView key={i} block={child} context={context} blockKey={`${blockKey}-${i}`} chips={false} />)}
        </div>}
      </section>;
    }
    default:
      return <p className={lead ? "answer-lead" : "answer-paragraph"}>{inline(block.text)}</p>;
  }
}

/** Groups consecutive file cards so the list reads as one set with light dividers. */
function groupBlocks(blocks: Block[]): (Block | Block[])[] {
  const groups: (Block | Block[])[] = [];
  for (const block of blocks) {
    const last = groups[groups.length - 1];
    if (block.kind === "file" && Array.isArray(last)) last.push(block);
    else groups.push(block.kind === "file" ? [block] : block);
  }
  return groups;
}

function StructuredAnswer({ text, context }: { text: string; context: InlineContext }) {
  const blocks = parseAnswerBlocks(text, { fileNames: context.fileNames });
  const leadIndex = blocks.length > 1 ? blocks.findIndex((block) => block.kind === "paragraph") : -1;
  const leadBlock = leadIndex >= 0 ? blocks[leadIndex] : null;
  return <div className="answer-body">{groupBlocks(blocks).map((group, index) => {
    const key = `b${index}`;
    if (Array.isArray(group)) return <div key={key} className="answer-file-group">{group.map((block, i) => <BlockView key={i} block={block} context={context} blockKey={`${key}-${i}`} />)}</div>;
    return <BlockView key={key} block={group} context={context} blockKey={key} lead={group === leadBlock} />;
  })}</div>;
}

/** Any rendering failure falls back to the answer as plain paragraphs: the user always gets the text. */
class AnswerBoundary extends Component<{ text: string; children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() {
    if (!this.state.failed) return this.props.children;
    return <div className="answer-body">{plainParagraphs(this.props.text).map((block, i) => <p key={i} className="answer-paragraph">{block.kind === "paragraph" ? block.text : ""}</p>)}</div>;
  }
}

export function AnswerMarkdown({ text, fileNames = [], onCite }: { text: string; fileNames?: string[]; onCite?: (number: number) => void }) {
  const context: InlineContext = { fileNames: [...new Set(fileNames)], sourceNames: fileNames, onCite };
  return <AnswerBoundary text={text}><StructuredAnswer text={text} context={context} /></AnswerBoundary>;
}

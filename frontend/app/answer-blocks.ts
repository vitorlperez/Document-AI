/**
 * Presentation vocabulary of a chat answer. The synthesis prompt (backend ANSWER_FORMAT_GUIDANCE)
 * lets the model compose any of these; everything else is ordinary markdown:
 *   ## Title                      -> heading (section)
 *   ::: file <file name> … :::    -> file card: summary sentence + indented details
 *   ::: highlight … :::           -> highlight (direct summary / key point)
 *   ::: steps … :::               -> numbered step-by-step
 *   **Label:** value              -> fields (label/value pairs)
 *   **Label:** a | b | c          -> fields whose short items ("|"-separated) render as tags
 *   - item / 1. item, table       -> list, table
 * Unknown or malformed directives degrade to plain markdown; parsing never throws.
 */
export type ListItem = { text: string; sub: string[]; paragraphs?: string[] };
export type Field = { label: string; value: string; tags?: string[]; marker?: string };
export type Block =
  | { kind: "heading"; level: number; text: string }
  | { kind: "paragraph"; text: string }
  | { kind: "list"; ordered: boolean; start?: number; items: ListItem[] }
  | { kind: "fields"; items: Field[] }
  | { kind: "table"; header: string[]; rows: string[][] }
  | { kind: "file"; name: string; marker: string; children: Block[] }
  | { kind: "highlight"; children: Block[] }
  | { kind: "steps"; start?: number; items: ListItem[] };

export type ParseOptions = { fileNames?: string[] };

const splitRow = (line: string) => line.trim().replace(/^\||\|$/g, "").split("|").map((cell) => cell.trim());
const isTableSeparator = (line: string) => /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(line);
const listMarker = /^(\s*)(?:[-*•]|\d+[.)])\s+/;
const fieldLine = /^\s*(?:[-*•]\s+)?\*\*([^*\n]{1,60}?):\*\*\s*(\S.*)$|^\s*(?:[-*•]\s+)?\*\*([^*\n]{1,60}?)\*\*:\s*(\S.*)$/;
const directiveOpen = /^\s*:::\s*([A-Za-zÀ-ÿ-]+)\s*(.*?)\s*$/;
const directiveClose = /^\s*:::\s*$/;
const sectionTitle = /^\s{0,3}#{1,2}\s+\S/;
/** "(fonte 2)", "(fontes 1 e 3)", "(fontes 1, 2 e 3)" as written by the backend numbering step. */
export const CITATION_MARKER = /\((?:fonte|fontes)\s+\d+(?:\s*(?:,|e)\s*\d+)*\)/gi;

const DIRECTIVES: Record<string, "file" | "highlight" | "steps"> = {
  file: "file", arquivo: "file",
  highlight: "highlight", destaque: "highlight", resumo: "highlight", summary: "highlight",
  steps: "steps", passos: "steps", "passo-a-passo": "steps",
};

const normalizeName = (value: string) => value.replace(/\*\*|`/g, "").trim().replace(/[:.]$/, "").trim().toLocaleLowerCase();

export function citationNumbers(marker: string): number[] {
  return [...marker.matchAll(/\d+/g)].map((match) => Number(match[0]));
}

function parseField(line: string): Field | null {
  const match = fieldLine.exec(line);
  if (!match) return null;
  const label = (match[1] ?? match[3]).trim();
  const value = (match[2] ?? match[4]).trim();
  return label && value ? withTags({ label, value }) : null;
}

const TAG_SEPARATOR = /\s+\|\s+/;
const MAX_TAG_LENGTH = 48;
const TRAILING_MARKERS = new RegExp(`(?:\\s*${CITATION_MARKER.source})+\\s*$`, "i");

/** A value written as short "|"-separated items ("Python | SQL | Docker") is a tag list; a sentence never is. */
function withTags(field: Field): Field {
  const trailing = TRAILING_MARKERS.exec(field.value)?.[0] ?? "";
  const body = trailing ? field.value.slice(0, field.value.length - trailing.length) : field.value;
  const parts = body.split(TAG_SEPARATOR).map((part) => part.trim().replace(/[;,.]+$/, "")).filter(Boolean);
  const isList = parts.length >= 2 && parts.every((part) => part.length <= MAX_TAG_LENGTH && part.split(/\s+/).length <= 7);
  return isList ? { ...field, tags: parts.map((part) => part.replace(/\*\*|`/g, "")), marker: trailing.trim() } : field;
}

/** Flat markdown subset: headings, lists (one sub level), fields, tables and paragraphs. */
function parseMarkdown(lines: string[]): Block[] {
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
    if (parseField(line)) {
      flush();
      const items: Field[] = [];
      while (i < lines.length && parseField(lines[i])) items.push(parseField(lines[i++])!);
      i--;
      blocks.push({ kind: "fields", items });
      continue;
    }
    if (listMarker.test(line)) {
      flush();
      const ordered = /^\s*\d/.test(line);
      const start = ordered ? Number(/^\s*(\d+)/.exec(line)![1]) : 1;
      const baseIndent = listMarker.exec(line)![1].length;
      const items: ListItem[] = [];
      let newParagraph = false;
      while (i < lines.length) {
        const current = lines[i];
        const marker = listMarker.exec(current);
        if (marker) {
          const indent = marker[1].length;
          if (indent < baseIndent || (indent === baseIndent && /^\s*\d/.test(current) !== ordered)) break;
          const text = current.replace(listMarker, "").trim();
          if (indent > baseIndent && items.length) items[items.length - 1].sub.push(text);
          else items.push({ text, sub: [] });
          newParagraph = false;
          i++;
          continue;
        }
        if (!current.trim()) {
          let next = i + 1;
          while (next < lines.length && !lines[next].trim()) next++;
          const following = lines[next] ?? "";
          const nextMarker = listMarker.exec(following);
          const continues = nextMarker
            ? nextMarker[1].length >= baseIndent && (nextMarker[1].length > baseIndent || /^\s*\d/.test(following) === ordered)
            : /^\s+\S/.test(following) && following.length - following.trimStart().length > baseIndent;
          if (!continues) break;
          // Blank lines inside a loose list do not create independent ol elements.
          i = next;
          newParagraph = true;
          continue;
        }
        if (items.length && current.length - current.trimStart().length > baseIndent) {
          const item = items[items.length - 1];
          if (newParagraph) (item.paragraphs ??= []).push(current.trim());
          else if (item.paragraphs?.length) item.paragraphs[item.paragraphs.length - 1] += ` ${current.trim()}`;
          else item.text += ` ${current.trim()}`;
          newParagraph = false;
          i++;
          continue;
        }
        break;
      }
      i--;
      blocks.push({ kind: "list", ordered, ...(start !== 1 ? { start } : {}), items });
      continue;
    }
    const label = /^\s*\*\*([^*]+?):?\*\*:?\s*$/.exec(line);
    if (label) { flush(); blocks.push({ kind: "heading", level: 3, text: label[1].trim() }); continue; }
    paragraph.push(line.trim());
  }
  flush();
  return blocks;
}

function fileCard(header: string, children: Block[]): Block {
  const marker = (header.match(CITATION_MARKER) ?? []).join(" ");
  const name = header.replace(CITATION_MARKER, "").replace(/\*\*|`/g, "").trim();
  return { kind: "file", name, marker, children };
}

function directiveBlock(kind: "file" | "highlight" | "steps", argument: string, body: string[]): Block | Block[] {
  const children = parseMarkdown(body);
  if (kind === "file") return argument ? fileCard(argument, children) : children;
  if (kind === "highlight") return { kind: "highlight", children };
  const items = children.flatMap((block) => block.kind === "list" ? block.items : block.kind === "paragraph" ? [{ text: block.text, sub: [] }] : []);
  const firstList = children.find((block) => block.kind === "list");
  return items.length ? { kind: "steps", ...(firstList?.start ? { start: firstList.start } : {}), items } : children;
}

/**
 * When the model lists files without the file directive ("- Profile.pdf: summary", a bullet that is
 * only the file name followed by its details, or "### Profile.pdf"), present each file as a card too.
 * Only names of the answer's own cited documents are promoted.
 */
function promoteFileCards(blocks: Block[], fileNames: string[]): Block[] {
  const known = new Map(fileNames.filter((name) => name.trim().length > 2).map((name) => [normalizeName(name), name]));
  if (!known.size) return blocks;
  const fileOf = (text: string) => known.get(normalizeName(text.replace(CITATION_MARKER, "")));
  const out: Block[] = [];
  for (let index = 0; index < blocks.length; index++) {
    const block = blocks[index];
    if (block.kind === "heading" && block.level >= 3 && fileOf(block.text)) {
      const children: Block[] = [];
      while (index + 1 < blocks.length && !(blocks[index + 1].kind === "heading") && blocks[index + 1].kind !== "file") children.push(blocks[++index]);
      out.push(fileCard(block.text, children));
      continue;
    }
    if (block.kind !== "list" || block.ordered) { out.push(block); continue; }
    const headers = block.items.map((item) => {
      const colon = /^(.+?)(?:\s*\((?:fonte|fontes)[^)]*\))?\s*:\s+(.+)$/i.exec(item.text);
      if (colon && fileOf(colon[1])) return { name: colon[1], summary: item.text.slice(colon[1].length).replace(/^\s*:\s*/, "").trim() };
      if (fileOf(item.text)) return { name: item.text, summary: "" };
      return null;
    });
    if (!headers.some(Boolean) || !headers[0]) { out.push(block); continue; }
    const allRows = headers.every((header) => header?.summary);
    if (allRows) {
      block.items.forEach((item, i) => out.push(fileCard(headers[i]!.name, [
        { kind: "paragraph", text: headers[i]!.summary },
        ...(item.sub.length ? [{ kind: "list" as const, ordered: false, items: item.sub.map((text) => ({ text, sub: [] })) }] : []),
      ])));
      continue;
    }
    if (headers.some((header) => header && !header.summary)) {
      // Name-only bullets act as headers of the bullets that follow them.
      let card: { name: string; details: ListItem[]; lead: string } | null = null;
      const emit = () => {
        // The first detail of a name-only header reads as that file's summary sentence.
        if (card && !card.lead && card.details.length && !card.details[0].sub.length) card.lead = card.details.shift()!.text;
        if (card) out.push(fileCard(card.name, [...(card.lead ? [{ kind: "paragraph" as const, text: card.lead }] : []), ...(card.details.length ? [{ kind: "list" as const, ordered: false, items: card.details }] : [])]));
      };
      block.items.forEach((item, i) => {
        const header = headers[i];
        if (header) { emit(); card = { name: header.name, lead: header.summary, details: item.sub.map((text) => ({ text, sub: [] })) }; }
        else card!.details.push(item);
      });
      emit();
      continue;
    }
    out.push(block);
  }
  return out;
}

export function parseAnswerBlocks(source: string, options: ParseOptions = {}): Block[] {
  try {
    const lines = source.replace(/\r\n/g, "\n").split("\n");
    const blocks: Block[] = [];
    let plain: string[] = [];
    const flushPlain = () => { if (plain.length) blocks.push(...parseMarkdown(plain)); plain = []; };
    for (let i = 0; i < lines.length; i++) {
      const open = directiveOpen.exec(lines[i]);
      if (!open) {
        if (!directiveClose.test(lines[i])) plain.push(lines[i]);
        continue;
      }
      flushPlain();
      const kind = DIRECTIVES[open[1].toLocaleLowerCase()];
      const body: string[] = [];
      // A directive ends at its ":::", at the next directive, at a section title, or at the end of the answer.
      while (i + 1 < lines.length && !directiveClose.test(lines[i + 1]) && !directiveOpen.test(lines[i + 1]) && !sectionTitle.test(lines[i + 1])) body.push(lines[++i]);
      if (i + 1 < lines.length && directiveClose.test(lines[i + 1])) i++;
      if (!kind) { blocks.push(...parseMarkdown(open[2] ? [open[2], ...body] : body)); continue; }
      const parsed = directiveBlock(kind, open[2], body);
      blocks.push(...(Array.isArray(parsed) ? parsed : [parsed]));
    }
    flushPlain();
    return promoteFileCards(blocks, options.fileNames ?? []);
  } catch {
    return plainParagraphs(source);
  }
}

/** Last-resort shape: the raw text as paragraphs, never an empty answer. */
export function plainParagraphs(source: string): Block[] {
  return source.split(/\n{2,}/).map((text) => text.trim()).filter(Boolean).map((text) => ({ kind: "paragraph" as const, text: text.replace(/\n/g, " ") }));
}

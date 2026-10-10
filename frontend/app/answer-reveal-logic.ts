/**
 * Progressive reveal of an answer that already arrived whole (the API answers with one JSON body, not a stream).
 * The text is shown word by word, but only at cut points where the markdown and the "(fonte N)" citation
 * markers parse the same way they will in the final text, so nothing flickers into a different shape.
 */

/** Unclosed spans shorter than this are held back until they close; longer ones render as plain text instead. */
const OPEN_SPAN_HOLD = 80;
const OPEN_PAREN_HOLD = 28;
const MS_PER_UNIT = 28;
const MIN_DURATION_MS = 700;
const MAX_DURATION_MS = 3600;

function openSpanLength(prefix: string, marker: string): number {
  const parts = prefix.split(marker);
  if (parts.length % 2 === 1) return 0;
  return prefix.length - prefix.lastIndexOf(marker);
}

function isSafeCut(text: string, cut: number): boolean {
  if (cut >= text.length) return true;
  const prefix = text.slice(0, cut);
  const openParen = prefix.lastIndexOf("(");
  if (openParen > prefix.lastIndexOf(")") && prefix.length - openParen < OPEN_PAREN_HOLD && !prefix.slice(openParen).includes("\n")) return false;
  for (const marker of ["**", "`"]) {
    const open = openSpanLength(prefix, marker);
    if (open > 0 && open < OPEN_SPAN_HOLD) return false;
  }
  // A table row only becomes a row once complete: reveal it whole.
  const lineStart = prefix.lastIndexOf("\n") + 1;
  if (text.slice(lineStart, cut).trimStart().startsWith("|")) {
    const lineEnd = text.indexOf("\n", cut);
    const rest = text.slice(cut, lineEnd === -1 ? undefined : lineEnd);
    if (rest.trim() !== "") return false;
  }
  return true;
}

/** Ascending, safe prefix lengths ending at text.length (empty text has no cut points). */
export function revealPlan(text: string): number[] {
  const cuts: number[] = [];
  for (const match of text.matchAll(/\S+\s*/g)) {
    const cut = match.index + match[0].length;
    if (isSafeCut(text, cut)) cuts.push(cut);
  }
  if (text.length > 0 && cuts[cuts.length - 1] !== text.length) cuts.push(text.length);
  return cuts;
}

/** Roughly 28 ms per word, but never under 0.7 s and never over 3.6 s: long answers speed up instead of dragging. */
export function revealDurationMs(units: number): number {
  return Math.min(MAX_DURATION_MS, Math.max(MIN_DURATION_MS, units * MS_PER_UNIT));
}

/** How many cut points are visible after `elapsedMs` of a reveal that lasts `durationMs`. */
export function revealedUnits(total: number, elapsedMs: number, durationMs: number): number {
  if (total <= 0) return 0;
  if (elapsedMs >= durationMs) return total;
  return Math.min(total, Math.max(1, Math.ceil((Math.max(0, elapsedMs) / durationMs) * total)));
}

export function revealedText(text: string, cuts: number[], units: number): string {
  if (units >= cuts.length) return text;
  return units <= 0 ? "" : text.slice(0, cuts[units - 1]);
}

/** Keep source links and citation numbering in the document list, never in answer prose. */
export function cleanAnswerForDisplay(value: string | null): string | null {
  if (value === null) return null;
  let answer = value.split("\n").filter((line) => !isSourceLinkLine(line)).join("\n");
  answer = stripMarkdownLinks(answer);
  answer = answer.replace(/<\s*(?:https?:\/\/|www\.)[^>]+>/gi, "");
  answer = answer.replace(/\s*\(\s*[a-z][a-z0-9_]{1,40}\s*:\s*(?:https?:\/\/|www\.)[^)\n]*\)/gi, "");
  answer = answer.replace(/\b(?:https?:\/\/|www\.|(?:drive|docs)\.google\.com\/|notion\.(?:so|site)\/)[^\s<>]+/gi, (url) => {
    let suffix = "";
    let candidate = url;
    while (/[.,;:!?]$/.test(candidate)) {
      suffix = candidate.slice(-1) + suffix;
      candidate = candidate.slice(0, -1);
    }
    while (candidate.endsWith(")") && (candidate.match(/\)/g)?.length ?? 0) > (candidate.match(/\(/g)?.length ?? 0)) {
      suffix = ")" + suffix;
      candidate = candidate.slice(0, -1);
    }
    return suffix;
  });
  answer = answer.replace(/\[\d+\]/g, "")
    .replace(/\(\s*[a-z][a-z0-9_]{1,40}\s*:\s*\)/gi, "")
    .replace(/\(\s*\)/g, "");
  answer = answer.replace(/[ \t]+([,.;:!?])/g, "$1").replace(/[ \t]{2,}/g, " ");
  answer = answer.split("\n").filter((line) => !/^\s*(?:[-*]\s*)?(?:(?:fonte|fontes|source|sources|link|links|url)\s*[:\-]|[.,;:!?]+\s*$)/i.test(line)).join("\n");
  return answer.replace(/\n{3,}/g, "\n\n").trim();
}

function isSourceLinkLine(line: string): boolean {
  return /^\s*(?:[-*]\s*)?(?:(?:fonte|fontes|source|sources|link|links|url)\s*[:\-]|\[\d+\]:)/i.test(line)
    && /(?:https?:\/\/|www\.|(?:drive|docs)\.google\.com\/|notion\.(?:so|site)\/)/i.test(line);
}

function stripMarkdownLinks(value: string): string {
  const start = /\[([^\]]+)\]\(/g;
  const parts: string[] = [];
  let cursor = 0;
  for (const match of value.matchAll(start)) {
    const index = match.index;
    if (index < cursor) continue;
    let depth = 1;
    let end = index + match[0].length;
    while (end < value.length && depth > 0) {
      if (value[end] === "(") depth++;
      else if (value[end] === ")") depth--;
      end++;
    }
    if (depth !== 0) continue;
    parts.push(value.slice(cursor, index), match[1]);
    cursor = end;
  }
  parts.push(value.slice(cursor));
  return parts.join("");
}

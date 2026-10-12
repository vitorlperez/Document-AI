const normalizeSearch = (value: string) => value.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLocaleLowerCase("pt-BR").trim();
export function filterRecipients<T extends { name: string | null; email: string }>(items: T[], query: string): T[] {
  const search = normalizeSearch(query);
  return items.filter((item) => normalizeSearch(`${item.name ?? ""} ${item.email}`).includes(search));
}
export function validateWebhookUrl(value: string): string | null {
  try {
    const url = new URL(value.trim());
    if (url.protocol === "https:" && !url.username && !url.password && !url.hash && (!url.port || url.port === "443")) return null;
  } catch { /* Show the same actionable validation for malformed URLs. */ }
  return "Informe uma URL HTTPS válida, na porta 443, sem usuário, senha ou fragmento (#).";
}

export type LibraryIndexingState = "indexed" | "pending" | "failed" | "ignored" | "skipped" | "not_found_in_source";
export type LibraryIndexingFields = {
  indexing?: {
    state: LibraryIndexingState;
    error_code: string | null;
    document_id: string | null;
    workspace_folder_id: string | null;
    indexed_at: string | null;
  };
};
type StatusInput = LibraryIndexingFields & { workspace_documents?: unknown[]; name?: string };
export type IndexingPresentation = {
  label: string;
  description: string;
  tone: "success" | "pending" | "warning" | "error" | "neutral";
  icon: "check" | "clock" | "warning" | "error" | "file" | "lock" | "missing";
};

const indexed: IndexingPresentation = { label: "Indexado", description: "O conteúdo deste arquivo está disponível nas respostas da biblioteca.", tone: "success", icon: "check" };
const reasons: Record<string, IndexingPresentation> = {
  unsupported_file_type: { label: "Formato não suportado", description: "Converta o arquivo para um formato compatível e sincronize a pasta novamente.", tone: "warning", icon: "file" },
  empty_extracted_text: { label: "PDF escaneado (sem texto)", description: "Nenhum texto foi extraído. Envie uma versão com texto selecionável ou peça ao administrador para verificar o OCR.", tone: "warning", icon: "file" },
  file_too_large: { label: "Arquivo grande demais", description: "Divida ou reduza o arquivo na fonte e sincronize a pasta novamente.", tone: "warning", icon: "warning" },
  file_encrypted: { label: "PDF protegido por senha", description: "Disponibilize uma cópia sem senha na fonte e sincronize a pasta novamente.", tone: "warning", icon: "lock" },
  empty_content: { label: "Arquivo vazio", description: "Adicione conteúdo ao arquivo na fonte e sincronize a pasta novamente.", tone: "neutral", icon: "file" },
  source_file_unavailable: { label: "Falha ao ler o arquivo", description: "Confira se o arquivo abre na fonte e se a integração tem acesso. Depois, sincronize a pasta novamente.", tone: "error", icon: "error" },
  text_extraction_failed: { label: "Falha ao ler o arquivo", description: "Confira se o arquivo está íntegro. Salve uma nova cópia na fonte e sincronize a pasta novamente.", tone: "error", icon: "error" },
  plan_limit_exceeded: { label: "Limite do plano atingido", description: "Peça ao administrador para conferir a cota do plano antes de sincronizar novamente.", tone: "warning", icon: "warning" },
  ocr_budget_exceeded: { label: "Limite de OCR atingido", description: "O limite de OCR desta sincronização foi atingido. Tente sincronizar a pasta novamente.", tone: "warning", icon: "warning" },
  ocr_failed: { label: "Falha no reconhecimento de texto", description: "Envie uma cópia mais legível ou com texto selecionável e sincronize a pasta novamente.", tone: "error", icon: "error" },
  ocr_document_too_large: { label: "PDF com páginas demais para OCR", description: "Divida o PDF em arquivos menores e sincronize a pasta novamente.", tone: "warning", icon: "warning" },
  embedding_failed: { label: "Falha ao preparar a busca", description: "Não foi possível preparar o conteúdo para busca. Sincronize a pasta novamente; se persistir, peça ajuda ao administrador.", tone: "error", icon: "error" },
};
reasons.empty_document = reasons.empty_content;

/** Explicit backend state wins; older payloads alone fall back to document references. */
export function libraryIndexingPresentation(item: StatusInput): IndexingPresentation {
  const status = item.indexing?.state;
  if (status === "indexed") return indexed;
  if (status === "not_found_in_source") return { label: "Não encontrado na fonte", description: "O arquivo não foi encontrado na fonte conectada. Confira se foi movido ou excluído e sincronize a pasta novamente.", tone: "warning", icon: "missing" };
  if (status === "failed" || status === "ignored" || status === "skipped") {
    const code = item.indexing?.error_code ?? "";
    const reason = Object.hasOwn(reasons, code) ? reasons[code] : undefined;
    if (reason) return reason;
    return { label: status === "failed" ? "Falha na indexação" : status === "ignored" ? "Arquivo ignorado" : "Indexação não realizada", description: "Este arquivo não foi indexado. Confira o arquivo e o histórico de sincronizações; peça ajuda ao administrador se o problema continuar.", tone: status === "failed" ? "error" : "warning", icon: status === "failed" ? "error" : "warning" };
  }
  // The v1 contract requires unknown future states to behave like pending.
  if (item.indexing) return { label: "Aguardando indexação", description: "Ainda não há conteúdo indexado. Aguarde a próxima sincronização ou sincronize a pasta e atualize a biblioteca.", tone: "pending", icon: "clock" };
  if ((item.workspace_documents?.length ?? 0) > 0) return indexed;
  return { label: "Ainda não processado", description: "Não há um resultado de indexação disponível. Sincronize a pasta ou consulte o histórico de sincronizações.", tone: "neutral", icon: "clock" };
}

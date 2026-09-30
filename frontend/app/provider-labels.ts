const PROVIDER_LABELS: Record<string, string> = {
  google_drive: "Google Drive",
  onedrive: "OneDrive",
  sharepoint: "SharePoint",
  notion: "Notion",
};

export function providerLabel(provider: string | null | undefined): string {
  return PROVIDER_LABELS[provider ?? ""] ?? "Google Drive";
}

const OAUTH_ERRORS: Record<string, string> = {
  onedrive_account_mismatch: "Esta fonte já pertence a outra conta OneDrive. Reconecte com a mesma conta para preservar as pastas indexadas.",
  onedrive: "Não foi possível conectar o OneDrive. Tente novamente.",
  sharepoint_tenant_mismatch: "Esta fonte SharePoint pertence a outra organização Microsoft 365 (outro tenant). Reconecte com uma conta da mesma organização.",
  sharepoint_admin_consent: "Sua organização Microsoft 365 exige aprovação do administrador para conectar o SharePoint. Peça ao administrador para autorizar o acesso e tente novamente.",
  sharepoint: "Não foi possível conectar o SharePoint. Tente novamente.",
  onedrive_unavailable: "A integração com o OneDrive não está configurada neste ambiente. Peça ao administrador da plataforma para habilitá-la.",
  sharepoint_unavailable: "A integração com o SharePoint não está configurada neste ambiente. Peça ao administrador da plataforma para habilitá-la.",
};

export function oauthErrorMessage(code: string | null | undefined): string | null {
  return OAUTH_ERRORS[code ?? ""] ?? null;
}

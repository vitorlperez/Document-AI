import { driveShareEnabled } from "./drive-share-logic";

/** Feature flag do modo "e-mail-robô" (Google Drive). Desligada (padrão) = a tela de Integrações fica idêntica à atual.
 * Ligue com NEXT_PUBLIC_DRIVE_SHARE_ENABLED=1 (ou VITE_DRIVE_SHARE_ENABLED=1). O backend continua a decidir por organização (GOOGLE_SA_ALLOWED_ORGS). */
export const DRIVE_SHARE_ENABLED = driveShareEnabled(
  (import.meta as unknown as { env?: Record<string, string | undefined> }).env?.VITE_DRIVE_SHARE_ENABLED ?? process.env.NEXT_PUBLIC_DRIVE_SHARE_ENABLED,
);

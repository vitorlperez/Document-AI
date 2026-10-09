const ACTIVE_ORGANIZATION_KEY = "arquivio:active-organization";
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

/** Last organization the user entered, kept per browser so the picker can highlight it. Storage may be unavailable. */
export function readActiveOrganizationId(): string | null {
  try {
    const value = window.localStorage.getItem(ACTIVE_ORGANIZATION_KEY);
    return value && UUID.test(value) ? value : null;
  } catch { return null; }
}

export function writeActiveOrganizationId(id: string) {
  try { window.localStorage.setItem(ACTIVE_ORGANIZATION_KEY, id); } catch { /* storage unavailable */ }
}

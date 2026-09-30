import assert from "node:assert/strict";
import test from "node:test";

import { oauthErrorMessage, providerLabel } from "../app/provider-labels.ts";

test("providerLabel names every provider", () => {
  assert.equal(providerLabel("sharepoint"), "SharePoint");
  assert.equal(providerLabel("onedrive"), "OneDrive");
  assert.equal(providerLabel("google_drive"), "Google Drive");
  assert.equal(providerLabel("notion"), "Notion");
});

test("oauthErrorMessage explains tenant mismatch and admin consent for SharePoint", () => {
  assert.match(oauthErrorMessage("sharepoint_tenant_mismatch"), /outra organização Microsoft/i);
  assert.match(oauthErrorMessage("sharepoint_admin_consent"), /administrador/i);
  assert.match(oauthErrorMessage("sharepoint"), /SharePoint/);
  assert.match(oauthErrorMessage("onedrive_account_mismatch"), /outra conta OneDrive/);
  assert.equal(oauthErrorMessage(null), null);
  assert.equal(oauthErrorMessage("unknown"), null);
});

test("oauthErrorMessage explains unconfigured Microsoft providers", () => {
  assert.match(oauthErrorMessage("sharepoint_unavailable"), /SharePoint.*não está configurada/i);
  assert.match(oauthErrorMessage("onedrive_unavailable"), /OneDrive.*não está configurada/i);
});

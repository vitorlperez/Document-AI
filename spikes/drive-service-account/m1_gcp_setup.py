"""Medicao 1: estado do projeto-pool no Google Cloud (somente leitura, via gcloud do dono). Sem segredos: so IDs publicos, politicas e cotas."""
import json
import subprocess

from lib import save_result

P = "arquivio-drive-poc"
G = "/opt/homebrew/bin/gcloud"


def gc(*args):
    return subprocess.run([G, *args], capture_output=True, text=True, timeout=120).stdout


proj = json.loads(gc("projects", "describe", P, "--format=json"))
sas = json.loads(gc("iam", "service-accounts", "list", "--project", P, "--format=json"))
eff = gc("org-policies", "describe", "iam.disableServiceAccountKeyCreation", "--effective", f"--project={P}")
org_policy_on_org = gc("org-policies", "describe", "iam.disableServiceAccountKeyCreation", "--organization=452494134551")
keys = {}
for sa in sas:
    k = json.loads(gc("iam", "service-accounts", "keys", "list", "--iam-account", sa["email"], "--format=json"))
    keys[sa["email"]] = [{"keyType": x["keyType"], "validAfterTime": x["validAfterTime"], "validBeforeTime": x["validBeforeTime"]} for x in k]
org_iam = json.loads(gc("organizations", "get-iam-policy", "452494134551", "--format=json"))
policy_admin_still_granted = any(b["role"] == "roles/orgpolicy.policyAdmin" for b in org_iam.get("bindings", []))
tok = gc("auth", "print-access-token").strip()
import httpx
q = httpx.get(f"https://serviceusage.googleapis.com/v1beta1/projects/{P}/services/iam.googleapis.com/consumerQuotaMetrics?view=BASIC",
              headers={"Authorization": f"Bearer {tok}", "x-goog-user-project": P}, timeout=60).json()
quotas = [{"metric": m.get("displayName"), "unit": l.get("unit"), "limit": b.get("effectiveLimit")}
          for m in q.get("metrics", []) for l in m.get("consumerQuotaLimits", []) for b in l.get("quotaBuckets", [])
          if any(w in (m.get("displayName") or "").lower() for w in ("service account", "key"))]
print(save_result("m01-gcp-setup", {
    "project": {"id": proj["projectId"], "number": proj["projectNumber"], "parent_type": proj["parent"]["type"], "org_created": "2026-09-12 (organizations/452494134551)"},
    "service_accounts": [s["email"] for s in sas], "keys_per_sa_now": {k: [x["keyType"] for x in v] for k, v in keys.items()},
    "service_account_count_quota": quotas,
    "org_policy_iam.disableServiceAccountKeyCreation": {
        "organization_level_before": "enforce: true (listado em `gcloud org-policies list --organization`, ao lado de disableServiceAccountKeyUpload, uniformBucketLevelAccess etc.)",
        "project_effective_before_exception": "enforce: true (observado antes de criar a excecao)",
        "key_creation_attempt_before_exception": "FAILED_PRECONDITION: 'Key creation is not allowed on this service account' (constraints/iam.disableServiceAccountKeyCreation)",
        "exception_applied": "policy no projeto arquivio-drive-poc com enforce:false (exigiu papel roles/orgpolicy.policyAdmin concedido NO NIVEL DA ORGANIZACAO; o Google rejeitou conceder no projeto)",
        "propagation": "criacao de chave seguiu bloqueada por ~60-90 s apos set-policy (2 tentativas falhas, 3a OK, intervalo de 30 s)",
        "project_effective_now": eff.strip().replace("\n", " | "),
    },
    "orgpolicy_admin_role_still_granted_on_org": policy_admin_still_granted,
}))

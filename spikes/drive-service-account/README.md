# PoC "e-mail-robô" (service account por organização) — M58

Spike isolado, sem tocar no produto. Resultado: `specs/google/drive-service-account-poc-result.md`;
desenho: `specs/google/drive-service-account-design.md` (§7 = as 13 medições).

```
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
# chaves JSON dos robôs: ~/.config/arquivio-drive-poc/sa-a.json e sa-b.json (FORA do repo; nunca commitar/logar)
.venv/bin/python make_fixtures.py        # gera fixtures/ (ignorado pelo git) para arrastar ao Drive
.venv/bin/python m1_gcp_setup.py         # medição 1 (gcloud do dono, só leitura)
.venv/bin/python m2_token.py             # medição 2: JWT bearer, latência, skew
.venv/bin/python m3_watch.py a 1500 2    # medição 3: mede visibilidade de pasta recém-compartilhada (sharedWithMeTime)
.venv/bin/python discover.py [link_publico]   # guarda IDs das pastas em ~/.config/arquivio-drive-poc/state.json
.venv/bin/python m4_fields.py ; .venv/bin/python m4b_roles.py <tag>   # medição 4
.venv/bin/python m5_isolation.py         # medição 5: robô B x pasta do robô A / link público
.venv/bin/python m6_watch.py 900 5 <nome># medição 6: changes.list + plano B (modifiedTime) + acesso à raiz
.venv/bin/python m7_content.py           # medição 7: alt=media, export, download bloqueado
.venv/bin/python m11_load.py             # medição 11: 1000 arquivos/50 pastas + simulação de 20 orgs
.venv/bin/python m13_links.py            # medição 13: parser de links + regra de compartilhamento explícito
```

Escopo sempre `drive.readonly`. `results/*.json` guardam só códigos HTTP, motivos, contagens, tempos, nomes de fixtures e e-mails mascarados
(token, JWT e chave privada nunca são gravados). Itens 8–10 e 12 (exigem Google Workspace) **não foram executados**.

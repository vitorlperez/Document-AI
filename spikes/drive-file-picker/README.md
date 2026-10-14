# PoC drive.file + Google Picker (ADR-0017 B7.0)

Spike isolado, sem tocar no produto. Resultado em `specs/google/drive-file-poc-result.md`.

```
# credenciais (nunca commitar): GOOGLE_OAUTH_CLIENT_ID no .env da raiz; GOOGLE_PICKER_API_KEY no .env da raiz
# ou em spikes/drive-file-picker/.env.local (ignorado pelo git)
python3 spikes/drive-file-picker/server.py     # http://localhost:8765
```

Console Google necessário: Drive API + Picker API habilitadas; API key (restrita à Picker API); no cliente OAuth Web,
origem JS `http://localhost:8765` e redirect `http://localhost:8765/` (fluxo "1b" quando o popup do GIS é bloqueado).

Fluxo: login (escopo único `drive.file`) → Picker (pasta / pasta em visão só de pastas / vários arquivos) →
`/verify?phase=baseline` → criar arquivos novos pela UI do Drive → `/verify?phase=after` → `/control` (controle positivo).
Tokens ficam só na memória do processo; `results/*.json` guardam apenas códigos HTTP, contagens e nomes.
`fixtures/` (arquivos aleatórios para subir ao Drive) é ignorado pelo git.

# Chaves de cifra por provider

API e worker devem receber as mesmas chaves de cada provider. Google usa
`GOOGLE_TOKEN_ENCRYPTION_KEY`, OneDrive usa `MICROSOFT_TOKEN_ENCRYPTION_KEY` e
Notion usa `NOTION_TOKEN_ENCRYPTION_KEY` e ClickUp usa `CLICKUP_TOKEN_ENCRYPTION_KEY`. Em
produção, chaves preenchidas devem ser distintas e Notion/ClickUp habilitados
exigem sua própria chave (ClickUp não tem fallback legado).

Para gerar uma chave em um terminal seguro:

```sh
python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
```

Não copie chaves, credenciais ou cursores para logs, tickets ou documentação.

## Migração do Notion

1. Configure a chave própria do Notion em API e worker e mantenha
   `NOTION_TOKEN_ENCRYPTION_LEGACY_FALLBACK=true` durante a janela de migração.
2. Faça deploy dos dois serviços. A primária cifra; a antiga chave Google só lê tokens legados.
3. No diretório `backend/`, rode `python -m scripts.rekey_sources --provider notion`.
   O padrão é dry-run: valida os tokens e imprime apenas contagens.
4. Confira as contagens e execute `python -m scripts.rekey_sources --provider notion --apply`.
   Fontes e checkpoints do provider são atualizados na mesma transação.
5. Repita o dry-run; exija `rotated == 0` e `cursors == 0`.
6. Defina `NOTION_TOKEN_ENCRYPTION_LEGACY_FALLBACK=false` em API e worker e faça redeploy.

Rollback: reative o fallback `true`, mantenha as chaves Notion e Google, e faça
redeploy. Nunca restaure somente a chave antiga depois de recifrar os tokens.
Um erro no rekey aborta a transação; confirme a configuração antes de tentar novamente.

## Rotação periódica

Revise as chaves anualmente. `CredentialCipher` e `OneDriveCipher` aceitam
`fallback_keys`: configure a nova primária e as antigas no keyring, recifre
credenciais e cursores, confira o dry-run e remova as antigas após a janela.
A CLI lê o keyring oferecido por `Settings.cipher_keys`; atualmente o fallback
configurável em ambiente é o Google legado do Notion. Rotação geral de Google e
OneDrive exige disponibilizar as antigas em `fallback_keys` na operação; não
substitua a variável primária antes de tornar a chave antiga disponível.

Não há migração Alembic nesta fase: o ciphertext continua nas colunas existentes.

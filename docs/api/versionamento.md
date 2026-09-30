# Versionamento da API pública

A versão maior faz parte do caminho: `/v1`. Campos opcionais e endpoints novos são aditivos. Clientes devem ignorar campos desconhecidos na resposta.

Remover ou renomear campos/endpoints, alterar sua semântica ou mudar regras incompatíveis exige `/v2`. Haverá pelo menos seis meses de sobreposição, com cabeçalhos `Deprecation` (RFC 9745) e `Sunset` (RFC 8594) na v1 antes da retirada. Mudanças são registradas em [CHANGELOG.md](CHANGELOG.md).

O contrato publicado em `/v1/openapi.json` corresponde a [openapi-v1.json](openapi-v1.json). `cd backend && .venv/bin/python scripts/export_openapi.py --check` detecta mudanças não exportadas sem acessar rede.

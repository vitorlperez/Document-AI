# PoC B7.0 (ADR-0017): `drive.file` + Google Picker sustenta o sync de pasta?

Data: 13/10/2026 · Spike: `spikes/drive-file-picker/` (servidor local `http://localhost:8765`, Google Identity Services + Picker + chamadas diretas à Drive API v3) · Conta de teste: Gmail pessoal, projeto Google Cloud existente (cliente OAuth "Document AI Local").

## Veredito

**`drive.file` NÃO SUSTENTA o modelo "pasta recursiva + arquivos novos".** Escolher uma pasta no Picker concede acesso à **pasta em si**, não aos filhos nem aos netos, existentes ou novos. A hipótese em aberto em `google-drive-deploy-review.md` §3.1 ("escolher a pasta libera os filhos?") está respondida: **não**.

## Preparação

- Escopo solicitado: apenas `https://www.googleapis.com/auth/drive.file`. A tela de consentimento mostrou só "ver, editar, criar e excluir apenas os arquivos do Google Drive que você usa com este app".
- Fixture no Drive (subida pela UI do Drive, ou seja, "criada pelo usuário", o cenário real):
  `poc-drivefile/` {`raiz-1.txt`, `raiz-2.txt`, `sub/` {`filho-1.txt`, `filho-2.txt`, `sub2/` {`neto-1.txt`}}} + `solto-1.txt` e `solto-2.txt` na raiz do Meu Drive. Confirmado pelo usuário no Drive web antes dos testes: 5 arquivos + 2 subpastas dentro da pasta.
- Picker com `DocsView(DOCS).setIncludeFolders(true).setSelectFolderEnabled(true)` (modo "pasta"), `DocsView(FOLDERS).setSelectFolderEnabled(true)` (visão só de pastas) e `Feature.MULTISELECT_ENABLED` (vários arquivos). `setDeveloperKey` + `setAppId` (número do projeto) preenchidos.

## Resultados (evidência: `spikes/drive-file-picker/results/*.json`)

### (a) Filhos e netos já existentes

| Escolha no Picker | `files.get(<id>)` | `files.list q='<id>' in parents and trashed=false` | Itens visíveis ao app (`files.list` sem filtro) |
|---|---|---|---|
| Pasta, modo `setSelectFolderEnabled(true)` | **200** | **200, 0 filhos** (esperado: 2 arquivos + `sub/`) | — |
| Pasta, visão `FOLDERS` | **200** | **200, 0 filhos** | — |
| 2 arquivos (`MULTISELECT_ENABLED`) | **200** nos dois | n/a | — |
| Download dos 2 arquivos escolhidos | `files.get alt=media` → **200**, 269 bytes cada | | |
| Total | | | **3**: `poc-drivefile`, `solto-1.txt`, `solto-2.txt` (200, 1 chamada) |

- Nenhum filho nem neto (`raiz-*`, `sub`, `filho-*`, `sub2`, `neto-1`) apareceu: 0 de 5 arquivos e 0 de 2 subpastas. Sem 403/404: a Drive API devolve lista vazia (200), não erro, o que é mais perigoso porque parece "pasta vazia".
- Seleção múltipla de **arquivos** funciona como esperado: cada arquivo escolhido é legível/baixável; o Picker não expande pastas.
- A concessão por arquivo **persistiu entre tokens**: após o token expirar (HTTP 401 após ~1 h) e novo login, `files.get` voltou 200 para a pasta e os 2 arquivos, sem repetir o Picker.

### (b) Arquivos novos criados depois na pasta

Criados pela UI do Drive após o baseline: `NOVO-na-raiz-da-pasta.txt` em `poc-drivefile/`, `NOVO-na-subpasta.txt` em `sub/`, `NOVO-no-neto.txt` em `sub/sub2/`.

| Chamada (token novo, 22:56) | Resultado |
|---|---|
| `files.list ... in parents` na pasta escolhida | **200, 0 filhos** (os 3 novos **não** aparecem) |
| `files.list` sem filtro | **200, 3 itens**, idêntico ao baseline (nenhum novo) |
| `changes.list` desde o `startPageToken` do baseline | **200, 1 mudança**: apenas a **própria pasta** `poc-drivefile` (metadado alterado); **nenhuma** das 3 mudanças dos arquivos novos |

### Controle positivo

O próprio app criou `criado-pelo-app.txt` na pasta escolhida (`files.create` com `parents=[<pasta>]` → **200**). Em seguida `files.list ... in parents` → **200, 1 filho: só `criado-pelo-app.txt`** (os 3+ arquivos que o usuário colocou continuam invisíveis) e `files.get alt=media` → **200**, 24 bytes. Conclusão do controle: o `drive.file` expõe só o que o **app criou** ou o usuário **abriu/escolheu individualmente**; o código de listagem e o token do spike estão corretos (não é falha de teste).

## O que isso implica

1. **Migrar para `drive.file` + Picker quebraria o produto** como descrito em §3.1: sync recursivo de pasta e captação automática de arquivos novos (`changes.list`) deixariam de funcionar. O usuário teria que reabrir o Picker e marcar arquivos individualmente a cada novo documento, sem expansão de pasta. Isso é um produto diferente.
2. **Decisão A fica comprovada: manter `drive.readonly`** (restrito: CASA, verificação e renovação anual). O "não" do PoC é a justificativa técnica concreta para o formulário de verificação do Google ("por que não `drive.file`?"): o escopo menos permissivo testado não permite listar nem ler filhos de uma pasta escolhida nem ver arquivos novos, requisito central do produto. Citar este documento e os `results/*.json` como evidência.
3. **Eliminar CASA com `drive.file` só é possível mudando o produto** (ex.: sync manual por arquivo via Picker, ou o app criar e gerenciar a pasta). Não testado: se arquivos que o usuário solta numa pasta **criada pelo app** ficam visíveis; a documentação indica que não (acesso por arquivo, não por pasta), então não é uma saída.
4. O `list_folders` do app (varre todas as pastas) continua exigindo `drive.readonly`/`drive`; com `drive.file` o seletor de pasta teria que ser o Picker.

## Limites do PoC

Uma conta pessoal, um tipo de arquivo (`.txt`, sem Google Docs/Sheets para `export`), sem Drives compartilhados, sem Workspace. O 200 vazio foi reproduzido com dois tokens distintos e dois modos de Picker. Não testado: pasta compartilhada por outra conta, arquivos escolhidos individualmente que são **modificados** depois (`changes.list` sobre eles). Estado do Drive de teste: sobrou `criado-pelo-app.txt` em `poc-drivefile/` (pode apagar), assim como a API key criada para o spike (recomenda-se apagá-la ou restringi-la).

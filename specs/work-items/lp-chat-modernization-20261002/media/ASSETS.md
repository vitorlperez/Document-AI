# ASSETS — LP Arquivio (direção A, H2 aprovado)

Gerado em 2026-10-02. Único asset de mídia da LP; vídeo/áudio indisponíveis e fora de escopo.

## I-01 — document-context

| Campo | Valor |
|---|---|
| Arquivo publicado | `frontend/public/landing/document-context.webp` |
| Origem | Gerado (asset próprio, nenhum asset de terceiros/referência usado) |
| Ferramenta | `overclock_media_generate` kind=image, provider `codex-cli` (Codex CLI, plano ChatGPT, sem API key). google/openai-image não configurados; não usados |
| Bruto | 1448×1086 PNG RGB, 1.223.182 B (scratchpad, não publicado) |
| Pós-processo | Recorte 880×660 em torno do conteúdo, resize LANCZOS para 640×480 (2× de 320×240), WebP q82 method 6 (Pillow 12.3) |
| Final | 640×480 (4:3), **3.946 B (~3,9 KB)**, fundo medido (245,247,243) = #F5F7F4 |
| Exibição | 320×240 CSS, `<img alt="" aria-hidden="true" width="320" height="240" loading="lazy" decoding="async">`, junto de Rotina, ≤12% da área da seção, decorativo/estático |
| Fallback PNG | Não publicado (272 KB, sem ganho; WebP é suportado por todos os navegadores-alvo). A LP deve funcionar sem a imagem |

### Prompt (lint F1–F6 sem falhas, ~85 palavras)

> Three sheets of paper arranged in a gentle diagonal, linked by two thin curved connector lines between them, small and centered with generous empty margin. Sheets are blank: no letters, no numbers, no text, no logos, no interface elements, no faces. Subtle embossed paper relief, soft shallow shadows, clean modern flat-minimal look. Style Block: delicate paper relief on a flat #F5F7F4 background, teal #1C6052 accents on edges and connector lines, dark ink #142B25 for fine details, one tiny #D9F279 lime dot as the only bright signal, single soft top-left light, no gradients. Landscape 4:3.

### Inspeção visual (Read do PNG bruto e do WebP final)

- Três folhas em branco ligadas por dois fios finos em diagonal; cantos dobrados em #1C6052, bordas inferiores/laterais verde, pontos de conexão em #142B25 e um ponto #D9F279.
- Sem letras, números, logos, UI ou rostos. Relevo de papel sutil, sem gradiente de fundo.
- 1 geração, sem retry. Observação: o CLI ignora `aspect`; 4:3 saiu natural (1448×1086).

### Notas para quem integra

- Fundo = --bg, então a imagem se funde à superfície clara; se a seção Rotina usar outro fundo, aplicar `mix-blend-mode`/fundo igual ou pedir nova geração.
- Lima é só ornamento (nunca texto). Chat e fontes continuam em HTML/texto; esta imagem nunca carrega conteúdo.

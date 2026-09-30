# Spike F0.3 — Docling Serve / OCR português

Data: 2026-09-29. Execução real em Docker local ARM64, limitado a 1 CPU (`--cpus=1`), sem memória limitada. **Não é medição no Railway ou Oracle:** gate do ambiente-alvo permanece pendente. Nenhum arquivo real de cliente foi enviado.

## Imagem e pré-requisito encontrado

`quay.io/docling-project/docling-serve-cpu:v1.35.0`, digest `sha256:79e5fcd19ab227ed36323fa5fa31820d14d53efc4f073417ba37be7931c7af0a`; tamanho local 2.142.208.932 bytes. OpenAPI lida do container em `/openapi.json` (docs em `/docs`).

A imagem traz somente `eng` e `osd` no Tesseract. Primeiro ensaio com `ocr_lang=["por","eng"]` retornou HTTP 404, `detail="Task result not found. Please wait for a completion status."`; log do worker identificou falta de `por.traineddata`. Não interpretar esse 404 como PDF sem texto. Foi instalado no container descartável `/usr/share/tesseract/tessdata/por.traineddata` de [tessdata_fast oficial](https://github.com/tesseract-ocr/tessdata_fast/blob/main/por.traineddata). **F4 precisa de imagem derivada pinada com português**, sem download de pesos durante jobs; não publicar a imagem base como pronta para PT-BR.

## Contrato confirmado

POST `/v1/convert/source`, JSON:

```json
{"sources":[{"kind":"file","filename":"clean.pdf","base64_string":"<PDF base64>"}],"options":{"to_formats":["json","text"],"do_ocr":true,"force_ocr":true,"ocr_preset":"tesseract","ocr_lang":["por","eng"],"do_table_structure":false,"document_timeout":180}}
```

Resposta: `status`, `errors`, `processing_time`, `document`. Texto completo em `document.text_content`. Texto por página: `document.json_content.texts[*].text` e cada item `prov[*].page_no` (1-based), **não** separar `text_content` por form-feed. `json_content.pages` contém metadados por página. Tabelas usam `tables[*].data.table_cells[*].text`; preservar provenance ao extraí-las, sem depender só de `texts`. A fixture `backend/tests/fixtures/ocr_pt/docling_serve_response.json` é resposta real do PDF sintético de 3 páginas, sem dados de cliente. Engine/schema local: `DoclingDocument` 1.10.0.

## Corpus e medidas

A4, 2480×3508 px, 300 dpi. Texto sintético: “Ação e informação: contratação em São Paulo.”, preço/vencimento e “Órgão público: café, açúcar, maçã, lingüiça.”. Três PDFs: limpo (1 pág), girado 2° + 10.000 pontos cinza de ruído com seed 11 (1 pág), limpo multipágina (3 págs). Medidas do segundo ensaio (pipeline já quente); primeira conversão fria anterior: 14,110 s.

| PDF | Páginas | HTTP / status | Total s | s/pág |
|---|---:|---|---:|---:|
| clean | 1 | 200 / success | 8.103 | 8.103 |
| rotated | 1 | 200 / success | 8.079 | 8.079 |
| multipage | 3 | 200 / success | 18.083 | 6.028 |
| protected | 1 | 200 / failure | 2.054 | 2.054 |
| corrupt | 1 | 200 / failure | 2.021 | 2.021 |

Mediana das médias por documento: 8.079 s/pág; p95 nearest-rank: 8.103 s/pág (**n=3 documentos**, não p95 robusto de latência de página). Pico RSS do processo principal `/proc/1/status:VmHWM`: 1.793.492 KiB no primeiro ensaio; cgroup `memory.peak`: 2.315.345.920 bytes. Após ensaio com ruído: RSS high-water 1.821.304 KiB, cgroup peak manteve 2.315.345.920 bytes; não equivaler RSS a limite de memória do container.

Acentos `ção`, `ã`, `é`, `ç` preservados nos exemplos; `ü` falhou (“lingúiça”/“linguiça”), e a ordem de leitura no PDF girado deslocou “Órgão público”. Não cumpre por si a suíte CER/recall da F4.8. PDF multipágina devolveu `prov.page_no` 1, 2, 3.

PDF protegido e PDF corrompido: **HTTP 200, status="failure", errors[0].category="backend_failure"**; F4 deve validar `status`, nunca aceitar só o HTTP. Interceptar proteção no pypdf antes do OCR.

## Decisão para F4

Manter sidecar como candidato; não mudar D3 para API pelo desempenho local observado (<20 s/pág). **Gate definitivo pendente:** repetir corpus e medir p95/RSS em Railway 1 vCPU ou Oracle ARM, incluindo 50 páginas e prazo do job. RSS próximo de 1,8 GiB pode inviabilizar o plano pequeno. API externa continua condicionada a consentimento/DPA e escolha do dono; sem extrapolar esta medição para produção. Orçamento de páginas, cache e deadline da F4 continuam obrigatórios.

## Reprodução

Imagem pinada; adicionar português antes do start/conversão; gerar imagens/PDF com Pillow, enviar payload acima por httpx com timeout 240 s, observar `/proc/1/status` e `/sys/fs/cgroup/memory.peak`. Script do ensaio, autocontido (deps de pesquisa Pillow/httpx/pypdf, sem produção):

```python
import base64, json, time, random
from pathlib import Path
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
import httpx
from pypdf import PdfReader, PdfWriter

out = Path('/tmp/integracoes-ocr'); out.mkdir(exist_ok=True)
font = ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial.ttf', 60)
texts = ['Ação e informação: contratação em São Paulo.', 'Preço: R$ 1.500. Vencimento: 15/03/2026.', 'Órgão público: café, açúcar, maçã, lingüiça.']
images = []
for i in range(3):
    im = Image.new('RGB', (2480,3508), 'white'); draw=ImageDraw.Draw(im)
    for j,line in enumerate(texts): draw.text((160,200+j*140),line,fill='black',font=font)
    images.append(im)
images[0].save(out/'clean.pdf','PDF',resolution=300)
noisy = images[0].rotate(2,fillcolor='white')
noise = ImageDraw.Draw(noisy); rng = random.Random(11)
for _ in range(10000): noise.point((rng.randrange(2480),rng.randrange(3508)), fill=(150,150,150))
noisy.save(out/'rotated.pdf','PDF',resolution=300)
images[0].save(out/'multipage.pdf','PDF',resolution=300,save_all=True,append_images=images[1:])
w=PdfWriter(); w.append(PdfReader(out/'clean.pdf')); w.encrypt('secret'); w.write(out/'protected.pdf')
(out/'corrupt.pdf').write_bytes(b'%PDF-1.7 broken')
results=[]
for name in ['clean','rotated','multipage','protected','corrupt']:
    content=(out/f'{name}.pdf').read_bytes()
    request={'sources':[{'kind':'file','filename':f'{name}.pdf','base64_string':base64.b64encode(content).decode()}], 'options':{'to_formats':['json','text'],'do_ocr':True,'force_ocr':True,'ocr_preset':'tesseract','ocr_lang':['por','eng'],'do_table_structure':False,'document_timeout':180}}
    start=time.perf_counter()
    try:
        r=httpx.post('http://127.0.0.1:55019/v1/convert/source',json=request,timeout=240)
        record={'name':name,'http_status':r.status_code,'seconds':round(time.perf_counter()-start,3)}
        (out/f'{name}-response.json').write_text(r.text)
        try: data=r.json(); record['status']=data.get('status'); record['errors']=data.get('errors')
        except ValueError: pass
    except Exception as e: record={'name':name,'seconds':round(time.perf_counter()-start,3),'error':type(e).__name__}
    results.append(record); (out/'results.json').write_text(json.dumps(results,indent=2)); print(json.dumps(record),flush=True)

```

Fonte: [docling-serve oficial](https://github.com/docling-project/docling-serve), OpenAPI do container e respostas reais deste ensaio.

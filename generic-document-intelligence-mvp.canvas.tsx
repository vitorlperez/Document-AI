import { Callout, Card, CardBody, CardHeader, Divider, Grid, H1, H2, Pill, Row, Stack, Stat, Text } from "cursor/canvas";

const included = [
  ["Uma fonte", "Google Drive, em modo somente leitura, conectado por um administrador."],
  ["Um escopo", "Pastas escolhidas pelo administrador - por cliente, projeto ou área."],
  ["Três formatos", "Google Docs, PDF e DOCX, com status de indexação e falhas visíveis."],
  ["Uma experiência", "Busca e perguntas dentro da pasta, sempre com documento, página/trecho e link de origem."],
];

const excluded = [
  "OneDrive, Dropbox, S3 e e-mail.",
  "OCR avançado, XLSX/CSV complexos e imagens escaneadas.",
  "Agentes autônomos, knowledge graph, versionamento e duplicados semânticos.",
  "Permissões por arquivo herdadas do Google Drive: no MVP, só pastas explicitamente seguras para todos os membros do workspace.",
  "Alertas, automações e relatórios exportáveis.",
];

export default function GenericDocumentIntelligenceMvp() {
  return <Stack gap={24} style={{ maxWidth: 1120, margin: "0 auto", padding: 28 }}>
    <Stack gap={8}>
      <Row gap={8} align="center"><Pill tone="info">MVP horizontal</Pill><Text size="small" tone="tertiary">Empresas de serviços, agências e equipes operacionais</Text></Row>
      <H1>Transformar uma pasta de trabalho em respostas verificáveis em minutos</H1>
      <Text tone="secondary" style={{ maxWidth: 900 }}>O MVP não deve tentar “entender toda a empresa”. Ele resolve uma pergunta recorrente: “onde está a informação certa sobre este cliente, projeto ou processo?”</Text>
    </Stack>
    <Grid columns={3} gap={12}><Stat label="Cliente inicial" value="20-150 pessoas" tone="info" /><Stat label="Entrada" value="1 pasta Drive" tone="success" /><Stat label="Resultado" value="Resposta com fonte" tone="success" /></Grid>
    <Callout tone="info" title="Posicionamento">“Conecte uma pasta compartilhada, encontre a informação certa e responda com a fonte original.” Isso serve agências de marketing, consultorias, software houses, RH, operações e empresas de serviços sem prometer substituir o Drive.</Callout>
    <Grid columns="1fr 1fr" gap={20} align="start">
      <Stack gap={12}><H2>Fluxo que precisa funcionar</H2><Card variant="elevated"><CardBody><Stack gap={10}>
        <Text><Text weight="semibold">1. Conectar.</Text> Um administrador escolhe uma ou poucas pastas compartilhadas no Google Drive.</Text>
        <Text><Text weight="semibold">2. Indexar.</Text> A plataforma mostra quantidade processada, arquivos ignorados, erros e data da última sincronização.</Text>
        <Text><Text weight="semibold">3. Encontrar.</Text> A pessoa busca por palavras, filtros ou uma pergunta, limitada à pasta do cliente/projeto.</Text>
        <Text><Text weight="semibold">4. Conferir.</Text> A resposta mostra o trecho, documento, página quando aplicável e link para o arquivo no Drive.</Text>
        <Text><Text weight="semibold">5. Reusar.</Text> Consultas úteis ficam salvas como atalhos do projeto, por exemplo “briefing atual” ou “escopo aprovado”.</Text>
      </Stack></CardBody></Card></Stack>
      <Stack gap={12}><H2>Escopo técnico de lançamento</H2><Grid columns={1} gap={8}>{included.map(([title, body]) => <Card key={title}><CardHeader title={title} /><CardBody><Text>{body}</Text></CardBody></Card>)}</Grid></Stack>
    </Grid>
    <Divider />
    <Grid columns="0.8fr 1.2fr" gap={20} align="start">
      <Stack gap={12}><H2>O que fica fora</H2><Card><CardBody><Stack gap={8}>{excluded.map((item) => <Text key={item}>- {item}</Text>)}</Stack></CardBody></Card></Stack>
      <Stack gap={12}><H2>Decisão de segurança do MVP</H2><Callout tone="warning" title="Não prometa ACL granular antes de implementá-la">No primeiro piloto, o administrador só pode conectar pastas cujo conteúdo possa ser visto por todos os membros convidados ao workspace. Isso evita vazamento via busca e RAG. O suporte a permissões herdadas por arquivo entra antes de atender clientes maiores ou documentos de RH/financeiro.</Callout><Callout tone="success" title="Impacto sem depender de um setor">Agências podem encontrar briefing, proposta e relatório de uma conta. Consultorias encontram escopo, diagnóstico e entregáveis. Equipes de operação encontram procedimento, fornecedor e decisão anterior. O objeto comum é a pasta de trabalho, não o segmento.</Callout></Stack>
    </Grid>
    <Divider />
    <H2>Plano de 6 semanas para chegar a pilotos</H2>
    <Grid columns={3} gap={12}>
      <Card><CardHeader title="Semanas 1-2" trailing={<Pill tone="neutral">Fundação</Pill>} /><CardBody><Text>Autenticação, organização, convite de membros, conexão Google Drive e seleção de pastas.</Text></CardBody></Card>
      <Card variant="elevated"><CardHeader title="Semanas 3-4" trailing={<Pill tone="success">Valor central</Pill>} /><CardBody><Text>Fila de processamento, extração, índices híbridos, busca e chat com citações e links de origem.</Text></CardBody></Card>
      <Card><CardHeader title="Semanas 5-6" trailing={<Pill tone="info">Piloto</Pill>} /><CardBody><Text>Status de sincronização, tratamento de falhas, telemetria de buscas e entrevistas semanais com 3-5 empresas.</Text></CardBody></Card>
    </Grid>
    <Callout tone="info" title="Métricas que provam valor">Ativação: empresa conecta uma pasta com pelo menos 50 documentos e três pessoas fazem buscas. Retenção: dois ou mais membros voltam semanalmente. Valor: pelo menos 30% das consultas terminam em abertura de uma fonte citada ou resposta salva, e os pilotos dizem que reduziram tempo de busca ou dependência de colegas.</Callout>
  </Stack>;
}

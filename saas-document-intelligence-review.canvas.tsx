import { Callout, Card, CardBody, CardHeader, Divider, Grid, H1, H2, Pill, Row, Stack, Stat, Text } from "cursor/canvas";

export default function SaaSReview() {
  return <Stack gap={24} style={{ maxWidth: 1080, margin: "0 auto", padding: 28 }}>
    <Stack gap={8}>
      <Row gap={8} align="center"><Pill tone="info">Revisão de produto</Pill><Text size="small" tone="tertiary">AI Document Intelligence SaaS</Text></Row>
      <H1>Boa tese, mas escopo grande demais para o primeiro lançamento</H1>
      <Text tone="secondary">A oportunidade existe: empresas têm conhecimento disperso e pouca confiança para consultar documentos. O MVP precisa provar um fluxo específico, não construir uma plataforma enterprise completa.</Text>
    </Stack>
    <Grid columns={3} gap={12}><Stat label="Tese" value="Forte" tone="success" /><Stat label="Escopo atual" value="Enterprise" tone="warning" /><Stat label="Prioridade" value="Vertical + fluxo" tone="info" /></Grid>
    <Grid columns="1fr 1fr" gap={20} align="start">
      <Stack gap={12}><H2>O que manter no MVP</H2><Card><CardBody><Stack gap={10}>
        <Text><Text weight="semibold">Busca híbrida:</Text> texto, metadados e semântica.</Text>
        <Text><Text weight="semibold">Chat com evidências:</Text> toda resposta deve apontar documento, página e trecho.</Text>
        <Text><Text weight="semibold">Processamento seguro:</Text> upload ou um conector, filas e controle de erros.</Text>
        <Text><Text weight="semibold">Permissões básicas:</Text> nunca recuperar conteúdo inacessível ao usuário.</Text>
      </Stack></CardBody></Card></Stack>
      <Stack gap={12}><H2>O que adiar</H2><Card><CardBody><Stack gap={10}>
        <Text>Knowledge graph e agentes autônomos.</Text>
        <Text>Detecção semântica de versões e duplicados.</Text>
        <Text>Múltiplos conectores e todos os formatos documentais.</Text>
        <Text>Organização automática que altere os arquivos do cliente.</Text>
      </Stack></CardBody></Card></Stack>
    </Grid>
    <Divider />
    <H2>Recorte recomendado</H2>
    <Callout tone="info" title="Começar por contratos jurídicos">Para escritórios de advocacia pequenos e médios: conecte uma única fonte, encontre contratos por cliente, responda com citações e extraia vigência, renovação, valor e partes. O mesmo padrão pode funcionar para contabilidade ou imobiliárias, mas escolha apenas um vertical no início.</Callout>
    <H2>Próximos passos</H2>
    <Grid columns={2} gap={12}>
      <Card><CardHeader title="Validação" trailing={<Pill tone="neutral">Antes de construir</Pill>} /><CardBody><Text>Conduzir 10–15 entrevistas e conseguir 3 clientes piloto. Validar urgência, acesso aos documentos e disposição para pagar.</Text></CardBody></Card>
      <Card variant="elevated"><CardHeader title="MVP" trailing={<Pill tone="success">8–12 semanas</Pill>} /><CardBody><Text>Entrega focada em upload/conector, PDF/DOCX, busca, citações e extração de poucos campos de alto valor.</Text></CardBody></Card>
    </Grid>
    <Text size="small" tone="tertiary">Critério de sucesso: clientes voltam semanalmente porque encontram ou conferem informação mais rápido que no Drive — e três deles aceitam pagar após uso real.</Text>
  </Stack>;
}

import type { Metadata } from "next";
import { LegalLayout } from "../legal-layout";

export const metadata: Metadata = {
  title: "Termos de Uso | Arquivio",
  description: "Condições de acesso e uso do Arquivio e de suas integrações documentais.",
};

export default function TermsPage() {
  return <LegalLayout title="Termos de Uso">
    <section><h2>1. Serviço e contato</h2><p>O Arquivio, operado por Vitor Perez, permite que organizações conectem fontes documentais, criem uma biblioteca pesquisável e façam perguntas com respostas apoiadas em fontes. Dúvidas sobre estes termos podem ser enviadas para <a href="mailto:lagevitor.dev@gmail.com">lagevitor.dev@gmail.com</a>.</p></section>
    <section><h2>2. Conta e acesso</h2><p>O usuário deve fornecer informações corretas, proteger o acesso à sua conta e usar o serviço conforme sua autorização na organização. Administradores gerenciam convites, membros, conexões e escopos de conteúdo. A organização é responsável por definir quem pode consultar os materiais conectados e por obter as permissões necessárias para usá-los.</p></section>
    <section><h2>3. Integrações e conteúdo</h2><p>Ao conectar o Google Drive, o usuário concede a permissão OAuth <code>drive.readonly</code>, que permite visualizar e baixar todos os arquivos do Drive acessíveis à conta conectada. A seleção posterior de pastas, arquivos ou de todo o conteúdo acessível determina o processamento e a indexação no Arquivio; não limita a permissão concedida ao aplicativo no Google. OneDrive e Notion seguem as autorizações de seus provedores. A organização mantém seus direitos sobre os arquivos e permite que o Arquivio processe, armazene trechos e índices e apresente resultados aos seus membros para executar o serviço. Os originais continuam nos provedores de origem. A disponibilidade de cada integração depende das APIs e autorizações do respectivo provedor.</p></section>
    <section><h2>4. Respostas com IA</h2><p>As respostas automáticas podem conter erros, omissões ou informação desatualizada. Confira as fontes originais antes de tomar decisões importantes. O Arquivio busca apresentar referências e pode informar que não há evidência suficiente. Não há garantia de que uma alteração no arquivo de origem apareça imediatamente: a consulta utiliza a última versão sincronizada e indexada.</p></section>
    <section><h2>5. Uso adequado</h2><p>Não use o serviço para acessar materiais sem autorização, violar direitos de terceiros, introduzir código malicioso, tentar contornar controles de acesso ou prejudicar a disponibilidade do sistema. Podemos restringir o acesso para proteger usuários, investigar abuso ou cumprir a lei, comunicando a organização quando apropriado.</p></section>
    <section><h2>6. Privacidade e encerramento</h2><p>O tratamento de dados está descrito na <a href="/privacidade">Política de Privacidade</a>. A organização pode desconectar integrações e remover conteúdos indexados pelos controles disponíveis; para excluir dados de conta ou da organização, entre em contato pelo e-mail acima. Desconectar uma fonte interrompe novas sincronizações, mas não exclui automaticamente o conteúdo já indexado.</p></section>
    <section><h2>7. Alterações</h2><p>Podemos alterar o serviço e estes termos. A versão vigente ficará disponível nesta página com a data de atualização. Alterações relevantes serão comunicadas por um canal apropriado.</p></section>
  </LegalLayout>;
}

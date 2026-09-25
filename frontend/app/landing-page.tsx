"use client";

import {
  ArrowDown, ArrowRight, ArrowUpRight, Check, ChevronDown,
  FileText, Folder, FolderOpen, HardDrive, Layers3, Link2, Menu,
  PanelRightClose, Plus, Search, Send, ShieldCheck, Sparkles,
} from "lucide-react";
import "./landing.css";
import { Brand } from "./brand";

type LandingPageProps = { onLogin: () => void; onSignUp: () => void };

function ProductPreview() {
  return (
    <figure className="landing-preview" aria-labelledby="landing-preview-caption">
      <div className="landing-preview-top"><span><Layers3 size={17} aria-hidden="true" /> Seu espaço de conhecimento</span><span className="landing-preview-label">Exemplo ilustrativo</span></div>
      <div className="landing-product">
        <aside className="landing-product-sources" aria-label="Biblioteca ilustrativa">
          <div className="landing-product-sidebar-heading"><div><strong>Biblioteca</strong><span>Arquivos e pastas sincronizados</span></div><Plus size={16} aria-hidden="true" /></div>
          <div className="landing-product-breadcrumb">Biblioteca</div>
          <div className="landing-product-source"><span className="landing-provider-mark landing-provider-google">G</span> Google Drive <ChevronDown size={13} aria-hidden="true" /></div>
          <div className="landing-product-folder"><Folder size={15} aria-hidden="true" /> Projeto Aurora</div>
          <div className="landing-product-source"><span className="landing-provider-mark landing-provider-notion">N</span> Notion <ChevronDown size={13} aria-hidden="true" /></div>
          <div className="landing-product-source"><span className="landing-provider-mark landing-provider-onedrive"><HardDrive size={11} aria-hidden="true" /></span> OneDrive <ChevronDown size={13} aria-hidden="true" /></div>
          <div className="landing-product-scope"><ShieldCheck size={16} aria-hidden="true" /><p>A conversa usa somente o contexto escolhido em “Consultar em”.</p></div>
        </aside>
        <section className="landing-product-chat" aria-label="Conversa ilustrativa">
          <div className="landing-product-context"><div><strong>Consultar em</strong><span>Todas as ferramentas · conteúdo indexado <ChevronDown size={13} aria-hidden="true" /></span><small>3 pastas disponíveis</small></div><PanelRightClose size={17} aria-hidden="true" /></div>
          <div className="landing-product-thread">
            <div className="landing-product-question-wrap"><span>Todas as ferramentas</span><p className="landing-product-question">O que ficou definido para a primeira entrega?</p></div>
            <div className="landing-product-answer">
              <span className="landing-product-avatar"><Sparkles size={16} aria-hidden="true" /></span>
              <div><p className="landing-product-answer-name">Arquivio <span>· Todas as ferramentas</span></p><p>A primeira entrega reúne o <strong>diagnóstico de marca</strong> e a <strong>proposta de posicionamento</strong>. O alinhamento também confirmou a apresentação dos conceitos visuais nesta etapa.</p>
                <div className="landing-product-references" aria-label="Documentos utilizados"><strong>DOCUMENTOS UTILIZADOS</strong><div><span>1</span><FileText size={13} aria-hidden="true" /> Escopo do projeto.pdf <small>Google Drive</small></div><div><span>2</span><FileText size={13} aria-hidden="true" /> Reunião de alinhamento <small>Notion</small></div></div>
              </div>
            </div>
          </div>
          <div className="landing-product-composer"><span>O que você gostaria de saber?</span><span className="landing-product-send"><Send size={14} aria-hidden="true" /> Enviar</span></div>
          <p className="landing-product-disclaimer">A IA usa somente o escopo selecionado e não responde sem evidência suficiente.</p>
        </section>
        <aside className="landing-product-library" aria-label="Consulta de arquivos ilustrativa">
          <div className="landing-product-library-heading">Buscar arquivos</div>
          <p>Encontre arquivos e pastas pelo nome em todas as fontes conectadas.</p>
          <div className="landing-product-library-search"><span>Nome de arquivo ou pasta</span><Search size={13} aria-hidden="true" /></div>
          <small>A busca consulta somente nomes; o conteúdo permanece no escopo da conversa.</small>
        </aside>
      </div>
      <figcaption id="landing-preview-caption">Converse com o conteúdo das ferramentas conectadas e confira os documentos utilizados. <span>Dados fictícios para demonstrar a experiência.</span></figcaption>
    </figure>
  );
}

const questions = [
  ["O Arquivio substitui minhas ferramentas?", "Não. Seus arquivos e páginas originais continuam no Google Drive, OneDrive ou Notion. O Arquivio usa conexões de leitura para criar uma base de consulta com o conteúdo selecionado, sem editar os originais."],
  ["Que conteúdo posso consultar?", "Documentos Google, PDFs com texto, arquivos DOCX, páginas do Notion e Markdown dentro do escopo conectado. Imagens escaneadas, planilhas e apresentações não são indexadas nesta versão. Não há upload direto de arquivos."],
  ["Quem pode acessar o conteúdo conectado?", "Todos os membros da sua organização no Arquivio podem consultar o conteúdo sincronizado. As permissões individuais das ferramentas não são reproduzidas. Conecte somente materiais que possam ser compartilhados com toda a equipe; áreas restritas de RH ou financeiro não são adequadas."],
  ["E se não houver informação suficiente para responder?", "O Arquivio indica que não encontrou evidência suficiente no contexto selecionado. As respostas são geradas por IA e devem ser conferidas na lista de documentos utilizados e nos originais antes de embasar uma decisão."],
  ["Os documentos ficam disponíveis imediatamente?", "A sincronização e a extração de texto acontecem em segundo plano. Você pode acompanhar o estado de processamento e as falhas por documento. Alterações nos arquivos precisam passar por uma nova sincronização para aparecer nas consultas."],
  ["Como o conteúdo é usado pela IA?", "O conteúdo extraído necessário para busca e resposta é processado pelo provedor de IA configurado. Os originais permanecem nas ferramentas conectadas. Antes de conectar uma fonte, confirme que esse uso é adequado às políticas da sua organização."],
];

export function LandingPage({ onLogin, onSignUp }: LandingPageProps) {
  return (
    <div className="landing-page">
      <a className="landing-skip-link" href="#landing-main">Pular para o conteúdo</a>
      <header className="landing-header landing-container">
        <a href="#landing-main" className="landing-brand-link" aria-label="Arquivio, início"><Brand /></a>
        <nav className="landing-desktop-nav" aria-label="Navegação principal"><a href="#como-funciona">Como funciona</a><a href="#para-equipes">Para sua equipe</a><a href="#perguntas">Dúvidas</a></nav>
        <div className="landing-header-actions"><button className="landing-login" onClick={onLogin}>Entrar</button><button className="landing-button landing-button-small" onClick={onSignUp}>Criar conta <ArrowUpRight size={16} aria-hidden="true" /></button></div>
        <details className="landing-mobile-menu"><summary aria-label="Abrir navegação"><Menu size={23} aria-hidden="true" /></summary><nav aria-label="Navegação móvel"><a href="#como-funciona">Como funciona</a><a href="#para-equipes">Para sua equipe</a><a href="#perguntas">Dúvidas</a><button onClick={onLogin}>Entrar na minha conta</button></nav></details>
      </header>

      <main id="landing-main">
        <section className="landing-hero landing-container" aria-labelledby="landing-hero-title">
          <p className="landing-eyebrow"><span className="landing-status-dot" /> SEU CONHECIMENTO, COM CONTEXTO</p>
          <h1 id="landing-hero-title">O que sua equipe sabe,<br /><em>ao alcance de uma pergunta.</em></h1>
          <p className="landing-hero-description">Conecte Google Drive, OneDrive e Notion para transformar documentos em respostas com fontes.<br className="landing-desktop-break" /> Encontre o que importa, entenda o contexto e confira de onde veio.</p>
          <div className="landing-hero-actions"><button className="landing-button" onClick={onSignUp}>Começar com o Arquivio <ArrowRight size={19} aria-hidden="true" /></button><a className="landing-text-link" href="#como-funciona">Conhecer o produto <ArrowDown size={16} aria-hidden="true" /></a></div>
          <p className="landing-hero-note"><Check size={14} aria-hidden="true" /> Conexões de leitura <span aria-hidden="true">·</span> Seus originais continuam nas ferramentas conectadas</p>
          <ProductPreview />
        </section>

        <section className="landing-benefits landing-container" aria-labelledby="landing-benefits-title">
          <div className="landing-section-intro"><p className="landing-eyebrow">MENOS PROCURA. MAIS CLAREZA.</p><h2 id="landing-benefits-title">A informação já existe.<br /><em>Agora ela participa da conversa.</em></h2><p>Do briefing à última decisão do projeto, dê à sua equipe um caminho direto até o conhecimento que está nos documentos.</p></div>
          <div className="landing-benefit-grid">
            <article><span className="landing-feature-icon"><Sparkles size={24} strokeWidth={1.5} aria-hidden="true" /></span><h3>Pergunte do seu jeito</h3><p>Faça perguntas em linguagem natural sobre o conteúdo sincronizado, sem abrir arquivo por arquivo.</p></article>
            <article><span className="landing-feature-icon"><Link2 size={24} strokeWidth={1.5} aria-hidden="true" /></span><h3>Uma resposta, com origem</h3><p>Veja os documentos utilizados na resposta e abra os originais para conferir os detalhes.</p></article>
            <article><span className="landing-feature-icon"><FolderOpen size={24} strokeWidth={1.5} aria-hidden="true" /></span><h3>O contexto é você quem escolhe</h3><p>Consulte todas as ferramentas, uma ferramenta ou uma pasta específica. Cada pergunta usa o escopo selecionado.</p></article>
          </div>
        </section>

        <section className="landing-workflow" id="como-funciona" aria-labelledby="landing-workflow-title"><div className="landing-container">
          <div className="landing-workflow-heading"><div><p className="landing-eyebrow">DAS FERRAMENTAS À RESPOSTA</p><h2 id="landing-workflow-title">Seu conhecimento.<br /><em>Um novo jeito de acessar.</em></h2></div><p>Comece com os documentos e páginas que a sua equipe já usa. O Arquivio conecta as informações à próxima pergunta.</p></div>
          <ol className="landing-steps">
            <li><span className="landing-step-number">01</span><h3>Conecte e escolha</h3><p>Um administrador conecta as ferramentas e seleciona o conteúdo que toda a organização pode consultar.</p><span className="landing-step-detail"><FolderOpen size={15} aria-hidden="true" /> Google Drive · OneDrive · Notion</span></li>
            <li><span className="landing-step-number">02</span><h3>Acompanhe a preparação</h3><p>Documentos e páginas são processados em segundo plano. Veja o que está pronto e o que precisa de atenção.</p><span className="landing-step-detail"><FileText size={15} aria-hidden="true" /> Google Docs · PDF · DOCX · Notion</span></li>
            <li><span className="landing-step-number">03</span><h3>Pergunte e confira</h3><p>Escolha todas as ferramentas, uma ferramenta ou uma pasta; depois confira os documentos utilizados na resposta.</p><span className="landing-step-detail"><Link2 size={15} aria-hidden="true" /> Respostas ligadas às fontes</span></li>
          </ol>
          <div className="landing-permission-note"><ShieldCheck size={21} aria-hidden="true" /><p><strong>Conhecimento compartilhado exige uma escolha consciente.</strong> Todos os membros da organização têm acesso ao conteúdo sincronizado. Selecione apenas materiais que possam ser vistos por toda a equipe.</p></div>
        </div></section>

        <section className="landing-audiences landing-container" id="para-equipes" aria-labelledby="landing-audiences-title">
          <div className="landing-section-intro"><p className="landing-eyebrow">FEITO PARA O TRABALHO EM EQUIPE</p><h2 id="landing-audiences-title">O próximo passo começa<br /><em>com uma boa pergunta.</em></h2><p>Para quem transforma informação em entregas, recomendações e decisões todos os dias.</p></div>
          <div className="landing-audience-list">
            <article><span className="landing-audience-index">01 /</span><div><h3>Agências e marketing</h3><p>Briefings, escopos e decisões de campanha no contexto do cliente.</p></div><blockquote>“Quais entregas estão previstas no briefing?”</blockquote><ArrowUpRight size={23} aria-hidden="true" /></article>
            <article><span className="landing-audience-index">02 /</span><div><h3>Consultorias</h3><p>Propostas, diagnósticos e relatórios para retomar o que foi documentado.</p></div><blockquote>“O que o diagnóstico recomenda para esta etapa?”</blockquote><ArrowUpRight size={23} aria-hidden="true" /></article>
            <article><span className="landing-audience-index">03 /</span><div><h3>Equipes de software</h3><p>Requisitos e registros de projeto disponíveis para a próxima conversa.</p></div><blockquote>“Qual foi o escopo definido para esta entrega?”</blockquote><ArrowUpRight size={23} aria-hidden="true" /></article>
          </div>
          <p className="landing-audience-note">Perguntas ilustrativas. As respostas dependem das evidências nos documentos conectados.</p>
        </section>

        <section className="landing-faq landing-container" id="perguntas" aria-labelledby="landing-faq-title"><div><p className="landing-eyebrow">ANTES DE COMEÇAR</p><h2 id="landing-faq-title">Clareza desde<br /><em>a primeira pergunta.</em></h2><p>O que o Arquivio faz, como funciona e o que considerar ao conectar sua equipe.</p></div><div className="landing-faq-list">{questions.map(([question, answer]) => <details key={question}><summary>{question}<ChevronDown size={19} aria-hidden="true" /></summary><p>{answer}</p></details>)}</div></section>

        <section className="landing-closing landing-container" aria-labelledby="landing-closing-title"><span className="landing-closing-symbol"><Layers3 size={33} strokeWidth={1.3} aria-hidden="true" /></span><p className="landing-eyebrow">MENOS ARQUIVOS ABERTOS. MAIS CONTEXTO.</p><h2 id="landing-closing-title">Sua próxima resposta<br /><em>pode estar nas ferramentas que você já usa.</em></h2><button className="landing-button" onClick={onSignUp}>Criar minha conta <ArrowRight size={19} aria-hidden="true" /></button><p>Já tem um espaço de trabalho? <button className="landing-inline-button" onClick={onLogin}>Entrar no Arquivio</button></p></section>
      </main>

      <footer className="landing-footer landing-container"><a href="#landing-main" className="landing-brand-link" aria-label="Arquivio, voltar ao início"><Brand /></a><p>Conhecimento que encontra o seu contexto.</p><a href="#perguntas">Sobre acesso e privacidade <ArrowUpRight size={14} aria-hidden="true" /></a></footer>
    </div>
  );
}

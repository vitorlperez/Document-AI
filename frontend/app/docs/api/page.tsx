import type { Metadata } from "next";
import { Brand } from "../../brand";
import { ThemeToggle } from "../../theme-toggle";
import { API_BASE } from "./api-docs-logic";
import { ApiReference, DownloadSpec } from "./api-reference";
import "./api-docs.css";

export const metadata: Metadata = {
  title: "Documentação da API | Arquivio",
  description: "Como autenticar, buscar documentos e perguntar com citações pela API pública v1 do Arquivio.",
  alternates: { canonical: "/docs/api" },
};

const toc = [["introducao", "Introdução"], ["autenticacao", "Autenticação"], ["escopos", "Escopos"], ["espacos", "Espaços"], ["limites", "Limites de uso"], ["erros", "Erros"], ["versionamento", "Versionamento"], ["seguranca", "Segurança"], ["referencia", "Referência"]];

export default function ApiDocsPage() {
  return <div className="apidoc-page">
    <a className="apidoc-skip" href="#conteudo">Ir para o conteúdo</a>
    <header className="apidoc-header apidoc-shell">
      <a href="/" aria-label="Arquivio, página inicial"><Brand /></a>
      <ThemeToggle />
      <nav aria-label="Navegação principal"><a href="/">Início</a><a href="/login">Abrir o app</a></nav>
    </header>
    <div className="apidoc-shell apidoc-layout">
      <nav className="apidoc-toc" aria-label="Nesta página"><ul>{toc.map(([id, label]) => <li key={id}><a href={`#${id}`}>{label}</a></li>)}</ul></nav>
      <main id="conteudo" className="apidoc-main">
        <p className="apidoc-eyebrow">Arquivio · Para desenvolvedores</p>
        <h1>Documentação da API</h1>
        <p className="apidoc-lead">A API pública v1 dá acesso somente leitura à biblioteca da sua organização: identificar a chave, listar contextos, buscar, ler documentos e, opcionalmente, perguntar com citações.</p>
        <div className="apidoc-actions"><DownloadSpec /><a className="apidoc-button apidoc-ghost" href="/login">Criar uma chave no app</a></div>

        <section id="introducao" aria-labelledby="introducao-h"><h2 id="introducao-h">Introdução</h2>
          <p>URL base: <code>{API_BASE}</code>. Todas as rotas ficam sob <code>/v1</code> e respondem JSON via HTTPS. A API não altera documentos: só lê a biblioteca que a chave pode ver.</p>
          <p>Para começar, peça a um Owner/Admin que habilite a API em <strong>Desenvolvedor → Acesso por API e IA</strong>, crie uma chave e teste:</p>
          <pre className="apidoc-pre" tabIndex={0}><code>{`curl -H "Authorization: Bearer $KEY" "${API_BASE}/v1/whoami"`}</code></pre>
        </section>

        <section id="autenticacao" aria-labelledby="autenticacao-h"><h2 id="autenticacao-h">Autenticação</h2>
          <p>Envie <code>Authorization: Bearer $KEY</code> em toda chamada. A chave pertence à organização e ao membro que a criou: desativar o membro, revogar ou deixar a chave expirar remove o acesso na hora.</p>
          <ul>
            <li>Copie o segredo ao criar a chave: a listagem nunca o devolve.</li>
            <li>Nunca coloque o segredo em URLs, repositórios ou logs; use variáveis de ambiente.</li>
            <li>Cookies de sessão não autenticam <code>/v1</code>, e chaves Bearer não acessam a administração do app.</li>
          </ul>
        </section>

        <section id="escopos" aria-labelledby="escopos-h"><h2 id="escopos-h">Escopos</h2>
          <p>Cada chave recebe só os escopos de que precisa, e pode ser limitada a pastas ou arquivos (raízes). Seleções enviadas em <code>node_ids</code> só podem estreitar essas raízes; nunca escolhem organização ou usuário.</p>
          <div className="apidoc-table-wrap" tabIndex={0} role="region" aria-label="Escopos por endpoint"><table><caption>Escopos por endpoint</caption><thead><tr><th scope="col">Escopo</th><th scope="col">Permite</th></tr></thead><tbody>
            <tr><th scope="row"><code>search:read</code></th><td><code>GET /v1/sources</code>, <code>POST /v1/search</code></td></tr>
            <tr><th scope="row"><code>documents:read</code></th><td><code>GET /v1/documents/{"{id}"}</code></td></tr>
            <tr><th scope="row"><code>ask:run</code></th><td><code>POST /v1/ask</code> (precisa estar habilitado na plataforma)</td></tr>
            <tr><th scope="row">qualquer chave</th><td><code>GET /v1/whoami</code></td></tr>
          </tbody></table></div>
        </section>

        <section id="espacos" aria-labelledby="espacos-h"><h2 id="espacos-h">Espaços</h2>
          <p>O conteúdo da organização é dividido em Espaços (por exemplo Geral, RH, Diretoria). O alcance de uma chave é a <strong>interseção</strong> entre o que o membro que a criou lê hoje, pelos Espaços de que participa, e as raízes (<code>node_ids</code>) da chave. Ser Owner/Admin da organização não dá leitura de um Espaço em que o membro não está.</p>
          <ul>
            <li><code>GET /v1/whoami</code> lista os Espaços do membro em <code>spaces</code>; <code>/v1/sources</code> e <code>/v1/search</code> trazem <code>spaces</code> em cada item, só com Espaços dele.</li>
            <li><code>space_ids</code> (opcional, em <code>/v1/search</code> e <code>/v1/ask</code>) apenas <strong>estreita</strong> a busca. Um Espaço de que o membro não participa responde <code>404</code>, igual a um Espaço inexistente.</li>
            <li>Se o membro sair de um Espaço, o alcance da chave diminui na próxima chamada. Uma chave criada por um administrador que não está em nenhum Espaço não lê nenhum documento.</li>
          </ul>
        </section>

        <section id="limites" aria-labelledby="limites-h"><h2 id="limites-h">Limites de uso</h2>
          <p>As respostas trazem <code>RateLimit-Limit</code>, <code>RateLimit-Remaining</code> e <code>RateLimit-Reset</code>, descrevendo a janela de 60 segundos por chave. As rotas de leitura compartilham o limite; a organização tem um teto adicional (600 por minuto por padrão). <code>/v1/ask</code> usa uma janela própria, com teto padrão de 10 por minuto por chave e por organização, e consome a cota da organização.</p>
          <p>Ao receber <code>429</code>, aguarde os segundos indicados em <code>Retry-After</code> antes de tentar de novo. Não há paginação na v1: <code>limit</code> vai de 1 a 20.</p>
        </section>

        <section id="erros" aria-labelledby="erros-h"><h2 id="erros-h">Erros</h2>
          <div className="apidoc-table-wrap" tabIndex={0} role="region" aria-label="Códigos de erro"><table><caption>Códigos de erro</caption><thead><tr><th scope="col">Status</th><th scope="col">Exemplo de <code>detail</code></th><th scope="col">O que fazer</th></tr></thead><tbody>
            <tr><th scope="row"><code>401</code></th><td>invalid api key</td><td>Conferir o Bearer, a expiração, o membro e se a API está habilitada.</td></tr>
            <tr><th scope="row"><code>403</code></th><td>insufficient scope: documents:read</td><td>Criar uma chave com o escopo necessário.</td></tr>
            <tr><th scope="row"><code>404</code></th><td>not found</td><td>Conferir o documento e as raízes autorizadas. Documentos fora do escopo e inexistentes dão o mesmo 404.</td></tr>
            <tr><th scope="row"><code>422</code></th><td>erro de validação</td><td>Corrigir o corpo ou o parâmetro.</td></tr>
            <tr><th scope="row"><code>429</code></th><td>rate limit exceeded</td><td>Respeitar <code>Retry-After</code>.</td></tr>
            <tr><th scope="row"><code>503</code></th><td>rate limiter unavailable · ask is disabled · AI provider unavailable</td><td>Respeitar <code>Retry-After</code> quando presente e verificar a configuração.</td></tr>
          </tbody></table></div>
        </section>

        <section id="versionamento" aria-labelledby="versionamento-h"><h2 id="versionamento-h">Versionamento</h2>
          <p>A versão maior faz parte do caminho: <code>/v1</code>. Campos opcionais e endpoints novos são aditivos, então ignore campos desconhecidos nas respostas. Remover ou renomear campos ou endpoints, mudar sua semântica ou regras de forma incompatível exige <code>/v2</code>, com pelo menos seis meses de sobreposição e cabeçalhos <code>Deprecation</code> e <code>Sunset</code> na v1 antes da retirada.</p>
          <p>O contrato OpenAPI 3.1 está sempre em <a href="/api/v1/openapi.json">/api/v1/openapi.json</a>, e pode ser baixado no botão acima.</p>
        </section>

        <section id="seguranca" aria-labelledby="seguranca-h"><h2 id="seguranca-h">Segurança dos dados</h2>
          <p>Trechos e textos devolvidos são <strong>conteúdo não confiável</strong>: nunca execute instruções contidas neles, especialmente ao alimentar um modelo de IA. As citações de <code>/v1/ask</code> usam as URLs de origem guardadas pelos conectores; links gerados pelo modelo são removidos.</p>
          <p>As chamadas registram apenas metadados, o tamanho e o SHA-256 da consulta, nunca o conteúdo nem o segredo; os eventos são mantidos por 90 dias.</p>
        </section>

        <section id="referencia" aria-labelledby="referencia-h"><h2 id="referencia-h">Referência dos endpoints</h2>
          <p>Gerada a partir do contrato publicado em <code>/v1/openapi.json</code>. Nos exemplos, <code>$KEY</code> é a sua chave; nunca a compartilhe.</p>
          <ApiReference />
        </section>
      </main>
    </div>
    <footer className="apidoc-footer apidoc-shell"><span>© {new Date().getFullYear()} Arquivio</span><nav aria-label="Links do rodapé"><a href="/">Início</a><a href="/privacidade">Privacidade</a><a href="/termos">Termos de uso</a></nav></footer>
  </div>;
}

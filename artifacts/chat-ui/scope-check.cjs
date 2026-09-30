const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const root = process.env.CHAT_TEST_ROOT || path.resolve(__dirname, '../../frontend');
const ts = require(path.join(root, 'node_modules/typescript'));
const React = require(path.join(root, 'node_modules/react'));
const { renderToStaticMarkup } = require(path.join(root, 'node_modules/react-dom/server'));
require.extensions['.css'] = () => {};
const filename = path.join(root, 'app/question-scope.tsx');
const compiled = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2021 }
}).outputText;
const component = new Module(filename, module);
component.filename = filename;
component.paths = Module._nodeModulePaths(path.dirname(filename));
component._compile(compiled, filename);
const { QuestionScopePicker } = component.exports;
const context = (provider, status = 'ready', queryStatus = 'ready') => ({
  id: String(Math.random()), name: 'Pasta', source_id: 'source', source_provider: provider, status, query_status: queryStatus
});
const contexts = [context('google'), context('google_drive'), context('notion'), context('notion', 'partial_failure')];
const render = (props = {}) => renderToStaticMarkup(React.createElement(QuestionScopePicker, {
  all: true, providers: [], contexts, loading: false, disabled: false, error: null,
  onRetry() {}, onChange() {}, ...props
}));
assert.match(render(), /2 ferramentas disponíveis/);
assert.match(render({ all: false, providers: ['google'] }), /1 ferramenta disponível/);
assert.match(render({ all: false, providers: [] }), /0 ferramentas disponíveis/);
assert.match(render({ contexts: [] }), /Ainda não há conteúdo pronto/);
const mixed = render({ contexts: [...contexts, context('slack', 'syncing', 'not_ready'), context('onedrive', 'ready', 'no_compatible_embeddings')] });
assert.match(mixed, /2 ferramentas disponíveis/);
assert.match(mixed, /Cobertura parcial: 2 pastas indisponíveis/);
assert.match(render({ contexts: [context('google', 'syncing', 'not_ready')] }), /0 ferramentas disponíveis/);
assert.match(render({ error: 'Falha ao carregar' }), /role="alert".*Falha ao carregar.*Tentar novamente/);
assert.match(render({ loading: true }), /Carregando ferramentas/);
console.log('PASS: provider deduplication and aliases, selection, singular/plural, empty and unready states, partial coverage, error/retry, loading.');

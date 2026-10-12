"use client";

import { FileSearch, TriangleAlert } from "lucide-react";
import { useState } from "react";
import { Enter, EmptyState, ErrorState, LoadingBlock, ProgressIndicator, Reveal, ScreenTransition, Shimmer, SkeletonAvatar, SkeletonBlock, SkeletonCard, SkeletonLine, SkeletonList, SkeletonText, Spinner, StaggerItem, StreamingText, Toast, ToastViewport, Transition, TypingIndicator } from "../ui";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return <section data-demo-section={title} className="rounded-xl border border-line bg-panel p-5"><h2 className="mb-4 text-sm font-semibold text-ink">{title}</h2>{children}</section>;
}

export function MotionDemo() {
  const [show, setShow] = useState(true);
  const [toast, setToast] = useState(false);
  const [tab, setTab] = useState("a");
  const [streaming, setStreaming] = useState<"streaming" | "idle" | "done">("streaming");
  return (
    <main className="mx-auto flex max-w-4xl flex-col gap-5 bg-paper p-6 text-ink">
      <h1 className="text-lg font-semibold">Motion foundation — vitrine interna</h1>
      <Section title="Skeletons">
        <LoadingBlock label="Carregando exemplo…">
          <div className="grid gap-4 sm:grid-cols-2">
            <SkeletonCard media />
            <div className="flex flex-col gap-3"><div className="flex items-center gap-3"><SkeletonAvatar /><SkeletonLine width="50%" /></div><SkeletonText lines={3} /><SkeletonBlock height="3rem" /></div>
          </div>
          <div className="mt-4"><SkeletonList rows={3} /></div>
        </LoadingBlock>
      </Section>
      <Section title="Spinner, progresso e shimmer">
        <div className="flex flex-wrap items-center gap-6"><Spinner label="Sincronizando…" /><Spinner size={28} /><Shimmer variant="text">Consultando os arquivos…</Shimmer></div>
        <div className="mt-4 grid gap-3"><ProgressIndicator value={62} label="Indexação" /><ProgressIndicator label="Preparando" /></div>
      </Section>
      <Section title="Chat: pensando e streaming">
        <div className="flex flex-col gap-3">
          <Enter variant="pop" origin="user" className="ml-auto max-w-xs rounded-xl bg-sage-selected px-3 py-2 text-sm">Qual o prazo do contrato?</Enter>
          <div className="rounded-xl bg-sage px-3 py-2 text-sm"><TypingIndicator /></div>
          <div className="rounded-xl bg-sage px-3 py-2 text-sm"><StreamingText state={streaming}>O prazo é de 12 meses, renovável</StreamingText></div>
          <div className="flex gap-2 text-xs">{(["streaming", "idle", "done"] as const).map((s) => <button key={s} type="button" onClick={() => setStreaming(s)} className="mo-interactive mo-focus rounded-lg border border-line px-3">{s}</button>)}</div>
        </div>
      </Section>
      <Section title="Entrada, saída e stagger">
        <button type="button" data-testid="toggle" onClick={() => setShow((v) => !v)} className="mo-interactive mo-focus mb-3 rounded-lg border border-line px-3 text-sm" data-variant="primary">{show ? "Ocultar" : "Mostrar"}</button>
        <div className="flex flex-wrap gap-3">{(["fade", "slide", "scale", "pop"] as const).map((v) => <Transition key={v} show={show} variant={v} className="rounded-lg border border-line bg-sage px-4 py-3 text-sm">{v}</Transition>)}</div>
        <ul className="mt-4 grid gap-2">{Array.from({ length: 10 }, (_, i) => <StaggerItem key={i} as="li" index={i} className="mo-interactive-card list-none rounded-lg border border-line bg-panel px-3 py-2 text-sm">Documento {i + 1}</StaggerItem>)}</ul>
      </Section>
      <Section title="Troca de tela e reveal">
        <div className="mb-3 flex gap-2">{["a", "b"].map((k) => <button key={k} type="button" onClick={() => setTab(k)} className="mo-interactive mo-focus rounded-lg border border-line px-3 text-sm">Tela {k.toUpperCase()}</button>)}</div>
        <ScreenTransition screenKey={tab} className="rounded-lg bg-sage p-4 text-sm">Conteúdo da tela {tab.toUpperCase()}</ScreenTransition>
        <Reveal className="mt-4 rounded-lg bg-sage p-4 text-sm">Bloco com scroll reveal (view timeline, quando suportado)</Reveal>
      </Section>
      <Section title="Vazio e erro">
        <div className="grid gap-4 sm:grid-cols-2">
          <EmptyState icon={<FileSearch size={22} />} title="Nenhum arquivo ainda" description="Conecte uma pasta para começar a consultar." actions={<button type="button" className="mo-interactive mo-focus rounded-lg border border-line bg-panel px-3 text-sm" data-variant="primary">Conectar pastas</button>} />
          <ErrorState icon={<TriangleAlert size={22} />} title="Não foi possível carregar" description="Verifique a conexão e tente de novo." actions={<button type="button" className="mo-interactive mo-focus rounded-lg border border-current px-3 text-sm">Tentar novamente</button>} />
        </div>
      </Section>
      <Section title="Toast e campos">
        <div className="flex flex-wrap items-center gap-3"><button type="button" onClick={() => setToast(true)} className="mo-interactive mo-focus rounded-lg border border-line px-3 text-sm">Disparar toast</button><input aria-label="Campo de exemplo" placeholder="Campo com foco" className="mo-field rounded-lg border border-control-edge bg-panel px-3 py-2 text-sm outline-none" /></div>
      </Section>
      <ToastViewport><Toast open={toast} tone="success" title="Pasta conectada" description="Indexação iniciada." duration={4000} onDismiss={() => setToast(false)} /></ToastViewport>
    </main>
  );
}

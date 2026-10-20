"use client";

import { CircleAlert, FolderOpen, LogIn, Plus, Trash2, Users } from "lucide-react";
import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { type Company } from "./types-and-api";
import { EmptyState, Enter, ErrorState, LoadingBlock, SkeletonList, btn } from "../ui";
import { canManageMembers, impactSentence } from "../spaces-model";
import { addableCandidates, canEnterSpace, spaceRoleLabel, toSpacesError, type OrgPerson, type SpaceFolder, type SpaceImpact, type SpaceMemberRow, type SpaceRole, type SpaceSummary } from "./spaces-api";
import { spacesApi } from "./spaces-client";
import { SpaceConfirmDialog } from "./space-dialogs";

type Tab = "people" | "folders";
type Pending = { kind: "disable"; member: SpaceMemberRow; impact: SpaceImpact | null } | { kind: "archive" } | null;

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

export function SpacesScreen({ company, setError, setNotice }: { company: Company; setError: (value: string | null) => void; setNotice: (value: string | null) => void }) {
  const isAdmin = company.role !== "member";
  const [spaces, setSpaces] = useState<SpaceSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  const load = useCallback(async (keep?: string | null) => {
    setLoading(true); setLoadError(null);
    try {
      const items = await spacesApi.listSpaces(company.id);
      setSpaces(items);
      setSelectedId((current) => { const wanted = keep ?? current; return items.some((item) => item.id === wanted) ? wanted : items[0]?.id ?? null; });
    } catch (caught) { setLoadError(toSpacesError(caught).message); } finally { setLoading(false); }
  }, [company.id]);
  useEffect(() => { void Promise.resolve().then(() => load()); }, [load]);

  const selected = spaces.find((item) => item.id === selectedId) ?? null;
  async function createSpace(name: string) {
    try { const created = await spacesApi.createSpace(company.id, { name }); setCreating(false); setNotice(`Espaço “${created.name}” criado.`); await load(created.id); }
    catch (caught) { setError(toSpacesError(caught).message); }
  }

  return <Enter variant="fade" className="grid gap-5 lg:grid-cols-[320px_1fr]">
    <section className="rounded-lg border border-line-soft bg-panel p-5" aria-labelledby="spaces-title" aria-busy={loading}>
      <p className="text-sm font-semibold text-primary">Quem vê o quê</p>
      <div className="mt-1 flex items-center justify-between gap-3">
        <h1 id="spaces-title" className="text-2xl font-semibold">Espaços</h1>
        {isAdmin && <button type="button" className={btn("secondary", "sm")} onClick={() => setCreating((open) => !open)} aria-expanded={creating}><Plus size={14} aria-hidden="true" />Novo Espaço</button>}
      </div>
      <p className="mt-2 text-sm text-muted-foreground">Cada Espaço junta pessoas e pastas conectadas. Você vê tudo o que está nos seus Espaços, em uma só visão.</p>
      {creating && <NewSpaceForm onSubmit={createSpace} onCancel={() => setCreating(false)} />}
      <div className="mt-4">
        {loading ? <LoadingBlock label="Carregando Espaços…" className="min-h-40"><SkeletonList rows={3} /></LoadingBlock>
          : loadError ? <ErrorState icon={<CircleAlert size={22} />} title="Não foi possível carregar os Espaços" description={loadError} actions={<button className={btn("secondary")} onClick={() => void load()}>Tentar novamente</button>} />
          : spaces.length === 0 ? <EmptyState icon={<Users size={22} />} title="Você ainda não está em nenhum Espaço" description="Peça acesso a um administrador da organização." />
          : <ul className="space-y-2" aria-label="Lista de Espaços">{spaces.map((space) => <li key={space.id}>
            <button type="button" onClick={() => setSelectedId(space.id)} aria-current={space.id === selectedId ? "true" : undefined}
              className={`mo-interactive w-full rounded-lg border p-3 text-left ${space.id === selectedId ? "border-primary bg-sage" : "border-line-soft bg-panel"}`}>
              <span className="flex items-center gap-2"><b className="min-w-0 truncate">{space.name}</b>{space.is_default && <span className="rounded-full bg-sage px-2 py-0.5 text-xs font-semibold text-muted-foreground">Padrão</span>}</span>
              <span className="mt-1 block text-xs text-muted-foreground">{plural(space.member_count, "pessoa", "pessoas")} · {plural(space.folder_count, "pasta", "pastas")} · {spaceRoleLabel(space.my_role)}</span>
            </button></li>)}</ul>}
      </div>
    </section>
    {selected ? <SpaceDetail key={selected.id} company={company} space={selected} onChanged={(keep) => load(keep)} setError={setError} setNotice={setNotice} />
      : !loading && !loadError && <section className="hidden rounded-lg border border-line-soft bg-panel p-6 text-sm text-muted-foreground lg:block">Escolha um Espaço para ver as pessoas e as pastas.</section>}
  </Enter>;
}

function NewSpaceForm({ onSubmit, onCancel }: { onSubmit: (name: string) => Promise<void>; onCancel: () => void }) {
  const [name, setName] = useState(""); const [busy, setBusy] = useState(false);
  async function submit(event: FormEvent) { event.preventDefault(); if (!name.trim()) return; setBusy(true); try { await onSubmit(name.trim()); } finally { setBusy(false); } }
  return <form onSubmit={submit} className="mt-4 space-y-2 rounded-lg border border-line-soft p-3">
    <label className="block text-sm font-semibold" htmlFor="new-space-name">Nome do Espaço</label>
    <input id="new-space-name" value={name} onChange={(event) => setName(event.target.value)} maxLength={120} autoFocus required className="w-full rounded-md border border-line bg-paper px-3 py-2 text-sm" placeholder="Ex.: RH" />
    <div className="flex gap-2"><button type="submit" disabled={busy || !name.trim()} aria-busy={busy} className={btn("primary", "sm")}>Criar</button><button type="button" onClick={onCancel} className={btn("ghost", "sm")}>Cancelar</button></div>
  </form>;
}

function SpaceDetail({ company, space, onChanged, setError, setNotice }: { company: Company; space: SpaceSummary; onChanged: (keep: string | null) => Promise<void>; setError: (value: string | null) => void; setNotice: (value: string | null) => void }) {
  const isAdmin = company.role !== "member";
  const canPeople = canManageMembers(company.role, space.my_role);
  const canSeeMembers = space.my_role !== null || isAdmin;
  const [tab, setTab] = useState<Tab>("people");
  const [pending, setPending] = useState<Pending>(null); const [busy, setBusy] = useState(false); const [dialogError, setDialogError] = useState<string | null>(null);

  async function enter() {
    try { await spacesApi.enter(company.id, space.id); setNotice(`Você entrou em ${space.name}. Os demais membros podem ver esse registro.`); await onChanged(space.id); }
    catch (caught) { setError(toSpacesError(caught).message); }
  }
  async function archive() {
    setBusy(true); setDialogError(null);
    try { await spacesApi.archiveSpace(company.id, space.id); setPending(null); setNotice(`Espaço “${space.name}” arquivado.`); await onChanged(null); }
    catch (caught) { setDialogError(toSpacesError(caught).message); } finally { setBusy(false); }
  }

  return <section className="rounded-lg border border-line-soft bg-panel p-5 sm:p-6" aria-labelledby="space-detail-title">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0"><h2 id="space-detail-title" className="break-words text-xl font-semibold">{space.name}</h2>
        {space.description && <p className="mt-1 text-sm text-muted-foreground">{space.description}</p>}
        <p className="mt-1 text-xs text-muted-foreground">{spaceRoleLabel(space.my_role)}{space.is_default ? " · Espaço padrão" : ""}</p></div>
      <div className="flex flex-wrap gap-2">
        {canEnterSpace(company.role, space) && <button type="button" className={btn("secondary", "sm")} onClick={() => void enter()}><LogIn size={14} aria-hidden="true" />Entrar neste Espaço</button>}
        {isAdmin && !space.is_default && <button type="button" className={btn("danger-ghost", "sm")} onClick={() => { setDialogError(null); setPending({ kind: "archive" }); }}><Trash2 size={14} aria-hidden="true" />Arquivar</button>}
      </div>
    </div>
    {isAdmin && space.my_role === null && <p className="mt-3 rounded-lg border border-line-soft bg-sage p-3 text-sm">Como administrador, você gerencia este Espaço mas não lê o conteúdo dele. Para ler, use “Entrar neste Espaço” — os membros verão que você entrou.</p>}
    <div role="tablist" aria-label="Seções do Espaço" className="mt-5 flex gap-2 border-b border-line-soft">
      {([["people", "Pessoas", Users], ...(isAdmin ? [["folders", "Pastas", FolderOpen]] : [])] as [Tab, string, typeof Users][]).map(([key, label, Icon]) =>
        <button key={key} role="tab" id={`tab-${key}`} aria-selected={tab === key} aria-controls={`panel-${key}`} type="button" onClick={() => setTab(key)}
          className={`mo-interactive -mb-px border-b-2 px-3 py-2 text-sm font-semibold ${tab === key ? "border-primary text-ink" : "border-transparent text-muted-foreground"}`}><Icon size={14} className="mr-1 inline" aria-hidden="true" />{label}</button>)}
    </div>
    <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`} className="mt-4">
      {tab === "people"
        ? <PeopleTab company={company} space={space} canEdit={canPeople} visible={canSeeMembers} setError={setError} setNotice={setNotice} onChanged={() => onChanged(space.id)} />
        : <FoldersTab company={company} space={space} setError={setError} setNotice={setNotice} onChanged={() => onChanged(space.id)} />}
    </div>
    {pending?.kind === "archive" && <SpaceConfirmDialog title="Arquivar este Espaço?" confirmLabel="Arquivar" busyLabel="Arquivando…" busy={busy} error={dialogError} onConfirm={() => void archive()} onCancel={() => setPending(null)}>
      <p>As pessoas deixam de ver, por <strong>{space.name}</strong>, as pastas concedidas a ele. O que continuarem vendo por outros Espaços não muda.</p></SpaceConfirmDialog>}
  </section>;
}

function PeopleTab({ company, space, canEdit, visible, setError, setNotice, onChanged }: { company: Company; space: SpaceSummary; canEdit: boolean; visible: boolean; setError: (value: string | null) => void; setNotice: (value: string | null) => void; onChanged: () => Promise<void> }) {
  const [members, setMembers] = useState<SpaceMemberRow[]>([]); const [loading, setLoading] = useState(visible); const [loadError, setLoadError] = useState<string | null>(null);
  const [people, setPeople] = useState<OrgPerson[] | null>(null); const [peopleNote, setPeopleNote] = useState<string | null>(null); const [term, setTerm] = useState("");
  const [pending, setPending] = useState<{ member: SpaceMemberRow; impact: SpaceImpact | null } | null>(null); const [busy, setBusy] = useState(false); const [dialogError, setDialogError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    if (!visible) return;
    setLoading(true); setLoadError(null);
    try { setMembers(await spacesApi.members(company.id, space.id)); } catch (caught) { setLoadError(toSpacesError(caught).message); } finally { setLoading(false); }
  }, [company.id, space.id, visible]);
  useEffect(() => { void Promise.resolve().then(reload); }, [reload]);
  useEffect(() => {
    if (!canEdit) return;
    let alive = true;
    spacesApi.orgPeople(company.id).then((rows) => { if (alive) setPeople(rows); }).catch((caught) => { if (alive) { setPeople([]); setPeopleNote(toSpacesError(caught).code === "forbidden" ? "A lista de pessoas da organização só está disponível para administradores e responsáveis por Espaços." : toSpacesError(caught).message); } });
    return () => { alive = false; };
  }, [canEdit, company.id]);

  const candidates = useMemo(() => people ? addableCandidates(people, members, term).slice(0, 8) : [], [people, members, term]);
  async function add(person: OrgPerson) {
    if (!person.user_id) return;
    try { await spacesApi.addMember(company.id, space.id, person.user_id); setNotice(`${person.email} agora está em ${space.name}.`); setTerm(""); await reload(); await onChanged(); }
    catch (caught) { setError(toSpacesError(caught).message); }
  }
  async function changeRole(member: SpaceMemberRow, role: SpaceRole) {
    try { await spacesApi.setRole(company.id, space.id, member.user_id, role); setMembers((rows) => rows.map((row) => row.user_id === member.user_id ? { ...row, role } : row)); }
    catch (caught) { setError(toSpacesError(caught).message); }
  }
  async function askDisable(member: SpaceMemberRow) {
    setDialogError(null); setPending({ member, impact: null });
    try { const impact = await spacesApi.impact(company.id, space.id, member.user_id); setPending((current) => current && current.member.user_id === member.user_id ? { member, impact } : current); }
    catch (caught) { setDialogError(toSpacesError(caught).message); }
  }
  async function confirmDisable() {
    if (!pending) return;
    setBusy(true); setDialogError(null);
    try { await spacesApi.removeMember(company.id, space.id, pending.member.user_id); setNotice(`${pending.member.email} foi desabilitado em ${space.name}.`); setPending(null); await reload(); await onChanged(); }
    catch (caught) { setDialogError(toSpacesError(caught).message); } finally { setBusy(false); }
  }

  if (!visible) return <EmptyState icon={<Users size={22} />} title="Lista de pessoas indisponível" description="Somente quem participa do Espaço ou administra a organização vê as pessoas." />;
  return <div>
    {canEdit && <div className="mb-4">
      <label htmlFor="space-add-person" className="text-sm font-semibold">Habilitar uma pessoa</label>
      <input id="space-add-person" value={term} onChange={(event) => setTerm(event.target.value)} placeholder="Buscar por e-mail" autoComplete="off" className="mt-1 w-full rounded-md border border-line bg-paper px-3 py-2 text-sm" />
      {peopleNote && <p className="mt-2 text-xs text-muted-foreground">{peopleNote}</p>}
      {term.trim() && people && !peopleNote && <ul className="mt-2 divide-y divide-line-soft rounded-md border border-line-soft" aria-label="Resultados da busca">
        {candidates.length === 0 ? <li className="p-3 text-sm text-muted-foreground">Ninguém encontrado fora deste Espaço.</li> : candidates.map((person) => <li key={person.user_id ?? person.email} className="flex items-center justify-between gap-3 p-3 text-sm">
          <span className="min-w-0 truncate">{person.email}</span><button type="button" className={btn("secondary", "sm")} onClick={() => void add(person)}>Habilitar</button></li>)}</ul>}
    </div>}
    {loading ? <LoadingBlock label="Carregando pessoas…" className="min-h-32"><SkeletonList rows={3} /></LoadingBlock>
      : loadError ? <ErrorState icon={<CircleAlert size={22} />} title="Não foi possível carregar as pessoas" description={loadError} actions={<button className={btn("secondary")} onClick={() => void reload()}>Tentar novamente</button>} />
      : members.length === 0 ? <EmptyState icon={<Users size={22} />} title="Nenhuma pessoa neste Espaço" description={canEdit ? "Busque acima para habilitar a primeira pessoa." : undefined} />
      : <ul className="divide-y divide-line-soft rounded-md border border-line-soft" aria-label={`Pessoas em ${space.name}`}>{members.map((member) => <li key={member.user_id} className="flex flex-wrap items-center justify-between gap-3 p-3">
        <span className="min-w-0 break-all text-sm font-medium">{member.email}</span>
        <span className="flex items-center gap-2">
          {canEdit ? <><label className="sr-only" htmlFor={`role-${member.user_id}`}>Papel de {member.email}</label>
            <select id={`role-${member.user_id}`} value={member.role} onChange={(event) => void changeRole(member, event.target.value as SpaceRole)} className="rounded-md border border-line bg-paper px-2 py-1.5 text-sm"><option value="member">Membro</option><option value="manager">Responsável</option></select>
            <button type="button" className={btn("danger-ghost", "sm")} aria-label={`Desabilitar ${member.email} em ${space.name}`} onClick={() => void askDisable(member)}>Desabilitar</button></>
            : <span className="rounded-full bg-sage px-2 py-0.5 text-xs font-semibold text-muted-foreground">{spaceRoleLabel(member.role)}</span>}
        </span></li>)}</ul>}
    {pending && <SpaceConfirmDialog title={`Desabilitar ${pending.member.email} em ${space.name}?`} confirmLabel="Desabilitar" busyLabel="Desabilitando…" busy={busy} error={dialogError} onConfirm={() => void confirmDisable()} onCancel={() => setPending(null)}>
      {pending.impact ? <><p>{impactSentence(pending.member.email, pending.impact)}</p><p className="text-muted-foreground">O que a pessoa vê por outros Espaços continua visível.</p></>
        : dialogError ? null : <p aria-live="polite">Calculando o que muda…</p>}
    </SpaceConfirmDialog>}
  </div>;
}

function FoldersTab({ company, space, setError, setNotice, onChanged }: { company: Company; space: SpaceSummary; setError: (value: string | null) => void; setNotice: (value: string | null) => void; onChanged: () => Promise<void> }) {
  const [folders, setFolders] = useState<SpaceFolder[]>([]); const [loading, setLoading] = useState(true); const [loadError, setLoadError] = useState<string | null>(null); const [busyId, setBusyId] = useState<string | null>(null);
  const reload = useCallback(async () => { setLoading(true); setLoadError(null); try { setFolders(await spacesApi.folders(company.id)); } catch (caught) { setLoadError(toSpacesError(caught).message); } finally { setLoading(false); } }, [company.id]);
  useEffect(() => { void Promise.resolve().then(reload); }, [reload]);
  async function toggle(folder: SpaceFolder, granted: boolean) {
    setBusyId(folder.id);
    try {
      if (granted) await spacesApi.revoke(company.id, space.id, folder.id); else await spacesApi.grant(company.id, space.id, folder.id);
      setNotice(granted ? `“${folder.name}” não é mais compartilhada com ${space.name}.` : `“${folder.name}” agora é compartilhada com ${space.name}.`);
      await reload(); await onChanged();
    } catch (caught) { setError(toSpacesError(caught).message); } finally { setBusyId(null); }
  }
  if (loading) return <LoadingBlock label="Carregando pastas…" className="min-h-32"><SkeletonList rows={3} /></LoadingBlock>;
  if (loadError) return <ErrorState icon={<CircleAlert size={22} />} title="Não foi possível carregar as pastas" description={loadError} actions={<button className={btn("secondary")} onClick={() => void reload()}>Tentar novamente</button>} />;
  if (folders.length === 0) return <EmptyState icon={<FolderOpen size={22} />} title="Nenhuma pasta conectada" description="Conecte uma pasta em Integrações para poder compartilhá-la com um Espaço." />;
  return <ul className="divide-y divide-line-soft rounded-md border border-line-soft" aria-label="Pastas conectadas">{folders.map((folder) => {
    const granted = folder.spaces.some((item) => item.id === space.id); const others = folder.spaces.filter((item) => item.id !== space.id);
    return <li key={folder.id} className="flex flex-wrap items-center justify-between gap-3 p-3">
      <span className="min-w-0"><b className="block break-words text-sm">{folder.name}</b>
        <span className="text-xs text-muted-foreground">{folder.spaces.length === 0 ? "Sem Espaço — ninguém lê esta pasta" : `Também em: ${others.map((item) => item.name).join(", ") || "nenhum outro Espaço"}`}</span></span>
      <button type="button" disabled={busyId === folder.id} aria-busy={busyId === folder.id} aria-pressed={granted} className={btn(granted ? "secondary" : "primary", "sm")} onClick={() => void toggle(folder, granted)}>{granted ? `Remover de ${space.name}` : `Compartilhar com ${space.name}`}</button></li>;
  })}</ul>;
}

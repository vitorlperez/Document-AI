"use client";

import { ChevronRight } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Brand } from "../brand";
import { readActiveOrganizationId } from "./active-organization";
import { roleLabel, type Company, type User } from "./types-and-api";
import "./org-picker.css";

/** Shown right after login when the user belongs to more than one organization. */
export function OrganizationPicker({ user, companies, onChoose, onLogout }: { user: User; companies: Company[]; onChoose: (id: string) => void; onLogout: () => void }) {
  const [lastId] = useState(readActiveOrganizationId);
  const last = companies.find((item) => item.id === lastId)?.id;
  const lastRef = useRef<HTMLButtonElement>(null);
  const firstRef = useRef<HTMLButtonElement>(null);
  // Focus the last-used organization (or the first) so Enter continues straight into it.
  useEffect(() => { (lastRef.current ?? firstRef.current)?.focus(); }, []);
  return <main className="auth-page"><section className="auth-card org-picker" aria-labelledby="org-picker-title"><Brand /><p className="mt-6 text-sm text-muted-foreground">{user.email}</p><h1 id="org-picker-title" className="mt-2 text-3xl font-semibold">Escolha a organização</h1><p className="mt-3 leading-6 text-muted-foreground">Você participa de mais de uma organização. Selecione em qual deseja entrar agora; você pode trocar depois pelo menu.</p>
    <ul className="org-picker-list">{companies.map((company, index) => <li key={company.id}><button type="button" ref={company.id === last ? lastRef : index === 0 ? firstRef : undefined} data-last={company.id === last} onClick={() => onChoose(company.id)} className="org-picker-option"><span className="org-picker-avatar" aria-hidden="true">{company.name.trim().charAt(0).toUpperCase() || "?"}</span><span className="org-picker-name"><strong>{company.name}</strong><span>{roleLabel(company.role)}</span></span>{company.id === last && <span className="org-picker-last">Última usada</span>}<ChevronRight size={16} aria-hidden="true" /></button></li>)}</ul>
    <button type="button" onClick={onLogout} className="org-picker-logout">Sair</button></section></main>;
}

"""Medicao 13: parser de links (casos sinteticos + IDs reais) e regra 'compartilhada explicitamente' (sharedWithMeTime subindo por parents)."""
from lib import ID_RE, Robot, load_state, parse_drive_link, save_result

st = load_state()["folders"]
r = Robot("a")
F = st["poc-notify-on"]
kid = r.call("/files", {"q": f"'{F}' in parents and trashed=false", "fields": "files(id,name,mimeType)"})["json"]["files"][0]
X = kid["id"]
root = st["arvore-1000"]
D1 = r.call("/files", {"q": f"'{root}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false", "fields": "files(id,name)", "orderBy": "name"})["json"]["files"][0]["id"]
PUB = st["poc-link-public"]

cases = [  # (descricao, entrada, kind esperado)
    ("pasta /drive/folders", f"https://drive.google.com/drive/folders/{F}", "folder"),
    ("pasta ?usp=sharing", f"https://drive.google.com/drive/folders/{F}?usp=sharing", "folder"),
    ("pasta ?usp=drive_link", f"https://drive.google.com/drive/folders/{F}?usp=drive_link", "folder"),
    ("pasta com resourcekey", f"https://drive.google.com/drive/folders/{F}?resourcekey=0-AbCdEfGh&usp=sharing", "folder"),
    ("pasta /drive/u/0/folders", f"https://drive.google.com/drive/u/0/folders/{F}", "folder"),
    ("pasta /drive/u/2/folders ?authuser", f"https://drive.google.com/drive/u/2/folders/{F}?authuser=2", "folder"),
    ("pasta /drive/mobile/folders", f"https://drive.google.com/drive/mobile/folders/{F}", "folder"),
    ("pasta http sem s", f"http://drive.google.com/drive/folders/{F}", "folder"),
    ("pasta /a/dominio/ legado", f"https://drive.google.com/a/acme.com.br/drive/folders/{F}", "folder"),
    ("folderview?id=", f"https://drive.google.com/folderview?id={F}", "folder"),
    ("folderview?usp=&id=", f"https://drive.google.com/folderview?usp=sharing&id={F}", "folder"),
    ("open?id= (pasta)", f"https://drive.google.com/open?id={F}", "ambiguous"),
    ("open?id= (arquivo)", f"https://drive.google.com/open?id={X}", "ambiguous"),
    ("ID cru (pasta)", F, "ambiguous"),
    ("ID cru com espacos", f"  {F}\n", "ambiguous"),
    ("arquivo /file/d/", f"https://drive.google.com/file/d/{X}/view?usp=sharing", "file"),
    ("Google Doc", f"https://docs.google.com/document/d/{X}/edit", "file"),
    ("Google Sheet", f"https://docs.google.com/spreadsheets/d/{X}/edit#gid=0", "file"),
    ("Slides", f"https://docs.google.com/presentation/d/{X}/edit", "file"),
    ("Meu Drive (raiz)", "https://drive.google.com/drive/my-drive", "invalid"),
    ("Compartilhados comigo", "https://drive.google.com/drive/shared-with-me", "invalid"),
    ("Recentes", "https://drive.google.com/drive/recent", "invalid"),
    ("dominio falso", f"https://drive.google.com.evil.example/drive/folders/{F}", "invalid"),
    ("dominio falso 2", f"https://evil.example/?u=https://drive.google.com/drive/folders/{F}", "invalid"),
    ("esquema javascript", f"javascript:alert('{F}')", "invalid"),
    ("injecao em q (aspas)", "x' or name contains 'a", "invalid"),
    ("injecao em q (ID valido + trecho)", f"{F}' or 'x' in parents", "invalid"),
    ("ID curto demais", "abc123", "invalid"),
    ("ID longo demais", "a" * 200, "invalid"),
    ("vazio", "", "invalid"),
    ("texto qualquer", "minha pasta de contratos", "invalid"),
]
rows = []
for desc, text, expected in cases:
    p = parse_drive_link(text)
    rows.append({"case": desc, "kind": p["kind"], "expected": expected, "ok": p["kind"] == expected,
                 "id_is_valid_charset": bool(p["id"] and ID_RE.match(p["id"]))})
# resolucao via API para os ambiguos/pasta: classificacao por mimeType
api = {}
for label, _id in {"folder_via_open_or_raw": F, "file_via_open_or_raw": X, "child_folder": D1, "nonexistent": "A" * 33}.items():
    g = r.call(f"/files/{_id}", {"fields": "id,name,mimeType,parents,sharedWithMeTime,sharingUser(emailAddress)", "supportsAllDrives": "true"})
    j = g.get("json", {})
    api[label] = {"status": g["status"], "mime": j.get("mimeType"), "is_folder": j.get("mimeType") == "application/vnd.google-apps.folder",
                  "has_parents": bool(j.get("parents")), "has_sharedWithMeTime": bool(j.get("sharedWithMeTime")), "reason": g.get("reason")}


def explicit_share_root(fid, hops=10):
    """Sobe por parents ate achar um no com sharedWithMeTime (compartilhamento explicito com o robo). None = nao explicito."""
    for i in range(hops):
        g = r.call(f"/files/{fid}", {"fields": "id,parents,sharedWithMeTime", "supportsAllDrives": "true"})
        if g["status"] != 200:
            return {"result": "not_accessible", "hops": i}
        j = g["json"]
        if j.get("sharedWithMeTime"):
            return {"result": "explicit_share_found", "hops": i, "is_selected_itself": i == 0}
        if not j.get("parents"):
            return {"result": "no_explicit_share", "hops": i}
        fid = j["parents"][0]
    return {"result": "too_deep"}


rules = {"top_level_shared_folder": explicit_share_root(F), "child_folder_of_shared_tree": explicit_share_root(D1),
         "public_link_folder": explicit_share_root(PUB), "nonexistent": explicit_share_root("A" * 33)}
out = {"parser_cases": rows, "parser_pass": sum(1 for x in rows if x["ok"]), "parser_total": len(rows),
       "api_classification": api, "explicit_share_rule_via_parents_climb": rules,
       "not_tested": ["Drive compartilhado (Shared Drive) vs Meu Drive: requer Workspace", "link de atalho (shortcut) colado: id do atalho nao testado diretamente; ver m07 (mimeType shortcut)"]}
print(save_result("m13-links", out))
print(out["parser_pass"], "/", out["parser_total"])
for x in rows:
    if not x["ok"]:
        print("FALHA", x)
print(api)
print(rules)

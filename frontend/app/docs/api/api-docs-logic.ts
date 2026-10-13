/** Pure helpers that turn the public /v1 OpenAPI document into what the docs page renders. */
export const API_BASE = "https://api.arquivio.com.br";
export const SPEC_URL = "/api/v1/openapi.json";

type Json = Record<string, unknown>;
export type Schema = { $ref?: string; type?: string; format?: string; title?: string; description?: string; default?: unknown; minimum?: number; maximum?: number; minLength?: number; maxLength?: number; maxItems?: number; items?: Schema; anyOf?: Schema[]; properties?: Record<string, Schema>; required?: string[] };
export type Field = { name: string; type: string; required: boolean; constraints: string; location?: string };
export type Endpoint = {
  id: string; method: "GET" | "POST"; path: string; summary: string; description: string; scope: string | null;
  params: Field[]; body: Field[]; example: Json | null; responses: { status: string; description: string }[];
};

const BODY_EXAMPLES: Record<string, Json> = {
  "/v1/search": { query: "Aurora", limit: 10 },
  "/v1/ask": { question: "Qual é o prazo do contrato Aurora?" },
};

export function resolve(spec: Json, schema: Schema | undefined): Schema {
  if (!schema?.$ref) return schema ?? {};
  let node: unknown = spec;
  for (const part of schema.$ref.replace(/^#\//, "").split("/")) node = (node as Json | undefined)?.[part];
  return (node as Schema | undefined) ?? {};
}

export function typeLabel(spec: Json, schema: Schema | undefined): string {
  const s = resolve(spec, schema);
  if (s.anyOf) return [...new Set(s.anyOf.map((item) => typeLabel(spec, item)))].filter((t) => t !== "null").join(" | ") || "null";
  if (s.type === "array") return `${typeLabel(spec, s.items)}[]`;
  return s.format ? `${s.type ?? "any"} (${s.format})` : (s.type ?? "any");
}

function constraints(spec: Json, schema: Schema | undefined): string {
  const s = resolve(spec, schema);
  const nested = s.anyOf?.map((item) => resolve(spec, item)).find((item) => item.type === "array") ?? s;
  const parts: string[] = [];
  if (s.minLength !== undefined || s.maxLength !== undefined) parts.push(`${s.minLength ?? 0}–${s.maxLength ?? "∞"} caracteres`);
  if (s.minimum !== undefined || s.maximum !== undefined) parts.push(`${s.minimum ?? "−∞"}–${s.maximum ?? "∞"}`);
  if (nested.maxItems !== undefined) parts.push(`até ${nested.maxItems} itens`);
  if (s.default !== undefined) parts.push(`padrão ${JSON.stringify(s.default)}`);
  return parts.join(" · ");
}

export function bodyFields(spec: Json, schema: Schema | undefined): Field[] {
  const s = resolve(spec, schema);
  return Object.entries(s.properties ?? {}).map(([name, prop]) => ({
    name, type: typeLabel(spec, prop), required: (s.required ?? []).includes(name), constraints: constraints(spec, prop),
  }));
}

function genericExample(spec: Json, schema: Schema | undefined): Json {
  const s = resolve(spec, schema);
  const out: Json = {};
  for (const name of s.required ?? []) out[name] = "exemplo";
  return out;
}

const scopeOf = (description: string) => /Escopo: `([^`]+)`/.exec(description)?.[1] ?? null;

/** Reads every operation of the document; an unexpected shape yields fewer endpoints rather than throwing. */
export function endpointsFrom(spec: Json): Endpoint[] {
  const paths = (spec.paths ?? {}) as Record<string, Record<string, Json>>;
  const result: Endpoint[] = [];
  for (const [path, operations] of Object.entries(paths)) {
    for (const [verb, op] of Object.entries(operations)) {
      const method = verb.toUpperCase();
      if (method !== "GET" && method !== "POST") continue;
      const description = String(op.description ?? "");
      const bodySchema = ((op.requestBody as Json | undefined)?.content as Record<string, { schema?: Schema }> | undefined)?.["application/json"]?.schema;
      const params = ((op.parameters ?? []) as Json[]).map((p) => ({
        name: String(p.name), location: String(p.in), required: Boolean(p.required), type: typeLabel(spec, p.schema as Schema), constraints: constraints(spec, p.schema as Schema),
      }));
      result.push({
        id: `${verb}-${path}`.replace(/[^a-z0-9]+/gi, "-").replace(/-$/, "").toLowerCase(),
        method, path, summary: String(op.summary ?? path), description, scope: scopeOf(description),
        params, body: bodySchema ? bodyFields(spec, bodySchema) : [],
        example: bodySchema ? (BODY_EXAMPLES[path] ?? genericExample(spec, bodySchema)) : null,
        responses: Object.entries((op.responses ?? {}) as Record<string, Json>).map(([status, r]) => ({ status, description: String(r.description ?? "") })),
      });
    }
  }
  const order = ["/v1/whoami", "/v1/sources", "/v1/search", "/v1/documents/{document_id}", "/v1/ask"];
  return result.sort((a, b) => (order.indexOf(a.path) + 1 || 99) - (order.indexOf(b.path) + 1 || 99));
}

export type Language = "curl" | "javascript" | "python";
export const LANGUAGES: { id: Language; label: string }[] = [{ id: "curl", label: "curl" }, { id: "javascript", label: "JavaScript" }, { id: "python", label: "Python" }];

/** Placeholders ($KEY, $DOCUMENT_ID) are shown literally: the page never holds or asks for a real secret. */
export function codeSample(endpoint: Pick<Endpoint, "method" | "path" | "example">, language: Language, base = API_BASE): string {
  const path = endpoint.path.replace("{document_id}", "$DOCUMENT_ID");
  const url = `${base}${path}`;
  const body = endpoint.example ? JSON.stringify(endpoint.example) : null;
  if (language === "curl") {
    const lines = [`curl ${endpoint.method === "POST" ? "-X POST " : ""}"${url}"`, `  -H "Authorization: Bearer $KEY"`];
    if (body) lines.push(`  -H "Content-Type: application/json"`, `  -d '${body.replaceAll("'", "'\"'\"'")}'`);
    return lines.join(" \\\n");
  }
  if (language === "javascript") {
    const jsUrl = path.includes("$DOCUMENT_ID") ? "`" + url.replace("$DOCUMENT_ID", "${documentId}") + "`" : `"${url}"`;
    const init = [`  method: "${endpoint.method}",`, `  headers: {`, `    Authorization: \`Bearer \${process.env.ARQUIVIO_KEY}\`,`, ...(body ? [`    "Content-Type": "application/json",`] : []), `  },`, ...(body ? [`  body: JSON.stringify(${JSON.stringify(endpoint.example)}),`] : [])];
    return `const response = await fetch(${jsUrl}, {\n${init.join("\n")}\n});\nif (!response.ok) throw new Error(\`Arquivio API: \${response.status}\`);\nconsole.log(await response.json());`;
  }
  const pyUrl = path.includes("$DOCUMENT_ID") ? `f"${url.replace("$DOCUMENT_ID", "{document_id}")}"` : `"${url}"`;
  const args = [pyUrl, `headers={"Authorization": f"Bearer {os.environ['ARQUIVIO_KEY']}"}`, ...(body ? [`json=${pythonLiteral(endpoint.example)}`] : []), "timeout=30"];
  return `import os\nimport requests\n\nresponse = requests.${endpoint.method.toLowerCase()}(\n${args.map((a) => `    ${a},`).join("\n")}\n)\nresponse.raise_for_status()\nprint(response.json())`;
}

function pythonLiteral(value: unknown): string {
  if (value === null) return "None";
  if (typeof value === "boolean") return value ? "True" : "False";
  if (Array.isArray(value)) return `[${value.map(pythonLiteral).join(", ")}]`;
  if (typeof value === "object") return `{${Object.entries(value as Json).map(([k, v]) => `${JSON.stringify(k)}: ${pythonLiteral(v)}`).join(", ")}}`;
  return JSON.stringify(value);
}

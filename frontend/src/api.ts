// Types mirror backend/archdraft/schema.py and service.py.

export type Mode = "pipeline" | "single_agent" | "baseline";
export type ElementKind = "person" | "system" | "component" | "datastore" | "external";

export interface ArchElement {
  id: string;
  name: string;
  kind: ElementKind;
  technology: string | null;
  responsibility: string;
  satisfies: string[];
  confidence: number;
}

export interface Relation {
  id: string;
  source: string;
  target: string;
  description: string;
  protocol: string | null;
  operation?: "calls" | "reads" | "writes" | "reads_writes" | "publishes" | "consumes";
  satisfies: string[];
}

export interface Fulfilment {
  obligation_id: string;
  element_ids: string[];
  relation_ids: string[];
  explanation: string;
}

export interface Obligation {
  id: string;
  requirement_ids: string[];
  category: string;
  statement: string;
}

export interface RequirementsAnalysis {
  system_name: string;
  system_description: string;
  requirements: Requirement[];
  actors: string[];
  data_classes: { name: string; requirement_ids: string[]; characteristics: string; personal_data: boolean }[];
  obligations: Obligation[];
  ambiguities: { requirement_id: string; issue: string; assumption: string }[];
}

export type CheckStatus = "met" | "partial" | "missing";

export interface ObligationCheck {
  obligation_id: string;
  status: CheckStatus;
  reason: string;
}

export interface Finding {
  severity: "blocking" | "major" | "minor";
  requirement_ids: string[];
  element_ids: string[];
  problem: string;
  fix: string;
}

export interface CriticReport {
  obligation_checks: ObligationCheck[];
  findings: Finding[];
}

export interface ReviewRound {
  round: number;
  met: number;
  partial: number;
  missing: number;
  blocking: number;
  major: number;
  minor: number;
}

export interface Judgement {
  score: number;
  met: number;
  partial: number;
  missing: number;
  total: number;
  checks: ObligationCheck[];
  unjustified_elements: string[];
  illogical_connections: string[];
  obligations_from: string;
  judge_model: string;
}

export interface Requirement {
  id: string;
  text: string;
  kind: "functional" | "non_functional";
}

export interface ArchitectureModel {
  system_name: string;
  system_description: string;
  requirements: Requirement[];
  elements: ArchElement[];
  relations: Relation[];
  unresolved: { requirement_id: string; reason: string }[];
  fulfilments?: Fulfilment[];
}

export interface ValidationIssue {
  rule: string;
  message: string;
  element_id: string | null;
  requirement_id: string | null;
  severity?: "error" | "warning";
}

export interface Coverage {
  covered: number;
  total: number;
  percent: number;
  uncovered: string[];
  basis: string;
}

export interface DiagramStats {
  elements: number;
  relations: number;
  traced_elements: number;
  datastore_nodes: number;
  datastore_technologies: string[];
  basis: string;
}

export interface GenerateResult {
  id: string;
  created_at: string;
  mode: Mode;
  llm_model: string;
  requirements_text: string;
  model: ArchitectureModel | null;
  mermaid: string;
  node_ids: Record<string, string>;
  validation_errors: ValidationIssue[];
  validation_history: { attempt: number; error_count: number; warning_count?: number; errors: ValidationIssue[] }[];
  coverage: Coverage;
  stats: DiagramStats;
  timings: { total_ms: number; nodes: { node: string; ms: number }[] };
  llm_calls: number;
  raw_llm_response: string;
  analysis?: RequirementsAnalysis | null;
  review?: CriticReport | null;
  review_history?: ReviewRound[];
  judgement?: Judgement | null;
}

export interface StepEvent {
  node: string;
  ms: number;
}

export interface Sample {
  id: string;
  title: string;
  text: string;
}

export interface ProjectSummary {
  id: string;
  created_at: string;
  mode: Mode;
  system_name: string;
  coverage_percent: number;
  error_count: number;
}

export interface Health {
  ok: boolean;
  model: string | null;
  credentials: boolean;
  adk_version: string;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, init);
  } catch {
    throw new Error("Cannot reach the backend. Is it running on port 8000?");
  }
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      if (typeof body.detail === "string") detail = body.detail;
      else if (body.detail) detail = JSON.stringify(body.detail);
    } catch {
      // Non-JSON error body (for example the Vite proxy when the backend is down).
      if (response.status >= 500) detail = "Cannot reach the backend. Is it running on port 8000?";
    }
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}

const BACKEND_DOWN = "Cannot reach the backend. Is it running on port 8000?";

/** POST /api/generate/stream: calls onStep for every finished pipeline node. */
async function generateStream(
  requirements_text: string,
  mode: Mode,
  onStep: (step: StepEvent) => void,
): Promise<GenerateResult> {
  let response: Response;
  try {
    response = await fetch("/api/generate/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ requirements_text, mode }),
    });
  } catch {
    throw new Error(BACKEND_DOWN);
  }
  if (!response.ok || !response.body) throw new Error(response.status >= 500 ? BACKEND_DOWN : response.statusText);

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done });
    let newline: number;
    while ((newline = buffer.indexOf("\n")) >= 0) {
      const line = buffer.slice(0, newline).trim();
      buffer = buffer.slice(newline + 1);
      if (!line) continue;
      const message = JSON.parse(line);
      if (message.type === "step") onStep({ node: message.node, ms: message.ms });
      else if (message.type === "result") return message.result as GenerateResult;
      else if (message.type === "error") throw new Error(message.detail);
    }
    if (done) break;
  }
  throw new Error("The backend closed the connection before the result arrived.");
}

// ---------------------------------------------------------------------------------------------
// Public demo (GitHub Pages): no backend, no API key. The pages replay real saved Gemini runs
// that were exported to public/demo/. Built with VITE_DEMO=true.
// ---------------------------------------------------------------------------------------------

export const DEMO = import.meta.env.VITE_DEMO === "true";
const DEMO_MESSAGE =
  "This is the public demo: it replays saved real runs for the two built-in samples. " +
  "To generate from your own requirements, run ArchDraft locally (see the README).";

let demoRuns: Promise<GenerateResult[]> | null = null;

function loadDemoRuns(): Promise<GenerateResult[]> {
  demoRuns ??= fetch(`${import.meta.env.BASE_URL}demo/runs.json`).then((r) => {
    if (!r.ok) throw new Error("The demo data could not be loaded.");
    return r.json() as Promise<GenerateResult[]>;
  });
  return demoRuns;
}

const demoApi = {
  health: async (): Promise<Health> => ({ ok: true, model: null, credentials: false, adk_version: "2.11.0" }),
  samples: () =>
    fetch(`${import.meta.env.BASE_URL}demo/samples.json`).then((r) => r.json() as Promise<Sample[]>),
  projects: async (): Promise<ProjectSummary[]> =>
    (await loadDemoRuns())
      .map((r) => ({
        id: r.id,
        created_at: r.created_at,
        mode: r.mode,
        system_name: r.model?.system_name ?? "(baseline diagram)",
        coverage_percent: r.coverage.percent,
        error_count: r.validation_errors.length,
      }))
      .sort((a, b) => b.created_at.localeCompare(a.created_at)),
  project: async (id: string): Promise<GenerateResult> => {
    const run = (await loadDemoRuns()).find((r) => r.id === id);
    if (!run) throw new Error(`No saved run '${id}'.`);
    return run;
  },
  /** Replays the newest saved run whose mode and requirements match, node by node. */
  generateStream: async (
    requirements_text: string,
    mode: Mode,
    onStep: (step: StepEvent) => void,
  ): Promise<GenerateResult> => {
    const wanted = requirements_text.trim();
    const match = (await loadDemoRuns())
      .filter((r) => r.mode === mode && r.requirements_text.trim() === wanted)
      .sort((a, b) => b.created_at.localeCompare(a.created_at))[0];
    if (!match) throw new Error(DEMO_MESSAGE);
    for (const node of match.timings.nodes) {
      onStep({ node: node.node, ms: node.ms });
      await new Promise((resolve) => setTimeout(resolve, 350));
    }
    return match;
  },
  generate: async (): Promise<GenerateResult> => {
    throw new Error(DEMO_MESSAGE);
  },
  judge: async (): Promise<Record<string, Judgement>> => {
    throw new Error("The independent judge calls Gemini, so it is switched off in the public demo.");
  },
};

const liveApi = {
  health: () => request<Health>("/api/health"),
  samples: () => request<Sample[]>("/api/samples"),
  projects: () => request<ProjectSummary[]>("/api/projects"),
  project: (id: string) => request<GenerateResult>(`/api/projects/${encodeURIComponent(id)}`),
  generate: (requirements_text: string, mode: Mode) =>
    request<GenerateResult>("/api/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ requirements_text, mode }),
    }),
  generateStream,
  judge: (project_ids: string[]) =>
    request<Record<string, Judgement>>("/api/judge", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project_ids }),
    }),
};

export const api = DEMO ? demoApi : liveApi;

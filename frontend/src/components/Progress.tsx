import { useEffect, useState } from "react";
import type { StepEvent } from "../api";

/** Human names for the ADK graph's nodes. Internal glue nodes are hidden. */
const NODE_LABELS: Record<string, string | null> = {
  prepare_input: "Read requirements",
  requirements_analyst: "Analyst agent: data classes, design obligations, open questions",
  build_architect_request: null,
  requirements_to_architecture: "Architect agent: designs the containers and data flows",
  validate_architecture: "Validator: 11 deterministic rules",
  build_repair_request: "Validator found errors: sent back to the architect",
  build_review_request: null,
  architecture_critic: "Critic agent: checks every obligation against the design",
  review_router: null,
  build_revision_request: "Critic found gaps: sent back to the architect for one revision",
  render_diagram: "Draw the diagram",
  naive_baseline: "One naive prompt",
};

/** What usually runs next, so the user sees which agent is working right now. */
const NEXT: Record<string, string> = {
  prepare_input: "Analyst agent is reading the requirements",
  requirements_analyst: "Architect agent is designing",
  build_architect_request: "Architect agent is designing",
  build_repair_request: "Architect agent is repairing the design",
  build_revision_request: "Architect agent is revising the design",
  requirements_to_architecture: "Validator is checking",
  build_review_request: "Critic agent is reviewing",
  architecture_critic: "Deciding whether a revision is needed",
};

function baseName(node: string): string {
  return node.replace(/ \(run \d+\)$/, "");
}

function seconds(ms: number): string {
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${ms} ms`;
}

export function Progress({ steps, title }: { steps: StepEvent[]; title: string }) {
  const [now, setNow] = useState(Date.now());
  const [started] = useState(Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 500);
    return () => window.clearInterval(timer);
  }, []);
  const visible = steps.filter((s) => NODE_LABELS[baseName(s.node)] !== null);
  const last = steps.length ? baseName(steps[steps.length - 1].node) : "";
  const working = steps.length === 0 ? "Starting" : (NEXT[last] ?? "Working");
  return (
    <div className="progress" role="status" aria-live="polite">
      <p>
        <strong>{title}</strong> <span className="muted">{Math.round((now - started) / 1000)} s</span>
      </p>
      <ol className="progress-steps">
        {visible.map((s, i) => {
          const run = s.node.match(/\(run (\d+)\)$/);
          return (
            <li key={i} className="done">
              <span aria-hidden="true">✓</span> {NODE_LABELS[baseName(s.node)] ?? s.node}
              {run ? <span className="muted"> (round {run[1]})</span> : null}
              <span className="muted"> · {seconds(s.ms)}</span>
            </li>
          );
        })}
        <li className="current">
          <span className="spinner-dot" aria-hidden="true">•</span> {working}…
        </li>
      </ol>
      <p className="muted small">The full pipeline usually takes 1–4 minutes; each agent waits for the previous one.</p>
    </div>
  );
}

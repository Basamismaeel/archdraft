import type { GenerateResult, ValidationIssue } from "../api";
import { normaliseId } from "./Inspector";

interface Props {
  result: GenerateResult;
  onSelectElement: (id: string) => void;
  onHighlightRequirement: (id: string) => void;
}

const RULE_LABELS: Record<string, string> = {
  relation_endpoint_exists: "Relation points to a missing element",
  no_isolated_element: "Isolated element",
  element_traced: "Element cites no requirement",
  relation_traced: "Relation cites no requirement",
  known_requirement_id: "Unknown requirement ID",
  requirement_accounted_for: "Requirement not covered or explained",
  unique_element_id: "Duplicate element ID",
  input_requirement_kept: "Requirement dropped from the input",
  datastore_written: "Datastore never written to",
  obligation_addressed: "Obligation not addressed",
  fulfilment_reference: "Fulfilment names a missing part",
  blanket_citation: "Blanket citation",
  over_citation: "Element cites too much",
};

function seconds(ms: number): string {
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${ms} ms`;
}

function pct(n: number, total: number): string {
  return total ? `${Math.round((100 * n) / total)}%` : "–";
}

export function ReportStrip({ result, onSelectElement, onHighlightRequirement }: Props) {
  const model = result.model;
  const texts = new Map((model?.requirements ?? []).map((r) => [normaliseId(r.id), r.text]));
  const elementIds = new Set((model?.elements ?? []).map((e) => e.id));
  const unresolved = new Map((model?.unresolved ?? []).map((u) => [normaliseId(u.requirement_id), u.reason]));
  const errors = result.validation_errors.filter((e) => (e.severity ?? "error") === "error");
  const warnings = result.validation_errors.filter((e) => e.severity === "warning");
  const checks = result.review?.obligation_checks ?? [];
  const obligations = result.analysis?.obligations.length ?? 0;
  const met = checks.filter((c) => c.status === "met").length;
  const partial = checks.filter((c) => c.status === "partial").length;

  function issueTarget(issue: ValidationIssue): (() => void) | null {
    if (issue.element_id && elementIds.has(issue.element_id)) return () => onSelectElement(issue.element_id!);
    if (issue.requirement_id && model) return () => onHighlightRequirement(normaliseId(issue.requirement_id!));
    return null;
  }

  function issueList(issues: ValidationIssue[], className: string) {
    return (
      <ul className="plain-list small">
        {issues.map((issue, i) => {
          const go = issueTarget(issue);
          return (
            <li key={i} className={className}>
              <strong>{RULE_LABELS[issue.rule] ?? issue.rule}:</strong>{" "}
              {go ? (
                <button type="button" className={`link-button ${className}`} onClick={go}>
                  {issue.message}
                </button>
              ) : (
                issue.message
              )}
            </li>
          );
        })}
      </ul>
    );
  }

  return (
    <section className="report" aria-label="Report">
      <div className="report-cell">
        <h3>Coverage</h3>
        <p className="big-number">{result.coverage.percent}%</p>
        <p className="small">
          {result.coverage.covered} of {result.coverage.total} requirements cited
        </p>
        {result.coverage.uncovered.length > 0 && (
          <ul className="plain-list small">
            {result.coverage.uncovered.map((id) => (
              <li key={id}>
                <span className="req-id">{id}</span> {texts.get(id) ?? ""}
                {unresolved.has(id) && <span className="muted"> (unresolved: {unresolved.get(id)})</span>}
              </li>
            ))}
          </ul>
        )}
        <p className="muted small">{result.coverage.basis}</p>
      </div>

      <div className="report-cell">
        <h3>Design obligations</h3>
        {result.analysis && result.review ? (
          <>
            <p className="big-number">{pct(met, obligations)}</p>
            <p className="small">
              {met} met, {partial} partial, {obligations - met - partial} missing of {obligations}
            </p>
            {(result.review_history ?? []).length > 1 && (
              <p className="small muted">
                Before revision:{" "}
                {pct(result.review_history![0].met, obligations)} met → after:{" "}
                {pct(result.review_history![result.review_history!.length - 1].met, obligations)}
              </p>
            )}
            <p className="muted small">judged by the critic agent against the final design</p>
          </>
        ) : (
          <p className="small muted">
            {result.mode === "baseline"
              ? "No obligations: the baseline is one naive prompt. Use the independent judge in Side by side."
              : "Not analysed: single-agent mode has no analyst or critic."}
          </p>
        )}
      </div>

      <div className="report-cell wide">
        <h3>Validation</h3>
        {result.mode === "baseline" ? (
          <p className="small muted">Not validated: the baseline produces no structured model to check.</p>
        ) : (
          <>
            <p className="small">
              {result.validation_history.map((a, i) => (
                <span key={a.attempt}>
                  {i > 0 && " → "}
                  check {a.attempt}: {a.error_count === 0 ? "passed" : `${a.error_count} error${a.error_count === 1 ? "" : "s"}`}
                </span>
              ))}
            </p>
            {errors.length === 0 ? <p className="small">All rules pass on the final design.</p> : issueList(errors, "error-text")}
            {warnings.length > 0 && (
              <>
                <p className="small muted">Warnings (do not block):</p>
                {issueList(warnings, "muted")}
              </>
            )}
          </>
        )}
      </div>

      <div className="report-cell">
        <h3>Pipeline run</h3>
        <ol className="plain-list small trace">
          {result.timings.nodes.map((n, i) => (
            <li key={i}>
              <code>{n.node}</code> <span className="muted">{seconds(n.ms)}</span>
            </li>
          ))}
        </ol>
        <p className="muted small">
          {result.llm_calls} LLM call{result.llm_calls === 1 ? "" : "s"} · {seconds(result.timings.total_ms)} ·{" "}
          {result.llm_model}
        </p>
      </div>

      <details className="report-raw">
        <summary>Raw model response</summary>
        <pre>{result.raw_llm_response}</pre>
      </details>
    </section>
  );
}

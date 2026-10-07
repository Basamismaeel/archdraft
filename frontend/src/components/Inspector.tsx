import { useState } from "react";
import type { ArchitectureModel, CheckStatus, GenerateResult, Requirement } from "../api";

export interface Highlight {
  key: string; // e.g. "req:FR-01", "ob:OB-03", "finding:2"
  elementIds: Set<string>;
}

interface Props {
  result: GenerateResult | null;
  selected: string | null;
  highlight: Highlight | null;
  onSelectElement: (id: string | null) => void;
  onHighlight: (highlight: Highlight | null) => void;
}

type Tab = "requirements" | "obligations" | "review" | "questions";

export function normaliseId(raw: string): string {
  const m = raw.trim().match(/^(N?FR)-0*(\d+)$/i);
  return m ? `${m[1].toUpperCase()}-${m[2].padStart(2, "0")}` : raw.trim();
}

function requirementIndex(model: ArchitectureModel): Map<string, Requirement> {
  return new Map(model.requirements.map((r) => [normaliseId(r.id), r]));
}

export function elementsSatisfying(model: ArchitectureModel, requirementId: string): string[] {
  const target = normaliseId(requirementId);
  return model.elements.filter((e) => e.satisfies.some((r) => normaliseId(r) === target)).map((e) => e.id);
}

/** Elements touched by an obligation's fulfilment: named elements plus both ends of named relations. */
export function elementsFulfilling(model: ArchitectureModel, obligationId: string): string[] {
  const fulfilment = (model.fulfilments ?? []).find((f) => f.obligation_id === obligationId);
  if (!fulfilment) return [];
  const ids = new Set(fulfilment.element_ids);
  for (const rel of model.relations) {
    if (fulfilment.relation_ids.includes(rel.id)) {
      ids.add(rel.source);
      ids.add(rel.target);
    }
  }
  return [...ids];
}

const STATUS_LABEL: Record<CheckStatus, string> = { met: "met", partial: "partial", missing: "missing" };

function StatusBadge({ status }: { status: CheckStatus | undefined }) {
  if (!status) return <span className="badge">not reviewed</span>;
  return <span className={`badge badge-${status}`}>{STATUS_LABEL[status]}</span>;
}

function RequirementList({ model, highlight, onHighlight }: {
  model: ArchitectureModel;
  highlight: Highlight | null;
  onHighlight: Props["onHighlight"];
}) {
  const unresolved = new Map(model.unresolved.map((u) => [normaliseId(u.requirement_id), u.reason]));
  const citedByRelation = new Set(model.relations.flatMap((r) => r.satisfies.map(normaliseId)));
  return (
    <>
      <p className="muted small">
        Every requirement and the elements that satisfy it. Click one to highlight them in the diagram.
      </p>
      <ul className="req-list">
        {model.requirements.map((req) => {
          const id = normaliseId(req.id);
          const elements = elementsSatisfying(model, id);
          const key = `req:${id}`;
          const status =
            elements.length > 0
              ? `${elements.length} element${elements.length === 1 ? "" : "s"}`
              : citedByRelation.has(id)
                ? "relation only"
                : unresolved.has(id)
                  ? "unresolved"
                  : "not covered";
          const bad = elements.length === 0 && !citedByRelation.has(id);
          return (
            <li key={id}>
              <button
                type="button"
                className={`req-row${highlight?.key === key ? " active" : ""}`}
                onClick={() => onHighlight(highlight?.key === key ? null : { key, elementIds: new Set(elements) })}
              >
                <span className="req-id">{id}</span>
                <span className="req-text">{req.text}</span>
                <span className={`req-status${bad ? " error-text" : " muted"}`}>{status}</span>
              </button>
              {unresolved.has(id) && <p className="small muted indent">Reason: {unresolved.get(id)}</p>}
            </li>
          );
        })}
      </ul>
    </>
  );
}

function ObligationList({ result, highlight, onHighlight }: {
  result: GenerateResult;
  highlight: Highlight | null;
  onHighlight: Props["onHighlight"];
}) {
  const model = result.model!;
  const analysis = result.analysis!;
  const checks = new Map((result.review?.obligation_checks ?? []).map((c) => [c.obligation_id, c]));
  const fulfilments = new Map((model.fulfilments ?? []).map((f) => [f.obligation_id, f]));
  return (
    <>
      <p className="muted small">
        Design obligations the analyst derived from the requirements, with the critic's verdict on the final design.
        Click one to highlight the parts of the design that fulfil it.
      </p>
      <ul className="req-list">
        {analysis.obligations.map((ob) => {
          const key = `ob:${ob.id}`;
          const check = checks.get(ob.id);
          const fulfilment = fulfilments.get(ob.id);
          return (
            <li key={ob.id}>
              <button
                type="button"
                className={`req-row${highlight?.key === key ? " active" : ""}`}
                onClick={() =>
                  onHighlight(
                    highlight?.key === key ? null : { key, elementIds: new Set(elementsFulfilling(model, ob.id)) },
                  )
                }
              >
                <span className="req-id">{ob.id}</span>
                <span className="req-text">{ob.statement}</span>
                <span className="req-status">
                  <StatusBadge status={check?.status} />{" "}
                  <span className="muted">{ob.requirement_ids.map(normaliseId).join(", ")}</span>
                </span>
              </button>
              {highlight?.key === key && (
                <div className="small indent detail">
                  {fulfilment ? <p>Design: {fulfilment.explanation}</p> : <p className="error-text">No fulfilment given.</p>}
                  {check && <p className="muted">Critic: {check.reason}</p>}
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </>
  );
}

function ReviewList({ result, highlight, onHighlight, onSelectElement }: {
  result: GenerateResult;
  highlight: Highlight | null;
  onHighlight: Props["onHighlight"];
  onSelectElement: Props["onSelectElement"];
}) {
  const review = result.review!;
  const rounds = result.review_history ?? [];
  const names = new Map((result.model?.elements ?? []).map((e) => [e.id, e.name]));
  return (
    <>
      <p className="muted small">
        {rounds.length > 1
          ? `The critic reviewed the design, the architect revised it, and the critic reviewed it again. These are the findings on the final design.`
          : "The critic's findings on the final design."}
      </p>
      {rounds.length > 0 && (
        <p className="small">
          {rounds.map((r, i) => (
            <span key={r.round}>
              {i > 0 && " → "}
              round {r.round}: {r.met} met, {r.partial} partial, {r.missing} missing
            </span>
          ))}
        </p>
      )}
      {review.findings.length === 0 && <p className="small">No findings.</p>}
      <ul className="req-list">
        {review.findings.map((f, i) => {
          const key = `finding:${i}`;
          return (
            <li key={key}>
              <button
                type="button"
                className={`req-row${highlight?.key === key ? " active" : ""}`}
                onClick={() =>
                  onHighlight(highlight?.key === key ? null : { key, elementIds: new Set(f.element_ids) })
                }
              >
                <span className={`badge badge-${f.severity}`}>{f.severity}</span>
                <span className="req-text">{f.problem}</span>
                <span className="req-status muted">Fix: {f.fix}</span>
              </button>
              {highlight?.key === key && f.element_ids.length > 0 && (
                <p className="small indent detail">
                  {f.element_ids.map((id, j) => (
                    <span key={id}>
                      {j > 0 && ", "}
                      <button type="button" className="link-button" onClick={() => onSelectElement(id)}>
                        {names.get(id) ?? id}
                      </button>
                    </span>
                  ))}
                </p>
              )}
            </li>
          );
        })}
      </ul>
    </>
  );
}

function QuestionList({ result }: { result: GenerateResult }) {
  const analysis = result.analysis!;
  return (
    <>
      <p className="muted small">
        What the analyst found unclear in the requirements: questions to ask the client. The design uses the stated
        assumption until they are answered.
      </p>
      {analysis.ambiguities.length === 0 && <p className="small">None found.</p>}
      <ul className="plain-list">
        {analysis.ambiguities.map((a, i) => (
          <li key={i} className="question">
            <span className="req-id">{normaliseId(a.requirement_id)}</span> {a.issue}
            <p className="small muted">Assumed: {a.assumption}</p>
          </li>
        ))}
      </ul>
      <h3>Data classes</h3>
      <ul className="plain-list">
        {analysis.data_classes.map((d) => (
          <li key={d.name} className="question small">
            <strong>{d.name}</strong>
            {d.personal_data && <span className="badge">personal data</span>}
            <p className="muted">{d.characteristics}</p>
          </li>
        ))}
      </ul>
    </>
  );
}

export function Inspector(props: Props) {
  const { result, selected } = props;
  const [tab, setTab] = useState<Tab>("requirements");

  if (!result) {
    return (
      <aside className="panel inspector">
        <h2>Inspector</h2>
        <p className="muted">Generate an architecture, then click any element to see the requirements behind it.</p>
      </aside>
    );
  }
  if (!result.model) {
    return (
      <aside className="panel inspector">
        <h2>Inspector</h2>
        <p className="muted">
          The baseline returns diagram text only. There is no model behind it, so there is nothing to trace: no
          element can say which requirement it serves.
        </p>
      </aside>
    );
  }

  const model = result.model;
  const element = selected ? model.elements.find((e) => e.id === selected) : undefined;

  if (!element) {
    const tabs: [Tab, string, boolean][] = [
      ["requirements", "Requirements", true],
      ["obligations", "Obligations", !!result.analysis],
      ["review", "Review", !!result.review],
      ["questions", "Questions", !!result.analysis],
    ];
    const active = tabs.find(([t, , available]) => t === tab && available) ? tab : "requirements";
    return (
      <aside className="panel inspector">
        <div className="tabs" role="tablist">
          {tabs
            .filter(([, , available]) => available)
            .map(([t, label]) => (
              <button
                key={t}
                type="button"
                role="tab"
                aria-selected={active === t}
                className={active === t ? "active" : ""}
                onClick={() => {
                  setTab(t);
                  props.onHighlight(null);
                }}
              >
                {label}
                {t === "questions" && result.analysis?.ambiguities.length ? ` (${result.analysis.ambiguities.length})` : ""}
              </button>
            ))}
        </div>
        {active === "requirements" && (
          <RequirementList model={model} highlight={props.highlight} onHighlight={props.onHighlight} />
        )}
        {active === "obligations" && (
          <ObligationList result={result} highlight={props.highlight} onHighlight={props.onHighlight} />
        )}
        {active === "review" && (
          <ReviewList
            result={result}
            highlight={props.highlight}
            onHighlight={props.onHighlight}
            onSelectElement={props.onSelectElement}
          />
        )}
        {active === "questions" && <QuestionList result={result} />}
      </aside>
    );
  }

  const requirements = requirementIndex(model);
  const names = new Map(model.elements.map((e) => [e.id, e.name]));
  const outgoing = model.relations.filter((r) => r.source === element.id);
  const incoming = model.relations.filter((r) => r.target === element.id);
  const issues = result.validation_errors.filter((e) => e.element_id === element.id);
  const findings = (result.review?.findings ?? []).filter((f) => f.element_ids.includes(element.id));
  const fulfils = (model.fulfilments ?? []).filter((f) => elementsFulfilling(model, f.obligation_id).includes(element.id));
  const obligationText = new Map((result.analysis?.obligations ?? []).map((o) => [o.id, o.statement]));
  const op = (o: string | undefined) => (o && o !== "calls" ? ` (${o.replace("_", "/")})` : "");

  return (
    <aside className="panel inspector">
      <button type="button" className="link-button" onClick={() => props.onSelectElement(null)}>
        ← Back
      </button>
      <h2>{element.name}</h2>
      <p className="muted small">
        {element.kind}
        {element.technology ? ` · ${element.technology}` : ""}
      </p>
      <p>{element.responsibility}</p>

      <dl className="facts">
        <dt>Confidence</dt>
        <dd>
          <span className="meter" aria-hidden="true">
            <span style={{ width: `${Math.round(element.confidence * 100)}%` }} />
          </span>{" "}
          {element.confidence.toFixed(2)}
        </dd>
        <dt>ID</dt>
        <dd>
          <code>{element.id}</code>
        </dd>
      </dl>

      <h3>Satisfies</h3>
      {element.satisfies.length === 0 && <p className="error-text">No requirement cited. This element is flagged.</p>}
      <ul className="satisfies">
        {element.satisfies.map((rid) => {
          const req = requirements.get(normaliseId(rid));
          return (
            <li key={rid}>
              <span className="req-id">{normaliseId(rid)}</span>{" "}
              {req ? req.text : <span className="error-text">Unknown requirement ID</span>}
            </li>
          );
        })}
      </ul>

      {fulfils.length > 0 && (
        <>
          <h3>Fulfils obligations</h3>
          <ul className="satisfies">
            {fulfils.map((f) => (
              <li key={f.obligation_id}>
                <span className="req-id">{f.obligation_id}</span> {obligationText.get(f.obligation_id) ?? f.explanation}
              </li>
            ))}
          </ul>
        </>
      )}

      {(issues.length > 0 || findings.length > 0) && (
        <>
          <h3>Problems</h3>
          <ul className="issues">
            {issues.map((issue, i) => (
              <li key={`v${i}`} className={`small ${issue.severity === "warning" ? "muted" : "error-text"}`}>
                {issue.message}
              </li>
            ))}
            {findings.map((f, i) => (
              <li key={`f${i}`} className="small">
                <span className={`badge badge-${f.severity}`}>{f.severity}</span> {f.problem}{" "}
                <span className="muted">Fix: {f.fix}</span>
              </li>
            ))}
          </ul>
        </>
      )}

      <h3>Relations</h3>
      {outgoing.length + incoming.length === 0 && <p className="muted small">None.</p>}
      <ul className="relations">
        {outgoing.map((r) => (
          <li key={r.id}>
            →{" "}
            <button type="button" className="link-button" onClick={() => props.onSelectElement(r.target)}>
              {names.get(r.target) ?? r.target}
            </button>
            {op(r.operation)}: {r.description}
            {r.protocol ? ` [${r.protocol}]` : ""}{" "}
            <span className="muted small">{r.satisfies.map(normaliseId).join(", ") || "no requirement"}</span>
          </li>
        ))}
        {incoming.map((r) => (
          <li key={r.id}>
            ←{" "}
            <button type="button" className="link-button" onClick={() => props.onSelectElement(r.source)}>
              {names.get(r.source) ?? r.source}
            </button>
            {op(r.operation)}: {r.description}
            {r.protocol ? ` [${r.protocol}]` : ""}{" "}
            <span className="muted small">{r.satisfies.map(normaliseId).join(", ") || "no requirement"}</span>
          </li>
        ))}
      </ul>
    </aside>
  );
}

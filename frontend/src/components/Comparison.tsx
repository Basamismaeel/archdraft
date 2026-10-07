import { useState } from "react";
import { DEMO, api } from "../api";
import type { GenerateResult, Judgement } from "../api";

interface Props {
  baseline: GenerateResult;
  pipeline: GenerateResult;
  renders: { baseline: boolean | null; pipeline: boolean | null };
  onJudged: (judgements: Record<string, Judgement>) => void;
}

function yesNo(value: boolean | null): string {
  return value === null ? "…" : value ? "yes" : "no, syntax error";
}

function grade(j: Judgement | null | undefined): string {
  return j ? `${j.score}% (${j.met} met, ${j.partial} partial, ${j.missing} missing)` : "–";
}

export function Comparison({ baseline, pipeline, renders, onJudged }: Props) {
  const [judging, setJudging] = useState(false);
  const [judgeError, setJudgeError] = useState<string | null>(null);
  const sameInput = baseline.requirements_text === pipeline.requirements_text;
  const bj = baseline.judgement;
  const pj = pipeline.judgement;

  async function runJudge() {
    setJudging(true);
    setJudgeError(null);
    try {
      onJudged(await api.judge([pipeline.id, baseline.id]));
    } catch (e) {
      setJudgeError((e as Error).message);
    } finally {
      setJudging(false);
    }
  }

  const rows: [string, string, string][] = [
    ...(bj && pj
      ? ([
          ["Design obligations met (independent judge)", grade(bj), grade(pj)],
          ["Boxes no requirement needs (judge)", String(bj.unjustified_elements.length), String(pj.unjustified_elements.length)],
          ["Illogical connections (judge)", String(bj.illogical_connections.length), String(pj.illogical_connections.length)],
        ] as [string, string, string][])
      : []),
    ["Diagram renders", yesNo(renders.baseline), yesNo(renders.pipeline)],
    ["Elements", String(baseline.stats.elements), String(pipeline.stats.elements)],
    ["Relations", String(baseline.stats.relations), String(pipeline.stats.relations)],
    [
      "Elements that cite a requirement",
      `${baseline.stats.traced_elements} of ${baseline.stats.elements}`,
      `${pipeline.stats.traced_elements} of ${pipeline.stats.elements}`,
    ],
    [
      "Requirement IDs cited",
      `${baseline.coverage.percent}% (${baseline.coverage.covered}/${baseline.coverage.total})`,
      `${pipeline.coverage.percent}% (${pipeline.coverage.covered}/${pipeline.coverage.total})`,
    ],
    ["Datastore nodes", String(baseline.stats.datastore_nodes), String(pipeline.stats.datastore_nodes)],
    [
      "Distinct datastore technologies",
      baseline.stats.datastore_technologies.join(", ") || "none named",
      pipeline.stats.datastore_technologies.join(", ") || "none named",
    ],
    [
      "Validation errors left",
      "not checked",
      String(pipeline.validation_errors.filter((e) => (e.severity ?? "error") === "error").length),
    ],
    ["LLM calls", String(baseline.llm_calls), String(pipeline.llm_calls)],
    [
      "Time",
      `${(baseline.timings.total_ms / 1000).toFixed(1)} s`,
      `${(pipeline.timings.total_ms / 1000).toFixed(1)} s`,
    ],
  ];

  return (
    <section className="panel comparison" aria-label="Comparison">
      <div className="comparison-head">
        <h2>Baseline vs ArchDraft</h2>
        {!DEMO && sameInput && pipeline.id && baseline.id && (
          <button type="button" onClick={() => void runJudge()} disabled={judging}>
            {judging ? "Judging both… (about a minute)" : bj && pj ? "Judge again" : "Grade both with an independent judge"}
          </button>
        )}
      </div>
      {!sameInput && (
        <p className="error-text small">These two results came from different inputs. Generate again to compare.</p>
      )}
      {judgeError && <p className="error-text small">{judgeError}</p>}
      <table>
        <thead>
          <tr>
            <th scope="col"></th>
            <th scope="col">Baseline (one naive prompt)</th>
            <th scope="col">ArchDraft pipeline</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([label, b, p]) => (
            <tr key={label}>
              <th scope="row">{label}</th>
              <td>{b}</td>
              <td>{p}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {bj && pj && (
        <details>
          <summary className="small">What the judge flagged</summary>
          <div className="judge-detail small">
            {(
              [
                ["Baseline", bj],
                ["ArchDraft", pj],
              ] as [string, Judgement][]
            ).map(([name, j]) => (
              <div key={name}>
                <strong>{name}</strong>
                <ul className="plain-list">
                  {j.checks
                    .filter((c) => c.status !== "met")
                    .map((c) => (
                      <li key={c.obligation_id}>
                        <span className={`badge badge-${c.status}`}>{c.status}</span> {c.obligation_id}: {c.reason}
                      </li>
                    ))}
                  {j.illogical_connections.map((c) => (
                    <li key={c}>Illogical: {c}</li>
                  ))}
                  {j.unjustified_elements.map((c) => (
                    <li key={c}>Unneeded: {c}</li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </details>
      )}
      <p className="muted small">
        The judge is a separate Gemini prompt that grades both diagrams, as Mermaid text, against the same design
        obligations ({pj?.obligations_from ?? "from the ArchDraft analysis"}). It is an LLM grading LLM output, so treat
        single runs as indicative; scripts/evaluate.py averages several runs. Baseline counts are read from its Mermaid
        text by keyword and ID matching.
      </p>
    </section>
  );
}

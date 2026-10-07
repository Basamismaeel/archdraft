import { useCallback, useEffect, useMemo, useState } from "react";
import { DEMO, api } from "./api";
import type { GenerateResult, Health, Judgement, ProjectSummary, Sample, StepEvent } from "./api";
import { DiagramPanel } from "./components/DiagramPanel";
import { Inspector, elementsSatisfying } from "./components/Inspector";
import type { Highlight } from "./components/Inspector";
import { ReportStrip } from "./components/ReportStrip";
import { Comparison } from "./components/Comparison";
import { Progress } from "./components/Progress";

type View = "pipeline" | "baseline" | "compare";
type Mode = "pipeline" | "baseline"; // the two result slots shown in the UI

interface Slot {
  result: GenerateResult | null;
  running: boolean;
  error: string | null;
  renders: boolean | null;
  steps: StepEvent[];
}

const EMPTY: Slot = { result: null, running: false, error: null, renders: null, steps: [] };

function slotFor(mode: GenerateResult["mode"]): Mode {
  return mode === "baseline" ? "baseline" : "pipeline";
}

function modesFor(view: View): Mode[] {
  return view === "compare" ? ["baseline", "pipeline"] : [view];
}

function countRequirements(text: string): { fr: number; nfr: number } {
  const ids = new Set(
    text
      .split("\n")
      .map((line) => line.match(/^\s*[-*]?\s*(N?FR)-0*(\d+)\b/i))
      .filter((m): m is RegExpMatchArray => m !== null)
      .map((m) => `${m[1].toUpperCase()}-${Number(m[2])}`),
  );
  const all = [...ids];
  return { fr: all.filter((id) => id.startsWith("FR")).length, nfr: all.filter((id) => id.startsWith("NFR")).length };
}

export default function App() {
  const [text, setText] = useState("");
  const [samples, setSamples] = useState<Sample[]>([]);
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [health, setHealth] = useState<Health | null>(null);
  const [backendError, setBackendError] = useState<string | null>(null);
  const [view, setView] = useState<View>("pipeline");
  const [slots, setSlots] = useState<Record<Mode, Slot>>({ pipeline: EMPTY, baseline: EMPTY });
  const [selected, setSelected] = useState<string | null>(null);
  const [highlight, setHighlight] = useState<Highlight | null>(null);

  const refreshProjects = useCallback(() => {
    api.projects().then(setProjects).catch(() => undefined);
  }, []);

  useEffect(() => {
    api
      .health()
      .then(setHealth)
      .catch((e: Error) => setBackendError(e.message));
    api
      .samples()
      .then((list) => {
        setSamples(list);
        setText((current) => current || list[0]?.text || "");
      })
      .catch(() => undefined);
    refreshProjects();
  }, [refreshProjects]);

  const patchSlot = (mode: Mode, patch: Partial<Slot>) =>
    setSlots((s) => ({ ...s, [mode]: { ...s[mode], ...patch } }));

  const run = useCallback(
    async (mode: Mode, input: string) => {
      setSlots((s) => ({ ...s, [mode]: { ...EMPTY, running: true } }));
      const onStep = (step: StepEvent) =>
        setSlots((s) => ({ ...s, [mode]: { ...s[mode], steps: [...s[mode].steps, step] } }));
      try {
        const result = await api.generateStream(input, mode, onStep);
        setSlots((s) => ({ ...s, [mode]: { ...EMPTY, result } }));
        refreshProjects();
      } catch (e) {
        setSlots((s) => ({ ...s, [mode]: { ...EMPTY, error: (e as Error).message } }));
      }
    },
    [refreshProjects],
  );

  function generate() {
    const input = text.trim();
    if (!input) return;
    setSelected(null);
    setHighlight(null);
    // Clear the other mode too, so an old result is never compared with a new input.
    setSlots({ pipeline: EMPTY, baseline: EMPTY });
    modesFor(view).forEach((mode) => void run(mode, input));
  }

  // The toggle re-runs the *same input* in the mode that is missing.
  function changeView(next: View) {
    setView(next);
    const reference = slots.pipeline.result?.requirements_text ?? slots.baseline.result?.requirements_text;
    if (!reference) return;
    for (const mode of modesFor(next)) {
      const slot = slots[mode];
      if (!slot.running && slot.result?.requirements_text !== reference) void run(mode, reference);
    }
  }

  async function openProject(id: string) {
    if (!id) return;
    try {
      const result = await api.project(id);
      const slot = slotFor(result.mode);
      setSlots((s) => ({ ...s, [slot]: { ...EMPTY, result } }));
      setText(result.requirements_text);
      setSelected(null);
      setHighlight(null);
      if (!modesFor(view).includes(slot)) setView(slot);
    } catch (e) {
      setBackendError((e as Error).message);
    }
  }

  const pipeline = slots.pipeline;
  const baseline = slots.baseline;
  const running = pipeline.running || baseline.running;
  const counts = useMemo(() => countRequirements(text), [text]);

  const selectElement = useCallback((id: string | null) => {
    setSelected(id);
    if (id) setHighlight(null);
  }, []);
  const changeHighlight = useCallback((next: Highlight | null) => {
    setHighlight(next);
    setSelected(null);
  }, []);
  const highlightRequirement = useCallback(
    (id: string) => {
      const model = pipeline.result?.model;
      if (model) changeHighlight({ key: `req:${id}`, elementIds: new Set(elementsSatisfying(model, id)) });
    },
    [pipeline.result, changeHighlight],
  );
  function storeJudgements(judgements: Record<string, Judgement>) {
    setSlots((s) => {
      const next = { ...s };
      for (const mode of ["pipeline", "baseline"] as Mode[]) {
        const result = s[mode].result;
        if (result && judgements[result.id]) {
          next[mode] = { ...s[mode], result: { ...result, judgement: judgements[result.id] } };
        }
      }
      return next;
    });
  }
  const pipelineRendered = useCallback((ok: boolean) => patchSlot("pipeline", { renders: ok }), []);
  const baselineRendered = useCallback((ok: boolean) => patchSlot("baseline", { renders: ok }), []);

  const showPipeline = view !== "baseline";
  const showBaseline = view !== "pipeline";
  const reportResult = showPipeline ? pipeline.result : baseline.result;

  return (
    <div className="app">
      <header className="topbar">
        <div>
          <h1>ArchDraft</h1>
          <p className="muted small">Requirements in, architecture out, with every box traced to the requirement behind it.</p>
        </div>
        <p className="muted small">
          {health ? (
            <>
              Google ADK {health.adk_version} · {DEMO ? "public demo" : (health.model ?? "GEMINI_MODEL not set")}
            </>
          ) : (
            "connecting…"
          )}
        </p>
      </header>

      {backendError && <div className="banner error">{backendError}</div>}
      {DEMO && (
        <div className="banner">
          <strong>Public demo.</strong> These are real runs that Gemini produced for the two built-in samples; pick a
          sample and click Generate to replay one, or try <em>Side by side</em> for the comparison with a naive
          single prompt. Generating from your own requirements needs the backend and a Gemini API key:{" "}
          <a href="https://github.com/Basamismaeel/archdraft#run-it-in-five-minutes">run it locally</a>. The runs
          shown were made before the analyst and critic agents were added, so the Obligations, Review and Questions
          tabs are empty here.
        </div>
      )}
      {!DEMO && health && !health.credentials && (
        <div className="banner">
          No Gemini API key found. Add <code>GOOGLE_API_KEY</code> to <code>.env</code> in the repository root and restart
          the backend. Previous runs can still be opened.
        </div>
      )}

      <main className={`layout view-${view}`}>
        <section className="panel input-panel" aria-label="Requirements input">
          <h2>Requirements</h2>
          <label className="field">
            <span className="small muted">Sample</span>
            <select
              onChange={(e) => {
                const sample = samples.find((s) => s.id === e.target.value);
                if (sample) setText(sample.text);
              }}
              defaultValue=""
            >
              <option value="" disabled>
                Load a sample…
              </option>
              {samples.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.title}
                </option>
              ))}
            </select>
          </label>
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) generate();
            }}
            spellCheck={false}
            aria-label="Requirements text"
            placeholder={"FR-01: Users can …\nNFR-01: Search responds within …"}
          />
          <p className="small muted">
            {counts.fr + counts.nfr > 0
              ? `${counts.fr} functional, ${counts.nfr} non-functional requirements detected`
              : "Number requirements FR-01, NFR-01 … to keep your IDs; otherwise IDs are assigned."}
          </p>
          <button type="button" className="primary" onClick={generate} disabled={running || !text.trim()}>
            {running ? "Generating…" : view === "compare" ? "Generate both" : "Generate"}
          </button>
          <p className="small muted">Ctrl/⌘ + Enter</p>

          <label className="field">
            <span className="small muted">Previous runs</span>
            <select value="" onChange={(e) => void openProject(e.target.value)}>
              <option value="">{projects.length ? "Open a previous run…" : "No saved runs yet"}</option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {new Date(p.created_at).toLocaleString([], { dateStyle: "short", timeStyle: "short" })} ·{" "}
                  {p.mode === "baseline" ? "baseline" : p.system_name} · {p.coverage_percent}%
                </option>
              ))}
            </select>
          </label>
        </section>

        <div className="diagram-area">
          <div className="view-toggle" role="radiogroup" aria-label="Which result to show">
            {(
              [
                ["pipeline", "ArchDraft"],
                ["baseline", "Baseline"],
                ["compare", "Side by side"],
              ] as [View, string][]
            ).map(([value, label]) => (
              <button
                key={value}
                type="button"
                role="radio"
                aria-checked={view === value}
                className={view === value ? "active" : ""}
                onClick={() => changeView(value)}
              >
                {label}
              </button>
            ))}
          </div>
          <div className="diagrams">
            {showBaseline && (
              <DiagramPanel
                title="Baseline"
                subtitle="One naive prompt asking for a Mermaid diagram"
                source={baseline.result?.mermaid ?? null}
                nodeIds={{}}
                selected={null}
                highlighted={null}
                running={baseline.running}
                runningView={<Progress steps={baseline.steps} title="Asking the naive baseline" />}
                error={baseline.error}
                emptyHint="Generate to see what a single naive prompt produces for the same requirements."
                onRenderStatus={baselineRendered}
              />
            )}
            {showPipeline && (
              <DiagramPanel
                title={pipeline.result?.model?.system_name ?? "ArchDraft"}
                subtitle="ADK pipeline · validated · every element traced"
                source={pipeline.result?.mermaid ?? null}
                nodeIds={pipeline.result?.node_ids ?? {}}
                selected={selected}
                highlighted={highlight?.elementIds ?? null}
                running={pipeline.running}
                runningView={<Progress steps={pipeline.steps} title="ArchDraft agents at work" />}
                error={pipeline.error}
                emptyHint="Pick a sample or paste requirements, then Generate."
                onSelect={selectElement}
                onRenderStatus={pipelineRendered}
              />
            )}
          </div>
        </div>

        <Inspector
          result={showPipeline ? pipeline.result : baseline.result}
          selected={selected}
          highlight={highlight}
          onSelectElement={selectElement}
          onHighlight={changeHighlight}
        />
      </main>

      {view === "compare" && pipeline.result && baseline.result && (
        <Comparison
          baseline={baseline.result}
          pipeline={pipeline.result}
          renders={{ baseline: baseline.renders, pipeline: pipeline.renders }}
          onJudged={storeJudgements}
        />
      )}
      {reportResult && (
        <ReportStrip
          result={reportResult}
          onSelectElement={(id) => selectElement(id)}
          onHighlightRequirement={(id) => highlightRequirement(id)}
        />
      )}
    </div>
  );
}

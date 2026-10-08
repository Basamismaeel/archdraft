# ArchDraft

ArchDraft turns software requirements into a C4-style architecture diagram, and every box and arrow in the diagram carries the IDs of the requirements that justify it. Three cooperating agents do the work:
- An **analyst** turns the requirements into checkable *design obligations*, for example "every store holding personal data has an erasure path".
- An **architect** designs against those obligations.
- A **critic** checks each obligation against the actual boxes and arrows and sends the design back once for revision.

Deterministic rules catch structural mistakes in between. Anything that is still wrong is shown in red, not hidden.

It is built on **Google's Agent Development Kit (ADK) 2.11** with Gemini. The UI runs the same requirements through a naive one-prompt baseline, side by side. An independent judge grades both against the same obligations, so each improvement can be measured.

**Live demo:** <https://basamismaeel.github.io/archdraft/> replays real Gemini runs saved from ArchDraft, including the side-by-side comparison with a naive single prompt. It has no backend and no API key, so it cannot generate from new requirements: run it locally for that (below).

---

## Run it in five minutes

You need **Python 3.11+**, **Node.js 20+** and a **Gemini API key** (free from <https://aistudio.google.com/apikey>). No Google Cloud project is needed.

### One-time setup

```bash
cp .env.example .env          # then open .env and paste your key after GOOGLE_API_KEY=
```

```bash
cd backend
python3 -m venv .venv         # python3 must be 3.11 or newer: check with python3 --version
.venv/bin/pip install -e ".[dev]"
```

```bash
cd frontend
npm install
```

On Windows use `.venv\Scripts\pip` and `.venv\Scripts\uvicorn` instead of `.venv/bin/...`.

### Run (two terminals)

```bash
cd backend && .venv/bin/uvicorn archdraft.api:app --reload --port 8000
```

```bash
cd frontend && npm run dev
```

Open <http://localhost:5173>.

### Use it

1. Pick **Car Sales Marketplace** from the sample list (or paste your own requirements; number them `FR-01`, `NFR-01` … to keep your IDs).
2. Click **Generate**. The panel shows each agent as it finishes. A large requirement set takes 1–4 minutes.
3. Click any box in the diagram. The inspector shows its technology and responsibility, the full text of every requirement it satisfies, the obligations it fulfils, and any problems found with it.
4. With nothing selected, the inspector has four tabs:
   - **Requirements**: click one to highlight the elements that satisfy it.
   - **Obligations**: each one with the critic's verdict (met, partial or missing); click one to highlight the parts that fulfil it.
   - **Review**: the critic's findings, before and after the revision.
   - **Questions**: ambiguities to raise with the client, with the assumption the design makes.
5. The report strip under the diagram shows citation coverage, obligations met, validation errors and warnings, and which pipeline nodes ran and how long each took.
6. Switch the toggle to **Side by side**. The same input is re-run through the naive baseline. Click **Grade both with an independent judge** to score both diagrams against the same obligations.

Every run is saved to `data/` and can be reopened from **Previous runs**. That is also the fallback if the API is slow during a demo.

---

## What this proves

- **Traceability is enforced, not hoped for.** The model must return a typed JSON model (ADK structured output), and every element and relation in it carries `satisfies: [requirement IDs]`.
- **Citations are not enough, so the design is checked.** v1 showed that a model can cite a requirement on a box without designing anything for it. In one run, GDPR erasure was "covered" by citation while no component could delete anything. v2 therefore checks the design itself:
  - The analyst writes concrete obligations, and the architect must record how each one is fulfilled.
  - Deterministic rules check that every datastore is written to, every obligation is addressed by real elements and relations, and no requirement is cited everywhere.
  - The critic judges each obligation by the boxes and arrows, not by the claims.
- **Failures are visible.** Rule errors go back to the architect once, and critic findings go back once. Whatever is still wrong is shown in red in the diagram and listed in the report.
- **The diagram can't have broken syntax.** The LLM never writes diagram code. Python renders Mermaid from the validated model (`backend/archdraft/render/mermaid.py`). Asynchronous flows (publish and consume) are drawn dashed.
- **Improvements are measured, not asserted.** `backend/scripts/evaluate.py` runs the baseline, v1 (one agent) and v2 (three agents) several times on the same requirements. An independent judge prompt grades all three against the same obligations, and the script writes averaged results to `docs/evaluation.md`.

---

## How it works

```
requirements
  -> prepare_input                        (code)
  -> requirements_analyst                 (Gemini)  data classes, design obligations, open questions
  -> requirements_to_architecture         (Gemini)  components, stores, flows, one fulfilment per obligation
  -> validate_architecture                (code)    11 rules
       REPAIR (once per round) ----------> back to the architect with the errors
       REVIEW -> architecture_critic      (Gemini)  met / partial / missing per obligation, findings
                   REVISE (once) --------> back to the architect with the findings
                   ACCEPT -> render_diagram (code)  Mermaid, requirement IDs on every node
```

It's an ADK graph `Workflow` with three LLM agents and deterministic nodes for everything that can be checked by code.

| Agent Garden role (from the project brief) | In ArchDraft | Where |
|---|---|---|
| Requirements Analyst | LLM agent | `requirements_analyst`, `prompts/requirements_analyst.md` |
| Constraint & Compliance Validator | Deterministic rules **and** an LLM critic | `validate_architecture` → `validation/rules.py`; `architecture_critic` |
| Component Decomposition & Synthesizer | LLM agent | `requirements_to_architecture` |
| Diagram Code Generation | Deterministic node | `render_diagram` → `render/mermaid.py` |

The 11 rules:
1. Relation endpoints exist.
2. No isolated elements.
3. Every element and relation cites a requirement.
4. Cited IDs exist.
5. Every requirement is cited or listed as unresolved.
6. Element IDs are unique.
7. No requirement from the input is dropped.
8. Every datastore is written to.
9. Every obligation is addressed by real parts.
10. Fulfilments name only parts that exist.
11. (warning) No blanket citations.

The baseline is a separate ADK workflow with one naive prompt ("create a diagram, return Mermaid"). `single_agent` mode keeps the v1 graph, the architect alone with the rules, for before/after evaluation.

---

## Why ADK

- **Version:** `google-adk==2.11.0`, pinned in `backend/pyproject.toml`, running locally against the Gemini API with an API key.
- **Pipeline root:** `archdraft_pipeline`, an ADK 2.x **graph `Workflow`**, defined in `backend/archdraft/agents/pipeline.py` and exposed as `root_agent` in `backend/archdraft/agents/agent.py`. The original plan named a `SequentialAgent`. ADK 2.0 (GA May 2026) made graph workflows the primary way to compose agents. They let plain Python functions run as nodes next to LLM agents, and they support conditional routing, which the repair loop needs. A `SequentialAgent` can only chain agents, so the validator and renderer would have had to be hidden inside callbacks.
- **How agents attach:** each agent is a node in the `edges` list of `build_pipeline()`. Adding the analyst and the critic in v2 changed no runner, API or frontend code apart from new UI panels. Built so far:
  1. `requirements_analyst` (v2): data classes, obligations, ambiguities.
  2. `architecture_critic` (v2): checks every obligation and every relation against the design; one revision round.

  Planned next:

  3. `datastore_advisor`: proposes the store for each data class before the architect designs. This targets the one-database-for-everything defect directly.
  4. `views_generator`: derives a C4 component view and a deployment view from the validated model.
  5. `adr_writer`: writes one architecture decision record per significant choice, citing its requirements.
- **Moving to Agent Engine is one configuration change:** in `.env`, set `GOOGLE_GENAI_USE_ENTERPRISE=TRUE` plus `GOOGLE_CLOUD_PROJECT` and `GOOGLE_CLOUD_LOCATION` (instead of `GOOGLE_API_KEY`). The model client then goes through Vertex AI, and the agent code stays the same. Deploying is then one command. `--extra_packages` ships the shared `archdraft` package (schema, validator, renderer) along with the agent folder:

  ```bash
  cd backend && .venv/bin/adk deploy agent_engine --project=$PROJECT_ID --region=$LOCATION_ID --extra_packages=archdraft archdraft/agents
  ```

  ArchDraft deliberately stays local: no Cloud project, no Vertex AI, no deployment. The deploy step has not been tried yet and needs a Google Cloud project with billing.

### Debugging the agent on its own

```bash
cd backend && .venv/bin/adk web archdraft/agents
```

This opens ADK's dev UI on port 8000, so stop the API first. Paste requirements into the chat and watch each node's events and state.

---

## Project layout

```
.env.example               copy to .env; holds GOOGLE_API_KEY and GEMINI_MODEL
samples/                   library.txt (10 FR + 4 NFR), car_sales.txt (20 FR + 13 NFR)
data/                      saved runs (gitignored)
backend/
  archdraft/
    schema.py              the canonical ArchitectureModel: the contract between everything
    agents/
      pipeline.py          the ADK graphs: v2 pipeline, v1 single agent, baseline, judge
      agent.py             root_agent for `adk web` / `adk deploy`
      prompts/             one Markdown file per agent; edit these, no code change needed
    validation/rules.py    the 11 deterministic checks
    render/mermaid.py      model → Mermaid, with requirement IDs on nodes and red flags
    metrics.py             coverage and comparison numbers
    service.py             runs a workflow, streams progress, builds the response, runs the judge
    api.py                 FastAPI endpoints
    storage.py             JSON files in data/
  scripts/generate.py      run any mode from the command line (no UI)
  scripts/evaluate.py      baseline vs v1 vs v2, judged and averaged -> docs/evaluation.md
  tests/                   pytest; no test calls a live API
frontend/                  React + TypeScript + Vite, plain CSS, mermaid
```

### Editing the prompt

Each agent's instructions live in `backend/archdraft/agents/prompts/`:
- `requirements_analyst.md`
- `requirements_to_architecture.md`
- `architecture_critic.md`
- `judge.md`
- `baseline.md`

The files are read on every model call, so edits take effect on the next **Generate** without a restart.

### Command line

```bash
cd backend
.venv/bin/python scripts/generate.py ../samples/car_sales.txt
.venv/bin/python scripts/generate.py ../samples/car_sales.txt --mode baseline
.venv/bin/python scripts/generate.py ../samples/library.txt --mode single_agent --json
.venv/bin/python scripts/evaluate.py --runs 3          # takes a while: ~9 runs per sample
```

### Tests and lint

```bash
cd backend && .venv/bin/pytest && .venv/bin/ruff check . && .venv/bin/ruff format --check .
```

```bash
cd frontend && npm run build
```

The test suite covers every validation rule and the Mermaid renderer against hand-written fixtures. It also runs the real ADK graphs end to end with a stub model that answers as whichever agent is asking. That exercises the analyst → architect → validator → critic flow, the repair and revision rounds, the streaming endpoint, the baseline and the judge, all without network access.

### API

| Method | Path | Returns |
|---|---|---|
| `POST` | `/api/generate` | body `{requirements_text, mode: "pipeline" \| "single_agent" \| "baseline"}` → `{model, mermaid, validation_errors, coverage, analysis, review, timings, …}` |
| `POST` | `/api/generate/stream` | same body; streams one JSON line per finished node, then the result |
| `POST` | `/api/judge` | body `{project_ids: [...]}` → independent judge grades for saved runs of the same requirements |
| `GET` | `/api/samples` | the built-in requirement sets |
| `GET` | `/api/projects` | saved runs, newest first |
| `GET` | `/api/projects/{id}` | one saved run |
| `GET` | `/api/health` | ADK version, configured model, whether a key is present |

---

## Public demo build

`.github/workflows/pages.yml` builds the frontend with `VITE_DEMO=true` and publishes it to GitHub Pages on every push to `main`. In that build the API client reads `frontend/public/demo/runs.json` (real saved runs) and `samples.json` instead of calling a backend, and **Generate** replays the saved run that matches the chosen sample. To refresh the demo after new runs, copy the wanted files from `data/` into a list in `runs.json` and push. Never put an API key in the frontend: GitHub Pages is public.

## Known limits

- The critic and the judge are LLMs grading LLM output. The judge uses a separate prompt and sees only the diagram, but single runs are still noisy, which is why `evaluate.py` averages repetitions and reports the spread.
- **Free-tier quota:** the free Gemini tier allows 20 requests per model per day (checked 2026-10-06). One v2 run uses 3–7 requests, so expect 3–5 full runs per model per day. A full `evaluate.py` run needs a paid tier, or several days.
- The full pipeline makes 3–7 model calls and takes 1–4 minutes. On the free Gemini tier, busy periods return "503 high demand"; ArchDraft retries and falls back to the models in `GEMINI_FALLBACK_MODEL`, but it cannot generate while every model is overloaded. Saved runs can always be reopened.
- Baseline counts (elements, IDs, datastores) are read from free-text Mermaid by keyword and ID matching.
- One level of detail: the deployable components, stores and external systems (what C4 calls the container level, named "component" here). There are no finer-grained or deployment views yet.
- No authentication, database, Docker, CI or diagram editing. These are out of scope by design.

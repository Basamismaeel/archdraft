"""Before/after evidence: baseline vs single agent (v1) vs full pipeline (v2).

For every sample and every repetition, the three modes run on the same requirements with the
same model. The independent judge then grades all three diagrams against the *same* design
obligations (taken from that repetition's v2 analysis). Results are averaged and written to
docs/evaluation.md and docs/evaluation.csv.

    python scripts/evaluate.py                       # both samples, 3 repetitions
    python scripts/evaluate.py --samples car_sales --runs 5
"""

import argparse
import asyncio
import csv
import statistics
import sys
from datetime import UTC, datetime

from archdraft import config, service
from archdraft.service import GenerateResult

MODES: list[service.Mode] = ["baseline", "single_agent", "pipeline"]
MODE_NAMES = {
    "baseline": "Baseline (1 naive prompt)",
    "single_agent": "v1: single architect agent",
    "pipeline": "v2: analyst + architect + critic",
}
DOCS = config.REPO_ROOT / "docs"


def row(sample: str, rep: int, result: GenerateResult) -> dict[str, object]:
    j = result.judgement
    s = result.stats
    errors = [e for e in result.validation_errors if e.severity == "error"]
    return {
        "sample": sample,
        "run": rep,
        "mode": result.mode,
        "judge_score": j.score if j else None,
        "obligations_met": j.met if j else None,
        "obligations_partial": j.partial if j else None,
        "obligations_missing": j.missing if j else None,
        "obligations_total": j.total if j else None,
        "unneeded_boxes": len(j.unjustified_elements) if j else None,
        "illogical_connections": len(j.illogical_connections) if j else None,
        "elements": s.elements,
        "relations": s.relations,
        "traced_elements_pct": round(100 * s.traced_elements / s.elements, 1) if s.elements else 0,
        "ids_cited_pct": result.coverage.percent,
        "validation_errors_left": len(errors) if result.mode != "baseline" else None,
        "datastore_technologies": len(s.datastore_technologies),
        "seconds": round(result.timings.total_ms / 1000, 1),
        "llm_calls": result.llm_calls,
        "model": result.llm_model,
        "id": result.id,
    }


async def one_repetition(sample: str, text: str, rep: int) -> list[dict[str, object]]:
    results = await asyncio.gather(*(service.generate(text, mode) for mode in MODES))
    await service.judge_saved([r.id for r in results])  # obligations from the v2 analysis
    rows = []
    for r in results:
        reloaded = GenerateResult.model_validate(service.storage.load(r.id))
        rows.append(row(sample, rep, reloaded))
    return rows


def mean_sd(values: list[float]) -> str:
    if not values:
        return "–"
    if len(values) == 1:
        return f"{values[0]:.1f}"
    return f"{statistics.mean(values):.1f} ± {statistics.stdev(values):.1f}"


METRICS = [
    ("judge_score", "Design obligations met, judge score (%) ↑"),
    ("obligations_missing", "Obligations missing ↓"),
    ("unneeded_boxes", "Boxes no requirement needs ↓"),
    ("illogical_connections", "Illogical connections ↓"),
    ("traced_elements_pct", "Elements that cite a requirement (%) ↑"),
    ("ids_cited_pct", "Requirement IDs cited (%) ↑"),
    ("validation_errors_left", "Validation errors left ↓"),
    ("elements", "Elements"),
    ("relations", "Relations"),
    ("datastore_technologies", "Distinct datastore technologies"),
    ("llm_calls", "LLM calls"),
    ("seconds", "Time (s)"),
]


def report(rows: list[dict[str, object]], runs: int) -> str:
    models = sorted({str(r["model"]) for r in rows})
    lines = [
        "# ArchDraft evaluation",
        "",
        f"Generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC by `backend/scripts/evaluate.py`. "
        f"{runs} repetition(s) per sample; values are mean ± standard deviation.",
        "",
        f"Model(s) that answered: {', '.join(models)}.",
        "",
        "**Method.** In each repetition the three modes receive identical requirements. An "
        "independent judge prompt (`agents/prompts/judge.md`, separate from the pipeline's own "
        "critic) grades each diagram, as Mermaid text, against the same list of design obligations "
        "produced by that repetition's requirements analyst. "
        "Score = (met + 0.5 × partial) / total. "
        "The judge is itself an LLM, so read the numbers as indicative; the spread across "
        "repetitions is shown for that reason.",
        "",
    ]
    for sample in sorted({str(r["sample"]) for r in rows}):
        lines += [
            f"## {sample}",
            "",
            "| Metric | " + " | ".join(MODE_NAMES[m] for m in MODES) + " |",
        ]
        lines.append("|---|" + "---|" * len(MODES))
        for key, label in METRICS:
            cells = []
            for mode in MODES:
                values = [
                    float(r[key])  # type: ignore[arg-type]
                    for r in rows
                    if r["sample"] == sample and r["mode"] == mode and r[key] is not None
                ]
                cells.append(mean_sd(values) if values else "n/a")
            lines.append(f"| {label} | " + " | ".join(cells) + " |")
        lines.append("")
    lines += [
        "Saved runs (open them in the UI under *Previous runs*): "
        + ", ".join(f"`{r['id']}`" for r in rows),
        "",
    ]
    return "\n".join(lines)


async def main_async(samples: list[str], runs: int) -> int:
    rows: list[dict[str, object]] = []
    for sample in samples:
        text = (config.SAMPLES_DIR / f"{sample}.txt").read_text(encoding="utf-8")
        for rep in range(1, runs + 1):
            print(f"{sample} run {rep}/{runs} …", flush=True)
            try:
                rows += await one_repetition(sample, text, rep)
            except service.GenerationError as exc:
                print(f"  skipped: {exc}", file=sys.stderr)
                continue
            last = {r["mode"]: r["judge_score"] for r in rows[-3:]}
            print(f"  judge scores: {last}", flush=True)
    if not rows:
        print("No successful runs.", file=sys.stderr)
        return 1
    DOCS.mkdir(exist_ok=True)
    with (DOCS / "evaluation.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    (DOCS / "evaluation.md").write_text(report(rows, runs), encoding="utf-8")
    print(f"Wrote {DOCS / 'evaluation.md'}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--samples", nargs="+", default=["library", "car_sales"])
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args()
    return asyncio.run(main_async(args.samples, args.runs))


if __name__ == "__main__":
    sys.exit(main())

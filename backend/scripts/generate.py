"""Stage 1 proof: run the ADK pipeline from the command line, no UI.

python scripts/generate.py ../samples/library.txt
python scripts/generate.py ../samples/car_sales.txt --mode baseline
python scripts/generate.py ../samples/car_sales.txt --json > result.json
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from archdraft.config import ConfigError
from archdraft.service import GenerateResult, GenerationError, generate


def print_summary(result: GenerateResult) -> None:
    print(f"mode            {result.mode}   model {result.llm_model}   saved as {result.id}")
    if result.model:
        print(f"system          {result.model.system_name}")
        print(f"requirements    {len(result.model.requirements)}")
    s = result.stats
    print(f"elements        {s.elements} ({s.traced_elements} traced), relations {s.relations}")
    techs = ", ".join(s.datastore_technologies) or "-"
    print(f"datastores      {s.datastore_nodes} nodes, technologies: {techs}")
    c = result.coverage
    print(f"coverage        {c.covered}/{c.total} = {c.percent}%  ({c.basis})")
    if c.uncovered:
        print(f"uncovered       {', '.join(c.uncovered)}")
    if result.analysis:
        a = result.analysis
        print(
            f"analysis        {len(a.data_classes)} data classes, "
            f"{len(a.obligations)} obligations, {len(a.ambiguities)} ambiguities"
        )
    for attempt in result.validation_history:
        print(
            f"validation      attempt {attempt.attempt}: {attempt.error_count} error(s), "
            f"{attempt.warning_count} warning(s)"
        )
    for r in result.review_history:
        print(
            f"review          round {r.round}: met {r.met}, partial {r.partial}, "
            f"missing {r.missing}; findings {r.blocking} blocking, {r.major} major, {r.minor} minor"
        )
    for err in result.validation_errors:
        print(f"  ! [{err.rule}] {err.message}")
    trail = " -> ".join(f"{n.node} {n.ms}ms" for n in result.timings.nodes)
    print(f"pipeline        {trail}")
    print(f"total           {result.timings.total_ms} ms, {result.llm_calls} LLM call(s)")
    print("\n" + result.mermaid)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("requirements", type=Path, help="Text file with FR/NFR requirements")
    parser.add_argument(
        "--mode", choices=["pipeline", "single_agent", "baseline"], default="pipeline"
    )
    parser.add_argument("--json", action="store_true", help="Print the full API response")
    args = parser.parse_args()

    text = args.requirements.read_text(encoding="utf-8")
    try:
        result = asyncio.run(generate(text, args.mode))
    except (ConfigError, GenerationError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result.model_dump(mode="json"), indent=2, ensure_ascii=False))
    else:
        print_summary(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())

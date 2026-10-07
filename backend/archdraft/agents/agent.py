"""Entry point for `adk web` / `adk run`: exposes the pipeline as `root_agent`.

Run from the backend folder:  adk web archdraft/agents
"""

from archdraft.agents.pipeline import build_pipeline
from archdraft.config import model_name

root_agent = build_pipeline(model_name())

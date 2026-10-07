"""ADK agent package. `adk web` loads `root_agent` from `agent.py` in this folder.

This file stays empty on purpose: importing the package must not require GEMINI_MODEL, so the
API and the tests can import `archdraft.agents.pipeline` without a configured model.
"""

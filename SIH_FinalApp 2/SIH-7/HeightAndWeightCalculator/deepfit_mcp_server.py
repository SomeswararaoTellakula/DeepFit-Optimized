"""
DeepFit MCP server - exposes DeepFit athlete data to any MCP client
(Claude Desktop, Cursor, VS Code, MCP Inspector, ...).

It serves exactly the same read-only tools the in-app AI Coach uses
(deepfit_tools.py). Because an MCP client has no web login, each tool takes the
athlete's registered email. Run it only on a machine you trust: anyone who can
start this server can read every athlete's results.

Install:   pip install "mcp[cli]"
Run:       python deepfit_mcp_server.py            (stdio transport)
Inspect:   mcp dev deepfit_mcp_server.py

Claude Desktop config (claude_desktop_config.json):
{
  "mcpServers": {
    "deepfit": {
      "command": "/ABSOLUTE/PATH/venv312/bin/python",
      "args": ["/ABSOLUTE/PATH/deepfit_mcp_server.py"],
      "env": {"MONGODB_URI": "mongodb://localhost:27017/"}
    }
  }
}
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.chdir(HERE)

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(HERE, ".env"))
except ImportError:
    pass

try:                                     # mcp 1.x
    from mcp.server.fastmcp import FastMCP  # noqa: E402
except ImportError:                      # mcp 2.x renamed FastMCP -> MCPServer
    from mcp.server.mcpserver import MCPServer as FastMCP  # noqa: E402

import deepfit_tools as T  # noqa: E402
from db_config import connect_mongodb  # noqa: E402

mcp = FastMCP("deepfit")
_db = None


def _ctx(email: str) -> T.AthleteContext:
    global _db
    if _db is None:
        # db_config prints status lines; stdout is the MCP channel, so send them to stderr
        import contextlib
        with contextlib.redirect_stdout(sys.stderr):
            _, _db = connect_mongodb()
    ctx = T.AthleteContext(_db, email=email.strip().lower() if email else None)
    if not ctx.known and email:
        ctx = T.AthleteContext(_db, email=email.strip())
    return ctx


@mcp.tool()
def get_athlete_profile(email: str) -> dict:
    """Profile of a DeepFit athlete (name, age, gender, place) by registered email."""
    return T.get_my_profile(_ctx(email))


@mcp.tool()
def get_exercise_history(email: str, exercise: str = "all", limit: int = 10) -> dict:
    """Recent DeepFit sessions, newest first. exercise: all | situps | dumbbell_curls | vertical_jump | height_weight."""
    return T.get_my_exercise_history(_ctx(email), exercise=exercise, limit=limit)


@mcp.tool()
def get_progress_summary(email: str) -> dict:
    """Per-test progress: sessions, best, latest and change since the first session."""
    return T.get_my_progress_summary(_ctx(email))


@mcp.tool()
def compare_with_benchmark(email: str) -> dict:
    """Compare the athlete with the closest reference athlete in DeepFit's benchmark dataset."""
    return T.compare_with_benchmark(_ctx(email))


@mcp.tool()
def get_hidden_potential(email: str) -> dict:
    """Hidden Potential Index (maturity-adjusted fitness + coachability + growth headroom) and late-bloomer flag."""
    return T.get_my_hidden_potential(_ctx(email))


@mcp.tool()
def get_exercise_guide(exercise: str) -> dict:
    """How a DeepFit test works (camera setup, counting rules, form cues). exercise: situps | dumbbell_curls | vertical_jump | height_weight | identity_check."""
    return T.get_exercise_guide(None, exercise)


@mcp.resource("deepfit://guides")
def all_guides() -> str:
    """All DeepFit test guides as JSON."""
    import json
    return json.dumps(T.GUIDES, indent=2)


if __name__ == "__main__":
    mcp.run()

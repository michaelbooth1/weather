"""Closed import boundary for the executable paper process."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

SAFE_WEATHER = {"weather", "weather.backtesting", "weather.paths",
                "weather.market", "weather.market.metar_reports", "weather.market.venue_settlement_rules"}
FORBIDDEN = {"socket", "ssl", "requests", "http", "httpx", "aiohttp", "websocket", "sitecustomize",
             "websockets", "polymarket", "polymarket_client", "py_clob_client", "eth_account",
             "web3", "dotenv", "maker_core", "subprocess"}


def allowed(name: str) -> bool:
    # pathlib imports the pure URL parser on CPython; request/openers stay denied.
    if name.startswith("urllib.") and name != "urllib.parse":
        return False
    if name.split(".")[0] in FORBIDDEN:
        return False
    if name == "weather" or name.startswith("weather."):
        return (name in SAFE_WEATHER or name == "weather.backtesting.low_ask"
                or name.startswith("weather.backtesting.low_ask."))
    if name in {"tzdata", "tzdata.zoneinfo"} or name.startswith("tzdata.zoneinfo."):
        return True  # Windows zoneinfo's data-only, version-pinned resource package.
    # Only CPython's standard library and inert interpreter bootstrap hooks.
    # No allow-by-default third-party client namespace, even if installed.
    return name.split(".")[0] in sys.stdlib_module_names or name.split(".")[0] in {
        "__main__", "_distutils_hack", "_virtualenv"}


class PaperImportBoundary:
    def find_spec(self, fullname, path=None, target=None):
        if not allowed(fullname):
            raise ImportError("LOW-ASK-1 paper import boundary")
        return None


def assert_no_order_path() -> None:
    """Inspect the entire owned import closure; refuse dynamic import/eval hooks.

    The executable also installs an import finder, so a later client import
    is refused instead of silently becoming reachable. It runs in a dedicated
    Python process, never inside an agent's already populated interpreter.
    """
    from weather.paths import repo_path
    paths = list(Path(__file__).parent.glob("*.py")) + [
        repo_path("src/weather/market/metar_reports.py"),
        repo_path("src/weather/market/venue_settlement_rules.py"),
        repo_path("src/weather/market/__init__.py"),
        repo_path("src/weather/backtesting/__init__.py"),
        repo_path("src/weather/__init__.py"), repo_path("src/weather/paths.py")]
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                if any(not allowed(a.name) for a in node.names):
                    raise ImportError("LOW-ASK-1 dependency refusal")
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                if not allowed(node.module):
                    raise ImportError("LOW-ASK-1 dependency refusal")
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {"eval", "exec", "__import__"}:
                raise ImportError("LOW-ASK-1 dynamic code refusal")


def install_boundary() -> None:
    assert_no_order_path()
    # The repository's benign console-suppression startup shim can preload
    # stdlib subprocess. Retire its cache entries in THIS dedicated process;
    # the finder below then denies re-import, including importlib cache hits.
    # Never silently discard a preloaded venue/network client: those refuse.
    sys.modules.pop("subprocess", None)
    sys.modules.pop("sitecustomize", None)
    if any(not allowed(name) for name in sys.modules):
        raise ImportError("LOW-ASK-1 contaminated process")
    sys.meta_path.insert(0, PaperImportBoundary())

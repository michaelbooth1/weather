import re
from pathlib import Path


APP_FILES = [
    *Path("app").rglob("*.py"),
    *Path("tests/app").rglob("*.py"),
]

WRAPPER_MODULE_NAMES = sorted(
    path.stem
    for path in Path("src").glob("*.py")
    if path.name != "__init__.py"
)

LEGACY_IMPORT_PATTERN = "|".join(re.escape(name) for name in WRAPPER_MODULE_NAMES)
LEGACY_IMPORT_RE = re.compile(
    (
        r"^(?:from|import)\s+(" + LEGACY_IMPORT_PATTERN + r")\b"
        if LEGACY_IMPORT_PATTERN
        else r"(?!x)x"
    ),
    re.MULTILINE,
)

MOJIBAKE_FRAGMENTS = ("\u00c2", "\u00c3", "\u00e2", "\u00f0", "\ufffd")
SYS_PATH_MUTATION_PATTERNS = (
    "sys.path" + ".insert",
    "sys.path" + ".append",
)
ROUTER_PATH = Path("app/streamlit_app.py")
VIEW_ROOT = Path("app/views")


def test_app_files_do_not_mutate_sys_path_or_import_legacy_wrappers():
    offenders = {}
    for path in APP_FILES:
        text = path.read_text(encoding="utf-8")
        findings = []
        if any(pattern in text for pattern in SYS_PATH_MUTATION_PATTERNS):
            findings.append("sys.path mutation")
        findings.extend(match.group(0) for match in LEGACY_IMPORT_RE.finditer(text))
        if findings:
            offenders[str(path)] = findings

    assert offenders == {}


def test_app_files_decode_as_utf8_without_mojibake_fragments():
    offenders = {}
    for path in APP_FILES:
        text = path.read_text(encoding="utf-8")
        matches = [fragment for fragment in MOJIBAKE_FRAGMENTS if fragment in text]
        if matches:
            offenders[str(path)] = matches

    assert offenders == {}


def test_streamlit_router_stays_thin_and_exposes_only_two_pages():
    router_text = ROUTER_PATH.read_text(encoding="utf-8")
    router_forbidden = [
        "SnapshotStore",
        "PolymarketClient",
        "TorontoHighTempModel",
        "all_specs",
        "data_path(",
        "@st.fragment",
        "render_single_market_page",
        "render_operations_page",
        "render_market_making_page",
        "render_overview_page",
        "render_history_page",
    ]

    view_files = {path.name for path in VIEW_ROOT.glob("*.py")}
    assert view_files == {"__init__.py", "control_room.py", "roadmap.py"}
    assert len(router_text.splitlines()) <= 100
    assert "render_control_room_page" in router_text
    assert "render_roadmap_page" in router_text
    assert all(pattern not in router_text for pattern in router_forbidden)


def test_frontend_does_not_reintroduce_retired_page_modules_or_routes():
    app_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in Path("app").rglob("*.py")
    )
    retired = (
        "app.views.history",
        "app.views.market_making",
        "app.views.model_pipeline",
        "app.views.operations",
        "app.views.overview",
        "app.views.single_market",
        '"overview"',
        '"history"',
        '"ops"',
        '"mm"',
    )

    assert all(marker not in app_text for marker in retired)

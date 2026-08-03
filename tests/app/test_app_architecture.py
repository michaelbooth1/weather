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
SINGLE_MARKET_VIEW_PATH = Path("app/views/single_market.py")


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


def test_streamlit_router_stays_thin_and_single_market_view_owns_page_body():
    router_text = ROUTER_PATH.read_text(encoding="utf-8")
    single_market_text = SINGLE_MARKET_VIEW_PATH.read_text(encoding="utf-8")
    router_forbidden = [
        "SnapshotStore",
        "PolymarketClient",
        "TorontoHighTempModel",
        "data_path(",
        "@st.fragment",
        "st.title(f\"{spec.city_label} Weather Market\")",
    ]

    assert SINGLE_MARKET_VIEW_PATH.exists()
    assert len(router_text.splitlines()) <= 100
    assert "render_single_market_page" in router_text
    assert "def render_single_market_page" in single_market_text
    assert "SnapshotStore" in single_market_text
    assert "PolymarketClient" in single_market_text
    assert "TorontoHighTempModel" in single_market_text
    assert {
        pattern: pattern in router_text
        for pattern in router_forbidden
        if pattern in router_text
    } == {}


def test_single_market_uses_served_floor_and_native_unit_labels():
    single_market_text = SINGLE_MARKET_VIEW_PATH.read_text(encoding="utf-8")

    assert 'model.get("distribution_components")' in single_market_text
    assert "Trusted observed-high floor" in single_market_text
    assert "Floor (Min possible high)" not in single_market_text
    assert "observed_bucket} C" not in single_market_text
    assert "high_so_far')} C" not in single_market_text
    assert "d['final_high']} C" not in single_market_text

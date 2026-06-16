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

LEGACY_IMPORT_RE = re.compile(
    r"^(?:from|import)\s+("
    + "|".join(re.escape(name) for name in WRAPPER_MODULE_NAMES)
    + r")\b",
    re.MULTILINE,
)

MOJIBAKE_FRAGMENTS = ("\u00c2", "\u00c3", "\u00e2", "\u00f0", "\ufffd")
SYS_PATH_MUTATION_PATTERNS = (
    "sys.path" + ".insert",
    "sys.path" + ".append",
)


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

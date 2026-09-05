"""Block agent shell commands that violate the exact capture-host load policy."""

from __future__ import annotations

import base64
import binascii
from datetime import datetime, time
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any


HEAVY_START = time(0, 30)
HEAVY_END = time(9, 0)
EXECUTION_HOST_DOMAIN = "international_live_execution_host_v2\0"
ASSIGNMENT_PATH = (
    Path(__file__).resolve().parents[2]
    / "config"
    / "international_live_execution_host.json"
)
_REPARSE_POINT = 0x400
_HEX64 = re.compile(r"\A[0-9a-f]{64}\Z")
_MAX_ASSIGNMENT_BYTES = 16_384
WORKSTATION_WRAPPER_PATH = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "ops"
    / "workstation_heavy.ps1"
)
_WORKSTATION_WRAPPER_CLOSURE = (
    Path("scripts/ops/workstation_heavy.ps1"),
    Path("scripts/ops/workload_admission.ps1"),
    Path("scripts/ops/windows_kill_on_close_job.ps1"),
)
_MAX_WRAPPER_CLOSURE_BYTES = 2 * 1024 * 1024
_SINGLE_QUOTE_CHARACTERS = frozenset({"'", "\u2018", "\u2019"})
_DOUBLE_QUOTE_CHARACTERS = frozenset({'"', "\u201c", "\u201d"})
_POWERSHELL_COMMAND_NAME_TRIM = " \t\u0085\u00a0"

_COMMAND_BOUNDARY = r"(?:\A|[;&|\r\n{}()])"
_COMMAND_TOKEN_END = r"(?=\s|[;&|{}()]|\Z)"
_OFFLINE_WEATHER_MODULES = frozenset(
    {
        "weather.backtesting.backtest",
        "weather.backtesting.replay",
        "weather.backtesting.replay_ablation",
        "weather.backtesting.replay_backtest",
        "weather.backtesting.snapshot_analytics",
        "weather.backtesting.tape_scoring",
        "weather.calibration.pooled_candidate_replay",
        "weather.calibration.pooled_candidate_replay_diagnostics",
        "weather.calibration.pooled_candidate_replay_report",
        "weather.operations.base_retrain",
        "weather.operations.density_live_replay_parity",
        "weather.operations.nightly_retrain",
        "weather.operations.replay_status_backfill",
        "weather.operations.workstation_cold_archive_stage",
        "weather.reporting.scorecards.train_serve_feature_parity",
    }
)
_OFFLINE_WEATHER_MODULE_PATTERN = (
    r"(?:"
    + "|".join(re.escape(module) for module in sorted(_OFFLINE_WEATHER_MODULES))
    + r")"
)
_OFFLINE_WEATHER_MODULE_ARGUMENT = (
    r'(?:"'
    + _OFFLINE_WEATHER_MODULE_PATTERN
    + r'"|\''
    + _OFFLINE_WEATHER_MODULE_PATTERN
    + r"\'|"
    + _OFFLINE_WEATHER_MODULE_PATTERN
    + r")"
)

_PYTHON_EXECUTABLE = (
    r"(?:(?:python|pythonw)(?:3(?:\.\d+)?t?)?"
    r"(?:-(?:32|64|arm64))?(?:_d)?(?:\.exe)?|"
    r"(?:pyw?|pyw?manager|pyw?-manager)(?:\.exe)?)"
)
_PYTHON_COMMAND = (
    _COMMAND_BOUNDARY
    + r"\s*(?:&\s*)?(?:"
    + r"\"(?:[^\"\r\n]*[\\/])?"
    + _PYTHON_EXECUTABLE
    + r"\"|'(?:[^'\r\n]*[\\/])?"
    + _PYTHON_EXECUTABLE
    + r"'|(?:[^\s;&|{}()]*[\\/])?"
    + _PYTHON_EXECUTABLE
    + r")(?=\s)"
)
_PYTHON_INVOCATION = re.compile(_PYTHON_COMMAND, re.IGNORECASE)
_MODULE_SWITCH = r"(?:-m|\"-m\"|'-m')"
_PYTEST_MODULE = r"(?:pytest|\"pytest\"|'pytest')"
_COMPILEALL_MODULE = r"(?:compileall|\"compileall\"|'compileall')"
_PYTEST = re.compile(
    _PYTHON_COMMAND
    + r"[^;&|\r\n{}()]*?\s"
    + _MODULE_SWITCH
    + r"\s+"
    + _PYTEST_MODULE
    + _COMMAND_TOKEN_END
    + r"|"
    + _COMMAND_BOUNDARY
    + r"\s*(?:&\s*)?(?:[^\s;&|{}()]*[\\/])?(?:pytest|py\.test)(?:\.exe)?\b",
    re.IGNORECASE,
)
_COMPILEALL = re.compile(
    _PYTHON_COMMAND
    + r"[^;&|\r\n{}()]*?\s"
    + _MODULE_SWITCH
    + r"\s+"
    + _COMPILEALL_MODULE
    + _COMMAND_TOKEN_END,
    re.IGNORECASE,
)
_DIRECT_ALLOWLISTED_WEATHER = re.compile(
    _PYTHON_COMMAND
    + r"[^;&|\r\n{}()]*?\s"
    + _MODULE_SWITCH
    + r"\s+"
    + _OFFLINE_WEATHER_MODULE_ARGUMENT
    + _COMMAND_TOKEN_END,
    re.IGNORECASE,
)
_DIRECT_HEAVY_WEATHER = re.compile(
    _PYTHON_COMMAND
    + r"[^;&|\r\n{}()]*?\s"
    + _MODULE_SWITCH
    + r"\s+['\"]?weather\.[^\s;&|{}()'\"]*"
    + r"(?:retrain|training|replay|backtest|daily_refresh|score_all)"
    + r"[^\s;&|{}()'\"]*['\"]?"
    + _COMMAND_TOKEN_END,
    re.IGNORECASE,
)
_CLUSTERABLE_PYTHON_FLAGS = r"[bBdEiIOPqRsSuvVx]*"
_CLUSTERED_MODULE_PREFIX = r"-" + _CLUSTERABLE_PYTHON_FLAGS + r"m"
_CLUSTERED_MODULE_TOKEN = re.compile(
    r"\A" + _CLUSTERED_MODULE_PREFIX + r"(?P<module>.+)\Z"
)
_ATTACHED_PYTHON_MODULE = re.compile(
    _PYTHON_COMMAND
    + r"[^;&|\r\n{}()]*?\s+"
    + r'''(?P<argument>"'''
    + _CLUSTERED_MODULE_PREFIX
    + r'''[^"\r\n]+"|'-'''
    + _CLUSTERABLE_PYTHON_FLAGS
    + r'''m[^'\r\n]+'|'''
    + _CLUSTERED_MODULE_PREFIX
    + r'''[^\s;&|{}()\r\n]+)''',
    re.IGNORECASE,
)
_LOOSE_ATTACHED_MODULE = re.compile(
    r'''(?<![A-Za-z0-9_'"-])(?P<argument>"'''
    + _CLUSTERED_MODULE_PREFIX
    + r'''[^"\r\n]+"|'-'''
    + _CLUSTERABLE_PYTHON_FLAGS
    + r'''m[^'\r\n]+'|'''
    + _CLUSTERED_MODULE_PREFIX
    + r'''[^\s;&|{}()\r\n]+)''',
    re.IGNORECASE,
)
_CLUSTERED_PYTHON_MODULE_SWITCH = re.compile(
    _PYTHON_COMMAND
    + r"[^;&|\r\n{}()]*?\s+"
    + r'''(?P<switch>"'''
    + _CLUSTERED_MODULE_PREFIX
    + r'''"|'-'''
    + _CLUSTERABLE_PYTHON_FLAGS
    + r'''m'|'''
    + _CLUSTERED_MODULE_PREFIX
    + r''')''',
    re.IGNORECASE,
)
_LOOSE_CLUSTERED_MODULE_SWITCH = re.compile(
    r'''(?<![A-Za-z0-9_'"-])(?P<switch>"'''
    + _CLUSTERED_MODULE_PREFIX
    + r'''"|'-'''
    + _CLUSTERABLE_PYTHON_FLAGS
    + r'''m'|'''
    + _CLUSTERED_MODULE_PREFIX
    + r''')''',
    re.IGNORECASE,
)
_HEURISTIC_HEAVY_WEATHER_NAME = re.compile(
    r"\Aweather\.[A-Za-z0-9_.-]*"
    r"(?:retrain|training|replay|backtest|daily_refresh|score_all)"
    r"[A-Za-z0-9_.-]*\Z",
    re.IGNORECASE,
)
_HEAVY_TEST_ENTRYPOINT = re.compile(
    _COMMAND_BOUNDARY
    + r"\s*(?:&\s*)?"
    r"(?:"
    r"\"(?:[^\"\r\n]*[\\/])?(?:coverage(?:3|-\d+(?:\.\d+)?)?|tox|nox)(?:\.exe)?\"|"
    r"'(?:[^'\r\n]*[\\/])?(?:coverage(?:3|-\d+(?:\.\d+)?)?|tox|nox)(?:\.exe)?'|"
    r"(?:[^\s;&|{}()]*[\\/])?(?:coverage(?:3|-\d+(?:\.\d+)?)?|tox|nox)(?:\.exe)?"
    r")"
    + _COMMAND_TOKEN_END,
    re.IGNORECASE,
)
_PYTEST_ENTRYPOINT = re.compile(
    _COMMAND_BOUNDARY
    + r"\s*(?:&\s*)?(?:[^\s;&|{}()]*[\\/])?"
    + r"(?:pytest|py\.test)(?:\.exe)?\b",
    re.IGNORECASE,
)
_TEST_FILE = re.compile(r"(?i)(?:^|\s)(?:[^\s\"']*[\\/])?test_[^\s\"']*\.py(?=\s|$)")
_POWERSHELL_COMMAND_SWITCHES = (
    "c", "co", "com", "comm", "comma", "comman", "command", "cwa",
    "commandw", "commandwi", "commandwit", "commandwith",
    "commandwitha", "commandwithar", "commandwitharg", "commandwithargs",
)
_POWERSHELL_ENCODED_SWITCHES = (
    "e", "ec", "en", "enc", "enco", "encod", "encode", "encoded",
    "encodedc", "encodedco", "encodedcom", "encodedcomm",
    "encodedcomma", "encodedcomman", "encodedcommand",
)
_POWERSHELL_FILE_SWITCHES = ("f", "fi", "fil", "file")
_START_PROCESS_PARAMETERS = frozenset(
    {
        "argumentlist",
        "confirm",
        "credential",
        "debug",
        "environment",
        "erroraction",
        "errorvariable",
        "filepath",
        "informationaction",
        "informationvariable",
        "loaduserprofile",
        "nonewwindow",
        "outbuffer",
        "outvariable",
        "passthru",
        "pipelinevariable",
        "progressaction",
        "redirectstandarderror",
        "redirectstandardinput",
        "redirectstandardoutput",
        "usenewenvironment",
        "verb",
        "verbose",
        "wait",
        "warningaction",
        "warningvariable",
        "whatif",
        "windowstyle",
        "workingdirectory",
    }
)
_START_PROCESS_VALUE_PARAMETERS = frozenset(
    {
        "credential",
        "environment",
        "erroraction",
        "errorvariable",
        "filepath",
        "informationaction",
        "informationvariable",
        "outbuffer",
        "outvariable",
        "pipelinevariable",
        "progressaction",
        "redirectstandarderror",
        "redirectstandardinput",
        "redirectstandardoutput",
        "verb",
        "warningaction",
        "warningvariable",
        "windowstyle",
        "workingdirectory",
    }
)
_START_PROCESS_PARAMETER_ALIASES = {
    "args": "argumentlist",
    "cf": "confirm",
    "db": "debug",
    "ea": "erroraction",
    "ev": "errorvariable",
    "infa": "informationaction",
    "iv": "informationvariable",
    "lup": "loaduserprofile",
    "nnw": "nonewwindow",
    "ob": "outbuffer",
    "ov": "outvariable",
    "path": "filepath",
    "proga": "progressaction",
    "pspath": "filepath",
    "pv": "pipelinevariable",
    "rse": "redirectstandarderror",
    "rsi": "redirectstandardinput",
    "rso": "redirectstandardoutput",
    "runas": "credential",
    "vb": "verbose",
    "wa": "warningaction",
    "wi": "whatif",
    "wv": "warningvariable",
}
_POWERSHELL_SCRIPT_BLOCK = re.compile(
    r"(?is)\{(?P<arguments>[^{}]*)\}"
)
_POWERSHELL_SUBEXPRESSION = re.compile(
    r"(?is)\$?\((?P<arguments>[^()]*)\)"
)
_LOOSE_PYTEST_MODULE = re.compile(
    r"(?i)(?<![A-Za-z0-9_-])-m(?:\s|[,;'\"\(\)=])+pytest\b"
)
_LOOSE_COMPILEALL_MODULE = re.compile(
    r"(?i)(?<![A-Za-z0-9_-])-m(?:\s|[,;'\"\(\)=])+compileall\b"
)
_STATIC_MODULE_ARGUMENT = re.compile(r"\A[A-Za-z0-9_.-]+\Z")
_PYTHON_MODULE_SWITCH = re.compile(
    _PYTHON_COMMAND
    + r"[^;&|\r\n{}()]*?\s"
    + _MODULE_SWITCH
    + r"\s+",
    re.IGNORECASE,
)
_QUOTED_PYTHON_MODULE_SWITCH = re.compile(
    _PYTHON_COMMAND
    + r"[^;&|\r\n{}()]*?\s+"
    + r'''(?:"-m"|'-m')''',
    re.IGNORECASE,
)
_LOOSE_MODULE_SWITCH = re.compile(
    r'''(?ix)(?<![A-Za-z0-9_-])(?:
        -m\s+|
        "-m"(?:\s|,)+|
        '-m'(?:\s|,)+
    )'''
)
_LOOSE_QUOTED_MODULE_SWITCH = re.compile(
    r'''(?i)(?<![A-Za-z0-9_'"-])(?:"-m"|'-m')'''
)
_LOOSE_ALLOWLISTED_WEATHER_MODULE = re.compile(
    r"(?i)(?<![A-Za-z0-9_-])-m(?:\s|[,;'\"\(\)=])+"
    + _OFFLINE_WEATHER_MODULE_PATTERN
    + r"(?=$|[\s,;'\"()&|{}])"
)
_LOOSE_HEAVY_WEATHER_MODULE = re.compile(
    r"(?i)(?<![A-Za-z0-9_-])-m(?:\s|[,;'\"\(\)=])+"
    r"weather\.[A-Za-z0-9_.-]*"
    r"(?:retrain|training|replay|backtest|daily_refresh|score_all)"
    r"[A-Za-z0-9_.-]*(?=$|[\s,;'\"()&|{}])"
)
_LOOSE_TEST_EXECUTABLE = re.compile(
    r"(?i)(?<![A-Za-z0-9_.-])"
    r"(?:pytest|py\.test|coverage(?:3|-\d+(?:\.\d+)?)?|tox|nox)(?:\.exe)?"
    r"(?=$|[\s,;'\"()&|{}])"
)
_WORKSTATION_WRAPPER_CALL = re.compile(
    r"(?is)\A\s*&\s+'(?P<script>[^'\r\n]+)'\s+"
    r"-Kind\s+(?P<kind>pytest|compileall|weather_heavy)\s+"
    r"-PythonPath\s+'(?P<python>[^'\r\n]+)'\s+"
    r"-ArgumentsBase64\s+'(?P<arguments>[A-Za-z0-9+/]*={0,2})'\s+"
    r"-RepoRoot\s+'(?P<repo_root>[^'\r\n]+)'\s*\Z"
)
_VARIABLE_EXECUTION = re.compile(
    r"(?is)" + _COMMAND_BOUNDARY + r"\s*&\s*\$[A-Za-z_][A-Za-z0-9_:.-]*\s+"
    r"(?P<arguments>[^;&|\r\n{}()]*)"
)
_DYNAMIC_EXECUTION = re.compile(
    r"(?is)" + _COMMAND_BOUNDARY + r"\s*&\s*"
    r"(?:\$\{[^}\r\n]+\}|\$?\([^\r\n;]+\))\s+"
    r"(?P<arguments>[^;&|\r\n{}()]*)"
)
_LIVE_ARGUMENT = re.compile(r"(?i)\A--?(?:live|execute|place|cancel|promote)(?:=|\Z)")


def _quote_class(character: str) -> str | None:
    if character in _SINGLE_QUOTE_CHARACTERS:
        return "'"
    if character in _DOUBLE_QUOTE_CHARACTERS:
        return '"'
    return None


def _powershell_parenthetical_end(command: str, opening: int) -> int | None:
    """Return the end of one balanced PowerShell parenthetical expression."""

    depth = 0
    quote = None
    cursor = opening
    while cursor < len(command):
        character = command[cursor]
        character_quote = _quote_class(character)
        if character == "`" and quote != "'":
            cursor = min(cursor + 2, len(command))
            continue
        if quote is not None:
            if character_quote == quote:
                if (
                    quote == "'"
                    and cursor + 1 < len(command)
                    and _quote_class(command[cursor + 1]) == quote
                ):
                    cursor += 2
                    continue
                quote = None
            cursor += 1
            continue
        if character_quote is not None:
            quote = character_quote
        elif character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth == 0:
                return cursor + 1
        cursor += 1
    return None


def _powershell_executable_skeleton(command: str) -> str:
    """Mask non-executing string text while preserving expandable subexpressions."""

    output = list(command)
    quote = None
    cursor = 0
    while cursor < len(command):
        character = command[cursor]
        character_quote = _quote_class(character)
        if quote is None:
            if command[cursor : cursor + 2] == "<#":
                comment_depth = 0
                while cursor < len(command):
                    if command[cursor : cursor + 2] == "<#":
                        output[cursor : cursor + 2] = [" ", " "]
                        comment_depth += 1
                        cursor += 2
                        continue
                    if command[cursor : cursor + 2] == "#>":
                        output[cursor : cursor + 2] = [" ", " "]
                        comment_depth -= 1
                        cursor += 2
                        if comment_depth == 0:
                            break
                        continue
                    output[cursor] = " "
                    cursor += 1
                continue
            if character == "#" and (
                cursor == 0
                or command[cursor - 1].isspace()
                or command[cursor - 1] in ";|&{}():."
            ):
                while cursor < len(command) and command[cursor] not in "\r\n":
                    output[cursor] = " "
                    cursor += 1
                continue
            if character == "`" and cursor + 1 < len(command):
                if not command[cursor + 1].isalnum():
                    output[cursor] = " "
                    output[cursor + 1] = " "
                cursor += 2
                continue
            if character_quote is not None:
                quote = character_quote
                output[cursor] = " "
            cursor += 1
            continue
        if quote == '"' and character == "$" and command[cursor : cursor + 2] == "$(":
            expression_end = _powershell_parenthetical_end(command, cursor + 1)
            if expression_end is None:
                return "".join(output)
            cursor = expression_end
            continue
        output[cursor] = " "
        if character == "`" and quote == '"':
            if cursor + 1 < len(command):
                output[cursor + 1] = " "
            cursor += 2
            continue
        if character_quote == quote:
            if (
                quote == "'"
                and cursor + 1 < len(command)
                and _quote_class(command[cursor + 1]) == quote
            ):
                output[cursor + 1] = " "
                cursor += 2
                continue
            quote = None
        cursor += 1
    return "".join(output)


def _static_powershell_member_name(expression: str) -> str | None:
    """Decode a simple quoted/concatenated static member selector."""

    without_comments = re.sub(r"(?s)<#.*?#>", " ", expression)
    without_comments = re.sub(
        r"(?m)(?:\A|(?<=\s))#[^\r\n]*",
        " ",
        without_comments,
    )
    if re.fullmatch(
        r"[A-Za-z\s+'\"\u2018\u2019\u201c\u201d]*",
        without_comments,
    ) is None:
        return None
    return re.sub(
        r"[\s+'\"\u2018\u2019\u201c\u201d]",
        "",
        without_comments,
    ).lower()


def _powershell_first_argument(arguments: str) -> str:
    """Return one call's first top-level argument without evaluating it."""

    depth = 0
    quote = None
    cursor = 0
    while cursor < len(arguments):
        character = arguments[cursor]
        character_quote = _quote_class(character)
        if character == "`" and quote != "'":
            cursor = min(cursor + 2, len(arguments))
            continue
        if quote is not None:
            if character_quote == quote:
                if (
                    quote == "'"
                    and cursor + 1 < len(arguments)
                    and _quote_class(arguments[cursor + 1]) == quote
                ):
                    cursor += 2
                    continue
                quote = None
            cursor += 1
            continue
        if character_quote is not None:
            quote = character_quote
        elif character in "([{":
            depth += 1
        elif character in ")]}" and depth:
            depth -= 1
        elif character == "," and depth == 0:
            return arguments[:cursor]
        cursor += 1
    return arguments


def _powershell_runspace_sink(
    command: str,
    executable_skeleton: str,
) -> bool:
    """Recognize execution-bearing PowerShell pipeline builder calls."""

    normalized = executable_skeleton.replace("`", "")
    sinks = {"addscript", "addcommand"}
    reflection_apis = {"getmethod", "getruntimemethod", "invokemember"}
    invoke_pattern = re.compile(
        r"(?is)\.\s*(?:invoke|begininvoke|invokeasync)\s*\("
    )

    def reflection_call_is_sink(opening: int) -> bool:
        reflection_end = _powershell_parenthetical_end(command, opening)
        if reflection_end is None:
            return True
        first_argument = _powershell_first_argument(
            command[opening + 1 : reflection_end - 1]
        )
        reflected_member = _static_powershell_member_name(first_argument)
        return bool(
            reflected_member in sinks
            or invoke_pattern.search(normalized[reflection_end:])
        )

    if re.search(r"(?is)\.\s*(?:addscript|addcommand)\s*\(", normalized):
        return True
    if (
        re.search(
            r"(?is)\.\s*psobject\s*\.\s*(?:methods|members)\s*\[",
            normalized,
        )
        and invoke_pattern.search(normalized)
    ):
        return True

    # Reflection can invoke the same sinks without ever spelling `.AddScript(`
    # as executable syntax. Correlate the lookup call with its first static
    # member-name argument rather than with unrelated quoted text elsewhere.
    for reflection in re.finditer(
        r"(?is)\.\s*(?:getmethod|getruntimemethod|invokemember)\s*\(",
        normalized,
    ):
        opening = reflection.end() - 1
        if reflection_call_is_sink(opening):
            return True

    # Quoted member syntax leaves only whitespace between the visible dot and
    # call parenthesis in the skeleton. A parenthesized static expression uses
    # that first parenthesis as its selector and a second one as its call.
    for selector in re.finditer(r"(?is)\.\s*\(", normalized):
        opening = selector.end() - 1
        inline_selector = command[selector.start() + 1 : opening]
        inline_member = _static_powershell_member_name(inline_selector)
        if inline_member in sinks:
            return True
        if (
            inline_member in reflection_apis
            and reflection_call_is_sink(opening)
        ):
            return True
        if inline_selector.strip():
            continue
        selector_end = _powershell_parenthetical_end(command, opening)
        if selector_end is None:
            continue
        call_start = selector_end
        while call_start < len(normalized) and normalized[call_start].isspace():
            call_start += 1
        if call_start < len(normalized) and normalized[call_start] == "(":
            selector_member = _static_powershell_member_name(
                command[opening + 1 : selector_end - 1]
            )
            if selector_member in sinks:
                return True
            if (
                selector_member in reflection_apis
                and reflection_call_is_sink(call_start)
            ):
                return True

    # An opaque member selector whose result is subsequently invoked is an
    # execution chain. This contains variable/expression spellings without
    # classifying ordinary dynamic property or method access by itself.
    dynamic_member = re.search(
        r"(?is)\.\s*(?:\$(?:\{[^}\r\n]+\}|[A-Za-z_][A-Za-z0-9_:.-]*)|"
        r"\(\s*[$@])",
        normalized,
    )
    invokes_pipeline = invoke_pattern.search(normalized)
    return bool(dynamic_member and invokes_pipeline)


def _derive_execution_host_id(machine_guid: str) -> str:
    canonical = machine_guid.strip().lower()
    if not canonical:
        raise ValueError("empty Windows installation identity")
    return hashlib.sha256(
        f"{EXECUTION_HOST_DOMAIN}{canonical}".encode("utf-8")
    ).hexdigest()


def _read_machine_guid() -> str:
    import winreg

    access = winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0)
    with winreg.OpenKey(
        winreg.HKEY_LOCAL_MACHINE,
        r"SOFTWARE\Microsoft\Cryptography",
        0,
        access,
    ) as key:
        value, value_type = winreg.QueryValueEx(key, "MachineGuid")
    if value_type != winreg.REG_SZ or not isinstance(value, str):
        raise ValueError("Windows installation identity is not a string")
    return value


def _reject_duplicate_json_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("capture-host assignment contains a duplicate key")
        result[key] = value
    return result


def _read_stable_assignment(path: Path) -> bytes:
    assignment_path = Path(os.path.abspath(os.fspath(path)))
    cursor = Path(assignment_path.anchor)
    for part in assignment_path.parts[1:]:
        cursor /= part
        entry = cursor.lstat()
        if cursor.is_symlink() or bool(
            getattr(entry, "st_file_attributes", 0) & _REPARSE_POINT
        ):
            raise ValueError("capture-host assignment path is redirected")

    descriptor = os.open(
        assignment_path,
        os.O_RDONLY | getattr(os, "O_BINARY", 0),
    )
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_size <= 0
            or opened.st_size > _MAX_ASSIGNMENT_BYTES
        ):
            raise ValueError("capture-host assignment is not a bounded regular file")
        chunks: list[bytes] = []
        remaining = _MAX_ASSIGNMENT_BYTES + 1
        while remaining > 0:
            block = os.read(descriptor, min(8192, remaining))
            if not block:
                break
            chunks.append(block)
            remaining -= len(block)
        raw = b"".join(chunks)
        after_handle = os.fstat(descriptor)
        after_path = assignment_path.stat()
        if (
            len(raw) != opened.st_size
            or not os.path.samestat(opened, after_handle)
            or not os.path.samestat(opened, after_path)
            or after_handle.st_size != opened.st_size
            or after_handle.st_mtime_ns != opened.st_mtime_ns
        ):
            raise ValueError("capture-host assignment changed while it was read")
        return raw
    finally:
        os.close(descriptor)


def _read_dedicated_capture_host_id(path: Path) -> str:
    raw = _read_stable_assignment(path)
    if raw.startswith(b"\xef\xbb\xbf"):
        raise ValueError("capture-host assignment must not contain a BOM")
    assignment = json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=_reject_duplicate_json_pairs,
    )
    expected = {
        "active_portable_execution_host_id",
        "active_portable_execution_principal_id",
        "assignment_status",
        "dedicated_capture_execution_host_id",
        "reassignment_requires_new_production_tip",
        "schema_version",
    }
    if not isinstance(assignment, dict) or set(assignment) != expected:
        raise ValueError("capture-host assignment does not have the exact keys")
    dedicated_id = assignment["dedicated_capture_execution_host_id"]
    active_host_id = assignment["active_portable_execution_host_id"]
    active_principal_id = assignment["active_portable_execution_principal_id"]
    status_value = assignment["assignment_status"]
    if (
        assignment["schema_version"]
        != "international_live_execution_host_assignment_v0.1"
        or not isinstance(dedicated_id, str)
        or _HEX64.fullmatch(dedicated_id) is None
        or assignment["reassignment_requires_new_production_tip"] is not True
        or status_value not in {"UNASSIGNED", "ASSIGNED"}
    ):
        raise ValueError("capture-host assignment contract is invalid")
    if status_value == "UNASSIGNED":
        if active_host_id is not None or active_principal_id is not None:
            raise ValueError("unassigned capture-host assignment has active identities")
    elif (
        not isinstance(active_host_id, str)
        or _HEX64.fullmatch(active_host_id) is None
        or not isinstance(active_principal_id, str)
        or _HEX64.fullmatch(active_principal_id) is None
        or active_host_id == dedicated_id
    ):
        raise ValueError("assigned portable execution-host identity is invalid")
    return dedicated_id


def _capture_host_policy_state(
    *,
    assignment_path: Path = ASSIGNMENT_PATH,
    machine_guid: str | None = None,
    windows: bool | None = None,
) -> bool | None:
    """Return exact capture-host match, non-match, or indeterminate proof."""

    is_windows = os.name == "nt" if windows is None else windows
    if not is_windows:
        return False
    try:
        observed_id = _derive_execution_host_id(
            _read_machine_guid() if machine_guid is None else machine_guid
        )
        dedicated_id = _read_dedicated_capture_host_id(assignment_path)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None
    return observed_id == dedicated_id


def _inside_heavy_window(now: datetime) -> bool:
    local = now.astimezone()
    return HEAVY_START <= local.time().replace(tzinfo=None) < HEAVY_END


def _forbidden_recursive_scan(command: str) -> bool:
    normalized = command.replace("/", "\\")
    data_root = re.search(r"(?i)(?:^|[\s\"'])(?:\.\\)?data(?:\\|[\s\"'])", normalized)
    get_child = re.search(r"(?i)\bGet-ChildItem\b", command)
    recurse = re.search(r"(?i)(?:^|\s)-(?:Recurse|r)(?:\s|$)", command)
    broad_rg = re.search(r"(?i)(?:^|[\s;&|])rg(?:\.exe)?(?:\s|$)", command)
    return bool((get_child and recurse) or (data_root and broad_rg))


def _iter_raw_shell_word_records(command: str, start: int):
    """Yield raw shell words and spans while preserving quote layout."""

    cursor = start
    escape = chr(96)
    while cursor < len(command):
        while cursor < len(command) and command[cursor].isspace():
            cursor += 1
        if cursor >= len(command) or command[cursor] in ";&|\r\n{}()":
            return
        word_start = cursor
        quote = None
        while cursor < len(command):
            character = command[cursor]
            if character == escape and quote != "'":
                cursor = min(cursor + 2, len(command))
                continue
            if character == "\\" and quote is not None and cursor + 1 < len(command):
                if _quote_class(command[cursor + 1]) == quote:
                    cursor += 2
                    continue
            if quote is not None:
                if _quote_class(character) == quote:
                    quote = None
                cursor += 1
                continue
            character_quote = _quote_class(character)
            if character_quote is not None:
                quote = character_quote
                cursor += 1
                continue
            if character.isspace() or character in ";&|\r\n{}()":
                break
            cursor += 1
        if cursor > word_start:
            yield command[word_start:cursor], word_start, cursor
        if cursor < len(command) and command[cursor] in ";&|\r\n{}()":
            return


def _iter_raw_shell_words(command: str, start: int):
    """Yield one command segment's raw words while preserving quote layout."""

    for word, _word_start, _word_end in _iter_raw_shell_word_records(command, start):
        yield word


def _decode_static_shell_word(word: str) -> tuple[str, bool]:
    """Return the literal concatenation and whether shell expansion is possible."""

    output: list[str] = []
    quote = None
    dynamic = False
    escape = chr(96)
    cursor = 0
    while cursor < len(word):
        character = word[cursor]
        if character == escape and quote != "'":
            dynamic = True
            cursor += 2
            continue
        if quote is not None:
            if _quote_class(character) == quote:
                quote = None
            else:
                if quote == '"' and character == "$":
                    dynamic = True
                output.append(character)
            cursor += 1
            continue
        character_quote = _quote_class(character)
        if character_quote is not None:
            quote = character_quote
        elif character in {"$", "^", "%", "!"}:
            dynamic = True
            output.append(character)
        else:
            output.append(character)
        cursor += 1
    if quote is not None:
        dynamic = True
    return "".join(output), dynamic


def _whole_quoted_word(word: str) -> bool:
    if len(word) < 2:
        return False
    quote = _quote_class(word[0])
    if quote is None or _quote_class(word[-1]) != quote:
        return False
    return sum(_quote_class(character) == quote for character in word) == 2


def _whole_powershell_string_literal(word: str) -> bool:
    """Recognize a complete static PowerShell string, including doubled quotes."""

    if len(word) < 2:
        return False
    quote = _quote_class(word[0])
    if quote is None:
        return False
    cursor = 1
    while cursor < len(word):
        character = word[cursor]
        if character == "`" and quote == '"':
            cursor += 2
            continue
        if _quote_class(character) == quote:
            if (
                quote == "'"
                and cursor + 1 < len(word)
                and _quote_class(word[cursor + 1]) == quote
            ):
                cursor += 2
                continue
            return cursor == len(word) - 1
        cursor += 1
    return False


def _canonical_clustered_switch_word(word: str) -> bool:
    """Recognize the deliberately supported static spellings of -<flags>m."""

    bare = re.compile(
        r"\A" + _CLUSTERED_MODULE_PREFIX + r"(?:[A-Za-z0-9_.-]+)?\Z",
        re.IGNORECASE,
    )
    if bare.fullmatch(word) is not None:
        return True
    if _whole_quoted_word(word) and bare.fullmatch(word[1:-1]) is not None:
        return True
    for quote in ("'", '"'):
        prefix = re.match(
            re.escape(quote)
            + _CLUSTERED_MODULE_PREFIX
            + re.escape(quote),
            word,
            re.IGNORECASE,
        )
        if prefix is None:
            continue
        tail = word[prefix.end() :]
        if _STATIC_MODULE_ARGUMENT.fullmatch(tail) is not None:
            return True
        if (
            _whole_quoted_word(tail)
            and _STATIC_MODULE_ARGUMENT.fullmatch(tail[1:-1]) is not None
        ):
            return True
    return False


def _decode_module_word(word: str) -> tuple[str | None, bool]:
    decoded, dynamic = _decode_static_shell_word(word)
    if dynamic:
        return None, True
    if word != decoded and not _whole_quoted_word(word):
        return None, True
    if _STATIC_MODULE_ARGUMENT.fullmatch(decoded) is not None:
        return decoded.lower(), False
    return None, False


def _parse_python_invocation(
    words: tuple[str, ...],
    *,
    launcher: bool,
) -> tuple[str | None, bool, tuple[str, ...]]:
    """Parse CPython interpreter arguments through the selected entry point."""

    no_argument_flags = _CLUSTERABLE_PYTHON_FLAGS
    module_option = re.compile(
        r"\A-(?P<flags>" + _CLUSTERABLE_PYTHON_FLAGS + r")m(?P<module>.*)\Z",
    )
    consuming_option = re.compile(
        r"\A-" + no_argument_flags + r"(?P<option>[WX])(?P<value>.*)\Z",
    )
    index = 0
    while index < len(words):
        raw_word = words[index]
        word, dynamic = _decode_static_shell_word(raw_word)
        if dynamic:
            return None, True, ()
        if raw_word.startswith("@"):
            return None, True, ()
        if launcher and re.fullmatch(
            r"[/-]\d+(?:\.\d+)?t?(?:-(?:32|64|arm64))?",
            word,
        ):
            index += 1
            continue
        if launcher and re.fullmatch(
            r"[/-]V:(?:[A-Za-z0-9_.-]+(?:[\\/][A-Za-z0-9_.-]*)?)?",
            word,
        ):
            if raw_word != word and not _whole_quoted_word(raw_word):
                return None, True, ()
            index += 1
            continue
        module_match = module_option.fullmatch(word)
        if module_match is not None:
            if "V" in module_match.group("flags"):
                return None, False, ()
            if not _canonical_clustered_switch_word(raw_word):
                return None, True, ()
            attached = module_match.group("module")
            if attached:
                if _STATIC_MODULE_ARGUMENT.fullmatch(attached) is None:
                    return None, False, ()
                return attached.lower(), False, words[index + 1 :]
            if index + 1 >= len(words):
                return None, True, ()
            if words[index + 1].startswith("@"):
                return None, True, ()
            module, module_dynamic = _decode_module_word(words[index + 1])
            return module, module_dynamic, words[index + 2 :]
        consuming_match = consuming_option.fullmatch(word)
        if consuming_match is not None:
            if not consuming_match.group("value"):
                if index + 1 >= len(words):
                    return None, False, ()
                _value, value_dynamic = _decode_static_shell_word(words[index + 1])
                if value_dynamic or words[index + 1].startswith("@"):
                    return None, True, ()
                index += 2
            else:
                index += 1
            continue
        lowered = word.lower()
        if lowered == "--check-hash-based-pycs":
            if index + 1 >= len(words):
                return None, False, ()
            _value, value_dynamic = _decode_static_shell_word(words[index + 1])
            if value_dynamic or words[index + 1].startswith("@"):
                return None, True, ()
            index += 2
            continue
        if lowered.startswith("--check-hash-based-pycs="):
            index += 1
            continue
        if lowered == "--" or lowered == "-" or lowered == "-c":
            return None, False, ()
        if lowered.startswith("-c") and len(word) > 2:
            return None, False, ()
        if "V" in word and re.fullmatch(r"-" + no_argument_flags, word):
            return None, False, ()
        if re.fullmatch(r"-" + no_argument_flags, word):
            index += 1
            continue
        if word.startswith("-"):
            return None, False, ()
        return None, False, ()
    return None, False, ()


def _iter_raw_command_segment_records(command: str):
    """Yield top-level command segments and their source spans."""

    escape = chr(96)
    start = 0
    cursor = 0
    quote = None
    while cursor < len(command):
        character = command[cursor]
        if character == escape and quote != "'":
            cursor = min(cursor + 2, len(command))
            continue
        if quote is not None:
            if _quote_class(character) == quote:
                quote = None
            cursor += 1
            continue
        character_quote = _quote_class(character)
        if character_quote is not None:
            quote = character_quote
            cursor += 1
            continue
        if character in ";&|\r\n{}()":
            if command[start:cursor].strip():
                yield command[start:cursor], start, cursor
            start = cursor + 1
        cursor += 1
    if command[start:].strip():
        yield command[start:], start, len(command)


def _iter_raw_command_segments(command: str):
    """Yield top-level command segments without entering quoted payload text."""

    for segment, _start, _end in _iter_raw_command_segment_records(command):
        yield segment


def _segment_consumes_pipeline_stdin(command: str, start: int) -> bool:
    cursor = start - 1
    while cursor >= 0 and command[cursor].isspace():
        cursor -= 1
    if cursor < 0:
        return False
    if command[cursor] == "|":
        previous = cursor - 1
        while previous >= 0 and command[previous].isspace():
            previous -= 1
        return previous < 0 or command[previous] != "|"
    if command[cursor] == "&":
        previous = cursor - 1
        while previous >= 0 and command[previous].isspace():
            previous -= 1
        return previous >= 0 and command[previous] == "|"
    return False


def _python_executable_kind(raw_word: str) -> tuple[bool, bool, bool] | None:
    """Return (is_launcher, dynamic, is_manager) for plausible Python."""

    decoded, dynamic = _decode_static_shell_word(raw_word)
    basename = re.split(
        r"[\\/]", decoded.strip(_POWERSHELL_COMMAND_NAME_TRIM)
    )[-1].lower()
    exact = re.fullmatch(
        r"(?:(?:python|pythonw)(?:3(?:\.\d+)?t?)?"
        r"(?:-(?:32|64|arm64))?(?:_d)?(?:\.exe)?|"
        r"(?:pyw?|pyw?manager|pyw?-manager)(?:\.exe)?)",
        basename,
    )
    if exact is not None:
        return (
            bool(
                re.fullmatch(
                    r"(?:pyw?|pyw?manager|pyw?-manager)(?:\.exe)?",
                    basename,
                )
            ),
            dynamic,
            bool(
                re.fullmatch(
                    r"(?:pyw?manager|pyw?-manager)(?:\.exe)?",
                    basename,
                )
            ),
        )
    if not dynamic:
        return None
    skeleton = re.sub(r"\$\([^)]*\)", "", raw_word)
    skeleton = re.sub(
        r"\$(?:\{[^}]*\}|[A-Za-z_][A-Za-z0-9_:]*)",
        "",
        skeleton,
    )
    skeleton = re.sub(r"%[^%]*%|![^!]*!", "", skeleton)
    skeleton = skeleton.replace(chr(96), "").replace("^", "")
    skeleton = skeleton.replace('"', "").replace("'", "")
    skeleton = re.split(r"[\\/]", skeleton)[-1].lower()
    if re.fullmatch(
        r"(?:(?:python|pythonw)(?:3(?:\.\d+)?t?)?"
        r"(?:-(?:32|64|arm64))?(?:_d)?(?:\.exe)?|"
        r"(?:pyw?|pyw?manager|pyw?-manager)(?:\.exe)?)",
        skeleton,
    ) is None:
        raw_basename = re.split(r"[\\/]", raw_word)[-1]
        raw_basename = raw_basename.replace('"', "").replace("'", "").lower()
        if not raw_basename.startswith("p"):
            return None
        return False, True, False
    return (
        bool(
            re.fullmatch(
                r"(?:pyw?|pyw?manager|pyw?-manager)(?:\.exe)?",
                skeleton,
            )
        ),
        True,
        bool(
            re.fullmatch(
                r"(?:pyw?manager|pyw?-manager)(?:\.exe)?",
                skeleton,
            )
        ),
    )


def _consume_manager_exec_options(
    arguments: tuple[str, ...],
) -> tuple[tuple[str, ...], bool, bool]:
    """Consume Python Install Manager common options after exec."""

    index = 0
    while index < len(arguments):
        raw_option = arguments[index]
        option, dynamic = _decode_static_shell_word(raw_option)
        if dynamic or raw_option.startswith("@"):
            return (), True, False
        if re.fullmatch(r"-(?:q+|v+)", option) or option in {
            "--quiet",
            "--verbose",
        }:
            index += 1
            continue
        if option.startswith("--config="):
            index += 1
            continue
        if option == "--config":
            if index + 1 >= len(arguments):
                return (), False, True
            _value, value_dynamic = _decode_static_shell_word(arguments[index + 1])
            if value_dynamic or arguments[index + 1].startswith("@"):
                return (), True, False
            index += 2
            continue
        if option in {"-?", "--help"}:
            return (), False, True
        break
    return arguments[index:], False, False


def _python_module_records(
    command: str,
) -> list[tuple[str | None, bool, tuple[str, ...]]]:
    records: list[tuple[str | None, bool, tuple[str, ...]]] = []
    for segment in _iter_raw_command_segments(command):
        words = tuple(_iter_raw_shell_words(segment, 0))
        if not words:
            continue
        kind = _python_executable_kind(words[0])
        if kind is None:
            _decoded_executable, executable_dynamic = _decode_static_shell_word(
                words[0]
            )
            if executable_dynamic and words[0].strip("'\"").startswith("$"):
                module, _selector_dynamic, arguments = _parse_python_invocation(
                    words[1:],
                    launcher=False,
                )
                if module is not None or _selector_dynamic:
                    records.append((module, True, arguments))
            continue
        launcher, executable_dynamic, manager = kind
        arguments = words[1:]
        explicit_exec = manager or (
            launcher
            and arguments
            and _decode_static_shell_word(arguments[0])[0].lower() == "exec"
        )
        if explicit_exec:
            if not arguments:
                continue
            if arguments[0].startswith("@"):
                records.append((None, True, ()))
                continue
            subcommand, subcommand_dynamic = _decode_static_shell_word(arguments[0])
            if subcommand_dynamic:
                records.append((None, True, ()))
                continue
            if subcommand.lower() != "exec":
                continue
            arguments = arguments[1:]
            arguments, manager_dynamic, manager_terminal = (
                _consume_manager_exec_options(arguments)
            )
            if manager_dynamic:
                records.append((None, True, ()))
                continue
            if manager_terminal:
                continue
        module, selector_dynamic, arguments = _parse_python_invocation(
            arguments,
            launcher=launcher,
        )
        records.append(
            (module, executable_dynamic or selector_dynamic, arguments)
        )
    return records


def _python_dynamic_selector(command: str) -> bool:
    return any(dynamic for _module, dynamic, _arguments in _python_module_records(command))


def _python_heavy_module(command: str) -> bool:
    return any(
        module is not None and _module_name_is_heavy(module)
        for module, _dynamic, _arguments in _python_module_records(command)
    )


def _pytest_has_explicit_test_target(arguments: tuple[str, ...]) -> bool:
    no_value_options = {
        "-q",
        "--quiet",
        "-v",
        "--verbose",
        "-s",
        "-x",
        "--exitfirst",
        "--collect-only",
        "--co",
        "--strict-config",
        "--strict-markers",
        "--disable-warnings",
        "--showlocals",
        "--no-showlocals",
        "--full-trace",
        "--lf",
        "--last-failed",
        "--ff",
        "--failed-first",
        "--nf",
        "--new-first",
        "--sw",
        "--stepwise",
        "--stepwise-skip",
        "--cache-clear",
    }
    target = re.compile(
        r"(?i)(?:\A|[\\/])test_[A-Za-z0-9_.-]+\.py(?:::.+)?\Z"
    )
    consume_next = False
    positional_only = False
    target_count = 0
    for raw_argument in arguments:
        argument, dynamic = _decode_static_shell_word(raw_argument)
        canonical = raw_argument == argument or _whole_quoted_word(raw_argument)
        if consume_next:
            consume_next = False
            continue
        if dynamic or not canonical:
            return False
        if positional_only:
            if target.search(argument):
                target_count += 1
                continue
            return False
        if argument == "--":
            positional_only = True
            continue
        if argument.startswith("--"):
            if "=" not in argument and argument not in no_value_options:
                consume_next = True
            continue
        if argument.startswith("-"):
            if argument in no_value_options:
                continue
            if re.fullmatch(r"-[qvsx]+", argument):
                continue
            if len(argument) == 2:
                consume_next = True
                continue
            short_cluster = argument[1:]
            value_position = next(
                (
                    index
                    for index, option in enumerate(short_cluster)
                    if option in "kmcoprWn"
                ),
                None,
            )
            if value_position is not None:
                consume_next = value_position == len(short_cluster) - 1
                continue
            return False
            continue
        if target.search(argument):
            target_count += 1
            continue
        return False
    return bool(not consume_next and 1 <= target_count <= 25)


def _pytest_executable_argument_records(
    command: str,
) -> list[tuple[str, ...]]:
    records: list[tuple[str, ...]] = []
    for segment in _iter_raw_command_segments(command):
        words = tuple(_iter_raw_shell_words(segment, 0))
        if not words:
            continue
        executable, dynamic = _decode_static_shell_word(words[0])
        basename = re.split(
            r"[\\/]", executable.strip(_POWERSHELL_COMMAND_NAME_TRIM)
        )[-1].lower()
        if dynamic:
            continue
        if re.fullmatch(r"(?:pytest|py\.test)(?:\.exe)?", basename):
            records.append(words[1:])
    return records


def _heavy_test_entrypoint(command: str) -> bool:
    for segment in _iter_raw_command_segments(command):
        words = tuple(_iter_raw_shell_words(segment, 0))
        if not words:
            continue
        executable, dynamic = _decode_static_shell_word(words[0])
        basename = re.split(
            r"[\\/]", executable.strip(_POWERSHELL_COMMAND_NAME_TRIM)
        )[-1].lower()
        if not dynamic and re.fullmatch(
            r"(?:coverage(?:3|-\d+(?:\.\d+)?)?|tox|nox)(?:\.exe)?",
            basename,
        ):
            return True
    return bool(_HEAVY_TEST_ENTRYPOINT.search(command))


def _python_unbounded_pytest(command: str) -> bool:
    direct = any(
        module in {"pytest", "pytest.__main__"}
        and not _pytest_has_explicit_test_target(arguments)
        for module, _dynamic, arguments in _python_module_records(command)
    )
    nested = any(
        not _pytest_has_explicit_test_target(arguments)
        for arguments in _nested_pytest_argument_records(command)
    )
    return direct or nested


def _coverage_run_start(arguments: tuple[str, ...]) -> tuple[int | None, bool]:
    for index, raw_word in enumerate(arguments):
        word, dynamic = _decode_static_shell_word(raw_word)
        if dynamic or raw_word.startswith("@"):
            return None, True
        if word.lower() == "run":
            return index + 1, False
    return None, False


def _long_option_prefixes(option: str, minimum: int) -> frozenset[str]:
    return frozenset(
        "--" + option[:length]
        for length in range(minimum, len(option) + 1)
    )


def _store_true_module_selector(
    arguments: tuple[str, ...],
    *,
    start: int,
    short_value_flags: str = "",
    long_value_options: frozenset[str] = frozenset(),
    long_module_options: frozenset[str] = frozenset(),
) -> tuple[str | None, bool, tuple[str, ...]] | None:
    """Parse wrappers whose module switch selects the first positional token."""

    module_mode = False
    index = start
    while index < len(arguments):
        raw_word = arguments[index]
        word, dynamic = _decode_static_shell_word(raw_word)
        if dynamic or raw_word.startswith("@"):
            return None, True, ()
        lowered = word.lower()
        if word == "--":
            index += 1
            break
        if word.startswith("--"):
            option_name, separator, _attached_value = lowered.partition("=")
            if option_name in long_module_options:
                if separator:
                    return None, True, ()
                module_mode = True
                index += 1
                continue
            if option_name in long_value_options and not separator:
                if index + 1 >= len(arguments):
                    return None, True, ()
                _value, value_dynamic = _decode_static_shell_word(arguments[index + 1])
                if value_dynamic or arguments[index + 1].startswith("@"):
                    return None, True, ()
                index += 2
                continue
            if option_name in {"--help", "--version"}:
                return None
            return None, True, ()
        if word.startswith("-") and len(word) > 1:
            flags = word[1:]
            consumed_separate_value = False
            for flag_index, short_flag in enumerate(flags):
                if short_flag == "m":
                    module_mode = True
                    continue
                if short_flag in short_value_flags:
                    if flag_index + 1 == len(flags):
                        if index + 1 >= len(arguments):
                            return None, True, ()
                        _value, value_dynamic = _decode_static_shell_word(
                            arguments[index + 1]
                        )
                        if value_dynamic or arguments[index + 1].startswith("@"):
                            return None, True, ()
                        consumed_separate_value = True
                    break
            index += 2 if consumed_separate_value else 1
            continue
        break
    if not module_mode or index >= len(arguments):
        return None
    module, module_dynamic = _decode_module_word(arguments[index])
    return module, module_dynamic, arguments[index + 1 :]


_NESTED_MODULE_WRAPPERS = frozenset(
    {"cprofile", "profile", "pdb", "trace", "coverage", "coverage.__main__"}
)


def _wrapper_module_selection(
    module: str,
    arguments: tuple[str, ...],
) -> tuple[str | None, bool, tuple[str, ...]] | None:
    start = 0
    if module in {"coverage", "coverage.__main__"}:
        start, dynamic = _coverage_run_start(arguments)
        if dynamic:
            return None, True, ()
        if start is None:
            return None
    if module in {"cprofile", "profile"}:
        return _store_true_module_selector(
            arguments,
            start=start,
            short_value_flags="os",
            long_value_options=(
                _long_option_prefixes("outfile", 3)
                | _long_option_prefixes("sort", 1)
            ),
            long_module_options=frozenset(
                "--" + "module"[:length] for length in range(1, 7)
            ),
        )
    if module == "pdb":
        return _store_true_module_selector(
            arguments,
            start=start,
            short_value_flags="c",
            long_value_options=_long_option_prefixes("command", 1),
        )
    if module == "trace":
        return _store_true_module_selector(
            arguments,
            start=start,
            short_value_flags="fC",
            long_value_options=frozenset(
                set(_long_option_prefixes("file", 1))
                | set(_long_option_prefixes("coverdir", 1))
                | set(_long_option_prefixes("ignore-module", 8))
                | set(_long_option_prefixes("ignore-dir", 8))
            ),
            long_module_options=frozenset(
                "--" + "module"[:length] for length in range(2, 7)
            ),
        )
    return _store_true_module_selector(
        arguments,
        start=start,
        long_value_options=frozenset(
            set(_long_option_prefixes("concurrency", 4))
            | set(_long_option_prefixes("context", 4))
            | set(_long_option_prefixes("data-file", 2))
            | set(_long_option_prefixes("debug", 2))
            | set(_long_option_prefixes("include", 1))
            | set(_long_option_prefixes("omit", 1))
            | set(_long_option_prefixes("rcfile", 1))
            | set(_long_option_prefixes("source", 1))
        ),
        long_module_options=frozenset(
            "--" + "module"[:length] for length in range(1, 7)
        ),
    )


def _pytest_arguments_through_wrapper(
    module: str,
    arguments: tuple[str, ...],
    *,
    depth: int = 0,
) -> list[tuple[str, ...]]:
    if depth >= 4:
        return [()]
    selected = _wrapper_module_selection(module, arguments)
    if selected is None:
        return []
    nested_module, dynamic, nested_arguments = selected
    if dynamic:
        return [()]
    if nested_module in {"pytest", "pytest.__main__"}:
        return [nested_arguments]
    if nested_module in _NESTED_MODULE_WRAPPERS:
        return _pytest_arguments_through_wrapper(
            nested_module,
            nested_arguments,
            depth=depth + 1,
        )
    return []


def _nested_pytest_argument_records(command: str) -> list[tuple[str, ...]]:
    """Find pytest launched through nested profiler/debugger/coverage chains."""

    records: list[tuple[str, ...]] = []
    for module, selector_dynamic, arguments in _python_module_records(command):
        if module not in _NESTED_MODULE_WRAPPERS:
            continue
        if selector_dynamic:
            records.append(())
        else:
            records.extend(_pytest_arguments_through_wrapper(module, arguments))

    for segment in _iter_raw_command_segments(command):
        words = tuple(_iter_raw_shell_words(segment, 0))
        if not words:
            continue
        executable, dynamic = _decode_static_shell_word(words[0])
        basename = re.split(
            r"[\\/]", executable.strip(_POWERSHELL_COMMAND_NAME_TRIM)
        )[-1].lower()
        if dynamic or re.fullmatch(
            r"coverage(?:3|-\d+(?:\.\d+)?)?(?:\.exe)?",
            basename,
        ) is None:
            continue
        records.extend(_pytest_arguments_through_wrapper("coverage", words[1:]))
    return records


def _decode_attached_module_argument(
    argument: str,
    *,
    single_quoted_literal_is_static: bool,
) -> tuple[str | None, bool]:
    quote = argument[0] if argument[0] in {"'", '"'} else None
    token = argument[1:-1] if quote is not None else argument
    clustered = _CLUSTERED_MODULE_TOKEN.fullmatch(token)
    if clustered is None:
        return None, True
    module = clustered.group("module")
    if _STATIC_MODULE_ARGUMENT.fullmatch(module) is not None:
        return module.lower(), False
    if quote == "'" and single_quoted_literal_is_static:
        return None, False
    return None, True


def _attached_module_records(
    command: str,
    *,
    loose: bool = False,
) -> list[tuple[str | None, bool]]:
    pattern = _LOOSE_ATTACHED_MODULE if loose else _ATTACHED_PYTHON_MODULE
    return [
        _decode_attached_module_argument(
            match.group("argument"),
            single_quoted_literal_is_static=not loose,
        )
        for match in pattern.finditer(command)
    ]


def _clustered_switch_module_records(
    command: str,
    *,
    loose: bool = False,
) -> list[tuple[str | None, bool]]:
    """Decode ``-<flags>m`` whether its module is attached or follows it."""

    pattern = (
        _LOOSE_CLUSTERED_MODULE_SWITCH
        if loose
        else _CLUSTERED_PYTHON_MODULE_SWITCH
    )
    return [
        _decode_module_argument_at(
            command,
            match.end(),
            single_quoted_literal_is_static=not loose,
        )
        for match in pattern.finditer(command)
    ]


def _module_name_is_heavy(module: str) -> bool:
    return bool(
        module
        in {
            "pytest",
            "pytest.__main__",
            "compileall",
            "coverage",
            "coverage.__main__",
            "tox",
            "tox.__main__",
            "nox",
            "nox.__main__",
            "cprofile",
            "profile",
            "pdb",
            "trace",
        }
        or module in _OFFLINE_WEATHER_MODULES
        or _HEURISTIC_HEAVY_WEATHER_NAME.fullmatch(module)
    )


def _attached_heavy_module(command: str, *, loose: bool = False) -> bool:
    return any(
        module is not None and _module_name_is_heavy(module)
        for module, _dynamic in _attached_module_records(command, loose=loose)
    )


def _attached_dynamic_module(command: str, *, loose: bool = False) -> bool:
    return any(
        dynamic
        for _module, dynamic in _attached_module_records(command, loose=loose)
    )


def _clustered_switch_heavy_module(command: str, *, loose: bool = False) -> bool:
    return any(
        module is not None and _module_name_is_heavy(module)
        for module, _dynamic in _clustered_switch_module_records(
            command,
            loose=loose,
        )
    )


def _clustered_switch_dynamic_module(command: str, *, loose: bool = False) -> bool:
    return any(
        dynamic
        for _module, dynamic in _clustered_switch_module_records(
            command,
            loose=loose,
        )
    )


def _clustered_switch_pytest(command: str) -> bool:
    return any(
        module == "pytest"
        for module, _dynamic in _clustered_switch_module_records(command)
    )


def _attached_pytest(command: str) -> bool:
    return any(
        module == "pytest"
        for module, _dynamic in _attached_module_records(command)
    )


def _unbounded_pytest(command: str) -> bool:
    executable_unbounded = any(
        not _pytest_has_explicit_test_target(arguments)
        for arguments in _pytest_executable_argument_records(command)
    )
    return executable_unbounded or _python_unbounded_pytest(command)


def _decode_module_argument_at(
    command: str,
    start: int,
    *,
    single_quoted_literal_is_static: bool,
) -> tuple[str | None, bool]:
    """Reject any ``-m`` argument that is not one canonical static token."""

    cursor = start
    while cursor < len(command) and command[cursor].isspace():
        cursor += 1
    if cursor >= len(command):
        return None, True

    quote = command[cursor] if command[cursor] in {"'", '"'} else None
    if quote is not None:
        closing = command.find(quote, cursor + 1)
        if closing < 0:
            return None, True
        content = command[cursor + 1 : closing]
        following = command[closing + 1 : closing + 2]
        if following and not (
            following.isspace() or following in ";&|{}()"
        ):
            return None, True
        if quote == "'" and single_quoted_literal_is_static:
            if _STATIC_MODULE_ARGUMENT.fullmatch(content) is not None:
                return content.lower(), False
            return None, False
        if _STATIC_MODULE_ARGUMENT.fullmatch(content) is not None:
            return content.lower(), False
        return None, True

    delimiters = " \t\r\n;&|{}()"
    end = cursor
    while end < len(command) and command[end] not in delimiters:
        end += 1
    token = command[cursor:end]
    if not token:
        return None, True
    if end < len(command) and command[end] in "{(":
        return None, True
    if _STATIC_MODULE_ARGUMENT.fullmatch(token) is not None:
        return token.lower(), False
    return None, True


def _module_argument_is_dynamic(
    command: str,
    start: int,
    *,
    single_quoted_literal_is_static: bool,
) -> bool:
    return _decode_module_argument_at(
        command,
        start,
        single_quoted_literal_is_static=single_quoted_literal_is_static,
    )[1]


def _quoted_switch_module_records(
    command: str,
    *,
    loose: bool = False,
) -> list[tuple[str | None, bool]]:
    pattern = (
        _LOOSE_QUOTED_MODULE_SWITCH if loose else _QUOTED_PYTHON_MODULE_SWITCH
    )
    return [
        _decode_module_argument_at(
            command,
            match.end(),
            single_quoted_literal_is_static=not loose,
        )
        for match in pattern.finditer(command)
    ]


def _quoted_switch_heavy_module(command: str, *, loose: bool = False) -> bool:
    return any(
        module is not None and _module_name_is_heavy(module)
        for module, _dynamic in _quoted_switch_module_records(
            command,
            loose=loose,
        )
    )


def _quoted_switch_dynamic_module(command: str, *, loose: bool = False) -> bool:
    return any(
        dynamic
        for _module, dynamic in _quoted_switch_module_records(
            command,
            loose=loose,
        )
    )


def _quoted_switch_pytest(command: str) -> bool:
    return any(
        module == "pytest"
        for module, _dynamic in _quoted_switch_module_records(command)
    )


def _dynamic_python_module(command: str) -> bool:
    return any(
        _module_argument_is_dynamic(
            command,
            match.end(),
            single_quoted_literal_is_static=True,
        )
        for match in _PYTHON_MODULE_SWITCH.finditer(command)
    )


def _loose_dynamic_module(command: str) -> bool:
    separated = any(
        _module_argument_is_dynamic(
            command,
            match.end(),
            single_quoted_literal_is_static=False,
        )
        for match in _LOOSE_MODULE_SWITCH.finditer(command)
    )
    return bool(
        separated
        or _attached_dynamic_module(command, loose=True)
        or _clustered_switch_dynamic_module(command, loose=True)
        or _quoted_switch_dynamic_module(command, loose=True)
    )


def _loose_nested_host_load_command(command: str) -> bool:
    """Recognize heavy payload syntax only after a nested launcher is proven."""

    if "workstation_heavy.ps1" in command.lower():
        return True
    if _attached_heavy_module(command, loose=True):
        return True
    if _clustered_switch_heavy_module(command, loose=True):
        return True
    if _quoted_switch_heavy_module(command, loose=True):
        return True
    if _LOOSE_TEST_EXECUTABLE.search(command):
        return True
    return bool(
        _LOOSE_PYTEST_MODULE.search(command)
        or _LOOSE_COMPILEALL_MODULE.search(command)
        or _loose_dynamic_module(command)
        or _LOOSE_ALLOWLISTED_WEATHER_MODULE.search(command)
        or _LOOSE_HEAVY_WEATHER_MODULE.search(command)
    )


def _strip_nested_command_quotes(command: str) -> str:
    stripped = command.strip()
    opening_quote = _quote_class(stripped[0]) if stripped else None
    if (
        len(stripped) >= 2
        and opening_quote is not None
        and _quote_class(stripped[-1]) == opening_quote
    ):
        return stripped[1:-1].strip()
    return stripped


def _powershell_encoded_command(arguments: str) -> bool:
    return bool(
        re.search(
            r"(?is)(?:\A|[\s,:;'\"\u2018\u2019\u201c\u201d])"
            r"(?:--|[-/\u2013\u2014\u2015\u2212])(?:"
            + "|".join(_POWERSHELL_ENCODED_SWITCHES)
            + r")(?=[\s,:;'\"\u2018\u2019\u201c\u201d]|\Z)",
            arguments,
        )
    )


def _powershell_nested_payload(arguments: str) -> tuple[bool, str | None]:
    if arguments.lstrip().startswith(("(", "$(", "@(")):
        return True, None
    records = tuple(_iter_raw_shell_word_records(arguments, 0))
    for index, (raw_word, _start, end) in enumerate(records):
        word, dynamic = _decode_static_shell_word(raw_word)
        if word.startswith(("\u2013", "\u2014", "\u2015", "\u2212")):
            word = "-" + word[1:]
        if dynamic and (
            word.startswith(("-", "/"))
            or raw_word.lstrip("'\"").startswith(
                ("-", "/", "$", "\u2013", "\u2014", "\u2015", "\u2212")
            )
        ):
            return True, None
        if dynamic:
            continue
        if word.startswith("--"):
            switch = word[2:]
        elif word.startswith(("-", "/")):
            switch = word[1:]
        else:
            continue
        switch_name, colon, attached = switch.partition(":")
        switch_name = switch_name.lower()
        if switch_name in _POWERSHELL_ENCODED_SWITCHES:
            return True, None
        if switch_name in _POWERSHELL_COMMAND_SWITCHES:
            remainder = arguments[end:].strip()
            payload = attached if colon else remainder
            if colon and remainder:
                payload = payload + " " + remainder
            if payload.strip() == "-":
                return True, None
            return False, payload
        if switch_name in _POWERSHELL_FILE_SWITCHES:
            candidate = attached if colon else ""
            if not colon and index + 1 < len(records):
                candidate, candidate_dynamic = _decode_static_shell_word(
                    records[index + 1][0]
                )
                if candidate_dynamic:
                    return True, None
            if candidate.strip() == "-":
                return True, None
    return False, None


def _powershell_launch_argument_records(
    arguments: str,
) -> tuple[tuple[tuple[str, int, int], ...], int]:
    """Tokenize one PowerShell invocation without splitting expressions."""

    records: list[tuple[str, int, int]] = []
    cursor = 0
    command_end = len(arguments)
    matching = {"(": ")", "[": "]", "{": "}"}
    while cursor < len(arguments):
        while cursor < len(arguments) and arguments[cursor].isspace():
            cursor += 1
        if cursor >= len(arguments):
            break
        if arguments[cursor] in ";|&\r\n":
            command_end = cursor
            break
        start = cursor
        quote = None
        stack: list[str] = []
        while cursor < len(arguments):
            character = arguments[cursor]
            character_quote = _quote_class(character)
            if character == "`" and quote != "'":
                cursor = min(cursor + 2, len(arguments))
                continue
            if quote is not None:
                if character_quote == quote:
                    quote = None
                cursor += 1
                continue
            if character_quote is not None:
                quote = character_quote
                cursor += 1
                continue
            if character in matching:
                stack.append(matching[character])
                cursor += 1
                continue
            if stack and character == stack[-1]:
                stack.pop()
                cursor += 1
                continue
            if not stack and (
                character.isspace() or character in ";|&\r\n"
            ):
                break
            cursor += 1
        if cursor > start:
            records.append((arguments[start:cursor], start, cursor))
        if cursor < len(arguments) and arguments[cursor] in ";|&\r\n":
            command_end = cursor
            break
    return tuple(records), command_end


def _unquoted_parameter_colon(raw_word: str) -> int | None:
    quote = None
    cursor = 0
    while cursor < len(raw_word):
        character = raw_word[cursor]
        character_quote = _quote_class(character)
        if character == "`" and quote != "'":
            cursor += 2
            continue
        if quote is not None:
            if character_quote == quote:
                quote = None
            cursor += 1
            continue
        if character_quote is not None:
            quote = character_quote
        elif character == ":":
            return cursor
        elif character in "([{":
            return None
        cursor += 1
    return None


def _start_process_parameter(
    raw_word: str,
) -> tuple[str | None, bool, int | None]:
    lexical = raw_word.lstrip()
    if not lexical or lexical[0] not in {
        "-", "\u2013", "\u2014", "\u2015", "\u2212",
    }:
        return None, False, None
    decoded, dynamic = _decode_static_shell_word(raw_word)
    decoded = decoded.strip()
    if decoded.startswith(("\u2013", "\u2014", "\u2015", "\u2212")):
        decoded = "-" + decoded[1:]
    if decoded.startswith("--"):
        switch = decoded[2:]
    elif decoded.startswith("-"):
        switch = decoded[1:]
    else:
        return None, dynamic, None
    name = switch.partition(":")[0].lower()
    if name in _START_PROCESS_PARAMETER_ALIASES:
        return (
            _START_PROCESS_PARAMETER_ALIASES[name],
            dynamic,
            _unquoted_parameter_colon(raw_word),
        )
    if not name:
        return None, dynamic, None
    if name in _START_PROCESS_PARAMETERS:
        return name, dynamic, _unquoted_parameter_colon(raw_word)
    matches = {
        candidate
        for candidate in _START_PROCESS_PARAMETERS
        if candidate.startswith(name)
    }
    matches.update(
        canonical
        for alias, canonical in _START_PROCESS_PARAMETER_ALIASES.items()
        if alias.startswith(name)
    )
    if len(matches) != 1:
        return None, dynamic, None
    return next(iter(matches)), dynamic, _unquoted_parameter_colon(raw_word)


def _whole_static_powershell_string(value: str) -> bool:
    quote = _quote_class(value[0]) if value else None
    if quote is None:
        return False
    cursor = 1
    while cursor < len(value):
        character_quote = _quote_class(value[cursor])
        if character_quote != quote:
            cursor += 1
            continue
        if (
            quote == "'"
            and cursor + 1 < len(value)
            and _quote_class(value[cursor + 1]) == quote
        ):
            cursor += 2
            continue
        return cursor == len(value) - 1
    return False


def _powershell_argument_value_is_dynamic(value: str) -> bool:
    """Accept only plainly static scalar/array syntax for a launch value."""

    quote = None
    cursor = 0
    atom_start = 0
    atoms: list[str] = []
    while cursor < len(value):
        character = value[cursor]
        character_quote = _quote_class(character)
        if quote == "'":
            if character_quote == quote:
                quote = None
            cursor += 1
            continue
        if quote == '"':
            if character in {"`", "$"}:
                return True
            if character_quote == quote:
                quote = None
            cursor += 1
            continue
        if character_quote is not None:
            quote = character_quote
            cursor += 1
            continue
        if character in {"`", "$", "(", ")", "[", "]", "{", "}", "+"}:
            return True
        if character == "@" and (
            cursor == atom_start or value[atom_start:cursor].strip() == ""
        ):
            return True
        if character.isspace() or character == ",":
            atom = value[atom_start:cursor].strip()
            if atom:
                atoms.append(atom)
            atom_start = cursor + 1
        cursor += 1
    if quote is not None:
        return True
    atom = value[atom_start:].strip()
    if atom:
        atoms.append(atom)
    expression_operator = re.compile(
        r"(?i)\A-(?:as|band|bnot|bor|bxor|contains|eq|f|ge|gt|in|is|"
        r"isnot|join|le|like|lt|match|ne|notcontains|notin|notlike|"
        r"notmatch|replace|shl|shr|split)\Z"
    )
    for atom in atoms:
        _decoded, dynamic = _decode_static_shell_word(atom)
        if dynamic:
            return True
        contains_quote = any(_quote_class(character) for character in atom)
        if contains_quote and not _whole_static_powershell_string(atom):
            return True
        if not contains_quote and expression_operator.fullmatch(atom):
            return True
    return False


def _start_process_child_shell_is_opaque(
    file_value: str | None,
    argument_value: str | None,
) -> bool:
    """Re-evaluate static values after PowerShell removes their outer quotes."""

    if file_value is None or argument_value is None:
        return False
    decoded_file, file_dynamic = _decode_static_shell_word(file_value)
    decoded_arguments, arguments_dynamic = _decode_static_shell_word(
        argument_value
    )
    if file_dynamic or arguments_dynamic:
        return True
    basename = re.split(
        r"[\\/]", decoded_file.strip(_POWERSHELL_COMMAND_NAME_TRIM)
    )[-1].lower()
    if basename in {"cmd", "cmd.exe"}:
        normalized_arguments = decoded_arguments.replace(",", " ")
        command_selected = re.search(
            r"(?is)(?:\A|\s)(?:/[^\s/]*)*?/[ckr].*\Z",
            normalized_arguments,
        )
        return bool(
            command_selected
            and (
                re.search(r"[%!^]", decoded_arguments)
                or _loose_nested_host_load_command(decoded_arguments)
            )
        )
    if basename in {"bash", "bash.exe", "sh", "sh.exe"}:
        command_selected = re.search(
            r"(?i)(?:\A|[\s,])-[a-z]*c(?=[\s,]|\Z)",
            decoded_arguments,
        )
        return bool(
            command_selected
            and (
                re.search(r"[$`\\]", decoded_arguments)
                or _loose_nested_host_load_command(decoded_arguments)
            )
        )
    if basename in {"powershell", "powershell.exe", "pwsh", "pwsh.exe"}:
        command_selected = re.search(
            r"(?i)(?:\A|[\s,])(?:--|[-/\u2013\u2014\u2015\u2212])(?:"
            + "|".join(_POWERSHELL_COMMAND_SWITCHES)
            + r")(?=[\s,:;,]|\Z)",
            decoded_arguments,
        )
        return bool(
            command_selected
            and (
                re.search(r"[$`()@+{}\[\]]", decoded_arguments)
                or _loose_nested_host_load_command(decoded_arguments)
            )
        )
    return False


def _dynamic_process_argument_list(arguments: str) -> bool:
    """Reject opaque FilePath/ArgumentList binding for ``Start-Process``."""

    records, command_end = _powershell_launch_argument_records(arguments)
    parsed = tuple(_start_process_parameter(record[0]) for record in records)
    consumed: set[int] = set()
    named_argument_list = False
    named_file_path = False
    file_value: str | None = None
    argument_value: str | None = None
    index = 0
    while index < len(records):
        raw_word, word_start, word_end = records[index]
        stripped = raw_word.lstrip()
        if index not in consumed and stripped.startswith("@"):
            return True
        parameter, parameter_dynamic, colon = parsed[index]
        if parameter_dynamic and stripped.startswith(
            ("-", "\u2013", "\u2014", "\u2015", "\u2212")
        ):
            return True
        if parameter == "argumentlist":
            next_index = index + 1
            while (
                next_index < len(records)
                and parsed[next_index][0] is None
            ):
                next_index += 1
            value_start = word_start + colon + 1 if colon is not None else word_end
            value_end = (
                records[next_index][1]
                if next_index < len(records)
                else command_end
            )
            observed_argument_value = arguments[value_start:value_end]
            if _powershell_argument_value_is_dynamic(observed_argument_value):
                return True
            argument_value = observed_argument_value
            consumed.update(range(index, next_index))
            named_argument_list = True
            index = next_index
            continue
        if parameter == "filepath":
            if colon is not None and colon + 1 < len(raw_word):
                file_value = raw_word[colon + 1 :]
            elif index + 1 < len(records):
                file_value = records[index + 1][0]
                consumed.add(index + 1)
            else:
                file_value = ""
            if _powershell_argument_value_is_dynamic(file_value):
                return True
            consumed.add(index)
            named_file_path = True
            index += 1
            continue
        if parameter is not None:
            consumed.add(index)
            if (
                parameter in _START_PROCESS_VALUE_PARAMETERS
                and colon is None
                and index + 1 < len(records)
            ):
                consumed.add(index + 1)
            index += 1
            continue

        index += 1

    positional = [
        candidate
        for candidate in range(len(records))
        if candidate not in consumed and parsed[candidate][0] is None
    ]
    if not named_file_path and positional:
        file_index = positional.pop(0)
        file_value = records[file_index][0]
        if _powershell_argument_value_is_dynamic(file_value):
            return True
    if not named_argument_list and positional:
        argument_index = positional[0]
        value_end = command_end
        for candidate in range(argument_index + 1, len(records)):
            if parsed[candidate][0] is not None:
                value_end = records[candidate][1]
                break
        argument_value = arguments[records[argument_index][1]:value_end]
        if _powershell_argument_value_is_dynamic(argument_value):
            return True
    return _start_process_child_shell_is_opaque(
        file_value,
        argument_value,
    )


def _cmd_nested_payload(arguments: str) -> tuple[bool, str | None]:
    decoded, dynamic = _decode_static_shell_word(arguments)
    flag = re.search(
        r"(?is)(?:\A|\s)(?:/[^\s/]*)*?/[ckr](.*)\Z",
        decoded,
    )
    if flag is not None:
        return False, flag.group(1)
    return dynamic and _loose_nested_host_load_command(arguments), None


def _posix_shell_nested_payload(arguments: str) -> tuple[bool, str | None]:
    for raw_word, _start, end in _iter_raw_shell_word_records(arguments, 0):
        word, dynamic = _decode_static_shell_word(raw_word)
        if dynamic and raw_word.lstrip("'\"").startswith("-"):
            return True, None
        if dynamic or not word.startswith("-"):
            continue
        command_option = re.fullmatch(r"(?is)-[a-z]*?c(?P<attached>.*)", word)
        if command_option is None:
            continue
        attached = command_option.group("attached")
        remainder = arguments[end:].strip()
        payload = attached
        if payload and remainder:
            payload += " " + remainder
        elif not payload:
            payload = remainder
        return False, payload
    return False, None


def _process_call_argument_tails(command: str):
    """Yield arguments after static or opaque PowerShell process calls."""

    quote = None
    cursor = 0
    while cursor < len(command):
        character = command[cursor]
        character_quote = _quote_class(character)
        if character == "`" and quote != "'":
            cursor += 2
            continue
        if quote is not None:
            if character_quote == quote:
                quote = None
            cursor += 1
            continue
        if character_quote is not None:
            quote = character_quote
            cursor += 1
            continue
        ampersand = character == "&" and not (
            cursor + 1 < len(command) and command[cursor + 1] == "&"
        )
        dot = character == "." and (
            cursor + 1 < len(command) and command[cursor + 1].isspace()
        )
        if dot:
            previous = cursor - 1
            while (
                previous >= 0
                and command[previous].isspace()
                and command[previous] not in "\r\n"
            ):
                previous -= 1
            dot = previous < 0 or command[previous] in ";|&\r\n{}("
        if not ampersand and not dot:
            cursor += 1
            continue
        target = cursor + 1
        while target < len(command) and command[target].isspace():
            target += 1
        if target >= len(command):
            return
        records, _command_end = _powershell_launch_argument_records(
            command[target:]
        )
        if not records:
            return
        raw_target, _target_start, target_end = records[0]
        decoded_target, target_dynamic = _decode_static_shell_word(raw_target)
        target_name = re.split(
            r"[\\/]", decoded_target.strip(_POWERSHELL_COMMAND_NAME_TRIM)
        )[-1].lower()
        opaque_target = target_dynamic or raw_target.lstrip().startswith(
            ("$", "(")
        )
        process_target = target_name in {"start-process", "start", "saps"}
        supported_target = process_target or target_name in {
            "start-job", "start-threadjob", "invoke-command",
            "invoke-expression", "iex", "powershell", "powershell.exe",
            "pwsh", "pwsh.exe", "cmd", "cmd.exe", "bash", "bash.exe",
            "sh", "sh.exe",
        }
        if not supported_target and not opaque_target:
            cursor += 1
            continue
        yield command[target + target_end :], process_target or opaque_target
        cursor = target + target_end


def _powershell_alias_mutation(command: str) -> bool:
    """Fail closed on command-local alias or function launcher changes."""

    normalized_command = command.replace("`", "")
    direct_launcher_assignment = re.compile(
        r"(?i)\A\s*(?:\$(?:alias|function):[A-Za-z_][A-Za-z0-9_.-]*|"
        r"\$\{(?:alias|function):[^}\r\n]+\})\s*="
    )
    if any(
        direct_launcher_assignment.search(segment) is not None
        for segment in _iter_raw_command_segments(command)
    ):
        return True
    for segment in _iter_raw_command_segments(command):
        words = tuple(_iter_raw_shell_words(segment, 0))
        if len(words) < 2:
            continue
        decoded_keyword, keyword_dynamic = _decode_static_shell_word(
            words[0].replace("`", "")
        )
        if not keyword_dynamic and decoded_keyword.lower() in {"filter", "function"}:
            return True
    if re.search(r"(?i)(?:set|new)-alias", normalized_command) and re.search(
        r"(?s)(?:&|(?:\A|[;|\r\n{}])\s*\.)\s*(?:\$|\()",
        command,
    ):
        return True
    launcher_provider_mentioned = any(
        re.search(r"(?i)(?:alias|function)\s*:", decoded_word) is not None
        for segment in _iter_raw_command_segments(command)
        for raw_word in _iter_raw_shell_words(segment, 0)
        for decoded_word, _dynamic in (
            _decode_static_shell_word(raw_word.replace("`", "")),
        )
    )
    location_commands = {
        "cd", "chdir", "pop-location", "popd", "push-location", "pushd",
        "set-location", "sl",
    }
    opaque_provider_invocation = re.search(
        r"(?s)(?:\A|[;&|\r\n{}])\s*(?:&|\.)\s*(?:\$|\()",
        command,
    ) is not None
    dynamic_provider_context = opaque_provider_invocation
    for segment, segment_start, _segment_end in _iter_raw_command_segment_records(
        command
    ):
        words = tuple(_iter_raw_shell_words(segment, 0))
        if words and words[0] == ".":
            words = words[1:]
        if not words:
            continue
        raw_location = words[0].replace("`", "")
        decoded_location, _dynamic = _decode_static_shell_word(raw_location)
        location_name = re.split(
            r"[\\/]",
            decoded_location.strip(_POWERSHELL_COMMAND_NAME_TRIM),
        )[-1].lower()
        if location_name not in location_commands:
            continue
        if _segment_consumes_pipeline_stdin(command, segment_start):
            dynamic_provider_context = True
            break
        if location_name in {"pop-location", "popd"}:
            dynamic_provider_context = True
            break
        if (
            _segment_end < len(command)
            and command[_segment_end] in "({"
        ):
            dynamic_provider_context = True
            break
        for raw_argument in words[1:]:
            normalized_argument = raw_argument.replace("`", "")
            decoded_argument, argument_dynamic = _decode_static_shell_word(
                normalized_argument
            )
            if (
                argument_dynamic
                or raw_argument.startswith("@")
                or re.search(r"[*?\[]", decoded_argument)
                or decoded_argument.lower().startswith("-stackname")
                or decoded_argument == "-"
            ):
                dynamic_provider_context = True
                break
        if dynamic_provider_context:
            break
    if launcher_provider_mentioned and opaque_provider_invocation:
        return True
    provider_mutators = {
        "add-content", "ac", "clear-content", "clear-item", "clc", "cli",
        "copy", "copy-item", "cp", "cpi", "del", "erase", "import-alias",
        "ipal", "move", "move-item", "mi", "mv", "new-item", "ni", "rd",
        "remove-item", "rename-item", "ren", "ri", "rm", "rmdir", "rni",
        "set-content", "sc", "set-item", "si",
    }
    for segment, segment_start, _segment_end in _iter_raw_command_segment_records(
        command
    ):
        words = tuple(_iter_raw_shell_words(segment, 0))
        if words and words[0] == ".":
            words = words[1:]
        if not words:
            continue
        raw_command = words[0].replace("`", "")
        decoded_command, _dynamic = _decode_static_shell_word(raw_command)
        command_name = re.split(
            r"[\\/]", decoded_command.strip(_POWERSHELL_COMMAND_NAME_TRIM)
        )[-1].lower()
        if command_name in {"set-alias", "new-alias", "sal", "nal"}:
            return True
        if command_name not in provider_mutators:
            continue
        if _segment_consumes_pipeline_stdin(command, segment_start):
            explicit_static_path = False
            if len(words) > 1:
                first_argument, first_dynamic = _decode_static_shell_word(
                    words[1].replace("`", "")
                )
                explicit_static_path = bool(
                    not first_dynamic
                    and not words[1].startswith("@")
                    and not first_argument.startswith("-")
                )
            for index, raw_argument in enumerate(words[1:], start=1):
                decoded_argument, argument_dynamic = _decode_static_shell_word(
                    raw_argument.replace("`", "")
                )
                path_option = re.fullmatch(
                    r"(?i)-(?:path|literalpath)(?::(.*))?",
                    decoded_argument,
                )
                if path_option is None:
                    continue
                attached_path = path_option.group(1)
                if attached_path:
                    explicit_static_path = not argument_dynamic
                elif index + 1 < len(words):
                    _path, path_dynamic = _decode_static_shell_word(
                        words[index + 1].replace("`", "")
                    )
                    explicit_static_path = bool(
                        not path_dynamic and not words[index + 1].startswith("@")
                    )
                break
            if not explicit_static_path:
                return True
        if command_name in {"import-alias", "ipal"}:
            return True
        if launcher_provider_mentioned or dynamic_provider_context:
            return True
        if re.search(r"[$@()+`]", segment):
            return True
    return False


def _nested_host_load_command(command: str, *, depth: int = 0) -> bool:
    """Detect heavy work hidden behind a shell or process-launch surface."""

    if depth >= 4:
        return True
    executable_skeleton = _powershell_executable_skeleton(command)
    normalized_command = executable_skeleton.replace("`", "")
    opaque_create_receiver = False
    opaque_dynamic_member_call = False
    for segment, _segment_start, segment_end in _iter_raw_command_segment_records(
        command
    ):
        for raw_word in _iter_raw_shell_words(segment, 0):
            decoded_word, _dynamic_word = _decode_static_shell_word(
                raw_word.replace("`", "")
            )
            if _whole_powershell_string_literal(raw_word):
                continue
            create_member = re.search(r"(?i)::\s*create\Z", decoded_word)
            if create_member:
                receiver = decoded_word[: create_member.start()].strip()
                if (
                    _dynamic_word
                    or not receiver
                    or re.fullmatch(r"\[[A-Za-z_][A-Za-z0-9_.]*\]", receiver)
                    is None
                ):
                    opaque_create_receiver = True
            if "::" in decoded_word and (
                _dynamic_word
                or re.search(r"::\s*[$@(]", raw_word)
                or (
                    decoded_word.rstrip().endswith("::")
                    and segment_end < len(command)
                    and command[segment_end] == "("
                )
            ):
                receiver, _separator, member = decoded_word.rpartition("::")
                receiver_is_static_type = re.fullmatch(
                    r"\[[A-Za-z_][A-Za-z0-9_.]*\]",
                    receiver.strip(),
                ) is not None
                member_is_static = re.fullmatch(
                    r"[A-Za-z_][A-Za-z0-9_]*",
                    member.strip(),
                ) is not None
                if not receiver_is_static_type and not member_is_static:
                    opaque_dynamic_member_call = True
            if re.search(
                r"(?i)\[\s*(?:system\.management\.automation\.)?"
                r"scriptblock\s*\]\s*::\s*create\Z",
                decoded_word,
            ):
                return True
    if opaque_create_receiver:
        return True
    if opaque_dynamic_member_call:
        return True
    # ScriptBlock.Create() and PowerShell.Create() are in-process command
    # executors whose payload can be opaque to this classifier. Correlate the
    # exact executable receiver with its static or dynamic member selector;
    # never combine an unrelated type mention with some other type's Create().
    if re.search(
        r"(?is)\[\s*(?:system\.management\.automation\.)?"
        r"(?:scriptblock|powershell)\s*\]\s*::\s*"
        r"(?:create\s*\(|\$|\()",
        normalized_command,
    ):
        return True
    # AddScript/AddCommand are the execution-bearing sinks even when the
    # PowerShell object came from reflection, New-Object, or an opaque factory.
    if _powershell_runspace_sink(command, executable_skeleton):
        return True
    if _powershell_alias_mutation(command):
        return True
    for dynamic_tail, process_target in _process_call_argument_tails(command):
        if (
            _loose_nested_host_load_command(dynamic_tail)
            or _powershell_encoded_command(dynamic_tail)
            or (
                process_target
                and _dynamic_process_argument_list(dynamic_tail)
            )
        ):
            return True
    for segment, segment_start, _segment_end in _iter_raw_command_segment_records(
        command
    ):
        word_records = tuple(_iter_raw_shell_word_records(segment, 0))
        if word_records and word_records[0][0] == ".":
            word_records = word_records[1:]
        words = tuple(record[0] for record in word_records)
        if word_records:
            launcher, launcher_dynamic = _decode_static_shell_word(word_records[0][0])
            launcher_is_assignment = re.match(
                r"\A\s*\$(?:\{[^}\r\n]+\}|[A-Za-z_][A-Za-z0-9_:.-]*)\s*=",
                segment,
            ) is not None
            launcher_name = re.split(
                r"[\\/]", launcher.strip(_POWERSHELL_COMMAND_NAME_TRIM)
            )[-1].lower()
            launcher_arguments = segment[word_records[0][2] :]
            full_launcher_arguments = command[
                segment_start + word_records[0][2] :
            ]
            if (
                launcher_name in {"invoke-expression", "iex"}
                and _segment_end < len(command)
                and command[_segment_end] in "({"
            ):
                return True
            if launcher_name in {"start-process", "start", "saps"} and (
                _loose_nested_host_load_command(launcher_arguments)
                or _powershell_encoded_command(launcher_arguments)
                or _dynamic_process_argument_list(full_launcher_arguments)
            ):
                return True
            if launcher_name in {
                "start-job", "start-threadjob", "invoke-command",
                "invoke-expression", "iex",
            } and (
                _loose_nested_host_load_command(launcher_arguments)
                or _powershell_encoded_command(launcher_arguments)
            ):
                return True
            if launcher_name in {"invoke-expression", "iex"}:
                if _segment_consumes_pipeline_stdin(command, segment_start):
                    return True
                payload_records = tuple(
                    _iter_raw_shell_word_records(launcher_arguments, 0)
                )
                if payload_records and payload_records[0][0].lower().startswith(
                    ("-c", "-command")
                ):
                    payload_records = payload_records[1:]
                if len(payload_records) != 1:
                    if launcher_arguments.strip():
                        return True
                else:
                    raw_payload = payload_records[0][0]
                    decoded_payload, payload_dynamic = _decode_static_shell_word(
                        raw_payload
                    )
                    if (
                        payload_dynamic
                        or raw_payload.startswith("@")
                        or _nested_host_load_command(
                            decoded_payload,
                            depth=depth + 1,
                        )
                    ):
                        return True
            if launcher_dynamic and not launcher_is_assignment and (
                _loose_nested_host_load_command(launcher_arguments)
                or _powershell_encoded_command(launcher_arguments)
                or _dynamic_process_argument_list(full_launcher_arguments)
            ):
                return True
        if words and _segment_consumes_pipeline_stdin(command, segment_start):
            pipeline_executable, pipeline_dynamic = _decode_static_shell_word(words[0])
            pipeline_basename = re.split(
                r"[\\/]", pipeline_executable.strip(_POWERSHELL_COMMAND_NAME_TRIM)
            )[-1].lower()
            if pipeline_basename in {
                "powershell", "powershell.exe", "pwsh", "pwsh.exe",
                "cmd", "cmd.exe", "bash", "bash.exe", "sh", "sh.exe",
            } or (pipeline_dynamic and words[0].lstrip().startswith("$")):
                return True
        if not word_records:
            continue
        raw_executable = word_records[0][0]
        executable, executable_dynamic = _decode_static_shell_word(raw_executable)
        basename = re.split(
            r"[\\/]", executable.strip(_POWERSHELL_COMMAND_NAME_TRIM)
        )[-1].lower()
        arguments = segment[word_records[0][2] :].lstrip()
        supported_shells = {
            "powershell", "powershell.exe", "pwsh", "pwsh.exe",
            "cmd", "cmd.exe", "bash", "bash.exe", "sh", "sh.exe",
        }
        if basename not in supported_shells:
            if executable_dynamic and not launcher_is_assignment and (
                _loose_nested_host_load_command(arguments)
                or _powershell_encoded_command(arguments)
            ):
                return True
            continue
        if _segment_end < len(command) and command[_segment_end] == "(":
            return True
        categorical = False
        payload = None
        if basename in {"powershell", "powershell.exe", "pwsh", "pwsh.exe"}:
            categorical, payload = _powershell_nested_payload(arguments)
        elif basename in {"cmd", "cmd.exe"}:
            categorical, payload = _cmd_nested_payload(arguments)
        elif basename in {"bash", "bash.exe", "sh", "sh.exe"}:
            categorical, payload = _posix_shell_nested_payload(arguments)
        if categorical:
            return True
        if payload is not None:
            payload = _strip_nested_command_quotes(payload)
            if (
                _direct_host_load_command(payload)
                or _loose_nested_host_load_command(payload)
                or _nested_host_load_command(payload, depth=depth + 1)
            ):
                return True

    for block in _POWERSHELL_SCRIPT_BLOCK.finditer(executable_skeleton):
        block_start, block_end = block.span("arguments")
        block_payload = command[block_start:block_end]
        if (
            _direct_host_load_command(block_payload)
            or _nested_host_load_command(block_payload, depth=depth + 1)
        ):
            return True
    for subexpression in _POWERSHELL_SUBEXPRESSION.finditer(executable_skeleton):
        subexpression_start, subexpression_end = subexpression.span("arguments")
        subexpression_payload = command[subexpression_start:subexpression_end]
        if (
            _direct_host_load_command(subexpression_payload)
            or _nested_host_load_command(
                subexpression_payload,
                depth=depth + 1,
            )
        ):
            return True
    return _dynamic_host_load_command(command)


def _dynamic_host_load_command(command: str) -> bool:
    dynamic_executable = any(
        _loose_nested_host_load_command(match.group("arguments"))
        or _powershell_encoded_command(match.group("arguments"))
        for pattern in (_VARIABLE_EXECUTION, _DYNAMIC_EXECUTION)
        for match in pattern.finditer(command)
    )
    return bool(
        dynamic_executable
        or _python_dynamic_selector(command)
    )


def _direct_host_load_command(command: str) -> bool:
    return bool(
        _forbidden_recursive_scan(command)
        or _pytest_executable_argument_records(command)
        or _python_heavy_module(command)
        or _heavy_test_entrypoint(command)
        or _WORKSTATION_WRAPPER_CALL.fullmatch(command)
        or "workstation_heavy.ps1" in command.lower()
        or _dynamic_host_load_command(command)
    )


def _recognized_host_load_command(command: str) -> bool:
    return _direct_host_load_command(command) or _nested_host_load_command(command)


def _stable_regular_file_sha256(path: Path) -> str:
    candidate = Path(os.path.abspath(os.fspath(path)))
    cursor = Path(candidate.anchor)
    for part in candidate.parts[1:]:
        cursor /= part
        entry = cursor.lstat()
        if cursor.is_symlink() or bool(
            getattr(entry, "st_file_attributes", 0) & _REPARSE_POINT
        ):
            raise ValueError("workstation wrapper closure is redirected")

    descriptor = os.open(candidate, os.O_RDONLY | getattr(os, "O_BINARY", 0))
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_size <= 0
            or opened.st_size > _MAX_WRAPPER_CLOSURE_BYTES
        ):
            raise ValueError("workstation wrapper closure is not a bounded file")
        digest = hashlib.sha256()
        remaining = opened.st_size
        while remaining:
            block = os.read(descriptor, min(8192, remaining))
            if not block:
                raise ValueError("workstation wrapper closure ended early")
            digest.update(block)
            remaining -= len(block)
        if os.read(descriptor, 1):
            raise ValueError("workstation wrapper closure grew while hashing")
        after_handle = os.fstat(descriptor)
        after_path = candidate.stat()
        if (
            not os.path.samestat(opened, after_handle)
            or not os.path.samestat(opened, after_path)
            or after_handle.st_size != opened.st_size
            or after_handle.st_mtime_ns != opened.st_mtime_ns
        ):
            raise ValueError("workstation wrapper closure changed while hashing")
        return digest.hexdigest()
    finally:
        os.close(descriptor)


def _approved_workstation_wrapper(command: str) -> bool:
    match = _WORKSTATION_WRAPPER_CALL.fullmatch(command)
    if match is None:
        return False
    python_path = Path(match.group("python"))
    repo_root = Path(match.group("repo_root"))
    if not python_path.is_absolute() or not repo_root.is_absolute():
        return False
    candidate_root = Path(os.path.abspath(repo_root))
    observed_script = os.path.normcase(os.path.abspath(match.group("script")))
    expected_script = os.path.normcase(
        os.path.abspath(candidate_root / _WORKSTATION_WRAPPER_CLOSURE[0])
    )
    if observed_script != expected_script:
        return False
    reference_root = WORKSTATION_WRAPPER_PATH.parents[2]
    try:
        if any(
            _stable_regular_file_sha256(candidate_root / relative)
            != _stable_regular_file_sha256(reference_root / relative)
            for relative in _WORKSTATION_WRAPPER_CLOSURE
        ):
            return False
    except (OSError, ValueError):
        return False
    try:
        encoded = match.group("arguments")
        raw = base64.b64decode(encoded, validate=True)
        if base64.b64encode(raw).decode("ascii") != encoded:
            return False
        arguments = json.loads(raw.decode("utf-8"))
    except (binascii.Error, UnicodeDecodeError, TypeError, ValueError):
        return False
    if (
        not isinstance(arguments, list)
        or not 2 <= len(arguments) <= 128
        or any(
            not isinstance(value, str)
            or len(value) > 4096
            or any(character in value for character in "\x00\r\n")
            for value in arguments
        )
        or arguments[0:1] != ["-m"]
    ):
        return False
    kind = match.group("kind").lower()
    module = arguments[1]
    if kind == "pytest":
        return module == "pytest"
    if kind == "compileall":
        return module == "compileall"
    return bool(
        module in _OFFLINE_WEATHER_MODULES
        and not any(_LIVE_ARGUMENT.fullmatch(value) for value in arguments[2:])
    )


def _deny(reason: str) -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def evaluate(
    payload: dict[str, Any],
    *,
    now: datetime | None = None,
    constrained_capture_host: bool | None = None,
) -> dict[str, Any] | None:
    """Return a Codex hook denial, or ``None`` when the call may proceed."""

    if payload.get("tool_name") != "Bash":
        return None
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return None
    command = tool_input.get("command")
    if not isinstance(command, str) or not command.strip():
        return None
    if constrained_capture_host is None and os.name != "nt":
        return None
    active = (
        _capture_host_policy_state()
        if constrained_capture_host is None
        else constrained_capture_host
    )
    if active is None:
        if _recognized_host_load_command(command):
            return _deny(
                "Cannot prove this Windows installation differs from the tracked "
                "dedicated capture host; recognized heavy work is blocked fail-closed."
            )
        return None
    if not active:
        if _recognized_host_load_command(command) and not _approved_workstation_wrapper(
            command
        ):
            return _deny(
                "On a non-capture workstation, recognized heavy work must use the "
                "repository-owned workstation_heavy.ps1 wrapper so it cannot overlap "
                "a portable live lease. The capture-host time window does not apply."
            )
        return None

    if "workstation_heavy.ps1" in command.lower():
        return _deny(
            "The workstation-heavy wrapper is forbidden on the tracked dedicated "
            "capture host; use the capture-host admitted workflow instead."
        )

    if _nested_host_load_command(command):
        return _deny(
            "Nested shell or process launchers may not start heavy work on the "
            "dedicated capture host; invoke the exact admitted command directly."
        )

    if _forbidden_recursive_scan(command):
        return _deny(
            "Recursive Get-ChildItem and broad scans of data/ are forbidden on the capture host; use rg or target a known file/bounded subtree."
        )
    if _unbounded_pytest(command):
        return _deny(
            "An unbounded pytest run is forbidden on the 16 GB capture host; use the repository-owned bounded 25-file suite wrapper."
        )

    instant = now or datetime.now().astimezone()
    if not _inside_heavy_window(instant) and (
        _pytest_executable_argument_records(command)
        or _python_heavy_module(command)
        or _heavy_test_entrypoint(command)
    ):
        return _deny(
            "Agent-started pytest, compileall, replay, backtest, or training work is allowed only 00:30-09:00 America/Toronto on this capture host."
        )
    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (OSError, ValueError, TypeError):
        return 0
    if not isinstance(payload, dict):
        return 0
    result = evaluate(payload)
    if result is not None:
        json.dump(result, sys.stdout, separators=(",", ":"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

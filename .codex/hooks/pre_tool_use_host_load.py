"""Block agent shell commands that violate the capture-host load policy."""

from __future__ import annotations

from datetime import datetime, time
import json
import os
import sys
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


HEAVY_START = time(0, 30)
HEAVY_END = time(9, 0)
try:
    POLICY_ZONE = ZoneInfo("America/Toronto")
except ZoneInfoNotFoundError:
    # The user-layer hook runs under the system ``py -3`` interpreter, which
    # need not have the third-party tzdata wheel. The capture host itself is
    # configured to America/Toronto, so system-local conversion is the safe
    # dependency-free fallback there.
    POLICY_ZONE = None

_PYTHON_EXECUTABLES = {"py", "python", "python3", "pythonw"}
_POWERSHELL_EXECUTABLES = {"powershell", "pwsh"}
_SHELL_EXECUTABLES = _POWERSHELL_EXECUTABLES | {"bash", "sh", "zsh"}
_RUN_COMMAND_WRAPPERS = {"uv", "poetry", "pipenv", "hatch", "pdm"}
_TEST_COMMAND_WRAPPERS = {"nox", "tox"}
_HEAVY_WRAPPERS = {
    "bounded_worktree_test_suite.ps1",
    "integration_attempt_suite.ps1",
    "prepare_integration_attempt.ps1",
}
_HEAVY_WEATHER_MODULE_MARKERS = (
    "retrain",
    "training",
    "replay",
    "backtest",
    "daily_refresh",
    "score_all",
)


def _is_constrained_capture_host() -> bool:
    # This user-layer hook is installed only on the dedicated Windows capture
    # host. Its protection must survive a RAM upgrade; physical-memory size is
    # not host identity and must never silently turn policy enforcement off.
    return os.name == "nt"


def _inside_heavy_window(now: datetime) -> bool:
    local = (
        now.astimezone(POLICY_ZONE)
        if POLICY_ZONE is not None
        else now.astimezone()
    )
    return HEAVY_START <= local.time().replace(tzinfo=None) < HEAVY_END


def _command_segments(command: str) -> list[list[str]]:
    """Tokenize PowerShell command positions without matching quoted data.

    This is intentionally a small policy lexer, not a PowerShell evaluator. It
    preserves quoted arguments as one token, honors PowerShell's backtick
    escape, and splits only on unquoted command separators. The distinction is
    important: a search such as ``rg -n \"pytest\"`` contains a heavy-command
    name as data and must not be mistaken for actually launching it.
    """

    segments: list[list[str]] = []
    current_segment: list[str] = []
    token: list[str] = []
    quote: str | None = None
    escaped = False

    def flush_token() -> None:
        if token:
            current_segment.append("".join(token))
            token.clear()

    def flush_segment() -> None:
        flush_token()
        if current_segment:
            segments.append(list(current_segment))
            current_segment.clear()

    for character in command:
        if escaped:
            token.append(character)
            escaped = False
            continue
        if character == "`":
            escaped = True
            continue
        if quote is not None:
            if character == quote:
                quote = None
            else:
                token.append(character)
            continue
        if character in {"'", '"'}:
            quote = character
            continue
        if character.isspace():
            flush_token()
            if character in {"\r", "\n"}:
                flush_segment()
            continue
        if character in {";", "|", "&", "{", "}"}:
            flush_segment()
            continue
        token.append(character)
    if escaped:
        token.append("`")
    flush_segment()
    return segments


def _executable_leaf(token: str) -> str:
    return token.replace("/", "\\").rsplit("\\", 1)[-1].casefold()


def _is_python_executable(token: str) -> bool:
    leaf = _executable_leaf(token)
    if leaf.endswith(".exe"):
        leaf = leaf[:-4]
    if leaf in _PYTHON_EXECUTABLES:
        return True
    for prefix in ("python", "pythonw"):
        if leaf.startswith(prefix):
            version = leaf[len(prefix) :]
            if version and version.replace(".", "").isdigit():
                return True
    return False


def _is_pytest_executable(token: str) -> bool:
    leaf = _executable_leaf(token)
    if leaf.endswith(".exe"):
        leaf = leaf[:-4]
    if leaf in {"pytest", "py.test"}:
        return True
    return leaf.startswith("pytest-") and leaf[7:].replace(".", "").isdigit()


def _powershell_option_matches(
    token: str,
    canonical: str,
    *,
    aliases: tuple[str, ...] = (),
) -> bool:
    """Conservatively recognize PowerShell's executable-option abbreviations."""

    folded = token.casefold()
    if folded.startswith("/"):
        folded = "-" + folded[1:]
    canonical = canonical.casefold()
    return folded in aliases or (
        folded.startswith("-")
        and len(folded) >= 2
        and canonical.startswith(folded)
    )


def _powershell_command_option(token: str) -> bool:
    return _powershell_option_matches(token, "-command", aliases=("-c",)) or (
        _powershell_option_matches(token, "-commandwithargs")
    )


def _powershell_encoded_option(token: str) -> bool:
    return _powershell_option_matches(
        token,
        "-encodedcommand",
        aliases=("-enc",),
    )


def _powershell_file_option(token: str) -> bool:
    return _powershell_option_matches(token, "-file", aliases=("-f",))


def _has_dynamic_command_expansion(command: str) -> bool:
    """Detect command substitution while leaving single-quoted search data inert."""

    quote: str | None = None
    escaped = False
    index = 0
    while index < len(command):
        character = command[index]
        if escaped:
            escaped = False
            index += 1
            continue
        if character == "`" and quote != "'":
            escaped = True
            index += 1
            continue
        if quote == "'":
            if character == "'":
                quote = None
            index += 1
            continue
        if character == '"':
            quote = None if quote == '"' else '"'
            index += 1
            continue
        if quote is None and character == "'":
            quote = "'"
            index += 1
            continue
        if character == "$" and index + 1 < len(command) and command[index + 1] == "(":
            return True
        index += 1
    return False


def _python_invocation_is_interactive(arguments: list[str]) -> bool:
    """Return true when an explicit Python launch has no finite entrypoint."""

    if any(
        token in {"-V", "-VV"}
        or token.casefold() in {"-h", "--help", "--version"}
        for token in arguments
    ):
        return False
    if any(token.casefold() in {"-i", "--interactive"} for token in arguments):
        return True

    positional_only = False
    index = 0
    while index < len(arguments):
        token = arguments[index]
        folded = token.casefold()
        if token == "--":
            positional_only = True
            index += 1
            continue
        if not positional_only and folded in {"-c", "-m"}:
            return index + 1 >= len(arguments)
        if not positional_only and token in {
            "-W",
            "-X",
            "--check-hash-based-pycs",
        }:
            index += 2
            continue
        if not positional_only and (
            (token.startswith("-W") or token.startswith("-X"))
            and len(token) > 2
        ):
            index += 1
            continue
        if not positional_only and token == "-x":
            index += 1
            continue
        if not positional_only and token.startswith("-"):
            index += 1
            continue
        # ``python -`` and an absent entrypoint both retain an input channel.
        return token == "-"
    return True


def _posix_shell_invocation_is_interactive(arguments: list[str]) -> bool:
    """Return true when bash/sh/zsh has no finite command or script."""

    if any(token.casefold() in {"--help", "--version"} for token in arguments):
        return False
    positional_only = False
    index = 0
    while index < len(arguments):
        token = arguments[index]
        folded = token.casefold()
        if not positional_only and token == "--":
            positional_only = True
            index += 1
            continue
        if not positional_only and (
            folded == "-c"
            or (
                folded.startswith("-")
                and folded[1:].isalpha()
                and "c" in folded[1:]
            )
        ):
            return index + 1 >= len(arguments)
        if not positional_only and (
            folded == "-s"
            or (
                folded.startswith("-")
                and folded[1:].isalpha()
                and "s" in folded[1:]
            )
        ):
            return True
        if not positional_only and folded in {
            "-o",
            "+o",
            "--init-file",
            "--rcfile",
        }:
            index += 2
            continue
        if not positional_only and (
            token.startswith("-") or token.startswith("+")
        ):
            index += 1
            continue
        return False
    return True


def _is_test_file(token: str) -> bool:
    # Pytest node ids append ``::Class::test`` to the path. The file remains
    # the bounded collection target and must not be mistaken for a full run.
    leaf = _executable_leaf(token.split("::", 1)[0])
    return leaf.endswith(".py") and (
        leaf.startswith("test_") or leaf.endswith("_test.py")
    )


def _segment_invocation(segment: list[str]) -> tuple[str, list[str]]:
    """Return the executable token and arguments for one policy segment."""

    if len(segment) > 1 and segment[0] == ".":
        return segment[1], segment[2:]
    # PowerShell permits a command invocation as an assignment's right-hand
    # expression (``$result = python -m pytest ...``). Treat that RHS as the
    # command position so assignment syntax cannot conceal a heavy launch.
    if segment and segment[0].startswith("$"):
        if "=" in segment:
            assignment = segment.index("=")
            if assignment + 1 < len(segment):
                return segment[assignment + 1], segment[assignment + 2 :]
        if "=" in segment[0]:
            _name, value = segment[0].split("=", 1)
            if value:
                return value, segment[1:]
    # POSIX shells permit one or more environment assignments before a
    # command. Nested ``bash -lc 'MODE=test python ...'`` must expose Python as
    # the executable instead of treating the assignment as a harmless command.
    index = 0
    while index < len(segment):
        name, separator, _value = segment[index].partition("=")
        if not separator or not name or not (
            name[0].isalpha() or name[0] == "_"
        ) or not all(character.isalnum() or character == "_" for character in name):
            break
        index += 1
    if index < len(segment):
        return segment[index], segment[index + 1 :]
    return segment[0], segment[1:]


def _pytest_invocation_is_unbounded(arguments: list[str]) -> bool:
    """Require one to 25 positional test files, excluding option values."""

    long_options_with_value = {
        "--assert",
        "--basetemp",
        "--capture",
        "--color",
        "--confcutdir",
        "--deselect",
        "--durations",
        "--durations-min",
        "--ignore",
        "--ignore-glob",
        "--import-mode",
        "--junit-prefix",
        "--junitxml",
        "--log-cli-date-format",
        "--log-cli-format",
        "--log-cli-level",
        "--log-date-format",
        "--log-file",
        "--log-file-date-format",
        "--log-file-format",
        "--log-file-level",
        "--log-format",
        "--log-level",
        "--maxfail",
        "--override-ini",
        "--rootdir",
        "--show-capture",
        "--tb",
        "--verbosity",
    }
    long_flag_options = {
        "--cache-clear",
        "--collect-only",
        "--continue-on-collection-errors",
        "--disable-warnings",
        "--exitfirst",
        "--fixtures",
        "--fixtures-per-test",
        "--full-trace",
        "--help",
        "--keep-duplicates",
        "--last-failed",
        "--last-failed-no-failures",
        "--markers",
        "--new-first",
        "--no-header",
        "--no-summary",
        "--pastebin",
        "--quiet",
        "--setup-only",
        "--setup-plan",
        "--setup-show",
        "--stepwise",
        "--stepwise-skip",
        "--strict-config",
        "--strict-markers",
        "--trace",
        "--verbose",
        "--version",
    }
    short_options_with_value = {"-c", "-k", "-m", "-o", "-p", "-W"}
    positional: list[str] = []
    positional_only = False
    index = 0
    while index < len(arguments):
        token = arguments[index]
        folded = token.casefold()
        if not positional_only and token == "--":
            positional_only = True
            index += 1
            continue
        if not positional_only and token.startswith("@"):
            return True
        if not positional_only and folded == "--pyargs":
            return True
        if not positional_only and folded.startswith("--"):
            option = folded.split("=", 1)[0]
            if "=" in folded:
                index += 1
                continue
            if option in long_options_with_value:
                if index + 1 >= len(arguments):
                    return True
                index += 2
                continue
            if option in long_flag_options:
                index += 1
                continue
            # Unknown plugin options can consume the following token. Refuse
            # rather than count that value as a bounded test-file target.
            return True
        if not positional_only and token.startswith("-"):
            if token in short_options_with_value:
                if index + 1 >= len(arguments):
                    return True
                index += 2
                continue
            if any(
                token.startswith(prefix) and len(token) > len(prefix)
                for prefix in short_options_with_value
            ):
                index += 1
                continue
            if len(token) > 1 and all(character in "qvxs" for character in token[1:]):
                index += 1
                continue
            if token.startswith("-r") and len(token) > 2:
                index += 1
                continue
            return True
        positional.append(token)
        index += 1

    if not 1 <= len(positional) <= 25:
        return True
    for token in positional:
        normalized = token.split("::", 1)[0].replace("/", "\\").rstrip("\\")
        normalized_folded = normalized.casefold()
        if any(marker in token for marker in ("*", "?", "[", "]")):
            return True
        if not _is_test_file(token):
            return True
        if normalized_folded in {".", "test", "tests"}:
            return True
    return False


def _is_broad_data_root(token: str) -> bool:
    normalized = token.replace("/", "\\").rstrip("\\").casefold()
    while normalized.endswith("\\."):
        normalized = normalized[:-2].rstrip("\\")
    for suffix in ("\\**", "\\*"):
        if normalized.endswith(suffix):
            normalized = normalized[: -len(suffix)].rstrip("\\")
            break
    if normalized in {
        "data",
        ".\\data",
    }:
        return True
    return normalized.endswith("\\data")


def _is_unbounded_search_root(token: str) -> bool:
    normalized = token.replace("/", "\\").rstrip("\\").casefold()
    return normalized in {".", ".."} or (
        len(normalized) == 2 and normalized[1] == ":"
    )


def _powershell_recursive_scan(arguments: list[str]) -> bool:
    for token in arguments:
        folded = token.casefold()
        if folded.startswith("/"):
            folded = "-" + folded[1:]
        option, separator, value = folded.partition(":")
        if separator and value in {"0", "false", "$false"}:
            continue
        if (
            option == "-r"
            or (
                option.startswith("-")
                and len(option) >= 3
                and "-recurse".startswith(option)
            )
            or option == "-depth"
        ):
            return True
    return False


def _rg_targets_broad_data(segment: list[str]) -> bool:
    """Recognize an explicit broad data/ search target, not a quoted pattern."""

    executable_token, arguments = _segment_invocation(segment)
    if _executable_leaf(executable_token) not in {"rg", "rg.exe"}:
        return False
    short_options_with_value = {
        "-A",
        "-B",
        "-C",
        "-E",
        "-g",
        "-j",
        "-m",
        "-M",
        "-r",
        "-t",
        "-T",
    }
    long_options_with_value = {
        "--after-context",
        "--before-context",
        "--context",
        "--color",
        "--colors",
        "--encoding",
        "--engine",
        "--glob",
        "--iglob",
        "--max-count",
        "--max-columns",
        "--max-depth",
        "--max-filesize",
        "--path-separator",
        "--pre",
        "--pre-glob",
        "--replace",
        "--sort",
        "--sortr",
        "--type",
        "--type-not",
        "--type-add",
        "--type-clear",
        "--threads",
    }
    pattern_seen = False
    files_mode = False
    hidden_mode = False
    ignore_bypass = False
    target_seen = False
    positional_only = False
    index = 0
    while index < len(arguments):
        token = arguments[index]
        folded = token.casefold()
        if not positional_only and folded == "--":
            positional_only = True
            index += 1
            continue
        if not positional_only and folded == "--files":
            files_mode = True
            pattern_seen = True
            index += 1
            continue
        if not positional_only and folded == "--hidden":
            hidden_mode = True
            index += 1
            continue
        if not positional_only and (
            folded.startswith("--no-ignore")
            or folded == "--unrestricted"
            or token in {"-u", "-uu", "-uuu"}
        ):
            ignore_bypass = True
            index += 1
            continue
        if not positional_only and (
            token in {"-e", "-f"} or folded in {"--regexp", "--file"}
        ):
            if index + 1 < len(arguments):
                pattern_seen = True
            index += 2
            continue
        if not positional_only and (
            (token.startswith("-e") and len(token) > 2)
            or (token.startswith("-f") and len(token) > 2)
            or folded.startswith("--regexp=")
            or folded.startswith("--file=")
        ):
            pattern_seen = True
            index += 1
            continue
        if not positional_only and (
            token in short_options_with_value or folded in long_options_with_value
        ):
            index += 2
            continue
        if not positional_only and any(
            folded.startswith(prefix)
            for prefix in ("--glob=", "--iglob=", "--type=", "--type-not=", "--type-add=")
        ):
            index += 1
            continue
        if not positional_only and folded.startswith("-"):
            index += 1
            continue
        if files_mode:
            target_seen = True
            if _is_broad_data_root(token) or _is_unbounded_search_root(token):
                return True
        elif not pattern_seen:
            pattern_seen = True
        else:
            target_seen = True
            if _is_broad_data_root(token) or (
                ignore_bypass and _is_unbounded_search_root(token)
            ):
                return True
        index += 1
    return (ignore_bypass or (files_mode and hidden_mode)) and not target_seen


def _nested_shell_commands(segment: list[str]) -> list[str]:
    if not segment:
        return []
    executable_token, arguments = _segment_invocation(segment)
    leaf = _executable_leaf(executable_token)
    if leaf.endswith(".exe"):
        leaf = leaf[:-4]
    if leaf in {"invoke-expression", "iex"}:
        return [" ".join(arguments)] if arguments else []
    if leaf in _POWERSHELL_EXECUTABLES:
        for index, token in enumerate(arguments):
            if _powershell_command_option(token) and index + 1 < len(arguments):
                return [" ".join(arguments[index + 1 :])]
        return []
    if leaf in {"bash", "sh", "zsh"}:
        for index, token in enumerate(arguments):
            folded = token.casefold()
            if (
                folded == "-c"
                or (
                    folded.startswith("-")
                    and folded[1:].isalpha()
                    and "c" in folded[1:]
                )
            ) and index + 1 < len(arguments):
                return [" ".join(arguments[index + 1 :])]
        return []
    if leaf == "cmd":
        for index, token in enumerate(arguments):
            if token.casefold() in {"/c", "/k"} and index + 1 < len(arguments):
                return [" ".join(arguments[index + 1 :])]
    return []


def _wrapped_process_commands(segment: list[str]) -> tuple[list[str], bool]:
    """Expose common runner/Start-Process child commands to the policy lexer.

    This is intentionally conservative. A dynamic Start-Process target cannot
    be classified from hook input, so it is opaque. Literal wrapper arguments
    are re-tokenized as the child command instead of relying on the wrapper's
    harmless executable name.
    """

    executable_token, arguments = _segment_invocation(segment)
    leaf = _executable_leaf(executable_token)
    if leaf.endswith(".exe"):
        leaf = leaf[:-4]
    if leaf == "env":
        index = 0
        while index < len(arguments):
            token = arguments[index]
            folded = token.casefold()
            name, separator, _value = token.partition("=")
            if token == "--":
                index += 1
                break
            if folded in {"-u", "--unset", "-c", "--chdir"}:
                if index + 1 >= len(arguments):
                    return [], True
                index += 2
                continue
            if folded in {"-s", "--split-string"}:
                if index + 1 >= len(arguments):
                    return [], True
                return [" ".join(arguments[index + 1 :])], False
            if folded.startswith("--split-string="):
                nested = token.split("=", 1)[1]
                return [" ".join([nested, *arguments[index + 1 :]])], False
            if token.startswith("-") and folded not in {
                "-i",
                "--ignore-environment",
                "-0",
                "--null",
                "-v",
                "--debug",
            }:
                return [], True
            if token.startswith("-"):
                index += 1
                continue
            if separator and name and (
                name[0].isalpha() or name[0] == "_"
            ) and all(character.isalnum() or character == "_" for character in name):
                index += 1
                continue
            break
        if index >= len(arguments):
            return [], True
        return [" ".join(arguments[index:])], False
    if leaf in _RUN_COMMAND_WRAPPERS:
        for index, token in enumerate(arguments):
            if token.casefold() == "run" and index + 1 < len(arguments):
                remainder = arguments[index + 1 :]
                while remainder and remainder[0] == "--":
                    remainder = remainder[1:]
                if not remainder:
                    return [], False
                if remainder[0].startswith("-"):
                    return [], True
                return [" ".join(remainder)], False
        return [], False
    if leaf in {"conda", "mamba", "micromamba"}:
        for index, token in enumerate(arguments):
            if token.casefold() == "run" and index + 1 < len(arguments):
                remainder = arguments[index + 1 :]
                child_index = 0
                while child_index < len(remainder):
                    token = remainder[child_index]
                    if token.casefold() in {"-n", "--name", "-p", "--prefix"}:
                        child_index += 2
                        continue
                    if token.startswith("-"):
                        child_index += 1
                        continue
                    return [" ".join(remainder[child_index:])], False
        return [], False
    if leaf not in {"start-process", "start", "saps"}:
        return [], False

    target = ""
    argument_list: list[str] = []
    index = 0
    while index < len(arguments):
        token = arguments[index]
        if _powershell_option_matches(
            token,
            "-filepath",
            aliases=("-file",),
        ):
            if index + 1 >= len(arguments):
                return [], True
            target = arguments[index + 1]
            index += 2
            continue
        if _powershell_option_matches(
            token,
            "-argumentlist",
            aliases=("-args",),
        ):
            if index + 1 >= len(arguments):
                return [], True
            argument_list = arguments[index + 1 :]
            break
        if any(
            _powershell_option_matches(token, parameter)
            for parameter in (
                "-credential",
                "-environment",
                "-redirectstandarderror",
                "-redirectstandardinput",
                "-redirectstandardoutput",
                "-verb",
                "-windowstyle",
                "-workingdirectory",
            )
        ):
            if index + 1 >= len(arguments):
                return [], True
            if any(
                marker in arguments[index + 1]
                for marker in ("$", "`", "@(", "$(")
            ):
                return [], True
            index += 2
            continue
        if any(
            _powershell_option_matches(token, parameter)
            for parameter in (
                "-loaduserprofile",
                "-nonewwindow",
                "-passthru",
                "-useNewEnvironment",
                "-wait",
            )
        ):
            index += 1
            continue
        if token.startswith(("-", "/")):
            # Unknown or ambiguous Start-Process parameters may consume the
            # next token. Refuse instead of misclassifying that value as the
            # executable and overlooking a later child command.
            return [], True
        if not target and not token.startswith("-"):
            target = token
        elif target:
            # Start-Process accepts ArgumentList positionally, but quote
            # provenance is no longer available after lexing. Re-tokenizing
            # these literal values remains conservative; dynamic values are
            # rejected below.
            argument_list.append(token)
        index += 1
    if not target or "$" in target or "`" in target:
        return [], True
    if any(
        any(marker in token for marker in ("$", "`", "@(", "$("))
        for token in argument_list
    ):
        return [], True
    flattened_arguments = " ".join(argument_list).replace(",", " ")
    return [" ".join(part for part in (target, flattened_arguments) if part)], False


def _command_facts(command: str) -> dict[str, bool]:
    facts = {
        "pytest": False,
        "unbounded_pytest": False,
        "compileall": False,
        "direct_heavy_weather": False,
        "heavy_wrapper": False,
        "recursive_scan": False,
        "opaque_command": False,
    }
    pending = [command]
    inspected = 0
    while pending:
        candidate = pending.pop()
        inspected += 1
        if _has_dynamic_command_expansion(candidate):
            facts["opaque_command"] = True
        if inspected > 8:
            # A deeply nested shell launch is not needed by repository
            # verification. Treat it conservatively as heavy rather than let a
            # recursive command-string construction evade the launch guard.
            facts["opaque_command"] = True
            break
        for segment in _command_segments(candidate):
            if not segment:
                continue
            pending.extend(_nested_shell_commands(segment))
            wrapped_commands, wrapped_is_opaque = _wrapped_process_commands(segment)
            pending.extend(wrapped_commands)
            if wrapped_is_opaque:
                facts["opaque_command"] = True
            executable_token, arguments = _segment_invocation(segment)
            executable = _executable_leaf(executable_token)
            if any(marker in executable_token for marker in ("$", "`", "%")):
                facts["opaque_command"] = True
            if executable_token.startswith(("(", "[")):
                facts["opaque_command"] = True
            if executable in _HEAVY_WRAPPERS:
                facts["heavy_wrapper"] = True
            executable_without_suffix = (
                executable[:-4] if executable.endswith(".exe") else executable
            )
            if executable_without_suffix in {"invoke-expression", "iex"}:
                facts["opaque_command"] = True
            if executable_without_suffix in _POWERSHELL_EXECUTABLES:
                if not any(
                    _powershell_command_option(token)
                    or _powershell_file_option(token)
                    or _powershell_encoded_option(token)
                    for token in arguments
                ):
                    facts["opaque_command"] = True
                if any(
                    _powershell_option_matches(token, "-noexit")
                    for token in arguments
                ):
                    facts["opaque_command"] = True
                for index, token in enumerate(arguments):
                    if (
                        _powershell_file_option(token)
                        and index + 1 < len(arguments)
                        and _executable_leaf(arguments[index + 1])
                        in _HEAVY_WRAPPERS
                    ):
                        facts["heavy_wrapper"] = True
                    if _powershell_encoded_option(token):
                        facts["opaque_command"] = True
            if executable_without_suffix in {"bash", "sh", "zsh"}:
                if _posix_shell_invocation_is_interactive(arguments):
                    facts["opaque_command"] = True
            if executable_without_suffix == "cmd":
                command_options = {token.casefold() for token in arguments}
                if "/k" in command_options or "/c" not in command_options:
                    facts["opaque_command"] = True
            if executable in {
                "get-childitem",
                "get-childitem.exe",
                "gci",
                "dir",
                "ls",
            } and _powershell_recursive_scan(arguments):
                facts["recursive_scan"] = True
            if executable == "dir" and any(
                token.casefold() == "/s" for token in arguments
            ):
                facts["recursive_scan"] = True
            if _rg_targets_broad_data(segment):
                facts["recursive_scan"] = True
            module = ""
            module_argument_start = 0
            if _is_python_executable(executable_token):
                for index in range(0, len(arguments) - 1):
                    if arguments[index].casefold() == "-m":
                        module = arguments[index + 1].casefold()
                        module_argument_start = index + 2
                        break
            direct_pytest = _is_pytest_executable(executable_token)
            module_pytest = module == "pytest"
            if direct_pytest or module_pytest:
                facts["pytest"] = True
                argument_start = 0 if direct_pytest else module_argument_start
                if _pytest_invocation_is_unbounded(arguments[argument_start:]):
                    facts["unbounded_pytest"] = True
            if executable_without_suffix in _TEST_COMMAND_WRAPPERS or module in {
                "nox",
                "tox",
                "unittest",
            }:
                facts["pytest"] = True
                facts["unbounded_pytest"] = True
            if _is_python_executable(executable_token):
                if _python_invocation_is_interactive(arguments):
                    facts["opaque_command"] = True
                for index, token in enumerate(arguments[:-1]):
                    if token.casefold() == "-c" and any(
                        marker in arguments[index + 1].casefold()
                        for marker in ("pytest", "compileall", "weather.")
                    ):
                        facts["opaque_command"] = True
            if module == "compileall":
                facts["compileall"] = True
            if module.startswith("weather.") and any(
                marker in module for marker in _HEAVY_WEATHER_MODULE_MARKERS
            ):
                facts["direct_heavy_weather"] = True
    return facts


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
        return _deny("The capture-host load hook received malformed shell tool input.")
    command = tool_input.get("command")
    if not isinstance(command, str) or not command.strip():
        return _deny("The capture-host load hook received an empty shell command.")
    active = (
        _is_constrained_capture_host()
        if constrained_capture_host is None
        else constrained_capture_host
    )
    if not active:
        return None

    command_facts = _command_facts(command)
    if command_facts["recursive_scan"]:
        return _deny(
            "Recursive Get-ChildItem and broad scans of data/ are forbidden on the capture host; use rg or target a known file/bounded subtree."
        )
    if command_facts["opaque_command"]:
        return _deny(
            "Opaque or dynamically evaluated shell commands are forbidden on the capture host because the load guard cannot classify their child workload."
        )
    if command_facts["unbounded_pytest"]:
        return _deny(
            "An unbounded test run is forbidden on the 16 GB capture host; "
            "direct pytest must name no more than 25 explicit test files and "
            "complete inventories must use the repository-owned bounded suite."
        )

    instant = now or datetime.now().astimezone()
    if not _inside_heavy_window(instant) and (
        command_facts["pytest"]
        or command_facts["compileall"]
        or command_facts["direct_heavy_weather"]
        or command_facts["heavy_wrapper"]
    ):
        return _deny(
            "Agent-started pytest, compileall, replay, backtest, or training work is allowed only 00:30-09:00 America/Toronto on this capture host."
        )
    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (OSError, ValueError, TypeError):
        json.dump(
            _deny("The capture-host load hook received invalid JSON input."),
            sys.stdout,
            separators=(",", ":"),
        )
        return 0
    if not isinstance(payload, dict):
        json.dump(
            _deny("The capture-host load hook received a non-object input."),
            sys.stdout,
            separators=(",", ":"),
        )
        return 0
    try:
        result = evaluate(payload)
    except Exception:
        # A policy implementation error must not become permission to launch an
        # unclassified workload. Keep the independent S4U watchdog as the
        # second layer, but fail closed at the earliest boundary too.
        result = _deny(
            "The capture-host load hook could not classify this shell command; execution is refused until the hook is repaired."
        )
    if result is not None:
        json.dump(result, sys.stdout, separators=(",", ":"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

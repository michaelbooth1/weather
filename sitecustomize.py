"""Local Windows safety defaults for background Python jobs.

The weather workers run from Task Scheduler under pythonw.exe. Some libraries
probe platform or CPU details by spawning console programs such as cmd.exe or
powershell.exe; with Windows Terminal as the default console host those probes
can steal focus. This file is imported automatically by Python when the repo
root is on sys.path, which is true for the scheduled workers.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parent
_SRC_ROOT = _REPO_ROOT / "src"
_OFFLINE_BOOTSTRAP_READY_ENV = "WEATHER_INTEGRATION_TEST_BOOTSTRAP_READY"
if (_SRC_ROOT / "weather").is_dir():
    _src_text = str(_SRC_ROOT)
    if os.environ.get("WEATHER_INTEGRATION_TEST_OFFLINE") == "1":
        # A reviewed-but-ambient ``.pth`` path may precede PYTHONPATH before
        # this module is imported.  Put this tracked candidate's canonical
        # source root first before importing the process-level safety latch.
        _src_normalized = {
            os.path.normcase(os.path.normpath(os.path.abspath(_src_text))),
            os.path.normcase(os.path.normpath(os.path.realpath(_src_text))),
        }
        _candidate_first_path = []
        for _path_entry in sys.path:
            _path_text = _path_entry or os.getcwd()
            _path_normalized = {
                os.path.normcase(os.path.normpath(os.path.abspath(_path_text))),
                os.path.normcase(os.path.normpath(os.path.realpath(_path_text))),
            }
            if _path_normalized.isdisjoint(_src_normalized):
                _candidate_first_path.append(_path_entry)
        sys.path[:] = [_src_text, *_candidate_first_path]
    elif _src_text not in sys.path:
        sys.path.insert(0, _src_text)

# The bounded integration suite deliberately exports this marker before it
# starts any Python descendant.  Enforce the no-network contract during the
# interpreter bootstrap so a test-launched Python subprocess cannot evade the
# later pytest ``conftest`` guard merely by changing its working directory.
if os.environ.get("WEATHER_INTEGRATION_TEST_OFFLINE") == "1":
    # Never trust an inherited success marker.  Each interpreter must finish
    # this tracked bootstrap before qualification code is allowed to run.
    os.environ.pop(_OFFLINE_BOOTSTRAP_READY_ENV, None)
    try:
        # Latch the non-network external-I/O guard before test code can alter
        # its inherited environment. Credential and real transport boundaries
        # consult this process-level state in addition to the environment.
        from weather.integration_test_safety import integration_test_offline

        if not integration_test_offline():
            raise RuntimeError("integration-test offline boundary did not latch")
        import re
        import shutil
        import subprocess
        import socket
        import threading

        _weather_secret_exact = {
            "PIP_INDEX_URL",
            "PIP_EXTRA_INDEX_URL",
            "UV_INDEX_URL",
            "UV_EXTRA_INDEX_URL",
            "GH_TOKEN",
            "GITHUB_TOKEN",
            "HF_TOKEN",
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "ALL_PROXY",
            "NO_PROXY",
            "CURL_CA_BUNDLE",
            "REQUESTS_CA_BUNDLE",
            "SSL_CERT_FILE",
            "SSL_CERT_DIR",
            "NODE_EXTRA_CA_CERTS",
            "PIP_CERT",
            "PIP_PROXY",
            "PIP_TRUSTED_HOST",
            "SSH_AUTH_SOCK",
            "GIT_ASKPASS",
            "SSH_ASKPASS",
            "GIT_SSH",
            "GIT_SSH_COMMAND",
            "GIT_PROXY_COMMAND",
        }
        _weather_secret_prefix = re.compile(
            r"^(?:POLYMARKET_|POLYMM_|OPENAI_|ANTHROPIC_|CLOUDFLARE_|"
            r"AWS_|AZURE_|GOOGLE_|GCM_|GIT_SSL_|GIT_SSH)",
            re.IGNORECASE,
        )
        _weather_secret_generic = re.compile(
            r"(?:^|_)(?:TOKEN|PASSWORD|PASSWD|SECRET|PRIVATE_KEY|API_KEY|"
            r"ACCESS_KEY|CLIENT_SECRET|CREDENTIALS?|CONNECTION_STRING|URL|"
            r"URI|DSN|AUTH|COOKIE|KEY|CERT)(?:$|_)",
            re.IGNORECASE,
        )
        _weather_git_redirect_environment = {
            "GIT_CONFIG_PARAMETERS",
            "GIT_DIR",
            "GIT_WORK_TREE",
            "GIT_INDEX_FILE",
            "GIT_OBJECT_DIRECTORY",
            "GIT_ALTERNATE_OBJECT_DIRECTORIES",
            "GIT_COMMON_DIR",
            "GIT_NAMESPACE",
            "GIT_CEILING_DIRECTORIES",
            "GIT_DISCOVERY_ACROSS_FILESYSTEM",
            "GIT_DIFF_OPTS",
            "GIT_EDITOR",
            "GIT_EXEC_PATH",
            "GIT_EXTERNAL_DIFF",
            "GIT_FLUSH",
            "GIT_TEMPLATE_DIR",
            "GIT_PAGER",
            "GIT_SEQUENCE_EDITOR",
            "GIT_TRACE",
            "GIT_TRACE2",
            "GIT_TRACE2_EVENT",
            "GIT_TRACE2_PERF",
            "GIT_TRACE2_SETUP",
        }

        def _weather_git_redirect_environment_name(value) -> bool:
            try:
                upper = os.fsdecode(value).upper()
            except (TypeError, ValueError):
                return True
            return (
                upper in _weather_git_redirect_environment
                or upper.startswith("GIT_CONFIG_KEY_")
                or upper.startswith("GIT_CONFIG_VALUE_")
            )

        def _weather_secret_environment_name(value) -> bool:
            try:
                name = os.fsdecode(value)
            except (TypeError, ValueError):
                return True
            upper = name.upper()
            if upper == "WEATHER_INTEGRATION_TEST_SECRET_POLICY":
                return False
            return (
                upper in _weather_secret_exact
                or _weather_secret_prefix.search(name) is not None
                or _weather_secret_generic.search(name) is not None
            )

        # Hosted runners and interactive shells can supply credentials that a
        # deterministic test never needs. Remove them before importing test
        # code, and apply the same classifier at every Python process edge.
        for _weather_environment_name in tuple(os.environ):
            if (
                _weather_secret_environment_name(_weather_environment_name)
                or _weather_git_redirect_environment_name(
                    _weather_environment_name
                )
            ):
                os.environ.pop(_weather_environment_name, None)

        _production_root_text = os.environ.get(
            "WEATHER_INTEGRATION_TEST_PRODUCTION_ROOT", ""
        ).strip()
        _candidate_root_text = os.environ.get(
            "WEATHER_INTEGRATION_TEST_CANDIDATE_ROOT", ""
        ).strip()
        _evidence_root_text = os.environ.get(
            "WEATHER_INTEGRATION_TEST_EVIDENCE_ROOT", ""
        ).strip()
        _read_only_production_probe_text = os.environ.get(
            "WEATHER_INTEGRATION_TEST_READ_ONLY_PRODUCTION_PROBE", ""
        ).strip()
        _read_only_production_probe = _read_only_production_probe_text == "1"
        _allowed_write_root_text = os.environ.get(
            "WEATHER_INTEGRATION_TEST_ALLOWED_WRITE_ROOT", ""
        ).strip()
        _secret_policy = os.environ.get(
            "WEATHER_INTEGRATION_TEST_SECRET_POLICY", ""
        ).strip()
        _temp_policy = os.environ.get(
            "WEATHER_INTEGRATION_TEST_TEMP_POLICY", ""
        ).strip()

        def _weather_normalized_path(value, *, base=None):
            if isinstance(value, int):
                return None
            try:
                text_value = os.fsdecode(value)
            except (TypeError, ValueError):
                return None
            if not text_value or text_value in {"NUL", "/dev/null"}:
                return None
            if os.name == "nt":
                windows_value = text_value.replace("/", "\\")
                if windows_value.startswith(("\\\\?\\", "\\\\.\\", "\\??\\")):
                    raise RuntimeError(
                        "Windows device-prefixed paths are forbidden by the "
                        "integration-test offline boundary"
                    )
            if base is not None and not os.path.isabs(text_value):
                text_value = os.path.join(os.fsdecode(base), text_value)
            absolute = os.path.abspath(text_value)
            return (
                os.path.normcase(os.path.normpath(absolute)),
                os.path.normcase(os.path.normpath(os.path.realpath(absolute))),
            )

        def _weather_path_below(candidate: str, root: str) -> bool:
            try:
                return os.path.commonpath((candidate, root)) == root
            except (OSError, ValueError):
                return False

        _protected_repository_paths = ()
        if _production_root_text:
            _production_paths = _weather_normalized_path(_production_root_text)
            _candidate_paths = _weather_normalized_path(_candidate_root_text)
            _evidence_paths = _weather_normalized_path(_evidence_root_text)
            _bootstrap_paths = _weather_normalized_path(_REPO_ROOT)
            _temp_values = tuple(
                os.environ.get(name, "").strip()
                for name in ("TEMP", "TMP", "TMPDIR")
            )
            _temp_paths = tuple(
                _weather_normalized_path(value) for value in _temp_values if value
            )
            _production_candidate_overlap = any(
                _weather_path_below(candidate, production)
                or _weather_path_below(production, candidate)
                for candidate, production in zip(
                    _candidate_paths or (), _production_paths or ()
                )
            )
            if (
                _production_paths is None
                or not os.path.isabs(_production_root_text)
                or not os.path.isdir(_production_root_text)
                or _candidate_paths is None
                or not os.path.isabs(_candidate_root_text)
                or not os.path.isdir(_candidate_root_text)
                or _bootstrap_paths is None
                or _candidate_paths != _bootstrap_paths
                or _secret_policy != "conservative_v1"
                or _temp_policy not in {"", "system_temp_unique_v1"}
                or _read_only_production_probe_text not in {"", "0", "1"}
                or (
                    _read_only_production_probe
                    and _candidate_paths != _production_paths
                )
                or (
                    not _read_only_production_probe
                    and _production_candidate_overlap
                )
                or (
                    bool(_evidence_root_text)
                    and (
                        _evidence_paths is None
                        or not os.path.isabs(_evidence_root_text)
                        or not os.path.isdir(_evidence_root_text)
                        or not all(
                            _weather_path_below(evidence, production)
                            for evidence, production in zip(
                                _evidence_paths, _production_paths
                            )
                        )
                        or (
                            not _read_only_production_probe
                            and any(
                                _weather_path_below(evidence, candidate)
                                or _weather_path_below(candidate, evidence)
                                for evidence, candidate in zip(
                                    _evidence_paths, _candidate_paths
                                )
                            )
                        )
                    )
                )
                or _allowed_write_root_text
                or (
                    _temp_policy == "system_temp_unique_v1"
                    and (
                        len(_temp_paths) != 3
                        or any(
                            paths != _temp_paths[0] for paths in _temp_paths[1:]
                        )
                        or not all(os.path.isabs(value) for value in _temp_values)
                        or not all(os.path.isdir(value) for value in _temp_values)
                        or any(
                            _weather_path_below(temp_path, protected_path)
                            or _weather_path_below(protected_path, temp_path)
                            for temp_path, protected_path in zip(
                                _temp_paths[0],
                                (
                                    _production_paths[0],
                                    _production_paths[1],
                                ),
                            )
                        )
                        or any(
                            _weather_path_below(temp_path, protected_path)
                            or _weather_path_below(protected_path, temp_path)
                            for protected_paths in (
                                _candidate_paths,
                                _evidence_paths,
                            )
                            if protected_paths is not None
                            for temp_path, protected_path in zip(
                                _temp_paths[0], protected_paths
                            )
                        )
                    )
                )
            ):
                raise RuntimeError(
                    "integration-test repository write boundary is malformed; "
                    "protected-tree write exceptions are forbidden"
                )
            _protected_repository_paths = tuple(
                paths
                for paths in (
                    _production_paths,
                    _candidate_paths,
                    _evidence_paths,
                )
                if paths is not None
            )

            # ``.pth`` files and the ambient launcher can place the production
            # checkout ahead of this candidate before sitecustomize runs.  The
            # bounded suite must never satisfy an import from either the
            # production repository root or its canonical ``src`` directory.
            # Remove only those two exact import roots: the production venv's
            # site-packages directory is intentionally retained as the pinned
            # interpreter environment and is separately fingerprinted by the
            # suite runner.
            if not _read_only_production_probe:
                _production_import_roots = {
                    normalized
                    for value in (
                        _production_root_text,
                        os.path.join(_production_root_text, "src"),
                    )
                    for normalized in (_weather_normalized_path(value) or ())
                }
                _candidate_sys_path = []
                for _weather_import_path in sys.path:
                    _weather_import_probe = _weather_normalized_path(
                        _weather_import_path or os.getcwd()
                    )
                    if (
                        _weather_import_probe is not None
                        and any(
                            normalized in _production_import_roots
                            for normalized in _weather_import_probe
                        )
                    ):
                        continue
                    _candidate_sys_path.append(_weather_import_path)
                sys.path[:] = _candidate_sys_path

            def _weather_repository_write_forbidden(value) -> bool:
                paths = _weather_normalized_path(value)
                if paths is None:
                    return False
                return any(
                    any(
                        _weather_path_below(path, root)
                        for path, root in zip(paths, protected_paths)
                    )
                    for protected_paths in _protected_repository_paths
                )

            def _weather_sensitive_repository_read(value) -> bool:
                paths = _weather_normalized_path(value)
                if paths is None:
                    return False
                leaf = os.path.basename(paths[0]).casefold()
                if os.name == "nt":
                    # NTFS alternate-stream spellings such as ``.env::$DATA``
                    # address the same protected secret while changing the
                    # apparent leaf name.
                    leaf = leaf.split(":", 1)[0]
                if leaf != ".env" and not leaf.startswith(".env."):
                    return False
                return any(
                    any(
                        _weather_path_below(path, root)
                        for path, root in zip(paths, protected_paths)
                    )
                    for protected_paths in _protected_repository_paths
                )

            _weather_mutation_path_arguments = {
                "os.remove": (0,),
                "os.rmdir": (0,),
                "os.rename": (0, 1),
                "os.mkdir": (0,),
                "os.mknod": (0,),
                "os.chmod": (0,),
                "os.chown": (0,),
                "os.utime": (0,),
                "os.setxattr": (0,),
                "os.removexattr": (0,),
                "os.link": (0, 1),
                "os.symlink": (0, 1),
                "os.truncate": (0,),
                "shutil.copyfile": (1,),
                "shutil.copymode": (1,),
                "shutil.copystat": (1,),
                "shutil.copytree": (1,),
                "shutil.move": (0, 1),
                "shutil.rmtree": (0,),
                "shutil.unpack_archive": (1,),
                "sqlite3.connect": (0,),
            }
            _weather_registry_mutation_events = {
                "winreg.CreateKey",
                "winreg.CreateKeyEx",
                "winreg.DeleteKey",
                "winreg.DeleteKeyEx",
                "winreg.DeleteValue",
                "winreg.DisableReflectionKey",
                "winreg.EnableReflectionKey",
                "winreg.FlushKey",
                "winreg.SetValue",
                "winreg.SetValueEx",
                "winreg.SaveKey",
                "winreg.LoadKey",
                "winreg.UnloadKey",
            }

            def _weather_offline_audit(event, arguments):
                if event == "open" and arguments:
                    mode = arguments[1] if len(arguments) > 1 else None
                    flags = arguments[2] if len(arguments) > 2 else 0
                    writes = isinstance(mode, str) and any(
                        marker in mode for marker in "wax+"
                    )
                    if isinstance(flags, int):
                        writes = writes or bool(
                            flags
                            & (
                                os.O_WRONLY
                                | os.O_RDWR
                                | os.O_CREAT
                                | os.O_TRUNC
                                | os.O_APPEND
                            )
                        )
                    if writes and _weather_repository_write_forbidden(arguments[0]):
                        raise RuntimeError(
                            "protected repository filesystem mutation is forbidden by the "
                            "integration-test offline boundary"
                        )
                    if not writes and _weather_sensitive_repository_read(arguments[0]):
                        raise RuntimeError(
                            "repository secret-file reads are forbidden by the "
                            "integration-test offline boundary"
                        )
                elif event == "sqlite3.connect" and arguments:
                    try:
                        sqlite_target = os.fsdecode(arguments[0])
                    except (TypeError, ValueError):
                        sqlite_target = ""
                    if sqlite_target.casefold().startswith("file:"):
                        raise RuntimeError(
                            "SQLite file URIs are forbidden by the integration-test "
                            "offline boundary"
                        )
                    if _weather_repository_write_forbidden(arguments[0]):
                        raise RuntimeError(
                            "protected repository filesystem mutation is forbidden by the "
                            "integration-test offline boundary"
                        )
                elif event in _weather_registry_mutation_events:
                    raise RuntimeError(
                        "Windows Registry mutation is forbidden by the "
                        "integration-test offline boundary"
                    )
                else:
                    for index in _weather_mutation_path_arguments.get(event, ()):
                        if index < len(arguments) and _weather_repository_write_forbidden(
                            arguments[index]
                        ):
                            raise RuntimeError(
                                "protected repository filesystem mutation is forbidden by the "
                                "integration-test offline boundary"
                            )

            sys.addaudithook(_weather_offline_audit)
        elif any(
            (
                _candidate_root_text,
                _evidence_root_text,
                _allowed_write_root_text,
                _secret_policy,
                _temp_policy,
                _read_only_production_probe_text,
            )
        ):
            raise RuntimeError(
                "integration-test repository boundary controls require one "
                "absolute production root"
            )

        def _weather_path_is_protected(value, *, base=None) -> bool:
            paths = _weather_normalized_path(value, base=base)
            if paths is None:
                return False
            return any(
                any(
                    _weather_path_below(path, root)
                    for path, root in zip(paths, protected_paths)
                )
                for protected_paths in _protected_repository_paths
            )

        _weather_executable_environment = {
            "python": "WEATHER_INTEGRATION_TEST_PYTHON_EXECUTABLE",
            "git": "WEATHER_INTEGRATION_TEST_GIT_EXECUTABLE",
            "powershell": "WEATHER_INTEGRATION_TEST_POWERSHELL_EXECUTABLE",
        }

        def _weather_located_executable(value):
            try:
                executable = os.fsdecode(value)
            except (TypeError, ValueError):
                return None
            if not executable or "\x00" in executable:
                return None
            has_directory = os.path.dirname(executable) != ""
            located = executable if has_directory else shutil.which(executable)
            if not located:
                return None
            located = os.path.abspath(located)
            if not os.path.isfile(located):
                return None
            return os.path.normpath(located)

        def _weather_resolved_executable(value):
            located = _weather_located_executable(value)
            if located is None:
                return None
            resolved = os.path.realpath(located)
            if not os.path.isfile(resolved):
                return None
            return os.path.normcase(os.path.normpath(resolved))

        def _weather_bound_executable(kind, fallbacks):
            environment_name = _weather_executable_environment[kind]
            requested = os.environ.get(environment_name, "").strip()
            if requested:
                if not os.path.isabs(requested):
                    raise RuntimeError(
                        f"{environment_name} must be an absolute executable path"
                    )
                located = _weather_located_executable(requested)
                if located is None:
                    raise RuntimeError(
                        f"{environment_name} does not identify a regular executable"
                    )
                return located
            for fallback in fallbacks:
                located = _weather_located_executable(fallback)
                if located is not None:
                    return located
            return None

        _weather_allowed_executables = {}
        _weather_current_python = _weather_bound_executable(
            "python", (sys.executable, getattr(sys, "_base_executable", ""))
        )
        if _weather_current_python is None:
            raise RuntimeError(
                "integration-test Python executable identity is unavailable"
            )
        _weather_allowed_executables[
            _weather_resolved_executable(_weather_current_python)
        ] = "python"
        _weather_git_executable = _weather_bound_executable("git", ("git", "git.exe"))
        if _weather_git_executable is not None:
            _weather_allowed_executables[
                _weather_resolved_executable(_weather_git_executable)
            ] = "git"
        _weather_powershell_executable = _weather_bound_executable(
            "powershell",
            ("powershell.exe", "powershell", "pwsh.exe", "pwsh"),
        )
        if _weather_powershell_executable is not None:
            _weather_allowed_executables[
                _weather_resolved_executable(_weather_powershell_executable)
            ] = "powershell"

        # Freeze discovered identities into the process environment so even a
        # replacement child environment receives the same approved tools. The
        # production runner supplies these paths after retaining their exact
        # executable bytes; ordinary CI derives them once at interpreter start.
        for _weather_kind, _weather_path in (
            ("python", _weather_current_python),
            ("git", _weather_git_executable),
            ("powershell", _weather_powershell_executable),
        ):
            _weather_name = _weather_executable_environment[_weather_kind]
            if _weather_path is None:
                os.environ.pop(_weather_name, None)
            else:
                os.environ[_weather_name] = _weather_path

        # These source scans are a deliberately conservative layer in front of
        # direct PowerShell children. They are defense in depth, not a
        # PowerShell parser and not an OS sandbox. The bounded runner's Job,
        # write boundary, stripped environment, and exact executable binding
        # remain independent controls; an accepted payload is not authority.
        _weather_powershell_external_io = re.compile(
            r"(?i)(?<![A-Za-z0-9_-])(?:"
            r"Invoke-(?:WebRequest|RestMethod)|Start-BitsTransfer|"
            r"Resolve-DnsName|Test-NetConnection|"
            r"(?:System\.)?Net\.(?:"
            r"WebClient|WebRequest|HttpWebRequest|FtpWebRequest|Dns|"
            r"Http\.HttpClient|Sockets\.(?:TcpClient|UdpClient)"
            r")|"
            r"curl(?:\.exe)?|wget(?:\.exe)?|ftp(?:\.exe)?|"
            r"ssh(?:\.exe)?|scp(?:\.exe)?|sftp(?:\.exe)?|"
            r"nslookup(?:\.exe)?|ping(?:\.exe)?|telnet(?:\.exe)?|"
            r"cmdkey(?:\.exe)?|vaultcmd(?:\.exe)?|"
            r"Get-StoredCredential|CredRead"
            r")(?![A-Za-z0-9_-])"
        )
        _weather_powershell_sensitive_store = re.compile(
            r"(?ix)(?:"
            r"(?<![A-Za-z0-9_])\.env(?:\.[A-Za-z0-9_.-]+)?"
            r"(?=$|[\s'\"`;,:\)\]\}/\\])|"
            r"(?:Microsoft[\\/]+Credentials|Microsoft[\\/]+Vault)|"
            r"(?:\.git-credentials|\.aws[\\/]+credentials|"
            r"\.netrc|_netrc|id_rsa|id_ed25519)|"
            r"(?:Get|Set|Remove)-(?:Secret|StoredCredential)|"
            r"Windows\.Security\.Credentials\.PasswordVault|"
            r"Security\.Cryptography\.ProtectedData\s*\]\s*::\s*Unprotect"
            r")"
        )
        _weather_powershell_scheduler_mutation = re.compile(
            r"(?i)(?<![A-Za-z0-9_-])(?:"
            r"(?:Register|Enable|Disable|Start|Stop|Unregister|Set)-ScheduledTask|"
            r"schtasks(?:\.exe)?|Schedule\.Service"
            r")(?![A-Za-z0-9_-])"
        )
        _weather_powershell_scheduler_function_mock = re.compile(
            r"(?im)^\s*function\s+"
            r"(?:Register|Enable|Disable|Start|Stop|Unregister|Set)-ScheduledTask\b"
        )
        _weather_powershell_scheduler_guard = re.compile(
            r"(?i)(?<![A-Za-z0-9_-])"
            r"Assert-WeatherIntegrationSchedulerMutationAllowed"
            r"(?![A-Za-z0-9_-])"
        )
        _weather_powershell_invoke_expression = re.compile(
            r"(?i)(?<![A-Za-z0-9_-])(?:Invoke-Expression|iex)"
            r"(?![A-Za-z0-9_-])"
        )
        _weather_powershell_add_type = re.compile(
            r"(?i)(?<![A-Za-z0-9_-])Add-Type(?![A-Za-z0-9_-])"
        )
        _weather_powershell_dynamic_creation = re.compile(
            r"(?ix)(?:"
            r"-(?:e|ec|en|enc|enco|encod|encode|encoded|"
            r"encodedc|encodedco|encodedcom|encodedcomm|encodedcomma|"
            r"encodedcomman|encodedcommand|encodedarguments)\b|"
            r"\[\s*(?:System\.)?Management\.Automation\.ScriptBlock\s*\]"
            r"\s*::\s*Create\b|"
            r"New-Object\s+(?:System\.)?Management\.Automation\.ScriptBlock\b"
            r")"
        )
        _weather_powershell_ast_fixture = re.compile(
            r"(?i)Management\.Automation\.Language\.Parser\s*\]\s*::\s*Parse"
        )
        _weather_powershell_job_add_type_fixture = re.compile(
            r"(?is)WEATHER_JOB_HELPER.*KillOnCloseJob|"
            r"KillOnCloseJob.*WEATHER_JOB_HELPER"
        )
        _weather_powershell_file_mutation = re.compile(
            r"(?ix)(?:"
            r"(?<![A-Za-z0-9_-])(?:Set|Add|Clear)-Content(?![A-Za-z0-9_-])|"
            r"(?<![A-Za-z0-9_-])Out-File(?![A-Za-z0-9_-])|"
            r"(?<![A-Za-z0-9_-])(?:Remove|Move|Copy|Rename|New|Set)-Item"
            r"(?![A-Za-z0-9_-])|"
            r"\[\s*(?:System\.)?(?:IO\.)?(?:File|Directory)\s*\]"
            r"\s*::\s*(?:WriteAllText|WriteAllBytes|AppendAllText|"
            r"AppendAllLines|Create|CreateText|Delete|Move|Copy|"
            r"CreateDirectory)\b"
            r")"
        )
        _weather_powershell_protected_reference_parts = [
            r"WEATHER_INTEGRATION_TEST_(?:PRODUCTION|CANDIDATE|EVIDENCE)_ROOT"
        ]
        for _weather_protected_text in (
            _production_root_text,
            _candidate_root_text,
            _evidence_root_text,
        ):
            if _weather_protected_text:
                _weather_powershell_protected_reference_parts.append(
                    re.escape(_weather_protected_text)
                )
        _weather_powershell_protected_reference = re.compile(
            "(?:" + "|".join(_weather_powershell_protected_reference_parts) + ")",
            re.IGNORECASE,
        )
        _weather_popen_audit_state = threading.local()

        def _weather_scan_powershell_payload(payload, *, label):
            if _weather_powershell_external_io.search(payload):
                raise RuntimeError(
                    f"{label} contains external-I/O or credential tooling forbidden "
                    "by the integration-test offline boundary"
                )
            if _weather_powershell_sensitive_store.search(payload):
                raise RuntimeError(
                    f"{label} contains a secret file or credential-store reference "
                    "forbidden by the integration-test offline boundary"
                )
            scheduler_payload = _weather_powershell_scheduler_function_mock.sub(
                "", payload
            )
            if (
                _weather_powershell_scheduler_mutation.search(scheduler_payload)
                and not _weather_powershell_scheduler_guard.search(payload)
            ):
                raise RuntimeError(
                    f"{label} contains Scheduler mutation without the canonical "
                    "offline Scheduler guard"
                )
            if _weather_powershell_dynamic_creation.search(payload):
                raise RuntimeError(
                    f"{label} contains encoded or dynamic PowerShell creation "
                    "forbidden by the integration-test offline boundary"
                )
            if (
                _weather_powershell_invoke_expression.search(payload)
                and not _weather_powershell_ast_fixture.search(payload)
            ):
                raise RuntimeError(
                    f"{label} contains unreviewed dynamic PowerShell evaluation "
                    "forbidden by the integration-test offline boundary"
                )
            if (
                _weather_powershell_add_type.search(payload)
                and not _weather_powershell_job_add_type_fixture.search(payload)
            ):
                raise RuntimeError(
                    f"{label} contains unreviewed Add-Type execution forbidden by "
                    "the integration-test offline boundary"
                )
            if (
                _weather_powershell_file_mutation.search(payload)
                and _weather_powershell_protected_reference.search(payload)
            ):
                raise RuntimeError(
                    f"{label} contains direct protected-root mutation forbidden by "
                    "the integration-test offline boundary"
                )

        _weather_git_network_commands = {
            "archive",
            "clone",
            "credential",
            "credential-cache",
            "credential-store",
            "daemon",
            "fetch",
            "http-backend",
            "lfs",
            "ls-remote",
            "p4",
            "pull",
            "push",
            "receive-pack",
            "request-pull",
            "send-email",
            "submodule",
            "svn",
            "upload-archive",
            "upload-pack",
        }
        _weather_git_protected_read_commands = {
            "cat-file",
            "check-attr",
            "check-ignore",
            "describe",
            "for-each-ref",
            "ls-files",
            "ls-tree",
            "merge-base",
            "name-rev",
            "rev-parse",
            "status",
        }
        _weather_git_local_commands = _weather_git_protected_read_commands | {
            "add",
            "branch",
            "commit",
            "commit-tree",
            "config",
            "diff",
            "init",
            "remote",
            "rev-list",
            "show-ref",
            "update-ref",
            "worktree",
        }
        _weather_git_safe_config_overrides = {
            "commit.gpgsign=false",
            "core.fsmonitor=false",
            "core.hookspath=nul",
            "core.hookspath=/dev/null",
            "tag.gpgsign=false",
        }
        _weather_git_redirect_options = {
            "--config-env",
            "--exec-path",
            "--git-dir",
            "--namespace",
            "--super-prefix",
            "--work-tree",
        }
        _weather_git_fixture_config_values = {
            "filter.lfs.clean": {"git-lfs clean -- %f"},
            "filter.lfs.smudge": {"git-lfs smudge -- %f"},
            "filter.lfs.process": {"git-lfs filter-process"},
            "filter.lfs.required": {"true", "false"},
            "lfs.repositoryformatversion": {"0"},
        }
        _weather_git_external_config_section = re.compile(
            r"(?im)^\s*\[\s*(?:alias|credential|filter|diff|difftool|"
            r"mergetool|include|includeif|gpg|pager|interactive|merge|rebase)"
            r"(?:\s|\]|\")"
        )
        _weather_git_external_config_key = re.compile(
            r"(?im)^\s*(?:editor|pager|askpass|sshcommand|gitproxy|hookspath|"
            r"fsmonitor|attributesfile|difffilter|command|textconv|clean|smudge|"
            r"process|helper|program)\s*="
        )
        _weather_git_forbidden_execution_options = {
            "--ext-diff",
            "--filters",
            "--output",
            "--textconv",
        }

        def _weather_git_effective_target(tokens, working_directory):
            try:
                initial_directory = os.fsdecode(
                    working_directory if working_directory is not None else os.getcwd()
                )
            except (TypeError, ValueError):
                raise RuntimeError(
                    "Git child working directory is not an inspectable path"
                ) from None
            directory_paths = _weather_normalized_path(initial_directory)
            if directory_paths is None:
                raise RuntimeError("Git child working directory is unavailable")
            git_directory = directory_paths[1]
            overrides = []
            index = 1
            command_name = None
            command_index = None
            while index < len(tokens):
                token = tokens[index]
                folded = token.casefold()
                if token == "-C":
                    if index + 1 >= len(tokens) or not tokens[index + 1]:
                        raise RuntimeError("Git -C requires one inspectable directory")
                    changed_paths = _weather_normalized_path(
                        tokens[index + 1], base=git_directory
                    )
                    if changed_paths is None:
                        raise RuntimeError("Git -C directory is unavailable")
                    git_directory = changed_paths[1]
                    index += 2
                    continue
                if token == "-c":
                    if index + 1 >= len(tokens):
                        raise RuntimeError("Git -c requires one reviewed override")
                    overrides.append(tokens[index + 1])
                    index += 2
                    continue
                if any(
                    folded == option or folded.startswith(option + "=")
                    for option in _weather_git_redirect_options
                ):
                    raise RuntimeError(
                        "Git repository/config/executable redirects are forbidden by the "
                        "integration-test offline boundary"
                    )
                if folded in {
                    "--literal-pathspecs",
                    "--no-pager",
                    "--no-replace-objects",
                    "--version",
                    "--help",
                }:
                    if folded in {"--version", "--help"}:
                        command_name = folded
                        command_index = index
                        index += 1
                        break
                    index += 1
                    continue
                if token.startswith("-"):
                    raise RuntimeError(
                        "Git global options are outside the reviewed offline grammar"
                    )
                command_name = folded
                command_index = index
                index += 1
                break
            if command_name is None or command_index is None:
                raise RuntimeError("Git child is missing one explicit command")

            for override in overrides:
                folded_override = override.casefold()
                identity_override = folded_override.startswith(
                    ("user.name=", "user.email=")
                )
                if (
                    folded_override not in _weather_git_safe_config_overrides
                    and not identity_override
                ):
                    raise RuntimeError(
                        "Git -c override is outside the reviewed offline grammar"
                    )
                if identity_override and (
                    "\r" in override
                    or "\n" in override
                    or len(override.encode("utf-8")) > 384
                    or not override.split("=", 1)[1]
                ):
                    raise RuntimeError(
                        "Git identity override is missing or unbounded"
                    )

            command_arguments = tokens[index:]
            target = git_directory
            if command_name == "init":
                operands = []
                option_index = 0
                while option_index < len(command_arguments):
                    argument = command_arguments[option_index]
                    folded_argument = argument.casefold()
                    if folded_argument in {"--separate-git-dir", "--template"}:
                        raise RuntimeError(
                            "Git init path redirects are forbidden by the offline boundary"
                        )
                    if folded_argument in {
                        "-b",
                        "--initial-branch",
                        "--object-format",
                        "--ref-format",
                        "--shared",
                    }:
                        if option_index + 1 >= len(command_arguments):
                            raise RuntimeError("Git init option is missing its value")
                        option_index += 2
                        continue
                    if any(
                        folded_argument.startswith(prefix)
                        for prefix in (
                            "--initial-branch=",
                            "--object-format=",
                            "--ref-format=",
                            "--shared=",
                        )
                    ) or folded_argument in {"--bare", "-q", "--quiet"}:
                        option_index += 1
                        continue
                    if argument.startswith("-"):
                        raise RuntimeError(
                            "Git init options are outside the reviewed offline grammar"
                        )
                    operands.append(argument)
                    option_index += 1
                if len(operands) > 1:
                    raise RuntimeError("Git init has more than one target directory")
                if operands:
                    target_paths = _weather_normalized_path(
                        operands[0], base=git_directory
                    )
                    if target_paths is None:
                        raise RuntimeError("Git init target is unavailable")
                    target = target_paths[1]
            elif command_name == "config":
                for option_index, argument in enumerate(command_arguments):
                    folded_argument = argument.casefold()
                    if folded_argument in {"--global", "--system"}:
                        raise RuntimeError(
                            "Git config global/system mutation is forbidden by the "
                            "integration-test offline boundary"
                        )
                    if folded_argument == "--file":
                        if option_index + 1 >= len(command_arguments):
                            raise RuntimeError("Git config --file is missing its path")
                        target_paths = _weather_normalized_path(
                            command_arguments[option_index + 1], base=git_directory
                        )
                        if target_paths is None:
                            raise RuntimeError("Git config file target is unavailable")
                        target = target_paths[1]
                    elif folded_argument.startswith("--file="):
                        target_paths = _weather_normalized_path(
                            argument.split("=", 1)[1], base=git_directory
                        )
                        if target_paths is None:
                            raise RuntimeError("Git config file target is unavailable")
                        target = target_paths[1]

            return (
                command_name,
                command_arguments,
                target,
                overrides,
                command_index,
            )

        def _weather_git_bounded_control_text(path, *, label, maximum_bytes=1048576):
            path_text = os.fsdecode(path)
            if _weather_path_is_protected(path_text):
                raise RuntimeError(
                    f"{label} resolves into a protected repository"
                )
            try:
                before = os.stat(path_text)
                if not os.path.isfile(path_text) or before.st_size > maximum_bytes:
                    raise RuntimeError(
                        f"{label} is not one bounded regular file"
                    )
                payload = Path(path_text).read_text(encoding="utf-8-sig")
                after = os.stat(path_text)
            except (OSError, UnicodeError) as error:
                raise RuntimeError(
                    f"{label} is not stable strict UTF-8"
                ) from error
            before_identity = (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
            )
            after_identity = (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
            )
            if before_identity != after_identity:
                raise RuntimeError(f"{label} changed during offline validation")
            return payload

        def _weather_git_resolved_control_path(value, *, base, label):
            paths = _weather_normalized_path(value, base=base)
            if paths is None or _weather_path_is_protected(paths[1]):
                raise RuntimeError(f"{label} is outside the local test boundary")
            return paths[1]

        def _weather_git_repository_config_paths(target):
            root = Path(target)
            dot_git = root / ".git"
            git_directory = None
            if dot_git.is_dir():
                git_directory = _weather_git_resolved_control_path(
                    dot_git, base=root, label="Git control directory"
                )
            elif dot_git.is_file():
                pointer = _weather_git_bounded_control_text(
                    dot_git, label="Git worktree pointer", maximum_bytes=8192
                ).strip()
                if (
                    not pointer.casefold().startswith("gitdir:")
                    or "\n" in pointer
                    or "\r" in pointer
                ):
                    raise RuntimeError("Git worktree pointer is malformed")
                git_directory = _weather_git_resolved_control_path(
                    pointer.split(":", 1)[1].strip(),
                    base=dot_git.parent,
                    label="Git worktree control directory",
                )
            elif (root / "HEAD").is_file() and (root / "objects").is_dir():
                git_directory = _weather_git_resolved_control_path(
                    root, base=root, label="bare Git control directory"
                )
            if git_directory is None:
                return ()

            git_directory_path = Path(git_directory)
            common_directory = git_directory
            common_pointer = git_directory_path / "commondir"
            if common_pointer.is_file():
                common_value = _weather_git_bounded_control_text(
                    common_pointer,
                    label="Git common-directory pointer",
                    maximum_bytes=8192,
                ).strip()
                if not common_value or "\n" in common_value or "\r" in common_value:
                    raise RuntimeError("Git common-directory pointer is malformed")
                common_directory = _weather_git_resolved_control_path(
                    common_value,
                    base=git_directory,
                    label="Git common control directory",
                )
            candidates = {
                str(Path(git_directory) / "config"),
                str(Path(git_directory) / "config.worktree"),
                str(Path(common_directory) / "config"),
                str(Path(common_directory) / "config.worktree"),
            }
            return tuple(sorted(path for path in candidates if os.path.exists(path)))

        def _weather_assert_git_no_external_config(target):
            for config_path in _weather_git_repository_config_paths(target):
                payload = _weather_git_bounded_control_text(
                    config_path, label="Git local configuration"
                )
                if (
                    _weather_git_external_config_section.search(payload)
                    or _weather_git_external_config_key.search(payload)
                ):
                    raise RuntimeError(
                        "Git command refused external-execution Git configuration "
                        "before child launch"
                    )

        def _weather_git_safe_text(value, *, maximum_bytes):
            return (
                bool(value)
                and "\x00" not in value
                and "\r" not in value
                and "\n" not in value
                and len(value.encode("utf-8")) <= maximum_bytes
            )

        def _weather_validate_git_config_arguments(arguments):
            values = list(arguments)
            index = 0
            scope = "local"
            if values and values[0].casefold() == "--local":
                index = 1
            elif values and values[0].casefold() == "--file":
                if len(values) < 2:
                    raise RuntimeError("Git config --file is missing its path")
                scope = "fixture-file"
                index = 2
            elif values and values[0].casefold().startswith("--file="):
                scope = "fixture-file"
                index = 1
            if len(values[index:]) != 2:
                raise RuntimeError(
                    "Git config is restricted to one reviewed fixture key/value write"
                )
            key, value = values[index:]
            folded_key = key.casefold()
            if not _weather_git_safe_text(key, maximum_bytes=1024) or not (
                _weather_git_safe_text(value, maximum_bytes=4096)
            ):
                raise RuntimeError("Git config key/value is not bounded text")

            allowed = False
            if folded_key in {"user.name", "user.email"} and scope == "local":
                allowed = len(value.encode("utf-8")) <= 320
            elif re.fullmatch(
                r"remote\.[A-Za-z0-9._-]+\.(?:url|pushurl)", folded_key
            ):
                allowed = scope == "local" and not value.startswith("-")
            elif re.fullmatch(
                r"url\..+\.(?:insteadof|pushinsteadof)", folded_key
            ):
                allowed = not value.startswith("-")
            elif folded_key in _weather_git_fixture_config_values:
                allowed = (
                    scope == "local"
                    and value in _weather_git_fixture_config_values[folded_key]
                )
            if not allowed:
                raise RuntimeError(
                    "Git config key/value is outside the reviewed inert fixture grammar"
                )

        def _weather_git_safe_ref(value):
            return bool(
                value
                and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", value)
                and ".." not in value
                and "//" not in value
                and "@{" not in value
                and not value.endswith((".", "/"))
            )

        def _weather_validate_git_commit_arguments(arguments):
            index = 0
            message_supplied = False
            while index < len(arguments):
                argument = arguments[index]
                folded = argument.casefold()
                if folded in {"-q", "--quiet", "--allow-empty"}:
                    index += 1
                    continue
                if folded in {"-m", "--message", "-qm", "-mq"}:
                    if index + 1 >= len(arguments) or not _weather_git_safe_text(
                        arguments[index + 1], maximum_bytes=16384
                    ):
                        raise RuntimeError("Git commit message is missing or unbounded")
                    message_supplied = True
                    index += 2
                    continue
                if folded.startswith("-m") and len(argument) > 2:
                    if not _weather_git_safe_text(argument[2:], maximum_bytes=16384):
                        raise RuntimeError("Git commit message is missing or unbounded")
                    message_supplied = True
                    index += 1
                    continue
                raise RuntimeError(
                    "Git commit options are outside the noninteractive offline grammar"
                )
            if not message_supplied:
                raise RuntimeError(
                    "Git commit requires an inline message so no editor can launch"
                )

        def _weather_validate_git_command(tokens, *, working_directory):
            (
                command_name,
                command_arguments,
                target,
                overrides,
                command_index,
            ) = _weather_git_effective_target(tokens, working_directory)
            if command_name in {"--help", "--version"}:
                return command_name, command_index
            if command_name in _weather_git_network_commands:
                raise RuntimeError(
                    "Git network, credential, helper, or filter commands are forbidden by "
                    "the integration-test offline boundary"
                )
            if command_name not in _weather_git_local_commands:
                raise RuntimeError(
                    "Git command outside the reviewed local-only grammar is forbidden"
                )
            if any(
                argument.casefold() in _weather_git_forbidden_execution_options
                or argument.casefold().startswith("--output=")
                for argument in command_arguments
            ):
                raise RuntimeError(
                    "Git executable, filter, textconv, or output options are forbidden"
                )

            target_is_protected = _weather_path_is_protected(target)
            if target_is_protected:
                if command_name == "branch":
                    if command_arguments != ["--show-current"]:
                        raise RuntimeError(
                            "Git mutation of a protected repository is forbidden by the "
                            "integration-test offline boundary"
                        )
                elif command_name not in _weather_git_protected_read_commands:
                    raise RuntimeError(
                        "Git mutation of a protected repository is forbidden by the "
                        "integration-test offline boundary"
                    )
                if any(
                    override.casefold().startswith(("user.name=", "user.email="))
                    for override in overrides
                ):
                    raise RuntimeError(
                        "Git identity overrides are forbidden for protected repositories"
                    )
                return command_name, command_index

            if command_name == "config":
                _weather_validate_git_config_arguments(command_arguments)
                return command_name, command_index
            if command_name == "remote":
                folded = [argument.casefold() for argument in command_arguments]
                if folded == ["-v"]:
                    return command_name, command_index
                if (
                    len(command_arguments) == 2
                    and folded[0] == "get-url"
                    and _weather_git_safe_ref(command_arguments[1])
                ):
                    return command_name, command_index
                if (
                    len(command_arguments) == 3
                    and folded[0] == "add"
                    and _weather_git_safe_ref(command_arguments[1])
                    and _weather_git_safe_text(
                        command_arguments[2], maximum_bytes=4096
                    )
                    and not command_arguments[2].startswith("-")
                ):
                    return command_name, command_index
                raise RuntimeError(
                    "Git remote action outside the reviewed non-contact grammar is forbidden"
                )
            if command_name == "commit":
                _weather_assert_git_no_external_config(target)
                _weather_validate_git_commit_arguments(command_arguments)
            elif command_name == "add":
                _weather_assert_git_no_external_config(target)
                path_arguments = [
                    argument for argument in command_arguments if argument != "--"
                ]
                if not path_arguments or any(
                    argument.startswith(("-", ":")) for argument in path_arguments
                ):
                    raise RuntimeError(
                        "Git add is restricted to explicit ordinary path operands"
                    )
            elif command_name == "diff":
                _weather_assert_git_no_external_config(target)
            elif command_name == "status":
                # Even a nominally read-only status walk may invoke a clean
                # filter for a path whose stat information changed.  Temp
                # fixtures therefore receive the same pre-launch config
                # inspection as add/commit/diff.  Protected repositories are
                # handled above and remain read-only; their retained
                # toolchain/config proof is owned by the bounded host runner.
                _weather_assert_git_no_external_config(target)
            elif command_name == "branch":
                if command_arguments == ["--show-current"]:
                    return command_name, command_index
                if (
                    len(command_arguments) != 2
                    or not _weather_git_safe_ref(command_arguments[0])
                    or not (
                        _weather_git_safe_ref(command_arguments[1])
                        or re.fullmatch(r"[0-9a-fA-F]{40,64}", command_arguments[1])
                    )
                ):
                    raise RuntimeError(
                        "Git branch is restricted to one explicit local ref creation"
                    )
            elif command_name == "worktree":
                _weather_assert_git_no_external_config(target)
                if (
                    len(command_arguments) != 3
                    or command_arguments[0].casefold() != "add"
                    or command_arguments[1].startswith("-")
                    or not (
                        _weather_git_safe_ref(command_arguments[2])
                        or re.fullmatch(r"[0-9a-fA-F]{40,64}", command_arguments[2])
                    )
                ):
                    raise RuntimeError(
                        "Git worktree is restricted to one explicit local checkout"
                    )
            elif command_name == "update-ref":
                if (
                    len(command_arguments) not in {2, 3}
                    or not command_arguments[0].startswith("refs/")
                    or not _weather_git_safe_ref(command_arguments[0])
                    or any(
                        re.fullmatch(r"[0-9a-fA-F]{40,64}", value) is None
                        for value in command_arguments[1:]
                    )
                ):
                    raise RuntimeError(
                        "Git update-ref is outside the reviewed local fixture grammar"
                    )
            elif command_name == "commit-tree":
                if (
                    len(command_arguments) < 1
                    or re.fullmatch(
                        r"[0-9a-fA-F]{40,64}", command_arguments[0]
                    )
                    is None
                ):
                    raise RuntimeError("Git commit-tree requires one exact tree")
                index = 1
                while index < len(command_arguments):
                    if (
                        command_arguments[index] != "-p"
                        or index + 1 >= len(command_arguments)
                        or re.fullmatch(
                            r"[0-9a-fA-F]{40,64}", command_arguments[index + 1]
                        )
                        is None
                    ):
                        raise RuntimeError(
                            "Git commit-tree options are outside the reviewed grammar"
                        )
                    index += 2

            for argument in command_arguments:
                if not argument or argument.startswith("-") or "://" in argument:
                    continue
                try:
                    if _weather_path_is_protected(argument, base=target):
                        raise RuntimeError(
                            "Git arguments may not address a protected repository path"
                        )
                except (OSError, ValueError):
                    raise RuntimeError("Git path argument is not inspectable") from None
            return command_name, command_index

        def _weather_validate_process_command(
            command, explicit_executable=None, working_directory=None
        ):
            if not isinstance(command, (list, tuple)) or not command:
                raise RuntimeError(
                    "opaque subprocess argument forms are forbidden by the "
                    "integration-test offline boundary"
                )
            try:
                tokens = [os.fsdecode(value) for value in command]
            except (TypeError, ValueError):
                raise RuntimeError(
                    "non-text subprocess arguments are forbidden by the "
                    "integration-test offline boundary"
                ) from None
            if any("\x00" in token for token in tokens):
                raise RuntimeError(
                    "NUL-bearing subprocess arguments are forbidden by the "
                    "integration-test offline boundary"
                )
            command_path = _weather_located_executable(tokens[0])
            command_executable = _weather_resolved_executable(command_path)
            actual_executable = (
                _weather_resolved_executable(explicit_executable)
                if explicit_executable is not None
                else command_executable
            )
            if (
                command_executable is None
                or actual_executable is None
                or command_executable != actual_executable
                or actual_executable not in _weather_allowed_executables
            ):
                raise RuntimeError(
                    "subprocess executable is not in the exact offline test allowlist"
                )
            kind = _weather_allowed_executables[actual_executable]
            if kind == "python":
                for argument in tokens[1:]:
                    if re.fullmatch(r"-[A-Za-z]*[EIS][A-Za-z]*", argument):
                        raise RuntimeError(
                            "Python child flags that disable the tracked "
                            "integration-test bootstrap are forbidden"
                        )
            elif kind == "git":
                _weather_validate_git_command(
                    tokens, working_directory=working_directory
                )
            elif kind == "powershell":
                index = 1
                entry_kind = None
                entry_value = None
                while index < len(tokens):
                    option = tokens[index].casefold()
                    if option in {"-noprofile", "-noninteractive", "-nologo"}:
                        index += 1
                        continue
                    if option == "-executionpolicy":
                        if (
                            index + 1 >= len(tokens)
                            or tokens[index + 1].casefold() != "bypass"
                        ):
                            raise RuntimeError(
                                "PowerShell execution-policy arguments are not approved "
                                "by the integration-test offline boundary"
                            )
                        index += 2
                        continue
                    if option in {"-command", "-file"}:
                        if index + 1 >= len(tokens):
                            raise RuntimeError(
                                "PowerShell child is missing its reviewed command or file"
                            )
                        entry_kind = option
                        entry_value = tokens[index + 1]
                        index += 2
                        break
                    raise RuntimeError(
                        "PowerShell child options are outside the reviewed offline grammar"
                    )
                if entry_kind is None:
                    raise RuntimeError(
                        "PowerShell child must use an explicit -Command or -File entrypoint"
                    )
                if entry_kind == "-command":
                    if index != len(tokens):
                        raise RuntimeError(
                            "PowerShell -Command must be one inspectable argument"
                        )
                    if len(entry_value.encode("utf-8")) > 2 * 1024 * 1024:
                        raise RuntimeError(
                            "PowerShell -Command exceeds the offline review bound"
                        )
                    _weather_scan_powershell_payload(
                        entry_value, label="PowerShell command"
                    )
                else:
                    script_path = os.path.realpath(os.path.abspath(entry_value))
                    if (
                        not script_path.casefold().endswith(".ps1")
                        or not os.path.isfile(script_path)
                    ):
                        raise RuntimeError(
                            "PowerShell -File entrypoint is not a regular .ps1 file"
                        )
                    if os.path.getsize(script_path) > 2 * 1024 * 1024:
                        raise RuntimeError(
                            "PowerShell -File entrypoint exceeds the offline review bound"
                        )
                    try:
                        script_payload = Path(script_path).read_text(
                            encoding="utf-8-sig"
                        )
                    except (OSError, UnicodeError) as error:
                        raise RuntimeError(
                            "PowerShell -File entrypoint is not stable strict UTF-8"
                        ) from error
                    _weather_scan_powershell_payload(
                        script_payload, label="PowerShell script"
                    )
            return command_path

        # A test can supply a replacement ``env`` mapping to subprocess APIs.
        # Keep the inherited offline and local-only Git boundary sticky across
        # that process edge even when the test deliberately clears or replaces
        # its own environment after interpreter startup.
        if not getattr(subprocess.Popen, "_weather_offline_children", False):
            _offline_original_popen = subprocess.Popen
            _OFFLINE_CHILD_ENV = {
                "WEATHER_INTEGRATION_TEST_OFFLINE": "1",
                _OFFLINE_BOOTSTRAP_READY_ENV: "1",
                "GIT_ALLOW_PROTOCOL": "file",
                "GIT_TERMINAL_PROMPT": "0",
                "GIT_PROTOCOL_FROM_USER": "0",
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_SYSTEM": os.devnull,
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_CONFIG_COUNT": "0",
                "GIT_ATTR_NOSYSTEM": "1",
                "GIT_OPTIONAL_LOCKS": "0",
                "PYTHONNOUSERSITE": "1",
                "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONHASHSEED": "0",
                "PYTHONUTF8": "1",
                "PYTHONIOENCODING": "utf-8",
                "PYTHONPATH": os.pathsep.join(
                    (str(_REPO_ROOT), str(_SRC_ROOT))
                ),
            }
            for _weather_kind, _weather_path in (
                ("python", _weather_current_python),
                ("git", _weather_git_executable),
                ("powershell", _weather_powershell_executable),
            ):
                if _weather_path is not None:
                    _OFFLINE_CHILD_ENV[
                        _weather_executable_environment[_weather_kind]
                    ] = _weather_path
            if _production_root_text:
                _OFFLINE_CHILD_ENV.update(
                    {
                        "WEATHER_INTEGRATION_TEST_PRODUCTION_ROOT":
                            _production_root_text,
                        "WEATHER_INTEGRATION_TEST_CANDIDATE_ROOT":
                            _candidate_root_text,
                        "WEATHER_INTEGRATION_TEST_READ_ONLY_PRODUCTION_PROBE":
                            "1" if _read_only_production_probe else "0",
                        "WEATHER_INTEGRATION_TEST_SECRET_POLICY":
                            _secret_policy,
                        "WEATHER_INTEGRATION_TEST_TEMP_POLICY":
                            _temp_policy,
                    }
                )
                if _evidence_root_text:
                    _OFFLINE_CHILD_ENV[
                        "WEATHER_INTEGRATION_TEST_EVIDENCE_ROOT"
                    ] = _evidence_root_text
                if _temp_policy == "system_temp_unique_v1":
                    for _weather_temp_name in ("TEMP", "TMP", "TMPDIR"):
                        _OFFLINE_CHILD_ENV[_weather_temp_name] = _temp_values[0]

            class _OfflineChildPopen(_offline_original_popen):
                _weather_offline_children = True

                def __init__(self, *popenargs, **kwargs):
                    command = (
                        popenargs[0]
                        if popenargs
                        else kwargs.get("args")
                    )
                    if kwargs.get("shell"):
                        raise RuntimeError(
                            "opaque shell subprocesses are forbidden by the "
                            "integration-test offline boundary"
                        )
                    if kwargs.get("executable") is not None:
                        raise RuntimeError(
                            "subprocess executable overrides are forbidden by the "
                            "integration-test offline boundary"
                        )
                    creation_flags = int(kwargs.get("creationflags") or 0)
                    breakaway_flag = int(
                        getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0x01000000)
                    )
                    if creation_flags & breakaway_flag:
                        raise RuntimeError(
                            "subprocess Job-breakaway flags are forbidden by the "
                            "integration-test offline boundary"
                        )
                    approved_executable = _weather_validate_process_command(
                        command, working_directory=kwargs.get("cwd")
                    )
                    approved_kind = _weather_allowed_executables[
                        _weather_resolved_executable(approved_executable)
                    ]
                    original_command = [os.fsdecode(value) for value in command]
                    original_tail = original_command[1:]
                    rewritten_command = [approved_executable]
                    if approved_kind == "git":
                        (
                            git_command_name,
                            _git_arguments,
                            _git_target,
                            _git_overrides,
                            git_command_index,
                        ) = _weather_git_effective_target(
                            original_command, kwargs.get("cwd")
                        )
                        if git_command_name == "diff":
                            # Git treats these as command options, so place
                            # them immediately after the located subcommand.
                            # They independently suppress local diff drivers
                            # and textconv even after the raw-config refusal.
                            original_tail[git_command_index:git_command_index] = [
                                "--no-ext-diff",
                                "--no-textconv",
                            ]
                        rewritten_command.extend(
                            [
                                "--no-pager",
                                "-c",
                                "core.fsmonitor=false",
                                "-c",
                                (
                                    "core.hooksPath=NUL"
                                    if os.name == "nt"
                                    else "core.hooksPath=/dev/null"
                                ),
                                "-c",
                                "commit.gpgSign=false",
                                "-c",
                                "tag.gpgSign=false",
                            ]
                        )
                    rewritten_command.extend(original_tail)
                    if popenargs:
                        popenargs = (rewritten_command,) + popenargs[1:]
                    else:
                        kwargs["args"] = rewritten_command
                    child_env = kwargs.get("env")
                    if child_env is None:
                        child_env = os.environ.copy()
                    else:
                        child_env = dict(child_env)
                    protected_names = {
                        name.casefold() for name in _OFFLINE_CHILD_ENV
                    }
                    child_env = {
                        key: value
                        for key, value in child_env.items()
                        if str(key).casefold() not in protected_names
                        and not _weather_secret_environment_name(key)
                        and not _weather_git_redirect_environment_name(key)
                    }
                    child_env.update(_OFFLINE_CHILD_ENV)
                    kwargs["env"] = child_env
                    prior_expected = getattr(
                        _weather_popen_audit_state,
                        "expected_executable",
                        None,
                    )
                    _weather_popen_audit_state.expected_executable = (
                        _weather_resolved_executable(approved_executable)
                    )
                    try:
                        super().__init__(*popenargs, **kwargs)
                    finally:
                        if prior_expected is None:
                            try:
                                del _weather_popen_audit_state.expected_executable
                            except AttributeError:
                                pass
                        else:
                            _weather_popen_audit_state.expected_executable = prior_expected

            subprocess.Popen = _OfflineChildPopen

        # Refuse alternate process APIs that cannot inherit the sticky child
        # environment through the Popen wrapper, and independently verify the
        # environment observed at the CPython subprocess audit boundary. This
        # closes cached-Popen and replacement-environment escape routes without
        # relying on every test to preserve process-global variables.
        _immutable_current_environment = {
            name.casefold(): value
            for name, value in _OFFLINE_CHILD_ENV.items()
            if os.environ.get(name) == value
        }
        _immutable_current_environment[
            _OFFLINE_BOOTSTRAP_READY_ENV.casefold()
        ] = "1"
        _required_child_environment = {
            name.casefold(): value for name, value in _OFFLINE_CHILD_ENV.items()
        }

        def _weather_environment_mapping(value):
            if value is None or not hasattr(value, "items"):
                return None
            normalized = {}
            for key, item in value.items():
                folded = os.fsdecode(key).casefold()
                if folded in normalized:
                    return None
                normalized[folded] = os.fsdecode(item)
            return normalized

        def _weather_process_boundary_audit(event, arguments):
            # Do not globally intercept os.kill/os.killpg here.  Signal 0 is a
            # required liveness probe, and POSIX qualification must terminate
            # the exact process groups created by run_isolated_subprocess.
            # Real operational signal owners call
            # require_real_external_io_allowed; arbitrary native signalling is
            # a documented residual because this layer is not an OS sandbox.
            if event in {
                "os.system",
                "os.spawn",
                "os.exec",
                "os.posix_spawn",
                "os.startfile",
                "os.startfile/2",
            }:
                raise RuntimeError(
                    "direct process APIs are forbidden by the integration-test "
                    "offline boundary; use guarded subprocess APIs"
                )
            if event == "subprocess.Popen":
                child_environment = (
                    _weather_environment_mapping(arguments[3])
                    if len(arguments) > 3
                    else None
                )
                if child_environment is None or any(
                    child_environment.get(name) != value
                    for name, value in _required_child_environment.items()
                ):
                    raise RuntimeError(
                        "subprocess environment escaped the integration-test "
                        "offline boundary"
                    )
                if any(
                    _weather_secret_environment_name(name)
                    for name in child_environment
                ):
                    raise RuntimeError(
                        "secret-bearing subprocess environment is forbidden by the "
                        "integration-test offline boundary"
                    )
                if any(
                    _weather_git_redirect_environment_name(name)
                    for name in child_environment
                ):
                    raise RuntimeError(
                        "Git redirect environment is forbidden by the "
                        "integration-test offline boundary"
                    )
                executable = arguments[0] if arguments else None
                command = arguments[1] if len(arguments) > 1 else None
                expected_executable = getattr(
                    _weather_popen_audit_state,
                    "expected_executable",
                    None,
                )
                if expected_executable is None:
                    # A caller using a cached original Popen receives no wrapper
                    # token. POSIX sequence arguments can still be validated;
                    # Windows has already rendered them into an opaque command
                    # line at this audit event and therefore fails closed.
                    _weather_validate_process_command(
                        command,
                        explicit_executable=executable,
                        working_directory=(arguments[2] if len(arguments) > 2 else None),
                    )
                else:
                    observed_executable = _weather_resolved_executable(executable)
                    if (
                        observed_executable is not None
                        and observed_executable != expected_executable
                    ):
                        raise RuntimeError(
                            "subprocess executable changed after offline validation"
                        )
                    if isinstance(command, (list, tuple)):
                        _weather_validate_process_command(
                            command,
                            explicit_executable=(
                                executable
                                if executable is not None
                                else command[0]
                            ),
                            working_directory=(
                                arguments[2] if len(arguments) > 2 else None
                            ),
                        )
            if event == "os.putenv" and len(arguments) >= 2:
                name = os.fsdecode(arguments[0]).casefold()
                expected = _immutable_current_environment.get(name)
                if expected is not None and os.fsdecode(arguments[1]) != expected:
                    raise RuntimeError(
                        "protected integration-test environment mutation is forbidden"
                    )
            if event == "os.unsetenv" and arguments:
                name = os.fsdecode(arguments[0]).casefold()
                if name in _immutable_current_environment:
                    raise RuntimeError(
                        "protected integration-test environment removal is forbidden"
                    )

        sys.addaudithook(_weather_process_boundary_audit)

        def _weather_socket_boundary_audit(event, _arguments):
            if event in {
                "socket.__new__",
                "socket.bind",
                "socket.connect",
                "socket.getaddrinfo",
                "socket.gethostbyaddr",
                "socket.gethostbyname",
                "socket.gethostbyname_ex",
                "socket.sendto",
            }:
                raise RuntimeError(
                    "network access is forbidden by the integration-test offline boundary"
                )

        sys.addaudithook(_weather_socket_boundary_audit)

        def _weather_blocked_external_io(*_args, **_kwargs):
            raise RuntimeError(
                "network access is forbidden by the integration-test offline boundary"
            )

        for _name in (
            "create_connection",
            "getaddrinfo",
            "gethostbyaddr",
            "gethostbyname",
            "gethostbyname_ex",
        ):
            if hasattr(socket, _name):
                setattr(socket, _name, _weather_blocked_external_io)
        for _name in ("connect", "connect_ex", "sendall", "sendmsg", "sendto"):
            if hasattr(socket.socket, _name):
                setattr(socket.socket, _name, _weather_blocked_external_io)
        os.environ[_OFFLINE_BOOTSTRAP_READY_ENV] = "1"
    except Exception as error:
        # CPython deliberately catches ordinary exceptions raised while loading
        # ``sitecustomize`` and then continues interpreter startup.  Raising
        # here would therefore be fail-open.  Terminate at the process boundary
        # so no test payload can run after a partial safety bootstrap.
        try:
            message = (
                "integration-test offline bootstrap failed closed: "
                f"{type(error).__name__}: {error}\n"
            )
            os.write(2, message.encode("utf-8", errors="backslashreplace"))
        finally:
            os._exit(78)

if os.name == "nt" and os.environ.get("WEATHER_ALLOW_CONSOLE_CHILDREN") != "1":
    _cpu_count = int(os.cpu_count() or 1)
    _safe_loky_count = max(1, _cpu_count - 1) if _cpu_count > 1 else 1
    try:
        _current_loky_count = int(os.environ.get("LOKY_MAX_CPU_COUNT", "0") or "0")
    except ValueError:
        _current_loky_count = 0
    if _current_loky_count <= 0 or _current_loky_count >= _cpu_count:
        os.environ["LOKY_MAX_CPU_COUNT"] = str(_safe_loky_count)

    try:
        import platform

        def _silent_syscmd_ver(system="", release="", version="", supported_platforms=None):
            return system, release, version

        platform._syscmd_ver = _silent_syscmd_ver
    except Exception:
        pass

    try:
        import subprocess

        if not getattr(subprocess.Popen, "_weather_silent_windows_children", False):
            _original_popen = subprocess.Popen

            class _SilentWindowsPopen(_original_popen):
                _weather_silent_windows_children = True

                def __init__(self, *popenargs, **kwargs):
                    try:
                        flags = int(kwargs.get("creationflags") or 0)
                        kwargs["creationflags"] = flags | subprocess.CREATE_NO_WINDOW
                    except Exception:
                        pass
                    super().__init__(*popenargs, **kwargs)

            subprocess.Popen = _SilentWindowsPopen
    except Exception:
        pass

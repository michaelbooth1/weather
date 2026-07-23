"""Deterministic execution-identity closures for research and replay jobs.

An execution identity binds code, artifacts, configuration, data inputs, and
the runtime environment as one serializable manifest.  Long jobs capture the
manifest before work, recapture it around cache admission/publication, and
fail closed if any byte, explicit absence, import, package, or selected
environment value changes.
"""

from __future__ import annotations

import ctypes
import errno
import hashlib
import importlib
import importlib.metadata
import json
import os
import platform
import secrets
import stat
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO, Callable, Literal, Mapping, Sequence


SCHEMA_VERSION = "execution_identity_manifest_v0.1"
PathExpectation = Literal[
    "required_file", "required_dir", "absent", "file_or_absent"
]
DEFAULT_ENV_NAMES = (
    "CUDA_VISIBLE_DEVICES",
    "LANG",
    "LC_ALL",
    "LOKY_MAX_CPU_COUNT",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "PATH",
    "PYTHONHOME",
    "PYTHONHASHSEED",
    "PYTHONPATH",
    "TZ",
    "VIRTUAL_ENV",
)


class ExecutionIdentityError(RuntimeError):
    """Base error for malformed or unstable execution identity."""


class ExecutionIdentityDriftError(ExecutionIdentityError):
    """Raised when a recaptured closure differs from its start manifest."""


class ExclusivePublicationError(ExecutionIdentityError):
    """Raised when one output leaf cannot be published without overwrite."""


@dataclass
class ExclusivePublication:
    """Evidence and optional held descriptor for one exact published leaf."""

    path: Path
    sha256: str
    size_bytes: int
    topology: tuple[int, ...]
    _descriptor: int | None = field(default=None, repr=False)

    @property
    def descriptor(self) -> int:
        if self._descriptor is None:
            raise ExclusivePublicationError(
                f"publication handle is not retained: {self.path}"
            )
        return self._descriptor

    def close(self) -> None:
        descriptor = self._descriptor
        self._descriptor = None
        if descriptor is not None:
            os.close(descriptor)


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def _payload_digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _json_copy(value: Any) -> Any:
    return json.loads(json.dumps(value, sort_keys=True, allow_nan=False))


def _is_hex_digest(value: object) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(character in "0123456789abcdef" for character in text)


def _stat_identity(value: os.stat_result) -> tuple[int, ...]:
    return (
        int(value.st_dev),
        int(value.st_ino),
        int(value.st_nlink),
        int(value.st_mode),
        int(value.st_size),
        int(value.st_mtime_ns),
        int(value.st_ctime_ns),
    )


def _open_target_identity(value: os.stat_result) -> tuple[int, ...]:
    """Comparable pathname/fstat identity (Windows alters permission bits)."""

    return (
        int(value.st_dev),
        int(value.st_ino),
        int(value.st_nlink),
        int(stat.S_IFMT(value.st_mode)),
        int(value.st_size),
        int(value.st_mtime_ns),
        int(value.st_ctime_ns),
    )


def _is_reparse_stat(value: os.stat_result) -> bool:
    attributes = int(getattr(value, "st_file_attributes", 0) or 0)
    marker = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0) or 0)
    return bool(marker and attributes & marker)


def _link_target(path: Path, value: os.stat_result) -> str | None:
    if not (stat.S_ISLNK(value.st_mode) or _is_reparse_stat(value)):
        return None
    try:
        return os.readlink(path)
    except OSError:
        return None


def _stable_file_record(path: Path) -> dict[str, Any]:
    """Hash one regular-file target and bind its link/physical topology.

    The two stat pairs reject target swaps or hard-link topology changes while
    hashing.  This does not claim to discover aliases outside the declared
    closure; start/end recapture still detects an alias-mediated byte or link
    change that remains visible at a gate.
    """

    before_link = path.lstat()
    before_target = path.stat()
    if not stat.S_ISREG(before_target.st_mode):
        raise ExecutionIdentityError(f"bound target is not a regular file: {path}")
    link_target = _link_target(path, before_link)
    digest = hashlib.sha256()
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0))
    with os.fdopen(descriptor, "rb", closefd=True) as handle:
        opened_before = os.fstat(handle.fileno())
        if _open_target_identity(opened_before) != _open_target_identity(before_target):
            raise ExecutionIdentityError(f"path target changed while opening: {path}")
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
        opened_after = os.fstat(handle.fileno())
    after_target = path.stat()
    after_link = path.lstat()
    after_link_target = _link_target(path, after_link)
    if (
        _stat_identity(before_target) != _stat_identity(after_target)
        or _stat_identity(opened_before) != _stat_identity(opened_after)
        or _open_target_identity(opened_after) != _open_target_identity(after_target)
        or _stat_identity(before_link) != _stat_identity(after_link)
        or link_target != after_link_target
    ):
        raise ExecutionIdentityError(f"file changed while hashing: {path}")
    return {
        "size_bytes": int(after_target.st_size),
        "sha256": digest.hexdigest(),
        "mtime_ns": int(after_target.st_mtime_ns),
        "ctime_ns": int(after_target.st_ctime_ns),
        "device": int(after_target.st_dev),
        "inode": int(after_target.st_ino),
        "hardlink_count": int(after_target.st_nlink),
        "link_target": after_link_target,
        "reparse_point": _is_reparse_stat(after_link),
    }


def _display_path(path: Path, base_root: Path) -> str:
    absolute = path.absolute()
    try:
        return absolute.relative_to(base_root).as_posix()
    except ValueError:
        return absolute.as_posix()


def _directory_topology_record(path: Path, base_root: Path) -> dict[str, Any]:
    link = path.lstat()
    target = path.stat()
    if not stat.S_ISDIR(target.st_mode):
        raise ExecutionIdentityError(f"bound target is not a directory: {path}")
    return {
        "resolved_path": _display_path(path.resolve(strict=True), base_root),
        "device": int(target.st_dev),
        "inode": int(target.st_ino),
        "mode": int(target.st_mode),
        "symlink": stat.S_ISLNK(link.st_mode),
        "reparse_point": _is_reparse_stat(link),
        "link_target": _link_target(path, link),
    }


def _absence_anchor(path: Path, base_root: Path) -> dict[str, Any]:
    existing = path.parent
    suffix = [path.name]
    while not os.path.lexists(existing):
        if existing == existing.parent:
            raise ExecutionIdentityError(f"cannot anchor absent path: {path}")
        suffix.insert(0, existing.name)
        existing = existing.parent
    if not existing.is_dir():
        raise ExecutionIdentityError(
            f"absent path has a non-directory existing parent: {path}: {existing}"
        )
    return {
        "existing_parent": _display_path(existing, base_root),
        "missing_suffix": "/".join(suffix),
        **{
            f"existing_parent_{key}": value
            for key, value in _directory_topology_record(existing, base_root).items()
        },
    }


@dataclass(frozen=True)
class PathBinding:
    label: str
    path: Path
    expectation: PathExpectation = "required_file"

    def __post_init__(self) -> None:
        if not self.label.strip():
            raise ValueError("path binding label must be nonempty")
        if self.expectation not in {
            "required_file",
            "required_dir",
            "absent",
            "file_or_absent",
        }:
            raise ValueError(f"invalid path expectation: {self.expectation}")
        object.__setattr__(self, "path", Path(self.path))


@dataclass(frozen=True)
class TreeBinding:
    label: str
    root: Path
    includes: tuple[str, ...] = ("**/*",)
    excludes: tuple[str, ...] = ()
    required: bool = True
    require_nonempty: bool = True

    def __post_init__(self) -> None:
        if not self.label.strip():
            raise ValueError("tree binding label must be nonempty")
        if not self.includes or any(not pattern for pattern in self.includes):
            raise ValueError("tree binding includes must be nonempty patterns")
        object.__setattr__(self, "root", Path(self.root))
        object.__setattr__(self, "includes", tuple(self.includes))
        object.__setattr__(self, "excludes", tuple(self.excludes))


@dataclass(frozen=True)
class EnvironmentSpec:
    import_names: tuple[str, ...] = ()
    env_names: tuple[str, ...] = DEFAULT_ENV_NAMES
    env_prefixes: tuple[str, ...] = ("WEATHER_",)
    include_packages: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "import_names", tuple(sorted(set(self.import_names))))
        object.__setattr__(self, "env_names", tuple(sorted(set(self.env_names))))
        object.__setattr__(self, "env_prefixes", tuple(sorted(set(self.env_prefixes))))
        if any(not value for value in self.import_names):
            raise ValueError("environment import names must be nonempty")
        if any(not value for value in (*self.env_names, *self.env_prefixes)):
            raise ValueError("environment names/prefixes must be nonempty")
        if not (
            self.include_packages
            or self.import_names
            or self.env_names
            or self.env_prefixes
        ):
            raise ValueError("environment specification binds no process state")


@dataclass(frozen=True)
class InvocationSpec:
    """Expected process invocation plus the effective parsed run contract."""

    cwd: Path
    argv: tuple[str, ...]
    run_parameters: Mapping[str, Any]

    def __post_init__(self) -> None:
        cwd = Path(self.cwd).resolve(strict=True)
        if not cwd.is_dir():
            raise ValueError("invocation cwd must be a directory")
        argv = tuple(self.argv)
        if not argv or not isinstance(argv[0], str) or not argv[0]:
            raise ValueError("invocation argv must contain a nonempty program name")
        if any(not isinstance(value, str) for value in argv):
            raise ValueError("invocation argv values must be strings")
        if not isinstance(self.run_parameters, Mapping) or not self.run_parameters:
            raise ValueError("invocation run_parameters must be a nonempty mapping")
        if any(not isinstance(key, str) or not key for key in self.run_parameters):
            raise ValueError("invocation run_parameter keys must be nonempty strings")
        try:
            run_parameters = _json_copy(dict(self.run_parameters))
        except (TypeError, ValueError) as exc:
            raise ValueError("invocation run_parameters must be finite JSON") from exc
        object.__setattr__(self, "cwd", cwd)
        object.__setattr__(self, "argv", argv)
        object.__setattr__(self, "run_parameters", run_parameters)

    @classmethod
    def current(cls, *, run_parameters: Mapping[str, Any]) -> "InvocationSpec":
        return cls(
            cwd=Path.cwd(),
            argv=tuple(sys.argv),
            run_parameters=run_parameters,
        )


@dataclass(frozen=True)
class ClosureSpec:
    name: str
    base_root: Path
    invocation: InvocationSpec
    path_bindings: tuple[PathBinding, ...] = ()
    tree_bindings: tuple[TreeBinding, ...] = ()
    environment: EnvironmentSpec = field(default_factory=EnvironmentSpec)

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("closure name must be nonempty")
        base_root = Path(self.base_root).resolve(strict=True)
        if not base_root.is_dir():
            raise ValueError("closure base_root must be a directory")
        if not isinstance(self.invocation, InvocationSpec):
            raise ValueError("closure invocation must be an InvocationSpec")
        path_bindings = tuple(
            PathBinding(
                binding.label,
                binding.path
                if binding.path.is_absolute()
                else base_root / binding.path,
                binding.expectation,
            )
            for binding in self.path_bindings
        )
        tree_bindings = tuple(
            TreeBinding(
                binding.label,
                binding.root
                if binding.root.is_absolute()
                else base_root / binding.root,
                binding.includes,
                binding.excludes,
                binding.required,
                binding.require_nonempty,
            )
            for binding in self.tree_bindings
        )
        object.__setattr__(self, "base_root", base_root)
        object.__setattr__(self, "path_bindings", path_bindings)
        object.__setattr__(self, "tree_bindings", tree_bindings)
        if not self.path_bindings and not self.tree_bindings:
            raise ValueError("execution closure must contain at least one binding")
        if not any(
            binding.expectation in {"required_file", "required_dir"}
            for binding in self.path_bindings
        ) and not any(binding.required for binding in self.tree_bindings):
            raise ValueError("execution closure must contain a required content binding")
        labels = [item.label for item in (*self.path_bindings, *self.tree_bindings)]
        if len(labels) != len(set(labels)):
            raise ValueError("execution-identity binding labels must be unique")


def _validate_sorted_unique(rows: Sequence[Mapping[str, Any]], field_name: str) -> None:
    values = [str(row.get(field_name) or "") for row in rows]
    if any(not value for value in values) or values != sorted(values):
        raise ExecutionIdentityError(f"manifest rows are not sorted by {field_name}")
    if len(values) != len(set(values)):
        raise ExecutionIdentityError(f"manifest has duplicate {field_name} values")


def _validate_identity_payload(identity: Mapping[str, Any]) -> None:
    if set(identity) != {
        "base_root",
        "bindings",
        "closure_name",
        "environment",
        "invocation",
    }:
        raise ExecutionIdentityError("manifest identity fields are malformed")
    if not str(identity.get("closure_name") or ""):
        raise ExecutionIdentityError("manifest closure_name is missing")
    bindings = identity.get("bindings")
    environment = identity.get("environment")
    invocation = identity.get("invocation")
    if (
        not isinstance(bindings, list)
        or not bindings
        or not isinstance(environment, Mapping)
        or not isinstance(invocation, Mapping)
    ):
        raise ExecutionIdentityError("manifest bindings/environment are malformed")
    _validate_sorted_unique(bindings, "label")
    if not any(
        binding.get("kind") == "tree"
        and binding.get("required") is True
        or binding.get("kind") == "path"
        and binding.get("expectation") in {"required_file", "required_dir"}
        for binding in bindings
    ):
        raise ExecutionIdentityError("manifest has no required content binding")
    for binding in bindings:
        if binding.get("kind") == "tree":
            files = binding.get("files")
            if not isinstance(files, list):
                raise ExecutionIdentityError("tree binding file inventory is malformed")
            _validate_sorted_unique(files, "relative_path")
            if (
                binding.get("state") == "directory"
                and binding.get("require_nonempty") is True
                and not files
            ):
                raise ExecutionIdentityError("required nonempty tree has no files")
        elif binding.get("kind") != "path":
            raise ExecutionIdentityError("manifest binding kind is malformed")
    if set(environment) != {"imports", "packages", "runtime", "selection", "variables"}:
        raise ExecutionIdentityError("environment inventory fields are malformed")
    packages = environment.get("packages")
    imports = environment.get("imports")
    variables = environment.get("variables")
    if not all(isinstance(value, list) for value in (packages, imports, variables)):
        raise ExecutionIdentityError("environment inventory is malformed")
    package_keys = [(str(row.get("name") or ""), str(row.get("version") or "")) for row in packages]
    if package_keys != sorted(package_keys):
        raise ExecutionIdentityError("package inventory is not canonical")
    _validate_sorted_unique(imports, "name")
    _validate_sorted_unique(variables, "name")
    if set(invocation) != {"argv", "cwd", "run_parameters"}:
        raise ExecutionIdentityError("invocation inventory fields are malformed")
    argv = invocation.get("argv")
    run_parameters = invocation.get("run_parameters")
    if (
        not isinstance(invocation.get("cwd"), str)
        or not invocation["cwd"]
        or not isinstance(argv, list)
        or not argv
        or any(not isinstance(value, str) for value in argv)
        or not isinstance(run_parameters, Mapping)
        or not run_parameters
    ):
        raise ExecutionIdentityError("invocation inventory is malformed")
    try:
        _canonical_json(run_parameters)
    except (TypeError, ValueError) as exc:
        raise ExecutionIdentityError("invocation run parameters are not finite JSON") from exc


@dataclass(frozen=True)
class ExecutionIdentityManifest:
    identity: dict[str, Any]
    identity_digest: str
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "identity": _json_copy(self.identity),
            "identity_digest": self.identity_digest,
        }

    @classmethod
    def from_dict(
        cls, raw: Mapping[str, Any], *, verify_digest: bool = True
    ) -> "ExecutionIdentityManifest":
        if not isinstance(raw, Mapping) or raw.get("schema_version") != SCHEMA_VERSION:
            raise ExecutionIdentityError("execution-identity schema mismatch")
        if set(raw) != {"schema_version", "identity", "identity_digest"}:
            raise ExecutionIdentityError("execution-identity envelope fields are malformed")
        identity = raw.get("identity")
        supplied_digest = str(raw.get("identity_digest") or "")
        if not isinstance(identity, Mapping) or not _is_hex_digest(supplied_digest):
            raise ExecutionIdentityError("execution-identity payload/digest is malformed")
        copied = _json_copy(identity)
        _validate_identity_payload(copied)
        observed = _payload_digest(copied)
        if verify_digest and observed != supplied_digest:
            raise ExecutionIdentityError("execution-identity digest does not match full manifest")
        return cls(identity=copied, identity_digest=observed)


def _capture_path(binding: PathBinding, base_root: Path) -> dict[str, Any]:
    path = binding.path.absolute()
    present = os.path.lexists(path)
    record: dict[str, Any] = {
        "label": binding.label,
        "kind": "path",
        "expectation": binding.expectation,
        "path": _display_path(path, base_root),
    }
    if not present:
        if binding.expectation in {"required_file", "required_dir"}:
            raise ExecutionIdentityError(f"required path is absent: {binding.label}: {path}")
        record["state"] = "absent"
        record["absence_anchor"] = _absence_anchor(path, base_root)
        return record
    if binding.expectation == "absent":
        raise ExecutionIdentityError(f"path required absent is present: {binding.label}: {path}")
    if path.is_file():
        if binding.expectation == "required_dir":
            raise ExecutionIdentityError(f"required directory is a file: {binding.label}: {path}")
        record.update({"state": "file", **_stable_file_record(path)})
    elif path.is_dir():
        if binding.expectation != "required_dir":
            raise ExecutionIdentityError(f"required file is a directory: {binding.label}: {path}")
        record.update({"state": "directory", **_directory_topology_record(path, base_root)})
    else:
        raise ExecutionIdentityError(f"bound path is not a regular file/directory: {path}")
    if path.is_file():
        link = path.lstat()
        record["resolved_path"] = _display_path(path.resolve(strict=True), base_root)
        record["symlink"] = stat.S_ISLNK(link.st_mode)
        record["reparse_point"] = _is_reparse_stat(link)
    return record


def _excluded(relative: Path, patterns: Sequence[str]) -> bool:
    return any(relative.match(pattern) for pattern in patterns)


def _enumerate_tree_candidates(binding: TreeBinding, root: Path) -> tuple[Path, ...]:
    candidates: set[Path] = set()
    for pattern in binding.includes:
        candidates.update(path for path in root.glob(pattern) if path.is_file())
    return tuple(
        path
        for path in sorted(
            candidates, key=lambda value: value.relative_to(root).as_posix()
        )
        if not _excluded(path.relative_to(root), binding.excludes)
    )


def _assert_tree_record_still_current(path: Path, row: Mapping[str, Any]) -> None:
    try:
        target = path.stat()
        link = path.lstat()
    except OSError as exc:
        raise ExecutionIdentityError(f"tree file changed after hashing: {path}") from exc
    observed = {
        "size_bytes": int(target.st_size),
        "mtime_ns": int(target.st_mtime_ns),
        "ctime_ns": int(target.st_ctime_ns),
        "device": int(target.st_dev),
        "inode": int(target.st_ino),
        "hardlink_count": int(target.st_nlink),
        "symlink": stat.S_ISLNK(link.st_mode),
        "reparse_point": _is_reparse_stat(link),
        "link_target": _link_target(path, link),
    }
    if any(row.get(key) != value for key, value in observed.items()):
        raise ExecutionIdentityError(f"tree file changed after hashing: {path}")


def _capture_tree(binding: TreeBinding, base_root: Path) -> dict[str, Any]:
    root = binding.root.absolute()
    record: dict[str, Any] = {
        "label": binding.label,
        "kind": "tree",
        "root": _display_path(root, base_root),
        "includes": list(binding.includes),
        "excludes": list(binding.excludes),
        "required": binding.required,
        "require_nonempty": binding.require_nonempty,
    }
    if not os.path.lexists(root):
        if binding.required:
            raise ExecutionIdentityError(f"required tree root is absent: {binding.label}: {root}")
        record.update({"state": "absent", "files": [], "file_count": 0, "size_bytes": 0})
        record["tree_digest"] = _payload_digest({"state": "absent", "files": []})
        return record
    if not root.is_dir():
        raise ExecutionIdentityError(f"tree root is not a directory: {binding.label}: {root}")
    candidates = _enumerate_tree_candidates(binding, root)
    rows = []
    for path in candidates:
        relative = path.relative_to(root)
        rows.append(
            {
                "relative_path": relative.as_posix(),
                "resolved_path": _display_path(path.resolve(strict=True), base_root),
                "symlink": path.is_symlink(),
                **_stable_file_record(path),
            }
        )
    completion_candidates = _enumerate_tree_candidates(binding, root)
    if tuple(path.relative_to(root) for path in candidates) != tuple(
        path.relative_to(root) for path in completion_candidates
    ):
        raise ExecutionIdentityError(
            f"tree candidate inventory changed while hashing: {binding.label}: {root}"
        )
    for path, row in zip(candidates, rows):
        _assert_tree_record_still_current(path, row)
    if binding.require_nonempty and not rows:
        raise ExecutionIdentityError(
            f"tree binding matched no files: {binding.label}: {root}"
        )
    record.update(
        {
            "state": "directory",
            "root_topology": _directory_topology_record(root, base_root),
            "files": rows,
            "file_count": len(rows),
            "size_bytes": sum(int(row["size_bytes"]) for row in rows),
            "tree_digest": _payload_digest({"state": "directory", "files": rows}),
        }
    )
    return record


def _capture_packages() -> list[dict[str, str]]:
    rows = []
    for distribution in importlib.metadata.distributions():
        name = str(distribution.metadata.get("Name") or "").strip()
        version = str(distribution.version or "").strip()
        if name:
            rows.append({"name": name.casefold(), "version": version})
    return sorted(rows, key=lambda row: (row["name"], row["version"]))


def _capture_import(name: str, base_root: Path) -> dict[str, Any]:
    module = importlib.import_module(name)
    raw_file = getattr(module, "__file__", None)
    row: dict[str, Any] = {
        "name": name,
        "version": str(getattr(module, "__version__", "") or ""),
        "path_entries": sorted(
            _display_path(Path(value), base_root)
            for value in (getattr(module, "__path__", None) or [])
        ),
    }
    if raw_file and Path(raw_file).is_file():
        path = Path(raw_file)
        row.update(
            {
                "file": _display_path(path, base_root),
                "resolved_file": _display_path(path.resolve(strict=True), base_root),
                **_stable_file_record(path),
            }
        )
    else:
        row.update({"file": None, "resolved_file": None, "size_bytes": None, "sha256": None})
    return row


def _capture_environment(spec: EnvironmentSpec, base_root: Path) -> dict[str, Any]:
    names = set(spec.env_names)
    names.update(
        name
        for name in os.environ
        if any(name.startswith(prefix) for prefix in spec.env_prefixes)
    )
    variables = []
    for name in sorted(names):
        present = name in os.environ
        value = os.environ.get(name, "")
        variables.append(
            {
                "name": name,
                "present": present,
                "value_sha256": hashlib.sha256(value.encode("utf-8")).hexdigest()
                if present
                else None,
            }
        )
    implementation_version = sys.implementation.version
    runtime = {
        "byteorder": sys.byteorder,
        "default_encoding": sys.getdefaultencoding(),
        "executable": Path(sys.executable).resolve(strict=True).as_posix(),
        "filesystem_encoding": sys.getfilesystemencoding(),
        "implementation": sys.implementation.name,
        "implementation_cache_tag": sys.implementation.cache_tag,
        "implementation_version": list(implementation_version),
        "machine": platform.machine(),
        "maxsize": sys.maxsize,
        "platform": platform.platform(),
        "prefix": Path(sys.prefix).resolve(strict=True).as_posix(),
        "base_prefix": Path(sys.base_prefix).resolve(strict=True).as_posix(),
        "python_version": platform.python_version(),
        "sys_path": [
            {
                "raw": value,
                "resolved": _display_path(
                    (Path.cwd() if value == "" else Path(value)).resolve(strict=False),
                    base_root,
                ),
            }
            for value in sys.path
        ],
        "version_info": list(sys.version_info),
    }
    return {
        "runtime": runtime,
        "packages": _capture_packages() if spec.include_packages else [],
        "imports": [_capture_import(name, base_root) for name in spec.import_names],
        "variables": variables,
        "selection": {
            "env_names": list(spec.env_names),
            "env_prefixes": list(spec.env_prefixes),
            "import_names": list(spec.import_names),
            "include_packages": spec.include_packages,
        },
    }


def capture_execution_identity(spec: ClosureSpec) -> ExecutionIdentityManifest:
    observed_cwd = Path.cwd().resolve(strict=True)
    if observed_cwd != spec.invocation.cwd:
        raise ExecutionIdentityError(
            f"process cwd differs from bound invocation: {observed_cwd} != {spec.invocation.cwd}"
        )
    observed_argv = tuple(sys.argv)
    if observed_argv != spec.invocation.argv:
        raise ExecutionIdentityError("process argv differs from bound invocation")
    bindings = [
        *(_capture_path(binding, spec.base_root) for binding in spec.path_bindings),
        *(_capture_tree(binding, spec.base_root) for binding in spec.tree_bindings),
    ]
    bindings.sort(key=lambda row: row["label"])
    identity = {
        "closure_name": spec.name,
        "base_root": spec.base_root.as_posix(),
        "bindings": bindings,
        "environment": _capture_environment(spec.environment, spec.base_root),
        "invocation": {
            "cwd": spec.invocation.cwd.as_posix(),
            "argv": list(spec.invocation.argv),
            "run_parameters": _json_copy(spec.invocation.run_parameters),
        },
    }
    _validate_identity_payload(identity)
    return ExecutionIdentityManifest(identity=identity, identity_digest=_payload_digest(identity))


def validate_execution_identity_dict(raw: Mapping[str, Any]) -> ExecutionIdentityManifest:
    return ExecutionIdentityManifest.from_dict(raw, verify_digest=True)


def assert_manifest_digest(
    manifest: ExecutionIdentityManifest | Mapping[str, Any], expected_digest: str
) -> ExecutionIdentityManifest:
    if not _is_hex_digest(expected_digest):
        raise ExecutionIdentityError("expected execution-identity digest is malformed")
    validated = validate_execution_identity_dict(
        manifest.to_dict()
        if isinstance(manifest, ExecutionIdentityManifest)
        else manifest
    )
    if validated.identity_digest != expected_digest:
        raise ExecutionIdentityError(
            "execution-identity manifest does not match expected digest"
        )
    return validated


def _changed_components(
    start: ExecutionIdentityManifest, completion: ExecutionIdentityManifest
) -> list[str]:
    changed = []
    start_bindings = {row["label"]: row for row in start.identity["bindings"]}
    completion_bindings = {row["label"]: row for row in completion.identity["bindings"]}
    for label in sorted(set(start_bindings) | set(completion_bindings)):
        if start_bindings.get(label) != completion_bindings.get(label):
            changed.append(f"binding:{label}")
    for name in ("runtime", "packages", "imports", "variables", "selection"):
        if start.identity["environment"].get(name) != completion.identity["environment"].get(name):
            changed.append(f"environment:{name}")
    for name in ("cwd", "argv", "run_parameters"):
        if start.identity["invocation"].get(name) != completion.identity["invocation"].get(name):
            changed.append(f"invocation:{name}")
    if start.identity.get("base_root") != completion.identity.get("base_root"):
        changed.append("base_root")
    if start.identity.get("closure_name") != completion.identity.get("closure_name"):
        changed.append("closure_name")
    return changed


def recapture_and_assert_unchanged(
    start: ExecutionIdentityManifest, spec: ClosureSpec, *, phase: str
) -> ExecutionIdentityManifest:
    start = validate_execution_identity_dict(start.to_dict())
    completion = capture_execution_identity(spec)
    if completion.identity_digest != start.identity_digest:
        changed = _changed_components(start, completion)
        detail = ", ".join(changed) if changed else "unclassified payload change"
        raise ExecutionIdentityDriftError(
            f"execution identity changed during {phase}: {detail}"
        )
    return completion


def assert_serialized_completion_matches(
    start_raw: Mapping[str, Any], completion_raw: Mapping[str, Any]
) -> tuple[ExecutionIdentityManifest, ExecutionIdentityManifest]:
    start = validate_execution_identity_dict(start_raw)
    completion = validate_execution_identity_dict(completion_raw)
    if start.identity_digest != completion.identity_digest:
        changed = _changed_components(start, completion)
        raise ExecutionIdentityDriftError(
            "serialized execution identities differ: "
            + (", ".join(changed) if changed else "unclassified payload change")
        )
    return start, completion


def _publication_topology(value: os.stat_result) -> tuple[int, ...]:
    return (
        int(value.st_dev),
        int(value.st_ino),
        int(value.st_nlink),
        int(stat.S_IFMT(value.st_mode)),
        int(value.st_size),
        int(value.st_mtime_ns),
    )


def _plain_directory_identity(directory: Path) -> tuple[int, int]:
    inspected = (
        Path(_windows_extended_path(directory)) if os.name == "nt" else directory
    )
    before_link = inspected.lstat()
    target = inspected.stat()
    after_link = inspected.lstat()
    if (
        stat.S_ISLNK(before_link.st_mode)
        or _is_reparse_stat(before_link)
        or stat.S_ISLNK(after_link.st_mode)
        or _is_reparse_stat(after_link)
        or not stat.S_ISDIR(target.st_mode)
    ):
        raise ExclusivePublicationError(
            f"publication parent is not a plain directory: {directory}"
        )
    identities = {
        (
            int(value.st_dev),
            int(value.st_ino),
            int(stat.S_IFMT(value.st_mode)),
        )
        for value in (before_link, target, after_link)
    }
    if len(identities) != 1:
        raise ExclusivePublicationError(
            f"publication parent changed while inspecting: {directory}"
        )
    return int(target.st_dev), int(target.st_ino)


def _plain_file_topology(file_path: Path) -> tuple[int, ...]:
    inspected = (
        Path(_windows_extended_path(file_path)) if os.name == "nt" else file_path
    )
    before_link = inspected.lstat()
    before = inspected.stat()
    after = inspected.stat()
    after_link = inspected.lstat()
    if (
        stat.S_ISLNK(before_link.st_mode)
        or _is_reparse_stat(before_link)
        or stat.S_ISLNK(after_link.st_mode)
        or _is_reparse_stat(after_link)
        or not stat.S_ISREG(before.st_mode)
        or not stat.S_ISREG(after.st_mode)
    ):
        raise ExclusivePublicationError(
            f"publication leaf is not a plain regular file: {file_path}"
        )
    topologies = {
        _publication_topology(value)
        for value in (before_link, before, after, after_link)
    }
    if len(topologies) != 1:
        raise ExclusivePublicationError(
            f"publication leaf changed while inspecting: {file_path}"
        )
    topology = _publication_topology(after)
    if topology[2] != 1:
        raise ExclusivePublicationError(
            f"publication leaf must have one hard link: {file_path}"
        )
    return topology


def _descriptor_receipt(descriptor: int) -> tuple[str, int, tuple[int, ...]]:
    before = os.fstat(descriptor)
    topology = _publication_topology(before)
    if not stat.S_ISREG(before.st_mode) or topology[2] != 1:
        raise ExclusivePublicationError(
            "publication descriptor is not a single-link regular file"
        )
    digest = hashlib.sha256()
    os.lseek(descriptor, 0, os.SEEK_SET)
    for chunk in iter(lambda: os.read(descriptor, 1024 * 1024), b""):
        digest.update(chunk)
    after = os.fstat(descriptor)
    if _publication_topology(after) != topology:
        raise ExclusivePublicationError(
            "publication descriptor changed while hashing"
        )
    return digest.hexdigest(), int(after.st_size), topology


def _windows_extended_path(path: Path) -> str:
    absolute = str(path.absolute())
    if absolute.startswith("\\\\?\\"):
        return absolute
    if absolute.startswith("\\\\"):
        return "\\\\?\\UNC\\" + absolute[2:]
    return "\\\\?\\" + absolute


def _windows_create_temporary_exclusive(path: Path) -> int:
    import msvcrt

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
    ]
    kernel32.CreateFileW.restype = ctypes.c_void_p
    handle = kernel32.CreateFileW(
        _windows_extended_path(path),
        0x80000000 | 0x40000000 | 0x00010000,  # READ | WRITE | DELETE
        0x0001,  # share read only: block write/delete/rename
        None,
        1,  # CREATE_NEW
        0x00000080 | 0x00200000,  # NORMAL | OPEN_REPARSE_POINT
        None,
    )
    invalid = ctypes.c_void_p(-1).value
    if handle in (None, invalid):
        error = ctypes.get_last_error()
        if error in {80, 183}:  # ERROR_FILE_EXISTS / ERROR_ALREADY_EXISTS
            raise FileExistsError(errno.EEXIST, "temporary already exists", path)
        raise ctypes.WinError(error)
    try:
        return msvcrt.open_osfhandle(
            int(handle),
            os.O_RDWR | getattr(os, "O_BINARY", 0),
        )
    except BaseException:
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = ctypes.c_int
        kernel32.CloseHandle(ctypes.c_void_p(handle))
        raise


def _windows_rename_open_file_exclusive(
    descriptor: int, destination: Path
) -> None:
    """Rename the exact held file; success is the visibility linearization."""

    import msvcrt

    class _FileRenameInfoHeader(ctypes.Structure):
        _fields_ = [
            ("ReplaceIfExists", ctypes.c_ubyte),
            ("RootDirectory", ctypes.c_void_p),
            ("FileNameLength", ctypes.c_uint32),
        ]

    encoded_name = _windows_extended_path(destination).encode("utf-16-le")
    name_offset = (
        _FileRenameInfoHeader.FileNameLength.offset
        + ctypes.sizeof(ctypes.c_uint32)
    )
    buffer = ctypes.create_string_buffer(name_offset + len(encoded_name) + 2)
    information = _FileRenameInfoHeader.from_buffer(buffer)
    information.ReplaceIfExists = 0
    information.RootDirectory = None
    information.FileNameLength = len(encoded_name)
    ctypes.memmove(
        ctypes.addressof(buffer) + name_offset,
        encoded_name,
        len(encoded_name),
    )
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.SetFileInformationByHandle.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_uint32,
    ]
    kernel32.SetFileInformationByHandle.restype = ctypes.c_int
    handle = msvcrt.get_osfhandle(descriptor)
    succeeded = kernel32.SetFileInformationByHandle(
        ctypes.c_void_p(handle),
        3,  # FileRenameInfo
        buffer,
        len(buffer),
    )
    if not succeeded:
        error = ctypes.get_last_error()
        if error in {80, 183}:
            raise FileExistsError(errno.EEXIST, "destination already exists", destination)
        raise ctypes.WinError(error)


def _posix_rename_open_file_exclusive(source: Path, destination: Path) -> None:
    """Use Linux renameat2(RENAME_NOREPLACE), or fail before visibility."""

    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(libc, "renameat2", None)
    if renameat2 is None:
        raise OSError(
            errno.ENOTSUP,
            "platform lacks atomic no-replace rename for held publication",
        )
    renameat2.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    renameat2.restype = ctypes.c_int
    result = renameat2(
        -100,  # AT_FDCWD
        os.fsencode(source),
        -100,
        os.fsencode(destination),
        1,  # RENAME_NOREPLACE
    )
    if result != 0:
        error = ctypes.get_errno()
        if error == errno.EEXIST:
            raise FileExistsError(error, os.strerror(error), destination)
        raise OSError(error, os.strerror(error), destination)


def _atomic_write_stream_exclusive(
    path: str | Path,
    writer: Callable[[BinaryIO], None],
    *,
    expected_parent_identity: tuple[int, int] | None = None,
    retain_handle: bool = False,
    capture_receipt: bool = False,
    expected_sha256: str | None = None,
    expected_size_bytes: int | None = None,
) -> Path | ExclusivePublication:
    """Publish one held file with an exclusive rename as the final operation.

    The writer, fsync, hash, topology validation, and parent validation all
    happen while the temporary file's exact descriptor is held.  On Windows
    the descriptor denies write/delete sharing and FileRenameInfo performs the
    fail-if-present rename.  Nothing fallible runs after visibility.  Directory
    entry crash durability is deliberately not claimed.
    """

    destination = Path(path).absolute()
    if expected_parent_identity is None:
        destination.parent.mkdir(parents=True, exist_ok=True)
    elif not os.path.lexists(destination.parent):
        raise ExclusivePublicationError(
            f"publication parent is absent: {destination.parent}"
        )
    parent_identity = _plain_directory_identity(destination.parent)
    if (
        expected_parent_identity is not None
        and parent_identity != tuple(expected_parent_identity)
    ):
        raise ExclusivePublicationError(
            f"publication parent identity changed: {destination.parent}"
        )
    if os.path.lexists(destination):
        raise ExclusivePublicationError(f"refusing to overwrite output: {destination}")
    temporary = destination.with_name(
        f".{destination.name}.tmp-{os.getpid()}-{secrets.token_hex(16)}"
    )
    descriptor: int | None = None
    publication: ExclusivePublication | None = None
    try:
        if os.name == "nt":
            descriptor = _windows_create_temporary_exclusive(temporary)
        else:
            descriptor = os.open(
                temporary,
                os.O_RDWR | os.O_CREAT | os.O_EXCL,
                0o600,
            )
        binary = os.fdopen(descriptor, "w+b", closefd=False)
        try:
            writer(binary)
            binary.flush()
            os.fsync(descriptor)
        finally:
            binary.close()
        sha256, size_bytes, topology = _descriptor_receipt(descriptor)
        if (
            expected_sha256 is not None
            and sha256 != expected_sha256
            or expected_size_bytes is not None
            and size_bytes != expected_size_bytes
        ):
            raise ExclusivePublicationError(
                "held publication bytes differ from the intended payload"
            )
        if _plain_file_topology(temporary) != topology:
            raise ExclusivePublicationError(
                f"publication temporary differs from held descriptor: {temporary}"
            )
        if _plain_directory_identity(destination.parent) != parent_identity:
            raise ExclusivePublicationError(
                f"publication parent changed before visibility: {destination.parent}"
            )
        publication = ExclusivePublication(
            path=destination,
            sha256=sha256,
            size_bytes=size_bytes,
            topology=topology,
            _descriptor=descriptor if retain_handle else None,
        )
        if os.name == "nt":
            _windows_rename_open_file_exclusive(descriptor, destination)
        else:
            _posix_rename_open_file_exclusive(temporary, destination)
        if retain_handle:
            descriptor = None
        if retain_handle or capture_receipt:
            return publication
        return destination
    except FileExistsError as exc:
        raise ExclusivePublicationError(
            f"refusing to overwrite output: {destination}"
        ) from exc
    except ExclusivePublicationError:
        raise
    except (OSError, TypeError, ValueError) as exc:
        raise ExclusivePublicationError(
            f"single-leaf exclusive publication failed: {destination}: {exc}"
        ) from exc
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except BaseException:
                # A close error before visibility leaves a retained incomplete
                # temporary.  After visibility it must not turn success into
                # reported failure.
                pass
        # Prepublication failures deliberately retain the random temporary.
        # Pathname cleanup would reintroduce a check/swap deletion race.


def _atomic_write_bytes_exclusive(
    path: str | Path,
    encoded: bytes,
    *,
    expected_parent_identity: tuple[int, int] | None = None,
    retain_handle: bool = False,
    capture_receipt: bool = False,
) -> Path | ExclusivePublication:
    expected_sha256 = hashlib.sha256(encoded).hexdigest()

    def write_all(handle: BinaryIO) -> None:
        remaining = memoryview(encoded)
        while remaining:
            written = handle.write(remaining)
            if written is None or written <= 0:
                raise OSError("short write while preparing publication")
            remaining = remaining[written:]

    return _atomic_write_stream_exclusive(
        path,
        write_all,
        expected_parent_identity=expected_parent_identity,
        retain_handle=retain_handle,
        capture_receipt=capture_receipt,
        expected_sha256=expected_sha256,
        expected_size_bytes=len(encoded),
    )


def atomic_write_json_exclusive(
    path: str | Path,
    payload: Mapping[str, Any],
    *,
    compact: bool = False,
    expected_parent_identity: tuple[int, int] | None = None,
    retain_handle: bool = False,
    capture_receipt: bool = False,
) -> Path | ExclusivePublication:
    """Publish one complete JSON leaf atomically, without overwrite."""
    try:
        encoded = (
            json.dumps(
                payload,
                indent=None if compact else 2,
                separators=(",", ":") if compact else None,
                sort_keys=True,
                ensure_ascii=True,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ExclusivePublicationError(
            f"JSON publication failed before temporary creation: {path}: {exc}"
        ) from exc
    return _atomic_write_bytes_exclusive(
        path,
        encoded,
        expected_parent_identity=expected_parent_identity,
        retain_handle=retain_handle,
        capture_receipt=capture_receipt,
    )


def atomic_write_text_exclusive(
    path: str | Path,
    text: str,
    *,
    expected_parent_identity: tuple[int, int] | None = None,
    retain_handle: bool = False,
    capture_receipt: bool = False,
) -> Path | ExclusivePublication:
    """Publish one complete UTF-8 text leaf atomically, without overwrite."""
    return _atomic_write_bytes_exclusive(
        path,
        text.encode("utf-8"),
        expected_parent_identity=expected_parent_identity,
        retain_handle=retain_handle,
        capture_receipt=capture_receipt,
    )


__all__ = [
    "ClosureSpec",
    "EnvironmentSpec",
    "ExecutionIdentityDriftError",
    "ExecutionIdentityError",
    "ExecutionIdentityManifest",
    "ExclusivePublication",
    "ExclusivePublicationError",
    "InvocationSpec",
    "PathBinding",
    "SCHEMA_VERSION",
    "TreeBinding",
    "assert_manifest_digest",
    "assert_serialized_completion_matches",
    "atomic_write_json_exclusive",
    "atomic_write_text_exclusive",
    "capture_execution_identity",
    "recapture_and_assert_unchanged",
    "validate_execution_identity_dict",
]

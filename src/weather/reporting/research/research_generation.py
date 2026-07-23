"""Exclusive, fail-closed publication for multi-leaf research generations."""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import stat
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from weather.execution_identity import (
    ExecutionIdentityManifest,
    ExclusivePublication,
    assert_serialized_completion_matches,
    atomic_write_json_exclusive,
    atomic_write_text_exclusive,
    validate_execution_identity_dict,
)


COMPLETE_NAME = "COMPLETE.json"


class ResearchGenerationError(RuntimeError):
    """A generation cannot be created or committed without weakening safety."""


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _is_reparse_stat(value: os.stat_result) -> bool:
    attributes = int(getattr(value, "st_file_attributes", 0) or 0)
    marker = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0) or 0)
    return bool(marker and attributes & marker)


def _plain_directory_identity(path: Path) -> tuple[int, int]:
    before_link = path.lstat()
    target = path.stat()
    after_link = path.lstat()
    if (
        stat.S_ISLNK(before_link.st_mode)
        or _is_reparse_stat(before_link)
        or stat.S_ISLNK(after_link.st_mode)
        or _is_reparse_stat(after_link)
        or not stat.S_ISDIR(target.st_mode)
    ):
        raise ResearchGenerationError(
            f"generation directory is a symlink, reparse point, or non-directory: {path}"
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
        raise ResearchGenerationError(
            f"generation directory changed while inspecting identity: {path}"
        )
    return int(target.st_dev), int(target.st_ino)


def _plain_file_topology(path: Path) -> tuple[int, ...]:
    before_link = path.lstat()
    before = path.stat()
    after = path.stat()
    after_link = path.lstat()
    if (
        stat.S_ISLNK(before_link.st_mode)
        or _is_reparse_stat(before_link)
        or stat.S_ISLNK(after_link.st_mode)
        or _is_reparse_stat(after_link)
        or not stat.S_ISREG(before.st_mode)
        or not stat.S_ISREG(after.st_mode)
    ):
        raise ResearchGenerationError(
            f"generation leaf is a symlink, reparse point, or non-file: {path}"
        )

    def identity(value: os.stat_result) -> tuple[int, ...]:
        return (
            int(value.st_dev),
            int(value.st_ino),
            int(value.st_nlink),
            int(stat.S_IFMT(value.st_mode)),
            int(value.st_size),
            int(value.st_mtime_ns),
        )

    observed = {identity(value) for value in (before_link, before, after, after_link)}
    if len(observed) != 1:
        raise ResearchGenerationError(
            f"generation leaf topology changed while inspecting: {path}"
        )
    topology = identity(after)
    if topology[2] != 1:
        raise ResearchGenerationError(
            f"generation leaf must have exactly one hard link: {path}"
        )
    return topology


@dataclass
class _DirectoryGuard:
    path: Path
    descriptor: int

    def close(self) -> None:
        os.close(self.descriptor)


def _open_directory_guard(
    path: Path, *, expected_identity: tuple[int, int]
) -> _DirectoryGuard:
    """Hold one plain directory so Windows cannot rename/delete it mid-write."""

    if _plain_directory_identity(path) != expected_identity:
        raise ResearchGenerationError(f"generation directory identity changed: {path}")
    if os.name == "nt":
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
            str(path),
            0x0080,  # FILE_READ_ATTRIBUTES
            0x0001 | 0x0002,  # share read/write, deliberately not delete
            None,
            3,  # OPEN_EXISTING
            0x02000000 | 0x00200000,  # BACKUP_SEMANTICS | OPEN_REPARSE_POINT
            None,
        )
        invalid = ctypes.c_void_p(-1).value
        if handle in (None, invalid):
            error = ctypes.get_last_error()
            raise ResearchGenerationError(
                f"cannot hold generation directory against replacement: {path}: winerror={error}"
            )
        try:
            import msvcrt

            descriptor = msvcrt.open_osfhandle(int(handle), os.O_RDONLY)
        except BaseException:
            kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel32.CloseHandle.restype = ctypes.c_int
            kernel32.CloseHandle(ctypes.c_void_p(handle))
            raise
        guard = _DirectoryGuard(path=path, descriptor=descriptor)
    else:
        flags = os.O_RDONLY
        flags |= int(getattr(os, "O_DIRECTORY", 0))
        flags |= int(getattr(os, "O_NOFOLLOW", 0))
        descriptor = os.open(path, flags)
        guard = _DirectoryGuard(path=path, descriptor=descriptor)
    try:
        opened = os.fstat(guard.descriptor)
        opened_identity = (int(opened.st_dev), int(opened.st_ino))
        if (
            not stat.S_ISDIR(opened.st_mode)
            or opened_identity != expected_identity
        ):
            raise ResearchGenerationError(
                f"opened generation directory differs from expected path: {path}"
            )
        if _plain_directory_identity(path) != expected_identity:
            raise ResearchGenerationError(
                f"generation directory changed while acquiring guard: {path}"
            )
    except BaseException:
        guard.close()
        raise
    return guard


def _stable_receipt(path: Path, *, relative_to: Path) -> dict[str, Any]:
    before_link = path.lstat()
    before = path.stat()
    if (
        stat.S_ISLNK(before_link.st_mode)
        or _is_reparse_stat(before_link)
        or not stat.S_ISREG(before.st_mode)
    ):
        raise ResearchGenerationError(
            f"generation leaf is a symlink, reparse point, or non-file: {path}"
        )
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        opened_before = os.fstat(handle.fileno())
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
        opened_after = os.fstat(handle.fileno())
    after = path.stat()
    after_link = path.lstat()

    def identity(value):
        return (
            int(value.st_dev),
            int(value.st_ino),
            int(value.st_nlink),
            int(value.st_size),
            int(value.st_mtime_ns),
            int(value.st_ctime_ns),
        )

    if not (
        identity(before)
        == identity(opened_before)
        == identity(opened_after)
        == identity(after)
        == identity(before_link)
        == identity(after_link)
    ):
        raise ResearchGenerationError(f"generation leaf changed while hashing: {path}")
    if stat.S_ISLNK(after_link.st_mode) or _is_reparse_stat(after_link):
        raise ResearchGenerationError(
            f"generation leaf became a symlink or reparse point: {path}"
        )
    if int(after.st_nlink) != 1:
        raise ResearchGenerationError(
            f"generation leaf must have exactly one hard link: {path}"
        )
    return {
        "name": path.relative_to(relative_to).as_posix(),
        "sha256": digest.hexdigest(),
        "size_bytes": int(after.st_size),
    }


@dataclass
class ResearchGeneration:
    """Build one private generation and expose it only with ``COMPLETE.json``.

    Individual leaves are atomically create-if-absent.  They are not a
    multi-file transaction: ``COMPLETE.json`` is the sole commit marker and is
    always written last after rehashing every registered fixed leaf.
    """

    generation_dir: Path
    read_only_roots: tuple[Path, ...]
    commit_schema_version: str
    _created: bool = field(default=False, init=False)
    _committed: bool = field(default=False, init=False)
    _parent_identity: tuple[int, int] | None = field(default=None, init=False)
    _generation_identity: tuple[int, int] | None = field(default=None, init=False)
    _registered: dict[str, dict[str, Any]] = field(default_factory=dict, init=False)
    _registered_topology: dict[str, tuple[int, ...]] = field(
        default_factory=dict, init=False
    )
    _directory_identities: dict[str, tuple[int, int]] = field(
        default_factory=dict, init=False
    )
    _directory_guards: dict[str, _DirectoryGuard] = field(
        default_factory=dict, init=False
    )
    _file_guards: dict[str, ExclusivePublication] = field(
        default_factory=dict, init=False
    )

    def __post_init__(self) -> None:
        expanded = Path(self.generation_dir).expanduser()
        generation = Path(os.path.abspath(os.fspath(expanded)))
        roots = tuple(Path(root).expanduser().resolve(strict=True) for root in self.read_only_roots)
        if not self.commit_schema_version.strip():
            raise ValueError("generation commit schema version must be nonempty")
        if generation.name in {"", ".", ".."}:
            raise ValueError("generation directory needs a concrete leaf name")
        if not roots or any(not root.is_dir() for root in roots):
            raise ValueError("generation requires explicit read-only directory roots")
        parent = generation.parent
        try:
            resolved_parent = parent.resolve(strict=True)
        except OSError as exc:
            raise ValueError(f"generation parent is not a directory: {parent}") from exc
        if resolved_parent != parent or not parent.is_dir():
            raise ValueError(
                f"generation parent path contains an alias or is not a directory: {parent}"
            )
        try:
            _plain_directory_identity(parent)
        except (OSError, ResearchGenerationError) as exc:
            raise ValueError(f"generation parent is not a directory: {parent}")
        for root in roots:
            if _is_within(generation, root):
                raise ValueError(
                    f"generation resolves inside read-only root: {generation}: {root}"
                )
        if os.path.lexists(generation):
            raise ValueError(f"generation directory already exists: {generation}")
        self.generation_dir = generation
        self.read_only_roots = roots

    @staticmethod
    def _identity(path: Path) -> tuple[int, int]:
        return _plain_directory_identity(path)

    def __enter__(self) -> "ResearchGeneration":
        parent = self.generation_dir.parent
        if parent.resolve(strict=True) != parent:
            raise ResearchGenerationError(
                f"generation parent path became an alias: {parent}"
            )
        self._parent_identity = self._identity(parent)
        self._directory_guards[".."] = _open_directory_guard(
            parent, expected_identity=self._parent_identity
        )
        try:
            os.mkdir(self.generation_dir)
        except FileExistsError as exc:
            self._close_guards()
            raise ResearchGenerationError(
                f"generation directory already exists: {self.generation_dir}"
            ) from exc
        except BaseException:
            self._close_guards()
            raise
        self._created = True
        try:
            self._generation_identity = self._identity(self.generation_dir)
            self._directory_identities["."] = self._generation_identity
            self._directory_guards["."] = _open_directory_guard(
                self.generation_dir,
                expected_identity=self._generation_identity,
            )
        except BaseException:
            self._close_guards()
            raise
        return self

    def _assert_container_identity(self) -> None:
        parent = self.generation_dir.parent
        generation = self.generation_dir
        if (
            parent.resolve(strict=True) != parent
            or generation.resolve(strict=True) != generation
            or self._identity(parent) != self._parent_identity
            or self._identity(generation) != self._generation_identity
        ):
            raise ResearchGenerationError("generation container identity changed")
        self._assert_directory_identities()

    def _assert_directory_identities(self) -> None:
        for name, expected in self._directory_identities.items():
            path = self.generation_dir if name == "." else self.generation_dir / name
            if self._identity(path) != expected:
                raise ResearchGenerationError(
                    f"generation directory identity changed: {path}"
                )

    def _close_guards(self, *, suppress_errors: bool = False) -> None:
        errors = []
        for key in sorted(self._file_guards, reverse=True):
            try:
                self._file_guards[key].close()
            except BaseException as exc:
                errors.append(exc)
        self._file_guards.clear()
        for key in sorted(self._directory_guards, reverse=True):
            try:
                self._directory_guards[key].close()
            except BaseException as exc:
                errors.append(exc)
        self._directory_guards.clear()
        if errors and not suppress_errors:
            raise ResearchGenerationError(
                f"failed to close generation directory guard: {errors[0]}"
            )

    def path(self, relative_name: str) -> Path:
        relative = Path(relative_name)
        windows_unsafe = os.name == "nt" and any(
            any(ord(character) < 32 or character in '<>:"|?*' for character in part)
            or part.endswith((" ", "."))
            or part.rstrip(" .").split(".", 1)[0].upper()
            in {
                "CON",
                "PRN",
                "AUX",
                "NUL",
                *(f"COM{index}" for index in range(1, 10)),
                *(f"LPT{index}" for index in range(1, 10)),
            }
            for part in relative.parts
        )
        if (
            relative.is_absolute()
            or not relative.parts
            or ".." in relative.parts
            or windows_unsafe
            or (
                relative.as_posix().casefold() == COMPLETE_NAME.casefold()
                if os.name == "nt"
                else relative.as_posix() == COMPLETE_NAME
            )
        ):
            raise ResearchGenerationError(f"invalid generation leaf: {relative_name!r}")
        self._assert_container_identity()
        return self.generation_dir / relative

    def _prepare_leaf_path(self, relative_name: str) -> tuple[Path, tuple[int, int]]:
        path = self.path(relative_name)
        relative = path.relative_to(self.generation_dir)
        current = self.generation_dir
        parts = []
        for part in relative.parent.parts:
            if part in {"", "."}:
                continue
            parts.append(part)
            current = current / part
            name = Path(*parts).as_posix()
            expected = self._directory_identities.get(name)
            if expected is None:
                try:
                    os.mkdir(current)
                except FileExistsError as exc:
                    raise ResearchGenerationError(
                        f"unregistered generation directory already exists: {current}"
                    ) from exc
                expected = self._identity(current)
                guard = _open_directory_guard(current, expected_identity=expected)
                self._directory_identities[name] = expected
                self._directory_guards[name] = guard
            elif self._identity(current) != expected:
                raise ResearchGenerationError(
                    f"generation leaf parent identity changed: {current}"
                )
        parent_name = (
            "."
            if relative.parent.as_posix() == "."
            else relative.parent.as_posix()
        )
        parent_identity = self._directory_identities[parent_name]
        self._assert_container_identity()
        return path, parent_identity

    def _register(
        self, path: Path, publication: ExclusivePublication
    ) -> dict[str, Any]:
        if publication.path != path.absolute():
            raise ResearchGenerationError(
                f"publication evidence path differs from generation leaf: {path}"
            )
        observed_topology = _plain_file_topology(path)
        if observed_topology != publication.topology:
            raise ResearchGenerationError(
                f"publication evidence topology differs from generation leaf: {path}"
            )
        name = path.relative_to(self.generation_dir).as_posix()
        receipt = {
            "name": name,
            "sha256": publication.sha256,
            "size_bytes": publication.size_bytes,
        }
        if name in self._registered:
            raise ResearchGenerationError(f"generation leaf already registered: {name}")
        self._registered[name] = receipt
        self._registered_topology[name] = publication.topology
        self._file_guards[name] = publication
        return dict(receipt)

    def _held_receipt(self, name: str) -> dict[str, Any]:
        publication = self._file_guards.get(name)
        if publication is None:
            raise ResearchGenerationError(
                f"generation leaf has no held publication handle: {name}"
            )
        descriptor = publication.descriptor
        before = os.fstat(descriptor)
        before_topology = (
            int(before.st_dev),
            int(before.st_ino),
            int(before.st_nlink),
            int(stat.S_IFMT(before.st_mode)),
            int(before.st_size),
            int(before.st_mtime_ns),
        )
        if before_topology != publication.topology:
            raise ResearchGenerationError(
                f"held generation leaf topology changed before hashing: {name}"
            )
        digest = hashlib.sha256()
        os.lseek(descriptor, 0, os.SEEK_SET)
        for chunk in iter(lambda: os.read(descriptor, 1024 * 1024), b""):
            digest.update(chunk)
        after = os.fstat(descriptor)
        after_topology = (
            int(after.st_dev),
            int(after.st_ino),
            int(after.st_nlink),
            int(stat.S_IFMT(after.st_mode)),
            int(after.st_size),
            int(after.st_mtime_ns),
        )
        path = self.generation_dir / Path(name)
        if (
            after_topology != publication.topology
            or _plain_file_topology(path) != publication.topology
        ):
            raise ResearchGenerationError(
                f"held generation leaf changed while hashing: {name}"
            )
        return {
            "name": name,
            "sha256": digest.hexdigest(),
            "size_bytes": int(after.st_size),
        }

    def _inventory(self) -> tuple[set[str], set[str]]:
        files: set[str] = set()
        directories: set[str] = set()
        stack = [(self.generation_dir, Path())]
        while stack:
            directory, relative_directory = stack.pop()
            try:
                entries = list(os.scandir(directory))
            except OSError as exc:
                raise ResearchGenerationError(
                    f"cannot inventory generation directory: {directory}: {exc}"
                ) from exc
            for entry in entries:
                relative = relative_directory / entry.name
                path = directory / entry.name
                try:
                    link = path.lstat()
                except OSError as exc:
                    raise ResearchGenerationError(
                        f"generation topology changed during inventory: {path}"
                    ) from exc
                if stat.S_ISLNK(link.st_mode) or _is_reparse_stat(link):
                    raise ResearchGenerationError(
                        f"generation contains a symlink or reparse point: {path}"
                    )
                if stat.S_ISDIR(link.st_mode):
                    name = relative.as_posix()
                    directories.add(name)
                    stack.append((path, relative))
                elif stat.S_ISREG(link.st_mode):
                    files.add(relative.as_posix())
                else:
                    raise ResearchGenerationError(
                        f"generation contains a special filesystem entry: {path}"
                    )
        return files, directories

    def _assert_exact_topology(
        self, expected_topology: Mapping[str, tuple[int, ...]]
    ) -> None:
        self._assert_container_identity()
        actual_files, actual_directories = self._inventory()
        expected_directories = set(self._directory_identities) - {"."}
        if actual_files != set(expected_topology) or actual_directories != expected_directories:
            raise ResearchGenerationError(
                "generation topology differs from registered leaves/directories: "
                f"files={sorted(actual_files)}, directories={sorted(actual_directories)}"
            )
        for name, expected in expected_topology.items():
            observed = _plain_file_topology(self.generation_dir / Path(name))
            if observed != expected:
                raise ResearchGenerationError(
                    f"generation leaf topology changed after hashing: {name}"
                )

    def publish_json(
        self, relative_name: str, payload: Mapping[str, Any], *, compact: bool = False
    ) -> dict[str, Any]:
        path, parent_identity = self._prepare_leaf_path(relative_name)
        publication = atomic_write_json_exclusive(
            path,
            payload,
            compact=compact,
            expected_parent_identity=parent_identity,
            retain_handle=True,
        )
        if not isinstance(publication, ExclusivePublication):
            raise ResearchGenerationError("publication did not retain its leaf handle")
        try:
            self._assert_container_identity()
            return self._register(path, publication)
        except BaseException:
            try:
                publication.close()
            except BaseException:
                pass
            raise

    def publish_text(self, relative_name: str, text: str) -> dict[str, Any]:
        path, parent_identity = self._prepare_leaf_path(relative_name)
        publication = atomic_write_text_exclusive(
            path,
            text,
            expected_parent_identity=parent_identity,
            retain_handle=True,
        )
        if not isinstance(publication, ExclusivePublication):
            raise ResearchGenerationError("publication did not retain its leaf handle")
        try:
            self._assert_container_identity()
            return self._register(path, publication)
        except BaseException:
            try:
                publication.close()
            except BaseException:
                pass
            raise

    def commit(
        self,
        *,
        start: ExecutionIdentityManifest,
        terminal_recapture: Callable[[], ExecutionIdentityManifest],
        expected_completion: ExecutionIdentityManifest | Mapping[str, Any] | None = None,
        terminal_seals: Mapping[str, Any],
        extra: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._assert_container_identity()
        validated_start = validate_execution_identity_dict(start.to_dict())
        if not callable(terminal_recapture):
            raise ResearchGenerationError("generation commit requires terminal recapture")
        if not terminal_seals:
            raise ResearchGenerationError("generation commit requires terminal seals")
        try:
            sealed_terminal_seals = json.loads(
                json.dumps(
                    dict(terminal_seals),
                    sort_keys=True,
                    ensure_ascii=True,
                    allow_nan=False,
                )
            )
            sealed_metadata = json.loads(
                json.dumps(
                    dict(extra or {}),
                    sort_keys=True,
                    ensure_ascii=True,
                    allow_nan=False,
                )
            )
        except (TypeError, ValueError) as exc:
            raise ResearchGenerationError(
                "generation terminal seals and metadata must be finite JSON"
            ) from exc
        expected_manifest = None
        if expected_completion is not None:
            expected_raw = (
                expected_completion.to_dict()
                if isinstance(expected_completion, ExecutionIdentityManifest)
                else expected_completion
            )
            _, expected_manifest = assert_serialized_completion_matches(
                validated_start.to_dict(), expected_raw
            )
        actual, actual_directories = self._inventory()
        if COMPLETE_NAME in actual:
            raise ResearchGenerationError("generation commit marker already exists")
        expected_directories = set(self._directory_identities) - {"."}
        if (
            actual != set(self._registered)
            or actual_directories != expected_directories
        ):
            raise ResearchGenerationError(
                "generation has unregistered or missing topology: "
                f"registered_files={sorted(self._registered)}, "
                f"actual_files={sorted(actual)}, "
                f"registered_directories={sorted(expected_directories)}, "
                f"actual_directories={sorted(actual_directories)}"
            )
        refreshed = {
            name: self._held_receipt(name)
            for name in sorted(self._registered)
        }
        if refreshed != self._registered:
            raise ResearchGenerationError("generation leaf changed after registration")
        refreshed_topology = {
            name: _plain_file_topology(self.generation_dir / Path(name))
            for name in sorted(refreshed)
        }
        if refreshed_topology != self._registered_topology:
            raise ResearchGenerationError("generation leaf topology changed after registration")
        # The callback is intentionally after the only full output rehash.
        # From this point to COMPLETE publication only bounded topology checks
        # and marker serialization are allowed.
        terminal = terminal_recapture()
        if not isinstance(terminal, ExecutionIdentityManifest):
            raise ResearchGenerationError(
                "terminal recapture must return an ExecutionIdentityManifest"
            )
        validated_start, validated_completion = assert_serialized_completion_matches(
            validated_start.to_dict(), terminal.to_dict()
        )
        if (
            expected_manifest is not None
            and expected_manifest.identity_digest != validated_completion.identity_digest
        ):
            raise ResearchGenerationError(
                "terminal recapture differs from embedded expected completion"
            )
        self._assert_exact_topology(refreshed_topology)
        commit = {
            "schema_version": self.commit_schema_version,
            "status": "COMPLETE",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "research_only": True,
            "serving_or_release_authorization": False,
            "multi_leaf_atomic_transaction_claimed": False,
            "commit_marker_semantics": "COMPLETE.json is the sole final commit marker",
            "execution_identity": {
                "start_digest": validated_start.identity_digest,
                "completion_digest": validated_completion.identity_digest,
                "identical_full_manifest": True,
            },
            "terminal_seals": sealed_terminal_seals,
            "outputs": [refreshed[name] for name in sorted(refreshed)],
            "metadata": sealed_metadata,
        }
        marker = self.generation_dir / COMPLETE_NAME
        atomic_write_json_exclusive(
            marker,
            commit,
            expected_parent_identity=self._generation_identity,
            capture_receipt=True,
        )
        # The exclusive handle rename above is the linearization point.  Its
        # bytes, hash, and topology were validated on the held descriptor
        # before visibility; no fallible operation may follow it.
        self._committed = True
        return commit

    def __exit__(self, exc_type, exc, traceback) -> bool:
        del exc_type, exc, traceback
        # Incomplete generations deliberately remain without COMPLETE.json.
        # Recursive pathname cleanup after an identity check has a destructive
        # check/swap race on Windows; absence of COMPLETE is the fail-closed
        # publication state and cleanup is a separate reviewed operation.
        self._close_guards(suppress_errors=self._committed)
        return False


__all__ = [
    "COMPLETE_NAME",
    "ResearchGeneration",
    "ResearchGenerationError",
]

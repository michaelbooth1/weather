"""Shared path guards for research that reads immutable evidence trees."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable


def resolve_output_outside_read_only_roots(
    path: str | Path,
    *,
    read_only_roots: Iterable[str | Path],
    protected_inputs: Iterable[str | Path] = (),
) -> Path:
    """Resolve one output and reject direct or linked immutable-root aliases."""

    roots: list[Path] = []
    for raw_root in read_only_roots:
        try:
            root = Path(raw_root).expanduser().resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ValueError(f"cannot resolve read-only root {raw_root!s}: {exc}") from exc
        if not root.is_dir():
            raise ValueError(f"read-only root is not a directory: {root}")
        roots.append(root)
    if not roots:
        raise ValueError("at least one explicit read-only root is required")
    try:
        target = Path(path).expanduser().resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise ValueError(f"cannot resolve output path {path!s}: {exc}") from exc
    for root in roots:
        try:
            target.relative_to(root)
        except ValueError:
            continue
        raise ValueError(
            "research output resolves inside a supplied read-only root: "
            f"target={target}, read_only_root={root}"
        )
    for raw_input in protected_inputs:
        try:
            protected = Path(raw_input).expanduser().resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ValueError(
                f"cannot resolve protected input {raw_input!s}: {exc}"
            ) from exc
        same_file = target == protected
        if not same_file and target.exists():
            try:
                same_file = target.samefile(protected)
            except OSError as exc:
                raise ValueError(
                    "cannot verify research output against protected input: "
                    f"target={target}, protected_input={protected}: {exc}"
                ) from exc
        if same_file:
            raise ValueError(
                "research output aliases a protected input: "
                f"target={target}, protected_input={protected}"
            )
    if target.exists() and target.is_file():
        try:
            link_count = int(target.stat().st_nlink)
        except OSError as exc:
            raise ValueError(
                f"cannot inspect existing research output {target}: {exc}"
            ) from exc
        if link_count > 1:
            raise ValueError(
                "existing research output has multiple hard links; refusing to "
                f"publish through it: target={target}, st_nlink={link_count}"
            )
    return target

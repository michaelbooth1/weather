"""Bounded explicit JSON file inputs for the portfolio command and reader."""
import json
from pathlib import Path
import stat


def read_json(path):
    path = Path(path)
    for part in (path, *path.parents):
        info = part.lstat()
        if part.is_symlink() or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise ValueError("redirected_portfolio_path")
    if not path.is_file() or path.stat().st_size > 4_000_000:
        raise ValueError("portfolio_file_refused")
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate_json_field")
            result[key] = value
        return result
    return json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite_json")))

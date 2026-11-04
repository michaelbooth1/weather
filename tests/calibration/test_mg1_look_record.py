"""MG-1 release-record writer on synthetic checkouts only (tmp_path; no repository data or real receipt is read).

Mirrors tests/calibration/test_b_look_record.py (claude/b-look-record-writer-20261103 @ 24a4e70fc): commit MG-1's
receipt byte-exact with a '<receipt_path> -text' line, and the record keyed to it. Not R14-bound.
"""
import ast
import hashlib
from pathlib import Path

import pytest

from weather.calibration import mg1_look_record as rec

ROW = "2026-12-01"
DL = ("| Date | Decision |\n| --- | --- |\n"
      f"| {ROW} | MG-1 look record (master ruling) |\n")
DL_ABANDON = DL + "| 2026-12-02 | The owner abandons MG-1: abandonment recorded |\n"
RECEIPT = b'{"schema": "mg1_look_receipt/1", "result": {"x": 1}}\r\n'  # CRLF on purpose: bytes must survive


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _checkout(tmp_path, attributes=b"* text=auto\n", dl=DL):
    root = tmp_path / "repo"
    (root / "docs" / "operations").mkdir(parents=True)
    (root / rec.DECISION_LOG).write_text(dl, encoding="utf-8")
    if attributes is not None:
        (root / rec.GITATTRIBUTES).write_bytes(attributes)
    receipt = tmp_path / "out" / f"receipt-{rec.MG1_RULE_SHA256}.json"
    receipt.parent.mkdir()
    receipt.write_bytes(RECEIPT)
    return root, receipt


def _write(root, receipt, **over):
    kw = {"root": root, "receipt": receipt, "decision_log_row": ROW, "expect_sha256": _sha(RECEIPT), **over}
    return rec.write_look_record(**kw)


def test_look_record_copies_the_receipt_byte_exact_and_passes_the_checks(tmp_path):
    root, receipt = _checkout(tmp_path)
    result = _write(root, receipt)
    copy = root / rec.RECEIPT_DEFAULT
    assert rec.RECEIPT_DEFAULT == "docs/research/mg1-look-record/mg1_look_receipt.json"
    assert rec.RECORD == "docs/research/mg1-look-record/mg1-look-record.md"
    assert copy.read_bytes() == RECEIPT
    attributes = (root / rec.GITATTRIBUTES).read_text(encoding="utf-8")
    assert attributes.splitlines()[-1] == f"{rec.RECEIPT_DEFAULT} -text"
    assert attributes.startswith("* text=auto\n")
    text = (root / rec.RECORD).read_text(encoding="utf-8")
    fields, dup = rec.record_fields(text)
    assert dup == [] and fields == {"rule_sha256": rec.MG1_RULE_SHA256, "receipt_path": rec.RECEIPT_DEFAULT,
                                    "receipt_sha256": _sha(RECEIPT), "decision_log_row": ROW}
    assert rec.record_problems(text, rec.MG1_RULE_SHA256, DL, root) == []
    assert result["commit"] == [rec.RECEIPT_DEFAULT, rec.GITATTRIBUTES, rec.RECORD]
    assert '"result"' not in text and "verdict" not in text.lower()  # no receipt content in the record


def test_the_rule_sha_is_mg1_looks_pin():
    from weather.calibration import mg1_look

    assert rec.MG1_RULE_SHA256 == mg1_look.MG1_RULE_SHA256


def test_crlf_gitattributes_keeps_its_line_ending_and_a_missing_one_is_created(tmp_path):
    root, receipt = _checkout(tmp_path, attributes=b"* text=auto\r\n*.png binary")
    _write(root, receipt)
    data = (root / rec.GITATTRIBUTES).read_bytes()
    assert data == b"* text=auto\r\n*.png binary\r\n" + rec.RECEIPT_DEFAULT.encode() + b" -text\r\n"
    root2, receipt2 = _checkout(tmp_path / "b", attributes=None)
    _write(root2, receipt2)
    assert (root2 / rec.GITATTRIBUTES).read_bytes() == rec.RECEIPT_DEFAULT.encode() + b" -text\n"


@pytest.mark.parametrize("over,match", [
    ({"expect_sha256": "0" * 64}, "expected archive copy"),
    ({"decision_log_row": "2026-12-20"}, "names no DECISION_LOG row"),
    ({"decision_log_row": "12-01"}, "names no DECISION_LOG row"),
    ({"receipt_path": "../outside.json"}, "not a repo-relative path"),
    ({"receipt_path": "/abs/m.json"}, "not a repo-relative path"),
    ({"rule_sha256": "B0" * 32}, "not 64 lowercase hex"),
])
def test_preflight_refusals_write_nothing(tmp_path, over, match):
    root, receipt = _checkout(tmp_path)
    before = (root / rec.GITATTRIBUTES).read_bytes()
    with pytest.raises(rec.RecordRefused, match=match):
        _write(root, receipt, **over)
    assert not (root / rec.RECORD).exists() and not (root / rec.RECEIPT_DEFAULT).exists()
    assert (root / rec.GITATTRIBUTES).read_bytes() == before


def test_one_record_and_one_receipt_copy(tmp_path):
    root, receipt = _checkout(tmp_path)
    _write(root, receipt)
    with pytest.raises(rec.RecordRefused, match="one release record"):
        _write(root, receipt, receipt_path="docs/research/mg1-look-record/other.json")
    root2, receipt2 = _checkout(tmp_path / "b")
    (root2 / rec.RECEIPT_DEFAULT).parent.mkdir(parents=True)
    (root2 / rec.RECEIPT_DEFAULT).write_bytes(b"other")
    with pytest.raises(rec.RecordRefused, match="written once"):
        _write(root2, receipt2)


def test_a_failed_self_check_undoes_every_write(tmp_path, monkeypatch):
    root, receipt = _checkout(tmp_path)
    before = (root / rec.GITATTRIBUTES).read_bytes()
    monkeypatch.setattr(rec, "record_problems", lambda *a, **k: ["forced"])
    with pytest.raises(rec.RecordRefused, match="fails its checks"):
        _write(root, receipt)
    assert not (root / rec.RECORD).exists() and not (root / rec.RECEIPT_DEFAULT).exists()
    assert (root / rec.GITATTRIBUTES).read_bytes() == before


def test_a_failed_write_undoes_every_write_and_a_missing_attributes_file_stays_missing(tmp_path, monkeypatch):
    root, receipt = _checkout(tmp_path, attributes=None)
    def broken(*a, **k):
        assert (root / rec.RECORD).is_file() and (root / rec.GITATTRIBUTES).is_file()  # every write happened
        raise OSError("disk")

    monkeypatch.setattr(rec, "record_problems", broken)
    with pytest.raises(OSError, match="disk"):
        _write(root, receipt)
    assert not (root / rec.RECEIPT_DEFAULT).exists() and not (root / rec.GITATTRIBUTES).exists()
    assert not (root / rec.RECORD).exists()


def test_receipt_attribute_rule_is_exact_path_and_last_wins():
    path = rec.RECEIPT_DEFAULT
    assert rec.receipt_attribute_problem(f"{path} -text\n", path) is None
    assert rec.receipt_attribute_problem(f"/{path} binary\n", path) is None
    assert rec.receipt_attribute_problem("docs/research/mg1-look-record/*.json -text\n", path)  # not exact
    assert rec.receipt_attribute_problem(f"{path} -text\n* text=auto\n", path)  # a later line sets text again
    assert rec.receipt_attribute_problem(f"{path} -text text\n", path)  # sets text on the same line
    assert rec.receipt_attribute_problem(f"# {path} -text\n", path)  # a comment


def test_record_problems_name_each_break(tmp_path):
    root, receipt = _checkout(tmp_path)
    _write(root, receipt)
    text = (root / rec.RECORD).read_text(encoding="utf-8")
    assert rec.record_problems(text, "f" * 64, DL, root)  # another rule sha
    assert any("more than once" in p for p in rec.record_problems(text + f"decision_log_row: {ROW}\n",
                                                                  rec.MG1_RULE_SHA256, DL, root))
    (root / rec.RECEIPT_DEFAULT).write_bytes(RECEIPT.replace(b"\r\n", b"\n"))  # a normalised blob
    assert any("not the sha256" in p for p in rec.record_problems(text, rec.MG1_RULE_SHA256, DL, root))
    (root / rec.GITATTRIBUTES).write_text("* text=auto\n", encoding="utf-8")
    assert any("byte-exact" in p for p in rec.record_problems(text, rec.MG1_RULE_SHA256, DL, root))
    (root / rec.RECEIPT_DEFAULT).unlink()
    assert any("not in the checkout" in p for p in rec.record_problems(text, rec.MG1_RULE_SHA256, DL, root))


def test_abandonment_record_needs_an_owner_abandonment_row(tmp_path):
    root, _ = _checkout(tmp_path, dl=DL_ABANDON)
    with pytest.raises(rec.RecordRefused, match="owner abandonment"):
        rec.write_abandonment_record(root=root, decision_log_row=ROW, reason="x")  # a master ruling row
    with pytest.raises(rec.RecordRefused, match="needs a reason"):
        rec.write_abandonment_record(root=root, decision_log_row="2026-12-02", reason="  ")
    assert not (root / rec.RECORD).exists()
    result = rec.write_abandonment_record(root=root, decision_log_row="2026-12-02", reason="owner abandons\n MG-1")
    assert result["commit"] == [rec.RECORD] and not (root / rec.RECEIPT_DEFAULT).exists()
    text = (root / rec.RECORD).read_text(encoding="utf-8")
    assert text.startswith("# MG-1 abandonment record\n")
    fields, _ = rec.record_fields(text)
    assert fields == {"mg1_abandonment": "owner abandons MG-1", "decision_log_row": "2026-12-02"}
    assert rec.record_problems(text, rec.MG1_RULE_SHA256, DL_ABANDON, root) == []
    assert rec.record_problems(text.replace("2026-12-02", ROW), rec.MG1_RULE_SHA256, DL_ABANDON, root)
    with pytest.raises(rec.RecordRefused, match="one release record"):
        rec.write_abandonment_record(root=root, decision_log_row="2026-12-02", reason="again")


def test_not_an_owner_decision_row_is_no_abandonment():
    dl = "| 2026-12-03 | owner asked; abandon considered (not an owner decision) |\n"
    assert rec.owner_abandonment_rows(dl, "2026-12-03") == []
    assert rec.owner_abandonment_rows(DL_ABANDON, "2026-12-02")


def test_cli_abandon(tmp_path, capsys):
    root, _ = _checkout(tmp_path, dl=DL_ABANDON)
    args = ["--root", str(root), "abandon", "--reason", "owner abandons MG-1", "--decision-log-row"]
    assert rec.main(args + [ROW]) == 2 and "owner abandonment" in capsys.readouterr().err
    assert rec.main(args + ["2026-12-02"]) == 0 and (root / rec.RECORD).is_file()


def test_cli_writes_and_refuses(tmp_path, capsys):
    root, receipt = _checkout(tmp_path)
    args = ["--root", str(root), "look", "--receipt", str(receipt), "--decision-log-row", ROW]
    assert rec.main(args + ["--expect-sha256", "0" * 64]) == 2 and "refused" in capsys.readouterr().err
    assert rec.main(args + ["--expect-sha256", _sha(RECEIPT)]) == 0
    assert (root / rec.RECORD).is_file()


def test_module_is_stdlib_only_and_never_parses_the_receipt():
    tree = ast.parse(Path(rec.__file__).read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
        elif isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
    assert imported <= {"__future__", "argparse", "hashlib", "json", "re", "sys", "pathlib"}
    loads = [n for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr in ("loads", "load")]
    assert not loads  # the receipt's bytes are copied and hashed, never parsed

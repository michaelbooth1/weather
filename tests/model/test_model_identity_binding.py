"""Identity must describe the process, not the filesystem.

`-09-75a` and `-09-76a` measured what the `v0.1` binding cost: only 114 of 358
decision snapshots reproduced their own recorded output, and 0 of 63 captured
identities could be rebuilt from Git. The cause was that `code_hash` was read
from disk at capture time, so an edit landing after a loop started rewrote the
identity of a process that had not changed.

These tests pin the three properties that fix must have, phrased as the failure
each one prevents.
"""
import sys
import unittest
from pathlib import Path

from weather.model import model_identity as mi


class LoadedCodeFingerprintTests(unittest.TestCase):
    def test_all_distribution_modules_are_reachable_by_module_name(self):
        """A typo in the path->module mapping would silently fingerprint nothing."""
        for relative in mi.DISTRIBUTION_CODE_FILES:
            name = mi._module_name_for(relative)
            __import__(name)
            fingerprint = mi.loaded_code_fingerprint(name)
            self.assertTrue(fingerprint["loaded"], f"{name} not reachable in sys.modules")
            self.assertIsNotNone(fingerprint["sha256"])
            self.assertGreater(
                (fingerprint["code_units"] or 0) + (fingerprint["constants"] or 0),
                0,
                f"{name} fingerprinted to nothing at all",
            )

    def test_fingerprint_is_deterministic(self):
        name = mi._module_name_for(mi.DISTRIBUTION_CODE_FILES[0])
        __import__(name)
        self.assertEqual(
            mi.loaded_code_fingerprint(name)["sha256"],
            mi.loaded_code_fingerprint(name)["sha256"],
        )

    def test_path_dunders_are_excluded(self):
        """A worktree and production must fingerprint identical code identically.

        `__file__` and `__cached__` differ between checkouts. Folding them in
        would make every verification run disagree with production for reasons
        that have nothing to do with the code.
        """
        name = mi._module_name_for(mi.DISTRIBUTION_CODE_FILES[0])
        __import__(name)
        module = sys.modules[name]
        before = mi.loaded_code_fingerprint(name)["sha256"]
        original = module.__file__
        try:
            module.__file__ = "C:/elsewhere/impostor.py"
            self.assertEqual(before, mi.loaded_code_fingerprint(name)["sha256"])
        finally:
            module.__file__ = original

    def test_module_level_constant_change_is_visible(self):
        """model_constants.py defines no functions.

        A bytecode-only witness reports an empty fingerprint for it, so a
        changed threshold would move nothing.
        """
        name = "weather.model.model_constants"
        __import__(name)
        module = sys.modules[name]
        before = mi.loaded_code_fingerprint(name)["sha256"]
        attribute = next(
            key
            for key, value in vars(module).items()
            if isinstance(value, (int, float)) and not key.startswith("__")
        )
        original = getattr(module, attribute)
        try:
            setattr(module, attribute, original + 1)
            self.assertNotEqual(before, mi.loaded_code_fingerprint(name)["sha256"])
        finally:
            setattr(module, attribute, original)
        self.assertEqual(before, mi.loaded_code_fingerprint(name)["sha256"])

    def test_missing_module_degrades_instead_of_raising(self):
        """Identity must never break capture."""
        fingerprint = mi.loaded_code_fingerprint("weather.model.definitely_not_a_module")
        self.assertFalse(fingerprint["loaded"])
        self.assertIsNone(fingerprint["sha256"])

    def test_a_module_that_imports_late_is_still_picked_up(self):
        """Four of the eleven modules import lazily.

        At the first capture only seven are in ``sys.modules``. Caching the whole
        set on the first call would freeze the other four as "never loaded" for
        the life of the process, quietly weakening the fingerprint to seven
        modules while still reporting a hash.
        """
        name = mi._module_name_for(mi.DISTRIBUTION_CODE_FILES[0])
        __import__(name)
        module = sys.modules[name]
        cached = mi._LOADED_MODULE_CACHE
        self.addCleanup(setattr, mi, "_LOADED_MODULE_CACHE", cached)
        self.addCleanup(sys.modules.__setitem__, name, module)

        # Stand in for "not imported yet": absent from sys.modules and recorded
        # as unloaded, exactly the state the first capture sees.
        del sys.modules[name]
        mi._LOADED_MODULE_CACHE = {}
        stale = mi.loaded_code_identity()
        self.assertIn(name, stale["modules_not_loaded"])

        sys.modules[name] = module
        refreshed = mi.loaded_code_identity()
        self.assertNotIn(name, refreshed["modules_not_loaded"])
        self.assertNotEqual(stale["loaded_code_hash"], refreshed["loaded_code_hash"])

    def test_a_loaded_module_is_never_re_fingerprinted(self):
        """Loaded code cannot change without a restart, so re-reading it would
        only add per-capture cost for an answer that cannot differ."""
        name = mi._module_name_for(mi.DISTRIBUTION_CODE_FILES[0])
        __import__(name)
        cached = mi._LOADED_MODULE_CACHE
        self.addCleanup(setattr, mi, "_LOADED_MODULE_CACHE", cached)

        mi._LOADED_MODULE_CACHE = dict(cached)
        first = mi.loaded_code_identity()
        record = mi._LOADED_MODULE_CACHE[name]
        second = mi.loaded_code_identity()
        self.assertIs(record, mi._LOADED_MODULE_CACHE[name])
        self.assertEqual(first["loaded_code_hash"], second["loaded_code_hash"])


class ImportTimeBindingTests(unittest.TestCase):
    """The v0.1 defect itself, pinned."""

    def setUp(self):
        self.original = mi._IMPORT_TIME_CODE_FILES
        self.addCleanup(setattr, mi, "_IMPORT_TIME_CODE_FILES", self.original)

    def test_import_time_snapshot_exists_and_covers_every_code_file(self):
        self.assertIsNotNone(mi._IMPORT_TIME_CODE_FILES)
        self.assertEqual(len(mi._IMPORT_TIME_CODE_FILES), len(mi.DISTRIBUTION_CODE_FILES))

    def test_disk_edit_after_import_does_not_change_the_identity(self):
        """This is the exact v0.1 failure.

        A roll-free commit advances the working tree while a capture loop keeps
        running the code it started with. Under v0.1 the recorded identity moved
        anyway, describing a process that never existed.
        """
        identity_before = mi.model_replay_identity(_StubModel())

        drifted = [dict(item) for item in mi._IMPORT_TIME_CODE_FILES]
        drifted[0]["sha256"] = "0" * 64
        mi._IMPORT_TIME_CODE_FILES = drifted

        identity_after = mi.model_replay_identity(_StubModel())

        self.assertNotEqual(identity_before["code_hash"], identity_after["code_hash"])
        self.assertNotEqual(identity_before["identity_hash"], identity_after["identity_hash"])
        self.assertFalse(identity_before["runtime_binding"]["code_disk_drift"])
        self.assertTrue(identity_after["runtime_binding"]["code_disk_drift"])
        self.assertEqual(
            identity_before["loaded_code_hash"],
            identity_after["loaded_code_hash"],
            "the in-memory witness must not move when only disk state is manipulated",
        )

    def test_drift_is_observed_but_not_hashed(self):
        """disk_code_hash must stay out of identity_hash.

        Hashing it would reintroduce v0.1: an unrelated edit on disk would
        change the recorded identity of a process that did not change.
        """
        identity = mi.model_replay_identity(_StubModel())
        binding = identity["runtime_binding"]
        self.assertIn("disk_code_hash", binding)
        self.assertNotIn("disk_code_hash", _hashed_payload_keys(identity))
        self.assertNotIn("code_disk_drift", _hashed_payload_keys(identity))

    def test_live_fallback_when_the_import_snapshot_failed(self):
        mi._IMPORT_TIME_CODE_FILES = None
        identity = mi.model_replay_identity(_StubModel())
        self.assertEqual(identity["runtime_binding"]["code_files_origin"], "live_fallback")
        self.assertFalse(identity["runtime_binding"]["code_disk_drift"])

    def test_schema_version_is_declared(self):
        identity = mi.model_replay_identity(_StubModel())
        self.assertEqual(identity["schema_version"], "weather_model_replay_identity_v0.2")
        self.assertEqual(identity["schema_version"], mi.IDENTITY_SCHEMA_VERSION)


def _hashed_payload_keys(identity):
    """Keys that feed identity_hash, per model_replay_identity."""
    return {
        "schema_version",
        "model_version",
        "market_id",
        "active_model_kind",
        "code_hash",
        "artifact_hash",
        "loaded_code_hash",
    }


class _StubSpec:
    id = "toronto"
    artifact_suffix = ""
    display_unit = "C"


class _StubModel:
    spec = _StubSpec()
    market_id = "toronto"
    active_model_kind = "hgb"

    def get_model_version_string(self):
        return "v0.5.10"


if __name__ == "__main__":
    unittest.main()

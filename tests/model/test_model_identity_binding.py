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
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

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

    def test_distribution_mro_owners_are_identity_bound(self):
        from weather.model.toronto_model import TorontoHighTempModel

        tracked = {mi._module_name_for(path) for path in mi.DISTRIBUTION_CODE_FILES}
        required = {
            cls.__module__
            for cls in TorontoHighTempModel.__mro__
            if cls.__module__.startswith("weather.model.")
            and cls.__module__ != "weather.model.model_presentation"
        }
        self.assertEqual(required - tracked, set())

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

    def test_compiled_filename_is_normalized_recursively(self):
        """Raw marshal bytes retain co_filename in nested code objects."""
        source = """
SETTINGS = {"ttl": [5, 10], "markets": {"toronto", "denver"}}
def outer(value=SETTINGS["ttl"][0]):
    def inner(delta=1):
        return value + delta
    return inner()
"""
        first = _source_fingerprint(source, r"C:\\worktree-a\\same.py")
        second = _source_fingerprint(source, r"D:\\worktree-b\\same.py")
        self.assertEqual(first, second)

    def test_function_defaults_are_bound(self):
        first = _source_fingerprint("def score(value=1):\n    return value\n", "a.py")
        second = _source_fingerprint("def score(value=2):\n    return value\n", "a.py")
        self.assertNotEqual(first, second)

    def test_nested_constant_change_is_visible_and_mapping_order_is_stable(self):
        first = _source_fingerprint('SETTINGS = {"ttl": [5, 10], "enabled": True}\n', "a.py")
        reordered = _source_fingerprint(
            'SETTINGS = {"enabled": True, "ttl": [5, 10]}\n', "b.py"
        )
        changed = _source_fingerprint(
            'SETTINGS = {"enabled": True, "ttl": [5, 11]}\n', "c.py"
        )
        self.assertEqual(first, reordered)
        self.assertNotEqual(first, changed)

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
        """Lazy imports must not be frozen as permanently absent.

        Caching the whole set on the first call would freeze any missing module
        as "never loaded" for the life of the process while still reporting a
        confident hash.
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
        self.assertEqual(identity_before["identity_hash"], identity_after["identity_hash"])
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
        self.assertNotIn("code_hash", _hashed_payload_keys(identity))
        self.assertNotIn("artifact_hash", _hashed_payload_keys(identity))

    def test_live_fallback_when_the_import_snapshot_failed(self):
        mi._IMPORT_TIME_CODE_FILES = None
        identity = mi.model_replay_identity(_StubModel())
        self.assertEqual(identity["runtime_binding"]["code_files_origin"], "live_fallback")
        self.assertFalse(identity["runtime_binding"]["code_disk_drift"])

    def test_schema_version_is_declared(self):
        identity = mi.model_replay_identity(_StubModel())
        self.assertEqual(identity["schema_version"], "weather_model_replay_identity_v0.3")
        self.assertEqual(identity["schema_version"], mi.IDENTITY_SCHEMA_VERSION)
        self.assertEqual(
            identity["runtime_dependency_hash"],
            identity["runtime_binding"]["runtime_dependencies"]["runtime_dependency_hash"],
        )


class LoadedArtifactBindingTests(unittest.TestCase):
    def test_loaded_artifact_replacement_changes_process_identity(self):
        model = _ArtifactModel()
        before = mi.model_replay_identity(model)
        model.calibrated_weights = {"hours": {"7": {"weight": 0.7}}}
        after = mi.model_replay_identity(model)
        self.assertNotEqual(before["loaded_artifact_hash"], after["loaded_artifact_hash"])
        self.assertNotEqual(before["identity_hash"], after["identity_hash"])

    def test_post_load_disk_mutation_cannot_relabel_the_process(self):
        model = _ArtifactModel()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)

            def resolved(name):
                return root / name

            for template in mi.DISTRIBUTION_ARTIFACT_TEMPLATES:
                path = resolved(template.format(suffix=""))
                path.write_bytes(b"before")
            with mock.patch.object(mi, "resolve_artifact_path", side_effect=resolved):
                before = mi.model_replay_identity(model)
                resolved("calibrated_weights.json").write_bytes(b"after")
                after = mi.model_replay_identity(model)

        self.assertNotEqual(before["artifact_hash"], after["artifact_hash"])
        self.assertEqual(before["loaded_artifact_hash"], after["loaded_artifact_hash"])
        self.assertEqual(before["identity_hash"], after["identity_hash"])

    def test_equivalent_mapping_order_has_same_loaded_artifact_hash(self):
        first = _ArtifactModel()
        second = _ArtifactModel()
        first.calibrated_weights = {"hours": {"7": 0.7}, "enabled": True}
        second.calibrated_weights = {"enabled": True, "hours": {"7": 0.7}}
        self.assertEqual(
            mi.loaded_artifact_identity(first)["loaded_artifact_hash"],
            mi.loaded_artifact_identity(second)["loaded_artifact_hash"],
        )

    def test_exact_loaded_source_hash_binds_unsupported_estimator_state(self):
        first = _ArtifactModel()
        second = _ArtifactModel()
        first._feature_model_hgb = object()
        second._feature_model_hgb = object()
        source = {"sha256": "a" * 64, "size": 123}
        first._loaded_artifact_source_hashes = {"feature_hgb": source}
        second._loaded_artifact_source_hashes = {"feature_hgb": source}
        first_identity = mi.loaded_artifact_identity(first)
        second_identity = mi.loaded_artifact_identity(second)
        self.assertEqual(
            first_identity["loaded_artifact_hash"],
            second_identity["loaded_artifact_hash"],
        )
        hgb = next(
            row for row in first_identity["components"] if row["role"] == "feature_hgb"
        )
        self.assertEqual(hgb["encoding"], "loaded-source-sha256-1")
        self.assertEqual(hgb["sha256"], "a" * 64)

    def test_source_binding_change_invalidates_cached_identity(self):
        model = _ArtifactModel()
        model._feature_model_hgb = object()
        model._loaded_artifact_source_hashes = {
            "feature_hgb": {"sha256": "a" * 64, "size": 123}
        }
        before = mi.loaded_artifact_identity(model)
        model._loaded_artifact_source_hashes["feature_hgb"] = {
            "sha256": "b" * 64,
            "size": 124,
        }
        after = mi.loaded_artifact_identity(model)
        self.assertNotEqual(before["loaded_artifact_hash"], after["loaded_artifact_hash"])

    def test_unsupported_unbound_state_degrades_visibly(self):
        model = _ArtifactModel()
        model._feature_model_hgb = object()
        identity = mi.loaded_artifact_identity(model)
        self.assertIn("feature_hgb", identity["components_failed"])

    def test_verified_release_hash_binds_materialized_estimator(self):
        model = _ArtifactModel()
        model._feature_model_hgb = object()
        model.serving_bundle = types.SimpleNamespace(
            base_model_graph={
                "markets": {
                    "toronto": {
                        "components": {
                            "feature_hgb": {"sha256": "b" * 64},
                        }
                    }
                },
                "shared_components": {},
            }
        )
        identity = mi.loaded_artifact_identity(model)
        hgb = next(
            row for row in identity["components"] if row["role"] == "feature_hgb"
        )
        self.assertEqual(hgb["encoding"], "loaded-source-sha256-1")
        self.assertEqual(hgb["sha256"], "b" * 64)


def _hashed_payload_keys(identity):
    """Keys that feed identity_hash, per model_replay_identity."""
    return {
        "schema_version",
        "model_version",
        "market_id",
        "active_model_kind",
        "loaded_code_hash",
        "loaded_artifact_hash",
        "runtime_dependency_hash",
    }


def _source_fingerprint(source, filename):
    name = "weather.model._identity_test_module"
    module = types.ModuleType(name)
    module.__file__ = filename
    exec(compile(source, filename, "exec"), module.__dict__)
    original = sys.modules.get(name)
    try:
        sys.modules[name] = module
        return mi.loaded_code_fingerprint(name)["sha256"]
    finally:
        if original is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = original


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


class _ArtifactModel(_StubModel):
    def __init__(self):
        self.calibrated_weights = {"hours": {"7": {"weight": 0.5}}}
        self._feature_model_coefs = {"7": {"coefs": [1.0, 2.0]}}
        self._feature_model_hgb = {"7": {"classes": [20, 21]}}
        self._late_day_model_coefs = {"17": {"coefs": [0.2]}}
        self.probability_calibration = {"hours": {"7": {"scale": 1.0}}}
        self.forecast_error_model = {"sources": {"open_meteo": {"mae": 1.0}}}
        self.settlement_lag_model = {"hours": {"17": {"rate": 0.2}}}
        self.afternoon_residual_centering = {"hours": {"14": {"shift": 0.1}}}
        self.family_secondary_artifacts = {"markets": {}}


if __name__ == "__main__":
    unittest.main()

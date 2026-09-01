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
            self.assertEqual(
                fingerprint["status"],
                mi.FINGERPRINT_COMPLETE,
                f"{name} has unsupported identity state: "
                f"{fingerprint['unsupported_entries']}",
            )
            self.assertIsNotNone(fingerprint["sha256"])
            self.assertGreater(
                (fingerprint["code_units"] or 0) + (fingerprint["constants"] or 0),
                0,
                f"{name} fingerprinted to nothing at all",
            )

    def test_provider_fanout_cache_exclusion_is_explicit(self):
        name = "weather.model.model_sources"
        __import__(name)
        fingerprint = mi.loaded_code_fingerprint(name)
        exclusion = next(
            row
            for row in fingerprint["excluded_entries"]
            if row["owner"] == "constant:NBM_NATIONAL_TEXT_FANOUT"
        )
        self.assertEqual(
            exclusion["reason"],
            "provider_fetch_coordination_cache_outside_fixed_sources_replay",
        )

    def test_serving_process_cache_does_not_relabel_loaded_code(self):
        import weather.release_serving as serving

        original = dict(serving._PROCESS_BUNDLES)
        try:
            serving._PROCESS_BUNDLES.clear()
            empty = mi.loaded_code_fingerprint("weather.release_serving")
            serving._PROCESS_BUNDLES["synthetic-pointer"] = "synthetic-bundle"
            populated = mi.loaded_code_fingerprint("weather.release_serving")
        finally:
            serving._PROCESS_BUNDLES.clear()
            serving._PROCESS_BUNDLES.update(original)

        self.assertEqual(empty["sha256"], populated["sha256"])
        exclusion = next(
            row
            for row in populated["excluded_entries"]
            if row["owner"] == "constant:_PROCESS_BUNDLES"
        )
        self.assertEqual(
            exclusion["reason"],
            "process_cache_state_bound_separately_by_pointer_and_manifest",
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

    def test_zoneinfo_function_defaults_are_bound(self):
        first = _source_fingerprint(
            'from zoneinfo import ZoneInfo\n'
            'def score(tz=ZoneInfo("America/Toronto")):\n    return tz.key\n',
            "a.py",
        )
        second = _source_fingerprint(
            'from zoneinfo import ZoneInfo\n'
            'def score(tz=ZoneInfo("America/New_York")):\n    return tz.key\n',
            "a.py",
        )
        self.assertNotEqual(first, second)

    def test_compiled_regex_constants_are_bound(self):
        first = _source_fingerprint(
            'import re\nROUTE_RE = re.compile(r"toronto-(\\d+)", re.IGNORECASE)\n',
            "a.py",
        )
        second = _source_fingerprint(
            'import re\nROUTE_RE = re.compile(r"toronto-(\\w+)", re.IGNORECASE)\n',
            "a.py",
        )
        self.assertNotEqual(first, second)

    def test_datetime_family_constants_are_bound(self):
        first = _source_fingerprint(
            "from datetime import date, datetime, time, timedelta, timezone\n"
            "VALUES = (date(2026, 8, 31), datetime(2026, 8, 31, 12, 0, "
            "tzinfo=timezone.utc), time(12, 0), timedelta(minutes=5))\n",
            "a.py",
        )
        second = _source_fingerprint(
            "from datetime import date, datetime, time, timedelta, timezone\n"
            "VALUES = (date(2026, 8, 31), datetime(2026, 8, 31, 12, 0, "
            "tzinfo=timezone.utc), time(12, 0), timedelta(minutes=6))\n",
            "a.py",
        )
        self.assertNotEqual(first, second)

    def test_named_module_sentinel_is_explicit_and_stable(self):
        first = _source_fingerprint_record("SENTINEL = object()\n", "a.py")
        second = _source_fingerprint_record("SENTINEL = object()\n", "b.py")
        self.assertEqual(first["status"], mi.FINGERPRINT_COMPLETE)
        self.assertEqual(first["sha256"], second["sha256"])

    def test_unsupported_module_constant_is_explicitly_incomplete(self):
        fingerprint = _source_fingerprint_record(
            "UNSUPPORTED = complex(1, 2)\n",
            "a.py",
        )
        self.assertEqual(fingerprint["status"], mi.FINGERPRINT_INCOMPLETE)
        self.assertIsNotNone(fingerprint["sha256"], "diagnostic hash must remain")
        self.assertEqual(
            fingerprint["unsupported_entries"][0]["owner"],
            "constant:UNSUPPORTED",
        )

    def test_unsupported_function_default_is_explicitly_incomplete(self):
        fingerprint = _source_fingerprint_record(
            "class Unsupported:\n    pass\n"
            "def score(value=Unsupported()):\n    return value\n",
            "a.py",
        )
        self.assertEqual(fingerprint["status"], mi.FINGERPRINT_INCOMPLETE)
        self.assertTrue(
            any(
                entry["owner"] == "function:score"
                for entry in fingerprint["unsupported_entries"]
            )
        )

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
        self.assertEqual(fingerprint["status"], mi.FINGERPRINT_UNLOADED)
        self.assertIsNone(fingerprint["sha256"])

    def test_fingerprint_exception_is_not_reported_as_unloaded(self):
        cached = mi._LOADED_MODULE_CACHE
        self.addCleanup(setattr, mi, "_LOADED_MODULE_CACHE", cached)
        mi._LOADED_MODULE_CACHE = {}
        with (
            mock.patch.object(
                mi,
                "DISTRIBUTION_CODE_FILES",
                (Path("weather/model/toronto_model.py"),),
            ),
            mock.patch.object(
                mi,
                "loaded_code_fingerprint",
                side_effect=RuntimeError("synthetic fingerprint failure"),
            ),
        ):
            identity = mi.loaded_code_identity()
        self.assertEqual(identity["status"], mi.FINGERPRINT_INCOMPLETE)
        self.assertEqual(identity["modules_not_loaded"], [])
        self.assertEqual(identity["modules_failed"], ["weather.model.toronto_model"])
        self.assertEqual(identity["modules"][0]["status"], mi.FINGERPRINT_ERROR)
        self.assertEqual(identity["modules"][0]["error_type"], "RuntimeError")

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


class PublicIdentityBindingTests(unittest.TestCase):
    def test_runtime_dependency_identity_is_a_deep_defensive_copy(self):
        first = mi.runtime_dependency_identity()
        self.assertEqual(first, mi._RUNTIME_DEPENDENCY_IDENTITY)

        first["packages"]["numpy"] = "mutated-by-caller"
        first["runtime_dependency_hash"] = "0" * 64

        second = mi.runtime_dependency_identity()
        self.assertEqual(second, mi._RUNTIME_DEPENDENCY_IDENTITY)
        self.assertNotEqual(second, first)

    def test_loaded_module_fingerprints_are_sorted_unique_and_defensive(self):
        first_name = "weather.model.model_constants"
        second_name = "weather.model.model_contracts"
        __import__(first_name)
        __import__(second_name)

        records = mi.loaded_module_fingerprints(
            [second_name, first_name, second_name]
        )
        self.assertEqual(
            [record["module"] for record in records],
            [first_name, second_name],
        )
        self.assertTrue(
            all(record["status"] == mi.FINGERPRINT_COMPLETE for record in records)
        )

        records[0]["unsupported_entries"].append({"caller": "mutation"})
        refreshed = mi.loaded_module_fingerprints([first_name])
        self.assertEqual(refreshed[0]["unsupported_entries"], [])

    def test_loaded_module_fingerprint_failure_is_an_explicit_error(self):
        name = "weather.model.model_contracts"
        __import__(name)
        with mock.patch.object(
            mi,
            "loaded_code_fingerprint",
            side_effect=RuntimeError("synthetic failure"),
        ):
            records = mi.loaded_module_fingerprints([name])

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["module"], name)
        self.assertEqual(records[0]["status"], mi.FINGERPRINT_ERROR)
        self.assertEqual(records[0]["error_type"], "RuntimeError")
        self.assertIsNone(records[0]["sha256"])

    def test_loaded_module_fingerprints_reject_invalid_names(self):
        for names in ([""], [None]):
            with self.subTest(names=names), self.assertRaises(ValueError):
                mi.loaded_module_fingerprints(names)


class ImportTimeBindingTests(unittest.TestCase):
    """The v0.1 defect itself, pinned."""

    def setUp(self):
        self.original = mi._IMPORT_TIME_CODE_FILES
        self.addCleanup(setattr, mi, "_IMPORT_TIME_CODE_FILES", self.original)
        patcher = mock.patch.object(
            mi,
            "loaded_code_identity",
            return_value=_complete_loaded_code_identity(),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

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


class AuthoritativeIdentityTests(unittest.TestCase):
    def test_incomplete_or_error_code_has_only_a_diagnostic_hash(self):
        for record_status in (mi.FINGERPRINT_INCOMPLETE, mi.FINGERPRINT_ERROR):
            with self.subTest(record_status=record_status), mock.patch.object(
                mi,
                "loaded_code_identity",
                return_value=_incomplete_loaded_code_identity(record_status),
            ):
                identity = mi.model_replay_identity(_ArtifactModel())
            self.assertEqual(identity["status"], mi.FINGERPRINT_INCOMPLETE)
            self.assertIsNone(identity["identity_hash"])
            self.assertIsNone(mi.identity_hash(identity))
            self.assertIsNotNone(identity["diagnostic_identity_hash"])
            self.assertEqual(identity["identity_blockers"][0]["status"], record_status)

    def test_v03_hash_without_complete_status_is_not_authoritative(self):
        identity = {
            "schema_version": mi.IDENTITY_SCHEMA_VERSION,
            "identity_hash": "a" * 64,
        }
        self.assertIsNone(mi.identity_hash(identity))

    def test_runtime_dependency_change_moves_authoritative_identity(self):
        first_runtime = {
            **mi._RUNTIME_DEPENDENCY_IDENTITY,
            "runtime_dependency_hash": "1" * 64,
        }
        second_runtime = {
            **mi._RUNTIME_DEPENDENCY_IDENTITY,
            "runtime_dependency_hash": "2" * 64,
        }
        with (
            mock.patch.object(
                mi,
                "loaded_code_identity",
                return_value=_complete_loaded_code_identity(),
            ),
            mock.patch.object(mi, "_RUNTIME_DEPENDENCY_IDENTITY", first_runtime),
        ):
            first = mi.model_replay_identity(_ArtifactModel())
        with (
            mock.patch.object(
                mi,
                "loaded_code_identity",
                return_value=_complete_loaded_code_identity(),
            ),
            mock.patch.object(mi, "_RUNTIME_DEPENDENCY_IDENTITY", second_runtime),
        ):
            second = mi.model_replay_identity(_ArtifactModel())
        self.assertEqual(first["status"], mi.FINGERPRINT_COMPLETE)
        self.assertEqual(second["status"], mi.FINGERPRINT_COMPLETE)
        self.assertIsNotNone(first["identity_hash"])
        self.assertNotEqual(first["identity_hash"], second["identity_hash"])


class LoadedArtifactBindingTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(
            mi,
            "loaded_code_identity",
            return_value=_complete_loaded_code_identity(),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

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

    def test_same_object_canonical_state_mutation_invalidates_identity(self):
        model = _ArtifactModel()
        before = mi.loaded_artifact_identity(model)
        model.calibrated_weights["hours"]["7"]["weight"] = 0.7
        after = mi.loaded_artifact_identity(model)
        self.assertNotEqual(before["loaded_artifact_hash"], after["loaded_artifact_hash"])

    def test_unbound_loaded_source_claim_is_incomplete_and_non_authoritative(self):
        model = _ArtifactModel()
        model._feature_model_hgb = object()
        model._loaded_artifact_source_hashes = {
            "feature_hgb": {"sha256": "a" * 64, "size": 123}
        }
        artifact_identity = mi.loaded_artifact_identity(model)
        replay_identity = mi.model_replay_identity(model)
        self.assertEqual(artifact_identity["status"], mi.FINGERPRINT_INCOMPLETE)
        self.assertIn("feature_hgb", artifact_identity["components_failed"])
        self.assertEqual(replay_identity["status"], mi.FINGERPRINT_INCOMPLETE)
        self.assertIsNone(replay_identity["identity_hash"])
        self.assertIsNone(mi.identity_hash(replay_identity))
        self.assertIsNotNone(replay_identity["diagnostic_identity_hash"])

    def test_exact_object_bound_source_hash_binds_unsupported_estimator_state(self):
        first = _ArtifactModel()
        second = _ArtifactModel()
        first._feature_model_hgb = object()
        second._feature_model_hgb = object()
        first._loaded_artifact_source_hashes = {
            "feature_hgb": _bound_source(first._feature_model_hgb, "a" * 64, 123)
        }
        second._loaded_artifact_source_hashes = {
            "feature_hgb": _bound_source(second._feature_model_hgb, "a" * 64, 123)
        }
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
        self.assertEqual(first_identity["status"], mi.FINGERPRINT_COMPLETE)

    def test_bound_source_change_invalidates_identity(self):
        model = _ArtifactModel()
        model._feature_model_hgb = object()
        model._loaded_artifact_source_hashes = {
            "feature_hgb": _bound_source(model._feature_model_hgb, "a" * 64, 123)
        }
        before = mi.loaded_artifact_identity(model)
        model._loaded_artifact_source_hashes["feature_hgb"] = _bound_source(
            model._feature_model_hgb,
            "b" * 64,
            124,
        )
        after = mi.loaded_artifact_identity(model)
        self.assertNotEqual(before["loaded_artifact_hash"], after["loaded_artifact_hash"])

    def test_unsupported_unbound_state_degrades_visibly(self):
        model = _ArtifactModel()
        model._feature_model_hgb = object()
        identity = mi.loaded_artifact_identity(model)
        self.assertIn("feature_hgb", identity["components_failed"])
        self.assertEqual(identity["status"], mi.FINGERPRINT_INCOMPLETE)
        hgb = next(row for row in identity["components"] if row["role"] == "feature_hgb")
        self.assertEqual(hgb["unsupported_entries"][0]["type"], "builtins.object")

    def test_release_graph_hash_alone_does_not_bind_materialized_estimator(self):
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
        self.assertEqual(hgb["state"], "fingerprint_error")
        self.assertEqual(hgb["error_type"], "_UnboundLoadedSourceHash")
        self.assertEqual(identity["status"], mi.FINGERPRINT_INCOMPLETE)


def _hashed_payload_keys(identity):
    """Keys that feed identity_hash, per model_replay_identity."""
    return {
        "schema_version",
        "status",
        "model_version",
        "market_id",
        "active_model_kind",
        "loaded_code_hash",
        "loaded_artifact_hash",
        "runtime_dependency_hash",
    }


def _source_fingerprint(source, filename):
    return _source_fingerprint_record(source, filename)["sha256"]


def _source_fingerprint_record(source, filename):
    name = "weather.model._identity_test_module"
    module = types.ModuleType(name)
    module.__file__ = filename
    exec(compile(source, filename, "exec"), module.__dict__)
    original = sys.modules.get(name)
    try:
        sys.modules[name] = module
        return mi.loaded_code_fingerprint(name)
    finally:
        if original is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = original


def _complete_loaded_code_identity():
    return {
        "modules": [],
        "loaded_code_hash": "c" * 64,
        "modules_loaded": 0,
        "modules_expected": 0,
        "modules_not_loaded": [],
        "modules_incomplete": [],
        "modules_failed": [],
        "marshal_version": mi.marshal.version,
        "python_version": sys.version.split()[0],
        "status": mi.FINGERPRINT_COMPLETE,
    }


def _incomplete_loaded_code_identity(record_status):
    record = {
        "module": "weather.model.synthetic_identity_gap",
        "loaded": record_status != mi.FINGERPRINT_UNLOADED,
        "status": record_status,
        "file": None,
        "code_units": None,
        "constants": None,
        "sha256": "d" * 64 if record_status == mi.FINGERPRINT_INCOMPLETE else None,
        "unsupported_entries": (
            [
                {
                    "owner": "constant:UNSUPPORTED",
                    "path": "module_constant.UNSUPPORTED",
                    "reason": "unsupported_type",
                    "type": "builtins.complex",
                }
            ]
            if record_status == mi.FINGERPRINT_INCOMPLETE
            else []
        ),
        "error_type": "RuntimeError" if record_status == mi.FINGERPRINT_ERROR else None,
    }
    return {
        "modules": [record],
        "loaded_code_hash": "e" * 64,
        "modules_loaded": int(record["loaded"]),
        "modules_expected": 1,
        "modules_not_loaded": (
            [record["module"]] if record_status == mi.FINGERPRINT_UNLOADED else []
        ),
        "modules_incomplete": (
            [record["module"]] if record_status == mi.FINGERPRINT_INCOMPLETE else []
        ),
        "modules_failed": (
            [record["module"]] if record_status == mi.FINGERPRINT_ERROR else []
        ),
        "marshal_version": mi.marshal.version,
        "python_version": sys.version.split()[0],
        "status": mi.FINGERPRINT_INCOMPLETE,
    }


def _bound_source(value, sha256, size):
    return {
        "sha256": sha256,
        "size": size,
        "binding": mi.LOADED_SOURCE_BINDING_MARKER,
        "object_id": id(value),
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

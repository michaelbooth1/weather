import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from weather.operations.release_bootstrap import (
    PARITY_DISPOSITION,
    assert_bootstrap_release_remains_inactive,
    bootstrap_release_lineage,
    evaluate_first_inactive_release_bootstrap,
    validate_first_inactive_release_bootstrap,
)
from weather.operations.release_manifest import (
    ReleaseLifecycleError,
    canonical_payload_sha256,
)


def _args(root: Path, **overrides):
    values = {
        "bootstrap_first_inactive_release": True,
        "releases_root": str(root / "artifacts" / "releases"),
        "release_pointer": str(
            root / "artifacts" / "releases" / "current_release.json"
        ),
        "release_candidate_mode": "production",
        "build_candidate_release": True,
        "skip_captured_input_replay_parity": False,
        "captured_input_parity_served": [],
        "captured_input_parity_replay": [],
        "release_parent": "",
        "repo_root": str(root),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class TestFirstInactiveReleaseBootstrap(unittest.TestCase):
    def test_explicit_empty_store_contract_is_self_hashed_and_parity_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = _args(Path(tmp))
            contract = evaluate_first_inactive_release_bootstrap(
                args,
                release_identity={"status": "BLOCK", "reason": "no pointer"},
            )
            validated = validate_first_inactive_release_bootstrap(
                contract,
                args=args,
            )

        self.assertEqual(validated["status"], "PASS")
        self.assertEqual(
            validated["contract_sha256"],
            canonical_payload_sha256(
                validated,
                omit=("contract_sha256",),
            ),
        )
        self.assertEqual(validated["active_pointer"]["state"], "ABSENT")
        self.assertEqual(validated["release_store"]["state"], "ABSENT")
        self.assertEqual(
            validated["pre_release_parity"]["disposition"],
            PARITY_DISPOSITION,
        )
        self.assertTrue(
            validated["pre_release_parity"]["ordinary_requirement_waived"]
        )
        self.assertEqual(
            set(validated["prohibited_actions"]),
            {"ACTIVE_POINTER_WRITE", "PROMOTION", "SERVING", "LIVE_FALLBACK"},
        )

    def test_disabled_contract_never_waives_parity(self):
        with tempfile.TemporaryDirectory() as tmp:
            contract = evaluate_first_inactive_release_bootstrap(
                _args(Path(tmp), bootstrap_first_inactive_release=False),
                release_identity={"status": "BLOCK"},
            )

        self.assertEqual(contract["status"], "DISABLED")
        self.assertFalse(
            contract["pre_release_parity"]["ordinary_requirement_waived"]
        )
        self.assertEqual(contract["pre_release_parity"]["disposition"], "REQUIRED")

    def test_requested_contract_blocks_every_ambiguous_or_nonfirst_state(self):
        cases = {
            "research_mode": (
                {"release_candidate_mode": "research_only"},
                "production_candidate_mode_required",
            ),
            "build_disabled": (
                {"build_candidate_release": False},
                "candidate_release_build_required",
            ),
            "generic_skip": (
                {"skip_captured_input_replay_parity": True},
                "generic_parity_skip_forbidden",
            ),
            "served_parity_supplied": (
                {"captured_input_parity_served": ["served.json"]},
                "preexisting_parity_inputs_forbidden",
            ),
            "parent_supplied": (
                {"release_parent": "prior-release"},
                "release_parent_forbidden",
            ),
        }
        for name, (overrides, expected_code) in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                contract = evaluate_first_inactive_release_bootstrap(
                    _args(Path(tmp), **overrides),
                    release_identity={"status": "BLOCK"},
                )
                codes = {row["code"] for row in contract["blockers"]}
            self.assertEqual(contract["status"], "BLOCK")
            self.assertIn(expected_code, codes)

    def test_existing_pointer_or_release_store_blocks_before_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            releases = root / "artifacts" / "releases"
            releases.mkdir(parents=True)
            (releases / "old-release").mkdir()
            (releases / "current_release.json").write_text("{}", encoding="utf-8")
            contract = evaluate_first_inactive_release_bootstrap(
                _args(root),
                release_identity={"status": "PASS", "release_id": "old-release"},
            )
            codes = {row["code"] for row in contract["blockers"]}

        self.assertEqual(contract["status"], "BLOCK")
        self.assertIn("active_pointer_not_absent", codes)
        self.assertIn("release_store_not_empty", codes)
        self.assertIn("serving_identity_already_exists", codes)

    def test_contract_tamper_and_parent_binding_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = _args(Path(tmp))
            contract = evaluate_first_inactive_release_bootstrap(
                args,
                release_identity={"status": "BLOCK"},
            )
            tampered = dict(contract)
            tampered["scope"] = "SERVING"
            with self.assertRaisesRegex(
                ReleaseLifecycleError,
                "bootstrap contract failed closed",
            ):
                validate_first_inactive_release_bootstrap(tampered, args=args)
            with self.assertRaisesRegex(
                ReleaseLifecycleError,
                "cannot bind a parent",
            ):
                bootstrap_release_lineage(
                    contract,
                    args=args,
                    parent_release="old-release",
                )

    def test_state_change_after_preflight_blocks_lineage_and_finalization(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            args = _args(root)
            contract = evaluate_first_inactive_release_bootstrap(
                args,
                release_identity={"status": "BLOCK"},
            )
            releases = Path(args.releases_root)
            releases.mkdir(parents=True)
            (releases / "unexpected-release").mkdir()
            with self.assertRaisesRegex(
                ReleaseLifecycleError,
                "release store changed",
            ):
                bootstrap_release_lineage(
                    contract,
                    args=args,
                    parent_release=None,
                )
            pointer = Path(args.release_pointer)
            pointer.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(
                ReleaseLifecycleError,
                "ended with an active pointer",
            ):
                assert_bootstrap_release_remains_inactive(contract, args=args)


if __name__ == "__main__":
    unittest.main()

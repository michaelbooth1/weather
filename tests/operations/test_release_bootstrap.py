import copy
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from weather.operations.release_bootstrap import (
    PARITY_DISPOSITION,
    assert_bootstrap_release_remains_inactive,
    bootstrap_release_lineage,
    evaluate_first_inactive_release_bootstrap,
    validate_first_inactive_release_bootstrap,
    verify_first_inactive_release,
)
from weather.operations.release_manifest import (
    ReleaseLifecycleError,
    canonical_payload_sha256,
)


def _create_directory_link_or_junction(alias: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    alias.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        result = subprocess.run(
            ["cmd", "/d", "/c", "mklink", "/J", str(alias), str(target)],
            check=False,
            capture_output=True,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode != 0:
            raise unittest.SkipTest(
                f"directory junction unavailable: {result.stderr}"
            )
        return
    try:
        alias.symlink_to(target, target_is_directory=True)
    except OSError as exc:
        raise unittest.SkipTest(f"directory symlink unavailable: {exc}") from exc


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

    def test_link_or_reparse_release_store_blocks_preflight_and_lineage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            args = _args(root)
            contract = evaluate_first_inactive_release_bootstrap(
                args,
                release_identity={"status": "BLOCK"},
            )
            self.assertEqual(contract["status"], "PASS")

            releases = Path(args.releases_root)
            external = root / "external-releases"
            _create_directory_link_or_junction(releases, external)

            blocked = evaluate_first_inactive_release_bootstrap(
                args,
                release_identity={"status": "BLOCK"},
            )
            codes = {row["code"] for row in blocked["blockers"]}
            self.assertEqual(blocked["status"], "BLOCK")
            self.assertEqual(
                blocked["release_store"]["state"],
                "LINK_OR_REPARSE",
            )
            self.assertIn("release_store_link_or_reparse", codes)
            self.assertIn("active_pointer_link_or_reparse", codes)
            with self.assertRaisesRegex(
                ReleaseLifecycleError,
                "symlink or reparse point",
            ):
                bootstrap_release_lineage(
                    contract,
                    args=args,
                    parent_release=None,
                )

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

    def test_post_freeze_verifier_requires_shadow_only_release_route(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            args = _args(root)
            contract = evaluate_first_inactive_release_bootstrap(
                args,
                release_identity={"status": "BLOCK"},
            )
            lineage = bootstrap_release_lineage(
                contract,
                args=args,
                parent_release=None,
            )
            release_id = "bootstrap-r1"
            release_dir = Path(args.releases_root) / release_id
            release_dir.mkdir(parents=True)
            route = {
                "promotion_verdict": "shadow",
                "promotion_eligibility": (
                    "BLOCKED_NON_AUTHORIZING_EVIDENCE"
                ),
                "promotion_authorization": {
                    "status": "BLOCKED_NON_AUTHORIZING_EVIDENCE",
                },
                "markets": {
                    "nyc": {
                        "decision": "shadow",
                        "counts_toward_promotion": False,
                        "serving_release": None,
                    }
                },
            }
            verified = {
                "release_id": release_id,
                "manifest_path": str(
                    release_dir / "release_manifest.json"
                ),
                "manifest_sha256": "a" * 64,
                "file_count": 1,
                "semantic_contract_verified": True,
                "semantic_contract": {
                    "candidate_mode": "production",
                    "production_capable": True,
                },
                "manifest": {
                    "state": "IMMUTABLE_CANDIDATE",
                    "parent_release": None,
                    "rollback_target": None,
                    "lineage": {
                        "first_inactive_release_bootstrap": lineage,
                    },
                    "route": route,
                },
            }
            release_result = {
                "status": "CREATED",
                "release_id": release_id,
                "manifest_sha256": "a" * 64,
            }
            with patch(
                "weather.operations.release_bootstrap.verify_release",
                return_value=verified,
            ):
                qualification = verify_first_inactive_release(
                    contract,
                    args=args,
                    release_result=release_result,
                )
            self.assertEqual(qualification["status"], "PASS")
            self.assertFalse(qualification["promotion_authorized"])
            self.assertFalse(qualification["serving_authorized"])

            invalid_routes = {}
            invalid_routes["verdict"] = copy.deepcopy(route)
            invalid_routes["verdict"]["promotion_verdict"] = "promote_ready"
            invalid_routes["eligibility"] = copy.deepcopy(route)
            invalid_routes["eligibility"]["promotion_eligibility"] = (
                "ELIGIBLE_FOR_GATED_PROMOTION"
            )
            invalid_routes["authorization"] = copy.deepcopy(route)
            invalid_routes["authorization"]["promotion_authorization"][
                "status"
            ] = "AUTHORIZED"
            invalid_routes["empty_markets"] = copy.deepcopy(route)
            invalid_routes["empty_markets"]["markets"] = {}
            for field, value in (
                ("decision", "promote"),
                ("counts_toward_promotion", True),
                ("serving_release", release_id),
            ):
                invalid_routes[field] = copy.deepcopy(route)
                invalid_routes[field]["markets"]["nyc"][field] = value

            for name, invalid_route in invalid_routes.items():
                with self.subTest(name=name):
                    invalid_verified = copy.deepcopy(verified)
                    invalid_verified["manifest"]["route"] = invalid_route
                    with patch(
                        "weather.operations.release_bootstrap.verify_release",
                        return_value=invalid_verified,
                    ), self.assertRaisesRegex(
                        ReleaseLifecycleError,
                        "first inactive release post-freeze verification failed",
                    ):
                        verify_first_inactive_release(
                            contract,
                            args=args,
                            release_result=release_result,
                        )


if __name__ == "__main__":
    unittest.main()

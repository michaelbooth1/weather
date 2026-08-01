import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from weather.calibration import pooled_feature_cli
from weather.calibration.family_secondary_artifacts import (
    build_parser as build_family_secondary_parser,
    cmd_train,
    family_specs,
)
from weather.reporting.promotion.cli import build_parser as build_promotion_parser
from weather.reporting.promotion.readers import _family_specs


def _spec(market_id, unit):
    return SimpleNamespace(id=market_id, display_unit=unit)


class TestFamilyUnitCliAdmission(unittest.TestCase):
    def test_pooled_trainer_admits_inactive_c_direct_band_lane(self):
        with (
            patch.object(sys, "argv", [
                "pooled-feature-model",
                "--family-unit", "C",
                "--objective", "band",
            ]),
            patch.object(pooled_feature_cli, "guard_training_artifact_output"),
            patch.object(pooled_feature_cli, "preflight_training_artifacts"),
            patch.object(
                pooled_feature_cli,
                "build_family_dataset",
                return_value=([], {}),
            ) as build_dataset,
        ):
            with self.assertRaisesRegex(SystemExit, "No pooled family records"):
                pooled_feature_cli.main()

        self.assertEqual(build_dataset.call_args.kwargs["unit"], "C")

    def test_pooled_trainer_f_default_is_unchanged(self):
        with (
            patch.object(sys, "argv", ["pooled-feature-model", "--objective", "band"]),
            patch.object(pooled_feature_cli, "guard_training_artifact_output"),
            patch.object(pooled_feature_cli, "preflight_training_artifacts"),
            patch.object(
                pooled_feature_cli,
                "build_family_dataset",
                return_value=([], {}),
            ) as build_dataset,
        ):
            with self.assertRaisesRegex(SystemExit, "No pooled family records"):
                pooled_feature_cli.main()

        self.assertEqual(build_dataset.call_args.kwargs["unit"], "F")

    def test_promotion_refresh_accepts_c_and_keeps_f_default(self):
        parser = build_promotion_parser()

        self.assertEqual(parser.parse_args([]).family_unit, "F")
        self.assertEqual(parser.parse_args(["--family-unit", "C"]).family_unit, "C")

    def test_family_secondary_accepts_c_and_keeps_f_default(self):
        parser = build_family_secondary_parser()

        self.assertEqual(parser.parse_args(["train"]).family_unit, "F")
        self.assertEqual(
            parser.parse_args(["train", "--family-unit", "C"]).family_unit,
            "C",
        )

    def test_family_secondary_c_requires_candidate_owned_outputs(self):
        args = build_family_secondary_parser().parse_args([
            "train",
            "--family-unit", "C",
        ])

        with self.assertRaisesRegex(SystemExit, "candidate --artifact-root"):
            cmd_train(args)

    def test_family_selection_is_native_unit_and_f_is_unchanged(self):
        specs = [_spec("nyc", "F"), _spec("toronto", "C")]

        self.assertEqual([spec.id for spec in _family_specs("F", specs=specs)], ["nyc"])
        self.assertEqual([spec.id for spec in _family_specs("C", specs=specs)], ["toronto"])
        with patch(
            "weather.calibration.family_secondary_artifacts.all_specs",
            return_value=specs,
        ):
            self.assertEqual([spec.id for spec in family_specs("F")], ["nyc"])
            self.assertEqual([spec.id for spec in family_specs("C")], ["toronto"])


if __name__ == "__main__":
    unittest.main()

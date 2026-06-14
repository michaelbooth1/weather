"""Item 10: the dashboard current-edge table contract.

The old edge table read a nonexistent ``groupItemTitle`` key (blank "Range"
labels) and re-summed only ``value`` (dropping calibration and, for F-market
2-degree bands, the band's upper bucket). The fixed table consumes the canonical
``bin_data['label']`` and ``bin_probability``. These tests lock that contract.
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath("src"))

from toronto_model import TorontoHighTempModel


def _event(labels):
    return {"markets": [
        {"groupItemTitle": label,
         "outcomes": json.dumps(["Yes", "No"]),
         "outcomePrices": json.dumps(["0.4", "0.6"])}
        for label in labels
    ]}


class TestEdgeTableContract(unittest.TestCase):
    def test_bins_carry_label_and_no_group_item_title(self):
        # The edge table reads bin_data['label']; the buggy fallback key
        # 'groupItemTitle' must never be present on the bin dict, so it cannot
        # silently win again and blank the labels.
        m = TorontoHighTempModel(market_id="nyc")
        bins = m.market_bins(_event(["75°F or below", "76-77°F", "94°F or higher"]))
        self.assertTrue(bins)
        for b in bins:
            self.assertTrue(b["label"], "bin label must be non-empty")
            self.assertNotIn("groupItemTitle", b)

    def test_edge_table_prob_is_range_aware(self):
        # An F 2-degree band must sum [value, value_hi]; the old value-only
        # path dropped the upper bucket (90 only -> 0.5 instead of 0.8).
        m = TorontoHighTempModel(market_id="nyc")
        dist = {88: 0.1, 89: 0.1, 90: 0.5, 91: 0.3}
        band = next(b for b in m.market_bins(_event(["90-91°F"])) if b["kind"] == "eq")
        self.assertEqual((band["value"], band["value_hi"]), (90, 91))
        prob = m.bin_probability(dist, band)
        self.assertAlmostEqual(prob, 0.8)
        # The old buggy single-bucket read would have produced 0.5.
        self.assertNotAlmostEqual(prob, dist[band["value"]])

    def test_toronto_exact_band_label_clean(self):
        m = TorontoHighTempModel()
        bins = m.market_bins(_event(["28 C", "30 C or higher"]))
        labels = {b["label"] for b in bins}
        self.assertIn("28 C", labels)


if __name__ == "__main__":
    unittest.main()

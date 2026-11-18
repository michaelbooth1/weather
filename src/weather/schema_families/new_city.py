"""Schema records for the new-city model lane (M1): ``weather.calibration.new_city_corpus``.

A family module (Data Layer v2 PL-2): it imports only ``weather.schema_registry_types``
and no capture loop imports it, so these schemas stay out of the frozen core.
"""

from weather.schema_registry_types import SchemaSpec

SCHEMAS = (
    SchemaSpec(
        "new_city_metar_label",
        "new_city_metar_label_v1",
        "weather.calibration.new_city_corpus",
        "active",
        "Daily IEM METAR label for a candidate new city, keyed on observation-time local date, with completeness.",
    ),
    SchemaSpec(
        "new_city_training_row",
        "new_city_training_row_v1",
        "weather.calibration.new_city_corpus",
        "active",
        "Candidate-city training row: PIT forecast high, METAR observed-so-far at the cutoff, METAR label.",
    ),
    SchemaSpec(
        "new_city_training_corpus_manifest",
        "new_city_training_corpus_manifest_v1",
        "weather.calibration.new_city_corpus",
        "active",
        "Content-addressed manifest of a candidate-city METAR-labelled training corpus and its input hashes.",
    ),
)

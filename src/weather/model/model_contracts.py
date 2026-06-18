"""Explicit model build contracts.

The public facade still returns dictionaries for compatibility, but these
dataclasses define the durable boundary between source collection, distribution
estimation, presentation, and snapshot persistence.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field


def _copy_dict(value):
    return deepcopy(dict(value or {}))


@dataclass(frozen=True)
class SourceBundle:
    historical_sources: dict = field(default_factory=dict)
    live_sources: dict = field(default_factory=dict)
    combined_sources: dict = field(default_factory=dict)

    @classmethod
    def from_groups(cls, historical_sources=None, live_sources=None):
        return cls(
            historical_sources=_copy_dict(historical_sources),
            live_sources=_copy_dict(live_sources),
        )

    @classmethod
    def from_combined(cls, sources=None):
        return cls(combined_sources=_copy_dict(sources))

    @property
    def sources(self):
        if self.combined_sources:
            return _copy_dict(self.combined_sources)
        merged = _copy_dict(self.historical_sources)
        merged.update(_copy_dict(self.live_sources))
        return merged

    def as_dict(self):
        return {
            "historical_sources": _copy_dict(self.historical_sources),
            "live_sources": _copy_dict(self.live_sources),
            "combined_sources": self.sources,
        }


@dataclass(frozen=True)
class DistributionResult:
    distribution: dict = field(default_factory=dict)
    component_payload: dict = field(default_factory=dict)
    calibration_context: dict = field(default_factory=dict)
    active_model_kind: str = "empirical"
    family_secondary_gate: dict = field(default_factory=dict)

    @classmethod
    def from_model(cls, model, distribution):
        component_payload = _copy_dict(getattr(model, "_last_distribution_components", {}) or {})
        calibration_context = _copy_dict(getattr(model, "_last_probability_calibration_context", {}) or {})
        family_secondary_gate = _copy_dict(getattr(model, "_last_family_secondary_gate", {}) or {})
        return cls(
            distribution=_copy_dict(distribution),
            component_payload=component_payload,
            calibration_context=calibration_context,
            active_model_kind=str(getattr(model, "active_model_kind", "empirical") or "empirical"),
            family_secondary_gate=family_secondary_gate,
        )

    @property
    def components(self):
        return _copy_dict((self.component_payload or {}).get("components") or {})

    def as_dict(self):
        return {
            "distribution": _copy_dict(self.distribution),
            "distribution_components": _copy_dict(self.component_payload),
            "probability_calibration_context": _copy_dict(self.calibration_context),
            "active_model_kind": self.active_model_kind,
            "family_secondary_gate": _copy_dict(self.family_secondary_gate),
        }


@dataclass(frozen=True)
class ModelBuildResult:
    source_bundle: SourceBundle
    built_at: str
    distribution_result: DistributionResult
    model_rows: list = field(default_factory=list)
    source_rows: list = field(default_factory=list)
    source_diagnostics: list = field(default_factory=list)
    forecast_rows: list = field(default_factory=list)
    deep_dive_rows: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    top_temp: int | float | None = None
    model_version: str | None = None
    feature_vector: dict | None = None
    boundary_transitions: dict | None = None
    late_day_risk: dict | None = None
    source_health: dict | None = None
    analog_search: dict | None = None
    model_explanation: dict | None = None

    def as_dict(self):
        distribution_payload = self.distribution_result.as_dict()
        return {
            "sources": self.source_bundle.sources,
            "source_bundle": self.source_bundle.as_dict(),
            "built_at": self.built_at,
            "distribution": _copy_dict(self.distribution_result.distribution),
            "distribution_components": distribution_payload["distribution_components"],
            "probability_calibration_context": distribution_payload["probability_calibration_context"],
            "active_model_kind": distribution_payload["active_model_kind"],
            "family_secondary_gate": distribution_payload["family_secondary_gate"],
            "distribution_result": distribution_payload,
            "model_rows": deepcopy(list(self.model_rows or [])),
            "source_rows": deepcopy(list(self.source_rows or [])),
            "source_diagnostics": deepcopy(list(self.source_diagnostics or [])),
            "forecast_rows": deepcopy(list(self.forecast_rows or [])),
            "deep_dive_rows": deepcopy(list(self.deep_dive_rows or [])),
            "notes": deepcopy(list(self.notes or [])),
            "top_temp": self.top_temp,
            "model_version": self.model_version,
            "feature_vector": _copy_dict(self.feature_vector),
            "boundary_transitions": _copy_dict(self.boundary_transitions),
            "late_day_risk": _copy_dict(self.late_day_risk),
            "source_health": _copy_dict(self.source_health),
            "analog_search": _copy_dict(self.analog_search),
            "model_explanation": _copy_dict(self.model_explanation),
        }

"""Bounded calibration-method projection, never release serving or promotion.

The captured source binds the release manifest's content hash; that manifest
binds the market's calibration JSON. No active pointer or model is opened.
"""
from maker_core.replay.bundle import sha256
from weather.market.maker_plugin.inputs import event_identity
from weather.market.maker_plugin_sources import Sources
from weather.release_artifacts import (
    manifest_content_sha256, safe_relative_artifact_path, strict_json_loads, validate_release_id,
)
from weather.schema_registry import schema_version


class ReleaseSources(Sources):
    def __init__(self, reader, day, markets, release_root):
        super().__init__(reader, day, markets)
        self.release_root, self.methods = release_root, {}

    def calibration(self, row, market):
        if self.release_root is None:
            return row.get("release_calibration_method"), None
        release = validate_release_id(row["release_id"])
        key = release, row["release_manifest_sha256"], market
        if key not in self.methods:
            folder = self.release_root / release
            raw = self.reader.read_release(self.release_root, folder / "release_manifest.json")
            manifest = strict_json_loads(raw.decode("utf-8"), label="replay release manifest")
            if (manifest["schema_version"] != schema_version("release_manifest") or
                    manifest["release_id"] != release or manifest["manifest_sha256"] != key[1] or
                    manifest_content_sha256(manifest) != key[1]):
                raise ValueError("release_calibration_manifest_binding")
            role = f"base_model.{market}.probability_calibration"
            candidates = [r for r in manifest["artifacts"]["inventory"]
                          if r.get("role") == role and r.get("declared") is True and r.get("kind") == "calibration"]
            if len(candidates) != 1:
                raise ValueError("release_calibration_role_missing_or_ambiguous")
            artifact = candidates[0]
            path = folder / safe_relative_artifact_path(artifact["path"])
            raw = self.reader.read_release(self.release_root, path)
            if len(raw) != artifact["bytes"] or sha256(raw) != artifact["sha256"]:
                raise ValueError("release_calibration_artifact_binding")
            method = strict_json_loads(raw.decode("utf-8"), label="replay calibration")["market_bin"]["method"]
            if not isinstance(method, str) or not method or method.strip() != method:
                raise ValueError("invalid_release_calibration_method")
            self.methods[key] = method, artifact["sha256"]
        return self.methods[key]

    def for_event(self, slug):
        support = super().for_event(slug)
        if support.get("release_projected"):
            return support  # A cache hit: projected once, providers built once.
        market, _ = event_identity(slug)
        projected = []
        for row in support["source_rows"]:
            self.reader.check()
            row = dict(row)
            if row.get("release_identity_status") == "verified_variant_serving_bundle":
                method, artifact_hash = self.calibration(row, market.id)
                if row.get("release_calibration_method") not in (None, "", method):
                    raise ValueError("captured_release_calibration_conflict")
                row["release_calibration_method"] = method
                if artifact_hash:
                    row["release_calibration_artifact_sha256"] = artifact_hash
            else:
                row.setdefault("release_calibration_method", None)
            projected.append(row)
        result = dict(support, source_rows=projected, release_projected=True)
        # Replace the cached entry in place (same budget accounting) so the next
        # minute reuses this projection and the providers built on it, instead of
        # rebuilding both for every book capture.
        if slug in self.cache and self.cache[slug][1] is support:
            self.cache[slug] = (self.cache[slug][0], result)
        return result

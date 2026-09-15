"""Fixed disposable host probes; no command, test selection or network option."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import sys


def main():
    if not sys.flags.isolated or not sys.flags.no_site or not sys.dont_write_bytecode or len(sys.argv) != 3:
        raise ValueError("fixed isolated probe bootstrap required")
    raw = Path(sys.argv[1]).read_bytes()
    if len(raw) > 2 * 1024**2 or hashlib.sha256(raw).hexdigest() != sys.argv[2]:
        raise ValueError("host probe request changed")
    import json
    request = json.loads(raw)
    if set(request) != {"candidate", "trusted_root", "bootstrap_sha256", "trusted_modules", "authority_root",
                        "source_inventory", "sites", "output", "configuration_root", "configuration", "forbidden_roots"}:
        raise ValueError("unsupported host probe request")
    bootstrap = Path(request["trusted_root"]) / "scripts/ops/qualification_host_child.py"
    code = bootstrap.read_bytes()
    if hashlib.sha256(code).hexdigest() != request["bootstrap_sha256"]:
        raise ValueError("adopted probe bootstrap changed")
    namespace = {"__name__": "_qualification_probe_bootstrap", "__file__": str(bootstrap)}
    exec(compile(code, str(bootstrap), "exec"), namespace)
    sys.meta_path.insert(0, namespace["FrozenModules"](
        Path(request["trusted_root"]) / "src/weather/operations/qualification", request["trusted_modules"]))
    from _weather_qualification_host_authority import contracts, records, offline_guard, inputs

    request = records.decode(raw)
    candidate = records.checked_root(Path(request["candidate"]))
    output = records.checked_root(Path(request["output"]))
    records.require(Path.cwd().resolve() == candidate, "probe candidate working directory differs")
    expected = {row["path"]: row for row in contracts.inventory(
        contracts.Graph(Path(request["authority_root"])).get(request["source_inventory"]),
        "qualification_source_inventory_v2")["files"]}
    sites = [str(records.checked_root(Path(path))) for path in request["sites"]]
    offline_guard.install(writable_roots=[str(output)], forbidden_roots=request["forbidden_roots"], executable_paths=[])
    sys.path[:] = [str(candidate), str(candidate / "src"), *sites,
                   *(entry for entry in sys.path if entry and Path(entry).is_absolute())]
    from weather.operations import event_metadata_validation
    from weather.market import market_registry
    from weather.market import live_sdk_overlay
    import importlib
    sdk = importlib.import_module(live_sdk_overlay.EXPECTED_IMPORT_PACKAGE)
    records.require(str(sdk.__version__) == live_sdk_overlay.EXPECTED_VERSION,
                    "qualified International SDK import version differs")
    records.require(not market_registry.validate_market_registry(), "candidate market registry is invalid")
    qgraph = contracts.Graph(Path(request["configuration_root"]))
    configuration = qgraph.get(request["configuration"])
    pair = {}
    for item in configuration["generated"]:
        ref = item["payload"]
        with records.open_record(qgraph.root, ref["path"]) as handle:
            body = handle.read(2 * 1024**2 + 1)
        records.require(len(body) == ref["size"] and hashlib.sha256(body).hexdigest() == ref["sha256"],
                        "probe generated configuration drift")
        pair[item["path"]] = inputs._input_object(body.decode("utf-8"))
    locations = event_metadata_validation.locations_by_id(pair["config/locations.json"])
    generated = event_metadata_validation.generated_locations_by_id(pair["config/location_market_events.json"])
    records.require(locations and generated and set(generated) == set(locations), "generated location overlay is incomplete")
    identities = []
    for name, module in sorted(sys.modules.items()):
        if name != "weather" and not name.startswith("weather."):
            continue
        path = Path(module.__file__).resolve()
        relative = path.relative_to(candidate).as_posix()
        content = path.read_bytes()
        pin = expected.get(relative)
        records.require(pin is not None and pin["size"] == len(content) and
                        pin["sha256"] == hashlib.sha256(content).hexdigest(), "probe import escaped reviewed S")
        identities.append({"module": name, "path": relative, "sha256": pin["sha256"]})
    records.require(identities, "native candidate imports are empty")
    records.require(sys.stdin.read() == "", "probe stdin inherited interactive authority")
    approved = {"SYSTEMROOT", "WINDIR", "COMSPEC", "SYSTEMDRIVE", "PATHEXT", "PATH", "TEMP", "TMP", "TMPDIR",
                "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "PSMODULEANALYSISCACHEPATH",
                "PYTHONDONTWRITEBYTECODE", "PYTHONNOUSERSITE",
                "PYTHONHASHSEED", "PYTEST_DISABLE_PLUGIN_AUTOLOAD", "WEATHER_INTEGRATION_TEST_OFFLINE",
                "GIT_CONFIG_NOSYSTEM", "GIT_CONFIG_GLOBAL", "GIT_TERMINAL_PROMPT", "GIT_LFS_SKIP_SMUDGE", "TZ", "LANG", "LC_ALL"}
    records.require(all(key.upper() in approved for key in os.environ), "probe environment contains undeclared authority")
    records.require(os.environ.get("PSModuleAnalysisCachePath") == os.devnull,
                    "native PowerShell module cache is not disabled")
    paths = [os.path.normcase(os.path.realpath(entry)) for entry in os.environ["PATH"].split(os.pathsep) if entry]
    records.require(len(paths) == len(set(paths)), "native PATH contains duplicate executable roots")
    once = records.publish(output, "create-once.json", {"nonce": "native-disposable-probe"})
    try:
        records.publish(output, "create-once.json", {"nonce": "must-not-replace"})
    except FileExistsError:
        pass
    else:
        raise ValueError("native create-once collision was accepted")
    records.require(records.read(output, once).value == {"nonce": "native-disposable-probe"},
                    "native create-once bytes changed")
    results = {}
    for name, detail in {
        "isolated_imports": "Exact candidate imports and qualified SDK loaded from pinned roots",
        "configuration_overlay": "Complete generated pair loaded by candidate read-only location readers",
        "offline_environment": "Actual child environment contains only fixed offline keys",
        "duplicate_path": "Actual normalized PATH has distinct approved executable roots",
        "stdin_eof": "Native child observed immediate stdin EOF",
        "create_once_flush_rename": "Native durable publication read back and refused replacement",
    }.items():
        results[name] = records.publish(output, name + ".json",
            {"schema": "qualification_host_probe_v2", "name": name, "status": "PASS", "detail": detail})
    records.publish(output, "probe-results.json", {"results": results, "imports": identities,
        "markets": sorted(market_registry.REGISTRY), "integration_eligible": False})
    print("qualification host stdout fixture", flush=True)
    print("qualification host stderr fixture", file=sys.stderr, flush=True)


if __name__ == "__main__":
    main()

"""Streaming JUnit corroboration without DTDs, entities or a retained XML tree."""

from __future__ import annotations

import hashlib
from xml.parsers import expat

from .records import digest, fields, integer, open_record, relative_path, require


def verify(root, ref, results):
    fields(ref, {"path", "sha256", "size"})
    relative_path(ref["path"])
    digest(ref["sha256"])
    integer(ref["size"], minimum=1, maximum=128 * 1024**2)
    parser = expat.ParserCreate()
    stack, cases, suite_totals = [], [], []
    active = None
    tags = {"testsuites", "testsuite", "testcase", "properties", "property", "system-out", "system-err",
            "failure", "error", "skipped"}

    def no_declarations(*args):
        require(False, "JUnit DTD/entity declarations are forbidden")

    def start(name, attributes):
        nonlocal active
        require(name in tags and len(stack) < 8 and len(attributes) <= 32, "unsupported JUnit structure")
        require(all(len(key) <= 128 and len(value) <= 8192 for key, value in attributes.items()),
                "JUnit attribute exceeds bound")
        if name == "testsuites":
            require(not stack, "nested JUnit root")
        elif name == "testsuite":
            require(not stack or stack == ["testsuites"], "nested JUnit suite")
            totals = {}
            for key in ("tests", "failures", "errors", "skipped"):
                raw = attributes.get(key)
                require(type(raw) is str and raw.isascii() and raw.isdigit() and len(raw) <= 8,
                        "invalid JUnit suite counts")
                totals[key] = int(raw)
            suite_totals.append(totals)
        elif name == "testcase":
            require(stack and stack[-1] == "testsuite" and active is None, "JUnit case outside suite")
            require(len(cases) < 100_000 and attributes.get("name") and attributes.get("classname"),
                    "JUnit case identity missing or count exceeded")
            active = {"name": attributes["name"], "classname": attributes["classname"], "outcome": "pass"}
        elif name in {"error", "failure", "skipped"}:
            require(stack and stack[-1] == "testcase" and active is not None and active["outcome"] == "pass",
                    "duplicate or misplaced JUnit outcome")
            active["outcome"] = ("xfail" if attributes.get("type") == "pytest.xfail" else "skip") if name == "skipped" else "fail"
        elif name == "property":
            require(stack and stack[-1] == "properties", "JUnit property outside properties")
        else:
            require(stack and stack[-1] in {"testcase", "testsuite"}, "misplaced JUnit payload")
        stack.append(name)

    def end(name):
        nonlocal active
        require(stack and stack[-1] == name, "malformed JUnit tail")
        stack.pop()
        if name == "testcase":
            cases.append(active)
            active = None

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.StartDoctypeDeclHandler = no_declarations
    parser.EntityDeclHandler = no_declarations
    parser.ExternalEntityRefHandler = no_declarations
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    hasher, count = hashlib.sha256(), 0
    with open_record(root, ref["path"]) as handle:
        while block := handle.read(min(64 * 1024, ref["size"] + 1 - count)):
            count += len(block)
            require(count <= ref["size"], "JUnit grew")
            hasher.update(block)
            parser.Parse(block, False)
        parser.Parse(b"", True)
    require(count == ref["size"] and hasher.hexdigest() == ref["sha256"], "JUnit bytes differ")
    require(not stack and active is None and suite_totals and len(cases) == len(results) > 0, "missing JUnit cases or tail")
    for case, result in zip(cases, results, strict=True):
        parts = result["nodeid"].split("::")
        classname = ".".join([parts[0].removesuffix(".py").replace("/", "."), *parts[1:-1]])
        require(case == {"name": parts[-1], "classname": classname, "outcome": result["outcome"]},
                "JUnit contradicts native event journal")
    totals = {key: sum(suite[key] for suite in suite_totals) for key in ("tests", "failures", "errors", "skipped")}
    require(totals == {"tests": len(results), "failures": 0, "errors": 0,
                       "skipped": sum(case["outcome"] in {"skip", "xfail"} for case in cases)},
            "JUnit counts contradict native results")
    return totals

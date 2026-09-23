"""Load only public-read definitions from frozen live sources, without imports.

The live modules combine public reads with order/credential code. Importing
them would violate the probe boundary; editing them would violate the campaign
freeze. This explicit source projection compiles the original AST definitions
unchanged. It is temporary qualification infrastructure, not a live runtime.
"""
from __future__ import annotations

import ast
import builtins
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from functools import lru_cache
import hashlib
import json
import re
import subprocess
from types import SimpleNamespace
from urllib.parse import urlencode, urlsplit
from urllib.request import Request

from weather.market.exchange_economics_sources import MAX_RESPONSE_BYTES, json_response_payload, response_evidence
from weather.market.reward_quote import _decimal
from weather.operations.live_path_security import assert_no_ambient_proxy_configuration
from weather.paths import REPO_ROOT


SELECTIONS = {
    're1_owner_checks': ('code_identity',),
    're1_transport': ('_user_agent', 'json_read', 'geography', 'condition_configurations', 'RPC', 'GEOBLOCK'),
    'mm_official_adapter': ('fetch_current_positions', 'CURRENT_POSITIONS_URL', 'EVM_ADDRESS_RE', 'CONDITION_ID_RE'),
    'mm_stage2_hold': ('utc',),
    'mm_stage2_selection': ('PublicBooks', 'reward_rate'),
}


def public_definitions(opener):
    """Return unchanged public functions bound to a real, one-shot opener.

    No source module is imported and no module initializer executes. Only
    explicitly named definitions/constants are admitted; unknown dependencies
    fail, rather than loading the live module as a fallback.
    """
    namespace = dict(datetime=datetime, timezone=timezone, Decimal=Decimal,
                     InvalidOperation=InvalidOperation, lru_cache=lru_cache,
                     hashlib=hashlib, json=json, re=re, subprocess=subprocess,
                     urlencode=urlencode, urlsplit=urlsplit, Request=Request,
                     urlopen=opener, REPO_ROOT=REPO_ROOT,
                     HOST='https://clob.polymarket.com', MAX_RESPONSE_BYTES=MAX_RESPONSE_BYTES,
                     json_response_payload=json_response_payload, response_evidence=response_evidence,
                     _decimal=_decimal, assert_no_ambient_proxy_configuration=assert_no_ambient_proxy_configuration)

    def safe_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == 'weather.market.re1_owner_checks' and fromlist == ('code_identity',):
            return SimpleNamespace(code_identity=namespace['code_identity'])
        if name == 're' and not level:
            return re
        raise ImportError(f'public source projection refuses import: {name}')

    namespace['__builtins__'] = {**vars(builtins), '__import__': safe_import}
    namespace['__name__'] = __name__
    hashes = {}
    for module, names in SELECTIONS.items():
        path = REPO_ROOT / 'src/weather/market' / (module + '.py')
        source = path.read_bytes()
        tree = ast.parse(source, filename=str(path))
        selected = []
        found = set()
        for node in tree.body:
            symbols = ([node.name] if isinstance(node, (ast.FunctionDef, ast.ClassDef)) else
                       [target.id for target in node.targets if isinstance(target, ast.Name)]
                       if isinstance(node, ast.Assign) else [])
            if set(symbols) & set(names):
                selected.append(node)
                found.update(set(symbols) & set(names))
        if found != set(names):
            raise RuntimeError(f'public definitions changed in {module}: {set(names) - found}')
        projected = ast.Module(body=selected, type_ignores=[])
        # Future flags affect compilation; no actual import is needed at exec.
        import __future__
        exec(compile(ast.fix_missing_locations(projected), str(path), 'exec',
                     flags=__future__.annotations.compiler_flag), namespace)
        hashes[module] = hashlib.sha256(source).hexdigest()
    namespace['source_sha256'] = hashes
    return SimpleNamespace(**{key: value for key, value in namespace.items() if not key.startswith('__')})

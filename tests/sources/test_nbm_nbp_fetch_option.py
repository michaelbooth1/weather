"""Offline checks for the opt-in NBP product of the L12 NBM block fetcher (lane L14, Toronto CYYZ).

Guards: tools/research/nbm_nbs_nbh_fetch.py ``--products nbp`` contract - the NBP bulletin key
``blend_nbptx.tHHz`` is listed and located like NBS/NBH, an NBP station block (CYYZ included) is
recognised only at a line start, unknown products are refused rather than silently dropped, the
default product set stays NBS/NBH, and the located CYYZ block parses with parser v2 when CYYZ is
mapped to America/Toronto in-process.
"""
from datetime import date

import pytest

from tools.research import nbm_nbs_nbh_fetch as fetch

HEADER = " CYYZ    NBM V4.0 NBP GUIDANCE    8/01/2021  0700 UTC                           "
BODY = [
    "        MON 02| TUE 03| WED 04| THU 05| FRI 06| SAT 07| SUN 08|MON 09 |TUE 10   ",
    " UTC    00  12| 00  12| 00  12| 00  12| 00  12| 00  12| 00  12| 00  12| 00  12  ",
    " FHR    17  29| 41  53| 65  77| 89 101|113 125|137 149|161 173|185 197|209 221  ",
    " TXNMN  75  57| 78  58| 81  62| 83  64| 85  66| 87  69| 89  71| 89  72| 89  72  ",
    " TXNSD   3   2|  2   2|  2   2|  2   2|  2   3|  3   3|  3   3|  4   3|  5   4  ",
    " TXNP1  70  54| 75  55| 78  59| 80  61| 83  64| 84  65| 85  68| 84  68| 82  67  ",
    " TXNP2  73  56| 77  56| 80  60| 83  63| 84  65| 86  67| 87  69| 87  70| 85  70  ",
    " TXNP5  75  57| 78  58| 82  62| 84  64| 86  67| 87  69| 89  71| 90  72| 89  73  ",
    " TXNP7  77  59| 80  60| 83  63| 85  66| 87  69| 88  71| 91  73| 92  74| 92  75  ",
    " TXNP9  78  60| 81  62| 84  65| 86  68| 88  70| 89  72| 92  75| 94  77| 94  77  ",
    " " * 80,
]


def _block(station):
    return "\n".join([HEADER.replace("CYYZ", station)] + BODY) + "\n"


BULLETIN = ("1\n" + "".join(_block(s) for s in ("CWTA", "CYYZ", "KATL"))).encode()
OBJ = {"key": "blend.20210801/07/text/blend_nbptx.t07z", "size": len(BULLETIN), "etag": "e"}


class _Resp:
    def __init__(self, status, content):
        self.status_code, self.content = status, content


class _Session:
    def get(self, url, timeout=None, headers=None, params=None):
        if params is not None:  # bucket listing
            key = OBJ["key"]
            xml = ('<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
                   f'<Contents><Key>{key}</Key><LastModified>2021-08-01T08:31:34.000Z</LastModified>'
                   f'<ETag>"e"</ETag><Size>{len(BULLETIN)}</Size></Contents>'
                   '<Contents><Key>blend.20210801/07/text/blend_nbetx.t07z</Key><LastModified>x</LastModified>'
                   '<ETag>"f"</ETag><Size>9</Size></Contents></ListBucketResult>')
            return _Resp(200, xml.encode())
        if (headers or {}).get("If-Match") != '"e"':
            return _Resp(412, b"")
        lo, hi = headers["Range"].split("=")[1].split("-")
        return _Resp(206, BULLETIN[int(lo): int(hi) + 1])


def test_nbp_is_a_known_product_but_not_a_default():
    assert "nbp" in fetch.PRODUCTS
    parser_default = [a for a in fetch.main.__code__.co_consts if a == "nbs,nbh"]
    assert parser_default == ["nbs,nbh"]


def test_listing_finds_the_nbp_key_and_ignores_other_text_products():
    listing = fetch.Fetcher(_Session(), pause=0).list_text(date(2021, 8, 1), "07")
    assert set(listing) == {"nbp"}
    assert listing["nbp"]["key"] == OBJ["key"] and listing["nbp"]["etag"] == "e"


def test_nbp_header_only_at_a_line_start():
    data = b"xx CYYZ    NBM V4.0 NBP GUIDANCE\n KATL    NBM V4.0 NBP GUIDANCE\n"
    assert [(h[0], h[1]) for h in fetch.header_matches(data)] == [("KATL", "NBP")]


def test_cyyz_nbp_block_is_located_whole_and_parses_with_parser_v2():
    blob, rows = fetch.fetch_object(fetch.Fetcher(_Session(), pause=0), OBJ, ["CYYZ"], {}, {}, "nbp")
    assert rows["CYYZ"]["status"] == "ok"
    assert blob.decode() == _block("CYYZ")
    from weather.sources import nbm_probabilistic_tmax as nbp

    assert "CYYZ" not in nbp.NBM_NBP_STATION_TIMEZONES  # production table untouched
    nbp.NBM_NBP_STATION_TIMEZONES["CYYZ"] = "America/Toronto"
    try:
        p = nbp.parse_nbp_station_tmax(blob.decode(), "CYYZ", date(2021, 8, 1))
    finally:
        nbp.NBM_NBP_STATION_TIMEZONES.pop("CYYZ")
    assert p["available"] and (p["mean_native"], p["stddev_native"]) == (75.0, 3.0)


def test_unknown_product_is_refused(tmp_path):
    with pytest.raises(SystemExit, match="unknown product"):
        fetch.main(["--out-dir", str(tmp_path), "--products", "nbp,nbx", "--stations", "CYYZ",
                    "--years", "2021", "--months", "8", "--limit", "1"])

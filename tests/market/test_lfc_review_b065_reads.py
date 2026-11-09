"""Guards: B065 large evidence ceilings never allocate the ceiling per tiny read."""
from pathlib import Path
import pytest

from weather.market.lfc_recording_io import read_bytes, STATE_JSON_LIMIT


def test_small_receipt_under_campaign_ceiling_uses_bounded_reads(tmp_path, monkeypatch):
    path = tmp_path/'receipt.json'; path.write_bytes(b'{"checked":true}\n')
    original = Path.open; sizes = []
    class BoundedReader:
        def __init__(self, stream): self.stream = stream
        def __enter__(self): return self
        def __exit__(self, *args): return self.stream.__exit__(*args)
        def read(self, size):
            sizes.append(size)
            assert 0 < size <= 65536
            return self.stream.read(size)
    monkeypatch.setattr(Path, 'open', lambda self, *a, **kw: BoundedReader(original(self,*a,**kw)))
    assert read_bytes(path, STATE_JSON_LIMIT)==b'{"checked":true}\n'
    assert sizes==[65536,65536]


@pytest.mark.parametrize('limit', [0,1,65535,65536,65537])
def test_exact_budget_and_one_byte_over_still_refuse(tmp_path, limit):
    path = tmp_path/'receipt'
    expected = b'a'*limit; path.write_bytes(expected)
    assert read_bytes(path,limit)==expected
    with path.open('ab') as stream: stream.write(b'b')
    with pytest.raises(ValueError,match='recording_file_budget'): read_bytes(path,limit)

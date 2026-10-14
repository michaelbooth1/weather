import os

from tests.conftest import MAX_BASETEMP_CHARS, needs_short_basetemp


def test_long_requested_basetemp_is_relocated_on_windows_only():
    deep = "C:\\Users\\someone\\AppData\\Local\\Temp\\agent\\scratchpad\\" + "x" * 80
    assert needs_short_basetemp(deep, tempdir="C:\\T", user="u", is_windows=True)
    assert not needs_short_basetemp(deep, tempdir="C:\\T", user="u", is_windows=False)


def test_short_requested_basetemp_is_kept():
    # The bounded suite's chunk base temps must pass through unchanged.
    assert not needs_short_basetemp("C:\\pt\\bs-20261001T010000-001", tempdir="C:\\T" + "x" * 200,
                                    user="u", is_windows=True)


def test_deep_default_temp_root_is_relocated():
    assert needs_short_basetemp(None, tempdir="C:\\" + "t" * 60, user="u", is_windows=True)
    assert not needs_short_basetemp(None, tempdir="C:\\Users\\u\\AppData\\Local\\Temp", user="u",
                                    is_windows=True)


def test_this_session_tmp_path_leaves_room_for_nested_layouts(tmp_path):
    if os.name == "nt":
        basetemp = tmp_path.parent
        assert len(str(basetemp)) <= MAX_BASETEMP_CHARS

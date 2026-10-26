from types import SimpleNamespace

import pytest

from convo_gallery.cli import resolve_inputs


def _cfg(**kw):
    base = {"MEDIA_DIR": "", "ROSTER_DIR": "", "ROOT_FOLDER_ID": "", "ROSTER_FOLDER_ID": ""}
    base.update(kw)
    return SimpleNamespace(**base)


def test_photos_only_is_local_without_roster():
    assert resolve_inputs("/p", None, None, None, _cfg()) == {"mode": "local", "media": "/p", "roster": None}


def test_photos_and_people():
    assert resolve_inputs("/p", "/h", None, None, _cfg())["roster"] == "/h"


def test_media_id_only_is_drive():
    r = resolve_inputs(None, None, "mid", None, _cfg())
    assert r == {"mode": "drive", "media": "mid", "roster": None}


def test_local_wins_over_drive():
    assert resolve_inputs("/p", None, "mid", "rid", _cfg())["mode"] == "local"


def test_nothing_exits():
    with pytest.raises(SystemExit):
        resolve_inputs(None, None, None, None, _cfg())


def test_config_media_dir_is_local():
    r = resolve_inputs(None, None, None, None, _cfg(MEDIA_DIR="/env"))
    assert r["mode"] == "local" and r["media"] == "/env"

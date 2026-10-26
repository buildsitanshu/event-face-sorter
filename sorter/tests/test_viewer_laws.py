import os
import re

import pytest
from convo_gallery import export_web

VIEWER = os.path.join(os.path.dirname(export_web.__file__), "viewer")
ALL = ("index.html", "app.js", "tokens.css")


def _read(name):
    with open(os.path.join(VIEWER, name), encoding="utf-8") as fh:
        return fh.read()


@pytest.mark.parametrize("name", ALL)
@pytest.mark.parametrize("banned", ["transition", "animation", "@keyframes"])
def test_no_motion(name, banned):
    assert banned not in _read(name)


@pytest.mark.parametrize("name", ["index.html", "app.js"])
@pytest.mark.parametrize(
    "label,pattern",
    [
        ("external url", r"https?://"),
        ("css url()", r"url\("),
        ("@import", r"@import"),
        ("hex colour", r"#[0-9a-fA-F]{3,8}"),
        ("raw px", r"[0-9]px"),
    ],
)
def test_tokens_only_and_offline(name, label, pattern):
    assert re.search(pattern, _read(name)) is None, f"{name} contains {label}"


@pytest.mark.parametrize("token", ["--color-bg", "--color-text", "--fs-xs", "--space-4"])
def test_tokens_defined(token):
    assert re.search(re.escape(token) + r"\s*:", _read("tokens.css"))

"""Nothing private ships: scan every tracked file for listed identifiers, secret shapes, private hosts and binaries.

What it proves: no tracked file contains a listed private identifier (matched by SHA-256 digest of a sliding
window, and of whole words, so this file does not hold the identifiers), a generic secret or key shape, a
private host shape, a user home path, a Drive-id shape, an email address or personal mail domain outside the
author lines, an Indian mobile number shape, an em dash or an emoji. Every tracked file must be UTF-8 text:
a file holding a NUL byte, a file that fails UTF-8 decoding, and a file with a banned extension (images, video,
databases, pickles, model weights, archives, PDF) are failures, never skips.

Before the digest and word scans the text is normalised: NFKC (full-width lookalikes become ASCII), soft hyphen
and zero-width characters removed, no-break space made a plain space, URL encoding decoded, lowercased. The
sliding-window digest scan then runs on the raw text lowercased (normalising can eat a token: URL-decoding
swallows the first two letters of a token written after a percent sign, and NFKC merges a last letter with a
combining accent that follows it), on the normalised text, on the normalised text with every whitespace
character removed (a single word split by a line wrap), and on the normalised text with each whitespace run
collapsed to one space (a two-word token whose space became a line break).

Its limit: HTML entities and base64 encodings are not decoded, so a token written that way is not caught. A
token typed in a different script (a transliteration, or lookalike letters that NFKC does not fold) is not
caught. File and folder names are not scanned, only file contents (a name is read only for the banned-extension
check). The scan reads the working tree, so a change committed and then reverted before the scan is not seen in
history: push a single squashed commit. It guards against accidental leaks, not an adversary.

Walk mode (no .git folder) does not read `*.egg-info` folders, `.DS_Store` or `.env` files, nor `.venv`,
`node_modules`, cache folders or `sorter/data`: these are generated or local and gitignored, so a token placed
only there is not caught in walk mode. Git mode lists every tracked file and every untracked file not ignored.

It never skips a listed file. With a .git folder it scans `git ls-files` plus untracked files that are not ignored;
without one (a ZIP download) it walks the tree. `scripts/check.sh` runs it as its own step before the suites.
"""
import hashlib
import os
import re
import subprocess
import unicodedata
import urllib.parse

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

# digests of tokens that must never appear; the tokens themselves are not in this repo.
# Each entry is (length, sha256 hex of the lowercased token).
DIGESTS = [
    (4, "bcfd719f09c980f6dfba58e47b994508dfa6639f6698ff33f9d1c074eda325bb"),
    (6, "2cd35d9fb7619e34af2e7952c74bc75febdbfd407212b09b476fc32b101abc68"),
    (11, "9cfb5ed585c9bf0042b2764d9956dba87627e00cc64ad1e59f8fa57124dbbce2"),
    (7, "a90770665a338e9d56ed5a2de70288b554d4e4acd174365913ad3fab0639828e"),
    (9, "2da59699d8198376303b41814a900929bbfe3a8747eb0403151f11299c8863fb"),
    (13, "d85992ad29f85fa3303fcf1e106bf07f9ad25594ac7d660abb3c776c0f5758f1"),
    (6, "2d9fc5715ed5b94a230884cee901c7ab178e7517a27e6d1c15830413d2e35610"),
    (8, "9052432cf323c46e29281a933d67f8ff05a6b39e5e147d848c5190f1a85f497a"),
    (6, "443f013f7c0529a44e4e55eff6ed7d0704399bc4f03f54a7a04829675579947e"),
    (7, "3ff2071e756ad240e28b307aa64174af90ef1083509c46f2b4d2b9e49a8ff10f"),
    (9, "1d7206055830c1a6f197b99b6e9f93c5eae2e28c62d7988d83de181d14acf889"),
]
DIGESTS_BY_LENGTH: dict[int, set[str]] = {}
for _n, _h in DIGESTS:
    DIGESTS_BY_LENGTH.setdefault(_n, set()).add(_h)

# whole-word tokens, lowercased; the words themselves are not in this repo.
# Each entry is the sha256 hex of one word as `re.findall(r"[a-z0-9]+", ...)` yields it from normalised text.
WORD_DIGESTS: set[str] = {
    "dd2dcc2d8f206914122e5376e83de8f129b1c2b99d2c878a9e10be39d90a1c5f",
}

# A Drive-id-shaped word: "1" plus 27 to 40 id characters standing as a whole word. It applies alongside the run
# rule below (_has_drive_id), which needs a digit after the "1" but also finds an id glued to other id characters.
DRIVE_ID_WORD = re.compile(r"\b1[A-Za-z0-9_-]{27,40}\b")

# Generic shapes. Patterns that would match their own source text are written in pieces.
GENERIC = [
    re.compile("/Us" + "ers/"),
    re.compile(r"100\.\d+\.\d+\.\d+"),
    re.compile(r"192\.168\."),
    re.compile(r"\.ts\.net"),
    re.compile(r"\.loc" + r"al\b"),
    re.compile(r"AIza[0-9A-Za-z_-]{30,}"),
    re.compile(r"ya29\."),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"ghp_[A-Za-z0-9]{30,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"BEGIN (RSA|OPENSSH|EC) PRIVATE KEY"),
    DRIVE_ID_WORD,
]
MAIL_MARK = "@g" + "mail"
MAIL_ALLOWED_FILES = ("LICENSE",)  # plus the author line of a pyproject.toml, see _mail_allowed
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")
EMAIL_ALLOWED_DOMAINS = {
    "example.com",
    "example.org",
    "example.net",
    "anthropic.com",
    "noreply.github.com",
    "users.noreply.github.com",
}
# Indian mobile number shapes: with the country code, and a bare ten-digit number starting 6 to 9 that stands
# alone as a token (no letter, digit or dot touching it, so a digit run inside a hex digest is not a number).
PHONE = [
    re.compile(r"\+91[ -]?[6-9]\d{4}[ -]?\d{5}"),
    re.compile(r"(?<![0-9A-Za-z.])[6-9]\d{9}(?![0-9A-Za-z.])"),
]
# Google Drive ids. Current ids: a run of id characters holding "1" plus 27 to 40 id characters, mixing upper
# case, lower case and a digit (and DRIVE_ID_WORD in GENERIC above). Legacy ids start "0B".
ID_RUN = re.compile(r"[A-Za-z0-9_-]{28,}")
DRIVE_ID_MIN, DRIVE_ID_MAX = 28, 41  # "1" plus 27 to 40 characters
LEGACY_DRIVE_ID = re.compile(r"\b0B[A-Za-z0-9_-]{20,}\b")
EM_DASH = chr(0x2014)
# Pictographs, dingbats and symbol blocks, plus variation selector and joiner. Plain arrows are not emoji.
EMOJI_RANGES = [(0x1F000, 0x1FAFF), (0x2600, 0x27BF), (0x2B00, 0x2BFF), (0x2300, 0x23FF), (0xFE0F, 0xFE0F), (0x200D, 0x200D)]
EMOJI = re.compile("[" + "".join(chr(lo) + "-" + chr(hi) for lo, hi in EMOJI_RANGES) + "]")

# Removed before the digest and word scans: soft hyphen and zero-width characters.
INVISIBLE = {0x00AD: None, 0x200B: None, 0x200C: None, 0x200D: None, 0x2060: None, 0xFEFF: None}
NBSP = chr(0x00A0)
WORD = re.compile(r"[a-z0-9]+")
WHITESPACE = re.compile(r"\s+")

BANNED_EXTENSIONS = {
    "jpg", "jpeg", "png", "gif", "bmp", "tif", "tiff", "webp", "heic", "heif", "cr2", "cr3", "nef", "arw", "dng",
    "mp4", "mov", "avi", "mkv", "m4v", "db", "sqlite", "sqlite3", "pkl", "pickle", "npy", "npz", "onnx", "pt",
    "pth", "zip", "tar", "gz", "tgz", "bz2", "xz", "7z", "rar", "pdf",
}
BINARY_HIT = "binary or non-UTF-8 file tracked (no binaries belong in this repo)"

# Skipped at every level in walk mode. A folder named data is skipped only at <root>/sorter/data. Folders ending
# ".egg-info" and the files in SKIP_FILES are generated or local (setup.sh, macOS Finder, local settings) and are
# gitignored, so git mode never lists them; walk mode skips them so a ZIP download that ran setup.sh still scans.
SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".claude", ".pytest_cache", ".ruff_cache"}
SKIP_DIR_SUFFIX = ".egg-info"
SKIP_FILES = {".DS_Store", ".env"}


def _is_git_root(root: str) -> bool:
    return os.path.isdir(os.path.join(root, ".git")) or os.path.isfile(os.path.join(root, ".git"))


def _list_files(root: str) -> list[str]:
    """Git mode: tracked files plus untracked files that are not ignored. Walk mode: every file outside SKIP_DIRS."""
    if _is_git_root(root):
        found: set[str] = set()
        for extra in ([], ["--others", "--exclude-standard"]):
            out = subprocess.run(["git", "ls-files", "-z", *extra], cwd=root, capture_output=True, check=True).stdout
            found.update(p for p in out.decode("utf-8").split("\0") if p)
        return sorted(found)
    data_dir = os.path.normpath(os.path.join(root, "sorter", "data"))
    found_walk = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames
            if d not in SKIP_DIRS
            and not d.endswith(SKIP_DIR_SUFFIX)
            and os.path.normpath(os.path.join(dirpath, d)) != data_dir
        ]
        for name in filenames:
            if name in SKIP_FILES:
                continue
            found_walk.append(os.path.relpath(os.path.join(dirpath, name), root))
    return sorted(found_walk)


def _mail_allowed(rel: str, line: str) -> bool:
    base = os.path.basename(rel)
    if base in MAIL_ALLOWED_FILES:
        return True
    return base == "pyproject.toml" and line.lstrip().startswith("authors")


def normalise(text: str) -> str:
    """The text the digest and word scans read: NFKC, invisibles removed, NBSP as space, URL-decoded, lowercased."""
    text = unicodedata.normalize("NFKC", text)
    text = text.translate(INVISIBLE)
    text = text.replace(NBSP, " ")
    text = urllib.parse.unquote(text)
    return text.lower()


def _digest_hits(lowered: str, digests_by_length: dict[int, set[str]]):
    """Yield (length, offset) for every window of the text whose SHA-256 is a listed digest."""
    for n, wanted in digests_by_length.items():
        for i in range(len(lowered) - n + 1):
            if hashlib.sha256(lowered[i:i + n].encode("utf-8")).hexdigest() in wanted:
                yield n, i


def _has_drive_id(line: str) -> bool:
    """True when a run of id characters holds "1" plus 27 to 40 id characters mixing upper, lower and a digit."""
    for m in ID_RUN.finditer(line):
        run = m.group(0)
        for i, ch in enumerate(run):
            if ch != "1":
                continue
            # The longest candidate from this "1" contains every shorter one, so it alone decides.
            cand = run[i:i + DRIVE_ID_MAX]
            if len(cand) < DRIVE_ID_MIN:
                break
            rest = cand[1:]
            if any(c.isupper() for c in rest) and any(c.islower() for c in rest) and any(c.isdigit() for c in rest):
                return True
    return False


def scan_bytes(
    rel: str,
    raw: bytes,
    *,
    digests_by_length: dict[int, set[str]] = DIGESTS_BY_LENGTH,
    word_digests: set[str] = WORD_DIGESTS,
) -> list[str]:
    """Return the hit strings for one file's content. An empty list means the file is clean."""
    hits: list[str] = []
    ext = rel.rsplit(".", 1)[-1].lower() if "." in os.path.basename(rel) else ""
    if ext in BANNED_EXTENSIONS:
        hits.append(f"{rel}: banned file type .{ext} tracked (no binaries belong in this repo)")
    if b"\0" in raw:
        hits.append(f"{rel}: {BINARY_HIT}")
        return hits
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        hits.append(f"{rel}: {BINARY_HIT}")
        return hits

    norm = normalise(text)
    # The raw pass and the two whitespace passes report only tokens the normalised pass did not already report, so
    # one token is one hit; the file fails whenever any pass finds anything.
    found: set[str] = set()
    for n, i in _digest_hits(norm, digests_by_length):
        found.add(norm[i:i + n])
        line_no = norm.count("\n", 0, i) + 1
        hits.append(f"{rel}:{line_no}: contains a listed private token (length {n})")
    # The raw text, lowercased only: normalising can eat a token (URL-decoding a percent sign followed by two hex
    # letters, NFKC merging a last letter with a following combining accent), so the raw text is scanned too.
    raw_lowered = text.lower()
    for n, i in _digest_hits(raw_lowered, digests_by_length):
        token = raw_lowered[i:i + n]
        if token in found:
            continue
        found.add(token)
        line_no = raw_lowered.count("\n", 0, i) + 1
        hits.append(f"{rel}:{line_no}: contains a listed private token (length {n}) (found in the raw text)")
    for variant, how in ((WHITESPACE.sub("", norm), "removal"), (WHITESPACE.sub(" ", norm), "collapse")):
        for n, i in _digest_hits(variant, digests_by_length):
            token = variant[i:i + n]
            if token in found:
                continue
            found.add(token)
            hits.append(f"{rel}: contains a listed private token (length {n}) (line unknown, found after whitespace {how})")
    for m in WORD.finditer(norm):
        if hashlib.sha256(m.group(0).encode("utf-8")).hexdigest() in word_digests:
            line_no = norm.count("\n", 0, m.start()) + 1
            hits.append(f"{rel}:{line_no}: contains a listed private word")

    is_license = os.path.basename(rel) in MAIL_ALLOWED_FILES
    for n, line in enumerate(text.splitlines(), start=1):
        for pat in GENERIC:
            if pat.search(line):
                hits.append(f"{rel}:{n}: matches {pat.pattern!r}")
        if _has_drive_id(line):
            hits.append(f"{rel}:{n}: contains a Drive-id-shaped string")
        if LEGACY_DRIVE_ID.search(line):
            hits.append(f"{rel}:{n}: contains a legacy Drive-id-shaped string")
        if MAIL_MARK in line and not _mail_allowed(rel, line):
            hits.append(f"{rel}:{n}: contains {MAIL_MARK!r}")
        if not is_license and not _mail_allowed(rel, line):
            for m in EMAIL.finditer(line):
                if m.group(1).lower() not in EMAIL_ALLOWED_DOMAINS:
                    hits.append(f"{rel}:{n}: contains an email address")
                    break
        for pat in PHONE:
            if pat.search(line):
                hits.append(f"{rel}:{n}: contains an Indian mobile number shape")
                break
        if EM_DASH in line:
            hits.append(f"{rel}:{n}: contains an em dash")
        if EMOJI.search(line):
            hits.append(f"{rel}:{n}: contains an emoji")
    return hits


def scan_tree(
    root: str,
    *,
    digests_by_length: dict[int, set[str]] = DIGESTS_BY_LENGTH,
    word_digests: set[str] = WORD_DIGESTS,
) -> tuple[int, list[str]]:
    """List the files under root (git or walk mode) and scan each. Returns (files scanned, hits)."""
    files = _list_files(root)
    assert files, f"no files found to scan under {root}"
    hits: list[str] = []
    scanned = 0
    for rel in files:
        path = os.path.join(root, rel)
        if not os.path.isfile(path):
            hits.append(f"{rel}: tracked but missing on disk")
            continue
        with open(path, "rb") as fh:
            raw = fh.read()
        scanned += 1
        hits.extend(scan_bytes(rel, raw, digests_by_length=digests_by_length, word_digests=word_digests))
    return scanned, hits


def test_no_private_strings_in_tracked_files():
    scanned, hits = scan_tree(ROOT)
    assert scanned > 0, "no file was scanned"
    assert not hits, "private or banned content in tracked files:\n" + "\n".join(hits)


# Unit tests for the rules. Every probe is fake material built at runtime, so this source holds nothing the
# tree scan above would flag.

def _sha(word: str) -> str:
    return hashlib.sha256(word.encode("utf-8")).hexdigest()


FAKE_WORD = "zqx" + "fakeword"
FAKE_PAIR = "zqx" + " " + "fakeinst"
FAKE_DIGESTS = {len(FAKE_WORD): {_sha(FAKE_WORD)}, len(FAKE_PAIR): {_sha(FAKE_PAIR)}}
CLEAN = "A clean paragraph about sorting event photos into folders.\nIt names no one and holds no secrets.\n"


def _fake_scan(text, rel="docs/probe.md", *, word_digests=frozenset()):
    raw = text.encode("utf-8") if isinstance(text, str) else text
    return scan_bytes(rel, raw, digests_by_length=FAKE_DIGESTS, word_digests=set(word_digests))


def _word_scan(text, word):
    return scan_bytes("docs/probe.md", text.encode("utf-8"), digests_by_length={}, word_digests={_sha(word)})


def test_negative_control_clean_paragraph_has_no_hits():
    assert _fake_scan(CLEAN, word_digests={_sha(FAKE_WORD), _sha("qzx")}) == []


def test_plain_fake_token_fires():
    assert _fake_scan("before " + FAKE_PAIR + " after")
    assert _fake_scan("x" + FAKE_WORD + "y")


def test_uppercase_token_fires():
    assert _fake_scan("before " + FAKE_PAIR.upper() + " after")


def test_url_encoded_token_fires():
    assert _fake_scan("https://example.com/?q=" + "zqx" + "%20" + "fakeinst")


def test_token_split_across_newline_fires():
    hits = _fake_scan("before zqx\nfakeinst after")
    assert hits
    assert any("line unknown" in h for h in hits)


def test_single_word_split_by_line_wrap_fires():
    hits = _fake_scan("before zqxfake\nword after")
    assert any("found after whitespace removal" in h for h in hits)


def test_nbsp_between_words_fires():
    assert _fake_scan("before zqx" + chr(0x00A0) + "fakeinst after")


def test_soft_hyphen_inside_word_fires():
    assert _fake_scan("before zqx fake" + chr(0x00AD) + "inst after")


def test_zero_width_space_inside_word_fires():
    assert _fake_scan("before zqx fa" + chr(0x200B) + "keinst after")
    assert _fake_scan("before zqxfake" + chr(0x2060) + "word after")


def test_percent_sign_before_token_fires():
    assert _fake_scan("50%ab" + FAKE_WORD)
    # A token starting with two hex letters, written after a percent sign: URL-decoding eats those two letters,
    # so only the raw-text pass finds it.
    hex_start = "ab" + "zqxfake"
    table = {len(hex_start): {_sha(hex_start)}}
    hits = scan_bytes("docs/probe.md", ("discount 50%" + hex_start).encode("utf-8"), digests_by_length=table,
                      word_digests=set())
    assert any("found in the raw text" in h for h in hits), hits


def test_combining_accent_after_token_fires():
    assert _fake_scan(FAKE_WORD + chr(0x0301))
    # A token ending in "e" followed by a combining acute: NFKC merges them into one letter, so only the raw-text
    # pass finds it.
    e_end = "zqxfak" + "e"
    table = {len(e_end): {_sha(e_end)}}
    hits = scan_bytes("docs/probe.md", ("before " + e_end + chr(0x0301) + " after").encode("utf-8"),
                      digests_by_length=table, word_digests=set())
    assert any("found in the raw text" in h for h in hits), hits


def test_full_width_letters_fire():
    full_width = chr(0xFF5A) + chr(0xFF51)  # full-width z and q
    assert _fake_scan("before " + full_width + "x fakeinst after")


def test_word_digest_fires_on_whole_word_only():
    assert any("listed private word" in h for h in _word_scan("see " + FAKE_WORD + ".", FAKE_WORD))
    assert _word_scan("see " + FAKE_WORD + "ish.", FAKE_WORD) == []
    three = "q" + "zx"
    assert any("listed private word" in h for h in _word_scan("the " + three + " headshots", three))
    assert any("listed private word" in h for h in _word_scan("(" + three.upper() + ")", three))
    assert _word_scan("the " + three + "y headshots", three) == []
    assert _word_scan("the a" + three + " headshots", three) == []


def test_nul_byte_is_a_hit():
    hits = _fake_scan(b"plain text\x00more text")
    assert any(BINARY_HIT in h for h in hits)


def test_utf16_text_is_a_hit():
    hits = _fake_scan("plain text".encode("utf-16"))
    assert any(BINARY_HIT in h for h in hits)


def test_latin1_accented_text_is_a_hit():
    hits = _fake_scan(("caf" + chr(0xE9)).encode("latin-1"))
    assert any(BINARY_HIT in h for h in hits)


def test_banned_extension_is_a_hit_even_when_empty():
    assert any("banned file type .jpg" in h for h in _fake_scan(b"", rel="docs/sample.jpg"))
    assert any("banned file type .cr3" in h for h in _fake_scan(b"", rel="docs/IMG_0001.CR3"))
    assert _fake_scan(b"", rel="docs/notes.md") == []


def _fake_drive_id() -> str:
    return "1" + "Zz" * 14 + "9"


def test_drive_id_shapes_fire():
    assert any("Drive-id" in h for h in _fake_scan("x = drive_" + _fake_drive_id()))
    assert any("Drive-id" in h for h in _fake_scan(_fake_drive_id() + "_DSC0123" + "4.CR3"))
    assert any("legacy Drive-id" in h for h in _fake_scan("id " + "0" + "B" + "aZ9" * 8))


def test_lowercase_hex_digest_is_not_a_drive_id():
    hex_digest = _sha("anything")
    assert not any("Drive-id" in h for h in _fake_scan("digest " + hex_digest))
    assert not any("Drive-id" in h for h in _fake_scan("1" + hex_digest))
    assert _fake_scan("digest " + hex_digest) == []
    assert _fake_scan("1" + hex_digest) == []


def test_letters_only_drive_id_word_fires():
    # "1" then letters only: the run rule needs a digit after the "1", so only DRIVE_ID_WORD catches it.
    fake_id = "1" + "AbCdEfGhIjKlMnOpQrStUvWxYz" + "AbCdEf"
    assert len(fake_id) == 33
    assert not _has_drive_id("id " + fake_id)
    hits = _fake_scan("id " + fake_id)
    assert any(repr(DRIVE_ID_WORD.pattern) in h for h in hits), hits


def test_email_rules():
    fake_address = "user" + "@" + "fake-host" + ".com"
    assert any("email address" in h for h in _fake_scan("write to " + fake_address))
    assert _fake_scan("write to someone" + "@" + "example.com") == []
    assert _fake_scan("x " + fake_address, rel="LICENSE") == []
    assert _fake_scan('authors = [{ email = "' + fake_address + '" }]', rel="pkg/pyproject.toml") == []
    assert any("email address" in h for h in _fake_scan('email = "' + fake_address + '"', rel="pkg/pyproject.toml"))


def test_generic_shapes_fire():
    # One fake per GENERIC pattern, built at runtime; every pattern must fire on its own probe.
    probes = [
        "/Us" + "ers/someone/x",
        "host 100." + "64.0.1",
        "host 192." + "168.0.1",
        "box" + ".ts" + ".net",
        "box" + ".loc" + "al",
        "key " + "AIza" + "0" * 35,
        "token " + "ya" + "29." + "abc",
        "key " + "sk-" + "a" * 20,
        "key " + "ghp_" + "a" * 30,
        "key " + "AKIA" + "A" * 16,
        "-----" + "BEGIN " + "RSA" + " PRIVATE KEY" + "-----",
        "id " + "1" + "AbCdEfGhIjKlMnOpQrStUvWxYz" + "AbCdEf",
    ]
    fired = set()
    for probe in probes:
        hits = _fake_scan(probe)
        assert hits, probe
        fired.update(pat.pattern for pat in GENERIC for h in hits if f"matches {pat.pattern!r}" in h)
    assert fired == {pat.pattern for pat in GENERIC}
    assert any("AIza" in h for h in _fake_scan("AIza" + "0" * 35))


def test_personal_mail_mark_fires():
    mark = "@g" + "mail"
    assert any(f"contains {mark!r}" in h for h in _fake_scan("see " + mark))
    assert _fake_scan("see " + mark, rel="LICENSE") == []


def test_em_dash_fires():
    assert any("em dash" in h for h in _fake_scan("one " + chr(0x2014) + " two"))


def test_emoji_fires():
    assert any("emoji" in h for h in _fake_scan("done " + chr(0x1F642)))
    assert _fake_scan("a " + chr(0x2192) + " b") == []


def test_indian_mobile_shapes_fire():
    spaced = "+9" + "1 98765 4" + "3210"
    assert any("mobile" in h for h in _fake_scan("call " + spaced))
    assert any("mobile" in h for h in _fake_scan("call " + "98765" + "43210" + " today"))


def test_epoch_is_not_a_mobile_number():
    assert _fake_scan("ts = 1782225000") == []


def test_digit_run_inside_hex_digest_is_not_a_mobile_number():
    assert not any("mobile" in h for h in _fake_scan("digest " + "d" + "81983" + "76303" + "b"))
    assert not any("mobile" in h for h in _fake_scan("digest " + "a" + "72060" + "55830" + "c" + _sha("x")))


def test_standalone_ten_digit_mobile_fires():
    digits = "81983" + "76303"
    for text in (digits, "call " + digits, "call:" + digits, "ph:" + digits):
        assert any("mobile" in h for h in _fake_scan(text)), text


def test_walk_mode_skips_only_root_sorter_data(tmp_path):
    root = tmp_path / "tree"
    (root / "sorter" / "data").mkdir(parents=True)
    (root / "sorter" / "data" / "photo.jpg").write_bytes(b"")
    (root / "other" / "data").mkdir(parents=True)
    (root / "other" / "data" / "probe.md").write_text("before " + FAKE_PAIR + " after", encoding="utf-8")
    (root / "pkg" / ".venv").mkdir(parents=True)
    (root / "pkg" / ".venv" / "lib.bin").write_bytes(b"\x00")
    scanned, hits = scan_tree(str(root), digests_by_length=FAKE_DIGESTS, word_digests=set())
    assert scanned == 1
    assert hits and all(h.startswith(os.path.join("other", "data", "probe.md")) for h in hits)


def test_walk_mode_skips_generated_egg_info_and_local_files(tmp_path):
    root = tmp_path / "zip"
    (root / "pkg" / "src" / "x.egg-info").mkdir(parents=True)
    author = "Author-email: Someone <" + "user" + "@" + "fake-host" + ".com>\n"
    (root / "pkg" / "src" / "x.egg-info" / "PKG-INFO").write_text("Name: x\n" + author, encoding="utf-8")
    (root / ".DS_Store").write_bytes(b"Bud1\x00\x00")
    (root / "pkg" / ".env").write_text("TOKEN=" + FAKE_PAIR + "\n", encoding="utf-8")
    (root / "docs").mkdir()
    (root / "docs" / "notes.md").write_text(CLEAN, encoding="utf-8")
    scanned, hits = scan_tree(str(root), digests_by_length=FAKE_DIGESTS, word_digests=set())
    assert (scanned, hits) == (1, [])
    (root / "docs" / "leak.txt").write_text("before " + FAKE_PAIR + " after\n", encoding="utf-8")
    scanned, hits = scan_tree(str(root), digests_by_length=FAKE_DIGESTS, word_digests=set())
    assert scanned == 2
    assert len(hits) == 1 and hits[0].startswith(os.path.join("docs", "leak.txt") + ":")


def test_git_mode_scans_untracked_and_flags_missing(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    (root / "kept.md").write_text(CLEAN, encoding="utf-8")
    (root / "gone.md").write_text(CLEAN, encoding="utf-8")
    subprocess.run(["git", "add", "kept.md", "gone.md"], cwd=root, check=True)
    (root / "gone.md").unlink()
    (root / "new.md").write_text("before " + FAKE_PAIR + " after", encoding="utf-8")
    scanned, hits = scan_tree(str(root), digests_by_length=FAKE_DIGESTS, word_digests=set())
    assert scanned == 2
    assert "gone.md: tracked but missing on disk" in hits
    assert any(h.startswith("new.md:") for h in hits)
    assert not any(h.startswith("kept.md") for h in hits)

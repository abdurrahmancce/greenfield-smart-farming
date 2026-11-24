"""Fails if something that looks like a real secret is committed (keys, tokens, private keys, OAuth json)."""
import os
import re
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", "venv", ".venv", "node_modules", "htmlcov", "vendor"}
PATTERNS = {
    "Brevo key": re.compile(r"xkeysib-[A-Za-z0-9]{20,}"),
    "Google API key": re.compile(r"AIza[0-9A-Za-z_\-]{30,}"),
    "Google OAuth secret": re.compile(r"GOCSPX-[0-9A-Za-z_\-]{20,}"),
    "private key block": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |)PRIVATE KEY-----"),
    "GitHub token": re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"),
    "AWS key id": re.compile(r"AKIA[0-9A-Z]{16}"),
}
TEXT_EXT = (".py", ".md", ".txt", ".yml", ".yaml", ".json", ".html", ".js", ".ino", ".env", ".cfg", ".ini", ".toml")


def _files():
    """Files that git tracks (so a private, git-ignored .env on your own computer does not fail the test);
    falls back to walking the folder when git is not available."""
    try:
        out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, timeout=20, check=True).stdout
        tracked = [os.path.join(ROOT, f) for f in out.splitlines() if f]
        if tracked:
            yield from (f for f in tracked if os.path.isfile(f))
            return
    except (OSError, subprocess.SubprocessError):
        pass
    for d, dirs, files in os.walk(ROOT):
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS]
        for f in files:
            yield os.path.join(d, f)


def test_no_secret_looking_strings_in_the_project():
    hits = []
    for path in _files():
        if not path.endswith(TEXT_EXT) or os.path.abspath(path) == os.path.abspath(__file__):
            continue
        try:
            text = open(path, encoding="utf-8", errors="ignore").read()
        except OSError:
            continue
        for label, rx in PATTERNS.items():
            if rx.search(text):
                hits.append((os.path.relpath(path, ROOT), label))
    assert not hits, f"possible secrets committed: {hits}"


def test_no_oauth_client_file_or_env_file_in_the_project():
    names = [os.path.basename(p) for p in _files()]
    assert not [n for n in names if n.startswith("client_secret") and n.endswith(".json")]
    assert ".env" not in names

"""Strict Content-Security-Policy: no third-party scripts, no inline handlers, nonce on inline scripts."""
import re
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parent.parent / "templates"


def test_csp_header_is_strict_for_scripts(client):
    r = client.get("/login")
    csp = r.headers["Content-Security-Policy"]
    script = [d for d in csp.split(";") if d.strip().startswith("script-src")][0]
    assert "'self'" in script and "'nonce-" in script
    assert "unsafe-inline" not in script and "unsafe-eval" not in script
    assert "http" not in script            # no CDN allowed for scripts
    for d in ("object-src 'none'", "frame-ancestors 'self'", "base-uri 'self'", "form-action 'self'"):
        assert d in csp


def test_every_inline_script_carries_the_request_nonce(client):
    for url in ("/", "/login", "/register"):
        r = client.get(url)
        nonce = re.search(r"'nonce-([^']+)'", r.headers["Content-Security-Policy"]).group(1)
        html = r.get_data(as_text=True)
        for tag in re.findall(r"<script\b[^>]*>", html):
            if "src=" in tag:
                continue
            assert f'nonce="{nonce}"' in tag, tag


def test_nonce_changes_every_request(client):
    a = client.get("/login").headers["Content-Security-Policy"]
    b = client.get("/login").headers["Content-Security-Policy"]
    assert a != b


def test_templates_have_no_inline_handlers_or_cdn_scripts():
    for p in TEMPLATES.glob("*.html"):
        s = p.read_text(encoding="utf-8")
        assert not re.search(r"""\son(click|input|change|submit|mouse\w+|load|error|focus|blur|key\w+)\s*=""", s, re.I), p.name
        assert "javascript:" not in s, p.name
        for src in re.findall(r"""<script[^>]+src=["']([^"']+)""", s):
            assert not src.startswith("http"), (p.name, src)
        assert "cdnjs.cloudflare.com" not in s and "unpkg.com" not in s, p.name
        for tag in re.findall(r"<script\b[^>]*>", s):
            if "src=" not in tag:
                assert "csp_nonce" in tag, (p.name, tag)


def test_vendor_files_are_served_locally(client):
    for path in ("/static/vendor/chartjs/chart.umd.js", "/static/vendor/leaflet/leaflet.js",
                 "/static/vendor/leaflet/leaflet.css", "/static/vendor/fontawesome/css/all.min.css",
                 "/static/vendor/fontawesome/webfonts/fa-solid-900.woff2", "/static/js/ui.js"):
        assert client.get(path).status_code == 200, path

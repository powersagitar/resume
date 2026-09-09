#!/usr/bin/env python3
"""Check that every link in a PDF is reachable.

Replaces pdfx, which sends an HTTP request to mailto: URIs and always
reports them as broken. This extracts links with PyMuPDF, validates
mailto: links by email format instead of over HTTP, and checks http(s)
links with curl (some sites, e.g. LinkedIn, block python-requests's
TLS/HTTP fingerprint but allow curl's).
"""

from __future__ import annotations

import re
import subprocess
import sys

import fitz

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
HTTP_TIMEOUT_SECONDS = "10"
# A browser UA + curl's own TLS/HTTP fingerprint gets past bot detection
# (e.g. LinkedIn) that blocks python-requests's fingerprint outright.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def extract_uris(pdf_path: str) -> list[str]:
    doc = fitz.open(pdf_path)
    uris = []
    for page in doc:
        for link in page.get_links():
            uri = link.get("uri")
            if uri:
                uris.append(uri)
    return sorted(set(uris))


def check_mailto(uri: str) -> str | None:
    address = uri[len("mailto:") :].split("?", 1)[0]
    if not EMAIL_RE.match(address):
        return f"malformed email address: {address}"
    return None


def check_http(uri: str) -> tuple[str | None, bool]:
    """Returns (error, is_skipped)."""
    result = subprocess.run(
        [
            "curl",
            "--silent",
            "--output",
            "/dev/null",
            "--write-out",
            "%{http_code}",
            "--location",
            "--max-time",
            HTTP_TIMEOUT_SECONDS,
            "--user-agent",
            USER_AGENT,
            uri,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return f"curl error: {result.stderr.strip() or result.returncode}", False

    status_code = int(result.stdout.strip())
    if status_code == 999:
        # LinkedIn's anti-scraping status code, returned intermittently to
        # non-browser clients regardless of headers used. Not evidence the
        # link is actually broken, so don't fail the build on it.
        return "HTTP 999 (likely anti-bot block, not a real broken link)", True
    if status_code >= 400:
        return f"HTTP {status_code}", False
    return None, False


def main() -> int:
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} <pdf-path>", file=sys.stderr)
        return 2

    uris = extract_uris(sys.argv[1])
    broken = []

    for uri in uris:
        skipped = False
        if uri.startswith("mailto:"):
            error = check_mailto(uri)
        elif uri.startswith("http://") or uri.startswith("https://"):
            error, skipped = check_http(uri)
        else:
            error = None  # unrecognized scheme, nothing to validate

        if error and skipped:
            print(f"SKIP    {uri} -> {error}")
        elif error:
            broken.append((uri, error))
            print(f"BROKEN  {uri} -> {error}")
        else:
            print(f"OK      {uri}")

    if broken:
        print(f"\n{len(broken)} broken link(s) found.", file=sys.stderr)
        return 1

    print(f"\nAll {len(uris)} link(s) OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

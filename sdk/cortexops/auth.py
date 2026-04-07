"""
cortexops login / logout / whoami — credential management.
Stores API key in ~/.cortexops/credentials (JSON).
Called by CLI and importable for programmatic use.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_CREDENTIALS_DIR  = Path.home() / ".cortexops"
_CREDENTIALS_FILE = _CREDENTIALS_DIR / "credentials"
_DEFAULT_API_URL  = "https://api.getcortexops.com"


def save_credentials(api_key: str, project: str, api_url: str = _DEFAULT_API_URL) -> None:
    """Persist credentials to ~/.cortexops/credentials."""
    _CREDENTIALS_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    creds = {"api_key": api_key, "project": project, "api_url": api_url}
    _CREDENTIALS_FILE.write_text(json.dumps(creds, indent=2))
    _CREDENTIALS_FILE.chmod(0o600)  # owner read/write only — no secrets leak


def load_credentials() -> dict | None:
    """Load credentials from ~/.cortexops/credentials. Returns None if not found."""
    if not _CREDENTIALS_FILE.exists():
        return None
    try:
        return json.loads(_CREDENTIALS_FILE.read_text())
    except Exception:
        return None


def clear_credentials() -> None:
    """Remove stored credentials."""
    if _CREDENTIALS_FILE.exists():
        _CREDENTIALS_FILE.unlink()


def verify_key(api_key: str, api_url: str = _DEFAULT_API_URL) -> dict | None:
    """
    Call GET /health with the key to verify it is valid.
    Returns {"project": ..., "environment": ...} on success, None on failure.
    """
    try:
        import httpx
        r = httpx.get(
            f"{api_url.rstrip('/')}/health",
            headers={"X-API-Key": api_key},
            timeout=8.0,
        )
        if r.status_code == 200:
            return r.json()
        return None
    except Exception:
        return None


def cmd_login(api_key: str | None = None, project: str | None = None,
              api_url: str = _DEFAULT_API_URL) -> int:
    """
    Interactive login flow. Called by `cortexops login`.

    If api_key is not provided, prompts interactively.
    Returns 0 on success, 1 on failure.
    """
    print("CortexOps Login")
    print("Get your API key at https://getcortexops.com/#pricing\n")

    if not api_key:
        try:
            import getpass
            api_key = getpass.getpass("API key (cxo-...): ").strip()
        except KeyboardInterrupt:
            print("\nCancelled.")
            return 1

    if not api_key.startswith("cxo-"):
        print("Error: API key must start with 'cxo-'", file=sys.stderr)
        return 1

    if not project:
        project = input("Default project name: ").strip() or "my-agent"

    print(f"\nVerifying key against {api_url}...")
    info = verify_key(api_key, api_url)
    if info is None:
        print(
            "Warning: Could not verify key (API may be unreachable).\n"
            "Saving credentials anyway — verify manually with: cortexops whoami",
            file=sys.stderr,
        )

    save_credentials(api_key, project, api_url)
    masked = api_key[:8] + "..." + api_key[-4:]
    print("\n✓ Logged in")
    print(f"  Key:     {masked}")
    print(f"  Project: {project}")
    print("  Stored:  ~/.cortexops/credentials")
    print("\nYou can now use CortexTracer without passing api_key:")
    print(f"  tracer = CortexTracer(project=\"{project}\")")
    return 0


def cmd_logout() -> int:
    """Called by `cortexops logout`."""
    creds = load_credentials()
    if not creds:
        print("Not logged in.")
        return 0
    clear_credentials()
    print("✓ Logged out — credentials removed from ~/.cortexops/credentials")
    return 0


def cmd_whoami(api_url: str | None = None) -> int:
    """Called by `cortexops whoami`."""
    # Check env var first
    env_key = os.getenv("CORTEXOPS_API_KEY")
    file_creds = load_credentials()

    if not env_key and not file_creds:
        print("Not logged in.\nRun: cortexops login", file=sys.stderr)
        return 1

    if env_key:
        print("API key source : CORTEXOPS_API_KEY (env)")
        masked = env_key[:8] + "..." + env_key[-4:]
        print(f"Key            : {masked}")
        url = api_url or os.getenv("CORTEXOPS_API_URL", _DEFAULT_API_URL)
    else:
        masked = file_creds["api_key"][:8] + "..." + file_creds["api_key"][-4:]
        print("API key source : ~/.cortexops/credentials")
        print(f"Key            : {masked}")
        print(f"Project        : {file_creds.get('project', '—')}")
        url = api_url or file_creds.get("api_url", _DEFAULT_API_URL)
        env_key = file_creds["api_key"]

    print(f"API URL        : {url}")
    print("\nVerifying...")
    info = verify_key(env_key, url)
    if info:
        print(f"✓ Key is valid  (API status: {info.get('status', 'ok')})")
    else:
        print("✗ Key verification failed — API unreachable or key invalid")
        return 1
    return 0
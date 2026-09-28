#!/usr/bin/env python3
"""Install the small Timesheet Clerk connection in its own external Hermes profile."""
from __future__ import annotations

import argparse
from getpass import getpass
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen, HTTPRedirectHandler, build_opener

REPOSITORY = "bramvrensen/Hermes-Timesheet-Clerk"


class NoCredentialRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch(url: str) -> bytes:
    with urlopen(Request(url, headers={"User-Agent": "Timesheet-Clerk-installer"}), timeout=30) as response:
        return response.read()


def connect(home: Path, hermes: str, *, url: str, token: str, ref: str, profile: str = "timesheet-clerk", yes: bool = False) -> Path:
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", profile):
        raise ValueError("Invalid Timesheet Clerk profile name")
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Gebruik het directe Timesheet Clerk API-adres.")
    if len(token) < 24 or any(c in token + url for c in "\x00\r\n'\\"):
        raise ValueError("Ongeldig Timesheet Clerk verbindingstoken of API-adres.")
    env = {**os.environ, "HERMES_HOME": str(home)}
    own = home / "profiles" / profile
    marker = own / ".timesheet-clerk-connection"
    created = not own.exists()
    if not created and not marker.exists():
        raise ValueError("Dit Hermes-profiel bestaat al en is niet door Timesheet Clerk aangemaakt. Kies --profile met een vrije naam.")
    with build_opener(NoCredentialRedirect).open(Request(url.rstrip("/") + "/v1/status", headers={"Authorization": f"Bearer {token}"}), timeout=15) as response:
        status = json.load(response)
    if not status.get("success") or not str(status.get("data", {}).get("version", "")).startswith("2."):
        raise ValueError("Geen werkende Timesheet Clerk V2 service gevonden.")
    revision = json.loads(fetch(f"https://api.github.com/repos/{REPOSITORY}/commits/{quote(ref, safe='')}"))["sha"]
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("Invalid GitHub revision")
    files = {name: fetch(f"https://raw.githubusercontent.com/{REPOSITORY}/{revision}/hermes_plugins/connection/{name}")
             for name in ("__init__.py", "plugin.yaml", "SKILL.md")}
    def run(*args: str):
        subprocess.run([hermes, *args], env=env, check=True)
    if created:
        run("profile", "create", profile, "--no-skills")
        marker.write_text("Managed Timesheet Clerk connection profile\n", encoding="utf-8")
    plugin = own / "plugins" / "timesheet-clerk-connection"
    plugin.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        (plugin / name).write_bytes(data)
    skill = own / "skills" / "timesheet-clerk"
    skill.mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_bytes(files["SKILL.md"])
    (own / "SOUL.md").write_text(
        "You are Timesheet Clerk, the connection to the independent Timesheet Clerk application. "
        "Use timesheet_clerk_status, timesheet_clerk_generate and timesheet_clerk_job. "
        "Use the user's requested calendar week, await job success and direct them to the review URL "
        "to review and book hours. Never claim a background job has finished before SUCCEEDED.\n",
        encoding="utf-8")
    secret_file = own / ".env"
    current = secret_file.read_text(encoding="utf-8") if secret_file.exists() else ""
    current = "\n".join(line for line in current.splitlines() if not re.match(r"(?:export\s+)?TIMESHEET_CLERK_API_(URL|TOKEN)\s*=", line))
    secret_file.write_text(current.rstrip() + f"\nTIMESHEET_CLERK_API_URL='{url.rstrip('/')}'\nTIMESHEET_CLERK_API_TOKEN='{token}'\n", encoding="utf-8")
    secret_file.chmod(0o600)
    run("-p", profile, "plugins", "enable", "timesheet-clerk-connection", "--no-allow-tool-override")
    run("-p", profile, "config", "set", "platform_toolsets.cli", '["timesheet_clerk"]')
    run("-p", profile, "config", "set", "tools.tool_search.enabled", "off")
    if created and not yes:
        print("Kies nu het model voor dit Hermes-profiel. De Timesheet Clerk service heeft zijn eigen modelinstellingen.")
        run("-p", profile, "model")
    print(f"\nTimesheet Clerk is verbonden. Open dit profiel met: hermes -p {profile}\n")
    return own


def main() -> None:
    parser = argparse.ArgumentParser(description="Connect a new Hermes installation to Timesheet Clerk")
    parser.add_argument("--url", default=os.getenv("TIMESHEET_CLERK_API_URL", ""))
    parser.add_argument("--ref", default="feature/v2")
    parser.add_argument("--profile", default="timesheet-clerk")
    parser.add_argument("--hermes-home", type=Path, default=Path(os.getenv("HERMES_HOME", str(Path.home() / ".hermes"))))
    parser.add_argument("--yes", action="store_true", help="Skip the Hermes model chooser; configure that profile separately")
    args = parser.parse_args()
    hermes = shutil.which("hermes")
    if not hermes:
        parser.error("Installeer eerst Hermes. Timesheet Clerk zelf blijft zelfstandig werken.")
    if args.yes and (not args.url or not os.getenv("TIMESHEET_CLERK_API_TOKEN")):
        parser.error("--yes requires --url and TIMESHEET_CLERK_API_TOKEN")
    url = args.url or input("Timesheet Clerk API-adres: ").strip()
    token = os.getenv("TIMESHEET_CLERK_API_TOKEN") or getpass("Timesheet Clerk verbindingstoken: ").strip()
    try:
        connect(args.hermes_home.expanduser().resolve(), hermes, url=url, token=token, ref=args.ref, profile=args.profile, yes=args.yes)
    except Exception as exc:
        print(f"Timesheet Clerk verbinden gestopt ({type(exc).__name__}). Controleer het API-adres, token en Hermes-installatie.", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()

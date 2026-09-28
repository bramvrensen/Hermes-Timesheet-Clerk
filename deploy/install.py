"""Dependency-free installation wizard. Application data never lives in a release directory."""
from __future__ import annotations

import argparse
from getpass import getpass
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
from urllib.parse import urlsplit


def env_text(values: dict[str, str]) -> str:
    lines = ["# Private Timesheet Clerk installation settings. Keep this file outside Git."]
    for key, value in values.items():
        if any(c in value for c in "\x00\r\n"):
            raise ValueError(f"{key} must be a single line")
        lines.append(f"{key}='" + value.replace("'", "\\'") + "'")
    return "\n".join(lines) + "\n"


def question(label: str, default: str = "", *, secret: bool = False, required: bool = False) -> str:
    while True:
        prompt = f"{label}" + (f" [{default}]" if default and not secret else "") + ": "
        value = (getpass(prompt) if secret else input(prompt)).strip() or default
        if value or not required:
            return value
        print("Dit veld is nodig voor Timesheet Clerk.")


def wizard() -> dict[str, str]:
    print("\nTimesheet Clerk maakt zijn eigen Hermes-profiel aan.\nVul eenmalig de verbindingen in; geheime sleutels verschijnen niet op het scherm.\n")
    values = {
        "CLOCKIFY_API_KEY": question("Clockify API-sleutel", secret=True, required=True),
        "CLOCKIFY_WORKSPACE_ID": question("Clockify workspace-ID", required=True),
        "CLOCKIFY_USER_ID": question("Clockify gebruiker-ID", required=True),
        "SIMPLICATE_BASE_URL": question("Simplicate API-adres (https://account.simplicate.nl/api/v2)", required=True),
        "SIMPLICATE_API_KEY": question("Simplicate API-sleutel", secret=True, required=True),
        "SIMPLICATE_API_SECRET": question("Simplicate API-secret", secret=True, required=True),
        "SIMPLICATE_EMPLOYEE_ID": question("Simplicate medewerker-ID", required=True),
        "TIMESHEET_CLERK_UI_PASSWORD": question("Wachtwoord voor de Timesheet Clerk webpagina", secret=True, required=True),
        "TIMESHEET_CLERK_API_TOKEN": secrets.token_urlsafe(36),
        "TZ": "Europe/Amsterdam",
    }
    if urlsplit(values["SIMPLICATE_BASE_URL"]).scheme != "https":
        raise ValueError("Gebruik het HTTPS API-adres van Simplicate.")
    if len(values["TIMESHEET_CLERK_UI_PASSWORD"]) < 8:
        raise ValueError("Gebruik een webwachtwoord van minimaal 8 tekens.")
    model = question("Modelnaam voor automatische voorstellen (leeg = handmatig beoordelen)")
    values["TIMESHEET_CLERK_MODEL"] = model
    values["TIMESHEET_CLERK_MODEL_BASE_URL"] = question("Model API-adres", "https://openrouter.ai/api/v1") if model else "https://openrouter.ai/api/v1"
    values["TIMESHEET_CLERK_MODEL_API_KEY"] = question("Model API-sleutel", secret=True, required=True) if model else ""
    values["TIMESHEET_CLERK_SIMPLICATE_WRITE_ENABLED"] = "true" if question("Boeken vanuit de webpagina inschakelen? (ja/nee)", "ja").lower() in {"ja", "yes", "y"} else "false"
    values["TIMESHEET_CLERK_HTTP_PORT"] = question("Lokale webpoort", "8501")
    values["TIMESHEET_CLERK_API_HOST_PORT"] = question("Lokale verbindingspoort", "8502")
    values["TIMESHEET_CLERK_LISTEN_ADDRESS"] = "127.0.0.1"
    values["TIMESHEET_CLERK_PUBLIC_URL"] = question("Webadres voor Timesheet Clerk", f"http://localhost:{values['TIMESHEET_CLERK_HTTP_PORT']}")
    return values


def install(source: Path, target: Path, revision: str, *, env_file: Path | None = None, migrate_from: Path | None = None, yes: bool = False) -> None:
    target = target.expanduser().resolve()
    target.mkdir(parents=True, exist_ok=True)
    settings = target / ".env"
    if not settings.exists():
        if env_file:
            shutil.copyfile(env_file.expanduser().resolve(), settings)
        elif yes:
            raise ValueError("Een nieuwe installatie met --yes heeft --env-file nodig.")
        else:
            settings.write_text(env_text(wizard()), encoding="utf-8")
    elif env_file:
        raise ValueError("Instellingen bestaan al. Bewerk de bestaande .env; de installer overschrijft deze niet.")
    settings.chmod(0o600)
    release = target / "releases" / revision
    if not release.exists():
        staged = target / "releases" / f".{revision}-{secrets.token_hex(4)}"
        staged.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, staged, ignore=shutil.ignore_patterns(".git", ".env", ".venv", "__pycache__", ".pytest_cache"))
        staged.rename(release)
    env = os.environ.copy()
    env.update(TIMESHEET_CLERK_ENV_FILE=str(settings), TIMESHEET_CLERK_IMAGE_TAG=revision[:12])
    compose = ["docker", "compose", "--env-file", str(settings), "-f", str(release / "compose.yaml")]
    def run(*args: str):
        subprocess.run([*compose, *args], env=env, cwd=target, check=True)
    run("config", "--quiet")
    print("Timesheet Clerk en zijn eigen Hermes-runtime worden gebouwd…")
    run("build")
    previous = (target / "current").resolve() if (target / "current").is_symlink() else None
    try:
        if migrate_from:
            origin = migrate_from.expanduser().resolve()
            if not origin.exists():
                raise ValueError(f"Oude Timesheet Clerk gegevens niet gevonden: {origin}")
            run("stop", "timesheet-clerk")
            mount = f"type=bind,src={origin},dst=/import,readonly"
            subprocess.run(["docker", "run", "--rm", "--user", "0", "--mount", mount,
                            "--mount", "type=volume,src=timesheet-clerk-v2-state,dst=/data/clerk",
                            f"timesheet-clerk-v2:{revision[:12]}", "python", "-m", "timesheet_clerk.migration",
                            "import", "/import", "/data/clerk"], env=env, check=True)
        run("up", "-d", "--wait", "--wait-timeout", "180")
    except Exception:
        if previous and previous.exists():
            print("De nieuwe versie kon niet starten; Timesheet Clerk start de vorige versie opnieuw.")
            rollback_env = {**env, "TIMESHEET_CLERK_IMAGE_TAG": previous.name[:12]}
            subprocess.run(["docker", "compose", "--env-file", str(settings), "-f", str(previous / "compose.yaml"),
                            "up", "-d", "--wait", "--wait-timeout", "180"], env=rollback_env, cwd=target, check=True)
        raise
    pointer = target / ".current-new"
    pointer.unlink(missing_ok=True)
    pointer.symlink_to(release, target_is_directory=True)
    pointer.replace(target / "current")
    receipt = {"service": "Timesheet Clerk", "version": "2.0.0", "revision": revision,
               "release": str(release), "settings": str(settings), "migrated_from": str(migrate_from) if migrate_from else None}
    (target / "installation.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(f"\nTimesheet Clerk draait. Instellingen: {settings}\nOpen het webadres uit TIMESHEET_CLERK_PUBLIC_URL.\n")
    print("Verbind een nieuwe Hermes-installatie met het Timesheet Clerk verbindingsprogramma uit de README.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Install Timesheet Clerk without changing ATLAS")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--ref", default="feature/v2")
    parser.add_argument("--dir", type=Path, default=Path.home() / "timesheet-clerk")
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--migrate-from", type=Path)
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args()
    import re
    if not re.fullmatch(r"[0-9a-f]{40}", args.revision):
        parser.error("Invalid GitHub commit")
    try:
        install(args.source, args.dir, args.revision, env_file=args.env_file, migrate_from=args.migrate_from, yes=args.yes)
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print(f"Timesheet Clerk installatie gestopt: {exc}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()

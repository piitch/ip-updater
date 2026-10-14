import os
import re
from pathlib import Path

import yaml

CONFIG_PATH = Path(os.environ.get("IPUPDATER_CONFIG", "config/config.yaml"))
STATE_PATH = Path(os.environ.get("IPUPDATER_STATE", "data/state.json"))

DEFAULTS = {
    "interval": 300,
    "resync_hours": 24,
    "rule_description": "HOME",
    "ip_sources": [
        "https://api.ipify.org",
        "https://ipv4.icanhazip.com",
        "https://ifconfig.me/ip",
    ],
}

_ENV = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class ConfigError(Exception):
    pass


def _expand(value):
    """Ersetzt ${VAR} durch Umgebungsvariablen, damit Secrets in .env bleiben können."""
    if isinstance(value, str):
        def repl(m):
            if m.group(1) not in os.environ:
                raise ConfigError(f"Umgebungsvariable {m.group(1)} ist nicht gesetzt")
            return os.environ[m.group(1)]
        return _ENV.sub(repl, value)
    if isinstance(value, list):
        return [_expand(v) for v in value]
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    return value


def load_raw(path: Path = CONFIG_PATH) -> dict:
    if not path.exists():
        return {}
    with path.open() as f:
        return yaml.safe_load(f) or {}


def load(path: Path = CONFIG_PATH) -> dict:
    if not path.exists():
        raise ConfigError(
            f"{path} fehlt. Zuerst den Wizard starten: docker compose run --rm ip-updater setup"
        )
    cfg = {**DEFAULTS, **_expand(load_raw(path))}
    if not any(cfg.get(p, {}).get("enabled") for p in ("hetzner", "oci", "cloudflare")):
        raise ConfigError("Kein Provider aktiviert (hetzner / oci / cloudflare)")
    return cfg


def save(cfg: dict, path: Path = CONFIG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w") as f:
        f.write("# Erzeugt von `ipupdater setup` – darf von Hand bearbeitet werden.\n")
        f.write("# Secrets können als ${VARIABLE} aus der Umgebung/.env gelesen werden.\n")
        yaml.safe_dump(cfg, f, sort_keys=False, allow_unicode=True)
    os.chmod(tmp, 0o600)
    tmp.replace(path)

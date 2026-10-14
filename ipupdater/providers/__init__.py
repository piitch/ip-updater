from .base import Provider
from .cloudflare import Cloudflare
from .hetzner import Hetzner
from .oci import OracleCloud

REGISTRY = {"hetzner": Hetzner, "oci": OracleCloud, "cloudflare": Cloudflare}


def enabled(cfg: dict) -> list[Provider]:
    return [
        cls(cfg[key], cfg["rule_description"])
        for key, cls in REGISTRY.items()
        if cfg.get(key, {}).get("enabled")
    ]

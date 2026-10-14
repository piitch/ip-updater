import ipaddress

import requests

from .log import log


def public_ipv4(sources: list[str]) -> str:
    """Fragt die Quellen der Reihe nach ab und liefert die erste gültige IPv4."""
    errors = []
    for url in sources:
        try:
            r = requests.get(url, timeout=10)
            r.raise_for_status()
            ip = ipaddress.ip_address(r.text.strip())
            if ip.version != 4 or not ip.is_global:
                raise ValueError(f"keine öffentliche IPv4: {ip}")
            return str(ip)
        except (requests.RequestException, ValueError) as e:
            log.debug("IP-Quelle %s fehlgeschlagen: %s", url, e)
            errors.append(f"{url}: {e}")
    raise RuntimeError("Öffentliche IP nicht ermittelbar:\n  " + "\n  ".join(errors))

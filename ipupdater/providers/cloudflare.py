from .base import JsonApi, Provider, ProviderError


class Cloudflare(Provider):
    """Setzt A-Records. Zone-IDs werden automatisch aus dem Namen ermittelt."""

    name = "Cloudflare"

    def __init__(self, cfg, tag):
        super().__init__(cfg, tag)
        self.api = JsonApi("https://api.cloudflare.com/client/v4", cfg["api_token"])
        self._zones = {}

    def records(self) -> list[dict]:
        out = []
        for r in self.cfg["records"]:
            out.append({"name": r} if isinstance(r, str) else r)
        return out

    def zone_for(self, name: str) -> tuple[str, str]:
        """Sucht die Zone von hinten: www.example.co.uk → example.co.uk → ..."""
        labels = name.strip(".").split(".")
        for i in range(len(labels) - 1):
            candidate = ".".join(labels[i:])
            if candidate not in self._zones:
                res = self.api("GET", "/zones", params={"name": candidate})["result"]
                self._zones[candidate] = res[0]["id"] if res else None
            if self._zones[candidate]:
                return candidate, self._zones[candidate]
        raise ProviderError(f"Keine Cloudflare-Zone für {name} gefunden (Token-Berechtigung Zone:Read?)")

    def verify_token(self) -> str:
        res = self.api("GET", "/user/tokens/verify")["result"]
        if res.get("status") != "active":
            raise ProviderError(f"Token-Status: {res.get('status')}")
        return res["status"]

    def check(self):
        self.verify_token()
        info = []
        for rec in self.records():
            zone, zone_id = self.zone_for(rec["name"])
            existing = self._get(zone_id, rec["name"])
            info.append(f"{rec['name']} = {existing['content'] if existing else '(neu)'}")
        return ", ".join(info)

    def _get(self, zone_id, name):
        res = self.api("GET", f"/zones/{zone_id}/dns_records", params={"type": "A", "name": name})["result"]
        return res[0] if res else None

    def apply(self, ip, dry_run=False):
        done, errors = [], []
        for rec in self.records():
            name = rec["name"]
            try:
                _, zone_id = self.zone_for(name)
                existing = self._get(zone_id, name)
                body = {"type": "A", "name": name, "content": ip}
                for key in ("ttl", "proxied"):
                    if key in rec:
                        body[key] = rec[key]
                if existing and existing["content"] == ip and all(existing.get(k) == v for k, v in body.items() if k != "name"):
                    done.append(f"{name}: schon aktuell")
                    continue
                if not dry_run:
                    if existing:
                        self.api("PATCH", f"/zones/{zone_id}/dns_records/{existing['id']}", json=body)
                    else:
                        self.api("POST", f"/zones/{zone_id}/dns_records", json={"ttl": 120, "proxied": False, **body})
                done.append(f"{name} → {ip}" + ("" if existing else " (angelegt)"))
            except ProviderError as e:
                errors.append(f"{name}: {e}")
        if errors:
            raise ProviderError("; ".join(errors + done))
        return done

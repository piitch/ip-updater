import json

from .base import JsonApi, Provider, ProviderError


class Hetzner(Provider):
    """Ersetzt in Hetzner-Cloud-Firewalls nur die Regeln mit unserer Beschreibung.

    Alle anderen Regeln bleiben erhalten (das alte Skript hat sie mit set_rules überschrieben).
    """

    name = "Hetzner"

    def __init__(self, cfg, tag):
        super().__init__(cfg, tag)
        self.api = JsonApi("https://api.hetzner.cloud/v1", cfg["api_token"])

    def firewalls(self) -> list[dict]:
        return self.api("GET", "/firewalls", params={"per_page": 50})["firewalls"]

    def check(self):
        names = []
        for fw_id in self.cfg["firewall_ids"]:
            fw = self.api("GET", f"/firewalls/{fw_id}")["firewall"]
            names.append(f"{fw['name']} ({fw_id})")
        return "Firewalls: " + ", ".join(names)

    def _home_rules(self, ip):
        rules = []
        for proto in self.cfg.get("protocols", ["tcp"]):
            rule = {"direction": "in", "protocol": proto, "source_ips": [f"{ip}/32"], "description": self.tag}
            if proto in ("tcp", "udp"):
                rule["port"] = str(self.cfg.get("port", "any"))
            rules.append(rule)
        return rules

    @staticmethod
    def _clean(rule):
        """API-Antwort in ein gültiges set_rules-Objekt verwandeln."""
        out = {"direction": rule["direction"], "protocol": rule["protocol"]}
        for key in ("port", "description"):
            if rule.get(key):
                out[key] = rule[key]
        ips = "source_ips" if rule["direction"] == "in" else "destination_ips"
        out[ips] = rule.get(ips) or []
        return out

    @staticmethod
    def _canon(rules):
        return sorted(json.dumps(r, sort_keys=True) for r in rules)

    def apply(self, ip, dry_run=False):
        done = []
        for fw_id in self.cfg["firewall_ids"]:
            fw = self.api("GET", f"/firewalls/{fw_id}")["firewall"]
            current = [self._clean(r) for r in fw["rules"]]
            others = [r for r in current if r.get("description") != self.tag]
            ours = len(current) - len(others)
            home = self._home_rules(ip)
            new = others + home
            if self._canon(new) == self._canon(current):
                done.append(f"{fw['name']}: schon aktuell ({len(home)} {self.tag}-Regeln)")
                continue
            if not dry_run:
                res = self.api("POST", f"/firewalls/{fw_id}/actions/set_rules", json={"rules": new})
                failed = [a for a in res.get("actions", []) if a.get("error")]
                if failed:
                    raise ProviderError(f"{fw['name']}: {failed[0]['error']}")
            done.append(
                f"{fw['name']}: {ours} → {len(home)} {self.tag}-Regeln auf {ip}, "
                f"{len(others)} andere Regeln unverändert"
            )
        return done

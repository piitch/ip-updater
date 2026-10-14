import pytest

from ipupdater.providers.base import ProviderError
from ipupdater.providers.cloudflare import Cloudflare
from ipupdater.providers.hetzner import Hetzner


class FakeApi:
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def __call__(self, method, path, **kw):
        self.calls.append((method, path, kw))
        handler = self.routes[(method, path)]
        return handler(kw) if callable(handler) else handler


def hetzner(rules, **cfg):
    h = Hetzner({"api_token": "x", "firewall_ids": [1], **cfg}, "HOME")
    h.api = FakeApi({
        ("GET", "/firewalls/1"): {"firewall": {"name": "fw", "rules": rules}},
        ("POST", "/firewalls/1/actions/set_rules"): {"actions": [{"error": None}]},
    })
    return h


SSH = {"direction": "in", "protocol": "tcp", "port": "22", "source_ips": ["0.0.0.0/0"],
       "destination_ips": [], "description": "ssh"}
HOME_OLD = {"direction": "in", "protocol": "tcp", "port": "any", "source_ips": ["1.1.1.1/32"],
            "destination_ips": [], "description": "HOME"}


def test_hetzner_keeps_foreign_rules_and_replaces_home():
    h = hetzner([SSH, HOME_OLD])
    h.apply("2.2.2.2")
    method, _, kw = h.api.calls[-1]
    assert method == "POST"
    rules = kw["json"]["rules"]
    assert {"direction": "in", "protocol": "tcp", "port": "22", "source_ips": ["0.0.0.0/0"], "description": "ssh"} in rules
    home = [r for r in rules if r["description"] == "HOME"]
    assert home == [{"direction": "in", "protocol": "tcp", "port": "any", "source_ips": ["2.2.2.2/32"], "description": "HOME"}]


def test_hetzner_noop_when_current():
    h = hetzner([SSH, HOME_OLD])
    assert "schon aktuell" in h.apply("1.1.1.1")[0]
    assert all(c[0] == "GET" for c in h.api.calls)


def test_hetzner_icmp_has_no_port():
    h = hetzner([], protocols=["tcp", "icmp"])
    h.apply("2.2.2.2")
    rules = h.api.calls[-1][2]["json"]["rules"]
    assert [r.get("port") for r in rules] == ["any", None]


def test_hetzner_message_counts_rules():
    h = hetzner([SSH, HOME_OLD], protocols=["tcp", "udp"])
    assert h.apply("2.2.2.2") == ["fw: 1 → 2 HOME-Regeln auf 2.2.2.2, 1 andere Regeln unverändert"]


def test_hetzner_dry_run_does_not_post():
    h = hetzner([HOME_OLD])
    h.apply("2.2.2.2", dry_run=True)
    assert all(c[0] == "GET" for c in h.api.calls)


def cloudflare(records, existing):
    cf = Cloudflare({"api_token": "x", "records": records}, "HOME")
    zones = {"example.com": "Z1"}
    def route(method, path, **kw):
        cf.api.calls.append((method, path, kw))
        if path == "/zones":
            z = zones.get(kw["params"]["name"])
            return {"result": [{"id": z}] if z else []}
        if method == "GET":
            rec = existing.get(kw["params"]["name"])
            return {"result": [rec] if rec else []}
        return {"success": True}
    cf.api = route
    cf.api.calls = []
    return cf


def test_cloudflare_finds_zone_for_subdomain_and_patches():
    cf = cloudflare(["vpn.example.com"], {"vpn.example.com": {"id": "R1", "content": "1.1.1.1", "proxied": False}})
    assert cf.apply("2.2.2.2") == ["vpn.example.com → 2.2.2.2"]
    patch = [c for c in cf.api.calls if c[0] == "PATCH"]
    assert patch and patch[0][1] == "/zones/Z1/dns_records/R1"


def test_cloudflare_creates_missing_record():
    cf = cloudflare([{"name": "example.com", "proxied": False}], {})
    assert "angelegt" in cf.apply("2.2.2.2")[0]
    assert any(c[0] == "POST" for c in cf.api.calls)


def test_cloudflare_unknown_zone_reports_error_but_does_others():
    cf = cloudflare(["example.com", "other.net"], {"example.com": {"id": "R1", "content": "1.1.1.1"}})
    with pytest.raises(ProviderError) as e:
        cf.apply("2.2.2.2")
    assert "other.net" in str(e.value) and "example.com → 2.2.2.2" in str(e.value)

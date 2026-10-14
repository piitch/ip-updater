import pytest

from ipupdater import config, state, updater
from ipupdater.providers.base import ProviderError


class P:
    def __init__(self, name, fail=False):
        self.name, self.fail, self.applied = name, fail, []

    def apply(self, ip, dry_run=False):
        if self.fail:
            raise ProviderError("kaputt")
        self.applied.append(ip)
        return ["ok"]


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "STATE_PATH", tmp_path / "state.json")
    sent = []
    monkeypatch.setattr(updater.notify, "send", lambda cfg, report: sent.append(updater.notify.subject(report)))
    box = {"ip": "1.1.1.1", "providers": [P("A")]}
    monkeypatch.setattr(updater, "public_ipv4", lambda s: box["ip"])
    monkeypatch.setattr(updater.providers, "enabled", lambda cfg: box["providers"])
    return box, sent, {**config.DEFAULTS, "resync_hours": 0}


def test_change_then_noop(env):
    box, sent, cfg = env
    assert updater.run_once(cfg)
    assert len(sent) == 1 and "1.1.1.1" in sent[0]
    assert updater.run_once(cfg)
    assert box["providers"][0].applied == ["1.1.1.1"]
    assert len(sent) == 1


def test_failure_is_retried_and_mailed_once(env):
    box, sent, cfg = env
    box["providers"] = [P("A"), P("B", fail=True)]
    assert not updater.run_once(cfg)
    assert not updater.run_once(cfg)  # Wiederholung, gleicher Fehler → keine zweite Mail
    assert len(sent) == 1 and "fehlgeschlagen" in sent[0]
    assert box["providers"][0].applied == ["1.1.1.1", "1.1.1.1"]
    box["providers"][1].fail = False
    assert updater.run_once(cfg)
    assert "wieder erfolgreich" in sent[-1]
    assert state.load()["failed"] == []


def test_dry_run_writes_no_state(env):
    box, sent, cfg = env
    updater.run_once(cfg, force=True, dry_run=True)
    assert state.load() == {} and sent == []


def test_mail_renders_text_and_html():
    from ipupdater import notify
    r = notify.Report("error", "2.2.2.2", "1.1.1.1", [
        notify.Result("Hetzner", True, ["fw: 1 → 5 HOME-Regeln auf 2.2.2.2"]),
        notify.Result("Cloudflare", False, ["a.com: HTTP 403 <boom>"]),
    ])
    assert notify.subject(r) == "❌ IP-Update fehlgeschlagen (Cloudflare)"
    assert "❌ Cloudflare" in notify.render_text(r)
    html = notify.render_html(r)
    assert "&lt;boom&gt;" in html and "2.2.2.2" in html and "FEHLER" in html

"""Interaktiver Setup-Wizard: fragt alles ab, testet es live und schreibt config.yaml."""

import getpass
import shutil
import sys
from pathlib import Path

try:
    import readline  # noqa: F401  – aktiviert Rücktaste/Pfeiltasten in input()
except ImportError:
    pass

from . import config, notify
from .ip import public_ipv4
from .providers.base import ProviderError
from .providers.cloudflare import Cloudflare
from .providers.hetzner import Hetzner
from .providers.oci import OracleCloud

B, G, R, Y, X = "\033[1m", "\033[32m", "\033[31m", "\033[33m", "\033[0m"


def head(text):
    print(f"\n{B}── {text} {'─' * max(0, 50 - len(text))}{X}")


def ok(text):
    print(f"  {G}✔{X} {text}")


def warn(text):
    print(f"  {Y}!{X} {text}")


def err(text):
    print(f"  {R}✘{X} {text}")


def ask(prompt, default=None, secret=False, required=True):
    while True:
        if secret:
            hint = " [gespeichert, Enter = behalten]" if default else ""
            val = getpass.getpass(f"  {prompt}{hint}: ")
        else:
            hint = f" [{default}]" if default not in (None, "") else ""
            val = input(f"  {prompt}{hint}: ").strip()
        val = val or (default if default is not None else "")
        if val or not required:
            return val
        err("Pflichtfeld")


def yes(prompt, default=True):
    d = "J/n" if default else "j/N"
    val = input(f"  {prompt} [{d}]: ").strip().lower()
    return default if not val else val in ("j", "ja", "y", "yes")


def pick(items, label, preselected=()):
    """Mehrfachauswahl per Nummern, z.B. '1,3'."""
    for i, (key, text) in enumerate(items, 1):
        mark = "*" if key in preselected else " "
        print(f"   {mark}{i:>2}) {text}")
    default = ",".join(str(i) for i, (k, _) in enumerate(items, 1) if k in preselected) or "1"
    while True:
        raw = ask(f"{label} (Nummern, kommagetrennt)", default)
        try:
            idx = [int(x) for x in raw.replace(" ", "").split(",") if x]
            return [items[i - 1][0] for i in idx]
        except (ValueError, IndexError):
            err("Ungültige Auswahl")


def retry(fn):
    """Fragt so lange neu, bis der Live-Test klappt oder der Nutzer abbricht."""
    while True:
        try:
            return fn()
        except (ProviderError, Exception) as e:
            err(str(e))
            if not yes("Nochmal versuchen?"):
                return None


# ── Abschnitte ──────────────────────────────────────────────────────────────

def setup_general(cfg):
    head("Allgemein")
    try:
        ok(f"Deine aktuelle öffentliche IP: {public_ipv4(config.DEFAULTS['ip_sources'])}")
    except RuntimeError as e:
        warn(str(e))
    cfg["interval"] = int(ask("Prüfintervall in Sekunden", cfg.get("interval", 300)))
    cfg["resync_hours"] = int(ask("Alle X Stunden trotzdem abgleichen (0 = nie)", cfg.get("resync_hours", 24)))
    cfg["rule_description"] = ask(
        "Beschreibung der verwalteten Firewall-Regeln", cfg.get("rule_description", "HOME")
    )
    print(f"    Nur Regeln mit Beschreibung „{cfg['rule_description']}“ werden angefasst, alle anderen bleiben.")


def setup_hetzner(cfg, tag):
    old = cfg.get("hetzner", {})
    head("Hetzner Cloud Firewall")
    if not yes("Hetzner verwenden?", old.get("enabled", True)):
        cfg["hetzner"] = {**old, "enabled": False}
        return

    def go():
        token = ask("API-Token (Projekt → Security → API Tokens, Read & Write)", old.get("api_token"), secret=True)
        h = Hetzner({"api_token": token}, tag)
        fws = h.firewalls()
        if not fws:
            raise ProviderError("Keine Firewalls in diesem Projekt gefunden")
        ok(f"Token gültig – {len(fws)} Firewall(s) gefunden")
        ids = pick(
            [(fw["id"], f"{fw['name']} (ID {fw['id']}, {len(fw['rules'])} Regeln)") for fw in fws],
            "Welche Firewalls aktualisieren?", old.get("firewall_ids", []),
        )
        protos = ask("Protokolle für die HOME-Regel (tcp,udp,icmp)", ",".join(old.get("protocols", ["tcp"])))
        return {
            "enabled": True,
            "api_token": token,
            "firewall_ids": ids,
            "protocols": [p.strip() for p in protos.split(",") if p.strip()],
            "port": old.get("port", "any"),
        }

    cfg["hetzner"] = retry(go) or {**old, "enabled": False}


def setup_cloudflare(cfg, tag):
    old = cfg.get("cloudflare", {})
    head("Cloudflare DNS")
    if not yes("Cloudflare verwenden?", old.get("enabled", True)):
        cfg["cloudflare"] = {**old, "enabled": False}
        return

    def go():
        print("    Token braucht: Zone → DNS → Edit und Zone → Zone → Read (für alle betroffenen Zonen).")
        token = ask("API-Token", old.get("api_token"), secret=True)
        cf = Cloudflare({"api_token": token, "records": []}, tag)
        cf.verify_token()
        ok("Token aktiv")
        prev = ",".join(r if isinstance(r, str) else r["name"] for r in old.get("records", []))
        names = ask("Records (z.B. example.com,example.org,vpn.example.com)", prev or None)
        records = []
        for name in [n.strip() for n in names.split(",") if n.strip()]:
            zone, zone_id = cf.zone_for(name)
            current = cf._get(zone_id, name)
            if current:
                ok(f"{name} (Zone {zone}) – aktuell {current['content']}, proxied={current['proxied']}")
            else:
                warn(f"{name} (Zone {zone}) – kein A-Record, wird beim ersten Lauf angelegt")
            records.append({"name": name, "ttl": 120, "proxied": bool(current and current["proxied"])})
        return {"enabled": True, "api_token": token, "records": records}

    cfg["cloudflare"] = retry(go) or {**old, "enabled": False}


def read_block(prompt):
    """Mehrzeilige Eingabe bis zur ersten Leerzeile (führende Leerzeilen werden ignoriert)."""
    print(f"  {prompt} (mit einer leeren Zeile abschließen):")
    lines = []
    while True:
        line = sys.stdin.readline()
        if not line:  # EOF
            break
        line = line.strip()
        if not line and lines:
            break
        if line:
            lines.append(line)
    return lines


def parse_oci_config(lines):
    """Liest die Vorschau „Konfigurationsdatei“ aus der OCI-Konsole (user=…, fingerprint=…, …)."""
    out = {}
    for line in lines:
        key, sep, val = line.partition("=")
        if sep and key.strip() in ("user", "fingerprint", "tenancy", "region"):
            out[key.strip()] = val.strip()
    return out


def generate_oci_key(path):
    """Erzeugt ein RSA-Schlüsselpaar wie die OCI-Konsole. Gibt (Public-PEM, Fingerprint) zurück."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ))
    path.chmod(0o600)
    return public_key_info(key.public_key())


def public_key_info(pub):
    import hashlib

    from cryptography.hazmat.primitives import serialization

    der = pub.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    pem = pub.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    digest = hashlib.md5(der).hexdigest()
    return pem.decode(), ":".join(digest[i:i + 2] for i in range(0, 32, 2))


def setup_oci(cfg, tag):
    old = cfg.get("oci", {})
    head("Oracle Cloud Security List")
    if not yes("Oracle Cloud verwenden?", old.get("enabled", False)):
        cfg["oci"] = {**old, "enabled": False}
        return

    key_target = config.CONFIG_PATH.parent / "oci" / "oci_api_key.pem"

    def go():
        fingerprint = None
        if key_target.exists() and yes(f"Vorhandenen Schlüssel {key_target} weiterverwenden?"):
            from cryptography.hazmat.primitives import serialization
            priv = serialization.load_pem_private_key(key_target.read_bytes(), password=None)
            _, fingerprint = public_key_info(priv.public_key())
        elif yes("Neues API-Schlüsselpaar erzeugen? (empfohlen, sonst vorhandene .pem verwenden)"):
            pem, fingerprint = generate_oci_key(key_target)
            ok(f"Schlüssel erzeugt: {key_target}")
            print(f"""
    In der OCI-Konsole: Profil (oben rechts) → Mein Profil → API-Schlüssel
      → API-Schlüssel hinzufügen → „Öffentlichen Schlüssel einfügen“ → diesen Block einfügen:

{pem}
    → Hinzufügen. Erwarteter Fingerprint: {fingerprint}
""")
            input("  Enter drücken, sobald der Schlüssel hinzugefügt ist … ")
        else:
            src = ask("Pfad zur privaten .pem (leer = Inhalt einfügen)", required=False)
            key_target.parent.mkdir(parents=True, exist_ok=True)
            if src:
                shutil.copyfile(Path(src).expanduser(), key_target)
            else:
                key_target.write_text("\n".join(read_block("PEM-Inhalt einfügen")) + "\n")
            key_target.chmod(0o600)
            from cryptography.hazmat.primitives import serialization
            priv = serialization.load_pem_private_key(key_target.read_bytes(), password=None)
            _, fingerprint = public_key_info(priv.public_key())

        print("    Die Konsole zeigt jetzt eine „Vorschau der Konfigurationsdatei“ ([DEFAULT], user=…, …).")
        c = parse_oci_config(read_block("Diesen Block hier einfügen (oder leer lassen für Einzeleingabe)"))
        for key, label, default in (
            ("user", "User-OCID", old.get("user")),
            ("tenancy", "Tenancy-OCID", old.get("tenancy")),
            ("region", "Region", old.get("region", "eu-frankfurt-1")),
        ):
            if key not in c:
                c[key] = ask(label, default)
        if c.get("fingerprint") and c["fingerprint"] != fingerprint:
            warn(f"Fingerprint aus der Konsole ({c['fingerprint']}) passt nicht zum Schlüssel ({fingerprint})")
        c["fingerprint"] = fingerprint
        ok(f"user …{c['user'][-8:]}, tenancy …{c['tenancy'][-8:]}, {c['region']}, {fingerprint}")

        c["enabled"] = True
        # Pfad so speichern, wie der Container ihn sieht
        c["key_file"] = "/config/oci/oci_api_key.pem" if Path("/config").is_dir() else str(key_target)
        print("    Security-List-OCID: Networking → VCN → Security Lists → Liste → OCID kopieren.")
        ids = ask("Security-List-OCIDs (kommagetrennt)", ",".join(old.get("security_list_ids", [])) or None)
        c["security_list_ids"] = [i.strip() for i in ids.split(",") if i.strip()]
        c["protocol"] = old.get("protocol", "all")
        ok(OracleCloud(c, tag).check())
        return c

    cfg["oci"] = retry(go) or {**old, "enabled": False}


def setup_notify(cfg):
    old = cfg.get("notify", {})
    head("Benachrichtigungen")
    n = {"on": old.get("on", ["change", "error"])}

    s_old = old.get("smtp", {})
    if yes("Per E-Mail benachrichtigen?", s_old.get("enabled", True)):
        def go():
            security = ask("Verschlüsselung (ssl/starttls/none)", s_old.get("security", "ssl"))
            s = {
                "enabled": True,
                "host": ask("SMTP-Server", s_old.get("host")),
                "port": int(ask("Port", s_old.get("port", 465 if security == "ssl" else 587))),
                "security": security,
                "user": ask("Benutzer", s_old.get("user"), required=False),
            }
            s["password"] = ask("Passwort", s_old.get("password"), secret=True, required=bool(s["user"]))
            s["from"] = ask("Absender", s_old.get("from", s["user"] or None))
            s["to"] = ask("Empfänger", s_old.get("to"))
            if yes("Testmail senden?"):
                notify.smtp(s, notify.Report("test"))
                ok(f"Testmail an {s['to']} verschickt")
            return s
        n["smtp"] = retry(go) or {**s_old, "enabled": False}
    else:
        n["smtp"] = {**s_old, "enabled": False}

    t_old = old.get("ntfy", {})
    if yes("Push über ntfy (ntfy.sh oder eigener Server)?", t_old.get("enabled", False)):
        n["ntfy"] = {
            "enabled": True,
            "url": ask("Topic-URL (z.B. https://ntfy.sh/mein-geheimes-topic)", t_old.get("url")),
            "token": ask("Access-Token (optional)", t_old.get("token"), secret=True, required=False),
        }
    else:
        n["ntfy"] = {**t_old, "enabled": False}
    cfg["notify"] = n


def main() -> int:
    print(f"{B}ip-updater – Setup{X}")
    cfg = config.load_raw()
    if cfg:
        print(f"  Vorhandene Konfiguration {config.CONFIG_PATH} gefunden – Werte werden als Vorgabe genutzt.")
    try:
        setup_general(cfg)
        tag = cfg["rule_description"]
        setup_hetzner(cfg, tag)
        setup_oci(cfg, tag)
        setup_cloudflare(cfg, tag)
        setup_notify(cfg)
    except (KeyboardInterrupt, EOFError):
        print(f"\n{Y}Abgebrochen – nichts gespeichert.{X}")
        return 1

    head("Fertig")
    active = [k for k in ("hetzner", "oci", "cloudflare") if cfg.get(k, {}).get("enabled")]
    if not active:
        err("Kein Provider aktiv – nichts zu tun.")
        return 1
    config.save(cfg)
    ok(f"Gespeichert: {config.CONFIG_PATH} (aktiv: {', '.join(active)})")
    print("\n  Nächste Schritte:")
    print("    docker compose run --rm ip-updater once --dry-run   # zeigt, was passieren würde")
    print("    docker compose up -d                                # Dauerbetrieb")
    return 0

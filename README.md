# ip-updater

Hält **Hetzner-Cloud-Firewalls**, **Oracle-Cloud-Security-Lists** und **Cloudflare-A-Records**
automatisch auf der aktuellen Heim-IP. Läuft als kleiner Docker-Container und hat einen
Setup-Wizard, der alle Zugangsdaten live prüft.

## Schnellstart

```bash
git clone <repo> ip-updater && cd ip-updater
docker compose build
docker compose run --rm ip-updater setup              # Wizard
docker compose run --rm ip-updater once --dry-run     # zeigt, was passieren würde
docker compose up -d                                  # Dauerbetrieb
docker compose logs -f
```

Der Wizard
- listet die Hetzner-Firewalls des Projekts auf und lässt dich auswählen,
- findet die Cloudflare-Zonen selbst (Zone-IDs müssen nicht mehr eingetragen werden) und zeigt den aktuellen Stand jedes Records,
- erzeugt für Oracle ein API-Schlüsselpaar und zeigt den öffentlichen Schlüssel zum Einfügen in der
  Konsole an (Profil → API-Schlüssel → „Öffentlichen Schlüssel einfügen“). Die Konfigurationsvorschau
  der Konsole wird am Stück eingefügt. Signiert wird jede Anfrage von der `oci`-Bibliothek, dafür ist
  keine eigene Einrichtung nötig. Danach testet er den Zugriff auf die Security-Lists,
- verschickt auf Wunsch eine Testmail,
- schreibt am Ende `config/config.yaml` mit den Rechten `600`. Ein erneuter Aufruf übernimmt die vorhandenen Werte als Vorgabe.

## Befehle

| Befehl | Zweck |
|---|---|
| `setup` | Einrichtungs-Wizard |
| `run` | Dauerbetrieb, prüft alle `interval` Sekunden (Standard) |
| `once [--force] [--dry-run]` | ein Durchlauf |
| `check` | Zugangsdaten testen, nichts ändern |
| `test-notify` | Testnachricht per Mail/ntfy |

Aufruf jeweils mit `docker compose run --rm ip-updater <befehl>`.

## Verhalten

- **Fremde Regeln bleiben erhalten.** Verwaltet werden nur Firewall-Regeln mit der Beschreibung
  `rule_description` (Standard `HOME`). Das alte Skript hat mit Hetzners `set_rules` und
  `oci … --force` alle übrigen Regeln gelöscht.
- **Fehler werden wiederholt.** Die neue IP gilt erst als erledigt, wenn alle Provider sie
  übernommen haben, sonst kommt beim nächsten Intervall ein neuer Versuch. Das alte Skript hat
  `/tmp/current_ip` schon vor dem Update geschrieben, ein Fehler wurde dort nie wiederholt.
- **Erfolg wird pro Provider ausgewertet.** Früher hat nur das Ergebnis des letzten Cloudflare-Records
  entschieden, ob „Erfolg“ gemeldet wurde.
- **Keine Mailflut.** Eine Mail kommt nur bei einem IP-Wechsel, bei einem neuen Fehler und wenn es danach wieder klappt.
- **Abgleich alle `resync_hours`.** Auch ohne IP-Wechsel wird regelmäßig abgeglichen, damit
  manuelle Änderungen in den Consoles wieder korrigiert werden.
- Der Zustand liegt in `data/state.json` und übersteht einen Neustart.
- Für die IP gibt es mehrere Quellen (ipify, icanhazip, ifconfig.me) und eine Prüfung auf eine gültige öffentliche IPv4.

## Oracle-Rechte

Ein Admin-Benutzer kann alles. Für einen eigenen, eingeschränkten Benutzer braucht dessen Gruppe:

```
Allow group ip-updater to manage security-lists in compartment <compartment>
```

## Secrets

Am einfachsten trägt der Wizard die Secrets direkt in `config/config.yaml` ein. Alternativ
schreibst du in der Config `${CLOUDFLARE_API_TOKEN}` usw. und legst die Werte in `.env` ab
(wird von `docker-compose.yml` geladen). `config/`, `data/` und `.env` stehen in `.gitignore`.

## Entwicklung

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt pytest
.venv/bin/pytest
IPUPDATER_CONFIG=config/config.yaml .venv/bin/python -m ipupdater once --dry-run
```

## Lizenz

MIT, siehe [LICENSE](LICENSE).

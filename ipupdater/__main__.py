import argparse
import sys

from . import __version__, config, log, notify, providers, state, updater


def cmd_check(cfg) -> int:
    """Zugangsdaten aller Provider testen, ohne etwas zu ändern."""
    good = True
    for p in providers.enabled(cfg):
        try:
            log.log.info("✅ %s: %s", p.name, p.check())
        except Exception as e:
            log.log.error("❌ %s: %s", p.name, e)
            good = False
    st = state.load()
    if st:
        log.log.info("Letzter Stand: IP %s, geprüft %s", st.get("ip"), st.get("checked_at"))
    return 0 if good else 1


def main() -> int:
    ap = argparse.ArgumentParser(prog="ipupdater", description="Firewalls & DNS auf die Heim-IP nachziehen")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("setup", help="interaktiver Einrichtungs-Wizard")
    sub.add_parser("run", help="Dauerbetrieb (Standard)")
    once = sub.add_parser("once", help="einmal prüfen und ggf. aktualisieren")
    once.add_argument("--force", action="store_true", help="auch ohne IP-Wechsel aktualisieren")
    once.add_argument("--dry-run", action="store_true", help="nur anzeigen, nichts ändern")
    sub.add_parser("check", help="Zugangsdaten testen, nichts ändern")
    sub.add_parser("test-notify", help="Testnachricht an alle Benachrichtigungskanäle")
    args = ap.parse_args()

    if args.cmd == "setup":
        from . import wizard
        return wizard.main()

    log.setup(args.verbose)
    try:
        cfg = config.load()
    except config.ConfigError as e:
        log.log.error("%s", e)
        return 2

    if args.cmd == "check":
        return cmd_check(cfg)
    if args.cmd == "test-notify":
        st = state.load()
        notify.send(cfg, notify.Report("test", st.get("ip", ""), st.get("previous_ip")))
        return 0
    if args.cmd == "once":
        return 0 if updater.run_once(cfg, force=args.force or args.dry_run, dry_run=args.dry_run) else 1
    updater.run_forever(cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())

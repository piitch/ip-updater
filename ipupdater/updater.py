import time
from datetime import datetime, timedelta, timezone

from . import notify, providers, state
from .ip import public_ipv4
from .log import log


def run_once(cfg: dict, force: bool = False, dry_run: bool = False) -> bool:
    """Ein Durchlauf. Gibt True zurück, wenn alles in Ordnung ist."""
    st = state.load()
    try:
        ip = public_ipv4(cfg["ip_sources"])
    except RuntimeError as e:
        log.error("%s", e)
        return False

    old_ip = st.get("ip")
    reason = None
    if force:
        reason = "erzwungen"
    elif ip != old_ip:
        reason = f"IP geändert ({old_ip or '–'} → {ip})"
    elif st.get("failed"):
        reason = "Wiederholung nach Fehler: " + ", ".join(st["failed"])
    elif _resync_due(cfg, st):
        reason = f"Abgleich ({cfg['resync_hours']} h)"

    if not reason:
        log.info("✅ IP unverändert (%s)", ip)
        return True

    log.info("🔄 %s%s", reason, " [dry-run]" if dry_run else "")
    results, failed = [], []
    for p in providers.enabled(cfg):
        try:
            lines = p.apply(ip, dry_run=dry_run)
            for line in lines:
                log.info("  ✅ %s: %s", p.name, line)
            results.append(notify.Result(p.name, True, lines))
        except Exception as e:
            log.error("  ❌ %s: %s", p.name, e)
            results.append(notify.Result(p.name, False, str(e).split("; ")))
            failed.append(p.name)

    if dry_run:
        return not failed

    changed = ip != old_ip
    prev_failed = st.get("failed", [])
    st.update(ip=ip, failed=failed, checked_at=state.now())
    if not failed:
        st["synced_at"] = state.now()
    if changed:
        st["changed_at"] = state.now()
        st["previous_ip"] = old_ip
    state.save(st)

    # Mails nur bei IP-Wechsel, neuen Fehlern oder Erholung – nicht alle 5 Minuten dasselbe.
    on = cfg.get("notify", {}).get("on", ["change", "error"])
    kind = None
    if failed and "error" in on and (changed or failed != prev_failed):
        kind = "error"
    elif not failed and changed and "change" in on:
        kind = "change"
    elif not failed and prev_failed and "error" in on:
        kind = "recovered"
    if kind:
        notify.send(cfg, notify.Report(kind, ip, old_ip, results))
    return not failed


def _resync_due(cfg, st) -> bool:
    hours = cfg.get("resync_hours") or 0
    if not hours or not st.get("synced_at"):
        return bool(hours)
    return datetime.now(timezone.utc) - datetime.fromisoformat(st["synced_at"]) > timedelta(hours=hours)


def run_forever(cfg: dict) -> None:
    interval = int(cfg["interval"])
    names = ", ".join(p.name for p in providers.enabled(cfg))
    log.info("🚀 ip-updater läuft – alle %ss, Provider: %s", interval, names)
    while True:
        try:
            run_once(cfg)
        except Exception:
            log.exception("Unerwarteter Fehler")
        time.sleep(interval)

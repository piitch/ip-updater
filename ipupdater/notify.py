import smtplib
import socket
import ssl
from dataclasses import dataclass, field
from datetime import datetime
from email.message import EmailMessage
from html import escape

import requests

from .log import log


@dataclass
class Result:
    provider: str
    ok: bool
    lines: list[str]


@dataclass
class Report:
    kind: str  # change | error | recovered | test
    ip: str = ""
    old_ip: str | None = None
    results: list[Result] = field(default_factory=list)
    when: datetime = field(default_factory=lambda: datetime.now().astimezone())

    @property
    def failed(self) -> list[str]:
        return [r.provider for r in self.results if not r.ok]


# Titel, Untertitel, Farbe je Anlass
KINDS = {
    "change": ("Neue IP-Adresse", "Alle Firewalls und DNS-Einträge wurden aktualisiert.", "#16a34a"),
    "error": ("IP-Update fehlgeschlagen", "Mindestens ein Ziel konnte nicht aktualisiert werden. "
              "Der nächste Versuch läuft automatisch.", "#dc2626"),
    "recovered": ("IP-Update wieder erfolgreich", "Die zuvor fehlgeschlagenen Ziele sind jetzt aktuell.", "#16a34a"),
    "test": ("Testmail", "Wenn du das liest, funktioniert der Versand.", "#2563eb"),
}


def subject(r: Report) -> str:
    if r.kind == "change":
        return f"✅ Neue IP {r.ip}"
    if r.kind == "error":
        return f"❌ IP-Update fehlgeschlagen ({', '.join(r.failed)})"
    if r.kind == "recovered":
        return f"✅ IP-Update wieder erfolgreich ({r.ip})"
    return "ip-updater: Testmail"


def render_text(r: Report) -> str:
    title, intro, _ = KINDS[r.kind]
    out = [title, "=" * len(title), "", intro, ""]
    if r.ip:
        out += [f"Neue IP:  {r.ip}", f"Alte IP:  {r.old_ip or '–'}", ""]
    for res in r.results:
        out.append(f"{'✅' if res.ok else '❌'} {res.provider}")
        out += [f"   • {line}" for line in res.lines]
    out += ["", f"{r.when:%d.%m.%Y %H:%M} · {socket.gethostname()}"]
    return "\n".join(out)


def render_html(r: Report) -> str:
    title, intro, color = KINDS[r.kind]
    font = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"

    ip_block = ""
    if r.ip:
        old = escape(r.old_ip or "–")
        ip_block = f"""
        <tr><td style="padding:8px 32px 24px">
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0"
                 style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px">
            <tr>
              <td style="padding:16px 20px;width:50%">
                <div style="font-size:12px;color:#64748b;text-transform:uppercase;letter-spacing:.05em">Neue IP</div>
                <div style="font-size:22px;font-weight:700;color:#0f172a;font-family:ui-monospace,Menlo,Consolas,monospace">{escape(r.ip)}</div>
              </td>
              <td style="padding:16px 20px;border-left:1px solid #e2e8f0">
                <div style="font-size:12px;color:#64748b;text-transform:uppercase;letter-spacing:.05em">Vorher</div>
                <div style="font-size:16px;color:#94a3b8;font-family:ui-monospace,Menlo,Consolas,monospace">{old}</div>
              </td>
            </tr>
          </table>
        </td></tr>"""

    rows = ""
    for res in r.results:
        badge_bg, badge_fg, badge = ("#dcfce7", "#166534", "OK") if res.ok else ("#fee2e2", "#991b1b", "FEHLER")
        lines = "".join(
            f'<div style="font-size:13px;color:#475569;padding-top:4px">{escape(line)}</div>'
            for line in res.lines
        )
        rows += f"""
            <tr><td style="padding:14px 0;border-top:1px solid #e2e8f0">
              <span style="display:inline-block;background:{badge_bg};color:{badge_fg};font-size:11px;font-weight:700;
                           padding:2px 8px;border-radius:999px;margin-right:8px">{badge}</span>
              <span style="font-size:15px;font-weight:600;color:#0f172a">{escape(res.provider)}</span>
              {lines}
            </td></tr>"""
    results_block = f"""
        <tr><td style="padding:0 32px 24px">
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0">{rows}</table>
        </td></tr>""" if rows else ""

    return f"""<!doctype html>
<html><body style="margin:0;padding:0;background:#f1f5f9">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f1f5f9;padding:24px 12px">
  <tr><td align="center">
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0"
           style="max-width:560px;background:#ffffff;border-radius:14px;overflow:hidden;font-family:{font}">
      <tr><td style="background:{color};height:6px;font-size:0;line-height:0">&nbsp;</td></tr>
      <tr><td style="padding:28px 32px 8px">
        <div style="font-size:13px;color:#64748b">ip-updater</div>
        <h1 style="margin:4px 0 8px;font-size:22px;color:#0f172a">{escape(title)}</h1>
        <p style="margin:0;font-size:14px;line-height:1.5;color:#475569">{escape(intro)}</p>
      </td></tr>
      {ip_block}
      {results_block}
      <tr><td style="padding:16px 32px;background:#f8fafc;border-top:1px solid #e2e8f0;font-size:12px;color:#94a3b8">
        {r.when:%d.%m.%Y, %H:%M} · {escape(socket.gethostname())}
      </td></tr>
    </table>
  </td></tr>
</table>
</body></html>"""


def send(cfg: dict, report: Report) -> None:
    """Verschickt an alle konfigurierten Kanäle; Fehler werden nur geloggt."""
    n = cfg.get("notify") or {}
    if n.get("smtp", {}).get("enabled"):
        try:
            smtp(n["smtp"], report)
            log.info("✉️  E-Mail an %s gesendet", n["smtp"]["to"])
        except Exception as e:
            log.error("E-Mail-Versand fehlgeschlagen: %s", e)
    if n.get("ntfy", {}).get("enabled"):
        try:
            ntfy(n["ntfy"], report)
            log.info("🔔 ntfy-Nachricht gesendet")
        except Exception as e:
            log.error("ntfy fehlgeschlagen: %s", e)


def smtp(c: dict, report: Report) -> None:
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject(report), c["from"], c["to"]
    msg.set_content(render_text(report))
    msg.add_alternative(render_html(report), subtype="html")
    security = c.get("security", "ssl")
    ctx = ssl.create_default_context()
    if security == "ssl":
        server = smtplib.SMTP_SSL(c["host"], c.get("port", 465), context=ctx, timeout=30)
    else:
        server = smtplib.SMTP(c["host"], c.get("port", 587), timeout=30)
    with server:
        if security == "starttls":
            server.starttls(context=ctx)
        if c.get("user"):
            server.login(c["user"], c["password"])
        server.send_message(msg)


def ntfy(c: dict, report: Report) -> None:
    lines = [f"{'✅' if r.ok else '❌'} {r.provider}: " + "; ".join(r.lines) for r in report.results]
    body = "\n".join(([f"{report.old_ip or '–'} → {report.ip}"] if report.ip else []) + lines)
    headers = {
        "Title": subject(report).encode("utf-8"),
        "Priority": "high" if report.kind == "error" else "default",
        "Tags": "rotating_light" if report.kind == "error" else "globe_with_meridians",
    }
    if c.get("token"):
        headers["Authorization"] = f"Bearer {c['token']}"
    r = requests.post(c["url"], data=(body or KINDS[report.kind][1]).encode("utf-8"), headers=headers, timeout=15)
    r.raise_for_status()

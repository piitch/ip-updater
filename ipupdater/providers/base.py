import requests


class ProviderError(Exception):
    pass


class Provider:
    """Ein Ziel, das die Heim-IP kennen muss (Firewall, DNS, ...)."""

    name = "provider"

    def __init__(self, cfg: dict, tag: str):
        self.cfg = cfg
        self.tag = tag

    def check(self) -> str:
        """Zugangsdaten und Ziele prüfen, ohne etwas zu ändern. Gibt eine Kurzinfo zurück."""
        raise NotImplementedError

    def apply(self, ip: str, dry_run: bool = False) -> list[str]:
        """IP setzen. Gibt eine Zeile pro Ziel zurück, wirft ProviderError bei Fehlern."""
        raise NotImplementedError


class JsonApi:
    """Dünner requests-Wrapper mit lesbaren Fehlermeldungen."""

    def __init__(self, base: str, token: str):
        self.base = base.rstrip("/")
        self.s = requests.Session()
        self.s.headers.update({"Authorization": f"Bearer {token}", "Content-Type": "application/json"})

    def __call__(self, method: str, path: str, **kw) -> dict:
        try:
            r = self.s.request(method, f"{self.base}{path}", timeout=30, **kw)
        except requests.RequestException as e:
            raise ProviderError(f"{method} {path}: {e}") from e
        try:
            body = r.json()
        except ValueError:
            body = {"raw": r.text[:500]}
        if not r.ok:
            raise ProviderError(f"{method} {path} → HTTP {r.status_code}: {body}")
        return body

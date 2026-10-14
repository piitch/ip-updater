from pathlib import Path

from .base import Provider, ProviderError


class OracleCloud(Provider):
    """Ersetzt in OCI-Security-Lists nur die Ingress-Regeln mit unserer Beschreibung.

    Das alte Skript hat mit `--ingress-security-rules ... --force` sämtliche Ingress-Regeln
    überschrieben; hier bleiben alle anderen erhalten.
    """

    name = "Oracle Cloud"

    def __init__(self, cfg, tag):
        super().__init__(cfg, tag)
        self._client = None

    def client(self):
        if self._client is None:
            import oci  # schwerer Import, nur wenn OCI aktiv ist

            try:
                if self.cfg.get("user"):
                    conf = {k: self.cfg[k] for k in ("user", "fingerprint", "tenancy", "region", "key_file")}
                else:
                    path = Path(self.cfg.get("config_file", "/config/oci/config"))
                    conf = oci.config.from_file(str(path), self.cfg.get("profile", "DEFAULT"))
                    if self.cfg.get("region"):
                        conf["region"] = self.cfg["region"]
                oci.config.validate_config(conf)
            except Exception as e:
                raise ProviderError(f"OCI-Konfiguration ungültig: {e}") from e
            self._oci = oci
            self._client = oci.core.VirtualNetworkClient(conf, timeout=(10, 60))
        return self._client

    def _get(self, sl_id):
        client = self.client()
        try:
            return client.get_security_list(sl_id).data
        except self._oci.exceptions.ServiceError as e:
            raise ProviderError(f"{sl_id}: {e.code} {e.message}") from e

    def check(self):
        return "Security-Lists: " + ", ".join(self._get(i).display_name for i in self.cfg["security_list_ids"])

    def apply(self, ip, dry_run=False):
        done = []
        for sl_id in self.cfg["security_list_ids"]:
            sl = self._get(sl_id)
            models = self._oci.core.models
            others = [r for r in sl.ingress_security_rules if r.description != self.tag]
            ours = [r for r in sl.ingress_security_rules if r.description == self.tag]
            proto = str(self.cfg.get("protocol", "all"))
            if len(ours) == 1 and ours[0].source == f"{ip}/32" and ours[0].protocol == proto:
                done.append(f"{sl.display_name}: schon aktuell")
                continue
            home = models.IngressSecurityRule(
                source=f"{ip}/32", source_type="CIDR_BLOCK", protocol=proto,
                is_stateless=False, description=self.tag,
            )
            if not dry_run:
                try:
                    self.client().update_security_list(
                        sl_id, models.UpdateSecurityListDetails(ingress_security_rules=others + [home])
                    )
                except self._oci.exceptions.ServiceError as e:
                    raise ProviderError(f"{sl.display_name}: {e.code} {e.message}") from e
            done.append(
                f"{sl.display_name}: {len(ours)} → 1 {self.tag}-Regel auf {ip}, "
                f"{len(others)} andere Regeln unverändert"
            )
        return done

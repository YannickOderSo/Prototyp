# Asterisk für den KI-Telefonassistenten (ADR-010). Nur gebaut, wenn das Profil „telefon“ läuft.
# Ubuntu 24.04 (Asterisk 20 LTS aus „universe“, mit app_audiosocket und func_curl). Debian 13 enthält kein Asterisk.
# Hinweis: Pakete aus „universe“ bekommen Sicherheitsupdates nur über die Community bzw. Ubuntu Pro (Offene-Fragen.md).
FROM ubuntu:24.04

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        asterisk asterisk-modules ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    # Beispielkonfigurationen entfernen, die Dienste nach außen öffnen würden (wir nutzen nur PJSIP mit TLS)
    && rm -f /etc/asterisk/sip.conf /etc/asterisk/iax.conf /etc/asterisk/manager.conf /etc/asterisk/ari.conf \
        /etc/asterisk/http.conf \
    && install -d -o asterisk -g asterisk /var/run/asterisk

# Eigene Konfiguration (Trunk-Zugang, Dialplan, TLS-Schlüssel, Ansage) kommt vom Host, nie aus dem Repository:
#   /srv/cockpit/asterisk/{pjsip.conf,extensions.conf,rtp.conf,keys/,sounds/}
COPY modules.conf /etc/asterisk/modules.conf

USER asterisk
HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD asterisk -rx "core show uptime" >/dev/null || exit 1
ENTRYPOINT ["asterisk", "-f", "-vvv"]

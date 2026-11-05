# Sicherung: pg_dump (passend zu Postgres 16) und restic (>= 0.17 für --stdin-from-command).
FROM postgres:16-alpine

RUN apk add --no-cache bash coreutils restic openssh-client jq curl ca-certificates \
    && restic version

COPY sicherung.sh restore_probe.sh wiederherstellen.sh /usr/local/bin/
RUN chmod 0755 /usr/local/bin/sicherung.sh /usr/local/bin/restore_probe.sh /usr/local/bin/wiederherstellen.sh

ENTRYPOINT []
CMD ["sicherung.sh"]

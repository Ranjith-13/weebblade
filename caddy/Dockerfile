FROM caddy:2-alpine

# Baked in rather than bind-mounted: a bind-mounted single file ties the mount to
# the file's inode at container-start, and this project's deploy process (tar
# extraction over ssh) replaces that inode on every deploy - the running container
# silently kept serving a stale config until an explicit restart, found live when
# a Caddyfile change didn't take effect after a normal `docker compose up -d`.
# Baking it into the image means every deploy's --build step picks up the current
# file automatically, same as the airflow/backend images already do for their code.
COPY Caddyfile /etc/caddy/Caddyfile

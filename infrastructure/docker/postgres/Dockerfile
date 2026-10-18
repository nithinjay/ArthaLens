# Postgres with the role-creation init script baked in (no host bind mount needed).
FROM postgres:17.9-alpine
COPY --chmod=0755 01-create-roles.sh /docker-entrypoint-initdb.d/01-create-roles.sh

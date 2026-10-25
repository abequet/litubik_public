# LitUbik hosted image: Node builds the frontend, Python serves everything.
# Build:  docker build -t litubik .
# Run:    see docker-compose.yml (volume on /data + LITUBIK_SECRET_KEY)

FROM node:24-slim AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /srv/backend
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
# pip installs the playwright *package*; the browser is a separate download, and
# python:3.12-slim ships none of Chrome's shared libraries. Without this the
# institutional (EZProxy/CAS) and bot-protected OA tiers fail at launch on every
# retrieval. Costs ~400 MB in the image.
RUN python -m playwright install --with-deps chromium
COPY backend/ ./
# the optional local extension never ships in an image: .dockerignore keeps it
# out of the build context, and should that rule ever drift, the build fails
# here instead of publishing it
RUN test ! -e app/services/fulltext/private     || (echo "app/services/fulltext/private must not be in the image" >&2 && exit 1)
COPY --from=frontend /build/dist /srv/frontend/dist
COPY LICENSE NOTICE THIRD_PARTY_LICENSES.md /srv/
# help/FAQ markdown lives outside backend/ — help_dir() resolves to /srv/docs/help
COPY docs/help /srv/docs/help

ENV LITUBIK_DATA_DIR=/data
# behind the platform's proxy (Railway, a reverse proxy…), trust the address
# and scheme it forwards — but only from a proxy on a private network. Never
# "*": uvicorn would then take the LEFTMOST X-Forwarded-For entry, which the
# client writes itself, and anyone could pick a new address per request to
# dodge the sign-in throttle and the guest-session limits. With private ranges
# only, uvicorn walks the header from the right and stops at the address the
# proxy itself appended.
ENV FORWARDED_ALLOW_IPS=127.0.0.1,::1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,100.64.0.0/10,fc00::/7
EXPOSE 8000
# migrations then server — the compose healthcheck probes /api/health
CMD ["sh", "-c", "python -m alembic upgrade head && \
     python -m uvicorn app.main:app --host 0.0.0.0 --port 8000"]

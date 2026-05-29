# Alpine (musl) image for the ps5rmtctl network control server.
#
# Build notes:
#  - Python 3.9: netifaces 0.11.0 does NOT compile on the C API of 3.11+.
#  - cryptography & aiohttp ship musllinux wheels, so no Rust/long compiles.
#  - netifaces (a hard pyremoteplay dep) has NO musl wheel, so it is compiled
#    from source in the build stage (gcc + headers); the runtime stage stays slim.
#  - Alpine's gcc 14 makes -Wint-conversion fatal, which breaks netifaces'
#    gateways() on musl; CFLAGS below demotes it (we never call gateways()).
#  - Lower friction alternative if you don't need Alpine: python:3.9-slim
#    (Debian) — older gcc compiles netifaces with no CFLAGS workaround.

# ---- build stage -----------------------------------------------------------
FROM python:3.9-alpine AS build
RUN apk add --no-cache gcc musl-dev libffi-dev
WORKDIR /app
COPY pyproject.toml ./
COPY ps5rmtctl ./ps5rmtctl
# Alpine's gcc 14 turns -Wint-conversion into a hard error, which breaks
# netifaces' glibc-shaped gateways() on musl. We don't use gateways(), so demote
# it back to a warning and let the (used) interface-enumeration code build.
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --no-cache-dir --upgrade pip wheel \
 && CFLAGS="-Wno-int-conversion" /opt/venv/bin/pip install --no-cache-dir .

# ---- runtime stage ---------------------------------------------------------
FROM python:3.9-alpine AS runtime
COPY --from=build /opt/venv /opt/venv
# HOME=/data so pyremoteplay's profile (~/.pyremoteplay/.profile.json) and our
# config (~/.ps5rmtctl) both land in the mounted volume.
ENV PATH=/opt/venv/bin:$PATH \
    HOME=/data \
    PYTHONUNBUFFERED=1 \
    PS5RMTCTL_HOME=/data/.ps5rmtctl
RUN adduser -D -h /data app && mkdir -p /data && chown -R app:app /data
USER app
VOLUME /data
EXPOSE 8645

# Configure via env: PS5RMTCTL_HOST, PS5RMTCTL_USER, PS5RMTCTL_TOKEN.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD wget -qO- "http://127.0.0.1:8645/api/buttons" >/dev/null 2>&1 || exit 1

ENTRYPOINT ["python", "-m", "ps5rmtctl"]
CMD ["serve", "--bind", "0.0.0.0", "--port", "8645"]

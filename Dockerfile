# U1 Web Slicer + the Snapmaker Orca CLI (official Linux AppImage, x86_64 only) in one image.
# Data (session, history, jobs, presets) lives in /data; models in /data/models unless U1WEB_MODELS says otherwise.
FROM ubuntu:24.04

ARG ORCA_VERSION=2.4.1
ARG VERSION=dev

# Orca links its GUI libraries even when it only slices on the command line (no display needed).
RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 python3-pil curl ca-certificates \
      libgtk-3-0t64 libwebkit2gtk-4.1-0 libglu1-mesa libgl1 libegl1 libosmesa6 libgl1-mesa-dri libglx-mesa0 \
      libgstreamer1.0-0 libgstreamer-plugins-base1.0-0 libsecret-1-0 \
 && curl -fsSL -o /tmp/orca.AppImage \
      "https://github.com/Snapmaker/OrcaSlicer/releases/download/v${ORCA_VERSION}/Snapmaker_Orca_Linux_AppImage_Ubuntu2404_V${ORCA_VERSION}.AppImage" \
 && chmod +x /tmp/orca.AppImage && cd /opt && /tmp/orca.AppImage --appimage-extract >/dev/null \
 && mv squashfs-root orca && chmod -R a+rX orca && rm /tmp/orca.AppImage \
 && apt-get purge -y curl && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --chown=root:root . /app

ENV U1WEB_VERSION=${VERSION} U1WEB_ORCA_VERSION=${ORCA_VERSION} \
    U1WEB_DATA=/data U1WEB_MODELS=/data/models U1WEB_ORCA_BIN=/opt/orca/bin/snapmaker-orca U1WEB_PORT=3060 \
    PYTHONUNBUFFERED=1

RUN mkdir -p /data && chown 1000:1000 /data
USER 1000:1000
VOLUME /data
EXPOSE 3060
HEALTHCHECK --interval=30s --timeout=5s CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:3060/api/slice_progress', timeout=4)"
CMD ["python3", "server.py"]

LABEL org.opencontainers.image.source="https://github.com/chylek/u1-web-slicer" \
      org.opencontainers.image.description="Phone-first web slicer for the Snapmaker U1 (bundles Snapmaker Orca, AGPL-3.0: https://github.com/Snapmaker/OrcaSlicer)" \
      org.opencontainers.image.licenses="AGPL-3.0-or-later"

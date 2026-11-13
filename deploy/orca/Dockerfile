# Snapmaker Orca in a browser (KasmVNC). Build: docker compose build
FROM ghcr.io/linuxserver/baseimage-kasmvnc:ubuntunoble
ARG V=2.4.1
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
      libwebkit2gtk-4.1-0 libgtk-3-0 libglu1-mesa libgl1 libegl1 libosmesa6 libgl1-mesa-dri mesa-libgallium libglx-mesa0 libfuse2t64 \
      gstreamer1.0-plugins-base gstreamer1.0-plugins-good gstreamer1.0-plugins-bad gstreamer1.0-libav gstreamer1.0-x libsecret-1-0 \
 && curl -fsSL -o /tmp/o.AppImage https://github.com/Snapmaker/OrcaSlicer/releases/download/v$V/Snapmaker_Orca_Linux_AppImage_Ubuntu2404_V$V.AppImage \
 && chmod +x /tmp/o.AppImage && cd /opt && /tmp/o.AppImage --appimage-extract >/dev/null \
 && chmod -R a+rX squashfs-root && mv squashfs-root orca && rm /tmp/o.AppImage && rm -rf /var/lib/apt/lists/*
RUN printf '#!/bin/sh\ncd /config\nwhile true; do /opt/orca/bin/snapmaker-orca; sleep 2; done\n' > /defaults/autostart && chmod +x /defaults/autostart
ENV TITLE="Snapmaker Orca" LIBGL_ALWAYS_SOFTWARE=1 GALLIUM_DRIVER=llvmpipe

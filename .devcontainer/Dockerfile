FROM mcr.microsoft.com/devcontainers/base:ubuntu-24.04

ARG KIND_VERSION=v0.31.0
ARG TOXIPROXY_VERSION=2.9.0

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl make \
    && arch="$(dpkg --print-architecture)" \
    && case "$arch" in \
        amd64) kind_arch=amd64; toxiproxy_arch=amd64 ;; \
        arm64) kind_arch=arm64; toxiproxy_arch=arm64 ;; \
        *) echo "Unsupported architecture: $arch" >&2; exit 1 ;; \
       esac \
    && curl -fsSL -o /usr/local/bin/kind "https://kind.sigs.k8s.io/dl/${KIND_VERSION}/kind-linux-${kind_arch}" \
    && curl -fsSL -o /usr/local/bin/toxiproxy-cli "https://github.com/Shopify/toxiproxy/releases/download/v${TOXIPROXY_VERSION}/toxiproxy-cli-linux-${toxiproxy_arch}" \
    && chmod +x /usr/local/bin/kind /usr/local/bin/toxiproxy-cli \
    && rm -rf /var/lib/apt/lists/*

ARG BUILD_FROM=ghcr.io/home-assistant/base:latest
FROM ${BUILD_FROM}

LABEL \
  io.hass.version="2.8.46" \
  io.hass.type="app" \
  io.hass.arch="aarch64|amd64|armv7"

RUN apk add --no-cache \
      bash \
      ca-certificates \
      curl \
      python3 \
      py3-pip \
      py3-setuptools \
      py3-wheel \
      tzdata \
      && python3 -m venv /opt/plumbox/.venv

COPY requirements.txt /tmp/requirements.txt
RUN /opt/plumbox/.venv/bin/pip install --no-cache-dir --upgrade pip wheel \
    && /opt/plumbox/.venv/bin/pip install --no-cache-dir -r /tmp/requirements.txt

WORKDIR /opt/plumbox
COPY app ./app
COPY licenses ./licenses
COPY addon_init.py ./addon_init.py
COPY run.sh /run.sh
RUN chmod a+x /run.sh

ENV PYTHONPATH=/opt/plumbox \
    PLUMBOX_CONFIG=/data/config.yaml \
    PLUMBOX_USERS=/data/users.yaml

CMD [ "/run.sh" ]



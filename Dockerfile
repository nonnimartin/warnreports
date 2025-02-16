FROM docker.io/python:3.12-alpine AS base
VOLUME /build
VOLUME /srv/artifacts
WORKDIR /code
ENV BUILD_DIR=/build
ENV ARTIFACTS_DIR=/srv/artifacts
ENV BOOTSTRAP_DIR=/usr/local/src/bootstrap
ENV FRONTEND_DIST=/srv/dist
ENV PYTHONSTARTUP=/code/scripts/startup.py
ENV UVICORN_HOST=0.0.0.0
ENV UVICORN_SERVER_HEADER=false
RUN apk --no-cache -q add bash curl mailcap g++ libc-dev linux-headers libffi-dev &&\
    ln -s /code/bin/wrep-docker /usr/local/bin/wrep
COPY ./scripts ./scripts
RUN ./scripts/download-warn-scraper.sh &&\
    ./scripts/download-bootstrap.sh
COPY ./requirements.txt ./
RUN pip install -qqq --no-cache-dir --no-input -r requirements.txt
CMD ["python", "-m", "wrep.main"]
COPY . .
RUN wrep frontend build

FROM base AS selenium
ENV SELENIUM_ENABLED=true
RUN apk --no-cache -q add chromium-chromedriver &&\
    pip install -qqq --no-cache-dir --no-input selenium

FROM base

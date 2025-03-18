FROM docker.io/node:alpine AS vitebuild
WORKDIR /workdir
COPY ./vite /workdir
RUN npm install && npm run build

# -----------------

FROM docker.io/nginx:stable-alpine AS vite
COPY ./vite/vite-nginx.conf /etc/nginx/conf.d/
COPY --from=vitebuild /workdir/build/client /srv/vite

# -----------------

FROM docker.io/python:3.12-alpine AS base
WORKDIR /code
ENV BUILD_DIR=/build
ENV ARTIFACTS_DIR=/srv/artifacts
ENV BOOTSTRAP_DIR=/usr/local/src/bootstrap
ENV PYTHONSTARTUP=/code/scripts/startup.py
ENV UVICORN_HOST=0.0.0.0
ENV UVICORN_SERVER_HEADER=false
RUN apk --no-cache -q add bash curl mailcap g++ linux-headers &&\
    pip install -qqq --no-cache-dir --no-input libsass &&\
    apk -q del g++ &&\
    ln -s /code/bin/wrep-docker /usr/local/bin/wrep
COPY ./scripts ./scripts
RUN ./scripts/download-warn-scraper.sh &&\
    ./scripts/download-bootstrap.sh
COPY ./requirements*.txt ./
RUN pip install -qqq --no-cache-dir --no-input -r requirements.txt
CMD ["python", "-m", "wrep.main"]

# -----------------

FROM base AS prodbase
ENV FRONTEND_DIST=/srv/dist
COPY . .
RUN apk --no-cache -q add g++ libc-dev libffi-dev &&\
    wrep frontend build &&\
    apk -q del g++ libc-dev libffi-dev

FROM prodbase AS server

FROM prodbase AS etl
RUN pip install -qqq --no-cache-dir --no-input -r requirements-etl.txt

FROM etl AS etl-selenium
RUN apk --no-cache -q add chromium-chromedriver &&\
    pip install -qqq --no-cache-dir --no-input -r requirements-selenium.txt
ENV SELENIUM_ENABLED=true

# -----------------

FROM base AS devbase
RUN apk --no-cache -q add g++ libc-dev libffi-dev &&\
    pip install -qqq --no-cache-dir --no-input -r requirements-etl.txt
ENV UVICORN_RELOAD=true
ENV FRONTEND_AUTO_BUILD=true

FROM devbase AS etl-dev

FROM devbase AS etl-selenium-dev
RUN apk --no-cache -q add chromium-chromedriver &&\
    pip install -qqq --no-cache-dir --no-input -r requirements-selenium.txt
ENV SELENIUM_ENABLED=true

FROM etl-selenium-dev AS selenium
FROM etl-dev AS dev
FROM dev

FROM python:3.12-alpine
VOLUME /build
VOLUME /srv/artifacts
WORKDIR /code
CMD python -m wrep.main
ENV BUILD_DIR=/build
ENV ARTIFACTS_DIR=/srv/artifacts
ENV UVICORN_HOST=0.0.0.0
RUN apk --no-cache -q add bash curl &&\
    ln -s /code/bin/wrep-docker /usr/local/bin/wrep
COPY ./scripts ./scripts
RUN ./scripts/install-warn-scraper.sh
COPY ./requirements.txt ./
RUN apk --no-cache -q add --virtual .build-deps gcc libc-dev linux-headers libffi-dev &&\
    pip install -qqq -r requirements.txt &&\
    apk --no-cache -q del .build-deps
COPY . .
# warnreports

## Install

```sh
docker compose build
docker compose up -d
```

App runs on port 8000, e.g. http://127.0.0.1:8000/

Mongo Express is available at http://127.0.0.1:8081/

Pgadmin is available at http://127.0.0.1:8082/ (blank password)

For available command run:

```sh
docker compose exec app wrep -h
```

## Selenium

To enable selenium, set the following in `.env`:

```sh
APP_IMAGE_TARGET=etl-selenium-dev
```

Then rebuild the image.

## React Development

It is best to run the react dev server directly on your machine, not in a container.
Make sure you have `npm` installed, then install the dependencies:

```sh
cd vite
npm install
```

Then start the dev server:

```sh
npm run dev
```

The react dev server will be available at http://127.0.0.1:5173/

### Frontend only development

By default, the react dev server proxies backend requests to the API container running at
http://127.0.0.1:8000 (see `vite.config.ts`).

Alternatively, you can set the environment variable `API_PROXY_TARGET` to the
production server:

```sh
API_PROXY_TARGET=https://warnreports.org npm run dev
```

This allow you to develop the frontend only, without running any of the containers.
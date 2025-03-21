# warnreports

## Install

### Using docker compose

The compose config includes MongoDB.

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

## React Development (WIP)

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

### Frontend only

By default, the react dev server proxies `/api/v0` to the API container running at
http://127.0.0.1:8000 (see `vite.config.ts`).

Alternatively, you can set the environment variable `API_PROXY_TARGET` to the
production server:

```sh
API_PROXY_TARGET=https://warnreports.org npm run dev
```

This allow you to develop the frontend only, without running any of the containers.
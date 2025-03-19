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

Example commands:

```sh
# Run pipeline
docker compose exec app wrep pipeline all

# Run migrations
docker compose exec app wrep migrations migrate

# Generate migration
docker compose exec app wrep migrations auto
```

## React Development (WIP)

It is best to run the react dev server directly on your machine, not in a container.
Make sure you have `npm` installed, then install the dependencies:

```sh
cd vite
npm install
```

Then start the dev server with `npm run dev`
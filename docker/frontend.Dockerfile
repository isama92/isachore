# syntax=docker/dockerfile:1
# Pinned to 24 (LTS). Node 26 ships a native experimental `localStorage`
# global that shadows jsdom's, so vitest collects 0 tests from every file
# while lint, tsc and the vite build all still pass. Recheck when vitest or
# jsdom handles it; keep .github/workflows/ci.yml's node-version in step.
FROM node:24-alpine AS base
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

# dev: vite dev server; source code arrives via the compose bind mount,
# node_modules is shadowed by a named volume so the image copy wins.
FROM base AS dev
COPY . .
EXPOSE 5173
CMD ["npm", "run", "dev"]

FROM base AS build
COPY . .
RUN npm run build

# prod: nginx serves the SPA and reverse-proxies /api/ to the backend.
# The confs come from the `nginxconf` named build context (docker/nginx), not
# from the build context: they configure the image, not the app, so they live
# beside this Dockerfile. Keeping the build context at ./frontend is what lets
# every other COPY here stay unchanged.
FROM nginx:stable-alpine AS prod
# http-context variables every mode needs, and the `00-` prefix keeps them ahead of
# default.conf in nginx's alphabetical include of conf.d/*.conf. Baked deliberately: the tls
# mode bind-mounts its own file over default.conf, so a variable defined there would be
# absent for any operator still holding an older copy - and an undefined variable is a
# refusal to start, i.e. the whole site down. See nginx-maps.conf.
COPY --from=nginxconf nginx-maps.conf /etc/nginx/conf.d/00-isachore-maps.conf
COPY --from=nginxconf nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=nginxconf nginx-common.conf /etc/nginx/snippets/isachore-common.conf
# The shared body of the two API-reference locations (/docs and /openapi.json), which
# nginx-common.conf includes from each of them. A separate snippet rather than two copies,
# and separate from isachore-common.conf because it is location-context (that one is
# server-context).
COPY --from=nginxconf nginx-docs.conf /etc/nginx/snippets/isachore-docs.conf
# Reference copy, inert at runtime: nginx only auto-includes conf.d/*.conf, and
# the TLS mode bind-mounts its own conf over conf.d/default.conf anyway. Baked
# so a TLS operator can extract the conf matching the image they pulled rather
# than guessing at main's current version (see README). Keep the path in step
# with the bind mount in compose.prod.tls.yml.
COPY --from=nginxconf nginx.tls.conf /etc/nginx/modes/tls.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80 443

# syntax=docker/dockerfile:1
FROM node:26-alpine AS base
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
COPY --from=nginxconf nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=nginxconf nginx-common.conf /etc/nginx/snippets/isachore-common.conf
# Reference copy, inert at runtime: nginx only auto-includes conf.d/*.conf, and
# the TLS mode bind-mounts its own conf over conf.d/default.conf anyway. Baked
# so a TLS operator can extract the conf matching the image they pulled rather
# than guessing at main's current version (see README). Keep the path in step
# with the bind mount in compose.prod.tls.yml.
COPY --from=nginxconf nginx.tls.conf /etc/nginx/modes/tls.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80 443

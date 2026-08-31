FROM node:26-trixie-slim AS builder

WORKDIR /app

COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci

COPY . .
RUN npm run build && npm prune --omit=dev


FROM node:26-trixie-slim

RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --create-home app

WORKDIR /app
COPY --from=builder --chown=app:app /app/build ./build
COPY --from=builder --chown=app:app /app/node_modules ./node_modules
COPY --from=builder --chown=app:app /app/package.json ./

# Loopback would be wrong here: the process is already alone in a container, and
# compose is what publishes it to the host's loopback and no further.
ENV NODE_ENV=production \
    HOST=0.0.0.0 \
    PORT=3000

USER 10001
EXPOSE 3000

CMD ["node", "build"]

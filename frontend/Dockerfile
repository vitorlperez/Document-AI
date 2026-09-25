FROM node:22-bookworm-slim

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .

EXPOSE 3000
# Run Vinext as PID 1 so Docker forwards SIGTERM directly to the dev server
# and its .vinext/dev/lock.json is released on restart.
CMD ["node", "scripts/run-framework.mjs", "dev", "--hostname", "0.0.0.0", "--port", "3000"]

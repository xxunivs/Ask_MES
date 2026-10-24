FROM node:22-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# 브라우저에서 부르는 주소라 빌드할 때 코드에 박힘
ARG NEXT_PUBLIC_API_URL=https://ask-mes-api-184800931191.us-central1.run.app
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
RUN npm run build

FROM node:22-slim
WORKDIR /app
ENV NODE_ENV=production
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
ENV PORT=8080
CMD ["node", "server.js"]

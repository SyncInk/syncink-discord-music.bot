FROM node:20-bookworm-slim

WORKDIR /app

RUN apt-get update \
  && apt-get install -y --no-install-recommends ffmpeg ca-certificates python3 python-is-python3 \
  && rm -rf /var/lib/apt/lists/*

COPY package.json package-lock.json ./
ENV YOUTUBE_DL_SKIP_PYTHON_CHECK=1
ENV YTDL_NO_UPDATE=1
RUN npm ci --omit=dev --no-audit --no-fund

COPY . .

ENV NODE_ENV=production
ENV FFMPEG_PATH=/usr/bin/ffmpeg
EXPOSE 3000

CMD ["npm", "run", "start:railway"]

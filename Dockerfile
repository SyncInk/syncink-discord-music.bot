FROM node:18-bullseye-slim

RUN apt-get update && apt-get install -y \
    ffmpeg \
    libopus-dev \
    python3 \
    python3-pip \
    make \
    g++ \
    && pip3 install -U yt-dlp \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY package*.json ./
RUN npm install

COPY . .

CMD ["npm", "start"]

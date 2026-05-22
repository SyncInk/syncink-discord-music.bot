FROM node:18-bullseye-slim

# Install the exact audio drivers required for Discord
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libopus-dev \
    python3 \
    make \
    g++ \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy dependency files and install
COPY package*.json ./
RUN npm install

# Copy the rest of the bot code
COPY . .

# Start the bot
CMD ["npm", "start"]

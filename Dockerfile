FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

RUN echo "Node: $(node --version)" && echo "npm: $(npm --version)"

RUN npm install -g @googleworkspace/cli \
    && echo "gws at: $(which gws)"

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

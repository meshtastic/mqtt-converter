# Docker Deployment Guide

Complete guide for deploying the Meshtastic MQTT Converter with Docker.

## Table of Contents

- [Quick Start](#quick-start)
- [Standalone Container](#standalone-container)
- [Docker Compose with Mosquitto](#docker-compose-with-mosquitto)
- [Configuration](#configuration)
- [Advanced Usage](#advanced-usage)

## Quick Start

### Option 1: Standalone Container

```bash
docker run -d \
  -e REGION=EU_868 \
  --name meshtastic-converter \
  meshtastic-converter
```

### Option 2: With Local Mosquitto Broker

```bash
docker-compose up -d
```

## Standalone Container

### Build the Image

```bash
docker build -t meshtastic-converter .
```

### Run Basic Container

```bash
docker run -d \
  -e BROKER=mqtt.meshtastic.org \
  -e REGION=EU_868 \
  --name meshtastic-converter \
  --restart unless-stopped \
  meshtastic-converter
```

### Run with Encryption

```bash
docker run -d \
  -e BROKER=mqtt.meshtastic.org \
  -e REGION=EU_868 \
  -e PSK=0x1a1a1a1a2b2b2b2b1a1a1a1a2b2b2b2b \
  --name meshtastic-converter \
  --restart unless-stopped \
  meshtastic-converter
```

### Run with Authentication

```bash
docker run -d \
  -e BROKER=mqtt.example.com \
  -e USERNAME=myuser \
  -e PASSWORD=mypass \
  -e REGION=EU_868 \
  --name meshtastic-converter \
  --restart unless-stopped \
  meshtastic-converter
```

### Run with Debug Mode

```bash
docker run -d \
  -e REGION=EU_868 \
  -e DEBUG=1 \
  --name meshtastic-converter \
  meshtastic-converter
```

## Docker Compose with Mosquitto

### Directory Structure

Create the following structure:

```
.
├── docker-compose.yml
├── mosquitto.conf
├── Dockerfile
├── meshtastic_protobuf_to_json.py
├── requirements.txt
└── mosquitto/
    ├── config/
    ├── data/
    └── log/
```

### Setup Steps

**1. Create directories:**
```bash
mkdir -p mosquitto/config mosquitto/data mosquitto/log
```

**2. Copy mosquitto configuration:**
```bash
cp mosquitto.conf mosquitto/config/mosquitto.conf
```

**3. Create environment file (optional):**
```bash
cp .env.example .env
nano .env
```

**4. Start services:**
```bash
docker-compose up -d
```

### Service Management

**Start services:**
```bash
docker-compose up -d
```

**Stop services:**
```bash
docker-compose down
```

**Restart services:**
```bash
docker-compose restart
```

**View logs:**
```bash
docker-compose logs -f
docker-compose logs -f converter
docker-compose logs -f mosquitto
```

**Rebuild after code changes:**
```bash
docker-compose down
docker-compose build --no-cache
docker-compose up -d
```

### Accessing Services

**MQTT (TCP):**
- Host: `localhost`
- Port: `1883`

**MQTT (WebSocket):**
- Host: `localhost`
- Port: `9001`

**Test connection:**
```bash
mosquitto_sub -h localhost -t "msh/#" -v
```

## Configuration

### Environment Variables

Create a `.env` file:

```env
BROKER=mosquitto
PORT=1883
REGION=EU_868
ROOT_TOPIC=msh
USERNAME=
PASSWORD=
PSK=
DEBUG=
```

### Mosquitto Configuration

Edit `mosquitto/config/mosquitto.conf`:

**Basic (allow anonymous):**
```conf
listener 1883
allow_anonymous true
persistence true
persistence_location /mosquitto/data/
```

**With authentication:**
```conf
listener 1883
allow_anonymous false
password_file /mosquitto/config/passwd
persistence true
persistence_location /mosquitto/data/
```

**Create password file:**
```bash
docker exec -it meshtastic-mosquitto mosquitto_passwd -c /mosquitto/config/passwd myuser
docker-compose restart mosquitto
```

### SSL/TLS Configuration

Add to `mosquitto.conf`:

```conf
listener 8883
cafile /mosquitto/config/ca.crt
certfile /mosquitto/config/server.crt
keyfile /mosquitto/config/server.key
require_certificate false
```

Mount certificates in `docker-compose.yml`:

```yaml
mosquitto:
  volumes:
    - ./certs/ca.crt:/mosquitto/config/ca.crt
    - ./certs/server.crt:/mosquitto/config/server.crt
    - ./certs/server.key:/mosquitto/config/server.key
```

## Advanced Usage

### Multiple Regions

Run separate converters for different regions:

```yaml
services:
  converter-eu:
    build: .
    environment:
      - BROKER=mosquitto
      - REGION=EU_868
    depends_on:
      - mosquitto

  converter-us:
    build: .
    environment:
      - BROKER=mosquitto
      - REGION=US
    depends_on:
      - mosquitto
```

### External Mosquitto

Connect to external MQTT broker:

```yaml
services:
  converter:
    build: .
    environment:
      - BROKER=mqtt.example.com
      - PORT=1883
      - USERNAME=${MQTT_USER}
      - PASSWORD=${MQTT_PASS}
      - REGION=EU_868
```

### Resource Limits

Add resource constraints:

```yaml
services:
  converter:
    build: .
    deploy:
      resources:
        limits:
          cpus: '0.5'
          memory: 256M
        reservations:
          cpus: '0.25'
          memory: 128M
```

### Health Checks

Add health check to mosquitto:

```yaml
mosquitto:
  image: eclipse-mosquitto:2.0.23-openssl
  healthcheck:
    test: ["CMD", "mosquitto_sub", "-t", "$$SYS/#", "-C", "1", "-i", "healthcheck", "-W", "3"]
    interval: 30s
    timeout: 10s
    retries: 3
```

### Logging Configuration

Configure logging in docker-compose:

```yaml
services:
  converter:
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
```

### Persistent Storage

Ensure mosquitto data persists:

```yaml
volumes:
  mosquitto-data:
    driver: local

services:
  mosquitto:
    volumes:
      - mosquitto-data:/mosquitto/data
```

## Troubleshooting

### Container Won't Start

**Check logs:**
```bash
docker logs meshtastic-converter
docker-compose logs converter
```

**Verify environment:**
```bash
docker exec meshtastic-converter env
```

### Can't Connect to Mosquitto

**Test mosquitto:**
```bash
docker exec meshtastic-mosquitto mosquitto_sub -t test -C 1
```

**Check network:**
```bash
docker network inspect meshtastic-net
```

### Permission Issues

**Fix mosquitto permissions:**
```bash
sudo chown -R 1883:1883 mosquitto/data mosquitto/log
```

### Rebuild Everything

```bash
docker-compose down -v
docker-compose build --no-cache
docker-compose up -d
```

## Monitoring

### Resource Usage

```bash
docker stats meshtastic-converter meshtastic-mosquitto
```

### Message Flow

```bash
docker exec meshtastic-mosquitto mosquitto_sub -t "msh/#" -v
```

### Logs

```bash
# Real-time logs
docker-compose logs -f --tail=100

# Save logs
docker-compose logs > logs.txt
```

## Production Deployment

### Best Practices

1. **Use environment files:**
   - Don't commit `.env` to git
   - Use secrets management for production

2. **Enable authentication:**
   - Set up Mosquitto passwords
   - Use SSL/TLS certificates

3. **Configure logging:**
   - Set up log rotation
   - Ship logs to central system

4. **Set resource limits:**
   - Prevent resource exhaustion
   - Monitor usage

5. **Use health checks:**
   - Auto-restart failed containers
   - Alert on failures

6. **Backup data:**
   - Backup mosquitto data directory
   - Store PSKs securely

### Example Production Stack

```yaml
version: '3.8'

services:
  mosquitto:
    image: eclipse-mosquitto:2.0.23-openssl
    container_name: meshtastic-mosquitto
    ports:
      - "1883:1883"
      - "8883:8883"
    volumes:
      - ./mosquitto/config:/mosquitto/config:ro
      - mosquitto-data:/mosquitto/data
      - mosquitto-log:/mosquitto/log
    restart: always
    healthcheck:
      test: ["CMD", "mosquitto_sub", "-t", "$$SYS/#", "-C", "1"]
      interval: 30s
      timeout: 10s
      retries: 3
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "5"

  converter:
    build: .
    container_name: meshtastic-converter
    env_file: .env
    depends_on:
      mosquitto:
        condition: service_healthy
    restart: always
    deploy:
      resources:
        limits:
          cpus: '0.5'
          memory: 256M
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "5"

volumes:
  mosquitto-data:
    driver: local
  mosquitto-log:
    driver: local
```

## Updating

### Update Container

```bash
# Pull latest code
git pull

# Rebuild and restart
docker-compose down
docker-compose build --no-cache
docker-compose up -d
```

### Update Base Images

```bash
docker-compose pull
docker-compose up -d
```

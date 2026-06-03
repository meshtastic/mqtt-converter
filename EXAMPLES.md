# Examples & Usage Guide

Practical reference for running the converter, sending messages to the mesh, and reading its JSON output.

## Running

### Standalone Python

```bash
pip install -r requirements.txt
python3 meshtastic_protobuf_to_json.py --region EU_868
```

### Command-line options

```
--broker      MQTT broker address (default: mqtt.meshtastic.org)
--port        MQTT port (default: 1883)
--username    MQTT username (optional)
--password    MQTT password (optional)
--region      Meshtastic region (default: EU_868)
--root-topic  Root topic (default: msh)
--psk         Channel PSK for encryption (optional)
--debug       Enable debug logging
```

### Docker

```bash
docker build -t meshtastic-converter .

docker run -d \
  -e BROKER=mqtt.meshtastic.org \
  -e PORT=1883 \
  -e REGION=EU_868 \
  -e PSK=0x1a1a1a1a2b2b2b2b1a1a1a1a2b2b2b2b \
  --name meshtastic-converter \
  --restart unless-stopped \
  meshtastic-converter
```

### Docker Compose (with Mosquitto)

`docker-compose.yml` brings up the converter alongside a Mosquitto broker.

```bash
# One-time setup
mkdir -p mosquitto/config mosquitto/data mosquitto/log
cp mosquitto.conf mosquitto/config/mosquitto.conf
cp .env.example .env   # then edit as needed

# Start / logs / stop
docker-compose up -d
docker-compose logs -f converter
docker-compose down
```

MQTT is exposed on `localhost:1883` and WebSocket on `localhost:9001`.

### Environment variables (Docker)

| Variable | Description | Default |
|----------|-------------|---------|
| `BROKER` | MQTT broker address | `mqtt.meshtastic.org` |
| `PORT` | MQTT port | `1883` |
| `REGION` | Meshtastic region | `EU_868` |
| `ROOT_TOPIC` | MQTT root topic | `msh` |
| `USERNAME` | MQTT username | (none) |
| `PASSWORD` | MQTT password | (none) |
| `PSK` | Channel encryption key | (none) |
| `DEBUG` | Enable debug mode | (none) |

## Encryption

A PSK is required to decrypt uplink packets and to encrypt downlink packets. Without one, only unencrypted packets are processed.

| Format | Example |
|--------|---------|
| Hex (16 bytes = AES-128, 32 bytes = AES-256) | `--psk 0x1a1a1a1a2b2b2b2b1a1a1a1a2b2b2b2b` |
| Base64 | `--psk base64:puavdd7vtYJh8NUVWgxbsoG2u9Sdqc54YvMLs+KNcMA=` |
| Default key (testing only, insecure) | `--psk default` |

Get your channel PSK from the Meshtastic CLI (`meshtastic --info`, see the "Channels" section) or decode it from a channel-share URL.

## Sending messages to the mesh (downlink)

Publish a JSON message to a `…/2/json/CHANNEL/` topic. The converter acts on messages whose `type` starts with `send`.

Envelope fields:

| Field | Required | Notes |
|-------|----------|-------|
| `from` | yes | Your node ID (integer) |
| `type` | yes | `sendtext` or `sendposition` |
| `payload` | yes | String (text) or object (position) |
| `to` | no | Recipient node ID; omit for broadcast (`0xFFFFFFFF`) |
| `channel` | no | Channel index |
| `hopLimit` | no | Hop limit (`hop_limit` also accepted) |
| `id` | no | Packet ID |

### Text message (broadcast)

```bash
mosquitto_pub -h mqtt.meshtastic.org -t "msh/EU_868/2/json/LongFast/" -m '{
  "from": 123456789,
  "type": "sendtext",
  "payload": "Hello Mesh!"
}'
```

### Text message (direct)

```bash
mosquitto_pub -h mqtt.meshtastic.org -t "msh/EU_868/2/json/LongFast/" -m '{
  "from": 123456789,
  "to": 987654321,
  "type": "sendtext",
  "payload": "Private message"
}'
```

### Position

Decimal `latitude`/`longitude` are accepted for convenience; the firmware's native form is raw scaled integers `latitude_i`/`longitude_i` (degrees × 1e7), which take precedence if both are present.

```bash
mosquitto_pub -h mqtt.meshtastic.org -t "msh/EU_868/2/json/LongFast/" -m '{
  "from": 123456789,
  "type": "sendposition",
  "payload": {
    "latitude": 50.7753,
    "longitude": 6.0839,
    "altitude": 200
  }
}'
```

Equivalent with raw integers:

```json
{
  "from": 123456789,
  "type": "sendposition",
  "payload": { "latitude_i": 507753000, "longitude_i": 60839000, "altitude": 200 }
}
```

### With Python paho-mqtt

```python
import paho.mqtt.client as mqtt
import json

client = mqtt.Client()
client.connect("mqtt.meshtastic.org", 1883)

message = {
    "from": 123456789,
    "type": "sendtext",
    "payload": "Hello Meshtastic!",
}
client.publish("msh/EU_868/2/json/LongFast/", json.dumps(message))
```

Notes:
- Replace `123456789` with your node ID and `LongFast` with a channel configured on your node.
- The channel must have downlink enabled on the gateway node that forwards to the radio.

## Reading JSON output (uplink)

Subscribe to the JSON topic to watch converted packets:

```bash
mosquitto_sub -h mqtt.meshtastic.org -t "msh/EU_868/2/json/#" -v
```

Every message carries a common envelope plus a type-specific `payload`. Object keys are emitted in alphabetical order to match the firmware byte-for-byte.

```json
{
  "channel": 0,
  "from": 123456789,
  "hop_start": 3,
  "hops_away": 0,
  "id": 1234567890,
  "rssi": -42,
  "sender": "!075bcd15",
  "snr": 6.25,
  "timestamp": 1717430400,
  "to": 4294967295,
  "type": "position",
  "payload": { "altitude": 200, "latitude_i": 507753000, "longitude_i": 60839000 }
}
```

Supported uplink types and their `payload` shape:

| Type | Notes |
|------|-------|
| `text` | `{ "text": ... }`, or the parsed object if the message body is itself JSON |
| `position` | raw `latitude_i`/`longitude_i`, plus optional `altitude`, `time`, speed, DOP, etc. |
| `nodeinfo` | `id`, `longname`, `shortname`, `hardware`, `role` |
| `telemetry` | device, environment, air-quality, or power metrics |
| `waypoint` | `id`, `name`, `description`, `expire`, `locked_to`, raw lat/lon |
| `neighborinfo` | `node_id`, counts, and a `neighbors` array |
| `traceroute` | `route` / `route_back` (node-id strings) and SNR arrays |
| `detection` | `{ "text": ... }` |
| `paxcounter` | `wifi_count`, `ble_count`, `uptime` |
| `gpios_changed` / `gpios_read_reply` | remote-hardware GPIO values |

> Traceroute hops are rendered as `!aabbccdd` node-id strings. The firmware resolved them to node long-names via its local database; a standalone converter has no such database.

## Regions

Common values: `EU_868`, `US`, `EU_433`, `CN`, `JP`, `ANZ`, `KR`, `TW`, `RU`, `IN`.

## Troubleshooting

**Connection** — confirm broker reachability:

```bash
mosquitto_sub -h mqtt.meshtastic.org -t "msh/#" -v
```

**Encryption** — check the PSK format (hex `0x…` of 32/64 chars, or `base64:…`) and that it matches the channel on your node. Run with `--debug` to log decrypt failures.

**No downlink delivery** — a real gateway node must be subscribed to the `2/e/` topic with downlink enabled; the converter only republishes to MQTT, it does not transmit on the radio itself.

**Docker** — inspect and rebuild:

```bash
docker-compose logs -f converter
docker-compose down && docker-compose build --no-cache && docker-compose up -d
```

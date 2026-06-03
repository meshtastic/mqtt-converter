# Meshtastic MQTT Protobuf ↔ JSON Converter

Bidirectional converter between Meshtastic Protobuf and JSON formats over MQTT, with AES channel encryption.

[![Python](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-GPLv3-green.svg)](LICENSE)

It is a drop-in, off-device replacement for the JSON MQTT support that used to be built into the Meshtastic firmware: it republishes encrypted protobuf packets as readable JSON (uplink) and turns JSON commands back into protobuf packets injected into the mesh (downlink). The JSON format matches the firmware's original output field-for-field.

## Features

- **Bidirectional** — Protobuf → JSON (uplink) and JSON → Protobuf (downlink)
- **Encryption** — AES-128 / AES-256, PSK as hex, base64, or default key
- **Deployment** — standalone script, Docker, or Docker Compose with a bundled Mosquitto broker
- **Message types** — text, position, node info, telemetry (device / environment / air-quality / power), waypoint, neighbor info, traceroute, detection sensor, paxcounter, and remote-hardware (GPIO)

## How it works

| Direction | Subscribes | Publishes |
|-----------|------------|-----------|
| Uplink (Protobuf → JSON) | `msh/REGION/2/e/CHANNEL/#` | `msh/REGION/2/json/CHANNEL/USERID` |
| Downlink (JSON → Protobuf) | `msh/REGION/2/json/#` | `msh/REGION/2/e/CHANNEL/GATEWAYID` |

Uplink decrypts the packet (if a PSK is set) and converts it to JSON. Downlink picks up JSON messages whose `type` starts with `send`, builds the protobuf packet, encrypts it, and republishes it for a gateway node to forward onto the radio.

## Quick start

```bash
pip install -r requirements.txt
python3 meshtastic_protobuf_to_json.py --region EU_868
```

With encryption and a private broker:

```bash
python3 meshtastic_protobuf_to_json.py \
  --broker mqtt.example.com --username myuser --password mypass \
  --region EU_868 --psk 0x1a1a1a1a2b2b2b2b1a1a1a1a2b2b2b2b
```

Or with Docker Compose (includes Mosquitto):

```bash
docker-compose up -d
```

See **[EXAMPLES.md](EXAMPLES.md)** for command-line options, Docker deployment, PSK handling, sending messages to the mesh, sample JSON output, regions, and troubleshooting.

## License

GNU General Public License v3 or later. This program comes with no warranty; see [LICENSE](LICENSE) and <https://www.gnu.org/licenses/>.

## Acknowledgments

- [Meshtastic](https://meshtastic.org/) — open source mesh networking
- [Eclipse Mosquitto](https://mosquitto.org/) — MQTT broker
- [Paho MQTT](https://www.eclipse.org/paho/) — MQTT client library

## Support

- Examples & guides: [EXAMPLES.md](EXAMPLES.md)
- Issues: [GitHub Issues](https://github.com/caveman99/meshtastic-mqtt-converter/issues)
- Meshtastic: [Discord](https://discord.gg/meshtastic)

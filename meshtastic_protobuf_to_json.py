
"""
Meshtastic MQTT Protobuf to JSON Converter

Subscribes to Protobuf MQTT topics, converts packets to JSON, and republishes them.
"""

import paho.mqtt.client as mqtt
import json
import base64
import logging
import argparse
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
import struct

try:
    from meshtastic import mesh_pb2, mqtt_pb2, telemetry_pb2, portnums_pb2
except ImportError:
    print("Error: Install dependencies with: pip install -r requirements.txt")
    exit(1)

# Optional payload types (absent in older meshtastic builds).
try:
    from meshtastic import remote_hardware_pb2
except ImportError:
    remote_hardware_pb2 = None
try:
    from meshtastic import paxcount_pb2
except ImportError:
    paxcount_pb2 = None

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class MeshtasticConverter:
    def __init__(self, broker, port, username, password, region, root_topic, psk=None):
        self.broker = broker
        self.port = port
        self.region = region
        self.root_topic = root_topic
        self.psk = self.decode_psk(psk) if psk else None
        
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        if username:
            self.client.username_pw_set(username, password)
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
    
    def decode_psk(self, psk_str):
        if not psk_str or psk_str.lower() == 'none':
            return None
        

        if psk_str.startswith('base64:'):
            return base64.b64decode(psk_str[7:])
        

        if psk_str.startswith('0x'):
            return bytes.fromhex(psk_str[2:])
        

        try:
            return bytes.fromhex(psk_str)
        except ValueError:
            pass
        

        try:
            return base64.b64decode(psk_str)
        except:
            pass
        

        if psk_str == 'default' or psk_str == '1':
            return bytes([1])
        
        logger.error(f"Could not decode PSK: {psk_str}")
        return None
    
    def decrypt_packet(self, packet):
        if not self.psk or len(self.psk) == 0:
            return False
        
        if not packet.HasField('encrypted') or len(packet.encrypted) == 0:
            return False
        
        try:

            if len(self.psk) == 1:

                key = bytearray([0xd4, 0xf1, 0xbb, 0x3a, 0x20, 0x29, 0x07, 0x59,
                                0xf0, 0xbc, 0xff, 0xab, 0xcf, 0x4e, 0x69, 0x01])
                if self.psk[0] > 1:
                    key[-1] += (self.psk[0] - 1)
                key = bytes(key)
            else:
                key = self.psk
            

            packet_id = packet.id
            from_node = getattr(packet, 'from')
            

            nonce = struct.pack('<I', packet_id) + bytes(4) + struct.pack('<I', from_node) + bytes(4)
            

            cipher = Cipher(algorithms.AES(key), modes.CTR(nonce), backend=default_backend())
            decryptor = cipher.decryptor()
            decrypted = decryptor.update(packet.encrypted) + decryptor.finalize()
            

            packet.decoded.ParseFromString(decrypted)
            return True
            
        except Exception as e:
            logger.debug(f"Decryption failed: {e}")
            return False
    
    def encrypt_packet(self, packet):
        if not self.psk or len(self.psk) == 0:
            return
        
        if not packet.HasField('decoded'):
            return
        
        try:

            if len(self.psk) == 1:
                key = bytearray([0xd4, 0xf1, 0xbb, 0x3a, 0x20, 0x29, 0x07, 0x59,
                                0xf0, 0xbc, 0xff, 0xab, 0xcf, 0x4e, 0x69, 0x01])
                if self.psk[0] > 1:
                    key[-1] += (self.psk[0] - 1)
                key = bytes(key)
            else:
                key = self.psk
            

            plaintext = packet.decoded.SerializeToString()
            

            packet_id = packet.id if packet.id else 0
            from_node = getattr(packet, 'from')
            nonce = struct.pack('<I', packet_id) + struct.pack('<I', from_node) + bytes(8)
            

            cipher = Cipher(algorithms.AES(key), modes.CTR(nonce), backend=default_backend())
            encryptor = cipher.encryptor()
            encrypted = encryptor.update(plaintext) + encryptor.finalize()
            

            packet.encrypted = encrypted
            packet.ClearField('decoded')
            
        except Exception as e:
            logger.error(f"Encryption failed: {e}")
        
    def on_connect(self, client, userdata, flags, rc, properties=None):
        if rc == 0:

            protobuf_topic = f"{self.root_topic}/{self.region}/2/e/#"

            json_topic = f"{self.root_topic}/{self.region}/2/json/#"
            
            logger.info(f"Connected to {self.broker}")
            logger.info(f"Subscribing to protobuf: {protobuf_topic}")
            logger.info(f"Subscribing to JSON downlink: {json_topic}")
            
            client.subscribe(protobuf_topic)
            client.subscribe(json_topic)
        else:
            logger.error(f"Connection failed with code {rc}")
    
    def on_message(self, client, userdata, msg):
        try:
            topic_parts = msg.topic.split('/')
            

            if '/json/' in msg.topic and len(topic_parts) >= 5:

                try:
                    json_data = json.loads(msg.payload.decode('utf-8'))

                    if 'type' in json_data and json_data['type'].startswith('send'):
                        self.handle_json_to_protobuf(client, msg, json_data)
                        return

                    return
                except (json.JSONDecodeError, UnicodeDecodeError):

                    logger.debug(f"Could not parse JSON on topic: {msg.topic}")
                    return
            

            if '/e/' in msg.topic:
                self.handle_protobuf_to_json(client, msg)
        except Exception as e:
            logger.error(f"Error processing message: {e}")
    
    def handle_json_to_protobuf(self, client, msg, json_data):
        try:
            logger.debug(f"Received JSON downlink: {json_data}")
            

            topic_parts = msg.topic.split('/')
            if len(topic_parts) >= 5:
                channel_name = topic_parts[4]
            else:
                channel_name = "LongFast"
            

            packet = mesh_pb2.MeshPacket()

            setattr(packet, 'from', json_data.get('from', 0))
            packet.to = json_data.get('to', 0xFFFFFFFF)
            packet.id = json_data.get('id', 0)
            
            if 'channel' in json_data:
                packet.channel = json_data['channel']

            # Firmware used camelCase "hopLimit"; accept both spellings.
            if 'hopLimit' in json_data:
                packet.hop_limit = json_data['hopLimit']
            elif 'hop_limit' in json_data:
                packet.hop_limit = json_data['hop_limit']


            msg_type = json_data.get('type', '')
            payload_data = json_data.get('payload', {})

            if msg_type == 'sendtext':
                packet.decoded.portnum = portnums_pb2.PortNum.TEXT_MESSAGE_APP
                text = payload_data if isinstance(payload_data, str) else payload_data.get('text', '')
                packet.decoded.payload = text.encode('utf-8')

            elif msg_type == 'sendposition':
                packet.decoded.portnum = portnums_pb2.PortNum.POSITION_APP
                pos = mesh_pb2.Position()
                # Prefer raw latitude_i/longitude_i; fall back to decimal.
                if 'latitude_i' in payload_data:
                    pos.latitude_i = int(payload_data['latitude_i'])
                elif 'latitude' in payload_data:
                    pos.latitude_i = int(payload_data['latitude'] * 1e7)
                if 'longitude_i' in payload_data:
                    pos.longitude_i = int(payload_data['longitude_i'])
                elif 'longitude' in payload_data:
                    pos.longitude_i = int(payload_data['longitude'] * 1e7)
                if 'altitude' in payload_data:
                    pos.altitude = int(payload_data['altitude'])
                if 'time' in payload_data:
                    pos.time = int(payload_data['time'])
                packet.decoded.payload = pos.SerializeToString()
            else:
                logger.warning(f"Unknown message type for downlink: {msg_type}")
                return
            

            envelope = mqtt_pb2.ServiceEnvelope()
            envelope.packet.CopyFrom(packet)
            envelope.channel_id = json_data.get('channel_id', channel_name)
            envelope.gateway_id = json_data.get('gateway_id', '')
            

            if self.psk:
                self.encrypt_packet(envelope.packet)
            

            protobuf_topic = f"{self.root_topic}/{self.region}/2/e/{channel_name}/{envelope.gateway_id}"
            client.publish(protobuf_topic, envelope.SerializeToString())
            logger.info(f"JSON->Protobuf: {msg.topic} -> {protobuf_topic}")
            
        except Exception as e:
            logger.error(f"Error converting JSON to Protobuf: {e}")
    
    def handle_protobuf_to_json(self, client, msg):
        try:
            topic_parts = msg.topic.split('/')
            if len(topic_parts) < 6:
                return
            
            channel = topic_parts[4]
            user_id = topic_parts[5]
            
            envelope = mqtt_pb2.ServiceEnvelope()
            envelope.ParseFromString(msg.payload)
            

            if envelope.packet.HasField('encrypted'):
                self.decrypt_packet(envelope.packet)
            
            json_data = self.convert_to_json(envelope)
            if json_data:
                json_topic = f"{self.root_topic}/{self.region}/2/json/{channel}/{user_id}"
                # sort_keys matches the firmware's std::map (alphabetical) order.
                client.publish(json_topic, json.dumps(json_data, separators=(',', ':'), sort_keys=True))
                logger.debug(f"Protobuf->JSON: {msg.topic} -> {json_topic}")
        except Exception as e:
            logger.error(f"Error converting Protobuf to JSON: {e}")
    
    @staticmethod
    def hops_away(packet):
        # Firmware getHopsAway(): -1 (unknown) unless hop_start is set and not exceeded.
        if packet.hop_start != 0 and packet.hop_limit <= packet.hop_start:
            return packet.hop_start - packet.hop_limit
        return -1

    def convert_to_json(self, envelope):
        packet = envelope.packet
        if not packet.HasField('decoded'):
            return None

        decoded = packet.decoded
        portnum = decoded.portnum

        json_obj = {
            "id": packet.id,
            "timestamp": packet.rx_time if packet.rx_time > 0 else 0,
            "to": packet.to,
            "from": getattr(packet, 'from'),
            "channel": packet.channel,
            "sender": envelope.gateway_id if envelope.gateway_id else f"!{getattr(packet, 'from'):08x}"
        }

        payload = None
        if portnum == portnums_pb2.PortNum.TEXT_MESSAGE_APP:
            json_obj["type"] = "text"
            text = decoded.payload.decode('utf-8', errors='ignore')
            # A JSON text payload passes through; otherwise wrap as {"text": ...}.
            try:
                payload = json.loads(text)
            except (json.JSONDecodeError, ValueError):
                payload = {"text": text}
        elif portnum == portnums_pb2.PortNum.POSITION_APP:
            json_obj["type"] = "position"
            payload = self.convert_position(decoded)
        elif portnum == portnums_pb2.PortNum.NODEINFO_APP:
            json_obj["type"] = "nodeinfo"
            payload = self.convert_nodeinfo(decoded)
        elif portnum == portnums_pb2.PortNum.TELEMETRY_APP:
            json_obj["type"] = "telemetry"
            payload = self.convert_telemetry(decoded)
        elif portnum == portnums_pb2.PortNum.WAYPOINT_APP:
            json_obj["type"] = "waypoint"
            payload = self.convert_waypoint(decoded)
        elif portnum == portnums_pb2.PortNum.NEIGHBORINFO_APP:
            json_obj["type"] = "neighborinfo"
            payload = self.convert_neighborinfo(decoded)
        elif portnum == portnums_pb2.PortNum.TRACEROUTE_APP:
            # Firmware only serializes the traceroute reply (request_id set).
            if decoded.request_id:
                json_obj["type"] = "traceroute"
                payload = self.convert_traceroute(packet, decoded)
        elif portnum == portnums_pb2.PortNum.DETECTION_SENSOR_APP:
            json_obj["type"] = "detection"
            payload = {"text": decoded.payload.decode('utf-8', errors='ignore')}
        elif portnum == portnums_pb2.PortNum.PAXCOUNTER_APP:
            json_obj["type"] = "paxcounter"
            payload = self.convert_paxcounter(decoded)
        elif portnum == portnums_pb2.PortNum.REMOTE_HARDWARE_APP:
            payload = self.convert_remotehardware(decoded, json_obj)

        # Radio metadata, gated exactly as the firmware gates it.
        if packet.rx_rssi != 0:
            json_obj["rssi"] = packet.rx_rssi
        if packet.rx_snr != 0:
            json_obj["snr"] = packet.rx_snr
        hops = self.hops_away(packet)
        if hops >= 0:
            json_obj["hops_away"] = hops
            json_obj["hop_start"] = packet.hop_start

        if payload is not None and json_obj.get("type"):
            json_obj["payload"] = payload
            return json_obj
        return None
    
    def convert_position(self, decoded):
        # Raw latitude_i/longitude_i; optional fields gated on non-zero like the firmware.
        try:
            pos = mesh_pb2.Position()
            pos.ParseFromString(decoded.payload)
            result = {}
            if pos.time:
                result["time"] = pos.time
            if pos.timestamp:
                result["timestamp"] = pos.timestamp
            result["latitude_i"] = pos.latitude_i
            result["longitude_i"] = pos.longitude_i
            if pos.altitude:
                result["altitude"] = pos.altitude
            if pos.ground_speed:
                result["ground_speed"] = pos.ground_speed
            if pos.ground_track:
                result["ground_track"] = pos.ground_track
            if pos.sats_in_view:
                result["sats_in_view"] = pos.sats_in_view
            if pos.PDOP:
                result["PDOP"] = pos.PDOP
            if pos.HDOP:
                result["HDOP"] = pos.HDOP
            if pos.VDOP:
                result["VDOP"] = pos.VDOP
            if pos.precision_bits:
                result["precision_bits"] = pos.precision_bits
            return result
        except Exception as e:
            logger.error(f"Error decoding position: {e}")
            return {}

    def convert_nodeinfo(self, decoded):
        user = mesh_pb2.User()
        user.ParseFromString(decoded.payload)
        return {
            "id": user.id,
            "longname": user.long_name,
            "shortname": user.short_name,
            "hardware": int(user.hw_model),
            "role": int(user.role)
        }
    
    def convert_telemetry(self, decoded):
        telemetry = telemetry_pb2.Telemetry()
        telemetry.ParseFromString(decoded.payload)
        result = {}
        
        if telemetry.HasField('device_metrics'):
            dm = telemetry.device_metrics
            # battery_level is presence-gated; the rest are always emitted.
            if dm.HasField('battery_level'):
                result["battery_level"] = dm.battery_level
            result["voltage"] = dm.voltage
            result["channel_utilization"] = dm.channel_utilization
            result["air_util_tx"] = dm.air_util_tx
            result["uptime_seconds"] = dm.uptime_seconds
        elif telemetry.HasField('environment_metrics'):
            em = telemetry.environment_metrics
            if em.HasField('temperature'):
                result["temperature"] = em.temperature
            if em.HasField('relative_humidity'):
                result["relative_humidity"] = em.relative_humidity
            if em.HasField('barometric_pressure'):
                result["barometric_pressure"] = em.barometric_pressure
            if em.HasField('gas_resistance'):
                result["gas_resistance"] = em.gas_resistance
            if em.HasField('voltage'):
                result["voltage"] = em.voltage
            if em.HasField('current'):
                result["current"] = em.current
            if em.HasField('lux'):
                result["lux"] = em.lux
            if em.HasField('white_lux'):
                result["white_lux"] = em.white_lux
            if em.HasField('iaq'):
                result["iaq"] = em.iaq
            if em.HasField('distance'):
                result["distance"] = em.distance
            if em.HasField('wind_speed'):
                result["wind_speed"] = em.wind_speed
            if em.HasField('wind_direction'):
                result["wind_direction"] = em.wind_direction
            if em.HasField('wind_gust'):
                result["wind_gust"] = em.wind_gust
            if em.HasField('wind_lull'):
                result["wind_lull"] = em.wind_lull
            if em.HasField('radiation'):
                result["radiation"] = em.radiation
            if em.HasField('ir_lux'):
                result["ir_lux"] = em.ir_lux
            if em.HasField('uv_lux'):
                result["uv_lux"] = em.uv_lux
            if em.HasField('weight'):
                result["weight"] = em.weight
            if em.HasField('rainfall_1h'):
                result["rainfall_1h"] = em.rainfall_1h
            if em.HasField('rainfall_24h'):
                result["rainfall_24h"] = em.rainfall_24h
            if em.HasField('soil_moisture'):
                result["soil_moisture"] = em.soil_moisture
            if em.HasField('soil_temperature'):
                result["soil_temperature"] = em.soil_temperature
        elif telemetry.HasField('air_quality_metrics'):
            aq = telemetry.air_quality_metrics
            if aq.HasField('pm10_standard'):
                result["pm10"] = aq.pm10_standard
            if aq.HasField('pm25_standard'):
                result["pm25"] = aq.pm25_standard
            if aq.HasField('pm100_standard'):
                result["pm100"] = aq.pm100_standard
            if aq.HasField('co2'):
                result["co2"] = aq.co2
            if aq.HasField('co2_temperature'):
                result["co2_temperature"] = aq.co2_temperature
            if aq.HasField('co2_humidity'):
                result["co2_humidity"] = aq.co2_humidity
            if aq.HasField('form_formaldehyde'):
                result["form_formaldehyde"] = aq.form_formaldehyde
            if aq.HasField('form_temperature'):
                result["form_temperature"] = aq.form_temperature
            if aq.HasField('form_humidity'):
                result["form_humidity"] = aq.form_humidity
        elif telemetry.HasField('power_metrics'):
            pm = telemetry.power_metrics
            if pm.HasField('ch1_voltage'):
                result["voltage_ch1"] = pm.ch1_voltage
            if pm.HasField('ch1_current'):
                result["current_ch1"] = pm.ch1_current
            if pm.HasField('ch2_voltage'):
                result["voltage_ch2"] = pm.ch2_voltage
            if pm.HasField('ch2_current'):
                result["current_ch2"] = pm.ch2_current
            if pm.HasField('ch3_voltage'):
                result["voltage_ch3"] = pm.ch3_voltage
            if pm.HasField('ch3_current'):
                result["current_ch3"] = pm.ch3_current
        elif telemetry.HasField('host_metrics'):
            hm = telemetry.host_metrics
            if hm.uptime_seconds != 0:
                result["uptime_seconds"] = hm.uptime_seconds
            if hm.freemem_bytes != 0:
                result["freemem_bytes"] = hm.freemem_bytes
            if hm.diskfree1_bytes != 0:
                result["diskfree1_bytes"] = hm.diskfree1_bytes
            if hm.diskfree2_bytes != 0:
                result["diskfree2_bytes"] = hm.diskfree2_bytes
            if hm.diskfree3_bytes != 0:
                result["diskfree3_bytes"] = hm.diskfree3_bytes
            if hm.load1 != 0:
                result["load1"] = hm.load1/100
            if hm.load5 != 0:
                result["load5"] = hm.load5/100
            if hm.load15 != 0:
                result["load15"] = hm.load15/100

        return result
    
    def convert_waypoint(self, decoded):
        waypoint = mesh_pb2.Waypoint()
        waypoint.ParseFromString(decoded.payload)
        # Firmware emits raw latitude_i/longitude_i plus the lifecycle fields.
        return {
            "id": waypoint.id,
            "name": waypoint.name,
            "description": waypoint.description,
            "expire": waypoint.expire,
            "locked_to": waypoint.locked_to,
            "latitude_i": waypoint.latitude_i,
            "longitude_i": waypoint.longitude_i
        }

    def convert_neighborinfo(self, decoded):
        neighbor_info = mesh_pb2.NeighborInfo()
        neighbor_info.ParseFromString(decoded.payload)
        return {
            "node_id": neighbor_info.node_id,
            "node_broadcast_interval_secs": neighbor_info.node_broadcast_interval_secs,
            "last_sent_by_id": neighbor_info.last_sent_by_id,
            "neighbors_count": len(neighbor_info.neighbors),
            "neighbors": [{"node_id": n.node_id, "snr": int(n.snr)} for n in neighbor_info.neighbors]
        }

    def convert_traceroute(self, packet, decoded):
        # No NodeDB here, so hops render as "!aabbccdd" ids (firmware uses long-names).
        # SNR is quarter-dB in the protobuf, hence /4.
        try:
            route_disc = mesh_pb2.RouteDiscovery()
            route_disc.ParseFromString(decoded.payload)

            def node_name(num):
                return f"!{num & 0xffffffff:08x}"

            route = [node_name(packet.to)]
            route += [node_name(n) for n in route_disc.route]
            route.append(node_name(getattr(packet, 'from')))

            route_back = [node_name(getattr(packet, 'from'))]
            route_back += [node_name(n) for n in route_disc.route_back]
            route_back.append(node_name(packet.to))

            return {
                "route": route,
                "route_back": route_back,
                "snr_back": [s / 4 for s in route_disc.snr_back],
                "snr_towards": [s / 4 for s in route_disc.snr_towards]
            }
        except Exception as e:
            logger.error(f"Error decoding traceroute: {e}")
            return None

    def convert_paxcounter(self, decoded):
        if paxcount_pb2 is None:
            logger.warning("paxcount_pb2 unavailable; cannot decode paxcounter")
            return None
        try:
            pax = paxcount_pb2.Paxcount()
            pax.ParseFromString(decoded.payload)
            return {
                "wifi_count": pax.wifi,
                "ble_count": pax.ble,
                "uptime": pax.uptime
            }
        except Exception as e:
            logger.error(f"Error decoding paxcounter: {e}")
            return None

    def convert_remotehardware(self, decoded, json_obj):
        # Sets json_obj["type"] itself (gpios_changed / gpios_read_reply).
        if remote_hardware_pb2 is None:
            logger.warning("remote_hardware_pb2 unavailable; cannot decode remote hardware")
            return None
        try:
            hw = remote_hardware_pb2.HardwareMessage()
            hw.ParseFromString(decoded.payload)
            if hw.type == remote_hardware_pb2.HardwareMessage.Type.GPIOS_CHANGED:
                json_obj["type"] = "gpios_changed"
                return {"gpio_value": hw.gpio_value}
            elif hw.type == remote_hardware_pb2.HardwareMessage.Type.READ_GPIOS_REPLY:
                json_obj["type"] = "gpios_read_reply"
                return {"gpio_value": hw.gpio_value, "gpio_mask": hw.gpio_mask}
            return None
        except Exception as e:
            logger.error(f"Error decoding remote hardware: {e}")
            return None

    def start(self):
        logger.info(f"Starting converter for region {self.region}")
        self.client.connect(self.broker, self.port, 60)
        self.client.loop_forever()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Meshtastic MQTT Protobuf to JSON Converter')
    parser.add_argument('--broker', default='mqtt.meshtastic.org', help='MQTT broker address')
    parser.add_argument('--port', type=int, default=1883, help='MQTT port')
    parser.add_argument('--username', default=None, help='MQTT username')
    parser.add_argument('--password', default=None, help='MQTT password')
    parser.add_argument('--region', default='EU_868', help='Meshtastic region')
    parser.add_argument('--root-topic', default='msh', help='Root topic')
    parser.add_argument('--psk', default=None, help='Channel PSK for encryption (hex, base64:xxx, or "default")')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    
    args = parser.parse_args()
    
    if args.debug:
        logger.setLevel(logging.DEBUG)
    
    converter = MeshtasticConverter(
        args.broker, args.port, args.username, args.password, args.region, args.root_topic, args.psk
    )
    
    try:
        converter.start()
    except KeyboardInterrupt:
        logger.info("Stopped")


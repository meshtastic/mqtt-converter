
"""
Meshtastic MQTT Protobuf to JSON Converter

Subscribes to Protobuf MQTT topics, converts packets to JSON, and republishes them.
"""

import paho.mqtt.client as mqtt
import json
import base64
from typing import Optional, Dict, Any
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
            
            if 'hop_limit' in json_data:
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
                if 'latitude' in payload_data:
                    pos.latitude_i = int(payload_data['latitude'] * 1e7)
                if 'longitude' in payload_data:
                    pos.longitude_i = int(payload_data['longitude'] * 1e7)
                if 'altitude' in payload_data:
                    pos.altitude = payload_data['altitude']
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
                client.publish(json_topic, json.dumps(json_data, separators=(',', ':')))
                logger.debug(f"Protobuf->JSON: {msg.topic} -> {json_topic}")
        except Exception as e:
            logger.error(f"Error converting Protobuf to JSON: {e}")
    
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
            payload = {"text": decoded.payload.decode('utf-8', errors='ignore')}
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
        
        if payload:
            json_obj["payload"] = payload
            return json_obj
        return None
    
    def convert_position(self, decoded):
        try:
            pos = mesh_pb2.Position()
            pos.ParseFromString(decoded.payload)
            result = {}
            if pos.HasField('latitude_i'):
                result["latitude"] = pos.latitude_i * 1e-7
            if pos.HasField('longitude_i'):
                result["longitude"] = pos.longitude_i * 1e-7
            if pos.HasField('altitude'):
                result["altitude"] = pos.altitude

            if pos.time:
                result["time"] = pos.time
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
            "hardware": user.hw_model
        }
    
    def convert_telemetry(self, decoded):
        telemetry = telemetry_pb2.Telemetry()
        telemetry.ParseFromString(decoded.payload)
        result = {}
        
        if telemetry.HasField('device_metrics'):
            dm = telemetry.device_metrics
            result.update({
                "battery_level": dm.battery_level,
                "voltage": dm.voltage,
                "channel_utilization": dm.channel_utilization,
                "air_util_tx": dm.air_util_tx
            })
        elif telemetry.HasField('environment_metrics'):
            em = telemetry.environment_metrics
            if em.HasField('temperature'):
                result["temperature"] = em.temperature
            if em.HasField('relative_humidity'):
                result["relative_humidity"] = em.relative_humidity
            if em.HasField('barometric_pressure'):
                result["barometric_pressure"] = em.barometric_pressure
        
        return result
    
    def convert_waypoint(self, decoded):
        waypoint = mesh_pb2.Waypoint()
        waypoint.ParseFromString(decoded.payload)
        return {
            "id": waypoint.id,
            "name": waypoint.name,
            "latitude": waypoint.latitude_i * 1e-7,
            "longitude": waypoint.longitude_i * 1e-7
        }
    
    def convert_neighborinfo(self, decoded):
        neighbor_info = mesh_pb2.NeighborInfo()
        neighbor_info.ParseFromString(decoded.payload)
        return {
            "node_id": neighbor_info.node_id,
            "neighbors": [{"node_id": n.node_id, "snr": n.snr} for n in neighbor_info.neighbors]
        }
    
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


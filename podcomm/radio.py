import time
from .exceptions import ProtocolError, PacketRadioError, TransmissionOutOfSyncError
from podcomm import crc
from .packet_radio import PacketRadio
from .pr_rileylink import RileyLink
from .message import Message, MessageState
from .packet import Packet
from .definitions import *

class Radio:
    def __init__(self, msg_sequence=0, pkt_sequence=0, debug_mode=False):
        self.messageSequence = msg_sequence
        self.packetSequence = pkt_sequence
        self.lastPacketReceived = None
        self.logger = getLogger()
        self.packetRadio = RileyLink()
        self.last_packet_received = None
        self.debug_mode = debug_mode

    def send_request_get_response(self, message, stay_connected=True, low_tx=False, high_tx=False,
                                  address2=None, debug_func=None):
        try:
            return self._send_request_get_response(message, stay_connected, low_tx, high_tx, address2,
                                                   debug_func=debug_func)
        except TransmissionOutOfSyncError:
            raise
        except Exception:
            self.packetRadio.disconnect(ignore_errors=True)
            raise

    def disconnect(self):
        try:
            self.packetRadio.disconnect(ignore_errors=True)
        except Exception as e:
            self.logger.warning("Error while disconnecting %s" % str(e))

    def _send_request_get_response(self, message, stay_connected=True, low_tx=False, high_tx=False,
                                   address2=None, debug_func=None):
        try:
            return self._send_request(message, low_tx=low_tx, high_tx=high_tx,
                                      address2=address2, debug_func=debug_func)
        except TransmissionOutOfSyncError:
            self.logger.warning("Transmission out of sync, radio needs resyncing")
            raise
        finally:
            if not stay_connected:
                self.packetRadio.disconnect()

    def _send_request(self, message, low_tx=False, high_tx=False, address2=None, debug_func=None):
        try:
            if low_tx:
                self.packetRadio.set_low_tx()
            elif high_tx:
                self.packetRadio.set_high_tx()

            message.setSequence(self.messageSequence)
            self.logger.debug("SENDING MSG: %s" % message)
            packets = message.getPackets(address2)
            received = None
            packet_index = 1
            packet_count = len(packets)
            for packet in packets:
                if packet_index == packet_count:
                    expected_type = "POD"
                else:
                    expected_type = "ACK"
                received = self._exchange_packets(packet, expected_type, debug_func=debug_func)
                if received is None:
                    raise ProtocolError("Timeout reached waiting for a response.")

                if received.type != expected_type:
                    raise ProtocolError("Invalid response received. Expected type %s, received %s"
                                        % (expected_type, received.type))
                packet_index += 1

            pod_response = Message.fromPacket(received)

            while pod_response.state == MessageState.Incomplete:
                ack_packet = Packet.Ack(message.address, False, address2)
                received = self._exchange_packets(ack_packet, "CON")
                if received is None:
                    raise ProtocolError("Timeout reached waiting for a response.")
                if received.type != "CON":
                    raise ProtocolError("Invalid response received. Expected type CON, received %s" % received.type)
                pod_response.addConPacket(received)

            if pod_response.state == MessageState.Invalid:
                raise ProtocolError("Received message is not valid")

            self.logger.debug("RECEIVED MSG: %s" % pod_response)

            self.logger.debug("Sending end of conversation")
            ack_packet = Packet.Ack(message.address, True, address2)
            self._send_packet(ack_packet, debug_func=debug_func)
            self.logger.debug("Conversation ended")

            self.messageSequence = (pod_response.sequence + 1) % 16
            return pod_response
        except TransmissionOutOfSyncError:
            self.messageSequence = (self.messageSequence + 2) % 16
            self.packetSequence = (self.packetSequence + 1) % 32
            self._send_request(message, low_tx, high_tx, address2)
        finally:
            if low_tx or high_tx:
                self.packetRadio.set_normal_tx()

    def _resync(self, p, o):
        self.packetSequence = 31 #(p.sequence ) % 32
        self.messageSequence = self.messageSequence + 1 % 16

        ack_packet = Packet.Ack(o.address, False, o.address2)
        ack_packet.setSequence(self.packetSequence)
        while True:
            received = self.packetRadio.send_and_receive_packet(ack_packet.data, 10, 20, 300, 10, 80)
            if received is None:
                self.logger.debug("Received nothing")
                self.packetSequence = (self.packetSequence + 2) % 32
                return
            else:
                p, rssi = self._get_packet(received)
                if p is None:
                    self.logger.debug("Received illegal packet")
                    self.packetRadio.tx_down()
                else:
                    print(p)


    def _exchange_packets(self, packet_to_send, expected_type, debug_func=None):
        send_retries = 30
        while send_retries > 0:
            try:
                packet_to_send.setSequence(self.packetSequence)
                expected_sequence = (self.packetSequence + 1) % 32
                expected_address = packet_to_send.address
                self.logger.debug("SENDING PACKET EXP RESPONSE: %s" % packet_to_send)
                data = packet_to_send.data
                data += bytes([crc.crc8(data)])

                if packet_to_send.type == "PDM":
                    send_retries -= 1
                    received = self.packetRadio.send_and_receive_packet(data, 0, 0, 100, 1, 130)
                else:
                    received = self.packetRadio.send_and_receive_packet(data, 0, 0, 100, 10, 20)

                if received is None:
                    self.logger.debug("Received nothing")
                    self.packetRadio.tx_up()
                    continue
                p, rssi = self._get_packet(received)
                if p is None:
                    self.logger.debug("Received illegal packet")
                    self.packetRadio.tx_down()
                    continue
                if p.address != expected_address and p.address2 != packet_to_send.address2:
                    self.logger.debug("Received packet for a different radio_address")
                    self.packetRadio.tx_down()
                    continue

                if p.type != expected_type or p.sequence != expected_sequence:
                    if self.last_packet_received is not None:
                        if p.type == self.last_packet_received.type and \
                                p.sequence == self.last_packet_received.sequence:
                            self.logger.debug("Received previous response")
                            self.packetRadio.tx_up()
                            continue

                    self.logger.debug("Resynchronization requested")
                    if debug_func is not None and debug_func("resync"):
                        self._resync(p, packet_to_send)

                self.packetSequence = (self.packetSequence + 2) % 32
                self.last_packet_received = p
                self.logger.debug("SEND AND RECEIVE complete")
                return p
            except PacketRadioError:
                self.logger.exception("Radio error during send and receive")
                self.packetRadio.disconnect()
        else:
            raise ProtocolError("Exceeded retry count while send and receive")

    def _send_packet(self, packetToSend, debug_func=None):
        while True:
            try:
                packetToSend.setSequence(self.packetSequence)
                data = packetToSend.data
                data += bytes([crc.crc8(data)])

                if debug_func is not None and debug_func("y to exit without sending last"):
                    return

                self.logger.debug("SENDING FINAL PACKET: %s" % packetToSend)
                received = self.packetRadio.send_and_receive_packet(data, 0, 0, 100, 3, 20)
                if received is None:
                    received = self.packetRadio.get_packet(1.0)
                    if received is None:
                        self.logger.debug("Silence has fallen")
                        break
                p, rssi = self._get_packet(received)
                if p is None:
                    self.logger.debug("Received illegal packet")
                    self.packetRadio.tx_down()
                    continue
                if p.address != packetToSend.address and p.address2 != packetToSend.address2:
                    self.logger.debug("Received packet for a different radio_address")
                    self.packetRadio.tx_down()
                    continue
                if self.last_packet_received is not None:
                    if p.type == self.last_packet_received.type and \
                            p.sequence == self.last_packet_received.sequence:
                        self.logger.debug("Received previous response")
                        self.packetRadio.tx_up()
                        continue
                self.logger.warning("Resynchronization requested")
                if debug_func is not None and debug_func("resync"):
                    self._resync(p)
                continue

            except PacketRadioError:
                self.logger.exception("Radio error during sending")
                self.packetRadio.disconnect()
        self.packetSequence = (self.packetSequence + 1) % 32
        self.logger.debug("SEND FINAL complete")

    @staticmethod
    def _get_packet(data):
        p = None
        rssi = None
        if data is not None and len(data) > 2:
            rssi = data[0]
            calc = crc.crc8(data[2:-1])
            if data[-1] == calc:
                try:
                    p = Packet.from_data(data[2:-1])
                    getLogger().debug("RECEIVED PACKET: %s RSSI: %d" % (p, rssi))
                except ProtocolError as pe:
                    getLogger().warning("Crc match on an invalid packet, error: %s" % pe)
        return p, rssi

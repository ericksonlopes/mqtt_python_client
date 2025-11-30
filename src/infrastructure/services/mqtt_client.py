import json
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, Optional

import paho.mqtt.client as mqtt
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.properties import Properties

from src.settings.logger import Logger

MessageCallback = Callable[[dict], None]


class MQTTClient(Logger):
    def __init__(
            self,
            broker_ip: str,
            broker_port: int,
            origin: str = "",
            use_loop_forever: bool = False,
            client_id: Optional[str] = None,
            clean_session: Optional[bool] = None,
            userdata: Any = None,
            reconnect_on_failure: bool = True,
            max_workers: int = 4,
    ) -> None:
        super().__init__()

        self.client = mqtt.Client(
            client_id=client_id or "",
            clean_session=clean_session,
            userdata=userdata,
            protocol=mqtt.MQTTv5,
            reconnect_on_failure=reconnect_on_failure,
        )

        self.broker_ip = broker_ip
        self.broker_port = broker_port
        self.origin = origin.rstrip("/")
        self.use_loop_forever = use_loop_forever

        self._topic_callbacks: Dict[str, MessageCallback] = {}
        self.executor = ThreadPoolExecutor(max_workers=max_workers)

        # Callbacks MQTT v5
        self.client.on_connect = self.on_connect
        self.client.on_message = self._internal_on_message
        self.client.on_disconnect = self.on_disconnect

    # ---------- Context manager ----------

    def __enter__(self) -> "MQTTClient":
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.disconnect()

    # ---------- Callbacks ----------

    @staticmethod
    def on_connect(
            client: mqtt.Client,
            userdata: Any,
            flags: Dict[str, Any],
            rc: int,
            properties: Optional[Properties] = None,
    ) -> None:  # [web:32]
        logger: Optional[logging.Logger] = getattr(client, "_logger", None)
        msg = f"Connected to MQTT broker successfully (rc={rc})." if rc == 0 else f"Failed to connect to MQTT broker (rc={rc})."
        if logger:
            logger.info(msg)
        else:
            print(msg)

    @staticmethod
    def on_disconnect(
            client: mqtt.Client,
            userdata: Any,
            rc: int,
            properties: Optional[Properties] = None,
    ) -> None:
        logger: Optional[logging.Logger] = getattr(client, "_logger", None)
        msg = f"Disconnected from MQTT broker (rc={rc})."
        if logger:
            logger.warning(msg)
        else:
            print(msg)

    def _internal_on_message(
            self,
            client: mqtt.Client,
            userdata: Any,
            msg: mqtt.MQTTMessage,
    ) -> None:  # [web:33]
        self.logger.debug(f"Received MQTT message on topic={msg.topic} qos={msg.qos} retain={msg.retain}")

        # prepare stripped topic early to avoid static analysis warnings
        stripped = self._strip_origin(msg.topic)

        # Try to find the callback using the exact topic first
        callback = self._topic_callbacks.get(msg.topic)
        if not callback:
            # if not found, try stripped topic (without origin prefix)
            callback = self._topic_callbacks.get(stripped)

        if not callback:
            self.logger.debug(f"No callback registered for topic {msg.topic} (stripped={stripped})")
            return

        try:
            # msg.payload may be bytes or already decoded string depending on client
            raw_payload = getattr(msg, "payload", None)
            if isinstance(raw_payload, (bytes, bytearray)):
                payload_str = raw_payload.decode("utf-8")
            else:
                payload_str = str(raw_payload)
            self.logger.debug(f"Payload received: {payload_str}")
            parsed_message = json.loads(payload_str)
        except Exception as e:
            self.logger.error(f"Error decoding/Parsing MQTT payload on topic {msg.topic}: {e}")
            return

        # delegate to the thread pool
        self.executor.submit(self._safe_execute_callback, callback, parsed_message)

    def _safe_execute_callback(self, callback: MessageCallback, message: dict) -> None:
        try:
            callback(message)
        except Exception as e:
            self.logger.exception(f"Error executing callback for MQTT message: {e}")

    # ---------- Token helper ----------

    @staticmethod
    def extract_token(msg: mqtt.MQTTMessage) -> Optional[str]:
        props = getattr(msg, "properties", None)
        if not props:
            return None

        user_props = getattr(props, "UserProperty", [])  # list of (key, value) in MQTT v5. [web:37]
        for key, value in user_props:
            if key == "token":
                return value
        return None

    # ---------- Connection / loop ----------

    def connect(self, keepalive: int = 60) -> None:
        # inject logger into the client for static callbacks
        setattr(self.client, "_logger", self.logger)

        self.logger.info(f"Connecting to MQTT broker {self.broker_ip}:{self.broker_port}...")
        self.client.connect(self.broker_ip, self.broker_port, keepalive=keepalive)  # [web:31]

        if self.use_loop_forever:
            self.logger.info("Starting MQTT loop_forever() (blocking)...")
            self.client.loop_forever(retry_first_connection=True)  # [web:34]
        else:
            self.logger.info("Starting MQTT loop_start() (non-blocking)...")
            self.client.loop_start()  # [web:34]

    def disconnect(self) -> None:
        self.logger.info("Shutting down MQTT ThreadPoolExecutor...")
        self.executor.shutdown(wait=True)
        self.client.loop_stop()
        self.client.disconnect()
        self.logger.info("Disconnected from MQTT broker.")

    # ---------- Subscribe / Publish ----------

    def _build_topic(self, topic: str) -> str:
        topic = topic.lstrip("/")
        return f"{self.origin}/{topic}" if self.origin else topic

    def _strip_origin(self, topic: str) -> str:
        """Remove configured origin prefix from topic if present, otherwise return topic unchanged."""
        if not self.origin:
            return topic
        # allow origin with or without trailing slash
        prefix = self.origin.rstrip("/") + "/"
        if topic.startswith(prefix):
            return topic[len(prefix):]
        return topic

    def subscribe(self, topic: str, callback: MessageCallback, qos: int = 1) -> None:
        full_topic = self._build_topic(topic)
        self.logger.info(f"Subscribing to topic: {full_topic} with QoS={qos}")
        # store callback for both full and stripped topic so incoming messages match regardless of origin prefix
        self._topic_callbacks[full_topic] = callback
        stripped = self._strip_origin(full_topic)
        self._topic_callbacks[stripped] = callback
        result, _ = self.client.subscribe(full_topic, qos=qos)  # [web:31]
        if result != mqtt.MQTT_ERR_SUCCESS:
            self.logger.error(f"Failed to subscribe to {full_topic}: {mqtt.error_string(result)}")

    def publish(
            self,
            topic: str,
            message: dict,
            options: Optional[dict] = None,
            token: Optional[str] = None,
    ) -> None:
        options = options or {}
        full_topic = self._build_topic(topic)

        payload = json.dumps(message)
        qos = options.get("qos", 1)
        retain = options.get("retain", False)

        # MQTT v5 Properties (including token in UserProperty). [web:44][web:37]
        props: Optional[Properties] = None
        if token is not None:
            props = Properties(PacketTypes.PUBLISH)
            props.UserProperty = [("token", token)]

        self.logger.debug(
            f"Publishing to topic={full_topic} qos={qos} retain={retain} payload={payload}"
        )

        message_info = self.client.publish(
            full_topic,
            payload=payload,
            qos=qos,
            retain=retain,
            properties=props,
        )

        # wait for the publish to complete
        try:
            message_info.wait_for_publish()
        except Exception as e:
            self.logger.error(f"Error waiting for publish to complete on topic {full_topic} : {e}")

        if message_info.rc != mqtt.MQTT_ERR_SUCCESS:
            self.logger.error(
                f"Failed to publish message to {full_topic}: {mqtt.error_string(message_info.rc)}"
            )

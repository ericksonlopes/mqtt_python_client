import random
from typing import Any, Dict


def publish_devices_update_status(mqtt_client: Any, payload: Dict) -> None:
    """Publica o payload gerado pelo subscriber em um tópico status pseudoaleatório."""
    try:
        topic = f"devices/update/status/{random.randint(1000, 9999)}"
        mqtt_client.publish(topic, payload, options={"qos": 1, "retain": False})
        mqtt_client.logger.info("%s <- %s", topic, payload)
    except Exception as exc:  # pragma: no cover - defensive logging
        mqtt_client.logger.exception("Failed to publish devices/update/status: %s", exc)


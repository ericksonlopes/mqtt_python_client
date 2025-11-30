import datetime
from typing import Any, Callable, Dict

from src.presentation.decorators.mqtt_subscribe import mqtt_subscribe
from src.presentation.publishes.devices_update_status import publish_devices_update_status


@mqtt_subscribe("devices/update")
def build_devices_update_callback(mqtt_client: Any) -> Callable[[Dict], None]:
    """Factory that creates the callback executed when 'devices/update' messages arrive."""

    def devices_update_callback(message: Dict) -> None:
        mqtt_client.logger.info("devices/update -> %s", message)

        payload = {
            "device_id": message.get("device_id"),
            "status": "received",
            "request": message,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }

        publish_devices_update_status(mqtt_client, payload)

    return devices_update_callback



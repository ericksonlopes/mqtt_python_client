from src.infrastructure.services.mqtt_client import MQTTClient
from src.settings.logger import Logger


class MqttSubscriptionHandler(Logger):
    def __init__(self):
        super().__init__()
        self._subscribe_callbacks = []

    def subscribe(self, topic: str):
        def decorator(func):
            self._subscribe_callbacks.append((topic, func))
            return func

        return decorator

    def get_subscribe_callbacks(self):
        return self._subscribe_callbacks

    def register_all_subscribes(self, mqtt_client: MQTTClient):
        try:
            for topic, factory in self.get_subscribe_callbacks():
                callback = factory(mqtt_client)
                mqtt_client.subscribe(topic, callback)
                self.logger.debug(f"Subscribed to {topic}, {callback.__name__=}")
        except Exception as e:
            self.logger.error(f"Error registering MQTT subscriptions: {e}")


mqtt_subscription_handler = MqttSubscriptionHandler()

mqtt_subscribe = mqtt_subscription_handler.subscribe

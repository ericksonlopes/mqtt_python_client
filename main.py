import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.infrastructure.services.mqtt_client import MQTTClient
from src.presentation.decorators.mqtt_subscribe import mqtt_subscription_handler

# Configurações via env (padrões para desenvolvimento)
BROKER_IP = os.getenv("MQTT_BROKER", "localhost")
BROKER_PORT = int(os.getenv("MQTT_PORT", "1883"))
ORIGIN = os.getenv("MQTT_ORIGIN", "")

# Cria cliente MQTT (não bloqueante)
mqtt_client = MQTTClient(
    broker_ip=BROKER_IP,
    broker_port=BROKER_PORT,
    origin=ORIGIN,
    use_loop_forever=False,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gerencia a conexão MQTT durante o ciclo de vida da aplicação FastAPI.

    - Conecta e faz subscribe antes de aceitar requisições.
    - Desconecta ao finalizar o servidor.
    """
    mqtt_client.connect()

    import src.presentation.subscribes.devices_update  # noqa: F401
    mqtt_subscription_handler.register_all_subscribes(mqtt_client)

    try:
        yield
    finally:
        mqtt_client.disconnect()
        mqtt_client.logger.info("MQTT client desconectado")


app = FastAPI(title="MQTT Bridge API", lifespan=lifespan)

if __name__ == "__main__":
    # Runner para desenvolvimento
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000)

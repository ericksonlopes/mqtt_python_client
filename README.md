# FastAPI + MQTT: bastidores de uma ponte inteligente

Sou criador de conteúdo e este repositório é o roteiro do meu artigo/vídeo mostrando como mantenho um único cliente MQTT ativo dentro de um app FastAPI para consumir `devices/update` e responder em `devices/update/status/<rand>`. A seguir está o texto completo que publico no LinkedIn e Medium, com direito a trechos de código de cada parte do projeto.

---

## 1. Por que este projeto existe?
- Demonstrar que HTTP/REST e MQTT podem coexistir harmoniosamente dentro do FastAPI.
- Provar que publishers e subscribers conseguem compartilhar o mesmo `MQTTClient` sem reconectar toda hora.
- Criar um laboratório prático para quem gosta de ver logs, tópicos e ferramentas como MQTT Explorer em ação.

---

## 2. Arquitetura em alto nível
O ciclo de vida nasceu para ser exibido em live:

```python
# main.py
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.infrastructure.services.mqtt_client import MQTTClient
from src.presentation.decorators.mqtt_subscribe import mqtt_subscription_handler

BROKER_IP = os.getenv("MQTT_BROKER", "localhost")
BROKER_PORT = int(os.getenv("MQTT_PORT", "1883"))
ORIGIN = os.getenv("MQTT_ORIGIN", "")

mqtt_client = MQTTClient(
    broker_ip=BROKER_IP,
    broker_port=BROKER_PORT,
    origin=ORIGIN,
    use_loop_forever=False,
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    mqtt_client.connect()
    import src.presentation.subscribes.devices_update  # força decorators a rodarem
    mqtt_subscription_handler.register_all_subscribes(mqtt_client)
    try:
        yield
    finally:
        mqtt_client.disconnect()
        mqtt_client.logger.info("MQTT client desconectado")

app = FastAPI(title="MQTT Bridge API", lifespan=lifespan)
```

**Truque didático**: o `@asynccontextmanager` mantém o cliente vivo durante todo o uptime do FastAPI. Subscriber e publisher recebem o mesmo objeto em memória.

---

## 3. Núcleo MQTT feito para creators
O wrapper em `src/infrastructure/services/mqtt_client.py` entrega blocos perfeitos para slides e carrosséis:

```python
# src/infrastructure/services/mqtt_client.py
class MQTTClient(Logger):
    def __init__(self, broker_ip: str, broker_port: int, origin: str = "", use_loop_forever: bool = False, ...):
        super().__init__()
        self.client = mqtt.Client(protocol=mqtt.MQTTv5, reconnect_on_failure=True)
        self.broker_ip = broker_ip
        self.broker_port = broker_port
        self.origin = origin.rstrip("/")
        self.use_loop_forever = use_loop_forever
        self._topic_callbacks: Dict[str, MessageCallback] = {}
        self.executor = ThreadPoolExecutor(max_workers=4)
        self.client.on_connect = self.on_connect
        self.client.on_message = self._internal_on_message
        self.client.on_disconnect = self.on_disconnect

    def connect(self, keepalive: int = 60) -> None:
        setattr(self.client, "_logger", self.logger)
        self.logger.info(f"Connecting to MQTT broker {self.broker_ip}:{self.broker_port}...")
        self.client.connect(self.broker_ip, self.broker_port, keepalive=keepalive)
        self.client.loop_start()

    def subscribe(self, topic: str, callback: MessageCallback, qos: int = 1) -> None:
        full_topic = self._build_topic(topic)
        self._topic_callbacks[full_topic] = callback
        stripped = self._strip_origin(full_topic)
        self._topic_callbacks[stripped] = callback
        result, _ = self.client.subscribe(full_topic, qos=qos)
        ...

    def publish(self, topic: str, message: dict, options: Optional[dict] = None, token: Optional[str] = None) -> None:
        payload = json.dumps(message)
        message_info = self.client.publish(
            self._build_topic(topic), payload=payload, qos=options.get("qos", 1), retain=options.get("retain", False), properties=props
        )
        message_info.wait_for_publish()
        if message_info.rc != mqtt.MQTT_ERR_SUCCESS:
            self.logger.error("Failed to publish message to %s", topic)
```

Pontos que enfatizo nos posts:
- Executor de threads para não travar o loop MQTT.
- Registro duplo de callbacks (com e sem prefixo `origin`).
- Publicações com QoS configurável e suporte a `token` no MQTT v5.

---

## 4. Decorator como mini DSL
O conteúdo ganha charme mostrando que registrar subscribers vira quase uma DSL Python:

```python
# src/presentation/decorators/mqtt_subscribe.py
class MqttSubscriptionHandler(Logger):
    def __init__(self):
        super().__init__()
        self._subscribe_callbacks = []

    def subscribe(self, topic: str):
        def decorator(func):
            self._subscribe_callbacks.append((topic, func))
            return func
        return decorator

    def register_all_subscribes(self, mqtt_client: MQTTClient):
        for topic, factory in self.get_subscribe_callbacks():
            callback = factory(mqtt_client)
            mqtt_client.subscribe(topic, callback)
            self.logger.debug(f"Subscribed to {topic}, {callback.__name__=}")

mqtt_subscription_handler = MqttSubscriptionHandler()
mqtt_subscribe = mqtt_subscription_handler.subscribe
```

Em aula mostro que basta decorar novas factories e reiniciar o app para ganhar tópicos adicionais.

---

## 5. Subscribers, payloads e publishers (com o mesmo cliente)
A tríade responsável por `devices/update` virou a parte mais popular do artigo:

```python
# src/presentation/subscribes/devices_update.py
from typing import Any, Callable, Dict

from src.presentation.decorators.mqtt_subscribe import mqtt_subscribe
from src.presentation.subscribes.devices_update_callback import devices_update_callback_factory

@mqtt_subscribe("devices/update")
def build_devices_update_callback(mqtt_client: Any) -> Callable[[Dict], None]:
    return devices_update_callback_factory(mqtt_client)
```

```python
# src/presentation/subscribes/devices_update_callback.py
import datetime
from typing import Any, Dict

from src.presentation.publishes.devices_update_status import publish_devices_update_status

def build_devices_update_payload(message: Dict) -> Dict:
    return {
        "device_id": message.get("device_id"),
        "status": "received",
        "request": message,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }

def devices_update_callback_factory(mqtt_client: Any):
    def devices_update_callback(message: Dict) -> None:
        mqtt_client.logger.info("devices/update -> %s", message)
        payload = build_devices_update_payload(message)
        publish_devices_update_status(mqtt_client, payload)
    return devices_update_callback
```

```python
# src/presentation/publishes/devices_update_status.py
import random
from typing import Any, Dict

def publish_devices_update_status(mqtt_client: Any, payload: Dict) -> None:
    topic = f"devices/update/status/{random.randint(1000, 9999)}"
    try:
        mqtt_client.publish(topic, payload, options={"qos": 1, "retain": False})
        mqtt_client.logger.info("%s <- %s", topic, payload)
    except Exception as exc:
        mqtt_client.logger.exception("Failed to publish devices/update/status: %s", exc)
```

Sempre ressalto: **subscriber e publisher usam exatamente o mesmo `mqtt_client` instanciado no `main.py`.**

---

## 6. Logging centralizado para storytelling
Nada melhor do que prints elegantes em lives:

```python
# src/settings/logger.py
class Logger:
    def __init__(self):
        import logging as _logging
        self.logger = _logging.getLogger("MQTTClient")
        handler = _logging.StreamHandler()
        formatter = _logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        if not self.logger.handlers:
            self.logger.addHandler(handler)
        self.logger.setLevel(_logging.DEBUG)
```

Com ele, todo log sai padronizado e pronto para screenshots.

---

## 7. Hands-on que mostro em LinkedIn/Medium
### Broker local
```yaml
# docker-compose.yml
services:
  vernemq:
    image: eclipse-mosquitto
    ports:
      - "1883:1883"
      - "8083:8083"
      - "8080:8080"
```

### Ambiente Python
```bash
pipenv install --dev
pipenv run uvicorn main:app --reload
```

### Teste com MQTT Explorer ou CLI
```bash
# Publica em devices/update
topic="devices/update"
payload='{"device_id":"sensor-99","version":"1.0"}'
mosquitto_pub -h localhost -p 1883 -t "$topic" -m "$payload"

# Escuta os ACKs
topic="devices/update/status/#"
mosquitto_sub -h localhost -p 1883 -t "$topic"
```

Durante a demonstração, deixo o terminal aberto para o log:
```
2025-11-30 10:12:33 - MQTTClient - INFO - devices/update -> {...}
2025-11-30 10:12:33 - MQTTClient - INFO - devices/update/status/7421 <- {...}
```

---

## 8. Storytelling pronto para publicação
- **Gancho**: “Um único cliente MQTT mantém tudo sincronizado enquanto o FastAPI cuida da saúde do serviço”.
- **Demonstração**: o `lifespan` garante conexão contínua; o decorator registra subscribers dinamicamente.
- **Expansão**: proponho que a audiência crie novos arquivos em `subscribes/` para tópicos próprios.
- **Chamada à ação**: clone o repo, poste seu log favorito e marque o criador.

---

## 9. Troubleshooting que ensino
- **Nada chega no subscriber**: confirme que `src.presentation.subscribes.devices_update` foi importado em `main.py` e que `MQTT_ORIGIN` não adiciona prefixos inesperados.
- **Sem mensagens no Explorer**: cheque se o container do broker está rodando e se a porta 1883 não está bloqueada por firewall.
- **Publish falha**: observe o log “Failed to publish devices/update/status” e ajuste QoS/retain conforme necessidade.

---

## 10. Próximos conteúdos para a comunidade
1. Testes unitários simulando payloads via mocks do `mqtt_client`.
2. Conteúdo sobre autenticação/token usando propriedades MQTT v5 já disponíveis no wrapper.
3. Endpoints HTTP extras para consultar último status recebido e disparar publicações on-demand.

---

Este README é literalmente o artigo que publico no LinkedIn e Medium. Sinta-se livre para remixar, mas mantenha a narrativa: FastAPI + MQTT, um único cliente compartilhado, callbacks desacoplados e conteúdo educativo para a comunidade Python.

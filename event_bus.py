import json
import pika
from typing import Callable, Dict, Any
from datetime import datetime
import logging
import os
import threading
from queue import Queue, Empty

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class EventBus:
    """Central event bus for publishing and consuming events (with connection pooling)."""

    def __init__(self, host: str = None, pool_size: int = 5):
        if host is None:
            host = os.getenv('RABBITMQ_HOST', 'localhost')
        self.host = host
        self.username = os.getenv('RABBITMQ_USER', 'admin')
        self.password = os.getenv('RABBITMQ_PASS', 'admin')
        self.exchange_name = 'order_events'

        self.pool_size = pool_size
        self.pool = Queue(maxsize=pool_size)
        self.pool_lock = threading.Lock()

        self.consumer_connection = None
        self.consumer_channel = None

    def _create_connection(self):
        credentials = pika.PlainCredentials(self.username, self.password)
        parameters = pika.ConnectionParameters(
            host=self.host,
            credentials=credentials,
            heartbeat=600,
            blocked_connection_timeout=300
        )
        return pika.BlockingConnection(parameters)

    def _get_connection(self):
        """Get a connection from pool or create a new one if pool isn't full."""
        try:
            return self.pool.get_nowait()
        except Empty:
            with self.pool_lock:
                if self.pool.qsize() + 1 <= self.pool_size:
                    return self._create_connection()
                else:
                    # Wait until a connection is returned
                    return self.pool.get()

    def _return_connection(self, connection):
        """Return a connection to the pool."""
        try:
            if connection.is_open:
                self.pool.put_nowait(connection)
            else:
                # Replace closed connection
                new_conn = self._create_connection()
                self.pool.put_nowait(new_conn)
        except Exception as e:
            logger.warning(f"Failed returning connection to pool: {e}")

    def connect(self):
        """Establish persistent connection for consumers only."""
        self.consumer_connection = self._create_connection()
        self.consumer_channel = self.consumer_connection.channel()
        self.consumer_channel.exchange_declare(
            exchange=self.exchange_name,
            exchange_type='topic',
            durable=True
        )
        logger.info(f"Connected to EventBus (consumer) at {self.host}")

    def publish_event(self, event_type: str, event_data: Dict[str, Any]):
        """Publish an event using a pooled connection."""
        connection = None
        try:
            connection = self._get_connection()
            channel = connection.channel()
            channel.exchange_declare(
                exchange=self.exchange_name,
                exchange_type='topic',
                durable=True
            )

            event = {
                'event_type': event_type,
                'event_id': f"{event_type}_{datetime.utcnow().timestamp()}",
                'timestamp': datetime.utcnow().isoformat(),
                'data': event_data
            }

            channel.basic_publish(
                exchange=self.exchange_name,
                routing_key=event_type,
                body=json.dumps(event),
                properties=pika.BasicProperties(
                    delivery_mode=2,
                    content_type='application/json'
                )
            )

            logger.info(f"Published event: {event_type} - {event['event_id']}")
        except Exception as e:
            logger.error(f"Error publishing event '{event_type}': {e}")
            # If a connection broke, don’t return it to pool
            if connection and connection.is_open:
                connection.close()
        finally:
            if connection:
                self._return_connection(connection)

    def subscribe(self, event_types: list, callback: Callable, queue_name: str):
        """Subscribe to specific event types (using consumer connection)."""
        if not self.consumer_channel:
            self.connect()

        self.consumer_channel.queue_declare(queue=queue_name, durable=True)

        for event_type in event_types:
            self.consumer_channel.queue_bind(
                exchange=self.exchange_name,
                queue=queue_name,
                routing_key=event_type
            )

        def on_message(ch, method, properties, body):
            try:
                event = json.loads(body)
                # logger.info(f"Received event: {event['event_type']}")
                callback(event)
                ch.basic_ack(delivery_tag=method.delivery_tag)
            except Exception as e:
                logger.error(f"Error processing event: {e}")
                ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)

        self.consumer_channel.basic_qos(prefetch_count=1)
        self.consumer_channel.basic_consume(
            queue=queue_name,
            on_message_callback=on_message
        )

        logger.info(f"Subscribed to events: {event_types} on queue: {queue_name}")

    def start_consuming(self):
        """Start consuming messages."""
        logger.info("Starting to consume messages...")
        self.consumer_channel.start_consuming()

    def close(self):
        """Close all pooled and consumer connections."""
        while not self.pool.empty():
            conn = self.pool.get_nowait()
            try:
                conn.close()
            except:
                pass
        if self.consumer_connection:
            self.consumer_connection.close()
        logger.info("EventBus connections closed")

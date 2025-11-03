# locustfile.py

import time
import threading
import os
import csv
from locust import HttpUser, task, events, between
from locust.env import Environment
from locust.stats import stats_printer, stats_history
from locust.log import setup_logging
import gevent

# Event bus import
try:
    from event_bus import EventBus
except Exception:
    from event_bus import EventBus


class EDAEventListener:
    """
    Singleton that manages EDA event listening across all users.
    Listens for 'order.final' events and signals waiting requests.
    """
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
            
        self._initialized = True
        self._event_bus = None
        self._consumer_thread = None
        self._queue_name = f"locust_eda_{os.getpid()}_{int(time.time()*1000)}"
        
        # order_id -> gevent.event.Event for signaling
        self._pending_orders = {}
        # order_id -> result dict
        self._order_results = {}
        self._lock = threading.Lock()
        
        self._start_consumer()
    
    def _start_consumer(self):
        """Start background thread consuming order.final events."""
        def handle_event(event):
            try:
                if event.get("event_type") != "order.final":
                    return
                    
                data = event.get("data", {}) or {}
                order_id = data.get("order_id")
                if not order_id:
                    return
                
                # Success if payment_id present
                success = "payment_id" in data
                
                with self._lock:
                    self._order_results[order_id] = {
                        "success": success,
                        "data": data
                    }
                    
                    # Signal any waiting greenlet
                    evt = self._pending_orders.get(order_id)
                    if evt:
                        evt.set()
                        
            except Exception as e:
                print(f"Error handling event: {e}")
        
        def consumer():
            bus = EventBus()
            self._event_bus = bus
            bus.connect()
            bus.subscribe(["order.final"], handle_event, queue_name=self._queue_name)
            bus.start_consuming()
        
        self._consumer_thread = threading.Thread(
            target=consumer,
            name="EDAConsumer",
            daemon=True
        )
        self._consumer_thread.start()
    
    def wait_for_order(self, order_id, timeout=60.0):
        """
        Register interest in an order and wait for its final event.
        Returns (success: bool, data: dict) or (False, None) on timeout.
        """
        evt = gevent.event.Event()
        
        with self._lock:
            self._pending_orders[order_id] = evt
        
        try:
            # Wait for event with timeout
            result = evt.wait(timeout=timeout)
            
            if not result:
                return False, {"reason": "timeout"}
            
            with self._lock:
                order_result = self._order_results.get(order_id, {})
                
            return order_result.get("success", False), order_result.get("data", {})
            
        finally:
            # Cleanup
            with self._lock:
                self._pending_orders.pop(order_id, None)
                self._order_results.pop(order_id, None)


class RequestResponseUser(HttpUser):
    """
    Locust user for testing Request-Response architecture.
    Measures synchronous HTTP request/response cycles.
    """
    wait_time = between(0.1, 0.5)
    host = "http://localhost:5000"
    
    @task
    def create_order(self):
        order = {
            "customer_id": f"customer_{int(time.time()*1000)}",
            "items": [
                {
                    "item_id": "item_001",
                    "name": "Laptop",
                    "quantity": 1,
                    "price": 1200
                }
            ]
        }
        
        with self.client.post(
            "/orders",
            json=order,
            catch_response=True,
            name="POST /orders [RR]"
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Status: {response.status_code}")


class EventDrivenUser(HttpUser):
    """
    Locust user for testing Event-Driven architecture.
    Measures end-to-end latency from POST to final event arrival.
    """
    wait_time = between(0.1, 0.5)
    host = "http://localhost:8001"
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.eda_listener = EDAEventListener()
    
    @task
    def create_order(self):
        order = {
            "customer_id": f"customer_{int(time.time()*1000)}",
            "items": [
                {
                    "item_id": "item_001",
                    "name": "Laptop",
                    "quantity": 1,
                    "price": 1200
                }
            ]
        }
        
        # Start E2E timer BEFORE the POST
        e2e_start = time.time()
        
        # Make the POST request (this gets tracked automatically as HTTP latency)
        response = self.client.post("/orders", json=order, name="POST /orders [EDA]")
        
        if response.status_code not in [200, 202]:
            # Fire failure event for E2E
            events.request.fire(
                request_type="EDA_E2E",
                name="Order E2E Flow [EDA]",
                response_time=0,
                response_length=0,
                exception=Exception(f"HTTP {response.status_code}"),
                context=self.context()
            )
            return
        
        try:
            body = response.json()
            order_id = body.get("order_id")
            
            if not order_id:
                events.request.fire(
                    request_type="EDA_E2E",
                    name="Order E2E Flow [EDA]",
                    response_time=0,
                    response_length=0,
                    exception=Exception("No order_id in response"),
                    context=self.context()
                )
                return
            
            # Wait for the final event (this is the async processing time)
            success, data = self.eda_listener.wait_for_order(order_id, timeout=60.0)
            
            # Calculate TOTAL E2E latency (POST + async processing + event)
            total_time_ms = (time.time() - e2e_start) * 1000
            
            # Fire custom event with E2E timing
            if success:
                events.request.fire(
                    request_type="EDA_E2E",
                    name="Order E2E Flow [EDA]",
                    response_time=total_time_ms,
                    response_length=len(str(data)),
                    exception=None,
                    context=self.context()
                )
            else:
                reason = data.get("reason", "unknown")
                events.request.fire(
                    request_type="EDA_E2E",
                    name="Order E2E Flow [EDA]",
                    response_time=total_time_ms,
                    response_length=0,
                    exception=Exception(f"Order failed: {reason}"),
                    context=self.context()
                )
                    
        except Exception as e:
            # Fire failure event
            events.request.fire(
                request_type="EDA_E2E",
                name="Order E2E Flow [EDA]",
                response_time=(time.time() - e2e_start) * 1000,
                response_length=0,
                exception=e,
                context=self.context()
            )


# ============================================================================
# Programmatic Test Runner with Enhanced CSV Export
# ============================================================================

def run_load_test(user_class, users, spawn_rate, run_time, host):
    """
    Run a single load test scenario programmatically.
    
    Args:
        user_class: RequestResponseUser or EventDrivenUser
        users: Number of concurrent users
        spawn_rate: Users spawned per second
        run_time: Test duration in seconds
        host: Base URL for the service
    """
    # Setup environment
    env = Environment(user_classes=[user_class], host=host)
    env.create_local_runner()
    
    # Start test
    env.runner.start(user_count=users, spawn_rate=spawn_rate)
    
    # Run for specified time
    gevent.spawn(stats_printer(env.stats))
    gevent.spawn(stats_history, env.runner)
    
    # Wait for test duration
    gevent.spawn_later(run_time, lambda: env.runner.quit())
    env.runner.greenlet.join()
    
    # Return stats
    return env.stats


def export_detailed_stats_to_csv(stats, filename, test_config):
    """
    Export comprehensive Locust stats to CSV with metadata.
    Each endpoint gets its own row with all metrics.
    """
    with open(filename, 'w', newline='') as f:
        writer = csv.writer(f)
        
        # Header
        writer.writerow([
            'Architecture',
            'Users',
            'Spawn Rate',
            'Run Time (s)',
            'Method',
            'Name',
            'Total Requests',
            'Failures',
            'Success Rate (%)',
            'Requests/sec',
            'Median (ms)',
            'Average (ms)',
            'Min (ms)',
            'Max (ms)',
            'P90 (ms)',
            'P95 (ms)',
            'P99 (ms)'
        ])
        
        # Determine architecture from filename or user class
        arch = "Event-Driven" if "eda" in filename.lower() else "Request-Response"
        
        # Write a row for each unique endpoint
        for entry in stats.entries.values():
            success_rate = 0
            if entry.num_requests > 0:
                success_rate = ((entry.num_requests - entry.num_failures) / entry.num_requests) * 100
            
            writer.writerow([
                arch,
                test_config.get('users', 'N/A'),
                test_config.get('spawn_rate', 'N/A'),
                test_config.get('run_time', 'N/A'),
                entry.method,
                entry.name,
                entry.num_requests,
                entry.num_failures,
                round(success_rate, 2),
                round(entry.total_rps, 2),
                round(entry.median_response_time, 2),
                round(entry.avg_response_time, 2),
                round(entry.min_response_time, 2) if entry.min_response_time else 0,
                round(entry.max_response_time, 2) if entry.max_response_time else 0,
                round(entry.get_response_time_percentile(0.90), 2) if entry.num_requests > 0 else 0,
                round(entry.get_response_time_percentile(0.95), 2) if entry.num_requests > 0 else 0,
                round(entry.get_response_time_percentile(0.99), 2) if entry.num_requests > 0 else 0,
            ])
        
        # Also write aggregate row if multiple endpoints exist
        if len(stats.entries) > 1:
            total_requests = stats.total.num_requests
            total_failures = stats.total.num_failures
            success_rate = ((total_requests - total_failures) / total_requests * 100) if total_requests > 0 else 0
            
            writer.writerow([
                arch,
                test_config.get('users', 'N/A'),
                test_config.get('spawn_rate', 'N/A'),
                test_config.get('run_time', 'N/A'),
                'AGGREGATE',
                'All Requests',
                total_requests,
                total_failures,
                round(success_rate, 2),
                round(stats.total.total_rps, 2),
                round(stats.total.median_response_time, 2),
                round(stats.total.avg_response_time, 2),
                round(stats.total.min_response_time, 2) if stats.total.min_response_time else 0,
                round(stats.total.max_response_time, 2) if stats.total.max_response_time else 0,
                round(stats.total.get_response_time_percentile(0.90), 2) if total_requests > 0 else 0,
                round(stats.total.get_response_time_percentile(0.95), 2) if total_requests > 0 else 0,
                round(stats.total.get_response_time_percentile(0.99), 2) if total_requests > 0 else 0,
            ])


if __name__ == "__main__":
    """
    Run comprehensive comparison tests between RR and EDA architectures.
    
    Usage:
        # Run with Locust CLI (recommended):
        locust -f locustfile.py --users 100 --spawn-rate 10 --run-time 60s --host http://localhost:5000
        
        # Or run programmatically for batch testing:
        python locustfile.py
    """
    setup_logging("INFO", None)
    
    # Test scenarios
    test_configs = [
        {"users": 50, "spawn_rate": 10, "run_time": 30},
        {"users": 100, "spawn_rate": 20, "run_time": 30},
        {"users": 200, "spawn_rate": 40, "run_time": 30},
    ]
    
    for config in test_configs:
        print(f"\n{'='*70}")
        print(f"Testing Request-Response: {config['users']} users")
        print(f"{'='*70}")
        
        rr_stats = run_load_test(
            user_class=RequestResponseUser,
            users=config['users'],
            spawn_rate=config['spawn_rate'],
            run_time=config['run_time'],
            host="http://localhost:5000"
        )
        
        export_detailed_stats_to_csv(
            rr_stats, 
            f"rr_{config['users']}users.csv",
            config
        )
        
        print(f"\n{'='*70}")
        print(f"Testing Event-Driven: {config['users']} users")
        print(f"{'='*70}")
        
        eda_stats = run_load_test(
            user_class=EventDrivenUser,
            users=config['users'],
            spawn_rate=config['spawn_rate'],
            run_time=config['run_time'],
            host="http://localhost:8001"
        )
        
        export_detailed_stats_to_csv(
            eda_stats, 
            f"eda_{config['users']}users.csv",
            config
        )
        
        # Brief pause between tests
        time.sleep(2)
    
    print("\n✅ All tests completed! Check the CSV files for detailed results.")
    print("\n📊 CSV Format:")
    print("   - Each row represents one endpoint type")
    print("   - For EDA: you'll see 'POST /orders [EDA]' and 'Order E2E Flow [EDA]'")
    print("   - For RR: you'll see 'POST /orders [RR]'")
    print("   - AGGREGATE row shows combined statistics")
    print("\n💡 Tip: Run 'locust -f locustfile.py --web' for interactive testing with live graphs!")
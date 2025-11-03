# metrics.py (rewritten)

import requests
import time
import statistics
import threading
from collections import defaultdict
import os
import csv
import numpy as np
import matplotlib
matplotlib.use("Agg")  # prevent Tkinter-related crashes
import matplotlib.pyplot as plt

# Optional system/container stats (left intact so your dashboards don't break)
import psutil  # noqa: F401
import docker  # noqa: F401

# --- Event bus import that works with both layouts (shared.event_bus or local event_bus.py)
try:
    from event_bus import EventBus
except Exception:
    from event_bus import EventBus


class MetricsCollector:
    """
    Metrics collector that can measure RR (request-response) or EDA (event-driven async) flows.

    RR  : success == 200 OK (or 2xx), time = HTTP round-trip.
    EDA : success/finality == receipt of 'order.final' with matching order_id,
          time = from HTTP POST start to arrival of that event.
    """
    def __init__(self, base_url: str, architecture: str = "rr", eda_wait_timeout: float = 60.0):
        assert architecture in ("rr", "eda"), "architecture must be 'rr' or 'eda'"
        self.base_url = base_url.rstrip("/")
        self.architecture = architecture
        self.eda_wait_timeout = eda_wait_timeout

        # Aggregates
        self.response_times = []
        self.errors = defaultdict(int)
        self.successes = 0
        self.start_time = None

        # --- EDA-only state
        self._eda_enabled = (architecture == "eda")
        self._event_bus = None
        self._consumer_thread = None
        self._queue_name = f"metrics_collector_{os.getpid()}_{int(time.time()*1000)}"
        # order_id -> threading.Event used to signal finality
        self._final_events = {}
        # order_id -> dict: {"success": bool, "data": dict}
        self._final_results = {}
        # Lock to protect dicts above
        self._lock = threading.Lock()

        if self._eda_enabled:
            self._init_event_consumer()

    # --------------------
    # EDA wiring
    # --------------------
    def _init_event_consumer(self):
        """Start a background consumer listening for 'order.final' and signaling waiters."""
        def handle_event(event):
            try:
                if event.get("event_type") != "order.final":
                    return
                data = event.get("data", {}) or {}
                order_id = data.get("order_id")
                if not order_id:
                    return

                # Infer success if payment_id present (matches payment.processed path)
                success = "payment_id" in data

                with self._lock:
                    self._final_results[order_id] = {"success": success, "data": data}
                    evt = self._final_events.get(order_id)
                    if evt:
                        evt.set()
            except Exception:
                # We don't crash the consumer
                pass

        def consumer():
            bus = EventBus()
            self._event_bus = bus
            bus.connect()
            bus.subscribe(["order.final"], handle_event, queue_name=self._queue_name)
            bus.start_consuming()

        self._consumer_thread = threading.Thread(target=consumer, name="EDAConsumer", daemon=True)
        self._consumer_thread.start()

    # --------------------
    # Common helpers
    # --------------------
    def _record_error(self, key: str):
        self.errors[key] += 1

    # --------------------
    # Work units
    # --------------------
    def _send_order_rr(self, order_data):
        """
        RR flow: measure request round-trip and treat 2xx as success/failure by status code.
        """
        start = time.time()
        try:
            response = requests.post(f"{self.base_url}/orders", json=order_data, timeout=30)
            elapsed = time.time() - start

            if 200 <= response.status_code < 300:
                self.successes += 1
                self.response_times.append(elapsed)
                return response.json()
            else:
                self._record_error(str(response.status_code))
        except requests.exceptions.Timeout:
            self._record_error("timeout")
        except Exception as e:
            self._record_error(type(e).__name__)
        return None

    def _send_order_eda(self, order_data):
        """
        EDA flow: start time at POST, then wait until we see `order.final` for this order_id.
        Success only when final event has 'payment_id'; otherwise record a failure.
        """
        post_start = time.time()
        order_id = None

        try:
            # Order Service returns 202 + {"order_id": "...", "status": "pending", ...}
            resp = requests.post(f"{self.base_url}/orders", json=order_data, timeout=30)
            # Even non-2xx will likely not enqueue any events, so treat non-2xx as immediate error.
            if not (200 <= resp.status_code < 300):
                self._record_error(str(resp.status_code))
                return None

            body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
            order_id = body.get("order_id")
            if not order_id:
                # If server didn't return an order_id, we cannot correlate -> count as error
                self._record_error("missing_order_id")
                return None

            # Register waiter for this order_id
            with self._lock:
                evt = self._final_events.get(order_id)
                if evt is None:
                    evt = threading.Event()
                    self._final_events[order_id] = evt

            # Wait for final event (with timeout)
            signaled = evt.wait(timeout=self.eda_wait_timeout)
            if not signaled:
                self._record_error("eda_timeout")
                return None

            # We were signaled; compute full E2E latency + evaluate success
            elapsed = time.time() - post_start
            with self._lock:
                res = self._final_results.get(order_id) or {}
            success = bool(res.get("success"))

            if success:
                self.successes += 1
                self.response_times.append(elapsed)
                return {"order_id": order_id, "status": "completed", "elapsed": elapsed, "final": res.get("data", {})}
            else:
                # We still consider this a *final* (failed) order, for error stats
                # Try to bucket by reason if available
                final_data = res.get("data") or {}
                reason = final_data.get("reason", "failed")
                self._record_error(reason)
                return None

        except requests.exceptions.Timeout:
            self._record_error("timeout")
        except Exception as e:
            self._record_error(type(e).__name__)
        finally:
            # Cleanup waiter/result to avoid leaks in long runs
            if order_id:
                with self._lock:
                    self._final_events.pop(order_id, None)
                    # keep _final_results in case external wants to inspect; or clean:
                    self._final_results.pop(order_id, None)

        return None

    def send_order(self, order_data):
        if self.architecture == "rr":
            return self._send_order_rr(order_data)
        else:
            return self._send_order_eda(order_data)

    # --------------------
    # Load test harness
    # --------------------
    def run_load_test(self, num_requests, concurrent_users):
        """Run load test with specified concurrency."""
        self.start_time = time.time()

        def worker(requests_per_worker, worker_id):
            for i in range(requests_per_worker):
                order = {
                    "customer_id": f"customer_{worker_id}_{i}",
                    "items": [
                        {"item_id": "item_001", "name": "Laptop", "quantity": 1, "price": 1200}
                    ]
                }
                self.send_order(order)

        # Distribute roughly evenly
        requests_per_worker = max(1, num_requests // max(1, concurrent_users))
        threads = []
        for w in range(concurrent_users):
            t = threading.Thread(target=worker, args=(requests_per_worker, w), daemon=True)
            threads.append(t)
            t.start()
        for t in threads:
            t.join()

    # --------------------
    # Optional: docker stats (left intact)
    # --------------------
    def get_docker_stats(self, container_names):
        """Get CPU and memory stats from Docker containers (unchanged)."""
        import docker
        client = docker.from_env()
        stats = {}
        for name in container_names:
            try:
                container = client.containers.get(name)
                container_stats = container.stats(stream=False)

                cpu_delta = (
                    container_stats["cpu_stats"]["cpu_usage"]["total_usage"]
                    - container_stats["precpu_stats"]["cpu_usage"]["total_usage"]
                )
                system_delta = (
                    container_stats["cpu_stats"]["system_cpu_usage"]
                    - container_stats["precpu_stats"]["system_cpu_usage"]
                )
                cpu_percent = (cpu_delta / system_delta) * 100.0 if system_delta else 0.0

                mem_usage = container_stats["memory_stats"]["usage"] / (1024 * 1024)  # MB
                mem_limit = container_stats["memory_stats"]["limit"] / (1024 * 1024)  # MB

                stats[name] = {
                    "cpu_percent": cpu_percent,
                    "memory_mb": mem_usage,
                    "memory_limit_mb": mem_limit,
                    "memory_percent": (mem_usage / mem_limit * 100) if mem_limit else 0.0,
                }
            except Exception as e:
                print(f"Error getting stats for {name}: {e}")
        return stats

    # --------------------
    # Reporting
    # --------------------
    def print_report(self):
        """Print comprehensive metrics report."""
        total_time = max(1e-9, time.time() - self.start_time)
        total_requests = self.successes + sum(self.errors.values())

        print("\n" + "=" * 70)
        print(f"PERFORMANCE METRICS REPORT — {self.architecture.upper()}")
        print("=" * 70)

        # Throughput
        print(f"\nThroughput:")
        print(f"  Total requests: {total_requests}")
        print(f"  Successful: {self.successes}")
        print(f"  Failed: {sum(self.errors.values())}")
        sr = (self.successes / total_requests * 100) if total_requests else 0.0
        print(f"  Success rate: {sr:.2f}%")
        print(f"  Requests/second: {total_requests / total_time:.2f}")
        print(f"  Total time: {total_time:.2f}s")

        # Response times
        if self.response_times:
            print(f"\nResponse Time (seconds) [{self.architecture}]:")
            print(f"  Mean: {statistics.mean(self.response_times):.3f}")
            print(f"  Median: {statistics.median(self.response_times):.3f}")
            print(f"  Min: {min(self.response_times):.3f}")
            print(f"  Max: {max(self.response_times):.3f}")

            sorted_times = sorted(self.response_times)
            p95_idx = max(0, int(len(sorted_times) * 0.95) - 1)
            p99_idx = max(0, int(len(sorted_times) * 0.99) - 1)
            print(f"  P95: {sorted_times[p95_idx]:.3f}")
            print(f"  P99: {sorted_times[p99_idx]:.3f}")

        # Errors
        if self.errors:
            print(f"\nErrors:")
            for error_type, count in self.errors.items():
                print(f"  {error_type}: {count}")

        print("=" * 70 + "\n")


# --------------------
# Plot helper (kept as you had, slight safety tweaks)
# --------------------
def plot_response_times(response_times, title, output_file):
    if not response_times:
        print(f"No response times recorded for {title}.")
        return

    p50 = np.percentile(response_times, 50)
    p95 = np.percentile(response_times, 95)
    p99 = np.percentile(response_times, 99)

    plt.figure(figsize=(10, 6))
    plt.hist(response_times, bins=50, edgecolor="black", alpha=0.7)
    plt.axvline(p50, linestyle="--", linewidth=2, label=f"P50 = {p50:.3f}s")
    plt.axvline(p95, linestyle="--", linewidth=2, label=f"P95 = {p95:.3f}s")
    plt.axvline(p99, linestyle="--", linewidth=2, label=f"P99 = {p99:.3f}s")

    plt.title(title)
    plt.xlabel("Response Time (seconds)")
    plt.ylabel("Number of Requests")
    plt.legend()
    plt.grid(True, alpha=0.3)

    os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)
    plt.savefig(output_file, dpi=300, bbox_inches="tight")
    plt.close()

    print(f"✅ Distribution plot saved as '{output_file}'")


# --------------------
# CLI runner (kept, but now passes architecture explicitly)
# --------------------
if __name__ == "__main__":
    requests_list = [1, 10, 20, 30, 40, 50]
    users_list = [50, 100, 150, 200, 250, 300]
    test_scenarios = [(n, u) for n in requests_list for u in users_list]

    rr_results = []
    eda_results = []

    plots_dir = "plots"

    for num_requests, concurrent_users in test_scenarios:
        print(f"\n=== Testing REQUEST-RESPONSE ({num_requests} requests, {concurrent_users} users) ===")
        rr_collector = MetricsCollector("http://localhost:5000", architecture="rr")
        rr_collector.run_load_test(num_requests=num_requests, concurrent_users=concurrent_users)
        rr_collector.print_report()

        rr_results.append({
            "Architecture": "Request-Response",
            "Requests": num_requests,
            "Users": concurrent_users,
            "Throughput (req/s)": round((rr_collector.successes + sum(rr_collector.errors.values())) / max(1e-9, (time.time() - rr_collector.start_time)), 2),
            "Success Rate (%)": round((rr_collector.successes / max(1, (rr_collector.successes + sum(rr_collector.errors.values())))) * 100, 2) if (rr_collector.successes + sum(rr_collector.errors.values())) else 0.0,
            "Mean (s)": round(statistics.mean(rr_collector.response_times), 3) if rr_collector.response_times else 0.0,
            "P50 (s)": round(np.percentile(rr_collector.response_times, 50), 3) if rr_collector.response_times else 0.0,
            "P95 (s)": round(np.percentile(rr_collector.response_times, 95), 3) if rr_collector.response_times else 0.0,
        })

        rr_filename = os.path.join(plots_dir, f"{num_requests}req_{concurrent_users}users_rr.png")
        plot_response_times(rr_collector.response_times, f"Request-Response — {num_requests} req, {concurrent_users} users", rr_filename)

        time.sleep(1)

        print(f"\n=== Testing EVENT-DRIVEN ({num_requests} requests, {concurrent_users} users) ===")
        eda_collector = MetricsCollector("http://localhost:8001", architecture="eda", eda_wait_timeout=90.0)
        eda_collector.run_load_test(num_requests=num_requests, concurrent_users=concurrent_users)
        eda_collector.print_report()

        eda_results.append({
            "Architecture": "Event-Driven",
            "Requests": num_requests,
            "Users": concurrent_users,
            "Throughput (req/s)": round((eda_collector.successes + sum(eda_collector.errors.values())) / max(1e-9, (time.time() - eda_collector.start_time)), 2),
            "Success Rate (%)": round((eda_collector.successes / max(1, (eda_collector.successes + sum(eda_collector.errors.values())))) * 100, 2) if (eda_collector.successes + sum(eda_collector.errors.values())) else 0.0,
            "Mean (s)": round(statistics.mean(eda_collector.response_times), 3) if eda_collector.response_times else 0.0,
            "P50 (s)": round(np.percentile(eda_collector.response_times, 50), 3) if eda_collector.response_times else 0.0,
            "P95 (s)": round(np.percentile(eda_collector.response_times, 95), 3) if eda_collector.response_times else 0.0,
        })

        eda_filename = os.path.join(plots_dir, f"{num_requests}req_{concurrent_users}users_eda.png")
        plot_response_times(eda_collector.response_times, f"Event-Driven — {num_requests} req, {concurrent_users} users", eda_filename)

        time.sleep(1)

    rr_output_file = "rr_results.csv"
    with open(rr_output_file, mode="w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rr_results[0].keys())
        writer.writeheader()
        writer.writerows(rr_results)

    eda_output_file = "eda_results.csv"
    with open(eda_output_file, mode="w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=eda_results[0].keys())
        writer.writeheader()
        writer.writerows(eda_results)

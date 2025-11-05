import requests
import time
import statistics
import threading
from collections import defaultdict
import psutil
import docker

class MetricsCollector:
    def __init__(self, base_url):
        self.base_url = base_url
        self.response_times = []
        self.errors = defaultdict(int)
        self.successes = 0
        self.start_time = None
        
    def send_order(self, order_data):
        start = time.time()
        try:
            response = requests.post(
                f"{self.base_url}/orders",
                json=order_data,
                timeout=30
            )
            elapsed = time.time() - start
            
            if response.status_code in [200, 202]:
                self.successes += 1
                self.response_times.append(elapsed)
                return response.json()
            else:
                self.errors[response.status_code] += 1
                
        except requests.exceptions.Timeout:
            self.errors['timeout'] += 1
        except Exception as e:
            self.errors[str(type(e).__name__)] += 1
            
        return None
    
    def run_load_test(self, num_requests, concurrent_users):
        """Run load test with specified concurrency"""
        self.start_time = time.time()
        
        def worker(requests_per_worker):
            for i in range(requests_per_worker):
                order = {
                    "customer_id": f"customer_{i}",
                    "items": [
                        {
                            "item_id": "item_001",
                            "name": "Laptop",
                            "quantity": 1,
                            "price": 1200
                        }
                    ]
                }
                self.send_order(order)
        
        requests_per_worker = num_requests // concurrent_users if (num_requests // concurrent_users) != 0 else num_requests
        threads = []
        
        for _ in range(concurrent_users):
            t = threading.Thread(target=worker, args=(requests_per_worker,))
            threads.append(t)
            t.start()
        
        for t in threads:
            t.join()
    
    def get_docker_stats(self, container_names):
        """Get CPU and memory stats from Docker containers"""
        client = docker.from_env()
        stats = {}
        
        for name in container_names:
            try:
                container = client.containers.get(name)
                container_stats = container.stats(stream=False)
                
                # Calculate CPU percentage
                cpu_delta = container_stats['cpu_stats']['cpu_usage']['total_usage'] - \
                           container_stats['precpu_stats']['cpu_usage']['total_usage']
                system_delta = container_stats['cpu_stats']['system_cpu_usage'] - \
                              container_stats['precpu_stats']['system_cpu_usage']
                cpu_percent = (cpu_delta / system_delta) * 100.0
                
                # Memory usage
                mem_usage = container_stats['memory_stats']['usage'] / (1024 * 1024)  # MB
                mem_limit = container_stats['memory_stats']['limit'] / (1024 * 1024)  # MB
                
                stats[name] = {
                    'cpu_percent': cpu_percent,
                    'memory_mb': mem_usage,
                    'memory_limit_mb': mem_limit,
                    'memory_percent': (mem_usage / mem_limit) * 100
                }
            except Exception as e:
                print(f"Error getting stats for {name}: {e}")
        
        return stats
    
    def print_report(self):
        """Print comprehensive metrics report"""
        total_time = time.time() - self.start_time
        total_requests = self.successes + sum(self.errors.values())
        
        print("\n" + "="*70)
        print("PERFORMANCE METRICS REPORT")
        print("="*70)
        
        # Throughput
        print(f"\nThroughput:")
        print(f"  Total requests: {total_requests}")
        print(f"  Successful: {self.successes}")
        print(f"  Failed: {sum(self.errors.values())}")
        print(f"  Success rate: {(self.successes/total_requests*100):.2f}%")
        print(f"  Requests/second: {total_requests/total_time:.2f}")
        print(f"  Total time: {total_time:.2f}s")
        
        # Response times
        if self.response_times:
            print(f"\nResponse Time (seconds):")
            print(f"  Mean: {statistics.mean(self.response_times):.3f}")
            print(f"  Median: {statistics.median(self.response_times):.3f}")
            print(f"  Min: {min(self.response_times):.3f}")
            print(f"  Max: {max(self.response_times):.3f}")
            
            sorted_times = sorted(self.response_times)
            p95_idx = int(len(sorted_times) * 0.95)
            p99_idx = int(len(sorted_times) * 0.99)
            print(f"  P95: {sorted_times[p95_idx]:.3f}")
            print(f"  P99: {sorted_times[p99_idx]:.3f}")
        
        # Errors
        if self.errors:
            print(f"\nErrors:")
            for error_type, count in self.errors.items():
                print(f"  {error_type}: {count}")
        
        print("="*70 + "\n")


import os
import csv
from tabulate import tabulate
import numpy as np
import matplotlib
matplotlib.use("Agg")  # 👈 prevents Tkinter-related crashes
import matplotlib.pyplot as plt

def plot_response_times(response_times, title, output_file):
    if not response_times:
        print(f"No response times recorded for {title}.")
        return

    # Calculate percentiles
    p50 = np.percentile(response_times, 50)
    p95 = np.percentile(response_times, 95)
    p99 = np.percentile(response_times, 99)

    # Plot histogram
    plt.figure(figsize=(10, 6))
    plt.hist(response_times, bins=50, color='skyblue', edgecolor='black', alpha=0.7)
    plt.axvline(p50, color='green', linestyle='--', linewidth=2, label=f'P50 = {p50:.3f}s')
    plt.axvline(p95, color='orange', linestyle='--', linewidth=2, label=f'P95 = {p95:.3f}s')
    plt.axvline(p99, color='red', linestyle='--', linewidth=2, label=f'P99 = {p99:.3f}s')

    # Labels and title
    plt.title(title)  # <-- use the provided title
    plt.xlabel("Response Time (seconds)")
    plt.ylabel("Number of Requests")
    plt.legend()
    plt.grid(True, alpha=0.3)

    # Ensure folder exists and save to the requested file path
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    plt.savefig(output_file, dpi=300, bbox_inches="tight")
    plt.close()

    print(f"✅ Distribution plot saved as '{output_file}'")


if __name__ == "__main__":
    requests_list = [1, 10, 20, 30, 40, 50]
    users_list = [50, 100, 150, 200, 250, 300]
    test_scenarios = [(num_requests, concurrent_users) for num_requests in requests_list for concurrent_users in users_list]

    rr_results = []
    eda_results = []

    # Folder for per-scenario plots
    plots_dir = "plots"

    for num_requests, concurrent_users in test_scenarios:
        print(f"\n=== Testing REQUEST-RESPONSE ({num_requests} requests, {concurrent_users} users) ===")
        rr_collector = MetricsCollector("http://localhost:5000")
        rr_collector.run_load_test(num_requests=num_requests, concurrent_users=concurrent_users)
        rr_collector.print_report()

        rr_results.append({
            "Architecture": "Request-Response",
            "Requests": num_requests,
            "Users": concurrent_users,
            "Throughput (req/s)": round((rr_collector.successes + sum(rr_collector.errors.values())) / (time.time() - rr_collector.start_time), 2),
            "Success Rate (%)": round((rr_collector.successes / (rr_collector.successes + sum(rr_collector.errors.values()))) * 100, 2) if rr_collector.successes else 0.0,
            "Mean (s)": round(statistics.mean(rr_collector.response_times), 3) if rr_collector.response_times else 0,
            "P50 (s)": round(np.percentile(rr_collector.response_times, 50), 3) if rr_collector.response_times else 0,
            "P95 (s)": round(np.percentile(rr_collector.response_times, 95), 3) if rr_collector.response_times else 0,
        })

        # Save per-scenario RR plot
        rr_filename = os.path.join(
            plots_dir, f"{num_requests}req_{concurrent_users}users_rr.png"
        )
        plot_response_times(
            rr_collector.response_times,
            f"Request-Response — {num_requests} req, {concurrent_users} users",
            rr_filename
        )

        # Pause between tests
        time.sleep(1)

        print(f"\n=== Testing EVENT-DRIVEN ({num_requests} requests, {concurrent_users} users) ===")
        eda_collector = MetricsCollector("http://localhost:8001")
        eda_collector.run_load_test(num_requests=num_requests, concurrent_users=concurrent_users)
        eda_collector.print_report()

        eda_results.append({
            "Architecture": "Event-Driven",
            "Requests": num_requests,
            "Users": concurrent_users,
            "Throughput (req/s)": round((eda_collector.successes + sum(eda_collector.errors.values())) / (time.time() - eda_collector.start_time), 2),
            "Success Rate (%)": round((eda_collector.successes / (eda_collector.successes + sum(eda_collector.errors.values()))) * 100, 2) if eda_collector.successes else 0.0,
            "Mean (s)": round(statistics.mean(eda_collector.response_times), 3) if eda_collector.response_times else 0,
            "P50 (s)": round(np.percentile(eda_collector.response_times, 50), 3) if eda_collector.response_times else 0,
            "P95 (s)": round(np.percentile(eda_collector.response_times, 95), 3) if eda_collector.response_times else 0,
        })

        # Save per-scenario EDA plot
        eda_filename = os.path.join(
            plots_dir, f"{num_requests}req_{concurrent_users}users_eda.png"
        )
        plot_response_times(
            eda_collector.response_times,
            f"Event-Driven — {num_requests} req, {concurrent_users} users",
            eda_filename
        )

        # Short delay between scenarios
        time.sleep(1)

    # Write results to CSV
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

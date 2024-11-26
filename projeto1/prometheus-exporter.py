from prometheus_client import start_http_server, Gauge, Summary
import requests
import time
from time import sleep

# Metrics
availability_metric = Gauge('service_availability', 'Availability of the service (reachable or not)', ['service'])
health_metric = Gauge('service_health', 'Health status of the reachable service (HTTP 200 = healthy)', ['service'])
response_time_metric = Summary('service_response_time_seconds', 'Response time of the service in seconds', ['service'])

# List of services to monitor
SERVICES = ['http://127.0.0.1:5001']

def check_service_health():
    for service in SERVICES:
        try:
            start_time = time.time()  # Record start time
            response = requests.get(service, timeout=5)
            elapsed_time = time.time() - start_time  # Calculate response time

            # Record response time
            response_time_metric.labels(service=service).observe(elapsed_time)

            # Update availability and health metrics
            availability_metric.labels(service=service).set(1.0)  # Service is reachable
            
            if response.status_code == 200:
                health_metric.labels(service=service).set(1.0)  # Healthy (overwrite any previous status)
            else:
                health_metric.labels(service=service).set(0.0)  # Unhealthy, but reset any previous health status

        except requests.exceptions.RequestException as e:
            # Service is unreachable
            availability_metric.labels(service=service).set(0.0)
            health_metric.labels(service=service).set(0.0)  # Reset health status when unreachable
            print(f"Error checking service {service}: {e}")

if __name__ == '__main__':
    # Start the HTTP server to expose the metrics
    start_http_server(8000)
    print("Prometheus exporter is running on port 8000...")

    # Periodically check service health
    while True:
        check_service_health()
        sleep(10)


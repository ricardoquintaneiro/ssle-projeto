import requests
import json
import time
import logging

# Configuration
PROMETHEUS_URL = "http://127.0.0.1:9090/api/v1/alerts"
LOG_FILE_PATH = "/var/log/alerts/prometheus_alerts.log"  # Log file that Wazuh will monitor
POLL_INTERVAL = 10  # seconds

# Configure logging
logging.basicConfig(filename=LOG_FILE_PATH, level=logging.INFO, format='%(message)s')

def get_prometheus_alerts():
    try:
        response = requests.get(PROMETHEUS_URL, timeout=5)
        response.raise_for_status()
        alerts = response.json().get("data", {}).get("alerts", [])
        return alerts
    except requests.exceptions.RequestException as e:
        print(f"Error querying Prometheus: {e}")
        return []

def log_alert_to_file(alert):
    log_message = {
        "alertname": alert["labels"]["alertname"],
        "severity": alert["labels"].get("severity", "unknown"),
        "description": alert["annotations"]["description"].replace("\n",""),
        "summary": alert["annotations"]["summary"].replace("\n", ""),
        "instance": alert["labels"].get("instance", "unknown"),
        "state": alert["state"],
        "activeAt": alert.get("activeAt")
    }
    logging.info(json.dumps(log_message))  # Log the alert as a JSON string

def main():
    while True:
        alerts = get_prometheus_alerts()
        for alert in alerts:
            # Only log alerts that are "firing", ignore "pending" state
            if alert["state"] == "firing":
                log_alert_to_file(alert)
        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    main()


import threading

import pika
import requests
from flask import Flask, jsonify, request
from flask_restful import Api, Resource
import logging
from logging.handlers import RotatingFileHandler

app = Flask(__name__)
api = Api(app)

SERVICE_REGISTRY_URL = "http://10.151.101.15:5000/services"
current_temperature = None

log_file_path = "/var/log/temp_c/access.log"
log_format = '%(h)s %(l)s %(u)s [%(t)s] "%(r)s" %(s)s %(b)s "%(referer)s" "%(user_agent)s"'

# Custom log formatter to match Apache2 log format
class ApacheLogFormatter(logging.Formatter):
    def format(self, record):
        record.h = record.__dict__.get('ip', '-')
        record.l = '-'
        record.u = '-'
        record.t = self.formatTime(record, "%d/%b/%Y:%H:%M:%S %z")
        record.r = record.__dict__.get('request', '-')
        record.s = record.__dict__.get('status_code', '-')
        record.b = record.__dict__.get('content_length', '-')
        record.referer = record.__dict__.get('referer', '-')
        record.user_agent = record.__dict__.get('user_agent', '-')
        return super().format(record)



handler = RotatingFileHandler(log_file_path, maxBytes=10*1024*1024, backupCount=5)
handler.setFormatter(ApacheLogFormatter(log_format))
app.logger.addHandler(handler)
app.logger.setLevel(logging.INFO)

def log_request(response):
    headers = dict(request.headers)
    app.logger.info(
        '',
        extra={
            'ip': request.remote_addr,
            'request': f"{request.method} {request.path} {request.environ.get('SERVER_PROTOCOL')}",
            'status_code': response.status_code,
            'content_length': response.content_length or '-',
            'referer': headers.get('Referer', '-'),
            'user_agent': headers.get('User-Agent', '-'),
        },
    )
    return response

# Apply log_request function after each request
app.after_request(log_request)

def register_service() -> None:
    payload = {"name": "Celsius", "url": "http://10.151.101.196:5001/"}
    try:
        response = requests.post(SERVICE_REGISTRY_URL, json=payload)
        response.raise_for_status()
        print("Service registered successfully.")
    except requests.exceptions.RequestException as e:
        print(f"An error occurred registering service: {e}")


def consume_temperature_c():
    global current_temperature

    credentials = pika.PlainCredentials("ricardo", "ricardo")
    connection = pika.BlockingConnection(pika.ConnectionParameters("10.151.101.144", credentials=credentials))
    channel = connection.channel()
    channel.queue_declare(queue="temperaturas")
    channel.queue_bind(
        exchange="temperaturas", queue="temperaturas", routing_key="temperatura_c"
    )

    def callback(ch, method, properties, body):
        global current_temperature
        current_temperature = float(body.decode())
        print(f"Temperature received: {current_temperature}°C")

    channel.basic_consume(
        queue="temperaturas", on_message_callback=callback, auto_ack=True
    )
    print("Waiting for temperature data...")
    channel.start_consuming()


class TempC(Resource):
    def get(self):
        if current_temperature is not None:
            return {"temp_c": current_temperature}
        return {"message": "No data available."}, 503


api.add_resource(TempC, "/")

if __name__ == "__main__":
    consumer_thread = threading.Thread(target=consume_temperature_c)
    consumer_thread.daemon = True
    consumer_thread.start()

    register_service()
    app.run(host="0.0.0.0", port=5001)

from flask import Flask, request, jsonify
from flask_restful import Resource, Api
import logging
from logging.handlers import RotatingFileHandler

app = Flask(__name__)
api = Api(app)

services = {}
urls = {}
count = 0

log_file_path = "/var/log/registry/access.log"
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

class Service(Resource):

    def get(self, service_id: int):
        # check if service_id is integer
        if not isinstance(service_id, int):
            return {"error": "Invalid service ID."}, 400
        service = services.get(service_id)
        if service is None:
            return {"error": "Service not found."}, 404
        url = urls.get(service)
        return url
    def delete(self, service_id: int):
        # Check if the service exists
        service = services.pop(service_id, None)
        if service is None:
            return {"error": "Service not found."}, 404
        # Remove the URL associated with the service name
        urls.pop(service, None)
        return {"message": f"Service with ID {service_id} deleted successfully."}, 200


class Services(Resource):
    def get(self):
        return services
    def post(self):
        global count
        count += 1
        name = request.json.get("name")
        services[count] = name
        urls[name] = request.json.get("url")
        return {"id": count, "name": name, "url": urls[name]}

api.add_resource(Service, "/services/<int:service_id>")
api.add_resource(Services, "/services")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)

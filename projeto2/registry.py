from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed448
from flask import Flask, request
from flask_restful import Api, Resource

from bank import verify_message_hmac

app = Flask(__name__)
api = Api(app)

services = {}


def is_valid_public_key(public_key_str):
    try:
        public_key = serialization.load_pem_public_key(public_key_str.encode('utf-8'))
        return isinstance(public_key, ed448.Ed448PublicKey)
    except Exception as e:
        return False


class Service(Resource):
    def get(self, service_id: int):
        if not isinstance(service_id, int):
            return {"error": "Invalid service ID."}, 400
        service = services.get(service_id)
        if service is None:
            return {"error": "Service not found."}, 404
        name = service.get("name")
        url = service.get("url")
        public_key = service.get("public_key")
        return {"id": service_id, "name": name, "url": url, "public_key": public_key}

class Services(Resource):
    def get(self):
        return services
    def post(self):
        signature = request.json.pop("signature", None)
        if signature is None:
            return {"error": "Missing signature."}, 400
        if not isinstance(signature, str):
            return {"error": "Invalid signature format."}, 400
        if not verify_message_hmac(str(request.json), signature):
            return {"error": "Invalid signature."}, 400
        service_id = request.json.get("id")
        if service_id is None:
            return {"error": "Missing service ID."}, 400
        if not isinstance(service_id, int) or service_id <= 0:
            return {"error": "Invalid service ID."}, 400
        if service_id in services:
            return {"error": "Service already exists."}, 400
        name = request.json.get("name")
        if name is None:
            return {"error": "Missing service name."}, 400
        url = request.json.get("url")
        if url is None:
            return {"error": "Missing service URL."}, 400
        public_key = request.json.get("public_key")
        if public_key is None:
            return {"error": "Missing public key."}, 400
        if not is_valid_public_key(public_key):
            return {"error": "Invalid public key format."}, 400
        services[service_id] = {"name": name, "url": url, "public_key": public_key}
        return {"id": service_id, "name": name, "url": url, "public_key": public_key}, 201

api.add_resource(Service, "/services/<int:service_id>")
api.add_resource(Services, "/services")

if __name__ == "__main__":
    app.run(port=5000)

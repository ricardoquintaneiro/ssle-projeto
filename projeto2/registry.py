from flask import Flask, request
from flask_restful import Resource, Api

app = Flask(__name__)
api = Api(app)

services = {}

class Service(Resource):

    def get(self, service_id: int):
        # check if service_id is integer
        if not isinstance(service_id, int):
            return {"error": "Invalid service ID."}, 400
        service = services.get(service_id)
        if service is None:
            return {"error": "Service not found."}, 404
        url = service.get("url")
        return url

class Services(Resource):
    def get(self):
        return services
    def post(self):
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
        services[service_id] = {"name": name, "url": url}
        return {"id": service_id, "name": name, "url": url}, 201

api.add_resource(Service, "/services/<int:service_id>")
api.add_resource(Services, "/services")

if __name__ == "__main__":
    app.run(port=5000)

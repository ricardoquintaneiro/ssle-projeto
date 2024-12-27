import asyncio
import argparse
import json
import socket
import threading

import requests
from flask import Flask, request
from flask_restful import Api, Resource

app = Flask(__name__)
api = Api(app)

account_balances = {"Europe": 1000, "America": 2000, "Asia": 3000, "Africa": 4000, "Oceania": 5000}
bank_ids = {"Europe": 1, "America": 2, "Asia": 3, "Africa": 4, "Oceania": 5}

total_money = sum(account_balances.values())

SERVICE_REGISTRY_URL = "http://127.0.0.1:5000/services"
proposal_id = 0
accepted_proposal = None

def register_service() -> None:
    payload = {"id": bank_id, "name": f"Bank of {continent}", "url": f"http://127.0.0.1:{PORT}/"}
    try:
        response = requests.post(SERVICE_REGISTRY_URL, json=payload)
        response.raise_for_status()
        print("Service registered successfully.")
    except requests.exceptions.RequestException as e:
        print(f"An error occurred registering service: {e}")

def get_services() -> list:
    try:
        response = requests.get(SERVICE_REGISTRY_URL)
        response.raise_for_status()
        services = response.json()

        # Convert dictionary of dictionaries to a list of dictionaries
        if isinstance(services, dict):
            return [{"id": int(bank_id), **details} for bank_id, details in services.items()]

        print("Unexpected response format:", services)
        return []
    except requests.exceptions.RequestException as e:
        print(f"An error occurred fetching services: {e}")
        return []


async def contact_service(service, payload, responses):
    target_port = 6000 + service["id"]
    try:
        reader, writer = await asyncio.open_connection('127.0.0.1', target_port)
        writer.write(json.dumps(payload).encode('utf-8'))
        await writer.drain()

        # Set a timeout for reading the response
        data = await asyncio.wait_for(reader.read(1024), timeout=5.0)
        response = data.decode('utf-8')
        if not response.strip():
            raise ValueError(f"Empty response from {service['name']} on port {target_port}")
        print(f"Response from {service['name']} (port {target_port}): {response}")
        responses.append(json.loads(response))
    except (ConnectionError, ValueError, asyncio.TimeoutError) as e:
        print(f"Error communicating with {service['name']} on port {target_port}: {e}")
        responses.append({"status": "error", "message": str(e)})
    finally:
        writer.close()
        await writer.wait_closed()


async def send_paxos_message(phase, message) -> list:
    payload = {"phase": phase, "data": message}
    services = get_services()
    responses = []

    tasks = [contact_service(service, payload, responses) for service in services]
    await asyncio.gather(*tasks)

    return responses


def majority_approved(responses, status_key="status", success_value="accepted"):
    # Check if the majority of responses are successful
    successful = sum(1 for response in responses if response.get(status_key) == success_value)
    return successful > len(responses) // 2

def handle_prepare(message):
    global proposal_id, accepted_proposal
    incoming_proposal_id = message["proposal_id"]
    incoming_node_id = message["node_id"]

    if incoming_proposal_id > proposal_id or (incoming_proposal_id == proposal_id and incoming_node_id <= bank_id):
        proposal_id = incoming_proposal_id
        return {"status": "promise", "last_accepted": accepted_proposal}
    return {"status": "reject"}

def handle_accept(message):
    global proposal_id, accepted_proposal
    incoming_proposal_id = message["proposal_id"]
    proposed_account_balances = message["account_balances"]

    if incoming_proposal_id == proposal_id:
        accepted_proposal = proposed_account_balances
        return {"status": "accepted"}
    return {"status": "reject"}

def handle_learn(message):
    global account_balances
    account_balances.update(message["account_balances"])

    return {"status": "success", "balances": account_balances}

def validate_total_money():
    global account_balances, total_money
    current_total = sum(account_balances.values())
    if current_total != total_money:
        raise ValueError(f"Inconsistent total money! Expected {total_money}, found {current_total}.")

def consume_paxos_messages():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:
        server_socket.bind(('127.0.0.1', PAXOS_PORT))
        server_socket.listen(5)
        print(f"Paxos server listening on port {PAXOS_PORT}...")

        while True:
            client_socket, _ = server_socket.accept()
            with client_socket:
                try:
                    message = json.loads(client_socket.recv(1024).decode('utf-8'))
                    phase = message.get("phase")
                    data = message.get("data")

                    if phase == "prepare":
                        response = handle_prepare(data)
                    elif phase == "accept":
                        response = handle_accept(data)
                    elif phase == "learn":
                        response = handle_learn(data)
                    else:
                        response = {"status": "error", "message": "Invalid phase"}
                except json.JSONDecodeError:
                    response = {"status": "error", "message": "Invalid JSON in request"}
                except Exception as e:
                    response = {"status": "error", "message": str(e)}

                # Ensure a response is sent back to the client
                client_socket.sendall(json.dumps(response).encode('utf-8'))



class Bank(Resource):

    def get(self):
        global account_balances
        if request.path == "/balance":
            return {"balances": account_balances}, 200
        return {"message": "Method not allowed"}, 405

    def patch(self):
        global account_balances, proposal_id, total_money
        action = request.json.get("action")
        amount = request.json.get("amount")
        source = request.json.get("source")
        destination = request.json.get("destination")

        # Validate action
        if action not in ["withdraw", "deposit", "transfer"]:
            return {"status": "error", "message": "Invalid action"}, 400

        if action == "transfer":
            if not source or not destination:
                return {"status": "error", "message": "Source and destination required for transfer"}, 400
            if source == destination:
                return {"status": "error", "message": "Source and destination must be different"}, 400
            if source not in account_balances or destination not in account_balances:
                return {"status": "error", "message": "Invalid source or destination account"}, 404
            if amount > account_balances[source]:
                return {"status": "error", "message": "Insufficient funds in source account"}, 400

            # Compute new balances
            new_account_balances = account_balances.copy()
            new_account_balances[source] -= amount
            new_account_balances[destination] += amount

        elif action in ["withdraw", "deposit"]:
            if not source:
                return {"status": "error", "message": "Account required for withdraw/deposit"}, 400
            if source not in account_balances:
                return {"status": "error", "message": "Invalid account"}, 404

            new_account_balances = account_balances.copy()
            if action == "withdraw":
                if amount > new_account_balances[source]:
                    return {"status": "error", "message": "Insufficient funds"}, 400
                new_account_balances[source] -= amount
            elif action == "deposit":
                new_account_balances[source] += amount

        # Increment proposal ID for Paxos
        proposal_id += 1

        # Paxos Phase 1: Prepare
        prepare_responses = asyncio.run(send_paxos_message("prepare", {"proposal_id": proposal_id, "node_id": bank_id, "account_balances": new_account_balances}))
        if not majority_approved(prepare_responses, "status", "promise"):
            return {"message": "Operation rejected during prepare phase"}, 400

        # Paxos Phase 2: Accept
        accept_responses = asyncio.run(send_paxos_message("accept", {"proposal_id": proposal_id, "node_id": bank_id, "account_balances": new_account_balances}))
        if not majority_approved(accept_responses):
            return {"message": "Operation rejected during accept phase"}, 400

        # Paxos Phase 3: Learn
        learn_responses = asyncio.run(send_paxos_message("learn", {"proposal_id": proposal_id, "node_id": bank_id, "account_balances": new_account_balances}))
        if not majority_approved(learn_responses, "status", "success"):
            return {"message": "Operation rejected during learn phase"}, 400

        # Update global balances after consensus
        account_balances.update(new_account_balances)
        return {"message": f"{action.capitalize()} successful", "balances": account_balances}, 200



api.add_resource(Bank, "/balance", endpoint="balance", methods=["GET"])
api.add_resource(Bank, "/update", endpoint="update", methods=["PATCH"])

if __name__ == "__main__":
    # Get continent from user arguments
    parser = argparse.ArgumentParser(description="Run a bank service.")
    parser.add_argument("continent", type=str, help="Continent where the bank is located")
    args = parser.parse_args()
    continent = args.continent
    bank_id = bank_ids.get(continent)

    PORT = 5000 + bank_id
    PAXOS_PORT = 6000 + bank_id

    threading.Thread(target=consume_paxos_messages, daemon=True).start()

    register_service()
    app.run(port=PORT)

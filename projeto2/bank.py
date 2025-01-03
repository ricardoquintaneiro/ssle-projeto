import argparse
import asyncio
import hashlib
import hmac
import json
import socket
import threading
from threading import Lock

import requests
from flask import Flask, request
from flask_restful import Api, Resource

SECRET_KEY = b"SSLE_24_25"

app = Flask(__name__)
api = Api(app)

account_balances = {"Europe": 1000, "America": 2000, "Asia": 3000, "Africa": 4000, "Oceania": 5000}
bank_ids = {"Europe": 1, "America": 2, "Asia": 3, "Africa": 4, "Oceania": 5}

total_money = sum(account_balances.values())

SERVICE_REGISTRY_URL = "http://127.0.0.1:5000/services"
proposal_id = 0
accepted_proposal = None
learned_proposals = {}
last_learned_proposal = 0

def sign_message(message: str) -> str:
    serialized_message = json.dumps(message, sort_keys=True).encode('utf-8')
    return hmac.new(SECRET_KEY, serialized_message, hashlib.sha384).hexdigest()

def verify_message(message: str, signature: str):
    expected_signature = sign_message(message)
    return hmac.compare_digest(expected_signature, signature)

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

        if payload["phase"] in ["prepare", "verify"]:
            # Set a timeout for reading the response
            data = await asyncio.wait_for(reader.read(1024), timeout=5.0)
            response = data.decode('utf-8')
            if not response.strip():
                raise ValueError(f"Empty response from {service['name']} on port {target_port}")
            response = json.loads(response)
            signature = response.pop("signature", "")
            if not verify_message(response, signature):
                raise ValueError(f"Invalid signature from {service['name']} on port {target_port}")
            print(f"Response from {service['name']} (port {target_port}): {response}")
            responses.append(response)
    except (ConnectionError, ValueError, asyncio.TimeoutError, Exception) as e:
        print(f"Error communicating with {service['name']} on port {target_port}: {e}")
        responses.append({"status": "error", "message": str(e)})
    finally:
        if 'writer' in locals():
            writer.close()
            await writer.wait_closed()



async def send_paxos_message(phase, message) -> list:
    payload = {"phase": phase, "data": message}
    payload["signature"] = sign_message(payload)
    services = get_services()
    responses = []
    node_id = message["node_id"]

    if phase == "verify":
        targets = [service for service in services if service["id"] != node_id]
    elif phase == "learn":
        targets = services
    else:
        targets = [service for service in services if service["id"] != bank_id]

    tasks = [contact_service(service, payload, responses) for service in targets]
    await asyncio.gather(*tasks)

    return responses


def majority_approved(responses, status_key="status", success_value="accepted"):
    # Check if the majority of responses are successful
    successful = sum(1 for response in responses if response.get(status_key) == success_value)
    return successful >= (len(get_services()) - 1) // 2


def handle_prepare(message):
    global proposal_id, accepted_proposal
    incoming_proposal_id = message.get("proposal_id", None)

    if incoming_proposal_id is None:
        return {"status": "error", "message": "'proposal_id' missing in message"}

    if incoming_proposal_id > proposal_id:
        proposal_id = incoming_proposal_id
        return {"status": "promise", "last_accepted": accepted_proposal}
    return {"status": "reject"}


def handle_accept(message):
    global proposal_id, accepted_proposal
    incoming_proposal_id = message["proposal_id"]
    incoming_node_id = message["node_id"]
    proposed_account_balances = message["account_balances"]

    if incoming_proposal_id == proposal_id:
        accepted_proposal = proposed_account_balances

        # Broadcast verify message asynchronously
        broadcast_message = {
            "proposal_id": proposal_id,
            "node_id": incoming_node_id,
            "account_balances": proposed_account_balances
        }
        print("Broadcasting verify message:", broadcast_message)

        # Dispatch the verify phase as a background task
        asyncio.create_task(verify_and_learn(broadcast_message))
    else:
        print(f"Rejected proposal {incoming_proposal_id} (current: {proposal_id})")


async def verify_and_learn(broadcast_message):
    # Verify phase
    verification_responses = await send_paxos_message("verify", broadcast_message)
    print("Responses:", verification_responses)

    if not majority_approved(verification_responses, "status", "verified"):
        print(f"Verification failed for proposal {broadcast_message['proposal_id']}. Aborting Paxos.")
        return

    # If majority verified, proceed to learn phase
    await send_paxos_message("learn", broadcast_message)
    print(f"Proposal {broadcast_message['proposal_id']} learned successfully.")




def handle_verify(message):
    global proposal_id, accepted_proposal

    incoming_proposal_id = message["proposal_id"]
    proposed_account_balances = message["account_balances"]

    # Check proposal ID and balances
    if incoming_proposal_id == proposal_id and proposed_account_balances == accepted_proposal:
        return {"status": "verified"}
    return {"status": "error", "message": "Mismatch in proposal or balances"}



learned_proposals_lock = Lock()

def handle_learn(message):
    global account_balances, learned_proposals, last_learned_proposal

    proposal_id = message["proposal_id"]
    proposed_balances = message["account_balances"]

    with learned_proposals_lock:
        if proposal_id not in learned_proposals:
            learned_proposals[proposal_id] = 0

        learned_proposals[proposal_id] += 1

        if last_learned_proposal != proposal_id and learned_proposals[proposal_id] == ((len(get_services()) - 1) // 2) + 1:
            account_balances.update(proposed_balances)
            del learned_proposals[proposal_id]
            last_learned_proposal = proposal_id


async def process_message(client_socket, address):
    try:
        message = json.loads(await asyncio.to_thread(client_socket.recv, 1024))
        signature = message.pop("signature", "")
        if not signature:
            raise ValueError("Missing signature")

        phase = message.get("phase")
        data = message.get("data")

        if not verify_message(message, signature):
            response = {"status": "error", "message": "Invalid signature"}
        else:
            response = None

            if phase == "prepare":
                response = handle_prepare(data)
            elif phase == "accept":
                handle_accept(data)
            elif phase == "verify":
                print("Handling verify message")
                response = handle_verify(data)
            elif phase == "learn":
                handle_learn(data)
            else:
                response = {"status": "error", "message": "Invalid phase"}

        if response:
            response["signature"] = sign_message(response)
            await asyncio.to_thread(client_socket.sendall, json.dumps(response).encode('utf-8'))
    except Exception as e:
        print(f"Error processing message from {address}: {e}")
    finally:
        client_socket.close()


async def consume_paxos_messages():
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind(('127.0.0.1', PAXOS_PORT))
    server_socket.listen(5)
    print(f"Paxos server listening on port {PAXOS_PORT}...")

    while True:
        client_socket, address = await asyncio.to_thread(server_socket.accept)
        asyncio.create_task(process_message(client_socket, address))


async def wait_for_majority_learn(proposal_id):
    global learned_proposals, last_learned_proposal

    timeout = 10  # Adjust as needed
    start_time = asyncio.get_event_loop().time()

    while asyncio.get_event_loop().time() - start_time < timeout:
        with learned_proposals_lock:
            if proposal_id == last_learned_proposal:
                return True
        await asyncio.sleep(0.1)

    return False


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
        asyncio.run(send_paxos_message("accept", {"proposal_id": proposal_id, "node_id": bank_id, "account_balances": new_account_balances}))

        # Wait until learning phase completes
        learning_completed = asyncio.run(wait_for_majority_learn(proposal_id))

        if not learning_completed:
            return {"message": "Operation timed out during learning phase"}, 408

        return {"message": f"{action.capitalize()} successful", "balances": account_balances}, 200


def start_paxos_server():
    asyncio.run(consume_paxos_messages())

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

    threading.Thread(target=start_paxos_server, daemon=True).start()

    register_service()
    app.run(port=PORT)

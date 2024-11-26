import requests

proxies = {
    "http": "http://10.151.101.193:8080",  # Proxy for HTTP traffic
    "https": "http://10.151.101.193:8080"  # Proxy for HTTPS traffic
}

def get_temperature(api_url):
    try:
        response = requests.get(api_url, proxies=proxies)
        response.raise_for_status()
        data = response.json()
        return data.get("temp_c")
    except requests.exceptions.RequestException as e:
        print(f"An error occurred: {e}")
        return None


def get_services(registry_url):
    try:
        response = requests.get(registry_url)
        response.raise_for_status()
        data = response.json()
        return data
    except requests.exceptions.RequestException as e:
        print(f"An error occurred: {e}")
        return {}


def get_service_url(service_id, registry_url):
    try:
        response = requests.get(f"{registry_url}/{service_id}")
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"An error occurred: {e}")
        return None


if __name__ == "__main__":
    registry_url = "http://10.151.101.15:5000/services"
    services = get_services(registry_url)
    print(services, type(services))
    for service_id, service_details in services.items():
        if service_details == "Celsius":
            api_url = get_service_url(service_id, registry_url)
            temperature = get_temperature(api_url)
            if temperature is not None:
                print(f"The current temperature is {temperature}°C")
            else:
                print("Failed to retrieve temperature data.")
            break

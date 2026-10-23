import requests

def get_weather(lat, lon):

    url = (
        f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true"
    )

    response = requests.get(url, timeout=10)
    data = response.json()

    current = data.get("current_weather", {})

    return {
        "temperature": current.get("temperature"),
        "wind": current.get("windspeed")
    }


if __name__ == "__main__":

    weather = get_weather(12.9716, 77.5946)  # Bengaluru

    print(weather)
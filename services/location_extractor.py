def extract_location(text):

    # Try full sentence first
    try:
        location = geolocator.geocode(text + ", Karnataka, India")

        if location:
            return {
                "query": text,
                "address": location.address,
                "latitude": location.latitude,
                "longitude": location.longitude
            }
    except:
        pass

    # Fallback: search important South India place names
    south_places = [
        "Mangaluru", "Mangalore", "Mysuru", "Mysore",
        "Bengaluru", "Bangalore", "Udupi",
        "Chikkamagaluru", "Chikmagalur", "Kodagu",
        "Kannur", "Kochi", "Palakkad", "Salem",
        "Coimbatore", "Madurai", "Tirunelveli",
        "Karimnagar", "Warangal", "Vijayawada"
    ]

    lower = text.lower()

    for place in south_places:
        if place.lower() in lower:
            try:
                location = geolocator.geocode(place + ", South India")
                if location:
                    return {
                        "query": place,
                        "address": location.address,
                        "latitude": location.latitude,
                        "longitude": location.longitude
                    }
            except:
                pass

    return None
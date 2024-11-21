import requests

# Define the URL of your local webhook
url = "http://127.0.0.1:5002/twitch-webhook"

# Define the data you want to send in the webhook
data = {
    "event": {
        "broadcaster_user_name": "test",  # Example username
        "title": "Test Stream"            # Example stream title
    }
}

# Send a POST request to the webhook
response = requests.post(url, json=data)

# Print the response status and body
if response.status_code == 200:
    print("Webhook sent successfully!")
    print("Response:", response.json())
else:
    print(f"Failed to send webhook. Status code: {response.status_code}")
    print("Response:", response.text)

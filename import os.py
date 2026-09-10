import os
import requests
from dotenv import load_dotenv

load_dotenv()

token = os.getenv("WHATSAPP_ACCESS_TOKEN")
waba_id = "3226614304206948"

url = f"https://graph.facebook.com/v26.0/{waba_id}/subscribed_apps"
headers = {"Authorization": f"Bearer {token}"}

response = requests.post(url, headers=headers)
print(response.json())
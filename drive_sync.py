import requests
import streamlit as st

WEB_APP_URL = st.secrets.get("WEB_APP_URL", "")
WEB_APP_PASSWORD = st.secrets.get("PASSWORD", "")

def fetch_inventory_from_drive():
    """Pulls the latest inventory.csv text data from Google Drive."""
    try:
        payload = {"action": "getInventory", "password": WEB_APP_PASSWORD}
        response = requests.post(WEB_APP_URL, json=payload, timeout=10)
        data = response.json()
        if data.get("status") == "success":
            return data.get("content")
    except Exception as e:
        st.error(f"Drive Fetch Error: {e}")
    return None

def push_inventory_to_drive(csv_string):
    """Pushes the entire updated CSV string to Google Drive in one clean request."""
    try:
        payload = {
            "action": "saveInventory",
            "password": WEB_APP_PASSWORD,
            "content": csv_string
        }
        response = requests.post(WEB_APP_URL, json=payload, timeout=15)
        data = response.json()
        return data.get("status") == "success"
    except Exception as e:
        st.error(f"Drive Sync Error: {e}")
        return False
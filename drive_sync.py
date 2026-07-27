import requests
import streamlit as st

# Retrieve credentials securely from Streamlit secrets TOML
WEB_APP_URL = st.secrets.get("WEB_APP_URL", "")
WEB_APP_PASSWORD = st.secrets.get("PASSWORD", "")

def fetch_inventory_from_drive():
    """Pulls the latest inventory.csv text data from Google Drive."""
    if not WEB_APP_URL:
        st.error("Error: WEB_APP_URL is missing from Streamlit secrets.")
        return None
        
    try:
        payload = {
            "action": "getInventory",
            "password": WEB_APP_PASSWORD
        }
        response = requests.post(WEB_APP_URL, json=payload, timeout=15)
        data = response.json()
        
        if data.get("status") == "success":
            return data.get("content")
        else:
            st.error(f"Google Drive Error: {data.get('message')}")
            return None
    except Exception as e:
        st.error(f"Connection Error: {e}")
        return None

def push_inventory_to_drive(csv_string):
    """Pushes updated CSV content straight back to Google Drive."""
    if not WEB_APP_URL:
        st.error("Error: WEB_APP_URL is missing from Streamlit secrets.")
        return False
        
    try:
        payload = {
            "action": "saveInventory",
            "password": WEB_APP_PASSWORD,
            "content": csv_string
        }
        response = requests.post(WEB_APP_URL, json=payload, timeout=20)
        data = response.json()
        
        return data.get("status") == "success"
    except Exception as e:
        st.error(f"Sync Error: {e}")
        return False
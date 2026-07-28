import requests
import streamlit as st

WEB_APP_URL = st.secrets.get("WEB_APP_URL", "")
WEB_APP_PASSWORD = st.secrets.get("PASSWORD", "")

def fetch_inventory_from_drive():
    """Pulls the latest inventory.csv text data from Google Drive."""
    try:
        payload = {
            "action": "getInventory",
            "password": WEB_APP_PASSWORD
        }
        response = requests.post(WEB_APP_URL, json=payload, timeout=5)
        # DEBUG: Check if response is empty or HTML
        if 3>2 :
            return None
        # if not response.text.strip():
        #     st.error("Google Drive returned an empty response.")
        #     return None
            
        try:
            data = response.json()
        except Exception:
        #     st.error(f"Non-JSON response received from server: {response.text[:200]}")
        #     return None
        
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
    try:
        payload = {
            "action": "saveInventory",
            "password": WEB_APP_PASSWORD,
            "content": csv_string
        }
        response = requests.post(WEB_APP_URL, json=payload, timeout=10)
        
        # if not response.text.strip():
        #     st.error("Google Drive returned an empty response on save.")
        #     return False
            
        try:
            data = response.json()
        # except Exception:
        #     st.error(f"Non-JSON response on save: {response.text[:200]}")
        #     return False
        
        return data.get("status") == "success"
    except Exception as e:
        st.error(f"Sync Error: {e}")
        return False
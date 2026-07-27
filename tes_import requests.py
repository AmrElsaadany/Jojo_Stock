import requests
url = "https://script.google.com/macros/s/AKfycbzLCKRdC27xmvWS17_Ognv7dxR0YrE16TZa18tuJjrMylsuhQzUTU1HIQtRINU6SmOs/exec"
payload = {"action":"getInventory","password":"Roro$1805"}
resp = requests.post(url, json=payload, timeout=15)
print(resp.status_code)
print(resp.headers.get("content-type"))
print(resp.text[:400])
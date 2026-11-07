# cookies_to_state.py  (run: python -m app.cookies_to_state)
import json

cookies = []
for line in open("secrets/instagram_cookies.txt", encoding="utf-8"):
    line = line.strip()
    if line.startswith("#HttpOnly_"):
        line = line[len("#HttpOnly_"):]
    elif not line or line.startswith("#"):
        continue
    parts = line.split("\t")
    if len(parts) != 7:
        continue
    domain, _, path, secure, expires, name, value = parts
    cookies.append({
        "name": name, "value": value, "domain": domain, "path": path,
        "expires": int(expires) if int(expires) > 0 else -1,
        "httpOnly": False, "secure": secure == "TRUE", "sameSite": "Lax",
    })

json.dump({"cookies": cookies, "origins": []}, open("secrets/instagram_state.json", "w"))
print("cookies:", len(cookies), "| sessionid:", any(c["name"] == "sessionid" for c in cookies))
import json
import urllib.request

SERVICE_ID = "srv-db9j706q1p3s738f2lo0"
API_KEY = "rnd_MDHgH6r3y5cfveR9PsrAp11pBUHQ"
HASH_VAL = "scrypt$16384$8$1$add69903bcf32aaac84987a09ca77667$e217fd3a86e57bae3cdce5c778863bd700267979814fee2a443ee1fbd82485ac"

def main():
    data = json.dumps({"value": HASH_VAL}).encode("utf-8")
    req = urllib.request.Request(
        f"https://api.render.com/v1/services/{SERVICE_ID}/env-vars/SITE_PASSWORD_HASH",
        data=data,
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="PUT",
    )
    with urllib.request.urlopen(req) as resp:
        print("Updated Render env var:", resp.status, resp.read().decode("utf-8"))

if __name__ == "__main__":
    main()

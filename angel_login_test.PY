
import logging
from getpass import getpass

from logzero import logger
from SmartApi import SmartConnect

# Avoid SDK request/response logs containing sensitive data.
logger.setLevel(logging.CRITICAL)

print("=== SMC | Angel One SmartAPI Login Test ===")

api_key = input("SmartAPI API Key: ").strip()
client_id = input("Angel One Client ID: ").strip()
mpin = getpass("Angel One MPIN: ").strip()
totp = getpass("Authenticator 6-digit TOTP: ").strip()

smart_api = None
logged_in = False

try:
    smart_api = SmartConnect(api_key=api_key)

    response = smart_api.generateSession(
        clientCode=client_id,
        password=mpin,
        totp=totp
    )

    if isinstance(response, dict) and response.get("status") is True:
        logged_in = True
        print("SUCCESS: SmartAPI authentication verified.")
        print("Profile access: verified by SDK.")
        print("No orders placed.")
    else:
        print("FAILED: Login was not accepted.")
        if isinstance(response, dict):
            print("Error code:", response.get("errorcode", "unknown"))
        print("Check credentials, TOTP and API access.")

except Exception as exc:
    print("ERROR: SmartAPI request failed.")
    print("Exception type:", type(exc).__name__)
    print("Sensitive error details intentionally hidden.")

finally:
    if logged_in and smart_api is not None:
        try:
            smart_api.terminateSession(client_id)
            print("Session logout requested.")
        except Exception:
            print("Logout could not be confirmed.")

print("=== Test Finished ===")

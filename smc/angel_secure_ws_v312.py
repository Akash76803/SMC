"""TLS-verified SmartWebSocketV2 adapter.

The upstream Angel Python SDK's WebSocket connect() has used
ssl.CERT_NONE. Never accept that in authenticated sessions: override
connect() to enforce certificate validation without changing SDK parsing,
subscription or retry methods. Recheck when upgrading SDK.
"""
from __future__ import annotations

import ssl


def make_secure_websocket(auth_token: str, api_key: str, client_id: str,
                          feed_token: str, *, ws_class=None,
                          websocket_module=None):
    if ws_class is None:
        from SmartApi.smartWebSocketV2 import SmartWebSocketV2 as ws_class
    if websocket_module is None:
        import websocket as websocket_module

    class SecureSmartWebSocketV2(ws_class):
        def connect(self):
            headers = {
                "Authorization": self.auth_token,
                "x-api-key": self.api_key,
                "x-client-code": self.client_code,
                "x-feed-token": self.feed_token,
            }
            self.wsapp = websocket_module.WebSocketApp(
                self.ROOT_URI, header=headers,
                on_open=self._on_open,
                on_error=self._on_error,
                on_close=self._on_close,
                on_data=self._on_data,
                on_ping=self._on_ping,
                on_pong=self._on_pong,
            )
            self.wsapp.run_forever(
                sslopt={"cert_reqs": ssl.CERT_REQUIRED,
                        "check_hostname": True},
                ping_interval=self.HEART_BEAT_INTERVAL)

    return SecureSmartWebSocketV2(
        auth_token, api_key, client_id, feed_token, max_retry_attempt=1)

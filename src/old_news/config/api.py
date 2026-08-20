from pydantic import BaseModel


class ApiSettings(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False

    # Which peers may set X-Forwarded-*. TLS terminates upstream, so untrusted every
    # generated URL says http:// and the browser blocks its own CSS. The default is
    # uvicorn's; compose widens it because the container's peer is the Docker gateway.
    forwarded_allow_ips: str = "127.0.0.1"

    # Local development only. Derived from the installed package, so no path is named.
    reload: bool = False

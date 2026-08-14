from pydantic import BaseModel


class ApiSettings(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False

    # Which peers may set X-Forwarded-Proto/For. TLS is terminated upstream by
    # Tailscale Serve, so without trusting the proxy every generated URL says
    # http:// and a browser blocks the page's own CSS as mixed content.
    #
    # The default is uvicorn's, which is safe anywhere. In a container the peer
    # is the Docker gateway rather than loopback, so compose widens it — sound
    # only because the published port is bound to loopback on the host.
    forwarded_allow_ips: str = "127.0.0.1"

    # Local development only. The reload directory is derived from the installed
    # package, so it is right on the host and in the container without either
    # having to name a path.
    reload: bool = False

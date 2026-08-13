from pydantic import BaseModel


class ApiSettings(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False

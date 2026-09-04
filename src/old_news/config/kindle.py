from pydantic import BaseModel, SecretStr


class KindleSettings(BaseModel):
    """Building a periodical and mailing it to Send to Kindle."""

    # Off until an address is set, so nothing tries to mail an issue nobody asked for.
    enabled: bool = False

    # 05:00 Monday in Sydney, which is Sunday in UTC — procrastinate hands croniter a
    # float timestamp, so this is read as UTC whatever the container's TZ says. Exact on
    # AEST; an hour later over AEDT, which no fixed UTC expression can avoid.
    cron: str = "0 19 * * 0"

    window_days: int = 7

    title: str = "Old News"

    # `ebook-convert` from calibre. On PATH in the image; overridable for a laptop.
    converter: str = "ebook-convert"
    convert_timeout_seconds: int = 600

    # A Kindle takes JPEG, not the AVIF the archive re-encodes to, and the device is
    # narrower than reading width.
    image_max_width: int = 1200
    image_quality: int = 72

    address: str = ""
    sender: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: SecretStr = SecretStr("")
    smtp_timeout_seconds: int = 120

    @property
    def deliverable(self) -> bool:
        """Whether there is somewhere to send an issue."""
        return bool(self.enabled and self.address and self.sender and self.smtp_host)

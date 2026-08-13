from dataclasses import dataclass

import pulumi


@dataclass(frozen=True)
class Host:
    """What the rest of the stack needs from a provider. Swapping clouds means
    writing one more module that returns this — nothing else changes."""

    name: str
    private_ip: pulumi.Output[str]
    public_ip: pulumi.Output[str] | None
    username: str

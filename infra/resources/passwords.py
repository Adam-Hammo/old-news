"""Passwords nobody types, so they exist in exactly one place."""

from dataclasses import dataclass

import pulumi
import pulumi_random as random


@dataclass(frozen=True)
class Secrets:
    postgres_password: pulumi.Output[str]
    restic_password: pulumi.Output[str]


def generate() -> Secrets:
    postgres = random.RandomPassword(
        "postgres-password",
        length=48,
        # No punctuation: this goes into a postgres:// URL, where @ : / ? and #
        # each terminate a field.
        special=False,
    )

    restic = random.RandomPassword(
        "restic-password",
        length=64,
        special=False,
    )

    return Secrets(
        postgres_password=postgres.result,
        restic_password=restic.result,
    )

"""The restic repository, off-provider so it doesn't share a fate with the box."""

from dataclasses import dataclass

import pulumi
import pulumi_b2 as b2


@dataclass(frozen=True)
class Repository:
    bucket: pulumi.Output[str]
    key_id: pulumi.Output[str]
    application_key: pulumi.Output[str]


def provision(bucket_name: str) -> Repository:
    bucket = b2.Bucket(
        "backups",
        bucket_name=bucket_name,
        bucket_type="allPrivate",
        lifecycle_rules=[
            b2.BucketLifecycleRuleArgs(
                file_name_prefix="",
                # restic deletes by hiding, and B2 bills hidden versions forever.
                days_from_hiding_to_deleting=1,
                # Interrupted uploads leave parts that are billed but invisible.
                days_from_starting_to_canceling_unfinished_large_files=3,
            )
        ],
        # The archive is the one part of this system that cannot be rebuilt.
        opts=pulumi.ResourceOptions(protect=True),
    )

    key = b2.ApplicationKey(
        "backups-key",
        key_name="old-news-restic",
        # Scoped, so a leaked key cannot read the rest of the account.
        bucket_ids=[bucket.bucket_id],
        capabilities=["listBuckets", "listFiles", "readFiles", "writeFiles", "deleteFiles"],
    )

    return Repository(
        bucket=bucket.bucket_name,
        key_id=key.application_key_id,
        application_key=key.application_key,
    )

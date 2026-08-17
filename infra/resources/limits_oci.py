"""The spend fence. A quota denies; a budget only tells you afterwards.

Both already existed in the console, so both are adopted by `pulumi import` and every
value here matches what is live. Import before the first `up`.
"""

from dataclasses import dataclass

import pulumi
import pulumi_oci as oci

# `up` replaces the list wholesale, so this carries every statement the tenancy needs.
# Note `quota`, singular — the plural form is a different statement shape.
QUOTA_STATEMENTS = [
    # Oracle halved Always Free A1 to 2 OCPU / 12 GB on 2026-06-15. The box is
    # exactly that, so the grant is spent: a third core would be billable.
    "set compute-core quota standard-a1-core-count to 2 in tenancy",
    "set compute-memory quota standard-a1-memory-count to 12 in tenancy",
    "set block-storage quota total-storage-gb to 200 in tenancy",
]


@dataclass(frozen=True)
class Limits:
    budget_id: pulumi.Output[str]
    quota_id: pulumi.Output[str]


def provision() -> Limits:
    config = pulumi.Config()

    # Both are root-compartment resources: a budget elsewhere is rejected, and a
    # quota only applies tenancy-wide from there.
    tenancy = config.get("tenancyOcid") or config.require("compartmentOcid")

    quota = oci.limits.Quota(
        "free-tier-cap",
        compartment_id=tenancy,
        name="free-tier-cap",
        description="Hard cap at Always Free limits (post June 2026)",
        statements=QUOTA_STATEMENTS,
    )

    budget = oci.budget.Budget(
        "free-tier-guard",
        compartment_id=tenancy,
        display_name="free-tier-guard",
        description="Alert on any spend at all",
        amount=1,
        reset_period="MONTHLY",
        target_type="COMPARTMENT",
        targets=[tenancy],
        processing_period_type="MONTH",
        budget_processing_period_start_offset=1,
    )

    # 10% of a $1 budget. ACTUAL rather than FORECAST: forecasting from near-zero
    # spend alerts on rounding.
    oci.budget.Rule(
        "any-spend",
        budget_id=budget.id,
        display_name="any-spend",
        type="ACTUAL",
        threshold=10,
        threshold_type="PERCENTAGE",
        recipients=config.require_secret("budgetAlertRecipient"),
        message="Something is costing money on the OCI free tier.",
    )

    return Limits(budget_id=budget.id, quota_id=quota.id)

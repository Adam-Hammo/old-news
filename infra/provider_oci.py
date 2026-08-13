"""The only provider-specific file.

VM.Standard.A1.Flex, 2 OCPU / 12 GB, 200 GB boot, Ubuntu 24.04 arm64 — the Always
Free allowance.
"""

import base64
from pathlib import Path

import pulumi
import pulumi_oci as oci

from provider import Host

CLOUD_INIT = Path(__file__).parent / "cloud-init.yaml"


def _user_data(tailscale_auth_key: pulumi.Output[str]) -> pulumi.Output[str]:
    template = CLOUD_INIT.read_text()
    return tailscale_auth_key.apply(
        lambda key: base64.b64encode(
            template.replace("${TAILSCALE_AUTH_KEY}", key).encode()
        ).decode()
    )


def provision() -> Host:
    config = pulumi.Config()
    oci_config = pulumi.Config("oci")

    compartment_id = config.require("compartmentOcid")
    availability_domain = config.require("availabilityDomain")
    ssh_public_key = config.require("sshPublicKey")
    tailscale_auth_key = config.require_secret("tailscaleAuthKey")

    ocpus = config.get_float("ocpus") or 2.0
    memory_gb = config.get_float("memoryGb") or 12.0
    boot_volume_gb = config.get_int("bootVolumeGb") or 200

    vcn = oci.core.Vcn(
        "vcn",
        compartment_id=compartment_id,
        cidr_blocks=["10.0.0.0/16"],
        display_name="old-news",
        dns_label="oldnews",
    )

    gateway = oci.core.InternetGateway(
        "internet-gateway",
        compartment_id=compartment_id,
        vcn_id=vcn.id,
        enabled=True,
    )

    route_table = oci.core.RouteTable(
        "route-table",
        compartment_id=compartment_id,
        vcn_id=vcn.id,
        route_rules=[
            oci.core.RouteTableRouteRuleArgs(
                destination="0.0.0.0/0",
                destination_type="CIDR_BLOCK",
                network_entity_id=gateway.id,
            )
        ],
    )

    # Zero inbound. The box reaches the tailnet by dialling out from cloud-init,
    # and you SSH to it over Tailscale.
    security_list = oci.core.SecurityList(
        "security-list",
        compartment_id=compartment_id,
        vcn_id=vcn.id,
        egress_security_rules=[
            oci.core.SecurityListEgressSecurityRuleArgs(
                destination="0.0.0.0/0",
                protocol="all",
            )
        ],
        ingress_security_rules=[],
    )

    subnet = oci.core.Subnet(
        "subnet",
        compartment_id=compartment_id,
        vcn_id=vcn.id,
        cidr_block="10.0.1.0/24",
        route_table_id=route_table.id,
        security_list_ids=[security_list.id],
        dns_label="app",
    )

    images = oci.core.get_images_output(
        compartment_id=compartment_id,
        operating_system="Canonical Ubuntu",
        operating_system_version="24.04",
        shape="VM.Standard.A1.Flex",
        sort_by="TIMECREATED",
        sort_order="DESC",
    )

    instance = oci.core.Instance(
        "instance",
        compartment_id=compartment_id,
        availability_domain=availability_domain,
        shape="VM.Standard.A1.Flex",
        shape_config=oci.core.InstanceShapeConfigArgs(ocpus=ocpus, memory_in_gbs=memory_gb),
        source_details=oci.core.InstanceSourceDetailsArgs(
            source_type="image",
            source_id=images.images[0].id,
            boot_volume_size_in_gbs=boot_volume_gb,
        ),
        create_vnic_details=oci.core.InstanceCreateVnicDetailsArgs(
            subnet_id=subnet.id,
            assign_public_ip=True,
        ),
        metadata={
            "ssh_authorized_keys": ssh_public_key,
            "user_data": _user_data(tailscale_auth_key),
        },
        display_name="old-news",
        # `Out of host capacity` is expected here and needs retrying, not debugging.
        opts=pulumi.ResourceOptions(custom_timeouts=pulumi.CustomTimeouts(create="30m")),
    )

    pulumi.log.info(f"region: {oci_config.get('region') or 'from provider config'}")

    return Host(
        name="old-news",
        private_ip=instance.private_ip,
        public_ip=instance.public_ip,
        username="ubuntu",
    )

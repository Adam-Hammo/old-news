"""The box: A1.Flex 2 OCPU / 12 GB / 200 GB boot, the whole Always Free allowance.

Adopted by `pulumi import`, so every value is pinned to the live resource rather
than computed. A computed image id or shape reads as a diff that replaces an
instance there is no spare quota to rebuild.
"""

import pulumi
import pulumi_oci as oci

from resources.host import Host


def provision() -> Host:
    config = pulumi.Config()

    compartment_id = config.require("compartmentOcid")
    availability_domain = config.require("availabilityDomain")
    ssh_public_key = config.require("sshPublicKey")
    image_id = config.require("imageOcid")

    ocpus = config.get_float("ocpus") or 2.0
    memory_gb = config.get_float("memoryGb") or 12.0
    boot_volume_gb = config.get_int("bootVolumeGb") or 200

    # Only close this once Tailscale is proven — it is the sole way back in.
    public_ssh = config.get_bool("publicSshEnabled")
    public_ssh = True if public_ssh is None else public_ssh

    vcn = oci.core.Vcn(
        "vcn",
        compartment_id=compartment_id,
        cidr_blocks=["10.0.0.0/16"],
        display_name="rss-vcn",
    )

    gateway = oci.core.InternetGateway(
        "internet-gateway",
        compartment_id=compartment_id,
        vcn_id=vcn.id,
        display_name="rss-igw",
        enabled=True,
    )

    # The VCN's defaults, which is what the subnet is already attached to.
    route_table = oci.core.DefaultRouteTable(
        "default-route-table",
        manage_default_resource_id=vcn.default_route_table_id,
        route_rules=[
            oci.core.DefaultRouteTableRouteRuleArgs(
                destination="0.0.0.0/0",
                destination_type="CIDR_BLOCK",
                network_entity_id=gateway.id,
            )
        ],
    )

    ingress = []
    if public_ssh:
        ingress.append(
            oci.core.DefaultSecurityListIngressSecurityRuleArgs(
                protocol="6",
                source="0.0.0.0/0",
                source_type="CIDR_BLOCK",
                stateless=False,
                tcp_options=oci.core.DefaultSecurityListIngressSecurityRuleTcpOptionsArgs(
                    min=22, max=22
                ),
            )
        )
    ingress += [
        # Path MTU discovery. Dropping it breaks large packets confusingly.
        oci.core.DefaultSecurityListIngressSecurityRuleArgs(
            protocol="1",
            source="0.0.0.0/0",
            source_type="CIDR_BLOCK",
            stateless=False,
            icmp_options=oci.core.DefaultSecurityListIngressSecurityRuleIcmpOptionsArgs(
                type=3, code=4
            ),
        ),
        oci.core.DefaultSecurityListIngressSecurityRuleArgs(
            protocol="1",
            source="10.0.0.0/16",
            source_type="CIDR_BLOCK",
            stateless=False,
            icmp_options=oci.core.DefaultSecurityListIngressSecurityRuleIcmpOptionsArgs(type=3),
        ),
    ]

    security_list = oci.core.DefaultSecurityList(
        "default-security-list",
        manage_default_resource_id=vcn.default_security_list_id,
        egress_security_rules=[
            oci.core.DefaultSecurityListEgressSecurityRuleArgs(
                destination="0.0.0.0/0",
                destination_type="CIDR_BLOCK",
                protocol="all",
                stateless=False,
            )
        ],
        ingress_security_rules=ingress,
    )

    subnet = oci.core.Subnet(
        "subnet",
        compartment_id=compartment_id,
        vcn_id=vcn.id,
        cidr_block="10.0.1.0/24",
        display_name="rss-subnet",
        route_table_id=route_table.manage_default_resource_id,
        security_list_ids=[security_list.manage_default_resource_id],
    )

    instance = oci.core.Instance(
        "instance",
        compartment_id=compartment_id,
        availability_domain=availability_domain,
        shape="VM.Standard.A1.Flex",
        shape_config=oci.core.InstanceShapeConfigArgs(ocpus=ocpus, memory_in_gbs=memory_gb),
        source_details=oci.core.InstanceSourceDetailsArgs(
            source_type="image",
            source_id=image_id,
            boot_volume_size_in_gbs=boot_volume_gb,
        ),
        create_vnic_details=oci.core.InstanceCreateVnicDetailsArgs(
            subnet_id=subnet.id,
            assign_public_ip=True,
        ),
        # No user_data: cloud-init runs once and cannot converge, so Ansible owns
        # bootstrap. The trailing newline matches what OCI stored from
        # --ssh-authorized-keys-file; metadata is replace-forcing, so without it the
        # diff is one invisible byte and a rebuilt instance.
        metadata={"ssh_authorized_keys": ssh_public_key.rstrip("\n") + "\n"},
        display_name="rss-01",
        opts=pulumi.ResourceOptions(
            protect=True,
            # A newer upstream image must not silently become a replacement.
            ignore_changes=["sourceDetails"],
        ),
    )

    return Host(
        name="rss-01",
        private_ip=instance.private_ip,
        public_ip=instance.public_ip,
        username="ubuntu",
    )

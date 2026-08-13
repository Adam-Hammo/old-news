import pulumi

from provider_oci import provision

host = provision()

pulumi.export("host_name", host.name)
pulumi.export("host_username", host.username)
pulumi.export("host_private_ip", host.private_ip)
pulumi.export("host_public_ip", host.public_ip)

# Terraform for the WeebBlade EC2 host

Describes the AWS resources that already exist — the instance was provisioned by
hand via the console for speed while chasing a hosting solution under time
pressure (see `../../PROGRESS.md` for the full saga). These files are IaC
documentation of the current state, not yet applied — they're written to be
brought under management via `terraform import` once AWS credentials exist
locally, not to provision a second, competing instance.

## Setup

1. Install the AWS CLI and configure credentials: `aws configure` — needs an IAM
   user with EC2 read/write permissions (create one via the IAM console; do not
   use root account access keys for this).
2. Install Terraform >= 1.5.
3. Copy `terraform.tfvars.example` to `terraform.tfvars` and fill in your current
   IP for `allowed_ssh_cidr`.

## Bringing the existing resources under management

Run `terraform init` first, then import each resource by its real AWS ID (find
IDs via the AWS Console, or `aws ec2 describe-instances` /
`describe-security-groups`):

```bash
terraform import aws_security_group.weebblade sg-XXXXXXXX
terraform import aws_instance.weebblade i-029eb264d81f9d9e4
```

Then run `terraform plan`. It should show **no changes** (or only cosmetic ones,
like tags) if these files accurately describe what's already running. If plan
shows anything that looks like it would replace or modify the instance, stop and
investigate before ever running `terraform apply` — the goal here is descriptive
IaC for an already-working box, not an accidental rebuild of it.

## Known gaps

- `aws_key_pair` isn't managed here. The keypair (`weebblade-key`) was created via
  the console wizard and its private key lives locally at
  `C:\Users\Hi\.ssh\weebblade-key.pem` — Terraform can reference an existing key
  pair by name, but can't reconstruct a private key it never generated.
- No Elastic IP. The instance's public IP is dynamic and will change if it's ever
  stopped and started — add an `aws_eip` resource if that becomes a real problem
  (e.g. once a domain points at it).
- No remote state backend configured — state lives in a local `terraform.tfstate`
  file (already gitignored). Fine for a solo project; revisit if that changes.

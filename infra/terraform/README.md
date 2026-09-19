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

## State: there isn't any

Checked on 2026-09-19: no `*.tfstate` exists on the Linux box or on the surviving
Windows drive, and the machine that held it was reinstalled. Nothing here is
under management, and an `apply` from empty state would create a **second**
instance and security group rather than touch the running ones. Import before
any apply; `plan` on its own is safe.

## Bringing the existing resources under management

Run `terraform init` first, then import each resource by its real AWS ID:

```bash
terraform import aws_security_group.weebblade sg-029497100335e0355
terraform import aws_instance.weebblade i-029eb264d81f9d9e4
```

Then run `terraform plan`. It should show **no changes** (or only cosmetic ones,
like tags) if these files accurately describe what's already running. On
2026-09-19 they did, checked field by field against the live resources with the
AWS CLI: instance `m7i-flex.large`, AMI `ami-03f1d2b3639314198`, key
`weebblade-key`, subnet `subnet-0733aa28f9366dbdb`, tag `Name=weebblade`, root
volume 30 GB gp3 at 3000 IOPS; the security group named `weebblade-sg` with 80
and 443 open to the world, everything out, and no standing SSH rule. So a plan
that proposes changes after import means something drifted after that date, not
that these files were always wrong. If plan
shows anything that looks like it would replace or modify the instance, stop and
investigate before ever running `terraform apply` — the goal here is descriptive
IaC for an already-working box, not an accidental rebuild of it.

## Known gaps

- `aws_key_pair` isn't managed here. The keypair (`weebblade-key`) was created via
  the console wizard; Terraform can reference an existing key pair by name, but
  can't reconstruct a private key it never generated. The private key was on the
  Windows machine that has since been reinstalled; the Linux box has its own key
  under `~/.ssh` (see `scripts/weebblade-ssh.sh`, which resolves it), added to the
  instance's `authorized_keys`.
- No Elastic IP. The instance's public IP is dynamic and will change if it's ever
  stopped and started — add an `aws_eip` resource if that becomes a real problem
  (e.g. once a domain points at it).
- No remote state backend configured — state would live in a local
  `terraform.tfstate` (gitignored), and today there is none at all (see "State:
  there isn't any"). Losing a laptop loses it again, which is the argument for a
  remote backend if this ever stops being a solo project.

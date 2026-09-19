# THERE IS NO STATE FILE. Searched for on 2026-09-19 across this machine and the
# surviving Windows drive: no *.tfstate anywhere. The machine that held it was
# reinstalled. So `terraform apply` from empty state would not manage the running
# instance and its security group - it would CREATE A SECOND SET, billable, while
# the live one carried on unmanaged. Import first: see README.md, "Bringing the
# existing resources under management". `terraform plan` alone is safe and is how
# to tell whether an import worked.

terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

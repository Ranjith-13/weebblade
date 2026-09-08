# Uses the account's default VPC/subnets in ap-south-2 - that's what the instance
# was actually launched into via the console wizard, not a custom VPC.
data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

resource "aws_security_group" "weebblade" {
  name = "weebblade-sg"
  # AWS security group description is immutable (ForceNew) - this is the
  # console's own auto-generated default from when the SG was created by hand
  # via the launch wizard, kept verbatim so `terraform plan` doesn't propose
  # destroying and recreating a security group actively attached to a running
  # instance just to change a cosmetic description string.
  description = "launch-wizard-1 created 2026-09-07T06:25:43.574Z"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "SSH"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.allowed_ssh_cidr]
  }

  ingress {
    description = "HTTP"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "HTTPS"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description = "All outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "weebblade-sg"
  }
}

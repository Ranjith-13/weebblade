variable "aws_region" {
  description = "AWS region - the running instance lives in ap-south-2 (Hyderabad)"
  type        = string
  default     = "ap-south-2"
}

variable "instance_name" {
  description = "Name tag for the EC2 instance"
  type        = string
  default     = "weebblade"
}

variable "instance_type" {
  description = "EC2 instance type. m7i-flex.large (memory-optimized, ~2 vCPU/8GB) was chosen over c7i-flex.large (compute-optimized, ~2 vCPU/4GB) because Airflow + PySpark + Docker together are more memory-hungry than compute-hungry."
  type        = string
  default     = "m7i-flex.large"
}

variable "key_name" {
  description = "Name of the existing EC2 key pair to attach (weebblade-key). The private key isn't managed by Terraform - it was created via the console wizard and lives locally; Terraform can only reference an existing key pair by name, not recreate its private half."
  type        = string
  default     = "weebblade-key"
}

variable "root_volume_size_gb" {
  description = "Root EBS volume size in GB. 30GB stays within AWS's free-tier EBS allowance (up to 30GB/month free)."
  type        = number
  default     = 30
}

variable "allowed_ssh_cidr" {
  description = "CIDR allowed to SSH in on port 22 - should be your current IP/32, not 0.0.0.0/0. This changes whenever your IP does (check via `curl ifconfig.me`), so it's a variable rather than hardcoded - set it in terraform.tfvars, not here."
  type        = string
}

variable "ami_id" {
  description = "AMI ID, pinned to the exact Ubuntu 24.04.4 LTS AMI the instance was actually launched with in ap-south-2 - deliberately not a dynamic `data \"aws_ami\"` lookup, so a `terraform plan` after `terraform import` doesn't propose replacing a perfectly good running instance just because a newer Ubuntu AMI has since been published."
  type        = string
  default     = "ami-03f1d2b3639314198"
}

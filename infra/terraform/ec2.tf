resource "aws_instance" "weebblade" {
  ami                         = var.ami_id
  instance_type               = var.instance_type
  key_name                    = var.key_name
  vpc_security_group_ids      = [aws_security_group.weebblade.id]
  subnet_id                   = data.aws_subnets.default.ids[0]
  associate_public_ip_address = true

  root_block_device {
    volume_size = var.root_volume_size_gb
    volume_type = "gp3"
    iops        = 3000
  }

  tags = {
    Name = var.instance_name
  }

  lifecycle {
    # The box is provisioned by hand after launch (Docker Compose stack, deployed
    # code, generated secrets in .env) - don't let an unrelated AMI/tag/user-data
    # change trigger an accidental replace-and-lose-everything.
    prevent_destroy = true
  }
}

output "instance_id" {
  value = aws_instance.weebblade.id
}

output "public_ip" {
  value       = aws_instance.weebblade.public_ip
  description = "Not an Elastic IP - this changes if the instance is stopped/started."
}

output "security_group_id" {
  value = aws_security_group.weebblade.id
}

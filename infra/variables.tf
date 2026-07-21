variable "project" { default = "ecomlake" }
variable "sql_location" { default = "centralus" } # pick a cheap region near you
variable "env" { default = "dev" }
variable "sql_password" { sensitive = true }
variable "location" { default = "eastus2" } # pick a cheap region near you

locals {
  prefix = "${var.project}-${var.env}"
  tags = {
    project = var.project
    env     = var.env
    owner   = "muhammad-fawad"
  }
}
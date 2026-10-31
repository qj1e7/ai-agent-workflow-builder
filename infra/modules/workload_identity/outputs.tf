output "id" {
  description = "Identity resource ID. It resolves only after the role assignments have had time to propagate."
  value       = time_sleep.rbac_propagation.triggers["identity_id"]
}

output "principal_id" {
  description = "Object ID of the identity, for role assignments outside this module."
  value       = azurerm_user_assigned_identity.this.principal_id
}

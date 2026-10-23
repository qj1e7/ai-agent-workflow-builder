output "id" {
  description = "Identity resource ID. It resolves only after the role assignments have had time to propagate."
  value       = time_sleep.rbac_propagation.triggers["identity_id"]
}

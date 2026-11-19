output "name" {
  description = "The runner app's name, for az containerapp exec and logs."
  value       = azapi_resource.this.name
}

output "container_settings" {
  description = "The names of the settings the runner's container gets, none of them n8n's."
  value       = [for setting in azapi_resource.this.body.properties.template.containers[0].env : setting.name]
}

output "identity_in_containers" {
  description = "Whether any container can ask for the identity's token. It must stay false."
  value       = anytrue([for setting in azapi_resource.this.body.properties.configuration.identitySettings : setting.lifecycle != "None"])
}

output "identity_principal_id" {
  description = "Object ID of the runner's identity, which may only pull its image and read its token."
  value       = module.identity.principal_id
}

variable "subscription_id" {
  description = "Azure subscription to deploy into."
  type        = string
}

variable "environment" {
  description = "Environment name, part of every resource name."
  type        = string
  default     = "dev"
}

variable "location" {
  description = "Azure region for every resource."
  type        = string
  default     = "southeastasia"
}

variable "image_tag" {
  description = "Tag of our three images in the registry. The deploy workflow uses the commit SHA."
  type        = string
}

# The sign-in variables follow docs/auth/entra-setup.md, which says where each value comes from.
# Their rules match the checks platform-api and the Portal (portal/nginx/16-portal-auth.envsh) run
# at startup, so plan refuses a value that would stop an app. infra/scripts/check-variables.sh
# tests them.

variable "oidc_issuer" {
  description = "Issuer that platform-api trusts (OIDC_ISSUER), and the authority the Portal signs people in with (OIDC_AUTHORITY). For Entra ID, https://login.microsoftonline.com/<tenant-id>/v2.0."
  type        = string

  validation {
    condition     = can(regex("^https://[A-Za-z0-9._~%-]+([:/][A-Za-z0-9._~:/%-]*)?$", var.oidc_issuer))
    error_message = "oidc_issuer must be an https URL with a host and no query or fragment, made of letters, digits and . _ ~ : / % -."
  }
}

variable "oidc_audience" {
  description = "Audience that platform-api expects in access tokens (OIDC_AUDIENCE): the Application (client) ID of platform-api's app registration."
  type        = string

  validation {
    condition     = trimspace(var.oidc_audience) != ""
    error_message = "oidc_audience is not set. platform-api refuses to start without it."
  }

  validation {
    condition     = !startswith(var.oidc_audience, "api://")
    error_message = "oidc_audience is platform-api's Application (client) ID, not its api:// Application ID URI. Entra puts the client ID in the tokens' aud claim."
  }
}

variable "oidc_jwks_url" {
  description = "Where platform-api reads the signing keys (OIDC_JWKS_URL). Leave it empty, and platform-api reads the address from the issuer's discovery document."
  type        = string
  default     = ""

  validation {
    condition     = var.oidc_jwks_url == "" || can(regex("^https://[A-Za-z0-9._~%-]+([:/][A-Za-z0-9._~:/%-]*)?$", var.oidc_jwks_url))
    error_message = "oidc_jwks_url must be empty, or an https URL with a host and no query or fragment, made of letters, digits and . _ ~ : / % -."
  }
}

variable "oidc_client_id" {
  description = "Application (client) ID of the Portal's app registration (OIDC_CLIENT_ID). The Portal serves it from /config.json."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9._-]+$", var.oidc_client_id))
    error_message = "oidc_client_id must be set, and may only hold letters, digits and . _ -. The Portal refuses to start otherwise."
  }
}

variable "oidc_scope" {
  description = "Scopes the Portal asks for at sign-in (OIDC_SCOPE). For Entra ID, openid profile offline_access api://<api-client-id>/access_as_user."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9._:/-]+( [A-Za-z0-9._:/-]+)*$", var.oidc_scope))
    error_message = "oidc_scope must be scopes separated by single spaces, made of letters, digits and . _ : / -. The Portal refuses to start otherwise."
  }

  validation {
    condition     = contains(split(" ", var.oidc_scope), "openid")
    error_message = "oidc_scope must include openid. The Portal refuses to start without it."
  }
}

variable "n8n_owner_email" {
  description = "Email of the n8n owner account that the bootstrap job creates."
  type        = string
}

variable "github_api_base" {
  description = "GitHub API that the release checker reads."
  type        = string
  default     = "https://api.github.com"
}

variable "log_daily_quota_gb" {
  description = "Daily Log Analytics ingestion cap in GB."
  type        = number
  default     = 1
}

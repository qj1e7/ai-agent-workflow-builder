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

variable "github_token" {
  description = "Optional GitHub token for agent-runtime's release checker (GITHUB_TOKEN). Without one, GitHub allows 60 requests an hour per IP address, and Container Apps can share that address with other Azure customers. Empty sends no token."
  type        = string
  default     = ""
  sensitive   = true
}

variable "teams_channel" {
  description = "The Teams channel the approval card names (TEAMS_CHANNEL). Empty keeps platform-api's default, CODESparks Ops."
  type        = string
  default     = ""

  validation {
    condition     = var.teams_channel == "" || can(regex("^[^\\x00-\\x1f]{1,100}$", var.teams_channel))
    error_message = "teams_channel must be empty, or a channel name of at most 100 characters on one line."
  }
}

variable "teams_webhook_url" {
  description = "Optional Teams Workflows webhook that receives the approval cards (TEAMS_WEBHOOK_URL, ADR 0036). Its address carries its own signature, so it is a secret. Empty keeps the practice Teams copy."
  type        = string
  default     = ""
  sensitive   = true

  validation {
    condition     = var.teams_webhook_url == "" || can(regex("^https://[^\\s]+$", var.teams_webhook_url))
    error_message = "teams_webhook_url must be empty, or the https address Teams Workflows gave, with no spaces."
  }
}

variable "github_api_base" {
  description = "GitHub API that the release checker reads."
  type        = string
  default     = "https://api.github.com"
}

variable "practice_jira_url" {
  description = "Where agent-runtime reads the practice Jira (PRACTICE_JIRA_URL). Empty uses platform-api's own practice Jira, as Compose does. agent-runtime sends each task's callback token there, so it must be https."
  type        = string
  default     = ""

  validation {
    condition     = var.practice_jira_url == "" || can(regex("^https://[A-Za-z0-9._~%-]+([:/][A-Za-z0-9._~:/%-]*)?$", var.practice_jira_url))
    error_message = "practice_jira_url must be empty, or an https URL with a host and no query or fragment, made of letters, digits and . _ ~ : / % -."
  }
}

# The first people (ADR 0030). platform-api reads them only while its People list is empty, so a
# later deploy cannot hand out roles. The rules match platform-api's startup check, so plan refuses
# what would stop it. Real addresses go in the azure-dev environment's variables, never in git.
# They are not secret. Sensitive only keeps the addresses out of Terraform's errors in the deploy log.

variable "first_operator" {
  description = "Work email of the first Operator (FIRST_OPERATOR). Needed on the first deploy, when the People list is empty."
  type        = string
  default     = ""
  sensitive   = true

  validation {
    condition     = trimspace(var.first_operator) == "" || can(regex("^[^@,[:space:]]+@[^,[:space:]]*[.][^,[:space:]]*$", trimspace(var.first_operator)))
    error_message = "first_operator must be empty or one email address."
  }
}

variable "first_approvers" {
  description = "Work emails of the first two Approvers, separated by a comma (FIRST_APPROVERS). They must be two different people, and the first Operator may be one of them."
  type        = string
  default     = ""
  sensitive   = true

  validation {
    condition = trimspace(var.first_approvers) == "" || (
      length([for email in split(",", var.first_approvers) : email if trimspace(email) != ""]) == 2 &&
      length(distinct([for email in split(",", var.first_approvers) : lower(trimspace(email)) if trimspace(email) != ""])) == 2
    )
    error_message = "first_approvers must name two different people, separated by a comma, so nobody has to approve their own work."
  }

  validation {
    condition = alltrue([
      for email in split(",", var.first_approvers) :
      can(regex("^[^@,[:space:]]+@[^,[:space:]]*[.][^,[:space:]]*$", trimspace(email))) if trimspace(email) != ""
    ])
    error_message = "Each address in first_approvers must be an email."
  }

  validation {
    condition     = (trimspace(var.first_operator) == "") == (trimspace(var.first_approvers) == "")
    error_message = "first_operator and first_approvers go together: one email, and two emails separated by a comma."
  }
}

variable "cosmos_serverless" {
  description = "False makes the Cosmos DB account on the free tier, which a subscription may have once. True makes it serverless, which has no free tier and bills each request. Use true only when the free tier is refused (ADR 0031)."
  type        = bool
  default     = false
}

variable "cosmos_location" {
  description = "Region for the Cosmos DB account. Empty uses location. Set it when the subscription's policy or Azure's capacity refuses Cosmos DB in location."
  type        = string
  default     = ""
}

variable "log_daily_quota_gb" {
  description = "Daily Log Analytics ingestion cap in GB."
  type        = number
  default     = 1
}

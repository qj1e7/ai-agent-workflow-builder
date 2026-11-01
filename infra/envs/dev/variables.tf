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

# n8n's editor on Azure (ADR 0034). Off, n8n is internal, as before. On, its ingress is external.
# With no addresses listed, every address reaches n8n's sign-in page. With addresses, Container
# Apps lets in only those and the inside ranges below, and refuses the rest.

variable "n8n_editor_external" {
  description = "True opens n8n's editor at https://n8n.<domain>, behind n8n's own sign-in. False keeps n8n internal, reachable only by the other apps."
  type        = bool
  default     = false
}

# The addresses are not secret, but they point at people, and the deploy logs are public. Sensitive
# only keeps them out of Terraform's errors there.
variable "n8n_editor_allowed_ips" {
  description = "Public IPv4 addresses or ranges, separated by commas, that may reach n8n when n8n_editor_external is true, such as 203.0.113.7,198.51.100.0/24. One address means that address alone (/32). Empty lets every address reach n8n. Unused while n8n_editor_external is false."
  type        = string
  default     = ""
  sensitive   = true

  validation {
    condition = alltrue([
      for entry in split(",", var.n8n_editor_allowed_ips) :
      can(regex("^((25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])[.]){3}(25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])(/(1[6-9]|2[0-9]|3[0-2]))?$", trimspace(entry)))
      if trimspace(entry) != ""
    ])
    error_message = "Each entry in n8n_editor_allowed_ips must be an IPv4 address, such as 203.0.113.7, or a range of /16 or narrower, such as 198.51.100.0/24."
  }

  validation {
    condition = alltrue([
      for entry in split(",", var.n8n_editor_allowed_ips) :
      try(cidrhost(trimspace(entry), 0) == split("/", trimspace(entry))[0], true)
      if strcontains(entry, "/")
    ])
    error_message = "A range in n8n_editor_allowed_ips must start at its first address, such as 198.51.100.0/24, not 198.51.100.7/24."
  }

  # Azure only sees an address from the internet. These ranges are inside a home, an office, an
  # internet provider or Azure, so an entry in one of them can never match.
  validation {
    condition = alltrue([
      for entry in split(",", var.n8n_editor_allowed_ips) :
      !anytrue([
        for private in ["0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8", "169.254.0.0/16", "172.16.0.0/12", "192.168.0.0/16"] :
        try(cidrhost("${split("/", trimspace(entry))[0]}/${split("/", private)[1]}", 0) == split("/", private)[0], false)
      ])
      if trimspace(entry) != ""
    ])
    error_message = "n8n_editor_allowed_ips must hold public addresses. Addresses such as 10.x, 172.16.x to 172.31.x, 192.168.x and 100.64.x to 100.127.x are inside a network, so Azure never sees them. Use the address that a \"what is my IP\" page shows."
  }
}

variable "n8n_internal_allowed_cidrs" {
  description = "IPv4 ranges, separated by commas, that n8n's allow list also lets in, so platform-api and the bootstrap job still reach n8n. Empty uses the ranges Microsoft reserves in a workload profiles environment: 100.100.0.0/17, 100.100.128.0/19, 100.100.160.0/19 and 100.100.192.0/19. Used only when n8n_editor_allowed_ips is set and n8n_editor_external is true."
  type        = string
  default     = ""

  validation {
    condition = alltrue([
      for entry in split(",", var.n8n_internal_allowed_cidrs) :
      can(regex("^((25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])[.]){3}(25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])(/(1[6-9]|2[0-9]|3[0-2]))?$", trimspace(entry)))
      if trimspace(entry) != ""
    ])
    error_message = "Each entry in n8n_internal_allowed_cidrs must be an IPv4 address or a range of /16 or narrower, such as 100.100.0.0/17."
  }

  validation {
    condition = alltrue([
      for entry in split(",", var.n8n_internal_allowed_cidrs) :
      try(cidrhost(trimspace(entry), 0) == split("/", trimspace(entry))[0], true)
      if strcontains(entry, "/")
    ])
    error_message = "A range in n8n_internal_allowed_cidrs must start at its first address, such as 100.100.0.0/17, not 100.100.0.51/17."
  }
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

# A real Jira (ADR 0035). Leave jira_base_url empty to keep platform-api's own practice Jira. The
# rules match platform-api's startup check, so plan refuses what would stop it.

variable "jira_base_url" {
  description = "A real Jira's address (JIRA_BASE_URL), such as https://jira.example.com. Empty uses platform-api's own practice Jira. The token goes there with every call, so it must be https."
  type        = string
  default     = ""

  validation {
    condition     = var.jira_base_url == "" || can(regex("^https://[A-Za-z0-9._~%-]+([:/][A-Za-z0-9._~:/%-]*)?$", var.jira_base_url))
    error_message = "jira_base_url must be empty, or an https URL with a host and no query or fragment, made of letters, digits and . _ ~ : / % -."
  }
}

variable "jira_api_flavor" {
  description = "Which Jira API to speak (JIRA_API_FLAVOR): datacenter (REST v2) or cloud (REST v3). The practice Jira speaks both."
  type        = string
  default     = "datacenter"

  validation {
    condition     = contains(["datacenter", "cloud"], var.jira_api_flavor)
    error_message = "jira_api_flavor must be datacenter or cloud."
  }
}

variable "jira_api_token" {
  description = "The Jira token (JIRA_API_TOKEN), kept in Key Vault as jira-api-token: a personal access token for Data Center, or an API token for Cloud. Needed with jira_base_url."
  type        = string
  default     = ""
  sensitive   = true

  validation {
    condition     = var.jira_base_url == "" || var.jira_api_token != ""
    error_message = "jira_api_token must be set when jira_base_url is."
  }
}

variable "jira_email" {
  description = "The Jira account's email (JIRA_EMAIL). Cloud signs in with it and the token."
  type        = string
  default     = ""
  sensitive   = true

  validation {
    condition     = var.jira_base_url == "" || var.jira_api_flavor != "cloud" || trimspace(var.jira_email) != ""
    error_message = "jira_email must be set for a Cloud Jira."
  }
}

variable "jira_issue_type" {
  description = "The issue type of each new ticket (JIRA_ISSUE_TYPE)."
  type        = string
  default     = "Task"

  validation {
    condition     = trimspace(var.jira_issue_type) != ""
    error_message = "jira_issue_type must name an issue type, such as Task."
  }
}

variable "jira_browse_url" {
  description = "Where people open a ticket (JIRA_BROWSE_URL), with {key} where the key goes. Empty uses jira_base_url/browse/{key}, or the Portal's Practice Jira page."
  type        = string
  default     = ""

  validation {
    condition     = var.jira_browse_url == "" || (strcontains(var.jira_browse_url, "{key}") && can(regex("^https?://[^/?#\\s]+", var.jira_browse_url)))
    error_message = "jira_browse_url must be empty, or an http or https address with {key} in it."
  }
}

variable "watchlist_jira_project" {
  description = "The Jira project the watchlist raises tickets in (WATCHLIST_JIRA_PROJECT). MOCK is the practice Jira's."
  type        = string
  default     = "MOCK"

  validation {
    condition     = can(regex("^[A-Z][A-Z0-9_]{0,254}$", var.watchlist_jira_project))
    error_message = "watchlist_jira_project must be a Jira project key: a capital letter, then capital letters, digits or underscores."
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

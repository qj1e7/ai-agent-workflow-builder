locals {
  # A B2as_v2 starts with 60 credits and earns 48 an hour. At full load on both vCPUs it spends
  # about 1.2 more a minute than it earns, so 50 left is about 40 minutes before Azure throttles
  # it to its 40% base.
  cpu_credits_alert_below = 50
  disk_used_alert_percent = 80
}

resource "azurerm_monitor_action_group" "this" {
  count = nonsensitive(var.alert_email != "") ? 1 : 0

  name                = "ag-${var.name}"
  resource_group_name = var.resource_group_name
  short_name          = "langfuse"
  tags                = var.tags

  email_receiver {
    name                    = "team"
    email_address           = var.alert_email
    use_common_alert_schema = true
  }
}

# ClickHouse's background work can use up the burstable VM's CPU credits, which docker stats cannot see.
resource "azurerm_monitor_metric_alert" "cpu_credits" {
  name                = "alert-${var.name}-cpu-credits"
  resource_group_name = var.resource_group_name
  scopes              = [azurerm_linux_virtual_machine.this.id]
  description         = "The Langfuse VM has fewer than ${local.cpu_credits_alert_below} CPU credits left. Azure throttles it to its base when they run out. ADR 0050 says when to move to Standard_B4as_v2."
  severity            = 2
  frequency           = "PT5M"
  window_size         = "PT15M"
  tags                = var.tags

  criteria {
    metric_namespace = "Microsoft.Compute/virtualMachines"
    metric_name      = "CPU Credits Remaining"
    aggregation      = "Average"
    operator         = "LessThan"
    threshold        = local.cpu_credits_alert_below
  }

  dynamic "action" {
    for_each = azurerm_monitor_action_group.this
    content {
      action_group_id = action.value.id
    }
  }
}

# Azure has no platform metric for how full a VM's disk is, so Azure Monitor Agent sends the root
# file system's use to the Log Analytics workspace, and a log alert reads it.
resource "azurerm_virtual_machine_extension" "monitor_agent" {
  name                       = "AzureMonitorLinuxAgent"
  virtual_machine_id         = azurerm_linux_virtual_machine.this.id
  publisher                  = "Microsoft.Azure.Monitor"
  type                       = "AzureMonitorLinuxAgent"
  type_handler_version       = "1.0"
  auto_upgrade_minor_version = true
  automatic_upgrade_enabled  = true
  tags                       = var.tags

  settings = jsonencode({
    authentication = {
      managedIdentity = {
        identifier-name  = "mi_res_id"
        identifier-value = azurerm_user_assigned_identity.this.id
      }
    }
  })
}

resource "azurerm_monitor_data_collection_rule" "disk" {
  name                = "dcr-${var.name}-disk"
  location            = var.location
  resource_group_name = var.resource_group_name
  kind                = "Linux"
  tags                = var.tags

  destinations {
    log_analytics {
      name                  = "workspace"
      workspace_resource_id = var.log_analytics_workspace_id
    }
  }

  data_flow {
    streams      = ["Microsoft-Perf"]
    destinations = ["workspace"]
  }

  data_sources {
    performance_counter {
      name                          = "disk-used"
      streams                       = ["Microsoft-Perf"]
      sampling_frequency_in_seconds = 300
      counter_specifiers            = ["Logical Disk(*)\\% Used Space"]
    }
  }
}

resource "azurerm_monitor_data_collection_rule_association" "disk" {
  name                    = "disk-used"
  target_resource_id      = azurerm_linux_virtual_machine.this.id
  data_collection_rule_id = azurerm_monitor_data_collection_rule.disk.id
}

resource "azurerm_monitor_scheduled_query_rules_alert_v2" "disk" {
  name                 = "alert-${var.name}-disk"
  location             = var.location
  resource_group_name  = var.resource_group_name
  scopes               = [azurerm_linux_virtual_machine.this.id]
  description          = "The Langfuse VM's disk is at least ${local.disk_used_alert_percent}% full. ClickHouse cannot write traces to a full disk."
  severity             = 2
  evaluation_frequency = "PT15M"
  window_duration      = "PT15M"
  tags                 = var.tags

  criteria {
    query                   = <<-KQL
      Perf
      | where ObjectName == "Logical Disk" and CounterName == "% Used Space" and InstanceName == "/"
    KQL
    time_aggregation_method = "Maximum"
    metric_measure_column   = "CounterValue"
    operator                = "GreaterThanOrEqual"
    threshold               = local.disk_used_alert_percent

    failing_periods {
      minimum_failing_periods_to_trigger_alert = 1
      number_of_evaluation_periods             = 1
    }
  }

  dynamic "action" {
    for_each = azurerm_monitor_action_group.this
    content {
      action_groups = [action.value.id]
    }
  }
}

# nagios-plugin-azure-resource

Nagios plugin to monitor Microsoft Azure resource objects.

## Authors

Mohamed El Morabity <melmorabity -(at)- fedoraproject.org>

## Requirements

The plugin is written in Python 2. It requires the following libraries:

* [pynag](https://pypi.python.org/pypi/pynag)
* [msrestazure](https://pypi.python.org/pypi/msrestazure) >= 0.4.15

## Usage
```
Usage: check_azure_resource.py [options]

Options:
  -h, --help            show this help message and exit
  -C CLIENT, --client=CLIENT
                        Azure client ID
  -S SECRET, --secret=SECRET
                        Azure client secret
  -T TENANT, --tenant=TENANT
                        Azure tenant ID
  -R RESOURCE, --resource=RESOURCE
                        Azure resource ID
  -M METRIC, --metric=METRIC
                        Metric
  -a AGGREGATION, --aggregation=AGGREGATION
                        Aggregation
  -f FILTER, --filter=FILTER
                        Filter
  -D DIMENSION, --dimension=DIMENSION
                        Metric dimension
  -V DIMENSION-VALUE, --dimension-value=DIMENSION-VALUE
                        Metric dimension value
  -v VERBOSE, --verbose=VERBOSE
                        Verbosity Level
  -H HOST, --host=HOST  
                        Optionnal Alternative Azure Management URL 
                        (default: 'management.azure.com')
  -t TIMEOUT, --timeout=TIMEOUT
                        Connection Timeout
  -c CRITICAL, --critical=CRITICAL
                        Critical Threshhold
  -w WARNING, --warning=WARNING
                        Warn Threshhold
```

### Focus on RESOURCE

Azure resource ID in the following format: 
    `/subscriptions/<subscriptionId>/resourceGroups/<resourceGroupName>/providers/<resourceProviderNamespace>/<resourceType>/<resourceName>`

### Focus on parameters linked to metric input

See https://docs.microsoft.com/en-us/azure/monitoring-and-diagnostics/monitoring-supported-metrics for a list of all metrics available for each resource type).
See https://docs.microsoft.com/en-us/rest/api/monitor/metrics/list for additionnel information about some parameters definition like aggregation of filter.

Note: see [Azure documentation about roles, permissions and security with Azure Monitor](https://docs.microsoft.com/en-us/azure/monitoring-and-diagnostics/monitoring-roles-permissions-security) to limit access to resources for monitoring.

Azure metrics contain different dimensions allowing to filter or split metric into different sub-values.
There are two way to filter across dimensions :

#### Parameter Dimension and Dimension-Value

Those two parameters must be uses together. 
They are not compatible with 'filter' parameter.

Dimension is used to set the name of the dimension to filter on.
Dimension-Value allow to set the value of the dimension.

#### Parameter Filter

Allow to filter metric according to one or more metric metadata.
ex: If Metric contain metadata A, B and C:

``` -f "A eq 'a1' and B eq 'b1' or B eq 'b2' and C eq ''"```

This paramter can also be used to split metric if this metric allow to.
In that case, each submetric is tested and displayed in the pugin output.

```-f "A eq 'a1' and B eq 'b1' or B eq 'b2' and C eq '*'"```

#### Parameter Aggregation

Allow to change the default aggregation type.
If not set, plugin will use the mainAggregationType defined by Azure for this metric.

Values can be Average, Count, Total, Min, Max, ...

### Thresholds

Warning and Critical thresholds for Nagios/Centreon output.

| Range definition | Generate an alert if x... |
| --- | --- |
| 10 | < 0 or > 10, (outside the range of {0 .. 10}) |
| 10: | < 10, (outside {10 .. ∞}) |
| ~:10 | > 10, (outside the range of {-∞ .. 10}) |
| 10:20 | < 10 or > 20, (outside the range of {10 .. 20}) |
| @10:20 | ≥ 10 and ≤ 20, (inside the range of {10 .. 20}) |


See https://nagios-plugins.org/doc/guidelines.html#PLUGOUTPUT for more informations about possibilities.

### Verbosity

If Verbosity Level is 2, then Log API Requests
If Verbosity Level is 3, then Log Level 2 AND Azure API Responses

## Examples

    $ ./check_azure_resource.py \
        --client=XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX \
        --secret=XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX \
        --tenant=XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX \
        --resource /subscriptions/XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX/resourceGroups/myResourceGroup/providers/Microsoft.Compute/virtualMachines/myVirtualMachine \
        --metric 'Percentage CPU' \
        --warning 50 --critical 75
    OK: Percentage CPU 3.865 percent | 'Percentage CPU'=3.865%;50;75;;

    $ ./check_azure_resource.py \
        --client=XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX \
        --secret=XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX \
        --tenant=XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX \
        --resource /subscriptions/XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX/resourceGroups/myResourceGroup/providers/Microsoft.Sql/servers/myDBServer \
        --metric storage_used \
        --dimension DatabaseResourceId \
        --dimension-value /subscriptions/XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX/resourceGroups/myResourceGroup/providers/Microsoft.Sql/servers/myDBServer/databases/myDB \
        --warning 25000000000 --critical 50000000000
    WARNING: Storage used 36783194112.0 bytes | 'storage_used'=36783194112.0B;25000000000;50000000000;;

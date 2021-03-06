#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright (C) 2018 Mohamed El Morabity <melmorabity@fedoraproject.com>
#
# This module is free software: you can redistribute it and/or modify it under the terms of the GNU
# General Public License as published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This software is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without
# even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with this program. If not,
# see <http://www.gnu.org/licenses/>.

#
# For nagios/centreon threshold possible values, 
# please see https://nagios-plugins.org/doc/guidelines.html#PLUGOUTPUT
#

import logging as log
import logging.config

from msrest.exceptions import ClientException
from msrest.service_client import ServiceClient

from msrestazure.azure_active_directory import ServicePrincipalCredentials
from msrestazure.azure_configuration import AzureConfiguration
from msrestazure.azure_exceptions import CloudError
import msrestazure.tools

from pynag import Plugins
from pynag.Plugins import simple as Plugin
from pynag.Plugins import PluginHelper as PluginHelper

from requests.exceptions import HTTPError


def _call_arm_rest_api(client, path, api_version, method='GET', body=None, query=None,
                       headers=None, timeout=None):
    """Launch an Azure REST API request."""

    request = getattr(client, method.lower())(
        url=path, params=dict(query or {}, **{'api-version': api_version})
    )
    response = client.send(
        request=request, content=body,
        headers=dict(headers or {}, **{'Content-Type': 'application/json; charset=utf-8'}),
        timeout=timeout
    )

    log.info("Request URL : \n{0}\n".format(request.url))

    try:
        response.raise_for_status()
    except HTTPError:
        # msrestazure.azure_exceptions.CloudError constructor provides a nice way to extract
        # Azure errors from request responses
        raise CloudError(response)

    try:
        result = response.json()
    except ValueError as ex:
        log.warning("_call_arm_rest_api : Failed to convert response to JSON ({0})\n".format(ex.message))
        result = response.text

    log.debug("Response : \n{0}\n".format(result))

    return result


class NagiosAzureResourceMonitor(Plugin):
    """Implements functionalities to grab metrics from Azure resource objects."""

    DEFAULT_AZURE_SERVICE_HOST = 'management.azure.com'
    _AZURE_METRICS_API = '2018-01-01'
    _AZURE_METRICS_UNIT_SYMBOLS = { 'Percent': '%', 
                                    'Bytes': 'B',
                                    'Seconds': 's',
                                    'MilliSeconds': 'ms',
                                    'BytesPerSecond': 'B/s',
                                    'CountPerSecond': '/s'}

    def __init__(self, *args, **kwargs):
        Plugin.__init__(self, *args, **kwargs)

        self._set_cli_options()
        #self._load_config()

    def _set_cli_options(self):
        """Define command line options."""

        self.add_arg('C', 'client', 'Azure client ID')
        self.add_arg('S', 'secret', 'Azure client secret')
        self.add_arg('T', 'tenant', 'Azure tenant ID')

        self.add_arg('R', 'resource', 'Azure resource ID')
        self.add_arg('M', 'metric', 'Metric')
        
        self.add_arg('a', 'aggregation', 'Aggregation', required=None)
        self.add_arg('f', 'filter', 'Filter', required=None)
        self.add_arg('D', 'dimension', 'Metric dimension', required=None)
        self.add_arg('V', 'dimension-value', 'Metric dimension value', required=None)

    def activate(self):
        """Parse out all command line options and get ready to process the plugin."""
        Plugin.activate(self)

        # Load config for logging
        self.load_config()

        if not msrestazure.tools.is_valid_resource_id(self['resource']):
            self.parser.error('invalid resource ID')

        if bool(self['dimension']) != bool(self['dimension-value']):
            self.parser.error('--dimension and --dimension-value must be used together')

        if bool(self['filter']) and bool(self['dimension']):
            self.parser.error('--dimension and --filter are exclusives')
            
        # Set up Azure Resource Management URL
        if self['host'] is None:
            self['host'] = self.DEFAULT_AZURE_SERVICE_HOST

        # Set up timeout
        if self['timeout'] is not None:
            try:
                self['timeout'] = float(self['timeout'])
                if self['timeout'] < 0:
                    raise ValueError
            except ValueError as ex:
                self.parser.error('Invalid timeout')

        # Authenticate to ARM
        azure_management_url = 'https://{}'.format(self['host'])
        try:
            credentials = ServicePrincipalCredentials(client_id=self['client'],
                                                      secret=self['secret'],
                                                      tenant=self['tenant'])
            self._client = ServiceClient(credentials, AzureConfiguration(azure_management_url))
        except ClientException as ex:
            self.nagios_exit(Plugins.UNKNOWN, str(ex.inner_exception or ex))

        try:
            self._metric_definitions = self._get_metric_definitions()
        except CloudError as ex:
            self.nagios_exit(Plugins.UNKNOWN, ex.message)

        metric_ids = [m['name']['value'] for m in self._metric_definitions]
        if self['metric'] not in metric_ids:
            self.parser.error(
                'Unknown metric {} for specified resource. ' \
                'Supported metrics are: {}'.format(self['metric'], ', '.join(metric_ids))
            )
        self._metric_properties = self._get_metric_properties()

        dimension_ids = [d['value'] for d in self._metric_properties.get('dimensions', [])]
        if self._is_dimension_required() and (self['dimension'] is None and self['filter'] is None):
            self.parser.error(
                'Dimension of Filter required for metric {}. ' \
                'Supported dimensions/filters are: {}'.format(self['metric'], ', '.join(dimension_ids))
            )
        if self['dimension'] is not None and self['dimension'] not in dimension_ids:
            self.parser.error(
                'Unknown dimension {} for metric {}. ' \
                'Supported dimensions are: {}'.format(self['dimension'], self['metric'],
                                                      ', '.join(dimension_ids))
            )
            
        aggregation_ids = self._metric_properties.get('supportedAggregationTypes', [])
        if self['aggregation'] is not None and self['aggregation'] not in aggregation_ids:
            self.parser.error(
                'Unsupported aggregation {} for metric {}. ' \
                'Supported aggregations are: {}'.format(self['aggregation'], self['metric'],
                                                        ', '.join(aggregation_ids))
            )

    def _get_metric_definitions(self):
        """Get all available metric definitions for the Azure resource object."""

        path = '{}/providers/Microsoft.Insights/metricDefinitions'.format(self['resource'])
        metrics = _call_arm_rest_api(self._client, path, self._AZURE_METRICS_API,
                                     timeout=self['timeout'])

        return metrics['value']

    def _get_metric_properties(self):
        """Get metric properties."""

        for metric in self._metric_definitions:
            if metric['name']['value'] == self['metric']:
                return metric

        return None

    def _is_dimension_required(self):
        """Check whether an additional metric is required for a given metric ID."""

        return self._metric_properties['isDimensionRequired']

    def _get_metric_values(self):
        """Get latest metric value available for the Azure resource object."""

        # Prepare Query
        query = {'metricnames': self['metric']}
        path = '{}/providers/Microsoft.Insights/metrics/'.format(self['resource'])

        # Handling dimension and filters
        if self['dimension'] is not None:
            query['$filter'] = "{} eq '{}'".format(self['dimension'], self['dimension-value'])
        elif self['filter'] is not None:
            query['$filter'] = self['filter']
        # Handling aggregation    
        if self['aggregation'] is not None:
            query['aggregation'] = self['aggregation']

        # Call API
        try:
            timeseries = _call_arm_rest_api(self._client, path,
                                               self._AZURE_METRICS_API, query=query,
                                               timeout=self['timeout'])
            timeseries = timeseries['value'][0]['timeseries']
        except CloudError as ex:
            self.nagios_exit(Plugins.UNKNOWN, ex.message)
        except Exception as ex:
            self.nagios_exit(Plugins.UNKNOWN, "Error wile getting timeseries data from Azure API JSON response (may be not a valid JSON)")

        # Check result
        if not timeseries:
            return None

        # Allow to get correct value according to parameter or primaryAggregationType
        if self['aggregation'] is not None:
            aggregation_type = self['aggregation'].lower()
        else:
            aggregation_type = self._metric_properties['primaryAggregationType'].lower()
            
        # Loop on all timeseries in case of data split (according to filter like A eq '*')
        metric_values = {}
        for metric_value in timeseries:
            # Get name of current timeseries or global metric name if only one timeserie available
            metric_name_ids = [d['value'] for d in metric_value.get('metadatavalues', [])]
            if len(metric_name_ids) > 0:
                metric_name = '{}'.format('_'.join(metric_name_ids))
            else:
                metric_name = self._metric_properties['name']['value']
            
            # Get the latest value available accross timeseries ("::-1" create a teporary reversed list)
            metric_values[metric_name] = None
            for value in metric_value['data'][::-1]:
                if aggregation_type in value:
                    metric_values[metric_name] = value[aggregation_type]
                    break;
        
        # Return array of metric_values
        return metric_values

    def check_metric(self):
        """Check if the metric value is within the threshold range, and exits with status code,
        message and perfdata.
        """

        # Get values
        metric_values = self._get_metric_values()
        unit = self._AZURE_METRICS_UNIT_SYMBOLS.get(self._metric_properties['unit'])
        if unit is None:
            unit = ''

        # Test if value to display
        if metric_values is None:
            message = 'No value available for metric {}'.format(self['metric'])
            if self['dimension'] is not None:
                message += ' and dimension {}'.format(self['dimension'])
            self.nagios_exit(Plugins.UNKNOWN, message)

        # PluginHelper of pynag import
        # https://pynag.readthedocs.io/en/latest/pynag.Plugins.html?highlight=check_threshold#pynag.Plugins.PluginHelper
        p = PluginHelper()
        
        # For each value, declare metric with according thresholds 
        for metric_idx in metric_values:
            p.add_metric(label=metric_idx,  value=metric_values[metric_idx], 
                                            uom=unit,
                                            warn=self['warning'], crit=self['critical'])

        # Test all metrics according to there thresholds
        p.check_all_metrics()
        
        # Add global summary for output
        p.add_summary(self._metric_properties['name']['localizedValue'])

        # Exit and display plugin output
        p.exit()

    def load_config(self):

        # Init default conf
        config = {
            "logging": {
                "version": 1,
                "formatters": {
                    "simple": {
                        "format": "%(asctime)s %(levelname)s %(message)s"
                    }
                } ,
                "handlers": {
                    "console": {
                        "class": "logging.StreamHandler",
                        "level": "ERROR",
                        "formatter": "simple",
                        "stream": "ext://sys.stdout"
                    }
                },
                "root": {
                    "level": "DEBUG",
                    "handlers": ["console"]
                }
            }
        }

        if self.data['verbosity'] == 1 :
            config["logging"]["handlers"]["console"]["level"] = "WARNING"
            Plugin.verbose = True
        elif self.data['verbosity'] == 2 :
            config["logging"]["handlers"]["console"]["level"] = "INFO"
            Plugin.verbose = True
        elif self.data['verbosity'] == 3 :
            config["logging"]["handlers"]["console"]["level"] = "DEBUG"
            Plugin.verbose = True
            Plugin.show_debug = True

        # Init logging
        logging.config.dictConfig(config["logging"])


if __name__ == '__main__':
    PLUGIN = NagiosAzureResourceMonitor()
    PLUGIN.activate()
    PLUGIN.check_metric()

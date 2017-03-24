"""
Check licences of all files of a package

Uses oslc and a matches against a list from Pelc

Output: list of detected licenses

"""

from cucoslib.utils import (get_command_output, assert_not_none)
from cucoslib.base import BaseTask
from cucoslib.schemas import SchemaRef
from cucoslib.object_cache import ObjectCache


class LicenseCheckTask(BaseTask):
    _analysis_name = 'source_licenses'
    description = "Check licences of all files of a package"
    schema_ref = SchemaRef(_analysis_name, '2-0-0')

    def execute(self, arguments):
        """
        task code

        :param arguments: dictionary with arguments
        :return: {}, results
        """
        self._strict_assert(arguments.get('ecosystem'))
        self._strict_assert(arguments.get('name'))
        self._strict_assert(arguments.get('version'))

        cache_path = ObjectCache.get_from_dict(arguments).get_sources()

        result_data = {'status': 'unknown',
                       'summary': {},
                       'details': {}}
        try:
            result_data['details'] = get_command_output(['cucos_license_check.py',
                                                         cache_path],
                                                        graceful=False,
                                                        is_json=True)
            result_data['status'] = result_data['details'].pop('status')
            result_data['summary'] = result_data['details'].pop('summary')
        except:
            self.log.exception("License scan failed")
            result_data['status'] = 'error'

        return result_data
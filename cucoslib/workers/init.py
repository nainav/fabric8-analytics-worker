import os
import datetime
import shutil
from tempfile import mkdtemp
from cucoslib.object_cache import ObjectCache
from cucoslib.base import BaseTask
from cucoslib.process import IndianaJones, MavenCoordinates
from cucoslib.models import Analysis, EcosystemBackend, Ecosystem, Version, Package
from cucoslib.utils import get_latest_analysis


class InitAnalysisFlow(BaseTask):
    def execute(self, arguments):
        self._strict_assert(arguments.get('name'))
        self._strict_assert(arguments.get('version'))
        self._strict_assert(arguments.get('ecosystem'))

        db = self.storage.session
        e = Ecosystem.by_name(db, arguments['ecosystem'])
        p = Package.get_or_create(db, ecosystem_id=e.id, name=arguments['name'])
        v = Version.get_or_create(db, package_id=p.id, identifier=arguments['version'])

        if not arguments.get('force'):
            # TODO: this is OK for now, but if we will scale and there will be 2+ workers running this task
            # they can potentially schedule two flows of a same type at the same time
            if db.query(Analysis).filter(Analysis.version_id == v.id).count() > 0:
                return None

        cache_path = mkdtemp(dir=self.configuration.worker_data_dir)
        epv_cache = ObjectCache.get_from_dict(arguments)
        ecosystem = Ecosystem.by_name(db, arguments['ecosystem'])

        try:
            if not epv_cache.has_source_tarball():
                _, source_tarball_path = IndianaJones.fetch_artifact(
                    ecosystem=ecosystem,
                    artifact=arguments['name'],
                    version=arguments['version'],
                    target_dir=cache_path
                )
                epv_cache.put_source_tarball(source_tarball_path)

            if ecosystem.is_backed_by(EcosystemBackend.maven):
                if not epv_cache.has_source_jar():
                    try:
                        source_jar_path = self._download_source_jar(cache_path, ecosystem, arguments)
                        epv_cache.put_source_jar(source_jar_path)
                    except Exception as e:
                        self.log.info(
                            'Failed to fetch source jar for maven artifact "{e}/{p}/{v}": {err}'.format(
                                e=arguments.get('ecosystem'),
                                p=arguments.get('name'),
                                v=arguments.get('version'),
                                err=str(e)
                            )
                        )

                if not epv_cache.has_pom_xml():
                    pom_xml_path = self._download_pom_xml(cache_path, ecosystem, arguments)
                    epv_cache.put_pom_xml(pom_xml_path)
        finally:
            # always clean up cache
            shutil.rmtree(cache_path)

        a = Analysis(version=v, access_count=1, started_at=datetime.datetime.now())
        db.add(a)
        db.commit()

        arguments['document_id'] = a.id
        return arguments

    @staticmethod
    def _download_source_jar(target, ecosystem, arguments):
        artifact_coords = MavenCoordinates.from_str(arguments['name'])
        sources_classifiers = ['sources', 'src']

        if artifact_coords.classifier not in sources_classifiers:
            for sources_classifier in sources_classifiers:
                artifact_coords.classifier = sources_classifier
                try:
                    _, source_jar_path = IndianaJones.fetch_artifact(
                        ecosystem=ecosystem,
                        artifact=artifact_coords.to_str(omit_version=True),
                        version=arguments['version'],
                        target_dir=target
                    )
                except Exception:
                    if sources_classifier == sources_classifiers[-1]:
                        # fetching of all variants failed
                        raise
                else:
                    return source_jar_path

    @staticmethod
    def _download_pom_xml(target, ecosystem, arguments):
        artifact_coords = MavenCoordinates.from_str(arguments['name'])
        artifact_coords.packaging = 'pom'
        artifact_coords.classifier = ''  # pom.xml files have no classifiers

        IndianaJones.fetch_artifact(
            ecosystem=ecosystem,
            artifact=artifact_coords.to_str(omit_version=True),
            version=arguments['version'],
            target_dir=target
        )

        # pom has to be named precisely pom.xml, otherwise mercator's Java handler
        #  which uses maven as subprocess won't see it
        pom_xml_path = os.path.join(target, 'pom.xml')
        os.rename(
            os.path.join(target,
                         '{}-{}.pom'.format(artifact_coords.artifactId, arguments['version'])),
            pom_xml_path
        )
        return pom_xml_path


class FinishedAnalysisGateTask(BaseTask):
    _RETRY_COUNTDOWN = 10

    def run(self, arguments):
        self._strict_assert(arguments.get('ecosystem'))
        self._strict_assert(arguments.get('name'))
        self._strict_assert(arguments.get('version'))

        analysis_result = get_latest_analysis(arguments['ecosystem'], arguments['name'], arguments['version'])
        if not analysis_result.finished_at:
            self.retry(self._RETRY_COUNTDOWN)

        raise NotImplementedError()
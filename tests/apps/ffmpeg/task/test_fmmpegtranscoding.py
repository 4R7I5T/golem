import shutil
import uuid
from unittest import mock

from apps.transcoding.common import ffmpegException
from apps.transcoding.ffmpeg.utils import StreamOperator, Commands, \
    FFMPEG_BASE_SCRIPT
from coverage.annotate import os
from golem.docker.job import DockerJob
from golem.docker.manager import DockerManager
from golem.docker.task_thread import DockerTaskThread
from golem.resource.dirmanager import DirManager
from golem.testutils import TempDirFixture
from tests.golem.docker.test_docker_image import DockerTestCase
from tests.golem.docker.test_docker_job import TestDockerJob


class TestffmpegTranscoding(TempDirFixture, DockerTestCase):
    def setUp(self):
        super(TestffmpegTranscoding, self).setUp()
        self.RESOURCES = os.path.join(os.path.dirname(
            os.path.dirname(os.path.realpath(__file__))), 'resources')
        self.RESOURCE_STREAM = os.path.join(self.RESOURCES, 'test_video2.mp4')
        dm = DockerTaskThread.docker_manager = DockerManager.install()
        dm.update_config(
            status_callback=mock.Mock(),
            done_callback=mock.Mock(),
            work_dir=self.new_path,
            in_background=True)

    def test_split_video(self):
        stream_operator = StreamOperator()
        for parts in [1, 2]:
            with self.subTest('Testing splitting', parts=parts):
                chunks = stream_operator.split_video(
                    self.RESOURCE_STREAM, parts, DirManager(self.tempdir),
                    str(uuid.uuid4()))
                self.assertEqual(len(chunks), parts)

    def test_split_invalid_video(self):
        stream_operator = StreamOperator()
        with self.assertRaises(ffmpegException):
            stream_operator.split_video(os.path.join(self.RESOURCES,
                                                     'invalid_test_video2.mp4'),
                                        1, DirManager(self.tempdir),
                                        str(uuid.uuid4()))


class TestffmpegDockerJob(TestDockerJob):
    def _get_test_repository(self):
        return "golemfactory/ffmpeg"

    def _get_test_tag(self):
        return "1.0"

    def test_ffmpeg_trancoding_job(self):
        stream_file = os.path.join(os.path.join(os.path.dirname(
            os.path.dirname(os.path.realpath(__file__))), 'resources'),
            'test_video.mp4')
        shutil.copy(str(stream_file), self.resources_dir)
        out_stream_path = os.path.join(DockerJob.OUTPUT_DIR, 'test_video2.mp4')
        params = {
            'track': os.path.join(DockerJob.RESOURCES_DIR, 'test_video.mp4'),
            'targs': {
                'resolution': [160, 120]
            },
            'output_stream': out_stream_path,
            'command': Commands.TRANSCODE.value[0],
            'use_playlist': 0,
            'script_filepath': FFMPEG_BASE_SCRIPT
        }

        # porownac paramsy.json

        with self._create_test_job(script=FFMPEG_BASE_SCRIPT,
                                   params=params) as job:
            job.start()
            exit_code = job.wait(timeout=300)
            self.assertEqual(exit_code, 0)

        out_files = os.listdir(self.output_dir)
        self.assertEqual(out_files, ['test_video_TC.mp4'])

import logging
import os

from golem.verificator import CoreVerifier
from golem.verificator.verifier import SubtaskVerificationState

logger = logging.getLogger(__name__)


class FFmpegVerifier(CoreVerifier):
    def __init__(self, verification_data):
        super(FFmpegVerifier, self).__init__()
        self.results = verification_data['results']
        self.state = SubtaskVerificationState.WAITING

    def simple_verification(self, verification_data):
        verdict = super().simple_verification(verification_data)

        # TODO more verification

        self.state = SubtaskVerificationState.VERIFIED if verdict \
            else SubtaskVerificationState.WRONG_ANSWER

        return verdict

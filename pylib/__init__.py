'''Headless LLM agent runner: scheduled jobs, skills/flows, email reports, blotter.'''

import os

from anya.__about__ import __version__
from anya.inference import InferenceProtocolError, UpstreamAPIError, inference
from anya.logs import configure_logging

# Running as a controller under the executor: keep logs off stdout (the report) and
# keep secrets out of tracebacks. Elsewhere, importing anya leaves logging alone.
if os.environ.get('ANYA_JOB_ID'):
    configure_logging()

__all__ = ['inference', 'InferenceProtocolError', 'UpstreamAPIError', '__version__']

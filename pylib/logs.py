'''
One logging policy for every anya process: the CLI and each controller subprocess.

- Logs go to **stderr**. A controller's stdout is its report, and structlog's default
  logger prints to stdout, so library warnings would otherwise land in the user's email.
- Tracebacks render plainly, **without local variables**. structlog's default (Rich)
  traceback shows locals, which can hold API keys (backend configs, request headers).
- Debug is filtered out unless ANYA_LOG_LEVEL says otherwise (e.g. ANYA_LOG_LEVEL=debug).

Controllers get this automatically: `import anya` calls configure_logging() when it
runs under the executor (ANYA_JOB_ID is set). The CLI calls it at startup.
'''

import logging
import os
import sys

import structlog
from structlog.contextvars import merge_contextvars
from structlog.dev import ConsoleRenderer, plain_traceback, set_exc_info
from structlog.processors import StackInfoRenderer, TimeStamper, add_log_level

LOG_LEVEL_ENV = 'ANYA_LOG_LEVEL'


def configure_logging(level: str | None = None) -> None:
    '''Configure structlog for an anya process (idempotent; safe to call again).'''
    name = (level or os.environ.get(LOG_LEVEL_ENV) or 'info').upper()
    numeric = logging.getLevelNamesMapping().get(name, logging.INFO)
    structlog.configure(
        processors=[
            merge_contextvars,
            add_log_level,
            StackInfoRenderer(),
            set_exc_info,
            TimeStamper(fmt='%Y-%m-%d %H:%M:%S', utc=False),
            # No ANSI colors into pipes (a controller's stderr is captured by the executor).
            ConsoleRenderer(exception_formatter=plain_traceback, colors=sys.stderr.isatty()),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric),
        logger_factory=structlog.PrintLoggerFactory(sys.stderr),
        cache_logger_on_first_use=False,
    )

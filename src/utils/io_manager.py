"""I/O manager: response formatting, log file management, and testcase tracking.

Output contract (Section 3.3 of the spec):
- Every answer is wrapped in  #RESPONSE <id> / #END <id>  tags.
- <id> starts at 1 and increments monotonically within a testcase.
- The testcase-init message is always response 1.
- Every line printed to stdout is also appended to <case_name>.log.
- The contest grader only sends the next request after it sees  #END <id>,
  so stdout must be flushed immediately after each #END.
"""

import sys
import re
import os
from typing import Optional


# ── testcase-name extraction ──────────────────────────────────────────────────
# Handles:
#   "This is the beginning of testcase case28."
#   "This is the beginning of a new testcase. The case name is 'test8'"
#   "This is the beginning of testcase case23. Please output a copy …"
_RE_CASE_INLINE = re.compile(
    r'beginning\s+of\s+(?:a\s+new\s+)?testcase\s+[\'"]?(\w+)[\'"]?',
    re.IGNORECASE,
)
_RE_CASE_NAME = re.compile(
    r'case\s+name\s+is\s+[\'"]?(\w+)[\'"]?',
    re.IGNORECASE,
)


def extract_testcase_name(line: str) -> Optional[str]:
    """Return the testcase name if *line* is a testcase-init message, else None."""
    m = _RE_CASE_INLINE.search(line)
    if m:
        return m.group(1)
    m = _RE_CASE_NAME.search(line)
    if m:
        return m.group(1)
    return None


# ── I/O manager ───────────────────────────────────────────────────────────────

class IOManager:
    """Owns the response-ID counter and the per-testcase log file."""

    def __init__(self) -> None:
        self._response_id: int = 0
        self._log_files: list = []
        self._case_name: Optional[str] = None

    # ------------------------------------------------------------------ public

    def init_testcase(self, case_name: str) -> None:
        """Open the per-testcase log sink(s) and reset the response counter.

        The spec (Section 3.3) only mandates a log file named <case_name>.log;
        it does not fix a directory, so the grader-safe location is the current
        working directory. When the local dev layout testcase/<case>/ exists, a
        copy is kept there as well so the team's tooling keeps working.
        """
        self.close()
        self._case_name = case_name
        self._response_id = 0

        paths = [f"{case_name}.log"]
        case_dir = os.path.join("testcase", case_name)
        if os.path.isdir(case_dir):
            paths.append(os.path.join(case_dir, f"{case_name}.log"))
        self._log_files = [open(p, "w", buffering=1) for p in paths]

    def write_response(self, text: str) -> None:
        """Increment the ID, wrap *text* in tags, write to stdout and the log.

        Flushes stdout immediately so the grader can detect #END <id>.
        """
        self._response_id += 1
        rid = self._response_id
        output = f"#RESPONSE {rid}\n{text}\n#END {rid}\n"

        sys.stdout.write(output)
        sys.stdout.flush()

        for f in self._log_files:
            f.write(output)
            f.flush()

    def close(self) -> None:
        """Flush and close all open log files."""
        for f in self._log_files:
            f.close()
        self._log_files = []

    # ---------------------------------------------------------------- property

    @property
    def case_name(self) -> Optional[str]:
        return self._case_name

    @property
    def response_id(self) -> int:
        return self._response_id

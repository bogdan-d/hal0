"""Shared fixtures for the container-provider test suite.

The privileged seam (D hardened-perms) routes unit writes + systemctl through
``sudo -n hal0-slotctl`` only when ``os.geteuid() != 0``. Every pre-existing
provider test was written for the **root** (direct) path — it mocks
``self._run`` and writes the unit into a tmp dir, assuming euid == 0. CI runs
pytest as a non-root user, so without this fixture those tests would fall into
the seam branch and make a real ``sudo`` call.

Default every test in this package to the root path by patching
``hal0.providers.container.os.geteuid`` to return 0. The dedicated seam test
(``test_container_privileged_seam.py``) patches the *same* target to a non-zero
value inside each ``with`` block, which nests correctly and overrides this
autouse default for the duration of that block.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from hal0.providers import container as container_mod


@pytest.fixture(autouse=True)
def _euid_root_by_default():
    """Run provider tests as if euid == 0 (the unchanged direct path)."""
    with patch.object(container_mod.os, "geteuid", return_value=0):
        yield

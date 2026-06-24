"""Shared fixtures for the memory test suite.

ADR-0023 removed the Cognee engine, so the per-test Cognee-install fixtures
(``_cognee_env`` / ``cognee_dir`` / ``reset_cognee_singletons``) that used to
live here are gone. The surviving memory tests run against the in-memory
:class:`tests.memory.fakes.FakeMemoryProvider`, the :class:`PgVectorProvider`,
or a faked Hindsight client — none of which need process-wide environment
priming, so this module is intentionally empty (kept so ``tests/memory`` stays a
package with a conftest hook point for future fixtures).
"""

from __future__ import annotations

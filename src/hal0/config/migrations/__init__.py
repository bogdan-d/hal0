# hal0.config.migrations — versioned config migration transforms.
#
# Each migration is a function in a module named v<N>_to_v<N+1>.py.
# The hal0 config migrate command walks /etc/hal0/ applying transforms
# in order, then bumps [meta] schema_version.
#
# See PLAN.md §5 Tier 3 ("Config evolution / migration tooling").
# Populated in Phase 5.

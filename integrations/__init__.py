"""Live connections to outside systems.

Every one of these sits behind an interface an agent already depends on, so
connecting an account swaps a provider and changes no agent code. The mocks
stay the default: `make demo` must run on a machine with no accounts at all.
"""

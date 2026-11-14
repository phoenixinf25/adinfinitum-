"""Shared file contracts — the shapes of every file that moves between team members.

Rule: modules never import each other's internals; they exchange the files defined here.
If you need a new field, add it here (with units + provenance) and update tests/test_contracts.py.
"""

from contracts.paths import data_root, repo_root, runs_root
from contracts.provenance import Meta, Provenance

__all__ = ["Meta", "Provenance", "data_root", "repo_root", "runs_root"]

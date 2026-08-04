"""Ontology loading and caching — the read side of the item lists.

Exposes the process-wide `repository` singleton plus the class behind it, so a
test can either reset the shared one or build a throwaway instance.
"""

from .repository import OntologyRepository, repository

__all__ = ['OntologyRepository', 'repository']

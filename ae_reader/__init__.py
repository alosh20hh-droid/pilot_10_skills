"""Isolated, read-only After Effects state observation."""

from .reader import AfterEffectsReadOnlyObserver
from .schema import (
    AECompositionSnapshot,
    AELayerSnapshot,
    AEPositionSnapshot,
    AEPropertyKey,
    AEPropertySnapshot,
    AEReadRequest,
    AEStateSnapshot,
)

__all__ = [
    "AfterEffectsReadOnlyObserver",
    "AECompositionSnapshot",
    "AELayerSnapshot",
    "AEPositionSnapshot",
    "AEPropertyKey",
    "AEPropertySnapshot",
    "AEReadRequest",
    "AEStateSnapshot",
]

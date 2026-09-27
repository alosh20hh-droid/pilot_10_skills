"""Isolated, read-only After Effects observation for the verification pilot."""

from .reader import AfterEffectsReadOnlyObserver
from .schema import (
    AECapabilityManifest,
    AECompositionSnapshot,
    AEEffectPropertySnapshot,
    AEEffectSnapshot,
    AELayerSnapshot,
    AEPositionSnapshot,
    AEProjectSnapshot,
    AEPropertyKey,
    AEPropertySnapshot,
    AEReadRequest,
    AEStateSnapshot,
    READER_VERSION,
    SCHEMA_VERSION,
)

__all__ = [
    "AfterEffectsReadOnlyObserver",
    "AECapabilityManifest",
    "AECompositionSnapshot",
    "AEEffectPropertySnapshot",
    "AEEffectSnapshot",
    "AELayerSnapshot",
    "AEPositionSnapshot",
    "AEProjectSnapshot",
    "AEPropertyKey",
    "AEPropertySnapshot",
    "AEReadRequest",
    "AEStateSnapshot",
    "READER_VERSION",
    "SCHEMA_VERSION",
]

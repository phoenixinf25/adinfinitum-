"""Provenance labels. Every output file and every on-screen number carries one.

observed  — measured by an instrument (e.g. LOLA laser spots, SPICE ephemeris)
modelled  — computed from observed data with physics (e.g. horizon ray-cast, slope)
generated — produced by a generative model (diffusion terrain). Must be shown as
            "GENERATED — NOT OBSERVED" and never used alone for a safety claim.
unknown   — we don't know; say so.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class Provenance(str, Enum):
    OBSERVED = "observed"
    MODELLED = "modelled"
    GENERATED = "generated"
    UNKNOWN = "unknown"

    @property
    def banner(self) -> str:
        """Text the UI must show next to this data."""
        return {
            Provenance.OBSERVED: "OBSERVED",
            Provenance.MODELLED: "MODELLED",
            Provenance.GENERATED: "GENERATED — NOT OBSERVED",
            Provenance.UNKNOWN: "UNKNOWN",
        }[self]


class Meta(BaseModel):
    """Metadata block required in every shared file."""

    model_config = ConfigDict(extra="allow")

    provenance: Provenance
    source: str = Field(description="Where the data came from, e.g. 'PGDA 90 LDEM_80S_20MPP_ADJ'")
    frame: str = Field(default="MOON_ME_DE440_ME421", description="Coordinate frame")
    units: dict[str, str] = Field(default_factory=dict, description="array/field name -> unit")
    created_by: str = Field(default="unknown", description="script or person that wrote the file")
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    schema_version: int = 1

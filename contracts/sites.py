"""Site library contract: sites/sites.json (owner: Tanush, KAN-38)."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from contracts.paths import sites_path
from contracts.provenance import Provenance


class Site(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = Field(pattern=r"^[a-z0-9_]+$")
    name: str
    lat_deg: float = Field(ge=-90, le=90)
    lon_deg: float = Field(ge=-180, le=360)
    source: str
    provenance: Provenance = Provenance.OBSERVED
    notes: str = ""
    region: str | None = Field(default=None, description="tile region name in data/tiles/")


class SiteLibrary(BaseModel):
    schema_version: int = 1
    sites: list[Site]

    def by_id(self, site_id: str) -> Site:
        for s in self.sites:
            if s.id == site_id:
                return s
        raise KeyError(site_id)


def load_sites(path: str | Path | None = None) -> SiteLibrary:
    p = Path(path) if path else sites_path()
    lib = SiteLibrary.model_validate(json.loads(p.read_text(encoding="utf-8")))
    ids = [s.id for s in lib.sites]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate site ids")
    return lib

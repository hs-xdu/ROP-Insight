"""Immutable, JSON-backed report payload; previews cannot alter source results."""

from dataclasses import dataclass
import json


@dataclass(frozen=True)
class ReportDocument:
    payload_json: str

    @property
    def data(self):
        return json.loads(self.payload_json)

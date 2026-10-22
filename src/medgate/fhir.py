"""The FHIR server the benchmark runs against: reads behave exactly as in the reference loop."""

from dataclasses import dataclass
from typing import Any, cast

import httpx

from medgate.protocol import FHIR_BASE


@dataclass(frozen=True)
class GetResult:
    data: Any = None
    error: str | None = None


class FhirClient:
    def __init__(self, base: str = FHIR_BASE, timeout: float = 30.0) -> None:
        self.base = base
        self._http = httpx.Client(timeout=timeout)

    def get(self, url: str) -> GetResult:
        """Same as the reference send_get_request: parsed JSON only if the content type is exactly application/json."""
        try:
            response = self._http.get(url)
            response.raise_for_status()
        except Exception as exc:  # noqa: BLE001 - the reference reports every failure as text to the agent
            return GetResult(error=str(exc))
        if response.headers.get("Content-Type") == "application/json":
            return GetResult(data=response.json())
        return GetResult(data=response.text)

    def is_up(self) -> bool:
        return self.get(f"{self.base}metadata").error is None

    def create(self, resource_type: str, payload: dict[str, Any]) -> str:
        """Write a resource and return its reference, for example "ServiceRequest/42". Raises on a server error.

        Only the review step writes (medgate.review.commit); the agent loops never do, as in the benchmark.
        """
        response = self._http.post(
            f"{self.base}{resource_type}", json=payload, headers={"Content-Type": "application/fhir+json"}
        )
        response.raise_for_status()
        created = cast(dict[str, Any], response.json())
        return f"{created['resourceType']}/{created['id']}"

    def read(self, reference: str) -> dict[str, Any]:
        """One resource as parsed JSON, whatever content type the server labels it with. Raises on a server error."""
        response = self._http.get(f"{self.base}{reference}", params={"_format": "json"})
        response.raise_for_status()
        return cast(dict[str, Any], response.json())

from __future__ import annotations

import logging
import time
from typing import Iterable

import requests

LOGGER = logging.getLogger(__name__)


class ArcGISError(RuntimeError):
    pass


def _session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "udot-safecorridor-intelligence/0.1 (independent portfolio POC)",
            "Accept": "application/json",
        }
    )
    return session


def get_json(
    url: str,
    params: dict | None = None,
    *,
    attempts: int = 4,
    timeout: int = 60,
) -> dict:
    """GET JSON with small retry/backoff and ArcGIS error detection."""
    last_error: Exception | None = None
    with _session() as session:
        for attempt in range(1, attempts + 1):
            try:
                response = session.get(url, params=params, timeout=timeout)
                response.raise_for_status()
                payload = response.json()
                if isinstance(payload, dict) and payload.get("error"):
                    raise ArcGISError(str(payload["error"]))
                return payload
            except (requests.RequestException, ValueError, ArcGISError) as exc:
                last_error = exc
                if attempt == attempts:
                    break
                delay = min(2 ** (attempt - 1), 8)
                LOGGER.warning("ArcGIS request failed (%s). Retrying in %ss", exc, delay)
                time.sleep(delay)
    raise ArcGISError(f"Request failed after {attempts} attempts: {url}: {last_error}")


def layer_metadata(layer_url: str) -> dict:
    return get_json(layer_url, {"f": "json"})


def service_metadata(service_url: str) -> dict:
    return get_json(service_url, {"f": "json"})


def query_all_features(
    layer_url: str,
    *,
    out_fields: Iterable[str] | str = "*",
    where: str = "1=1",
    return_geometry: bool = False,
    out_sr: int | None = None,
    page_size: int = 2000,
) -> list[dict]:
    """Page through an ArcGIS Feature/MapServer layer.

    Returns ArcGIS feature objects containing `attributes` and optional `geometry`.
    """
    if not isinstance(out_fields, str):
        out_fields = ",".join(out_fields)

    features: list[dict] = []
    offset = 0

    while True:
        params = {
            "f": "json",
            "where": where,
            "outFields": out_fields,
            "returnGeometry": "true" if return_geometry else "false",
            "resultOffset": offset,
            "resultRecordCount": page_size,
            "orderByFields": "OBJECTID ASC",
        }
        if out_sr is not None:
            params["outSR"] = str(out_sr)

        payload = get_json(f"{layer_url}/query", params)
        page = payload.get("features", [])
        features.extend(page)

        LOGGER.info("Fetched %s rows from %s (total=%s)", len(page), layer_url, len(features))

        exceeded = bool(payload.get("exceededTransferLimit"))
        if not page or (len(page) < page_size and not exceeded):
            break

        offset += len(page)
        if len(page) == 0:
            break

    return features

"""Sparkplug API client for Atomic Fungi."""

import json
import os
import requests
from pathlib import Path
from typing import Optional

BASE_URL = "https://api-server-production.sparkplug-technology.io/api/v1"
VENDOR_GROUP_ID = "691270b4e489475b3f933902"


class SparkplugClient:
    """HTTP client for the Sparkplug internal API."""

    def __init__(self, config_path: Optional[Path] = None):
        self.config_path = config_path or (Path.home() / ".sparkplug" / "sparkplug.json")
        self._token: Optional[str] = None
        self._group_id: str = VENDOR_GROUP_ID

    def load_config(self) -> dict:
        """Load token and config from file or env."""
        if self.config_path.exists():
            with open(self.config_path) as f:
                return json.load(f)
        return {}

    def save_config(self, config: dict):
        """Persist config to disk."""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, "w") as f:
            json.dump(config, f, indent=2)

    @property
    def token(self) -> str:
        if self._token:
            return self._token
        config = self.load_config()
        token = config.get("jwt_token") or os.environ.get("SPARKPLUG_JWT_TOKEN", "")
        if not token:
            raise RuntimeError(
                "No Sparkplug JWT token found. "
                "Run the /sparkplug-setup command or set SPARKPLUG_JWT_TOKEN env var."
            )
        self._token = token
        return token

    @property
    def group_id(self) -> str:
        config = self.load_config()
        return config.get("group_id") or os.environ.get("SPARKPLUG_GROUP_ID", VENDOR_GROUP_ID)

    @property
    def headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    def _get(self, path: str, params: dict = None) -> dict:
        resp = requests.get(f"{BASE_URL}{path}", headers=self.headers, params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, body: dict) -> dict:
        resp = requests.post(f"{BASE_URL}{path}", headers=self.headers, json=body, timeout=30)
        resp.raise_for_status()
        return resp.json()

    # ─── Core API methods ─────────────────────────────────────────────────────

    def get_retailers(self) -> list[dict]:
        """Return all retailer partners for Atomic Fungi."""
        data = self._get(f"/groups/{self.group_id}/account-links/", params={"filterMarkets": "true"})
        if isinstance(data, list):
            return data
        return data.get("data", [])

    def get_retailer_detail(self, retailer_id: str) -> dict:
        """Return full detail for a single retailer."""
        return self._get(f"/accounts/{self.group_id}/vendor-retailers/{retailer_id}")

    def _chart_body(self, retailer_ids: list[str], date_start: str, date_end: str, frequency: str) -> dict:
        return {
            "dateStart": date_start,
            "dateEnd": date_end,
            "frequency": frequency,
            "retailerAccountIds": retailer_ids,
        }

    def get_sales_totals(self, retailer_id: str, date_start: str, date_end: str, frequency: str = "monthly") -> dict:
        """Total units sold at a retailer over the date range."""
        body = self._chart_body([retailer_id], date_start, date_end, frequency)
        return self._post(f"/sparkplug/chart/vendor/{self.group_id}/total_units/total/totals", body)

    def get_sales_buckets(self, retailer_id: str, date_start: str, date_end: str, frequency: str = "monthly") -> dict:
        """Time-series sales buckets (for trend charts)."""
        body = self._chart_body([retailer_id], date_start, date_end, frequency)
        return self._post(f"/sparkplug/chart/vendor/{self.group_id}/total_units/total/buckets", body)

    def get_budtender_performance(self, retailer_id: str, date_start: str, date_end: str, frequency: str = "monthly") -> dict:
        """Per-employee unit totals. Returns {employee_id: units} mapping."""
        body = self._chart_body([retailer_id], date_start, date_end, frequency)
        return self._post(f"/sparkplug/chart/vendor/{self.group_id}/total_units/employee/totals", body)

    def get_products_with_sales(self, retailer_id: str, date_start: str, date_end: str) -> list[str]:
        """Product IDs that have recorded sales in the period."""
        body = self._chart_body([retailer_id], date_start, date_end, "monthly")
        result = self._post(f"/sparkplug/chart/vendor/{self.group_id}/products_with_sales", body)
        return result.get("productsWithSales", [])

    def get_pos_locations(self, retailer_id: str) -> list[dict]:
        """POS locations for a retailer."""
        return self._get(f"/pos/locations", params={"group_id": retailer_id})

    def get_snaps_list(self) -> list[dict]:
        """
        Return all Snaps for this vendor.
        Each snap includes _id, name, storifymeSnapId (numeric), thumbnailUrl, totalPages, markets, etc.
        The storifymeSnapId is what the engagement-csv endpoint requires.
        """
        data = self._get(f"/accounts/{self.group_id}/snaps")
        if isinstance(data, list):
            return data
        return data.get("snaps", data.get("data", []))

    def get_snap_engagement(self, storiyme_snap_id: str) -> list[dict]:
        """
        Fetch per-employee engagement rows for a single Snap.
        Returns a list of dicts with: Employee, Retailer, Location, Action,
        Total Slides, Slide, Component Id, and a raw 'data' JSON string.

        storiyme_snap_id: numeric ID (storifymeSnapId field from get_snaps_list).
        Endpoint: GET /accounts/{groupId}/{snapId}/engagement-csv
        """
        raw = self._get(f"/accounts/{self.group_id}/{storiyme_snap_id}/engagement-csv")
        if isinstance(raw, list):
            return raw
        # Some responses wrap in a key
        return raw.get("data", raw.get("rows", [raw]))

    def get_config(self) -> dict:
        """Sparkplug app config for this vendor."""
        return self._get(f"/sparkplug/config", params={"group_id": self.group_id})

"""Sparkplug API client for Atomic Fungi."""

import json
import os
import stat
import requests
from pathlib import Path
from typing import Optional
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE_URL = "https://api-server-production.sparkplug-technology.io/api/v1"
VENDOR_GROUP_ID = "691270b4e489475b3f933902"


class SparkplugClient:
    """HTTP client for the Sparkplug internal API."""

    def __init__(self, config_path: Optional[Path] = None):
        self.config_path = config_path or (Path.home() / ".sparkplug" / "sparkplug.json")
        self._token: Optional[str] = None
        self._group_id: Optional[str] = None
        self._session: Optional[requests.Session] = None

    def _get_session(self) -> requests.Session:
        if self._session is None:
            self._session = requests.Session()
            retry = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
            adapter = HTTPAdapter(max_retries=retry)
            self._session.mount("https://", adapter)
            self._session.mount("http://", adapter)
        return self._session

    def load_config(self) -> dict:
        """Load token and config from file or env."""
        if self.config_path.exists():
            with open(self.config_path) as f:
                return json.load(f)
        return {}

    def save_config(self, config: dict):
        """Persist config to disk with restricted permissions."""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, "w") as f:
            json.dump(config, f, indent=2)
        try:
            os.chmod(self.config_path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass  # Windows may not support Unix-style permissions

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
        if self._group_id:
            return self._group_id
        config = self.load_config()
        self._group_id = config.get("group_id") or os.environ.get("SPARKPLUG_GROUP_ID", VENDOR_GROUP_ID)
        return self._group_id

    @property
    def headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    def _handle_response(self, resp: requests.Response) -> dict:
        if resp.status_code == 401:
            self._token = None  # Clear cached token
            raise RuntimeError(
                "Sparkplug API returned 401 Unauthorized — JWT token may be expired. "
                "Re-extract from browser: DevTools → Application → Local Storage → my.sparkplug.app → token, "
                "then save to ~/.sparkplug/sparkplug.json"
            )
        resp.raise_for_status()
        return resp.json()

    def _get(self, path: str, params: dict = None) -> dict:
        session = self._get_session()
        resp = session.get(f"{BASE_URL}{path}", headers=self.headers, params=params, timeout=30)
        return self._handle_response(resp)

    def _post(self, path: str, body: dict) -> dict:
        session = self._get_session()
        resp = session.post(f"{BASE_URL}{path}", headers=self.headers, json=body, timeout=30)
        return self._handle_response(resp)

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

    def get_snap_engagement(self, storifyme_snap_id: str) -> list[dict]:
        """
        Fetch per-employee engagement rows for a single Snap.
        Returns a list of dicts with: Employee, Retailer, Location, Action,
        Total Slides, Slide, Component Id, and a raw 'data' JSON string.

        storifyme_snap_id: numeric ID (storifymeSnapId field from get_snaps_list).
        Endpoint: GET /accounts/{groupId}/{snapId}/engagement-csv
        """
        raw = self._get(f"/accounts/{self.group_id}/{storifyme_snap_id}/engagement-csv")
        if isinstance(raw, list):
            return raw
        return raw.get("data", raw.get("rows", [raw]))

    def get_config(self) -> dict:
        """Sparkplug app config for this vendor."""
        return self._get(f"/sparkplug/config", params={"group_id": self.group_id})

    def get_learning_resources(self) -> list[dict]:
        """Return all training courses for this vendor."""
        data = self._get("/learning-resource", params={
            "limit": 100, "offset": 0, "order": "desc",
            "sort": "createdAt", "accountId": self.group_id,
        })
        if isinstance(data, dict):
            return data.get("data", [])
        return data

    def get_course_responses(self, learning_resource_id: str) -> list[dict]:
        """Return all employee responses/completions for a training course."""
        data = self._get(f"/learning-resource/{learning_resource_id}/response")
        if isinstance(data, dict):
            return data.get("data", [])
        return data

    def get_course_response_count(self, learning_resource_id: str) -> int:
        """Return count of responses for a training course."""
        data = self._get(f"/learning-resource/{learning_resource_id}/response/count")
        return data.get("count", 0)

    def get_all_cta_responses(self) -> list[dict]:
        """Pull all CTA/question responses across all Snaps. Returns list of response dicts, newest first."""
        snaps = self.get_snaps_list()
        responses = []
        for s in snaps:
            sid = s.get("storifymeSnapId", "")
            if not sid:
                continue
            snap_date = s.get("updatedAt", s.get("createdAt", ""))
            try:
                rows = self.get_snap_engagement(str(sid))
                for r in rows:
                    if r.get("Response"):
                        responses.append({
                            "snap_name": s.get("name", ""),
                            "snap_id": sid,
                            "employee": r.get("Employee", ""),
                            "retailer": r.get("Retailer", ""),
                            "action": r.get("Action", ""),
                            "slide": r.get("Slide", ""),
                            "response": r.get("Response", ""),
                            "date": snap_date[:10] if snap_date else "",
                        })
            except Exception:
                pass
        # Sort newest first
        responses.sort(key=lambda x: x.get("date", ""), reverse=True)
        return responses

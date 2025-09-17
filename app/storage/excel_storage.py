from __future__ import annotations
import os
import datetime as dt
from typing import Optional, List, Dict, Any

import pandas as pd
from openpyxl.utils import get_column_letter
import re
from difflib import SequenceMatcher

from ..schemas import JobApplicationCreate
from ..domain import Status

COLUMNS = [
    "id",
    "title",
    "employer",
    "status",
    "date_applied",
    "source_url",
]


def _empty_df() -> pd.DataFrame:
    return pd.DataFrame(columns=COLUMNS)


def ensure_file(path: str) -> None:
    if not os.path.exists(path):
        df = _empty_df()
        _write_df(df, path)


def _read_df(path: str) -> pd.DataFrame:
    if not os.path.exists(path):
        return _empty_df()
    try:
        # Prefer our named sheet if present
        try:
            df = pd.read_excel(path, sheet_name="Applications")
        except Exception:
            df = pd.read_excel(path)
    except Exception:
        # if file is corrupt or unreadable, start new (could log and raise instead)
        df = _empty_df()
    # Make sure all expected columns exist
    for col in COLUMNS:
        if col not in df.columns:
            df[col] = pd.NA
    # Order columns
    df = df[COLUMNS]
    return df


def _write_df(df: pd.DataFrame, path: str) -> None:
    df = _normalize_for_excel(df)
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Applications")
        ws = writer.sheets["Applications"]
        _set_column_widths(ws, df)


def _now() -> dt.datetime:
    # Return a timezone-naive UTC datetime to satisfy Excel/openpyxl
    return dt.datetime.utcnow()


def _normalize_for_excel(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure datetime columns are timezone-naive and date columns are plain dates.

    Excel (openpyxl) cannot handle timezone-aware datetimes.
    """
    df = df.copy()
    # Normalize date columns to python date objects
    for col in ("date_applied",):
        if col in df.columns:
            ser = pd.to_datetime(df[col], errors="coerce")
            try:
                ser = ser.dt.tz_localize(None)
            except Exception:
                pass
            df[col] = ser.dt.date
    return df


def _next_id(df: pd.DataFrame) -> int:
    if df.empty or "id" not in df or df["id"].isna().all():
        return 1
    try:
        return int(pd.to_numeric(df["id"], errors="coerce").max()) + 1
    except Exception:
        return 1


def create_or_update(path: str, data: JobApplicationCreate) -> Dict[str, Any]:
    ensure_file(path)
    df = _read_df(path)

    # Locate existing by source_url
    mask = df["source_url"].astype(str) == data.source_url
    now = _now()

    if mask.any():
        idx = df.index[mask][0]
        df.at[idx, "title"] = data.title
        df.at[idx, "employer"] = data.employer
        df.at[idx, "status"] = data.status.value
        df.at[idx, "date_applied"] = data.date_applied
        _write_df(df, path)
        return df.loc[idx].to_dict()

    new_id = _next_id(df)
    row = {
        "id": new_id,
        "title": data.title,
        "employer": data.employer,
        "status": data.status.value,
        "date_applied": data.date_applied,
        "source_url": data.source_url,
    }
    # Avoid concat warning; append using loc ensures stable dtypes
    df.loc[len(df)] = row
    _write_df(df, path)
    return row


def list_applications(path: str, status: Optional[Status] = None) -> List[Dict[str, Any]]:
    ensure_file(path)
    df = _read_df(path)
    if status is not None:
        df = df[df["status"].astype(str) == status.value]
    # Sort by id desc
    df = df.sort_values(by=["id"], ascending=False)
    return df.to_dict(orient="records")


def update_status(path: str, selector: str | int, new_status: Status) -> Optional[Dict[str, Any]]:
    ensure_file(path)
    df = _read_df(path)

    if isinstance(selector, int) or (isinstance(selector, str) and selector.isdigit()):
        sel_id = int(selector)
        mask = pd.to_numeric(df["id"], errors="coerce") == sel_id
    else:
        mask = df["source_url"].astype(str) == str(selector)

    if not mask.any():
        return None

    idx = df.index[mask][0]
    df.at[idx, "status"] = new_status.value
    _write_df(df, path)
    return df.loc[idx].to_dict()


def remove_by_id(path: str, item_id: int) -> Optional[Dict[str, Any]]:
    ensure_file(path)
    df = _read_df(path)
    mask = pd.to_numeric(df["id"], errors="coerce") == int(item_id)
    if not mask.any():
        return None
    idx = df.index[mask][0]
    row = df.loc[idx].to_dict()
    df = df.drop(index=idx).reset_index(drop=True)
    _write_df(df, path)
    return row


def export_to_excel(path: str, out_path: str) -> None:
    ensure_file(path)
    df = _read_df(path)
    df = _normalize_for_excel(df)
    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Applications")
        ws = writer.sheets["Applications"]
        _set_column_widths(ws, df)


def export_to_csv(path: str, out_path: str) -> None:
    ensure_file(path)
    df = _read_df(path)
    df.to_csv(out_path, index=False)


def _set_column_widths(ws, df: pd.DataFrame) -> None:
    widths = {
        "id": 6,
        "title": 40,
        "employer": 40,
        "status": 13,
        "date_applied": 20,
        "source_url": 30,
    }
    for idx, col_name in enumerate(df.columns, start=1):
        letter = get_column_letter(idx)
        ws.column_dimensions[letter].width = widths.get(col_name, 20)


def search(
    path: str,
    item_id: Optional[int] = None,
    title: Optional[str] = None,
    employer: Optional[str] = None,
    limit: Optional[int] = 20,
) -> List[Dict[str, Any]]:
    """Search applications by id, title regex, and/or employer regex.

    - Matching is case-insensitive.
    - Title/employer use regex substring matching; invalid regex fall back to literal.
    - Results are sorted by closeness score (difflib ratio) then by id desc.
    """
    ensure_file(path)
    df = _read_df(path)
    if df.empty:
        return []

    mask = pd.Series(True, index=df.index)

    # ID filter
    if item_id is not None:
        mask &= pd.to_numeric(df["id"], errors="coerce") == int(item_id)

    def _compile(pat: str) -> str:
        try:
            re.compile(pat)
            return pat
        except re.error:
            return re.escape(pat)

    # Title filter
    if title:
        pat = _compile(title)
        mask &= df["title"].fillna("").str.contains(pat, case=False, regex=True)

    # Employer filter
    if employer:
        pat = _compile(employer)
        mask &= df["employer"].fillna("").str.contains(pat, case=False, regex=True)

    results = df[mask].copy()
    if results.empty:
        return []

    def _ci(val: Any) -> str:
        return "" if pd.isna(val) else str(val).lower()

    def _similarity(a: Optional[str], b: str) -> float:
        if not a:
            return 0.0
        return SequenceMatcher(None, a.lower(), b).ratio()

    # Score rows based on similarity to queries
    scores: List[float] = []
    def _row_score(row: pd.Series) -> float:
        s = 0.0
        if title:
            s = max(s, _similarity(title, _ci(row.get("title"))))
        if employer:
            s = max(s, _similarity(employer, _ci(row.get("employer"))))
        if item_id is not None:
            # Boost exact id matches
            rid = row.get("id")
            try:
                if int(rid) == int(item_id):
                    s = max(s, 1.0)
            except Exception:
                pass
        # If no text criteria provided, keep stable ordering
        return s

    results["_score"] = results.apply(_row_score, axis=1)
    results = results.sort_values(by=["_score", "id"], ascending=[False, False])
    if limit is not None and limit > 0:
        results = results.head(limit)
    results = results.drop(columns=["_score"])
    return results.to_dict(orient="records")

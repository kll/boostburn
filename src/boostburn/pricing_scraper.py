from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Dict, Iterable, Optional
import unicodedata

import requests
import yaml
from bs4 import BeautifulSoup

from .adapters.pricing import canonical_model_key

PRICING_URL = "https://aws.amazon.com/bedrock/pricing/"

_REGION_NAME_TO_CODE = {
    "us east (n. virginia)": "us-east-1",
    "us east (ohio)": "us-east-2",
    "us west (oregon)": "us-west-2",
    "us west (n. california)": "us-west-1",
    "canada (central)": "ca-central-1",
    "eu (ireland)": "eu-west-1",
    "eu (london)": "eu-west-2",
    "eu (paris)": "eu-west-3",
    "eu (frankfurt)": "eu-central-1",
    "eu (zurich)": "eu-central-2",
    "eu (stockholm)": "eu-north-1",
    "eu (milan)": "eu-south-1",
    "europe (spain)": "eu-south-2",
    "asia pacific (tokyo)": "ap-northeast-1",
    "asia pacific (seoul)": "ap-northeast-2",
    "asia pacific (osaka)": "ap-northeast-3",
    "asia pacific (mumbai)": "ap-south-1",
    "asia pacific (hyderabad)": "ap-south-2",
    "asia pacific (singapore)": "ap-southeast-1",
    "asia pacific (sydney)": "ap-southeast-2",
    "asia pacific (jakarta)": "ap-southeast-3",
    "asia pacific (melbourne)": "ap-southeast-4",
    "asia pacific (malaysia)": "ap-southeast-5",
    "asia pacific (thailand)": "ap-southeast-7",
    "south america (sao paulo)": "sa-east-1",
    "middle east (uae)": "me-central-1",
    "middle east (bahrain)": "me-south-1",
    "israel (tel aviv)": "il-central-1",
    "africa (cape town)": "af-south-1",
}


@dataclass
class ScrapeStats:
    rows_parsed: int = 0
    models_parsed: int = 0
    tables_used: int = 0
    inline_rows_parsed: int = 0


def fetch_pricing_html(url: str = PRICING_URL, timeout: int = 20) -> str:
    response = requests.get(url, timeout=timeout, headers={"User-Agent": "boostburn-pricing-scraper/1.0"})
    response.raise_for_status()
    return response.text


def parse_pricing_html(html: str, *, region_override: Optional[str] = None) -> tuple[dict, ScrapeStats]:
    soup = BeautifulSoup(html, "html.parser")
    rates: Dict[str, Dict[str, dict]] = {}
    stats = ScrapeStats()

    for table in soup.find_all("table"):
        headers, header_rows = _extract_headers(table)
        if not headers:
            continue
        model_idx = _find_model_header(headers)
        input_idx, output_idx = _find_price_headers(headers)
        if model_idx is None or input_idx is None:
            continue
        region_idx = _find_header(headers, ["region"]) or _find_header(headers, ["location"])
        stats.tables_used += 1

        for row in table.find_all("tr"):
            if row in header_rows:
                continue
            cells = _expand_row_cells(row, len(headers))
            if len(cells) < len(headers):
                continue
            model = _clean_model_name(cells[model_idx])
            if not model or model.lower() == "model":
                continue
            input_price = _parse_price(_clean_text(cells[input_idx]))
            output_price = None
            if output_idx is not None:
                output_price = _parse_price(_clean_text(cells[output_idx]))

            if input_price is None and output_price is None:
                continue

            region_code = region_override
            if region_code is None and region_idx is not None:
                region_text = _clean_text(cells[region_idx])
                region_code = _REGION_NAME_TO_CODE.get(_normalize_region_name(region_text))
            if region_code is None:
                region_code = "default"

            model_key = canonical_model_key(model)
            if not model_key:
                continue

            entry = _build_rate_entry(input_price, output_price)
            stats.rows_parsed += 1

            _upsert_rate(rates, model_key, region_code, entry)

    inline_rates, inline_rows = _parse_inline_pricing(soup, region_override=region_override)
    stats.inline_rows_parsed = inline_rows
    stats.rows_parsed += inline_rows
    for model_key, region_map in inline_rates.items():
        for region_code, entry in region_map.items():
            _upsert_rate(rates, model_key, region_code, entry)

    stats.models_parsed = len(rates)
    return rates, stats


def build_pricing_payload(rates: dict, source: str = PRICING_URL) -> dict:
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "rates": rates,
    }


def write_pricing_yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=True))


def _extract_headers(table) -> tuple[list[str], list]:
    header_rows = _collect_header_rows(table)
    if header_rows:
        return _collapse_header_rows(header_rows), header_rows
    header_row = table.find("tr")
    if header_row is None:
        return [], []
    headers = []
    for cell in header_row.find_all(["th", "td"]):
        headers.append(_clean_text(cell.get_text()).lower())
    return headers, []


def _find_header(headers: list[str], tokens: list[str]) -> Optional[int]:
    for idx, header in enumerate(headers):
        if all(token in header for token in tokens):
            return idx
    return None


def _find_model_header(headers: list[str]) -> Optional[int]:
    candidates: list[tuple[int, int]] = []
    for idx, header in enumerate(headers):
        if "model" not in header:
            continue
        score = 0
        if header.strip() == "model":
            score += 2
        if "provider" in header:
            score -= 2
        if "name" in header:
            score += 1
        candidates.append((score, idx))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]


def _find_price_headers(headers: list[str]) -> tuple[Optional[int], Optional[int]]:
    input_candidates = [idx for idx, header in enumerate(headers) if "input" in header and "token" in header]
    output_candidates = [idx for idx, header in enumerate(headers) if "output" in header and "token" in header]
    if not input_candidates:
        return None, None
    if not output_candidates:
        return _best_header_by_score(headers, input_candidates), None
    best_pair = _best_price_pair(headers, input_candidates, output_candidates)
    return best_pair


def _parse_price(text: str) -> Optional[float]:
    if not text:
        return None
    cleaned = text.replace(",", "")
    match = re.search(r"(\d+\.?\d*)", cleaned)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def _clean_text(text: str) -> str:
    return " ".join(text.split())


def _clean_model_name(text: str) -> str:
    if not text:
        return ""
    value = text
    if "|" in value:
        value = value.split("|")[-1]
    value = re.sub(r"\([^)]*\)", "", value)
    value = re.sub(r"\bpublic extended access\b.*$", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\beffective\b.*$", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\s+-\s+.*$", "", value)
    return _clean_text(value)


def _normalize_region_name(value: str) -> str:
    lowered = value.lower()
    normalized = unicodedata.normalize("NFKD", lowered)
    return "".join(char for char in normalized if not unicodedata.combining(char))


def _collect_header_rows(table) -> list:
    thead = table.find("thead")
    if thead:
        rows = thead.find_all("tr")
        if rows:
            return rows
    rows: list = []
    for row in table.find_all("tr"):
        cells = row.find_all(["th", "td"])
        if not cells:
            continue
        has_header = any(
            cell.name == "th"
            or cell.get("role") == "columnheader"
            or cell.get("scope") == "col"
            for cell in cells
        )
        if not has_header:
            break
        rows.append(row)
    return rows


def _collapse_header_rows(rows: Iterable) -> list[str]:
    col_texts: list[list[str]] = []
    span_map: dict[int, int] = {}
    for row in rows:
        col_idx = 0
        for cell in row.find_all(["th", "td"]):
            while span_map.get(col_idx, 0) > 0:
                span_map[col_idx] -= 1
                col_idx += 1
            colspan = int(cell.get("colspan", 1) or 1)
            rowspan = int(cell.get("rowspan", 1) or 1)
            text = _clean_text(cell.get_text()).lower()
            for _ in range(colspan):
                if col_idx >= len(col_texts):
                    col_texts.append([])
                if text:
                    col_texts[col_idx].append(text)
                if rowspan > 1:
                    span_map[col_idx] = max(span_map.get(col_idx, 0), rowspan - 1)
                col_idx += 1
    headers: list[str] = []
    for texts in col_texts:
        if not texts:
            headers.append("")
            continue
        seen: set[str] = set()
        parts: list[str] = []
        for text in texts:
            if text in seen:
                continue
            seen.add(text)
            parts.append(text)
        headers.append(" ".join(parts).strip())
    return headers


def _expand_row_cells(row, target_cols: int) -> list[str]:
    values: list[str] = []
    for cell in row.find_all(["td", "th"]):
        colspan = int(cell.get("colspan", 1) or 1)
        text = _clean_text(cell.get_text())
        for _ in range(colspan):
            values.append(text)
    if target_cols and len(values) < target_cols:
        values.extend([""] * (target_cols - len(values)))
    return values


def _best_header_by_score(headers: list[str], candidates: list[int]) -> Optional[int]:
    if not candidates:
        return None
    best_idx = candidates[0]
    best_score = _header_score(headers[best_idx])
    for idx in candidates[1:]:
        score = _header_score(headers[idx])
        if score > best_score:
            best_score = score
            best_idx = idx
    return best_idx


def _best_price_pair(
    headers: list[str], input_candidates: list[int], output_candidates: list[int]
) -> tuple[Optional[int], Optional[int]]:
    best_pair: tuple[Optional[int], Optional[int]] = (None, None)
    best_score: Optional[int] = None
    for input_idx in input_candidates:
        for output_idx in output_candidates:
            score = _header_score(headers[input_idx]) + _header_score(headers[output_idx])
            score += _header_group_overlap(headers[input_idx], headers[output_idx])
            if best_score is None or score > best_score:
                best_score = score
                best_pair = (input_idx, output_idx)
    return best_pair


def _header_score(header: str) -> int:
    score = 0
    lowered = header.lower()
    if "on-demand" in lowered or "on demand" in lowered or "ondemand" in lowered:
        score += 3
    if "batch" in lowered:
        score -= 2
    if "cached" in lowered or "cache" in lowered:
        score -= 2
    if "latency" in lowered or "optimized" in lowered:
        score -= 2
    if "provisioned" in lowered or "throughput" in lowered or "hour" in lowered:
        score -= 3
    return score


def _header_group_overlap(input_header: str, output_header: str) -> int:
    input_tokens = _header_group_tokens(input_header)
    output_tokens = _header_group_tokens(output_header)
    return len(input_tokens & output_tokens)


def _header_group_tokens(header: str) -> set[str]:
    tokens = re.findall(r"[a-z0-9]+", header.lower())
    ignore = {"price", "per", "1", "000", "input", "output", "token", "tokens"}
    return {token for token in tokens if token not in ignore}


def _parse_inline_pricing(soup: BeautifulSoup, *, region_override: Optional[str]) -> tuple[dict, int]:
    lines = [line.strip() for line in soup.get_text("\n").splitlines() if line.strip()]
    rates: Dict[str, Dict[str, dict]] = {}
    rows_parsed = 0
    for idx, line in enumerate(lines):
        if "$" not in line or "input" not in line.lower():
            continue
        prefix_parts: list[str] = []
        for prev_idx in range(max(0, idx - 4), idx):
            prev_line = lines[prev_idx]
            lowered = prev_line.lower()
            if "input" in lowered or "output" in lowered:
                continue
            prefix_parts.append(prev_line)
        prefix_text = " ".join(prefix_parts).strip()
        combined = f"{prefix_text} {line}".strip() if prefix_text else line
        if idx + 1 < len(lines) and "output" in lines[idx + 1].lower():
            combined = f"{combined} {lines[idx + 1]}"
        input_price = _parse_labeled_price(combined, "input")
        output_price = _parse_labeled_price(combined, "output")
        if input_price is None and output_price is None:
            continue
        target_text = prefix_text or combined
        model_text, region_codes = _split_model_and_regions(target_text)
        model_text = _clean_model_name(model_text)
        if not model_text:
            continue
        model_key = canonical_model_key(model_text)
        if not model_key:
            continue
        if region_override:
            region_codes = [region_override]
        if not region_codes:
            region_codes = ["default"]
        entry = _build_rate_entry(input_price, output_price)
        for region_code in region_codes:
            _upsert_rate(rates, model_key, region_code, entry)
        rows_parsed += 1
    return rates, rows_parsed


def _parse_labeled_price(text: str, label: str) -> Optional[float]:
    escaped_label = re.escape(label)
    pattern = rf"{escaped_label}[^$]*\$?([0-9.,]+)"
    match = re.search(pattern, text, re.IGNORECASE)
    if not match:
        return None
    return _parse_price(match.group(1))


def _split_model_and_regions(text: str) -> tuple[str, list[str]]:
    if not text:
        return "", []
    normalized = _normalize_region_name(text)
    first_idx: Optional[int] = None
    for region_name in _REGION_NAME_TO_CODE:
        idx = normalized.find(region_name)
        if idx == -1:
            continue
        if first_idx is None or idx < first_idx:
            first_idx = idx
    if first_idx is None:
        return text.strip(), []
    model_text = text[:first_idx].strip(" ,;|-")
    region_text = text[first_idx:]
    region_codes = _extract_region_codes(region_text)
    return model_text, region_codes


def _extract_region_codes(text: str) -> list[str]:
    normalized = _normalize_region_name(text)
    matches: list[tuple[int, str]] = []
    for region_name, region_code in _REGION_NAME_TO_CODE.items():
        idx = normalized.find(region_name)
        if idx == -1:
            continue
        matches.append((idx, region_code))
    matches.sort(key=lambda item: item[0])
    region_codes: list[str] = []
    for _, code in matches:
        if code not in region_codes:
            region_codes.append(code)
    return region_codes


def _build_rate_entry(input_price: Optional[float], output_price: Optional[float]) -> dict:
    missing_input = input_price is None
    missing_output = output_price is None
    entry = {
        "input_per_1k": float(input_price or 0.0),
        "output_per_1k": float(output_price or 0.0),
        "currency": "USD",
    }
    if missing_input:
        entry["missing_input"] = True
    if missing_output:
        entry["missing_output"] = True
    return entry


def _is_better_rate(candidate: dict, existing: dict) -> bool:
    if existing.get("missing_output") and not candidate.get("missing_output"):
        return True
    if existing.get("missing_input") and not candidate.get("missing_input"):
        return True
    return False


def _upsert_rate(rates: Dict[str, Dict[str, dict]], model_key: str, region_code: str, entry: dict) -> None:
    existing = rates.setdefault(model_key, {}).get(region_code)
    if existing is None or _is_better_rate(entry, existing):
        rates.setdefault(model_key, {})[region_code] = entry

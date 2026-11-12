"""CSV reading/writing helpers shared by the upload step, executor and verifier.

Uploaded files are normalised once (UTF-8, comma-separated, rectangular rows)
and saved as input.csv. Everything downstream reads that normalised file.
"""
from __future__ import annotations

import csv
import hashlib
import io
from typing import List, Tuple

Rows = List[List[str]]


class CSVFormatError(ValueError):
    pass


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def decode_upload(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise CSVFormatError("Could not read the file's text encoding.")


def _clean_headers(headers: List[str]) -> List[str]:
    seen: dict = {}
    out = []
    for i, h in enumerate(headers):
        name = (h or "").strip() or f"Column {i + 1}"
        if name in seen:
            seen[name] += 1
            name = f"{name} ({seen[name]})"
        else:
            seen[name] = 1
        out.append(name)
    return out


def parse_csv_text(text: str, max_rows: int) -> Tuple[List[str], Rows]:
    """Parse arbitrary supplier CSV text into (headers, rows)."""
    sample = text[:20000]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ","
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    all_rows = [r for r in reader]
    # drop fully empty lines
    all_rows = [r for r in all_rows if any((c or "").strip() for c in r)]
    if not all_rows:
        raise CSVFormatError("The file is empty.")
    headers = _clean_headers(all_rows[0])
    if len(headers) < 2:
        raise CSVFormatError("Need at least two columns. Is this a CSV file?")
    body = all_rows[1:]
    if not body:
        raise CSVFormatError("The file has a header row but no data rows.")
    if len(body) > max_rows:
        raise CSVFormatError(f"Too many rows ({len(body)}). The limit is {max_rows}.")
    width = len(headers)
    rows = [(r + [""] * width)[:width] for r in body]
    return headers, rows


def write_csv(path: str, headers: List[str], rows: Rows) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(headers)
        w.writerows(rows)


def read_csv(path: str) -> Tuple[List[str], Rows]:
    """Read a normalised (UTF-8, comma) CSV written by write_csv."""
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        data = [r for r in reader]
    if not data:
        return [], []
    return data[0], data[1:]

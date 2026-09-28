"""model/datasets/_common.py -- shared numeric and I/O helpers for the real-dataset
loaders (nasa_pcoe.py, calce.py). Kept dependency-free beyond numpy/pandas/scipy so
it never needs installing anything (CONTRACTS.md SS3).

Sign convention used throughout this package (loaders convert their source's raw
sign into this convention at parse time, documented per-loader):
    I > 0  -> charge current
    I < 0  -> discharge current
This matches CONTRACTS.md SS1's "+charge, -discharge" convention for the 1 Hz
sample stream, so the same helpers can eventually feed either path.
"""

from __future__ import annotations

import csv
import hashlib
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from features.schema import DYNAMIC_FEATURES, STATIC_FEATURES, LABEL_COLUMNS  # noqa: E402

MANIFEST_COLUMNS = [
    "battery_id", "chemistry", "n_cycles", "capacity_bol", "capacity_eol",
    "source_file", "sha256",
]

# Channels that no offline Li-ion cycler log (NASA/CALCE) can supply, with the
# reason -- loaders fill these with NaN, never a fabricated number. Individual
# loaders may add further NaN columns of their own (e.g. a channel whose
# preconditions are never met in a given file) but this set is always NaN.
COMMON_NONDERIVABLE = {
    "ocv_err": (
        "requires an independent EKF SoC estimate and a chemistry-calibrated "
        "OCV-SoC curve to compare against; this offline loader has neither -- "
        "it only re-derives what is in the raw cycler log."
    ),
    "st_float": (
        "S_T,float (design 02 SS1.5) is Arrhenius stress accumulated while the "
        "battery sits in a lead-acid-style FLOAT/trickle-charge state after "
        "reaching full charge; Li-ion CC-CV cycler protocols (NASA/CALCE) stop "
        "at a tail-current cutoff and never hold a float voltage, so the "
        "state this channel measures never occurs in the source data."
    ),
}


# --------------------------------------------------------------------------- #
# Hashing / manifest
# --------------------------------------------------------------------------- #

def sha256_file(path, chunk_size=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def write_manifest(rows, out_path):
    """rows: list of dicts with keys == MANIFEST_COLUMNS (subset ok, missing
    filled with '')."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=MANIFEST_COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in MANIFEST_COLUMNS})
    return out_path


# --------------------------------------------------------------------------- #
# Download: plain streamed GET with a byte cap, and a seekable HTTP-range file
# object usable as zipfile.ZipFile's fileobj (so a group archive can be pulled
# out of a much larger outer zip without downloading the whole outer file).
# --------------------------------------------------------------------------- #

class DownloadError(RuntimeError):
    pass


def download_file(url, dest, timeout=30, max_bytes=None, chunk_size=1 << 20):
    """Stream url -> dest. Raises DownloadError on any failure (network,
    HTTP status, or max_bytes exceeded) -- callers must not fabricate data on
    failure, only report the URL that needs fetching manually."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "sentinel-dataset-loader/1.0"})
    try:
        t0 = time.time()
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            total = 0
            with open(dest, "wb") as f:
                while True:
                    chunk = resp.read(chunk_size)
                    if not chunk:
                        break
                    total += len(chunk)
                    if max_bytes is not None and total > max_bytes:
                        raise DownloadError(
                            "%s exceeded max_bytes=%d before finishing (partial file "
                            "left at %s for inspection)" % (url, max_bytes, dest))
                    f.write(chunk)
        return {"bytes": total, "seconds": time.time() - t0, "url": url, "dest": str(dest)}
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, TimeoutError) as e:
        if dest.exists():
            try:
                dest.unlink()
            except OSError:
                pass
        raise DownloadError("failed to download %s: %s" % (url, e)) from e


class HTTPRangeFile:
    """Minimal seekable/readable file-like object over HTTP Range requests,
    buffered so zipfile's sequential/central-directory access patterns don't
    turn into one HTTP request per few-KB read. Lets us pull one named entry
    out of a multi-hundred-MB zip (the NASA PCoE archive is a zip of zips)
    while transferring only that entry's bytes, not the whole outer file."""

    def __init__(self, url, start=0, length=None, timeout=30, read_chunk=1 << 21):
        self.url = url
        self.start = start
        self.timeout = timeout
        self.read_chunk = read_chunk
        if length is None:
            req = urllib.request.Request(url, method="HEAD",
                                          headers={"User-Agent": "sentinel-dataset-loader/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                total = int(r.headers["Content-Length"])
            length = total - start
        self.length = length
        self.pos = 0
        self._buf_start = 0
        self._buf = b""
        self.n_bytes_fetched = 0

    # zipfile needs: read, seek, tell, seekable
    def seekable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, offset, whence=0):
        if whence == 0:
            self.pos = offset
        elif whence == 1:
            self.pos += offset
        elif whence == 2:
            self.pos = self.length + offset
        return self.pos

    def read(self, n=-1):
        if n is None or n < 0:
            n = self.length - self.pos
        if n <= 0 or self.pos >= self.length:
            return b""
        buf_end = self._buf_start + len(self._buf)
        if not (self._buf_start <= self.pos < buf_end):
            self._fetch(self.pos, max(n, self.read_chunk))
            buf_end = self._buf_start + len(self._buf)
        avail_start = self.pos - self._buf_start
        avail = self._buf[avail_start:avail_start + n]
        if len(avail) < n and self.pos + len(avail) < self.length:
            # buffer didn't cover the whole request (near a buffer edge): refetch
            self._fetch(self.pos, max(n, self.read_chunk))
            avail_start = self.pos - self._buf_start
            avail = self._buf[avail_start:avail_start + n]
        self.pos += len(avail)
        return avail

    def _fetch(self, start, n):
        end = min(start + n, self.length) - 1
        req = urllib.request.Request(
            self.url, headers={"Range": "bytes=%d-%d" % (self.start + start, self.start + end),
                                "User-Agent": "sentinel-dataset-loader/1.0"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            data = r.read()
        self._buf_start = start
        self._buf = data
        self.n_bytes_fetched += len(data)


def try_urls(fns, label):
    """Run each zero-arg callable in fns in order; return the first success
    (its return value), or raise DownloadError listing every URL that failed
    plus the manual-fetch instruction, per CONTRACTS honesty rules -- never
    fabricate data when every mirror fails."""
    errors = []
    for fn, url in fns:
        try:
            return fn(), url
        except DownloadError as e:
            errors.append(str(e))
    raise DownloadError(
        "%s: all mirrors failed:\n  - %s\nFetch manually from one of:\n  %s" %
        (label, "\n  - ".join(errors), "\n  ".join(u for _, u in fns))
    )


# --------------------------------------------------------------------------- #
# Numeric helpers shared by the per-cycle feature engines
# --------------------------------------------------------------------------- #

def arrhenius_factor(t_celsius):
    """AF(T) = exp(6400*(1/298.15 - 1/(T+273.15))), design 02 SS1.5. Doubles
    roughly every +10 degC around 25 degC."""
    t_celsius = np.asarray(t_celsius, dtype=np.float64)
    return np.exp(6400.0 * (1.0 / 298.15 - 1.0 / (t_celsius + 273.15)))


def trapz_ah(t_seconds, i_amps):
    """Integral of |I| dt in Ah via the trapezoid rule. Empty/1-point input -> 0."""
    t_seconds = np.asarray(t_seconds, dtype=np.float64)
    i_amps = np.asarray(i_amps, dtype=np.float64)
    if len(t_seconds) < 2:
        return 0.0
    return float(np.trapz(np.abs(i_amps), t_seconds) / 3600.0)


def carry_forward_with_staleness(values, valid_mask, max_stale=30):
    """values, valid_mask: same-length 1-D arrays, one entry per cycle.
    Returns (carried, staleness_frac) where carried[i] is the most recent
    valid value at or before i (or the first valid value if none precede it),
    and staleness_frac[i] = min(cycles_since_valid, max_stale) / max_stale.
    Design 02 SS1.6/SS1.7's carry-last-plus-staleness-channel policy."""
    values = np.asarray(values, dtype=np.float64)
    valid_mask = np.asarray(valid_mask, dtype=bool)
    n = len(values)
    carried = np.full(n, np.nan)
    stale = np.zeros(n, dtype=np.float64)
    last = np.nan
    stale_ct = max_stale
    first_valid_idx = np.argmax(valid_mask) if valid_mask.any() else None
    for i in range(n):
        if valid_mask[i]:
            last = values[i]
            stale_ct = 0
        elif first_valid_idx is not None and i < first_valid_idx:
            stale_ct = max_stale  # nothing valid has happened yet
        else:
            stale_ct = min(stale_ct + 1, max_stale)
        carried[i] = last
        stale[i] = stale_ct / max_stale
    return carried, stale


def cc_cv_transition(i_amps, drop_frac=0.98):
    """Index of the first sample where current falls below drop_frac times
    the CC-phase nominal current (median of the first third of the array) --
    i.e. where a CC->CV charge transition happened. Returns len(i_amps) if no
    such drop is found (never reached CV in this record)."""
    i_amps = np.asarray(i_amps, dtype=np.float64)
    n = len(i_amps)
    if n < 3:
        return n
    i_cc_nominal = float(np.median(i_amps[: max(n // 3, 1)]))
    if i_cc_nominal <= 0:
        return n
    below = np.where(i_amps < drop_frac * i_cc_nominal)[0]
    # ignore a below-threshold sample inside the CC nominal-estimation window
    below = below[below >= max(n // 3, 1)]
    return int(below[0]) if len(below) else n


def dqdv_curve(v, q_cum, v_lo, v_hi, n_bins=60):
    """Bin cumulative charge q_cum(Ah) against voltage v(V) into n_bins equal
    voltage bins spanning [v_lo, v_hi]; returns (bin_centers, dQ_per_bin).
    Design 02 SS1.7's ICA binning, generalised (voltage range is a parameter
    here rather than the lead-acid-specific 12.0-14.4 V window)."""
    v = np.asarray(v, dtype=np.float64)
    q_cum = np.asarray(q_cum, dtype=np.float64)
    if len(v) < 2 or v_hi <= v_lo:
        return np.array([]), np.array([])
    edges = np.linspace(v_lo, v_hi, n_bins + 1)
    centers = 0.5 * (edges[:-1] + edges[1:])
    dq = np.diff(q_cum, prepend=q_cum[0])
    bin_idx = np.clip(np.digitize(v, edges) - 1, 0, n_bins - 1)
    qbin = np.zeros(n_bins)
    np.add.at(qbin, bin_idx, np.abs(dq))
    return centers, qbin


def smooth_ma(x, window=5):
    x = np.asarray(x, dtype=np.float64)
    if len(x) < window:
        return x.copy()
    kernel = np.ones(window) / window
    pad = window // 2
    xp = np.pad(x, (pad, pad), mode="edge")
    return np.convolve(xp, kernel, mode="valid")[: len(x)]


def find_ica_peak(v_bins, qbin):
    """Smooth then argmax -> (peak_height, peak_v). NaN, NaN if qbin is all
    zero/empty (e.g. too few samples landed in the window)."""
    if len(qbin) == 0 or not np.any(qbin > 0):
        return float("nan"), float("nan")
    sm = smooth_ma(qbin, window=5)
    i = int(np.argmax(sm))
    return float(sm[i]), float(v_bins[i])

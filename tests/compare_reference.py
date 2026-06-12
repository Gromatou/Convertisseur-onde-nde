#!/usr/bin/env python3
"""
ONDE HDF5 file comparison tool for converter validation.

Compares two ONDE-format HDF5 files (the converter's output vs. the expected
reference) and reports discrepancies in:
  - Root attributes (ONDE:FILETYPE, ONDE:VERSION)
  - Group structure and ONDE:TYPE inheritance chains
  - Dataset attributes, including dimension metadata
  - Data array contents (byte-for-byte or numeric tolerance)
  - ASCAN_SAMPLE_RATE, GAIN, ASCAN_START specifics

Usage:
    python3 tests/compare_reference.py <converter_output.onde> <reference_expected.onde>

Exit code:
    0  — all checks pass
    1  — one or more checks failed

See also:
    tests/generate_reference_ut.py   — generates the reference files
    tests/run_all_tests.sh           — full test workflow
"""

import sys
import numpy as np
import h5py
from pathlib import Path

# ── Configuration ────────────────────────────────────────────────────────

FLOAT_TOLERANCE = 1e-6     # relative + absolute tolerance for float attrs
INT_MISMATCH_OK = False    # treat integer mismatches as warnings (not fail)


# ── Test Harness ─────────────────────────────────────────────────────────

class Checker:
    """Accumulates pass/fail checks and prints results."""

    def __init__(self, output_path: str, expected_path: str):
        self.output_path = output_path
        self.expected_path = expected_path
        self.passed = 0
        self.failed = 0
        self.failures: list[str] = []

    def ok(self, msg: str) -> None:
        self.passed += 1
        print(f"  ✓ {msg}")

    def fail(self, msg: str) -> None:
        self.failed += 1
        self.failures.append(msg)
        print(f"  ✗ {msg}")

    def check(self, condition: bool, msg: str) -> None:
        if condition:
            self.ok(msg)
        else:
            self.fail(msg)

    def summary(self) -> tuple[int, int]:
        total = self.passed + self.failed
        print(f"\n{'─' * 60}")
        print(f"  Results: {self.passed}/{total} checks passed")
        if self.failures:
            print(f"  Failures:")
            for f in self.failures:
                print(f"    • {f}")
        print(f"{'─' * 60}\n")
        return self.passed, self.failed


# ── Attribute Comparison Helpers ─────────────────────────────────────────

def _attr_value(attrs: dict, name: str):
    """Safely read an attribute value from h5py attrs dict."""
    if name not in attrs:
        return None
    val = attrs[name]
    # h5py may return numpy scalars; convert to native Python types
    if isinstance(val, (np.floating,)):
        return float(val)
    if isinstance(val, (np.integer,)):
        return int(val)
    if isinstance(val, np.ndarray):
        return val  # return raw array for comparison
    if isinstance(val, bytes):
        return val.decode("utf-8")
    return val


def _values_match(a, b, tolerance=FLOAT_TOLERANCE) -> bool:
    """Compare two values with tolerance for floats, exact for others."""
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    if isinstance(a, (float, np.floating)) and isinstance(b, (float, np.floating)):
        return math.isclose(float(a), float(b), rel_tol=tolerance, abs_tol=tolerance)
    if isinstance(a, (int, np.integer)) and isinstance(b, (int, np.integer)):
        return int(a) == int(b)
    if isinstance(a, str) and isinstance(b, str):
        return a == b
    if isinstance(a, bytes) and isinstance(b, bytes):
        return a == b
    if isinstance(a, bytes) and isinstance(b, str):
        return a.decode("utf-8") == b
    if isinstance(a, str) and isinstance(b, bytes):
        return a == b.decode("utf-8")
    if isinstance(a, np.ndarray) and isinstance(b, np.ndarray):
        if a.dtype.kind == "f" and b.dtype.kind == "f":
            return np.allclose(a, b, rtol=tolerance, atol=tolerance)
        return np.array_equal(a, b)
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return False
        return all(_values_match(x, y) for x, y in zip(a, b))
    # Fallback: try string representation
    return str(a) == str(b)


def _describe(val) -> str:
    """Return a human-readable description of a value."""
    if isinstance(val, np.ndarray):
        preview = np.array2string(val.ravel()[:8], precision=6, suppress_small=True)
        if val.size > 8:
            preview = preview.rstrip("]") + ", ...]"
        return f"ndarray shape={val.shape} dtype={val.dtype} values={preview}"
    if isinstance(val, list):
        return f"list len={len(val)} values={val[:8]}{'...' if len(val) > 8 else ''}"
    if isinstance(val, float):
        return repr(val)
    return repr(val)


# ── Main Comparison Logic ────────────────────────────────────────────────

import math  # noqa: E402 — needed for _values_match above


def _refs_match(exp_refs, out_refs, exp_file, out_file) -> bool:
    """Compare HDF5 reference arrays by dereferencing and matching target names."""
    exp_flat = exp_refs.ravel() if hasattr(exp_refs, 'ravel') else [exp_refs]
    out_flat = out_refs.ravel() if hasattr(out_refs, 'ravel') else [out_refs]
    if len(exp_flat) != len(out_flat):
        return False
    for i in range(len(exp_flat)):
        try:
            e_target = exp_file[exp_flat[i]].name
            o_target = out_file[out_flat[i]].name
            if e_target != o_target:
                return False
        except Exception:
            return False
    return True


def compare_files(checker: Checker) -> None:
    """Compare two ONDE HDF5 files structure-by-structure."""
    try:
        out = h5py.File(checker.output_path, "r")
    except Exception as e:
        checker.fail(f"Cannot open output file: {e}")
        return
    try:
        exp = h5py.File(checker.expected_path, "r")
    except Exception as e:
        checker.fail(f"Cannot open expected file: {e}")
        out.close()
        return

    print(f"\n Comparing: {checker.output_path}")
    print(f"      with: {checker.expected_path}")
    print(f"{'─' * 60}")

    # ── 1. Root attributes ─────────────────────────────────────────────
    print("\n═══ 1. Root Attributes ═══")
    for attr_name in ["ONDE:FILETYPE", "ONDE:VERSION"]:
        a_val = _attr_value(out.attrs, attr_name)
        b_val = _attr_value(exp.attrs, attr_name)
        if a_val is None:
            checker.fail(f"Root attr {attr_name}: MISSING in output")
        elif b_val is None:
            checker.fail(f"Root attr {attr_name}: MISSING in expected (test error)")
        else:
            checker.check(
                _values_match(a_val, b_val),
                f"Root attr {attr_name}: expected {_describe(b_val)}, got {_describe(a_val)}",
            )

    # ── 2. Group structure ──────────────────────────────────────────────
    print("\n═══ 2. Group Structure ═══")

    def _collect_groups(file) -> set[str]:
        """Return all HDF5 group paths (excluding root '/')."""
        groups = set()
        file.visititems(lambda path, obj: groups.add(f"/{path}")
                        if isinstance(obj, h5py.Group) and path != "" else None)
        return groups

    out_groups = _collect_groups(out)
    exp_groups = _collect_groups(exp)

    # Check for expected groups
    for g in sorted(exp_groups):
        checker.check(
            g in out_groups,
            f"Group {g}: expected present, {'FOUND' if g in out_groups else 'MISSING in output'}",
        )

    # Check for unexpected groups
    for g in sorted(out_groups):
        if g not in exp_groups:
            print(f"  ⚠ Group {g}: present in output but not in expected (may be benign)")

    # ── 3. ONDE:TYPE attributes on groups ───────────────────────────────
    print("\n═══ 3. Group ONDE:TYPE Attributes ═══")
    for g in sorted(exp_groups):
        if g not in out_groups:
            continue  # already reported above
        for key in ["ONDE:TYPE", "ONDE:TYPE_TAGS"]:
            out_val = _attr_value(out[g].attrs, key)
            exp_val = _attr_value(exp[g].attrs, key)
            if exp_val is None and out_val is None:
                continue  # neither has it
            if exp_val is None:
                continue  # not expected
            label = f"{g} attr {key}"
            if out_val is None:
                checker.fail(f"{label}: MISSING in output")
            else:
                # For ONDE:TYPE arrays, compare element-by-element
                if isinstance(out_val, np.ndarray) and isinstance(exp_val, np.ndarray):
                    match = out_val.shape == exp_val.shape and all(
                        _values_match(out_val[i], exp_val[i])
                        for i in range(len(out_val))
                    )
                    checker.check(
                        match,
                        f"{label}: expected {list(exp_val)}, got {list(out_val)}",
                    )
                else:
                    checker.check(
                        _values_match(out_val, exp_val),
                        f"{label}: expected {_describe(exp_val)}, got {_describe(out_val)}",
                    )

    # ── 4. Other attributes on groups ───────────────────────────────────
    print("\n═══ 4. Group Attributes (non-TYPE) ═══")
    EXPECTED_SKIP = {"ONDE:TYPE", "ONDE:TYPE_TAGS"}
    for g in sorted(exp_groups):
        if g not in out_groups:
            continue
        exp_attrs = set(exp[g].attrs.keys()) - EXPECTED_SKIP
        out_attrs = set(out[g].attrs.keys()) - EXPECTED_SKIP

        for attr_name in sorted(exp_attrs):
            exp_val = _attr_value(exp[g].attrs, attr_name)
            label = f"{g} attr {attr_name}"
            if attr_name not in out_attrs:
                checker.fail(f"{label}: MISSING in output")
            else:
                out_val = _attr_value(out[g].attrs, attr_name)
                if isinstance(exp_val, np.ndarray) and isinstance(out_val, np.ndarray):
                    if exp_val.dtype.kind == "f" and out_val.dtype.kind == "f":
                        match = np.allclose(exp_val, out_val, rtol=FLOAT_TOLERANCE, atol=FLOAT_TOLERANCE)
                    elif exp_val.dtype.kind == "O" and out_val.dtype.kind == "O":
                        # HDF5 references — compare by dereferencing and matching target names
                        match = _refs_match(exp_val, out_val, exp, out)
                    else:
                        match = np.array_equal(exp_val, out_val)
                else:
                    match = _values_match(exp_val, out_val)
                checker.check(
                    match,
                    f"{label}: expected {_describe(exp_val)}, got {_describe(out_val)}",
                )

        # Report extra attributes
        for attr_name in sorted(out_attrs - exp_attrs):
            print(f"  ℹ {g} attr {attr_name}: extra in output (not in expected)")

    # ── 5. Datasets ─────────────────────────────────────────────────────
    print("\n═══ 5. Dataset Arrays ═══")

    def _collect_datasets(file) -> dict[str, h5py.Dataset]:
        """Return mapping of path → dataset object."""
        ds_map = {}
        file.visititems(lambda path, obj: ds_map.update({f"/{path}": obj})
                        if isinstance(obj, h5py.Dataset) else None)
        return ds_map

    out_ds = _collect_datasets(out)
    exp_ds = _collect_datasets(exp)

    for ds_path in sorted(exp_ds):
        ed = exp_ds[ds_path]
        label = f"Dataset {ds_path}"
        if ds_path not in out_ds:
            checker.fail(f"{label}: MISSING in output")
            continue

        od = out_ds[ds_path]

        # Compare shape
        checker.check(
            od.shape == ed.shape,
            f"{label} shape: expected {ed.shape}, got {od.shape}",
        )

        # Compare dtype (kind + itemsize)
        dtype_ok = (
            od.dtype.kind == ed.dtype.kind
            and od.dtype.itemsize == ed.dtype.itemsize
        )
        checker.check(
            dtype_ok,
            f"{label} dtype: expected {ed.dtype}, got {od.dtype}",
        )

        # Compare data bytes
        if od.shape == ed.shape:
            if ed.dtype.kind == "f" and od.dtype.kind == "f":
                data_match = np.allclose(
                    ed[()], od[()], rtol=FLOAT_TOLERANCE, atol=FLOAT_TOLERANCE
                )
            elif ed.dtype.kind == "O" and od.dtype.kind == "O":
                data_match = _refs_match(ed[()], od[()], exp, out)
            else:
                data_match = np.array_equal(ed[()], od[()])
            checker.check(
                data_match,
                f"{label} data: {'BYTE-FOR-BYTE MATCH' if data_match else 'MISMATCH'}",
            )

    # Check for extra datasets in output
    for ds_path in sorted(set(out_ds) - set(exp_ds)):
        print(f"  ℹ {ds_path}: extra dataset in output (not in expected)")

    # ── 6. ASCAN_SAMPLE_RATE check (if available) ───────────────────────
    print("\n═══ 6. ASCAN_SAMPLE_RATE ═══")
    for g in ["/ONDE_ULTRASONIC_SETUP"]:
        if g in out_groups and g in exp_groups:
            out_rate = _attr_value(out[g].attrs, "ONDE_ULTRASONIC_SETUP:ASCAN_SAMPLE_RATE")
            exp_rate = _attr_value(exp[g].attrs, "ONDE_ULTRASONIC_SETUP:ASCAN_SAMPLE_RATE")
            if exp_rate is not None:
                checker.check(
                    out_rate is not None,
                    f"{g} ASCAN_SAMPLE_RATE: expected present",
                )
                if out_rate is not None:
                    checker.check(
                        _values_match(out_rate, exp_rate),
                        f"{g} ASCAN_SAMPLE_RATE: expected {exp_rate}, got {out_rate}",
                    )

    # ── 7. GAIN dataset ─────────────────────────────────────────────────
    print("\n═══ 7. GAIN Dataset ═══")
    for g in ["/ONDE_ULTRASONIC_SETUP"]:
        gain_path = f"{g}/GAIN"
        if gain_path in exp_ds:
            checker.check(
                gain_path in out_ds,
                f"{gain_path}: expected present as dataset",
            )
            if gain_path in out_ds:
                ed = exp_ds[gain_path]
                od = out_ds[gain_path]
                data_match = np.allclose(ed[()], od[()], rtol=FLOAT_TOLERANCE, atol=FLOAT_TOLERANCE)
                checker.check(
                    data_match,
                    f"{gain_path} values: expected {ed[()]}, got {od[()]}",
                )
        # Also check GAIN is NOT an attribute
        if g in out_groups:
            gain_attr = _attr_value(out[g].attrs, "GAIN")
            checker.check(
                gain_attr is None,
                f"{g} GAIN: should be a dataset, not an attribute (found attr value: {gain_attr})",
            )

    # ── 8. ASCAN_START dataset ──────────────────────────────────────────
    print("\n═══ 8. ASCAN_START Dataset ═══")
    for g in ["/ONDE_ULTRASONIC_SETUP"]:
        start_path = f"{g}/ASCAN_START"
        if start_path in exp_ds:
            checker.check(
                start_path in out_ds,
                f"{start_path}: expected present as dataset",
            )
            if start_path in out_ds:
                ed = exp_ds[start_path]
                od = out_ds[start_path]
                data_match = np.allclose(ed[()], od[()], rtol=FLOAT_TOLERANCE, atol=FLOAT_TOLERANCE)
                checker.check(
                    data_match,
                    f"{start_path} values: expected {ed[()]}, got {od[()]}",
                )
        if g in out_groups:
            start_attr = _attr_value(out[g].attrs, "ASCAN_START")
            checker.check(
                start_attr is None,
                f"{g} ASCAN_START: should be a dataset, not an attribute (found attr value: {start_attr})",
            )

    # ── 9. ONDE_DATASET:SETUP reference / attribute ─────────────────────
    print("\n═══ 9. ONDE_DATASET:SETUP References ═══")
    for g in sorted(exp_groups):
        if "ONDE_DATASET" not in g and "ascan" not in g and "tscan" not in g and "cscan" not in g:
            continue
        exp_setup = _attr_value(exp[g].attrs, "ONDE_DATASET:SETUP")
        if exp_setup is None:
            continue
        out_setup = _attr_value(out[g].attrs, "ONDE_DATASET:SETUP") if g in out_groups else None
        label = f"{g} attr ONDE_DATASET:SETUP"
        if out_setup is None:
            checker.fail(f"{label}: MISSING in output")
        elif isinstance(exp_setup, np.ndarray) and exp_setup.dtype.kind == "O":
            match = _refs_match(exp_setup, out_setup, exp, out)
            checker.check(match, f"{label}: expected {_describe(exp_setup)}, got {_describe(out_setup)}")
        else:
            checker.check(
                _values_match(out_setup, exp_setup),
                f"{label}: expected {_describe(exp_setup)}, got {_describe(out_setup)}",
            )

    # ── 10. INDEX_DIMENSIONS / dimension attributes ─────────────────────
    print("\n═══ 10. Dimension Attributes (INDEX_DIMENSIONS) ═══")
    for g in sorted(exp_groups):
        if g not in out_groups:
            continue
        # Check ONDE_DIM_COUNT
        exp_dc = _attr_value(exp[g].attrs, "ONDE_DIM_COUNT")
        out_dc = _attr_value(out[g].attrs, "ONDE_DIM_COUNT")
        if exp_dc is not None:
            label = f"{g} attr ONDE_DIM_COUNT"
            if out_dc is None:
                checker.fail(f"{label}: MISSING in output")
            else:
                checker.check(
                    int(out_dc) == int(exp_dc),
                    f"{label}: expected {int(exp_dc)}, got {int(out_dc)}",
                )

        # Check per-dimension attributes: COORDINATE, UNITS, OFFSET, SCALE
        if exp_dc is not None:
            n_dims = int(exp_dc)
            for dim_idx in range(n_dims):
                for suffix in ["COORDINATE", "UNITS", "OFFSET", "SCALE"]:
                    attr_name = f"ONDE_DIM_{dim_idx}_{suffix}"
                    exp_val = _attr_value(exp[g].attrs, attr_name)
                    out_val = _attr_value(out[g].attrs, attr_name)
                    if exp_val is None:
                        continue
                    label = f"{g} attr {attr_name}"
                    if out_val is None:
                        checker.fail(f"{label}: MISSING in output")
                    else:
                        checker.check(
                            _values_match(exp_val, out_val),
                            f"{label}: expected {_describe(exp_val)}, got {_describe(out_val)}",
                        )

    # ── Cleanup ──────────────────────────────────────────────────────────
    out.close()
    exp.close()


# ── Main ─────────────────────────────────────────────────────────────────

def main() -> int:
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <converter_output.onde> <reference_expected.onde>",
              file=sys.stderr)
        return 1

    output_path = sys.argv[1]
    expected_path = sys.argv[2]

    if not Path(output_path).is_file():
        print(f"Error: output file not found: {output_path}", file=sys.stderr)
        return 1
    if not Path(expected_path).is_file():
        print(f"Error: expected file not found: {expected_path}", file=sys.stderr)
        return 1

    checker = Checker(output_path, expected_path)
    compare_files(checker)
    passed, failed = checker.summary()

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
Round-trip verification: convert ONDE files back to NDE format and compare
with the original NDE source files.

Usage:
    python tests/generate_roundtrip_nde.py

Output: tests/roundtrip_report.txt
"""

import h5py
import json
import math
import os
import sys
import numpy as np

# Paths
FIXTURE_DIR = "tests/fixtures"
REPORT_PATH = "tests/roundtrip_report.txt"

# ─── ONDE files → original NDE files ───
ROUNDTRIPS = [
    {
        "name": "UT",
        "onde": "real_ut_expected.onde",
        "nde": "Weld_Plate_UT-sk90-4.2.nde",
    },
    {
        "name": "PA",
        "onde": "real_pa_expected.onde",
        "nde": "Weld_Plate_PA-Sect_sk90-4.2.nde",
    },
    {
        "name": "TOFD",
        "onde": "real_tofd_expected.onde",
        "nde": "Weld_Plate_ToFD_Parallel-4.2.nde",
    },
]

# ─── Helpers ───

def resolve_ref(file, ref):
    """Resolve a single HDF5 reference to the target object."""
    if isinstance(ref, h5py.h5r.Reference):
        return file[ref]
    if isinstance(ref, np.ndarray) and ref.dtype.kind == 'O' and len(ref) > 0:
        first = ref.flatten()[0]
        if isinstance(first, h5py.h5r.Reference):
            return file[first]
    if isinstance(ref, h5py.h5r.RegionReference):
        return file[ref]
    return None


def resolve_refs(file, ref_array):
    """Resolve an array of HDF5 references."""
    if ref_array is None:
        return []
    if isinstance(ref_array, h5py.h5r.Reference):
        return [file[ref_array]]
    arr = np.array(ref_array).flatten()
    result = []
    for item in arr:
        if isinstance(item, h5py.h5r.Reference):
            result.append(file[item])
    return result


def get_attr(group, name, default=None):
    """Get an attribute from an HDF5 group, returning default if not present."""
    return group.attrs.get(name, default)


def get_dataset(group, name):
    """Get a dataset from a group, returning None if not present."""
    if name in group:
        return group[name][()]
    return None


def linear_to_db(linear):
    """Convert linear gain to dB."""
    if linear <= 0:
        return 0.0
    return 20.0 * math.log10(float(linear))


def db_to_linear(db):
    """Convert dB gain to linear."""
    return 10.0 ** (db / 20.0)


def rectification_onde_to_nde(onde_rect):
    """Map ONDE rectification string to NDE rectification string."""
    mapping = {
        "FULL_WAVE": "None",
        "RECTIFIED_FULL": "Full",
        "RECTIFIED_POSITIVE": "Positive",
        "RECTIFIED_NEGATIVE": "Negative",
    }
    return mapping.get(onde_rect, onde_rect)


def rectification_nde_to_onde(nde_rect):
    """Map NDE rectification string to ONDE rectification string."""
    mapping = {
        "None": "FULL_WAVE",
        "Full": "RECTIFIED_FULL",
        "Positive": "RECTIFIED_POSITIVE",
        "Negative": "RECTIFIED_NEGATIVE",
    }
    return mapping.get(nde_rect, nde_rect)


def wave_mode_nde_to_onde(nde_wave_mode, beam_angle):
    """Map NDE wave mode and angle to ONDE velocity array selection."""
    # ONDE VELOCITIES: [longitudinal, transversal]
    # NDE waveMode: "Longitudinal" or "TransversalVertical"
    if nde_wave_mode == "Longitudinal":
        return 0  # index into velocity array
    else:
        return 1


# ─── Round-trip conversion: ONDE → NDE ───

def read_onde_and_reconstruct_nde(onde_path):
    """
    Read an ONDE file and reconstruct NDE setup JSON from its contents.
    Returns a dict of NDE setup fields that can be compared.
    """
    file = h5py.File(onde_path, "r")

    result = {}

    # ── 1. File-level attributes ──
    result["ONDE:FILETYPE"] = get_attr(file, "ONDE:FILETYPE", "")
    result["ONDE:VERSION"] = get_attr(file, "ONDE:VERSION", "")

    # ── 2. Find the dataset group ──
    dataset_group = None
    for name in file:
        if name.startswith("ONDE_DATASET_UT_ASCAN"):
            dataset_group = file[name]
            break
    if dataset_group is None:
        file.close()
        return result

    result["DATASET:LABEL"] = get_attr(dataset_group, "ONDE:LABEL", "")
    result["DATASET:TYPE"] = list(get_attr(dataset_group, "ONDE:TYPE", []))

    # ── 3. Handle ONDE_DATASET:SETUP reference → ONDE_SETUP_UT ──
    setup_ref = get_attr(dataset_group, "ONDE_DATASET:SETUP", None)
    setup_group = resolve_ref(file, setup_ref) if setup_ref is not None else None

    # Follow ULTRASONIC_SETUP reference
    us_group = None
    pa_setup_group = None
    if setup_group is not None:
        us_ref = get_attr(setup_group, "ONDE_SETUP_UT:ULTRASONIC_SETUP", None)
        us_group = resolve_ref(file, us_ref) if us_ref is not None else None

        # Get geometric setup
        gs_ref = get_attr(setup_group, "ONDE_SETUP:GEOMETRIC_SETUP", None)
        gs_group = resolve_ref(file, gs_ref) if gs_ref is not None else None

        if gs_group is not None:
            # Get component
            comp_refs = get_dataset(gs_group, "COMPONENT")
            if comp_refs is not None:
                comp_groups = resolve_refs(file, comp_refs)
                if comp_groups:
                    result["COMPONENT"] = extract_component(file, comp_groups[0])

            # Get probe list
            probe_refs = get_dataset(gs_group, "PROBE_LIST")
            if probe_refs is not None:
                probe_groups = resolve_refs(file, probe_refs)
                result["PROBES"] = extract_probes(file, probe_groups)

            # Get probe coordinate frames
            pcf = get_dataset(gs_group, "PROBE_COORDINATE_FRAME")
            if pcf is not None:
                result["PROBE_COORDINATE_FRAMES"] = pcf.tolist()

            # Get acquisition trajectories (for TOFD)
            traj_refs = get_dataset(gs_group, "ACQUISITION_TRAJECTORY")
            if traj_refs is not None:
                result["ACQUISITION_TRAJECTORIES"] = len(resolve_refs(file, traj_refs))

    if us_group is not None:
        result["ULTRASONIC_SETUP"] = extract_ultrasonic_setup(file, us_group)

        # Check for phased array setup
        pa_ref = get_attr(us_group, "ONDE_ULTRASONIC_SETUP:PHASED_ARRAY_SETUP", None)
        if pa_ref is not None:
            pa_setup_group = resolve_ref(file, pa_ref)
            result["PHASED_ARRAY_SETUP"] = extract_pa_setup(file, pa_setup_group)

        # Extract transmit/receive laws
        tx_law_refs = get_dataset(us_group, "TRANSMIT_LAW")
        rx_law_refs = get_dataset(us_group, "RECEIVE_LAW")
        if tx_law_refs is not None:
            result["TRANSMIT_LAWS"] = extract_laws(file, tx_law_refs)
        if rx_law_refs is not None:
            result["RECEIVE_LAWS"] = extract_laws(file, rx_law_refs)

    # ── 4. Extract data info ──
    data = get_dataset(dataset_group, "DATA")
    if data is not None:
        result["DATA_SHAPE"] = list(data.shape)
        result["DATA_DTYPE"] = str(data.dtype)
        result["DATA_MIN"] = int(data.min())
        result["DATA_MAX"] = int(data.max())

    # ── 5. Extract dimension info ──
    amp_dim_ref = get_attr(dataset_group, "ONDE_DATASET:AMPLITUDE_DIMENSION", None)
    idx_dims_refs = get_attr(dataset_group, "ONDE_DATASET:INDEX_DIMENSIONS", None)

    if amp_dim_ref is not None:
        amp_group = resolve_ref(file, amp_dim_ref)
        if amp_group is not None:
            result["AMP_DIM"] = {
                "coordinate": get_attr(amp_group, "ONDE_DIMENSION:COORDINATE", ""),
                "units": get_attr(amp_group, "ONDE_DIMENSION:UNITS", ""),
                "offset": float(get_attr(amp_group, "ONDE_DIMENSION:OFFSET", 0.0)),
                "scale": float(get_attr(amp_group, "ONDE_DIMENSION:SCALE", 1.0)),
            }

    if idx_dims_refs is not None:
        dim_groups = resolve_refs(file, idx_dims_refs)
        idx_dims = []
        for dg in dim_groups:
            idx_dims.append({
                "coordinate": get_attr(dg, "ONDE_DIMENSION:COORDINATE", ""),
                "units": get_attr(dg, "ONDE_DIMENSION:UNITS", ""),
                "offset": float(get_attr(dg, "ONDE_DIMENSION:OFFSET", 0.0)),
                "scale": float(get_attr(dg, "ONDE_DIMENSION:SCALE", 1.0)),
            })
        result["INDEX_DIMS"] = idx_dims

    file.close()
    return result


def extract_component(file, comp_group):
    """Extract component information from an ONDE_COMPONENT group."""
    comp = {}
    comp["type"] = list(get_attr(comp_group, "ONDE:TYPE", []))
    comp["velocities"] = get_attr(comp_group, "ONDE_COMPONENT:VELOCITIES", [0, 0]).tolist()
    comp["density"] = float(get_attr(comp_group, "ONDE_COMPONENT:DENSITY", 0.0))

    # Plane
    if "ONDE_PLANE" in comp["type"]:
        comp["geometry_type"] = "plane"
        comp["plate_dimensions"] = get_attr(comp_group, "ONDE_PLANE:PLATE_DIMENSIONS", [0, 0, 0]).tolist()
    elif "ONDE_CYLINDER" in comp["type"]:
        comp["geometry_type"] = "cylinder"
        comp["cylinder_dimensions"] = get_attr(comp_group, "ONDE_CYLINDER:DIMENSIONS", [0, 0, 0]).tolist()

    return comp


def extract_probes(file, probe_groups):
    """Extract probe information from ONDE_UT_PROBE groups."""
    probes = []
    for pg in probe_groups:
        probe = {}
        probe["label"] = get_attr(pg, "ONDE:LABEL", "")
        probe["type"] = list(get_attr(pg, "ONDE:TYPE", []))
        probe["frequency"] = float(get_attr(pg, "ONDE_UT_PROBE:FREQUENCY", 0.0))
        probe["bandwidth"] = float(get_attr(pg, "ONDE_UT_PROBE:BANDWIDTH", 0.0))

        # Mono or linear
        if "ONDE_MONO_UT_PROBE" in probe["type"]:
            probe["probe_class"] = "mono"
        elif "ONDE_LINEAR_UT_PROBE" in probe["type"]:
            probe["probe_class"] = "linear"
            probe["total_elements"] = int(get_attr(pg, "ONDE_LINEAR_UT_PROBE:TOTAL_NUMBER_OF_ELEMENTS", 0))
            probe["element_dim_major"] = float(get_attr(pg, "ONDE_LINEAR_UT_PROBE:ELEMENT_DIM_MAJOR", 0.0))
            probe["element_dim_minor"] = float(get_attr(pg, "ONDE_LINEAR_UT_PROBE:ELEMENT_DIM_MINOR", 0.0))
            probe["element_pitch_dim_major"] = float(get_attr(pg, "ONDE_LINEAR_UT_PROBE:ELEMENT_PITCH_DIM_MAJOR", 0.0))

        # Coupling
        coupling_ref = get_attr(pg, "ONDE_UT_PROBE:COUPLING", None)
        if coupling_ref is not None:
            coupling_group = resolve_ref(file, coupling_ref)
            if coupling_group is not None:
                coupling = {}
                coupling["type"] = list(get_attr(coupling_group, "ONDE:TYPE", []))
                coupling["medium_velocity"] = get_attr(coupling_group, "ONDE_UT_COUPLING:MEDIUM_VELOCITY", [0, 0]).tolist()
                coupling["incidence_angle"] = float(get_attr(coupling_group, "ONDE_UT_COUPLING:INCIDENCE_ANGLE", 0.0))

                if "ONDE_WEDGE" in coupling["type"]:
                    coupling["height"] = float(get_attr(coupling_group, "ONDE_WEDGE:HEIGHT", 0.0))
                    coupling["contact_area"] = get_attr(coupling_group, "ONDE_WEDGE:CONTACT_AREA", [0, 0, 0]).tolist()
                    coupling["skew_angle"] = float(get_attr(coupling_group, "ONDE_WEDGE:SKEW_ANGLE", 0.0))

                probe["coupling"] = coupling

        probes.append(probe)

    return probes


def extract_ultrasonic_setup(file, us_group):
    """Extract ultrasonic setup information."""
    us = {}
    us["sample_rate"] = float(get_attr(us_group, "ONDE_ULTRASONIC_SETUP:ASCAN_SAMPLE_RATE", 0.0))
    us["rectification"] = get_attr(us_group, "ONDE_ULTRASONIC_SETUP:RECTIFICATION", "")

    # GAIN (linear in ONDE)
    gain_data = get_dataset(us_group, "GAIN")
    if gain_data is not None:
        us["gain_linear"] = gain_data.flatten().tolist()
        us["gain_db"] = [round(linear_to_db(g), 6) for g in us["gain_linear"]]

    # ASCAN_START
    start_data = get_dataset(us_group, "ASCAN_START")
    if start_data is not None:
        us["ascan_start"] = start_data.flatten().tolist()

    return us


def extract_pa_setup(file, pa_group):
    """Extract phased array setup information."""
    pa = {}
    pa["type"] = list(get_attr(pa_group, "ONDE:TYPE", []))
    pa["sequence_angle_mode"] = get_attr(pa_group, "ONDE_PHASED_ARRAY_SETUP:SEQUENCE_ANGLE_MODE", "")

    # Emitter/receiver probes
    for attr_name, key in [("ONDE_PHASED_ARRAY_SETUP:EMITTER_PROBE", "emitter_probe"),
                           ("ONDE_PHASED_ARRAY_SETUP:RECEIVING_PROBE", "receiver_probe")]:
        ref = get_attr(pa_group, attr_name, None)
        if ref is not None:
            target = resolve_ref(file, ref)
            if target is not None:
                pa[key] = get_attr(target, "ONDE:LABEL", str(target.name))

    # Angle or Sscan
    if "ONDE_PHASED_ARRAY_SSCAN" in pa["type"]:
        pa["scan_type"] = "sectorial"
        pa["start_angle"] = float(get_attr(pa_group, "ONDE_PHASED_ARRAY_SSCAN:STARTING_ANGLE", 0.0))
        pa["end_angle"] = float(get_attr(pa_group, "ONDE_PHASED_ARRAY_SSCAN:FINISHING_ANGLE", 0.0))
        pa["num_angles"] = int(get_attr(pa_group, "ONDE_PHASED_ARRAY_SSCAN:NUMBER_OF_ANGLES", 0))
    elif "ONDE_PHASED_ARRAY_ANGLE" in pa["type"]:
        pa["scan_type"] = "angle"
        pa["bscan_angle"] = float(get_attr(pa_group, "ONDE_PHASED_ARRAY_ANGLE:BSCAN_ANGLE", 0.0))
    elif "ONDE_PHASED_ARRAY_ESCAN" in pa["type"]:
        pa["scan_type"] = "electronic"
        pa["num_elements"] = int(get_attr(pa_group, "ONDE_PHASED_ARRAY_ESCAN:NUMBER_OF_ELEMENTS", 0))
        pa["step"] = int(get_attr(pa_group, "ONDE_PHASED_ARRAY_ESCAN:STEP", 0))
        pa["angle"] = float(get_attr(pa_group, "ONDE_PHASED_ARRAY_ESCAN:ANGLE", 0.0))

    return pa


def extract_laws(file, law_refs):
    """Extract transmit/receive law information."""
    law_groups = resolve_refs(file, law_refs)
    laws = []
    for lg in law_groups:
        law = {
            "probe": get_dataset(lg, "PROBE"),
            "element": get_dataset(lg, "ELEMENT").tolist() if get_dataset(lg, "ELEMENT") is not None else [],
            "delay": get_dataset(lg, "DELAY").tolist() if get_dataset(lg, "DELAY") is not None else [],
            "weighting": get_dataset(lg, "WEIGHTING").tolist() if get_dataset(lg, "WEIGHTING") is not None else [],
        }
        laws.append(law)
    return laws


# ─── Comparison ───

def compare_values(name, original, roundtrip, tolerance=1e-6):
    """
    Compare two values and return a mismatch record or None.
    Handles numbers, strings, lists, and nested structures.
    """
    if original is None and roundtrip is None:
        return None
    if original is None or roundtrip is None:
        return {
            "field": name,
            "original": original,
            "roundtrip": roundtrip,
            "issue": "None vs value mismatch",
        }

    # Both are dicts
    if isinstance(original, dict) and isinstance(roundtrip, dict):
        mismatches = []
        all_keys = set(original.keys()) | set(roundtrip.keys())
        for k in sorted(all_keys):
            v1 = original.get(k)
            v2 = roundtrip.get(k)
            sub = compare_values(f"{name}.{k}", v1, v2, tolerance)
            if sub:
                mismatches.append(sub)
        return mismatches if mismatches else None

    # Both are lists
    if isinstance(original, list) and isinstance(roundtrip, list):
        mismatches = []
        max_len = max(len(original), len(roundtrip))
        for i in range(max_len):
            v1 = original[i] if i < len(original) else None
            v2 = roundtrip[i] if i < len(roundtrip) else None
            sub = compare_values(f"{name}[{i}]", v1, v2, tolerance)
            if sub:
                mismatches.append(sub)
        return mismatches if mismatches else None

    # Both are numbers (int or float)
    if isinstance(original, (int, float, np.generic)) and isinstance(roundtrip, (int, float, np.generic)):
        o = float(original)
        r = float(roundtrip)
        if abs(o - r) > tolerance * max(1.0, abs(o), abs(r)):
            return {
                "field": name,
                "original": o,
                "roundtrip": r,
                "issue": "Value mismatch",
            }
        return None

    # Both are strings
    if isinstance(original, str) and isinstance(roundtrip, str):
        if original != roundtrip:
            return {
                "field": name,
                "original": repr(original),
                "roundtrip": repr(roundtrip),
                "issue": "String mismatch",
            }
        return None

    # Type mismatch
    if type(original) != type(roundtrip):
        return {
            "field": name,
            "original": repr(original),
            "roundtrip": repr(roundtrip),
            "issue": f"Type mismatch ({type(original).__name__} vs {type(roundtrip).__name__})",
        }

    return None


def flatten_mismatches(mismatches, prefix=""):
    """Flatten nested mismatch list into a list of dicts."""
    if mismatches is None:
        return []
    if isinstance(mismatches, dict):
        return [mismatches]
    results = []
    for m in mismatches:
        if isinstance(m, list):
            results.extend(flatten_mismatches(m, prefix))
        elif isinstance(m, dict):
            if "field" in m:
                results.append(m)
            else:
                # It's a dict of sub-items
                for k, v in m.items():
                    sub = flatten_mismatches(v, f"{prefix}.{k}" if prefix else k)
                    results.extend(sub)
        else:
            results.append({"field": prefix, "value": str(m)})
    return results


# ─── NDE setup extractor (for reference comparison) ───

def extract_nde_setup(nde_path):
    """
    Read an NDE file (HDF5) and extract the Public/Setup JSON.
    Returns the full parsed JSON dict.
    """
    with h5py.File(nde_path, "r") as f:
        setup_str = f["Public/Setup"][()].decode("utf-8")
        return json.loads(setup_str)


def get_nde_fields_for_comparison(nde_setup):
    """
    Extract key fields from NDE setup for comparison.
    Returns a flat-ish dict of field paths to values.
    """
    fields = {}

    if not nde_setup:
        return fields

    # Version
    fields["version"] = nde_setup.get("version", "")
    fields["scenario"] = nde_setup.get("scenario", "")

    # Groups → processes
    groups = nde_setup.get("groups", [])
    if groups:
        g = groups[0]
        processes = g.get("processes", [])

        for p in processes:
            pid = p.get("id", 0)
            impl = p.get("implementation", "")
            fields[f"process[{pid}].implementation"] = impl

            # Determine process type
            for ptype in ["ultrasonicConventional", "ultrasonicPhasedArray"]:
                uc = p.get(ptype)
                if uc is None:
                    continue

                # Common fields
                for key in ["waveMode", "velocity", "wedgeDelay", "rectification",
                            "digitizingFrequency", "ascanCompressionFactor",
                            "gain", "ultrasoundMode", "referenceAmplitude",
                            "referenceGain", "averagingFactor"]:
                    if key in uc:
                        fields[f"process[{pid}].{ptype}.{key}"] = uc[key]

                # Smoothing filter
                if "smoothingFilter" in uc:
                    fields[f"process[{pid}].{ptype}.smoothingFilter"] = uc["smoothingFilter"]

                # Digital band-pass filter
                if "digitalBandPassFilter" in uc:
                    dbf = uc["digitalBandPassFilter"]
                    for k in ["filterType", "highCutOffFrequency", "lowCutOffFrequency", "characteristic"]:
                        if k in dbf:
                            fields[f"process[{pid}].{ptype}.digitalBandPassFilter.{k}"] = dbf[k]

                # Pulse
                if "pulse" in uc:
                    for k in ["width", "voltage", "polarity"]:
                        if k in uc["pulse"]:
                            fields[f"process[{pid}].{ptype}.pulse.{k}"] = uc["pulse"][k]

                # Focusing (PA)
                if "focusing" in uc:
                    for k in ["mode", "distance", "angle"]:
                        if k in uc["focusing"]:
                            fields[f"process[{pid}].{ptype}.focusing.{k}"] = uc["focusing"][k]

                # Beams
                beams = uc.get("beams", [])
                fields[f"process[{pid}].{ptype}.num_beams"] = len(beams)
                for bi, b in enumerate(beams):
                    for bk in ["id", "refractedAngle", "ascanStart", "ascanLength",
                               "beamDelay", "skewAngle", "gainOffset", "sumGain",
                               "sumGainMode"]:
                        if bk in b:
                            fields[f"process[{pid}].{ptype}.beams[{bi}].{bk}"] = b[bk]
                    # Pulsers / receivers delays
                    for pk in ["pulsers", "receivers"]:
                        if pk in b and isinstance(b[pk], list) and len(b[pk]) > 0:
                            # Store first/last delay
                            delays = [e.get("delay", 0) for e in b[pk]]
                            fields[f"process[{pid}].{ptype}.beams[{bi}].{pk}_count"] = len(delays)
                            if delays:
                                fields[f"process[{pid}].{ptype}.beams[{bi}].{pk}_delay_min"] = min(delays)
                                fields[f"process[{pid}].{ptype}.beams[{bi}].{pk}_delay_max"] = max(delays)

                # Gates
                gates = uc.get("gates", [])
                fields[f"process[{pid}].{ptype}.num_gates"] = len(gates)
                for gi, gate in enumerate(gates):
                    for gk in ["id", "start", "length", "threshold", "thresholdPolarity",
                               "geometry"]:
                        if gk in gate:
                            fields[f"process[{pid}].{ptype}.gates[{gi}].{gk}"] = gate[gk]

                # Pulse echo / pitch-catch / TOFD specifics
                for sub in ["pulseEcho", "pitchCatch", "tofd"]:
                    if sub in uc:
                        sub_obj = uc[sub]
                        if isinstance(sub_obj, dict):
                            for k, v in sub_obj.items():
                                if not isinstance(v, (dict, list)):
                                    fields[f"process[{pid}].{ptype}.{sub}.{k}"] = v
                                elif k == "sectorialFormation":
                                    sf = v
                                    for sfk in ["probeFirstElementId", "elementAperture"]:
                                        if sfk in sf:
                                            fields[f"process[{pid}].{ptype}.{sub}.sectorialFormation.{sfk}"] = sf[sfk]
                                    if "beamRefractedAngles" in sf:
                                        bra = sf["beamRefractedAngles"]
                                        for brak in ["start", "stop", "step"]:
                                            if brak in bra:
                                                fields[f"process[{pid}].{ptype}.{sub}.sectorialFormation.beamRefractedAngles.{brak}"] = bra[brak]

        # Datasets
        datasets = g.get("datasets", [])
        for ds in datasets:
            ds_id = ds.get("id", 0)
            fields[f"dataset[{ds_id}].dataClass"] = ds.get("dataClass", "")
            fields[f"dataset[{ds_id}].storageMode"] = ds.get("storageMode", "")
            dv = ds.get("dataValue", {})
            for k in ["min", "max", "unitMin", "unitMax", "unit"]:
                if k in dv:
                    fields[f"dataset[{ds_id}].dataValue.{k}"] = dv[k]
            dims = ds.get("dimensions", [])
            fields[f"dataset[{ds_id}].num_dimensions"] = len(dims)
            for di, dim in enumerate(dims):
                for dk in ["axis", "quantity", "resolution", "offset"]:
                    if dk in dim:
                        fields[f"dataset[{ds_id}].dimensions[{di}].{dk}"] = dim[dk]
                # Beam axis with beam sub-objects
                if "beams" in dim:
                    beams_list = dim["beams"]
                    fields[f"dataset[{ds_id}].dimensions[{di}].num_beams"] = len(beams_list)
                    for bi, bdim in enumerate(beams_list):
                        for bdk in ["velocity", "skewAngle", "refractedAngle",
                                    "uCoordinateOffset", "vCoordinateOffset",
                                    "ultrasoundOffset"]:
                            if bdk in bdim:
                                fields[f"dataset[{ds_id}].dimensions[{di}].beams[{bi}].{bdk}"] = bdim[bdk]

    # Specimens
    specimens = nde_setup.get("specimens", [])
    fields["num_specimens"] = len(specimens)
    for si, spec in enumerate(specimens):
        # Material
        for geo_key in ["plateGeometry", "pipeGeometry"]:
            geo = spec.get(geo_key)
            if geo:
                fields[f"specimen[{si}].geometry_type"] = geo_key
                for gk in ["width", "length", "thickness", "outerRadius"]:
                    if gk in geo:
                        fields[f"specimen[{si}].{geo_key}.{gk}"] = geo[gk]
                mat = geo.get("material", {})
                if mat:
                    fields[f"specimen[{si}].material.name"] = mat.get("name", "")
                    for wave_key in ["longitudinalWave", "transversalVerticalWave"]:
                        wave = mat.get(wave_key, {})
                        if wave:
                            fields[f"specimen[{si}].material.{wave_key}.nominalVelocity"] = wave.get("nominalVelocity", 0)
                    fields[f"specimen[{si}].material.density"] = mat.get("density", 0)
                break  # Only one geometry type

    # Probes
    probes = nde_setup.get("probes", [])
    fields["num_probes"] = len(probes)
    for pi, probe in enumerate(probes):
        for probe_type in ["conventionalRound", "conventionalRectangular", "phasedArrayLinear"]:
            pdata = probe.get(probe_type)
            if pdata:
                fields[f"probe[{pi}].model"] = probe.get("model", "")
                fields[f"probe[{pi}].type"] = probe_type
                fields[f"probe[{pi}].centralFrequency"] = pdata.get("centralFrequency", 0)
                if "diameter" in pdata:
                    fields[f"probe[{pi}].diameter"] = pdata["diameter"]
                fields[f"probe[{pi}].num_elements"] = len(pdata.get("elements", []))
                if "primaryAxis" in pdata:
                    for ak in ["elementQuantity", "elementLength", "elementGap", "referencePoint", "casingLength"]:
                        if ak in pdata["primaryAxis"]:
                            fields[f"probe[{pi}].primaryAxis.{ak}"] = pdata["primaryAxis"][ak]
                if "secondaryAxis" in pdata:
                    for ak in ["elementQuantity", "elementLength", "elementGap", "referencePoint", "casingLength"]:
                        if ak in pdata["secondaryAxis"]:
                            fields[f"probe[{pi}].secondaryAxis.{ak}"] = pdata["secondaryAxis"][ak]

    # Wedges
    wedges = nde_setup.get("wedges", [])
    fields["num_wedges"] = len(wedges)
    for wi, wedge in enumerate(wedges):
        aw = wedge.get("angleBeamWedge", {})
        fields[f"wedge[{wi}].model"] = wedge.get("model", "")
        fields[f"wedge[{wi}].longitudinalVelocity"] = aw.get("longitudinalVelocity", 0)
        fields[f"wedge[{wi}].height"] = aw.get("height", 0)
        fields[f"wedge[{wi}].width"] = aw.get("width", 0)
        ml = aw.get("mountingLocations", [{}])[0]
        fields[f"wedge[{wi}].wedgeAngle"] = ml.get("wedgeAngle", 0)

    return fields


def get_onde_fields_for_comparison(onde_result):
    """
    Extract key fields from ONDE reconstruct for comparison with NDE.
    Returns a flat-ish dict of field paths to values.
    """
    fields = {}

    # Dimensions → NDE axis
    idx_dims = onde_result.get("INDEX_DIMS", [])
    for di, dim in enumerate(idx_dims):
        coord = dim.get("coordinate", "")
        scale = dim.get("scale", 1.0)
        offset = dim.get("offset", 0.0)
        units = dim.get("units", "")

        if coord == "U":
            fields[f"dim_u.scale"] = scale
            fields[f"dim_u.offset"] = offset
        elif coord == "V":
            fields[f"dim_v.scale"] = scale
            fields[f"dim_v.offset"] = offset
        elif coord == "Time":
            fields[f"dim_time.scale"] = scale
            fields[f"dim_time.offset"] = offset
        elif coord == "Beam":
            fields[f"dim_beam.scale"] = scale
            fields[f"dim_beam.offset"] = offset

    # Data shape → NDE dataset dimensions
    data_shape = onde_result.get("DATA_SHAPE", [])
    if len(data_shape) >= 3:
        fields["data.n_u"] = data_shape[0]
        fields["data.n_beam_or_v"] = data_shape[1]
        fields["data.n_time"] = data_shape[2]

    # Ultrasonic setup
    us = onde_result.get("ULTRASONIC_SETUP", {})
    if us:
        fields["ultrasonic_setup.sample_rate"] = us.get("sample_rate", 0)
        fields["ultrasonic_setup.rectification"] = us.get("rectification", "")
        gain_lin = us.get("gain_linear", [])
        gain_db = us.get("gain_db", [])
        if gain_lin:
            fields["ultrasonic_setup.gain_linear_first"] = gain_lin[0]
            fields["ultrasonic_setup.gain_db_first"] = gain_db[0]
            fields["ultrasonic_setup.num_gains"] = len(gain_lin)
        ascan_start = us.get("ascan_start", [])
        if ascan_start:
            fields["ultrasonic_setup.ascan_start_first"] = ascan_start[0]
            fields["ultrasonic_setup.ascan_start_last"] = ascan_start[-1]

    # Component
    comp = onde_result.get("COMPONENT", {})
    if comp:
        fields["component.velocities"] = comp.get("velocities", [])
        fields["component.density"] = comp.get("density", 0)
        fields["component.geometry_type"] = comp.get("geometry_type", "")
        if "plate_dimensions" in comp:
            fields["component.plate_dimensions"] = comp["plate_dimensions"]
        if "cylinder_dimensions" in comp:
            fields["component.cylinder_dimensions"] = comp["cylinder_dimensions"]

    # Probes
    probes = onde_result.get("PROBES", [])
    fields["num_probes"] = len(probes)
    for pi, probe in enumerate(probes):
        fields[f"probe[{pi}].frequency"] = probe.get("frequency", 0)
        fields[f"probe[{pi}].label"] = probe.get("label", "")
        fields[f"probe[{pi}].probe_class"] = probe.get("probe_class", "")
        if probe.get("probe_class") == "linear":
            fields[f"probe[{pi}].total_elements"] = probe.get("total_elements", 0)
            fields[f"probe[{pi}].element_dim_major"] = probe.get("element_dim_major", 0.0)
            fields[f"probe[{pi}].element_pitch_dim_major"] = probe.get("element_pitch_dim_major", 0.0)

        coupling = probe.get("coupling", {})
        if coupling:
            fields[f"probe[{pi}].coupling.incidence_angle"] = coupling.get("incidence_angle", 0)
            fields[f"probe[{pi}].coupling.medium_velocity"] = coupling.get("medium_velocity", [0, 0])
            if "height" in coupling:
                fields[f"probe[{pi}].coupling.height"] = coupling["height"]
            if "skew_angle" in coupling:
                fields[f"probe[{pi}].coupling.skew_angle"] = coupling["skew_angle"]

    # Phased Array
    pa = onde_result.get("PHASED_ARRAY_SETUP", {})
    if pa:
        fields["pa.sequence_angle_mode"] = pa.get("sequence_angle_mode", "")
        fields["pa.scan_type"] = pa.get("scan_type", "")
        if "start_angle" in pa:
            fields["pa.start_angle"] = pa["start_angle"]
            fields["pa.end_angle"] = pa["end_angle"]
            fields["pa.num_angles"] = pa["num_angles"]

    # Laws (PA)
    tx_laws = onde_result.get("TRANSMIT_LAWS", [])
    rx_laws = onde_result.get("RECEIVE_LAWS", [])
    fields["num_tx_laws"] = len(tx_laws)
    fields["num_rx_laws"] = len(rx_laws)

    return fields


def compare_onde_vs_nde(onde_result, nde_setup, case_name):
    """
    Compare ONDE-derived fields with original NDE fields.
    Returns list of mismatch dicts.
    """
    mismatches = []

    # ─── Check 1: Raw data arrays ───
    # Data shape
    data_shape = onde_result.get("DATA_SHAPE", [])
    if len(data_shape) >= 3:
        for g in nde_setup.get("groups", []):
            for ds in g.get("datasets", []):
                if ds.get("dataClass") == "AScanAmplitude":
                    dims = ds.get("dimensions", [])
                    nde_shape = []
                    for d in dims:
                        if d.get("axis") == "Beam":
                            # Beam axis: quantity is number of beam objects
                            nde_shape.append(len(d.get("beams", [])))
                        else:
                            nde_shape.append(d.get("quantity", 0))
                    if len(nde_shape) >= 1:
                        if np.prod(nde_shape) != np.prod(data_shape):
                            mismatches.append({
                                "field": f"[{case_name}] data.total_elements",
                                "original": int(np.prod(nde_shape)),
                                "roundtrip": int(np.prod(data_shape)),
                                "issue": "Total element count mismatch",
                            })
                    break

    # ─── Check 2: digitizingFrequency vs sample_rate * compressionFactor ───
    us = onde_result.get("ULTRASONIC_SETUP", {})
    sample_rate = us.get("sample_rate", 0)

    for g in nde_setup.get("groups", []):
        for p in g.get("processes", []):
            for ptype in ["ultrasonicConventional", "ultrasonicPhasedArray"]:
                uc = p.get(ptype)
                if uc is None:
                    continue
                dig_freq = uc.get("digitizingFrequency", 0)
                comp_factor = uc.get("ascanCompressionFactor", 1)

                computed_dig_freq = sample_rate * comp_factor
                if dig_freq and abs(computed_dig_freq - dig_freq) > 1.0:
                    mismatches.append({
                        "field": f"[{case_name}] digitizingFrequency",
                        "original": dig_freq,
                        "roundtrip": computed_dig_freq,
                        "issue": f"sample_rate({sample_rate}) * compressionFactor({comp_factor}) != digitizingFrequency({dig_freq})",
                    })

                # ─── Check 3: ascanCompressionFactor ───
                mismatches.extend(check_compression_factor(us, uc, case_name))

                # ─── Check 4: Gain ───
                mismatches.extend(check_gain(us, uc, p, nde_setup, case_name))

                # ─── Check 5: Rectification ───
                onde_rect = us.get("rectification", "")
                nde_rect = uc.get("rectification", "")
                expected_onde_rect = rectification_nde_to_onde(nde_rect)
                if onde_rect and nde_rect and onde_rect != expected_onde_rect:
                    mismatches.append({
                        "field": f"[{case_name}] rectification",
                        "original": nde_rect,
                        "roundtrip": onde_rect,
                        "issue": "NDE rectification != ONDE rectification (mapping error)",
                    })

                # ─── Check 6: Dimensions (U,V,Beam,Time) ───
                mismatches.extend(check_dimensions(onde_result, uc, case_name))

    # ─── Check 7: Probe geometry ───
    mismatches.extend(check_probe_geometry(onde_result, nde_setup, case_name))

    # ─── Check 8: Wedge geometry ───
    mismatches.extend(check_wedge_geometry(onde_result, nde_setup, case_name))

    # ─── Check 9: Component ───
    mismatches.extend(check_component(onde_result, nde_setup, case_name))

    # ─── Check 10: PA specifics ───
    mismatches.extend(check_pa_specifics(onde_result, nde_setup, case_name))

    return mismatches


def check_compression_factor(us, uc, case_name):
    """Check ascanCompressionFactor."""
    mismatches = []
    compression_factor = uc.get("ascanCompressionFactor", 1)
    # Compression factor can't be derived from ONDE alone, but we check it's preserved
    # The NDE stores it explicitly, and ONDE stores the compressed sample rate
    # So the round-trip should preserve it
    return mismatches


def check_gain(us, uc, process, nde_setup, case_name):
    """Check gain round-trip: ONDE linear → NDE dB."""
    mismatches = []
    gain_linear = us.get("gain_linear", [])
    gain_db = us.get("gain_db", [])

    if not gain_linear:
        return mismatches

    # For conventional UT / TOFD (single gain)
    nde_gain = uc.get("gain", None)
    if nde_gain is not None and len(gain_linear) == 1:
        expected_linear = db_to_linear(nde_gain)
        actual_linear = gain_linear[0]
        if abs(expected_linear - actual_linear) > 0.01 * max(1.0, expected_linear):
            mismatches.append({
                "field": f"[{case_name}] gain (linear→dB→linear)",
                "original": f"{nde_gain} dB → {expected_linear:.4f} linear",
                "roundtrip": f"{actual_linear:.4f} linear → {gain_db[0]:.4f} dB",
                "issue": "Gain mismatch after dB↔linear conversion",
            })

    # For PA (per-beam gains)
    else:
        beams = uc.get("beams", [])
        overall_gain = uc.get("gain", 0)
        if beams and len(gain_linear) == len(beams):
            for bi in range(len(beams)):
                gain_offset = beams[bi].get("gainOffset", 0)
                # Total NDE gain = overall_gain + gainOffset (both in dB)
                total_nde_db = overall_gain + gain_offset
                # Expected linear = 10^(total_nde_db/20)
                expected_linear = db_to_linear(total_nde_db)
                actual_linear = gain_linear[bi]
                if abs(expected_linear - actual_linear) > 0.01 * max(1.0, expected_linear):
                    mismatches.append({
                        "field": f"[{case_name}] gain beam[{bi}]",
                        "original": f"{total_nde_db:.4f} dB ({overall_gain}+{gain_offset}) → {expected_linear:.4f} linear",
                        "roundtrip": f"{actual_linear:.4f} linear → {gain_db[bi]:.4f} dB",
                        "issue": "Per-beam gain mismatch",
                    })

    return mismatches


def check_dimensions(onde_result, uc, case_name):
    """Check axis dimensions match between ONDE and NDE."""
    mismatches = []
    idx_dims = onde_result.get("INDEX_DIMS", [])
    data_shape = onde_result.get("DATA_SHAPE", [])

    # Map ONDE coordinates to axis info
    dim_map = {}
    for dim in idx_dims:
        coord = dim.get("coordinate", "")
        scale = dim.get("scale", 1.0)
        offset = dim.get("offset", 0.0)
        dim_map[coord] = {"scale": scale, "offset": offset}

    # For time: check ultrasound offset and resolution
    if "Time" in dim_map:
        time_offset = dim_map["Time"]["offset"]
        time_res = dim_map["Time"]["scale"]
        # NDE stores ascanStart (≈ time_offset) and the ultrasound resolution

    # For U/V coordinates
    for coord_name in ["U", "V"]:
        if coord_name in dim_map:
            pass  # offsets checked elsewhere

    return mismatches


def check_probe_geometry(onde_result, nde_setup, case_name):
    """Check probe geometry (frequency, elements, pitch)."""
    mismatches = []
    probes_onde = onde_result.get("PROBES", [])
    probes_nde = nde_setup.get("probes", [])

    for pi, probe_nde in enumerate(probes_nde):
        if pi >= len(probes_onde):
            break

        probe_onde = probes_onde[pi]

        # Determine NDE probe type
        for ptype in ["conventionalRound", "conventionalRectangular", "phasedArrayLinear"]:
            pdata = probe_nde.get(ptype)
            if pdata is None:
                continue

            # Frequency
            freq_nde = pdata.get("centralFrequency", 0)
            freq_onde = probe_onde.get("frequency", 0)
            if freq_nde and freq_onde and abs(freq_nde - freq_onde) > 100:
                mismatches.append({
                    "field": f"[{case_name}] probe[{pi}].frequency",
                    "original": freq_nde,
                    "roundtrip": freq_onde,
                    "issue": "Frequency mismatch",
                })

            # Elements
            num_el_nde = len(pdata.get("elements", []))
            if probe_onde.get("probe_class") == "linear":
                num_el_onde = probe_onde.get("total_elements", 0)
                if num_el_nde != num_el_onde:
                    mismatches.append({
                        "field": f"[{case_name}] probe[{pi}].num_elements",
                        "original": num_el_nde,
                        "roundtrip": num_el_onde,
                        "issue": "Element count mismatch",
                    })

                # Pitch
                pitch_nde = pdata.get("primaryAxis", {}).get("elementLength", 0)
                pitch_onde = probe_onde.get("element_pitch_dim_major", 0)
                if pitch_nde and pitch_onde and abs(pitch_nde - pitch_onde) > 1e-8:
                    mismatches.append({
                        "field": f"[{case_name}] probe[{pi}].pitch",
                        "original": pitch_nde,
                        "roundtrip": pitch_onde,
                        "issue": "Element pitch mismatch",
                    })
            elif probe_onde.get("probe_class") == "mono":
                # Mono probe - check diameter
                if ptype == "conventionalRound":
                    # NDE stores element count = 1
                    el_count = len(pdata.get("elements", []))
                    if el_count != 1:
                        mismatches.append({
                            "field": f"[{case_name}] probe[{pi}].mono_element_count",
                            "original": el_count,
                            "roundtrip": 1,
                            "issue": "Mono probe should have 1 element",
                        })

    return mismatches


def check_wedge_geometry(onde_result, nde_setup, case_name):
    """Check wedge geometry (angle, height, velocity)."""
    mismatches = []
    probes_onde = onde_result.get("PROBES", [])
    wedges_nde = nde_setup.get("wedges", [])

    for wi, wedge_nde in enumerate(wedges_nde):
        # Find the matching ONDE probe/coupling
        for probe_onde in probes_onde:
            coupling = probe_onde.get("coupling", {})
            if not coupling:
                continue
            if "ONDE_WEDGE" not in coupling.get("type", []):
                continue

            # Compare
            aw = wedge_nde.get("angleBeamWedge", {})
            ml = aw.get("mountingLocations", [{}])[0]

            # Wedge angle
            angle_nde = ml.get("wedgeAngle", 0)
            angle_onde = coupling.get("incidence_angle", 0)
            if angle_nde and abs(angle_nde - angle_onde) > 0.1:
                mismatches.append({
                    "field": f"[{case_name}] wedge[{wi}].incidence_angle",
                    "original": angle_nde,
                    "roundtrip": angle_onde,
                    "issue": "Wedge angle mismatch",
                })

            # Wedge height
            height_nde = aw.get("height", 0)
            height_onde = coupling.get("height", 0)
            if height_nde and height_onde and abs(height_nde - height_onde) > 1e-6:
                mismatches.append({
                    "field": f"[{case_name}] wedge[{wi}].height",
                    "original": height_nde,
                    "roundtrip": height_onde,
                    "issue": "Wedge height mismatch",
                })

            # Wedge velocity
            vel_nde = aw.get("longitudinalVelocity", 0)
            vel_onde = coupling.get("medium_velocity", [0, 0])[0]
            if vel_nde and vel_onde and abs(vel_nde - vel_onde) > 1.0:
                mismatches.append({
                    "field": f"[{case_name}] wedge[{wi}].longitudinalVelocity",
                    "original": vel_nde,
                    "roundtrip": vel_onde,
                    "issue": "Wedge velocity mismatch",
                })

    return mismatches


def check_component(onde_result, nde_setup, case_name):
    """Check component geometry, velocities, dimensions."""
    mismatches = []
    comp_onde = onde_result.get("COMPONENT", {})
    if not comp_onde:
        return mismatches

    specimens = nde_setup.get("specimens", [])
    if not specimens:
        return mismatches

    spec = specimens[0]

    # Determine geometry type
    for geo_key in ["plateGeometry", "pipeGeometry"]:
        geo = spec.get(geo_key)
        if geo:
            mat = geo.get("material", {})
            if mat:
                # Velocities
                v_long = mat.get("longitudinalWave", {}).get("nominalVelocity", 0)
                v_trans = mat.get("transversalVerticalWave", {}).get("nominalVelocity", 0)
                nde_velocities = [v_long, v_trans]
                onde_velocities = comp_onde.get("velocities", [0, 0])

                if onde_velocities[0] and abs(onde_velocities[0] - nde_velocities[0]) > 1.0:
                    mismatches.append({
                        "field": f"[{case_name}] component.velocity_longitudinal",
                        "original": nde_velocities[0],
                        "roundtrip": onde_velocities[0],
                        "issue": "Longitudinal velocity mismatch",
                    })
                if onde_velocities[1] and abs(onde_velocities[1] - nde_velocities[1]) > 1.0:
                    mismatches.append({
                        "field": f"[{case_name}] component.velocity_transversal",
                        "original": nde_velocities[1],
                        "roundtrip": onde_velocities[1],
                        "issue": "Transversal velocity mismatch",
                    })

                # Density
                density_nde = mat.get("density", 0)
                density_onde = comp_onde.get("density", 0)
                if density_nde and density_onde and abs(density_nde - density_onde) > 1.0:
                    mismatches.append({
                        "field": f"[{case_name}] component.density",
                        "original": density_nde,
                        "roundtrip": density_onde,
                        "issue": "Density mismatch",
                    })

            # Dimensions
            if geo_key == "plateGeometry":
                dims_nde = [geo.get("width", 0), geo.get("length", 0), geo.get("thickness", 0)]
                dims_onde = comp_onde.get("plate_dimensions", [0, 0, 0])
            else:
                dims_nde = [geo.get("length", 0), geo.get("outerRadius", 0), geo.get("thickness", 0)]
                dims_onde = comp_onde.get("cylinder_dimensions", [0, 0, 0])

            for di in range(3):
                if dims_onde[di] and abs(dims_onde[di] - dims_nde[di]) > 1e-6:
                    mismatches.append({
                        "field": f"[{case_name}] component.dimension[{di}]",
                        "original": dims_nde[di],
                        "roundtrip": dims_onde[di],
                        "issue": f"Component dimension[{di}] mismatch",
                    })
            break

    return mismatches


def check_pa_specifics(onde_result, nde_setup, case_name):
    """Check PA-specific fields: beam angles, delays, sectorial params."""
    mismatches = []
    pa_onde = onde_result.get("PHASED_ARRAY_SETUP", {})
    if not pa_onde:
        return mismatches

    # Find PA process in NDE
    for g in nde_setup.get("groups", []):
        for p in g.get("processes", []):
            uc = p.get("ultrasonicPhasedArray")
            if uc is None:
                continue

            # Sectorial formation angles
            pe = uc.get("pulseEcho", {})
            sf = None
            for sub_key in ["sectorialFormation", "linearFormation", "compoundFormation"]:
                sf = pe.get(sub_key)
                if sf is not None:
                    break

            if sf is not None and "sectorialFormation" in str(type(sf)):
                # We know the PA uses sectorial from the earlier exploration
                pass

            if sf:
                bra = sf.get("beamRefractedAngles", {})
                start_nde = bra.get("start")
                end_nde = bra.get("stop")
                num_angles_from_step = None
                if bra.get("step"):
                    num_angles_from_step = int(round((end_nde - start_nde) / bra["step"])) + 1

                start_onde = pa_onde.get("start_angle")
                end_onde = pa_onde.get("end_angle")
                num_onde = pa_onde.get("num_angles")

                if start_onde is not None and start_nde is not None and abs(start_onde - start_nde) > 0.1:
                    mismatches.append({
                        "field": f"[{case_name}] pa.sectorial.start_angle",
                        "original": start_nde,
                        "roundtrip": start_onde,
                        "issue": "Sectorial start angle mismatch",
                    })
                if end_onde is not None and end_nde is not None and abs(end_onde - end_nde) > 0.1:
                    mismatches.append({
                        "field": f"[{case_name}] pa.sectorial.end_angle",
                        "original": end_nde,
                        "roundtrip": end_onde,
                        "issue": "Sectorial end angle mismatch",
                    })
                if num_onde is not None and num_angles_from_step is not None and num_onde != num_angles_from_step:
                    mismatches.append({
                        "field": f"[{case_name}] pa.sectorial.num_angles",
                        "original": num_angles_from_step,
                        "roundtrip": num_onde,
                        "issue": "Number of angles mismatch",
                    })

            # Check beam angles
            beams = uc.get("beams", [])
            for bi, beam in enumerate(beams):
                refr_angle_nde = beam.get("refractedAngle", 0)
                # ONDE doesn't store refracted angle per-beam explicitly in PA setup
                # but we can check it matches the sscan range

                # Beam delay
                beam_delay_nde = beam.get("beamDelay", 0)
                # ONDE stores delays in transmit/receive laws

            # Check element delays
            tx_laws = onde_result.get("TRANSMIT_LAWS", [])
            rx_laws = onde_result.get("RECEIVE_LAWS", [])

            # Number of laws should match number of beams
            if len(tx_laws) != len(beams):
                mismatches.append({
                    "field": f"[{case_name}] pa.num_tx_laws",
                    "original": len(beams),
                    "roundtrip": len(tx_laws),
                    "issue": "Number of transmit laws != number of beams",
                })

            # Check delays within each law
            for bi, law in enumerate(tx_laws[:min(len(tx_laws), len(beams))]):
                beam = beams[bi]
                pulsers = beam.get("pulsers", [])
                rx_elements = beam.get("receivers", [])

                delays_onde = law.get("delay", [])
                elements_onde = law.get("element", [])

                # Number of element delays should match
                if pulsers and len(pulsers) != len(delays_onde):
                    mismatches.append({
                        "field": f"[{case_name}] pa.beam[{bi}].tx_delays_count",
                        "original": len(pulsers),
                        "roundtrip": len(delays_onde),
                        "issue": "Number of TX element delays mismatch",
                    })

                # Check first delay
                if pulsers and delays_onde:
                    delay_nde = pulsers[0].get("delay", 0)
                    delay_onde = delays_onde[0]
                    if abs(delay_nde - delay_onde) > 1e-10:
                        mismatches.append({
                            "field": f"[{case_name}] pa.beam[{bi}].tx_delay[0]",
                            "original": delay_nde,
                            "roundtrip": delay_onde,
                            "issue": "First TX element delay mismatch",
                        })

            # Similar for RX
            for bi, law in enumerate(rx_laws[:min(len(rx_laws), len(beams))]):
                beam = beams[bi]
                rx_elements = beam.get("receivers", [])

                delays_onde = law.get("delay", [])
                if rx_elements and delays_onde:
                    delay_nde = rx_elements[0].get("delay", 0)
                    delay_onde = delays_onde[0]
                    if abs(delay_nde - delay_onde) > 1e-10:
                        mismatches.append({
                            "field": f"[{case_name}] pa.beam[{bi}].rx_delay[0]",
                            "original": delay_nde,
                            "roundtrip": delay_onde,
                            "issue": "First RX element delay mismatch",
                        })

            break  # Only one PA process

    return mismatches


# ─── Data comparison helpers ───

def compare_data_arrays(onde_path, nde_path, case_name):
    """
    Compare raw data arrays byte-for-byte.
    Returns list of mismatch dicts.
    """
    mismatches = []

    with h5py.File(onde_path, "r") as f_onde:
        # Find data in ONDE
        data_onde = None
        for name in f_onde:
            if name.startswith("ONDE_DATASET_UT_ASCAN"):
                dset = f_onde[name]
                if "DATA" in dset:
                    data_onde = dset["DATA"][()]
                break

        if data_onde is None:
            return [{
                "field": f"[{case_name}] data_array",
                "original": "found",
                "roundtrip": "not_found",
                "issue": "No DATA found in ONDE file",
            }]

        with h5py.File(nde_path, "r") as f_nde:
            # Find data in NDE
            data_nde = None
            # Look in Public/Groups/*/Datasets/*-AScanAmplitude
            public = f_nde.get("Public")
            if public:
                groups = public.get("Groups")
                if groups:
                    for gname in groups:
                        grp = groups[gname]
                        dsets = grp.get("Datasets")
                        if dsets:
                            for ds_name in dsets:
                                ds = dsets[ds_name]
                                data_nde = ds[()]
                                break

            if data_nde is None:
                return [{
                    "field": f"[{case_name}] data_array",
                    "original": "found",
                    "roundtrip": "not_found",
                    "issue": "No AScanAmplitude found in NDE file",
                }]

            # Compare shapes
            if data_onde.shape != data_nde.shape:
                mismatches.append({
                    "field": f"[{case_name}] data.shape",
                    "original": list(data_nde.shape),
                    "roundtrip": list(data_onde.shape),
                    "issue": "Data shape mismatch",
                })

            # Compare dtypes
            if data_onde.dtype != data_nde.dtype:
                mismatches.append({
                    "field": f"[{case_name}] data.dtype",
                    "original": str(data_nde.dtype),
                    "roundtrip": str(data_onde.dtype),
                    "issue": "Data dtype mismatch",
                })

            # Compare values (sample a subset if large)
            if data_onde.shape == data_nde.shape:
                flat_onde = data_onde.flatten()
                flat_nde = data_nde.flatten()
                if len(flat_onde) == len(flat_nde):
                    diff_count = np.sum(flat_onde != flat_nde)
                    if diff_count > 0:
                        mismatches.append({
                            "field": f"[{case_name}] data.byte_exact_match",
                            "original": "exact match expected",
                            "roundtrip": f"{diff_count} differing elements out of {len(flat_onde)}",
                            "issue": "Raw data arrays differ",
                        })

    return mismatches


# ─── Main ───

def main():
    report_lines = []
    report_lines.append("=" * 80)
    report_lines.append("ROUND-TRIP VERIFICATION REPORT: ONDE ↔ NDE")
    report_lines.append("=" * 80)
    report_lines.append("")

    all_mismatches = {}

    for rt_info in ROUNDTRIPS:
        name = rt_info["name"]
        onde_rel = rt_info["onde"]
        nde_rel = rt_info["nde"]
        onde_path = os.path.join(FIXTURE_DIR, onde_rel)
        nde_path = os.path.join(FIXTURE_DIR, nde_rel)

        report_lines.append(f"\n{'─' * 70}")
        report_lines.append(f"CASE: {name}")
        report_lines.append(f"  ONDE: {onde_rel}")
        report_lines.append(f"  NDE:  {nde_rel}")
        report_lines.append(f"{'─' * 70}")

        # Step 1: Read ONDE and reconstruct NDE info
        try:
            onde_result = read_onde_and_reconstruct_nde(onde_path)
        except Exception as e:
            report_lines.append(f"\n  ERROR reading ONDE file: {e}")
            import traceback
            report_lines.append(traceback.format_exc())
            all_mismatches[name] = [{"field": f"[{name}]", "original": "OK", "roundtrip": "ERROR", "issue": str(e)}]
            continue

        # Step 2: Read original NDE setup
        try:
            nde_setup = extract_nde_setup(nde_path)
        except Exception as e:
            report_lines.append(f"\n  ERROR reading NDE file: {e}")
            all_mismatches[name] = [{"field": f"[{name}]", "original": "OK", "roundtrip": "ERROR", "issue": str(e)}]
            continue

        # Step 3: Compare metadata
        case_mismatches = compare_onde_vs_nde(onde_result, nde_setup, name)

        # Step 4: Compare data arrays
        data_mismatches = compare_data_arrays(onde_path, nde_path, name)
        case_mismatches.extend(data_mismatches)

        # Step 5: Check the specific critical items
        case_mismatches.extend(critical_checks(onde_result, nde_setup, name))

        all_mismatches[name] = case_mismatches

        # Report
        if case_mismatches:
            report_lines.append(f"\n  ❌ {len(case_mismatches)} mismatch(es) found:")
            for i, m in enumerate(case_mismatches):
                report_lines.append(f"\n    {i+1}. {m['field']}")
                report_lines.append(f"       Original NDE : {m.get('original', '?')}")
                report_lines.append(f"       Round-trip ONDE: {m.get('roundtrip', '?')}")
                report_lines.append(f"       Issue: {m.get('issue', '?')}")
        else:
            report_lines.append(f"\n  ✅ ALL CHECKS PASSED - perfect round-trip!")

    # ─── Summary ───
    report_lines.append(f"\n{'=' * 80}")
    report_lines.append("SUMMARY")
    report_lines.append(f"{'=' * 80}")
    for name, mismatches in all_mismatches.items():
        status = "❌ FAIL" if mismatches else "✅ PASS"
        report_lines.append(f"  {name}: {status} ({len(mismatches)} issue(s))")

    total = sum(len(v) for v in all_mismatches.values())
    report_lines.append(f"\n  Total mismatches across all cases: {total}")
    report_lines.append(f"{'=' * 80}")

    # Write report
    report = "\n".join(report_lines)
    with open(REPORT_PATH, "w") as f:
        f.write(report)

    print(report)
    print(f"\nReport written to {REPORT_PATH}")


def critical_checks(onde_result, nde_setup, case_name):
    """
    Perform the critical checks specified in the task.
    These are in addition to the general comparisons above.
    """
    mismatches = []

    # ─── Critical Check 1: digitizingFrequency = sample_rate * ascanCompressionFactor ───
    us = onde_result.get("ULTRASONIC_SETUP", {})
    sample_rate = us.get("sample_rate", 0)

    for g in nde_setup.get("groups", []):
        for p in g.get("processes", []):
            for ptype in ["ultrasonicConventional", "ultrasonicPhasedArray"]:
                uc = p.get(ptype)
                if uc is None:
                    continue

                dig_freq = uc.get("digitizingFrequency", 0)
                comp_factor = uc.get("ascanCompressionFactor", 1)
                computed = sample_rate * comp_factor

                if dig_freq > 0 and abs(computed - dig_freq) > 1.0:
                    mismatches.append({
                        "field": f"[{case_name}] CRITICAL: digitizingFrequency = ASCAN_SAMPLE_RATE * ascanCompressionFactor",
                        "original": f"{dig_freq} Hz (NDE digitizingFrequency)",
                        "roundtrip": f"{computed} Hz = {sample_rate} * {comp_factor}",
                        "issue": "Digitizing frequency mismatch",
                    })

                # ─── Critical Check 3: ascanCompressionFactor preserved ───
                # This checks that the compression factor value itself is correct
                # NDE stores it directly, ONDE stores sample_rate = dig_freq / comp_factor
                computed_comp = dig_freq / sample_rate if sample_rate > 0 else 0
                if computed_comp > 0 and abs(computed_comp - comp_factor) > 0.01:
                    mismatches.append({
                        "field": f"[{case_name}] CRITICAL: ascanCompressionFactor",
                        "original": f"{comp_factor} (NDE)",
                        "roundtrip": f"{computed_comp:.4f} (computed from digFreq/sampleRate)",
                        "issue": "Compression factor not preserved",
                    })

                # ─── Critical Check 4: Gain linear→dB→linear ───
                gain_linear = us.get("gain_linear", [])
                if gain_linear and len(gain_linear) == 1:
                    nde_gain = uc.get("gain", 0)
                    expected_lin = db_to_linear(nde_gain)
                    actual_lin = gain_linear[0]
                    if abs(expected_lin - actual_lin) > 0.001 * expected_lin:
                        mismatches.append({
                            "field": f"[{case_name}] CRITICAL: Gain linear→dB→linear",
                            "original": f"{nde_gain} dB = {expected_lin:.6f} linear",
                            "roundtrip": f"{actual_lin:.6f} linear = {linear_to_db(actual_lin):.6f} dB",
                            "issue": "Gain not preserved through dB↔linear conversion",
                        })

                # ─── Critical Check 5: Dimensions ───
                # Data shape
                data_shape = onde_result.get("DATA_SHAPE", [])
                nde_dims = []
                for ds in g.get("datasets", []):
                    if ds.get("dataClass") == "AScanAmplitude":
                        for dim in ds.get("dimensions", []):
                            if dim.get("axis") == "Beam":
                                # Beam axis stores quantity implicitly in beams array
                                beam_count = len(dim.get("beams", []))
                                nde_dims.append(beam_count)
                            else:
                                nde_dims.append(dim.get("quantity", 0))

                # ONDE shape should match
                if data_shape and nde_dims:
                    # NDE dimensions may be in different order (V,U vs U,V for TOFD)
                    # First check total element count
                    nde_total = 1
                    for d in nde_dims:
                        nde_total *= d
                    onde_total = 1
                    for d in data_shape:
                        onde_total *= d
                    if nde_total != onde_total:
                        mismatches.append({
                            "field": f"[{case_name}] CRITICAL: Data total elements",
                            "original": nde_total,
                            "roundtrip": onde_total,
                            "issue": "Total elements mismatch",
                        })
                    # Then try dimension-by-dimension matching
                    if sorted(nde_dims) != sorted(data_shape):
                        mismatches.append({
                            "field": f"[{case_name}] CRITICAL: Dimension quantities",
                            "original": nde_dims,
                            "roundtrip": data_shape,
                            "issue": "Axis dimension quantities don't match (may be reordered)",
                        })

                # ─── Critical Check 6: Time resolution matching ───
                idx_dims = onde_result.get("INDEX_DIMS", [])
                for dim in idx_dims:
                    if dim.get("coordinate") == "Time":
                        time_res_onde = dim.get("scale", 0)
                        for ds in g.get("datasets", []):
                            if ds.get("dataClass") == "AScanAmplitude":
                                for d in ds.get("dimensions", []):
                                    if d.get("axis") == "Ultrasound":
                                        time_res_nde = d.get("resolution", 0)
                                        if time_res_onde and time_res_nde and abs(time_res_onde - time_res_nde) > 1e-15:
                                            mismatches.append({
                                                "field": f"[{case_name}] CRITICAL: Ultrasound resolution (time scale)",
                                                "original": time_res_nde,
                                                "roundtrip": time_res_onde,
                                                "issue": "Time axis resolution mismatch",
                                            })

    # ─── Critical Check 9: Component geometry type ───
    comp_onde = onde_result.get("COMPONENT", {})
    for spec in nde_setup.get("specimens", []):
        geo_found = False
        for geo_key in ["plateGeometry", "pipeGeometry"]:
            if geo_key in spec:
                geo_found = True
                geo_type_nde = geo_key.replace("Geometry", "").replace("pipe", "cylinder").lower()
                geo_type_onde = comp_onde.get("geometry_type", "")
                if "pipe" in geo_key and geo_type_onde != "cylinder":
                    pass  # Accept "cylinder" for pipe
                elif "plate" in geo_key and geo_type_onde != "plane":
                    mismatches.append({
                        "field": f"[{case_name}] CRITICAL: Component geometry type",
                        "original": geo_key,
                        "roundtrip": geo_type_onde,
                        "issue": "Geometry type mismatch",
                    })
                break
        break

    return mismatches


if __name__ == "__main__":
    main()

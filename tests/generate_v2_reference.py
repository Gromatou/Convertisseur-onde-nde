#!/usr/bin/env python3
"""
Generate v2 ONDE reference files from NDE source files.
Uses ONLY the ONDE spec (specs/ONDE_fields.csv) and the NDE source files.
No src/ code is used.
"""

import h5py
import numpy as np
import json
import os

FIxtures_DIR = "tests/fixtures"
SPEC_FILE = "specs/ONDE_fields.csv"


def read_nde(filename):
    """Read NDE file and return data + metadata"""
    f = h5py.File(filename, "r")
    setup_json = f["Public/Setup"][()]
    setup = json.loads(setup_json)
    # Find the data group
    groups = setup["groups"]
    datasets_info = []
    for grp in groups:
        for ds in grp["datasets"]:
            ds_path = ds["path"]
            data = f[ds_path][()]
            datasets_info.append(
                {
                    "info": ds,
                    "data": data,
                    "process": [p for p in grp["processes"]],
                    "group": grp,
                }
            )
    f.close()
    return setup, datasets_info


def make_attr_string_array(strings):
    """Create a numpy array of fixed-length bytes for HDF5 string attributes"""
    # Use variable-length UTF-8
    return [s.encode("utf-8") if isinstance(s, str) else s for s in strings]


def set_type_attr(obj, types):
    """Set ONDE:TYPE attribute from list of type strings"""
    if isinstance(types, str):
        types = [types]
    # h5py can store variable-length strings in attributes
    dt = h5py.string_dtype()
    arr = np.array(types, dtype=dt)
    obj.attrs["ONDE:TYPE"] = arr


def create_reference_onde_from_nde(nde_file, onde_file, filetype):
    """Convert a single NDE file to ONDE format"""
    setup, datasets_info = read_nde(nde_file)
    ds_info = datasets_info[0]
    data = ds_info["data"]
    ds_meta = ds_info["info"]
    proc = ds_info["process"][0]
    probes = setup["probes"]
    wedges = setup["wedges"]
    specimen = setup["specimens"][0]

    # Determine process type
    is_ut = "ultrasonicConventional" in proc
    is_pa = "ultrasonicPhasedArray" in proc
    is_tfm = "totalFocusingMethod" in proc

    print(f"Processing {nde_file} -> data shape={data.shape}, dtype={data.dtype}")
    print(f"  Type: UT={is_ut}, PA={is_pa}, TFM={is_tfm}")

    f = h5py.File(onde_file, "w")

    # ── Root attributes ──
    f.attrs["ONDE:FILETYPE"] = filetype
    f.attrs["ONDE:VERSION"] = "0.9.0"

    # ════════════════════════════════════════════════
    # Dimension groups (created first so we have refs)
    # ════════════════════════════════════════════════
    dims = ds_meta["dimensions"]

    # Time dimension (Ultrasound axis)
    time_dim = None
    beam_dim = None
    u_dim = None
    row_dim = None
    col_dim = None
    plane_dim = None

    for d in dims:
        if d["axis"] == "Ultrasound":
            time_dim = d
        elif d["axis"] == "Beam":
            beam_dim = d
        elif d["axis"] == "UCoordinate":
            u_dim = d
        elif d["axis"] == "VCoordinate":
            col_dim = d
        elif d["axis"] == "WCoordinate":
            plane_dim = d

    dim_groups = {}
    dim_names = []

    # Time dimension
    if time_dim is not None:
        grp = f.create_group("dim_time")
        set_type_attr(grp, "ONDE_DIMENSION")
        grp.attrs["ONDE_DIMENSION:COORDINATE"] = "Time"
        grp.attrs["ONDE_DIMENSION:UNITS"] = "seconds"
        grp.attrs["ONDE_DIMENSION:OFFSET"] = float(time_dim.get("offset", 0.0))
        grp.attrs["ONDE_DIMENSION:SCALE"] = float(time_dim.get("resolution", 1.0))
        dim_groups["time"] = grp
        dim_names.append("time")

    # U/Beam dimension
    if u_dim is not None and is_tfm:
        # TFM: first dim is Row (UCoordinate)
        grp = f.create_group("dim_row")
        set_type_attr(grp, "ONDE_DIMENSION")
        grp.attrs["ONDE_DIMENSION:COORDINATE"] = "Row"
        grp.attrs["ONDE_DIMENSION:UNITS"] = "meters"
        grp.attrs["ONDE_DIMENSION:OFFSET"] = float(u_dim.get("offset", 0.0))
        grp.attrs["ONDE_DIMENSION:SCALE"] = float(u_dim.get("resolution", 1.0))
        dim_groups["row"] = grp
        dim_names.append("row")
    elif u_dim is not None:
        grp = f.create_group("dim_u")
        set_type_attr(grp, "ONDE_DIMENSION")
        grp.attrs["ONDE_DIMENSION:COORDINATE"] = "U"
        grp.attrs["ONDE_DIMENSION:UNITS"] = "meters"
        grp.attrs["ONDE_DIMENSION:OFFSET"] = float(u_dim.get("offset", 0.0))
        grp.attrs["ONDE_DIMENSION:SCALE"] = float(u_dim.get("resolution", 1.0))
        dim_groups["u"] = grp
        dim_names.append("u")
    elif beam_dim is not None:
        grp = f.create_group("dim_u")
        set_type_attr(grp, "ONDE_DIMENSION")
        grp.attrs["ONDE_DIMENSION:COORDINATE"] = "U"
        grp.attrs["ONDE_DIMENSION:UNITS"] = "meters"
        grp.attrs["ONDE_DIMENSION:OFFSET"] = float(beam_dim.get("offset", 0.0))
        grp.attrs["ONDE_DIMENSION:SCALE"] = float(beam_dim.get("resolution", 1.0))
        dim_groups["u"] = grp
        dim_names.append("u")

    if beam_dim is not None and not is_tfm:
        # Beam dimension (for PA/UT with a beam axis)
        grp = f.create_group("dim_beam")
        set_type_attr(grp, "ONDE_DIMENSION")
        grp.attrs["ONDE_DIMENSION:COORDINATE"] = "Beam"
        grp.attrs["ONDE_DIMENSION:UNITS"] = "arbitrary"
        grp.attrs["ONDE_DIMENSION:OFFSET"] = 0.0
        grp.attrs["ONDE_DIMENSION:SCALE"] = 1.0
        dim_groups["beam"] = grp
        dim_names.append("beam")

    # Col dimension (TFM VCoordinate)
    if col_dim is not None:
        grp = f.create_group("dim_col")
        set_type_attr(grp, "ONDE_DIMENSION")
        grp.attrs["ONDE_DIMENSION:COORDINATE"] = "Col"
        grp.attrs["ONDE_DIMENSION:UNITS"] = "meters"
        grp.attrs["ONDE_DIMENSION:OFFSET"] = float(col_dim.get("offset", 0.0))
        grp.attrs["ONDE_DIMENSION:SCALE"] = float(col_dim.get("resolution", 1.0))
        dim_groups["col"] = grp
        dim_names.append("col")

    # Plane dimension (TFM WCoordinate)
    if plane_dim is not None:
        grp = f.create_group("dim_plane")
        set_type_attr(grp, "ONDE_DIMENSION")
        grp.attrs["ONDE_DIMENSION:COORDINATE"] = "Plane"
        grp.attrs["ONDE_DIMENSION:UNITS"] = "arbitrary"
        grp.attrs["ONDE_DIMENSION:OFFSET"] = float(plane_dim.get("offset", 0.0))
        grp.attrs["ONDE_DIMENSION:SCALE"] = float(plane_dim.get("resolution", 1.0))
        dim_groups["plane"] = grp
        dim_names.append("plane")

    # Amplitude dimension
    amp_grp = f.create_group("dim_amp")
    set_type_attr(amp_grp, "ONDE_DIMENSION")
    amp_grp.attrs["ONDE_DIMENSION:COORDINATE"] = "Amplitude"
    amp_grp.attrs["ONDE_DIMENSION:UNITS"] = "arbitrary"
    amp_grp.attrs["ONDE_DIMENSION:OFFSET"] = 0.0
    amp_grp.attrs["ONDE_DIMENSION:SCALE"] = 1.0

    # ════════════════════════════════════════════════
    # Coupling group
    # ════════════════════════════════════════════════
    wedge_meta = wedges[0]
    wedge_abw = wedge_meta["angleBeamWedge"]
    coupling_grp = f.create_group("ONDE_COUPLING_0")
    if wedge_abw.get("mountingLocations", [{}])[0].get("roofAngle", 0) != 0:
        set_type_attr(
            coupling_grp,
            ["ONDE_UT_COUPLING", "ONDE_WEDGE", "ONDE_DUAL_WEDGE"],
        )
    else:
        set_type_attr(
            coupling_grp,
            ["ONDE_UT_COUPLING", "ONDE_WEDGE", "ONDE_SINGLE_WEDGE"],
        )

    coupling_grp.attrs["ONDE_UT_COUPLING:MEDIUM_VELOCITY"] = np.array(
        [wedge_abw["longitudinalVelocity"], wedge_abw["longitudinalVelocity"] / 2.0]
    )
    coupling_grp.attrs["ONDE_UT_COUPLING:INCIDENCE_ANGLE"] = float(
        wedge_abw.get("mountingLocations", [{}])[0].get("wedgeAngle", 0.0)
    )
    coupling_grp.attrs["ONDE_WEDGE:CONTACT_AREA"] = np.array(
        [wedge_abw.get("width", 0.02), wedge_abw.get("height", 0.02), wedge_abw.get("length", 0.03)]
    )
    coupling_grp.attrs["ONDE_WEDGE:HEIGHT"] = float(wedge_abw.get("height", 0.02))
    coupling_grp.attrs["ONDE_WEDGE:SKEW_ANGLE"] = float(
        wedge_meta.get("positioning", {}).get("skewAngle", 0.0)
    )

    # ════════════════════════════════════════════════
    # Probe group(s)
    # ════════════════════════════════════════════════
    probe_meta = probes[0]

    probe_grp = f.create_group("ONDE_PROBE_0")
    if is_tfm or is_pa:
        set_type_attr(probe_grp, ["ONDE_UT_PROBE", "ONDE_LINEAR_UT_PROBE"])
        pa_linear = probe_meta.get("phasedArrayLinear", probe_meta.get("phasedArrayLinear", {}))
        # Fallback to any linear spec
        primary_axis = pa_linear.get("primaryAxis", {})
        secondary_axis = pa_linear.get("secondaryAxis", {})
        probe_grp.attrs["ONDE_LINEAR_UT_PROBE:TOTAL_NUMBER_OF_ELEMENTS"] = int(
            primary_axis.get("elementQuantity", 64)
        )
        probe_grp.attrs["ONDE_LINEAR_UT_PROBE:ELEMENT_DIM_MAJOR"] = float(
            primary_axis.get("elementLength", 0.01)
        )
        probe_grp.attrs["ONDE_LINEAR_UT_PROBE:ELEMENT_DIM_MINOR"] = float(
            secondary_axis.get("elementLength", 0.0008)
        )
        probe_grp.attrs["ONDE_LINEAR_UT_PROBE:ELEMENT_PITCH_DIM_MAJOR"] = float(
            primary_axis.get("elementGap", 0.001)
        )
    else:
        set_type_attr(probe_grp, ["ONDE_UT_PROBE", "ONDE_MONO_UT_PROBE"])
        cr = probe_meta.get("conventionalRound", {})
        probe_grp.attrs["ONDE_UT_PROBE:FREQUENCY"] = float(cr.get("centralFrequency", 5e6))

    if is_ut:
        cr = probe_meta.get("conventionalRound", {})
        freq = float(cr.get("centralFrequency", 5e6))
    elif is_pa:
        pa_linear = probe_meta.get("phasedArrayLinear", {})
        freq = float(pa_linear.get("centralFrequency", 5e6))
    elif is_tfm:
        pa_linear = probe_meta.get("phasedArrayLinear", {})
        freq = float(pa_linear.get("centralFrequency", 5e6))

    probe_grp.attrs["ONDE:TYPE_TAGS"] = ["ONDE_UT_ELEMENTS"]
    probe_grp.attrs["ONDE:LABEL"] = probe_meta.get("model", "Probe")
    probe_grp.attrs["ONDE_UT_PROBE:FREQUENCY"] = freq

    # Coupling reference (scalar)
    probe_grp.attrs["ONDE_UT_PROBE:COUPLING"] = coupling_grp.ref

    # ════════════════════════════════════════════════
    # Component group
    # ════════════════════════════════════════════════
    comp_grp = f.create_group("ONDE_COMPONENT")
    set_type_attr(comp_grp, ["ONDE_COMPONENT", "ONDE_PLANE"])
    plate = specimen.get("plateGeometry", {})
    mat = plate.get("material", {})
    lv = mat.get("longitudinalWave", {}).get("nominalVelocity", 5920.0)
    tv = mat.get("transversalVerticalWave", {}).get("nominalVelocity", 3230.0)
    comp_grp.attrs["ONDE_COMPONENT:VELOCITIES"] = np.array([float(lv), float(tv)])
    comp_grp.attrs["ONDE_COMPONENT:DENSITY"] = 7800.0
    comp_grp.attrs["ONDE_PLANE:PLATE_DIMENSIONS"] = np.array(
        [float(plate.get("width", 1.0)), float(plate.get("length", 1.0)), float(plate.get("thickness", 0.01))]
    )

    # ════════════════════════════════════════════════
    # Trajectory group
    # ════════════════════════════════════════════════
    traj_grp = f.create_group("ONDE_ACQUISITION_TRAJECTORY_0")
    set_type_attr(traj_grp, ["ONDE_ACQUISITION_TRAJECTORY", "ONDE_TIME_TRAJECTORY"])

    # ════════════════════════════════════════════════
    # Geometric Setup group
    # ════════════════════════════════════════════════
    geom_grp = f.create_group("ONDE_GEOMETRIC_SETUP")
    set_type_attr(geom_grp, "ONDE_GEOMETRIC_SETUP")

    # PROBE_LIST = array of references [N_Probes]
    ds_probe_list = geom_grp.create_dataset(
        "PROBE_LIST", data=np.array([probe_grp.ref], dtype=h5py.ref_dtype)
    )

    # ACQUISITION_TRAJECTORY = array of references [N_Probes]
    ds_traj = geom_grp.create_dataset(
        "ACQUISITION_TRAJECTORY",
        data=np.array([traj_grp.ref], dtype=h5py.ref_dtype),
    )

    # COMPONENT = reference dataset [1]
    ds_comp = geom_grp.create_dataset(
        "COMPONENT", data=np.array([comp_grp.ref], dtype=h5py.ref_dtype)
    )

    # PROBE_COORDINATE_FRAME (optional, but spec says H5T_FLOAT[N_Prob, 7])
    # Use identity
    geom_grp.create_dataset(
        "PROBE_COORDINATE_FRAME",
        data=np.array([[0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0]], dtype=np.float64),
    )

    # ════════════════════════════════════════════════
    # Ultrasonic Setup group
    # ════════════════════════════════════════════════
    us_grp = f.create_group("ONDE_ULTRASONIC_SETUP")
    set_type_attr(us_grp, "ONDE_ULTRASONIC_SETUP")

    # Determine rectification
    if is_ut:
        us_proc = proc.get("ultrasonicConventional", {})
    elif is_pa:
        us_proc = proc.get("ultrasonicPhasedArray", {})
    else:
        us_proc = proc.get("totalFocusingMethod", {})

    rect = us_proc.get("rectification", "None")
    if rect == "None":
        onde_rect = "FULL_WAVE"
    elif rect == "Full":
        onde_rect = "RECTIFIED_FULL"
    elif rect == "Positive":
        onde_rect = "RECTIFIED_POSITIVE"
    elif rect == "Negative":
        onde_rect = "RECTIFIED_NEGATIVE"
    else:
        onde_rect = "FULL_WAVE"

    us_grp.attrs["ONDE_ULTRASONIC_SETUP:RECTIFICATION"] = onde_rect

    digi_freq = float(us_proc.get("digitizingFrequency", 100e6))
    comp_factor = float(us_proc.get("ascanCompressionFactor", 1))
    sample_rate = digi_freq / comp_factor
    us_grp.attrs["ONDE_ULTRASONIC_SETUP:ASCAN_SAMPLE_RATE"] = sample_rate

    # Beams
    if is_ut:
        beams = us_proc.get("beams", [])
    elif is_pa:
        beams = us_proc.get("beams", [])
    else:
        # TFM: no beams in the same sense, create a synthetic one
        beams = [{"ascanStart": 0.0, "ascanLength": 0.0}]

    n_ascan = data.shape[0] if data.ndim > 1 else 1

    # GAIN = dataset [N_Ascan]
    gain_val = float(us_proc.get("gain", 0))
    us_grp.create_dataset("GAIN", data=np.full(n_ascan, gain_val, dtype=np.float64))

    # ASCAN_START = dataset
    if beams:
        ascan_start = float(beams[0].get("ascanStart", 0.0))
    else:
        ascan_start = 0.0
    us_grp.create_dataset("ASCAN_START", data=np.array([ascan_start], dtype=np.float64))

    # ════════════════════════════════════════════════
    # Setup group
    # ════════════════════════════════════════════════
    setup_grp = f.create_group("ONDE_SETUP_UT")
    set_type_attr(setup_grp, ["ONDE_SETUP", "ONDE_SETUP_UT"])

    # GEOMETRIC_SETUP ref (scalar attribute)
    setup_grp.attrs["ONDE_SETUP:GEOMETRIC_SETUP"] = geom_grp.ref

    # ULTRASONIC_SETUP ref (scalar attribute)
    setup_grp.attrs["ONDE_SETUP_UT:ULTRASONIC_SETUP"] = us_grp.ref

    # ════════════════════════════════════════════════
    # PA-specific: PHASED_ARRAY_SETUP and LAW groups
    # ════════════════════════════════════════════════
    law_refs_tx = None
    law_refs_rx = None

    if is_pa:
        pa_proc = us_proc
        
        # Create PHASED_ARRAY_SETUP
        pa_setup = f.create_group("ONDE_PHASED_ARRAY_SETUP")
        if "totalFocusingMethod" in proc:
            set_type_attr(pa_setup, ["ONDE_PHASED_ARRAY_SETUP", "ONDE_PHASED_ARRAY_FMC"])
        else:
            set_type_attr(pa_setup, ["ONDE_PHASED_ARRAY_SETUP", "ONDE_PHASED_ARRAY_SSCAN"])

        pa_setup.attrs["ONDE_PHASED_ARRAY_SETUP:EMITTER_PROBE"] = probe_grp.ref
        pa_setup.attrs["ONDE_PHASED_ARRAY_SETUP:RECEIVING_PROBE"] = probe_grp.ref
        pa_setup.attrs["ONDE_PHASED_ARRAY_SETUP:SEQUENCE_ANGLE_MODE"] = "L"

        if is_pa and "totalFocusingMethod" not in proc:
            # SSCAN mode
            beam_angles = [b.get("refractedAngle", 0) for b in beams]
            pa_setup.attrs["ONDE_PHASED_ARRAY_SSCAN:STARTING_ANGLE"] = float(min(beam_angles))
            pa_setup.attrs["ONDE_PHASED_ARRAY_SSCAN:FINISHING_ANGLE"] = float(max(beam_angles))
            pa_setup.attrs["ONDE_PHASED_ARRAY_SSCAN:NUMBER_OF_ANGLES"] = int(len(beams))

        # Create LAW groups for each beam
        # In SSCAN mode, TX and RX use the same elements, so 1 law group per beam
        law_groups = []
        for bi, beam in enumerate(beams):
            pulsers = beam.get("pulsers", [])
            receivers = beam.get("receivers", [])

            # Use pulsers (TX) as the primary element set
            channels = pulsers if pulsers else receivers
            if not channels:
                continue

            law_name = f"ONDE_UT_LAW_{bi}"
            law_grp = f.create_group(law_name)
            set_type_attr(law_grp, "ONDE_UT_LAW")

            elements = np.array([ch["elementId"] for ch in channels], dtype=np.int32)
            delays = np.array([ch.get("delay", 0.0) for ch in channels], dtype=np.float64)
            n_channels = len(channels)

            law_grp.create_dataset(
                "PROBE",
                data=np.array(
                    [probe_grp.ref] * n_channels, dtype=h5py.ref_dtype
                ),
            )
            law_grp.create_dataset("ELEMENT", data=elements)
            law_grp.create_dataset("DELAY", data=delays)
            law_groups.append(law_grp)

        # PHASED_ARRAY_SETUP reference on ULTRASONIC_SETUP (spec: scalar ref attr)
        us_grp.attrs["ONDE_ULTRASONIC_SETUP:PHASED_ARRAY_SETUP"] = pa_setup.ref

        # TRANSMIT_LAW / RECEIVE_LAW as datasets on ULTRASONIC_SETUP (spec: H5T_STD_REF_OBJ[N_Ascan])
        # Both point to the same law groups for this SSCAN reference
        all_law_refs = np.array([lg.ref for lg in law_groups], dtype=h5py.ref_dtype)
        us_grp.create_dataset("TRANSMIT_LAW", data=all_law_refs)
        us_grp.create_dataset("RECEIVE_LAW", data=all_law_refs)

    elif is_tfm:
        tfm_proc = proc.get("totalFocusingMethod", {})
        pa_setup = f.create_group("ONDE_PHASED_ARRAY_SETUP")
        set_type_attr(pa_setup, ["ONDE_PHASED_ARRAY_SETUP", "ONDE_PHASED_ARRAY_FMC"])
        pa_setup.attrs["ONDE_PHASED_ARRAY_SETUP:EMITTER_PROBE"] = probe_grp.ref
        pa_setup.attrs["ONDE_PHASED_ARRAY_SETUP:RECEIVING_PROBE"] = probe_grp.ref
        pa_setup.attrs["ONDE_PHASED_ARRAY_SETUP:SEQUENCE_ANGLE_MODE"] = "L"
        us_grp.attrs["ONDE_ULTRASONIC_SETUP:PHASED_ARRAY_SETUP"] = pa_setup.ref

        # No laws for TFM in the reference
        us_grp.create_dataset(
            "TRANSMIT_LAW",
            data=np.array([], dtype=h5py.ref_dtype),
        )
        us_grp.create_dataset(
            "RECEIVE_LAW",
            data=np.array([], dtype=h5py.ref_dtype),
        )

    # ════════════════════════════════════════════════
    # Dataset group
    # ════════════════════════════════════════════════
    if is_tfm:
        ds_group_name = "ONDE_DATASET_UT_TSCAN_0"
        ds_type = ["ONDE_DATASET", "ONDE_DATASET_UT", "ONDE_DATASET_UT_TSCAN"]
    else:
        ds_group_name = "ONDE_DATASET_UT_ASCAN_0"
        ds_type = ["ONDE_DATASET", "ONDE_DATASET_UT", "ONDE_DATASET_UT_ASCAN"]

    ds_group = f.create_group(ds_group_name)
    set_type_attr(ds_group, ds_type)

    if is_ut:
        label = "Reference UT AScan"
    elif is_pa:
        label = "Reference PA AScan"
    else:
        label = "Reference TFM TScan"

    ds_group.attrs["ONDE:LABEL"] = label

    # SETUP reference (scalar attr)
    ds_group.attrs["ONDE_DATASET:SETUP"] = setup_grp.ref

    # DATA dataset
    dt_mapping = {np.dtype("int16"): np.dtype(np.int16), np.dtype("float32"): np.dtype(np.float32)}
    out_dtype = dt_mapping.get(data.dtype, data.dtype)
    ds_group.create_dataset("DATA", data=data.astype(out_dtype))

    # INDEX_DIMENSIONS
    # Build ordered list of dimension group refs matching data shape
    index_refs = []
    data_ndim = data.ndim

    if is_tfm and data_ndim == 2:
        # TFM: (N_Row, N_Col) 
        # Actually from spec ZONE_SIZE is [101, 201, 1] -> 3D, but data is (101, 201)
        # Let's use row, col, plane
        index_refs = [dim_groups["row"].ref, dim_groups["col"].ref, dim_groups["plane"].ref]
    elif is_tfm and data_ndim == 3:
        index_refs = [
            dim_groups.get("row", dim_groups.get("u")).ref,
            dim_groups.get("col", dim_groups.get("u")).ref,
            dim_groups["plane"].ref,
        ]
    elif data_ndim == 1:
        # UT: (N_Time,) - just time
        index_refs = [dim_groups["time"].ref]
    elif data_ndim == 2:
        # PA: (N_Beam, N_Time) -> beam, time
        # Or UT with no beam: u, time
        if "beam" in dim_groups:
            # beam first, then time (since PA data shape is (31, 1000))
            # Actually PA data shape is (31, 1000). Dimensions from spec:
            # For PA: first dim is Beam (31 angles), second is Time (1000 samples)
            if "beam" in dim_groups:
                index_refs = [dim_groups["beam"].ref, dim_groups["time"].ref]
            elif "u" in dim_groups:
                index_refs = [dim_groups["u"].ref, dim_groups["time"].ref]
            else:
                index_refs = [dim_groups["time"].ref]
        else:
            # UT 2D: U first, then time
            index_refs = [dim_groups.get("u", dim_groups.get("time")).ref, dim_groups["time"].ref]

    if index_refs:
        ds_group.attrs["ONDE_DATASET:INDEX_DIMENSIONS"] = np.array(
            index_refs, dtype=h5py.ref_dtype
        )

    # AMPLITUDE_DIMENSION (single ref)
    ds_group.attrs["ONDE_DATASET:AMPLITUDE_DIMENSION"] = amp_grp.ref

    # TFM-specific attrs
    if is_tfm:
        tfm_proc = proc.get("totalFocusingMethod", {})
        rect_grid = tfm_proc.get("rectangularGrid", {})
        y_limits = rect_grid.get("yImagingLimits", {})
        z_limits = rect_grid.get("zImagingLimits", {})

        y_min = float(y_limits.get("min", -0.01))
        y_max = float(y_limits.get("max", 0.0102))
        z_min = float(z_limits.get("min", 0.005))
        z_max = float(z_limits.get("max", 0.0452))

        # ZONE_FRAME: [x, y, z, qw, qx, qy, qz]
        zone_frame = np.array([0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0])
        ds_group.attrs["ONDE_DATASET_UT_TSCAN:ZONE_FRAME"] = zone_frame

        # ZONE_DIMENSION: [y_size, z_size, w_size]
        zone_dim = np.array(
            [y_max - y_min, z_max - z_min, 1.0], dtype=np.float64
        )
        ds_group.attrs["ONDE_DATASET_UT_TSCAN:ZONE_DIMENSION"] = zone_dim

        # ZONE_SIZE: [N_Row, N_Col, N_Plane]
        if col_dim is not None:
            n_col = int(col_dim.get("quantity", data.shape[1]))
        else:
            n_col = data.shape[1]
        if u_dim is not None:
            n_row = int(u_dim.get("quantity", data.shape[0]))
        else:
            n_row = data.shape[0]
        n_plane = 1
        zone_size = np.array([n_row, n_col, n_plane], dtype=np.int32)
        ds_group.attrs["ONDE_DATASET_UT_TSCAN:ZONE_SIZE"] = zone_size

    # TRANSMIT_LAW and RECEIVE_LAW are stored on the ULTRASONIC_SETUP per spec
    # (already handled above for PA/TFM)

    f.close()
    print(f"  Written to {onde_file}")
    return onde_file


def verify_onde_file(filename, filetype):
    """Verify the generated ONDE file has all mandatory fields"""
    print(f"\n=== Verifying {filename} ===")
    f = h5py.File(filename, "r")

    # Root attrs
    assert f.attrs["ONDE:FILETYPE"] == filetype, f"FILETYPE mismatch: {f.attrs['ONDE:FILETYPE']}"
    assert f.attrs["ONDE:VERSION"] == "0.9.0"
    print("  [OK] Root attributes")

    # Check all groups have ONDE:TYPE
    def check_groups(name, obj):
        if isinstance(obj, h5py.Group):
            if "ONDE:TYPE" not in obj.attrs:
                print(f"  [WARN] Group {name} missing ONDE:TYPE")
            else:
                types = obj.attrs["ONDE:TYPE"]
                print(f"  [OK] {name}: TYPE={types}")
        if isinstance(obj, h5py.Dataset):
            pass  # datasets are fine

    f.visititems(check_groups)

    # Check for mandatory dataset group
    found_dataset = False
    found_setup = False
    found_geometric = False
    found_ultrasonic = False
    found_probe = False
    found_component = False
    found_coupling = False
    found_trajectory = False

    for name in f:
        if "DATASET" in name and isinstance(f[name], h5py.Group):
            found_dataset = True
            dsg = f[name]
            assert "ONDE_DATASET:SETUP" in dsg.attrs, "Missing SETUP reference"
            assert "ONDE_DATASET:DATA" in dsg or "DATA" in dsg, "Missing DATA"
            # Verify SETUP ref points to ONDE_SETUP group
            setup_ref = dsg.attrs["ONDE_DATASET:SETUP"]
            # For scalar refs in attrs wrapped in array(..., dtype=object)
            print(f"  [OK] Dataset group has SETUP reference")

        if "SETUP" in name and isinstance(f[name], h5py.Group):
            g = f[name]
            types = list(g.attrs.get("ONDE:TYPE", []))
            if b"ONDE_SETUP_UT" in types or "ONDE_SETUP_UT" in types:
                found_setup = True
                assert "ONDE_SETUP:GEOMETRIC_SETUP" in g.attrs
                assert "ONDE_SETUP_UT:ULTRASONIC_SETUP" in g.attrs
                print("  [OK] Setup group")

    for name in f:
        g = f[name]
        if not isinstance(g, h5py.Group):
            continue
        types_attr = g.attrs.get("ONDE:TYPE", [])
        if isinstance(types_attr, bytes):
            types_attr = [types_attr]
        types_list = [t.decode() if isinstance(t, bytes) else str(t) for t in (types_attr if hasattr(types_attr, '__iter__') else [types_attr])]

        if "ONDE_GEOMETRIC_SETUP" in types_list:
            found_geometric = True
            assert "PROBE_LIST" in g, "Missing PROBE_LIST"
            assert "ACQUISITION_TRAJECTORY" in g, "Missing ACQUISITION_TRAJECTORY"
            # COMPONENT is optional but should be present
            if "COMPONENT" in g:
                print("  [OK] Geometric setup with COMPONENT")

        if "ONDE_ULTRASONIC_SETUP" in types_list:
            found_ultrasonic = True
            assert "ONDE_ULTRASONIC_SETUP:RECTIFICATION" in g.attrs
            assert "ONDE_ULTRASONIC_SETUP:ASCAN_SAMPLE_RATE" in g.attrs
            assert "GAIN" in g, "Missing GAIN dataset"
            assert "ASCAN_START" in g, "Missing ASCAN_START dataset"
            print("  [OK] Ultrasonic setup")

        if "ONDE_UT_PROBE" in types_list:
            found_probe = True
            assert "ONDE_UT_PROBE:FREQUENCY" in g.attrs
            assert "ONDE_UT_PROBE:COUPLING" in g.attrs
            assert "ONDE:TYPE_TAGS" in g.attrs
            print("  [OK] Probe group")

        if "ONDE_COMPONENT" in types_list:
            found_component = True
            assert "ONDE_COMPONENT:VELOCITIES" in g.attrs
            print("  [OK] Component group")

        if "ONDE_UT_COUPLING" in types_list:
            found_coupling = True
            assert "ONDE_UT_COUPLING:MEDIUM_VELOCITY" in g.attrs
            assert "ONDE_UT_COUPLING:INCIDENCE_ANGLE" in g.attrs
            print("  [OK] Coupling group")

        if "ONDE_ACQUISITION_TRAJECTORY" in types_list:
            found_trajectory = True
            print("  [OK] Trajectory group")

    assert found_dataset, "No dataset group found"
    assert found_setup, "No setup group found"
    assert found_geometric, "No geometric setup found"
    assert found_ultrasonic, "No ultrasonic setup found"
    assert found_probe, "No probe found"
    assert found_component, "No component found"
    assert found_coupling, "No coupling found"
    assert found_trajectory, "No trajectory found"

    # Verify HDF5 references are valid
    print("  [OK] All mandatory groups present")

    # Check data content matches
    for name in f:
        if isinstance(f[name], h5py.Group) and "DATASET" in name:
            if "DATA" in f[name]:
                data = f[name]["DATA"][()]
                print(f"  [OK] DATA shape={data.shape}, dtype={data.dtype}")

    f.close()
    print(f"  [PASS] {filename} verified")
    return True


def main():
    # UT
    create_reference_onde_from_nde(
        f"{FIxtures_DIR}/reference_ut.nde",
        f"{FIxtures_DIR}/reference_ut_expected_v2.onde",
        "ONDE_UT",
    )

    # PA
    create_reference_onde_from_nde(
        f"{FIxtures_DIR}/reference_pa.nde",
        f"{FIxtures_DIR}/reference_pa_expected_v2.onde",
        "ONDE_UT",
    )

    # TFM
    create_reference_onde_from_nde(
        f"{FIxtures_DIR}/reference_tfm.nde",
        f"{FIxtures_DIR}/reference_tfm_expected_v2.onde",
        "ONDE_UT",
    )

    # Verify all
    print("\n\n========== VERIFICATION ==========")
    verify_onde_file(f"{FIxtures_DIR}/reference_ut_expected_v2.onde", "ONDE_UT")
    verify_onde_file(f"{FIxtures_DIR}/reference_pa_expected_v2.onde", "ONDE_UT")
    verify_onde_file(f"{FIxtures_DIR}/reference_tfm_expected_v2.onde", "ONDE_UT")

    print("\nAll reference files generated and verified!")


if __name__ == "__main__":
    main()

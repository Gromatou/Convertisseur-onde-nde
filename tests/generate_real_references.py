#!/usr/bin/env python3
"""
Manual conversion of real Evident NDE files to spec-compliant ONDE format.

Converts three NDE fixture files:
  - Weld_Plate_UT-sk90-4.2.nde     → real_ut_expected.onde
  - Weld_Plate_PA-Sect_sk90-4.2.nde → real_pa_expected.onde
  - Weld_Plate_ToFD_Parallel-4.2.nde → real_tofd_expected.onde

Usage:
    python tests/generate_real_references.py

Requires: h5py, numpy
"""

import json
import os
import numpy as np
import h5py

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
OUTPUT_DIR = FIXTURES_DIR


def db_to_linear(db):
    """Convert dB gain to linear scaling factor."""
    return 10.0 ** (db / 20.0)


def make_ref_array(refs):
    """Create a numpy array of HDF5 object references."""
    arr = np.array(refs, dtype=h5py.ref_dtype)
    return arr


def make_string_array(strings):
    """Create a numpy array of variable-length UTF-8 strings for HDF5."""
    dt = h5py.string_dtype()
    arr = np.array(strings, dtype=dt)
    return arr


def set_attr(group, name, value):
    """Set an attribute on an HDF5 group, handling string arrays properly."""
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        group.attrs[name] = make_string_array(value)
    elif isinstance(value, str):
        group.attrs[name] = value
    elif isinstance(value, (np.integer, int)):
        group.attrs[name] = np.int64(value)
    elif isinstance(value, (np.floating, float)):
        group.attrs[name] = np.float64(value)
    elif isinstance(value, (list, np.ndarray)):
        if all(isinstance(v, str) for v in value):
            group.attrs[name] = make_string_array(value)
        else:
            group.attrs[name] = np.array(value, dtype=np.float64)
    elif isinstance(value, h5py.h5r.Reference):
        group.attrs[name] = value
    else:
        group.attrs[name] = value


def create_dimension(root, name, coordinate, units, offset, scale):
    """Create an ONDE_DIMENSION group."""
    grp = root.create_group(name)
    set_attr(grp, "ONDE:TYPE", ["ONDE_DIMENSION"])
    set_attr(grp, "ONDE_DIMENSION:COORDINATE", coordinate)
    set_attr(grp, "ONDE_DIMENSION:UNITS", units)
    set_attr(grp, "ONDE_DIMENSION:OFFSET", offset)
    set_attr(grp, "ONDE_DIMENSION:SCALE", scale)
    return grp


def rectification_map(nde_rect):
    """Map NDE rectification string to ONDE rectification string."""
    mapping = {
        "None": "FULL_WAVE",
        "Positive": "RECTIFIED_POSITIVE",
        "Negative": "RECTIFIED_NEGATIVE",
        "Full": "RECTIFIED_FULL",
    }
    return mapping.get(nde_rect, "FULL_WAVE")


def convert_ut(src_path, dst_path):
    """Convert conventional UT NDE file to ONDE."""
    print(f"Converting UT: {src_path} → {dst_path}")
    src = h5py.File(src_path, "r")

    # Read setup JSON
    setup = json.loads(src["Public/Setup"][()])
    groups_info = setup["groups"][0]
    proc = groups_info["processes"][0]["ultrasonicConventional"]

    # Read data
    data = src["Public/Groups/0/Datasets/0-AScanAmplitude"][:]
    data_shape = data.shape  # (151, 1, 624)

    # Read amplitude dataset dimensions info
    amp_ds_info = groups_info["datasets"][0]
    dims_info = amp_ds_info["dimensions"]

    # Find axis info
    u_dim = None
    v_dim = None
    time_dim = None
    for d in dims_info:
        if d["axis"] == "UCoordinate":
            u_dim = d
        elif d["axis"] == "VCoordinate":
            v_dim = d
        elif d["axis"] == "Ultrasound":
            time_dim = d

    # NDE parameters
    digitizing_freq = proc["digitizingFrequency"]  # 100e6
    compression = proc["ascanCompressionFactor"]  # 8
    ascan_sample_rate = digitizing_freq / compression  # 12.5e6
    time_scale = 1.0 / ascan_sample_rate  # 8e-8
    gain_db = proc["gain"]  # 33.0 dB
    ascan_start = proc["beams"][0]["ascanStart"]  # 0.0
    rect = proc["rectification"]  # "Full"

    # NDE probe/wedge info
    probe_id = proc["pulseEcho"]["probeId"]
    probe_info = None
    wedge_info = None
    for p in setup["probes"]:
        if p["id"] == probe_id:
            probe_info = p
            break
    if probe_info and "wedgeAssociation" in probe_info:
        wedge_id = probe_info["wedgeAssociation"]["wedgeId"]
        for w in setup["wedges"]:
            if w["id"] == wedge_id:
                wedge_info = w
                break

    # NDE specimen info
    specimen = setup["specimens"][0]
    material = specimen["plateGeometry"]["material"] if "plateGeometry" in specimen else specimen.get("pipeGeometry", {}).get("material", {})

    # Get velocities
    v_long = material.get("longitudinalWave", {}).get("nominalVelocity", 5890.0)
    v_shear = material.get("transversalVerticalWave", {}).get("nominalVelocity", 3240.0)
    density = material.get("density", 7800.0)

    # Plate dimensions
    if "plateGeometry" in specimen:
        plate = specimen["plateGeometry"]
        plate_dims = [plate.get("width", 0.25), plate.get("length", 0.25), plate.get("thickness", 0.011)]
    else:
        plate_dims = [0.25, 0.25, 0.011]

    # ── Build ONDE file ──
    dst = h5py.File(dst_path, "w")

    # Root attributes
    dst.attrs["ONDE:FILETYPE"] = "ONDE_UT"
    dst.attrs["ONDE:VERSION"] = "0.9.0"

    # ── Dimension groups ──
    # U dimension
    u_offset = u_dim.get("offset", 0.0) if u_dim else 0.0
    u_scale = u_dim.get("resolution", 0.001) if u_dim else 1.0
    dim_u = create_dimension(dst, "dim_u", "U", "meters", u_offset, u_scale)

    # V dimension
    v_offset = v_dim.get("offset", 0.0) if v_dim else 0.0
    v_scale = v_dim.get("resolution", 0.001) if v_dim else 1.0
    dim_v = create_dimension(dst, "dim_v", "V", "meters", v_offset, v_scale)

    # Time dimension
    dim_time = create_dimension(dst, "dim_time", "Time", "seconds", ascan_start, time_scale)

    # Amplitude dimension
    dim_amp = create_dimension(dst, "dim_amp", "Amplitude", "arbitrary", 0.0, 1.0)

    # ── Coupling (Wedge) ──
    wedge_v_long = wedge_info["angleBeamWedge"]["longitudinalVelocity"] if wedge_info else 2330.0
    wedge_angle = wedge_info["angleBeamWedge"]["mountingLocations"][0]["wedgeAngle"] if wedge_info else 0.0

    coupling_grp = dst.create_group("ONDE_COUPLING_0")
    set_attr(coupling_grp, "ONDE:TYPE", ["ONDE_UT_COUPLING", "ONDE_WEDGE", "ONDE_SINGLE_WEDGE"])
    set_attr(coupling_grp, "ONDE_UT_COUPLING:MEDIUM_VELOCITY", [wedge_v_long, wedge_v_long / 2.0])
    set_attr(coupling_grp, "ONDE_UT_COUPLING:INCIDENCE_ANGLE", wedge_angle)

    if wedge_info:
        wdata = wedge_info["angleBeamWedge"]
        contact_area = [wdata.get("width", 0.025), wdata.get("length", 0.025), wdata.get("height", 0.017)]
        height = wdata.get("height", 0.017)
        set_attr(coupling_grp, "ONDE_WEDGE:CONTACT_AREA", contact_area)
        set_attr(coupling_grp, "ONDE_WEDGE:HEIGHT", height)
        set_attr(coupling_grp, "ONDE_WEDGE:SKEW_ANGLE", 0.0)

    # ── Probe ──
    probe_freq = probe_info["conventionalRound"]["centralFrequency"] if probe_info else 2250000.0

    probe_grp = dst.create_group("ONDE_PROBE_0")
    set_attr(probe_grp, "ONDE:TYPE", ["ONDE_UT_PROBE", "ONDE_MONO_UT_PROBE"])
    set_attr(probe_grp, "ONDE:TYPE_TAGS", ["ONDE_UT_ELEMENTS"])
    set_attr(probe_grp, "ONDE:LABEL", probe_info.get("model", "UT Probe") if probe_info else "UT Probe")
    set_attr(probe_grp, "ONDE_UT_PROBE:FREQUENCY", probe_freq)
    set_attr(probe_grp, "ONDE_UT_PROBE:COUPLING", coupling_grp.ref)

    # ── Component (Plate) ──
    comp_grp = dst.create_group("ONDE_COMPONENT")
    set_attr(comp_grp, "ONDE:TYPE", ["ONDE_COMPONENT", "ONDE_PLANE"])
    set_attr(comp_grp, "ONDE_COMPONENT:VELOCITIES", [v_long, v_shear])
    set_attr(comp_grp, "ONDE_COMPONENT:DENSITY", density)
    set_attr(comp_grp, "ONDE_PLANE:PLATE_DIMENSIONS", plate_dims)

    # ── Acquisition Trajectory ──
    traj_grp = dst.create_group("ONDE_ACQUISITION_TRAJECTORY_0")
    set_attr(traj_grp, "ONDE:TYPE", ["ONDE_ACQUISITION_TRAJECTORY", "ONDE_TIME_TRAJECTORY"])

    # ── Geometric Setup ──
    geom_grp = dst.create_group("ONDE_GEOMETRIC_SETUP")
    set_attr(geom_grp, "ONDE:TYPE", ["ONDE_GEOMETRIC_SETUP"])

    # COMPONENT: dataset of refs (scalar dataset with 1 ref)
    comp_ref_ds = geom_grp.create_dataset("COMPONENT", data=np.array([comp_grp.ref], dtype=h5py.ref_dtype))

    # PROBE_LIST: dataset of refs
    probe_list_ds = geom_grp.create_dataset("PROBE_LIST", data=np.array([probe_grp.ref], dtype=h5py.ref_dtype))

    # ACQUISITION_TRAJECTORY: dataset of refs
    traj_list_ds = geom_grp.create_dataset("ACQUISITION_TRAJECTORY", data=np.array([traj_grp.ref], dtype=h5py.ref_dtype))

    # PROBE_COORDINATE_FRAME: identity [x,y,z,qw,qx,qy,qz]
    identity_frame = np.array([[0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0]], dtype=np.float64)
    frame_ds = geom_grp.create_dataset("PROBE_COORDINATE_FRAME", data=identity_frame)

    # ── Ultrasonic Setup ──
    us_grp = dst.create_group("ONDE_ULTRASONIC_SETUP")
    set_attr(us_grp, "ONDE:TYPE", ["ONDE_ULTRASONIC_SETUP"])
    set_attr(us_grp, "ONDE_ULTRASONIC_SETUP:RECTIFICATION", rectification_map(rect))
    set_attr(us_grp, "ONDE_ULTRASONIC_SETUP:ASCAN_SAMPLE_RATE", ascan_sample_rate)

    # GAIN: dataset (H5T_FLOAT), one value
    gain_linear = db_to_linear(gain_db)
    us_grp.create_dataset("GAIN", data=np.array([gain_linear], dtype=np.float64))

    # ASCAN_START: dataset
    us_grp.create_dataset("ASCAN_START", data=np.array([ascan_start], dtype=np.float64))

    # ── Setup UT ──
    setup_grp = dst.create_group("ONDE_SETUP_UT")
    set_attr(setup_grp, "ONDE:TYPE", ["ONDE_SETUP", "ONDE_SETUP_UT"])
    set_attr(setup_grp, "ONDE_SETUP:GEOMETRIC_SETUP", geom_grp.ref)
    set_attr(setup_grp, "ONDE_SETUP_UT:ULTRASONIC_SETUP", us_grp.ref)

    # ── Dataset UT AScan ──
    ds_grp = dst.create_group("ONDE_DATASET_UT_ASCAN_0")

    set_attr(ds_grp, "ONDE:TYPE", ["ONDE_DATASET", "ONDE_DATASET_UT", "ONDE_DATASET_UT_ASCAN"])
    set_attr(ds_grp, "ONDE:LABEL", "Weld Plate UT AScan")

    # ONDE_DATASET:SETUP = ref to ONDE_SETUP_UT
    set_attr(ds_grp, "ONDE_DATASET:SETUP", setup_grp.ref)

    # INDEX_DIMENSIONS = array of refs: [dim_u, dim_v, dim_time]
    index_dims = make_ref_array([dim_u.ref, dim_v.ref, dim_time.ref])
    ds_grp.attrs["ONDE_DATASET:INDEX_DIMENSIONS"] = index_dims

    # AMPLITUDE_DIMENSION = ref to dim_amp
    set_attr(ds_grp, "ONDE_DATASET:AMPLITUDE_DIMENSION", dim_amp.ref)

    # DATA = raw data
    ds_grp.create_dataset("DATA", data=data, dtype=data.dtype)

    dst.close()
    src.close()
    print(f"  ✓ Written: {dst_path}")


def convert_pa(src_path, dst_path):
    """Convert phased array NDE file to ONDE."""
    print(f"Converting PA: {src_path} → {dst_path}")
    src = h5py.File(src_path, "r")

    # Read setup JSON
    setup = json.loads(src["Public/Setup"][()])
    groups_info = setup["groups"][0]
    proc = groups_info["processes"][0]["ultrasonicPhasedArray"]

    # Read data
    data = src["Public/Groups/0/Datasets/0-AScanAmplitude"][:]  # (45, 31, 1600) int16
    data_shape = data.shape

    # Read amplitude dataset dimensions info
    amp_ds_info = groups_info["datasets"][0]
    dims_info = amp_ds_info["dimensions"]

    # Find axis info
    u_dim = None
    beam_dim = None
    time_dim = None
    for d in dims_info:
        if d["axis"] == "UCoordinate":
            u_dim = d
        elif d["axis"] == "Beam":
            beam_dim = d
        elif d["axis"] == "Ultrasound":
            time_dim = d

    # NDE parameters
    digitizing_freq = proc["digitizingFrequency"]  # 100e6
    compression = proc["ascanCompressionFactor"]  # 4
    ascan_sample_rate = digitizing_freq / compression  # 25e6
    time_scale = 1.0 / ascan_sample_rate  # 4e-8
    gain_db = proc["gain"]  # 20.9 dB (process gain)
    rect = proc["rectification"]  # "Full"

    # Beams info
    beams = proc["beams"]  # 31 beams
    n_beams = len(beams)

    # For sectorial formation
    sectorial = proc["pulseEcho"]["sectorialFormation"]
    start_angle = sectorial["beamRefractedAngles"]["start"]  # 40.0
    stop_angle = sectorial["beamRefractedAngles"]["stop"]  # 70.0
    step_angle = sectorial["beamRefractedAngles"]["step"]  # 1.0
    aperture = sectorial["elementAperture"]  # 32

    # NDE probe info
    probe_id = proc["pulseEcho"]["probeId"]
    probe_info = None
    for p in setup["probes"]:
        if p["id"] == probe_id:
            probe_info = p
            break

    wedge_info = None
    if probe_info and "wedgeAssociation" in probe_info:
        wedge_id = probe_info["wedgeAssociation"]["wedgeId"]
        for w in setup["wedges"]:
            if w["id"] == wedge_id:
                wedge_info = w
                break

    # NDE specimen info
    specimen = setup["specimens"][0]
    material = specimen["plateGeometry"]["material"] if "plateGeometry" in specimen else {}

    v_long = material.get("longitudinalWave", {}).get("nominalVelocity", 5800.0)
    v_shear = material.get("transversalVerticalWave", {}).get("nominalVelocity", 3100.0)
    density = material.get("density", 7890.0)

    if "plateGeometry" in specimen:
        plate = specimen["plateGeometry"]
        plate_dims = [plate.get("width", 0.3), plate.get("length", 0.3), plate.get("thickness", 0.026)]

    # Probe geometry
    primary_axis = probe_info["phasedArrayLinear"]["primaryAxis"]
    secondary_axis = probe_info["phasedArrayLinear"]["secondaryAxis"]
    n_elements_total = primary_axis["elementQuantity"]  # 64
    element_length = primary_axis["elementLength"]  # 0.0005
    element_width = secondary_axis["elementLength"]  # 0.01
    pitch = element_length + primary_axis.get("elementGap", 0.0)  # 0.0005

    # ── Build ONDE file ──
    dst = h5py.File(dst_path, "w")

    # Root attributes
    dst.attrs["ONDE:FILETYPE"] = "ONDE_UT"
    dst.attrs["ONDE:VERSION"] = "0.9.0"

    # ── Dimension groups ──
    u_offset = u_dim.get("offset", 0.042) if u_dim else 0.042
    u_scale = u_dim.get("resolution", 0.001) if u_dim else 0.001
    dim_u = create_dimension(dst, "dim_u", "U", "meters", u_offset, u_scale)

    # Beam dimension
    dim_beam = create_dimension(dst, "dim_beam", "Beam", "arbitrary", 0.0, 1.0)

    # Time dimension: use beam[0] ascanStart as the common start
    ascan_start = beams[0]["ascanStart"]  # 1.421e-05
    dim_time = create_dimension(dst, "dim_time", "Time", "seconds", ascan_start, time_scale)

    # Amplitude dimension
    dim_amp = create_dimension(dst, "dim_amp", "Amplitude", "arbitrary", 0.0, 1.0)

    # ── Coupling (Wedge) ──
    wedge_v_long = wedge_info["angleBeamWedge"]["longitudinalVelocity"] if wedge_info else 2330.0
    wedge_angle = wedge_info["angleBeamWedge"]["mountingLocations"][0]["wedgeAngle"] if wedge_info else 0.0

    coupling_grp = dst.create_group("ONDE_COUPLING_0")
    set_attr(coupling_grp, "ONDE:TYPE", ["ONDE_UT_COUPLING", "ONDE_WEDGE", "ONDE_SINGLE_WEDGE"])
    set_attr(coupling_grp, "ONDE_UT_COUPLING:MEDIUM_VELOCITY", [wedge_v_long, wedge_v_long / 2.0])
    set_attr(coupling_grp, "ONDE_UT_COUPLING:INCIDENCE_ANGLE", wedge_angle)

    if wedge_info:
        wdata = wedge_info["angleBeamWedge"]
        contact_area = [wdata.get("width", 0.03), wdata.get("length", 0.0615), wdata.get("height", 0.03315)]
        height = wdata.get("height", 0.03315)
        set_attr(coupling_grp, "ONDE_WEDGE:CONTACT_AREA", contact_area)
        set_attr(coupling_grp, "ONDE_WEDGE:HEIGHT", height)
        set_attr(coupling_grp, "ONDE_WEDGE:SKEW_ANGLE", 0.0)

    # ── Probe ──
    probe_freq = probe_info["phasedArrayLinear"]["centralFrequency"] if probe_info else 5000000.0

    probe_grp = dst.create_group("ONDE_PROBE_0")
    set_attr(probe_grp, "ONDE:TYPE", ["ONDE_UT_PROBE", "ONDE_LINEAR_UT_PROBE"])
    set_attr(probe_grp, "ONDE:TYPE_TAGS", ["ONDE_UT_ELEMENTS"])
    set_attr(probe_grp, "ONDE:LABEL", probe_info.get("model", "PA Probe") if probe_info else "PA Probe")
    set_attr(probe_grp, "ONDE_UT_PROBE:FREQUENCY", probe_freq)
    set_attr(probe_grp, "ONDE_UT_PROBE:COUPLING", coupling_grp.ref)
    set_attr(probe_grp, "ONDE_LINEAR_UT_PROBE:TOTAL_NUMBER_OF_ELEMENTS", n_elements_total)
    set_attr(probe_grp, "ONDE_LINEAR_UT_PROBE:ELEMENT_DIM_MAJOR", element_width)
    set_attr(probe_grp, "ONDE_LINEAR_UT_PROBE:ELEMENT_DIM_MINOR", element_length)
    set_attr(probe_grp, "ONDE_LINEAR_UT_PROBE:ELEMENT_PITCH_DIM_MAJOR", pitch)

    # ── Component (Plate) ──
    comp_grp = dst.create_group("ONDE_COMPONENT")
    set_attr(comp_grp, "ONDE:TYPE", ["ONDE_COMPONENT", "ONDE_PLANE"])
    set_attr(comp_grp, "ONDE_COMPONENT:VELOCITIES", [v_long, v_shear])
    set_attr(comp_grp, "ONDE_COMPONENT:DENSITY", density)
    set_attr(comp_grp, "ONDE_PLANE:PLATE_DIMENSIONS", plate_dims)

    # ── Acquisition Trajectory ──
    traj_grp = dst.create_group("ONDE_ACQUISITION_TRAJECTORY_0")
    set_attr(traj_grp, "ONDE:TYPE", ["ONDE_ACQUISITION_TRAJECTORY", "ONDE_TIME_TRAJECTORY"])

    # ── Geometric Setup ──
    geom_grp = dst.create_group("ONDE_GEOMETRIC_SETUP")
    set_attr(geom_grp, "ONDE:TYPE", ["ONDE_GEOMETRIC_SETUP"])
    geom_grp.create_dataset("COMPONENT", data=np.array([comp_grp.ref], dtype=h5py.ref_dtype))
    geom_grp.create_dataset("PROBE_LIST", data=np.array([probe_grp.ref], dtype=h5py.ref_dtype))
    geom_grp.create_dataset("ACQUISITION_TRAJECTORY", data=np.array([traj_grp.ref], dtype=h5py.ref_dtype))
    identity_frame = np.array([[0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0]], dtype=np.float64)
    geom_grp.create_dataset("PROBE_COORDINATE_FRAME", data=identity_frame)

    # ── Phased Array Setup ──
    pa_grp = dst.create_group("ONDE_PHASED_ARRAY_SETUP")
    set_attr(pa_grp, "ONDE:TYPE", ["ONDE_PHASED_ARRAY_SETUP", "ONDE_PHASED_ARRAY_SSCAN"])
    set_attr(pa_grp, "ONDE_PHASED_ARRAY_SETUP:EMITTER_PROBE", probe_grp.ref)
    set_attr(pa_grp, "ONDE_PHASED_ARRAY_SETUP:RECEIVING_PROBE", probe_grp.ref)
    set_attr(pa_grp, "ONDE_PHASED_ARRAY_SETUP:SEQUENCE_ANGLE_MODE", "L")
    set_attr(pa_grp, "ONDE_PHASED_ARRAY_SSCAN:STARTING_ANGLE", start_angle)
    set_attr(pa_grp, "ONDE_PHASED_ARRAY_SSCAN:FINISHING_ANGLE", stop_angle)
    set_attr(pa_grp, "ONDE_PHASED_ARRAY_SSCAN:NUMBER_OF_ANGLES", n_beams)

    # ── UT Law groups (one per beam) ──
    first_element_id = sectorial["probeFirstElementId"]  # 0

    # For each beam, build law groups for transmit and receive
    tx_law_refs = []
    rx_law_refs = []

    for beam_idx, beam in enumerate(beams):
        # Use either "pulsers" (transmit) and "receivers" (receive) from the beam data
        pulsers = beam.get("pulsers", [])
        receivers = beam.get("receivers", pulsers)  # Fallback to pulsers if no separate receivers

        # Create transmit law
        tx_law_name = f"ONDE_UT_LAW_{beam_idx}"
        tx_law_grp = dst.create_group(tx_law_name)
        set_attr(tx_law_grp, "ONDE:TYPE", ["ONDE_UT_LAW"])

        n_active = len(pulsers)
        probe_refs = np.array([probe_grp.ref] * n_active, dtype=h5py.ref_dtype)
        element_ids = np.array([p["elementId"] for p in pulsers], dtype=np.int32)
        delays = np.array([p["delay"] for p in pulsers], dtype=np.float64)

        tx_law_grp.create_dataset("PROBE", data=probe_refs)
        tx_law_grp.create_dataset("ELEMENT", data=element_ids)
        tx_law_grp.create_dataset("DELAY", data=delays)
        tx_law_refs.append(tx_law_grp.ref)

        # Create receive law (may be same as transmit for pulse-echo)
        rx_law_name = f"ONDE_UT_LAW_RX_{beam_idx}"
        rx_law_grp = dst.create_group(rx_law_name)
        set_attr(rx_law_grp, "ONDE:TYPE", ["ONDE_UT_LAW"])

        n_active_rx = len(receivers)
        probe_refs_rx = np.array([probe_grp.ref] * n_active_rx, dtype=h5py.ref_dtype)
        element_ids_rx = np.array([r["elementId"] for r in receivers], dtype=np.int32)
        delays_rx = np.array([r["delay"] for r in receivers], dtype=np.float64)

        rx_law_grp.create_dataset("PROBE", data=probe_refs_rx)
        rx_law_grp.create_dataset("ELEMENT", data=element_ids_rx)
        rx_law_grp.create_dataset("DELAY", data=delays_rx)
        rx_law_refs.append(rx_law_grp.ref)

    # ── Ultrasonic Setup ──
    us_grp = dst.create_group("ONDE_ULTRASONIC_SETUP")
    set_attr(us_grp, "ONDE:TYPE", ["ONDE_ULTRASONIC_SETUP"])
    set_attr(us_grp, "ONDE_ULTRASONIC_SETUP:RECTIFICATION", rectification_map(rect))
    set_attr(us_grp, "ONDE_ULTRASONIC_SETUP:ASCAN_SAMPLE_RATE", ascan_sample_rate)

    # PHASED_ARRAY_SETUP reference
    set_attr(us_grp, "ONDE_ULTRASONIC_SETUP:PHASED_ARRAY_SETUP", pa_grp.ref)

    # GAIN: per-beam dataset (linear gain = process gain + gainOffset per beam)
    gains = np.array([db_to_linear(gain_db + beam.get("gainOffset", 0.0)) for beam in beams], dtype=np.float64)
    us_grp.create_dataset("GAIN", data=gains)

    # ASCAN_START: per-beam dataset
    ascan_starts = np.array([beam.get("ascanStart", 1.421e-05) for beam in beams], dtype=np.float64)
    us_grp.create_dataset("ASCAN_START", data=ascan_starts)

    # TRANSMIT_LAW: dataset of refs
    tx_law_arr = np.array(tx_law_refs, dtype=h5py.ref_dtype)
    us_grp.create_dataset("TRANSMIT_LAW", data=tx_law_arr)

    # RECEIVE_LAW: dataset of refs
    rx_law_arr = np.array(rx_law_refs, dtype=h5py.ref_dtype)
    us_grp.create_dataset("RECEIVE_LAW", data=rx_law_arr)

    # ── Setup UT ──
    setup_grp = dst.create_group("ONDE_SETUP_UT")
    set_attr(setup_grp, "ONDE:TYPE", ["ONDE_SETUP", "ONDE_SETUP_UT"])
    set_attr(setup_grp, "ONDE_SETUP:GEOMETRIC_SETUP", geom_grp.ref)
    set_attr(setup_grp, "ONDE_SETUP_UT:ULTRASONIC_SETUP", us_grp.ref)

    # ── Dataset UT AScan ──
    ds_grp = dst.create_group("ONDE_DATASET_UT_ASCAN_0")
    set_attr(ds_grp, "ONDE:TYPE", ["ONDE_DATASET", "ONDE_DATASET_UT", "ONDE_DATASET_UT_ASCAN"])
    set_attr(ds_grp, "ONDE:LABEL", "Weld Plate PA AScan")
    set_attr(ds_grp, "ONDE_DATASET:SETUP", setup_grp.ref)

    # INDEX_DIMENSIONS = [dim_u, dim_beam, dim_time]
    index_dims = make_ref_array([dim_u.ref, dim_beam.ref, dim_time.ref])
    ds_grp.attrs["ONDE_DATASET:INDEX_DIMENSIONS"] = index_dims

    set_attr(ds_grp, "ONDE_DATASET:AMPLITUDE_DIMENSION", dim_amp.ref)

    # DATA
    ds_grp.create_dataset("DATA", data=data, dtype=data.dtype)

    dst.close()
    src.close()
    print(f"  ✓ Written: {dst_path}")


def convert_tofd(src_path, dst_path):
    """Convert TOFD NDE file to ONDE."""
    print(f"Converting TOFD: {src_path} → {dst_path}")
    src = h5py.File(src_path, "r")

    # Read setup JSON
    setup = json.loads(src["Public/Setup"][()])
    groups_info = setup["groups"][0]
    proc = groups_info["processes"][0]["ultrasonicConventional"]

    # Read data
    data = src["Public/Groups/0/Datasets/0-AScanAmplitude"][:]  # (51, 1, 560) int16

    # Read amplitude dataset dimensions info
    amp_ds_info = groups_info["datasets"][0]
    dims_info = amp_ds_info["dimensions"]

    # Find axis info
    v_dim = None
    u_dim = None
    time_dim = None
    for d in dims_info:
        if d["axis"] == "UCoordinate":
            u_dim = d
        elif d["axis"] == "VCoordinate":
            v_dim = d
        elif d["axis"] == "Ultrasound":
            time_dim = d

    # NDE parameters
    digitizing_freq = proc["digitizingFrequency"]  # 100e6
    compression = proc["ascanCompressionFactor"]  # 1
    ascan_sample_rate = digitizing_freq / compression  # 100e6
    time_scale = 1.0 / ascan_sample_rate  # 1e-8
    gain_db = proc["gain"]  # 57.0 dB
    rect = proc["rectification"]  # "None"
    beam = proc["beams"][0]
    ascan_start = beam["ascanStart"]  # 5.98e-06

    # TOFD specific
    tofd_info = proc["tofd"]
    pulser_probe_id = tofd_info["pulserProbeId"]
    receiver_probe_id = tofd_info["receiverProbeId"]
    pcs = tofd_info["pcs"]  # 0.036267

    # Probe info
    probe_infos = {}
    for p in setup["probes"]:
        probe_infos[p["id"]] = p

    # Wedge info
    wedge_infos = {}
    for w in setup["wedges"]:
        wedge_infos[w["id"]] = w

    pulser_probe = probe_infos.get(pulser_probe_id)
    receiver_probe = probe_infos.get(receiver_probe_id)

    # Get wedge associations
    pulser_wedge = None
    receiver_wedge = None
    if pulser_probe and "wedgeAssociation" in pulser_probe:
        pulser_wedge = wedge_infos.get(pulser_probe["wedgeAssociation"]["wedgeId"])
    if receiver_probe and "wedgeAssociation" in receiver_probe:
        receiver_wedge = wedge_infos.get(receiver_probe["wedgeAssociation"]["wedgeId"])

    # Specimen info
    specimen = setup["specimens"][0]
    pipe_geo = specimen.get("pipeGeometry", {})
    material = pipe_geo.get("material", {})

    v_long = material.get("longitudinalWave", {}).get("nominalVelocity", 5890.0)
    v_shear = material.get("transversalVerticalWave", {}).get("nominalVelocity", 3240.0)
    density = material.get("density", 7800.0)

    # Pipe (cylinder) dimensions
    if "pipeGeometry" in specimen:
        pipe = specimen["pipeGeometry"]
        cylinder_dims = [pipe.get("length", 0.3), pipe.get("outerRadius", 0.15), pipe.get("thickness", 0.01)]
    else:
        cylinder_dims = [0.3, 0.15, 0.01]

    # ── Build ONDE file ──
    dst = h5py.File(dst_path, "w")

    # Root attributes
    dst.attrs["ONDE:FILETYPE"] = "ONDE_UT"
    dst.attrs["ONDE:VERSION"] = "0.9.0"

    # ── Dimension groups ──
    v_offset = v_dim.get("offset", 0.00013335) if v_dim else 0.00013335
    v_scale = v_dim.get("resolution", 0.001) if v_dim else 0.001
    dim_v = create_dimension(dst, "dim_v", "V", "meters", v_offset, v_scale)

    u_offset = u_dim.get("offset", 0.00013335) if u_dim else 0.00013335
    u_scale = u_dim.get("resolution", 0.001) if u_dim else 0.001
    dim_u = create_dimension(dst, "dim_u", "U", "meters", u_offset, u_scale)

    dim_time = create_dimension(dst, "dim_time", "Time", "seconds", ascan_start, time_scale)

    dim_amp = create_dimension(dst, "dim_amp", "Amplitude", "arbitrary", 0.0, 1.0)

    # ── Coupling groups (two wedges: pulser and receiver) ──
    # Pulser wedge
    pulser_wedge_v_long = pulser_wedge["angleBeamWedge"]["longitudinalVelocity"] if pulser_wedge else 2330.0
    pulser_wedge_angle = pulser_wedge["angleBeamWedge"]["mountingLocations"][0]["wedgeAngle"] if pulser_wedge else 0.0

    coupling_pulser = dst.create_group("ONDE_COUPLING_0")
    set_attr(coupling_pulser, "ONDE:TYPE", ["ONDE_UT_COUPLING", "ONDE_WEDGE", "ONDE_SINGLE_WEDGE"])
    set_attr(coupling_pulser, "ONDE_UT_COUPLING:MEDIUM_VELOCITY", [pulser_wedge_v_long, pulser_wedge_v_long / 2.0])
    set_attr(coupling_pulser, "ONDE_UT_COUPLING:INCIDENCE_ANGLE", pulser_wedge_angle)
    if pulser_wedge:
        wd = pulser_wedge["angleBeamWedge"]
        set_attr(coupling_pulser, "ONDE_WEDGE:CONTACT_AREA",
                 [wd.get("width", 0.02054), wd.get("length", 0.02054), wd.get("height", 0.0127)])
        set_attr(coupling_pulser, "ONDE_WEDGE:HEIGHT", wd.get("height", 0.0127))
        set_attr(coupling_pulser, "ONDE_WEDGE:SKEW_ANGLE", 0.0)

    # Receiver wedge
    receiver_wedge_v_long = receiver_wedge["angleBeamWedge"]["longitudinalVelocity"] if receiver_wedge else 2330.0
    receiver_wedge_angle = receiver_wedge["angleBeamWedge"]["mountingLocations"][0]["wedgeAngle"] if receiver_wedge else 0.0

    coupling_receiver = dst.create_group("ONDE_COUPLING_1")
    set_attr(coupling_receiver, "ONDE:TYPE", ["ONDE_UT_COUPLING", "ONDE_WEDGE", "ONDE_SINGLE_WEDGE"])
    set_attr(coupling_receiver, "ONDE_UT_COUPLING:MEDIUM_VELOCITY", [receiver_wedge_v_long, receiver_wedge_v_long / 2.0])
    set_attr(coupling_receiver, "ONDE_UT_COUPLING:INCIDENCE_ANGLE", receiver_wedge_angle)
    if receiver_wedge:
        wd = receiver_wedge["angleBeamWedge"]
        set_attr(coupling_receiver, "ONDE_WEDGE:CONTACT_AREA",
                 [wd.get("width", 0.02054), wd.get("length", 0.02054), wd.get("height", 0.0127)])
        set_attr(coupling_receiver, "ONDE_WEDGE:HEIGHT", wd.get("height", 0.0127))
        set_attr(coupling_receiver, "ONDE_WEDGE:SKEW_ANGLE", 0.0)

    # ── Probe groups (two probes: pulser and receiver) ──
    pulser_freq = pulser_probe["conventionalRound"]["centralFrequency"] if pulser_probe else 10000000.0
    receiver_freq = receiver_probe["conventionalRound"]["centralFrequency"] if receiver_probe else 10000000.0

    probe_pulser = dst.create_group("ONDE_PROBE_0")
    set_attr(probe_pulser, "ONDE:TYPE", ["ONDE_UT_PROBE", "ONDE_MONO_UT_PROBE"])
    set_attr(probe_pulser, "ONDE:TYPE_TAGS", ["ONDE_UT_ELEMENTS"])
    set_attr(probe_pulser, "ONDE:LABEL",
             pulser_probe.get("model", "TOFD Pulser") if pulser_probe else "TOFD Pulser")
    set_attr(probe_pulser, "ONDE_UT_PROBE:FREQUENCY", pulser_freq)
    set_attr(probe_pulser, "ONDE_UT_PROBE:COUPLING", coupling_pulser.ref)

    probe_receiver = dst.create_group("ONDE_PROBE_1")
    set_attr(probe_receiver, "ONDE:TYPE", ["ONDE_UT_PROBE", "ONDE_MONO_UT_PROBE"])
    set_attr(probe_receiver, "ONDE:TYPE_TAGS", ["ONDE_UT_ELEMENTS"])
    set_attr(probe_receiver, "ONDE:LABEL",
             receiver_probe.get("model", "TOFD Receiver") if receiver_probe else "TOFD Receiver")
    set_attr(probe_receiver, "ONDE_UT_PROBE:FREQUENCY", receiver_freq)
    set_attr(probe_receiver, "ONDE_UT_PROBE:COUPLING", coupling_receiver.ref)

    # ── Component (Cylinder/Pipe) ──
    comp_grp = dst.create_group("ONDE_COMPONENT")
    set_attr(comp_grp, "ONDE:TYPE", ["ONDE_COMPONENT", "ONDE_CYLINDER"])
    set_attr(comp_grp, "ONDE_COMPONENT:VELOCITIES", [v_long, v_shear])
    set_attr(comp_grp, "ONDE_COMPONENT:DENSITY", density)
    set_attr(comp_grp, "ONDE_CYLINDER:DIMENSIONS", cylinder_dims)

    # ── Acquisition Trajectory (one per probe) ──
    traj_grp_0 = dst.create_group("ONDE_ACQUISITION_TRAJECTORY_0")
    set_attr(traj_grp_0, "ONDE:TYPE", ["ONDE_ACQUISITION_TRAJECTORY", "ONDE_TIME_TRAJECTORY"])

    traj_grp_1 = dst.create_group("ONDE_ACQUISITION_TRAJECTORY_1")
    set_attr(traj_grp_1, "ONDE:TYPE", ["ONDE_ACQUISITION_TRAJECTORY", "ONDE_TIME_TRAJECTORY"])

    # ── Geometric Setup ──
    geom_grp = dst.create_group("ONDE_GEOMETRIC_SETUP")
    set_attr(geom_grp, "ONDE:TYPE", ["ONDE_GEOMETRIC_SETUP"])
    geom_grp.create_dataset("COMPONENT", data=np.array([comp_grp.ref], dtype=h5py.ref_dtype))

    # PROBE_LIST: two probes
    probe_refs_arr = np.array([probe_pulser.ref, probe_receiver.ref], dtype=h5py.ref_dtype)
    geom_grp.create_dataset("PROBE_LIST", data=probe_refs_arr)

    # ACQUISITION_TRAJECTORY: two trajectories
    traj_refs_arr = np.array([traj_grp_0.ref, traj_grp_1.ref], dtype=h5py.ref_dtype)
    geom_grp.create_dataset("ACQUISITION_TRAJECTORY", data=traj_refs_arr)

    # PROBE_COORDINATE_FRAME: identity for both probes
    identity_frame = np.array([
        [0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0],
        [0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0],
    ], dtype=np.float64)
    geom_grp.create_dataset("PROBE_COORDINATE_FRAME", data=identity_frame)

    # ── Ultrasonic Setup ──
    us_grp = dst.create_group("ONDE_ULTRASONIC_SETUP")
    set_attr(us_grp, "ONDE:TYPE", ["ONDE_ULTRASONIC_SETUP"])
    set_attr(us_grp, "ONDE_ULTRASONIC_SETUP:RECTIFICATION", rectification_map(rect))
    set_attr(us_grp, "ONDE_ULTRASONIC_SETUP:ASCAN_SAMPLE_RATE", ascan_sample_rate)

    # GAIN: scalar dataset
    gain_linear = db_to_linear(gain_db)
    us_grp.create_dataset("GAIN", data=np.array([gain_linear], dtype=np.float64))

    # ASCAN_START: scalar dataset
    us_grp.create_dataset("ASCAN_START", data=np.array([ascan_start], dtype=np.float64))

    # ── Setup UT ──
    setup_grp = dst.create_group("ONDE_SETUP_UT")
    set_attr(setup_grp, "ONDE:TYPE", ["ONDE_SETUP", "ONDE_SETUP_UT"])
    set_attr(setup_grp, "ONDE_SETUP:GEOMETRIC_SETUP", geom_grp.ref)
    set_attr(setup_grp, "ONDE_SETUP_UT:ULTRASONIC_SETUP", us_grp.ref)

    # ── Dataset UT AScan ──
    ds_grp = dst.create_group("ONDE_DATASET_UT_ASCAN_0")
    set_attr(ds_grp, "ONDE:TYPE", ["ONDE_DATASET", "ONDE_DATASET_UT", "ONDE_DATASET_UT_ASCAN"])
    set_attr(ds_grp, "ONDE:LABEL", "Weld Plate TOFD AScan")
    set_attr(ds_grp, "ONDE_DATASET:SETUP", setup_grp.ref)

    # INDEX_DIMENSIONS = [dim_v, dim_u, dim_time]
    index_dims = make_ref_array([dim_v.ref, dim_u.ref, dim_time.ref])
    ds_grp.attrs["ONDE_DATASET:INDEX_DIMENSIONS"] = index_dims

    set_attr(ds_grp, "ONDE_DATASET:AMPLITUDE_DIMENSION", dim_amp.ref)

    # DATA
    ds_grp.create_dataset("DATA", data=data, dtype=data.dtype)

    dst.close()
    src.close()
    print(f"  ✓ Written: {dst_path}")


def main():
    os.makedirs(FIXTURES_DIR, exist_ok=True)

    # UT conversion
    convert_ut(
        src_path=os.path.join(FIXTURES_DIR, "Weld_Plate_UT-sk90-4.2.nde"),
        dst_path=os.path.join(OUTPUT_DIR, "real_ut_expected.onde"),
    )

    # PA conversion
    convert_pa(
        src_path=os.path.join(FIXTURES_DIR, "Weld_Plate_PA-Sect_sk90-4.2.nde"),
        dst_path=os.path.join(OUTPUT_DIR, "real_pa_expected.onde"),
    )

    # TOFD conversion
    convert_tofd(
        src_path=os.path.join(FIXTURES_DIR, "Weld_Plate_ToFD_Parallel-4.2.nde"),
        dst_path=os.path.join(OUTPUT_DIR, "real_tofd_expected.onde"),
    )

    print("\nAll conversions complete!")


if __name__ == "__main__":
    main()

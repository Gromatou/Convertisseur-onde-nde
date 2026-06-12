#!/usr/bin/env python3
"""
Generate reference NDE and ONDE files for Total Focusing Method (TFM) testing.

This script creates:
  - tests/fixtures/reference_tfm.nde          (NDE input)
  - tests/fixtures/reference_tfm_expected.onde (expected ONDE output)

TFM specifics:
  - FMC acquisition with 64 elements (64×64 = 4096 elementary signals)
  - TFM reconstruction data as float32
  - Rectangular grid: Y × Z = 101 × 201 pixels
  - Data stored as TfmValue (float32, 101×201)

Usage: python3 tests/generate_reference_tfm.py
"""

import json
import math
import os
import sys

import h5py
import numpy as np

# ── Paths ─────────────────────────────────────────────────────────────────
FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
NDE_PATH = os.path.join(FIXTURES_DIR, "reference_tfm.nde")
ONDE_PATH = os.path.join(FIXTURES_DIR, "reference_tfm_expected.onde")

# ── Known parameters ─────────────────────────────────────────────────────
DIGITIZING_FREQUENCY = 100e6
ASCAN_COMPRESSION = 1                # no compression for FMC
EFFECTIVE_SAMPLE_RATE = DIGITIZING_FREQUENCY  # 100 MHz
TIME_RESOLUTION = 1.0 / EFFECTIVE_SAMPLE_RATE  # 10 ns
ASCAN_START = 0.0
ASCAN_LENGTH = 20e-6
NUM_SAMPLES = 2000
PROBE_FREQUENCY = 5e6
NUM_ELEMENTS = 64
ELEMENT_PITCH = 0.001

# TFM reconstruction grid
TFM_Y_QUANTITY = 101                  # number of Y pixels
TFM_Z_QUANTITY = 201                  # number of Z pixels
TFM_Y_RESOLUTION = 0.0002             # 0.2 mm per pixel
TFM_Z_RESOLUTION = 0.0002
TFM_Y_OFFSET = -0.010                 # -10 mm to +10 mm
TFM_Z_OFFSET = 0.005                  # 5 mm to 45 mm

SPECIMEN_LONG_VEL = 5920.0
SPECIMEN_SHEAR_VEL = 3230.0
PLATE_THICKNESS = 0.050


def make_tfm_data():
    """Create synthetic TFM data as float32: shape (TFM_Y_QUANTITY, TFM_Z_QUANTITY)."""
    y = np.linspace(0, TFM_Y_QUANTITY - 1, TFM_Y_QUANTITY) * TFM_Y_RESOLUTION + TFM_Y_OFFSET
    z = np.linspace(0, TFM_Z_QUANTITY - 1, TFM_Z_QUANTITY) * TFM_Z_RESOLUTION + TFM_Z_OFFSET
    Z, Y = np.meshgrid(z, y, indexing="ij")

    # Synthetic: a point reflector at (0, 0.025)
    cx, cy = 0.0, 0.025
    dist = np.sqrt((Y - cx) ** 2 + (Z - cy) ** 2)
    # Gaussian blob to simulate a reflector
    sigma = 0.002  # 2 mm spread
    data = np.exp(-0.5 * (dist / sigma) ** 2) * 100.0
    return data.T.astype(np.float32)  # shape (TFM_Y_QUANTITY, TFM_Z_QUANTITY)


def build_nde_setup_json():
    """Build the NDE Public/Setup JSON for TFM."""

    # FMC beams: 64 pulsers x 64 receivers = 4096 elementary acquisitions
    # In NDE, we store the TFM result as TfmValue
    fmc_beams = []
    for tx in range(NUM_ELEMENTS):
        for rx in range(NUM_ELEMENTS):
            fmc_beams.append({
                "id": tx * NUM_ELEMENTS + rx,
                "pulsers": [
                    {
                        "id": tx,
                        "elementId": tx,
                        "probeId": 0,
                        "waveformId": 0,
                    }
                ],
                "receivers": [
                    {
                        "id": rx,
                        "elementId": rx,
                        "probeId": 0,
                    }
                ],
            })

    elements = []
    for i in range(NUM_ELEMENTS):
        elements.append({
            "id": i,
            "pinId": i,
            "acquisitionUnitId": 0,
            "connectorName": f"CH{i+1}",
            "primaryIndex": i,
            "secondaryIndex": 0,
            "enabled": True,
        })

    return {
        "$schema": "./Setup-Schema-4.2.0.json",
        "version": "4.2.0",
        "scenario": "General Mapping",
        "groups": [
            {
                "id": 0,
                "name": "Group_0",
                "usage": "TFM Acquisition",
                "datasets": [
                    {
                        "id": 0,
                        "name": "0-TfmValue",
                        "dataClass": "TfmValue",
                        "storageMode": "Independent",
                        "dataValue": {
                            "min": 0.0,
                            "max": 100.0,
                            "unitMin": 0.0,
                            "unitMax": 100.0,
                            "unit": "Percent",
                        },
                        "path": "/Public/Groups/0/Datasets/0-TfmValue",
                        "dimensions": [
                            {
                                "axis": "UCoordinate",
                                "quantity": TFM_Y_QUANTITY,
                                "resolution": TFM_Y_RESOLUTION,
                                "offset": TFM_Y_OFFSET,
                                "name": "Row",
                            },
                            {
                                "axis": "VCoordinate",
                                "quantity": TFM_Z_QUANTITY,
                                "resolution": TFM_Z_RESOLUTION,
                                "offset": TFM_Z_OFFSET,
                                "name": "Col",
                            },
                            {
                                "axis": "WCoordinate",
                                "quantity": 1,
                                "resolution": 1.0,
                                "offset": 0,
                                "name": "Plane",
                            },
                        ],
                    }
                ],
                "processes": [
                    {
                        "id": 0,
                        "inputs": None,
                        "outputs": [
                            {
                                "id": 0,
                                "datasetId": 0,
                                "dataClass": "TfmValue",
                            }
                        ],
                        "dataMappingId": 0,
                        "implementation": "Hardware",
                        "totalFocusingMethod": {
                            "signalSource": "Real",
                            "gain": 0,
                            "referenceAmplitude": 100.0,
                            "referenceGain": 0,
                            "rectangularGrid": {
                                "yImagingLimits": {
                                    "min": TFM_Y_OFFSET,
                                    "max": TFM_Y_OFFSET + TFM_Y_QUANTITY * TFM_Y_RESOLUTION,
                                    "resolution": TFM_Y_RESOLUTION,
                                },
                                "zImagingLimits": {
                                    "min": TFM_Z_OFFSET,
                                    "max": TFM_Z_OFFSET + TFM_Z_QUANTITY * TFM_Z_RESOLUTION,
                                    "resolution": TFM_Z_RESOLUTION,
                                },
                            },
                            "fmcPulserIds": list(range(NUM_ELEMENTS)),
                            "fmcReceiverIds": list(range(NUM_ELEMENTS)),
                            "pathName": "TT",
                            "waveSet": {
                                "pulsings": ["Longitudinal"],
                                "receivings": ["Longitudinal"],
                            },
                            "columns": [
                                {
                                    "id": 0,
                                    "gainMap": {
                                        "points": [
                                            {"position": 0.0, "gain": 0.0},
                                        ]
                                    },
                                }
                            ],
                        },
                    }
                ],
            }
        ],
        "probes": [
            {
                "id": 0,
                "model": "TFM Linear Probe",
                "serialNumber": "TFM-SN-001",
                "serie": "Standard",
                "phasedArrayLinear": {
                    "centralFrequency": PROBE_FREQUENCY,
                    "elements": elements,
                    "primaryAxis": {
                        "elementGap": ELEMENT_PITCH,
                        "elementQuantity": NUM_ELEMENTS,
                        "elementLength": 0.010,
                        "referencePoint": 0,
                        "casingLength": 0.065,
                    },
                    "secondaryAxis": {
                        "elementGap": ELEMENT_PITCH * 0.8,
                        "elementQuantity": 1,
                        "elementLength": ELEMENT_PITCH * 0.8,
                        "referencePoint": 0,
                    },
                },
                "wedgeAssociation": {
                    "wedgeId": 0,
                    "mountingLocationId": 0,
                },
            }
        ],
        "wedges": [
            {
                "id": 0,
                "model": "Direct Contact",
                "serialNumber": "N/A",
                "serie": "Standard",
                "angleBeamWedge": {
                    "width": 0.020,
                    "height": 0.005,
                    "length": 0.030,
                    "longitudinalVelocity": 2330.0,
                    "mountingLocations": [
                        {
                            "id": 0,
                            "wedgeAngle": 0,
                            "squintAngle": 0,
                            "roofAngle": 0,
                            "primaryOffset": 0,
                            "secondaryOffset": 0,
                            "tertiaryOffset": 0,
                        }
                    ],
                    "pocketDepth": 0,
                },
                "positioning": {
                    "specimenId": 0,
                    "surfaceId": 0,
                    "uCoordinateOffset": 0,
                    "vCoordinateOffset": 0,
                    "skewAngle": 0,
                },
            }
        ],
        "specimens": [
            {
                "id": 0,
                "plateGeometry": {
                    "width": 0.1,
                    "length": 0.2,
                    "thickness": PLATE_THICKNESS,
                    "material": {
                        "name": "Steel",
                        "longitudinalWave": {
                            "nominalVelocity": SPECIMEN_LONG_VEL,
                        },
                        "transversalVerticalWave": {
                            "nominalVelocity": SPECIMEN_SHEAR_VEL,
                        },
                    },
                    "surfaces": [
                        {"id": 0, "name": "Top"},
                        {"id": 1, "name": "Bottom"},
                    ],
                }
            }
        ],
        "acquisitionUnits": [
            {
                "id": 0,
                "platform": "OmniScan",
                "model": "MX2",
                "serialNumber": "MX2-003",
                "name": "Main Unit",
                "acquisitionRate": 60,
            }
        ],
        "motionDevices": [
            {
                "id": 0,
                "name": "Static",
                "encoder": {
                    "serialNumber": "ENC-001",
                    "mode": "Quadrature",
                    "stepResolution": 0.001,
                    "preset": 0,
                    "inverted": False,
                },
            }
        ],
        "dataMappings": [
            {
                "id": 0,
                "specimenId": 0,
                "surfaceId": 0,
                "discreteGrid": {
                    "scanPattern": "OneLineScan",
                    "uCoordinateOrientation": "Length",
                    "dimensions": [
                        {
                            "axis": "UCoordinate",
                            "quantity": 1,
                            "resolution": 1.0,
                            "offset": 0,
                            "name": "U",
                        }
                    ],
                },
            }
        ],
    }


# ═══════════════════════════════════════════════════════════════════════════
#  NDE file creation
# ═══════════════════════════════════════════════════════════════════════════

def write_nde_file():
    """Create the NDE reference file for TFM."""
    os.makedirs(FIXTURES_DIR, exist_ok=True)
    tfm_data = make_tfm_data()  # shape (TFM_Y_QUANTITY, TFM_Z_QUANTITY)

    with h5py.File(NDE_PATH, "w") as f:
        # ── /Properties ────────────────────────────────────────────────
        props = {
            "$schema": "./Properties-Schema-4.2.0.json",
            "methods": ["UT"],
            "file": {
                "formatVersion": "4.2.0",
                "description": "Reference TFM file for converter testing",
            },
        }
        f.create_dataset("Properties", data=json.dumps(props, indent=2))

        # ── /Public/Setup ──────────────────────────────────────────────
        setup = build_nde_setup_json()
        f.create_dataset("Public/Setup", data=json.dumps(setup, indent=2))

        # ── /Public/Groups/0/Datasets/0-TfmValue ───────────────────────
        f.create_dataset(
            "Public/Groups/0/Datasets/0-TfmValue",
            data=tfm_data,
            dtype=np.float32,
        )

    print(f"  ✓ Created NDE file: {NDE_PATH}")


# ═══════════════════════════════════════════════════════════════════════════
#  ONDE file creation
# ═══════════════════════════════════════════════════════════════════════════

def set_ref_attr(obj, name, refs):
    """Set an attribute containing one or more HDF5 object references."""
    if not isinstance(refs, list):
        refs = [refs]
    ref_dtype = h5py.special_dtype(ref=h5py.Reference)
    arr = np.empty(len(refs), dtype=object)
    for i, r in enumerate(refs):
        arr[i] = r
    obj.attrs.create(name, arr, dtype=ref_dtype)


def write_onde_file():
    """Create the expected ONDE output file for TFM."""
    tfm_data = make_tfm_data()

    with h5py.File(ONDE_PATH, "w") as f:
        # ── Root attributes ────────────────────────────────────────────
        f.attrs["ONDE:FILETYPE"] = "ONDE_UT"
        f.attrs["ONDE:VERSION"] = "0.9.0"

        # ═══════════════════════════════════════════════════════════════
        #  ONDE_DIMENSION groups (for TScan: Row, Col, Plane)
        # ═══════════════════════════════════════════════════════════════

        dim_row = f.create_group("dim_row")
        dim_row.attrs["ONDE:TYPE"] = np.array(["ONDE_DIMENSION"], dtype="S16")
        dim_row.attrs["ONDE_DIMENSION:COORDINATE"] = "Row"
        dim_row.attrs["ONDE_DIMENSION:UNITS"] = "meters"
        dim_row.attrs["ONDE_DIMENSION:OFFSET"] = TFM_Y_OFFSET
        dim_row.attrs["ONDE_DIMENSION:SCALE"] = TFM_Y_RESOLUTION

        dim_col = f.create_group("dim_col")
        dim_col.attrs["ONDE:TYPE"] = np.array(["ONDE_DIMENSION"], dtype="S16")
        dim_col.attrs["ONDE_DIMENSION:COORDINATE"] = "Col"
        dim_col.attrs["ONDE_DIMENSION:UNITS"] = "meters"
        dim_col.attrs["ONDE_DIMENSION:OFFSET"] = TFM_Z_OFFSET
        dim_col.attrs["ONDE_DIMENSION:SCALE"] = TFM_Z_RESOLUTION

        dim_plane = f.create_group("dim_plane")
        dim_plane.attrs["ONDE:TYPE"] = np.array(["ONDE_DIMENSION"], dtype="S16")
        dim_plane.attrs["ONDE_DIMENSION:COORDINATE"] = "Plane"
        dim_plane.attrs["ONDE_DIMENSION:UNITS"] = "arbitrary"
        dim_plane.attrs["ONDE_DIMENSION:OFFSET"] = 0.0
        dim_plane.attrs["ONDE_DIMENSION:SCALE"] = 1.0

        dim_amp = f.create_group("dim_amp")
        dim_amp.attrs["ONDE:TYPE"] = np.array(["ONDE_DIMENSION"], dtype="S16")
        dim_amp.attrs["ONDE_DIMENSION:COORDINATE"] = "Amplitude"
        dim_amp.attrs["ONDE_DIMENSION:UNITS"] = "arbitrary"
        dim_amp.attrs["ONDE_DIMENSION:OFFSET"] = 0.0
        dim_amp.attrs["ONDE_DIMENSION:SCALE"] = 1.0

        # ═══════════════════════════════════════════════════════════════
        #  ONDE_UT_COUPLING / ONDE_SINGLE_WEDGE
        # ═══════════════════════════════════════════════════════════════
        coupling = f.create_group("ONDE_COUPLING_0")
        coupling.attrs["ONDE:TYPE"] = np.array(
            ["ONDE_UT_COUPLING", "ONDE_WEDGE", "ONDE_SINGLE_WEDGE"], dtype="S24"
        )
        coupling.attrs["ONDE_UT_COUPLING:MEDIUM_VELOCITY"] = np.float64(
            [2330.0, 1165.0]
        )
        coupling.attrs["ONDE_UT_COUPLING:INCIDENCE_ANGLE"] = np.float64(0.0)
        coupling.attrs["ONDE_WEDGE:HEIGHT"] = np.float64(0.005)
        coupling.attrs["ONDE_WEDGE:CONTACT_AREA"] = np.float64([0.020, 0.025, 0.030])
        coupling.attrs["ONDE_WEDGE:SKEW_ANGLE"] = np.float64(0.0)

        # ═══════════════════════════════════════════════════════════════
        #  ONDE_UT_PROBE / ONDE_LINEAR_UT_PROBE
        # ═══════════════════════════════════════════════════════════════
        probe = f.create_group("ONDE_PROBE_0")
        probe.attrs["ONDE:TYPE"] = np.array(
            ["ONDE_UT_PROBE", "ONDE_LINEAR_UT_PROBE"], dtype="S24"
        )
        probe.attrs["ONDE:TYPE_TAGS"] = np.array(["ONDE_UT_ELEMENTS"], dtype="S18")
        probe.attrs["ONDE:LABEL"] = "TFM Linear Probe"
        probe.attrs["ONDE_UT_PROBE:FREQUENCY"] = np.float64(PROBE_FREQUENCY)
        probe.attrs["ONDE_LINEAR_UT_PROBE:TOTAL_NUMBER_OF_ELEMENTS"] = np.int32(
            NUM_ELEMENTS
        )
        probe.attrs["ONDE_LINEAR_UT_PROBE:ELEMENT_DIM_MAJOR"] = np.float64(0.010)
        probe.attrs["ONDE_LINEAR_UT_PROBE:ELEMENT_DIM_MINOR"] = np.float64(
            ELEMENT_PITCH * 0.8
        )
        probe.attrs["ONDE_LINEAR_UT_PROBE:ELEMENT_PITCH_DIM_MAJOR"] = np.float64(
            ELEMENT_PITCH
        )
        probe.attrs["ONDE_UT_PROBE:COUPLING"] = coupling.ref

        # ═══════════════════════════════════════════════════════════════
        #  ONDE_COMPONENT / ONDE_PLANE
        # ═══════════════════════════════════════════════════════════════
        component = f.create_group("ONDE_COMPONENT")
        component.attrs["ONDE:TYPE"] = np.array(
            ["ONDE_COMPONENT", "ONDE_PLANE"], dtype="S18"
        )
        component.attrs["ONDE_COMPONENT:VELOCITIES"] = np.float64(
            [SPECIMEN_LONG_VEL, SPECIMEN_SHEAR_VEL]
        )
        component.attrs["ONDE_PLANE:PLATE_DIMENSIONS"] = np.float64(
            [1.0, 1.0, PLATE_THICKNESS]
        )
        component.attrs["ONDE_COMPONENT:DENSITY"] = np.float64(7800.0)

        # ═══════════════════════════════════════════════════════════════
        #  ONDE_ACQUISITION_TRAJECTORY
        # ═══════════════════════════════════════════════════════════════
        traj = f.create_group("ONDE_ACQUISITION_TRAJECTORY_0")
        traj.attrs["ONDE:TYPE"] = np.array(
            ["ONDE_ACQUISITION_TRAJECTORY", "ONDE_TIME_TRAJECTORY"], dtype="S30"
        )

        # ═══════════════════════════════════════════════════════════════
        #  ONDE_GEOMETRIC_SETUP
        # ═══════════════════════════════════════════════════════════════
        geom = f.create_group("ONDE_GEOMETRIC_SETUP")
        geom.attrs["ONDE:TYPE"] = np.array(["ONDE_GEOMETRIC_SETUP"], dtype="S22")
        set_ref_attr(geom, "ONDE_GEOMETRIC_SETUP:PROBE_LIST", [probe.ref])
        set_ref_attr(
            geom, "ONDE_GEOMETRIC_SETUP:ACQUISITION_TRAJECTORY", [traj.ref]
        )
        geom.create_dataset(
            "COMPONENT",
            data=np.array(
                [component.ref], dtype=h5py.special_dtype(ref=h5py.Reference)
            ),
        )

        # ═══════════════════════════════════════════════════════════════
        #  ONDE_ULTRASONIC_SETUP
        # ═══════════════════════════════════════════════════════════════
        us = f.create_group("ONDE_ULTRASONIC_SETUP")
        us.attrs["ONDE:TYPE"] = np.array(["ONDE_ULTRASONIC_SETUP"], dtype="S23")
        us.attrs["ONDE_ULTRASONIC_SETUP:RECTIFICATION"] = "FULL_WAVE"
        us.attrs["ONDE_ULTRASONIC_SETUP:ASCAN_SAMPLE_RATE"] = np.float64(
            EFFECTIVE_SAMPLE_RATE
        )
        us.create_dataset("GAIN", data=np.float64([1.0]))
        us.create_dataset("ASCAN_START", data=np.float64([ASCAN_START]))

        # ═══════════════════════════════════════════════════════════════
        #  ONDE_PHASED_ARRAY_SETUP / ONDE_PHASED_ARRAY_FMC
        # ═══════════════════════════════════════════════════════════════
        pa_setup = f.create_group("ONDE_PHASED_ARRAY_SETUP")
        pa_setup.attrs["ONDE:TYPE"] = np.array(
            ["ONDE_PHASED_ARRAY_SETUP", "ONDE_PHASED_ARRAY_FMC"], dtype="S28"
        )
        pa_setup.attrs["ONDE_PHASED_ARRAY_SETUP:EMITTER_PROBE"] = probe.ref
        pa_setup.attrs["ONDE_PHASED_ARRAY_SETUP:RECEIVING_PROBE"] = probe.ref
        pa_setup.attrs["ONDE_PHASED_ARRAY_SETUP:SEQUENCE_ANGLE_MODE"] = "L"

        # ═══════════════════════════════════════════════════════════════
        #  ONDE_SETUP_UT
        # ═══════════════════════════════════════════════════════════════
        setup = f.create_group("ONDE_SETUP_UT")
        setup.attrs["ONDE:TYPE"] = np.array(
            ["ONDE_SETUP", "ONDE_SETUP_UT"], dtype="S16"
        )
        set_ref_attr(setup, "ONDE_SETUP:GEOMETRIC_SETUP", geom.ref)
        set_ref_attr(setup, "ONDE_SETUP_UT:ULTRASONIC_SETUP", us.ref)

        # ═══════════════════════════════════════════════════════════════
        #  ONDE_DATASET_UT_TSCAN (TFM data group)
        # ═══════════════════════════════════════════════════════════════
        ds_group = f.create_group("ONDE_DATASET_UT_TSCAN_0")
        ds_group.attrs["ONDE:TYPE"] = np.array(
            ["ONDE_DATASET", "ONDE_DATASET_UT", "ONDE_DATASET_UT_TSCAN"],
            dtype="S24",
        )
        ds_group.attrs["ONDE:LABEL"] = "Reference TFM TScan"

        # SETUP reference
        set_ref_attr(ds_group, "ONDE_DATASET:SETUP", setup.ref)

        # DATA: float32 2D grid (Row, Col)
        ds_group.create_dataset("DATA", data=tfm_data, dtype=np.float32)

        # INDEX_DIMENSIONS: [Row, Col, Plane]
        set_ref_attr(
            ds_group,
            "ONDE_DATASET:INDEX_DIMENSIONS",
            [dim_row.ref, dim_col.ref, dim_plane.ref],
        )

        # AMPLITUDE_DIMENSION
        set_ref_attr(ds_group, "ONDE_DATASET:AMPLITUDE_DIMENSION", dim_amp.ref)

        # ZONE_FRAME (TScan-specific)
        ds_group.attrs["ONDE_DATASET_UT_TSCAN:ZONE_FRAME"] = np.float64(
            [0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0]
        )

        # ZONE_DIMENSION
        ds_group.attrs["ONDE_DATASET_UT_TSCAN:ZONE_DIMENSION"] = np.float64([
            TFM_Y_QUANTITY * TFM_Y_RESOLUTION,
            TFM_Z_QUANTITY * TFM_Z_RESOLUTION,
            1.0,
        ])

        # ZONE_SIZE
        ds_group.attrs["ONDE_DATASET_UT_TSCAN:ZONE_SIZE"] = np.int32([
            TFM_Y_QUANTITY,
            TFM_Z_QUANTITY,
            1,
        ])

    print(f"  ✓ Created ONDE file: {ONDE_PATH}")


# ═══════════════════════════════════════════════════════════════════════════
#  Verification
# ═══════════════════════════════════════════════════════════════════════════

def verify_files():
    """Quick verification that both files exist and have expected content."""
    errors = []

    # Check NDE file
    with h5py.File(NDE_PATH, "r") as f:
        props = json.loads(f["Properties"][()])
        if "UT" not in props.get("methods", []):
            errors.append("NDE /Properties missing methods: ['UT']")

        data_ds = f["Public/Groups/0/Datasets/0-TfmValue"]
        expected_shape = (TFM_Y_QUANTITY, TFM_Z_QUANTITY)
        if data_ds.shape != expected_shape:
            errors.append(
                f"NDE data shape mismatch: {data_ds.shape} != {expected_shape}"
            )
        if data_ds.dtype != np.float32:
            errors.append(f"NDE data dtype mismatch: {data_ds.dtype}")

    # Check ONDE file
    with h5py.File(ONDE_PATH, "r") as f:
        if f.attrs.get("ONDE:FILETYPE") != "ONDE_UT":
            errors.append("ONDE root missing ONDE:FILETYPE")
        if f.attrs.get("ONDE:VERSION") != "0.9.0":
            errors.append("ONDE root missing ONDE:VERSION")

        required_groups = [
            "ONDE_DATASET_UT_TSCAN_0",
            "ONDE_SETUP_UT",
            "ONDE_GEOMETRIC_SETUP",
            "ONDE_ULTRASONIC_SETUP",
            "ONDE_COMPONENT",
            "ONDE_PROBE_0",
            "ONDE_COUPLING_0",
            "ONDE_PHASED_ARRAY_SETUP",
        ]
        for g in required_groups:
            if g not in f:
                errors.append(f"ONDE missing group: {g}")

        # Check data
        dsg = f["ONDE_DATASET_UT_TSCAN_0"]
        if "DATA" not in dsg:
            errors.append("ONDE dataset missing DATA")
        elif dsg["DATA"].shape != (TFM_Y_QUANTITY, TFM_Z_QUANTITY):
            errors.append(
                f"ONDE DATA shape mismatch: {dsg['DATA'].shape}"
            )
        elif dsg["DATA"].dtype != np.float32:
            errors.append(f"ONDE DATA dtype mismatch: {dsg['DATA'].dtype}")

        # Check TScan-specific attributes
        for attr_name in [
            "ONDE_DATASET_UT_TSCAN:ZONE_FRAME",
            "ONDE_DATASET_UT_TSCAN:ZONE_DIMENSION",
            "ONDE_DATASET_UT_TSCAN:ZONE_SIZE",
        ]:
            if attr_name not in dsg.attrs:
                errors.append(f"ONDE TScan missing attribute: {attr_name}")

        # Check GAIN is dataset
        usg = f["ONDE_ULTRASONIC_SETUP"]
        if "GAIN" not in usg:
            errors.append("ONDE GAIN missing (should be dataset)")
        if "ASCAN_START" not in usg:
            errors.append("ONDE ASCAN_START missing (should be dataset)")

        # Check ONDE:TYPE chain
        type_attr = dsg.attrs.get("ONDE:TYPE")
        expected = ["ONDE_DATASET", "ONDE_DATASET_UT", "ONDE_DATASET_UT_TSCAN"]
        decoded = [t.decode() if isinstance(t, bytes) else t for t in type_attr]
        if decoded != expected:
            errors.append(f"ONDE dataset ONDE:TYPE mismatch: {decoded}")

    if errors:
        print(f"  ✗ Verification failed ({len(errors)} errors):")
        for e in errors:
            print(f"    - {e}")
        return False
    print("  ✓ Verification passed")
    return True


# ═══════════════════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════════════════

def main():
    print("Generating reference files for Total Focusing Method (TFM)...")
    write_nde_file()
    write_onde_file()
    if verify_files():
        print("\nDone. Both files created successfully.")
    else:
        print("\nDone with verification errors.")
        sys.exit(1)


if __name__ == "__main__":
    main()

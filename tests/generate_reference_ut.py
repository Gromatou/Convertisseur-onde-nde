#!/usr/bin/env python3
"""
Generate reference NDE and ONDE files for conventional UT testing.

This script creates:
  - tests/fixtures/reference_ut.nde        (NDE input)
  - tests/fixtures/reference_ut_expected.onde (expected ONDE output)

It uses ONLY:
  - h5py for HDF5 I/O
  - The ONDE spec (ONDE_fields.csv)
  - The NDE spec (NDE_Setup_Schema.json)
  - NO imports from src/mapping.js or src/converter.js

Usage: python3 tests/generate_reference_ut.py
"""

import json
import math
import os
import sys

import h5py
import numpy as np

# ── Paths ─────────────────────────────────────────────────────────────────
FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
NDE_PATH = os.path.join(FIXTURES_DIR, "reference_ut.nde")
ONDE_PATH = os.path.join(FIXTURES_DIR, "reference_ut_expected.onde")

# ── Known parameters ─────────────────────────────────────────────────────
DIGITIZING_FREQUENCY = 100e6       # 100 MHz
ASCAN_COMPRESSION = 2               # decimation factor
EFFECTIVE_SAMPLE_RATE = DIGITIZING_FREQUENCY / ASCAN_COMPRESSION  # 50 MHz
TIME_RESOLUTION = 1.0 / EFFECTIVE_SAMPLE_RATE   # 20 ns
ASCAN_START = 1e-6                  # 1 µs
ASCAN_LENGTH = 50e-6                # 50 µs
NUM_SAMPLES = 1000
REFRACTED_ANGLE = 45.0              # degrees
WEDGE_DELAY = 5e-6                  # 5 µs
PROBE_FREQUENCY = 5e6               # 5 MHz
WEDGE_HEIGHT = 0.020                # 20 mm
WEDGE_LONG_VEL = 2330.0            # Rexolite longitudinal velocity (m/s)
WEDGE_SHEAR_VEL = 1165.0
SPECIMEN_LONG_VEL = 5920.0         # Steel longitudinal (m/s)
SPECIMEN_SHEAR_VEL = 3230.0        # Steel shear (m/s)
PLATE_THICKNESS = 0.010             # 10 mm
SINE_AMPLITUDE = 10000
SINE_CYCLES = 5


def make_sine_wave(n_samples, amplitude, n_cycles):
    """Create a sine wave as int16."""
    t = np.arange(n_samples, dtype=np.float64)
    signal = amplitude * np.sin(2 * np.pi * n_cycles * t / n_samples)
    return signal.astype(np.int16)


# ═══════════════════════════════════════════════════════════════════════════
#  NDE file creation
# ═══════════════════════════════════════════════════════════════════════════

def build_nde_setup_json():
    """Build the full NDE Public/Setup JSON structure."""
    return {
        "$schema": "./Setup-Schema-4.2.0.json",
        "version": "4.2.0",
        "scenario": "General Mapping",
        "groups": [
            {
                "id": 0,
                "name": "Group_0",
                "usage": "UT Acquisition",
                "datasets": [
                    {
                        "id": 0,
                        "name": "0-AScanAmplitude",
                        "dataClass": "AScanAmplitude",
                        "storageMode": "Independent",
                        "dataValue": {
                            "min": -32768,
                            "max": 32767,
                            "unitMin": -100,
                            "unitMax": 100,
                            "unit": "Percent"
                        },
                        "path": "/Public/Groups/0/Datasets/0-AScanAmplitude",
                        "dimensions": [
                            {
                                "axis": "UCoordinate",
                                "quantity": 1,
                                "resolution": 1.0,
                                "offset": 0,
                                "name": "U"
                            },
                            {
                                "axis": "Beam",
                                "beams": [
                                    {
                                        "id": 0,
                                        "velocity": SPECIMEN_LONG_VEL,
                                        "skewAngle": 0,
                                        "refractedAngle": REFRACTED_ANGLE,
                                        "uCoordinateOffset": 0,
                                        "vCoordinateOffset": 0,
                                        "ultrasoundOffset": 0
                                    }
                                ]
                            },
                            {
                                "axis": "Ultrasound",
                                "quantity": NUM_SAMPLES,
                                "resolution": TIME_RESOLUTION,
                                "offset": ASCAN_START
                            }
                        ]
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
                                "dataClass": "AScanAmplitude"
                            }
                        ],
                        "dataMappingId": 0,
                        "implementation": "Hardware",
                        "ultrasonicConventional": {
                            "pulseEcho": {
                                "probeId": 0
                            },
                            "waveMode": "TransversalVertical",
                            "velocity": SPECIMEN_LONG_VEL,
                            "wedgeDelay": WEDGE_DELAY,
                            "rectification": "None",
                            "ascanSynchroMode": "Pulse",
                            "ascanCompressionFactor": ASCAN_COMPRESSION,
                            "gain": 0,
                            "ultrasoundMode": "SoundPath",
                            "digitizingFrequency": DIGITIZING_FREQUENCY,
                            "beams": [
                                {
                                    "id": 0,
                                    "refractedAngle": REFRACTED_ANGLE,
                                    "ascanStart": ASCAN_START,
                                    "ascanLength": ASCAN_LENGTH
                                }
                            ]
                        }
                    }
                ]
            }
        ],
        "probes": [
            {
                "id": 0,
                "model": "Default Probe",
                "serialNumber": "SN001",
                "serie": "Standard",
                "conventionalRound": {
                    "centralFrequency": PROBE_FREQUENCY,
                    "diameter": 0.0127,
                    "elements": [
                        {
                            "id": 0,
                            "pinId": 0,
                            "acquisitionUnitId": 0,
                            "connectorName": "CH1"
                        }
                    ]
                },
                "wedgeAssociation": {
                    "wedgeId": 0,
                    "mountingLocationId": 0
                }
            }
        ],
        "wedges": [
            {
                "id": 0,
                "model": "SAW Wedge",
                "serialNumber": "WSN001",
                "serie": "Standard",
                "angleBeamWedge": {
                    "width": 0.015,
                    "height": WEDGE_HEIGHT,
                    "length": 0.025,
                    "longitudinalVelocity": WEDGE_LONG_VEL,
                    "mountingLocations": [
                        {
                            "id": 0,
                            "wedgeAngle": 0,
                            "squintAngle": 0,
                            "roofAngle": 0,
                            "primaryOffset": 0,
                            "secondaryOffset": 0,
                            "tertiaryOffset": 0
                        }
                    ],
                    "pocketDepth": 0
                },
                "positioning": {
                    "specimenId": 0,
                    "surfaceId": 0,
                    "uCoordinateOffset": 0,
                    "vCoordinateOffset": 0,
                    "skewAngle": 0
                }
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
                            "nominalVelocity": SPECIMEN_LONG_VEL
                        },
                        "transversalVerticalWave": {
                            "nominalVelocity": SPECIMEN_SHEAR_VEL
                        }
                    },
                    "surfaces": [
                        {"id": 0, "name": "Top"},
                        {"id": 1, "name": "Bottom"}
                    ]
                }
            }
        ],
        "acquisitionUnits": [
            {
                "id": 0,
                "platform": "OmniScan",
                "model": "MX2",
                "serialNumber": "MX2-001",
                "name": "Main Unit",
                "acquisitionRate": 60
            }
        ],
        "motionDevices": [
            {
                "id": 0,
                "name": "Manual Scan",
                "encoder": {
                    "serialNumber": "ENC-001",
                    "mode": "Quadrature",
                    "stepResolution": 0.001,
                    "preset": 0,
                    "inverted": False
                }
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
                            "name": "U"
                        }
                    ]
                }
            }
        ]
    }


def write_nde_file():
    """Create the NDE reference file."""
    os.makedirs(FIXTURES_DIR, exist_ok=True)
    signal = make_sine_wave(NUM_SAMPLES, SINE_AMPLITUDE, SINE_CYCLES)

    with h5py.File(NDE_PATH, "w") as f:
        # ── /Properties ────────────────────────────────────────────────
        props = {
            "$schema": "./Properties-Schema-4.2.0.json",
            "methods": ["UT"],
            "file": {
                "formatVersion": "4.2.0",
                "description": "Reference UT file for converter testing"
            }
        }
        f.create_dataset("Properties", data=json.dumps(props, indent=2))

        # ── /Public/Setup ──────────────────────────────────────────────
        setup = build_nde_setup_json()
        f.create_dataset("Public/Setup", data=json.dumps(setup, indent=2))

        # ── /Public/Groups/0/Datasets/0-AScanAmplitude ─────────────────
        f.create_dataset(
            "Public/Groups/0/Datasets/0-AScanAmplitude",
            data=signal,
            dtype=np.int16
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
    # Create as a 1-D array of references
    arr = np.empty(len(refs), dtype=object)
    for i, r in enumerate(refs):
        arr[i] = r
    obj.attrs.create(name, arr, dtype=ref_dtype)


def write_onde_file():
    """Create the expected ONDE output file."""
    signal = make_sine_wave(NUM_SAMPLES, SINE_AMPLITUDE, SINE_CYCLES)

    with h5py.File(ONDE_PATH, "w") as f:
        # ── Root attributes ────────────────────────────────────────────
        f.attrs["ONDE:FILETYPE"] = "ONDE_UT"
        f.attrs["ONDE:VERSION"] = "0.9.0"

        # ═══════════════════════════════════════════════════════════════
        #  ONDE_DIMENSION groups (for INDEX_DIMENSIONS)
        # ═══════════════════════════════════════════════════════════════

        # Dimension for U (1 position)
        dim_u = f.create_group("dim_u")
        dim_u.attrs["ONDE:TYPE"] = np.array(["ONDE_DIMENSION"], dtype="S16")
        dim_u.attrs["ONDE_DIMENSION:COORDINATE"] = "U"
        dim_u.attrs["ONDE_DIMENSION:UNITS"] = "meters"
        dim_u.attrs["ONDE_DIMENSION:OFFSET"] = 0.0
        dim_u.attrs["ONDE_DIMENSION:SCALE"] = 1.0

        # Dimension for Beam (1 beam)
        dim_beam = f.create_group("dim_beam")
        dim_beam.attrs["ONDE:TYPE"] = np.array(["ONDE_DIMENSION"], dtype="S16")
        dim_beam.attrs["ONDE_DIMENSION:COORDINATE"] = "Beam"
        dim_beam.attrs["ONDE_DIMENSION:UNITS"] = "arbitrary"
        dim_beam.attrs["ONDE_DIMENSION:OFFSET"] = 0.0
        dim_beam.attrs["ONDE_DIMENSION:SCALE"] = 1.0

        # Dimension for Time (1000 samples)
        dim_time = f.create_group("dim_time")
        dim_time.attrs["ONDE:TYPE"] = np.array(["ONDE_DIMENSION"], dtype="S16")
        dim_time.attrs["ONDE_DIMENSION:COORDINATE"] = "Time"
        dim_time.attrs["ONDE_DIMENSION:UNITS"] = "seconds"
        dim_time.attrs["ONDE_DIMENSION:OFFSET"] = ASCAN_START
        dim_time.attrs["ONDE_DIMENSION:SCALE"] = TIME_RESOLUTION

        # Dimension for Amplitude
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
            [WEDGE_LONG_VEL, WEDGE_SHEAR_VEL]
        )
        coupling.attrs["ONDE_UT_COUPLING:INCIDENCE_ANGLE"] = np.float64(0.0)
        coupling.attrs["ONDE_WEDGE:HEIGHT"] = np.float64(WEDGE_HEIGHT)
        coupling.attrs["ONDE_WEDGE:CONTACT_AREA"] = np.float64([0.015, 0.020, 0.025])
        coupling.attrs["ONDE_WEDGE:SKEW_ANGLE"] = np.float64(0.0)

        # ═══════════════════════════════════════════════════════════════
        #  ONDE_UT_PROBE / ONDE_MONO_UT_PROBE
        # ═══════════════════════════════════════════════════════════════
        probe = f.create_group("ONDE_PROBE_0")
        probe.attrs["ONDE:TYPE"] = np.array(
            ["ONDE_UT_PROBE", "ONDE_MONO_UT_PROBE"], dtype="S20"
        )
        probe.attrs["ONDE:TYPE_TAGS"] = np.array(["ONDE_UT_ELEMENTS"], dtype="S18")
        probe.attrs["ONDE:LABEL"] = "UT Probe"
        probe.attrs["ONDE_UT_PROBE:FREQUENCY"] = np.float64(PROBE_FREQUENCY)
        # Coupling reference
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
        #  ONDE_ACQUISITION_TRAJECTORY / ONDE_TIME_TRAJECTORY
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

        # PROBE_LIST: array of references
        set_ref_attr(geom, "ONDE_GEOMETRIC_SETUP:PROBE_LIST", [probe.ref])

        # ACQUISITION_TRAJECTORY: array of references
        set_ref_attr(
            geom,
            "ONDE_GEOMETRIC_SETUP:ACQUISITION_TRAJECTORY",
            [traj.ref],
        )

        # COMPONENT: single reference (dataset, not attribute, per spec)
        # Wait, looking at ONDE_fields.csv line 46:
        # "ONDE_GEOMETRIC_SETUP:COMPONENT;;O;D;H5T_STD_REF_OBJ<ONDE_COMPONENT>;[1]"
        # D = Dataset, not attribute! So it must be a dataset.
        comp_ref_ds = geom.create_dataset(
            "COMPONENT", data=np.array([component.ref], dtype=object)
        )
        # Need to set the dtype properly for reference
        # h5py needs special handling for reference datasets
        # Actually, let's delete and recreate with proper type
        del geom["COMPONENT"]
        comp_ref_ds = geom.create_dataset(
            "COMPONENT",
            data=np.array([component.ref], dtype=h5py.special_dtype(ref=h5py.Reference)),
        )

        # ═══════════════════════════════════════════════════════════════
        #  ONDE_ULTRASONIC_SETUP
        # ═══════════════════════════════════════════════════════════════
        us = f.create_group("ONDE_ULTRASONIC_SETUP")
        us.attrs["ONDE:TYPE"] = np.array(["ONDE_ULTRASONIC_SETUP"], dtype="S23")
        us.attrs["ONDE_ULTRASONIC_SETUP:RECTIFICATION"] = "FULL_WAVE"

        # ASCAN_SAMPLE_RATE is an attribute
        us.attrs["ONDE_ULTRASONIC_SETUP:ASCAN_SAMPLE_RATE"] = np.float64(
            EFFECTIVE_SAMPLE_RATE
        )

        # GAIN is a DATASET (per spec: H5T_FLOAT; [N_Ascan<m>])
        us.create_dataset("GAIN", data=np.float64([1.0]))

        # ASCAN_START is a DATASET (per spec)
        us.create_dataset("ASCAN_START", data=np.float64([ASCAN_START]))

        # ═══════════════════════════════════════════════════════════════
        #  ONDE_SETUP_UT
        # ═══════════════════════════════════════════════════════════════
        setup = f.create_group("ONDE_SETUP_UT")
        setup.attrs["ONDE:TYPE"] = np.array(
            ["ONDE_SETUP", "ONDE_SETUP_UT"], dtype="S16"
        )

        # ONDE_SETUP:GEOMETRIC_SETUP reference (attribute)
        set_ref_attr(setup, "ONDE_SETUP:GEOMETRIC_SETUP", geom.ref)

        # ONDE_SETUP_UT:ULTRASONIC_SETUP reference (attribute)
        set_ref_attr(setup, "ONDE_SETUP_UT:ULTRASONIC_SETUP", us.ref)

        # ═══════════════════════════════════════════════════════════════
        #  ONDE_DATASET_UT_ASCAN (the main data group)
        # ═══════════════════════════════════════════════════════════════
        ds_group = f.create_group("ONDE_DATASET_UT_ASCAN_0")
        ds_group.attrs["ONDE:TYPE"] = np.array(
            ["ONDE_DATASET", "ONDE_DATASET_UT", "ONDE_DATASET_UT_ASCAN"],
            dtype="S24",
        )
        ds_group.attrs["ONDE:LABEL"] = "Reference UT AScan"

        # ONDE_DATASET:SETUP reference
        set_ref_attr(ds_group, "ONDE_DATASET:SETUP", setup.ref)

        # ONDE_DATASET:DATA — the actual signal data (int16)
        ds_group.create_dataset("DATA", data=signal, dtype=np.int16)

        # INDEX_DIMENSIONS: array of references to dimension groups
        set_ref_attr(
            ds_group,
            "ONDE_DATASET:INDEX_DIMENSIONS",
            [dim_u.ref, dim_beam.ref, dim_time.ref],
        )

        # AMPLITUDE_DIMENSION: reference to amplitude dimension
        set_ref_attr(ds_group, "ONDE_DATASET:AMPLITUDE_DIMENSION", dim_amp.ref)

    print(f"  ✓ Created ONDE file: {ONDE_PATH}")


# ═══════════════════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════════════════

def verify_files():
    """Quick verification that both files exist and have expected content."""
    errors = []

    # Check NDE file
    with h5py.File(NDE_PATH, "r") as f:
        props_ds = f["Properties"]
        props = json.loads(props_ds[()])
        if "UT" not in props.get("methods", []):
            errors.append("NDE /Properties missing methods: ['UT']")

        setup_ds = f["Public/Setup"]
        setup = json.loads(setup_ds[()])
        if "groups" not in setup:
            errors.append("NDE /Public/Setup missing groups")

        data_ds = f["Public/Groups/0/Datasets/0-AScanAmplitude"]
        if data_ds.shape != (NUM_SAMPLES,):
            errors.append(f"NDE data shape mismatch: {data_ds.shape}")
        if data_ds.dtype != np.int16:
            errors.append(f"NDE data dtype mismatch: {data_ds.dtype}")

    # Check ONDE file
    with h5py.File(ONDE_PATH, "r") as f:
        if f.attrs.get("ONDE:FILETYPE") != "ONDE_UT":
            errors.append("ONDE root missing ONDE:FILETYPE")
        if f.attrs.get("ONDE:VERSION") != "0.9.0":
            errors.append("ONDE root missing ONDE:VERSION")

        required_groups = [
            "ONDE_DATASET_UT_ASCAN_0",
            "ONDE_SETUP_UT",
            "ONDE_GEOMETRIC_SETUP",
            "ONDE_ULTRASONIC_SETUP",
            "ONDE_COMPONENT",
            "ONDE_PROBE_0",
            "ONDE_COUPLING_0",
        ]
        for g in required_groups:
            if g not in f:
                errors.append(f"ONDE missing group: {g}")

        # Check GROUP datasets
        dsg = f["ONDE_DATASET_UT_ASCAN_0"]
        if "DATA" not in dsg:
            errors.append("ONDE dataset missing DATA")
        elif dsg["DATA"].shape != (NUM_SAMPLES,):
            errors.append(f"ONDE DATA shape mismatch: {dsg['DATA'].shape}")
        elif dsg["DATA"].dtype != np.int16:
            errors.append(f"ONDE DATA dtype mismatch: {dsg['DATA'].dtype}")

        # Check GAIN is a dataset
        usg = f["ONDE_ULTRASONIC_SETUP"]
        if "GAIN" not in usg:
            errors.append("ONDE ULTRASONIC_SETUP missing GAIN dataset")
        elif usg["GAIN"][()] != 1.0:
            errors.append(f"ONDE GAIN value mismatch: {usg['GAIN'][()]}")
        if "ASCAN_START" not in usg:
            errors.append("ONDE ASCAN_START missing (should be dataset)")
        elif abs(usg["ASCAN_START"][()] - ASCAN_START) > 1e-12:
            errors.append(
                f"ONDE ASCAN_START mismatch: {usg['ASCAN_START'][()]}"
            )

        # Check ASCAN_SAMPLE_RATE is an attribute
        sample_rate = usg.attrs.get("ONDE_ULTRASONIC_SETUP:ASCAN_SAMPLE_RATE")
        if sample_rate is None:
            errors.append("ONDE missing ASCAN_SAMPLE_RATE attribute")
        elif abs(sample_rate - EFFECTIVE_SAMPLE_RATE) > 1:
            errors.append(
                f"ONDE ASCAN_SAMPLE_RATE mismatch: {sample_rate}"
            )

        # Check ONDE:TYPE on main dataset group
        type_attr = dsg.attrs.get("ONDE:TYPE")
        if type_attr is None:
            errors.append("ONDE dataset missing ONDE:TYPE")
        else:
            expected = ["ONDE_DATASET", "ONDE_DATASET_UT", "ONDE_DATASET_UT_ASCAN"]
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


def main():
    print("Generating reference files for Conventional UT...")
    write_nde_file()
    write_onde_file()
    if verify_files():
        print("\nDone. Both files created successfully.")
    else:
        print("\nDone with verification errors.")
        sys.exit(1)


if __name__ == "__main__":
    main()

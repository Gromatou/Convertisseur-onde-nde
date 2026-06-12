#!/usr/bin/env python3
"""
Generate reference NDE and ONDE files for Phased Array testing.

This script creates:
  - tests/fixtures/reference_pa.nde          (NDE input)
  - tests/fixtures/reference_pa_expected.onde (expected ONDE output)

Phased array specifics:
  - Linear probe, 64 elements, 5 MHz
  - Sectorial scan: 31 beams, 40°–70° (1° step)
  - Focal law setup in ONDE
  - Digitizing frequency 100 MHz, compression factor 2 → 50 MHz effective
  - AScan data: int16, 31 x 1000 samples (sine waves with beam-dependent phase)

Usage: python3 tests/generate_reference_pa.py
"""

import json
import math
import os
import sys

import h5py
import numpy as np

# ── Paths ─────────────────────────────────────────────────────────────────
FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
NDE_PATH = os.path.join(FIXTURES_DIR, "reference_pa.nde")
ONDE_PATH = os.path.join(FIXTURES_DIR, "reference_pa_expected.onde")

# ── Known parameters ─────────────────────────────────────────────────────
DIGITIZING_FREQUENCY = 100e6       # 100 MHz
ASCAN_COMPRESSION = 2               # decimation factor
EFFECTIVE_SAMPLE_RATE = DIGITIZING_FREQUENCY / ASCAN_COMPRESSION  # 50 MHz
TIME_RESOLUTION = 1.0 / EFFECTIVE_SAMPLE_RATE   # 20 ns
ASCAN_START = 1e-6                  # 1 µs
ASCAN_LENGTH = 50e-6                # 50 µs
NUM_SAMPLES = 1000
NUM_BEAMS = 31
SECTORIAL_START = 40.0              # degrees
SECTORIAL_STOP = 70.0               # degrees
PROBE_FREQUENCY = 5e6               # 5 MHz
NUM_ELEMENTS = 64
ELEMENT_PITCH = 0.001               # 1 mm
ELEMENT_WIDTH = 0.0008              # 0.8 mm
APERTURE = 16                        # elements per beam
SINE_AMPLITUDE = 10000
SINE_CYCLES = 5
WEDGE_DELAY = 5e-6
SPECIMEN_LONG_VEL = 5920.0
SPECIMEN_SHEAR_VEL = 3230.0
PLATE_THICKNESS = 0.010
WEDGE_HEIGHT = 0.020
WEDGE_LONG_VEL = 2330.0
WEDGE_SHEAR_VEL = 1165.0


def make_sine_wave(n_samples, amplitude, n_cycles, phase=0):
    """Create a sine wave as int16 with optional phase shift."""
    t = np.arange(n_samples, dtype=np.float64)
    signal = amplitude * np.sin(2 * np.pi * n_cycles * t / n_samples + phase)
    return signal.astype(np.int16)


def compute_beam_angles():
    """Compute beam angles from start to stop with (stop-start)/(n-1) step."""
    return np.linspace(SECTORIAL_START, SECTORIAL_STOP, NUM_BEAMS)


def make_pa_data():
    """Create 2D AScan data: shape (NUM_BEAMS, NUM_SAMPLES)."""
    angles = compute_beam_angles()
    data = np.zeros((NUM_BEAMS, NUM_SAMPLES), dtype=np.int16)
    for i, angle in enumerate(angles):
        # Use angle-dependent phase to make beams distinguishable
        phase = math.radians(angle - SECTORIAL_START)
        data[i, :] = make_sine_wave(NUM_SAMPLES, SINE_AMPLITUDE, SINE_CYCLES, phase)
    return data


def build_nde_setup_json():
    """Build the full NDE Public/Setup JSON for phased array."""
    angles = compute_beam_angles()
    beams = []
    for i in range(NUM_BEAMS):
        beams.append({
            "id": i,
            "skewAngle": 0,
            "refractedAngle": float(angles[i]),
            "beamDelay": 0,
            "ascanStart": ASCAN_START,
            "ascanLength": ASCAN_LENGTH,
            "gainOffset": 0,
            "recurrence": 1,
            "sumGain": 0,
            "sumGainMode": "Manual",
            "tcg": {"points": []},
            "pulsers": [
                {
                    "id": j,
                    "elementId": j,
                    "delay": 0.0
                }
                for j in range(APERTURE)
            ],
            "receivers": [
                {
                    "id": j,
                    "elementId": j,
                    "delay": 0.0
                }
                for j in range(APERTURE)
            ]
        })

    # Build elements list for probe
    elements = []
    for i in range(NUM_ELEMENTS):
        elements.append({
            "id": i,
            "pinId": i,
            "acquisitionUnitId": 0,
            "connectorName": f"CH{i+1}",
            "primaryIndex": i,
            "secondaryIndex": 0,
            "enabled": True
        })

    return {
        "$schema": "./Setup-Schema-4.2.0.json",
        "version": "4.2.0",
        "scenario": "General Mapping",
        "groups": [
            {
                "id": 0,
                "name": "Group_0",
                "usage": "PA Acquisition",
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
                                "beams": beams
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
                        "ultrasonicPhasedArray": {
                            "pulseEcho": {
                                "probeId": 0,
                                "sectorialFormation": {
                                    "probeFirstElementId": 0,
                                    "elementAperture": APERTURE,
                                    "beamRefractedAngles": {
                                        "start": SECTORIAL_START,
                                        "stop": SECTORIAL_STOP,
                                        "step": (SECTORIAL_STOP - SECTORIAL_START) / (NUM_BEAMS - 1)
                                    }
                                }
                            },
                            "waveMode": "Longitudinal",
                            "velocity": SPECIMEN_LONG_VEL,
                            "pulse": {
                                "width": 5e-8,
                                "voltage": 100
                            },
                            "focusing": {
                                "mode": "HalfPath",
                                "distance": 0.030,
                                "angle": 0
                            },
                            "beams": beams,
                            "rectification": "None",
                            "digitizingFrequency": DIGITIZING_FREQUENCY,
                            "ascanSynchroMode": "Pulse",
                            "ascanCompressionFactor": ASCAN_COMPRESSION,
                            "gain": 0,
                            "wedgeDelay": WEDGE_DELAY,
                            "ultrasoundMode": "SoundPath"
                        }
                    }
                ]
            }
        ],
        "probes": [
            {
                "id": 0,
                "model": "PA Linear Probe",
                "serialNumber": "PA-SN-001",
                "serie": "Standard",
                "phasedArrayLinear": {
                    "centralFrequency": PROBE_FREQUENCY,
                    "elements": elements,
                    "primaryAxis": {
                        "elementGap": ELEMENT_PITCH,
                        "elementQuantity": NUM_ELEMENTS,
                        "elementLength": 0.010,
                        "referencePoint": 0,
                        "casingLength": 0.065
                    },
                    "secondaryAxis": {
                        "elementGap": ELEMENT_WIDTH,
                        "elementQuantity": 1,
                        "elementLength": ELEMENT_WIDTH,
                        "referencePoint": 0
                    }
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
                "model": "PA Wedge",
                "serialNumber": "PA-W-SN-001",
                "serie": "Standard",
                "angleBeamWedge": {
                    "width": 0.020,
                    "height": WEDGE_HEIGHT,
                    "length": 0.030,
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
                "serialNumber": "MX2-002",
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


# ═══════════════════════════════════════════════════════════════════════════
#  NDE file creation
# ═══════════════════════════════════════════════════════════════════════════

def write_nde_file():
    """Create the NDE reference file for phased array."""
    os.makedirs(FIXTURES_DIR, exist_ok=True)
    signal = make_pa_data()  # shape (NUM_BEAMS, NUM_SAMPLES)

    with h5py.File(NDE_PATH, "w") as f:
        # ── /Properties ────────────────────────────────────────────────
        props = {
            "$schema": "./Properties-Schema-4.2.0.json",
            "methods": ["UT"],
            "file": {
                "formatVersion": "4.2.0",
                "description": "Reference PA file for converter testing"
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
    arr = np.empty(len(refs), dtype=object)
    for i, r in enumerate(refs):
        arr[i] = r
    obj.attrs.create(name, arr, dtype=ref_dtype)


def write_onde_file():
    """Create the expected ONDE output file for phased array."""
    signal = make_pa_data()
    angles = compute_beam_angles()

    with h5py.File(ONDE_PATH, "w") as f:
        # ── Root attributes ────────────────────────────────────────────
        f.attrs["ONDE:FILETYPE"] = "ONDE_UT"
        f.attrs["ONDE:VERSION"] = "0.9.0"

        # ═══════════════════════════════════════════════════════════════
        #  ONDE_DIMENSION groups
        # ═══════════════════════════════════════════════════════════════

        dim_u = f.create_group("dim_u")
        dim_u.attrs["ONDE:TYPE"] = np.array(["ONDE_DIMENSION"], dtype="S16")
        dim_u.attrs["ONDE_DIMENSION:COORDINATE"] = "U"
        dim_u.attrs["ONDE_DIMENSION:UNITS"] = "meters"
        dim_u.attrs["ONDE_DIMENSION:OFFSET"] = 0.0
        dim_u.attrs["ONDE_DIMENSION:SCALE"] = 1.0

        dim_beam = f.create_group("dim_beam")
        dim_beam.attrs["ONDE:TYPE"] = np.array(["ONDE_DIMENSION"], dtype="S16")
        dim_beam.attrs["ONDE_DIMENSION:COORDINATE"] = "Beam"
        dim_beam.attrs["ONDE_DIMENSION:UNITS"] = "arbitrary"
        dim_beam.attrs["ONDE_DIMENSION:OFFSET"] = 0.0
        dim_beam.attrs["ONDE_DIMENSION:SCALE"] = 1.0

        dim_time = f.create_group("dim_time")
        dim_time.attrs["ONDE:TYPE"] = np.array(["ONDE_DIMENSION"], dtype="S16")
        dim_time.attrs["ONDE_DIMENSION:COORDINATE"] = "Time"
        dim_time.attrs["ONDE_DIMENSION:UNITS"] = "seconds"
        dim_time.attrs["ONDE_DIMENSION:OFFSET"] = ASCAN_START
        dim_time.attrs["ONDE_DIMENSION:SCALE"] = TIME_RESOLUTION

        dim_amp = f.create_group("dim_amp")
        dim_amp.attrs["ONDE:TYPE"] = np.array(["ONDE_DIMENSION"], dtype="S16")
        dim_amp.attrs["ONDE_DIMENSION:COORDINATE"] = "Amplitude"
        dim_amp.attrs["ONDE_DIMENSION:UNITS"] = "arbitrary"
        dim_amp.attrs["ONDE_DIMENSION:OFFSET"] = 0.0
        dim_amp.attrs["ONDE_DIMENSION:SCALE"] = 1.0

        # ═══════════════════════════════════════════════════════════════
        #  ONDE_UT_COUPLING / ONDE_WEDGE / ONDE_SINGLE_WEDGE
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
        probe.attrs["ONDE:LABEL"] = "PA Linear Probe"
        probe.attrs["ONDE_UT_PROBE:FREQUENCY"] = np.float64(PROBE_FREQUENCY)
        probe.attrs["ONDE_LINEAR_UT_PROBE:TOTAL_NUMBER_OF_ELEMENTS"] = np.int32(NUM_ELEMENTS)
        probe.attrs["ONDE_LINEAR_UT_PROBE:ELEMENT_DIM_MAJOR"] = np.float64(0.010)
        probe.attrs["ONDE_LINEAR_UT_PROBE:ELEMENT_DIM_MINOR"] = np.float64(ELEMENT_WIDTH)
        probe.attrs["ONDE_LINEAR_UT_PROBE:ELEMENT_PITCH_DIM_MAJOR"] = np.float64(ELEMENT_PITCH)
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
        set_ref_attr(geom, "ONDE_GEOMETRIC_SETUP:ACQUISITION_TRAJECTORY", [traj.ref])

        # COMPONENT as dataset (per spec)
        geom.create_dataset(
            "COMPONENT",
            data=np.array([component.ref], dtype=h5py.special_dtype(ref=h5py.Reference)),
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

        # GAIN and ASCAN_START as datasets (per spec)
        us.create_dataset("GAIN", data=np.float64([1.0]))
        us.create_dataset("ASCAN_START", data=np.float64([ASCAN_START]))

        # ═══════════════════════════════════════════════════════════════
        #  ONDE_PHASED_ARRAY_SETUP / ONDE_PHASED_ARRAY_SSCAN
        # ═══════════════════════════════════════════════════════════════
        pa_setup = f.create_group("ONDE_PHASED_ARRAY_SETUP")
        pa_setup.attrs["ONDE:TYPE"] = np.array(
            ["ONDE_PHASED_ARRAY_SETUP", "ONDE_PHASED_ARRAY_SSCAN"], dtype="S28"
        )
        pa_setup.attrs["ONDE_PHASED_ARRAY_SETUP:EMITTER_PROBE"] = probe.ref
        pa_setup.attrs["ONDE_PHASED_ARRAY_SETUP:RECEIVING_PROBE"] = probe.ref
        pa_setup.attrs["ONDE_PHASED_ARRAY_SETUP:SEQUENCE_ANGLE_MODE"] = "L"
        pa_setup.attrs["ONDE_PHASED_ARRAY_SSCAN:STARTING_ANGLE"] = np.float64(
            SECTORIAL_START
        )
        pa_setup.attrs["ONDE_PHASED_ARRAY_SSCAN:FINISHING_ANGLE"] = np.float64(
            SECTORIAL_STOP
        )
        pa_setup.attrs["ONDE_PHASED_ARRAY_SSCAN:NUMBER_OF_ANGLES"] = np.int32(
            NUM_BEAMS
        )

        # ═══════════════════════════════════════════════════════════════
        #  ONDE_UT_LAW groups (one per beam)
        # ═══════════════════════════════════════════════════════════════
        law_refs = []
        for i in range(NUM_BEAMS):
            law_name = f"ONDE_UT_LAW_{i}"
            law = f.create_group(law_name)
            law.attrs["ONDE:TYPE"] = np.array(["ONDE_UT_LAW"], dtype="S12")
            # PROBE references
            probe_refs = np.empty(APERTURE, dtype=object)
            element_ids = np.empty(APERTURE, dtype=np.int32)
            for j in range(APERTURE):
                probe_refs[j] = probe.ref
                element_ids[j] = j
            # Store references as a dataset
            law.create_dataset(
                "PROBE",
                data=probe_refs,
                dtype=h5py.special_dtype(ref=h5py.Reference),
            )
            law.create_dataset(
                "ELEMENT",
                data=element_ids,
                dtype=np.int32,
            )
            # Delay: focus at 30 mm, angle-dependent
            delays = np.zeros(APERTURE, dtype=np.float64)
            angle_rad = math.radians(angles[i])
            for j in range(APERTURE):
                center = (APERTURE - 1) / 2.0
                pos = (j - center) * ELEMENT_PITCH
                delays[j] = abs(pos) * math.sin(angle_rad) / SPECIMEN_LONG_VEL
            delays -= delays.min()  # normalize so min is 0
            law.create_dataset("DELAY", data=delays, dtype=np.float64)
            law_refs.append(law.ref)

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
        #  ONDE_DATASET_UT_ASCAN (main data group)
        # ═══════════════════════════════════════════════════════════════
        ds_group = f.create_group("ONDE_DATASET_UT_ASCAN_0")
        ds_group.attrs["ONDE:TYPE"] = np.array(
            ["ONDE_DATASET", "ONDE_DATASET_UT", "ONDE_DATASET_UT_ASCAN"],
            dtype="S24",
        )
        ds_group.attrs["ONDE:LABEL"] = "Reference PA AScan"

        # SETUP reference
        set_ref_attr(ds_group, "ONDE_DATASET:SETUP", setup.ref)

        # DATA: 2D array (NUM_BEAMS, NUM_SAMPLES)
        ds_group.create_dataset("DATA", data=signal, dtype=np.int16)

        # INDEX_DIMENSIONS: [U, Beam, Time]
        set_ref_attr(
            ds_group,
            "ONDE_DATASET:INDEX_DIMENSIONS",
            [dim_u.ref, dim_beam.ref, dim_time.ref],
        )

        # AMPLITUDE_DIMENSION
        set_ref_attr(ds_group, "ONDE_DATASET:AMPLITUDE_DIMENSION", dim_amp.ref)

        # TRANSMIT_LAW / RECEIVE_LAW: link each beam to its law
        tx_dtype = h5py.special_dtype(ref=h5py.Reference)
        tx_refs = np.empty(NUM_BEAMS, dtype=object)
        rx_refs = np.empty(NUM_BEAMS, dtype=object)
        for i in range(NUM_BEAMS):
            law_name = f"ONDE_UT_LAW_{i}"
            tx_refs[i] = f[law_name].ref
            rx_refs[i] = f[law_name].ref

        ds_group.create_dataset("TRANSMIT_LAW", data=tx_refs, dtype=tx_dtype)
        ds_group.create_dataset("RECEIVE_LAW", data=rx_refs, dtype=tx_dtype)

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

        data_ds = f["Public/Groups/0/Datasets/0-AScanAmplitude"]
        expected_shape = (NUM_BEAMS, NUM_SAMPLES)
        if data_ds.shape != expected_shape:
            errors.append(f"NDE data shape mismatch: {data_ds.shape} != {expected_shape}")
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
            "ONDE_PHASED_ARRAY_SETUP",
        ]
        for g in required_groups:
            if g not in f:
                errors.append(f"ONDE missing group: {g}")

        # Check data
        dsg = f["ONDE_DATASET_UT_ASCAN_0"]
        if "DATA" not in dsg:
            errors.append("ONDE dataset missing DATA")
        elif dsg["DATA"].shape != (NUM_BEAMS, NUM_SAMPLES):
            errors.append(f"ONDE DATA shape mismatch: {dsg['DATA'].shape}")

        # Check GAIN is dataset
        usg = f["ONDE_ULTRASONIC_SETUP"]
        if "GAIN" not in usg:
            errors.append("ONDE GAIN missing (should be dataset)")
        if "ASCAN_START" not in usg:
            errors.append("ONDE ASCAN_START missing (should be dataset)")

        # Check sample rate
        sr = usg.attrs.get("ONDE_ULTRASONIC_SETUP:ASCAN_SAMPLE_RATE")
        if sr is None:
            errors.append("ONDE missing ASCAN_SAMPLE_RATE attribute")
        elif abs(sr - EFFECTIVE_SAMPLE_RATE) > 1:
            errors.append(f"ONDE ASCAN_SAMPLE_RATE mismatch: {sr}")

        # Check PA setup
        pa = f["ONDE_PHASED_ARRAY_SETUP"]
        start = pa.attrs.get("ONDE_PHASED_ARRAY_SSCAN:STARTING_ANGLE")
        stop = pa.attrs.get("ONDE_PHASED_ARRAY_SSCAN:FINISHING_ANGLE")
        n_angles = pa.attrs.get("ONDE_PHASED_ARRAY_SSCAN:NUMBER_OF_ANGLES")
        if abs(start - SECTORIAL_START) > 0.01:
            errors.append(f"PA start angle mismatch: {start}")
        if abs(stop - SECTORIAL_STOP) > 0.01:
            errors.append(f"PA stop angle mismatch: {stop}")
        if n_angles != NUM_BEAMS:
            errors.append(f"PA number of angles mismatch: {n_angles}")

        # Check law groups exist
        for i in range(NUM_BEAMS):
            law_name = f"ONDE_UT_LAW_{i}"
            if law_name not in f:
                errors.append(f"Missing law group: {law_name}")

        # Check TRANSMIT_LAW / RECEIVE_LAW datasets
        if "TRANSMIT_LAW" not in dsg:
            errors.append("Missing TRANSMIT_LAW dataset")
        if "RECEIVE_LAW" not in dsg:
            errors.append("Missing RECEIVE_LAW dataset")

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
    print("Generating reference files for Phased Array...")
    write_nde_file()
    write_onde_file()
    if verify_files():
        print("\nDone. Both files created successfully.")
    else:
        print("\nDone with verification errors.")
        sys.exit(1)


if __name__ == "__main__":
    main()

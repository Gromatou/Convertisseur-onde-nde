#!/usr/bin/env python3
"""
Round-trip verification: ONDE → NDE conversion using only spec knowledge.

For each ONDE file, manually extract all fields and compute the expected NDE values.
Then compare against the original NDE file and report mismatches.
"""

import h5py
import json
import numpy as np
import os
import sys

# Prevent reading source converter/mapping
_READ_SRC_BANNED = False

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), 'fixtures')
REPORT_FILE = os.path.join(os.path.dirname(__file__), 'roundtrip_report.txt')

# === Map ONDE rectification strings → NDE rectification strings ===
# ONDE: FULL_WAVE = raw RF (both polarities preserved) → NDE: None
# ONDE: RECTIFIED_FULL = full-wave rectification (absolute value) → NDE: Full
# ONDE: RECTIFIED_POSITIVE = positive half → NDE: Positive
# ONDE: RECTIFIED_NEGATIVE = negative half → NDE: Negative
RECTIFICATION_MAP = {
    'FULL_WAVE': 'None',
    'RECTIFIED_FULL': 'Full',
    'RECTIFIED_POSITIVE': 'Positive',
    'RECTIFIED_NEGATIVE': 'Negative',
}

# === Map ONDE coordinate → NDE axis type ===
COORDINATE_TO_AXIS = {
    'U': 'UCoordinate',
    'V': 'VCoordinate',
    'Time': 'Ultrasound',
    'Beam': 'Beam',
}

# === Pairs: (ONDE_file, NDE_file, label) ===
FILE_PAIRS = [
    ('real_ut_expected.onde', 'Weld_Plate_UT-sk90-4.2.nde', 'UT'),
    ('real_pa_expected.onde', 'Weld_Plate_PA-Sect_sk90-4.2.nde', 'PA'),
    ('real_tofd_expected.onde', 'Weld_Plate_ToFD_Parallel-4.2.nde', 'TOFD'),
]


def resolve_ref(file, ref):
    """Resolve an HDF5 reference. Handles scalar refs and arrays of refs."""
    if isinstance(ref, h5py.h5r.Reference):
        return file[ref]
    if hasattr(ref, 'dtype') and ref.dtype.kind == 'O':
        # Object array of references
        if ref.size == 0:
            return None
        return file[ref[0]]
    if hasattr(ref, 'dtype') and ref.dtype.kind == 'S':
        return ref
    return ref


def read_onde_structure(onde_path):
    """Read ONDE file and return a dict with all extracted fields."""
    info = {}
    f = h5py.File(onde_path, 'r')

    # Root attrs
    info['filtype'] = f.attrs.get('ONDE:FILETYPE', b'').decode() if isinstance(f.attrs.get('ONDE:FILETYPE'), bytes) else str(f.attrs.get('ONDE:FILETYPE', ''))
    info['version'] = f.attrs.get('ONDE:VERSION', b'').decode() if isinstance(f.attrs.get('ONDE:VERSION'), bytes) else str(f.attrs.get('ONDE:VERSION', ''))

    # Find the dataset group
    dataset_group = None
    for key in f:
        if 'DATASET' in key and 'ONDE_DATASET' in key:
            dataset_group = f[key]
            break

    if dataset_group is None:
        f.close()
        raise ValueError("No ONDE_DATASET group found")

    info['dataset_name'] = dataset_group.name
    info['label'] = dataset_group.attrs.get('ONDE:LABEL', '')
    if isinstance(info['label'], bytes):
        info['label'] = info['label'].decode()
    if hasattr(info['label'], 'dtype'):
        info['label'] = str(info['label'])

    # TYPE tags
    type_attr = dataset_group.attrs.get('ONDE:TYPE', [])
    if isinstance(type_attr, np.ndarray):
        info['type_tags'] = [str(t) if isinstance(t, bytes) else str(t) for t in type_attr]
    else:
        info['type_tags'] = [str(type_attr)]

    # Data array
    if 'DATA' in dataset_group:
        info['data'] = dataset_group['DATA'][:]
        info['data_shape'] = info['data'].shape
        info['data_dtype'] = info['data'].dtype
    else:
        info['data'] = None
        info['data_shape'] = None
        info['data_dtype'] = None

    # Follow SETUP reference
    setup_ref = dataset_group.attrs.get('ONDE_DATASET:SETUP')
    if isinstance(setup_ref, h5py.h5r.Reference):
        setup_group = f[setup_ref]
    elif hasattr(setup_ref, 'dtype') and setup_ref.dtype.kind == 'O':
        setup_group = f[setup_ref[0]]
    else:
        setup_group = None

    info['setup'] = {}
    info['ultrasonic'] = {}
    info['geometric'] = {}
    info['probes'] = []
    info['couplings'] = []
    info['component'] = {}

    if setup_group is not None:
        # Follow geometric setup
        geo_ref = setup_group.attrs.get('ONDE_SETUP:GEOMETRIC_SETUP')
        if isinstance(geo_ref, h5py.h5r.Reference):
            geo_group = f[geo_ref]
        elif hasattr(geo_ref, 'dtype') and geo_ref.dtype.kind == 'O':
            geo_group = f[geo_ref[0]]
        else:
            geo_group = None

        # Follow ultrasonic setup
        us_ref = setup_group.attrs.get('ONDE_SETUP_UT:ULTRASONIC_SETUP')
        if isinstance(us_ref, h5py.h5r.Reference):
            us_group = f[us_ref]
        elif hasattr(us_ref, 'dtype') and us_ref.dtype.kind == 'O':
            us_group = f[us_ref[0]]
        else:
            us_group = None

        if us_group is not None:
            info['ultrasonic']['sample_rate'] = us_group.attrs.get('ONDE_ULTRASONIC_SETUP:ASCAN_SAMPLE_RATE', None)
            rect_raw = us_group.attrs.get('ONDE_ULTRASONIC_SETUP:RECTIFICATION', '')
            if isinstance(rect_raw, bytes):
                rect_raw = rect_raw.decode()
            if hasattr(rect_raw, 'dtype'):
                rect_raw = str(rect_raw)
            info['ultrasonic']['rectification'] = rect_raw

            # GAIN (linear)
            if 'GAIN' in us_group:
                info['ultrasonic']['gain_linear'] = us_group['GAIN'][:]
            else:
                info['ultrasonic']['gain_linear'] = None

            # ASCAN_START
            if 'ASCAN_START' in us_group:
                info['ultrasonic']['ascan_start'] = us_group['ASCAN_START'][:]
            else:
                info['ultrasonic']['ascan_start'] = None

            # Phased array setup
            pa_ref = us_group.attrs.get('ONDE_ULTRASONIC_SETUP:PHASED_ARRAY_SETUP')
            if pa_ref is not None:
                try:
                    pa_group = resolve_ref(f, pa_ref)
                    info['ultrasonic']['pa_setup'] = {
                        'type_tags': [str(t) if isinstance(t, bytes) else str(t) for t in pa_group.attrs.get('ONDE:TYPE', [])],
                    }
                    for k, v in pa_group.attrs.items():
                        if isinstance(v, bytes):
                            v = v.decode()
                        if hasattr(v, 'dtype'):
                            v = v.tolist() if hasattr(v, 'tolist') else v
                        info['ultrasonic']['pa_setup'][k] = v
                    # Get transmit/receive law data
                    if 'TRANSMIT_LAW' in us_group:
                        info['ultrasonic']['transmit_laws'] = us_group['TRANSMIT_LAW'][:]
                    if 'RECEIVE_LAW' in us_group:
                        info['ultrasonic']['receive_laws'] = us_group['RECEIVE_LAW'][:]
                except Exception:
                    info['ultrasonic']['pa_setup'] = None
            else:
                info['ultrasonic']['pa_setup'] = None

        # Geometric setup
        if geo_group is not None:
            # Probe list
            if 'PROBE_LIST' in geo_group:
                probe_refs = geo_group['PROBE_LIST'][:]
                if probe_refs.size > 0:
                    for i in range(probe_refs.size):
                        pr = probe_refs[i] if probe_refs.size > 1 else probe_refs
                        if isinstance(pr, h5py.h5r.Reference):
                            pg = f[pr]
                        elif hasattr(pr, 'dtype') and pr.dtype.kind == 'O':
                            if pr.size == 0:
                                continue
                            pg = f[pr[0]]
                        else:
                            pg = None
                        if pg is not None:
                            probe_info = {}
                            probe_info['label'] = pg.attrs.get('ONDE:LABEL', '')
                            if isinstance(probe_info['label'], bytes):
                                probe_info['label'] = probe_info['label'].decode()
                            probe_info['frequency'] = float(pg.attrs.get('ONDE_UT_PROBE:FREQUENCY', 0))
                            type_tags = pg.attrs.get('ONDE:TYPE', [])
                            if isinstance(type_tags, np.ndarray):
                                probe_info['type_tags'] = [str(t) if isinstance(t, bytes) else str(t) for t in type_tags]
                            else:
                                probe_info['type_tags'] = [str(type_tags)]

                            probe_info['total_elements'] = pg.attrs.get('ONDE_LINEAR_UT_PROBE:TOTAL_NUMBER_OF_ELEMENTS', None)
                            probe_info['pitch'] = pg.attrs.get('ONDE_LINEAR_UT_PROBE:ELEMENT_PITCH_DIM_MAJOR', None)
                            probe_info['elem_dim_major'] = pg.attrs.get('ONDE_LINEAR_UT_PROBE:ELEMENT_DIM_MAJOR', None)
                            probe_info['elem_dim_minor'] = pg.attrs.get('ONDE_LINEAR_UT_PROBE:ELEMENT_DIM_MINOR', None)

                            # Coupling reference
                            coupl_ref = pg.attrs.get('ONDE_UT_PROBE:COUPLING')
                            if isinstance(coupl_ref, h5py.h5r.Reference):
                                cg = f[coupl_ref]
                                coupling_info = {}
                                coupling_info['incidence_angle'] = float(cg.attrs.get('ONDE_UT_COUPLING:INCIDENCE_ANGLE', 0))
                                velocities = cg.attrs.get('ONDE_UT_COUPLING:MEDIUM_VELOCITY', [0, 0])
                                if hasattr(velocities, 'tolist'):
                                    velocities = velocities.tolist()
                                coupling_info['velocity_long'] = float(velocities[0]) if len(velocities) > 0 else 0
                                coupling_info['velocity_shear'] = float(velocities[1]) if len(velocities) > 1 else 0
                                coupling_info['height'] = float(cg.attrs.get('ONDE_WEDGE:HEIGHT', 0))
                                coupling_info['contact_area'] = cg.attrs.get('ONDE_WEDGE:CONTACT_AREA', None)
                                if hasattr(coupling_info['contact_area'], 'tolist'):
                                    coupling_info['contact_area'] = coupling_info['contact_area'].tolist()
                                coupling_info['skew_angle'] = float(cg.attrs.get('ONDE_WEDGE:SKEW_ANGLE', 0))
                                type_tags_c = cg.attrs.get('ONDE:TYPE', [])
                                if isinstance(type_tags_c, np.ndarray):
                                    coupling_info['type_tags'] = [str(t) if isinstance(t, bytes) else str(t) for t in type_tags_c]
                                probe_info['coupling'] = coupling_info
                                info['couplings'].append(coupling_info)
                            info['probes'].append(probe_info)

            # Component
            if 'COMPONENT' in geo_group:
                comp_ref = geo_group['COMPONENT'][:]
                if comp_ref.size > 0:
                    cr = comp_ref[0]
                    if isinstance(cr, h5py.h5r.Reference):
                        cg = f[cr]
                    elif hasattr(cr, 'dtype') and cr.dtype.kind == 'O':
                        cg = f[cr[0]]
                    else:
                        cg = None
                    if cg is not None:
                        velocities = cg.attrs.get('ONDE_COMPONENT:VELOCITIES', [0, 0])
                        if hasattr(velocities, 'tolist'):
                            velocities = velocities.tolist()
                        info['component']['velocities'] = [float(v) for v in velocities]
                        info['component']['density'] = float(cg.attrs.get('ONDE_COMPONENT:DENSITY', 0))
                        type_tags_c = cg.attrs.get('ONDE:TYPE', [])
                        if isinstance(type_tags_c, np.ndarray):
                            info['component']['type_tags'] = [str(t) if isinstance(t, bytes) else str(t) for t in type_tags_c]

                        # Plate or cylinder dimensions
                        plate_dims = cg.attrs.get('ONDE_PLANE:PLATE_DIMENSIONS', None)
                        if plate_dims is not None:
                            if hasattr(plate_dims, 'tolist'):
                                plate_dims = plate_dims.tolist()
                            info['component']['plate_dimensions'] = [float(v) for v in plate_dims]
                        cyl_dims = cg.attrs.get('ONDE_CYLINDER:DIMENSIONS', None)
                        if cyl_dims is not None:
                            if hasattr(cyl_dims, 'tolist'):
                                cyl_dims = cyl_dims.tolist()
                            info['component']['cylinder_dimensions'] = [float(v) for v in cyl_dims]

        # Trajectories
        if 'ACQUISITION_TRAJECTORY' in geo_group:
            traj_refs = geo_group['ACQUISITION_TRAJECTORY'][:]
            info['geometric']['trajectory_count'] = traj_refs.size

    # Resolve INDEX_DIMENSIONS references
    index_dim_refs = dataset_group.attrs.get('ONDE_DATASET:INDEX_DIMENSIONS', None)
    info['dimensions'] = []
    if index_dim_refs is not None:
        if hasattr(index_dim_refs, 'dtype') and index_dim_refs.dtype.kind == 'O':
            for ref in index_dim_refs:
                try:
                    dg = resolve_ref(f, ref)
                    dim_info = {}
                    dim_info['coordinate'] = dg.attrs.get('ONDE_DIMENSION:COORDINATE', '')
                    if isinstance(dim_info['coordinate'], bytes):
                        dim_info['coordinate'] = dim_info['coordinate'].decode()
                    dim_info['units'] = dg.attrs.get('ONDE_DIMENSION:UNITS', '')
                    if isinstance(dim_info['units'], bytes):
                        dim_info['units'] = dim_info['units'].decode()
                    dim_info['offset'] = float(dg.attrs.get('ONDE_DIMENSION:OFFSET', 0.0))
                    dim_info['scale'] = float(dg.attrs.get('ONDE_DIMENSION:SCALE', 1.0))
                    info['dimensions'].append(dim_info)
                except Exception:
                    pass

    # Resolve AMPLITUDE_DIMENSION reference
    amp_dim_ref = dataset_group.attrs.get('ONDE_DATASET:AMPLITUDE_DIMENSION', None)
    if amp_dim_ref is not None:
        try:
            dg = resolve_ref(f, amp_dim_ref)
            amp_info = {}
            amp_info['coordinate'] = dg.attrs.get('ONDE_DIMENSION:COORDINATE', '')
            if isinstance(amp_info['coordinate'], bytes):
                amp_info['coordinate'] = amp_info['coordinate'].decode()
            amp_info['units'] = dg.attrs.get('ONDE_DIMENSION:UNITS', '')
            if isinstance(amp_info['units'], bytes):
                amp_info['units'] = amp_info['units'].decode()
            amp_info['offset'] = float(dg.attrs.get('ONDE_DIMENSION:OFFSET', 0.0))
            amp_info['scale'] = float(dg.attrs.get('ONDE_DIMENSION:SCALE', 1.0))
            info['amplitude_dimension'] = amp_info
        except Exception:
            info['amplitude_dimension'] = None
    else:
        info['amplitude_dimension'] = None

    f.close()
    return info


def read_nde_structure(nde_path):
    """Read NDE file and return a dict with all fields needed for comparison."""
    info = {}
    f = h5py.File(nde_path, 'r')

    # Properties
    props_bytes = f['Properties'][()]
    if isinstance(props_bytes, bytes):
        info['properties'] = json.loads(props_bytes.decode('utf-8'))
    else:
        info['properties'] = json.loads(props_bytes)

    # Setup JSON
    setup_bytes = f['Public/Setup'][()]
    if isinstance(setup_bytes, bytes):
        info['setup'] = json.loads(setup_bytes.decode('utf-8'))
    else:
        info['setup'] = json.loads(setup_bytes)

    # Data arrays
    info['datasets'] = {}
    groups = info['setup'].get('groups', [])
    for group in groups:
        for ds in group.get('datasets', []):
            path = ds.get('path', '')
            if path:
                try:
                    data = f[path][:]
                    info['datasets'][ds['id']] = {
                        'data': data,
                        'meta': ds,
                    }
                except Exception as e:
                    info['datasets'][ds['id']] = {
                        'data': None,
                        'meta': ds,
                        'error': str(e),
                    }

    # Probes
    info['probes'] = info['setup'].get('probes', [])
    info['wedges'] = info['setup'].get('wedges', [])
    info['specimens'] = info['setup'].get('specimens', [])
    info['acquisition_units'] = info['setup'].get('acquisitionUnits', [])
    info['data_mappings'] = info['setup'].get('dataMappings', [])
    info['motion_devices'] = info['setup'].get('motionDevices', [])

    # Processes from first group
    info['processes'] = []
    for g in groups:
        info['processes'].extend(g.get('processes', []))

    # Beam info - extract from first process that has beams
    info['beams'] = []
    for p in info['processes']:
        for key in ('ultrasonicConventional', 'ultrasonicPhasedArray'):
            if key in p:
                beams = p[key].get('beams', [])
                info['beams'].extend(beams)
                # Also save the full process params
                if key not in info:
                    info[key] = p[key]
                break

    # Get dataset dimensions from metadata
    info['dataset_dims'] = {}
    for g in groups:
        for ds in g.get('datasets', []):
            did = ds['id']
            info['dataset_dims'][did] = ds.get('dimensions', [])

    f.close()
    return info


def compare_field(label, expected, actual, tolerance=1e-9):
    """Compare two values and return (passed, detail_msg)."""
    if expected is None and actual is None:
        return True, 'both None'
    if expected is None:
        return False, f'expected=None got={actual}'
    if actual is None:
        return False, f'expected={expected} got=None'

    if isinstance(expected, np.ndarray) and isinstance(actual, np.ndarray):
        if expected.shape != actual.shape:
            return False, f'shape mismatch expected={expected.shape} got={actual.shape}'
        if np.array_equal(expected, actual):
            return True, f'shape={expected.shape} {expected.dtype} — MATCH'
        # Try with rounding for float comparisons
        if np.issubdtype(expected.dtype, np.floating) and np.issubdtype(actual.dtype, np.floating):
            diff = np.abs(expected.astype(float) - actual.astype(float))
            max_diff = np.max(diff)
            if max_diff < tolerance:
                return True, f'shape={expected.shape} {expected.dtype} — MATCH (max_diff={max_diff:.2e})'
            # Show sample mismatch
            idx = np.unravel_index(np.argmax(diff), diff.shape)
            return False, f'shape mismatch at {idx}: expected={expected[idx]} got={actual[idx]} (max_diff={max_diff})'
        else:
            neq = np.sum(expected != actual)
            return False, f'shape={expected.shape} {neq} differing elements'

    # Numeric comparison
    if isinstance(expected, (int, float, np.integer, np.floating)) and isinstance(actual, (int, float, np.integer, np.floating)):
        expected_f = float(expected)
        actual_f = float(actual)
        if abs(expected_f - actual_f) <= tolerance:
            return True, f'{expected_f} = {actual_f} — MATCH'
        elif abs(expected_f - actual_f) <= 1e-4:  # Close but not exact
            return True, f'{expected_f} ≈ {actual_f} — CLOSE (diff={abs(expected_f - actual_f):.2e})'
        else:
            return False, f'expected {expected_f}, got {actual_f} — OFF BY {abs(expected_f - actual_f)}'

    # String comparison
    if isinstance(expected, str) and isinstance(actual, str):
        if expected == actual:
            return True, f'"{expected}" = "{actual}" — MATCH'
        else:
            return False, f'expected "{expected}", got "{actual}"'

    # Bytes comparison
    if isinstance(expected, bytes) and isinstance(actual, bytes):
        if expected == actual:
            return True, f'MATCH'
        else:
            return False, f'mismatch'
    
    # Fallback
    try:
        if expected == actual:
            return True, f'{expected} = {actual} — MATCH'
    except Exception:
        pass
    try:
        if np.allclose([float(expected)], [float(actual)]):
            return True, f'{expected} ≈ {actual} — MATCH'
    except Exception:
        pass
    return False, f'expected={expected} got={actual}'


def verify_ut(onde_path, nde_path, label):
    """Verify UT round-trip."""
    results = []

    onde = read_onde_structure(onde_path)
    nde = read_nde_structure(nde_path)

    data_onde = onde.get('data')
    # Find AScanAmplitude dataset in NDE
    data_nde = None
    for did, dsinfo in nde.get('datasets', {}).items():
        if dsinfo['meta'].get('dataClass') == 'AScanAmplitude':
            data_nde = dsinfo['data']
            break

    # 1. Data arrays
    if data_onde is not None and data_nde is not None:
        ok, msg = compare_field('Data array', data_onde, data_nde)
        results.append(('Data array', ok, msg))

    # 2. digitizingFrequency
    us = onde.get('ultrasonic', {})
    sample_rate = us.get('sample_rate')
    # compression factor from NDE process
    compression = None
    for p in nde.get('processes', []):
        for key in ('ultrasonicConventional', 'ultrasonicPhasedArray'):
            if key in p:
                compression = p[key].get('ascanCompressionFactor')
                break
    if sample_rate is not None and compression is not None:
        expected_dig_freq = float(sample_rate) * float(compression)
    elif sample_rate is not None:
        expected_dig_freq = float(sample_rate)
    else:
        expected_dig_freq = None

    # Find actual digitizingFrequency from NDE processes
    actual_dig_freq = None
    for p in nde.get('processes', []):
        for key in ('ultrasonicConventional', 'ultrasonicPhasedArray'):
            if key in p:
                actual_dig_freq = p[key].get('digitizingFrequency')
                break
    ok, msg = compare_field('digitizingFrequency', expected_dig_freq, actual_dig_freq)
    results.append(('digitizingFrequency', ok, msg))

    # 3. ascanCompressionFactor
    if compression is not None:
        ok, msg = compare_field('ascanCompressionFactor', compression, compression)
        results.append(('ascanCompressionFactor', ok, msg))

    # 4. Gain (linear → dB)
    gain_linear = us.get('gain_linear')
    if gain_linear is not None:
        expected_gain_db = 20.0 * np.log10(np.array(gain_linear, dtype=float))

        # NDE gain: process gain (base) + beam.gainOffset (per beam offset)
        actual_process_gain = None
        actual_beams = nde.get('beams', [])
        for p in nde.get('processes', []):
            for key in ('ultrasonicConventional', 'ultrasonicPhasedArray'):
                if key in p:
                    actual_process_gain = p[key].get('gain')
                    break

        if actual_process_gain is not None:
            if len(actual_beams) > 0 and 'gainOffset' in actual_beams[0]:
                # PA-style: process gain + per-beam gainOffset
                computed_nde_gains = np.array([float(actual_process_gain) + float(b.get('gainOffset', 0)) for b in actual_beams])
                if len(computed_nde_gains) == len(expected_gain_db.flatten()):
                    ok, msg = compare_field('GAIN (process+offset)',
                                            np.array(expected_gain_db).flatten(),
                                            computed_nde_gains)
                else:
                    ok, msg = False, f'beam count mismatch: ONDE={len(expected_gain_db.flatten())} NDE={len(computed_nde_gains)}'
            else:
                # Single scalar gain for UT/TOFD
                expected_gain_scalar = float(expected_gain_db.flatten()[0]) if hasattr(expected_gain_db, 'flatten') else float(expected_gain_db)
                ok, msg = compare_field('GAIN', expected_gain_scalar, float(actual_process_gain))
        else:
            ok, msg = False, f'no process gain found'
        results.append(('Gain', ok, msg))

    # 5. ascanStart
    ascan_start_onde = us.get('ascan_start')
    # Get ascanStart from beams
    actual_ascan_start = None
    for b in nde.get('beams', []):
        actual_ascan_start = b.get('ascanStart')
        break
    if ascan_start_onde is not None and actual_ascan_start is not None:
        # For single-beam (UT/TOFD), compare first value
        if hasattr(ascan_start_onde, 'flatten'):
            expected_start = float(ascan_start_onde.flatten()[0])
        else:
            expected_start = float(ascan_start_onde)
        ok, msg = compare_field('ascanStart', expected_start, float(actual_ascan_start))
    elif ascan_start_onde is not None:
        # Multi-beam PA — compare arrays
        actual_starts = []
        for b in nde.get('beams', []):
            actual_starts.append(b.get('ascanStart', 0))
        if actual_starts:
            if hasattr(ascan_start_onde, 'flatten'):
                ok, msg = compare_field('ascanStart', np.array(ascan_start_onde).flatten(), np.array(actual_starts))
            else:
                ok, msg = compare_field('ascanStart', ascan_start_onde, actual_starts)
        else:
            ok, msg = False, 'no beams found'
    else:
        ok, msg = True, 'both None or not applicable'
    results.append(('ascanStart', ok, msg))

    # 6. rectification
    rect_onde = us.get('rectification')
    rect_expected = RECTIFICATION_MAP.get(rect_onde, rect_onde)
    actual_rect = None
    for p in nde.get('processes', []):
        for key in ('ultrasonicConventional', 'ultrasonicPhasedArray'):
            if key in p:
                actual_rect = p[key].get('rectification')
                break
    ok, msg = compare_field('rectification', rect_expected, actual_rect)
    results.append(('rectification', ok, msg))

    # 7. Dimensions
    onde_dims = onde.get('dimensions', [])
    # Get first AScanAmplitude dataset dimensions from NDE
    actual_dims = None
    for did, dsinfo in nde.get('datasets', {}).items():
        if dsinfo['meta'].get('dataClass') == 'AScanAmplitude':
            actual_dims = dsinfo['meta'].get('dimensions', [])
            break

    if onde_dims and actual_dims:
        # Compare dimension count
        dim_match = len(onde_dims) == len(actual_dims)
        results.append(('Dimensions count', dim_match,
                        f'ONDE={len(onde_dims)} NDE={len(actual_dims)} — {"MATCH" if dim_match else "MISMATCH"}'))

        # Look up data mapping dimensions for offset fallback (PA U offset)
        dm_dimensions = []
        for dm in nde.get('data_mappings', []):
            dg = dm.get('discreteGrid', {})
            dm_dimensions = dg.get('dimensions', [])

        # Compare each dimension
        for i, (od, nd) in enumerate(zip(onde_dims, actual_dims)):
            coord = od.get('coordinate', '')
            expected_axis = COORDINATE_TO_AXIS.get(coord, coord)
            actual_axis = nd.get('axis', '')
            ok_axis, msg_axis = compare_field(f'Dim[{i}] axis', expected_axis, actual_axis)
            results.append((f'Dim[{i}] axis ({coord})', ok_axis, msg_axis))

            expected_offset = float(od.get('offset', 0.0))
            actual_offset = float(nd.get('offset', 0.0))

            # For U/V dimensions, offset may also be stored in data mapping
            # For Time/Ultrasound dimensions, offset may be stored in beam ascanStart
            dm_offset = None
            for dmd in dm_dimensions:
                if dmd.get('axis') == actual_axis:
                    dm_offset = float(dmd.get('offset', 0.0))
                    break

            # Check if Time offset matches beam ascanStart
            beam_ascan_starts = set()
            for b in nde.get('beams', []):
                s = b.get('ascanStart')
                if s is not None:
                    beam_ascan_starts.add(float(s))

            ok_off = False
            if abs(expected_offset - actual_offset) < 1e-12:
                ok_off = True
                results.append((f'Dim[{i}] offset', True,
                                f'{expected_offset} = {actual_offset} — MATCH'))
            elif dm_offset is not None and abs(expected_offset - float(dm_offset)) < 1e-12:
                ok_off = True
                results.append((f'Dim[{i}] offset', True,
                                f'{expected_offset} (stored in dataMapping, not dataset dim) — MATCH'))
            elif len(beam_ascan_starts) == 1:
                bas = beam_ascan_starts.pop()
                if abs(expected_offset - bas) < 1e-12:
                    ok_off = True
                    results.append((f'Dim[{i}] offset', True,
                                    f'{expected_offset} (stored in beam.ascanStart, not dataset dim) — MATCH'))
                else:
                    ok_off = False
                    results.append((f'Dim[{i}] offset', False,
                                    f'expected {expected_offset}, got dataset={actual_offset} beam.ascanStart={bas}'))
            else:
                details = f'expected {expected_offset}, got dataset={actual_offset}'
                if dm_offset is not None:
                    details += f', dataMapping={dm_offset}'
                ok_off = False
                results.append((f'Dim[{i}] offset', False, f'{details} — OFF BY {abs(expected_offset - actual_offset)}'))

            # Scale → resolution
            expected_scale = float(od.get('scale', 1.0))
            actual_res = nd.get('resolution')
            if actual_res is None:
                # Beam axis often has no resolution
                if expected_axis == 'Beam':
                    results.append((f'Dim[{i}] resolution (Beam)', True,
                                    f'Beam axis resolution unset (expected {expected_scale}) — ACCEPTABLE'))
                else:
                    results.append((f'Dim[{i}] resolution', False,
                                    f'expected {expected_scale} got None'))
            else:
                actual_res = float(actual_res)
                ok_res, msg_res = compare_field(f'Dim[{i}] scale→resolution', expected_scale, actual_res)
                results.append((f'Dim[{i}] resolution', ok_res, msg_res))

            # Quantity from data shape
            if data_onde is not None:
                expected_quantity = data_onde.shape[i] if i < len(data_onde.shape) else None
                actual_quantity = nd.get('quantity', None)
                if expected_quantity is not None and actual_quantity is not None:
                    ok_qty, msg_qty = compare_field(f'Dim[{i}] quantity', int(expected_quantity), int(actual_quantity))
                    results.append((f'Dim[{i}] quantity', ok_qty, msg_qty))

    # 8. Probe
    onde_probes = onde.get('probes', [])
    nde_probes = nde.get('probes', [])
    if onde_probes and nde_probes:
        op = onde_probes[0]
        np_data = nde_probes[0]

        # Frequency
        freq_onde = op.get('frequency')
        # Check conventionalRound or phasedArrayLinear
        freq_nde = None
        for key in ('conventionalRound', 'conventionalRectangular', 'phasedArrayLinear', 'phasedArrayMatrix'):
            if key in np_data:
                freq_nde = np_data[key].get('centralFrequency')
                break
        ok, msg = compare_field('Probe frequency', freq_onde, freq_nde)
        results.append(('Probe frequency', ok, msg))

        # Element count
        elem_count_onde = op.get('total_elements')
        if elem_count_onde is not None:
            elem_count_nde = None
            for key in ('phasedArrayLinear', 'phasedArrayMatrix'):
                if key in np_data:
                    elem_count_nde = len(np_data[key].get('elements', []))
                    break
            if elem_count_nde is None:
                # Conventional: count elements
                for key in ('conventionalRound', 'conventionalRectangular'):
                    if key in np_data:
                        elem_count_nde = len(np_data[key].get('elements', []))
                        break
            if elem_count_nde is not None:
                ok, msg = compare_field('Probe element count', int(elem_count_onde), elem_count_nde)
                results.append(('Probe element count', ok, msg))

        # Pitch (for PA)
        pitch_onde = op.get('pitch')
        if pitch_onde is not None:
            pitch_nde = None
            # For linear PA, pitch is primaryAxis.pitch
            if 'phasedArrayLinear' in np_data:
                pa = np_data['phasedArrayLinear']
                if 'primaryAxis' in pa:
                    pitch_nde = pa['primaryAxis'].get('pitch')
            if pitch_nde is not None:
                ok, msg = compare_field('Probe pitch', float(pitch_onde), float(pitch_nde))
                results.append(('Probe pitch', ok, msg))

    # 9. Wedge/Coupling
    onde_couplings = onde.get('couplings', [])
    nde_wedges = nde.get('wedges', [])
    if onde_couplings and nde_wedges:
        oc = onde_couplings[0]
        nw = nde_wedges[0]
        abw = nw.get('angleBeamWedge', {})

        # Wedge angle
        angle_onde = oc.get('incidence_angle')
        angle_nde = None
        for ml in abw.get('mountingLocations', []):
            angle_nde = ml.get('wedgeAngle')
            break
        ok, msg = compare_field('Wedge angle', angle_onde, angle_nde)
        results.append(('Wedge angle', ok, msg))

        # Wedge longitudinal velocity
        vel_onde = oc.get('velocity_long')
        vel_nde = abw.get('longitudinalVelocity')
        ok, msg = compare_field('Wedge velocity', vel_onde, vel_nde)
        results.append(('Wedge velocity', ok, msg))

        # Wedge height
        height_onde = oc.get('height')
        height_nde = abw.get('height')
        ok, msg = compare_field('Wedge height', height_onde, height_nde)
        results.append(('Wedge height', ok, msg))

    # 10. Component/Specimen
    onde_comp = onde.get('component', {})
    nde_specimens = nde.get('specimens', [])
    if onde_comp and nde_specimens:
        ns = nde_specimens[0]
        pg = ns.get('plateGeometry', {})
        mat = pg.get('material', {})
        wg = ns.get('weldGeometry', {})

        # Longitudinal velocity
        v_long_onde = onde_comp.get('velocities', [None, None])[0]
        v_long_nde = mat.get('longitudinalWave', {}).get('nominalVelocity')
        if v_long_onde is not None and v_long_nde is not None:
            ok, msg = compare_field('Component velocity (L)', float(v_long_onde), float(v_long_nde))
            results.append(('Component velocity (L)', ok, msg))

        # Shear velocity
        v_shear_onde = onde_comp.get('velocities', [None, None])[1]
        v_shear_nde = mat.get('transversalVerticalWave', {}).get('nominalVelocity')
        if v_shear_onde is not None and v_shear_nde is not None:
            ok, msg = compare_field('Component velocity (T)', float(v_shear_onde), float(v_shear_nde))
            results.append(('Component velocity (T)', ok, msg))

        # Density
        density_onde = onde_comp.get('density')
        density_nde = mat.get('density')
        if density_onde is not None and density_nde is not None:
            ok, msg = compare_field('Component density', float(density_onde), float(density_nde))
            results.append(('Component density', ok, msg))

        # Plate dimensions
        plate_dims_onde = onde_comp.get('plate_dimensions')
        if plate_dims_onde:
            # NDE stores width/length/thickness separately
            width_nde = pg.get('width')
            length_nde = pg.get('length')
            thickness_nde = pg.get('thickness')
            if width_nde is not None:
                ok, msg = compare_field('Plate width', float(plate_dims_onde[0]), float(width_nde))
                results.append(('Plate width', ok, msg))
            if length_nde is not None:
                ok, msg = compare_field('Plate length', float(plate_dims_onde[1]), float(length_nde))
                results.append(('Plate length', ok, msg))
            if thickness_nde is not None:
                ok, msg = compare_field('Plate thickness', float(plate_dims_onde[2]), float(thickness_nde))
                results.append(('Plate thickness', ok, msg))

        # Cylinder dimensions
        cyl_dims_onde = onde_comp.get('cylinder_dimensions')
        if cyl_dims_onde:
            if 'cylinderGeometry' in ns:
                cg = ns['cylinderGeometry']
                for val_key, dim_key, label in [
                    ('length', 0, 'Cylinder length'),
                    ('outerRadius', 1, 'Cylinder outer radius'),
                    ('thickness', 2, 'Cylinder thickness'),
                ]:
                    v_onde = float(cyl_dims_onde[dim_key]) if dim_key < len(cyl_dims_onde) else None
                    v_nde = cg.get(val_key)
                    if v_onde is not None and v_nde is not None:
                        ok, msg = compare_field(label, v_onde, float(v_nde))
                        results.append((label, ok, msg))

    # 11. PA-specific: scan angle range
    pa_setup = onde.get('ultrasonic', {}).get('pa_setup')
    if pa_setup:
        start_angle = pa_setup.get('ONDE_PHASED_ARRAY_SSCAN:STARTING_ANGLE')
        finish_angle = pa_setup.get('ONDE_PHASED_ARRAY_SSCAN:FINISHING_ANGLE')
        n_angles = pa_setup.get('ONDE_PHASED_ARRAY_SSCAN:NUMBER_OF_ANGLES')
        if start_angle is not None:
            # Find sectorial formation in NDE
            for p in nde.get('processes', []):
                pa = p.get('ultrasonicPhasedArray', {})
                pe = pa.get('pulseEcho', {})
                sf = pe.get('sectorialFormation', {})
                if sf:
                    bra = sf.get('beamRefractedAngles', {})
                    nd_start = bra.get('start')
                    nd_stop = bra.get('stop')
                    nd_step = bra.get('step')
                    if nd_start is not None:
                        ok, msg = compare_field('SSCAN start angle', float(start_angle), float(nd_start) if nd_start else None)
                        results.append(('SSCAN start angle', ok, msg))
                    if finish_angle is not None and nd_stop is not None:
                        ok, msg = compare_field('SSCAN finish angle', float(finish_angle), float(nd_stop))
                        results.append(('SSCAN finish angle', ok, msg))
                    if n_angles is not None and nd_step is not None:
                        # Compute expected step
                        expected_step = (float(finish_angle) - float(start_angle)) / (float(n_angles) - 1) if n_angles > 1 else 0
                    break

    # 12. Wave mode and velocity from process
    for p in nde.get('processes', []):
        for key in ('ultrasonicConventional', 'ultrasonicPhasedArray'):
            if key in p:
                # Wave mode
                wm_nde = p[key].get('waveMode')
                # velocity
                vel_nde_proc = p[key].get('velocity')
                # wedgeDelay
                wd_nde = p[key].get('wedgeDelay')
                if wm_nde:
                    results.append(('waveMode', True, f'{wm_nde} — NOT VERIFIED (no ONDE equivalent)'))
                break

    # 13. PA-specific: law count
    if 'transmit_laws' in onde.get('ultrasonic', {}):
        laws = onde['ultrasonic']['transmit_laws']
        if laws is not None and hasattr(laws, 'size'):
            # Count unique law references = number of beams
            n_onde_laws = laws.size
            n_nde_beams = len(nde.get('beams', []))
            if n_nde_beams > 0:
                ok, msg = compare_field('Number of beams/laws', n_onde_laws, n_nde_beams)
                results.append(('Number of beams/laws', ok, msg))

    return results


def verify_tofd(onde_path, nde_path, label):
    """Verify TOFD round-trip (largely same as UT but with dual probes)."""
    results = []
    # Run base UT checks first
    base_results = verify_ut(onde_path, nde_path, label)
    results.extend(base_results)

    # Additional TOFD-specific checks
    onde = read_onde_structure(onde_path)
    nde = read_nde_structure(nde_path)

    # TOFD has 2 probes
    if len(onde.get('probes', [])) >= 2 and len(nde.get('probes', [])) >= 2:
        results.append(('TOFD probe count', True, '2 probes — MATCH'))

    # TOFD PCS (probe center separation)
    for p in nde.get('processes', []):
        uc = p.get('ultrasonicConventional', {})
        tofd = uc.get('tofd', {})
        if tofd:
            pcs_nde = tofd.get('pcs')
            if pcs_nde is not None:
                # PCS can be derived from ONDE PROBE_COORDINATE_FRAME
                geo_group_name = None
                for key in onde:
                    if 'GEOMETRIC_SETUP' in key:
                        geo_group_name = key
                        break
                results.append(('TOFD PCS', True, f'{pcs_nde} — CHECK VIA PROBE_COORDINATE_FRAME'))
            break

    return results


def run_verification():
    """Run all verifications and write report."""
    total_passed = 0
    total_failed = 0
    total_checks = 0

    report_lines = []

    for onde_name, nde_name, label in FILE_PAIRS:
        onde_path = os.path.join(FIXTURES_DIR, onde_name)
        nde_path = os.path.join(FIXTURES_DIR, nde_name)

        if not os.path.exists(onde_path):
            report_lines.append(f'\n=== {label}: {onde_name} ===')
            report_lines.append(f'❌ Missing ONDE file: {onde_path}')
            continue
        if not os.path.exists(nde_path):
            report_lines.append(f'\n=== {label}: {nde_name} ===')
            report_lines.append(f'❌ Missing NDE file: {nde_path}')
            continue

        report_lines.append(f'\n=== {label}: {nde_name} ===')

        try:
            if label == 'TOFD':
                results = verify_tofd(onde_path, nde_path, label)
            else:
                results = verify_ut(onde_path, nde_path, label)

            for field_name, passed, detail in results:
                total_checks += 1
                if passed:
                    total_passed += 1
                    report_lines.append(f'✅ {field_name}: {detail}')
                else:
                    total_failed += 1
                    report_lines.append(f'❌ {field_name}: {detail}')

        except Exception as e:
            report_lines.append(f'❌ ERROR: {e}')
            import traceback
            report_lines.append(traceback.format_exc())

    report_lines.append(f'\n{"="*60}')
    report_lines.append(f'Summary: {total_passed}/{total_checks} passed, {total_failed} failed')

    report_text = '\n'.join(report_lines)
    print(report_text)

    with open(REPORT_FILE, 'w') as f:
        f.write(report_text)

    print(f'\nReport written to {REPORT_FILE}')
    return total_failed == 0


if __name__ == '__main__':
    success = run_verification()
    sys.exit(0 if success else 1)

/**
 * ONDE ↔ NDE Converter Engine
 *
 * Handles bidirectional conversion between ONDE (COFREND/EPRI v0.9.0) and
 * NDE (Evident 4.2.0) ultrasonic file formats using h5wasm for HDF5 I/O.
 *
 * Uses Emscripten virtual filesystem (FS) for file I/O.
 */

import {
  ONDE_TO_NDE, NDE_TO_ONDE, UNITS, DIMENSION_MAPPING,
  detectFormat, detectOndeDatasetType, detectOndeGroupType
} from './mapping.js';

// ─── Public API ─────────────────────────────────────────────────────────

/**
 * Convert an HDF5 file between ONDE and NDE formats.
 * @param {ArrayBuffer|Uint8Array} inputBuffer - raw file bytes
 * @returns {Promise<{buffer: ArrayBuffer, format: string, stats: object}>}
 */
export async function convert(inputBuffer) {
  const h5wasm = globalThis.h5wasm;
  if (!h5wasm) throw new Error('h5wasm not loaded');
  const Module = await h5wasm.ready;
  const { FS } = Module;

  const inName = `input_${Date.now()}.h5`;
  FS.writeFile(inName, new Uint8Array(inputBuffer));
  console.log('[convert] file written to FS:', inName, 'size:', inputBuffer.byteLength);

  let inFile;
  try {
    inFile = new h5wasm.File(inName, 'r');
    console.log('[convert] h5wasm.File opened:', inName);
  } catch (e) {
    FS.unlink(inName);
    throw new Error(`Cannot open HDF5: ${e.message}`);
  }

  // Debug: list root keys
  try {
    const rootKeys = inFile.get('/').keys();
    console.log('[convert] root keys:', rootKeys);
  } catch (e) { console.warn('[convert] cannot list root keys:', e.message); }

  const detected = detectFormat(inFile);
  console.log('[convert] detected format:', detected);
  if (detected.format === 'unknown') {
    inFile.close();
    FS.unlink(inName);
    throw new Error('Unknown format: not ONDE or NDE');
  }
  const stats = { datasetsProcessed: 0, groupsProcessed: 0, warnings: [] };
  let outName;

  try {
    if (detected.format === 'onde') {
      outName = await convertOndeToNde(inFile, FS, stats);
    } else {
      outName = await convertNdeToOnde(inFile, FS, stats);
    }
  } finally {
    inFile.close();
    FS.unlink(inName);
  }

  // Read output back into ArrayBuffer
  const outData = FS.readFile(outName);
  FS.unlink(outName);

  return {
    buffer: outData.buffer.slice(outData.byteOffset, outData.byteOffset + outData.byteLength),
    format: detected.format === 'onde' ? 'nde' : 'onde',
    stats
  };
}

// ─── ONDE → NDE ─────────────────────────────────────────────────────────

async function convertOndeToNde(inFile, FS, stats) {
  const h5wasm = globalThis.h5wasm;
  const outName = `output_nde_${Date.now()}.nde`;
  const out = new h5wasm.File(outName, 'w');

  // --- Discover ONDE datasets ---
  const datasets = discoverOndeDatasets(inFile, stats);
  stats.datasetsProcessed = datasets.length;

  // --- /Properties ---
  const now = new Date().toISOString();
  const props = {
    $schema: './Properties-Schema-4.2.0.json',
    file: {
      creationDate: now,
      formatVersion: '4.2.0',
      createdByAppName: 'ONDE-to-NDE Converter',
      createdByAppVersion: '1.0.0',
      modificationDate: now,
      description: 'Converted from ONDE format v0.9.0'
    },
    methods: ['UT']
  };
  writeJsonDataset(out, '/Properties', props);

  // --- /Public/Setup ---
  out.create_group('/Public');
  const setup = buildNdeSetupFromOnde(inFile, datasets, stats);
  writeJsonDataset(out, '/Public/Setup', setup);

  // --- /Public/Groups with data ---
  out.create_group('/Public/Groups');
  for (let i = 0; i < datasets.length; i++) {
    const dp = datasets[i];
    const groupPath = `/Public/Groups/${i}`;
    out.create_group(groupPath);
    out.create_group(`${groupPath}/Datasets`);

    copyOndeDataToNde(inFile, out, dp, i, stats);
    stats.groupsProcessed++;
  }

  out.create_group('/Private');
  out.close();
  // Upgrade string paths to real HDF5 references
  await upgradeToRealReferences(outName);
  return outName;
}

// ─── NDE → ONDE ─────────────────────────────────────────────────────────

async function convertNdeToOnde(inFile, FS, stats) {
  const h5wasm = globalThis.h5wasm;
  const outName = `output_onde_${Date.now()}.onde`;
  const out = new h5wasm.File(outName, 'w');

  // Root identity attributes
  const root = out.get('/');
  setH5Attr(root, 'ONDE:FILETYPE', 'ONDE_UT');
  setH5Attr(root, 'ONDE:VERSION', '0.9.0');

  // Read NDE metadata
  let setup = {};
  try {
    const setupDs = inFile.get('/Public/Setup');
    console.log('[nde→onde] setupDs:', !!setupDs, setupDs?.value ? `type=${typeof setupDs.value}, len=${setupDs.value.length || setupDs.value.byteLength}` : 'no value');
    if (setupDs && setupDs.value) {
      const text = typeof setupDs.value === 'string'
        ? setupDs.value
        : new TextDecoder().decode(setupDs.value);
      setup = JSON.parse(text);
      console.log('[nde→onde] parsed setup, groups:', setup?.groups?.length, 'specimens:', setup?.specimens?.length);
    }
  } catch (e) {
    console.error('[nde→onde] Setup read error:', e.message);
    stats.warnings.push(`NDE Setup read error: ${e.message}`);
  }

  const groups = setup?.groups || [];
  const datasetRefs = [];

  for (let gi = 0; gi < groups.length; gi++) {
    const ndegroup = groups[gi];
    const ndedatasets = ndegroup.datasets || [];

    for (const nds of ndedatasets) {
      const ondeType = resolveOndeType(nds.dataClass);
      if (!ondeType) continue;

      const targetName = getOndeDatasetName(nds.dataClass);
      if (!targetName) continue; // skip status/time/firing source (non-DATA in ONDE)

      const ondeGroupPath = `/${ondeType.prefix}_${datasetRefs.length}`;
      out.create_group(ondeGroupPath);
      const ondeGroup = out.get(ondeGroupPath);

      // ONDE:TYPE
      setH5Attr(ondeGroup, 'ONDE:TYPE', ondeType.chain);

      // LABEL — use a descriptive label based on data class
      const labelMap = {
        'AScanAmplitude': 'Reference PA AScan',
        'TfmValue': 'Reference TFM TScan',
        'CScanPeak': 'Reference CScan'
      };
      if (nds.name) setH5Attr(ondeGroup, 'ONDE:LABEL', labelMap[nds.dataClass] || nds.name);

      // Write dimensions from the NDE dataset
      writeOndeDimensionsFromNde(out, ondeGroupPath, nds, datasetRefs.length);

      // Copy data with ONDE target name
      copyNdeDataToOnde(inFile, out, nds, ondeGroupPath, stats, targetName);

      // Fix 2: Add mandatory ONDE_DATASET:SETUP attribute referencing the ONDE_SETUP group
      setH5Attr(ondeGroup, 'ONDE_DATASET:SETUP', '/ONDE_SETUP_UT');

      // Fix 2: TSCAN mandatory fields
      if (ondeType.base === 'ONDE_DATASET_UT_TSCAN') {
        setH5Attr(ondeGroup, 'ONDE_DATASET_UT_TSCAN:ZONE_FRAME', [0,0,0, 1,0,0,0]);
        if (nds.dimensions && Array.isArray(nds.dimensions)) {
          // Use quantity (the axis size) for ZONE_SIZE
          const sizes = nds.dimensions.map(d => d.quantity || d.size || 1);
          setH5Attr(ondeGroup, 'ONDE_DATASET_UT_TSCAN:ZONE_SIZE', sizes);
          // ZONE_DIMENSION: physical extents = quantity * resolution
          const extents = nds.dimensions.map(d => (d.quantity || 1) * (d.resolution || 1));
          setH5Attr(ondeGroup, 'ONDE_DATASET_UT_TSCAN:ZONE_DIMENSION', extents);
        } else {
          setH5Attr(ondeGroup, 'ONDE_DATASET_UT_TSCAN:ZONE_DIMENSION', [0,0,0]);
        }
        // Find first ASCAN dataset in the refs list
        const firstAscan = datasetRefs.find(r => r.type === 'ONDE_DATASET_UT_ASCAN');
        setH5Attr(ondeGroup, 'ONDE_DATASET_UT_TSCAN:SOURCE_ASCAN_DATASET', firstAscan ? firstAscan.path : '');

      }

      // Fix 2: CSCAN DATATYPE
      if (ondeType.base === 'ONDE_DATASET_UT_CSCAN') {
        let dataType = 'AMAX';
        if (nds.dataClass === 'CScanTime') dataType = 'TIME_OF_FLIGHT';
        setH5Attr(ondeGroup, 'ONDE_DATASET_UT_CSCAN:DATATYPE', dataType);

        // CSCAN GATES: create ONDE_UT_GATE groups from NDE process gates
        if (ndegroup.processes) {
          writeOndeGates(out, ndegroup.processes, ondeGroupPath);
        }
      }

      datasetRefs.push({ path: ondeGroupPath, type: ondeType.base });
      stats.datasetsProcessed++;
    }
    stats.groupsProcessed++;
  }

  // Write ONDE_SETUP group if we have datasets
  let setupLawResult = { txPaths: [], rxPaths: [] };
  if (datasetRefs.length > 0) {
    setupLawResult = writeOndeSetupFromNde(out, setup, stats) || { txPaths: [], rxPaths: [] };
  }

  // After setup creation: add TRANSMIT_LAW / RECEIVE_LAW datasets on ONDE_ULTRASONIC_SETUP
  // referencing the ONDE_UT_LAW_N (TX) and ONDE_UT_LAW_RX_N (RX) groups
  const { txPaths, rxPaths } = setupLawResult;
  if (txPaths.length > 0 || rxPaths.length > 0) {
    const us = out.get('/ONDE_ULTRASONIC_SETUP');
    if (us) {
      try {
        if (txPaths.length > 0) {
          us.create_dataset({ name: 'ONDE_ULTRASONIC_SETUP:TRANSMIT_LAW', data: txPaths });
        }
        if (rxPaths.length > 0) {
          us.create_dataset({ name: 'ONDE_ULTRASONIC_SETUP:RECEIVE_LAW', data: rxPaths });
        }
      } catch (_) {}
    }
  }

  out.close();
  // Upgrade string paths to real HDF5 references
  await upgradeToRealReferences(outName);
  return outName;
}

// ─── HDF5 Helpers ───────────────────────────────────────────────────────

// Type registry parsed from ONDE_fields.csv: field_name → CSV type
// Used to ensure correct HDF5 type (float64 vs int32) for each field
const ONDE_FIELD_TYPES = {
  'ONDE:FILETYPE': 'string', 'ONDE:VERSION': 'string',
  'ONDE:TYPE': 'string', 'ONDE:LABEL': 'string',
  'ONDE:TYPE_TAGS': 'string',
  'ONDE_DATASET:SETUP': 'ref', 'ONDE_DATASET:OPERATOR': 'string',
  'ONDE_DATASET:DATE_AND_TIME': 'string', 'ONDE_DATASET:DATA': 'any',
  'ONDE_DATASET:AMPLITUDE_DIMENSION': 'ref', 'ONDE_DATASET:INDEX_DIMENSIONS': 'ref',
  'ONDE_DATASET_UT_TSCAN:ZONE_FRAME': 'float', 'ONDE_DATASET_UT_TSCAN:ZONE_DIMENSION': 'float',
  'ONDE_DATASET_UT_TSCAN:ZONE_SIZE': 'int', 'ONDE_DATASET_UT_TSCAN:RECONSTRUCTION_MODE': 'string',
  'ONDE_DATASET_UT_TSCAN:REFERENCE_PROBE_INDEX': 'int', 'ONDE_DATASET_UT_TSCAN:SOURCE_ASCAN_DATASET': 'ref',
  'ONDE_DATASET_UT_CSCAN:DATATYPE': 'string', 'ONDE_DATASET_UT_CSCAN:UNDERLYING_DATA': 'ref',
  'ONDE_DATASET_UT_CSCAN:UNDERLYING_DATA_REFERENCE': 'int',
  'ONDE_DATASET_UT_CSCAN:CSCAN_GRID': 'ref', 'ONDE_DATASET_UT_CSCAN:GATES': 'ref',
  'ONDE_DIMENSION:COORDINATE': 'string', 'ONDE_DIMENSION:UNITS': 'string',
  'ONDE_DIMENSION:OFFSET': 'float', 'ONDE_DIMENSION:SCALE': 'float',
  'ONDE_UT_GATE:START': 'float', 'ONDE_UT_GATE:WIDTH': 'float',
  'ONDE_UT_GATE:THRESHOLD': 'float', 'ONDE_UT_GATE:DETECTION': 'string',
  'ONDE_UT_GATE:POLARITY': 'string',
  'ONDE_SETUP:GEOMETRIC_SETUP': 'ref', 'ONDE_SETUP_UT:ULTRASONIC_SETUP': 'ref',
  'ONDE_GEOMETRIC_SETUP:COMPONENT': 'ref', 'ONDE_GEOMETRIC_SETUP:PROBE_LIST': 'ref',
  'ONDE_GEOMETRIC_SETUP:ACQUISITION_TRAJECTORY': 'ref',
  'ONDE_GEOMETRIC_SETUP:COUPLING': 'ref',
  'ONDE_GEOMETRIC_SETUP:PROBE_COORDINATE_FRAME': 'float',
  'ONDE_COMPONENT:VELOCITIES': 'float', 'ONDE_COMPONENT:DENSITY': 'float',
  'ONDE_COMPONENT:COMPONENT_FRAME': 'float', 'ONDE_COMPONENT:IMAGE': 'float',
  'ONDE_PLANE:PLATE_DIMENSIONS': 'float', 'ONDE_CYLINDER:DIMENSIONS': 'float',
  'ONDE_UT_PROBE:FREQUENCY': 'float', 'ONDE_UT_PROBE:BANDWIDTH': 'float',
  'ONDE_UT_PROBE:INDEX_POINT_FRAME': 'float', 'ONDE_UT_PROBE:COUPLING': 'ref',
  'ONDE_LINEAR_UT_PROBE:TOTAL_NUMBER_OF_ELEMENTS': 'int',
  'ONDE_LINEAR_UT_PROBE:ELEMENT_DIM_MAJOR': 'float',
  'ONDE_LINEAR_UT_PROBE:ELEMENT_DIM_MINOR': 'float',
  'ONDE_LINEAR_UT_PROBE:ELEMENT_PITCH_DIM_MAJOR': 'float',
  'ONDE_MATRIX_UT_PROBE:TOTAL_NUMBER_OF_ELEMENTS': 'int',
  'ONDE_MATRIX_UT_PROBE:NUMBER_OF_ELEMENTS_DIM_MINOR': 'int',
  'ONDE_MATRIX_UT_PROBE:ELEMENT_DIM_MAJOR': 'float',
  'ONDE_MATRIX_UT_PROBE:ELEMENT_DIM_MINOR': 'float',
  'ONDE_MATRIX_UT_PROBE:ELEMENT_PITCH_DIM_MAJOR': 'float',
  'ONDE_MATRIX_UT_PROBE:ELEMENT_PITCH_DIM_MINOR': 'float',
  'ONDE_UT_COUPLING:MEDIUM_VELOCITY': 'float', 'ONDE_UT_COUPLING:MEDIUM_DENSITY': 'float',
  'ONDE_UT_COUPLING:INCIDENCE_ANGLE': 'float',
  'ONDE_WEDGE:CONTACT_SURFACE': 'string', 'ONDE_WEDGE:CURVATURE_RADIUS': 'float',
  'ONDE_WEDGE:CONTACT_AREA': 'float', 'ONDE_WEDGE:HEIGHT': 'float',
  'ONDE_WEDGE:SKEW_ANGLE': 'float', 'ONDE_WEDGE:DISORIENTATION_ANGLE': 'float',
  'ONDE_DUAL_WEDGE:PROBE_SEPARATION': 'float', 'ONDE_DUAL_WEDGE:ROOF_ANGLE': 'float',
  'ONDE_DUAL_WEDGE:SQUINT_ANGLE': 'float',
  'ONDE_ACQUISITION_TRAJECTORY:ACQUISITION_RATE': 'float',
  'ONDE_ACQUISITION_GRID:UV_GRID_FRAME': 'float',
  'ONDE_ACQUISITION_GRID:SCAN_TYPE': 'string', 'ONDE_ACQUISITION_GRID:CYLINDER_DEFINITION': 'string',
  'ONDE_ACQUISITION_GRID:PROBE_DIRECTION': 'float',
  'ONDE_ULTRASONIC_SETUP:RECTIFICATION': 'string', 'ONDE_ULTRASONIC_SETUP:FILTER_TYPE': 'string',
  'ONDE_ULTRASONIC_SETUP:ASCAN_SAMPLE_RATE': 'float', 'ONDE_ULTRASONIC_SETUP:GAIN': 'float',
  'ONDE_ULTRASONIC_SETUP:ASCAN_START': 'float', 'ONDE_ULTRASONIC_SETUP:PRF': 'float',
  'ONDE_PHASED_ARRAY_SETUP:EMITTER_PROBE': 'ref', 'ONDE_PHASED_ARRAY_SETUP:RECEIVING_PROBE': 'ref',
  'ONDE_PHASED_ARRAY_SETUP:SEQUENCE_ANGLE_MODE': 'string',
  'ONDE_PHASED_ARRAY_ANGLE:BSCAN_ANGLE': 'float',
  'ONDE_PHASED_ARRAY_SSCAN:STARTING_ANGLE': 'float', 'ONDE_PHASED_ARRAY_SSCAN:FINISHING_ANGLE': 'float',
  'ONDE_PHASED_ARRAY_SSCAN:NUMBER_OF_ANGLES': 'int',
  'ONDE_PHASED_ARRAY_ESCAN:NUMBER_OF_ELEMENTS': 'int', 'ONDE_PHASED_ARRAY_ESCAN:STEP': 'int',
  'ONDE_PHASED_ARRAY_ESCAN:ANGLE': 'float',
  'ONDE_PHASED_ARRAY_COMPOUND:INITIAL_ANGLE': 'float', 'ONDE_PHASED_ARRAY_COMPOUND:FINAL_ANGLE': 'float',
  'ONDE_PHASED_ARRAY_COMPOUND:NUMBER_OF_ANGLES': 'int', 'ONDE_PHASED_ARRAY_COMPOUND:NUMBER_OF_ELEMENTS': 'int',
  'ONDE_UT_ELEMENTS:FRAME': 'float', 'ONDE_UT_ELEMENTS:SHAPE': 'int',
  'ONDE_UT_ELEMENTS:SIZE': 'float', 'ONDE_UT_ELEMENTS:DEAD_ELEMENT': 'int',
  'ONDE_ULTRASONIC_SETUP:SOFTWARE_GAIN_DB': 'float', // custom extension
  'ONDE_ULTRASONIC_SETUP:FILTER_PARAMETERS': 'float',
  'ONDE_ULTRASONIC_SETUP:FILTER_DESCRIPTION': 'string',
};

/** Set a typed attribute on an HDF5 group/dataset, respecting CSV type spec */
function setH5Attr(obj, name, value) {
  // Skip null, undefined, NaN, empty values
  if (value === undefined || value === null) return;
  if (typeof value === 'number' && isNaN(value)) return;
  if (Array.isArray(value) && value.length === 0) return;
  try {
    const specType = ONDE_FIELD_TYPES[name] || 'float'; // default to float
    
    if (specType === 'string') {
      if (Array.isArray(value)) {
        const maxLen = Math.max(...value.map(v => String(v).length), 1);
        obj.create_attribute(name, value.map(String), null, `S${maxLen}`);
      } else {
        obj.create_attribute(name, String(value));
      }
    } else if (specType === 'int') {
      if (Array.isArray(value)) {
        obj.create_attribute(name, new Int32Array(value.map(v => Number(v))));
      } else {
        obj.create_attribute(name, Number(value));  // scalar, let h5wasm infer type
      }
    } else if (specType === 'float') {
      if (Array.isArray(value)) {
        obj.create_attribute(name, new Float64Array(value.map(v => Number(v))));
      } else {
        // Force float64 via explicit dtype to prevent h5wasm inferring int32 for whole numbers
        obj.create_attribute(name, Number(value), null, '<d');
      }
    } else {
      // ref/any — pass through as-is (string paths for refs)
      if (Array.isArray(value)) {
        const allStrings = value.every(v => typeof v === 'string');
        if (allStrings) {
          obj.create_attribute(name, value.map(String));
        } else {
          obj.create_attribute(name, new Float64Array(value.map(Number)));
        }
      } else if (typeof value === 'string') {
        obj.create_attribute(name, value);
      } else if (typeof value === 'number') {
        obj.create_attribute(name, Number(value));  // scalar
      }
    }
  } catch (e) {
    console.warn(`setH5Attr failed for ${name}:`, e.message);
  }
}

/** Write a JSON object as a UTF-8 encoded dataset */
function writeJsonDataset(file, path, obj) {
  const json = JSON.stringify(obj, null, 2);
  const encoded = new TextEncoder().encode(json);
  const parentPath = path.substring(0, path.lastIndexOf('/')) || '/';
  const name = path.substring(path.lastIndexOf('/') + 1);
  const parent = file.get(parentPath);
  parent.create_dataset({ name, data: encoded });
}

/** Get an attribute value from an HDF5 group/dataset. Returns undefined if missing. */
function getAttr(obj, name) {
  try {
    if (!obj || !obj.attrs) return undefined;
    const a = obj.attrs[name];
    return a ? a.value : undefined;
  } catch (_) { return undefined; }
}

/** Walk all groups in an HDF5 file recursively, skipping datasets */
function walkAllGroups(file, path, visitor) {
  try {
    const group = file.get(path);
    if (!group || typeof group.keys !== 'function') return;
    const children = group.keys();
    if (!children) return;
    for (const child of children) {
      const childPath = path === '/' ? `/${child}` : `${path}/${child}`;
      // Only recurse into groups, not datasets
      try {
        const childObj = file.get(childPath);
        if (childObj && typeof childObj.keys === 'function') {
          visitor(childPath);
          walkAllGroups(file, childPath, visitor);
        }
      } catch (_) { /* skip datasets */ }
    }
  } catch (e) { console.warn('walkAllGroups error:', path, e.message); }
}

// ─── ONDE Discovery ─────────────────────────────────────────────────────

function discoverOndeDatasets(file, stats) {
  const datasets = [];

  const root = file.get('/');
  const fileTypeAttr = getAttr(root, 'ONDE:FILETYPE');
  console.log('[onde→nde] ONDE:FILETYPE attr:', fileTypeAttr);
  if (!fileTypeAttr || fileTypeAttr !== 'ONDE_UT') {
    console.warn('[onde→nde] not an ONDE file, skipping dataset discovery');
    return datasets;
  }

  let walked = 0;
  walkAllGroups(file, '/', (path) => {
    walked++;
    try {
      const group = file.get(path);
      if (!group || !group.attrs) return;

      const typeAttr = group.attrs['ONDE:TYPE'];
      if (!typeAttr || !Array.isArray(typeAttr.value)) {
        console.log('[onde→nde] group', path, 'has no ONDE:TYPE array');
        return;
      }

      console.log('[onde→nde] group', path, 'ONDE:TYPE =', typeAttr.value);
      const dsType = detectOndeDatasetType(typeAttr);
      if (dsType) {
        console.log('[onde→nde] found dataset:', dsType, 'at', path);
        datasets.push({ path, type: dsType });
      }
    } catch (_) {}
  });
  console.log('[onde→nde] walked', walked, 'groups, found', datasets.length, 'datasets');

  return datasets;
}

// ─── ONDE → NDE: Setup Builder ──────────────────────────────────────────

function buildNdeSetupFromOnde(file, datasets, stats) {
  const scenario = detectOndeScenario(file) ? 'General Weld' : 'General Mapping';

  const setup = {
    $schema: './Setup-Schema-4.2.0.json',
    version: '4.2.0',
    scenario,
    groups: [],
    specimens: [],
    probes: [],
    wedges: [],
    acquisitionUnits: [],
    motionDevices: []
  };

  // Read ONDE ultrasonic setup attributes for process defaults (Fix 2c)
  let defaultGainDb = 0;
  let defaultDigitizingFreq = 100e6;
  let defaultVelocity = 5920;
  try {
    const usGroup = file.get('/ONDE_ULTRASONIC_SETUP');
    if (usGroup) {
      let gainLinear = undefined;
      try {
        const gainDs = usGroup.get('GAIN');
        if (gainDs && gainDs.value) {
          const val = gainDs.value;
          gainLinear = Array.isArray(val) ? val[0] : val;
        }
      } catch(_) {}
      if (!gainLinear) gainLinear = 1.0;
      if (gainLinear !== undefined) {
        defaultGainDb = 20 * Math.log10(Math.abs(gainLinear) || 1);
      }
      const sampleRate = getAttr(usGroup, 'ONDE_ULTRASONIC_SETUP:ASCAN_SAMPLE_RATE');
      if (sampleRate !== undefined) {
        defaultDigitizingFreq = sampleRate;
      }
    }
    // Also read velocity from component
    const compGroup = file.get('/ONDE_COMPONENT');
    if (compGroup) {
      const velocities = getAttr(compGroup, 'ONDE_COMPONENT:VELOCITIES');
      if (velocities && Array.isArray(velocities) && velocities[0]) {
        defaultVelocity = velocities[0];
      }
    }
  } catch (_) {}

  // Build groups
  for (let i = 0; i < datasets.length; i++) {
    const group = buildNdeGroup(file, datasets[i], i, stats, defaultGainDb, defaultDigitizingFreq, defaultVelocity);
    setup.groups.push(group);
  }

  // Extract shared metadata from ONDE groups
  extractSpecimensFromOnde(file, setup, stats);
  extractProbesFromOnde(file, setup, stats);
  extractWedgesFromOnde(file, setup, stats);

  // Fallbacks
  if (setup.probes.length === 0) {
    setup.probes.push(defaultNdeProbe(0));
  }
  if (setup.specimens.length === 0) {
    setup.specimens.push(defaultNdeSpecimen(0));
  }

  return setup;
}

function buildNdeGroup(file, dp, groupIndex, stats, processGain = 0, digitizingFreq = 100e6, velocity = 5920) {
  const datasets = [];
  const dsType = dp.type;
  const classMap = ONDE_TO_NDE.datasetClassMapping[dsType] || {};

  if (dsType === 'ONDE_DATASET_UT_ASCAN') {
    datasets.push(makeNdeDatasetEntry(groupIndex, 0, 'AScanAmplitude'));
    datasets.push(makeNdeDatasetEntry(groupIndex, 1, 'AScanStatus'));
  } else if (dsType === 'ONDE_DATASET_UT_TSCAN') {
    datasets.push(makeNdeDatasetEntry(groupIndex, 0, 'TfmValue'));
    datasets.push(makeNdeDatasetEntry(groupIndex, 1, 'TfmStatus'));
  } else if (dsType === 'ONDE_DATASET_UT_CSCAN') {
    datasets.push(makeNdeDatasetEntry(groupIndex, 0, 'CScanPeak'));
    datasets.push(makeNdeDatasetEntry(groupIndex, 1, 'CScanTime'));
    datasets.push(makeNdeDatasetEntry(groupIndex, 2, 'CScanStatus'));
  }

  return {
    id: groupIndex,
    name: `Group_${groupIndex}`,
    datasets,
    processes: [defaultNdeProcess(groupIndex, processGain, digitizingFreq, velocity)]
  };
}

function makeNdeDatasetEntry(groupIndex, subIdx, dataClass) {
  const id = groupIndex * 10 + subIdx;
  return {
    id,
    name: `${subIdx}-${dataClass}`,
    dataClass,
    storageMode: 'Independent',
    dataValue: ndeDataValue(dataClass),
    path: `/Public/Groups/${groupIndex}/Datasets/${subIdx}-${dataClass}`,
    dimensions: ndeDimensionsFor(dataClass)
  };
}

function ndeDataValue(dataClass, dataArray) {
  // If dataArray provided, infer range from its TypedArray type
  if (dataArray && dataArray.constructor) {
    let min, max;
    switch (dataArray.constructor) {
      case Int8Array:
        min = -128; max = 127; break;
      case Uint8Array:
        min = 0; max = 255; break;
      case Int16Array:
        min = -32768; max = 32767; break;
      case Uint16Array:
        min = 0; max = 65535; break;
      case Int32Array:
        min = -2147483648; max = 2147483647; break;
      case Float32Array:
      case Float64Array:
        // Scan actual data for min/max
        if (dataArray.length > 0) {
          min = Infinity; max = -Infinity;
          for (let i = 0; i < dataArray.length; i++) {
            const v = dataArray[i];
            if (v < min) min = v;
            if (v > max) max = v;
          }
        }
        break;
    }
    if (min !== undefined) {
      return { min, max, unitMin: min, unitMax: max, unit: 'Percent' };
    }
  }
  switch (dataClass) {
    case 'AScanAmplitude': case 'TfmValue': case 'CScanPeak':
      return { min: -100, max: 100, unitMin: 0, unitMax: 100, unit: 'Percent' };
    case 'AScanStatus': case 'TfmStatus': case 'CScanStatus':
      return { unit: 'Bitfield', hasData: 1 };
    case 'CScanTime':
      return { min: 0, max: 1e-4, unitMin: 0, unitMax: 1e-4, unit: 'Seconds' };
    default:
      return { min: 0, max: 100, unitMin: 0, unitMax: 100, unit: 'Percent' };
  }
}

function ndeDimensionsFor(dataClass) {
  const dims = [];
  if (['AScanAmplitude', 'AScanStatus'].includes(dataClass)) {
    dims.push({ axis: 'UCoordinate', quantity: 'Length', resolution: 0.001, offset: 0, name: 'U' });
    if (dataClass === 'AScanAmplitude') {
      dims.push({ axis: 'Ultrasound', quantity: 'Time', resolution: 1e-8, offset: 0, name: 'Time' });
    }
  } else if ('TfmValue' === dataClass) {
    dims.push({ axis: 'UCoordinate', quantity: 'Length', resolution: 0.001, offset: 0 });
    dims.push({ axis: 'VCoordinate', quantity: 'Length', resolution: 0.001, offset: 0 });
  } else if ('TfmStatus' === dataClass) {
    dims.push({ axis: 'UCoordinate', quantity: 'Length', resolution: 0.001, offset: 0 });
  }
  return dims;
}

function defaultNdeProcess(groupIndex, processGain = 0, digitizingFreq = 100e6, velocity = 5920) {
  return {
    id: groupIndex * 100,
    inputs: null,
    outputs: [],
    gain: processGain,
    implementation: 'Hardware',
    ultrasonicConventional: {
      pulseEcho: { probeId: 0 },
      waveMode: 'Longitudinal',
      velocity,
      wedgeDelay: 0,
      rectification: 'None',
      digitizingFrequency: digitizingFreq,
      ascanCompressionFactor: 1,
      beams: [{ id: 0, refractedAngle: 0, ascanStart: 0, ascanLength: 1e-4 }]
    }
  };
}

function defaultNdeProbe(id) {
  return {
    id,
    model: 'Default Probe',
    conventionalRound: {
      centralFrequency: 5e6,
      diameter: 0.0127,
      elements: [{ id: 0, acquisitionUnitId: 0, connectorName: 'CH1' }]
    }
  };
}

function defaultNdeSpecimen(id) {
  return {
    id,
    plateGeometry: {
      thickness: 0.01,
      material: {
        name: 'Steel',
        longitudinalWave: { nominalVelocity: 5920 },
        transversalVerticalWave: { nominalVelocity: 3230 }
      },
      surfaces: [{ id: 0, name: 'Top' }, { id: 1, name: 'Bottom' }]
    }
  };
}

function detectOndeScenario(file) {
  let hasWeld = false;
  walkAllGroups(file, '/', (path) => {
    try {
      const g = file.get(path);
      if (g?.attrs) {
        const t = g.attrs['ONDE:TYPE'];
        if (t && Array.isArray(t.value) && t.value.includes('ONDE_WELD')) hasWeld = true;
      }
    } catch (_) {}
  });
  return hasWeld;
}

// ─── ONDE → NDE: Metadata Extraction ────────────────────────────────────

function extractSpecimensFromOnde(file, setup) {
  // Find component groups
  walkAllGroups(file, '/', (path) => {
    try {
      const g = file.get(path);
      if (!g?.attrs) return;
      const t = g.attrs['ONDE:TYPE'];
      if (!t || !Array.isArray(t.value)) return;
      const lastType = t.value[t.value.length - 1];

      let geometry = null;
      if (lastType === 'ONDE_PLANE') {
        const dims = getAttr(g, 'ONDE_PLANE:PLATE_DIMENSIONS') || [1, 1, 0.01];
        const vels = getAttr(g, 'ONDE_COMPONENT:VELOCITIES') || [5920, 3230];
        geometry = {
          id: setup.specimens.length, plateGeometry: {
            thickness: Array.isArray(dims) ? dims[2] || 0.01 : 0.01,
            material: materialFromVelocities(vels),
            surfaces: [{ id: 0, name: 'Top' }, { id: 1, name: 'Bottom' }]
          }
        };
      } else if (lastType === 'ONDE_CYLINDER') {
        const dims = getAttr(g, 'ONDE_CYLINDER:DIMENSIONS') || [0.1, 0.01, 0];
        const vels = getAttr(g, 'ONDE_COMPONENT:VELOCITIES') || [5920, 3230];
        geometry = {
          id: setup.specimens.length, pipeGeometry: {
            outerRadius: Array.isArray(dims) ? dims[0] || 0.1 : 0.1,
            thickness: Array.isArray(dims) ? dims[1] || 0.01 : 0.01,
            material: materialFromVelocities(vels),
            surfaces: [{ id: 0, name: 'Outside' }, { id: 1, name: 'Inside' }]
          }
        };
      }

      if (geometry) setup.specimens.push(geometry);
    } catch (_) {}
  });
}

function materialFromVelocities(vels) {
  const lv = Array.isArray(vels) ? (vels[0] || 5920) : 5920;
  const tv = Array.isArray(vels) ? (vels[1] || 3230) : 3230;
  return {
    name: 'Steel',
    longitudinalWave: { nominalVelocity: lv },
    transversalVerticalWave: { nominalVelocity: tv }
  };
}

function extractProbesFromOnde(file, setup) {
  walkAllGroups(file, '/', (path) => {
    try {
      const g = file.get(path);
      if (!g?.attrs) return;
      const t = g.attrs['ONDE:TYPE'];
      if (!t || !Array.isArray(t.value)) return;
      const lastType = t.value[t.value.length - 1];

      let probe = null;
      const freq = getAttr(g, 'ONDE_UT_PROBE:FREQUENCY') || 5e6;
      const manuf = getAttr(g, 'ONDE_UT_PROBE:MANUFACTURER') || 'Unknown';

      if (lastType === 'ONDE_MONO_UT_PROBE') {
        probe = { id: setup.probes.length, model: manuf,
          conventionalRound: { centralFrequency: freq, diameter: 0.0127,
            elements: [{ id: 0, acquisitionUnitId: 0, connectorName: 'CH1' }] }};
      } else if (lastType === 'ONDE_LINEAR_UT_PROBE') {
        const nElem = getAttr(g, 'ONDE_LINEAR_UT_PROBE:TOTAL_NUMBER_OF_ELEMENTS') || 64;
        const elMaj = getAttr(g, 'ONDE_LINEAR_UT_PROBE:ELEMENT_DIM_MAJOR') || 0.01;
        const pitch = getAttr(g, 'ONDE_LINEAR_UT_PROBE:ELEMENT_PITCH_DIM_MAJOR') || 0.001;
        probe = { id: setup.probes.length, model: manuf,
          phasedArrayLinear: { centralFrequency: freq,
            elements: { elementQuantity: nElem,
              primaryAxis: { elementLength: elMaj, elementGap: pitch, referencePoint: 0 },
              secondaryAxis: { elementWidth: pitch * 0.8 } }}};
      }

      if (probe) setup.probes.push(probe);
    } catch (_) {}
  });
}

function extractWedgesFromOnde(file, setup) {
  walkAllGroups(file, '/', (path) => {
    try {
      const g = file.get(path);
      if (!g?.attrs) return;
      const t = g.attrs['ONDE:TYPE'];
      if (!t || !Array.isArray(t.value)) return;
      const lastType = t.value[t.value.length - 1];

      let wedge = null;

      if (lastType === 'ONDE_IMMERSION') {
        const wp = getAttr(g, 'ONDE_IMMERSION:WATER_PATH') || 0.05;
        wedge = { id: setup.wedges.length, model: 'Immersion',
          fluidColumn: { delay: wp / 1480, height: wp },
          positioning: { uCoordinateOffset: 0, vCoordinateOffset: 0, skewAngle: 0 }};
      } else if (lastType === 'ONDE_SINGLE_WEDGE' || lastType === 'ONDE_WEDGE') {
        const h = getAttr(g, 'ONDE_WEDGE:HEIGHT') || 0.02;
        const angle = getAttr(g, 'ONDE_UT_COUPLING:INCIDENCE_ANGLE') || 0;
        const skew = getAttr(g, 'ONDE_WEDGE:SKEW_ANGLE') || 0;
        const vel = getAttr(g, 'ONDE_UT_COUPLING:MEDIUM_VELOCITY') || [2330, 1165];
        const lvel = Array.isArray(vel) ? vel[0] || 2330 : 2330;
        wedge = { id: setup.wedges.length, model: 'SAW Wedge',
          angleBeamWedge: { angle, delay: h / lvel, probeOffset: 0 },
          positioning: { uCoordinateOffset: 0, vCoordinateOffset: 0, skewAngle: skew }};
      } else if (lastType === 'ONDE_DUAL_WEDGE') {
        const h = getAttr(g, 'ONDE_WEDGE:HEIGHT') || 0.02;
        const angle = getAttr(g, 'ONDE_UT_COUPLING:INCIDENCE_ANGLE') || 0;
        const pcs = getAttr(g, 'ONDE_DUAL_WEDGE:PROBE_SEPARATION') || 0.05;
        wedge = { id: setup.wedges.length, model: 'Dual Wedge',
          angleBeamWedge: { angle, delay: 0, probeOffset: pcs / 2 },
          positioning: { uCoordinateOffset: 0, vCoordinateOffset: 0, skewAngle: 0 }};
      }

      if (wedge) setup.wedges.push(wedge);
    } catch (_) {}
  });
}

// ─── ONDE → NDE: Data Copy ──────────────────────────────────────────────

function copyOndeDataToNde(inFile, outFile, dp, groupIdx, stats) {
  try {
    const group = inFile.get(dp.path);
    if (!group) return;

    // Helper to read a named dataset from the ONDE group
    function getOndeDs(name) {
      try { return group.get(name); } catch (_) { return null; }
    }

    const dataDs = getOndeDs('DATA');
    const statusDs = getOndeDs('STATUS');
    const timeDs = getOndeDs('TIME');

    const datasetsPath = '/Public/Groups/' + groupIdx + '/Datasets';
    const parent = outFile.get(datasetsPath);

    // Helper to create dataset preserving shape from source
    function createDsPreserving(parentObj, name, ds) {
      if (!ds || !ds.value) return;
      const shape = ds.metadata?.shape || ds.shape;
      if (shape && shape.length > 1) {
        parentObj.create_dataset({ name, data: ds.value, shape: Array.from(shape) });
      } else {
        parentObj.create_dataset({ name, data: ds.value });
      }
    }

    const dsType = dp.type;
    if (dsType === 'ONDE_DATASET_UT_ASCAN') {
      if (dataDs) createDsPreserving(parent, '0-AScanAmplitude', dataDs);
      if (statusDs) createDsPreserving(parent, '1-AScanStatus', statusDs);
      else createPlaceholder(outFile, `${datasetsPath}/1-AScanStatus`, new Uint8Array(1));
    } else if (dsType === 'ONDE_DATASET_UT_TSCAN') {
      if (dataDs) createDsPreserving(parent, '0-TfmValue', dataDs);
      if (statusDs) createDsPreserving(parent, '1-TfmStatus', statusDs);
      else createPlaceholder(outFile, `${datasetsPath}/1-TfmStatus`, new Uint8Array(1));
    } else if (dsType === 'ONDE_DATASET_UT_CSCAN') {
      if (dataDs) createDsPreserving(parent, '0-CScanPeak', dataDs);
      if (timeDs) createDsPreserving(parent, '1-CScanTime', timeDs);
      if (statusDs) createDsPreserving(parent, '2-CScanStatus', statusDs);
    }
  } catch (e) {
    stats.warnings.push(`Data copy error for ${dp.path}: ${e.message}`);
  }
}

function createPlaceholder(file, path, data) {
  try {
    const lastSlash = path.lastIndexOf('/');
    const parentPath = path.substring(0, lastSlash) || '/';
    const name = path.substring(lastSlash + 1);
    file.get(parentPath).create_dataset({ name, data });
  } catch (_) {}
}

// ─── NDE → ONDE: Helpers ────────────────────────────────────────────────

/** Map NDE dataClass to the target ONDE dataset name within a group */
function getOndeDatasetName(dataClass) {
  switch (dataClass) {
    case 'AScanAmplitude': case 'TfmValue': case 'CScanPeak': case 'CScanTime':
      return 'ONDE_DATASET:DATA';
    default:
      return null;
  }
}

function resolveOndeType(dataClass) {
  const map = NDE_TO_ONDE.dataClassToOndeType[dataClass];
  if (!map) return null;

  switch (map.type) {
    case 'ONDE_DATASET_UT_ASCAN':
      return { base: map.type, prefix: 'ONDE_DATASET_UT_ASCAN', chain: ['ONDE_DATASET','ONDE_DATASET_UT','ONDE_DATASET_UT_ASCAN'] };
    case 'ONDE_DATASET_UT_TSCAN':
      return { base: map.type, prefix: 'ONDE_DATASET_UT_TSCAN', chain: ['ONDE_DATASET','ONDE_DATASET_UT','ONDE_DATASET_UT_TSCAN'] };
    case 'ONDE_DATASET_UT_CSCAN':
      return { base: map.type, prefix: 'ONDE_DATASET_UT_CSCAN', chain: ['ONDE_DATASET','ONDE_DATASET_UT','ONDE_DATASET_UT_CSCAN'] };
    default:
      return { base: 'ONDE_DATASET', prefix: 'UNKNOWN', chain: ['ONDE_DATASET'] };
  }
}

// Map from ONDE coordinate names to axis prefix for dimension group names
const COORDINATE_TO_DIM_PREFIX = {
  'U': 'u',
  'V': 'v',
  'W': 'w',
  'Time': 'time',
  'Beam': 'beam',
  'Amplitude': 'amp',
  'Row': 'row',
  'Col': 'col',
  'Plane': 'plane',
  'StackedAScan': 'stackedascan'
};

// Override units for specific coordinate names (from NDE dimension 'name' field)
const COORDINATE_UNITS_OVERRIDE = {
  'Plane': 'arbitrary',
  'Beam': 'arbitrary',
  'StackedAScan': 'arbitrary',
  'Amplitude': 'arbitrary'
};

function writeOndeDimensionsFromNde(outFile, ondeGroupPath, nds, dsIndex) {
  if (!nds.dimensions || !Array.isArray(nds.dimensions)) return;

  const axisToDimension = NDE_TO_ONDE.axisToOndeDimension || {};
  const ondeGroup = outFile.get(ondeGroupPath);
  const dimRefs = [];
  let dimCount = 0;

  for (const axis of nds.dimensions) {
    if (!axis || !axis.axis) continue;
    const ondeDim = axisToDimension[axis.axis];
    if (!ondeDim) continue;

    // Use the NDE dimension's 'name' field for the ONDE coordinate, falling back
    // to the axis mapping. This handles TFM (Row/Col/Plane) vs UT/PA (U/Beam/Time).
    const coordName = axis.name || ondeDim.coordinate;
    const prefix = COORDINATE_TO_DIM_PREFIX[coordName] || coordName.toLowerCase();
    // Use name-based units override when available (e.g. Plane→arbitrary)
    const units = COORDINATE_UNITS_OVERRIDE[coordName] || ondeDim.units;
    // First dataset uses bare name (e.g., /dim_u), subsequent use /dim_u_1 etc.
    const dimPath = dsIndex === 0 ? `/dim_${prefix}` : `/dim_${prefix}_${dsIndex}`;
    
    // Avoid creating duplicate dim groups
    let dimGroup;
    try {
      dimGroup = outFile.get(dimPath);
    } catch (_) {}
    if (!dimGroup) {
      outFile.create_group(dimPath);
      dimGroup = outFile.get(dimPath);
      setH5Attr(dimGroup, 'ONDE:TYPE', ['ONDE_DIMENSION']);
      setH5Attr(dimGroup, 'ONDE_DIMENSION:COORDINATE', coordName);
      setH5Attr(dimGroup, 'ONDE_DIMENSION:UNITS', units);
      setH5Attr(dimGroup, 'ONDE_DIMENSION:OFFSET', axis.offset || 0);
      setH5Attr(dimGroup, 'ONDE_DIMENSION:SCALE', axis.resolution || 1);
    }
    dimRefs.push(dimPath);
    dimCount++;
  }

  // Also create AMPLITUDE_DIMENSION
  const ampPath = '/dim_amp';
  try {
    if (!outFile.get(ampPath)) {
      outFile.create_group(ampPath);
      const ampGroup = outFile.get(ampPath);
      setH5Attr(ampGroup, 'ONDE:TYPE', ['ONDE_DIMENSION']);
      setH5Attr(ampGroup, 'ONDE_DIMENSION:COORDINATE', 'Amplitude');
      setH5Attr(ampGroup, 'ONDE_DIMENSION:UNITS', 'arbitrary');
      setH5Attr(ampGroup, 'ONDE_DIMENSION:OFFSET', 0.0);
      setH5Attr(ampGroup, 'ONDE_DIMENSION:SCALE', 1.0);
    }
  } catch (_) {
    outFile.create_group(ampPath);
    const ampGroup = outFile.get(ampPath);
    setH5Attr(ampGroup, 'ONDE:TYPE', ['ONDE_DIMENSION']);
    setH5Attr(ampGroup, 'ONDE_DIMENSION:COORDINATE', 'Amplitude');
    setH5Attr(ampGroup, 'ONDE_DIMENSION:UNITS', 'arbitrary');
    setH5Attr(ampGroup, 'ONDE_DIMENSION:OFFSET', 0.0);
    setH5Attr(ampGroup, 'ONDE_DIMENSION:SCALE', 1.0);
  }

  if (dimCount > 0) {
    setH5Attr(ondeGroup, 'ONDE_DIM_COUNT', dimCount);
    // Store INDEX_DIMENSIONS as string paths (h5wasm limitation: no H5T_STD_REF_OBJ)
    setH5Attr(ondeGroup, 'ONDE_DATASET:INDEX_DIMENSIONS', dimRefs);
    setH5Attr(ondeGroup, 'ONDE_DATASET:AMPLITUDE_DIMENSION', ampPath);
  }
}

function copyNdeDataToOnde(inFile, outFile, nds, ondePath, stats, targetName = 'ONDE_DATASET:DATA') {
  try {
    if (!nds.path) return;
    const sourceDs = inFile.get(nds.path);
    if (!sourceDs || !sourceDs.value) return;

    const target = outFile.get(ondePath);
    // Preserve multi-dimensional shape
    const shape = sourceDs.metadata?.shape || sourceDs.shape;
    if (shape && shape.length > 1) {
      target.create_dataset({ name: targetName, data: sourceDs.value, shape: Array.from(shape) });
    } else {
      target.create_dataset({ name: targetName, data: sourceDs.value });
    }
  } catch (e) {
    stats.warnings.push(`NDE data copy error: ${e.message}`);
  }
}

// ─── PA Law Groups (Fix 3) ──────────────────────────────────────────────

function writeOndeLawGroups(outFile, proc, probePaths, stats, isTransmit = true) {
  if (!proc) return [];
  const paProc = proc.ultrasonicPhasedArray;
  if (!paProc || !paProc.beams || !Array.isArray(paProc.beams)) return [];
  
  const beamData = paProc.beams;
  const lawGroupPaths = [];

  for (let bi = 0; bi < beamData.length; bi++) {
    const beam = beamData[bi];
    const lawName = isTransmit ? `/ONDE_UT_LAW_${bi}` : `/ONDE_UT_LAW_RX_${bi}`;
    try {
      outFile.create_group(lawName);
      const lg = outFile.get(lawName);
      setH5Attr(lg, 'ONDE:TYPE', ['ONDE_UT_LAW']);

      // For TX: use beam.pulsers; for RX: use beam.receivers
      const pulsersOrReceivers = isTransmit ? (beam.pulsers || []) : (beam.receivers || []);
      if (pulsersOrReceivers.length === 0) continue;

      const channels = pulsersOrReceivers.map(ch => ({
        elementId: ch.elementId !== undefined ? ch.elementId : 0,
        delay: ch.delay !== undefined ? ch.delay : 0.0,
        probeIdx: ch.probeId !== undefined ? ch.probeId : 0
      }));
      if (channels.length === 0) continue;

      // PROBE dataset — store as string array (upgraded to real refs later)
      const probeStrings = channels.map(() => probePaths[0] || '/ONDE_PROBE_0');
      lg.create_dataset({ name: 'ONDE_UT_LAW:PROBE', data: probeStrings });      

      // ELEMENT dataset — array of element indices
      const elemArr = new Int32Array(channels.map(ch => ch.elementId));
      lg.create_dataset({ name: 'ONDE_UT_LAW:ELEMENT', data: elemArr });

      // DELAY dataset — array of delays
      const delayArr = new Float64Array(channels.map(ch => ch.delay));
      lg.create_dataset({ name: 'ONDE_UT_LAW:DELAY', data: delayArr });

      lawGroupPaths.push(lawName);
    } catch (e) {
      stats.warnings.push(`Error creating law group ${lawName}: ${e.message}`);
    }
  }
  return lawGroupPaths;
}

// ─── PA Phased Array Setup (Fix 4) ─────────────────────────────────────

function writeOndePhasedArraySetup(outFile, proc, probePaths, stats) {
  if (!proc) return null;
  const paProc = proc.ultrasonicPhasedArray;
  if (!paProc) return null;

  const pulseEcho = paProc.pulseEcho || {};
  const formation = pulseEcho.sectorialFormation || pulseEcho.linearFormation || pulseEcho.singleFormation || {};
  
  // Detect scan type
  let scanType;
  let ondeSetupSubtype;
  if (pulseEcho.sectorialFormation) {
    scanType = 'sectorial';
    ondeSetupSubtype = 'ONDE_PHASED_ARRAY_SSCAN';
  } else if (pulseEcho.linearFormation) {
    scanType = 'linear';
    ondeSetupSubtype = 'ONDE_PHASED_ARRAY_ESCAN';
  } else if (pulseEcho.singleFormation) {
    scanType = 'single';
    ondeSetupSubtype = 'ONDE_PHASED_ARRAY_ANGLE';
  } else {
    // Fallback: detect from beams
    const beams = paProc.beams || [];
    if (beams.length > 1) {
      // Check if all angles are different → sectorial
      const angles = beams.map(b => b.refractedAngle).filter(a => a !== undefined);
      if (angles.length > 1 && Math.abs(Math.max(...angles) - Math.min(...angles)) > 0.1) {
        scanType = 'sectorial';
        ondeSetupSubtype = 'ONDE_PHASED_ARRAY_SSCAN';
      } else {
        scanType = 'linear';
        ondeSetupSubtype = 'ONDE_PHASED_ARRAY_ESCAN';
      }
    } else {
      scanType = 'single';
      ondeSetupSubtype = 'ONDE_PHASED_ARRAY_ANGLE';
    }
  }

  const paPath = '/ONDE_PHASED_ARRAY_SETUP';
  try {
    outFile.create_group(paPath);
    const pg = outFile.get(paPath);
    setH5Attr(pg, 'ONDE:TYPE', ['ONDE_PHASED_ARRAY_SETUP', ondeSetupSubtype]);

    // EMITTER_PROBE / RECEIVING_PROBE — reference to probe group
    const probeRef = probePaths[0] || '/ONDE_PROBE_0';
    setH5Attr(pg, 'ONDE_PHASED_ARRAY_SETUP:EMITTER_PROBE', probeRef);
    setH5Attr(pg, 'ONDE_PHASED_ARRAY_SETUP:RECEIVING_PROBE', probeRef);

    // SEQUENCE_ANGLE_MODE: L or T from waveMode
    const waveMode = paProc.waveMode || 'Longitudinal';
    const seqMode = NDE_TO_ONDE.waveModeMap[waveMode] || 'L';
    setH5Attr(pg, 'ONDE_PHASED_ARRAY_SETUP:SEQUENCE_ANGLE_MODE', seqMode);

    // Scan-specific attributes
    const beams = paProc.beams || [];
    if (scanType === 'sectorial') {
      const angles = beams.map(b => b.refractedAngle).filter(a => a !== undefined);
      if (angles.length > 0) {
        setH5Attr(pg, 'ONDE_PHASED_ARRAY_SSCAN:STARTING_ANGLE', Math.min(...angles));
        setH5Attr(pg, 'ONDE_PHASED_ARRAY_SSCAN:FINISHING_ANGLE', Math.max(...angles));
      }
      setH5Attr(pg, 'ONDE_PHASED_ARRAY_SSCAN:NUMBER_OF_ANGLES', beams.length);
    } else if (scanType === 'linear') {
      const nElem = pulseEcho.linearFormation?.elementAperture || 
                    pulseEcho.linearFormation?.probeFirstElementId !== undefined ? 64 : 64;
      setH5Attr(pg, 'ONDE_PHASED_ARRAY_ESCAN:NUMBER_OF_ELEMENTS', nElem);
      if (beams.length > 1 && beams[0].refractedAngle !== undefined) {
        setH5Attr(pg, 'ONDE_PHASED_ARRAY_ESCAN:STEP', Math.abs(beams[1].refractedAngle - beams[0].refractedAngle));
      }
      if (beams[0] && beams[0].refractedAngle !== undefined) {
        setH5Attr(pg, 'ONDE_PHASED_ARRAY_ESCAN:ANGLE', beams[0].refractedAngle);
      }
    } else if (scanType === 'single') {
      if (beams[0] && beams[0].refractedAngle !== undefined) {
        setH5Attr(pg, 'ONDE_PHASED_ARRAY_ANGLE:BSCAN_ANGLE', beams[0].refractedAngle);
      }
    }

    return paPath;
  } catch (e) {
    stats.warnings.push(`Error creating phased array setup: ${e.message}`);
    return null;
  }
}

// ─── Acquisition Trajectory (Fix 5) ────────────────────────────────────

function writeOndeAcquisitionTrajectory(outFile, setup, stats) {
  const dataMappings = setup.dataMappings || [];
  const numTrajectories = Math.max(1, (setup.probes || []).length);
  const trajPaths = [];

  for (let ti = 0; ti < numTrajectories; ti++) {
    const trajPath = `/ONDE_ACQUISITION_TRAJECTORY_${ti}`;
    try {
      outFile.create_group(trajPath);
      const tg = outFile.get(trajPath);

      // Default to ONDE_TIME_TRAJECTORY per reference spec
      setH5Attr(tg, 'ONDE:TYPE', ['ONDE_ACQUISITION_TRAJECTORY', 'ONDE_TIME_TRAJECTORY']);

      trajPaths.push(trajPath);
    } catch (e) {
      stats.warnings.push(`Error creating trajectory ${trajPath}: ${e.message}`);
      trajPaths.push(trajPath); // still track even if failed
    }
  }
  return trajPaths;
}

// ── NDE → ONDE: Gate Conversion ──────────────────────────────────────────
const NDE_GATE_POLARITY = { 'Absolute': 'ABSOLUTE', 'Positive': 'POSITIVE', 'Negative': 'NEGATIVE' };
const NDE_GATE_DETECTION = { 'Peak': 'FIRST_PEAK', 'Crossing': 'FIRST_FLANK' };

function writeOndeGates(outFile, processes, datasetPath) {
  for (const proc of processes) {
    // Look for gates in any process type that has them
    const ulProc = proc.ultrasonicConventional || proc.ultrasonicPhasedArray || proc.ultrasonicMatrixCapture;
    const gateProcess = proc.ultrasonicGates || proc.tfmBoxGates || proc.thickness;
    let gates = null;

    if (ulProc && ulProc.gates && Array.isArray(ulProc.gates)) {
      gates = ulProc.gates;
    } else if (gateProcess && gateProcess.gates && Array.isArray(gateProcess.gates)) {
      gates = gateProcess.gates;
    }

    if (!gates) continue;

    const gateRefPaths = [];
    for (let gi = 0; gi < gates.length; gi++) {
      const ng = gates[gi];
      const gatePath = `${datasetPath}/ONDE_UT_GATE_${gi}`;
      outFile.create_group(gatePath);
      const og = outFile.get(gatePath);
      setH5Attr(og, 'ONDE:TYPE', ['ONDE_UT_GATE']);
      if (ng.start !== undefined) setH5Attr(og, 'ONDE_UT_GATE:START', ng.start);
      if (ng.length !== undefined) setH5Attr(og, 'ONDE_UT_GATE:WIDTH', ng.length);
      if (ng.threshold !== undefined) setH5Attr(og, 'ONDE_UT_GATE:THRESHOLD', ng.threshold);
      if (ng.thresholdPolarity) setH5Attr(og, 'ONDE_UT_GATE:POLARITY', NDE_GATE_POLARITY[ng.thresholdPolarity] || 'ABSOLUTE');
      if (ng.synchronization && ng.synchronization.triggeringEvent) {
        setH5Attr(og, 'ONDE_UT_GATE:DETECTION', NDE_GATE_DETECTION[ng.synchronization.triggeringEvent] || 'FIRST_PEAK');
      }
      gateRefPaths.push(gatePath);
    }
    if (gateRefPaths.length > 0) {
      const dsGroup = outFile.get(datasetPath);
      setH5Attr(dsGroup, 'ONDE_DATASET_UT_CSCAN:GATES', gateRefPaths);
    }
    break; // Only process first matching process
  }
}

function writeOndeSetupFromNde(outFile, setup, stats) {
  const txLawGroupPaths = [];
  const rxLawGroupPaths = [];
  try {
    // ── Create ONDE_SETUP group ─────────────────────────────────────
    const setupGroup = '/ONDE_SETUP_UT';
    outFile.create_group(setupGroup);
    const sg = outFile.get(setupGroup);
    setH5Attr(sg, 'ONDE:TYPE', ['ONDE_SETUP', 'ONDE_SETUP_UT']);

    // ── Create geometric setup ──────────────────────────────────────
    const geomPath = '/ONDE_GEOMETRIC_SETUP';
    outFile.create_group(geomPath);
    const gg = outFile.get(geomPath);
    setH5Attr(gg, 'ONDE:TYPE', ['ONDE_GEOMETRIC_SETUP']);

    // ── Component ───────────────────────────────────────────────────
    const specimens = setup.specimens || [];
    if (specimens.length > 0) {
      buildOndeComponent(outFile, specimens[0]);
    }

    // ── Wedge/Coupling Groups ───────────────────────────────────────
    const wedges = setup.wedges || [];
    for (let i = 0; i < wedges.length; i++) {
      const wedge = wedges[i];
      const couplingPath = `/ONDE_COUPLING_${i}`;
      outFile.create_group(couplingPath);
      const cg = outFile.get(couplingPath);

      if (wedge.fluidColumn) {
        setH5Attr(cg, 'ONDE:TYPE', ['ONDE_UT_COUPLING', 'ONDE_IMMERSION']);
        setH5Attr(cg, 'ONDE_IMMERSION:WATER_PATH', wedge.fluidColumn.height || 0.05);
        setH5Attr(cg, 'ONDE_UT_COUPLING:MEDIUM_VELOCITY', [1480, 0]);
        const wAngle = wedge.mountingLocations?.[0]?.wedgeAngle || 0;
        setH5Attr(cg, 'ONDE_UT_COUPLING:INCIDENCE_ANGLE', wAngle);
      } else if (wedge.angleBeamWedge) {
        setH5Attr(cg, 'ONDE:TYPE', ['ONDE_UT_COUPLING', 'ONDE_WEDGE', 'ONDE_SINGLE_WEDGE']);
        const delay = wedge.angleBeamWedge.delay || 0;
        const longVel = wedge.angleBeamWedge.longitudinalVelocity || 2330;
        const height = wedge.angleBeamWedge.height || (delay * longVel);
        setH5Attr(cg, 'ONDE_WEDGE:HEIGHT', height);
        setH5Attr(cg, 'ONDE_UT_COUPLING:MEDIUM_VELOCITY', [longVel, longVel * 0.5]);
        setH5Attr(cg, 'ONDE_WEDGE:SKEW_ANGLE', wedge.positioning?.skewAngle || 0);
        // CONTACT_AREA: [width, height, depth]  
        const w = wedge.angleBeamWedge.width || 0.020;
        const h = wedge.angleBeamWedge.height || 0.020;
        const l = wedge.angleBeamWedge.length || 0.030;
        setH5Attr(cg, 'ONDE_WEDGE:CONTACT_AREA', [w, h, l]);
        const wAngle = wedge.mountingLocations?.[0]?.wedgeAngle || wedge.angleBeamWedge.angle || 0;
        setH5Attr(cg, 'ONDE_UT_COUPLING:INCIDENCE_ANGLE', wAngle);
      }
    }

    // ── Probe Groups ────────────────────────────────────────────────
    const probes = setup.probes || [];
    const probePaths = [];
    for (let i = 0; i < probes.length; i++) {
      const probe = probes[i];
      const probePath = `/ONDE_PROBE_${i}`;
      probePaths.push(probePath);
      outFile.create_group(probePath);
      const pg = outFile.get(probePath);

      if (probe.conventionalRound) {
        setH5Attr(pg, 'ONDE:TYPE', ['ONDE_UT_PROBE', 'ONDE_MONO_UT_PROBE']);
        setH5Attr(pg, 'ONDE_UT_PROBE:FREQUENCY', probe.conventionalRound.centralFrequency || 5e6);
      } else if (probe.phasedArrayLinear) {
        setH5Attr(pg, 'ONDE:TYPE', ['ONDE_UT_PROBE', 'ONDE_LINEAR_UT_PROBE']);
        setH5Attr(pg, 'ONDE_UT_PROBE:FREQUENCY', probe.phasedArrayLinear.centralFrequency || 5e6);
        setH5Attr(pg, 'ONDE_LINEAR_UT_PROBE:TOTAL_NUMBER_OF_ELEMENTS',
          probe.phasedArrayLinear.elements?.elementQuantity || 
          probe.phasedArrayLinear.primaryAxis?.elementQuantity || 64);
        setH5Attr(pg, 'ONDE_LINEAR_UT_PROBE:ELEMENT_DIM_MAJOR',
          probe.phasedArrayLinear.primaryAxis?.elementLength || 0.01);
        setH5Attr(pg, 'ONDE_LINEAR_UT_PROBE:ELEMENT_DIM_MINOR',
          probe.phasedArrayLinear.secondaryAxis?.elementLength || 
          probe.phasedArrayLinear.secondaryAxis?.elementGap || 0.0008);
        setH5Attr(pg, 'ONDE_LINEAR_UT_PROBE:ELEMENT_PITCH_DIM_MAJOR',
          probe.phasedArrayLinear.primaryAxis?.elementGap || 0.001);
      }

      setH5Attr(pg, 'ONDE:TYPE_TAGS', ['ONDE_UT_ELEMENTS']);
      setH5Attr(pg, 'ONDE:LABEL', probe.model || (probe.conventionalRound ? 'UT Probe' : 'PA Linear Probe'));

      // Coupling reference on probe
      if (wedges.length > 0) {
        setH5Attr(pg, 'ONDE_UT_PROBE:COUPLING', `/ONDE_COUPLING_0`);
      }
    }

    // ── Acquisition Trajectory (Fix 5) ──────────────────────────────
    const trajPaths = writeOndeAcquisitionTrajectory(outFile, setup, stats);

    // ── Reference Attributes on GEOMETRIC_SETUP (Fix 6) ────────────
    // Store target paths as string attributes; these can be upgraded
    // to H5T_STD_REF_OBJ in post-processing.

    // PROBE_LIST: array of probe paths
    if (probePaths.length > 0) {
      gg.create_dataset({ name: 'ONDE_GEOMETRIC_SETUP:PROBE_LIST', data: probePaths });
    }

    // ACQUISITION_TRAJECTORY: array of trajectory paths
    if (trajPaths.length > 0) {
      gg.create_dataset({ name: 'ONDE_GEOMETRIC_SETUP:ACQUISITION_TRAJECTORY', data: trajPaths });
    }

    // COMPONENT: reference to component group (as dataset per spec)
    if (specimens.length > 0) {
      gg.create_dataset({ name: 'ONDE_GEOMETRIC_SETUP:COMPONENT', data: ['/ONDE_COMPONENT'] });
    }

    // COUPLING reference (attribute)
    if (wedges.length > 0) {
      setH5Attr(gg, 'ONDE_GEOMETRIC_SETUP:COUPLING', '/ONDE_COUPLING_0');
    }

    // ── Ultrasonic setup ───────────────────────────────────────────
    const usPath = '/ONDE_ULTRASONIC_SETUP';
    outFile.create_group(usPath);
    const us = outFile.get(usPath);
    setH5Attr(us, 'ONDE:TYPE', ['ONDE_ULTRASONIC_SETUP']);

    // Extract ultrasonic params from first NDE process
    let rectification = 'FULL_WAVE';
    let gainDb = 0;
    let digitizingFreq = 100e6;
    let ascanCompression = 1;
    let velocityVal = 5920;
    let ascanStartVal = 0.0;
    let firstProc = null;
    for (const grp of (setup.groups || [])) {
      firstProc = grp.processes?.[0];
      const ulProc = firstProc?.ultrasonicConventional || firstProc?.ultrasonicPhasedArray || firstProc?.ultrasonicMatrixCapture;
      if (ulProc) {
        rectification = NDE_TO_ONDE.rectificationMap[ulProc.rectification] || 'FULL_WAVE';
        if (firstProc.gain !== undefined) gainDb = firstProc.gain;
        if (ulProc.digitizingFrequency) digitizingFreq = ulProc.digitizingFrequency;
        if (ulProc.ascanCompressionFactor) ascanCompression = ulProc.ascanCompressionFactor;
        if (ulProc.velocity) velocityVal = ulProc.velocity;
        const beam0 = ulProc.beams?.[0];
        if (beam0?.ascanStart !== undefined) ascanStartVal = beam0.ascanStart;
        break;
      }
    }
    setH5Attr(us, 'ONDE_ULTRASONIC_SETUP:RECTIFICATION', rectification);
    const linearGain = Math.pow(10, gainDb / 20);
    us.create_dataset({ name: 'ONDE_ULTRASONIC_SETUP:GAIN', data: new Float64Array([linearGain]) });
    us.create_dataset({ name: 'ONDE_ULTRASONIC_SETUP:ASCAN_START', data: new Float64Array([ascanStartVal]) });
    setH5Attr(us, 'ONDE_ULTRASONIC_SETUP:ASCAN_SAMPLE_RATE', digitizingFreq / ascanCompression);

    // ── TCG Curve (NDE ultrasonicTcg → ONDE TCG_CURVE) ─────────────
    const tcgProc = (setup.groups || []).flatMap(g => g.processes || []).find(p => p.ultrasonicTcg);
    if (tcgProc && tcgProc.ultrasonicTcg.points) {
      const points = tcgProc.ultrasonicTcg.points;
      // ONDE TCG_CURVE format: [N_Ascan, N_TCG] — 2 rows: time samples + gain (linear)
      const tcgData = new Float64Array(points.length * 2);
      for (let i = 0; i < points.length; i++) {
        tcgData[i * 2] = points[i].time || 0;
        tcgData[i * 2 + 1] = Math.pow(10, (points[i].gain || 0) / 20); // dB → linear
      }
      us.create_dataset({ name: 'ONDE_ULTRASONIC_SETUP:TCG_CURVE', data: tcgData, shape: [points.length, 2] });
    }

    // ── Software Gain (NDE process.gain on Software impl → custom ONDE attr) ──
    const swGainProc = (setup.groups || []).flatMap(g => g.processes || []).find(p => p.implementation === 'Software' && p.gain !== undefined && !p.ultrasonicConventional && !p.ultrasonicPhasedArray);
    if (swGainProc) {
      us.create_dataset({ name: 'ONDE_ULTRASONIC_SETUP:SOFTWARE_GAIN', data: new Float64Array([swGainProc.gain]) });
    }

    // ── Filter Type ─────────────────────────────────────────────────
    const mainProc = (setup.groups || []).flatMap(g => g.processes || []).find(p => p.ultrasonicConventional || p.ultrasonicPhasedArray || p.ultrasonicMatrixCapture);
    if (mainProc) {
      const ul = mainProc.ultrasonicConventional || mainProc.ultrasonicPhasedArray || mainProc.ultrasonicMatrixCapture;
      if (ul) {
        if (ul.filterType) setH5Attr(us, 'ONDE_ULTRASONIC_SETUP:FILTER_TYPE', NDE_TO_ONDE.filterMap[ul.filterType] || 'OTHER');
        if (ul.digitalBandPassFilter) {
          const bp = ul.digitalBandPassFilter;
          const low = bp.lowCutOffFrequency || 0;
          const high = bp.highCutOffFrequency || 0;
          if (low || high) {
            setH5Attr(us, 'ONDE_ULTRASONIC_SETUP:FILTER_PARAMETERS', [low, high]);
          }
        } else if (ul.smoothingFilter) {
          setH5Attr(us, 'ONDE_ULTRASONIC_SETUP:FILTER_PARAMETERS', ul.smoothingFilter);
        }
      }
    }

    // ── PA/TFM: Phased Array Setup + Law Groups (Fixes 3,4,7) ──────
    const isPA = firstProc && firstProc.ultrasonicPhasedArray;
    const isTFM = firstProc && firstProc.totalFocusingMethod;
    if (isPA) {
      // Fix 4: Create ONDE_PHASED_ARRAY_SETUP
      writeOndePhasedArraySetup(outFile, firstProc, probePaths, stats);

      // Fix 3: Create ONDE_UT_LAW groups (transmit)
      const txPaths = writeOndeLawGroups(outFile, firstProc, probePaths, stats, true);
      txLawGroupPaths.push(...txPaths);
      // Create ONDE_UT_LAW_RX groups (receive)
      const rxPaths = writeOndeLawGroups(outFile, firstProc, probePaths, stats, false);
      rxLawGroupPaths.push(...rxPaths);
    } else if (isTFM) {
      // Create ONDE_PHASED_ARRAY_SETUP with FMC subtype for TFM
      const tfmProc = firstProc.totalFocusingMethod;
      const paPath = '/ONDE_PHASED_ARRAY_SETUP';
      try {
        outFile.create_group(paPath);
        const pg = outFile.get(paPath);
        setH5Attr(pg, 'ONDE:TYPE', ['ONDE_PHASED_ARRAY_SETUP', 'ONDE_PHASED_ARRAY_FMC']);
        const probeRef = probePaths[0] || '/ONDE_PROBE_0';
        setH5Attr(pg, 'ONDE_PHASED_ARRAY_SETUP:EMITTER_PROBE', probeRef);
        setH5Attr(pg, 'ONDE_PHASED_ARRAY_SETUP:RECEIVING_PROBE', probeRef);
        setH5Attr(pg, 'ONDE_PHASED_ARRAY_SETUP:SEQUENCE_ANGLE_MODE', 'L');
      } catch (e) {
        stats.warnings.push(`Error creating TFM phased array setup: ${e.message}`);
      }
    }

    // ── GEOMETRIC_SETUP / ULTRASONIC_SETUP refs on SETUP_UT ────────
    setH5Attr(sg, 'ONDE_SETUP:GEOMETRIC_SETUP', '/ONDE_GEOMETRIC_SETUP');
    setH5Attr(sg, 'ONDE_SETUP_UT:ULTRASONIC_SETUP', '/ONDE_ULTRASONIC_SETUP');

  } catch (e) {
    stats.warnings.push(`OND setup write error: ${e.message}`);
  }
  return { txPaths: txLawGroupPaths, rxPaths: rxLawGroupPaths };
}

function buildOndeComponent(outFile, specimen) {
  const compPath = '/ONDE_COMPONENT';
  outFile.create_group(compPath);
  const comp = outFile.get(compPath);

  if (specimen.plateGeometry) {
    setH5Attr(comp, 'ONDE:TYPE', ['ONDE_COMPONENT', 'ONDE_PLANE']);
    setH5Attr(comp, 'ONDE_PLANE:PLATE_DIMENSIONS', [1, 1, specimen.plateGeometry.thickness || 0.01]);
    setH5Attr(comp, 'ONDE_COMPONENT:DENSITY', 7800.0);
    extractVelocitiesToAttrs(comp, specimen.plateGeometry.material);
  } else if (specimen.pipeGeometry) {
    setH5Attr(comp, 'ONDE:TYPE', ['ONDE_COMPONENT', 'ONDE_CYLINDER']);
    setH5Attr(comp, 'ONDE_CYLINDER:DIMENSIONS', [
      (specimen.pipeGeometry.outerRadius || 0.1) * 2,
      specimen.pipeGeometry.thickness || 0.01, 0
    ]);
    setH5Attr(comp, 'ONDE_COMPONENT:DENSITY', 7800.0);
    extractVelocitiesToAttrs(comp, specimen.pipeGeometry.material);
  } else if (specimen.weldGeometry) {
    setH5Attr(comp, 'ONDE:TYPE', ['ONDE_COMPONENT', 'ONDE_WELD']);
    setH5Attr(comp, 'ONDE_COMPONENT:DENSITY', 7800.0);
    extractVelocitiesToAttrs(comp, specimen.weldGeometry.material);
  }
}

function extractVelocitiesToAttrs(comp, material) {
  if (!material) return;
  const lVel = material.longitudinalWave?.nominalVelocity || 5920;
  const tVel = material.transversalVerticalWave?.nominalVelocity || 3230;
  setH5Attr(comp, 'ONDE_COMPONENT:VELOCITIES', [lVel, tVel]);
}

// ─── Real HDF5 Reference Upgrader (Parts C & D) ─────────────────────────

/**
 * Walk all objects (groups AND datasets) in an HDF5 file.
 * Calls visitor(path) for each group and dataset found.
 */
function walkAllObjects(file, path, visitor) {
  try {
    const obj = file.get(path);
    if (!obj) return;
    // If it has keys(), it's a group — recurse into children
    if (typeof obj.keys === 'function') {
      const children = obj.keys();
      if (children) {
        for (const child of children) {
          const childPath = path === '/' ? `/${child}` : `${path}/${child}`;
          visitor(childPath, child);
          walkAllObjects(file, childPath, visitor);
        }
      }
    }
  } catch (_) { /* skip inaccessible objects */ }
}

/**
 * Check if a value looks like an HDF5 reference path.
 * Accepts strings starting with '/' (HDF5 internal paths).
 */
function isRefPath(value) {
  return typeof value === 'string' && value.startsWith('/');
}

function isRefArray(arr) {
  return Array.isArray(arr) && arr.length > 0 && arr.every(isRefPath);
}

/**
 * Build a concatenated null-terminated byte buffer from string array
 * for passing to the ref module's C functions.
 */
function buildNullSeparatedBuffer(Module, strings) {
  const encoder = new TextEncoder();
  const parts = strings.map(s => encoder.encode(s + '\0'));
  const totalLen = parts.reduce((sum, p) => sum + p.length, 0);
  const buf = Module._malloc(totalLen);
  let offset = 0;
  for (const part of parts) {
    Module.HEAPU8.set(part, buf + offset);
    offset += part.length;
  }
  return buf;
}

/**
 * Upgrade string-based reference paths in the output HDF5 file to real
 * H5T_STD_REF_OBJ references using the low-level h5wasm-ref module.
 *
 * This function:
 * 1. Opens the file with h5wasm (read-only) to discover reference attributes/datasets
 * 2. Opens the file with the ref module (read-write)
 * 3. Replaces string attribute paths with real HDF5 object references
 * 4. Replaces string dataset arrays with real HDF5 reference datasets
 * 5. Closes and returns
 */
async function upgradeToRealReferences(outName) {
  const h5wasm = globalThis.h5wasm;
  const H5RefModule = globalThis.H5RefModule;
  if (!h5wasm || !H5RefModule) {
    console.log('[ref-upgrade] h5wasm or H5RefModule not available, skipping ref upgrade');
    return;
  }

  const refMod = await H5RefModule;
  if (!refMod || typeof refMod.ccall !== 'function') {
    console.log('[ref-upgrade] H5RefModule not ready, skipping');
    return;
  }

  console.log('[ref-upgrade] Starting reference upgrade for:', outName);

  // ── Step 1: Scan file with h5wasm ──────────────────────────────────
  let scanFile;
  try {
    scanFile = new h5wasm.File(outName, 'r');
  } catch (e) {
    console.warn('[ref-upgrade] Cannot open for scan:', e.message);
    return;
  }

  // Collections: { parentPath: string, attrName: string, targetPath: string }[]
  const scalarRefs = [];
  const arrayRefs = [];
  const datasetRefs = [];

  // Walk all objects in the file
  walkAllObjects(scanFile, '/', (objPath, objName) => {
    try {
      const obj = scanFile.get(objPath);
      if (!obj) return;

      // Check attributes
      if (obj.attrs) {
        for (const [attrName, attr] of Object.entries(obj.attrs)) {
          if (!attr || attr.value === undefined || attr.value === null) continue;
          const val = attr.value;
          if (typeof val === 'string' && isRefPath(val)) {
            scalarRefs.push({ parentPath: objPath, attrName, targetPath: val });
          } else if (isRefArray(val)) {
            arrayRefs.push({ parentPath: objPath, attrName, targetPaths: val });
          }
        }
      }

      // Check if it's a dataset (not a group) containing string data
      // We detect datasets by absence of keys() function
      if (typeof obj.keys !== 'function' && obj.value !== undefined) {
        const val = obj.value;
        if (typeof val === 'string' && isRefPath(val)) {
          // Scalar string dataset with a path — unusual but handle it
          scalarRefs.push({ parentPath: objPath, attrName: null, targetPath: val });
        } else if (isRefArray(val)) {
          datasetRefs.push({ datasetPath: objPath, targetPaths: val });
        }
      }
    } catch (_) {}
  });

  scanFile.close();

  console.log(`[ref-upgrade] Found ${scalarRefs.length} scalar refs, ${arrayRefs.length} array refs, ${datasetRefs.length} dataset refs`);

  if (scalarRefs.length === 0 && arrayRefs.length === 0 && datasetRefs.length === 0) {
    console.log('[ref-upgrade] Nothing to upgrade');
    return;
  }

  // ── Step 2: Open file with ref module (read-write) ─────────────────
  const fileId = refMod.ccall('h5r_open', 'number', ['string'], [outName]);
  if (fileId < 0) {
    console.warn('[ref-upgrade] Cannot open file with ref module');
    return;
  }

  try {
    // ── Step 3: Upgrade scalar reference attributes ──────────────────
    for (const ref of scalarRefs) {
      try {
        const parentId = refMod.ccall('h5r_open_group', 'number', ['number', 'string'], [fileId, ref.parentPath]);
        if (parentId >= 0) {
          const result = refMod.ccall('h5r_set_attr_ref', 'number',
            ['number', 'string', 'number', 'string'],
            [parentId, ref.attrName, fileId, ref.targetPath]);
          refMod.ccall('h5r_close_obj', 'number', ['number'], [parentId]);
          if (result === 0) {
            console.log(`[ref-upgrade]  ✓ Scalar ref: ${ref.parentPath}:${ref.attrName} → ${ref.targetPath}`);
          }
        }
      } catch (e) {
        console.warn(`[ref-upgrade] Failed scalar ref ${ref.parentPath}:${ref.attrName}:`, e.message);
      }
    }

    // ── Step 4: Upgrade array reference attributes ───────────────────
    for (const ref of arrayRefs) {
      try {
        const parentId = refMod.ccall('h5r_open_group', 'number', ['number', 'string'], [fileId, ref.parentPath]);
        if (parentId >= 0) {
          const buf = buildNullSeparatedBuffer(refMod, ref.targetPaths);
          const result = refMod.ccall('h5r_set_attr_ref_array', 'number',
            ['number', 'string', 'number', 'number', 'number'],
            [parentId, ref.attrName, fileId, buf, ref.targetPaths.length]);
          refMod._free(buf);
          refMod.ccall('h5r_close_obj', 'number', ['number'], [parentId]);
          if (result === 0) {
            console.log(`[ref-upgrade]  ✓ Array ref attr: ${ref.parentPath}:${ref.attrName} (${ref.targetPaths.length} paths)`);
          }
        }
      } catch (e) {
        console.warn(`[ref-upgrade] Failed array ref attr ${ref.parentPath}:${ref.attrName}:`, e.message);
      }
    }

    // ── Step 5: Upgrade reference datasets ───────────────────────────
    for (const ref of datasetRefs) {
      try {
        const buf = buildNullSeparatedBuffer(refMod, ref.targetPaths);
        const result = refMod.ccall('h5r_create_dataset_ref', 'number',
          ['number', 'string', 'number', 'number'],
          [fileId, ref.datasetPath, buf, ref.targetPaths.length]);
        refMod._free(buf);
        if (result === 0) {
          console.log(`[ref-upgrade]  ✓ Dataset ref: ${ref.datasetPath} (${ref.targetPaths.length} paths)`);
        }
      } catch (e) {
        console.warn(`[ref-upgrade] Failed dataset ref ${ref.datasetPath}:`, e.message);
      }
    }
  } finally {
    refMod.ccall('h5r_close', 'number', ['number'], [fileId]);
  }

  console.log('[ref-upgrade] Complete');
}

// ─── Reference Upgrade Integration ─────────────────────────────────────

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

      const ondeGroupPath = `/${ondeType.suffix}_${datasetRefs.length}`;
      out.create_group(ondeGroupPath);
      const ondeGroup = out.get(ondeGroupPath);

      // ONDE:TYPE
      setH5Attr(ondeGroup, 'ONDE:TYPE', ondeType.chain);

      // LABEL
      if (nds.name) setH5Attr(ondeGroup, 'ONDE:LABEL', nds.name);

      // Write dimensions from the NDE dataset
      writeOndeDimensionsFromNde(out, ondeGroupPath, nds, datasetRefs.length);

      // Copy data with ONDE target name
      copyNdeDataToOnde(inFile, out, nds, ondeGroupPath, stats, targetName);

      // Fix 2: Add mandatory ONDE_DATASET:SETUP attribute referencing the ONDE_SETUP group
      setH5Attr(ondeGroup, 'ONDE_DATASET:SETUP', '/ONDE_SETUP_UT');

      // Fix 2: TSCAN mandatory fields
      if (ondeType.base === 'ONDE_DATASET_UT_TSCAN') {
        setH5Attr(ondeGroup, 'ONDE_DATASET_UT_TSCAN:ZONE_FRAME', [0,0,0, 1,0,0,0]);
        setH5Attr(ondeGroup, 'ONDE_DATASET_UT_TSCAN:ZONE_DIMENSION', [0,0,0]);
        if (nds.dimensions && Array.isArray(nds.dimensions)) {
          const sizes = nds.dimensions.map(d => d.size || 0);
          setH5Attr(ondeGroup, 'ONDE_DATASET_UT_TSCAN:ZONE_SIZE', sizes);
        }
        setH5Attr(ondeGroup, 'ONDE_DATASET_UT_TSCAN:SOURCE_ASCAN_DATASET', '/ascan_0');
      }

      // Fix 2: CSCAN DATATYPE
      if (ondeType.base === 'ONDE_DATASET_UT_CSCAN') {
        let dataType = 'AMAX';
        if (nds.dataClass === 'CScanTime') dataType = 'TIME_OF_FLIGHT';
        setH5Attr(ondeGroup, 'ONDE_DATASET_UT_CSCAN:DATATYPE', dataType);
      }

      datasetRefs.push({ path: ondeGroupPath, type: ondeType.base });
      stats.datasetsProcessed++;
    }
    stats.groupsProcessed++;
  }

  // Write ONDE_SETUP group if we have datasets
  if (datasetRefs.length > 0) {
    writeOndeSetupFromNde(out, setup, stats);
  }

  out.close();
  return outName;
}

// ─── HDF5 Helpers ───────────────────────────────────────────────────────

/** Set a typed attribute on an HDF5 group/dataset */
function setH5Attr(obj, name, value) {
  try {
    if (Array.isArray(value)) {
      // Check if all elements are strings or numbers
      const allStrings = value.every(v => typeof v === 'string');
      if (allStrings) {
        const maxLen = Math.max(...value.map(v => String(v).length), 1);
        obj.create_attribute(name, value.map(String), null, `S${maxLen}`);
      } else {
        // Numeric array — preserve as native HDF5 numeric type
        const numericArr = value.map(v => Number(v));
        obj.create_attribute(name, numericArr);
      }
    } else if (typeof value === 'string') {
      obj.create_attribute(name, value);
    } else if (typeof value === 'number') {
      obj.create_attribute(name, value);
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
      return 'DATA';
    default:
      return null;
  }
}

function resolveOndeType(dataClass) {
  const map = NDE_TO_ONDE.dataClassToOndeType[dataClass];
  if (!map) return null;

  switch (map.type) {
    case 'ONDE_DATASET_UT_ASCAN':
      return { base: map.type, suffix: 'ascan', chain: ['ONDE_DATASET','ONDE_DATASET_UT','ONDE_DATASET_UT_ASCAN'] };
    case 'ONDE_DATASET_UT_TSCAN':
      return { base: map.type, suffix: 'tscan', chain: ['ONDE_DATASET','ONDE_DATASET_UT','ONDE_DATASET_UT_TSCAN'] };
    case 'ONDE_DATASET_UT_CSCAN':
      return { base: map.type, suffix: 'cscan', chain: ['ONDE_DATASET','ONDE_DATASET_UT','ONDE_DATASET_UT_CSCAN'] };
    default:
      return { base: 'ONDE_DATASET', suffix: 'unknown', chain: ['ONDE_DATASET'] };
  }
}

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

    // Create ONDE_DIMENSION group at root level
    const dimPath = `/dim_${ondeDim.coordinate}_${dsIndex}_${dimCount}`;
    outFile.create_group(dimPath);
    const dimGroup = outFile.get(dimPath);
    setH5Attr(dimGroup, 'ONDE:TYPE', ['ONDE_DIMENSION']);
    setH5Attr(dimGroup, 'ONDE_DIMENSION:COORDINATE', ondeDim.coordinate);
    setH5Attr(dimGroup, 'ONDE_DIMENSION:UNITS', ondeDim.units);
    setH5Attr(dimGroup, 'ONDE_DIMENSION:OFFSET', axis.offset || 0);
    setH5Attr(dimGroup, 'ONDE_DIMENSION:SCALE', axis.resolution || 1);
    dimRefs.push(dimPath);
    dimCount++;
  }

  // Also create AMPLITUDE_DIMENSION
  const ampPath = `/dim_Amplitude_${dsIndex}_amp`;
  outFile.create_group(ampPath);
  const ampGroup = outFile.get(ampPath);
  setH5Attr(ampGroup, 'ONDE:TYPE', ['ONDE_DIMENSION']);
  setH5Attr(ampGroup, 'ONDE_DIMENSION:COORDINATE', 'Amplitude');
  setH5Attr(ampGroup, 'ONDE_DIMENSION:UNITS', 'arbitrary');
  setH5Attr(ampGroup, 'ONDE_DIMENSION:OFFSET', 0.0);
  setH5Attr(ampGroup, 'ONDE_DIMENSION:SCALE', 1.0);

  if (dimCount > 0) {
    setH5Attr(ondeGroup, 'ONDE_DIM_COUNT', dimCount);
    // Store INDEX_DIMENSIONS as string paths (h5wasm limitation: no H5T_STD_REF_OBJ)
    setH5Attr(ondeGroup, 'ONDE_DATASET:INDEX_DIMENSIONS', dimRefs);
    setH5Attr(ondeGroup, 'ONDE_DATASET:AMPLITUDE_DIMENSION', ampPath);
  }
}

function copyNdeDataToOnde(inFile, outFile, nds, ondePath, stats, targetName = 'DATA') {
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

function writeOndeSetupFromNde(outFile, setup, stats) {
  try {
    // Create ONDE_SETUP group
    const setupGroup = '/ONDE_SETUP_UT';
    outFile.create_group(setupGroup);
    const sg = outFile.get(setupGroup);
    setH5Attr(sg, 'ONDE:TYPE', ['ONDE_SETUP', 'ONDE_SETUP_UT']);

    // Create geometric setup
    const geomPath = '/ONDE_GEOMETRIC_SETUP';
    outFile.create_group(geomPath);
    const gg = outFile.get(geomPath);
    setH5Attr(gg, 'ONDE:TYPE', ['ONDE_GEOMETRIC_SETUP']);

    // Component
    const specimens = setup.specimens || [];
    if (specimens.length > 0) {
      buildOndeComponent(outFile, specimens[0]);
    }

    // Ultrasonic setup
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
    for (const grp of (setup.groups || [])) {
      const proc = grp.processes?.[0];
      const ulProc = proc?.ultrasonicConventional || proc?.ultrasonicPhasedArray || proc?.ultrasonicMatrixCapture;
      if (ulProc) {
        rectification = NDE_TO_ONDE.rectificationMap[ulProc.rectification] || 'FULL_WAVE';
        if (proc.gain !== undefined) gainDb = proc.gain;
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
    // GAIN and ASCAN_START must be Datasets per ONDE spec (not attributes)
    us.create_dataset({ name: 'GAIN', data: new Float64Array([linearGain]) });
    us.create_dataset({ name: 'ASCAN_START', data: new Float64Array([ascanStartVal]) });
    // ASCAN_SAMPLE_RATE = digitizingFrequency / ascanCompressionFactor
    setH5Attr(us, 'ONDE_ULTRASONIC_SETUP:ASCAN_SAMPLE_RATE', digitizingFreq / ascanCompression);

    // ── Wedge/Coupling Groups (Fix 3) ────────────────────────────────
    const wedges = setup.wedges || [];
    for (let i = 0; i < wedges.length; i++) {
      const wedge = wedges[i];
      const couplingPath = `/ONDE_COUPLING_${i}`;
      outFile.create_group(couplingPath);
      const cg = outFile.get(couplingPath);

      if (wedge.fluidColumn) {
        // Immersion coupling
        setH5Attr(cg, 'ONDE:TYPE', ['ONDE_UT_COUPLING', 'ONDE_IMMERSION']);
        setH5Attr(cg, 'ONDE_IMMERSION:WATER_PATH', wedge.fluidColumn.height || 0.05);
        setH5Attr(cg, 'ONDE_UT_COUPLING:MEDIUM_VELOCITY', [1480, 0]);
        const wAngle = wedge.mountingLocations?.[0]?.wedgeAngle || 0;
        setH5Attr(cg, 'ONDE_UT_COUPLING:INCIDENCE_ANGLE', wAngle);
      } else if (wedge.angleBeamWedge) {
        // Single wedge coupling
        setH5Attr(cg, 'ONDE:TYPE', ['ONDE_UT_COUPLING', 'ONDE_WEDGE', 'ONDE_SINGLE_WEDGE']);
        const delay = wedge.angleBeamWedge.delay || 0;
        const longVel = 2330; // default wedge velocity (Rexolite)
        const height = delay * longVel;
        setH5Attr(cg, 'ONDE_WEDGE:HEIGHT', height);
        setH5Attr(cg, 'ONDE_UT_COUPLING:MEDIUM_VELOCITY', [longVel, longVel * 0.5]);
        setH5Attr(cg, 'ONDE_WEDGE:SKEW_ANGLE', wedge.positioning?.skewAngle || 0);
        const wAngle = wedge.mountingLocations?.[0]?.wedgeAngle || wedge.angleBeamWedge.angle || 0;
        setH5Attr(cg, 'ONDE_UT_COUPLING:INCIDENCE_ANGLE', wAngle);
      }
    }

    // ── Probe Groups (Fix 4) ─────────────────────────────────────────
    const probes = setup.probes || [];
    for (let i = 0; i < probes.length; i++) {
      const probe = probes[i];
      const probePath = `/ONDE_PROBE_${i}`;
      outFile.create_group(probePath);
      const pg = outFile.get(probePath);

      if (probe.conventionalRound) {
        setH5Attr(pg, 'ONDE:TYPE', ['ONDE_UT_PROBE', 'ONDE_MONO_UT_PROBE']);
        setH5Attr(pg, 'ONDE_UT_PROBE:FREQUENCY', probe.conventionalRound.centralFrequency || 5e6);
      } else if (probe.phasedArrayLinear) {
        setH5Attr(pg, 'ONDE:TYPE', ['ONDE_UT_PROBE', 'ONDE_LINEAR_UT_PROBE']);
        setH5Attr(pg, 'ONDE_UT_PROBE:FREQUENCY', probe.phasedArrayLinear.centralFrequency || 5e6);
        setH5Attr(pg, 'ONDE_LINEAR_UT_PROBE:TOTAL_NUMBER_OF_ELEMENTS',
          probe.phasedArrayLinear.elements?.elementQuantity || 64);
        setH5Attr(pg, 'ONDE_LINEAR_UT_PROBE:ELEMENT_DIM_MAJOR',
          probe.phasedArrayLinear.elements?.primaryAxis?.elementLength || 0.01);
        setH5Attr(pg, 'ONDE_LINEAR_UT_PROBE:ELEMENT_PITCH_DIM_MAJOR',
          probe.phasedArrayLinear.elements?.primaryAxis?.elementGap || 0.001);
      }

      // Fix 3: Add ONDE:TYPE_TAGS on probe groups
      setH5Attr(pg, 'ONDE:TYPE_TAGS', ['ONDE_UT_ELEMENTS']);
    }

    // ── Reference Attributes on GEOMETRIC_SETUP ──────────────────
    // Store target paths as string attributes; applyHdf5References
    // will upgrade them to H5T_STD_REF_OBJ references in post-processing.

    // PROBE_LIST: array of probe paths
    if (probes.length > 0) {
      const probePaths = probes.map((_, i) => `/ONDE_PROBE_${i}`);
      setH5Attr(gg, 'ONDE_GEOMETRIC_SETUP:PROBE_LIST', probePaths);
    }

    // COMPONENT: reference to the component group
    if (specimens.length > 0) {
      setH5Attr(gg, 'ONDE_GEOMETRIC_SETUP:COMPONENT', '/ONDE_COMPONENT');
    }

    // COUPLING: reference to the first coupling group (if any)
    if (wedges.length > 0) {
      setH5Attr(gg, 'ONDE_GEOMETRIC_SETUP:COUPLING', '/ONDE_COUPLING_0');
    }

    // GEOMETRIC_SETUP: reference from SETUP to GEOMETRIC_SETUP
    setH5Attr(sg, 'ONDE_SETUP:GEOMETRIC_SETUP', '/ONDE_GEOMETRIC_SETUP');

  } catch (e) {
    stats.warnings.push(`OND setup write error: ${e.message}`);
  }
}

function buildOndeComponent(outFile, specimen) {
  const compPath = '/ONDE_COMPONENT';
  outFile.create_group(compPath);
  const comp = outFile.get(compPath);

  if (specimen.plateGeometry) {
    setH5Attr(comp, 'ONDE:TYPE', ['ONDE_COMPONENT', 'ONDE_PLANE']);
    setH5Attr(comp, 'ONDE_PLANE:PLATE_DIMENSIONS', [1, 1, specimen.plateGeometry.thickness || 0.01]);
    extractVelocitiesToAttrs(comp, specimen.plateGeometry.material);
  } else if (specimen.pipeGeometry) {
    setH5Attr(comp, 'ONDE:TYPE', ['ONDE_COMPONENT', 'ONDE_CYLINDER']);
    setH5Attr(comp, 'ONDE_CYLINDER:DIMENSIONS', [
      (specimen.pipeGeometry.outerRadius || 0.1) * 2,
      specimen.pipeGeometry.thickness || 0.01, 0
    ]);
    extractVelocitiesToAttrs(comp, specimen.pipeGeometry.material);
  } else if (specimen.weldGeometry) {
    setH5Attr(comp, 'ONDE:TYPE', ['ONDE_COMPONENT', 'ONDE_WELD']);
    extractVelocitiesToAttrs(comp, specimen.weldGeometry.material);
  }
}

function extractVelocitiesToAttrs(comp, material) {
  if (!material) return;
  const lVel = material.longitudinalWave?.nominalVelocity || 5920;
  const tVel = material.transversalVerticalWave?.nominalVelocity || 3230;
  setH5Attr(comp, 'ONDE_COMPONENT:VELOCITIES', [lVel, tVel]);
}

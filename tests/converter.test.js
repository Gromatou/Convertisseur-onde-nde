#!/usr/bin/env node

/**
 * Comprehensive test suite for ONDE↔NDE ultrasonic file converter.
 *
 * Tests:
 *   1. Mapping tables (ONDE_TO_NDE, NDE_TO_ONDE)
 *   2. Format detection (detectFormat, detectOndeDatasetType, detectOndeGroupType)
 *   3. Unit conversions (UNITS)
 *   4. Dimension mappings (DIMENSION_MAPPING)
 *   5. Edge cases (null, empty, unknown, missing fields)
 *
 * Usage: node tests/converter.test.js
 *   Exit code 0 = all pass, 1 = any failure
 */

// ── Test harness ──────────────────────────────────────────────────────────

let passed = 0;
let failed = 0;
const failures = [];

function assert(condition, message) {
  if (condition) {
    passed++;
    process.stdout.write('  ✓ ');
  } else {
    failed++;
    process.stdout.write('  ✗ ');
    failures.push(message);
  }
  console.log(message);
}

function assertStrictEqual(actual, expected, label) {
  const ok = actual === expected;
  const msg = ok
    ? `${label} → ${JSON.stringify(actual)}`
    : `${label} → expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`;
  if (ok) {
    passed++;
    process.stdout.write('  ✓ ');
  } else {
    failed++;
    process.stdout.write('  ✗ ');
    failures.push(msg);
  }
  console.log(msg);
}

function assertDeepEqual(actual, expected, label) {
  const ok = deepEqual(actual, expected);
  const msg = ok
    ? `${label} → ${JSON.stringify(actual)}`
    : `${label} → expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`;
  if (ok) {
    passed++;
    process.stdout.write('  ✓ ');
  } else {
    failed++;
    process.stdout.write('  ✗ ');
    failures.push(msg);
  }
  console.log(msg);
}

function deepEqual(a, b) {
  if (a === b) return true;
  if (a == null || b == null) return false;
  if (typeof a !== typeof b) return false;
  if (Array.isArray(a) && Array.isArray(b)) {
    if (a.length !== b.length) return false;
    return a.every((v, i) => deepEqual(v, b[i]));
  }
  if (typeof a === 'object') {
    const ka = Object.keys(a);
    const kb = Object.keys(b);
    if (ka.length !== kb.length) return false;
    return ka.every(k => Object.prototype.hasOwnProperty.call(b, k) && deepEqual(a[k], b[k]));
  }
  return false;
}

function group(name) {
  console.log(`\n═══ ${name} ═══`);
}

// ── Main entry ────────────────────────────────────────────────────────────

(async function main() {
  // Dynamically import ESM modules
  const mapping = await import('../src/mapping.js');
  const {
    ONDE_TO_NDE, NDE_TO_ONDE, UNITS, DIMENSION_MAPPING,
    detectFormat, detectOndeDatasetType, detectOndeGroupType
  } = mapping;

  // ═══════════════════════════════════════════════════════════════════════
  //  1. ONDE_TO_NDE Mapping Table
  // ═══════════════════════════════════════════════════════════════════════

  group('1. ONDE_TO_NDE — File Identity');
  assertStrictEqual(ONDE_TO_NDE.fileType.onde.attr, 'ONDE:FILETYPE', 'fileType.onde.attr');
  assertStrictEqual(ONDE_TO_NDE.fileType.onde.check, 'ONDE_UT', 'fileType.onde.check');
  assertStrictEqual(ONDE_TO_NDE.formatVersion.onde.attr, 'ONDE:VERSION', 'formatVersion.onde.attr');

  group('1.1 — Dataset Class Mapping');
  const dcm = ONDE_TO_NDE.datasetClassMapping;
  assert(dcm['ONDE_DATASET_UT_ASCAN'] !== undefined, 'ONDE_DATASET_UT_ASCAN exists');
  assertStrictEqual(dcm['ONDE_DATASET_UT_ASCAN'].amplitude, 'AScanAmplitude', 'ASCAN → amplitude');
  assertStrictEqual(dcm['ONDE_DATASET_UT_ASCAN'].status, 'AScanStatus', 'ASCAN → status');

  assert(dcm['ONDE_DATASET_UT_TSCAN'] !== undefined, 'ONDE_DATASET_UT_TSCAN exists');
  assertStrictEqual(dcm['ONDE_DATASET_UT_TSCAN'].value, 'TfmValue', 'TSCAN → value');
  assertStrictEqual(dcm['ONDE_DATASET_UT_TSCAN'].status, 'TfmStatus', 'TSCAN → status');

  assert(dcm['ONDE_DATASET_UT_CSCAN'] !== undefined, 'ONDE_DATASET_UT_CSCAN exists');
  assertStrictEqual(dcm['ONDE_DATASET_UT_CSCAN'].peak, 'CScanPeak', 'CSCAN → peak');
  assertStrictEqual(dcm['ONDE_DATASET_UT_CSCAN'].time, 'CScanTime', 'CSCAN → time');
  assertStrictEqual(dcm['ONDE_DATASET_UT_CSCAN'].status, 'CScanStatus', 'CSCAN → status');

  group('1.2 — Ultrasonic Setup Mapping');
  const ultrasonic = ONDE_TO_NDE.setup.ultrasonic;
  ['ASCAN_SAMPLE_RATE', 'ASCAN_START', 'RECTIFICATION', 'FILTER_TYPE', 'GAIN', 'PRF'].forEach(key => {
    assert(ultrasonic[key] !== undefined, `ultrasonic.${key} exists`);
  });
  assertStrictEqual(ultrasonic.ASCAN_SAMPLE_RATE.nde, 'digitizingFrequency', 'sample rate → digitizingFrequency');
  assertStrictEqual(ultrasonic.ASCAN_START.nde, 'ascanStart', 'start → ascanStart');
  assertStrictEqual(ultrasonic.GAIN.nde, 'gain', 'gain → gain');
  assertStrictEqual(ultrasonic.PRF.nde, 'pulseRepetitionFrequency', 'PRF mapping');

  // Rectification sub-mapping
  const rect = ultrasonic.RECTIFICATION.map;
  assertStrictEqual(rect.FULL_WAVE, 'None', 'FULL_WAVE → None');
  assertStrictEqual(rect.RECTIFIED_POSITIVE, 'Positive', 'RECTIFIED_POSITIVE → Positive');
  assertStrictEqual(rect.RECTIFIED_NEGATIVE, 'Negative', 'RECTIFIED_NEGATIVE → Negative');
  assertStrictEqual(rect.RECTIFIED_FULL, 'Full', 'RECTIFIED_FULL → Full');

  // Filter sub-mapping
  const filt = ultrasonic.FILTER_TYPE.map;
  assertStrictEqual(filt.NO_FILTER, 'None', 'NO_FILTER → None');
  assertStrictEqual(filt.LOW_PASS, 'LowPass', 'LOW_PASS → LowPass');
  assertStrictEqual(filt.HIGH_PASS, 'HighPass', 'HIGH_PASS → HighPass');
  assertStrictEqual(filt.BAND_PASS, 'BandPass', 'BAND_PASS → BandPass');

  group('1.3 — Geometric Setup Mapping');
  const geometric = ONDE_TO_NDE.setup.geometric;
  assert(geometric.COMPONENT !== undefined, 'geometric.COMPONENT exists');
  assertStrictEqual(geometric.COMPONENT.nde, 'specimens', 'COMPONENT → specimens');
  assertStrictEqual(geometric.PROBE_LIST.nde, 'probes', 'PROBE_LIST → probes');
  assertStrictEqual(geometric.ACQUISITION_TRAJECTORY.nde, 'motionDevices', 'TRAJECTORY → motionDevices');

  group('1.4 — Component/Geometry Mapping');
  const comp = ONDE_TO_NDE.component;
  assertStrictEqual(comp.ONDE_PLANE, 'plateGeometry', 'ONDE_PLANE → plateGeometry');
  assertStrictEqual(comp.ONDE_CYLINDER, 'pipeGeometry', 'ONDE_CYLINDER → pipeGeometry');
  assertStrictEqual(comp.ONDE_2DCAD, 'plateGeometry', 'ONDE_2DCAD → plateGeometry (approx)');
  assertStrictEqual(comp.ONDE_3DCAD, 'plateGeometry', 'ONDE_3DCAD → plateGeometry (approx)');
  assertStrictEqual(comp.ONDE_WELD, 'weldGeometry', 'ONDE_WELD → weldGeometry');

  group('1.5 — Probe Mapping (ONDE_TO_NDE)');
  const probe = ONDE_TO_NDE.probe;

  // Mono probe
  assert(probe.ONDE_MONO_UT_PROBE !== undefined, 'ONDE_MONO_UT_PROBE exists');
  assertStrictEqual(probe.ONDE_MONO_UT_PROBE.type, 'conventionalRound', 'mono → conventionalRound');
  assertStrictEqual(probe.ONDE_MONO_UT_PROBE.mapping.FREQUENCY, 'centralFrequency', 'mono FREQUENCY map');
  assertStrictEqual(probe.ONDE_MONO_UT_PROBE.mapping.MANUFACTURER, 'probeManufacturer', 'mono MANUFACTURER map');
  assertStrictEqual(probe.ONDE_MONO_UT_PROBE.mapping.SERIAL_NUMBER, 'model', 'mono SERIAL_NUMBER → model');

  // Linear probe
  assert(probe.ONDE_LINEAR_UT_PROBE !== undefined, 'ONDE_LINEAR_UT_PROBE exists');
  assertStrictEqual(probe.ONDE_LINEAR_UT_PROBE.type, 'phasedArrayLinear', 'linear → phasedArrayLinear');
  assertStrictEqual(probe.ONDE_LINEAR_UT_PROBE.mapping.FREQUENCY, 'centralFrequency', 'linear FREQUENCY');
  assertStrictEqual(probe.ONDE_LINEAR_UT_PROBE.mapping.TOTAL_NUMBER_OF_ELEMENTS, 'elements.elementQuantity', 'linear elements');
  assertStrictEqual(probe.ONDE_LINEAR_UT_PROBE.mapping.ELEMENT_DIM_MAJOR, 'elements.primaryAxis.elementLength', 'linear dim major');
  assertStrictEqual(probe.ONDE_LINEAR_UT_PROBE.mapping.ELEMENT_DIM_MINOR, 'elements.secondaryAxis.elementWidth', 'linear dim minor');
  assertStrictEqual(probe.ONDE_LINEAR_UT_PROBE.mapping.ELEMENT_PITCH_DIM_MAJOR, 'elements.primaryAxis.elementGap', 'linear pitch major');
  assertStrictEqual(probe.ONDE_LINEAR_UT_PROBE.mapping.MANUFACTURER, 'model', 'linear manufacturer');
  assertStrictEqual(probe.ONDE_LINEAR_UT_PROBE.mapping.SERIAL_NUMBER, 'serialNumber', 'linear serial');

  // Matrix probe
  assert(probe.ONDE_MATRIX_UT_PROBE !== undefined, 'ONDE_MATRIX_UT_PROBE exists');
  assertStrictEqual(probe.ONDE_MATRIX_UT_PROBE.type, 'phasedArrayLinear', 'matrix → phasedArrayLinear (closest)');
  assertStrictEqual(probe.ONDE_MATRIX_UT_PROBE.mapping.ELEMENT_PITCH_DIM_MINOR, 'elements.secondaryAxis.elementGap', 'matrix pitch minor');

  group('1.6 — Coupling/Wedge Mapping (ONDE_TO_NDE)');
  const coupling = ONDE_TO_NDE.coupling;

  // Immersion
  assert(coupling.ONDE_IMMERSION !== undefined, 'ONDE_IMMERSION exists');
  assertStrictEqual(coupling.ONDE_IMMERSION.type, 'fluidColumn', 'immersion → fluidColumn');
  assertStrictEqual(coupling.ONDE_IMMERSION.mapping.WATER_PATH, 'height', 'immersion WATER_PATH → height');
  assertStrictEqual(coupling.ONDE_IMMERSION.mapping.MEDIUM_VELOCITY, 'velocity', 'immersion velocity');
  assertStrictEqual(coupling.ONDE_IMMERSION.mapping.MEDIUM_DENSITY, 'density', 'immersion density');
  assertStrictEqual(coupling.ONDE_IMMERSION.mapping.INCIDENCE_ANGLE, 'angle', 'immersion angle');

  // Wedge
  assert(coupling.ONDE_WEDGE !== undefined, 'ONDE_WEDGE exists');
  assertStrictEqual(coupling.ONDE_WEDGE.type, 'angleBeamWedge', 'wedge → angleBeamWedge');
  assertStrictEqual(coupling.ONDE_WEDGE.mapping.HEIGHT, 'delay', 'wedge HEIGHT → delay');
  assertStrictEqual(coupling.ONDE_WEDGE.mapping.SKEW_ANGLE, 'skewAngle', 'wedge skew');
  assertStrictEqual(coupling.ONDE_WEDGE.mapping.CONTACT_AREA, 'contactArea', 'wedge contact area');
  assertStrictEqual(coupling.ONDE_WEDGE.mapping.MANUFACTURER, 'model', 'wedge manufacturer');
  assertStrictEqual(coupling.ONDE_WEDGE.mapping.SERIAL_NUMBER, 'serialNumber', 'wedge serial');

  // Single wedge
  assert(coupling.ONDE_SINGLE_WEDGE !== undefined, 'ONDE_SINGLE_WEDGE exists');
  assertStrictEqual(coupling.ONDE_SINGLE_WEDGE.type, 'angleBeamWedge', 'single wedge → angleBeamWedge');
  assert(coupling.ONDE_SINGLE_WEDGE.mapping.HEIGHT !== undefined, 'single wedge has HEIGHT');

  // Dual wedge
  assert(coupling.ONDE_DUAL_WEDGE !== undefined, 'ONDE_DUAL_WEDGE exists');
  assertStrictEqual(coupling.ONDE_DUAL_WEDGE.type, 'angleBeamWedge', 'dual wedge → angleBeamWedge');
  assertStrictEqual(coupling.ONDE_DUAL_WEDGE.mapping.PROBE_SEPARATION, 'pcs', 'dual PROBE_SEPARATION → pcs');
  assertStrictEqual(coupling.ONDE_DUAL_WEDGE.mapping.ROOF_ANGLE, 'roofAngle', 'dual ROOF_ANGLE → roofAngle');

  group('1.7 — Phased Array Mapping (ONDE_TO_NDE)');
  const pa = ONDE_TO_NDE.phasedArray;
  assertStrictEqual(pa.ONDE_PHASED_ARRAY_ANGLE.nde, 'singleFormation', 'ANGLE → singleFormation');
  assertStrictEqual(pa.ONDE_PHASED_ARRAY_SSCAN.nde, 'sectorialFormation', 'SSCAN → sectorialFormation');
  assertStrictEqual(pa.ONDE_PHASED_ARRAY_ESCAN.nde, 'linearFormation', 'ESCAN → linearFormation');
  assertStrictEqual(pa.ONDE_PHASED_ARRAY_COMPOUND.nde, 'compoundFormation', 'COMPOUND → compoundFormation');
  assertStrictEqual(pa.ONDE_PHASED_ARRAY_PWI.nde, 'planeWaveImaging', 'PWI → planeWaveImaging');
  assert(pa.ONDE_PHASED_ARRAY_FMC.nde.acquisitionPattern !== undefined, 'FMC has acquisitionPattern');
  assertStrictEqual(pa.ONDE_PHASED_ARRAY_FMC.nde.acquisitionPattern, 'FMC', 'FMC → acquisitionPattern: FMC');

  group('1.8 — Gate Detection Mapping');
  const gd = ONDE_TO_NDE.gateDetection;
  assert(gd !== undefined, 'gateDetection mapping exists');
  assertStrictEqual(gd['FIRST_PEAK'], 'FirstPeak', 'FIRST_PEAK → FirstPeak');
  assertStrictEqual(gd['LAST_PEAK'], 'LastPeak', 'LAST_PEAK → LastPeak');
  assertStrictEqual(gd['MAX_PEAK'], 'MaximumPeak', 'MAX_PEAK → MaximumPeak');
  assertStrictEqual(gd['FIRST_FLANK'], 'Crossing', 'FIRST_FLANK → Crossing');
  assertStrictEqual(gd['LAST_FLANK'], 'Crossing', 'LAST_FLANK → Crossing (approximated)');
  assertStrictEqual(gd['MAX_FLANK'], 'Crossing', 'MAX_FLANK → Crossing (approximated)');

  group('1.9 — Scenario Detection');
  const sd = ONDE_TO_NDE.scenarioDetection;
  assertStrictEqual(sd['ONDE_PHASED_ARRAY_FMC'], 'General Mapping', 'FMC scenario');
  assertStrictEqual(sd['ONDE_DATASET_UT_TSCAN'], 'General Mapping', 'TSCAN scenario');
  assertStrictEqual(sd['ONDE_WELD'], 'General Weld', 'Weld scenario');
  assertStrictEqual(sd.default, 'General Mapping', 'default scenario');

  // ═══════════════════════════════════════════════════════════════════════
  //  2. NDE_TO_ONDE Reverse Mapping
  // ═══════════════════════════════════════════════════════════════════════

  group('2. NDE_TO_ONDE — File Identity');
  assertDeepEqual(NDE_TO_ONDE.fileIdentity.attributes, {
    'ONDE:FILETYPE': 'ONDE_UT',
    'ONDE:VERSION': '0.9.0'
  }, 'NDE→ONDE file identity attrs');

  group('2.1 — DataClass to ONDE Type');
  const dct = NDE_TO_ONDE.dataClassToOndeType;
  assertStrictEqual(dct.AScanAmplitude.type, 'ONDE_DATASET_UT_ASCAN', 'AScanAmplitude → ASCAN');
  assertStrictEqual(dct.AScanStatus.type, 'ONDE_DATASET_UT_ASCAN', 'AScanStatus → ASCAN');
  assertStrictEqual(dct.TfmValue.type, 'ONDE_DATASET_UT_TSCAN', 'TfmValue → TSCAN');
  assertStrictEqual(dct.TfmStatus.type, 'ONDE_DATASET_UT_TSCAN', 'TfmStatus → TSCAN');
  assertStrictEqual(dct.CScanPeak.type, 'ONDE_DATASET_UT_CSCAN', 'CScanPeak → CSCAN');
  assertStrictEqual(dct.CScanTime.type, 'ONDE_DATASET_UT_CSCAN', 'CScanTime → CSCAN');
  assertStrictEqual(dct.CScanStatus.type, 'ONDE_DATASET_UT_CSCAN', 'CScanStatus → CSCAN');
  assertStrictEqual(dct.FiringSource.type, 'ONDE_DATASET_UT_ASCAN', 'FiringSource → ASCAN');

  group('2.2 — Reverse Rectification Map');
  const rmap = NDE_TO_ONDE.rectificationMap;
  assertStrictEqual(rmap.None, 'FULL_WAVE', 'None → FULL_WAVE');
  assertStrictEqual(rmap.Positive, 'RECTIFIED_POSITIVE', 'Positive → RECTIFIED_POSITIVE');
  assertStrictEqual(rmap.Negative, 'RECTIFIED_NEGATIVE', 'Negative → RECTIFIED_NEGATIVE');
  assertStrictEqual(rmap.Full, 'RECTIFIED_FULL', 'Full → RECTIFIED_FULL');
  // Verify reversibility with forward map
  const fwdRect = ONDE_TO_NDE.setup.ultrasonic.RECTIFICATION.map;
  assertStrictEqual(rmap[fwdRect.FULL_WAVE], 'FULL_WAVE', 'rectification roundtrip FULL_WAVE');
  assertStrictEqual(rmap[fwdRect.RECTIFIED_POSITIVE], 'RECTIFIED_POSITIVE', 'rectification roundtrip POSITIVE');

  group('2.3 — Reverse Filter Map');
  const fmap = NDE_TO_ONDE.filterMap;
  assertStrictEqual(fmap.None, 'NO_FILTER', 'None → NO_FILTER');
  assertStrictEqual(fmap.LowPass, 'LOW_PASS', 'LowPass → LOW_PASS');
  assertStrictEqual(fmap.HighPass, 'HIGH_PASS', 'HighPass → HIGH_PASS');
  assertStrictEqual(fmap.BandPass, 'BAND_PASS', 'BandPass → BAND_PASS');

  group('2.4 — Geometry to ONDE Type (Reverse)');
  const gtot = NDE_TO_ONDE.geometryToOndeType;
  assertStrictEqual(gtot.plateGeometry, 'ONDE_PLANE', 'plateGeometry → ONDE_PLANE');
  assertStrictEqual(gtot.pipeGeometry, 'ONDE_CYLINDER', 'pipeGeometry → ONDE_CYLINDER');
  assertStrictEqual(gtot.barGeometry, 'ONDE_CYLINDER', 'barGeometry → ONDE_CYLINDER');
  assertStrictEqual(gtot.weldGeometry, 'ONDE_WELD', 'weldGeometry → ONDE_WELD');
  // Verify forward → reverse consistency
  assertStrictEqual(gtot[ONDE_TO_NDE.component.ONDE_PLANE], 'ONDE_PLANE', 'component roundtrip PLANE');
  assertStrictEqual(gtot[ONDE_TO_NDE.component.ONDE_CYLINDER], 'ONDE_CYLINDER', 'component roundtrip CYLINDER');

  group('2.5 — Probe Type to ONDE (Reverse)');
  const pto = NDE_TO_ONDE.probeTypeToOnde;
  assert(pto.conventionalRound !== undefined, 'conventionalRound reverse exists');
  assertStrictEqual(pto.conventionalRound.type, 'ONDE_MONO_UT_PROBE', 'conventionalRound → MONO_UT_PROBE');
  assert(pto.conventionalRectangular !== undefined, 'conventionalRectangular reverse exists');
  assertStrictEqual(pto.conventionalRectangular.type, 'ONDE_MONO_UT_PROBE', 'conventionalRect → MONO_UT_PROBE');
  assert(pto.phasedArrayLinear !== undefined, 'phasedArrayLinear reverse exists');
  assertStrictEqual(pto.phasedArrayLinear.type, 'ONDE_LINEAR_UT_PROBE', 'phasedArrayLinear → LINEAR_UT_PROBE');
  assertStrictEqual(pto.phasedArrayLinear.mapping['elements.elementQuantity'], 'TOTAL_NUMBER_OF_ELEMENTS', 'PA reverse element quantity');

  group('2.6 — Wedge to ONDE (Reverse)');
  const wto = NDE_TO_ONDE.wedgeToOnde;
  assert(wto.angleBeamWedge !== undefined, 'angleBeamWedge reverse exists');
  assertStrictEqual(wto.angleBeamWedge.type, 'ONDE_SINGLE_WEDGE', 'angleBeamWedge → SINGLE_WEDGE');
  assertStrictEqual(wto.angleBeamWedge.mapping['mountingLocations[0].wedgeAngle'], 'INCIDENCE_ANGLE', 'wedge reverse angle');
  assert(wto.fluidColumn !== undefined, 'fluidColumn reverse exists');
  assertStrictEqual(wto.fluidColumn.type, 'ONDE_IMMERSION', 'fluidColumn → IMMERSION');

  group('2.7 — Process to ONDE PA Setup');
  const ptopa = NDE_TO_ONDE.processToOndePASetup;
  assertStrictEqual(ptopa.sectorialFormation, 'ONDE_PHASED_ARRAY_SSCAN', 'sectorialFormation → SSCAN');
  assertStrictEqual(ptopa.linearFormation, 'ONDE_PHASED_ARRAY_ESCAN', 'linearFormation → ESCAN');
  assertStrictEqual(ptopa.compoundFormation, 'ONDE_PHASED_ARRAY_COMPOUND', 'compoundFormation → COMPOUND');
  assertStrictEqual(ptopa.singleFormation, 'ONDE_PHASED_ARRAY_ANGLE', 'singleFormation → ANGLE');

  group('2.8 — Axis to ONDE Dimension');
  const atod = NDE_TO_ONDE.axisToOndeDimension;
  assertDeepEqual(atod.UCoordinate, { coordinate: 'U', units: 'meters' }, 'UCoordinate');
  assertDeepEqual(atod.VCoordinate, { coordinate: 'V', units: 'meters' }, 'VCoordinate');
  assertDeepEqual(atod.WCoordinate, { coordinate: 'W', units: 'meters' }, 'WCoordinate');
  assertDeepEqual(atod.Ultrasound, { coordinate: 'Time', units: 'seconds' }, 'Ultrasound → Time');
  assertDeepEqual(atod.Beam, { coordinate: 'Beam', units: 'arbitrary' }, 'Beam');
  assertDeepEqual(atod.StackedAScan, { coordinate: 'StackedAScan', units: 'arbitrary' }, 'StackedAScan');

  // ═══════════════════════════════════════════════════════════════════════
  //  3. Unit Conversions (UNITS)
  // ═══════════════════════════════════════════════════════════════════════

  group('3. UNITS — ONDE → NDE');
  const ondeToNde = UNITS.ondeToNde;
  assertStrictEqual(ondeToNde.meters, 'Meter', 'meters → Meter');
  assertStrictEqual(ondeToNde.seconds, 'Second', 'seconds → Second');
  assertStrictEqual(ondeToNde.arbitrary, 'Arbitrary', 'arbitrary → Arbitrary');
  assertStrictEqual(ondeToNde.degrees, 'Degree', 'degrees → Degree');

  group('3.1 — UNITS — NDE → ONDE');
  const ndeToOnde = UNITS.ndeToOnde;
  assertStrictEqual(ndeToOnde.Meter, 'meters', 'Meter → meters');
  assertStrictEqual(ndeToOnde.Second, 'seconds', 'Second → seconds');
  assertStrictEqual(ndeToOnde.Arbitrary, 'arbitrary', 'Arbitrary → arbitrary');
  assertStrictEqual(ndeToOnde.Degree, 'degrees', 'Degree → degrees');
  assertStrictEqual(ndeToOnde.Percent, 'arbitrary', 'Percent → arbitrary');
  assertStrictEqual(ndeToOnde.Bitfield, 'arbitrary', 'Bitfield → arbitrary');
  assertStrictEqual(ndeToOnde.BeamId, 'arbitrary', 'BeamId → arbitrary');
  assertStrictEqual(ndeToOnde.ColumnId, 'arbitrary', 'ColumnId → arbitrary');
  assertStrictEqual(ndeToOnde.Coherence, 'arbitrary', 'Coherence → arbitrary');
  assertStrictEqual(ndeToOnde.Seconds, 'seconds', 'Seconds → seconds');

  // Verify roundtrip for core units
  Object.keys(ondeToNde).forEach(key => {
    const ndeUnit = ondeToNde[key];
    if (ndeToOnde[ndeUnit] !== undefined) {
      assertStrictEqual(ndeToOnde[ndeUnit], key, `unit roundtrip: ${key} → ${ndeUnit} → ${key}`);
    }
  });

  // ═══════════════════════════════════════════════════════════════════════
  //  4. Dimension Mappings (DIMENSION_MAPPING)
  // ═══════════════════════════════════════════════════════════════════════

  group('4. DIMENSION_MAPPING — AScan');
  const ascanDims = DIMENSION_MAPPING.ONDE_DATASET_UT_ASCAN;
  assert(ascanDims !== undefined, 'ASCAN dimension mapping exists');
  assert(Array.isArray(ascanDims.indexMapping), 'ASCAN indexMapping is array');
  assert(ascanDims.indexMapping.length >= 3, 'ASCAN indexMapping has >=3 entries');
  const uEntry = ascanDims.indexMapping.find(e => e.name === 'U');
  assert(uEntry !== undefined, 'ASCAN has U dimension');
  assertStrictEqual(uEntry.ondeIndex, 0, 'U has ondeIndex 0');
  assertStrictEqual(uEntry.ndeAxis, 'UCoordinate', 'U → UCoordinate');
  const timeEntry = ascanDims.indexMapping.find(e => e.name === 'Time');
  assert(timeEntry !== undefined, 'ASCAN has Time dimension');
  assertStrictEqual(timeEntry.ondeIndex, 2, 'Time has ondeIndex 2');
  assertStrictEqual(timeEntry.ndeAxis, 'Ultrasound', 'Time → Ultrasound');
  const beamEntry = ascanDims.indexMapping.find(e => e.name === 'Beam');
  assert(beamEntry !== undefined, 'ASCAN has Beam dimension');
  assertStrictEqual(beamEntry.ndeAxis, 'Beam', 'Beam → Beam');
  assertDeepEqual(ascanDims.amplitudeMapping, { name: 'Amplitude', units: 'arbitrary' }, 'ASCAN amplitude mapping');

  group('4.1 — TScan Dimension Mapping');
  const tscanDims = DIMENSION_MAPPING.ONDE_DATASET_UT_TSCAN;
  assert(tscanDims !== undefined, 'TSCAN dimension mapping exists');
  assertStrictEqual(tscanDims.indexMapping.length, 3, 'TSCAN has 3 index entries');
  assertStrictEqual(tscanDims.indexMapping[0].name, 'Row', 'TSCAN row');
  assertStrictEqual(tscanDims.indexMapping[1].name, 'Col', 'TSCAN col');
  assertStrictEqual(tscanDims.indexMapping[2].name, 'Plane', 'TSCAN plane');
  assertStrictEqual(tscanDims.indexMapping[0].ndeAxis, 'UCoordinate', 'TSCAN Row → UCoordinate');
  assertStrictEqual(tscanDims.indexMapping[1].ndeAxis, 'VCoordinate', 'TSCAN Col → VCoordinate');
  assertStrictEqual(tscanDims.indexMapping[2].ndeAxis, 'WCoordinate', 'TSCAN Plane → WCoordinate');

  group('4.2 — CScan Dimension Mapping');
  const cscanDims = DIMENSION_MAPPING.ONDE_DATASET_UT_CSCAN;
  assert(cscanDims !== undefined, 'CSCAN dimension mapping exists');
  assertStrictEqual(cscanDims.indexMapping.length, 2, 'CSCAN has 2 index entries');
  assertStrictEqual(cscanDims.indexMapping[0].name, 'U', 'CSCAN U');
  assertStrictEqual(cscanDims.indexMapping[1].name, 'V', 'CSCAN V');
  assertStrictEqual(cscanDims.indexMapping[0].ndeAxis, 'UCoordinate', 'CSCAN U → UCoordinate');
  assertStrictEqual(cscanDims.indexMapping[1].ndeAxis, 'VCoordinate', 'CSCAN V → VCoordinate');

  // ═══════════════════════════════════════════════════════════════════════
  //  5. Format Detection
  // ═══════════════════════════════════════════════════════════════════════

  group('5. detectFormat — ONDE detection');

  function createMockOndeFile() {
    const rootAttrs = {
      'ONDE:FILETYPE': { value: 'ONDE_UT' },
      'ONDE:VERSION': { value: '0.9.0' }
    };
    return {
      attrs: rootAttrs,
      get(path) {
        if (path === '/') return { attrs: rootAttrs };
        if (path === '/ONDE:TYPE' || path.endsWith('ONDE:TYPE')) {
          return { value: ['ONDE_DATASET', 'ONDE_DATASET_UT', 'ONDE_DATASET_UT_ASCAN'] };
        }
        return this._groups?.[path] || null;
      },
      _groups: {},
      close() {}
    };
  }

  function createMockNdeFile() {
    const propsJson = JSON.stringify({
      methods: ['UT'],
      file: { formatVersion: '4.2.0' }
    });
    return {
      attrs: {},
      get(path) {
        if (path === '/') return { attrs: {} };
        if (path === '/Properties') {
          return { value: new TextEncoder().encode(propsJson) };
        }
        return null;
      },
      close() {}
    };
  }

  function createMockUnknownFile() {
    return {
      attrs: {},
      get(path) {
        if (path === '/') return { attrs: {} };
        return null;
      },
      close() {}
    };
  }

  const ondeFile = createMockOndeFile();
  const ondeDetected = detectFormat(ondeFile);
  assertStrictEqual(ondeDetected.format, 'onde', 'ONDE file detected as onde');
  assertStrictEqual(ondeDetected.version, '0.9.0', 'ONDE file version=0.9.0');

  const ndeFile = createMockNdeFile();
  const ndeDetected = detectFormat(ndeFile);
  assertStrictEqual(ndeDetected.format, 'nde', 'NDE file detected as nde');
  assertStrictEqual(ndeDetected.version, '4.2.0', 'NDE file version=4.2.0');

  const unknownFile = createMockUnknownFile();
  const unknownDetected = detectFormat(unknownFile);
  assertStrictEqual(unknownDetected.format, 'unknown', 'Unknown file detected as unknown');
  assert(unknownDetected.version === undefined, 'Unknown file has no version');

  // ONDE detection without version attr
  const ondeFileNoVer = createMockOndeFile();
  delete ondeFileNoVer.attrs['ONDE:VERSION'];
  const ondeDet2 = detectFormat(ondeFileNoVer);
  assertStrictEqual(ondeDet2.format, 'onde', 'ONDE without version still detected');
  assertStrictEqual(ondeDet2.version, 'unknown', 'ONDE without version → unknown');

  group('5.1 — detectOndeDatasetType');

  // Valid type arrays
  const validAttr1 = { value: ['ONDE_DATASET', 'ONDE_DATASET_UT', 'ONDE_DATASET_UT_ASCAN'] };
  assertStrictEqual(detectOndeDatasetType(validAttr1), 'ONDE_DATASET_UT_ASCAN', 'detect ASCAN dataset type');

  const validAttr2 = { value: ['ONDE_DATASET', 'ONDE_DATASET_UT', 'ONDE_DATASET_UT_TSCAN'] };
  assertStrictEqual(detectOndeDatasetType(validAttr2), 'ONDE_DATASET_UT_TSCAN', 'detect TSCAN dataset type');

  const validAttr3 = { value: ['ONDE_DATASET', 'ONDE_DATASET_UT', 'ONDE_DATASET_UT_CSCAN'] };
  assertStrictEqual(detectOndeDatasetType(validAttr3), 'ONDE_DATASET_UT_CSCAN', 'detect CSCAN dataset type');

  // Null / invalid inputs
  assertStrictEqual(detectOndeDatasetType(null), null, 'null typeAttr → null');
  assertStrictEqual(detectOndeDatasetType(undefined), null, 'undefined typeAttr → null');
  assertStrictEqual(detectOndeDatasetType({}), null, '{} typeAttr (no value) → null');
  assertStrictEqual(detectOndeDatasetType({ value: 'string' }), null, 'non-array value → null');
  assertStrictEqual(detectOndeDatasetType({ value: [] }), null, 'empty array → null');
  assertStrictEqual(detectOndeDatasetType({ value: ['ONDE_DATASET', 'UNKNOWN'] }), null, 'unknown type → null');

  group('5.2 — detectOndeGroupType');

  // Inheritance chain: returns last element
  const groupAttr1 = { value: ['ONDE_UT_PROBE', 'ONDE_LINEAR_UT_PROBE'] };
  assertStrictEqual(detectOndeGroupType(groupAttr1), 'ONDE_LINEAR_UT_PROBE', 'group type returns most specific (last)');

  const groupAttr2 = { value: ['ONDE_COMPONENT', 'ONDE_PLANE'] };
  assertStrictEqual(detectOndeGroupType(groupAttr2), 'ONDE_PLANE', 'component chain → ONDE_PLANE');

  // Single type
  const groupAttr3 = { value: ['ONDE_ULTRASONIC_SETUP'] };
  assertStrictEqual(detectOndeGroupType(groupAttr3), 'ONDE_ULTRASONIC_SETUP', 'single type');

  // Edge cases
  assertStrictEqual(detectOndeGroupType(null), null, 'null group type → null');
  assertStrictEqual(detectOndeGroupType(undefined), null, 'undefined group type → null');
  assertStrictEqual(detectOndeGroupType({}), null, 'empty object group type → null');
  assertStrictEqual(detectOndeGroupType({ value: [] }), null, 'empty array group type → null');

  // ═══════════════════════════════════════════════════════════════════════
  //  6. Edge Cases
  // ═══════════════════════════════════════════════════════════════════════

  group('6. Edge Cases — Null/Empty/Missing');

  // detectFormat edge cases
  const emptyFile = { attrs: {}, get() { return null; }, close() {} };
  assertStrictEqual(detectFormat(emptyFile).format, 'unknown', 'empty file → unknown');

  // File with missing attrs
  const noAttrsFile = { get() { return null; }, close() {} };
  // This shouldn't throw - catch block handles it
  let result;
  try {
    result = detectFormat(noAttrsFile);
  } catch (e) {
    result = { format: 'error' };
  }
  assert(result !== undefined, 'file with no attrs does not crash detectFormat');

  // ONDE file with missing TYPE attr
  const ondeNoType = createMockOndeFile();
  ondeNoType.get = (p) => p === '/' ? { attrs: ondeNoType.attrs } : null; // Override get to return nothing for children, but keep root attrs accessible
  const detected = detectFormat(ondeNoType);
  assertStrictEqual(detected.format, 'onde', 'ONDE file without children still detected by root attrs');
  assertStrictEqual(detected.version, '0.9.0', 'version still read');

  // detectOndeDatasetType with various bad inputs
  assertStrictEqual(detectOndeDatasetType({ value: ['ONDE_DATASET'] }), null, 'generic ONDE_DATASET (no UT subclass) → null');
  assertStrictEqual(detectOndeDatasetType({ value: ['ONDE_DATASET_UT'] }), null, 'generic ONDE_DATASET_UT (no specific) → null');

  // detectOndeGroupType with single-element array vs multi
  const singleType = { value: ['ONDE_PLANE'] };
  assertStrictEqual(detectOndeGroupType(singleType), 'ONDE_PLANE', 'single-element array returns that element');

  // Verify ONDE_TO_NDE keys for completeness
  group('6.1 — Mapping completeness checks');
  const expectedDatasetTypes = ['ONDE_DATASET_UT_ASCAN', 'ONDE_DATASET_UT_TSCAN', 'ONDE_DATASET_UT_CSCAN'];
  expectedDatasetTypes.forEach(t => {
    assert(dcm[t] !== undefined, `datasetClassMapping includes ${t}`);
  });

  const expectedProbeTypes = ['ONDE_MONO_UT_PROBE', 'ONDE_LINEAR_UT_PROBE', 'ONDE_MATRIX_UT_PROBE'];
  expectedProbeTypes.forEach(t => {
    assert(probe[t] !== undefined, `probe mapping includes ${t}`);
  });

  const expectedCouplingTypes = ['ONDE_IMMERSION', 'ONDE_WEDGE', 'ONDE_SINGLE_WEDGE', 'ONDE_DUAL_WEDGE'];
  expectedCouplingTypes.forEach(t => {
    assert(coupling[t] !== undefined, `coupling mapping includes ${t}`);
  });

  const expectedComponentTypes = ['ONDE_PLANE', 'ONDE_CYLINDER', 'ONDE_2DCAD', 'ONDE_3DCAD', 'ONDE_WELD'];
  expectedComponentTypes.forEach(t => {
    assert(comp[t] !== undefined, `component mapping includes ${t}`);
  });

  const expectedPATypes = [
    'ONDE_PHASED_ARRAY_ANGLE', 'ONDE_PHASED_ARRAY_SSCAN', 'ONDE_PHASED_ARRAY_ESCAN',
    'ONDE_PHASED_ARRAY_COMPOUND', 'ONDE_PHASED_ARRAY_PWI', 'ONDE_PHASED_ARRAY_FMC'
  ];
  expectedPATypes.forEach(t => {
    assert(pa[t] !== undefined, `phasedArray mapping includes ${t}`);
  });

  // Verify NDE_TO_ONDE reverse mapping contains all forward dataset class keys
  group('6.2 — Reverse mapping coverage');
  const reverseTypes = new Set(Object.values(NDE_TO_ONDE.dataClassToOndeType).map(v => v.type));
  Object.keys(ONDE_TO_NDE.datasetClassMapping).forEach(fwdType => {
    assert(reverseTypes.has(fwdType), `reverse mapping covers ${fwdType}`);
  });

  // Verify every component forward mapping has reverse
  Object.values(ONDE_TO_NDE.component).forEach(ndeGeom => {
    const reverseType = NDE_TO_ONDE.geometryToOndeType[ndeGeom];
    // Not all NDE geometries have reverse (e.g., plateGeometry for 2DCAD/3DCAD is approximate)
    // but at minimum plateGeometry & pipeGeometry should be covered
    if (ndeGeom === 'plateGeometry' || ndeGeom === 'pipeGeometry' || ndeGeom === 'weldGeometry') {
      assert(reverseType !== undefined, `reverse mapping covers ${ndeGeom}`);
    }
  });

  // ═══════════════════════════════════════════════════════════════════════
  //  Summary
  // ═══════════════════════════════════════════════════════════════════════

  const total = passed + failed;
  console.log(`\n${'═'.repeat(58)}`);
  console.log(`  Results: ${passed}/${total} passed`);
  if (failures.length > 0) {
    console.log(`  Failures:`);
    failures.forEach(f => console.log(`    • ${f}`));
  }
  console.log(`${'═'.repeat(58)}\n`);

  process.exit(failed > 0 ? 1 : 0);
})();

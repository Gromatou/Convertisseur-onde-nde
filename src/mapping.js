/**
 * ONDE ↔ NDE Bidirectional Field Mapping Table
 *
 * ONDE (COFREND/EPRI): HDF5 attributes + object references, class inheritance via ONDE:TYPE
 * NDE  (Evident 4.2.0): JSON metadata embedded in HDF5 datasets, flat JSON objects with $ref IDs
 *
 * Both formats store raw data arrays identically in HDF5 datasets.
 * Conversion is metadata remapping across two different conventions.
 */

// ─── ONDE → NDE Mapping ───────────────────────────────────────────────

export const ONDE_TO_NDE = {
  // ── File Identity ──────────────────────────────────────────────────
  fileType: {
    onde: { path: '/', attr: 'ONDE:FILETYPE', check: 'ONDE_UT' },
    nde:  { set: { '/Properties': { methods: ['UT'] } } }
  },
  formatVersion: {
    onde: { path: '/', attr: 'ONDE:VERSION' },
    nde:  { set: { '/Properties': { 'file.formatVersion': '4.2.0' } } }
  },

  // ── Dataset Types → NDE dataClass ───────────────────────────────────
  datasetClassMapping: {
    'ONDE_DATASET_UT_ASCAN': {
      amplitude: 'AScanAmplitude',
      status:    'AScanStatus'
    },
    'ONDE_DATASET_UT_TSCAN': {
      value:  'TfmValue',
      status: 'TfmStatus'
    },
    'ONDE_DATASET_UT_CSCAN': {
      peak:   'CScanPeak',
      time:   'CScanTime',
      status: 'CScanStatus'
    }
  },

  // ── ONDE_SETUP → NDE Public/Setup ──────────────────────────────────
  setup: {
    // ULTRASONIC_SETUP fields to NDE Setup properties
    ultrasonic: {
      'ASCAN_SAMPLE_RATE':       { nde: 'digitizingFrequency', type: 'number' },
      'ASCAN_START':             { nde: 'ascanStart', type: 'number' },
      'RECTIFICATION':           { nde: 'rectification', type: 'mapping',
        map: { 'FULL_WAVE': 'None', 'RECTIFIED_POSITIVE': 'Positive',
               'RECTIFIED_NEGATIVE': 'Negative', 'RECTIFIED_FULL': 'Full' }},
      'FILTER_TYPE':             { nde: 'filterType', type: 'mapping',
        map: { 'NO_FILTER': 'None', 'LOW_PASS': 'LowPass',
               'HIGH_PASS': 'HighPass', 'BAND_PASS': 'BandPass' }},
      'GAIN':                    { nde: 'gain', type: 'number' },
      'PRF':                     { nde: 'pulseRepetitionFrequency', type: 'number' }
    },

    // GEOMETRIC_SETUP fields
    geometric: {
      'COMPONENT':               { nde: 'specimens', type: 'component' },
      'PROBE_LIST':              { nde: 'probes', type: 'probes' },
      'ACQUISITION_TRAJECTORY':  { nde: 'motionDevices', type: 'trajectory' }
    }
  },

  // ── Component/Geometry → NDE specimens ──────────────────────────────
  component: {
    'ONDE_PLANE':    'plateGeometry',
    'ONDE_CYLINDER': 'pipeGeometry',
    'ONDE_2DCAD':    'plateGeometry',  // approximated
    'ONDE_3DCAD':    'plateGeometry',  // approximated
    'ONDE_WELD':     'weldGeometry'
  },

  // ── Probe → NDE probes ──────────────────────────────────────────────
  probe: {
    'ONDE_MONO_UT_PROBE': {
      type: 'conventionalRound',
      mapping: {
        'FREQUENCY':  'centralFrequency',
        'MANUFACTURER': 'probeManufacturer',  // NDE has no direct equivalent, placed in model
        'SERIAL_NUMBER': 'model'
      }
    },
    'ONDE_LINEAR_UT_PROBE': {
      type: 'phasedArrayLinear',
      mapping: {
        'FREQUENCY':                'centralFrequency',
        'TOTAL_NUMBER_OF_ELEMENTS': 'elements.elementQuantity',
        'ELEMENT_DIM_MAJOR':        'elements.primaryAxis.elementLength',
        'ELEMENT_DIM_MINOR':        'elements.secondaryAxis.elementWidth',
        'ELEMENT_PITCH_DIM_MAJOR':  'elements.primaryAxis.elementGap',
        'MANUFACTURER':             'model',
        'SERIAL_NUMBER':            'serialNumber'
      }
    },
    'ONDE_MATRIX_UT_PROBE': {
      type: 'phasedArrayLinear',  // closest NDE type
      mapping: {
        'FREQUENCY':      'centralFrequency',
        'ELEMENT_DIM_MAJOR':  'elements.primaryAxis.elementLength',
        'ELEMENT_DIM_MINOR':  'elements.secondaryAxis.elementWidth',
        'ELEMENT_PITCH_DIM_MAJOR': 'elements.primaryAxis.elementGap',
        'ELEMENT_PITCH_DIM_MINOR': 'elements.secondaryAxis.elementGap'
      }
    }
  },

  // ── Coupling/Wedge → NDE wedges ────────────────────────────────────
  coupling: {
    'ONDE_IMMERSION': {
      type: 'fluidColumn',
      mapping: {
        'WATER_PATH':          'height',
        'MEDIUM_VELOCITY':     'velocity',  // [0] = longitudinal
        'MEDIUM_DENSITY':      'density',
        'INCIDENCE_ANGLE':     'angle'
      }
    },
    'ONDE_WEDGE': {
      type: 'angleBeamWedge',
      mapping: {
        'HEIGHT':              'delay',
        'SKEW_ANGLE':          'skewAngle',
        'CONTACT_AREA':        'contactArea',
        'MANUFACTURER':        'model',
        'SERIAL_NUMBER':       'serialNumber',
        'MEDIUM_VELOCITY':     'velocity',
        'INCIDENCE_ANGLE':     'mountingLocations[0].wedgeAngle'
      }
    },
    'ONDE_SINGLE_WEDGE': {
      type: 'angleBeamWedge',
      mapping: {
        'HEIGHT':              'delay',
        'SKEW_ANGLE':          'skewAngle',
        'CONTACT_AREA':        'contactArea',
        'MEDIUM_VELOCITY':     'velocity',
        'INCIDENCE_ANGLE':     'mountingLocations[0].wedgeAngle'
      }
    },
    'ONDE_DUAL_WEDGE': {
      type: 'angleBeamWedge',
      mapping: {
        'HEIGHT':              'delay',
        'SKEW_ANGLE':          'skewAngle',
        'PROBE_SEPARATION':    'pcs',
        'ROOF_ANGLE':          'roofAngle',
        'MEDIUM_VELOCITY':     'velocity',
        'INCIDENCE_ANGLE':     'mountingLocations[0].wedgeAngle'
      }
    }
  },

  // ── Phased Array Setup → NDE processes ─────────────────────────────
  phasedArray: {
    'ONDE_PHASED_ARRAY_ANGLE':   { nde: 'singleFormation' },
    'ONDE_PHASED_ARRAY_SSCAN':   { nde: 'sectorialFormation' },
    'ONDE_PHASED_ARRAY_ESCAN':   { nde: 'linearFormation' },
    'ONDE_PHASED_ARRAY_COMPOUND': { nde: 'compoundFormation' },
    'ONDE_PHASED_ARRAY_PWI':     { nde: 'planeWaveImaging' },
    'ONDE_PHASED_ARRAY_FMC':     { nde: { acquisitionPattern: 'FMC' } }
  },

  // ── Gate Detection ──────────────────────────────────────────────────
  gateDetection: {
    'FIRST_PEAK':  'FirstPeak',
    'LAST_PEAK':   'LastPeak',
    'MAX_PEAK':    'MaximumPeak',
    'FIRST_FLANK': 'Crossing',
    'LAST_FLANK':  'Crossing',   // no direct NDE equivalent
    'MAX_FLANK':   'Crossing'    // no direct NDE equivalent
  },

  // ── Scenario Detection ──────────────────────────────────────────────
  scenarioDetection: {
    'ONDE_PHASED_ARRAY_FMC':  'General Mapping',
    'ONDE_DATASET_UT_TSCAN':  'General Mapping',
    'ONDE_WELD':              'General Weld',
    default:                  'General Mapping'
  }
};

// ─── NDE → ONDE Mapping ───────────────────────────────────────────────

export const NDE_TO_ONDE = {
  // ── File Identity ──────────────────────────────────────────────────
  fileIdentity: {
    attributes: {
      'ONDE:FILETYPE': 'ONDE_UT',
      'ONDE:VERSION':  '0.9.0'
    }
  },

  // ── dataClass → ONDE dataset type ──────────────────────────────────
  dataClassToOndeType: {
    'AScanAmplitude': { type: 'ONDE_DATASET_UT_ASCAN' },
    'AScanStatus':    { type: 'ONDE_DATASET_UT_ASCAN' },
    'TfmValue':       { type: 'ONDE_DATASET_UT_TSCAN' },
    'TfmStatus':      { type: 'ONDE_DATASET_UT_TSCAN' },
    'CScanPeak':      { type: 'ONDE_DATASET_UT_CSCAN' },
    'CScanTime':      { type: 'ONDE_DATASET_UT_CSCAN' },
    'CScanStatus':    { type: 'ONDE_DATASET_UT_CSCAN' },
    'FiringSource':   { type: 'ONDE_DATASET_UT_ASCAN' }
  },

  // ── NDE rectification → ONDE ───────────────────────────────────────
  rectificationMap: {
    'None':     'FULL_WAVE',
    'Positive': 'RECTIFIED_POSITIVE',
    'Negative': 'RECTIFIED_NEGATIVE',
    'Full':     'RECTIFIED_FULL'
  },

  // ── NDE filter → ONDE ──────────────────────────────────────────────
  filterMap: {
    'None':     'NO_FILTER',
    'LowPass':  'LOW_PASS',
    'HighPass': 'HIGH_PASS',
    'BandPass': 'BAND_PASS'
  },

  // ── NDE geometry type → ONDE component ─────────────────────────────
  geometryToOndeType: {
    'plateGeometry':  'ONDE_PLANE',
    'pipeGeometry':   'ONDE_CYLINDER',
    'barGeometry':    'ONDE_CYLINDER',
    'weldGeometry':   'ONDE_WELD'
  },

  // ── NDE probe type → ONDE probe ────────────────────────────────────
  probeTypeToOnde: {
    'conventionalRound':      { type: 'ONDE_MONO_UT_PROBE',
      mapping: { 'centralFrequency': 'FREQUENCY', 'diameter': 'ELEMENT_DIM_MAJOR' }},
    'conventionalRectangular': { type: 'ONDE_MONO_UT_PROBE',
      mapping: { 'centralFrequency': 'FREQUENCY', 'length': 'ELEMENT_DIM_MAJOR' }},
    'phasedArrayLinear':      { type: 'ONDE_LINEAR_UT_PROBE',
      mapping: {
        'centralFrequency':      'FREQUENCY',
        'elements.elementQuantity': 'TOTAL_NUMBER_OF_ELEMENTS',
        'elements.primaryAxis.elementLength': 'ELEMENT_DIM_MAJOR',
        'elements.primaryAxis.elementGap':    'ELEMENT_PITCH_DIM_MAJOR'
      }}
  },

  // ── NDE wedge → ONDE coupling ──────────────────────────────────────
  wedgeToOnde: {
    'angleBeamWedge': { type: 'ONDE_SINGLE_WEDGE',
      mapping: { 'mountingLocations[0].wedgeAngle': 'INCIDENCE_ANGLE', 'delay': 'HEIGHT', 'skewAngle': 'SKEW_ANGLE' }},
    'fluidColumn':    { type: 'ONDE_IMMERSION',
      mapping: { 'height': 'WATER_PATH' }}
  },

  // ── NDE process → ONDE phased array ────────────────────────────────
  processToOndePASetup: {
    'sectorialFormation':   'ONDE_PHASED_ARRAY_SSCAN',
    'linearFormation':      'ONDE_PHASED_ARRAY_ESCAN',
    'compoundFormation':    'ONDE_PHASED_ARRAY_COMPOUND',
    'singleFormation':      'ONDE_PHASED_ARRAY_ANGLE'
  },

  // ── NDE dimension axes → ONDE dimensions ───────────────────────────
  axisToOndeDimension: {
    'UCoordinate':   { coordinate: 'U',  units: 'meters' },
    'VCoordinate':   { coordinate: 'V',  units: 'meters' },
    'WCoordinate':   { coordinate: 'W',  units: 'meters' },
    'Ultrasound':    { coordinate: 'Time', units: 'seconds' },
    'Beam':          { coordinate: 'Beam', units: 'arbitrary' },
    'StackedAScan':  { coordinate: 'StackedAScan', units: 'arbitrary' }
  },

  // ── NDE wave mode → ONDE wave mode ────────────────────────────────
  waveModeMap: { 'Longitudinal': 'L', 'TransversalVertical': 'T' }
};

// ─── Shared Unit/Type Conversions ──────────────────────────────────────

export const UNITS = {
  ondeToNde: {
    'meters': 'Meter',
    'seconds': 'Second',
    'arbitrary': 'Arbitrary',
    'degrees': 'Degree'
  },
  ndeToOnde: {
    'Meter': 'meters',
    'Second': 'seconds',
    'Arbitrary': 'arbitrary',
    'Degree': 'degrees',
    'Percent': 'arbitrary',
    'Bitfield': 'arbitrary',
    'BeamId': 'arbitrary',
    'ColumnId': 'arbitrary',
    'Coherence': 'arbitrary',
    'Seconds': 'seconds'
  }
};

// ─── Dimension Mapping (ONDE INDEX_DIMENSIONS ↔ NDE axes) ──────────────

export const DIMENSION_MAPPING = {
  ONDE_DATASET_UT_ASCAN: {
    // NDE axes for AScanAmplitude: [U, V, Ultrasound] or [U, Beam, Ultrasound] etc.
    indexMapping: [
      { ondeIndex: 0, name: 'U', ndeAxis: 'UCoordinate' },
      { ondeIndex: 1, name: 'V', ndeAxis: 'VCoordinate' },
      { ondeIndex: 1, name: 'Beam', ndeAxis: 'Beam' },
      { ondeIndex: 1, name: 'StackedAScan', ndeAxis: 'StackedAScan' },
      { ondeIndex: 2, name: 'Time', ndeAxis: 'Ultrasound' }
    ],
    amplitudeMapping: { name: 'Amplitude', units: 'arbitrary' }
  },
  ONDE_DATASET_UT_TSCAN: {
    indexMapping: [
      { ondeIndex: 0, name: 'Row', ndeAxis: 'UCoordinate' },
      { ondeIndex: 1, name: 'Col', ndeAxis: 'VCoordinate' },
      { ondeIndex: 2, name: 'Plane', ndeAxis: 'WCoordinate' }
    ],
    amplitudeMapping: { name: 'Amplitude', units: 'arbitrary' }
  },
  ONDE_DATASET_UT_CSCAN: {
    indexMapping: [
      { ondeIndex: 0, name: 'U', ndeAxis: 'UCoordinate' },
      { ondeIndex: 1, name: 'V', ndeAxis: 'VCoordinate' }
    ],
    amplitudeMapping: { name: 'Amplitude', units: 'arbitrary' }
  }
};

/**
 * Detection: determine if an HDF5 file is ONDE or NDE format.
 * Returns { format: 'onde'|'nde'|'unknown', version: string|undefined }
 */
export function detectFormat(h5file) {
  // Check ONDE markers (root attributes)
  try {
    const root = h5file.get('/');
    const rootAttrs = root?.attrs || {};
    const fileType = rootAttrs['ONDE:FILETYPE']?.value;
    if (fileType === 'ONDE_UT') {
      return { format: 'onde', version: rootAttrs['ONDE:VERSION']?.value || 'unknown' };
    }
  } catch (_) { /* not ONDE */ }

  // Check NDE markers (Properties dataset)
  try {
    const propsDataset = h5file.get('/Properties');
    if (propsDataset && propsDataset.value) {
      const jsonBytes = propsDataset.value;
      const text = typeof jsonBytes === 'string'
        ? jsonBytes
        : new TextDecoder().decode(jsonBytes);
      const props = JSON.parse(text);
      if (props.methods?.includes('UT') && props.file?.formatVersion) {
        return { format: 'nde', version: props.file.formatVersion };
      }
    }
  } catch (_) { /* not NDE */ }

  return { format: 'unknown' };
}

/**
 * Detect ONDE dataset type from ONDE:TYPE HDF5 attribute
 */
export function detectOndeDatasetType(typeAttr) {
  if (!typeAttr || !Array.isArray(typeAttr.value)) return null;
  const types = typeAttr.value;
  if (types.includes('ONDE_DATASET_UT_ASCAN')) return 'ONDE_DATASET_UT_ASCAN';
  if (types.includes('ONDE_DATASET_UT_TSCAN')) return 'ONDE_DATASET_UT_TSCAN';
  if (types.includes('ONDE_DATASET_UT_CSCAN')) return 'ONDE_DATASET_UT_CSCAN';
  return null;
}

/**
 * Detect ONDE group type from its ONDE:TYPE attribute
 */
export function detectOndeGroupType(typeAttr) {
  if (!typeAttr || !Array.isArray(typeAttr.value)) return null;
  const types = typeAttr.value;
  // Return the most specific type (last in inheritance chain)
  return types[types.length - 1] || types[0] || null;
}

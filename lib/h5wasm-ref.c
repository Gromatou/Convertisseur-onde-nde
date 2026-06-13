/**
 * h5wasm-ref.c — HDF5 Object Reference Module for Emscripten
 *
 * Exposes low-level HDF5 C API functions needed to create and manipulate
 * H5T_STD_REF_OBJ object references in HDF5 files.
 *
 * Compile with:
 *   emcc -O2 -sEXPORTED_RUNTIME_METHODS=FS,allocateUTF8,stringToUTF8,UTF8ToString \
 *        -sINITIAL_MEMORY=16MB -sMAXIMUM_MEMORY=512MB \
 *        -sALLOW_MEMORY_GROWTH=1 -sEXPORT_ES6=0 -sMODULARIZE=1 \
 *        -I/tmp/hdf5-install/include -L/tmp/hdf5-install/lib \
 *        -lhdf5 -lhdf5_hl \
 *        h5wasm-ref.c -o h5wasm-ref.js
 */

#include <hdf5.h>
#include <emscripten.h>
#include <string.h>
#include <stdlib.h>

// ─── File Operations ─────────────────────────────────────────────────────

EMSCRIPTEN_KEEPALIVE
hid_t h5r_open(const char *filename) {
    return H5Fopen(filename, H5F_ACC_RDWR, H5P_DEFAULT);
}

EMSCRIPTEN_KEEPALIVE
herr_t h5r_close(hid_t file_id) {
    return H5Fclose(file_id);
}

EMSCRIPTEN_KEEPALIVE
hid_t h5r_create_file(const char *filename) {
    return H5Fcreate(filename, H5F_ACC_TRUNC, H5P_DEFAULT, H5P_DEFAULT);
}

// ─── Group Operations ────────────────────────────────────────────────────

EMSCRIPTEN_KEEPALIVE
hid_t h5r_open_group(hid_t file_id, const char *path) {
    return H5Gopen2(file_id, path, H5P_DEFAULT);
}

EMSCRIPTEN_KEEPALIVE
herr_t h5r_close_obj(hid_t obj_id) {
    return H5Oclose(obj_id);
}

EMSCRIPTEN_KEEPALIVE
hid_t h5r_create_group(hid_t file_id, const char *path) {
    return H5Gcreate2(file_id, path, H5P_DEFAULT, H5P_DEFAULT, H5P_DEFAULT);
}

// ─── Reference Operations ────────────────────────────────────────────────

/**
 * Create an HDF5 object reference and write the 8-byte reference to the
 * provided buffer (ref_buf must point to at least 8 bytes).
 */
EMSCRIPTEN_KEEPALIVE
int h5r_create_reference(hid_t file_id, const char *obj_path, void *ref_buf) {
    hdset_reg_ref_t ref;
    herr_t status = H5Rcreate(&ref, file_id, obj_path, H5R_OBJECT, -1);
    if (status < 0) return -1;
    memcpy(ref_buf, &ref, sizeof(hdset_reg_ref_t));
    return 0;
}

/**
 * Dereference an object reference, returning the object ID.
 * The ref_buf must be an 8-byte HDF5 object reference.
 */
EMSCRIPTEN_KEEPALIVE
hid_t h5r_dereference(hid_t file_id, const void *ref_buf) {
    hdset_reg_ref_t ref;
    memcpy(&ref, ref_buf, sizeof(hdset_reg_ref_t));
    return H5Rdereference2(file_id, H5P_DEFAULT, H5R_OBJECT, &ref);
}

/**
 * Get the name of a referenced object. Returns the length of the name,
 * or -1 on error. Writes up to buf_size bytes into name_buf.
 */
EMSCRIPTEN_KEEPALIVE
int h5r_get_name(hid_t file_id, const void *ref_buf, char *name_buf, int buf_size) {
    hdset_reg_ref_t ref;
    memcpy(&ref, ref_buf, sizeof(hdset_reg_ref_t));
    ssize_t len = H5Rget_name(file_id, H5R_OBJECT, &ref, name_buf, (size_t)buf_size);
    return (int)len;
}

/**
 * Get the type of a referenced object.
 * Returns one of H5G_UNKNOWN (=-1), H5G_GROUP, H5G_DATASET, H5G_TYPE.
 */
EMSCRIPTEN_KEEPALIVE
int h5r_get_obj_type(hid_t file_id, const void *ref_buf) {
    H5O_type_t obj_type;
    hdset_reg_ref_t ref;
    memcpy(&ref, ref_buf, sizeof(hdset_reg_ref_t));
    herr_t status = H5Rget_obj_type2(file_id, H5R_OBJECT, &ref, &obj_type);
    if (status < 0) return -1;
    return (int)obj_type;
}

// ─── Attribute Operations ────────────────────────────────────────────────

EMSCRIPTEN_KEEPALIVE
herr_t h5r_set_attr_double(hid_t obj_id, const char *attr_name, double value) {
    // Delete existing attribute first (to replace e.g. a string attr with double)
    H5Adelete(obj_id, attr_name);

    hid_t space_id = H5Screate(H5S_SCALAR);
    hid_t attr_id = H5Acreate2(obj_id, attr_name, H5T_NATIVE_DOUBLE, space_id, H5P_DEFAULT, H5P_DEFAULT);
    if (attr_id < 0) { H5Sclose(space_id); return -1; }
    herr_t status = H5Awrite(attr_id, H5T_NATIVE_DOUBLE, &value);
    H5Aclose(attr_id);
    H5Sclose(space_id);
    return status;
}

EMSCRIPTEN_KEEPALIVE
herr_t h5r_set_attr_int(hid_t obj_id, const char *attr_name, int value) {
    H5Adelete(obj_id, attr_name);

    hid_t space_id = H5Screate(H5S_SCALAR);
    hid_t attr_id = H5Acreate2(obj_id, attr_name, H5T_NATIVE_INT, space_id, H5P_DEFAULT, H5P_DEFAULT);
    if (attr_id < 0) { H5Sclose(space_id); return -1; }
    herr_t status = H5Awrite(attr_id, H5T_NATIVE_INT, &value);
    H5Aclose(attr_id);
    H5Sclose(space_id);
    return status;
}

EMSCRIPTEN_KEEPALIVE
herr_t h5r_set_attr_string(hid_t obj_id, const char *attr_name, const char *value) {
    H5Adelete(obj_id, attr_name);

    hid_t space_id = H5Screate(H5S_SCALAR);
    hid_t attr_type = H5Tcopy(H5T_C_S1);
    H5Tset_size(attr_type, strlen(value) + 1);
    hid_t attr_id = H5Acreate2(obj_id, attr_name, attr_type, space_id, H5P_DEFAULT, H5P_DEFAULT);
    if (attr_id < 0) { H5Tclose(attr_type); H5Sclose(space_id); return -1; }
    herr_t status = H5Awrite(attr_id, attr_type, value);
    H5Aclose(attr_id);
    H5Tclose(attr_type);
    H5Sclose(space_id);
    return status;
}

EMSCRIPTEN_KEEPALIVE
double h5r_get_attr_double(hid_t obj_id, const char *attr_name) {
    hid_t attr_id = H5Aopen(obj_id, attr_name, H5P_DEFAULT);
    if (attr_id < 0) return -1.0;
    double value;
    herr_t status = H5Aread(attr_id, H5T_NATIVE_DOUBLE, &value);
    H5Aclose(attr_id);
    if (status < 0) return -1.0;
    return value;
}

// ─── NEW: Reference Attributes (Part B) ──────────────────────────────────

/**
 * Create (or replace) an attribute of type H5T_STD_REF_OBJ on the given
 * object, pointing to target_path in the same file.
 *
 * Unlike storing raw reference bytes as a double attribute, this creates a
 * REAL HDF5 object reference attribute that HDF5 readers will correctly
 * interpret as H5T_STD_REF_OBJ.
 *
 * Returns 0 on success, -1 on failure.
 */
EMSCRIPTEN_KEEPALIVE
int h5r_set_attr_ref(hid_t obj_id, const char *attr_name, hid_t file_id, const char *target_path) {
    hdset_reg_ref_t ref;

    // Create the object reference
    herr_t status = H5Rcreate(&ref, file_id, target_path, H5R_OBJECT, -1);
    if (status < 0) return -1;

    // Delete existing attribute if present (to replace string attr with ref)
    H5Adelete(obj_id, attr_name);

    // Create scalar dataspace
    hid_t space_id = H5Screate(H5S_SCALAR);
    if (space_id < 0) return -1;

    // Create attribute with H5T_STD_REF_OBJ type
    hid_t attr_id = H5Acreate2(obj_id, attr_name, H5T_STD_REF_OBJ, space_id, H5P_DEFAULT, H5P_DEFAULT);
    if (attr_id < 0) {
        H5Sclose(space_id);
        return -1;
    }

    // Write the reference
    status = H5Awrite(attr_id, H5T_STD_REF_OBJ, &ref);

    H5Aclose(attr_id);
    H5Sclose(space_id);
    return (status < 0) ? -1 : 0;
}

/**
 * Create (or replace) an attribute containing an array of HDF5 object references.
 * target_paths should be a concatenation of null-terminated C strings,
 * and count specifies the number of paths.
 *
 * Example: target_paths = "/dim_U\0/dim_V\0" with count=2
 * creates an attribute with 2 references.
 *
 * Returns 0 on success, -1 on failure.
 */
EMSCRIPTEN_KEEPALIVE
int h5r_set_attr_ref_array(hid_t obj_id, const char *attr_name, hid_t file_id,
                           const char *target_paths, int count) {
    if (count <= 0) return -1;

    // Allocate array of references
    hdset_reg_ref_t *refs = (hdset_reg_ref_t *)malloc((size_t)count * sizeof(hdset_reg_ref_t));
    if (!refs) return -1;

    // Create each reference
    const char *cur = target_paths;
    for (int i = 0; i < count; i++) {
        herr_t status = H5Rcreate(&refs[i], file_id, cur, H5R_OBJECT, -1);
        if (status < 0) {
            free(refs);
            return -1;
        }
        // Advance past null terminator
        cur += strlen(cur) + 1;
    }

    // Delete existing attribute
    H5Adelete(obj_id, attr_name);

    // Create 1D dataspace for the reference array
    hsize_t dims[1] = {(hsize_t)count};
    hid_t space_id = H5Screate_simple(1, dims, NULL);
    if (space_id < 0) { free(refs); return -1; }

    // Create attribute with H5T_STD_REF_OBJ
    hid_t attr_id = H5Acreate2(obj_id, attr_name, H5T_STD_REF_OBJ, space_id, H5P_DEFAULT, H5P_DEFAULT);
    if (attr_id < 0) { H5Sclose(space_id); free(refs); return -1; }

    herr_t status = H5Awrite(attr_id, H5T_STD_REF_OBJ, refs);
    H5Aclose(attr_id);
    H5Sclose(space_id);
    free(refs);
    return (status < 0) ? -1 : 0;
}

/**
 * Create a REFERENCE DATASET containing a single HDF5 object reference.
 * This is useful for storing reference values as datasets (e.g., PROBE_LIST
 * can be a dataset of references).
 *
 * Returns the dataset ID on success, or -1 on failure.
 */
EMSCRIPTEN_KEEPALIVE
hid_t h5r_create_ref_dataset(hid_t parent_id, const char *ds_name, hid_t file_id, const char *target_path) {
    hdset_reg_ref_t ref;

    herr_t status = H5Rcreate(&ref, file_id, target_path, H5R_OBJECT, -1);
    if (status < 0) return -1;

    hid_t space_id = H5Screate(H5S_SCALAR);
    if (space_id < 0) return -1;

    hid_t ds_id = H5Dcreate2(parent_id, ds_name, H5T_STD_REF_OBJ, space_id,
                             H5P_DEFAULT, H5P_DEFAULT, H5P_DEFAULT);
    if (ds_id < 0) {
        H5Sclose(space_id);
        return -1;
    }

    status = H5Dwrite(ds_id, H5T_STD_REF_OBJ, H5S_ALL, H5S_ALL, H5P_DEFAULT, &ref);
    if (status < 0) {
        H5Dclose(ds_id);
        H5Sclose(space_id);
        return -1;
    }

    H5Sclose(space_id);
    return ds_id;
}

/**
 * Create a 1D dataset of doubles on the given parent object.
 * Useful for storing multiple values as a dataset.
 *
 * Returns the dataset ID, or -1 on failure.
 */
EMSCRIPTEN_KEEPALIVE
hid_t h5r_create_dataset_f64(hid_t parent_id, const char *name, const double *data, int count) {
    hsize_t dims[1] = {(hsize_t)count};
    hid_t space_id = H5Screate_simple(1, dims, NULL);
    if (space_id < 0) return -1;

    hid_t ds_id = H5Dcreate2(parent_id, name, H5T_NATIVE_DOUBLE, space_id,
                             H5P_DEFAULT, H5P_DEFAULT, H5P_DEFAULT);
    if (ds_id < 0) {
        H5Sclose(space_id);
        return -1;
    }

    herr_t status = H5Dwrite(ds_id, H5T_NATIVE_DOUBLE, H5S_ALL, H5S_ALL, H5P_DEFAULT, data);
    if (status < 0) {
        H5Dclose(ds_id);
        H5Sclose(space_id);
        return -1;
    }

    H5Sclose(space_id);
    return ds_id;
}

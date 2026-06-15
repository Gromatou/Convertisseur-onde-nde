#!/usr/bin/env python3
"""Upgrade string-path references to real HDF5 references in an ONDE file."""
import sys, h5py, numpy as np

def upgrade_refs(input_path, output_path):
    import shutil, tempfile, os
    # Copy input to output
    shutil.copy2(input_path, output_path)
    
    f = h5py.File(output_path, 'r+')
    
    def upgrade_attr(obj, attr_name, val):
        """Replace a string path attribute with a real HDF5 reference."""
        if isinstance(val, np.ndarray):
            # Array of string paths
            refs = []
            for v in val.ravel():
                if isinstance(v, (str, bytes)):
                    path = v.decode() if isinstance(v, bytes) else v
                    if path.startswith('/'):
                        try:
                            refs.append(f[path].ref)
                        except:
                            refs.append(None)
                    else:
                        refs.append(None)
                else:
                    refs.append(None)
            if any(r is not None for r in refs):
                arr = np.array([r if r is not None else 0 for r in refs], dtype=h5py.ref_dtype)
                del obj.attrs[attr_name]
                obj.attrs[attr_name] = arr
                return True
        elif isinstance(val, (str, bytes)):
            path = val.decode() if isinstance(val, bytes) else val
            if path.startswith('/'):
                try:
                    target = f[path]
                    del obj.attrs[attr_name]
                    obj.attrs[attr_name] = target.ref
                    return True
                except:
                    pass
        return False
    
    upgraded = 0
    def visitor(name, obj):
        nonlocal upgraded
        if hasattr(obj, 'attrs'):
            for attr_name in list(obj.attrs.keys()):
                val = obj.attrs[attr_name]
                if upgrade_attr(obj, attr_name, val):
                    upgraded += 1
    
    f.visititems(visitor)
    f.close()
    print(f'  Upgraded {upgraded} references')
    return upgraded

if __name__ == '__main__':
    if len(sys.argv) != 3:
        print(f'Usage: {sys.argv[0]} <input.onde> <output.onde>')
        sys.exit(1)
    upgrade_refs(sys.argv[1], sys.argv[2])

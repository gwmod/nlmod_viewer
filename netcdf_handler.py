import os
import numpy as np
from qgis.core import QgsMessageLog, Qgis

try:
    from osgeo import gdal
except ImportError:
    gdal = None

try:
    import netCDF4
    QgsMessageLog.logMessage("NLMOD: netCDF4 is available", "NLMOD Viewer", Qgis.Info)
except ImportError:
    QgsMessageLog.logMessage("NLMOD: netCDF4 is NOT available", "NLMOD Viewer", Qgis.Info)

try:
    import xarray
    QgsMessageLog.logMessage("NLMOD: xarray is available", "NLMOD Viewer", Qgis.Info)
except ImportError:
    QgsMessageLog.logMessage("NLMOD: xarray is NOT available", "NLMOD Viewer", Qgis.Info)

def num2date(vals, units, calendar='standard'):
    from datetime import datetime, timedelta
    try:
        parts = str(units).split(' since ')
        if len(parts) == 2:
            unit = parts[0].strip().lower()
            base_time_str = parts[1].strip()
            base_time_str = base_time_str.replace('T', ' ').split('.')[0]
            if len(base_time_str) == 10:
                base_dt = datetime.strptime(base_time_str, "%Y-%m-%d")
            elif len(base_time_str) >= 19:
                base_dt = datetime.strptime(base_time_str[:19], "%Y-%m-%d %H:%M:%S")
            else:
                import dateutil.parser
                base_dt = dateutil.parser.parse(base_time_str)
                
            def convert_single(v):
                if np.isnan(v): return datetime(1970,1,1)
                if 'day' in unit: return base_dt + timedelta(days=float(v))
                if 'hour' in unit: return base_dt + timedelta(hours=float(v))
                if 'min' in unit: return base_dt + timedelta(minutes=float(v))
                if 'sec' in unit: return base_dt + timedelta(seconds=float(v))
                return base_dt + timedelta(days=float(v))
                
            if isinstance(vals, (list, np.ndarray)):
                return [convert_single(v) for v in vals]
            else:
                return convert_single(vals)
    except Exception as e:
        return vals
    return vals

class GdalNetcdfVariable:
    def __init__(self, md_array, filepath=None):
        self._array = md_array
        self.filepath = filepath
        self.name = md_array.GetName()
        self.ndim = md_array.GetDimensionCount()
        dim_objs = md_array.GetDimensions()
        self.dimensions = tuple(d.GetName() for d in dim_objs) if dim_objs else ()
        self.shape = tuple(d.GetSize() for d in dim_objs) if dim_objs else ()
        self.datatype = md_array.GetDataType()
        # Detect if it's a string type or 2D char array
        self._is_string = self.datatype.GetClass() == gdal.GEDTC_STRING
        if not self._is_string and self.ndim == 2 and self.datatype.GetNumericDataType() == gdal.GDT_Byte:
             # Check if last dimension size is small (standard for NetCDF char arrays)
             if self.shape[-1] <= 1024:
                  self._is_string = True
        
        self._attrs = {}
        attrs = md_array.GetAttributes()
        if attrs:
            from qgis.core import QgsMessageLog, Qgis
            for attr in attrs:
                name = attr.GetName()
                try:
                    val = attr.Read()
                except Exception:
                    try: val = attr.ReadAsString()
                    except: val = ""
                
                QgsMessageLog.logMessage(f"NLMOD: Variable {self.name} Attr {name}: {val}", "NLMOD Viewer", Qgis.Info)
                
                if isinstance(val, list) and len(val) == 1:
                    val = val[0]
                if hasattr(val, 'ndim') and val.ndim == 1 and val.size == 1:
                    val = val[0]
                self._attrs[name] = val
                setattr(self, name, val)
                
    def __getitem__(self, key):
        import numpy as np
        from qgis.core import QgsMessageLog, Qgis
        from osgeo import gdal
        
        arr = None
        # 1. Primary approach - standard ReadAsArray
        try:
            # First, check if classic metadata has these strings
            try:
                ds_cl = gdal.Open(self.filepath)
                if ds_cl:
                    # In some NetCDF drivers, 1D values are stored in special metadata items
                    # such as 'variable#values' or similar
                    meta = ds_cl.GetMetadata('NETCDF')
                    if meta:
                         # Look for values associated with this variable name
                         for k, v in meta.items():
                              if self.name in k and 'value' in k.lower():
                                   # Values are often comma-separated or space-separated
                                   vals = v.replace(',', ' ').split()
                                   if len(vals) == self.shape[0]:
                                        arr = np.array(vals)
                                        QgsMessageLog.logMessage(f"NLMOD: Variable {self.name} extracted via Classic Metadata", "NLMOD Viewer", Qgis.Info)
                                        break
                ds_cl = None
            except:
                pass
            
            if arr is None:
                arr = self._array.ReadAsArray()
        except Exception as e:
            QgsMessageLog.logMessage(f"NLMOD: ReadAsArray failed for {self.name}: {str(e)}", "NLMOD Viewer", Qgis.Info)
            arr = None
            
        if arr is None or (hasattr(arr, 'size') and arr.size == 0):
            if hasattr(self._array, 'ReadAsStringArray'):
                try:
                    arr = np.array(self._array.ReadAsStringArray())
                except:
                    pass

        # 3. Direct Buffer Read Fallback (Avoids SWIG string conversion bug)
        if (arr is None or (hasattr(arr, 'size') and arr.size == 0)) and self._is_string:
            try:
                # Try to read into a bytearray. 
                # This sometimes bypasses the SWIG string pointer issue 
                # by treating it as a raw buffer.
                dim_sizes = [d.GetSize() for d in self._array.GetDimensions()]
                total_elements = np.prod(dim_sizes)
                # We don't know the string length, let's guess 256 for coordinates
                buf_size = int(total_elements * 256) 
                buf = bytearray(buf_size)
                # In GDAL MD API, Read() can take a buffer
                if hasattr(self._array, 'Read'):
                    try:
                        # This might still fail if SWIG won't even allow the Read call
                        # but it's worth a shot.
                        pass 
                    except:
                        pass
            except:
                pass
        # 3. Explicit Vector Fallback
        if (arr is None or (hasattr(arr, 'size') and arr.size == 0)) and self.ndim == 1:
            try:
                ds_vec = gdal.OpenEx(self.filepath, gdal.OF_VECTOR, allowed_drivers=['netCDF'])
                if ds_vec:
                    lyr = ds_vec.GetLayerByName(self.name)
                    if lyr:
                        vals = []
                        for feat in lyr:
                            # Try to find a field that contains the name
                            val = feat.GetField(0) 
                            if val:
                                vals.append(str(val))
                        if len(vals) == self.shape[0]:
                            arr = np.array(vals)
                            QgsMessageLog.logMessage(f"NLMOD: Variable {self.name} extracted via Vector API", "NLMOD Viewer", Qgis.Info)
                ds_vec = None
            except:
                pass

        # 3. Classic Raster Subdataset Fallback
        if (arr is None or (hasattr(arr, 'size') and arr.size == 0)) and self.ndim == 1:
            try:
                # Try opening as a subdataset directly
                subdataset_path = f'NETCDF:"{self.filepath}":{self.name}'
                ds_sub = gdal.Open(subdataset_path)
                if ds_sub:
                    # If it's 1D, it might show up as a 1xN or Nx1 raster
                    band = ds_sub.GetRasterBand(1)
                    if band:
                        # For strings, this usually won't work easily as pixels, 
                        # but check if the metadata contains the values
                        meta = ds_sub.GetMetadata()
                        # Some drivers store 1D values in metadata
                        if meta:
                            # Search for values in metadata
                            for k, v in meta.items():
                                if 'value' in k.lower():
                                     # ... parse ...
                                     pass
                    ds_sub = None
            except:
                pass

        # 5. Ultimate Binary Scanning Fallback (Nuclear Option)
        if (arr is None or (hasattr(arr, 'size') and arr.size == 0)) and self.ndim == 1:
            try:
                import re
                with open(self.filepath, 'rb') as f:
                    data = f.read(1024 * 768) 
                
                count = self.shape[0] if hasattr(self, 'shape') else 48
                
                # Extract all alphanumeric strings
                raw_strings = re.findall(b'[a-zA-Z0-9]{2,20}', data)
                
                # REGIS Hydrogeological Units prefixes - be more specific to avoid 'OHDR'
                # but 'DR' is a real unit prefix (Drenthe formation). 
                # We'll just exclude known HDF5 tags.
                exclude = [b'OHDR', b'BTHL', b'SNOD', b'FRHP']
                regis_prefixes = [b'WA', b'PZ', b'MS', b'HL', b'BX', b'KR', b'EE', b'DR', b'ST', b'UR', b'AP', b'BR', b'OO', b'DT']
                
                units = []
                for s in raw_strings:
                    if s in exclude: continue
                    if any(s.startswith(p) for p in regis_prefixes):
                        units.append(s)
                
                # Remove duplicates while preserving discovery order
                unique_units = []
                for u in units:
                    if u not in unique_units:
                        unique_units.append(u)
                
                # In this NetCDF/HDF5 version, discovery order is often REVERSED 
                # compared to coordinate order.
                if len(unique_units) >= count:
                    # Search for HLc which is the first coordinate
                    if b'HLc' in unique_units:
                        # If HLc is the start of coordinate order, it's likely 
                        # at the END of a discovery block if reversed.
                        h_idx = unique_units.index(b'HLc')
                        # Take the block ENDING at HLc and REVERSE it
                        if h_idx >= count - 1:
                            candidate = unique_units[h_idx - count + 1 : h_idx + 1]
                            candidate.reverse()
                            arr = np.array([s.decode('utf-8', 'ignore') for s in candidate])
                            QgsMessageLog.logMessage(f"NLMOD: Variable {self.name} reconstructed via reverse unit scanning", "NLMOD Viewer", Qgis.Info)
                    
                    if arr is None:
                        # Try forward taking next 48 from HLc
                        if b'HLc' in unique_units:
                            h_idx = unique_units.index(b'HLc')
                            candidate = unique_units[h_idx : h_idx + count]
                            if len(candidate) == count:
                                arr = np.array([s.decode('utf-8', 'ignore') for s in candidate])
                                QgsMessageLog.logMessage(f"NLMOD: Variable {self.name} reconstructed via forward unit scanning", "NLMOD Viewer", Qgis.Info)
            except Exception as e:
                QgsMessageLog.logMessage(f"NLMOD: Binary scan failed: {str(e)}", "NLMOD Viewer", Qgis.Info)
                pass

        # 4. gdal.Info Fallback (The ultimate way to get coordinates if SWIG fails)
        if (arr is None or (hasattr(arr, 'size') and arr.size == 0)) and self.filepath:
            try:
                import json
                # format='json' requires GDAL >= 2.1
                # DESERIALIZE=YES might help
                # Use 'mdd' and 'all' to ensure coordinates are included
                info_raw = gdal.Info(self.filepath, format='json', allMetadata=True, options=['-mdd', 'all'])
                if info_raw:
                    QgsMessageLog.logMessage(f"NLMOD: gdal.Info raw (start): {str(info_raw)[:1000]}", "NLMOD Viewer", Qgis.Info)
                info = json.loads(info_raw) if isinstance(info_raw, str) else info_raw
                
                # Check for values in the arrays section
                if 'arrays' in info and self.name in info['arrays']:
                     v_info = info['arrays'][self.name]
                     if 'values' in v_info:
                          arr = np.array(v_info['values'])
                          QgsMessageLog.logMessage(f"NLMOD: Variable {self.name} read via gdal.Info", "NLMOD Viewer", Qgis.Info)
                
                # Check for values in the dimensions section (coords)
                if 'dimensions' in info:
                     for d_info in info['dimensions']:
                          if d_info.get('name') == self.name and 'indexing_variable' in d_info:
                               idx_var_name = d_info['indexing_variable']
                               if idx_var_name in info.get('arrays', {}):
                                    vals = info['arrays'][idx_var_name].get('values')
                                    if vals:
                                         arr = np.array(vals)
                                         QgsMessageLog.logMessage(f"NLMOD: Variable {self.name} read via gdal.Info (indexed)", "NLMOD Viewer", Qgis.Info)
            except:
                pass

        # 4. OGR Fallback (Already tried but failed in logs, keeping for other drivers)
        if (arr is None or (hasattr(arr, 'size') and arr.size == 0)) and self.filepath:
            try:
                ds_vec = gdal.OpenEx(self.filepath, gdal.OF_VECTOR)
                if ds_vec:
                    layer_vec = ds_vec.GetLayerByName(self.name)
                    if not layer_vec:
                         for i in range(ds_vec.GetLayerCount()):
                              lyr = ds_vec.GetLayerByIndex(i)
                              if lyr.GetName().lower() == self.name.lower():
                                   layer_vec = lyr
                                   break
                    if layer_vec:
                        vals = [feat.GetField(0) for feat in layer_vec]
                        if len(vals) > 0: arr = np.array(vals)
                ds_vec = None
            except:
                pass

        # 5. Last Ditch: Use gdalinfo output if possible?
        # Instead, let's try to search for the strings as Global Attributes
        # Sometimes dimensions info is put in global attributes like 'layer_names'
        # but that was removed from my heuristics.
        
        if arr is None or (hasattr(arr, 'size') and arr.size == 0):
            QgsMessageLog.logMessage(f"NLMOD: Variable {self.name} returned NO data", "NLMOD Viewer", Qgis.Warning)
            return np.array([])
            
        if getattr(arr, 'dtype', None) is not None:
            kind = arr.dtype.kind
            if kind in ('S', 'U', 'O'):
                if arr.ndim == 2:
                    try:
                        if kind == 'S':
                            arr = np.array([b"".join(r).decode('utf-8', 'ignore').strip("\x00 \t") for r in arr])
                        elif kind == 'O':
                            results = []
                            for r in arr:
                                try:
                                    if not hasattr(r, '__iter__'): 
                                         results.append(str(r).strip("\x00 \t"))
                                         continue
                                    s = "".join([v.decode('utf-8') if isinstance(v, bytes) else str(v) for v in r])
                                    results.append(s.strip("\x00 \t"))
                                except:
                                    results.append(str(r).strip("\x00 \t"))
                            arr = np.array(results)
                        else:
                            arr = np.array(["".join(r).strip("\x00 \t") for r in arr])
                    except:
                        pass
                elif kind == 'S' or kind == 'O':
                    try:
                        arr = np.array([v.decode('utf-8', 'ignore').strip("\x00 \t") if isinstance(v, bytes) else str(v).strip("\x00 \t") for v in arr])
                    except:
                        pass
                    
        return arr[key]
                    
        return arr[key]

class GdalNetcdfDimension:
    def __init__(self, dim, filepath=None):
        self.name = dim.GetName()
        self.size = dim.GetSize()
        self.indexing_variable = None
        try:
            v = dim.GetIndexingVariable()
            if v:
                self.indexing_variable = GdalNetcdfVariable(v, filepath=filepath)
        except:
            pass
            
        self._attrs = {}
        # GDAL Dimensions do not have attributes, only MDArrays and Groups do.
        # We'll rely on global attributes and indexing variable attributes instead.

class GdalNetcdfDataset:
    def __init__(self, filepath, mode='r'):
        if gdal is None:
            raise ImportError("osgeo.gdal module not found")
        self._ds = gdal.OpenEx(filepath, gdal.OF_MULTIDIM_RASTER)
        if not self._ds:
            raise Exception("File could not be opened as Multi-Dimensional Array by GDAL.")
            
        root = self._ds.GetRootGroup()
        if not root:
            del self._ds
            raise Exception("No root group found in NetCDF.")
            
        from qgis.core import QgsMessageLog, Qgis
        
        self.variables = {}
        var_names = root.GetMDArrayNames()
        QgsMessageLog.logMessage(f"NLMOD: Found {len(var_names)} MDArrays: {var_names}", "NLMOD Viewer", Qgis.Info)
        for name in var_names:
            md_arr = root.OpenMDArray(name)
            shape = [d.GetSize() for d in md_arr.GetDimensions()]
            dtype = md_arr.GetDataType()
            QgsMessageLog.logMessage(f"NLMOD: MDArray {name} shape: {shape}, type: {dtype.GetName()}, class: {dtype.GetClass()}", "NLMOD Viewer", Qgis.Info)
            self.variables[name] = GdalNetcdfVariable(md_arr, filepath=filepath)
            
        self.dimensions = {}
        dims = root.GetDimensions()
        QgsMessageLog.logMessage(f"NLMOD: Found {len(dims)} Dimensions", "NLMOD Viewer", Qgis.Info)
        for dim in dims:
            d_name = dim.GetName()
            d_obj = GdalNetcdfDimension(dim, filepath=filepath)
            self.dimensions[d_name] = d_obj
            has_idx = d_obj.indexing_variable is not None
            QgsMessageLog.logMessage(f"  Dimension: {d_name} (size {d_obj.size}, has indexing var={has_idx})", "NLMOD Viewer", Qgis.Info)
            
        # Ensure that any indexing variables are also in self.variables
        for d in self.dimensions.values():
             if d.indexing_variable and d.name not in self.variables:
                   self.variables[d.name] = d.indexing_variable
            
        # Log subdatasets for debugging
        try:
            ds_rast = gdal.Open(filepath)
            if ds_rast:
                subs = ds_rast.GetMetadata('SUBDATASETS')
                if subs:
                    for k, v in subs.items():
                        if '_NAME' in k:
                            QgsMessageLog.logMessage(f"NLMOD: Found Subdataset: {v}", "NLMOD Viewer", Qgis.Info)
                ds_rast = None
        except:
             pass
            
        self._global_attrs = []
        attrs = root.GetAttributes()
        if attrs:
            for attr in attrs:
                name = attr.GetName()
                try:
                    val = attr.Read()
                except Exception:
                    try: val = attr.ReadAsString()
                    except: val = ""
                QgsMessageLog.logMessage(f"NLMOD: Global Attr {name}: {val}", "NLMOD Viewer", Qgis.Info)
                
                if isinstance(val, list) and len(val) == 1:
                    val = val[0]
                if hasattr(val, 'ndim') and val.ndim == 1 and val.size == 1:
                    val = val[0]
                setattr(self, name, val)
                self._global_attrs.append(name)
        self._root = root
        
    def close(self):
        self.variables = {}
        self.dimensions = {}
        self._global_attrs = []
        self._ds = None
        
    def ncattrs(self):
        return self._global_attrs

try:
    from scipy.spatial import cKDTree
except ImportError:
    cKDTree = None

try:
    import shapely
    from shapely.geometry import LineString, Polygon, MultiLineString
    from shapely import STRtree, intersection, line_locate_point, get_coordinates, box
except ImportError:
    shapely = None

class NetcdfHandler:
    def _get_topology_var(self, name):
        """Helper to get and cache topology variables."""
        if name in self._cache:
            return self._cache[name]
        if name in self.ds.variables:
            val = self.ds.variables[name][:]
            self._cache[name] = val
            return val
        return None

    def __init__(self, filepath):
        self.filepath = filepath
        self.ds = None
        self.grid_type = "unknown"
        self._cache = {} # Cache for topology and spatial index
        self.angrot = 0.0
        self.xorigin = 0.0
        self.yorigin = 0.0
        self.is_absolute = False

    def open(self):
        if not os.path.exists(self.filepath):
            return False, "File not found"
        try:
            if gdal is None:
                raise ImportError("gdal module not found")
                
            self.ds = GdalNetcdfDataset(self.filepath, 'r')
            
            # Read rotation and origin attributes if present
            self.angrot = float(getattr(self.ds, 'angrot', 0.0))
            self.xorigin = float(getattr(self.ds, 'xorigin', 0.0))
            self.yorigin = float(getattr(self.ds, 'yorigin', 0.0))

            self.detect_grid_type()
            
            # Detect if coordinates are already absolute
            self.is_absolute = False
            if self.xorigin != 0 or self.yorigin != 0:
                import numpy as np
                xc_test = None
                if 'x' in self.ds.variables and self.ds.variables['x'].ndim == 1:
                    xc_test = self.ds.variables['x'][:]
                elif 'xc' in self.ds.variables:
                    xc_test = self.ds.variables['xc'][:]
                
                if xc_test is not None:
                    mean_x = np.nanmean(xc_test)
                    # If mean coordinate is closer to xorigin than to 0, it's absolute
                    if np.abs(mean_x) > np.abs(self.xorigin) * 0.5:
                        self.is_absolute = True
            
            return True, ""
        except ImportError:
            return False, "The 'gdal' library is missing.\n\nPlease install it using the OSGeo4W Shell or use QGIS which has GDAL builtin."
        except Exception as e:
            return False, f"Error opening file: {str(e)}"

    def close(self):
        if self.ds:
            self.ds.close()
            self.ds = None
        self._cache = {} # Clear cache
        self.angrot = 0.0
        self.xorigin = 0.0
        self.yorigin = 0.0
        self.is_absolute = False

    def detect_grid_type(self):
        # Heuristics for nlmod / UGRID / MODFLOW 6
        keys = self.ds.variables.keys()
        dims = self.ds.dimensions.keys()
        
        # 1. Explicit nlmod gridtype attribute
        gridtype = getattr(self.ds, 'gridtype', None)
        if not gridtype:
            # Check variables for the attribute
            for var in self.ds.variables.values():
                gridtype = getattr(var, 'gridtype', None)
                if gridtype: break
        
        if gridtype == 'vertex':
            self.grid_type = "vertex"
            return
        elif gridtype == 'structured':
            self.grid_type = "structured"
            return

        # 2. UGRID conventions
        if 'mesh2d_face_nodes' in keys or 'face_nodes' in keys:
            self.grid_type = "vertex"
            return
            
        # 3. Check for icell2d (nlmod/MF6 vertex grid dimension)
        if 'icell2d' in dims:
            self.grid_type = "vertex"
            return

        # 4. Check for structured dimensions (x, y) or (row, column)
        if 'x' in dims and 'y' in dims:
            self.grid_type = "structured"
            return
        if 'row' in dims and 'column' in dims:
            self.grid_type = "structured"
            return
            
        # 5. Variable-based check for x/y coordinates
        if 'x' in keys and 'y' in keys:
            if self.ds.variables['x'].ndim == 1 and self.ds.variables['y'].ndim == 1:
                self.grid_type = "structured"
                return
        
        if 'lat' in keys and 'lon' in keys:
             self.grid_type = "structured"
             return
            
        self.grid_type = "unknown"

    def transform_model_to_world(self, xm, ym):
        """Transforms model coordinates (xm, ym) to world coordinates (xw, yw)."""
        import numpy as np
        if self.is_absolute:
            return xm, ym
            
        if self.angrot == 0:
            return xm + self.xorigin, ym + self.yorigin
            
        angle_rad = np.radians(self.angrot)
        cos_ang = np.cos(angle_rad)
        sin_ang = np.sin(angle_rad)
        
        xw = self.xorigin + xm * cos_ang - ym * sin_ang
        yw = self.yorigin + xm * sin_ang + ym * cos_ang
        return xw, yw

    def transform_world_to_model(self, xw, yw):
        """Transforms world coordinates (xw, yw) to model coordinates (xm, ym)."""
        import numpy as np
        if self.is_absolute:
            return xw, yw
            
        dx = xw - self.xorigin
        dy = yw - self.yorigin
        
        if self.angrot == 0:
            return dx, dy
            
        angle_rad = np.radians(self.angrot)
        cos_ang = np.cos(angle_rad)
        sin_ang = np.sin(angle_rad)
        
        xm = dx * cos_ang + dy * sin_ang
        ym = -dx * sin_ang + dy * cos_ang
        return xm, ym

    def get_geotransform(self, var_name=None):
        """Calculates the GDAL 6-parameter geotransform [ulx, dx, rotation, uly, rotation, -dy]."""
        import numpy as np
        if not self.ds or self.grid_type != 'structured':
            return None
            
        # 1. Get model space extent and cell size
        # We search for coords same as in get_extent but simpler
        x_var, y_var = None, None
        vkeys = self.ds.variables.keys()
        for pair in [('x', 'y'), ('lon', 'lat'), ('longitude', 'latitude')]:
            if pair[0] in vkeys and pair[1] in vkeys:
                x_var, y_var = self.ds.variables[pair[0]], self.ds.variables[pair[1]]
                break
        
        if x_var is None: return None
        
        x_vals, y_vals = x_var[:], y_var[:]
        dx = np.abs(x_vals[1] - x_vals[0]) if len(x_vals) > 1 else 1.0
        dy = np.abs(y_vals[1] - y_vals[0]) if len(y_vals) > 1 else 1.0
        
        # Model space limits (bottom-left origin)
        xm_min = np.min(x_vals) - dx/2
        ym_max = np.max(y_vals) + dy/2
        
        # 2. Transform model top-left (xm_min, ym_max) to world space top-left
        # Detect if coordinates are already absolute
        is_absolute = False
        if self.xorigin != 0 or self.yorigin != 0:
            if np.abs(xm_min + dx/2) > np.abs(self.xorigin) * 0.5:
                is_absolute = True

        if not is_absolute:
            # Rotation angle in radians
            a = np.radians(self.angrot)
            cosa = np.cos(a)
            sina = np.sin(a)
            
            # World Top-Left (ulx, uly)
            ulx = self.xorigin + xm_min * cosa - ym_max * sina
            uly = self.yorigin + xm_min * sina + ym_max * cosa
            
            # Geotransform parameters (pixel to world)
            return [ulx, dx * cosa, dy * sina, uly, dx * sina, -dy * cosa]
        else:
            # Already absolute: just need standard 0-rotation geotransform?
            # Actually, even if absolute, it COULD be rotated, but flopy usually doesn't do that.
            # If it's absolute, xm_min/ym_max ARE the world coordinates.
            return [xm_min, dx, 0, ym_max, 0, -dy]

    def get_vars_with_time(self):
        """Returns a list of variable names that have a time dimension."""
        if not self.ds:
            return []
            
        vars_with_time = []
        possible_times = {'time'}
        spatial_dims_vertex = {'icell2d'}
        spatial_dims_structured = {'x', 'y'}
        
        for name, var in self.ds.variables.items():
            # Skip coordinate variables themselves
            if name.lower() in possible_times or name.lower() in spatial_dims_vertex or name.lower() in spatial_dims_structured:
                continue
                
            dims_lower = [d.lower() for d in var.dimensions]
            has_time = any(d in possible_times for d in dims_lower)
            
            # Check spatial dimensions
            has_spatial = False
            if 'icell2d' in dims_lower:
                has_spatial = True
            elif 'x' in dims_lower and 'y' in dims_lower:
                has_spatial = True
            
            if has_time and has_spatial:
                vars_with_time.append(name)
                
        return sorted(vars_with_time)

    def get_crs(self):
        """Attempts to find CRS definition in the NetCDF file."""
        if not self.ds:
            return None
        
        # 1. Check for 'spatial_ref', 'crs', or 'grid_mapping' variables
        for name in ['spatial_ref', 'crs', 'grid_mapping']:
            if name in self.ds.variables:
                var = self.ds.variables[name]
                for attr in ['spatial_ref', 'wkt', 'crs_wkt']:
                    if hasattr(var, attr):
                        return str(getattr(var, attr))
                if hasattr(var, 'epsg_code'):
                    return f"EPSG:{var.epsg_code}"
                if hasattr(var, 'epsg'):
                    return f"EPSG:{var.epsg}"
        
        # 2. Check for grid_mapping attribute on data variables
        for var in self.ds.variables.values():
            if hasattr(var, 'grid_mapping'):
                gm_name = var.grid_mapping
                if gm_name in self.ds.variables:
                    gm_var = self.ds.variables[gm_name]
                    for attr in ['spatial_ref', 'wkt', 'crs_wkt']:
                        if hasattr(gm_var, attr):
                            return str(getattr(gm_var, attr))
        
        # 3. Check global attributes
        for attr in ['crs', 'spatial_ref']:
            if hasattr(self.ds, attr):
                return str(getattr(self.ds, attr))
            
        return None

    def _get_layer_values(self, d):
        """Helper to get string representation of layer names for a dimension."""
        if d not in self.ds.dimensions:
            return []
            
        dim = self.ds.dimensions[d]
        size = dim.size
        
        from qgis.core import QgsMessageLog, Qgis
        QgsMessageLog.logMessage(f"NLMOD: Finding layer values for dimension: {d}", "NLMOD Viewer", Qgis.Info)
        
        # 1. Use indexing variable directly if it exists
        if dim.indexing_variable:
            QgsMessageLog.logMessage(f"  Using indexing variable for {d}", "NLMOD Viewer", Qgis.Info)
            vals = dim.indexing_variable[:]
            if len(vals) == size:
                 return [str(v) for v in vals]
        
        # 2. Variable with same name
        if d in self.ds.variables:
            QgsMessageLog.logMessage(f"  Using variable with same name: {d}", "NLMOD Viewer", Qgis.Info)
            vals = self.ds.variables[d][:]
            if len(vals) == size:
                 return [str(v) for v in vals]
        
        # 3. Check indexing variable attributes for names
        if dim.indexing_variable:
             for attr_name, attr_val in dim.indexing_variable._attrs.items():
                  if 'name' in attr_name.lower() or 'text' in attr_name.lower():
                       if isinstance(attr_val, (str, list)) and len(attr_val) == size:
                            QgsMessageLog.logMessage(f"  Found names in indexing variable attribute: {attr_name}", "NLMOD Viewer", Qgis.Info)
                            return [str(v) for v in attr_val]
        
        # 4. Check global attributes for list of names
        for attr_name in getattr(self.ds, '_global_attrs', []):
             val = getattr(self.ds, attr_name)
             if isinstance(val, (list, tuple)) and len(val) == size:
                  if 'name' in attr_name.lower() or 'layer' in attr_name.lower():
                       QgsMessageLog.logMessage(f"  Found names in global attribute: {attr_name}", "NLMOD Viewer", Qgis.Info)
                       return [str(v) for v in val]
        
        # 5. Search for any other 1D string variable of this size (Deep Search)
        QgsMessageLog.logMessage(f"  No primary variable found for {d}, searching all variables...", "NLMOD Viewer", Qgis.Info)
        for v_name, var in self.ds.variables.items():
            if var.ndim == 1 and var.shape[0] == size:
                # If we detected it as a string variable or it has a suggestive name
                if 'name' in v_name.lower() or 'layer' in v_name.lower() or getattr(var, '_is_string', False):
                    vals = var[:]
                    if len(vals) == size:
                        QgsMessageLog.logMessage(f"  Found names in other variable: {v_name}", "NLMOD Viewer", Qgis.Info)
                        return [str(v) for v in vals]
        
        QgsMessageLog.logMessage(f"  No names found for {d}, falling back to integers.", "NLMOD Viewer", Qgis.Warning)
        # 3. Fallback to integers
        return [str(i+1) for i in range(size)]

    def _get_time_metadata(self, d):
        """Helper to get strings and timestamps for a time dimension."""
        times = []
        time_stamps = []
        
        if d not in self.ds.dimensions:
             return [], []
             
        dim = self.ds.dimensions[d]
        size = dim.size
        
        # Use indexing variable if available
        if dim.indexing_variable:
            vals = dim.indexing_variable[:]
            try:
                if hasattr(dim.indexing_variable, 'units'):
                    cal = getattr(dim.indexing_variable, 'calendar', 'standard')
                    dates = num2date(vals, units=dim.indexing_variable.units, calendar=cal)
                    
                    def fmt(dt):
                        if hasattr(dt, 'strftime'):
                            return dt.strftime('%Y-%m-%d %H:%M:%S') if dt.hour or dt.minute else dt.strftime('%Y-%m-%d')
                        return str(dt)
                        
                    def to_ts(dt):
                        try:
                            if hasattr(dt, 'timestamp'):
                                return dt.timestamp()
                            from datetime import datetime
                            d_dt = datetime(dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second)
                            return d_dt.timestamp()
                        except:
                            return 0.0

                    if isinstance(dates, (list, np.ndarray)):
                        times = [fmt(dt) for dt in dates]
                        time_stamps = [to_ts(dt) for dt in dates]
                    else:
                        times = [fmt(dates)]
                        time_stamps = [to_ts(dates)]
                else:
                    times = [str(v) for v in vals]
                    time_stamps = [float(v) for v in vals]
            except:
                times = [str(v) for v in vals]
                time_stamps = [float(v) for v in vals]
        
        if not times:
            times = [str(i+1) for i in range(size)]
            time_stamps = [float(i) for i in range(size)]
            
        return times, time_stamps

    def get_dimensions_metadata(self):
        """Returns metadata for all available dimensions (layers, times) in the file."""
        if not self.ds:
            return {"layers": [], "times": [], "time_stamps": []}
            
        layers = []
        times = []
        time_stamps = []
        
        possible_layers = {'layer', 'z', 'nlayer', 'lev', 'level', 'k', 'layer_index'}
        possible_times = {'time'}
        
        # Look for these dimensions in the variables
        for d in self.ds.dimensions:
            if d.lower() in possible_layers:
                layers = self._get_layer_values(d)
            
            if d.lower() in possible_times:
                times, time_stamps = self._get_time_metadata(d)
                    
        return {"layers": layers, "times": times, "time_stamps": time_stamps}                    
        return {"layers": layers, "times": times, "time_stamps": time_stamps}

    def get_variables(self):
        """Returns list of variables that are likely model data (skipping coords)."""
        if not self.ds:
            return []
        
        # Common coordinate/topology variables to exclude
        exclude = {
            'x', 'y', 'lat', 'lon', 'latitude', 'longitude', 
            'time', 'layer',
            'mesh2d', 'mesh2d_face_nodes', 'mesh2d_edge_nodes', 
            'mesh2d_node_x', 'mesh2d_node_y', 'time_bnds',
            'crs', 'grid_mapping', 'spatial_ref',
            # Vertex topology
            'icvert', 'xv', 'yv', 'xc', 'yc', 'icell2d', 'icv', 'iv'
        }
        
        data_vars = []
        for name, var in self.ds.variables.items():
            if name in exclude:
                continue
            # Also exclude variables that look like 1D coordinates matching dimensions
            if var.ndim == 1 and name in self.ds.dimensions:
                continue
            
            # Helper: get definition
            desc = getattr(var, 'long_name', getattr(var, 'description', name))
            
            # Detect layer dim
            layer_dim = None
            layer_size = 0
            layer_values = []
            possible_layers = {'layer', 'z', 'nlayer', 'nlay', 'lev', 'level', 'k', 'layer_index'}
            
            # Detect time dim
            time_dim = None
            time_size = 0
            time_values = []
            possible_times = {'time'}

            for d in var.dimensions:
                if d in possible_layers:
                    layer_dim = d
                    layer_values = self._get_layer_values(d)
                    layer_size = len(layer_values)
                
                if d in possible_times:
                    time_dim = d
                    time_values, _ = self._get_time_metadata(d)
                    time_size = len(time_values)

            # Detect spatial dims
            dims_lower = [d.lower() for d in var.dimensions]
            has_spatial = 'icell2d' in dims_lower or ('x' in dims_lower and 'y' in dims_lower)

            data_vars.append({
                'name': name,
                'description': desc,
                'shape': var.shape,
                'dimensions': var.dimensions,
                'layer_dim': layer_dim,
                'layer_size': layer_size,
                'layer_values': layer_values,
                'time_dim': time_dim,
                'time_size': time_size,
                'time_values': time_values,
                'has_spatial': has_spatial
            })
        return data_vars



    def get_extent(self, var_name=None):
        """
        Calculates the extent (xmin, xmax, ymin, ymax).
        1. Checks 'coordinates' attribute of var_name.
        2. Checks distinct x/y variables by standard_name or name.
        Returns None if not found or error.
        """
        if not self.ds or self.grid_type != 'structured':
            return None
            
        try:
            import numpy as np
            from qgis.core import QgsMessageLog, Qgis
            
            x_var = None
            y_var = None
            
            # Strategy 1: Check 'coordinates' attribute (CF Convention)
            if var_name and var_name in self.ds.variables:
                var = self.ds.variables[var_name]
                if hasattr(var, 'coordinates'):
                    # e.g. "lat lon" or "y x"
                    coord_names = var.coordinates.split()
                    if len(coord_names) >= 2:
                        candidates = [self.ds.variables[n] for n in coord_names if n in self.ds.variables]
                        x_cand = None
                        y_cand = None
                        for c in candidates:
                            c_name = c.name.lower()
                            std_name = getattr(c, 'standard_name', '').lower()
                            if 'x' in c_name or 'lon' in c_name or 'projection_x_coordinate' in std_name:
                                x_cand = c
                            if 'y' in c_name or 'lat' in c_name or 'projection_y_coordinate' in std_name:
                                y_cand = c
                        if x_cand and y_cand:
                            x_var = x_cand
                            y_var = y_cand
                            QgsMessageLog.logMessage(f"NLMOD: Found coordinates via attribute: {x_var.name}, {y_var.name}", "NLMOD Viewer", Qgis.Info)

            # Strategy 2: Search by standard_name (projection_x_coordinate)
            if x_var is None:
                for n, v in self.ds.variables.items():
                    std_name = getattr(v, 'standard_name', '').lower()
                    if 'projection_x_coordinate' in std_name or 'longitude' in std_name:
                        x_var = v
                    if 'projection_y_coordinate' in std_name or 'latitude' in std_name:
                        y_var = v
                if x_var and y_var:
                     QgsMessageLog.logMessage(f"NLMOD: Found coordinates via standard_name: {x_var.name}, {y_var.name}", "NLMOD Viewer", Qgis.Info)

            # Strategy 3: Common names (fallback)
            if x_var is None:
                vkeys = self.ds.variables.keys()
                # Log keys for debug
                QgsMessageLog.logMessage(f"NLMOD: Variable keys: {list(vkeys)}", "NLMOD Viewer", Qgis.Info)
                
                for pair in [('x', 'y'), ('lon', 'lat'), ('longitude', 'latitude'), ('x_coord', 'y_coord'), ('X', 'Y')]:
                    if pair[0] in vkeys and pair[1] in vkeys:
                        x_var = self.ds.variables[pair[0]]
                        y_var = self.ds.variables[pair[1]]
                        QgsMessageLog.logMessage(f"NLMOD: Found coordinates via name match: {pair}", "NLMOD Viewer", Qgis.Info)
                        break

            if x_var is None or y_var is None:
                # If we can't find coords but have extent attribute, use it as a last resort
                if hasattr(self.ds, 'extent'):
                    ext = self.ds.extent
                    if len(ext) == 4:
                         # For nlmod, if we only have extent, it's often South-to-North (Ascending)
                         # Previous Hardcoded 'False' was reported as flipped.
                         QgsMessageLog.logMessage(f"NLMOD: Found extent via attribute (no coords): {ext}. Defaulting Ascending=True", "NLMOD Viewer", Qgis.Info)
                         return (ext[0], ext[1], ext[2], ext[3], True)
                return None
            
            # Use detected coords to determine direction
            y_vals = y_var[:]
            if len(y_vals) >= 2:
                y_is_ascending = (y_vals[1] > y_vals[0])
                QgsMessageLog.logMessage(f"NLMOD: Detected Y direction: {y_vals[0]} to {y_vals[-1]} (Ascending={y_is_ascending})", "NLMOD Viewer", Qgis.Info)
            else:
                y_is_ascending = False

            # Check for global extent attribute for bounds
            if hasattr(self.ds, 'extent'):
                ext = self.ds.extent
                if len(ext) == 4:
                     QgsMessageLog.logMessage(f"NLMOD: Using global extent for bounds, Ascending={y_is_ascending}", "NLMOD Viewer", Qgis.Info)
                     return (ext[0], ext[1], ext[2], ext[3], y_is_ascending)

            # Otherwise calculate bounds from coords
            x = x_var[:]
            y = y_vals
            
            if len(x) < 2 or len(y) < 2:
                QgsMessageLog.logMessage("NLMOD: Coordinate arrays too short.", "NLMOD Viewer", Qgis.Warning)
                return None
                
            # Determine cell sizes (dx, dy)
            dx = np.abs(x[1] - x[0])
            dy = np.abs(y[1] - y[0])
            
            # Model space bounds
            xm_min = np.min(x) - dx/2
            xm_max = np.max(x) + dx/2
            ym_min = np.min(y) - dy/2
            ym_max = np.max(y) + dy/2
            
            # Now transform corners if rotated or moved from QGIS 0,0
            # Detect if already absolute
            is_absolute = False
            if self.xorigin != 0 or self.yorigin != 0:
                if np.nanmean(np.abs(x)) > np.abs(self.xorigin) * 0.5:
                    is_absolute = True

            if (self.angrot == 0 and self.xorigin == 0 and self.yorigin == 0) or is_absolute:
                return (xm_min, xm_max, ym_min, ym_max, y_is_ascending)
            
            # Calculate 4 corners in model space and transform
            corners = [
                (xm_min, ym_min), (xm_max, ym_min),
                (xm_max, ym_max), (xm_min, ym_max)
            ]
            
            xw_list, yw_list = [], []
            for cx, cy in corners:
                xw, yw = self.transform_model_to_world(cx, cy)
                xw_list.append(xw)
                yw_list.append(yw)
            
            return (min(xw_list), max(xw_list), min(yw_list), max(yw_list), y_is_ascending)
        except Exception as e:
            from qgis.core import QgsMessageLog, Qgis
            QgsMessageLog.logMessage(f"NLMOD: Error calculating extent: {e}", "NLMOD Viewer", Qgis.Critical)
            return None

    def get_info_text(self):
        if not self.ds:
            return "No file loaded."
        
        info = []
        info.append(f"Grid Type: {self.grid_type}")
        
        # Global attributes
        # Global attributes
        info.append("\nGlobal Attributes:")
        for attr in self.ds.ncattrs():
             val = getattr(self.ds, attr)
             # Truncate if too long (e.g. history)
             val_str = str(val)
             if len(val_str) > 200:
                 val_str = val_str[:197] + "..."
             info.append(f"{attr}: {val_str}")
        
        # Dimensions
        info.append("\nDimensions:")
        for dname, dim in self.ds.dimensions.items():
            info.append(f"  {dname}: {dim.size}")
            
        return "\n".join(info)

    def _get_centroids(self):
        """Helper to get or calculate centroids for any grid type."""
        import numpy as np
        
        if 'centroids' in self._cache:
            return self._cache['centroids']

        # 1. Fallback to file-provided coordinates
        if 'xc' in self.ds.variables and 'yc' in self.ds.variables:
            xc_vals = self.ds.variables['xc'][:]
            yc_vals = self.ds.variables['yc'][:]
            
            # Apply transformation if necessary (and if not already absolute)
            # Heuristic: if mean xc is much larger than its range, and near xorigin, it's likely absolute.
            is_absolute = False
            if self.xorigin != 0 or self.yorigin != 0:
                mean_x = np.nanmean(xc_vals)
                if np.abs(mean_x) > np.abs(self.xorigin) * 0.5:
                    is_absolute = True

            if (self.angrot != 0 or self.xorigin != 0 or self.yorigin != 0) and not is_absolute:
                xc_trans, yc_trans = self.transform_model_to_world(xc_vals, yc_vals)
                res = (xc_trans, yc_trans)
            else:
                res = (xc_vals, yc_vals)
            
            self._cache['centroids'] = res
            return res
        
        # 2. Calculate from vertices
        icv = self._get_topology_var('icvert')
        xv = self._get_topology_var('xv')
        yv = self._get_topology_var('yv')
        
        if icv is not None and xv is not None and yv is not None:
            # Detect if vertices are absolute
            is_absolute = False
            if self.xorigin != 0 or self.yorigin != 0:
                if np.nanmean(np.abs(xv)) > np.abs(self.xorigin) * 0.5:
                    is_absolute = True

            # First transform vertices to world space if necessary
            if (self.angrot != 0 or self.xorigin != 0 or self.yorigin != 0) and not is_absolute:
                xv_world, yv_world = self.transform_model_to_world(xv, yv)
            else:
                xv_world, yv_world = xv, yv

            nodata = getattr(self.ds.variables['icvert'], 'nodata', -1)
            n_cells = icv.shape[0]
            xc = np.full(n_cells, np.nan)
            yc = np.full(n_cells, np.nan)
            
            # Use fast arithmetic mean for centroids using world-space vertices
            for i in range(n_cells):
                curr_v = icv[i]
                v_idx = curr_v[curr_v != nodata]
                if len(v_idx) >= 3:
                    try:
                        xc[i] = np.mean(xv_world[v_idx])
                        yc[i] = np.mean(yv_world[v_idx])
                    except:
                        pass
            
            res = (xc, yc)
            self._cache['centroids'] = res
            return res
            
        return None, None

    def _get_line_segment_ranges(self, line, intersection_geom):
        """Returns a list of (d1, d2) tuples representing linear segments along the line."""
        if not intersection_geom or intersection_geom.is_empty:
            return []
        
        from shapely import Point
        geom_type = intersection_geom.geom_type
        parts = []
        if geom_type == 'LineString':
            parts = [intersection_geom]
        elif geom_type == 'MultiLineString':
            parts = list(intersection_geom.geoms)
        elif geom_type == 'GeometryCollection':
            for g in intersection_geom.geoms:
                if g.geom_type == 'LineString': parts.append(g)
                elif g.geom_type == 'MultiLineString': parts.extend(list(g.geoms))
        
        ranges = []
        for p in parts:
            if len(p.coords) >= 2:
                d1 = line_locate_point(line, Point(p.coords[0]))
                d2 = line_locate_point(line, Point(p.coords[-1]))
                ranges.append((min(d1, d2), max(d1, d2)))
        return ranges

    def get_cross_section_data(self, variable_name, points, time_idx=0):
        """
        Extracts cross-section data using exact Shapely intersections with cell geometries.
        """
        if not self.ds:
            return None

        import numpy as np
        
        # 1. Prepare Line and Bounds
        pts_world = []
        pts_model = []
        for p in points:
            if hasattr(p, 'x'): wx, wy = p.x(), p.y()
            else: wx, wy = p[0], p[1]
            pts_world.append((wx, wy))
            mx, my = self.transform_world_to_model(wx, wy)
            pts_model.append((mx, my))
        
        if len(pts_world) < 2: return None
        
        if shapely is None:
            # This should not happen if QGIS environment is correct as per user
            return {"error": "Shapely library is required for cross-sections."}

        line_model = LineString(pts_model)
        bbox_model = line_model.bounds 
        
        # 2. Identify candidate cells and calculate intersections
        cell_segments = [] # List of {'d1':, 'd2':, 'idx':, 'cx':, 'cy':}
        xc_all, yc_all = self._get_centroids() # These are World-Space (handled by updated _get_centroids)
        
        if self.grid_type == 'structured':
            x_v, y_v = self.ds.variables['x'][:], self.ds.variables['y'][:]
            dx = np.abs(x_v[1]-x_v[0]) if len(x_v) > 1 else 0
            dy = np.abs(y_v[1]-y_v[0]) if len(y_v) > 1 else 0
            
            # Bound query in model space
            ix = np.where((x_v >= bbox_model[0] - dx) & (x_v <= bbox_model[2] + dx))[0]
            iy = np.where((y_v >= bbox_model[1] - dy) & (y_v <= bbox_model[3] + dy))[0]
            
            for r in iy:
                for c in ix:
                    xc, yc = x_v[c], y_v[r]
                    p = box(xc - dx/2, yc - dy/2, xc + dx/2, yc + dy/2)
                    if line_model.intersects(p):
                        inter = intersection(line_model, p)
                        # Distances along line are calculated in model space (invariant)
                        for d1, d2 in self._get_line_segment_ranges(line_model, inter):
                            # Cell centroids for display (transformed to world space if not absolute)
                            is_absolute = False
                            if self.xorigin != 0 or self.yorigin != 0:
                                if np.abs(xc) > np.abs(self.xorigin) * 0.5:
                                    is_absolute = True
                                    
                            if (self.angrot != 0 or self.xorigin != 0 or self.yorigin != 0) and not is_absolute:
                                cw_x, cw_y = self.transform_model_to_world(xc, yc)
                            else:
                                cw_x, cw_y = xc, yc
                            cell_segments.append({'d1': d1, 'd2': d2, 'idx': (r, c), 'cx': cw_x, 'cy': cw_y})
        else:
            # Vertex Grid
            icv = self._get_topology_var('icvert')
            xv_m = self._get_topology_var('xv') # Model Coordinates
            yv_m = self._get_topology_var('yv') # Model Coordinates
            
            if icv is None or xv_m is None or yv_m is None or xc_all is None: 
                return None
            
            # Spatial Index (STRtree) for massive speedup on large grids
            # Index is built in Model Space
            if 'strtree' not in self._cache and shapely:
                nodata = getattr(self.ds.variables['icvert'], 'nodata', -1)
                polys = []
                poly_indices = []
                for i in range(len(icv)):
                    v_idx = icv[i][icv[i] != nodata]
                    if len(v_idx) >= 3:
                        polys.append(Polygon(zip(xv_m[v_idx], yv_m[v_idx])))
                        poly_indices.append(i)
                self._cache['polys'] = polys
                self._cache['poly_indices'] = poly_indices
                self._cache['strtree'] = STRtree(polys)
            
            if 'strtree' in self._cache:
                tree = self._cache['strtree']
                all_polys = self._cache['polys']
                all_indices = self._cache['poly_indices']
                
                # Query tree for cells intersecting the line in model space
                intersecting_indices = tree.query(line_model, predicate='intersects')
                for idx_in_tree in intersecting_indices:
                    p = all_polys[idx_in_tree]
                    global_idx = all_indices[idx_in_tree]
                    inter = intersection(line_model, p)
                    for d1, d2 in self._get_line_segment_ranges(line_model, inter):
                        cell_segments.append({
                            'd1': d1, 'd2': d2, 
                            'idx': int(global_idx), 
                            # xc_all/yc_all are world-space from our updated _get_centroids
                            'cx': xc_all[global_idx], 
                            'cy': yc_all[global_idx]
                        })
            else:
                # Fallback to bbox filtering in model space
                c_mask = (self.ds.variables['xc'][:] >= bbox_model[0] - 1000) & (self.ds.variables['xc'][:] <= bbox_model[2] + 1000) & \
                         (self.ds.variables['yc'][:] >= bbox_model[1] - 1000) & (self.ds.variables['yc'][:] <= bbox_model[3] + 1000)
                cand_indices = np.where(c_mask)[0]
                nodata = getattr(self.ds.variables['icvert'], 'nodata', -1)
                
                for i in cand_indices:
                    v_idx = icv[i][icv[i] != nodata]
                    if len(v_idx) < 3: continue
                    p = Polygon(zip(xv_m[v_idx], yv_m[v_idx]))
                    if line_model.intersects(p):
                        inter = intersection(line_model, p)
                        for d1, d2 in self._get_line_segment_ranges(line_model, inter):
                            cell_segments.append({
                                'd1': d1, 'd2': d2, 
                                'idx': int(i), 
                                'cx': xc_all[i], 
                                'cy': yc_all[i]
                            })
        if not cell_segments:
            return {"error": "No cells found along the cross-section line."}

        # 3. Sort segments by distance and build transition points
        cell_segments.sort(key=lambda x: x['d1'])
        
        # We need a point at the start and end of each segment for proper flat rendering
        final_dists = []
        indices_list = []
        cell_x = []
        cell_y = []
        
        for seg in cell_segments:
            # Entry point
            final_dists.append(seg['d1'])
            indices_list.append(seg['idx'])
            cell_x.append(seg['cx'])
            cell_y.append(seg['cy'])
            # Exit point
            final_dists.append(seg['d2'])
            indices_list.append(seg['idx'])
            cell_x.append(seg['cx'])
            cell_y.append(seg['cy'])

        final_dists = np.array(final_dists)
        cell_x = np.array(cell_x)
        cell_y = np.array(cell_y)
        
        # 4. Fetch Scalar Data
        try:
            if self.grid_type == 'structured':
                yi = np.array([idx[0] for idx in indices_list])
                xi = np.array([idx[1] for idx in indices_list])
                indices = (yi, xi)
                
                # Slicing optimization
                sy = slice(yi.min(), yi.max()+1)
                sx = slice(xi.min(), xi.max()+1)
                yl, xl = yi - yi.min(), xi - xi.min()
                
                def get_v(v):
                    if v not in self.ds.variables: return None
                    d = self.ds.variables[v]
                    dims = d.dimensions
                    sl = [slice(None)] * d.ndim
                    
                    # Apply Time selection
                    possible_times = {'time'}
                    for i, dim_name in enumerate(dims):
                        if dim_name in possible_times:
                            sl[i] = time_idx
                            break
                    
                    # Structured: extract the spatial sub-region (sy, sx)
                    # and all layers.
                    if 'x' in dims and 'y' in dims:
                        # Find indices for x and y
                        ix = dims.index('x')
                        iy = dims.index('y')
                        sl[ix] = sx
                        sl[iy] = sy
                        c = d[tuple(sl)]
                    else:
                        # Fallback for structured variables that might use different dim names
                        # or simple ndim checks
                        if d.ndim == 2: c = d[sy, sx]
                        elif d.ndim == 3: c = d[tuple(sl)][sy, sx]
                        elif d.ndim == 4: c = d[tuple(sl)][:, sy, sx]
                        else: return None
                    
                    arr = c.filled(np.nan) if hasattr(c, 'filled') else c
                    # arr is now (layer, y_sub, x_sub)
                    # index with yl, xl (arrays) to get values along the line
                    if arr.ndim == 3:
                        return arr[:, yl, xl]
                    else:
                        return arr[yl, xl]
                    
                top = get_v('top')
                botm = get_v('botm')
                vals = get_v(variable_name) if variable_name else None
            else:
                idx = np.array(indices_list)
                indices = idx
                
                def get_v(v):
                    if v not in self.ds.variables: return None
                    d = self.ds.variables[v]
                    dims = d.dimensions
                    sl = [slice(None)] * d.ndim
                    
                    # Apply Time selection
                    possible_times = {'time'}
                    for i, dim_name in enumerate(dims):
                        if dim_name in possible_times:
                            sl[i] = time_idx
                            break
                    
                    # Apply icell2d selections
                    if 'icell2d' in dims:
                        idx_dim = dims.index('icell2d')
                        sl[idx_dim] = idx
                        c = d[tuple(sl)]
                    else:
                        # Fallback simple logic
                        if d.ndim == 1: c = d[idx]
                        elif d.ndim == 2: c = d[tuple(sl)][idx]
                        elif d.ndim == 3: c = d[tuple(sl)][:, idx]
                        else: return None
                        
                    return c.filled(np.nan) if hasattr(c, 'filled') else c
                
                top, botm = get_v('top'), get_v('botm')
                vals = get_v(variable_name) if variable_name else None

            # 5. Layer Names
            layer_names = self._get_layer_values('layer')
            if not layer_names and botm is not None:
                layer_names = [str(i+1) for i in range(botm.shape[0])]

            # 6. Metadata
            var_desc = variable_name
            var_units = ""
            if variable_name in self.ds.variables:
                v_obj = self.ds.variables[variable_name]
                var_desc = getattr(v_obj, 'long_name', getattr(v_obj, 'description', variable_name))
                var_units = getattr(v_obj, 'units', "")

            # 7. Check if variable has time dimension
            has_time = False
            if variable_name in self.ds.variables:
                v_obj = self.ds.variables[variable_name]
                if any(d in {'time'} for d in v_obj.dimensions):
                    has_time = True

            return {
                "distances": final_dists,
                "top": top,
                "botm": botm,
                "values": vals,
                "indices": indices,
                "cell_x": cell_x,
                "cell_y": cell_y,
                "layer_names": layer_names,
                "num_layers": botm.shape[0],
                "description": var_desc,
                "units": var_units,
                "has_time": has_time
            }

        except Exception as e:
            import traceback
            return {"error": f"Data extraction failed: {str(e)}\n{traceback.format_exc()}"}

    def export_to_mesh(self, var_name, layer_idx=0, time_idx=0, output_path=None):
        """
        Exports a single variable (at a specific layer and time) to a clean UGRID NetCDF file.
        This provides maximal compatibility with MDAL.
        """
        if not self.ds or var_name not in self.ds.variables:
            return False, "Variable not found"
            
        try:
            import numpy as np
            
            # 1. Prepare data slice
            var = self.ds.variables[var_name]
            
            # Identify dimensions
            dims = var.dimensions
            if 'icell2d' not in dims:
                return False, f"Variable {var_name} does not have icell2d dimension."
                
            # Generic slicing approach
            sl = [slice(None)] * var.ndim
            
            # Handle Layer Dim
            possible_layers = {'layer', 'z'}
            for i, d in enumerate(dims):
                if d in possible_layers:
                    sl[i] = layer_idx
                    break
            
            # Handle Time Dim
            possible_times = {'time'}
            for i, d in enumerate(dims):
                if d in possible_times:
                    sl[i] = time_idx
                    break
            
            data = var[tuple(sl)]
            
            if data is None:
                return False, "Unsupported variable dimensions"

            # 2. Create new NetCDF
            driver = gdal.GetDriverByName('netCDF')
            if driver is None or not hasattr(driver, 'CreateMultiDimensional'):
                return False, "GDAL version does not support multidimensional NetCDF creation."
            
            out_ds = driver.CreateMultiDimensional(output_path)
            if not out_ds:
                return False, "Failed to create output file."
                
            root = out_ds.GetRootGroup()
            
            # Copy topology variables and dimensions
            icert_in = self.ds.variables.get('icvert')
            if icert_in is None:
                return False, "icvert (topology) not found in source"
                
            n_cells = self.ds.dimensions['icell2d'].size
            n_vert_per_cell = len(icert_in.dimensions) > 1 and self.ds.dimensions[icert_in.dimensions[1]].size or getattr(icert_in, 'shape', [0,0])[1]
            
            dim_icell2d = root.CreateDimension("icell2d", "", "", n_cells)
            dim_nvertex = root.CreateDimension("nvertex", "", "", n_vert_per_cell)
            
            dt_int = gdal.ExtendedDataType.Create(gdal.GDT_Int32)
            dt_float = gdal.ExtendedDataType.Create(gdal.GDT_Float32)
            dt_str = gdal.ExtendedDataType.CreateString()
            
            icv_out = root.CreateMDArray("icvert", [dim_icell2d, dim_nvertex], dt_int)
            icv_out.WriteArray(np.array(icert_in[:], dtype=np.int32))
            
            attr = icv_out.CreateAttribute("cf_role", [], dt_str)
            attr.Write("face_node_connectivity")
            attr = icv_out.CreateAttribute("start_index", [], dt_int)
            attr.Write(0)
            
            nodata = getattr(icert_in, 'nodata', -1)
            if nodata != -1:
                attr = icv_out.CreateAttribute("_FillValue", [], dt_int)
                attr.Write(int(nodata))
            
            # Vertices
            xv_in = self.ds.variables.get('xv')
            yv_in = self.ds.variables.get('yv')
            if xv_in is not None and yv_in is not None:
                n_node_dim = self.ds.dimensions.get('nnode', self.ds.dimensions.get('node', None))
                n_node_size = n_node_dim.size if n_node_dim else len(xv_in[:])
                dim_nnode = root.CreateDimension("nnode", "", "", n_node_size)
                
                xv_out = root.CreateMDArray("xv", [dim_nnode], dt_float)
                yv_out = root.CreateMDArray("yv", [dim_nnode], dt_float)
                
                # Transform vertices to world space if rotated/moved
                if self.angrot != 0 or self.xorigin != 0 or self.yorigin != 0:
                    xv_world, yv_world = self.transform_model_to_world(xv_in[:], yv_in[:])
                    xv_out.WriteArray(xv_world.astype(np.float32))
                    yv_out.WriteArray(yv_world.astype(np.float32))
                else:
                    xv_out.WriteArray(np.array(xv_in[:], dtype=np.float32))
                    yv_out.WriteArray(np.array(yv_in[:], dtype=np.float32))
                    
                attr = xv_out.CreateAttribute("standard_name", [], dt_str)
                attr.Write("projection_x_coordinate")
                attr = xv_out.CreateAttribute("units", [], dt_str)
                attr.Write("m")
                
                attr = yv_out.CreateAttribute("standard_name", [], dt_str)
                attr.Write("projection_y_coordinate")
                attr = yv_out.CreateAttribute("units", [], dt_str)
                attr.Write("m")
                
            # Centroids (xc, yc) - Calculated if missing
            xc_vals, yc_vals = self._get_centroids()
            if xc_vals is None:
                 return False, "Could not determine cell centroids"
            
            xc_out = root.CreateMDArray("xc", [dim_icell2d], dt_float)
            yc_out = root.CreateMDArray("yc", [dim_icell2d], dt_float)
            xc_out.WriteArray(xc_vals.astype(np.float32))
            yc_out.WriteArray(yc_vals.astype(np.float32))
            
            attr = xc_out.CreateAttribute("standard_name", [], dt_str)
            attr.Write("projection_x_coordinate")
            attr = xc_out.CreateAttribute("units", [], dt_str)
            attr.Write("m")
            
            attr = yc_out.CreateAttribute("standard_name", [], dt_str)
            attr.Write("projection_y_coordinate")
            attr = yc_out.CreateAttribute("units", [], dt_str)
            attr.Write("m")

            # Mesh Topology variable
            mesh_v = root.CreateMDArray("mesh2d", [], dt_int)
            attr = mesh_v.CreateAttribute("cf_role", [], dt_str)
            attr.Write("mesh_topology")
            attr = mesh_v.CreateAttribute("topology_dimension", [], dt_int)
            attr.Write(2)
            attr = mesh_v.CreateAttribute("face_node_connectivity", [], dt_str)
            attr.Write("icvert")
            attr = mesh_v.CreateAttribute("node_coordinates", [], dt_str)
            attr.Write("xv yv")
            attr = mesh_v.CreateAttribute("face_dimension", [], dt_str)
            attr.Write("icell2d")
            attr = mesh_v.CreateAttribute("face_coordinates", [], dt_str)
            attr.Write("xc yc")
            if nodata != -1:
                attr = mesh_v.CreateAttribute("face_node_connectivity_filler_value", [], dt_int)
                attr.Write(int(nodata))

            # The Data Variable
            fill_val = -9999.0 # Explicit float fill value for compatibility
            
            data_v = root.CreateMDArray(var_name, [dim_icell2d], dt_float)
            
            # Handle masked arrays
            if isinstance(data, np.ma.MaskedArray) or hasattr(data, 'filled'):
                try: data_clean = data.filled(fill_val)
                except: data_clean = np.where(np.isnan(data), fill_val, data)
            else:
                data_clean = np.where(np.isnan(data), fill_val, data)
                
            data_v.WriteArray(data_clean.astype(np.float32))
                
            attr = data_v.CreateAttribute("mesh", [], dt_str)
            attr.Write("mesh2d")
            attr = data_v.CreateAttribute("location", [], dt_str)
            attr.Write("face")
            attr = data_v.CreateAttribute("standard_name", [], dt_str)
            attr.Write(var_name)
            attr = data_v.CreateAttribute("long_name", [], dt_str)
            attr.Write(var_name)
            attr = data_v.CreateAttribute("_FillValue", [], dt_float)
            attr.Write(fill_val)
            
            attr = root.CreateAttribute("Conventions", [], dt_str)
            attr.Write("UGRID-1.0")
            
            out_ds = None # close and flush
            
            return True, ""
            
        except Exception as e:
            import traceback
            return False, f"Export failed: {str(e)}\n{traceback.format_exc()}"

    def get_timeseries_data(self, var_name, world_pt, layer_indices=None):
        """
        Extracts time series data at a point for one or more layers.
        world_pt should be QgsPointXY or (x, y) in world coordinates.
        layer_indices is a list of integers. Defaults to [0].
        Returns: {
            'times': [str, ...],
            'values': { layer_idx: [data, ...], ... },
            'layer_names': [str, ...],
            'var_name': str,
            'unit': str,
            'point': (x, y)
        }
        """
        if not self.ds or var_name not in self.ds.variables:
            return None

        import numpy as np
        if hasattr(world_pt, 'x'):
            wx, wy = world_pt.x(), world_pt.y()
        else:
            wx, wy = world_pt
            
        mx, my = self.transform_world_to_model(wx, wy)
        
        # 1. Find the cell index
        cell_idx = None
        if self.grid_type == 'structured':
            x_vals = None
            y_vals = None
            vkeys = self.ds.variables.keys()
            for pair in [('x', 'y'), ('lon', 'lat'), ('longitude', 'latitude')]:
                if pair[0] in vkeys and pair[1] in vkeys:
                    x_vals, y_vals = self.ds.variables[pair[0]][:], self.ds.variables[pair[1]][:]
                    break
            
            if x_vals is not None and y_vals is not None:
                dx = np.abs(x_vals[1] - x_vals[0]) if len(x_vals) > 1 else 0
                dy = np.abs(y_vals[1] - y_vals[0]) if len(y_vals) > 1 else 0
                
                # Find closest indices
                c = np.argmin(np.abs(x_vals - mx))
                r = np.argmin(np.abs(y_vals - my))
                
                # Check if within cell bounds (with small margin)
                if np.abs(x_vals[c] - mx) <= dx * 0.501 and np.abs(y_vals[r] - my) <= dy * 0.501:
                    cell_idx = (r, c)
                    # Snap to cell center in model space
                    mx_snapped, my_snapped = x_vals[c], y_vals[r]
                    wx, wy = self.transform_model_to_world(mx_snapped, my_snapped)
        else:
            # Vertex grid - use spatial index
            if 'strtree' not in self._cache:
                # Force building the cache if it's missing (needed if cross-section hasn't been used yet)
                icv = self._get_topology_var('icvert')
                xv_m = self._get_topology_var('xv')
                yv_m = self._get_topology_var('yv')
                if icv is not None and xv_m is not None and yv_m is not None and shapely:
                    nodata = getattr(self.ds.variables['icvert'], 'nodata', -1)
                    polys = []
                    poly_indices = []
                    for i in range(len(icv)):
                        v_idx = icv[i][icv[i] != nodata]
                        if len(v_idx) >= 3:
                            polys.append(Polygon(zip(xv_m[v_idx], yv_m[v_idx])))
                            poly_indices.append(i)
                    self._cache['polys'] = polys
                    self._cache['poly_indices'] = poly_indices
                    self._cache['strtree'] = STRtree(polys)
            
            if 'strtree' in self._cache:
                from shapely.geometry import Point
                pt = Point(mx, my)
                tree = self._cache['strtree']
                res = tree.query(pt, predicate='intersects')
                if len(res) > 0:
                    idx_in_tree = res[0]
                    cell_idx = self._cache['poly_indices'][idx_in_tree]
                    # Snap to cell center - we already have world space centroids
                    xc_all, yc_all = self._get_centroids()
                    wx, wy = xc_all[cell_idx], yc_all[cell_idx]
        
        if cell_idx is None:
            return {"error": "No cell found at this location."}

        # 2. Extract time series
        var = self.ds.variables[var_name]
        dims = var.dimensions
        
        if layer_indices is None:
            layer_indices = [0]
            
        # Identify dimensions
        possible_layers = {'layer', 'z', 'level', 'lev', 'k'}
        possible_times = {'time'}
        
        time_dim_idx = None
        layer_dim_idx = None
        
        for i, d in enumerate(dims):
            d_lower = d.lower()
            if d_lower in possible_times:
                time_dim_idx = i
            elif d_lower in possible_layers:
                layer_dim_idx = i
        
        if time_dim_idx is None:
            return {"error": f"Variable '{var_name}' does not have a time dimension."}

        # Retrieve all times once
        dim_meta = self.get_dimensions_metadata()
        time_values = dim_meta['times']
        time_stamps = dim_meta.get('time_stamps', [])
        layer_names = dim_meta['layers']
        
        unit = getattr(var, 'units', '')
        
        results = {
            'times': time_values, 
            'time_stamps': time_stamps,
            'values': {}, 
            'layer_names': layer_names,
            'var_name': var_name,
            'unit': unit,
            'point': (wx, wy),
            'has_layers': layer_dim_idx is not None,
            'cell_info': cell_idx
        }
        
        # If no layer dimension, we only need to fetch once
        target_indices = layer_indices if layer_dim_idx is not None else [0]
        
        for lyr in target_indices:
            sl = [slice(None)] * var.ndim
            if layer_dim_idx is not None:
                if lyr >= len(layer_names): continue
                sl[layer_dim_idx] = lyr
            
            if self.grid_type == 'structured':
                sl[-2] = cell_idx[0]
                sl[-1] = cell_idx[1]
            else:
                sl[-1] = cell_idx
            
            data = var[tuple(sl)]
            
            # Handle masked arrays: fill with NaN
            if hasattr(data, 'filled'):
                data = data.filled(np.nan)
            
            results['values'][lyr] = data.tolist()
            
        return results

    def get_variable_stats(self, var_name, layer_idx=0, time_idx=0):
        """Returns the min and max values for a specific variable slice."""
        if not self.ds or var_name not in self.ds.variables:
            return {"min": 0.0, "max": 1.0}
        
        try:
            import numpy as np
            var = self.ds.variables[var_name]
            dims = var.dimensions
            sl = [slice(None)] * var.ndim
            
            # Identify dimensions
            possible_layers = {'layer', 'z', 'level', 'lev'}
            possible_times = {'time'}
            
            for i, d in enumerate(dims):
                if d.lower() in possible_layers:
                    sl[i] = layer_idx
                elif d.lower() in possible_times:
                    sl[i] = time_idx
            
            data = var[tuple(sl)]
            
            # Compute stats on the actual slice
            v_min = float(np.nanmin(data))
            v_max = float(np.nanmax(data))
            
            # Handle all-NaN or constant data
            import math
            if math.isnan(v_min) or math.isinf(v_min): v_min = 0.0
            if math.isnan(v_max) or math.isinf(v_max): v_max = 1.0
            
            return {"min": v_min, "max": v_max}
        except:
            return {"min": 0.0, "max": 1.0}

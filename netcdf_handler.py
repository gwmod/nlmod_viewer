import importlib
import os
import numpy as np

try:
    import netCDF4
except ImportError:
    netCDF4 = None

try:
    import shapely
    from shapely.geometry import LineString, Polygon
    from shapely import STRtree, intersection, line_locate_point, box
except ImportError:
    shapely = None

NETCDF4_MISSING_MESSAGE = "The 'netCDF4' library is missing from the QGIS Python environment."


def ensure_netcdf4():
    """Imports netCDF4 lazily so the plugin can retry after installing it."""
    global netCDF4
    if netCDF4 is not None:
        return netCDF4

    try:
        importlib.invalidate_caches()
        netCDF4 = importlib.import_module('netCDF4')
    except ImportError:
        netCDF4 = None

    return netCDF4

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
        self.last_error_code = None
        self.grid_type = "unknown"
        self._cache = {} # Cache for topology and spatial index
        self._structured_fallback_messages = []
        self.angrot = 0.0
        self.xorigin = 0.0
        self.yorigin = 0.0
        self.is_absolute = False

    def _record_structured_fallback_warning(self, message):
        if message not in self._structured_fallback_messages:
            self._structured_fallback_messages.append(message)

    def consume_structured_fallback_warnings(self):
        msgs = list(self._structured_fallback_messages)
        self._structured_fallback_messages = []
        return msgs

    def _detect_absolute_coords(self, x_vals, y_vals=None):
        """Heuristic for datasets that already store world coordinates."""
        if self.angrot != 0:
            # Rotated nlmod grids should be transformed; do not auto-mark absolute.
            return False
        if self.xorigin == 0 and self.yorigin == 0:
            return False

        try:
            xv = np.asarray(x_vals, dtype=float).ravel()
            xv = xv[np.isfinite(xv)]
            if xv.size == 0:
                return False

            yv = None
            if y_vals is not None:
                yv = np.asarray(y_vals, dtype=float).ravel()
                yv = yv[np.isfinite(yv)]
                if yv.size == 0:
                    yv = None

            mean_x = float(np.nanmean(xv))
            close_to_xorigin = np.abs(mean_x - self.xorigin) < np.abs(mean_x)

            if yv is None:
                return bool(close_to_xorigin)

            mean_y = float(np.nanmean(yv))
            close_to_yorigin = np.abs(mean_y - self.yorigin) < np.abs(mean_y)
            return bool(close_to_xorigin and close_to_yorigin)
        except (TypeError, ValueError, AttributeError):
            return False

    def _log_qgis_message(self, message, level='info'):
        """Best-effort QGIS logging that is safe outside QGIS runtime."""
        try:
            from qgis.core import QgsMessageLog, Qgis
            level_map = {
                'info': Qgis.MessageLevel.Info,
                'warning': Qgis.MessageLevel.Warning,
                'critical': Qgis.MessageLevel.Critical,
            }
            QgsMessageLog.logMessage(message, "NLMOD Viewer", level_map.get(level, Qgis.MessageLevel.Info))
        except (ImportError, AttributeError):
            print(f"NLMOD [{level.upper()}]: {message}")

    def _normalize_structured_axes(self, x_vals, y_vals, context='structured'):
        """Returns 1D x/y axes for affine approximations on structured grids."""
        x_arr = np.asarray(x_vals, dtype=float)
        y_arr = np.asarray(y_vals, dtype=float)

        if x_arr.ndim == 1 and y_arr.ndim == 1:
            return x_arr, y_arr

        if x_arr.ndim == 2 and y_arr.ndim == 2 and x_arr.shape == y_arr.shape:
            msg = f"NLMOD: {context}: 2D coordinate arrays detected (e.g. variable delr/delc). Using best-effort affine from row/column means."
            self._record_structured_fallback_warning(msg)
            self._log_qgis_message(msg, 'warning')
            x_axis = np.nanmean(x_arr, axis=0)
            y_axis = np.nanmean(y_arr, axis=1)
            return x_axis, y_axis

        msg = f"NLMOD: {context}: unsupported coordinate array shapes x={x_arr.shape}, y={y_arr.shape}. Using unique sorted coordinates as fallback."
        self._record_structured_fallback_warning(msg)
        self._log_qgis_message(msg, 'warning')

        x_flat = x_arr[np.isfinite(x_arr)]
        y_flat = y_arr[np.isfinite(y_arr)]
        if x_flat.size < 2 or y_flat.size < 2:
            return None, None

        return np.unique(np.sort(x_flat)), np.unique(np.sort(y_flat))

    def _estimate_axis_spacing(self, axis_vals, axis_name='axis', context='structured'):
        """Estimate representative cell size for possibly irregular axes."""
        axis = np.asarray(axis_vals, dtype=float)
        if axis.size < 2:
            return 1.0

        diffs = np.abs(np.diff(axis))
        diffs = diffs[np.isfinite(diffs)]
        diffs = diffs[diffs > 0]
        if diffs.size == 0:
            return 1.0

        if not np.allclose(diffs, diffs[0], rtol=1e-4, atol=1e-9):
            msg = f"NLMOD: {context}: non-uniform {axis_name} spacing detected. Using median spacing for best-effort rendering."
            self._record_structured_fallback_warning(msg)
            self._log_qgis_message(msg, 'warning')

        return float(np.nanmedian(diffs))

    def open(self):
        self.last_error_code = None
        if not os.path.exists(self.filepath):
            self.last_error_code = "file-not-found"
            return False, "File not found"
        try:
            if ensure_netcdf4() is None:
                raise ImportError("netCDF4 module not found")
                
            self.ds = netCDF4.Dataset(self.filepath, 'r')
            
            # Read rotation and origin attributes if present
            self.angrot = float(getattr(self.ds, 'angrot', 0.0))
            self.xorigin = float(getattr(self.ds, 'xorigin', 0.0))
            self.yorigin = float(getattr(self.ds, 'yorigin', 0.0))

            self.detect_grid_type()
            
            # Detect if coordinates are already absolute
            self.is_absolute = False
            x_test = None
            y_test = None
            if 'x' in self.ds.variables and self.ds.variables['x'].ndim == 1:
                x_test = self.ds.variables['x'][:]
                if 'y' in self.ds.variables and self.ds.variables['y'].ndim == 1:
                    y_test = self.ds.variables['y'][:]
            elif 'xc' in self.ds.variables:
                x_test = self.ds.variables['xc'][:]
                if 'yc' in self.ds.variables:
                    y_test = self.ds.variables['yc'][:]

            if x_test is not None:
                self.is_absolute = self._detect_absolute_coords(x_test, y_test)

            # Helpful for diagnosing shifted/rotated render behavior per dataset.
            self._log_qgis_message(
                f"NLMOD: Transform detection -> is_absolute={self.is_absolute}, angrot={self.angrot}, xorigin={self.xorigin}, yorigin={self.yorigin}",
                'info',
            )
            
            return True, ""
        except ImportError:
            self.last_error_code = "missing-netcdf4"
            return False, NETCDF4_MISSING_MESSAGE
        except Exception as e:
            self.last_error_code = "open-failed"
            return False, f"Error opening file: {str(e)}"

    def close(self):
        if self.ds:
            self.ds.close()
            self.ds = None
        self._cache = {} # Clear cache
        self._structured_fallback_messages = []
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
        
        x_vals_raw, y_vals_raw = x_var[:], y_var[:]
        x_vals, y_vals = self._normalize_structured_axes(x_vals_raw, y_vals_raw, context='get_geotransform')
        if x_vals is None or y_vals is None or len(x_vals) < 2 or len(y_vals) < 2:
            self._log_qgis_message("NLMOD: get_geotransform: could not derive structured axes.", 'warning')
            return None

        dx = self._estimate_axis_spacing(x_vals, axis_name='x', context='get_geotransform')
        dy = self._estimate_axis_spacing(y_vals, axis_name='y', context='get_geotransform')
        
        # Model space limits
        xm_min = np.min(x_vals) - dx/2
        ym_min = np.min(y_vals) - dy/2
        ym_max = np.max(y_vals) + dy/2
        
        # Determine whether raw Y axis in NetCDF dataset is ascending or descending
        y_is_ascending = (y_vals_raw[1] > y_vals_raw[0]) if len(y_vals_raw) >= 2 else True

        if not self.is_absolute:
            a = np.radians(self.angrot)
            cosa = np.cos(a)
            sina = np.sin(a)
            
            if y_is_ascending:
                # GDAL NetCDF driver reads NetCDF array row ny-1 (ym_max, North) into GDAL row 0.
                # So GDAL row 0 corresponds to top-left in model space (xm_min, ym_max).
                ulx = self.xorigin + xm_min * cosa - ym_max * sina
                uly = self.yorigin + xm_min * sina + ym_max * cosa
                return [ulx, dx * cosa, dy * sina, uly, dx * sina, -dy * cosa]
            else:
                # GDAL NetCDF driver reads NetCDF array row ny-1 (ym_min, South) into GDAL row 0.
                # So GDAL row 0 corresponds to bottom-left in model space (xm_min, ym_min).
                bl_x = self.xorigin + xm_min * cosa - ym_min * sina
                bl_y = self.yorigin + xm_min * sina + ym_min * cosa
                return [bl_x, dx * cosa, -dy * sina, bl_y, dx * sina, dy * cosa]
        else:
            if y_is_ascending:
                return [xm_min, dx, 0, ym_max, 0, -dy]
            else:
                return [xm_min, dx, 0, ym_min, 0, dy]

    def get_vars_with_time(self):
        """Returns a list of variable names that have a time dimension."""
        if not self.ds:
            return []
            
        vars_with_time = []
        possible_times = {'time'}
        
        for name, var in self.ds.variables.items():
            # Skip coordinate variables themselves
            if name.lower() in possible_times:
                continue
                
            dims_lower = [d.lower() for d in var.dimensions]
            has_time = any(d in possible_times for d in dims_lower)

            if has_time:
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

    def get_dimensions_metadata(self):
        """Returns metadata for all available dimensions (layers, times) in the file."""
        if not self.ds:
            return {"layers": [], "times": [], "time_stamps": []}
            
        layers = []
        times = []
        time_stamps = []
        
        possible_layers = {'layer', 'z'}
        possible_times = {'time'}
        
        # Look for these dimensions in the variables
        for d in self.ds.dimensions:
            if d.lower() in possible_layers:
                # Get values from variable if it exists
                if d in self.ds.variables:
                    vals = self.ds.variables[d][:]
                    layers = [str(v) for v in vals]
                if not layers:
                    layers = [str(i+1) for i in range(self.ds.dimensions[d].size)]
            
            if d.lower() in possible_times:
                if d in self.ds.variables:
                    t_var = self.ds.variables[d]
                    vals = t_var[:]
                    try:
                        from datetime import datetime
                        if hasattr(t_var, 'units'):
                            cal = getattr(t_var, 'calendar', 'standard')
                            dates = netCDF4.num2date(vals, units=t_var.units, calendar=cal)
                            
                            def fmt(dt):
                                if hasattr(dt, 'strftime'):
                                    return dt.strftime('%Y-%m-%d %H:%M:%S') if dt.hour or dt.minute else dt.strftime('%Y-%m-%d')
                                return str(dt)
                                
                            def to_ts(dt):
                                try:
                                    if hasattr(dt, 'timestamp'):
                                        return dt.timestamp()
                                    # Fallback for cftime
                                    d_dt = datetime(dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second)
                                    return d_dt.timestamp()
                                except (AttributeError, ValueError, TypeError):
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
                    except (ValueError, TypeError, AttributeError):
                        times = [str(v) for v in vals]
                        time_stamps = [float(v) for v in vals]
                if not times:
                    size = self.ds.dimensions[d].size
                    times = [str(i+1) for i in range(size)]
                    time_stamps = [float(i) for i in range(size)]
                    
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
            possible_layers = {'layer', 'z'}
            
            # Detect time dim
            time_dim = None
            time_size = 0
            time_values = []
            possible_times = {'time'}

            for d in var.dimensions:
                if d in possible_layers:
                    layer_dim = d
                    if d in self.ds.variables:
                        vals = self.ds.variables[d][:]
                        try:
                            layer_values = [str(v) for v in vals]
                        except (TypeError, ValueError, AttributeError):
                            layer_values = []
                    if not layer_values:
                         size = self.ds.dimensions[d].size
                         layer_values = [str(i+1) for i in range(size)]
                    layer_size = len(layer_values)
                
                if d in possible_times:
                    time_dim = d
                    if d in self.ds.variables:
                        t_var = self.ds.variables[d]
                        vals = t_var[:]
                        try:
                            if hasattr(t_var, 'units'):
                                cal = getattr(t_var, 'calendar', 'standard')
                                dates = netCDF4.num2date(vals, units=t_var.units, calendar=cal)
                                
                                def fmt(dt):
                                    if hasattr(dt, 'strftime'):
                                        return dt.strftime('%Y-%m-%d %H:%M:%S') if dt.hour or dt.minute else dt.strftime('%Y-%m-%d')
                                    return str(dt)
                                
                                if isinstance(dates, (list, np.ndarray)):
                                    time_values = [fmt(dt) for dt in dates]
                                else:
                                    # Might be a single cftime object
                                    time_values = [fmt(dates)]
                            else:
                                time_values = [str(v) for v in vals]
                        except (ValueError, TypeError, AttributeError):
                            time_values = [str(v) for v in vals]
                    if not time_values:
                         size = self.ds.dimensions[d].size
                         time_values = [str(i+1) for i in range(size)]
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

    def get_extra_dimensions(self, var_name):
        """
        Returns a list of extra dimensions for a variable — i.e. every dimension that is
        NOT the time dim, layer/z dim, or spatial dim (icell2d / x / y).
        Each entry: {'dim_name': str, 'size': int, 'values': [str]}
        Returns [] when there are no extra dimensions.
        """
        if not self.ds or var_name not in self.ds.variables:
            return []
        var = self.ds.variables[var_name]
        known_dims = {'time', 'layer', 'z', 'icell2d', 'x', 'y',
                      'layer_index', 'lev', 'k', 'lat', 'lon', 'latitude', 'longitude'}
        extra = []
        for d in var.dimensions:
            if d.lower() in known_dims:
                continue
            size = self.ds.dimensions[d].size
            # Try to read human-readable labels from a coordinate variable
            if d in self.ds.variables:
                raw = self.ds.variables[d][:]
                values = [str(v) for v in raw]
            else:
                values = [str(i) for i in range(size)]
            extra.append({'dim_name': d, 'size': size, 'values': values})
        return extra


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
                        if x_cand is not None and y_cand is not None:
                            x_var = x_cand
                            y_var = y_cand
                            QgsMessageLog.logMessage(f"NLMOD: Found coordinates via attribute: {x_var.name}, {y_var.name}", "NLMOD Viewer", Qgis.MessageLevel.Info)

            # Strategy 2: Search by standard_name (projection_x_coordinate)
            if x_var is None:
                for n, v in self.ds.variables.items():
                    std_name = getattr(v, 'standard_name', '').lower()
                    if 'projection_x_coordinate' in std_name or 'longitude' in std_name:
                        x_var = v
                    if 'projection_y_coordinate' in std_name or 'latitude' in std_name:
                        y_var = v
                if x_var is not None and y_var is not None:
                    QgsMessageLog.logMessage(f"NLMOD: Found coordinates via standard_name: {x_var.name}, {y_var.name}", "NLMOD Viewer", Qgis.MessageLevel.Info)

            # Strategy 3: Common names (fallback)
            if x_var is None:
                vkeys = self.ds.variables.keys()
                # Log keys for debug
                QgsMessageLog.logMessage(f"NLMOD: Variable keys: {list(vkeys)}", "NLMOD Viewer", Qgis.MessageLevel.Info)
                
                for pair in [('x', 'y'), ('lon', 'lat'), ('longitude', 'latitude'), ('x_coord', 'y_coord'), ('X', 'Y')]:
                    if pair[0] in vkeys and pair[1] in vkeys:
                        x_var = self.ds.variables[pair[0]]
                        y_var = self.ds.variables[pair[1]]
                        QgsMessageLog.logMessage(f"NLMOD: Found coordinates via name match: {pair}", "NLMOD Viewer", Qgis.MessageLevel.Info)
                        break

            if x_var is None or y_var is None:
                # If we can't find coords but have extent attribute, use it as a last resort
                if hasattr(self.ds, 'extent'):
                    ext = self.ds.extent
                    if len(ext) == 4:
                         # For nlmod, if we only have extent, it's often South-to-North (Ascending)
                         # Previous Hardcoded 'False' was reported as flipped.
                         QgsMessageLog.logMessage(f"NLMOD: Found extent via attribute (no coords): {ext}. Defaulting Ascending=True", "NLMOD Viewer", Qgis.MessageLevel.Info)
                         return (ext[0], ext[1], ext[2], ext[3], True)
                return None
            
            # Use detected coords to determine direction
            x_vals_raw = x_var[:]
            y_vals_raw = y_var[:]
            x_vals, y_vals = self._normalize_structured_axes(x_vals_raw, y_vals_raw, context='get_extent')
            if x_vals is None or y_vals is None:
                QgsMessageLog.logMessage("NLMOD: Could not normalize structured coordinate axes.", "NLMOD Viewer", Qgis.MessageLevel.Warning)
                return None

            if len(y_vals) >= 2:
                y_is_ascending = (y_vals[1] > y_vals[0])
                QgsMessageLog.logMessage(f"NLMOD: Detected Y direction: {y_vals[0]} to {y_vals[-1]} (Ascending={y_is_ascending})", "NLMOD Viewer", Qgis.MessageLevel.Info)
            else:
                y_is_ascending = False

            # Check for global extent attribute for bounds
            if hasattr(self.ds, 'extent'):
                ext = self.ds.extent
                if len(ext) == 4:
                     QgsMessageLog.logMessage(f"NLMOD: Using global extent for bounds, Ascending={y_is_ascending}", "NLMOD Viewer", Qgis.MessageLevel.Info)
                     return (ext[0], ext[1], ext[2], ext[3], y_is_ascending)

            # Otherwise calculate bounds from coords
            x = x_vals
            y = y_vals
            
            if len(x) < 2 or len(y) < 2:
                QgsMessageLog.logMessage("NLMOD: Coordinate arrays too short.", "NLMOD Viewer", Qgis.MessageLevel.Warning)
                return None
                
            # Determine cell sizes (dx, dy)
            dx = self._estimate_axis_spacing(x, axis_name='x', context='get_extent')
            dy = self._estimate_axis_spacing(y, axis_name='y', context='get_extent')
            
            # Model space bounds
            xm_min = np.min(x) - dx/2
            xm_max = np.max(x) + dx/2
            ym_min = np.min(y) - dy/2
            ym_max = np.max(y) + dy/2
            
            # Now transform corners if rotated or moved from QGIS 0,0
            if (self.angrot == 0 and self.xorigin == 0 and self.yorigin == 0) or self.is_absolute:
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
            QgsMessageLog.logMessage(f"NLMOD: Error calculating extent: {e}", "NLMOD Viewer", Qgis.MessageLevel.Critical)
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

        def _looks_absolute_world(x_vals, y_vals):
            """Heuristic: coordinates close to origin offsets are likely already world-space."""
            try:
                xv = np.asarray(x_vals, dtype=float).ravel()
                yv = np.asarray(y_vals, dtype=float).ravel()
                xv = xv[np.isfinite(xv)]
                yv = yv[np.isfinite(yv)]
                if xv.size == 0 or yv.size == 0:
                    return False

                mean_x = float(np.nanmean(xv))
                mean_y = float(np.nanmean(yv))
                close_x = np.abs(mean_x - self.xorigin) < np.abs(mean_x)
                close_y = np.abs(mean_y - self.yorigin) < np.abs(mean_y)
                return bool(close_x and close_y)
            except (TypeError, ValueError, AttributeError):
                return False
        
        if 'centroids' in self._cache:
            return self._cache['centroids']

        # 1. Fallback to file-provided coordinates
        if 'xc' in self.ds.variables and 'yc' in self.ds.variables:
            xc_vals = self.ds.variables['xc'][:]
            yc_vals = self.ds.variables['yc'][:]
            
            # Apply transform only when centroids appear to be model-space coordinates.
            # Some rotated datasets store xc/yc already in world coordinates.
            is_world_coords = self.is_absolute or _looks_absolute_world(xc_vals, yc_vals)
            if (self.angrot != 0 or self.xorigin != 0 or self.yorigin != 0) and not is_world_coords:
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
            # First transform vertices to world space if necessary
            if (self.angrot != 0 or self.xorigin != 0 or self.yorigin != 0) and not self.is_absolute:
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
                        xc[i] = float(np.mean(xv_world[v_idx]))
                        yc[i] = float(np.mean(yv_world[v_idx]))
                    except (IndexError, TypeError, ValueError):
                        xc[i] = np.nan
                        yc[i] = np.nan
            
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

    def get_cross_section_data(self, variable_name, points, time_idx=0, extra_dim_indices=None):
        """
        Extracts cross-section data using exact Shapely intersections with cell geometries.
        extra_dim_indices: dict mapping extra dimension names to integer indices.
        """
        if not self.ds:
            return None
        
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
                            if (self.angrot != 0 or self.xorigin != 0 or self.yorigin != 0) and not self.is_absolute:
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

                    # Apply extra user-specified dimensions (only for the data variable)
                    if extra_dim_indices and v == variable_name:
                        for i, dim_name in enumerate(dims):
                            if dim_name in extra_dim_indices:
                                sl[i] = int(extra_dim_indices[dim_name])
                    
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

                    # Apply extra user-specified dimensions (only for the data variable)
                    if extra_dim_indices and v == variable_name:
                        for i, dim_name in enumerate(dims):
                            if dim_name in extra_dim_indices:
                                sl[i] = int(extra_dim_indices[dim_name])
                    
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
            nm = self.ds.variables.get('layer', [str(i+1) for i in range(botm.shape[0])])[:]
            layer_names = [str(x) for x in nm] if hasattr(nm, '__len__') else [str(i+1) for i in range(botm.shape[0])]

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

    def export_to_mesh(self, var_name, layer_idx=0, time_idx=0, output_path=None, extra_dim_indices=None):
        """
        Exports a single variable (at a specific layer and time) to a clean UGRID NetCDF file.
        This provides maximal compatibility with MDAL.
        extra_dim_indices: dict mapping extra dimension names to integer indices.
        """
        if not self.ds or var_name not in self.ds.variables:
            return False, "Variable not found"
            
        try:
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

            # Handle extra (user-specified) dimensions
            if extra_dim_indices:
                for i, d in enumerate(dims):
                    if d in extra_dim_indices:
                        sl[i] = int(extra_dim_indices[d])
            
            data = var[tuple(sl)]
            
            if data is None:
                return False, "Unsupported variable dimensions"

            # 2. Create new NetCDF
            out_ds = netCDF4.Dataset(output_path, 'w', format='NETCDF4')
            
            # Copy topology variables and dimensions
            # We need icell2d and nvertex (from icvert)
            icert_in = self.ds.variables.get('icvert')
            if icert_in is None:
                return False, "icvert (topology) not found in source"
                
            n_cells = self.ds.dimensions['icell2d'].size
            n_vert_per_cell = icert_in.shape[1]
            
            out_ds.createDimension('icell2d', n_cells)
            out_ds.createDimension('nvertex', n_vert_per_cell)
            
            # Create icvert
            icv_out = out_ds.createVariable('icvert', icert_in.dtype, ('icell2d', 'nvertex'))
            icv_out[:] = icert_in[:]
            icv_out.cf_role = "face_node_connectivity"
            icv_out.start_index = 0
            nodata = getattr(icert_in, 'nodata', -1)
            
            # Vertices
            xv_in = self.ds.variables.get('xv')
            yv_in = self.ds.variables.get('yv')
            if xv_in is not None and yv_in is not None:
                n_node = self.ds.dimensions.get('nnode', self.ds.dimensions.get('node', None))
                if not n_node:
                    out_ds.createDimension('nnode', len(xv_in))
                else:
                    out_ds.createDimension('nnode', n_node.size)
                    
                xv_out = out_ds.createVariable('xv', 'f4', ('nnode',))
                yv_out = out_ds.createVariable('yv', 'f4', ('nnode',))
                
                # Transform vertices to world space if rotated/moved
                if self.angrot != 0 or self.xorigin != 0 or self.yorigin != 0:
                    xv_world, yv_world = self.transform_model_to_world(xv_in[:], yv_in[:])
                    xv_out[:] = xv_world
                    yv_out[:] = yv_world
                else:
                    xv_out[:] = xv_in[:]
                    yv_out[:] = yv_in[:]
                xv_out.standard_name = "projection_x_coordinate"
                yv_out.standard_name = "projection_y_coordinate"
                xv_out.units = "m"
                yv_out.units = "m"

            # Centroids (xc, yc) - Calculated if missing
            xc_vals, yc_vals = self._get_centroids()
            if xc_vals is None:
                 return False, "Could not determine cell centroids"
            
            xc_out = out_ds.createVariable('xc', 'f4', ('icell2d',))
            yc_out = out_ds.createVariable('yc', 'f4', ('icell2d',))
            xc_out[:] = xc_vals
            yc_out[:] = yc_vals
            xc_out.standard_name = "projection_x_coordinate"
            yc_out.standard_name = "projection_y_coordinate"
            xc_out.units = "m"
            yc_out.units = "m"

            # Mesh Topology variable
            mesh_v = out_ds.createVariable('mesh2d', 'i4')
            mesh_v.cf_role = "mesh_topology"
            mesh_v.topology_dimension = 2
            mesh_v.face_node_connectivity = "icvert"
            mesh_v.node_coordinates = "xv yv"
            mesh_v.face_dimension = "icell2d"
            mesh_v.face_coordinates = "xc yc"
            if nodata != -1:
                mesh_v.face_node_connectivity_filler_value = nodata

            # The Data Variable
            fill_val = -9999.0 # Explicit float fill value for compatibility
            
            data_v = out_ds.createVariable(var_name, 'f4', ('icell2d',), fill_value=fill_val)
            # Handle masked arrays
            if isinstance(data, np.ma.MaskedArray):
                data_v[:] = data.filled(fill_val)
            else:
                # Replace NaNs with fill value
                data_clean = np.where(np.isnan(data), fill_val, data)
                data_v[:] = data_clean
                
            data_v.mesh = "mesh2d"
            data_v.location = "face"
            data_v.standard_name = var_name
            data_v.long_name = var_name
            
            out_ds.Conventions = "UGRID-1.0"
            out_ds.close()
            
            return True, ""
            
        except Exception as e:
            import traceback
            return False, f"Export failed: {str(e)}\n{traceback.format_exc()}"

    def get_timeseries_data(self, var_name, world_pt, layer_indices=None, extra_dim_indices=None):
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

        wx, wy = None, None
        mx, my = None, None
        if world_pt is not None:
            if hasattr(world_pt, 'x'):
                wx, wy = world_pt.x(), world_pt.y()
            else:
                wx, wy = world_pt
            mx, my = self.transform_world_to_model(wx, wy)

        var = self.ds.variables[var_name]
        dims = var.dimensions

        dims_lower = [d.lower() for d in dims]
        has_spatial = ('icell2d' in dims_lower) or ('x' in dims_lower and 'y' in dims_lower)
        
        # 1. Find the cell index for spatial variables
        cell_idx = None
        if has_spatial and self.grid_type == 'structured':
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
        elif has_spatial:
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
        
        if has_spatial and cell_idx is None:
            return {"error": "No cell found at this location."}

        # 2. Extract time series
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
            'point': (wx, wy) if has_spatial and wx is not None and wy is not None else None,
            'has_layers': layer_dim_idx is not None,
            'cell_info': cell_idx
        }
        
        # If no layer dimension, we only need to fetch once
        target_indices = layer_indices if layer_dim_idx is not None else [0]

        # Build extra-dimension combinations (single values or multi-select lists).
        extra_dim_defs = {d['dim_name']: d for d in self.get_extra_dimensions(var_name)}

        def _normalize_selection(sel, size):
            if isinstance(sel, (list, tuple, set, np.ndarray)):
                vals = [int(v) for v in sel]
            else:
                vals = [int(sel)]
            vals = sorted(set(v for v in vals if 0 <= v < int(size)))
            return vals or [0]

        extra_dim_order = []
        extra_dim_choices = []
        if extra_dim_indices:
            for d in dims:
                if d in extra_dim_indices and d in self.ds.dimensions:
                    size = self.ds.dimensions[d].size
                    idxs = _normalize_selection(extra_dim_indices[d], size)
                    extra_dim_order.append(d)
                    extra_dim_choices.append(idxs)

        combo_dicts = [{}]
        if extra_dim_order:
            import itertools
            combo_dicts = [
                {dim_name: int(ix) for dim_name, ix in zip(extra_dim_order, combo)}
                for combo in itertools.product(*extra_dim_choices)
            ]

        series = []
        for lyr in target_indices:
            if layer_dim_idx is not None and lyr >= len(layer_names):
                continue

            for combo in combo_dicts:
                sl = [slice(None)] * var.ndim
                if layer_dim_idx is not None:
                    sl[layer_dim_idx] = lyr

                for i, d in enumerate(dims):
                    if d in combo:
                        sl[i] = combo[d]

                if has_spatial:
                    if self.grid_type == 'structured':
                        sl[-2] = cell_idx[0]
                        sl[-1] = cell_idx[1]
                    else:
                        sl[-1] = cell_idx

                data = var[tuple(sl)]

                # Handle masked arrays: fill with NaN
                if hasattr(data, 'filled'):
                    data = data.filled(np.nan)

                values = data.tolist()

                # Keep legacy structure for existing callers.
                if lyr not in results['values']:
                    results['values'][lyr] = values

                base_name = var_name
                if layer_dim_idx is not None and lyr < len(layer_names):
                    base_name = layer_names[lyr]

                if combo:
                    labels = []
                    for dim_name in extra_dim_order:
                        ix = combo[dim_name]
                        dim_def = extra_dim_defs.get(dim_name, {})
                        dim_values = dim_def.get('values', [])
                        lbl = dim_values[ix] if ix < len(dim_values) else str(ix)
                        labels.append(f"{dim_name}={lbl}")
                    series_name = f"{base_name} | {', '.join(labels)}"
                else:
                    series_name = base_name

                series.append({
                    'name': series_name,
                    'layer_idx': int(lyr),
                    'extra_selection': combo,
                    'values': values,
                })

        results['series'] = series
            
        return results

    def get_variable_stats(self, var_name, layer_idx=0, time_idx=0, extra_dim_indices=None):
        """Returns the min and max values for a specific variable slice."""
        if not self.ds or var_name not in self.ds.variables:
            return {"min": 0.0, "max": 1.0}
        
        try:
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

            # Apply extra user-specified dimensions
            if extra_dim_indices:
                for i, d in enumerate(dims):
                    if d in extra_dim_indices:
                        sl[i] = int(extra_dim_indices[d])
            
            data = var[tuple(sl)]
            
            # Compute stats on the actual slice
            v_min = float(np.nanmin(data))
            v_max = float(np.nanmax(data))
            
            # Handle all-NaN or constant data
            import math
            if math.isnan(v_min) or math.isinf(v_min): v_min = 0.0
            if math.isnan(v_max) or math.isinf(v_max): v_max = 1.0
            
            return {"min": v_min, "max": v_max}
        except (KeyError, IndexError, ValueError, TypeError):
            return {"min": 0.0, "max": 1.0}

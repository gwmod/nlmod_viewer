try:
    import netCDF4
except ImportError:
    netCDF4 = None

import os
import numpy as np
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
    def __init__(self, filepath):
        self.filepath = filepath
        self.ds = None
        self.grid_type = "unknown"

    def open(self):
        if not os.path.exists(self.filepath):
            return False, "File not found"
        try:
            if netCDF4 is None:
                raise ImportError("netCDF4 module not found")
                
            self.ds = netCDF4.Dataset(self.filepath, 'r')
            
            # Check for grid rotation (angrot)
            angrot = getattr(self.ds, 'angrot', 0)
            if angrot != 0:
                self.ds.close()
                self.ds = None
                return False, f"Grid rotation detected (angrot={angrot}).\n\nModel datasets with grid rotation are not yet supported."

            self.detect_grid_type()
            return True, ""
        except ImportError:
            return False, "The 'netCDF4' library is missing.\n\nPlease install it using the OSGeo4W Shell:\n  pip install netCDF4"
        except Exception as e:
            return False, f"Error opening file: {str(e)}"

    def close(self):
        if self.ds:
            self.ds.close()
            self.ds = None

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

    def get_variables(self):
        """Returns list of variables that are likely model data (skipping coords)."""
        if not self.ds:
            return []
        
        # Common coordinate/topology variables to exclude
        exclude = {
            'x', 'y', 'lat', 'lon', 'latitude', 'longitude', 
            'time', 'layer', 'lev', 'level',
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
            possible_layers = {'layer', 'lev', 'level', 'z'}
            for d in var.dimensions:
                if d in possible_layers:
                    layer_dim = d
                    if d in self.ds.variables:
                        # Get values
                        vals = self.ds.variables[d][:]
                        try:
                            # Convert to list of strings
                            if vals.dtype.kind in 'SU': # String
                                layer_values = [str(v) for v in vals]
                            else:
                                layer_values = [str(v) for v in vals]
                        except:
                            # Fallback if conversion fails
                            pass
                            
                    if not layer_values:
                         # Fallback to indices if variable data missing but dimension exists
                         size = self.ds.dimensions[d].size
                         layer_values = [str(i+1) for i in range(size)]
                         
                    layer_size = len(layer_values)
                    break

            data_vars.append({
                'name': name,
                'description': desc,
                'shape': var.shape,
                'dimensions': var.dimensions,
                'layer_dim': layer_dim,
                'layer_size': layer_size,
                'layer_values': layer_values
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
                            QgsMessageLog.logMessage(f"NLMOD: Found coordinates via attribute: {x_var.name}, {y_var.name}", "NlmodInspector", Qgis.Info)

            # Strategy 2: Search by standard_name (projection_x_coordinate)
            if x_var is None:
                for n, v in self.ds.variables.items():
                    std_name = getattr(v, 'standard_name', '').lower()
                    if 'projection_x_coordinate' in std_name or 'longitude' in std_name:
                        x_var = v
                    if 'projection_y_coordinate' in std_name or 'latitude' in std_name:
                        y_var = v
                if x_var and y_var:
                     QgsMessageLog.logMessage(f"NLMOD: Found coordinates via standard_name: {x_var.name}, {y_var.name}", "NlmodInspector", Qgis.Info)

            # Strategy 3: Common names (fallback)
            if x_var is None:
                vkeys = self.ds.variables.keys()
                # Log keys for debug
                QgsMessageLog.logMessage(f"NLMOD: Variable keys: {list(vkeys)}", "NlmodInspector", Qgis.Info)
                
                for pair in [('x', 'y'), ('lon', 'lat'), ('longitude', 'latitude'), ('x_coord', 'y_coord'), ('X', 'Y')]:
                    if pair[0] in vkeys and pair[1] in vkeys:
                        x_var = self.ds.variables[pair[0]]
                        y_var = self.ds.variables[pair[1]]
                        QgsMessageLog.logMessage(f"NLMOD: Found coordinates via name match: {pair}", "NlmodInspector", Qgis.Info)
                        break

            if x_var is None or y_var is None:
                # If we can't find coords but have extent attribute, use it as a last resort
                if hasattr(self.ds, 'extent'):
                    ext = self.ds.extent
                    if len(ext) == 4:
                         # For nlmod, if we only have extent, it's often South-to-North (Ascending)
                         # Previous Hardcoded 'False' was reported as flipped.
                         QgsMessageLog.logMessage(f"NLMOD: Found extent via attribute (no coords): {ext}. Defaulting Ascending=True", "NlmodInspector", Qgis.Info)
                         return (ext[0], ext[1], ext[2], ext[3], True)
                return None
            
            # Use detected coords to determine direction
            y_vals = y_var[:]
            if len(y_vals) >= 2:
                y_is_ascending = (y_vals[1] > y_vals[0])
                QgsMessageLog.logMessage(f"NLMOD: Detected Y direction: {y_vals[0]} to {y_vals[-1]} (Ascending={y_is_ascending})", "NlmodInspector", Qgis.Info)
            else:
                y_is_ascending = False

            # Check for global extent attribute for bounds
            if hasattr(self.ds, 'extent'):
                ext = self.ds.extent
                if len(ext) == 4:
                     QgsMessageLog.logMessage(f"NLMOD: Using global extent for bounds, Ascending={y_is_ascending}", "NlmodInspector", Qgis.Info)
                     return (ext[0], ext[1], ext[2], ext[3], y_is_ascending)

            # Otherwise calculate bounds from coords
            x = x_var[:]
            y = y_vals
            
            if len(x) < 2 or len(y) < 2:
                QgsMessageLog.logMessage("NLMOD: Coordinate arrays too short.", "NlmodInspector", Qgis.Warning)
                return None
                
            # Determine cell sizes (dx, dy)
            dx = np.abs(x[1] - x[0])
            dy = np.abs(y[1] - y[0])
            
            # Min is center - dx/2
            xmin = np.min(x) - dx/2
            xmax = np.max(x) + dx/2
            ymin = np.min(y) - dy/2
            ymax = np.max(y) + dy/2
            
            return (xmin, xmax, ymin, ymax, y_is_ascending)
        except Exception as e:
            from qgis.core import QgsMessageLog, Qgis
            QgsMessageLog.logMessage(f"NLMOD: Error calculating extent: {e}", "NlmodInspector", Qgis.Critical)
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
        if 'xc' in self.ds.variables and 'yc' in self.ds.variables:
            return self.ds.variables['xc'][:], self.ds.variables['yc'][:]
        
        # Calculate from vertices if needed (generic approach)
        if 'icvert' in self.ds.variables and 'xv' in self.ds.variables and 'yv' in self.ds.variables:
            icv = self.ds.variables['icvert'][:]
            xv = self.ds.variables['xv'][:]
            yv = self.ds.variables['yv'][:]
            nodata = getattr(self.ds.variables['icvert'], 'nodata', -1)
            
            n_cells = icv.shape[0]
            xc = np.full(n_cells, np.nan)
            yc = np.full(n_cells, np.nan)
            
            if shapely:
                # Use shapely Polygons for true centroid (area-weighted)
                for i in range(n_cells):
                    curr_v = icv[i]
                    v_idx = curr_v[curr_v != nodata]
                    if len(v_idx) >= 3:
                        try:
                            p = Polygon(zip(xv[v_idx], yv[v_idx]))
                            cent = p.centroid
                            xc[i], yc[i] = cent.x, cent.y
                        except:
                            pass
            else:
                # Arithmetic mean fallback - improved to handle duplicated vertices
                for i in range(n_cells):
                    curr_v = icv[i]
                    v_idx = curr_v[curr_v != nodata]
                    if len(v_idx) > 0:
                        # Exclude last point if it duplicates the first
                        if len(v_idx) > 1 and v_idx[0] == v_idx[-1]:
                            v_idx = v_idx[:-1]
                        xc[i] = np.mean(xv[v_idx])
                        yc[i] = np.mean(yv[v_idx])
            return xc, yc
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

    def get_cross_section_data(self, variable_name, points):
        """
        Extracts cross-section data using exact Shapely intersections with cell geometries.
        """
        if not self.ds:
            return None

        import numpy as np
        
        # 1. Prepare Line
        pts_coords = []
        for p in points:
            if hasattr(p, 'x'): pts_coords.append((p.x(), p.y()))
            else: pts_coords.append(p)
        
        if len(pts_coords) < 2: return None
        
        if shapely is None:
            # This should not happen if QGIS environment is correct as per user
            return {"error": "Shapely library is required for cross-sections."}

        line = LineString(pts_coords)
        bbox = line.bounds # (minx, miny, maxx, maxy)
        
        # 2. Identify candidate cells and calculate intersections
        cell_segments = [] # List of {'d1':, 'd2':, 'idx':, 'cx':, 'cy':}
        
        if self.grid_type == 'structured':
            x_v, y_v = self.ds.variables['x'][:], self.ds.variables['y'][:]
            dx = np.abs(x_v[1]-x_v[0]) if len(x_v) > 1 else 0
            dy = np.abs(y_v[1]-y_v[0]) if len(y_v) > 1 else 0
            
            # Bound query
            ix = np.where((x_v >= bbox[0] - dx) & (x_v <= bbox[2] + dx))[0]
            iy = np.where((y_v >= bbox[1] - dy) & (y_v <= bbox[3] + dy))[0]
            
            for r in iy:
                for c in ix:
                    xc, yc = x_v[c], y_v[r]
                    p = box(xc - dx/2, yc - dy/2, xc + dx/2, yc + dy/2)
                    if line.intersects(p):
                        inter = intersection(line, p)
                        for d1, d2 in self._get_line_segment_ranges(line, inter):
                            cell_segments.append({'d1': d1, 'd2': d2, 'idx': (r, c), 'cx': xc, 'cy': yc})
        else:
            # Vertex Grid
            icv = self.ds.variables['icvert'][:]
            xv = self.ds.variables['xv'][:]
            yv = self.ds.variables['yv'][:]
            nodata = getattr(self.ds.variables['icvert'], 'nodata', -1)
            xc_all, yc_all = self._get_centroids()
            if xc_all is None: return None
            
            # Candidate filter (centroids within bbox + buffer)
            c_mask = (xc_all >= bbox[0] - 1000) & (xc_all <= bbox[2] + 1000) & \
                     (yc_all >= bbox[1] - 1000) & (yc_all <= bbox[3] + 1000)
            cand_indices = np.where(c_mask)[0]
            
            for i in cand_indices:
                v_idx = icv[i][icv[i] != nodata]
                if len(v_idx) < 3: continue
                p = Polygon(zip(xv[v_idx], yv[v_idx]))
                if line.intersects(p):
                    inter = intersection(line, p)
                    for d1, d2 in self._get_line_segment_ranges(line, inter):
                        cell_segments.append({'d1': d1, 'd2': d2, 'idx': int(i), 'cx': xc_all[i], 'cy': yc_all[i]})

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
                    if d.ndim == 2: c = d[sy, sx]
                    elif d.ndim == 3: c = d[:, sy, sx]
                    elif d.ndim == 4: c = d[-1, :, sy, sx]
                    else: return None
                    arr = c.filled(np.nan) if hasattr(c, 'filled') else c
                    return arr[:, yl, xl] if d.ndim > 2 else arr[yl, xl]
                    
                top = get_v('top')
                botm = get_v('botm')
                vals = get_v(variable_name) if variable_name else None
            else:
                idx = np.array(indices_list)
                indices = idx
                
                def get_v(v):
                    if v not in self.ds.variables: return None
                    d = self.ds.variables[v]
                    if d.ndim == 1: c = d[idx]
                    elif d.ndim == 2: c = d[:, idx]
                    elif d.ndim == 3: c = d[-1, :, idx]
                    else: return None
                    return c.filled(np.nan) if hasattr(c, 'filled') else c
                
                top, botm = get_v('top'), get_v('botm')
                vals = get_v(variable_name) if variable_name else None

            # 5. Layer Names
            nm = self.ds.variables.get('layer', [str(i+1) for i in range(botm.shape[0])])[:]
            layer_names = [str(x) for x in nm] if hasattr(nm, '__len__') else [str(i+1) for i in range(botm.shape[0])]

            return {
                "distances": final_dists,
                "top": top,
                "botm": botm,
                "values": vals,
                "indices": indices,
                "cell_x": cell_x,
                "cell_y": cell_y,
                "layer_names": layer_names,
                "num_layers": botm.shape[0]
            }

        except Exception as e:
            import traceback
            return {"error": f"Data extraction failed: {str(e)}\n{traceback.format_exc()}"}

    def export_to_mesh(self, var_name, layer_idx=0, output_path=None):
        """
        Exports a single variable (at a specific layer) to a clean UGRID NetCDF file.
        This provides maximal compatibility with MDAL.
        """
        if not self.ds or var_name not in self.ds.variables:
            return False, "Variable not found"
            
        try:
            import netCDF4
            import numpy as np
            
            # 1. Prepare data slice
            var = self.ds.variables[var_name]
            data = None
            
            # Determine dimensions and slice
            # Expected dims for vertex grid: (time, layer, icell2d) or (layer, icell2d) or (icell2d)
            if 'icell2d' not in var.dimensions:
                return False, f"Variable {var_name} does not have icell2d dimension."
                
            ic_idx = var.dimensions.index('icell2d')
            
            if var.ndim == 1:
                data = var[:]
            elif var.ndim == 2:
                # Assume (layer, icell2d) or (time, icell2d)
                # Slice by layer_idx
                if ic_idx == 1:
                    data = var[layer_idx, :]
                else:
                    data = var[:, layer_idx]
            elif var.ndim == 3:
                # Assume (time, layer, icell2d) - slice to last time, selected layer
                if var.dimensions == ('time', 'layer', 'icell2d'):
                    data = var[-1, layer_idx, :]
                else:
                    # Fallback slice
                    data = var.chunk() # Not sure of generic slice, use simple approach
                    sl = [slice(None)] * var.ndim
                    sl[1] = layer_idx # layer usually 2nd
                    sl[0] = -1 # time usually 1st
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
            data_v = out_ds.createVariable(var_name, 'f4', ('icell2d',))
            # Handle masked arrays
            if isinstance(data, np.ma.MaskedArray):
                data_v[:] = data.filled(np.nan)
            else:
                data_v[:] = data
                
            data_v.mesh = "mesh2d"
            data_v.location = "face"
            data_v.standard_name = var_name
            
            out_ds.Conventions = "UGRID-1.0"
            out_ds.close()
            
            return True, ""
            
        except Exception as e:
            import traceback
            return False, f"Export failed: {str(e)}\n{traceback.format_exc()}"

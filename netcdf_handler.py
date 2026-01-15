try:
    import netCDF4
except ImportError:
    netCDF4 = None

import os

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

    def get_crs(self):
        """Attempts to retrieve the CRS from the NetCDF file."""
        if not self.ds:
            return None
            
        # Common variable names for grid mapping
        crs_vars = ['spatial_ref', 'crs', 'grid_mapping']
        
        for vname in crs_vars:
            if vname in self.ds.variables:
                var = self.ds.variables[vname]
                # Check for WKT or similar attributes
                if hasattr(var, 'crs_wkt'):
                    return var.crs_wkt
                if hasattr(var, 'spatial_ref'):
                    return var.spatial_ref
                if hasattr(var, 'epsg_code'):
                    return f"EPSG:{var.epsg_code}"
                    
        # Check global attributes if no variable found
        if hasattr(self.ds, 'Conventions') and 'CF' in self.ds.Conventions:
             # Try to find grid_mapping attribute on data variables?
             pass
             
        return None

    def get_cross_section_data(self, variable_name, points, num_points=100):
        """
        Extracts cross-section data for a given variable along a polyline.
        points: List of (x, y) tuples or objects with x, y attributes.
        Returns a dict with distances, elevation data, and variable data.
        """
        if not self.ds:
            return None

        # 1. Generate points along the polyline
        import numpy as np
        
        # Ensure points is a list
        if not isinstance(points, list):
             # Legacy support or single point? assume [p1, p2] passed as args?
             # Actually, if the caller changed, we should just assume list.
             # But let's handle if user passed just one point (error)
             return None
             
        if len(points) < 2:
             return None

        xs_list = []
        ys_list = []
        dist_list = []
        
        # Extract coordinates from QgsPoints or tuples
        pts_coords = []
        for p in points:
             if hasattr(p, 'x'): pts_coords.append((p.x(), p.y()))
             else: pts_coords.append(p)
             
        # Calculate total length to allocate num_points
        segment_lengths = []
        total_len = 0.0
        for i in range(len(pts_coords)-1):
             p1 = pts_coords[i]
             p2 = pts_coords[i+1]
             dist = np.sqrt((p2[0]-p1[0])**2 + (p2[1]-p1[1])**2)
             segment_lengths.append(dist)
             total_len += dist
             
        if total_len == 0:
             return None

        current_dist = 0.0
        
        # Collect all points
        # Be careful not to duplicate vertices
        
        for i in range(len(pts_coords)-1):
             seg_len = segment_lengths[i]
             # Number of points for this segment
             n_seg = int(np.ceil(num_points * (seg_len / total_len)))
             if n_seg < 2: n_seg = 2
             
             p1 = pts_coords[i]
             p2 = pts_coords[i+1]
             
             # Linspace for segment
             # endpoint=False unless it's the last segment
             is_last = (i == len(pts_coords) - 2)
             
             s_xs = np.linspace(p1[0], p2[0], n_seg)
             s_ys = np.linspace(p1[1], p2[1], n_seg)
             s_dists = np.linspace(current_dist, current_dist + seg_len, n_seg)
             
             if not is_last:
                  # Remove last point to avoid double counting
                  s_xs = s_xs[:-1]
                  s_ys = s_ys[:-1]
                  s_dists = s_dists[:-1]
                  
             xs_list.append(s_xs)
             ys_list.append(s_ys)
             dist_list.append(s_dists)
             
             current_dist += seg_len
             
        xs = np.concatenate(xs_list)
        ys = np.concatenate(ys_list)
        distances = np.concatenate(dist_list)
        
        # 2. Extract Data
        try:
            if self.grid_type == 'structured':
                x_var = self.ds.variables['x'][:]
                y_var = self.ds.variables['y'][:]
                
                # Robust ABS Argmin
                xi = np.abs(x_var[:, None] - xs[None, :]).argmin(axis=0)
                yi = np.abs(y_var[:, None] - ys[None, :]).argmin(axis=0)

                # Identify out-of-bounds points
                x_min_val, x_max_val = np.min(x_var), np.max(x_var)
                y_min_val, y_max_val = np.min(y_var), np.max(y_var)
                dx = np.abs(x_var[1] - x_var[0]) if len(x_var) > 1 else 1.0
                dy = np.abs(y_var[1] - y_var[0]) if len(y_var) > 1 else 1.0
                
                oob_mask = (xs < x_min_val - dx/2) | (xs > x_max_val + dx/2) | \
                           (ys < y_min_val - dy/2) | (ys > y_max_val + dy/2)

                x_min_idx, x_max_idx = xi.min(), xi.max()
                y_min_idx, y_max_idx = yi.min(), yi.max()
                sl_y = slice(y_min_idx, y_max_idx + 1)
                sl_x = slice(x_min_idx, x_max_idx + 1)
                xi_local = xi - x_min_idx
                yi_local = yi - y_min_idx
                
                def get_data(varname, slice_obj=None):
                    var = self.ds.variables[varname]
                    if slice_obj: data = var[slice_obj]
                    else: data = var[:]
                    if isinstance(data, np.ma.MaskedArray): return data.filled(np.nan)
                    return data.astype(float)

                top_chunk = get_data('top', (sl_y, sl_x))
                botm_chunk = get_data('botm', (slice(None), sl_y, sl_x))
                top = top_chunk[yi_local, xi_local]
                botm = botm_chunk[:, yi_local, xi_local]
                
                vals = None
                if variable_name:
                    var = self.ds.variables[variable_name]
                    if var.ndim == 4:
                         vals_chunk = get_data(variable_name, (-1, slice(None), sl_y, sl_x))
                         vals = vals_chunk[:, yi_local, xi_local]
                    elif var.ndim == 3:
                         vals_chunk = get_data(variable_name, (slice(None), sl_y, sl_x))
                         vals = vals_chunk[:, yi_local, xi_local]
                
                # Store indices for flat plotting
                indices = (yi, xi)

            elif self.grid_type == 'vertex':
                # Vertex/Unstructured grid support
                if 'xc' in self.ds.variables and 'yc' in self.ds.variables:
                    xc = self.ds.variables['xc'][:]
                    yc = self.ds.variables['yc'][:]
                else:
                    # Calculate centroids from vertices
                    if 'icvert' not in self.ds.variables or 'xv' not in self.ds.variables or 'yv' not in self.ds.variables:
                        return {"error": "Vertex grid missing topology (icvert/xv/yv)"}
                    
                    icvert = self.ds.variables['icvert'][:]
                    xv = self.ds.variables['xv'][:]
                    yv = self.ds.variables['yv'][:]
                    
                    # icvert is (icell2d, icv). Nodata values should be ignored.
                    nodata = getattr(self.ds.variables['icvert'], 'nodata', -1)
                    
                    # Calculate mean of valid vertices for each cell
                    xc = np.full(icvert.shape[0], np.nan)
                    yc = np.full(icvert.shape[0], np.nan)
                    
                    for i in range(icvert.shape[0]):
                        v_idx = icvert[i]
                        valid = v_idx[v_idx != nodata]
                        if len(valid) > 0:
                            xc[i] = np.mean(xv[valid])
                            yc[i] = np.mean(yv[valid])
                
                # Nearest neighbor search (Centroids to Cross-section points)
                # Compute distance matrix between centroids (Ncells) and points (Npoints)
                # This could be memory intensive for huge grids, but is robust.
                # Optimized version: find index of min distance
                indices = []
                for p_idx in range(len(xs)):
                    d2 = (xc - xs[p_idx])**2 + (yc - ys[p_idx])**2
                    indices.append(np.nanargmin(d2))
                indices = np.array(indices)
                
                def get_data(varname):
                    var = self.ds.variables[varname]
                    data = var[:]
                    if isinstance(data, np.ma.MaskedArray): return data.filled(np.nan)
                    return data.astype(float)

                top_all = get_data('top')
                botm_all = get_data('botm')
                
                top = top_all[indices]
                botm = botm_all[:, indices]
                
                vals = None
                if variable_name:
                    var = self.ds.variables[variable_name]
                    data_all = get_data(variable_name)
                    if data_all.ndim == 3: # (time, layer, icell2d)
                        vals = data_all[-1, :, indices]
                    elif data_all.ndim == 2: # (layer, icell2d)
                        vals = data_all[:, indices]
                
                # OOB mask for vertex grid (if too far from any centroid, but argmin always finds one)
                # We can check a threshold distance or use the min/max of centroids
                x_min_val, x_max_val = np.nanmin(xc), np.nanmax(xc)
                y_min_val, y_max_val = np.nanmin(yc), np.nanmax(yc)
                # Use a larger buffer for vertex grids as cells are often irregular
                dx = (x_max_val - x_min_val) / np.sqrt(len(xc))
                dy = (y_max_val - y_min_val) / np.sqrt(len(yc))
                oob_mask = (xs < x_min_val - dx) | (xs > x_max_val + dx) | \
                           (ys < y_min_val - dy) | (ys > y_max_val + dy)

            else:
                return {"error": f"Unsupported or unknown grid type: {self.grid_type}"}

            # Final check / Apply OOB
            if top is not None:
                top[oob_mask] = np.nan
            if botm is not None:
                botm[:, oob_mask] = np.nan
            if vals is not None:
                vals[:, oob_mask] = np.nan
            
            return {
                "distances": distances,
                "top": top,
                "botm": botm,
                "values": vals,
                "indices": indices, # Add indices
                "num_layers": botm.shape[0] if botm is not None else 0
            }

        except Exception as e:
            return {"error": str(e)}

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
            xc_in = self.ds.variables.get('xc')
            yc_in = self.ds.variables.get('yc')
            
            if xc_in is not None and yc_in is not None:
                xc_vals = xc_in[:]
                yc_vals = yc_in[:]
            else:
                # Calculate
                xv_data = xv_in[:]
                yv_data = yv_in[:]
                icv_data = icert_in[:]
                nodata = getattr(icert_in, 'nodata', -1)
                xc_vals = np.full(n_cells, np.nan)
                yc_vals = np.full(n_cells, np.nan)
                for i in range(n_cells):
                    v_idx = icv_data[i]
                    valid = v_idx[v_idx != nodata]
                    if len(valid) > 0:
                        xc_vals[i] = np.mean(xv_data[valid])
                        yc_vals[i] = np.mean(yv_data[valid])
            
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

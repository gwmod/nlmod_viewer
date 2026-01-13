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
        # UGRID conventions often use specific topological variables
        keys = self.ds.variables.keys()
        if 'mesh2d_face_nodes' in keys or 'face_nodes' in keys:
            self.grid_type = "vertex"  # Unstructured
            return

        # Check for structured dimensions
        # nlmod structured often has x and y (1D) or x/y as dimensions
        if 'x' in keys and 'y' in keys:
            if self.ds.variables['x'].ndim == 1 and self.ds.variables['y'].ndim == 1:
                self.grid_type = "structured"
                return
        
        # Check standard CF lat/lon
        if 'lat' in keys and 'lon' in keys:
             self.grid_type = "structured"
             return

        # Fallback check on dimensions
        dims = self.ds.dimensions.keys()
        if 'x' in dims and 'y' in dims:
            self.grid_type = "structured"
            return
            
        # MODFLOW 6 Structured
        if 'row' in dims and 'column' in dims:
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
            'crs', 'grid_mapping', 'spatial_ref'
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
            
            # Strategy 0: Check global attribute 'extent' (nlmod convention)
            if hasattr(self.ds, 'extent'):
                # Expected format: [xmin, xmax, ymin, ymax]
                ext = self.ds.extent
                if len(ext) == 4:
                     QgsMessageLog.logMessage(f"NLMOD: Found extent via attribute: {ext}", "NlmodInspector", Qgis.Info)
                     return tuple(ext)
            
            x_var = None
            y_var = None
            
            # Strategy 1: Check 'coordinates' attribute (CF Convention)
            if var_name and var_name in self.ds.variables:
                var = self.ds.variables[var_name]
                if hasattr(var, 'coordinates'):
                    # e.g. "lat lon" or "y x"
                    coord_names = var.coordinates.split()
                    # Try to identify which is X and which is Y
                    # Heuristic: X usually has longer range/bounds or check attributes
                    if len(coord_names) >= 2:
                        candidates = [self.ds.variables[n] for n in coord_names if n in self.ds.variables]
                        # Assign based on units or standard_name if possible
                        # For now, simplistic: if one is 'x' or 'lon', use it.
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
                return None
                
            x = x_var[:]
            y = y_var[:]
            
            if len(x) < 2 or len(y) < 2:
                QgsMessageLog.logMessage("NLMOD: Coordinate arrays too short.", "NlmodInspector", Qgis.Warning)
                return None
                
            # Determine cell sizes (dx, dy)
            dx = np.abs(x[1] - x[0])
            dy = np.abs(y[1] - y[0])
            
            # If simplistic uniform:
            # Min is center - dx/2
            xmin = np.min(x) - dx/2
            xmax = np.max(x) + dx/2
            ymin = np.min(y) - dy/2
            ymax = np.max(y) + dy/2
            
            return (xmin, xmax, ymin, ymax)
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
        
        # 2. Get Coordinate Arrays (Assuming structured grid for now)
        if self.grid_type != 'structured':
            return None 
            
        try:
            x_var = self.ds.variables['x'][:]
            y_var = self.ds.variables['y'][:]
            
            # Vectorized Nearest Neighbor Search
            # Find closest index for each point in xs/ys
            # Uses broadcasting: |coords[:, None] - points[None, :]|^2 minimized
            # x_var is (Nx,), xs is (Npoints,)
            # We want index for each point.
            
            # Optimization: If sorted, use searchsorted.
            # Check sort order
            is_sorted_x = (x_var[-1] > x_var[0])
            is_sorted_y = (y_var[-1] > y_var[0])
            
            if is_sorted_x:
                xi = np.searchsorted(x_var, xs)
                xi = np.clip(xi, 0, len(x_var)-1)
                # Fix nearest: check neighbors
                # (searchsorted gives insertion point i where a[i-1] <= v < a[i])
                # We need closer of i-1 or i
                # Simplified: abs argmin is robust but potentially slower. 
                # Given small N (100) and reasonable grid size, abs argmin is fine.
                pass
            
            # Robust ABS Argmin (works for ascending, descending, or unordered)
            # Memory usage: GridDim * NumPoints * float64. 
            # E.g. 5000 * 100 * 8 = 4MB. Safe.
            xi = np.abs(x_var[:, None] - xs[None, :]).argmin(axis=0)
            yi = np.abs(y_var[:, None] - ys[None, :]).argmin(axis=0)

            # 3. Extract Data (Bounding Box Optimization)
            # Instead of looping or reading fully, read the bounding range
            x_min, x_max = xi.min(), xi.max()
            y_min, y_max = yi.min(), yi.max()
            
            # Slices (inclusive end for numpy slice requires +1)
            # NetCDF4 supports this efficient reading
            sl_y = slice(y_min, y_max + 1)
            sl_x = slice(x_min, x_max + 1)
            
            # Local indices relative to the chunk
            xi_local = xi - x_min
            yi_local = yi - y_min
            
            # Check if variables exist
            if 'top' not in self.ds.variables or 'botm' not in self.ds.variables:
                return {"error": "Dataset missing 'top' or 'botm'."}

            # Read chunks (returns multidimensional array)
            # top: (y, x) -> chunk (sub_y, sub_x)
            top_chunk = self.ds.variables['top'][sl_y, sl_x]
            # botm: (nlay, y, x) -> chunk (nlay, sub_y, sub_x)
            botm_chunk = self.ds.variables['botm'][:, sl_y, sl_x]
            
            # Fancy Indexing to get points along line
            # top_chunk[yi_local, xi_local] returns (Npoints,)
            top = top_chunk[yi_local, xi_local]
            
            # botm_chunk: (L, Y, X). We want (L, Npoints).
            # botm_chunk[:, yi_local, xi_local] works in Numpy
            botm = botm_chunk[:, yi_local, xi_local]

            # Variable extraction
            vals = None
            if variable_name:
                var = self.ds.variables[variable_name]
                if var.ndim == 4:
                     # (time, layer, y, x)
                     # Read chunk for last time step
                     vals_chunk = var[-1, :, sl_y, sl_x]
                     vals = vals_chunk[:, yi_local, xi_local]
                     
                elif var.ndim == 3:
                     # (layer, y, x)
                     vals_chunk = var[:, sl_y, sl_x]
                     vals = vals_chunk[:, yi_local, xi_local]
            
            return {
                "distances": distances,
                "top": top,
                "botm": botm,
                "values": vals,
                "num_layers": botm.shape[0]
            }

        except Exception as e:
            return {"error": str(e)}

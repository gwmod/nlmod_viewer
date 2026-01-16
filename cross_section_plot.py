from qgis.PyQt import QtWidgets, QtCore, QtGui
import pyqtgraph as pg
import numpy as np

try:
    from pyqtgraph import PColorMeshItem
except ImportError:
    PColorMeshItem = None

class SettingsDialog(QtWidgets.QDialog):
    def __init__(self, parent=None, show_layer_boundaries=False, show_cell_boundaries=False):
        super().__init__(parent)
        self.setWindowTitle("Cross Section Settings")
        layout = QtWidgets.QVBoxLayout(self)
        
        self.chk_boundaries = QtWidgets.QCheckBox("Show Layer Boundaries")
        self.chk_boundaries.setChecked(show_layer_boundaries)
        layout.addWidget(self.chk_boundaries)

        self.chk_cell_boundaries = QtWidgets.QCheckBox("Show Cell Boundaries")
        self.chk_cell_boundaries.setChecked(show_cell_boundaries)
        layout.addWidget(self.chk_cell_boundaries)
        
        btns = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel,
            QtCore.Qt.Horizontal, self)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

class CrossSectionPlotWindow(QtWidgets.QDockWidget):
    variable_changed = QtCore.pyqtSignal(str, str) # item_id, new_var_name
    cursor_moved = QtCore.pyqtSignal(str, float) # item_id, distance along cross-section
    cursor_left = QtCore.pyqtSignal()
    range_changed = QtCore.pyqtSignal()
    settings_changed = QtCore.pyqtSignal()
    def __init__(self, data, variable_name, parent=None, vertex_distances=None, 
                 item_id=None, all_vars=None, data_fetcher=None, label="A", points=None,
                 z_range=None, v_range=None, show_layers=True, show_cells=False):
        super().__init__(parent)
        self.item_id = item_id # Store for signaling
        self.data_fetcher = data_fetcher
        self.all_vars = all_vars or [variable_name]
        self.current_var = variable_name
        self.cs_label = label
        self.points = points
        self.show_layer_boundaries = show_layers 
        self.show_cell_boundaries = show_cells
        
        self.setWindowTitle(f"Cross Section {self.cs_label}: {variable_name}")
        self.setAllowedAreas(QtCore.Qt.AllDockWidgetAreas)
        
        # Central Widget & Layout
        central = QtWidgets.QWidget()
        self.setWidget(central)
        layout = QtWidgets.QVBoxLayout(central)
        
        # Tools Layout
        tools_layout = QtWidgets.QHBoxLayout()
        
        # Variable Selection
        tools_layout.addWidget(QtWidgets.QLabel("Variable:"))
        self.var_combo = QtWidgets.QComboBox()
        self.var_combo.addItems(self.all_vars)
        if self.current_var in self.all_vars:
            self.var_combo.setCurrentText(self.current_var)
        self.var_combo.currentTextChanged.connect(self.change_variable)
        tools_layout.addWidget(self.var_combo)
        
        tools_layout.addSpacing(20)
        
        tools_layout.addWidget(QtWidgets.QLabel("Z-Range (m):"))
        
        self.z_min_spin = QtWidgets.QDoubleSpinBox()
        self.z_min_spin.setRange(-10000, 10000)
        self.z_min_spin.setDecimals(1)
        self.z_min_spin.valueChanged.connect(self.update_z_range)
        self.z_min_spin.valueChanged.connect(self.range_changed.emit)
        tools_layout.addWidget(self.z_min_spin)
        
        tools_layout.addWidget(QtWidgets.QLabel(" to "))
        
        self.z_max_spin = QtWidgets.QDoubleSpinBox()
        self.z_max_spin.setRange(-10000, 10000)
        self.z_max_spin.setDecimals(1)
        self.z_max_spin.valueChanged.connect(self.update_z_range)
        self.z_max_spin.valueChanged.connect(self.range_changed.emit)
        tools_layout.addWidget(self.z_max_spin)
        
        # Spacer
        tools_layout.addSpacing(20)
        
        # Data Range
        tools_layout.addWidget(QtWidgets.QLabel("Data Range:"))
        
        self.v_min_spin = QtWidgets.QDoubleSpinBox()
        self.v_min_spin.setRange(-1e6, 1e6)
        self.v_min_spin.setDecimals(4)
        self.v_min_spin.valueChanged.connect(self.apply_data_range)
        self.v_min_spin.valueChanged.connect(self.range_changed.emit)
        tools_layout.addWidget(self.v_min_spin)
        
        tools_layout.addWidget(QtWidgets.QLabel(" to "))
        
        self.v_max_spin = QtWidgets.QDoubleSpinBox()
        self.v_max_spin.setRange(-1e6, 1e6)
        self.v_max_spin.setDecimals(4)
        self.v_max_spin.valueChanged.connect(self.apply_data_range)
        self.v_max_spin.valueChanged.connect(self.range_changed.emit)
        tools_layout.addWidget(self.v_max_spin)
        
        tools_layout.addStretch()
        
        self.reset_btn = QtWidgets.QPushButton("Reset to Data")
        self.reset_btn.clicked.connect(self.reset_ranges)
        tools_layout.addWidget(self.reset_btn)
        
        # Settings Button
        self.settings_btn = QtWidgets.QPushButton("Settings...")
        self.settings_btn.clicked.connect(self.show_settings)
        tools_layout.addWidget(self.settings_btn)
        
        layout.addLayout(tools_layout)
        
        # Picking Info Label
        self.info_label = QtWidgets.QLabel("Click in plot to see cell info")
        self.info_label.setStyleSheet("font-weight: bold; color: #444; background: #f0f0f0; padding: 4px; border-radius: 4px;")
        layout.addWidget(self.info_label)
        
        # Store data for re-rendering
        self.data = data
        self.colorbar = None
        self.vertex_lines = []
        self.vertex_distances = vertex_distances
        
        # Plot Widget
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground('w')
        
        # Set axis colors to black for visibility on white
        styles = {'color': 'k', 'font-size': '10pt'}
        self.plot_widget.getPlotItem().getAxis('left').setPen('k')
        self.plot_widget.getPlotItem().getAxis('left').setTextPen('k')
        self.plot_widget.getPlotItem().getAxis('bottom').setPen('k')
        self.plot_widget.getPlotItem().getAxis('bottom').setTextPen('k')
        
        layout.addWidget(self.plot_widget)
        self.plot_widget.setLabel('left', 'Elevation', units='m', **styles)
        self.plot_widget.setLabel('bottom', 'Distance', units='m', **styles)
        self.plot_widget.showGrid(x=False, y=False)
        
        # Add Mouse Handlers
        self.plot_widget.scene().sigMouseClicked.connect(self.on_plot_clicked)
        self.plot_widget.scene().sigMouseMoved.connect(self.on_mouse_moved)
        
        # Render Data
        v_min, v_max = (v_range[0], v_range[1]) if v_range else (None, None)
        self.render_data(data, v_min=v_min, v_max=v_max, vertex_distances=vertex_distances)
        
        # Initialize Range Settings
        self.init_ranges(data, z_range=z_range)

    def init_ranges(self, data, z_range=None):
        # Calculate elevation extremes from top and botm
        all_z = []
        if 'top' in data: all_z.append(data['top'])
        if 'botm' in data: all_z.append(data['botm'])
        
        if all_z:
            merged = np.concatenate([np.atleast_1d(z).flatten() for z in all_z])
            valid_z = merged[~np.isnan(merged)]
            if len(valid_z) > 0:
                self.data_z_min = np.nanmin(valid_z)
                self.data_z_max = np.nanmax(valid_z)
                
                # Add some padding
                margin = (self.data_z_max - self.data_z_min) * 0.1
                if margin == 0: margin = 1.0
                
                self.z_min_spin.blockSignals(True)
                self.z_max_spin.blockSignals(True)
                
                if z_range:
                    self.z_min_spin.setValue(z_range[0])
                    self.z_max_spin.setValue(z_range[1])
                else:
                    self.z_min_spin.setValue(self.data_z_min - margin)
                    self.z_max_spin.setValue(self.data_z_max + margin)
                    
                self.z_min_spin.blockSignals(False)
                self.z_max_spin.blockSignals(False)
                
                self.update_z_range()

    def update_z_range(self):
        z_min = self.z_min_spin.value()
        z_max = self.z_max_spin.value()
        if z_max > z_min:
            self.plot_widget.setYRange(z_min, z_max)
            self.range_changed.emit()

    def reset_elevation_range(self):
        if hasattr(self, 'data_z_min'):
            margin = (self.data_z_max - self.data_z_min) * 0.1
            if margin == 0: margin = 1.0
            
            self.z_min_spin.blockSignals(True)
            self.z_max_spin.blockSignals(True)
            self.z_min_spin.setValue(self.data_z_min - margin)
            self.z_max_spin.setValue(self.data_z_max + margin)
            self.z_min_spin.blockSignals(False)
            self.z_max_spin.blockSignals(False)
            self.update_z_range()

    def reset_data_range(self):
        valid_vals = self.data['values'][~np.isnan(self.data['values'])]
        if len(valid_vals) > 0:
            v_min = np.nanmin(valid_vals)
            v_max = np.nanmax(valid_vals)
            
            self.v_min_spin.blockSignals(True)
            self.v_max_spin.blockSignals(True)
            self.v_min_spin.setValue(v_min)
            self.v_max_spin.setValue(v_max)
            self.v_min_spin.blockSignals(False)
            self.v_max_spin.blockSignals(False)
            self.apply_data_range()

    def reset_ranges(self):
        self.reset_elevation_range()
        self.reset_data_range()

    def apply_data_range(self):
        v_min = self.v_min_spin.value()
        v_max = self.v_max_spin.value()
        if v_max > v_min:
            # Re-render with new limits
            self.render_data(self.data, v_min, v_max)

    def show_settings(self):
        dlg = SettingsDialog(self, 
                             show_layer_boundaries=self.show_layer_boundaries, 
                             show_cell_boundaries=self.show_cell_boundaries)
        if dlg.exec_():
            new_layer_boundaries = dlg.chk_boundaries.isChecked()
            new_cell_boundaries = dlg.chk_cell_boundaries.isChecked()
            
            changed = False
            if new_layer_boundaries != self.show_layer_boundaries:
                self.show_layer_boundaries = new_layer_boundaries
                changed = True
            if new_cell_boundaries != self.show_cell_boundaries:
                self.show_cell_boundaries = new_cell_boundaries
                changed = True
                
            if changed:
                # Clear info
                self.info_label.setText("Click in plot to see cell info")
                # Re-render
                self.render_data(self.data, vertex_distances=self.vertex_distances)
                # Save
                self.settings_changed.emit()

    def change_variable(self, var_name):
        if not self.data_fetcher:
            return
            
        try:
            # Fetch new data
            new_data = self.data_fetcher(var_name, self.points)
            if new_data:
                self.data = new_data
                self.current_var = var_name
                self.setWindowTitle(f"Cross Section {self.cs_label}: {var_name}")
                
                # Clear info
                self.info_label.setText("Click in plot to see cell info")
                
                # Re-render (using auto-range for the first time on new var)
                if hasattr(self, '_first_render_done'):
                    delattr(self, '_first_render_done')
                
                self.render_data(self.data, vertex_distances=self.vertex_distances)
                # Keep Z range per user request
                self.reset_data_range() 
                
                # Notify dock widget
                if self.item_id:
                    self.variable_changed.emit(self.item_id, var_name)
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Data Error", f"Failed to fetch data for {var_name}: {e}")

    def on_mouse_moved(self, pos):
        if not self.plot_widget.plotItem.sceneBoundingRect().contains(pos):
            self.cursor_left.emit()
            return
            
        mouse_point = self.plot_widget.plotItem.vb.mapSceneToView(pos)
        dist = mouse_point.x()
        
        # Check if within data range
        if 'distances' in self.data and len(self.data['distances']) > 0:
            min_d = self.data['distances'].min()
            max_d = self.data['distances'].max()
            if min_d <= dist <= max_d:
                self.cursor_moved.emit(self.item_id, dist)
            else:
                self.cursor_left.emit()
        else:
            self.cursor_left.emit()

    def leaveEvent(self, event):
        self.cursor_left.emit()
        super().leaveEvent(event)

    def on_plot_clicked(self, event):
        if event.button() != QtCore.Qt.LeftButton:
            return
            
        pos = event.scenePos()
        if not self.plot_widget.plotItem.sceneBoundingRect().contains(pos):
            return
            
        mouse_point = self.plot_widget.plotItem.vb.mapSceneToView(pos)
        x_click = mouse_point.x()
        z_click = mouse_point.y()
        
        # Find the segment index in distances
        # dists has entries [entry0, exit0, entry1, exit1, ...]
        dists = self.data['distances']
        if len(dists) == 0: return
        idx = np.searchsorted(dists, x_click) - 1
        idx = max(0, min(idx, len(dists) - 2))
        
        # Consistent with flat rendering, we want properties from the start of the cell segment
        seg_start_idx = idx - (idx % 2)
        
        # Find the layer
        top = self.data['top'][seg_start_idx]
        botm = self.data['botm'][:, seg_start_idx]
        num_layers = self.data['num_layers']
        
        found_layer = -1
        for i in range(num_layers):
            l_top = top if i == 0 else botm[i-1]
            l_bot = botm[i]
            
            if np.isnan(l_top) or np.isnan(l_bot): continue
            
            # Check if z_click is between l_top and l_bot
            # Keep in mind coordinate system (usually positive is up)
            z_min = min(l_top, l_bot)
            z_max = max(l_top, l_bot)
            if z_min <= z_click <= z_max:
                found_layer = i
                break
        
        if found_layer != -1:
            val = self.data['values'][found_layer, seg_start_idx]
            cx = self.data['cell_x'][seg_start_idx]
            cy = self.data['cell_y'][seg_start_idx]
            layer_name = self.data['layer_names'][found_layer]
            
            val_str = f"{val:.4f}" if not np.isnan(val) else "NaN"
            self.info_label.setText(
                f"X: {cx:.1f}, Y: {cy:.1f}, Layer: {layer_name}, Value: {val_str}"
            )
        else:
            self.info_label.setText("No cell at click location")

    def render_data(self, data, v_min=None, v_max=None, vertex_distances=None):
        """Update the plot with new data and manage internal state."""
        self.data = data
        if vertex_distances is not None:
            self.vertex_distances = vertex_distances
            
        # Clear previous items
        self.plot_widget.clear()
        if self.colorbar:
            self.plot_widget.plotItem.layout.removeItem(self.colorbar)
            self.colorbar = None
        
        self.vertex_lines = []
            
        # Unpack
        dists = data['distances']
        top = data['top']
        botm = data['botm']
        vals = data['values']
        
        # Color Map
        cmap = pg.colormap.get('turbo')
        
        # Data Range
        valid_vals = vals[~np.isnan(vals)]
        if len(valid_vals) == 0:
            return
            
        if v_min is None:
            if hasattr(self, '_first_render_done'):
                v_min = self.v_min_spin.value()
            else:
                v_min = np.nanmin(valid_vals)
                
        if v_max is None:
            if hasattr(self, '_first_render_done'):
                v_max = self.v_max_spin.value()
            else:
                v_max = np.nanmax(valid_vals)
        
        # Update spinboxes if this is first render
        if not hasattr(self, '_first_render_done'):
            self.v_min_spin.blockSignals(True)
            self.v_max_spin.blockSignals(True)
            self.v_min_spin.setValue(v_min)
            self.v_max_spin.setValue(v_max)
            self.v_min_spin.blockSignals(False)
            self.v_max_spin.blockSignals(False)
            self._first_render_done = True
        
        # Optimized Rendering using PColorMeshItem if available
        if PColorMeshItem is not None:
            num_layers = data['num_layers']
            num_points = len(dists)
            
            # Construct Mesh Coordinates
            # X: (Layers+1, Points)
            # Y: (Layers+1, Points)
            x_mesh = np.tile(dists, (num_layers + 1, 1))
            y_mesh = np.zeros((num_layers + 1, num_points))
            y_mesh[0, :] = top
            y_mesh[1:, :] = botm
            
            # Data: (Layers, Points-1)
            # We use the value from the start of each interval
            z_mesh = vals[:, :-1]
            
            # Apply "Flat Cells" logic to mesh geometry
            if data.get('indices') is not None:
                indices = data['indices']
                if isinstance(indices, tuple): # structured
                    idx_combined = indices[0].astype(np.int64) * 1000000 + indices[1].astype(np.int64)
                else:
                    idx_combined = indices
                
                # Identify blocks of identical cell indices
                changes = np.where(idx_combined[1:] != idx_combined[:-1])[0] + 1
                starts = np.concatenate(([0], changes))
                ends = np.concatenate((changes, [num_points]))
                
                # For each cell block, make top/bottom flat
                for s, e in zip(starts, ends):
                    if e > s:
                        # Use elevation from start of cell block
                        y_mesh[:, s:e] = y_mesh[:, s][:, None]
            
            # Create PColorMeshItem
            self.dataset_item = PColorMeshItem(
                x_mesh, y_mesh, z_mesh,
                colorMap=cmap,
                levels=(v_min, v_max),
                antialiasing=False
            )
            self.plot_widget.addItem(self.dataset_item)
            
            # Add Optional Layer Boundaries using PlotCurveItem (very fast)
            if self.show_layer_boundaries:
                pen = pg.mkPen('k', width=1)
                for i in range(num_layers + 1):
                    # Filter NaNs for PlotCurveItem
                    valid = ~np.isnan(y_mesh[i, :])
                    if np.any(valid):
                        line = pg.PlotCurveItem(dists[valid], y_mesh[i, valid], pen=pen)
                        self.plot_widget.addItem(line)

            # Add Optional Cell Boundaries (Vertical lines)
            if self.show_cell_boundaries and data.get('indices') is not None:
                pen = pg.mkPen('k', width=1)
                indices = data['indices']
                if isinstance(indices, tuple): # structured
                    idx_combined = indices[0].astype(np.int64) * 1000000 + indices[1].astype(np.int64)
                else:
                    idx_combined = indices
                
                # Find indices where cell changes
                changes = np.where(idx_combined[1:] != idx_combined[:-1])[0] + 1
                for ch in changes:
                    d = dists[ch]
                    # Vertical line from top to bottom
                    z_t = top[ch]
                    z_b = botm[-1, ch]
                    if not np.isnan(z_t) and not np.isnan(z_b):
                        line = pg.PlotCurveItem([d, d], [z_t, z_b], pen=pen)
                        self.plot_widget.addItem(line)
        else:
            # Fallback to slower custom Item
            self.dataset_item = CrossSectionMeshItem(
                dists, top, botm, vals, cmap, (v_min, v_max), 
                show_layer_boundaries=self.show_layer_boundaries,
                show_cell_boundaries=self.show_cell_boundaries,
                indices=data.get('indices')
            )
            self.plot_widget.addItem(self.dataset_item)
        
        # Add Vertical Vertex Lines (the A, B, C... points)
        if vertex_distances:
            for d in vertex_distances:
                line = pg.InfiniteLine(pos=d, angle=90, pen=pg.mkPen('k', style=QtCore.Qt.DashLine))
                self.plot_widget.addItem(line)
                self.vertex_lines.append(line)

        # Add Colorbar
        # Create ColorBarItem
        self.colorbar = pg.ColorBarItem(
            values=(v_min, v_max),
            colorMap=cmap,
            width=15,
            interactive=False
        )
        
        # Add directly to plot layout (row 2, column 3 = right side)
        self.plot_widget.plotItem.layout.addItem(self.colorbar, 2, 3)
        
        # Style the colorbar axis
        self.colorbar.getAxis('right').setPen('k')
        self.colorbar.getAxis('right').setTextPen('k')


class CrossSectionMeshItem(pg.GraphicsObject):
    def __init__(self, dists, top, botm, vals, cmap, val_range=None, 
                 show_layer_boundaries=False, show_cell_boundaries=False, 
                 indices=None):
        super().__init__()
        self.dists = dists
        self.top = top
        self.botm = botm
        self.vals = vals
        self.cmap = cmap
        self.val_range_override = val_range
        self.show_layer_boundaries = show_layer_boundaries
        self.show_cell_boundaries = show_cell_boundaries
        self.indices = indices
        self.picture = None
        self._generate_picture()
        
    def _generate_picture(self):
        self.picture = QtGui.QPicture()
        p = QtGui.QPainter(self.picture)
        p.setPen(pg.mkPen(None))
        
        # Calculate ranges
        if self.val_range_override:
            min_val, max_val = self.val_range_override
        else:
            valid_vals = self.vals[~np.isnan(self.vals)]
            if len(valid_vals) == 0:
                p.end()
                return
            min_val = np.nanmin(valid_vals)
            max_val = np.nanmax(valid_vals)
            
        val_range = max_val - min_val if max_val > min_val else 1.0
        
        num_layers = self.botm.shape[0]
        num_points = len(self.dists)
        
        # Optimization: Quantize colors into bins
        n_bins = 256
        paths = [QtGui.QPainterPath() for _ in range(n_bins)]
        
        # Pre-calculate colors
        colors = [self.cmap.map(i / (n_bins - 1)) for i in range(n_bins)]
        
        # Boundary line path
        boundary_path = QtGui.QPainterPath() if self.show_layer_boundaries else None
        cell_boundary_path = QtGui.QPainterPath() if self.show_cell_boundaries else None

        for i in range(num_layers):
            if i == 0: l_top_all = self.top
            else: l_top_all = self.botm[i-1]
            l_bot_all = self.botm[i]
            
            j = 0
            while j < num_points - 1:
                # Use flat cell rendering when indices are available
                if self.indices is not None:
                    # Find span of current cell
                    if isinstance(self.indices, tuple): # structured (yi, xi)
                        curr_idx = (self.indices[0][j], self.indices[1][j])
                    else: # vertex
                        curr_idx = self.indices[j]
                    
                    j_end = j
                    while j_end < num_points - 2:
                        if isinstance(self.indices, tuple):
                            next_idx = (self.indices[0][j_end+1], self.indices[1][j_end+1])
                        else:
                            next_idx = self.indices[j_end+1]
                        
                        if next_idx != curr_idx:
                            break
                        j_end += 1
                    
                    # Properties from start of span
                    val = float(self.vals[i, j])
                    z_t = l_top_all[j]
                    z_b = l_bot_all[j]
                    
                    if not np.isnan(val) and not np.isnan(z_t) and not np.isnan(z_b):
                        # Bin index
                        norm = (val - min_val) / val_range
                        bin_idx = int(norm * (n_bins - 1))
                        bin_idx = max(0, min(n_bins-1, bin_idx))
                        
                        # Flat rectangle
                        # Note: we use dists[j_end+1] to close the gap
                        poly = QtGui.QPolygonF([
                            QtCore.QPointF(self.dists[j], z_t),
                            QtCore.QPointF(self.dists[j_end+1], z_t),
                            QtCore.QPointF(self.dists[j_end+1], z_b),
                            QtCore.QPointF(self.dists[j], z_b)
                        ])
                        paths[bin_idx].addPolygon(poly)
                        
                        if boundary_path:
                            boundary_path.moveTo(self.dists[j], z_t)
                            boundary_path.lineTo(self.dists[j_end+1], z_t)
                            boundary_path.moveTo(self.dists[j], z_b)
                            boundary_path.lineTo(self.dists[j_end+1], z_b)
                        
                        if cell_boundary_path and j > 0:
                            # Draw vertical line at start of cell
                            cell_boundary_path.moveTo(self.dists[j], z_t)
                            cell_boundary_path.lineTo(self.dists[j], z_b)
                        if cell_boundary_path and j_end == num_points - 2:
                            # Final vertical line
                            cell_boundary_path.moveTo(self.dists[j_end+1], z_t)
                            cell_boundary_path.lineTo(self.dists[j_end+1], z_b)
                    
                    j = j_end + 1
                    
                else:
                    # Fallback: simple interpolated rendering without indices
                    val = float(self.vals[i, j])
                    if not np.isnan(val):
                        # Skip if geometry is NaN (Out of Domain)
                        z_t1, z_t2 = l_top_all[j], l_top_all[j+1]
                        z_b1, z_b2 = l_bot_all[j], l_bot_all[j+1]
                        
                        if not (np.isnan(z_t1) or np.isnan(z_t2) or np.isnan(z_b1) or np.isnan(z_b2)):
                            # Bin index
                            norm = (val - min_val) / val_range
                            bin_idx = int(norm * (n_bins - 1))
                            bin_idx = max(0, min(n_bins-1, bin_idx))
                            
                            # Slanted quad
                            poly = QtGui.QPolygonF([
                                QtCore.QPointF(self.dists[j], z_t1),
                                QtCore.QPointF(self.dists[j+1], z_t2),
                                QtCore.QPointF(self.dists[j+1], z_b2),
                                QtCore.QPointF(self.dists[j], z_b1)
                            ])
                            paths[bin_idx].addPolygon(poly)
                            
                            if boundary_path:
                                boundary_path.moveTo(self.dists[j], z_t1)
                                boundary_path.lineTo(self.dists[j+1], z_t2)
                                boundary_path.moveTo(self.dists[j], z_b1)
                                boundary_path.lineTo(self.dists[j+1], z_b2)
                    j += 1
        
        # Draw paths
        for bin_idx, path in enumerate(paths):
            if path.isEmpty(): continue
            p.setBrush(pg.mkBrush(colors[bin_idx]))
            p.drawPath(path)
            
        if boundary_path and not boundary_path.isEmpty():
            p.setBrush(pg.mkBrush(None))
            p.setPen(pg.mkPen('k', width=1))
            p.drawPath(boundary_path)

        if cell_boundary_path and not cell_boundary_path.isEmpty():
            p.setBrush(pg.mkBrush(None))
            p.setPen(pg.mkPen('k', width=1))
            p.drawPath(cell_boundary_path)
        
        p.end()
        
    def paint(self, p, *args):
        if self.picture:
            self.picture.play(p)
    
    def boundingRect(self):
        if self.picture:
            return QtCore.QRectF(self.picture.boundingRect())
        return QtCore.QRectF()

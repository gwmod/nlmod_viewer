from qgis.PyQt import QtWidgets, QtCore, QtGui
from qgis.core import QgsStyle
import pyqtgraph as pg
import numpy as np

try:
    from pyqtgraph import PColorMeshItem
except ImportError:
    PColorMeshItem = None

class SettingsDialog(QtWidgets.QDialog):
    def __init__(self, parent=None, show_layer_boundaries=False, show_cell_boundaries=False, show_layer_names=False,
                 v_min=None, v_max=None, use_log=False, cmap_name='Turbo', invert_cmap=False):
        super().__init__(parent)
        self.setWindowTitle("Cross Section Settings")
        layout = QtWidgets.QVBoxLayout(self)
        
        # Appearance Group
        appearance_group = QtWidgets.QGroupBox("Appearance")
        app_layout = QtWidgets.QVBoxLayout(appearance_group)
        self.chk_boundaries = QtWidgets.QCheckBox("Show Layer Boundaries")
        self.chk_boundaries.setChecked(show_layer_boundaries)
        app_layout.addWidget(self.chk_boundaries)

        self.chk_cell_boundaries = QtWidgets.QCheckBox("Show Cell Boundaries")
        self.chk_cell_boundaries.setChecked(show_cell_boundaries)
        app_layout.addWidget(self.chk_cell_boundaries)

        self.chk_layer_names = QtWidgets.QCheckBox("Show Layer Names")
        self.chk_layer_names.setChecked(show_layer_names)
        app_layout.addWidget(self.chk_layer_names)
        layout.addWidget(appearance_group)
        
        # Color Scale Group
        scale_group = QtWidgets.QGroupBox("Color Scale")
        scale_layout = QtWidgets.QVBoxLayout(scale_group)
        
        range_layout = QtWidgets.QHBoxLayout()
        range_layout.addWidget(QtWidgets.QLabel("Data Range:"))
        self.v_min_spin = QtWidgets.QDoubleSpinBox()
        self.v_min_spin.setRange(-1e9, 1e9)
        self.v_min_spin.setDecimals(4)
        if v_min is not None: self.v_min_spin.setValue(v_min)
        range_layout.addWidget(self.v_min_spin)
        
        range_layout.addWidget(QtWidgets.QLabel(" to "))
        
        self.v_max_spin = QtWidgets.QDoubleSpinBox()
        self.v_max_spin.setRange(-1e9, 1e9)
        self.v_max_spin.setDecimals(4)
        if v_max is not None: self.v_max_spin.setValue(v_max)
        range_layout.addWidget(self.v_max_spin)
        scale_layout.addLayout(range_layout)
        
        self.chk_log = QtWidgets.QCheckBox("Use Log Scale")
        self.chk_log.setChecked(use_log)
        scale_layout.addWidget(self.chk_log)
        
        cmap_layout = QtWidgets.QHBoxLayout()
        cmap_layout.addWidget(QtWidgets.QLabel("Colormap:"))
        self.cmap_combo = QtWidgets.QComboBox()
        self.cmap_combo.setIconSize(QtCore.QSize(80, 16))
        
        # Manually populate with QGIS ramps and previews
        style = QgsStyle.defaultStyle()
        ramp_names = style.colorRampNames()
        icon_w, icon_h = 80, 16
        for name in ramp_names:
            ramp = style.colorRamp(name)
            if ramp:
                try:
                    # Manually create preview pixmap as the API method is not always available
                    pixmap = QtGui.QPixmap(icon_w, icon_h)
                    painter = QtGui.QPainter(pixmap)
                    for i in range(icon_w):
                        qcolor = ramp.color(i / (icon_w - 1))
                        painter.setPen(qcolor)
                        painter.drawLine(i, 0, i, icon_h)
                    painter.end()
                    icon = QtGui.QIcon(pixmap)
                    self.cmap_combo.addItem(icon, name)
                except Exception:
                    self.cmap_combo.addItem(name)
        
        if cmap_name:
            idx = self.cmap_combo.findText(cmap_name)
            if idx >= 0:
                self.cmap_combo.setCurrentIndex(idx)
        else:
            # Try to default to Turbo
            idx = self.cmap_combo.findText('Turbo')
            if idx >= 0:
                self.cmap_combo.setCurrentIndex(idx)
            
        cmap_layout.addWidget(self.cmap_combo)
        
        self.chk_invert = QtWidgets.QCheckBox("Invert")
        self.chk_invert.setChecked(invert_cmap)
        cmap_layout.addWidget(self.chk_invert)
        
        scale_layout.addLayout(cmap_layout)
        
        layout.addWidget(scale_group)
        
        btns = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel,
            QtCore.Qt.Horizontal, self)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)


class LayerSelectionDialog(QtWidgets.QDialog):
    def __init__(self, layer_names, selected_indices, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select Cross-Section Layers")
        self.resize(320, 420)
        layout = QtWidgets.QVBoxLayout(self)

        layout.addWidget(QtWidgets.QLabel("Select layers to plot for this cross-section:"))

        self.list_widget = QtWidgets.QListWidget()
        self.list_widget.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        layout.addWidget(self.list_widget)

        selected_set = set(selected_indices)
        for i, name in enumerate(layer_names):
            item = QtWidgets.QListWidgetItem(str(name))
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
            item.setCheckState(QtCore.Qt.Checked if i in selected_set else QtCore.Qt.Unchecked)
            self.list_widget.addItem(item)

        quick_layout = QtWidgets.QHBoxLayout()
        select_all_btn = QtWidgets.QPushButton("Select All")
        select_none_btn = QtWidgets.QPushButton("Select None")
        quick_layout.addWidget(select_all_btn)
        quick_layout.addWidget(select_none_btn)
        layout.addLayout(quick_layout)

        select_all_btn.clicked.connect(self.select_all)
        select_none_btn.clicked.connect(self.select_none)

        btns = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel,
            QtCore.Qt.Horizontal,
            self,
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def select_all(self):
        for i in range(self.list_widget.count()):
            self.list_widget.item(i).setCheckState(QtCore.Qt.Checked)

    def select_none(self):
        for i in range(self.list_widget.count()):
            self.list_widget.item(i).setCheckState(QtCore.Qt.Unchecked)

    def get_selected_indices(self):
        out = []
        for i in range(self.list_widget.count()):
            if self.list_widget.item(i).checkState() == QtCore.Qt.Checked:
                out.append(i)
        return out

class CrossSectionPlotWindow(QtWidgets.QDockWidget):
    variable_changed = QtCore.pyqtSignal(str, str) # item_id, new_var_name
    cursor_moved = QtCore.pyqtSignal(str, float) # item_id, distance along cross-section
    cursor_left = QtCore.pyqtSignal()
    range_changed = QtCore.pyqtSignal()
    settings_changed = QtCore.pyqtSignal()
    layers_changed = QtCore.pyqtSignal(str, object) # item_id, selected layer indices
    sigPointPicked = QtCore.pyqtSignal(object) # Emit QgsPointXY
    def __init__(self, data, variable_name, parent=None, vertex_distances=None, 
                 item_id=None, all_vars=None, head_vars=None, data_fetcher=None, label="A", points=None,
                 z_range=None, x_range=None, v_range=None, show_layers=True, show_cells=False, show_layer_names=False,
                 use_log=False, cmap_name='Turbo', invert_cmap=False, time_values=None, time_idx=0,
                 selected_layers=None):
        super().__init__(parent)
        self.item_id = item_id # Store for signaling
        self.data_fetcher = data_fetcher
        self.data = data
        self.all_vars = all_vars or [variable_name]
        self.head_vars = ["None"] + (head_vars or self.all_vars)
        self.current_var = variable_name
        self.current_head_var = "None"
        self.head_data = None
        self.cs_label = label
        self.points = points
        self.show_layer_boundaries = show_layers 
        self.show_cell_boundaries = show_cells
        self.show_layer_names = show_layer_names
        self.use_log = use_log
        self.cmap_name = cmap_name
        self.invert_cmap = invert_cmap
        self.v_min = v_range[0] if v_range else None
        self.v_max = v_range[1] if v_range else None
        self.time_values = time_values or []
        self.current_time_idx = time_idx
        self.selected_layer_indices = self._sanitize_selected_layers(selected_layers, data)
        
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
        
        tools_layout.addSpacing(10)
        
        # Head Selection (Wet Part)
        tools_layout.addWidget(QtWidgets.QLabel("Wet Top (Head):"))
        self.head_combo = QtWidgets.QComboBox()
        self.head_combo.addItems(self.head_vars)
        self.head_combo.setCurrentText("None")
        self.head_combo.currentTextChanged.connect(self.change_head_variable)
        tools_layout.addWidget(self.head_combo)
        
        tools_layout.addSpacing(20)
        
        # Spacer
        
        # Spacer
        tools_layout.addSpacing(20)
        
        # Spacer
        tools_layout.addStretch()
        
        tools_layout.addStretch()
        
        self.reset_btn = QtWidgets.QPushButton("Reset to Data")
        self.reset_btn.clicked.connect(self.reset_ranges)
        tools_layout.addWidget(self.reset_btn)

        self.layers_btn = QtWidgets.QPushButton("Layers...")
        self.layers_btn.clicked.connect(self.show_layer_selector)
        tools_layout.addWidget(self.layers_btn)
        
        # Settings Button
        self.settings_btn = QtWidgets.QPushButton("Settings...")
        self.settings_btn.clicked.connect(self.show_settings)
        tools_layout.addWidget(self.settings_btn)
        
        layout.addLayout(tools_layout)
        
        # Time Slider Layout
        self.time_container = QtWidgets.QWidget()
        time_layout = QtWidgets.QHBoxLayout(self.time_container)
        time_layout.setContentsMargins(0, 5, 0, 5)
        
        time_layout.addWidget(QtWidgets.QLabel("Time:"))
        self.time_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.time_slider.setMinimum(0)
        self.time_slider.setMaximum(max(0, len(self.time_values) - 1))
        self.time_slider.setValue(self.current_time_idx)
        self.time_slider.setTickPosition(QtWidgets.QSlider.TicksBelow)
        self.time_slider.setTickInterval(1)
        self.time_slider.valueChanged.connect(self.change_time)
        time_layout.addWidget(self.time_slider)
        
        self.time_label = QtWidgets.QLabel("")
        self.time_label.setMinimumWidth(120)
        if self.time_values:
            idx = min(self.current_time_idx, len(self.time_values)-1)
            self.time_label.setText(self.time_values[idx])
        time_layout.addWidget(self.time_label)
        
        layout.addWidget(self.time_container)
        
        # Update slider visibility
        self.update_time_slider_visibility()
        
        # Picking Info Label
        self.info_label = QtWidgets.QLabel("Click in plot to see cell info")
        self.info_label.setStyleSheet("font-weight: bold; color: #444; background: #f0f0f0; padding: 4px; border-radius: 4px;")
        layout.addWidget(self.info_label)
        
        # Store data for re-rendering
        self.colorbar = None
        self.vertex_lines = []
        self.vertex_distances = vertex_distances
        self.ts_sync_markers = [] # Tracking for TS location markers
        
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
        
        # Connect to range changes from user interaction (zoom/pan)
        self.plot_widget.getViewBox().sigYRangeChanged.connect(self.on_range_changed)
        self.plot_widget.getViewBox().sigXRangeChanged.connect(self.on_range_changed)
        
        # Connect mouse signals
        self.plot_widget.scene().sigMouseMoved.connect(self.on_mouse_moved)
        self.plot_widget.scene().sigMouseClicked.connect(self.on_plot_clicked)
        
        # Render Data
        self.render_data(data, v_min=self.v_min, v_max=self.v_max, vertex_distances=vertex_distances)
        
        # Initialize Range Settings
        self.init_ranges(data, z_range=z_range, x_range=x_range)

    def init_ranges(self, data, z_range=None, x_range=None):
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
                
                if z_range:
                    self.plot_widget.setYRange(z_range[0], z_range[1], padding=0)
                else:
                    self.plot_widget.setYRange(self.data_z_min - margin, self.data_z_max + margin, padding=0)
        
        if x_range:
            self.plot_widget.setXRange(x_range[0], x_range[1], padding=0)
        elif 'distances' in data and len(data['distances']) > 0:
            self.plot_widget.setXRange(data['distances'].min(), data['distances'].max(), padding=0)

    def on_range_changed(self, vb, new_range):
        """Notify that the plot range has changed."""
        self.range_changed.emit()

    def reset_elevation_range(self):
        if hasattr(self, 'data_z_min'):
            margin = (self.data_z_max - self.data_z_min) * 0.1
            if margin == 0: margin = 1.0
            self.plot_widget.setYRange(self.data_z_min - margin, self.data_z_max + margin, padding=0)

    def reset_ranges(self):
        self.reset_elevation_range()
        # Reset X range
        if 'distances' in self.data and len(self.data['distances']) > 0:
            d = self.data['distances']
            self.plot_widget.setXRange(d.min(), d.max(), padding=0)
        # Reset data range
        vals = self.data['values']
        layer_mask = np.array([i in set(self.selected_layer_indices) for i in range(vals.shape[0])], dtype=bool)
        vals_sel = vals[layer_mask, :] if vals.ndim >= 2 else vals
        valid_vals = vals_sel[~np.isnan(vals_sel)]
        if len(valid_vals) > 0:
            self.v_min = np.nanmin(valid_vals)
            self.v_max = np.nanmax(valid_vals)
            self.render_data(self.data, self.v_min, self.v_max)
            self.range_changed.emit()

    def _sanitize_selected_layers(self, selected_layers, data):
        n_layers = int(data.get('num_layers', 0))
        if n_layers <= 0:
            return []
        if selected_layers is None:
            return list(range(n_layers))
        out = []
        for idx in selected_layers:
            try:
                i = int(idx)
            except Exception:
                continue
            if 0 <= i < n_layers and i not in out:
                out.append(i)
        if not out:
            return list(range(n_layers))
        return sorted(out)

    def is_layer_visible(self, layer_idx):
        return int(layer_idx) in set(self.selected_layer_indices)

    def show_layer_selector(self):
        layer_names = self.data.get('layer_names', [])
        if not layer_names:
            layer_names = [str(i + 1) for i in range(self.data.get('num_layers', 0))]

        dlg = LayerSelectionDialog(layer_names, self.selected_layer_indices, self)
        if dlg.exec_():
            selected = dlg.get_selected_indices()
            if not selected:
                QtWidgets.QMessageBox.warning(self, "Invalid Selection", "Select at least one layer.")
                return

            self.selected_layer_indices = self._sanitize_selected_layers(selected, self.data)
            self.info_label.setText("Click in plot to see cell info")
            self.render_data(self.data, self.v_min, self.v_max, vertex_distances=self.vertex_distances)
            if self.item_id:
                self.layers_changed.emit(self.item_id, list(self.selected_layer_indices))
            self.settings_changed.emit()
            self.range_changed.emit()

    def apply_data_range(self):
        # Re-render with existing limits
        self.render_data(self.data, self.v_min, self.v_max)

    def show_settings(self):
        dlg = SettingsDialog(self, 
                             show_layer_boundaries=self.show_layer_boundaries, 
                             show_cell_boundaries=self.show_cell_boundaries,
                             show_layer_names=self.show_layer_names,
                             v_min=self.v_min, v_max=self.v_max, use_log=self.use_log,
                             cmap_name=self.cmap_name, invert_cmap=self.invert_cmap)
        if dlg.exec_():
            new_layer_boundaries = dlg.chk_boundaries.isChecked()
            new_cell_boundaries = dlg.chk_cell_boundaries.isChecked()
            new_layer_names = dlg.chk_layer_names.isChecked()
            new_v_min = dlg.v_min_spin.value()
            new_v_max = dlg.v_max_spin.value()
            new_use_log = dlg.chk_log.isChecked()
            new_cmap = dlg.cmap_combo.currentText()
            new_invert = dlg.chk_invert.isChecked()
            
            changed = False
            if (new_layer_boundaries != self.show_layer_boundaries or 
                new_cell_boundaries != self.show_cell_boundaries or
                new_layer_names != self.show_layer_names or
                new_v_min != self.v_min or
                new_v_max != self.v_max or
                new_use_log != self.use_log or
                new_cmap != self.cmap_name or
                new_invert != self.invert_cmap):
                
                self.show_layer_boundaries = new_layer_boundaries
                self.show_cell_boundaries = new_cell_boundaries
                self.show_layer_names = new_layer_names
                self.v_min = new_v_min
                self.v_max = new_v_max
                self.use_log = new_use_log
                self.cmap_name = new_cmap
                self.invert_cmap = new_invert
                changed = True
                
            if changed:
                # Clear info
                self.info_label.setText("Click in plot to see cell info")
                # Re-render
                self.render_data(self.data, vertex_distances=self.vertex_distances)
                # Save
                self.settings_changed.emit()
                self.range_changed.emit()

    def change_variable(self, var_name):
        if not self.data_fetcher:
            return
            
        try:
            # Fetch new data with current time
            new_data = self.data_fetcher(var_name, self.points, time_idx=self.current_time_idx)
            if new_data:
                if "error" in new_data:
                    QtWidgets.QMessageBox.warning(self, "Data Error", new_data['error'])
                    return

                self.data = new_data
                self.current_var = var_name
                self.selected_layer_indices = self._sanitize_selected_layers(self.selected_layer_indices, self.data)
                
                # Reset Data Range (v_min/v_max) so it's recalculated for the new variable
                # This addresses the user's request for "date range" (intended "data range") updates.
                self.v_min = None
                self.v_max = None
                
                # Update visibility in case the new variable has/doesn't have time
                self.update_time_slider_visibility()
                
                self.setWindowTitle(f"Cross Section {self.cs_label}: {var_name}")
                
                # Clear info
                self.info_label.setText("Click in plot to see cell info")
                
                self.render_data(self.data, vertex_distances=self.vertex_distances)
                # Notify dock widget of variable and range change
                if self.item_id:
                    self.variable_changed.emit(self.item_id, var_name)
                    self.range_changed.emit()
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Data Error", f"Failed to fetch data for {var_name}: {e}")

    def change_head_variable(self, head_var_name):
        self.current_head_var = head_var_name
        if head_var_name == "None":
            self.head_data = None
        else:
            try:
                self.head_data = self.data_fetcher(head_var_name, self.points, time_idx=self.current_time_idx)
            except Exception as e:
                QtWidgets.QMessageBox.warning(self, "Data Error", f"Failed to fetch head data for {head_var_name}: {e}")
                self.head_data = "Error"
        
        # Update visibility in case the new variable has/doesn't have time
        self.update_time_slider_visibility()
        
        # Re-render with existing data
        self.render_data(self.data, vertex_distances=self.vertex_distances)
        self.settings_changed.emit()

    def change_time(self, time_idx):
        self.current_time_idx = time_idx
        if self.time_values:
            idx = min(time_idx, len(self.time_values)-1)
            self.time_label.setText(self.time_values[idx])
            
        # Refresh current variable data
        try:
            new_data = self.data_fetcher(self.current_var, self.points, time_idx=time_idx)
            if new_data and "error" not in new_data:
                self.data = new_data
                self.selected_layer_indices = self._sanitize_selected_layers(self.selected_layer_indices, self.data)
            
            # Refresh head data if active
            if self.current_head_var != "None":
                new_head = self.data_fetcher(self.current_head_var, self.points, time_idx=time_idx)
                if new_head and "error" not in new_head:
                    self.head_data = new_head
                    
            self.render_data(self.data, vertex_distances=self.vertex_distances)
            self.settings_changed.emit()
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Time Error", f"Failed to update data for time index {time_idx}: {e}")

    def update_time_slider_visibility(self):
        # Only show slider if there are actually time steps available in the file
        # AND if either the current main variable or the head variable has a time dimension.
        if len(self.time_values) <= 1:
            self.time_container.hide()
            return

        has_time = False
        # The main data dict contains metadata if we added it in netcdf_handler.
        # Let's check if the current data has multiple time steps available for this var.
        # Actually, the handler returns sliced data. We can check the presence of 
        # time dimension name in the original variable metadata provided by dockwidget.
        
        # A more direct way: check the datafetcher metadata if available, 
        # but here we can just check self.data.get('has_time') if we add it.
        if self.data and self.data.get('has_time', True):
            has_time = True
            
        if self.head_data and self.head_data != "Error" and self.head_data.get('has_time', True):
            has_time = True

        if has_time:
            self.time_container.show()
        else:
            self.time_container.hide()

    def refresh(self, all_vars=None, head_vars=None, time_values=None):
        """Updates the available variables and reloads data for the current window."""
        if time_values is not None:
            self.time_values = time_values
            self.time_slider.blockSignals(True)
            self.time_slider.setMaximum(max(0, len(self.time_values) - 1))
            self.current_time_idx = min(self.current_time_idx, self.time_slider.maximum())
            self.time_slider.setValue(self.current_time_idx)
            if self.time_values:
                self.time_label.setText(self.time_values[self.current_time_idx])
            self.time_slider.blockSignals(False)
            self.update_time_slider_visibility()

        if head_vars is not None:
            self.head_vars = ["None"] + head_vars
            self.head_combo.blockSignals(True)
            self.head_combo.clear()
            self.head_combo.addItems(self.head_vars)
            if self.current_head_var in self.head_vars:
                self.head_combo.setCurrentText(self.current_head_var)
            else:
                self.current_head_var = "None"
                self.head_combo.setCurrentText("None")
            self.head_combo.blockSignals(False)

        if all_vars is not None:
            self.all_vars = all_vars
            self.var_combo.blockSignals(True)
            self.var_combo.clear()
            self.var_combo.addItems(self.all_vars)
            if self.current_var in self.all_vars:
                self.var_combo.setCurrentText(self.current_var)
            else:
                # current variable not in the new file, use first 3d variable
                if self.all_vars:
                    self.current_var = self.all_vars[0]
                    self.var_combo.setCurrentText(self.current_var)
            self.var_combo.blockSignals(False)
        
        # Reload current head if selected
        if self.current_head_var != "None":
            self.change_head_variable(self.current_head_var)

        # Reload currently selected main variable
        self.change_variable(self.current_var)

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
        
        # Check if click is outside cross-section distance
        if x_click < dists[0] or x_click > dists[-1]:
            self.info_label.setText("No cell at click location")
            return
            
        idx = np.searchsorted(dists, x_click) - 1
        idx = max(0, min(idx, len(dists) - 2))
        
        # Consistent with flat rendering, we want properties from the start of the cell segment
        seg_start_idx = idx - (idx % 2)
        
        # Find the layer using rendered boundaries (handles Wet Part shifting)
        top = self.rendered_top[seg_start_idx]
        botm = self.rendered_botm[:, seg_start_idx]
        num_layers = self.data['num_layers']
        selected_set = set(self.selected_layer_indices)
        
        found_layer = -1
        for i in range(num_layers):
            if i not in selected_set:
                continue
            l_top = top if i == 0 else botm[i-1]
            l_bot = botm[i]
            
            if np.isnan(l_top) or np.isnan(l_bot): continue
            
            # Check if z_click is between l_top and l_bot
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
            
            indices = self.data.get('indices')
            cell_id_str = ""
            if indices is not None:
                if isinstance(indices, tuple):
                    # Structured: (yi, xi)
                    r = indices[0][seg_start_idx]
                    c = indices[1][seg_start_idx]
                    cell_id_str = f"Row: {r}, Col: {c}, "
                else:
                    # Vertex: icell2d
                    icell2d = indices[seg_start_idx]
                    cell_id_str = f"Icell2d: {icell2d}, "

            val_str = f"{val:.4f}" if not np.isnan(val) else "NaN"
            self.info_label.setText(
                f"X: {cx:.1f}, Y: {cy:.1f}, Layer: {layer_name}, {cell_id_str}Value: {val_str}"
            )
            
            # Emit signal with world point
            from qgis.core import QgsPointXY
            self.sigPointPicked.emit(QgsPointXY(cx, cy))
        else:
            self.info_label.setText("No cell at click location")

    def get_pyqtgraph_cmap(self, ramp_name, invert=False):
        """Converts a QGIS color ramp to a pyqtgraph ColorMap."""
        try:
            style = QgsStyle.defaultStyle()
            ramp = style.colorRamp(ramp_name)
            
            if not ramp:
                # Fallback
                return pg.colormap.get('turbo')
            
            # Sample the ramp
            n_samples = 256
            stops = []
            colors = []
            
            for i in range(n_samples):
                val = i / (n_samples - 1)
                # Apply inversion if requested
                sample_val = 1.0 - val if invert else val
                qcolor = ramp.color(sample_val)
                stops.append(val)
                colors.append([qcolor.red(), qcolor.green(), qcolor.blue(), qcolor.alpha()])
            
            return pg.ColorMap(stops, np.array(colors))
        except Exception:
            return pg.colormap.get('turbo')

    def render_data(self, data, v_min=None, v_max=None, vertex_distances=None):
        """Update the plot with new data and manage internal state."""
        self.data = data
        if vertex_distances is not None:
            self.vertex_distances = vertex_distances
            
        # Clear previous items
        self.plot_widget.clear()
        self.ts_sync_markers = []
        if self.colorbar:
            self.plot_widget.plotItem.layout.removeItem(self.colorbar)
            self.colorbar = None
        
        self.vertex_lines = []
        self.label_items = []
            
        # Unpack
        dists = data['distances']
        top = data['top'].copy()
        botm = data['botm'].copy()
        vals = data['values']
        self.selected_layer_indices = self._sanitize_selected_layers(self.selected_layer_indices, data)
        selected_set = set(self.selected_layer_indices)
        vals_plot = vals.copy()
        if vals_plot.ndim >= 2:
            for i in range(vals_plot.shape[0]):
                if i not in selected_set:
                    vals_plot[i, :] = np.nan
        
        # 0. Sync Head Data if necessary
        if self.current_head_var != "None":
            # Re-fetch if head data is missing, erroneous, or doesn't match the current cross-section points
            points_changed = False
            if self.head_data is not None and self.head_data != "Error":
                h_dists = self.head_data.get('distances', [])
                if len(h_dists) != len(dists):
                    points_changed = True
                elif len(dists) > 0 and not np.isclose(h_dists[0], dists[0]):
                    points_changed = True
            
            if self.head_data is None or self.head_data == "Error" or points_changed:
                try:
                    # Use the points currently stored in the window and the current time
                    res = self.data_fetcher(self.current_head_var, self.points, time_idx=self.current_time_idx)
                    if res and "error" not in res:
                        self.head_data = res
                    else:
                        self.head_data = "Error"
                except:
                    self.head_data = "Error"
        
        # Color Map
        cmap = self.get_pyqtgraph_cmap(self.cmap_name, invert=self.invert_cmap)
        
        # Data Range
        # Exclude both NaNs and Infs for range calculation
        valid_vals = vals_plot[np.isfinite(vals_plot)]
        if len(valid_vals) == 0:
            return
            
        if v_min is None:
            if hasattr(self, '_first_render_done') and self.v_min is not None:
                v_min = self.v_min
            else:
                v_min = np.nanmin(valid_vals)
                
        if v_max is None:
            if hasattr(self, '_first_render_done') and self.v_max is not None:
                v_max = self.v_max
            else:
                v_max = np.nanmax(valid_vals)
        
        # Update stored range (locks auto-scale to first calculated value)
        self.v_min = v_min
        self.v_max = v_max
        self._first_render_done = True
        
        # Apply "Wet Part" logic if head_data is available
        if self.head_data and self.head_data != "Error":
            h_vals = self.head_data['values']
            num_layers = botm.shape[0]
            
            # Treat NaNs in head as "dry"
            h_safe = np.nan_to_num(h_vals, nan=-1e30)
            
            # We build the mesh boundaries by stacking only the wet thicknesses
            # on top of the absolute bottom. This ensures zero-thickness for dry cells
            # and prevents "layer shifting" where dry space was being filled by upper layers.
            curr_elev = data['botm'][-1, :].copy() 
            new_boundaries = [curr_elev]
            
            for i in range(num_layers - 1, -1, -1):
                # Use original reference boundaries from the data dictionary
                l_top_orig = data['top'] if i == 0 else data['botm'][i-1, :]
                l_bot_orig = data['botm'][i, :]
                h_layer = h_safe[i, :] if h_safe.ndim > 1 else h_safe
                
                # Saturated thickness of this layer
                wet_top = np.minimum(l_top_orig, h_layer)
                wet_thick = np.maximum(0, wet_top - l_bot_orig)
                
                curr_elev = curr_elev + wet_thick
                new_boundaries.append(curr_elev)
            
            # new_boundaries is [AbsoluteBottom, TopLast, ..., Top0]
            new_boundaries.reverse()
            # Now: [Top0, Top1, ..., BotLast]
            
            top = new_boundaries[0]
            for i in range(num_layers):
                botm[i, :] = new_boundaries[i+1]
        
        self.rendered_top = top
        self.rendered_botm = botm
        
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
            z_mesh = vals_plot[:, :-1]
            
            # Handle Log Scale
            render_min, render_max = v_min, v_max
            if self.use_log:
                # Map data to log space. 
                # Use a small epsilon for values <= 0
                epsilon = 1e-10
                z_mesh = np.log10(np.where(z_mesh > epsilon, z_mesh, epsilon))
                render_min = np.log10(max(v_min, epsilon))
                render_max = np.log10(max(v_max, epsilon))
            
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
            
            if not np.isnan(z_mesh).any():
                # Create PColorMeshItem
                self.dataset_item = PColorMeshItem(
                x_mesh, y_mesh, z_mesh,
                    colorMap=cmap,
                    antialiasing=False
                )
                self.dataset_item.setLevels((render_min, render_max))
                self.plot_widget.addItem(self.dataset_item)
            else:
                # Fallback to slower custom Item if PColorMeshItem fails (e.g. older versions or NaN coords)
                from qgis.core import QgsMessageLog, Qgis
                QgsMessageLog.logMessage(f"NLMOD: NaN values found in z_mesh, using custom renderer", "NLMOD Viewer", Qgis.Info)
                self.dataset_item = CrossSectionMeshItem(
                    dists, top, botm, vals_plot, cmap, (v_min, v_max), 
                    show_layer_boundaries=False, # Item handles its own
                    show_cell_boundaries=False,
                    indices=data.get('indices'),
                    use_log=self.use_log
                )
                self.plot_widget.addItem(self.dataset_item)
            
            # Add Optional Layer Boundaries using PlotCurveItem (very fast)
            if self.show_layer_boundaries:
                pen = pg.mkPen('k', width=1)
                for i in range(num_layers + 1):
                    show_boundary = False
                    if i == 0 and 0 in selected_set:
                        show_boundary = True
                    elif i == num_layers and (num_layers - 1) in selected_set:
                        show_boundary = True
                    elif (i - 1) in selected_set or i in selected_set:
                        show_boundary = True
                    if not show_boundary:
                        continue
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
                        
            # Show Layer Names at thickest part
            if self.show_layer_names and 'layer_names' in data:
                layer_names = data['layer_names']
                for i in range(num_layers):
                    if i not in selected_set:
                        continue
                    # Calculate segment thicknesses for this layer
                    # Layer i top: y_mesh[i], bot: y_mesh[i+1]
                    # We compute average thickness for each interval [j, j+1]
                    l_top = y_mesh[i, :]
                    l_bot = y_mesh[i+1, :]
                    
                    # Mid-points for x
                    x_mids = (dists[:-1] + dists[1:]) / 2
                    
                    # Avg thickness
                    t_avg = ((l_top[:-1] - l_bot[:-1]) + (l_top[1:] - l_bot[1:])) / 2
                    
                    # Find max
                    # Handle NaNs
                    valid_mask = np.isfinite(t_avg)
                    if not np.any(valid_mask): continue
                    
                    # Zero out invalid to find max
                    t_clean = np.where(valid_mask, t_avg, -1.0)
                    j_max = np.argmax(t_clean)
                    
                    if t_clean[j_max] <= 0: continue
                    
                    # Position
                    x_pos = x_mids[j_max]
                    y_pos = (l_top[j_max] + l_bot[j_max] + l_top[j_max+1] + l_bot[j_max+1]) / 4
                    
                    # Add Label
                    name_idx = i % len(layer_names)
                    txt = pg.TextItem(layer_names[name_idx], anchor=(0.5, 0.5), color='k')
                    txt.setPos(x_pos, y_pos)
                    self.plot_widget.addItem(txt)
                    self.label_items.append(txt)
        else:
            # Fallback to slower custom Item
            self.dataset_item = CrossSectionMeshItem(
                dists, top, botm, vals_plot, cmap, (v_min, v_max), 
                show_layer_boundaries=self.show_layer_boundaries,
                show_cell_boundaries=self.show_cell_boundaries,
                indices=data.get('indices'),
                use_log=self.use_log
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
            colorMap=cmap,
            width=15,
            interactive=False
        )
        self.colorbar.setLevels((render_min, render_max))
        
        # Add directly to plot layout (row 2, column 3 = right side)
        self.plot_widget.plotItem.layout.addItem(self.colorbar, 2, 3)
        
        # Style the colorbar axis
        axis = self.colorbar.getAxis('right')
        axis.setPen('k')
        axis.setTextPen('k')
        
        # Set Label from metadata
        desc = data.get('description', self.current_var)
        units = data.get('units', '')
        label_text = f"{desc} ({units})" if units else desc
        axis.setLabel(label_text, **{'color': '#000', 'font-size': '10pt'})
        
        if self.use_log:
            # Custom formatter to show real values (10^x)
            def log_formatter(values, scale, spacing):
                labels = []
                for v in values:
                    try:
                        real_val = 10**v
                        if 0.01 <= real_val <= 1000:
                            labels.append(f"{real_val:.2f}".rstrip('0').rstrip('.'))
                        else:
                            labels.append(f"{real_val:.2e}")
                    except:
                        labels.append("")
                return labels
            axis.tickStrings = log_formatter

    def clear_ts_sync_markers(self):
        """Removes all blue cross markers from the plot."""
        for m in self.ts_sync_markers:
            self.plot_widget.removeItem(m)
        self.ts_sync_markers = []

    def add_ts_sync_marker(self, x, y, color='b', marker_type='x'):
        """Adds a cross marker to the plot with specified color."""
        
        # Map generic types to pyqtgraph symbols
        symbol_map = {
            'x': 'x',
            'cross': '+',
            'box': 's',
            'circle': 'o',
            'triangle': 't1'
        }
        symbol = symbol_map.get(marker_type, 'x')
        
        marker = pg.ScatterPlotItem(
            [x], [y], 
            symbol=symbol, 
            size=12, 
            pen=pg.mkPen(color, width=3),
            brush=None
        )
        self.plot_widget.addItem(marker)
        self.ts_sync_markers.append(marker)


class CrossSectionMeshItem(pg.GraphicsObject):
    def __init__(self, dists, top, botm, vals, cmap, val_range=None, 
                 show_layer_boundaries=False, show_cell_boundaries=False, 
                 indices=None, use_log=False):
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
        self.use_log = use_log
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
            valid_vals = self.vals[np.isfinite(self.vals)]
            if len(valid_vals) == 0:
                p.end()
                return
            min_val = np.nanmin(valid_vals)
            max_val = np.nanmax(valid_vals)
            
        if self.use_log:
            epsilon = 1e-10
            min_val = np.log10(max(min_val, epsilon))
            max_val = np.log10(max(max_val, epsilon))
            
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
                    if self.use_log:
                        epsilon = 1e-10
                        val = np.log10(max(val, epsilon))
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
                    if self.use_log:
                        epsilon = 1e-10
                        val = np.log10(max(val, epsilon))
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

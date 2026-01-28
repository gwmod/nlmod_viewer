from qgis.PyQt import QtWidgets, QtCore
from qgis.core import (
    QgsProject, QgsMeshLayer, QgsRasterLayer, QgsCoordinateReferenceSystem,
    QgsSingleBandPseudoColorRenderer, QgsColorRampShader, QgsStyle, QgsRasterShader,
    QgsRasterBandStats, QgsMessageLog, Qgis, QgsGradientColorRamp,
    QgsMeshRendererScalarSettings, QgsMeshDatasetIndex, QgsMeshRendererSettings
)
from .netcdf_handler import NetcdfHandler
import os
import tempfile
import json
import time as py_time
from .time_series_plot import TimeSeriesPlotWindow
from .time_series_tool import TimeSeriesMapTool
from qgis.PyQt.QtCore import Qt, pyqtSignal, QPointF
from qgis.core import QgsPointXY, QgsGeometry, QgsWkbTypes

class VertexEditorDialog(QtWidgets.QDialog):
    def __init__(self, points, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Vertices")
        self.resize(400, 500)
        layout = QtWidgets.QVBoxLayout(self)
        
        layout.addWidget(QtWidgets.QLabel("Manual Coordinate Entry:"))
        
        self.table = QtWidgets.QTableWidget(len(points), 2)
        self.table.setHorizontalHeaderLabels(["X (Easting)", "Y (Northing)"])
        self.table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        
        for i, p in enumerate(points):
            self.table.setItem(i, 0, QtWidgets.QTableWidgetItem(f"{p.x():.3f}"))
            self.table.setItem(i, 1, QtWidgets.QTableWidgetItem(f"{p.y():.3f}"))
        
        layout.addWidget(self.table)
        
        # Add note about projection
        note = QtWidgets.QLabel("Note: Coordinates should be in the model CRS (e.g. EPSG:28992).")
        note.setStyleSheet("font-style: italic; color: #666;")
        layout.addWidget(note)
        
        btns = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel,
            QtCore.Qt.Horizontal, self)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)
        
    def get_points(self):
        pts = []
        for i in range(self.table.rowCount()):
            try:
                x_text = self.table.item(i, 0).text()
                y_text = self.table.item(i, 1).text()
                if x_text and y_text:
                    pts.append(QgsPointXY(float(x_text), float(y_text)))
            except ValueError:
                continue
        return pts

class PointEditorDialog(QtWidgets.QDialog):
    def __init__(self, point, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Point Coordinates")
        layout = QtWidgets.QFormLayout(self)
        self.x_edit = QtWidgets.QLineEdit(f"{point.x():.3f}")
        self.y_edit = QtWidgets.QLineEdit(f"{point.y():.3f}")
        layout.addRow("X (Easting):", self.x_edit)
        layout.addRow("Y (Northing):", self.y_edit)
        
        # Add note about projection
        note = QtWidgets.QLabel("Note: Coordinates should be in the model CRS.")
        note.setStyleSheet("font-style: italic; color: #666;")
        layout.addRow(note)
        
        self.btns = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        self.btns.accepted.connect(self.accept)
        self.btns.rejected.connect(self.reject)
        layout.addRow(self.btns)

    def get_point(self):
        try:
            return QgsPointXY(float(self.x_edit.text()), float(self.y_edit.text()))
        except:
            return None

class MainSettingsDialog(QtWidgets.QDialog):
    def __init__(self, parent=None, auto_var=False, auto_layer=False, auto_time=False):
        super().__init__(parent)
        self.setWindowTitle("Global Settings")
        layout = QtWidgets.QVBoxLayout(self)
        
        group = QtWidgets.QGroupBox("Update map")
        group_layout = QtWidgets.QVBoxLayout()
        
        self.chk_var = QtWidgets.QCheckBox("When variable changes")
        self.chk_var.setChecked(auto_var)
        group_layout.addWidget(self.chk_var)
        
        self.chk_layer = QtWidgets.QCheckBox("When layer changes")
        self.chk_layer.setChecked(auto_layer)
        group_layout.addWidget(self.chk_layer)
        
        self.chk_time = QtWidgets.QCheckBox("When time changes")
        self.chk_time.setChecked(auto_time)
        group_layout.addWidget(self.chk_time)
        
        self.chk_color = QtWidgets.QCheckBox("Update color scale on every change")
        self.chk_color.setChecked(getattr(parent, 'auto_update_color', True))
        group_layout.addWidget(self.chk_color)
        
        group.setLayout(group_layout)
        layout.addWidget(group)
        
        btns = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel,
            QtCore.Qt.Horizontal, self)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

class NlmodDockWidget(QtWidgets.QDockWidget):
    def __init__(self, parent=None, iface=None):
        super(NlmodDockWidget, self).__init__(parent)
        self.iface = iface # Store iface reference
        self.setWindowTitle("NLMOD Inspector")
        self.setAllowedAreas(QtCore.Qt.LeftDockWidgetArea | QtCore.Qt.RightDockWidgetArea)
        
        # Main Widget & Layout
        self.main_widget = QtWidgets.QWidget()
        self.setWidget(self.main_widget)
        layout = QtWidgets.QVBoxLayout(self.main_widget)
        
        # File Selection / Select Data Group
        file_group = QtWidgets.QGroupBox("Select Data")
        file_layout = QtWidgets.QVBoxLayout()
        h_layout = QtWidgets.QHBoxLayout()
        self.file_edit = QtWidgets.QLineEdit()
        self.browse_btn = QtWidgets.QPushButton("Browse...")
        self.browse_btn.clicked.connect(self.select_file)
        h_layout.addWidget(self.file_edit)
        h_layout.addWidget(self.browse_btn)
        
        self.settings_btn = QtWidgets.QPushButton("Settings...")
        self.settings_btn.clicked.connect(self.show_settings)
        h_layout.addWidget(self.settings_btn)
        
        file_layout.addLayout(h_layout)
        
        # Metadata / Info Area
        self.info_text = QtWidgets.QTextBrowser()
        self.info_text.setMaximumHeight(100)
        file_layout.addWidget(QtWidgets.QLabel("Metadata:"))
        file_layout.addWidget(self.info_text)
        
        # Ensure the group stays compact if given more space
        file_layout.addStretch()
        
        file_group.setLayout(file_layout)
        layout.addWidget(file_group, 0)
        

        # Map Layer Group
        layer_group = QtWidgets.QGroupBox("Map Layer")
        layer_group_layout = QtWidgets.QVBoxLayout()
        layer_group.setLayout(layer_group_layout)
        
        # Variable List
        self.var_list = QtWidgets.QListWidget()
        self.var_list.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.var_list.itemSelectionChanged.connect(self.update_layer_selection)
        self.var_list.itemDoubleClicked.connect(lambda: self.add_layer(force_new=True))
        self.var_list.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.var_list.customContextMenuRequested.connect(self.handle_var_context_menu)
        layer_group_layout.addWidget(QtWidgets.QLabel("Variables:"))
        layer_group_layout.addWidget(self.var_list)

        # Layer Selection
        layer_sel_layout = QtWidgets.QHBoxLayout()
        layer_sel_layout.addWidget(QtWidgets.QLabel("Select Layer:"))
        self.layer_combo = QtWidgets.QComboBox()
        self.layer_combo.setEnabled(False)
        self.layer_combo.currentIndexChanged.connect(self.on_layer_combo_changed)
        layer_sel_layout.addWidget(self.layer_combo)
        layer_group_layout.addLayout(layer_sel_layout)

        # Time Selection
        self.time_widget = QtWidgets.QWidget()
        time_sel_layout = QtWidgets.QHBoxLayout(self.time_widget)
        time_sel_layout.setContentsMargins(0, 0, 0, 0)
        
        self.time_heading = QtWidgets.QLabel("Select Time:")
        time_sel_layout.addWidget(self.time_heading)
        
        self.time_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.time_slider.setEnabled(False)
        self.time_slider.setTickPosition(QtWidgets.QSlider.TicksBelow)
        self.time_slider.setTickInterval(1)
        self.time_slider.valueChanged.connect(self.on_time_slider_changed)
        time_sel_layout.addWidget(self.time_slider)
        
        self.time_label = QtWidgets.QLabel("")
        self.time_label.setMinimumWidth(100)
        time_sel_layout.addWidget(self.time_label)
        
        layer_group_layout.addWidget(self.time_widget)
        self.time_widget.setVisible(False)
        
        # Add to Map Button
        self.load_btn = QtWidgets.QPushButton("Add to Map")
        self.load_btn.clicked.connect(lambda: self.add_layer(force_new=True))
        layer_group_layout.addWidget(self.load_btn)
        
        layout.addWidget(layer_group, 1)
        
        # Cross Section Group (at bottom)
        cs_group = QtWidgets.QGroupBox("Cross Section")
        cs_layout = QtWidgets.QVBoxLayout()
        cs_group.setLayout(cs_layout)
        
        cs_btn_layout = QtWidgets.QHBoxLayout()
        self.btn_cross_section = QtWidgets.QPushButton("Add")
        self.btn_cross_section.clicked.connect(self.activate_cross_section_tool)
        cs_btn_layout.addWidget(self.btn_cross_section)
        
        self.btn_remove_cs = QtWidgets.QPushButton("Remove")
        self.btn_remove_cs.setEnabled(False) # Default disabled
        self.btn_remove_cs.clicked.connect(self.remove_cross_section)
        cs_btn_layout.addWidget(self.btn_remove_cs)
        
        cs_layout.addLayout(cs_btn_layout)
        
        # Cross Section List Manager
        self.cs_list = QtWidgets.QListWidget()
        self.cs_list.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.cs_list.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.cs_list.customContextMenuRequested.connect(self.on_cs_list_context_menu)
        self.cs_list.itemSelectionChanged.connect(self.on_cs_selection_changed)
        self.cs_list.itemSelectionChanged.connect(self.update_ui_state) # Track button enablement
        self.cs_list.itemDoubleClicked.connect(self.raise_cross_section_window)
        cs_layout.addWidget(self.cs_list)
        
        layout.addWidget(cs_group, 0)
        
        # Time Series Group
        self.ts_group = QtWidgets.QGroupBox("Time Series")
        ts_layout = QtWidgets.QVBoxLayout()
        self.ts_group.setLayout(ts_layout)
        
        ts_btn_layout = QtWidgets.QHBoxLayout()
        self.btn_add_ts = QtWidgets.QPushButton("Add")
        self.btn_add_ts.clicked.connect(self.activate_point_tool)
        ts_btn_layout.addWidget(self.btn_add_ts)
        
        self.btn_remove_ts = QtWidgets.QPushButton("Remove")
        self.btn_remove_ts.setEnabled(False)
        self.btn_remove_ts.clicked.connect(self.remove_time_series)
        ts_btn_layout.addWidget(self.btn_remove_ts)
        
        ts_layout.addLayout(ts_btn_layout)
        
        self.ts_list = QtWidgets.QListWidget()
        self.ts_list.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.ts_list.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.ts_list.customContextMenuRequested.connect(self.on_ts_list_context_menu)
        self.ts_list.itemSelectionChanged.connect(self.on_ts_selection_changed)
        self.ts_list.itemSelectionChanged.connect(self.update_ui_state)
        self.ts_list.itemDoubleClicked.connect(self.raise_timeseries_window)
        ts_layout.addWidget(self.ts_list)
        
        layout.addWidget(self.ts_group, 0)
        
        # Stretch to fill bottom
        layout.addStretch()
        
        # Logic State
        self.handler = None
        self.time_values = []
        self.active_map_layer = None # Track the managed map layer
        self.active_var_name = None  # Track the name of the currently loaded variable
        self.plot_windows = {}  # Dictionary to track cross-section plot windows
        self.cs_geometries = {}  # Dictionary to store cross-section line geometries
        self.cs_rubber_bands = {}  # Dictionary to store QgsRubberBand for each CS
        self.active_cs_id = None  # Track which CS is currently being edited/drawn
        
        self.ts_windows = {}    # item_id -> window
        self.ts_points = {}     # item_id -> QgsPointXY
        self.ts_markers = {}    # item_id -> QgsVertexMarker
        self.active_ts_id = None
        
        self.prev_map_tool = None # Store map tool before activation
        self.sync_marker = None   # Marker for plot synchronization
        
        # Auto-update settings
        self.auto_update_var = False
        self.auto_update_layer = False
        self.auto_update_time = False
        self.auto_update_color = True
        
        self.is_restoring = True  # Start in restoring mode to prevent overwrites
        # Signal connection moved to end of restore_state_from_project

    def select_file(self):
        filename, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Select NetCDF File", "", "NetCDF Files (*.nc *.nc4 *.hdf5);;All Files (*)"
        )
        if filename:
            self.file_edit.setText(filename)
            self.open_netcdf(filename)

    def open_netcdf(self, filepath):
        if self.handler:
            self.handler.close()
        
        self.handler = NetcdfHandler(filepath)
        success, msg = self.handler.open()
        
        if not success:
             self.info_text.setText(f"Error opening file:\n{msg}")
             self.var_list.clear()
             QtWidgets.QMessageBox.critical(self, "Open Error", msg)
             return
        
        self.info_text.setText(self.handler.get_info_text())
        
        # Populate Layers and Times globally
        dim_meta = self.handler.get_dimensions_metadata()
        
        self.layer_combo.blockSignals(True)
        self.layer_combo.clear()
        if dim_meta["layers"]:
            self.layer_combo.addItems(dim_meta["layers"])
        self.layer_combo.blockSignals(False)
        
        self.time_values = dim_meta["times"]
        has_time = len(self.time_values) > 0
        self.time_widget.setVisible(has_time)
        
        self.time_slider.blockSignals(True)
        self.time_slider.setMinimum(0)
        self.time_slider.setMaximum(max(0, len(self.time_values) - 1))
        self.time_slider.setValue(0)
        if self.time_values:
            self.time_label.setText(self.time_values[0])
        else:
            self.time_label.setText("")
        self.time_slider.blockSignals(False)
            
        self.populate_vars()
        
        # Update existing cross-sections and time series with new data/variables
        vars_3d = self.get_vars_3d()
        all_vars = self.get_all_vars()
        all_vars_with_time = self.get_vars_with_time()
        times = dim_meta["times"]
        for win in self.plot_windows.values():
            win.refresh(vars_3d, head_vars=all_vars, time_values=times)
        
        for win in self.ts_windows.values():
            win.refresh(all_vars=all_vars_with_time)
            
        # Hide Time Series group if no time dimension
        self.ts_group.setVisible(len(self.time_values) > 0)
        
        self.save_state_to_project()

    def populate_vars(self):
        self.var_list.clear()
        vars = self.handler.get_variables()
        for v in vars:
            # Display: Name (Dims) - Description
            dims_str = ",".join(v['dimensions'])
            text = f"{v['name']} [{dims_str}]"
            item = QtWidgets.QListWidgetItem(text)
            item.setToolTip(v['description'])
            item.setData(QtCore.Qt.UserRole, v['name'])
            
            # Dimension Presence Flags
            item.setData(QtCore.Qt.UserRole + 1, v.get('layer_size', 0) > 0)
            item.setData(QtCore.Qt.UserRole + 2, v.get('time_size', 0) > 0)
            
            self.var_list.addItem(item)
    
    def update_layer_selection(self):
        """Enable/Disable combos based on the selected variable's dimensions."""
        selected_items = self.var_list.selectedItems()
        
        if not selected_items:
            self.layer_combo.setEnabled(False)
            self.time_slider.setEnabled(False)
            return
            
        item = selected_items[0]
        has_layers = item.data(QtCore.Qt.UserRole + 1)
        has_times = item.data(QtCore.Qt.UserRole + 2)
        
        self.layer_combo.setEnabled(has_layers)
        self.time_slider.setEnabled(has_times)

        if self.auto_update_var:
            self.add_layer()

    def get_vars_3d(self):
        """Helper to identify variables that have a layer/vertical dimension."""
        vars_3d = []
        if not self.handler:
            return vars_3d
        try:
            all_vars = self.handler.get_variables()
            possible_layer_dims = {'layer', 'lev', 'level', 'z'}
            for v in all_vars:
                if any(d in possible_layer_dims for d in v.get('dimensions', [])):
                    vars_3d.append(v['name'])
        except:
            pass
        return vars_3d

    def get_vars_with_time(self):
        if self.handler:
            return self.handler.get_vars_with_time()
        return []

    def get_all_vars(self):
        """Helper to get all variable names."""
        if not self.handler:
            return []
        try:
            return [v['name'] for v in self.handler.get_variables()]
        except:
            return []

    def handle_var_context_menu(self, point):
        item = self.var_list.itemAt(point)
        if not item:
            return
            
        var_name = item.data(QtCore.Qt.UserRole)
        menu = QtWidgets.QMenu(self.var_list)
        
        info_action = menu.addAction("Show Attributes")
        
        action = menu.exec_(self.var_list.mapToGlobal(point))
        
        if action == info_action:
            self.show_variable_info(var_name)
            
    def show_variable_info(self, var_name):
        if not self.handler: return
        
        # Find variable metadata
        try:
            vars = self.handler.get_variables()
            var_meta = next((v for v in vars if v['name'] == var_name), None)
            
            if var_meta:
                # Also fetch attributes from the netcdf variable directly for completeness
                # (The handler summary might be limited)
                # But we can reconstruct a nice message
                msg = []
                msg.append(f"<b>Variable:</b> {var_name}")
                msg.append(f"<b>Dimensions:</b> {', '.join(var_meta['dimensions'])}")
                msg.append(f"<b>Description:</b> {var_meta['description']}")
                
                # Show in a message box
                QtWidgets.QMessageBox.information(self, f"Attributes: {var_name}", "<br>".join(msg))
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Error", f"Could not fetch info: {e}")

    def add_layer(self, force_new=False, layer_to_update=None, params=None):
        if not self.handler:
            return
            
        if params:
            var_name = params.get('var_name')
            layer_idx = int(params.get('layer_idx', 0))
            time_idx = int(params.get('time_idx', 0))
        else:
            selected_items = self.var_list.selectedItems()
            if not selected_items:
                if not getattr(self, 'auto_update_var', False):
                    QtWidgets.QMessageBox.information(self, "Info", "Please select a variable first.")
                return
                
            var_name = selected_items[0].data(QtCore.Qt.UserRole)
            layer_idx = self.layer_combo.currentIndex() if self.layer_combo.isEnabled() else 0
            time_idx = self.time_slider.value() if self.time_slider.isEnabled() else 0

        grid_type = self.handler.grid_type
        filepath = self.handler.filepath
        base_name = os.path.basename(filepath)
        
        # Vertex grids (quadtree, unstructured) always load as Mesh (MDAL)
        # Structured grids always load as Raster (GDAL)
        use_mesh = (grid_type == "vertex")
        
        # Determine Layer name for legend
        if params:
            if self.layer_combo.count() > layer_idx:
                layer_val = self.layer_combo.itemText(layer_idx)
            else:
                layer_val = str(layer_idx + 1)
            time_val = self.time_values[time_idx] if (0 <= time_idx < len(self.time_values)) else ""
        else:
            layer_val = self.layer_combo.currentText() if self.layer_combo.isEnabled() else "1"
            time_val = self.time_values[time_idx] if (self.time_slider.isEnabled() and self.time_values) else ""
        
        display_name = f"{var_name}"
        if layer_val: display_name += f" ({layer_val})"
        if time_val: display_name += f" [{time_val}]"
        display_name += f" @ {base_name}"
        
        # Get consistent CRS from handler or default to RD New
        crs_def = self.handler.get_crs()
        if not crs_def:
            crs_def = "EPSG:28992"
        qgs_crs = QgsCoordinateReferenceSystem(crs_def)

        # Check for existing managed layer (only if not forcing a new one)
        existing_layer = layer_to_update
        if not existing_layer and not force_new and self.active_map_layer:
            try:
                # Check if layer still exists in the project
                if self.active_map_layer.id() in QgsProject.instance().mapLayers():
                    # If the type matches, we can update it
                    is_mesh = isinstance(self.active_map_layer, QgsMeshLayer)
                    if is_mesh == use_mesh:
                        existing_layer = self.active_map_layer
                else:
                    self.active_map_layer = None
            except RuntimeError:
                # Layer was deleted from QGIS, so the C++ object is gone
                self.active_map_layer = None
        
        # If we don't have a reference, try to find an existing layer by custom property
        if not existing_layer and not force_new:
            for layer_id, layer in QgsProject.instance().mapLayers().items():
                if use_mesh and isinstance(layer, QgsMeshLayer):
                    # Check if this layer was created by our plugin for this file
                    if layer.customProperty("nlmod_inspector_source") == filepath:
                        # If we are restoring, we might want to match the exact variable too
                        if params and layer.customProperty("nlmod_inspector_var") != var_name:
                            continue
                        existing_layer = layer
                        self.active_map_layer = layer
                        break
                elif not use_mesh and isinstance(layer, QgsRasterLayer):
                    if layer.customProperty("nlmod_inspector_source") == filepath:
                        if params and layer.customProperty("nlmod_inspector_var") != var_name:
                            continue
                        existing_layer = layer
                        self.active_map_layer = layer
                        break

        if use_mesh:
            # Use a unique timestamped filename to avoid "Permission denied" locks from MDAL
            import time
            timestamp = int(time.time() * 1000)
            temp_path = os.path.join(tempfile.gettempdir(), f"nlmod_mesh_{id(self)}_{timestamp}.nc")
            
            success, msg = self.handler.export_to_mesh(var_name, layer_idx, time_idx, temp_path)
            
            if not success:
                QtWidgets.QMessageBox.warning(self, "Export Error", f"Failed to export mesh: {msg}")
                return

            # Capture existing style if we want to preserve it
            preserved_mesh_style = None
            preserved_native_mesh = None
            preserved_edges = None
            
            if existing_layer:
                try:
                    old_settings = existing_layer.rendererSettings()
                    
                    # Capture scalar style if auto-update is off
                    if not self.auto_update_color:
                        idx = old_settings.activeScalarDatasetGroup()
                        if idx >= 0:
                            preserved_mesh_style = old_settings.scalarSettings(idx)
                    
                    # Always capture mesh-level settings (wireframe, etc.)
                    if hasattr(old_settings, 'nativeMeshSettings'):
                        preserved_native_mesh = old_settings.nativeMeshSettings()
                    if hasattr(old_settings, 'edgeSettings'):
                        preserved_edges = old_settings.edgeSettings()
                        
                except Exception as e:
                    pass  # If capture fails, we'll just use default styling

            # Calculate actual min/max for the current selection
            stats = self.handler.get_variable_stats(var_name, layer_idx, time_idx)
            v_min, v_max = stats['min'], stats['max']
            
            if existing_layer:
                # For mesh layers, it's more reliable to remove and recreate than to update
                # This avoids issues with cached group states
                
                # Capture the layer's position in the layer tree before removing
                layer_tree_root = QgsProject.instance().layerTreeRoot()
                old_tree_layer = layer_tree_root.findLayer(existing_layer.id())
                parent_group = None
                insert_index = 0
                
                if old_tree_layer:
                    parent_group = old_tree_layer.parent()
                    if parent_group:
                        # Get the index of this layer within its parent group
                        insert_index = parent_group.children().index(old_tree_layer)
                
                QgsProject.instance().removeMapLayer(existing_layer)
                existing_layer = None
                self.active_map_layer = None
            else:
                # No existing layer, so no position to preserve
                parent_group = None
                insert_index = 0
            
            # Always create a fresh layer for mesh
            layer = QgsMeshLayer(temp_path, display_name, "mdal")
            if layer.isValid():
                layer.setCrs(qgs_crs)
                
                # Force group 0 active before styling
                settings = layer.rendererSettings()
                settings.setActiveScalarDatasetGroup(0)
                settings.setActiveVectorDatasetGroup(0)
                layer.setRendererSettings(settings)
                
                # Apply styling based on mode
                if self.auto_update_color:
                    # Auto-update enabled: apply fresh styling with new min/max
                    self.style_mesh_layer(layer, min_val=v_min, max_val=v_max, idx=0)
                elif preserved_mesh_style:
                    # Auto-update disabled and we have preserved style: use it
                    settings = layer.rendererSettings()
                    settings.setScalarSettings(0, preserved_mesh_style)
                    layer.setRendererSettings(settings)
                else:
                    # No auto-update and no preserved style: apply default styling
                    self.style_mesh_layer(layer, min_val=v_min, max_val=v_max, idx=0)
                
                # Apply preserved mesh-level settings (wireframe, etc.) if they exist
                # This must happen AFTER style_mesh_layer to override its defaults
                if preserved_native_mesh or preserved_edges:
                    settings = layer.rendererSettings()
                    if preserved_native_mesh:
                        settings.setNativeMeshSettings(preserved_native_mesh)
                    if preserved_edges:
                        settings.setEdgeSettings(preserved_edges)
                    layer.setRendererSettings(settings)
                
                QgsProject.instance().addMapLayer(layer, False)  # False = don't add to legend yet
                
                # Mark this layer as managed by our plugin
                layer.setCustomProperty("nlmod_inspector_source", filepath)
                layer.setCustomProperty("nlmod_inspector_managed", True)
                layer.setCustomProperty("nlmod_inspector_var", var_name)
                layer.setCustomProperty("nlmod_inspector_layer_idx", int(layer_idx))
                layer.setCustomProperty("nlmod_inspector_time_idx", int(time_idx))
                
                # Add to layer tree at the preserved position
                layer_tree_root = QgsProject.instance().layerTreeRoot()
                if parent_group:
                    # Insert at the same position in the same group
                    parent_group.insertLayer(insert_index, layer)
                else:
                    # Add to root at the preserved index (or top if no previous position)
                    layer_tree_root.insertLayer(insert_index, layer)
                
                self.active_map_layer = layer
                self.active_var_name = var_name
            else:
                QtWidgets.QMessageBox.warning(self, "Error", "Failed to load the exported mesh file in QGIS.")


        elif grid_type == "structured":
            QgsMessageLog.logMessage(f"NLMOD: Loading structured layer for {var_name}", "NlmodInspector", Qgis.Info)
            
            # Try loading as Raster (NetCDF)
            safe_path = filepath.replace('\\', '/')
            uri = f'NETCDF:"{safe_path}":{var_name}'
            layer_name = f"{var_name} @ {base_name}"
            
            # Determine n_layers for this specific variable from NetCDF dimensions
            # This is crucial because different variables in the same file might have different dimensions
            # and we need to know the correct stride for GDAL's band indexing.
            n_layers = 1
            if self.handler and self.handler.ds and var_name in self.handler.ds.variables:
                var = self.handler.ds.variables[var_name]
                for d in var.dimensions:
                    # Common names for the vertical dimension in groundwater models
                    if d.lower() in ['layer', 'z', 'layer_index', 'lev', 'k']:
                        n_layers = self.handler.ds.dimensions[d].size
                        break
            
            # GDAL flattens NetCDF dimensions: band_idx = time_idx * n_layers + layer_idx + 1
            band_idx = (time_idx * n_layers) + layer_idx + 1
            QgsMessageLog.logMessage(f"NLMOD: Structured layer for {var_name}: indices [layer={layer_idx}/{n_layers}, time={time_idx}] -> band={band_idx}", "NlmodInspector", Qgis.Info)
            
            safe_path = filepath.replace('\\', '/')
            # (Note: display_name is already calculated above)

            # --- VRT Workaround for Coordinates & Rotation ---
            try:
                geotransform = self.handler.get_geotransform(var_name)
                extent = self.handler.get_extent(var_name)
                
                if geotransform and extent:
                    from osgeo import gdal
                    subdataset_uri = f'NETCDF:"{safe_path}":{var_name}'
                    ds = gdal.Open(subdataset_uri)
                    if ds:
                        if self.handler.angrot == 0:
                            # Standard Non-Rotated: Use Translate with outputBounds for auto-flipping
                            xmin, xmax, ymin, ymax, y_is_ascending = extent
                            vrt_ds = gdal.Translate('', ds, format='VRT', 
                                                    outputBounds=[xmin, ymin, xmax, ymax], 
                                                    bandList=[band_idx])
                        else:
                            # Rotated Grid: Manual Geotransform
                            # Translate first just to extract the band and basic VRT structure
                            vrt_ds = gdal.Translate('', ds, format='VRT', bandList=[band_idx])
                            if vrt_ds:
                                vrt_ds.SetGeoTransform(geotransform)
                                # We might still need the CRS from the handler
                                crs_wkt = self.handler.get_crs()
                                if crs_wkt:
                                    vrt_ds.SetProjection(crs_wkt)
                        
                        if vrt_ds:
                            vrt_xml = vrt_ds.GetMetadata('xml:VRT')[0]
                            vrt_ds = None # Close
                            
                            # Handle Ascending Y if necessary
                            y_is_ascending = extent[4]
                            if y_is_ascending:
                                var_info = self.handler.ds.variables[var_name]
                                y_size = var_info.shape[-2] if var_info.ndim >= 2 else 0
                                if y_size > 0:
                                    vrt_xml = vrt_xml.replace('yOff="0"', f'yOff="{y_size}"')
                                    vrt_xml = vrt_xml.replace(f'ySize="{y_size}"', f'ySize="-{y_size}"')
                                    QgsMessageLog.logMessage(f"NLMOD: Applied VRT flip for ascending Y (size={y_size})", "NlmodInspector", Qgis.Info)
                        else:
                            raise Exception("gdal.Translate failed")
                        ds = None
                    else:
                        raise Exception("Could not open subdataset")

                    # Save to physical temp file to allow QGIS to find it during project load
                    # (vsimem is faster but disappears on restart, causing "Unavailable layers" warnings)
                    import time
                    ts = int(time.time() * 1000)
                    vrt_path = os.path.join(tempfile.gettempdir(), f"nlmod_raster_{id(self)}_{ts}.vrt")
                    
                    try:
                        with open(vrt_path, "w") as f:
                            f.write(vrt_xml)
                        uri = vrt_path
                        QgsMessageLog.logMessage(f"NLMOD: Created VRT on disk at {uri}", "NlmodInspector", Qgis.Info)
                    except Exception as e:
                        QgsMessageLog.logMessage(f"NLMOD: Failed to write VRT to disk: {e}. Falling back to vsimem.", "NlmodInspector", Qgis.Warning)
                        vrt_mem_path = f"/vsimem/nlmod_raster_{id(self)}_{ts}.vrt"
                        gdal.FileFromMemBuffer(vrt_mem_path, vrt_xml)
                        uri = vrt_mem_path
            except Exception as e:
                QgsMessageLog.logMessage(f"NLMOD: VRT creation failed: {e}", "NlmodInspector", Qgis.Warning)

            # Capture existing style if we want to preserve it
            preserved_raster_renderer = None
            if existing_layer and not self.auto_update_color:
                try:
                    preserved_raster_renderer = existing_layer.renderer().clone()
                    QgsMessageLog.logMessage("NLMOD: Preserving raster renderer", "NlmodInspector", Qgis.Info)
                except Exception as e:
                    QgsMessageLog.logMessage(f"NLMOD: Failed to capture style: {e}", "NlmodInspector", Qgis.Warning)

            # Calculate actual min/max for the current selection
            stats = self.handler.get_variable_stats(var_name, layer_idx, time_idx)
            v_min, v_max = stats['min'], stats['max']

            if existing_layer:
                old_uri = existing_layer.source()
                existing_layer.setDataSource(uri, display_name, "gdal")
                existing_layer.reload()
                existing_layer.setName(display_name)
                
                if self.auto_update_color:
                    self.apply_raster_style(existing_layer, band_idx=1, min_val=v_min, max_val=v_max)
                elif preserved_raster_renderer:
                    existing_layer.setRenderer(preserved_raster_renderer)
                    QgsMessageLog.logMessage("NLMOD: Restored preserved raster style", "NlmodInspector", Qgis.Info)
                
                # Re-apply CRS to prevent "invalid projection" warning after setDataSource
                if not existing_layer.crs().isValid() or existing_layer.crs() != qgs_crs:
                    existing_layer.setCrs(qgs_crs)

                # Update metadata properties
                existing_layer.setCustomProperty("nlmod_inspector_var", var_name)
                existing_layer.setCustomProperty("nlmod_inspector_layer_idx", int(layer_idx))
                existing_layer.setCustomProperty("nlmod_inspector_time_idx", int(time_idx))

                existing_layer.triggerRepaint()
                
                # Cleanup old temp VRT
                if "nlmod_raster_" in old_uri:
                    try:
                        if "/vsimem/" in old_uri:
                            from osgeo import gdal
                            gdal.Unlink(old_uri)
                        elif os.path.exists(old_uri):
                            os.remove(old_uri)
                    except:
                        pass
                
                self.active_var_name = var_name
            else:
                layer = QgsRasterLayer(uri, display_name)
                if layer.isValid():
                    layer.setCrs(qgs_crs)
                    self.apply_raster_style(layer, band_idx=1, min_val=v_min, max_val=v_max)
                    QgsProject.instance().addMapLayer(layer)
                    
                    # Mark this layer as managed by our plugin
                    layer.setCustomProperty("nlmod_inspector_source", filepath)
                    layer.setCustomProperty("nlmod_inspector_managed", True)
                    layer.setCustomProperty("nlmod_inspector_var", var_name)
                    layer.setCustomProperty("nlmod_inspector_layer_idx", int(layer_idx))
                    layer.setCustomProperty("nlmod_inspector_time_idx", int(time_idx))
                    
                    self.active_map_layer = layer
                    self.active_var_name = var_name
                else:
                    QtWidgets.QMessageBox.warning(self, "Error", f"Failed to load variable '{var_name}'.")
        else:
            # Unknown grid, try Mesh
            layer = QgsMeshLayer(filepath, base_name, "mdal")
            if layer.isValid():
                if not layer.crs().isValid():
                    layer.setCrs(QgsCoordinateReferenceSystem("EPSG:28992"))
                
                QgsProject.instance().addMapLayer(layer)
                self.activate_mesh_dataset(layer, var_name)
                self.style_mesh_layer(layer)
            else:
                QtWidgets.QMessageBox.warning(self, "Error", "Could not load file.")


    def apply_raster_style(self, layer, band_idx=1, min_val=None, max_val=None):
        """Helper to apply Turbo colormap to raster layers."""
        try:
            def get_ramp(name, default_colors):
                style = QgsStyle.defaultStyle()
                ramp = style.colorRamp(name)
                if not ramp:
                    from qgis.PyQt.QtGui import QColor
                    return QgsGradientColorRamp(QColor(default_colors[0]), QColor(default_colors[1]))
                return ramp

            ramp = get_ramp("Turbo", ["blue", "red"])
            if not ramp:
                 style = QgsStyle.defaultStyle()
                 ramp = style.colorRamp("Spectral")

            if ramp:
                # If values weren't passed, try to get them from the provider
                if min_val is None or max_val is None:
                    # Statistics
                    stats = layer.dataProvider().bandStatistics(band_idx, QgsRasterBandStats.Min | QgsRasterBandStats.Max, layer.extent(), 0)
                    min_val, max_val = stats.minimumValue, stats.maximumValue
                
                # Robustly handle NaN/Inf and Constant values
                import math
                if math.isnan(min_val) or math.isinf(min_val): min_val = 0.0
                if math.isnan(max_val) or math.isinf(max_val): max_val = 1.0
                
                if min_val >= max_val:
                    # Constant value or single pixel - use wider buffer for stability
                    min_val = min_val - 1.0
                    max_val = max_val + 1.0

                fcn = QgsColorRampShader(min_val, max_val)
                fcn.setColorRampType(QgsColorRampShader.Interpolated)
                fcn.setSourceColorRamp(ramp)
                
                # Manual item generation ensures we use our sanitized min/max 
                # instead of potentially stale provider metrics
                items = []
                steps = 10
                for i in range(steps):
                    v = min_val + (max_val - min_val) * i / (steps - 1)
                    color = ramp.color(i / (steps - 1))
                    items.append(QgsColorRampShader.ColorRampItem(v, color, f"{v:.4g}"))
                fcn.setColorRampItemList(items)
                
                shader = QgsRasterShader()
                shader.setRasterShaderFunction(fcn)
                renderer = QgsSingleBandPseudoColorRenderer(layer.dataProvider(), band_idx, shader)
                layer.setRenderer(renderer)
                layer.triggerRepaint()
                
                # Force canvas refresh to be absolutely sure
                if self.iface:
                    self.iface.mapCanvas().refresh()
        except Exception as e:
            QgsMessageLog.logMessage(f"NLMOD: Raster styling failed: {e}", "NlmodInspector", Qgis.Warning)

    def style_mesh_layer(self, layer, min_val=None, max_val=None, idx=None):
        """Applies the Turbo colormap to a mesh layer's active scalar dataset."""
        try:
            # 1. Get Turbo Ramp
            def get_ramp(name, default_colors):
                style = QgsStyle.defaultStyle()
                ramp = style.colorRamp(name)
                if not ramp:
                    return QgsGradientColorRamp(QColor(default_colors[0]), QColor(default_colors[1]))
                return ramp

            from qgis.PyQt.QtGui import QColor
            from qgis.core import QgsMeshRendererScalarSettings
            ramp = get_ramp("Turbo", ["blue", "red"])
            if not ramp:
                return

            # 2. Get dataset group index
            if idx is None:
                idx = int(layer.rendererSettings().activeScalarDatasetGroup())
                if idx < 0: 
                    if layer.datasetGroupCount() > 0:
                        idx = 0
                    else:
                        return
            
            # 3. Get bounds for shader
            if min_val is None or max_val is None:
                # Using dataProvider is often more robust for metadata in PyQGIS
                provider = layer.dataProvider()
                if provider:
                    meta = provider.datasetGroupMetadata(idx)
                else:
                    meta = layer.datasetGroupMetadata(idx)
                
                # Robustly try to get min/max from metadata
                min_val = None
                max_val = None
                
                if hasattr(meta, 'minimumValue'):
                    min_val = meta.minimumValue()
                    max_val = meta.maximumValue()
                elif hasattr(meta, 'statistic'):
                    try:
                        min_val = meta.statistic(0)
                        max_val = meta.statistic(1)
                    except:
                        pass
                elif hasattr(meta, 'minimum'):
                    min_val = meta.minimum()
                    max_val = meta.maximum()
                
                # Use dataProvider as secondary source for min/max
                if (min_val is None or max_val is None) and provider:
                    stats = provider.datasetGroupMetadata(idx) # Re-fetch metadata

                # Sanitize values
                import math
                if min_val is None or math.isnan(min_val) or math.isinf(min_val): min_val = 0.0
                if max_val is None or math.isnan(max_val) or math.isinf(max_val): max_val = 1.0
            
            if min_val >= max_val:
                min_val -= 1.0
                max_val += 1.0

            # 4. Create Shader
            shader = QgsColorRampShader(min_val, max_val)
            shader.setColorRampType(QgsColorRampShader.Interpolated)
            shader.setSourceColorRamp(ramp)
            # MDAL doesn't have classifyColorRamp directly on shader in the same way 
            # as raster data provider, so we manually build items if needed 
            # OR just set the ramp and QGIS often handles it if we set discrete/interpolated.
            # Actually fcn.classifyColorRamp(...) is on QgsColorRampShader.
            # But MDAL renderer might prefer a full ramp list.
            
            items = []
            steps = 10
            for i in range(steps):
                v = min_val + (max_val - min_val) * i / (steps - 1)
                color = ramp.color(i / (steps - 1))
                items.append(QgsColorRampShader.ColorRampItem(v, color, f"{v:.4g}"))
            shader.setColorRampItemList(items)

            # 5. Apply to Mesh Settings
            settings = layer.rendererSettings()
            scalar_settings = settings.scalarSettings(idx)
            scalar_settings.setColorRampShader(shader)
            
            # Ensure it is enabled (method name/existence varies)
            if hasattr(scalar_settings, 'setEnabled'):
                scalar_settings.setEnabled(True)
                
            # Set to interpolated (method name/existence varies)
            if hasattr(scalar_settings, 'setDataResamplingMethod'):
                # Resampling methods: 0=None, 1=Neighbor, 2=Linear
                # Setting to 0 (None) by default as requested.
                scalar_settings.setDataResamplingMethod(0)
            
            settings.setScalarSettings(idx, scalar_settings)
            
            # 6. Native Mesh Rendering (Wireframe)
            # User requested 0.1 mm line width
            if hasattr(settings, 'nativeMeshSettings'):
                m_set = settings.nativeMeshSettings()
                m_set.setEnabled(True)
                m_set.setLineWidth(0.1)
                if hasattr(Qgis, 'RenderMillimeters'):
                    m_set.setLineWidthUnit(Qgis.RenderMillimeters)
                settings.setNativeMeshSettings(m_set)
            
            if hasattr(settings, 'edgeSettings'):
                # Keep edges disabled unless explicitly asked, 
                # as native mesh usually covers the wireframe needs.
                e_set = settings.edgeSettings()
                e_set.setEnabled(False)
                settings.setEdgeSettings(e_set)

            layer.setRendererSettings(settings)
            layer.triggerRepaint()
            
            # Force canvas refresh
            if self.iface:
                self.iface.mapCanvas().refresh()

        except Exception as e:
            QgsMessageLog.logMessage(f"NLMOD: Mesh styling failed: {e}", "NlmodInspector", Qgis.Warning)


    def activate_mesh_dataset(self, layer, var_name):
        """Sets the active scalar and vector dataset group by name."""
        count = layer.datasetGroupCount()
        for i in range(count):
            meta = layer.datasetGroupMetadata(i)
            if meta.name() == var_name:
                settings = layer.rendererSettings()
                settings.setActiveScalarDatasetGroup(i)
                settings.setActiveVectorDatasetGroup(i)
                layer.setRendererSettings(settings)
                break


    def get_or_create_xs_tool(self):
        """Helper to get or create the cross-section map tool with signals connected."""
        if not hasattr(self, "xs_tool") or self.xs_tool is None:
            from .cross_section_tool import CrossSectionMapTool
            canvas = self.iface.mapCanvas()
            self.xs_tool = CrossSectionMapTool(canvas)
            self.xs_tool.line_finished.connect(self.on_cross_section_finished)
            self.xs_tool.points_changed.connect(self.on_cross_section_changed)
        return self.xs_tool

    def activate_cross_section_tool(self):
        # 1. Automatic variable selection if none is picked
        selected_items = self.var_list.selectedItems()
        if not selected_items and self.handler and self.handler.ds:
            possible_layer_dims = {'layer', 'z'}
            found_idx = -1
            for i in range(self.var_list.count()):
                v_name = self.var_list.item(i).data(QtCore.Qt.UserRole)
                if v_name in self.handler.ds.variables:
                    v_dims = self.handler.ds.variables[v_name].dimensions
                    if any(d in possible_layer_dims for d in v_dims):
                        found_idx = i
                        break
            
            if found_idx != -1:
                self.var_list.setCurrentRow(found_idx)
                selected_items = self.var_list.selectedItems()

        # Check if a variable is selected and has layer dimension
        if not selected_items:
            QtWidgets.QMessageBox.information(self, "Info", "Please select a 3D variable first.")
            return
            
        var_name = selected_items[0].data(QtCore.Qt.UserRole)
        
        # Final validation check
        if self.handler and self.handler.ds:
            var = self.handler.ds.variables[var_name]
            has_layer_dim = False
            possible_layer_dims = {'layer', 'z'}
            
            for dim in var.dimensions:
                if dim in possible_layer_dims:
                    has_layer_dim = True
                    break
            
            if not has_layer_dim:
                QtWidgets.QMessageBox.warning(
                    self, 
                    "Invalid Variable", 
                    f"Variable '{var_name}' does not have a layer dimension.\n\n"
                    "Cross-sections require 3D variables with layers (e.g., 'layer', 'z')."
                )
                return
        
        try:
            canvas = self.iface.mapCanvas()
            tool = self.get_or_create_xs_tool()
            
            if canvas.mapTool() != tool:
                self.prev_map_tool = canvas.mapTool()
                canvas.setMapTool(tool)
            
            # Allow new drawing
            tool.can_draw = True
            
            # Reset tool for new drawing
            tool.set_points([])
            self.active_cs_id = None
            
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Tool Error", f"Failed to start tool: {e}")

    def fetch_cross_section_data(self, var_name, points, time_idx=None):
        """Callback for CrossSectionPlotWindow to fetch data."""
        if not self.handler:
            return None
            
        if time_idx is None:
            time_idx = self.time_slider.value() if self.time_slider.isEnabled() else 0
            
        # Transform points to Model CRS
        try:
            from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform
            canvas_crs = self.iface.mapCanvas().mapSettings().destinationCrs()
            model_crs_def = self.handler.get_crs()
            model_crs = QgsCoordinateReferenceSystem(model_crs_def if model_crs_def else "EPSG:28992")
            
            if model_crs.isValid() and canvas_crs != model_crs:
                xform = QgsCoordinateTransform(canvas_crs, model_crs, QgsProject.instance())
                points = [xform.transform(p) for p in points]
        except:
            pass
            
        return self.handler.get_cross_section_data(var_name, points, time_idx=time_idx)

    def add_cross_section_plot(self, points, var_name, cs_label=None, item_id=None,
                               z_range=None, x_range=None, v_range=None, visible=True,
                               show_layers=True, show_cells=False, show_layer_names=True, use_log=False,
                               cmap_name='Turbo', invert_cmap=False, time_idx=None):
        """Creates a cross-section window and adds it to the UI/Map."""
        if not points or len(points) < 2:
            return

        # 1. Get all 3D variables for the combo box
        vars_3d = self.get_vars_3d()
        if not vars_3d:
            vars_3d = [var_name]
        
        all_vars = self.get_all_vars()

        # 1.5 Get current time info
        time_idx = time_idx if time_idx is not None else (self.time_slider.value() if self.time_slider.isEnabled() else 0)
        time_values = self.handler.get_dimensions_metadata()["times"]

        # 2. Extract Data
        try:
            data = self.fetch_cross_section_data(var_name, points, time_idx=time_idx)
            if not data:
                return
            if "error" in data:
                QtWidgets.QMessageBox.warning(self, "Error", data["error"])
                return
                
            # 3. Calculate cumulative distances for vertices (in model units)
            dist_points = points
            try:
                from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform
                canvas_crs = self.iface.mapCanvas().mapSettings().destinationCrs()
                model_crs_def = self.handler.get_crs()
                model_crs = QgsCoordinateReferenceSystem(model_crs_def if model_crs_def else "EPSG:28992")
                if model_crs.isValid() and canvas_crs != model_crs:
                    xform = QgsCoordinateTransform(canvas_crs, model_crs, QgsProject.instance())
                    dist_points = [xform.transform(p) for p in points]
            except:
                pass

            v_dists = [0.0]
            curr_d = 0.0
            for i in range(len(dist_points)-1):
                p1 = dist_points[i]
                p2 = dist_points[i+1]
                curr_d += ((p2.x()-p1.x())**2 + (p2.y()-p1.y())**2)**0.5
                v_dists.append(curr_d)

            # 4. Handle Labels and IDs
            import time
            if item_id is None:
                item_id = str(time.time())
            
            if cs_label is None:
                cs_label = self.get_next_cs_label()
            
            from .cross_section_plot import CrossSectionPlotWindow
            
            # 4. Show Window
            win = CrossSectionPlotWindow(
                data, var_name, self, vertex_distances=v_dists,
                item_id=item_id, all_vars=vars_3d, head_vars=all_vars, data_fetcher=self.fetch_cross_section_data,
                label=cs_label, points=points, z_range=z_range, x_range=x_range, v_range=v_range,
                show_layers=show_layers, show_cells=show_cells, show_layer_names=show_layer_names,
                use_log=use_log, cmap_name=cmap_name, invert_cmap=invert_cmap,
                time_values=time_values, time_idx=time_idx
            )
            win.variable_changed.connect(self.update_cs_list_label)
            win.cursor_moved.connect(self.on_cs_cursor_moved)
            win.cursor_left.connect(self.on_cs_cursor_left)
            win.range_changed.connect(self.save_state_to_project)
            win.visibilityChanged.connect(self.save_state_to_project)
            win.settings_changed.connect(self.save_state_to_project)
            win.sigPointPicked.connect(self.on_cs_point_picked)
            win.variable_changed.connect(lambda id, v: self.sync_ts_on_cross_sections())
            
            # Create Label: A: Head
            display_label = f"{cs_label}: {var_name}"
            
            item = QtWidgets.QListWidgetItem(display_label)
            item.setData(QtCore.Qt.UserRole, item_id)
            self.cs_list.addItem(item)
            
            # Select it
            self.cs_list.setCurrentItem(item)
            
            # Store
            self.plot_windows[item_id] = win
            self.cs_geometries[item_id] = points 
            self.active_cs_id = item_id
            
            # Dock it in QGIS
            self.iface.addDockWidget(QtCore.Qt.BottomDockWidgetArea, win)
            if visible:
                win.show()
            else:
                win.hide()
            
            # Create RubberBand
            from qgis.gui import QgsRubberBand
            from qgis.core import QgsWkbTypes
            from qgis.PyQt.QtGui import QColor
            
            rubber_band = QgsRubberBand(self.iface.mapCanvas(), QgsWkbTypes.LineGeometry)
            rubber_band.setColor(QColor(255, 0, 0, 180)) 
            rubber_band.setWidth(3)
            rubber_band.setLineStyle(QtCore.Qt.DashLine)
            
            for point in points:
                rubber_band.addPoint(point)
            
            rubber_band.show()
            self.cs_rubber_bands[item_id] = rubber_band
            
            self.highlight_cross_section(item)
            self.save_state_to_project()
            return win
            
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Plot Error", f"Failed to plot: {e}")

    def on_cross_section_finished(self, points):
        """Called when user finishes drawing a line."""
        if not points or len(points) < 2:
            return
            
        selected_items = self.var_list.selectedItems()
        if not selected_items:
            QtWidgets.QMessageBox.information(self, "Info", "Please select a variable first.")
            return
            
        var_name = selected_items[0].data(QtCore.Qt.UserRole)
        
        # Restore previous map tool
        if self.prev_map_tool:
            self.iface.mapCanvas().setMapTool(self.prev_map_tool)
            self.prev_map_tool = None
            
        # Disable further drawing until Add is pressed again
        if hasattr(self, 'xs_tool') and self.xs_tool:
            self.xs_tool.can_draw = False

        self.add_cross_section_plot(points, var_name)

    def on_cross_section_changed(self, points):
        """Update existing plot window when geometry is edited on map."""
        if not self.active_cs_id or self.active_cs_id not in self.plot_windows:
            return
            
        item_id = self.active_cs_id
        win = self.plot_windows[item_id]
        
        # 1. Get current variable name from plot window
        var_name = win.current_var
        
        # 2. Update window points (canvas points)
        win.points = points
        
        # 3. Extract new data (points are transformed inside fetcher)
        try:
            data = self.fetch_cross_section_data(var_name, points)
            if not data or "error" in data:
                return
                
            # 4. Calculate cumulative distances for vertices (in model units)
            dist_points = points
            try:
                from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform
                canvas_crs = self.iface.mapCanvas().mapSettings().destinationCrs()
                model_crs_def = self.handler.get_crs()
                model_crs = QgsCoordinateReferenceSystem(model_crs_def if model_crs_def else "EPSG:28992")
                if model_crs.isValid() and canvas_crs != model_crs:
                    xform = QgsCoordinateTransform(canvas_crs, model_crs, QgsProject.instance())
                    dist_points = [xform.transform(p) for p in points]
            except:
                pass

            v_dists = [0.0]
            curr_d = 0.0
            for i in range(len(dist_points)-1):
                p1 = dist_points[i]
                p2 = dist_points[i+1]
                curr_d += ((p2.x()-p1.x())**2 + (p2.y()-p1.y())**2)**0.5
                v_dists.append(curr_d)

            win.vertex_distances = v_dists
            win.render_data(data, vertex_distances=v_dists)
            
            # 5. Update persistent rubber band and geometry
            self.cs_geometries[item_id] = points
            if item_id in self.cs_rubber_bands:
                rb = self.cs_rubber_bands[item_id]
                rb.reset()
                for p in points:
                    rb.addPoint(p)
                rb.show()
            
            self.save_state_to_project()
                
        except Exception as e:
            print(f"Error updating cross-section on change: {e}")

    def highlight_cross_section(self, item):
        from qgis.PyQt.QtGui import QColor
        item_id = item.data(QtCore.Qt.UserRole)
        
        # Highlight rubber band on map
        # Hide all other rubber bands and show only the selected one
        for rb_id, rb in self.cs_rubber_bands.items():
            if rb_id == item_id:
                rb.setWidth(4)  # Make selected thicker
                rb.setColor(QColor(255, 0, 0, 255))  # Fully opaque red
            else:
                rb.setWidth(2)  # Make others thinner
                rb.setColor(QColor(255, 0, 0, 100))  # More transparent
        
        self.active_cs_id = item_id

        # Ensure tool is active and loaded with these points
        try:
            canvas = self.iface.mapCanvas()
            tool = self.get_or_create_xs_tool()
            
            # If we are highlighting, we are in edit mode, so disable new drawing
            tool.can_draw = False
            
            if canvas.mapTool() != tool:
                self.prev_map_tool = canvas.mapTool()
                canvas.setMapTool(tool)
            
            # Load points into tool for editing
            # Note: We use the points stored in the plot window if available, 
            # as they are the most up-to-date canvas points.
            points = []
            if item_id in self.plot_windows:
                points = self.plot_windows[item_id].points
            else:
                points = self.cs_geometries.get(item_id, [])
                
            tool.set_points(points)
        except Exception as e:
            QgsMessageLog.logMessage(f"NLMOD: Failed to activate edit tool: {e}", "NlmodInspector", Qgis.Warning)

    def raise_cross_section_window(self, item):
        item_id = item.data(QtCore.Qt.UserRole)
        
        # Show window
        if item_id in self.plot_windows:
            win = self.plot_windows[item_id]
            win.show()
            win.raise_()
            win.activateWindow()
            self.highlight_cross_section(item)

    def on_cs_list_context_menu(self, pos):
        item = self.cs_list.itemAt(pos)
        if not item: return
        
        item_id = item.data(QtCore.Qt.UserRole)
        
        menu = QtWidgets.QMenu(self)
        
        rename_action = menu.addAction("Rename")
        edit_pts_action = menu.addAction("Edit vertices...")
        
        menu.addSeparator()
        
        move_up = menu.addAction("Move Up")
        move_down = menu.addAction("Move Down")
        
        action = menu.exec_(self.cs_list.mapToGlobal(pos))
        
        if action == rename_action:
            self.rename_cross_section(item)
        elif action == edit_pts_action:
            self.edit_cross_section_vertices(item_id)
        elif action == move_up:
            self.move_cs_item(item, -1)
        elif action == move_down:
            self.move_cs_item(item, 1)

    def move_cs_item(self, item, direction):
        row = self.cs_list.row(item)
        new_row = row + direction
        if 0 <= new_row < self.cs_list.count():
            current = self.cs_list.takeItem(row)
            self.cs_list.insertItem(new_row, current)
            self.cs_list.setCurrentItem(current)
            self.save_state_to_project()

    def rename_cross_section(self, item):
        item_id = item.data(QtCore.Qt.UserRole)
        win = self.plot_windows.get(item_id)
        if not win: return
        
        new_label, ok = QtWidgets.QInputDialog.getText(
            self, "Rename Cross-Section", "New Label:", 
            QtWidgets.QLineEdit.Normal, win.cs_label)
            
        if ok and new_label:
            win.cs_label = new_label
            win.setWindowTitle(f"Cross Section {new_label}: {win.current_var}")
            self.update_cs_list_label(item_id, win.current_var)
            self.save_state_to_project()

    def edit_cross_section_vertices(self, item_id):
        points = self.cs_geometries.get(item_id)
        if not points: return
        
        dlg = VertexEditorDialog(points, self)
        if dlg.exec_() == QtWidgets.QDialog.Accepted:
            new_points = dlg.get_points()
            if len(new_points) >= 2:
                # Set active and trigger update
                self.active_cs_id = item_id
                self.on_cross_section_changed(new_points)

    def update_cs_list_label(self, item_id, new_var_name):
        """Update the list widget text when a plot's variable changes."""
        for i in range(self.cs_list.count()):
            item = self.cs_list.item(i)
            if item.data(QtCore.Qt.UserRole) == item_id:
                # Find the label (A, B, C...) from the window title or similar
                # Or just reconstruct if we store it.
                # The window itself has cs_label.
                if item_id in self.plot_windows:
                    cs_label = self.plot_windows[item_id].cs_label
                    item.setText(f"{cs_label}: {new_var_name}")
                break
        self.save_state_to_project()

    def on_cs_selection_changed(self):
        """Called when selection in cross-section list changes."""
        selected = self.cs_list.selectedItems()
        if selected:
            # Clear TS selection to avoid tool conflicts
            self.ts_list.blockSignals(True)
            self.ts_list.clearSelection()
            self.ts_list.blockSignals(False)
            
            self.highlight_cross_section(selected[0])

    def on_ts_selection_changed(self):
        """Called when selection in time series list changes."""
        selected = self.ts_list.selectedItems()
        if selected:
            # Clear CS selection to avoid tool conflicts
            self.cs_list.blockSignals(True)
            self.cs_list.clearSelection()
            self.cs_list.blockSignals(False)
            
            # Note: highlight_cross_section already handles clearing markers/tool if needed?
            # No, but we can do it here. 
            item_id = selected[0].data(QtCore.Qt.UserRole)
            self.active_ts_id = item_id
            
            if item_id in self.ts_points:
                # Automatically activate/initialize tool for dragging if not active
                if self.iface.mapCanvas().mapTool() != getattr(self, 'ts_tool', None):
                    self.activate_point_tool()
                
                # Update the tool's marker position
                if hasattr(self, 'ts_tool') and self.ts_tool:
                    self.ts_tool.set_point(self.ts_points[item_id])
                    
            # Reset CS highlight state (un-highlight all)
            for rb in self.cs_rubber_bands.values():
                from qgis.PyQt.QtGui import QColor
                rb.setWidth(2)
                rb.setColor(QColor(255, 0, 0, 100))
            self.active_cs_id = None
            self.sync_ts_on_cross_sections()

    def sync_ts_on_cross_sections(self):
        """Draw markers on cross-section plots for any TS points that intersect them."""
        import numpy as np
        for cs_id, cs_win in self.plot_windows.items():
            cs_win.clear_ts_sync_markers()
            
            # Check cell indices in cross-section
            if not hasattr(cs_win, 'data') or 'indices' not in cs_win.data:
                continue
                
            cs_indices = cs_win.data['indices']
            dists = cs_win.data['distances']
            rendered_top = getattr(cs_win, 'rendered_top', None)
            rendered_botm = getattr(cs_win, 'rendered_botm', None)
            
            if rendered_top is None or rendered_botm is None:
                continue
            
            for ts_id, ts_win in self.ts_windows.items():
                if ts_win.current_var != cs_win.current_var:
                    continue
                
                # Find cell info for TS
                if not ts_win.data or 'cell_info' not in ts_win.data:
                    continue
                
                ts_cell = ts_win.data['cell_info']
                
                # Find where this cell is in the CS segments
                if isinstance(ts_cell, (list, tuple)):
                    # Structured
                    tr, tc = ts_cell
                    if isinstance(cs_indices, tuple):
                        csr, csc = cs_indices
                        matches = np.where((csr == tr) & (csc == tc))[0]
                else:
                    # Vertex
                    if not isinstance(cs_indices, tuple):
                        matches = np.where(cs_indices == ts_cell)[0]
                
                # Double points fix: each segment has two entries (entry/exit). 
                # We only want the starting index (even) to get the correct midpoint.
                matches = [m for m in matches if m % 2 == 0]
                
                for m_idx in matches:
                    # dists has double points [entry, exit, entry, exit]
                    # indices/values match these segments.
                    # We usually want the flat parts if they exist.
                    # m_idx is the index into indices/values and first of distance pair.
                    x_mid = (dists[m_idx] + dists[m_idx+1]) / 2.0
                    
                    # For each selected layer in TS
                    for lyr_idx in ts_win.layer_indices:
                        if lyr_idx < rendered_botm.shape[0]:
                            l_top = rendered_top[m_idx] if lyr_idx == 0 else rendered_botm[lyr_idx-1, m_idx]
                            l_bot = rendered_botm[lyr_idx, m_idx]
                            
                            if not np.isnan(l_top) and not np.isnan(l_bot):
                                y_mid = (l_top + l_bot) / 2.0
                                cs_win.add_ts_sync_marker(x_mid, y_mid)

    def remove_cross_section_by_id(self, item_id):
        """Cleanup when plot window is closed directly or removed from list."""
        # Clear tool if this was the active CS
        if self.active_cs_id == item_id:
            self.active_cs_id = None
            if hasattr(self, 'xs_tool') and self.xs_tool:
                self.xs_tool.set_points([])

        if item_id in self.plot_windows:
            win = self.plot_windows[item_id]
            self.iface.removeDockWidget(win)
            win.deleteLater()
            del self.plot_windows[item_id]
            
        if item_id in self.cs_rubber_bands:
            rb = self.cs_rubber_bands[item_id]
            rb.reset()
            self.iface.mapCanvas().scene().removeItem(rb)
            del self.cs_rubber_bands[item_id]
            
        if item_id in self.cs_geometries:
            del self.cs_geometries[item_id]
            
        self.save_state_to_project()
            
        # Also remove from list if it's still there (e.g. if closed via [X] on dock)
        for i in range(self.cs_list.count()):
            item = self.cs_list.item(i)
            if item.data(QtCore.Qt.UserRole) == item_id:
                # Block signals to avoid recursive selection changes
                self.cs_list.blockSignals(True)
                self.cs_list.takeItem(i)
                self.cs_list.blockSignals(False)
                break
        
        self.sync_ts_on_cross_sections()
    def activate_point_tool(self):
        if not self.handler:
            QtWidgets.QMessageBox.warning(self, "Warning", "Please open a NetCDF file first.")
            return

        if not hasattr(self, 'ts_tool') or not self.ts_tool:
            self.ts_tool = TimeSeriesMapTool(self.iface.mapCanvas())
            self.ts_tool.point_clicked.connect(self.on_point_picked)
            self.ts_tool.point_moved.connect(self.on_point_moved)

        curr_tool = self.iface.mapCanvas().mapTool()
        if curr_tool != self.ts_tool:
            self.prev_map_tool = curr_tool
            
        self.iface.mapCanvas().setMapTool(self.ts_tool)

    def on_point_picked(self, point):
        # Create a new Time Series
        win = self.add_time_series_plot(point)
        if not win and hasattr(self, 'ts_tool') and self.ts_tool:
            # Clear the temporary marker if plot creation failed (e.g. no time dimension)
            self.ts_tool.clear_point()
            
            # Only deactivate if it failed
            if self.prev_map_tool:
                self.iface.mapCanvas().setMapTool(self.prev_map_tool)
                self.prev_map_tool = None

    def on_point_moved(self, point):
        if self.active_ts_id and self.active_ts_id in self.ts_windows:
            win = self.ts_windows[self.active_ts_id]
            win.point = point
            # Refresh data (this calls update_info_label inside)
            win.change_variable(win.current_var)
            
            # Snap to what the handler found
            if 'point' in win.data:
                from qgis.core import QgsPointXY
                px, py = win.data['point']
                point = QgsPointXY(px, py)
                win.point = point
            
            # Update markers
            if self.active_ts_id in self.ts_markers:
                self.ts_markers[self.active_ts_id].setCenter(point)
            
            if hasattr(self, 'ts_tool') and self.ts_tool:
                self.ts_tool.set_point(point)
            
            self.ts_points[self.active_ts_id] = point
            self.save_state_to_project()
            self.sync_ts_on_cross_sections()

    def on_cs_point_picked(self, point):
        """Called when a point is clicked in a cross-section plot."""
        # Only act if we are currently in "Add Time Series" mode or TS tool is active
        if hasattr(self, 'ts_tool') and self.iface.mapCanvas().mapTool() == self.ts_tool:
            # If we are NOT dragging an existing point, treat this as a new point pick
            if not self.ts_tool.is_dragging:
                self.on_point_picked(point)

    def add_time_series_plot(self, point, var_name=None, ts_label=None, item_id=None, layer_indices=None):
        if not self.handler: return
        
        if not var_name:
            selected = self.var_list.selectedItems()
            var_name = selected[0].data(QtCore.Qt.UserRole) if selected else self.get_vars_with_time()[0]
        
        if not item_id:
            import uuid
            item_id = str(uuid.uuid4())
            
        if not ts_label:
            ts_label = str(len(self.ts_windows) + 1)
            
        if layer_indices is None:
            # Default to all layers for time series
            dim_meta = self.handler.get_dimensions_metadata()
            if dim_meta['layers']:
                layer_indices = list(range(len(dim_meta['layers'])))
            else:
                layer_indices = [0]

        # Fetch initial data
        from qgis.PyQt.QtGui import QColor
        from qgis.gui import QgsVertexMarker
        try:
            data = self.handler.get_timeseries_data(var_name, point, layer_indices)
            if not data or "error" in data:
                QtWidgets.QMessageBox.warning(self, "Error", data.get("error", "No data found"))
                return
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Error", f"Failed to fetch data: {e}")
            return

        # Snapshot the snapped point if available
        if 'point' in data:
            from qgis.core import QgsPointXY
            px, py = data['point']
            point = QgsPointXY(px, py)

        win = TimeSeriesPlotWindow(
            data, var_name, parent=self.iface.mainWindow(),
            item_id=item_id, all_vars=self.get_vars_with_time(),
            data_fetcher=self.handler.get_timeseries_data,
            label=ts_label, point=point, layer_indices=layer_indices
        )
        
        self.ts_windows[item_id] = win
        self.ts_points[item_id] = point
        
        # Create persistent marker
        marker = QgsVertexMarker(self.iface.mapCanvas())
        marker.setCenter(point)
        marker.setColor(QColor(0, 0, 255))
        marker.setIconType(QgsVertexMarker.ICON_X)
        marker.setPenWidth(2)
        marker.setIconSize(10)
        self.ts_markers[item_id] = marker
        
        # Signals
        win.variable_changed.connect(lambda id, v: self.update_ts_list_item(id))
        win.variable_changed.connect(lambda id, v: self.sync_ts_on_cross_sections())
        win.layers_changed.connect(lambda id, l: self.save_state_to_project())
        win.layers_changed.connect(lambda id, l: self.sync_ts_on_cross_sections())
        # Removing win.closed connection to remove_time_series_by_id 
        # so closing the pane doesn't remove it from the list.
        # Change visibility to Bottom pane as requested
        self.iface.addDockWidget(QtCore.Qt.BottomDockWidgetArea, win)
        
        # Add to list
        item = QtWidgets.QListWidgetItem(f"{ts_label}: {var_name}")
        item.setData(QtCore.Qt.UserRole, item_id)
        self.ts_list.addItem(item)
        self.ts_list.setCurrentItem(item)
        
        self.active_ts_id = item_id
        if hasattr(self, 'ts_tool'):
            self.ts_tool.set_point(point)

        self.save_state_to_project()
        return win

    def update_ts_list_item(self, item_id):
        if item_id in self.ts_windows:
            win = self.ts_windows[item_id]
            for i in range(self.ts_list.count()):
                item = self.ts_list.item(i)
                if item.data(QtCore.Qt.UserRole) == item_id:
                    item.setText(f"{win.label}: {win.current_var}")
                    break
        self.save_state_to_project()

    def remove_time_series(self):
        selected = self.ts_list.selectedItems()
        if not selected: return
        item_id = selected[0].data(QtCore.Qt.UserRole)
        self.remove_time_series_by_id(item_id)

    def remove_time_series_by_id(self, item_id):
        if item_id in self.ts_windows:
            win = self.ts_windows.pop(item_id)
            self.iface.removeDockWidget(win)
            win.deleteLater()
            
        if item_id in self.ts_markers:
            m = self.ts_markers.pop(item_id)
            self.iface.mapCanvas().scene().removeItem(m)
            
        if item_id in self.ts_points:
            del self.ts_points[item_id]
            
        for i in range(self.ts_list.count()):
            item = self.ts_list.item(i)
            if item.data(QtCore.Qt.UserRole) == item_id:
                self.ts_list.takeItem(i)
                break
                
        if self.active_ts_id == item_id:
            self.active_ts_id = None
            if hasattr(self, 'ts_tool'):
                self.ts_tool.set_point(None)
        
        self.sync_ts_on_cross_sections()
                
        self.save_state_to_project()
        self.update_ui_state()

    def raise_timeseries_window(self, item=None):
        if not item:
            selected = self.ts_list.selectedItems()
            if not selected: return
            item = selected[0]
            
        item_id = item.data(QtCore.Qt.UserRole)
        if item_id in self.ts_windows:
            win = self.ts_windows[item_id]
            win.show()
            win.raise_()
            win.activateWindow() # Add focus
            self.active_ts_id = item_id
            if hasattr(self, 'ts_tool'):
                self.ts_tool.set_point(self.ts_points[item_id])

    def on_ts_list_context_menu(self, pos):
        item = self.ts_list.itemAt(pos)
        if not item: return
        
        item_id = item.data(QtCore.Qt.UserRole)
        
        menu = QtWidgets.QMenu(self)
        rename_action = menu.addAction("Rename")
        edit_pos_action = menu.addAction("Edit Coordinates...")
        
        menu.addSeparator()
        
        move_up = menu.addAction("Move Up")
        move_down = menu.addAction("Move Down")
        
        action = menu.exec_(self.ts_list.mapToGlobal(pos))
        
        if action == rename_action:
            self.rename_time_series(item)
        elif action == edit_pos_action:
            self.edit_ts_point(item_id)
        elif action == move_up:
            self.move_ts_item(item, -1)
        elif action == move_down:
            self.move_ts_item(item, 1)

    def move_ts_item(self, item, direction):
        row = self.ts_list.row(item)
        new_row = row + direction
        if 0 <= new_row < self.ts_list.count():
            # Remove and re-insert
            self.ts_list.takeItem(row)
            self.ts_list.insertItem(new_row, item)
            self.ts_list.setCurrentItem(item)
            self.save_state_to_project()

    def rename_time_series(self, item):
        item_id = item.data(QtCore.Qt.UserRole)
        win = self.ts_windows.get(item_id)
        if not win: return
        
        new_label, ok = QtWidgets.QInputDialog.getText(
            self, "Rename Time Series", "New Label:", 
            QtWidgets.QLineEdit.Normal, win.label)
            
        if ok and new_label:
            win.label = new_label
            win.setWindowTitle(f"Time Series {new_label}: {win.current_var}")
            self.update_ts_list_item(item_id)
            self.save_state_to_project()

    def edit_ts_point(self, item_id):
        point = self.ts_points.get(item_id)
        if not point: return
        
        dlg = PointEditorDialog(point, self)
        if dlg.exec_() == QtWidgets.QDialog.Accepted:
            new_point = dlg.get_point()
            if new_point:
                self.active_ts_id = item_id
                self.on_point_moved(new_point)

    def update_ui_state(self):
        """Enable/Disable buttons based on current state."""
        has_selection_cs = len(self.cs_list.selectedItems()) > 0
        self.btn_remove_cs.setEnabled(has_selection_cs)
        
        has_selection_ts = len(self.ts_list.selectedItems()) > 0
        self.btn_remove_ts.setEnabled(has_selection_ts)

    def clear_all_cross_sections(self):
        """Removes all cross-sections and resets the plugin state."""
        self.is_restoring = True # Block auto-saves during mass removal
        try:
            # 1. Remove all CS windows and rubber bands
            ids = list(self.plot_windows.keys())
            for item_id in ids:
                # Optimized removal logic similar to remove_cross_section_by_id but without individual saves
                if item_id in self.plot_windows:
                    win = self.plot_windows.pop(item_id)
                    self.iface.removeDockWidget(win)
                    win.close()
                    win.deleteLater()
                
                if item_id in self.cs_rubber_bands:
                    rb = self.cs_rubber_bands.pop(item_id)
                    rb.reset()
                    self.iface.mapCanvas().scene().removeItem(rb)
            
            # 2. Clear dictionaries and lists
            self.cs_geometries.clear()
            self.cs_list.clear()
            
            # 3. Remove all Time Series
            ids = list(self.ts_windows.keys())
            for item_id in ids:
                if item_id in self.ts_windows:
                    win = self.ts_windows.pop(item_id)
                    self.iface.removeDockWidget(win)
                    win.close()
                    win.deleteLater()
                if item_id in self.ts_markers:
                    m = self.ts_markers.pop(item_id)
                    self.iface.mapCanvas().scene().removeItem(m)
            
            self.ts_list.clear()
            self.ts_points.clear()
            self.active_ts_id = None

            self.var_list.clear()
            self.info_text.clear()
            self.file_edit.clear()
            
            # 3. Close handler
            if self.handler:
                self.handler.close()
                self.handler = None
            
            # 4. Reset tool
            if hasattr(self, 'xs_tool') and self.xs_tool:
                self.xs_tool.set_points([])
            
            self.active_cs_id = None
            
        finally:
            self.is_restoring = False

    def remove_cross_section(self):
        selected_items = self.cs_list.selectedItems()
        if not selected_items:
            return
            
        item = selected_items[0]
        item_id = item.data(QtCore.Qt.UserRole)
        
        self.remove_cross_section_by_id(item_id)

    def on_cs_cursor_moved(self, item_id, dist):
        """Show synchronization marker on map when hovering on plot."""
        if not item_id or item_id not in self.cs_geometries:
            return
            
        points = self.cs_geometries[item_id]
        if len(points) < 2: return
        
        # 1. Coordinate Transform: Canvas -> Model
        try:
            from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsPointXY
            from qgis.gui import QgsVertexMarker
            from qgis.PyQt.QtGui import QColor
            
            canvas_crs = self.iface.mapCanvas().mapSettings().destinationCrs()
            model_crs_def = self.handler.get_crs()
            model_crs = QgsCoordinateReferenceSystem(model_crs_def if model_crs_def else "EPSG:28992")
            
            xform_to_model = None
            xform_to_canvas = None
            if model_crs.isValid() and canvas_crs != model_crs:
                xform_to_model = QgsCoordinateTransform(canvas_crs, model_crs, QgsProject.instance())
                xform_to_canvas = QgsCoordinateTransform(model_crs, canvas_crs, QgsProject.instance())
            
            # 2. Points in Model CRS
            m_points = [xform_to_model.transform(p) for p in points] if xform_to_model else points
            
            # 3. Find Segment
            curr_d = 0.0
            found_p = None
            for i in range(len(m_points)-1):
                p1, p2 = m_points[i], m_points[i+1]
                seg_len = ((p2.x()-p1.x())**2 + (p2.y()-p1.y())**2)**0.5
                if curr_d <= dist <= curr_d + seg_len + 1e-3:
                    # Interpolate
                    if seg_len > 0:
                        ratio = (dist - curr_d) / seg_len
                        found_p = QgsPointXY(p1.x() + (p2.x()-p1.x())*ratio, 
                                            p1.y() + (p2.y()-p1.y())*ratio)
                    else:
                        found_p = p1
                    break
                curr_d += seg_len
            
            if found_p:
                # 4. Transform back to Canvas
                canvas_p = xform_to_canvas.transform(found_p) if xform_to_canvas else found_p
                
                # 5. Show/Move Marker
                if not self.sync_marker:
                    self.sync_marker = QgsVertexMarker(self.iface.mapCanvas())
                    self.sync_marker.setIconType(QgsVertexMarker.ICON_CIRCLE)
                    self.sync_marker.setPenWidth(3)
                    self.sync_marker.setIconSize(12)
                    self.sync_marker.setColor(QColor('yellow'))
                
                self.sync_marker.setCenter(canvas_p)
                self.sync_marker.show()
                
        except Exception as e:
            QgsMessageLog.logMessage(f"NLMOD: Sync marker error: {e}", "NlmodInspector", Qgis.Warning)

    def on_cs_cursor_left(self):
        if self.sync_marker:
            self.sync_marker.hide()
            
    def on_time_slider_changed(self, value):
        if self.time_values and 0 <= value < len(self.time_values):
            self.time_label.setText(self.time_values[value])
            # Note: We don't automatically update map layers here, 
            # as adding a layer is an explicit "Add to Map" action.
            # But the state is stored for the next "Add to Map" or for cross-sections.
            self.save_state_to_project()
            
            if self.auto_update_time:
                self.add_layer()

    def on_layer_combo_changed(self, index):
        if self.auto_update_layer and not self.is_restoring:
            self.add_layer()
            self.save_state_to_project()

    def show_settings(self):
        dlg = MainSettingsDialog(self, 
                                 auto_var=self.auto_update_var,
                                 auto_layer=self.auto_update_layer,
                                 auto_time=self.auto_update_time)
        if dlg.exec_():
            self.auto_update_var = dlg.chk_var.isChecked()
            self.auto_update_layer = dlg.chk_layer.isChecked()
            self.auto_update_time = dlg.chk_time.isChecked()
            self.auto_update_color = dlg.chk_color.isChecked()
            self.save_state_to_project()

    def get_next_cs_label(self):
        """Finds the next label based on Max(existing_labels) + 1."""
        existing_labels = []
        for win in self.plot_windows.values():
            existing_labels.append(win.cs_label)
        
        import string
        alphabet = list(string.ascii_uppercase)
        
        for char in alphabet:
            if char not in existing_labels:
                return char
        
        # Fallback if A-Z are used
        return f"Z{len(existing_labels)}"

    def save_state_to_project(self):
        """Saves filepath and cross-sections to the QGIS project."""
        if self.is_restoring:
            return
            
        import json
        from qgis.core import QgsProject
        filepath = self.file_edit.text()
        QgsProject.instance().writeEntry("NlmodInspector", "filepath", filepath)
        
        is_open = "true" if self.isVisible() else "false"
        QgsProject.instance().writeEntry("NlmodInspector", "is_open", is_open)
        
        # Save current selections
        if self.time_slider.isEnabled():
            QgsProject.instance().writeEntry("NlmodInspector", "global_time_idx", str(self.time_slider.value()))

        QgsProject.instance().writeEntry("NlmodInspector", "auto_update_var", "true" if self.auto_update_var else "false")
        QgsProject.instance().writeEntry("NlmodInspector", "auto_update_layer", "true" if self.auto_update_layer else "false")
        QgsProject.instance().writeEntry("NlmodInspector", "auto_update_time", "true" if self.auto_update_time else "false")
        QgsProject.instance().writeEntry("NlmodInspector", "auto_update_color", "true" if self.auto_update_color else "false")
        
        cs_list = []
        for item_id, points in self.cs_geometries.items():
            win = self.plot_windows.get(item_id)
            if win:
                # Get current view ranges from the plot directly
                view_range = win.plot_widget.getViewBox().viewRange() # [[xmin, xmax], [ymin, ymax]]
                
                v_min = float(win.v_min) if win.v_min is not None else None
                v_max = float(win.v_max) if win.v_max is not None else None
                
                cs_list.append({
                    'id': item_id,
                    'label': win.cs_label,
                    'variable': win.current_var,
                    'head_variable': win.current_head_var,
                    'time_idx': win.current_time_idx,
                    'points': [(float(p.x()), float(p.y())) for p in points],
                    'z_range': (float(view_range[1][0]), float(view_range[1][1])),
                    'x_range': (float(view_range[0][0]), float(view_range[0][1])),
                    'v_range': (v_min, v_max),
                    'visible': win.isVisible(),
                    'show_layers': win.show_layer_boundaries,
                    'show_cells': win.show_cell_boundaries,
                    'show_layer_names': win.show_layer_names,
                    'use_log': win.use_log,
                    'cmap': win.cmap_name,
                    'invert_cmap': win.invert_cmap
                })
        
        QgsProject.instance().writeEntry("NlmodInspector", "cross_sections", json.dumps(cs_list))
        
        # Save Time Series
        ts_data = []
        for item_id, win in self.ts_windows.items():
            pt = self.ts_points.get(item_id)
            if not pt: continue
            ts_data.append({
                'id': item_id,
                'label': win.label,
                'variable': win.current_var,
                'point': (float(pt.x()), float(pt.y())),
                'layer_indices': win.layer_indices,
                'visible': win.isVisible()
            })
        QgsProject.instance().writeEntry("NlmodInspector", "time_series", json.dumps(ts_data))

    def restore_state_from_project(self):
        """Restores plugin state from project entries."""
        self.is_restoring = True
        try:
            import json
            import os
            from qgis.core import QgsProject, QgsPointXY, Qgis, QgsMessageLog
            
            filepath, _ = QgsProject.instance().readEntry("NlmodInspector", "filepath", "")
            QgsMessageLog.logMessage(f"NLMOD: Restoring filepath: {filepath}", "NlmodInspector", Qgis.Info)
            
            if filepath and os.path.exists(filepath):
                self.file_edit.setText(filepath)
                self.open_netcdf(filepath)
                
                # Restore time selection
                time_str, ok = QgsProject.instance().readEntry("NlmodInspector", "global_time_idx", "0")
                if ok and self.time_slider.isEnabled():
                    try:
                        time_idx = int(time_str)
                        if time_idx <= self.time_slider.maximum():
                            self.time_slider.setValue(time_idx)
                    except:
                        pass
                
                # Restore auto-update settings
                v, _ = QgsProject.instance().readEntry("NlmodInspector", "auto_update_var", "false")
                self.auto_update_var = (v == "true")
                v, _ = QgsProject.instance().readEntry("NlmodInspector", "auto_update_layer", "false")
                self.auto_update_layer = (v == "true")
                v, _ = QgsProject.instance().readEntry("NlmodInspector", "auto_update_time", "false")
                self.auto_update_time = (v == "true")
                v, _ = QgsProject.instance().readEntry("NlmodInspector", "auto_update_color", "true")
                self.auto_update_color = (v == "true")
                
                cs_json, _ = QgsProject.instance().readEntry("NlmodInspector", "cross_sections", "[]")
                QgsMessageLog.logMessage(f"NLMOD: Restoring cross-sections: {cs_json}", "NlmodInspector", Qgis.Info)
                
                try:
                    cs_list = json.loads(cs_json)
                    for cs in cs_list:
                        points = [QgsPointXY(p[0], p[1]) for p in cs['points']]
                        win = self.add_cross_section_plot(
                            points, 
                            cs['variable'], 
                            cs_label=cs['label'], 
                            item_id=cs['id'],
                            z_range=cs.get('z_range'),
                            x_range=cs.get('x_range'),
                            v_range=cs.get('v_range'),
                            visible=cs.get('visible', True),
                            show_layers=cs.get('show_layers', True),
                            show_cells=cs.get('show_cells', False),
                            show_layer_names=cs.get('show_layer_names', True),
                            use_log=cs.get('use_log', False),
                            cmap_name=cs.get('cmap', 'Turbo'),
                            invert_cmap=cs.get('invert_cmap', False),
                            time_idx=cs.get('time_idx', 0)
                        )
                        # Set head variable if it was saved
                        if win and cs.get('head_variable'):
                            win.head_combo.setCurrentText(cs['head_variable'])
                except Exception as e:
                    QgsMessageLog.logMessage(f"NLMOD: Failed to restore cross-sections: {e}", "NlmodInspector", Qgis.Warning)
                
                # Restore managed layers
                self.restore_managed_layers()
                
                # Restore Time Series
                ts_json, _ = QgsProject.instance().readEntry("NlmodInspector", "time_series", "[]")
                try:
                    ts_list = json.loads(ts_json)
                    for ts in ts_list:
                        point = QgsPointXY(ts['point'][0], ts['point'][1])
                        win = self.add_time_series_plot(
                            point, 
                            ts['variable'], 
                            ts_label=ts['label'], 
                            item_id=ts['id'],
                            layer_indices=ts.get('layer_indices')
                        )
                        if win and not ts.get('visible', True):
                            win.hide()
                except Exception as e:
                    QgsMessageLog.logMessage(f"NLMOD: Failed to restore time series: {e}", "NlmodInspector", Qgis.Warning)

            else:
                if filepath:
                    QgsMessageLog.logMessage(f"NLMOD: Saved filepath does not exist: {filepath}", "NlmodInspector", Qgis.Warning)
        finally:
            self.is_restoring = False
            # Now safe to connect visibility signal
            try:
                self.visibilityChanged.disconnect(self.save_state_to_project)
            except:
                pass
            self.visibilityChanged.connect(self.save_state_to_project)
            # DO NOT call save_state_to_project() here

    def restore_managed_layers(self):
        """Finds all layers in the project that were created by this plugin and refreshes them."""
        if not self.handler:
            return
            
        from qgis.core import QgsProject, Qgis, QgsMessageLog
        filepath = self.handler.filepath
        layers_to_refresh = []
        
        # We use a list to avoid issues with modifying the project during iteration
        for layer in list(QgsProject.instance().mapLayers().values()):
            if layer.customProperty("nlmod_inspector_managed"):
                if layer.customProperty("nlmod_inspector_source") == filepath:
                    layers_to_refresh.append(layer)
        
        if layers_to_refresh:
            QgsMessageLog.logMessage(f"NLMOD: Restoring {len(layers_to_refresh)} managed layers", "NlmodInspector", Qgis.Info)
            
        for layer in layers_to_refresh:
            var_name = layer.customProperty("nlmod_inspector_var")
            if not var_name: continue
            
            # Read properties
            try:
                layer_idx = int(layer.customProperty("nlmod_inspector_layer_idx") or 0)
                time_idx = int(layer.customProperty("nlmod_inspector_time_idx") or 0)
            except (ValueError, TypeError):
                layer_idx = 0
                time_idx = 0
                
            params = {
                'var_name': var_name,
                'layer_idx': layer_idx,
                'time_idx': time_idx
            }
            
            # Refresh this layer
            # We use force_new=False because we want to update the existing layer object if possible
            self.add_layer(force_new=False, layer_to_update=layer, params=params)

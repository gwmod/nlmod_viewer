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

class MainSettingsDialog(QtWidgets.QDialog):
    def __init__(self, parent=None, auto_var=False, auto_layer=False, auto_time=False):
        super().__init__(parent)
        self.setWindowTitle("Global Settings")
        layout = QtWidgets.QVBoxLayout(self)
        
        group = QtWidgets.QGroupBox("Update map")
        group_layout = QtWidgets.QVBoxLayout()
        
        self.chk_var = QtWidgets.QCheckBox("Update map when variable changes")
        self.chk_var.setChecked(auto_var)
        group_layout.addWidget(self.chk_var)
        
        self.chk_layer = QtWidgets.QCheckBox("Update map when layer changes")
        self.chk_layer.setChecked(auto_layer)
        group_layout.addWidget(self.chk_layer)
        
        self.chk_time = QtWidgets.QCheckBox("Update map when time changes")
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
        time_sel_layout = QtWidgets.QHBoxLayout()
        time_sel_layout.addWidget(QtWidgets.QLabel("Select Time:"))
        
        self.time_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.time_slider.setEnabled(False)
        self.time_slider.setTickPosition(QtWidgets.QSlider.TicksBelow)
        self.time_slider.setTickInterval(1)
        self.time_slider.valueChanged.connect(self.on_time_slider_changed)
        time_sel_layout.addWidget(self.time_slider)
        
        self.time_label = QtWidgets.QLabel("")
        self.time_label.setMinimumWidth(100)
        time_sel_layout.addWidget(self.time_label)
        
        layer_group_layout.addLayout(time_sel_layout)
        
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
        
        # Update existing cross-sections with new data/variables
        vars_3d = self.get_vars_3d()
        all_vars = self.get_all_vars()
        times = dim_meta["times"]
        for win in self.plot_windows.values():
            win.refresh(vars_3d, head_vars=all_vars, time_values=times)
            
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

    def add_layer(self, force_new=False):
        if not self.handler:
            return
            
        selected_items = self.var_list.selectedItems()
        if not selected_items:
            if not getattr(self, 'auto_update_var', False):
                QtWidgets.QMessageBox.information(self, "Info", "Please select a variable first.")
            return
            
        var_name = selected_items[0].data(QtCore.Qt.UserRole)
        grid_type = self.handler.grid_type
        filepath = self.handler.filepath
        base_name = os.path.basename(filepath)
        
        # Vertex grids (quadtree, unstructured) always load as Mesh (MDAL)
        # Structured grids always load as Raster (GDAL)
        use_mesh = (grid_type == "vertex")
        
        # Determine Layer name for legend
        layer_idx = self.layer_combo.currentIndex() if self.layer_combo.isEnabled() else 0
        layer_val = self.layer_combo.currentText() if self.layer_combo.isEnabled() else "1"
        time_idx = self.time_slider.value() if self.time_slider.isEnabled() else 0
        time_val = self.time_values[time_idx] if (self.time_slider.isEnabled() and self.time_values) else ""
        
        display_name = f"{var_name}"
        if self.layer_combo.isEnabled(): display_name += f" ({layer_val})"
        if time_val: display_name += f" [{time_val}]"
        display_name += f" @ {base_name}"

        # Check for existing managed layer (only if not forcing a new one)
        existing_layer = None
        if not force_new and self.active_map_layer:
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

        if use_mesh:
            # Use a unique timestamped filename to avoid "Permission denied" locks from MDAL
            import time
            timestamp = int(time.time() * 1000)
            temp_path = os.path.join(tempfile.gettempdir(), f"nlmod_mesh_{id(self)}_{timestamp}.nc")
            
            QgsMessageLog.logMessage(f"NLMOD: Exporting mesh to {temp_path}", "NlmodInspector", Qgis.Info)
            success, msg = self.handler.export_to_mesh(var_name, layer_idx, time_idx, temp_path)
            
            if not success:
                QtWidgets.QMessageBox.warning(self, "Export Error", f"Failed to export mesh: {msg}")
                return

            # Calculate actual min/max for the current selection
            stats = self.handler.get_variable_stats(var_name, layer_idx, time_idx)
            v_min, v_max = stats['min'], stats['max']
            
            if existing_layer:
                # Store old path for cleanup attempt
                old_path = existing_layer.source()
                
                # Update source to the new unique file
                existing_layer.setDataSource(temp_path, display_name, "mdal")
                existing_layer.reload()
                existing_layer.setName(display_name)
                # Only update style if auto-update-color is enabled
                if self.auto_update_color:
                    self.style_mesh_layer(existing_layer, min_val=v_min, max_val=v_max)
                existing_layer.triggerRepaint()
                
                # Try to clean up the old file (might still be locked, so we ignore errors)
                if old_path and os.path.exists(old_path) and "nlmod_mesh_" in old_path:
                    try:
                        os.remove(old_path)
                    except:
                        pass
            else:
                layer = QgsMeshLayer(temp_path, display_name, "mdal")
                if layer.isValid():
                    if not layer.crs().isValid():
                        layer.setCrs(QgsCoordinateReferenceSystem("EPSG:28992"))
                    self.style_mesh_layer(layer, min_val=v_min, max_val=v_max)
                    QgsProject.instance().addMapLayer(layer)
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
            
            # Determine Band Index FIRST (1-based)
            band_idx = 1
            
            layer_idx = self.layer_combo.currentIndex() if self.layer_combo.isEnabled() else 0
            time_idx = self.time_slider.value() if self.time_slider.isEnabled() else 0
            
            # Use global count if the variable has layers, else 1
            n_layers = self.layer_combo.count() if self.layer_combo.isEnabled() else 1
            if n_layers == 0: n_layers = 1
            
            # GDAL flattens NetCDF dimensions: band_idx = time_idx * n_layers + layer_idx + 1
            band_idx = (time_idx * n_layers) + layer_idx + 1
            
            safe_path = filepath.replace('\\', '/')
            uri = f'NETCDF:"{safe_path}":{var_name}'
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

                    # Save to unique vsimem path to bypass GDAL/QGIS caching
                    import time
                    ts = int(time.time() * 1000)
                    vrt_mem_path = f"/vsimem/nlmod_raster_{id(self)}_{ts}.vrt"
                    gdal.FileFromMemBuffer(vrt_mem_path, vrt_xml)
                    uri = vrt_mem_path
                    QgsMessageLog.logMessage(f"NLMOD: Created VRT at {uri}", "NlmodInspector", Qgis.Info)
            except Exception as e:
                QgsMessageLog.logMessage(f"NLMOD: VRT creation failed: {e}", "NlmodInspector", Qgis.Warning)

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
                existing_layer.triggerRepaint()
                
                # Cleanup old vsimem VRT
                if "/vsimem/nlmod_raster_" in old_uri:
                    try:
                        from osgeo import gdal
                        gdal.Unlink(old_uri)
                    except:
                        pass
                
                self.active_var_name = var_name
            else:
                layer = QgsRasterLayer(uri, display_name)
                if layer.isValid():
                    if not layer.crs().isValid():
                        layer.setCrs(QgsCoordinateReferenceSystem("EPSG:28992"))
                    self.apply_raster_style(layer, band_idx=1, min_val=v_min, max_val=v_max)
                    QgsProject.instance().addMapLayer(layer)
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

    def style_mesh_layer(self, layer, min_val=None, max_val=None):
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
            if not ramp: return

            # 2. Get active dataset group index
            # Explicit cast to int is required for some PyQGIS versions to prevent type errors
            idx = int(layer.rendererSettings().activeScalarDatasetGroup())
            if idx < 0: 
                # If nothing active, try finding one or default to 0
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
            self.highlight_cross_section(selected[0])

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
        self.update_ui_state()

    def update_ui_state(self):
        """Enable/Disable buttons based on current state."""
        has_selection = len(self.cs_list.selectedItems()) > 0
        self.btn_remove_cs.setEnabled(has_selection)

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

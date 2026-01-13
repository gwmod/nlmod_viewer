from qgis.PyQt import QtWidgets, QtCore
from qgis.core import (
    QgsProject, QgsMeshLayer, QgsRasterLayer, QgsCoordinateReferenceSystem,
    QgsSingleBandPseudoColorRenderer, QgsColorRampShader, QgsStyle, QgsRasterShader,
    QgsRasterBandStats
)
from .netcdf_handler import NetcdfHandler
import os

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
        
        # File Selection
        file_group = QtWidgets.QGroupBox("Select Data")
        file_layout = QtWidgets.QVBoxLayout()
        h_layout = QtWidgets.QHBoxLayout()
        self.file_edit = QtWidgets.QLineEdit()
        self.browse_btn = QtWidgets.QPushButton("Browse...")
        self.browse_btn.clicked.connect(self.select_file)
        h_layout.addWidget(self.file_edit)
        h_layout.addWidget(self.browse_btn)
        file_layout.addLayout(h_layout)
        file_group.setLayout(file_layout)
        layout.addWidget(file_group)
        

        # Info Area
        self.info_text = QtWidgets.QTextBrowser()
        self.info_text.setMaximumHeight(120)
        layout.addWidget(QtWidgets.QLabel("Metadata:"))
        layout.addWidget(self.info_text)
        
        # Variable List
        self.var_list = QtWidgets.QListWidget()
        self.var_list.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.var_list.itemSelectionChanged.connect(self.update_layer_selection)
        layout.addWidget(QtWidgets.QLabel("Variables (Input/Output):"))
        layout.addWidget(self.var_list)

        # Layer Selection
        layer_layout = QtWidgets.QHBoxLayout()
        layer_layout.addWidget(QtWidgets.QLabel("Select Layer:"))
        self.layer_combo = QtWidgets.QComboBox()
        self.layer_combo.setEnabled(False)
        layer_layout.addWidget(self.layer_combo)
        layout.addLayout(layer_layout)
        
        # Buttons
        btn_layout = QtWidgets.QHBoxLayout()
        self.use_mesh_chk = QtWidgets.QCheckBox("Load as Mesh Layer")
        self.use_mesh_chk.setToolTip("Force usage of MDAL (Mesh) provider. Better for 3D/Unstructured data.")
        btn_layout.addWidget(self.use_mesh_chk)
        self.load_btn = QtWidgets.QPushButton("Add to Map")
        self.load_btn.clicked.connect(self.add_layer)
        btn_layout.addWidget(self.load_btn)
        
        layout.addLayout(btn_layout)
        
        # Cross Section Group (at bottom)
        cs_group = QtWidgets.QGroupBox("Cross Section")
        cs_layout = QtWidgets.QVBoxLayout()
        cs_group.setLayout(cs_layout)
        
        self.btn_cross_section = QtWidgets.QPushButton("Plot Cross-Section")
        self.btn_cross_section.clicked.connect(self.activate_cross_section_tool)
        cs_layout.addWidget(self.btn_cross_section)
        
        # Cross Section List Manager
        self.cs_list = QtWidgets.QListWidget()
        self.cs_list.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.cs_list.itemClicked.connect(self.raise_cross_section_window)
        cs_layout.addWidget(self.cs_list)
        
        self.btn_remove_cs = QtWidgets.QPushButton("Remove Selected Plot")
        self.btn_remove_cs.clicked.connect(self.remove_cross_section)
        cs_layout.addWidget(self.btn_remove_cs)
        
        layout.addWidget(cs_group)
        
        # Stretch to fill bottom
        layout.addStretch()
        
        # Logic State
        self.handler = None
        self.plot_windows = {}  # Dictionary to track cross-section plot windows
        self.cs_geometries = {}  # Dictionary to store cross-section line geometries
        self.cs_rubber_bands = {}  # Dictionary to store QgsRubberBand for each CS

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
             return
        
        self.info_text.setText(self.handler.get_info_text())
        
        # Auto-check mesh if vertex
        if self.handler.grid_type == "vertex":
            self.use_mesh_chk.setChecked(True)
        else:
            self.use_mesh_chk.setChecked(False)
            
        self.populate_vars()

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
            item.setData(QtCore.Qt.UserRole + 1, v['layer_size'])
            item.setData(QtCore.Qt.UserRole + 2, v['layer_values'])
            self.var_list.addItem(item)
    
    def update_layer_selection(self):
        self.layer_combo.clear()
        self.layer_combo.setEnabled(False)
        
        selected_items = self.var_list.selectedItems()
        if not selected_items:
            return
            
        item = selected_items[0]
        layer_size = item.data(QtCore.Qt.UserRole + 1)
        layer_values = item.data(QtCore.Qt.UserRole + 2)
        
        if layer_size and layer_size > 0:
            self.layer_combo.setEnabled(True)
            if layer_values:
                self.layer_combo.addItems([str(x) for x in layer_values])
            else:
                self.layer_combo.addItems([str(i+1) for i in range(layer_size)])

    def add_layer(self):
        if not self.handler:
            return
            
        selected_items = self.var_list.selectedItems()
        if not selected_items:
            QtWidgets.QMessageBox.information(self, "Info", "Please select a variable first.")
            return
            
        var_name = selected_items[0].data(QtCore.Qt.UserRole)
        grid_type = self.handler.grid_type
        filepath = self.handler.filepath
        base_name = os.path.basename(filepath)
        
        # Check explicit force mesh or vertex type
        use_mesh = self.use_mesh_chk.isChecked() or (grid_type == "vertex")
        
        if use_mesh:
            # For unstructured grids or forced mesh, use MDAL
            layer_name = f"{base_name} (Mesh)"
            layer = QgsMeshLayer(filepath, layer_name, "mdal")
            
            if layer.isValid():
                if not layer.crs().isValid():
                    layer.setCrs(QgsCoordinateReferenceSystem("EPSG:28992"))
                QgsProject.instance().addMapLayer(layer)
                self.activate_mesh_dataset(layer, var_name)
            else:
                QtWidgets.QMessageBox.warning(self, "Error", "Failed to load as Mesh Layer.")

        elif grid_type == "structured":
            from qgis.core import QgsMessageLog, Qgis
            QgsMessageLog.logMessage(f"NLMOD: Loading structured layer for {var_name}", "NlmodInspector", Qgis.Info)
            
            # Try loading as Raster (NetCDF)
            safe_path = filepath.replace('\\', '/')
            uri = f'NETCDF:"{safe_path}":{var_name}'
            layer_name = f"{var_name} @ {base_name}"
            
            # Determine Band Index FIRST (1-based)
            band_idx = 1
            # Apply layer selection if applicable
            if self.layer_combo.isEnabled():
                # Map selection index to band index (assuming order matches)
                idx = self.layer_combo.currentIndex()
                if idx >= 0:
                    band_idx = idx + 1
                    val_str = self.layer_combo.currentText()
                    layer_name = f"{var_name} (Layer {val_str}) @ {base_name}"
            
            # --- VRT Workaround for Coordinates ---
            # QGIS/GDAL often defaults to 0..N if grid mapping isn't standard.
            # We explicitly calculate bounds and wrap in a VRT.
            try:
                extent = self.handler.get_extent(var_name)
                if extent:
                    from qgis.core import QgsMessageLog, Qgis
                    xmin, xmax, ymin, ymax = extent
                    QgsMessageLog.logMessage(f"NLMOD: Calculated extent: {xmin},{xmax},{ymin},{ymax}", "NlmodInspector", Qgis.Info)
                    
                    # Prepare VRT metadata
                    # Dimensions
                    # We need actual pixel dimensions
                    var_info = self.handler.ds.variables[var_name]
                    # Shape is typically (layer, y, x) or (y,x) or (time, layer, y, x)
                    # We need the last two dimensions
                    if var_info.ndim >= 2:
                        y_size = var_info.shape[-2]
                        x_size = var_info.shape[-1]
                        
                        # Calculate GeoTransform
                        # GT = [top_left_x, w_pixel_val, rotation_x, top_left_y, rotation_y, h_pixel_val]
                        # pixel width = (xmax - xmin) / x_size
                        # pixel height = (ymin - ymax) / y_size  (negative usually)
                        
                        pixel_width = (xmax - xmin) / x_size
                        pixel_height = (ymax - ymin) / y_size # Note: ymin is bottom, ymax is top. (ymax - ymin) -> positive height? 
                        # Usually GT[5] is negative for north-up images.
                        # If ymax is top: GT[3] = ymax. GT[5] = (ymin - ymax) / y_size = NEGATIVE
                        
                        gt_5 = (ymin - ymax) / y_size
                        
                        geotransform = f"{xmin}, {pixel_width}, 0, {ymax}, 0, {gt_5}"
                        
                        # CRS
                        crs_wkt = self.handler.get_crs()
                        if not crs_wkt:
                             crs_wkt = "EPSG:28992" # Fallback
                             
                        # Build VRT XML manually - USE SELECTED BAND
                        vrt_xml = f"""<VRTDataset rasterXSize="{x_size}" rasterYSize="{y_size}">
  <SRS>{crs_wkt}</SRS>
  <GeoTransform>{geotransform}</GeoTransform>
  <VRTRasterBand dataType="Float32" band="1">
    <SimpleSource>
      <SourceFilename relativeToVRT="0">NETCDF:"{safe_path}":{var_name}</SourceFilename>
      <SourceBand>{band_idx}</SourceBand>
      <SrcRect xOff="0" yOff="0" xSize="{x_size}" ySize="{y_size}" />
      <DstRect xOff="0" yOff="0" xSize="{x_size}" ySize="{y_size}" />
    </SimpleSource>
  </VRTRasterBand>
</VRTDataset>"""

                        # Save to vsimem (or temporary file if vsimem assumes path)
                        # QgsRasterLayer takes a path. 
                        # We can pass the XML content directly? No, usually needs a path.
                        # But we can write to /vsimem/
                        from osgeo import gdal
                        vrt_mem_path = f"/vsimem/{var_name}_{band_idx}_{id(self)}.vrt"
                        gdal.FileFromMemBuffer(vrt_mem_path, vrt_xml)
                        
                        uri = vrt_mem_path
                        QgsMessageLog.logMessage(f"NLMOD: Created VRT at {uri} for band {band_idx}", "NlmodInspector", Qgis.Info)
                else:
                     QgsMessageLog.logMessage(f"NLMOD: Extent not found for {var_name}", "NlmodInspector", Qgis.Warning)

            except Exception as e:
                import traceback
                tb = traceback.format_exc()
                from qgis.core import QgsMessageLog, Qgis
                QgsMessageLog.logMessage(f"NLMOD: VRT creation failed: {e}\n{tb}", "NlmodInspector", Qgis.Warning)
            # ------------------------------------

            layer = QgsRasterLayer(uri, layer_name)
            if layer.isValid():
                if not layer.crs().isValid():
                    layer.setCrs(QgsCoordinateReferenceSystem("EPSG:28992"))
                
                # Band index is always 1 for VRT (VRT exposes selected source band as band 1)
                band_idx = 1

                # Apply Pseudocolor Renderer (Turbo)
                try:
                    # Robust Color Ramp Getter
                    def get_ramp(name, default_colors):
                        style = QgsStyle.defaultStyle()
                        ramp = style.colorRamp(name)
                        if not ramp:
                            # Create a simple gradient if not found
                            from qgis.core import QgsGradientColorRamp
                            from qgis.PyQt.QtGui import QColor
                            return QgsGradientColorRamp(QColor(default_colors[0]), QColor(default_colors[1]))
                        return ramp

                    # Try Turbo -> Viridis -> Spectral -> Blue-Red
                    ramp = get_ramp("Turbo", ["blue", "red"])
                    if not ramp:
                         # Very safe fallback
                         style = QgsStyle.defaultStyle()
                         ramp = style.colorRamp("Spectral")

                    if ramp:
                        # Statistics - use approximate for speed/safety
                        stats = layer.dataProvider().bandStatistics(band_idx, QgsRasterBandStats.Min | QgsRasterBandStats.Max, layer.extent(), 0)
                        min_val = stats.minimumValue
                        max_val = stats.maximumValue
                        
                        # Handle flat data (min == max)
                        if min_val >= max_val:
                            min_val = min_val - 1.0
                            max_val = max_val + 1.0

                        # Create shader with automatic classification
                        fcn = QgsColorRampShader(min_val, max_val)
                        fcn.setColorRampType(QgsColorRampShader.Interpolated)
                        fcn.setSourceColorRamp(ramp)
                        fcn.classifyColorRamp(classes=10, band=band_idx, input=layer.dataProvider())
                        
                        shader = QgsRasterShader()
                        shader.setRasterShaderFunction(fcn)
                        
                        renderer = QgsSingleBandPseudoColorRenderer(layer.dataProvider(), band_idx, shader)
                        layer.setRenderer(renderer)
                        layer.triggerRepaint()
                    else:
                        print("Could not find any color ramp.")
                        QtWidgets.QMessageBox.warning(self, "Style Error", "Could not find 'Turbo' or fallback color ramp.")
                except Exception as e:
                    import traceback
                    tb = traceback.format_exc()
                    print(f"Error setting style: {e}")
                    QtWidgets.QMessageBox.critical(self, "Style Error", f"Failed to set pseudocolor renderer:\n{str(e)}\n\n{tb}")

                QgsProject.instance().addMapLayer(layer)
            else:
                # Fallback
                layer = QgsMeshLayer(filepath, f"{base_name} (Mesh)", "mdal")
                if layer.isValid():
                    if not layer.crs().isValid():
                        layer.setCrs(QgsCoordinateReferenceSystem("EPSG:28992"))
                    QgsProject.instance().addMapLayer(layer)
                    self.activate_mesh_dataset(layer, var_name)
                else:
                    QtWidgets.QMessageBox.warning(self, "Error", f"Failed to load variable '{var_name}'.")
        else:
             # Unknown grid, try Mesh
             layer = QgsMeshLayer(filepath, base_name, "mdal")
             if layer.isValid():
                 if not layer.crs().isValid():
                     layer.setCrs(QgsCoordinateReferenceSystem("EPSG:28992"))
                 QgsProject.instance().addMapLayer(layer)
             else:
                 QtWidgets.QMessageBox.warning(self, "Error", "Could not load file.")


    def activate_mesh_dataset(self, layer, var_name):
        # Helper to set the active dataset on the mesh layer if possible
        # This iterates through dataset groups to find a match by name
        count = layer.datasetGroupCount()
        for i in range(count):
            meta = layer.datasetGroupMetadata(i)
            if meta.name() == var_name:
                # Set active scalar/vector dataset
                # Note: this API changes slightly between QGIS versions, but generally:
                # layer.setStaticLayer(False) # Enable temporal if needed
                # For now just let the user see it's loaded.
                break

    def activate_cross_section_tool(self):
        # Check if a variable is selected and has layer dimension
        selected_items = self.var_list.selectedItems()
        if not selected_items:
            QtWidgets.QMessageBox.information(self, "Info", "Please select a variable first.")
            return
            
        var_name = selected_items[0].data(QtCore.Qt.UserRole)
        
        # Check if variable is 3D (has layer dimension)
        if self.handler and self.handler.ds:
            var = self.handler.ds.variables[var_name]
            has_layer_dim = False
            possible_layer_dims = {'layer', 'lev', 'level', 'z'}
            
            for dim in var.dimensions:
                if dim in possible_layer_dims:
                    has_layer_dim = True
                    break
            
            if not has_layer_dim:
                QtWidgets.QMessageBox.warning(
                    self, 
                    "Invalid Variable", 
                    f"Variable '{var_name}' does not have a layer dimension.\n\n"
                    "Cross-sections require 3D variables with layers (e.g., 'layer', 'lev', 'level')."
                )
                return
        
        try:
            from .cross_section_tool import CrossSectionMapTool
            
            canvas = self.iface.mapCanvas()
            self.xs_tool = CrossSectionMapTool(canvas)
            self.xs_tool.line_finished.connect(self.on_cross_section_finished)
            canvas.setMapTool(self.xs_tool)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Tool Error", f"Failed to start tool: {e}")

    def on_cross_section_finished(self, points):
        # 1. Get selected variable
        selected_items = self.var_list.selectedItems()
        if not selected_items:
            QtWidgets.QMessageBox.information(self, "Info", "Please select a variable first.")
            return
            
        var_name = selected_items[0].data(QtCore.Qt.UserRole)
        
        # 1.5 Check if variable is 3D (has layer dimension)
        if self.handler and self.handler.ds:
            var = self.handler.ds.variables[var_name]
            has_layer_dim = False
            possible_layer_dims = {'layer', 'lev', 'level', 'z'}
            
            for dim in var.dimensions:
                if dim in possible_layer_dims:
                    has_layer_dim = True
                    break
            
            if not has_layer_dim:
                QtWidgets.QMessageBox.warning(
                    self, 
                    "Invalid Variable", 
                    f"Variable '{var_name}' does not have a layer dimension.\n\n"
                    "Cross-sections require 3D variables with layers (e.g., 'layer', 'lev', 'level')."
                )
                return
        
        # 2. Transform Coordinates
        try:
            from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform
            
            canvas_crs = self.iface.mapCanvas().mapSettings().destinationCrs()
            
            # Get Model CRS
            model_crs_def = self.handler.get_crs()
            if model_crs_def:
                model_crs = QgsCoordinateReferenceSystem(model_crs_def)
            else:
                # Fallback to EPSG:28992 (nlmod default)
                model_crs = QgsCoordinateReferenceSystem("EPSG:28992")
                
            if model_crs.isValid() and canvas_crs != model_crs:
                xform = QgsCoordinateTransform(canvas_crs, model_crs, QgsProject.instance())
                # Transform all points
                transformed_points = [xform.transform(p) for p in points]
                points = transformed_points
                
        except Exception as e:
            print(f"CRS Transform Error: {e}")
            # Continue with original points if transform fails
        
        # 3. Extract Data
        try:
            data = self.handler.get_cross_section_data(var_name, points)
            if not data:
                return
            if "error" in data:
                QtWidgets.QMessageBox.warning(self, "Error", data["error"])
                return
                
            from .cross_section_plot import CrossSectionPlotWindow
            
            # Create Window
            win = CrossSectionPlotWindow(data, var_name)
            win.show()
            
            # Add to List Manager
            import time
            # Unique ID based on time or count
            item_id = str(start_time := time.time())
            
            # Simple name: VarName (Time)
            label = f"{var_name} [{len(self.plot_windows) + 1}]"
            
            item = QtWidgets.QListWidgetItem(label)
            item.setData(QtCore.Qt.UserRole, item_id)
            self.cs_list.addItem(item)
            
            # Select it
            self.cs_list.setCurrentItem(item)
            
            # Store
            self.plot_windows[item_id] = win
            self.cs_geometries[item_id] = points  # Store original points
            
            # Create RubberBand for map visualization
            from qgis.gui import QgsRubberBand
            from qgis.core import QgsWkbTypes
            from qgis.PyQt.QtGui import QColor
            
            rubber_band = QgsRubberBand(self.iface.mapCanvas(), QgsWkbTypes.LineGeometry)
            rubber_band.setColor(QColor(255, 0, 0, 180))  # Red with transparency
            rubber_band.setWidth(3)
            
            for point in points:
                rubber_band.addPoint(point)
            
            rubber_band.show()
            self.cs_rubber_bands[item_id] = rubber_band
            
            # Clean up when closed? We could connect a signal, 
            # but for now explicit removal or app exit is fine.
            # Ideally: win.closed.connect(lambda: self.cleanup(item_id))
            
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Plot Error", f"Failed to plot: {e}")

    def raise_cross_section_window(self, item):
        from qgis.PyQt.QtGui import QColor
        
        item_id = item.data(QtCore.Qt.UserRole)
        
        # Show window
        if item_id in self.plot_windows:
            win = self.plot_windows[item_id]
            win.show()
            win.raise_()
            win.activateWindow()
        
        # Highlight rubber band on map
        # Hide all other rubber bands and show only the selected one
        for rb_id, rb in self.cs_rubber_bands.items():
            if rb_id == item_id:
                rb.setWidth(4)  # Make selected thicker
                rb.setColor(QColor(255, 0, 0, 255))  # Fully opaque red
            else:
                rb.setWidth(2)  # Make others thinner
                rb.setColor(QColor(255, 0, 0, 100))  # More transparent

    def remove_cross_section(self):
        selected_items = self.cs_list.selectedItems()
        if not selected_items:
            return
            
        item = selected_items[0]
        item_id = item.data(QtCore.Qt.UserRole)
        
        # Close window
        if item_id in self.plot_windows:
            win = self.plot_windows[item_id]
            win.close()
            del self.plot_windows[item_id]
        
        # Remove rubber band from map
        if item_id in self.cs_rubber_bands:
            rb = self.cs_rubber_bands[item_id]
            rb.reset()
            self.iface.mapCanvas().scene().removeItem(rb)
            del self.cs_rubber_bands[item_id]
        
        # Remove geometry
        if item_id in self.cs_geometries:
            del self.cs_geometries[item_id]
            
        # Remove from list (takeItem returns item, we discard it)
        row = self.cs_list.row(item)
        self.cs_list.takeItem(row)

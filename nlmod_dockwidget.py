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
        self.load_btn = QtWidgets.QPushButton("Add to Map")
        self.load_btn.clicked.connect(self.add_layer)
        btn_layout.addWidget(self.load_btn)
        
        layout.addLayout(btn_layout)
        
        # Cross Section Group (at bottom)
        cs_group = QtWidgets.QGroupBox("Cross Section")
        cs_layout = QtWidgets.QVBoxLayout()
        cs_group.setLayout(cs_layout)
        
        self.btn_cross_section = QtWidgets.QPushButton("Add Cross-Section")
        self.btn_cross_section.clicked.connect(self.activate_cross_section_tool)
        cs_layout.addWidget(self.btn_cross_section)
        
        # Cross Section List Manager
        self.cs_list = QtWidgets.QListWidget()
        self.cs_list.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.cs_list.itemClicked.connect(self.highlight_cross_section)
        self.cs_list.itemDoubleClicked.connect(self.raise_cross_section_window)
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
        self.active_cs_id = None  # Track which CS is currently being edited/drawn
        self.prev_map_tool = None # Store map tool before activation

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
        
        # Vertex grids (quadtree, unstructured) always load as Mesh (MDAL)
        # Structured grids always load as Raster (GDAL)
        use_mesh = (grid_type == "vertex")
        
        if use_mesh:
            
            # For vertex grids, export to a dedicated clean UGRID file
            # This solves MDAL's identification issues with complex multi-var files
            layer_idx = 0
            if self.layer_combo.isEnabled():
                layer_idx = self.layer_combo.currentIndex()
            
            # Create a descriptive temp filename
            temp_dir = tempfile.gettempdir()
            clean_var = "".join(x for x in var_name if x.isalnum())
            temp_path = os.path.join(temp_dir, f"nlmod_{clean_var}_L{layer_idx+1}.nc")
            
            QgsMessageLog.logMessage(f"NLMOD: Exporting mesh to {temp_path}", "NlmodInspector", Qgis.Info)
            
            success, msg = self.handler.export_to_mesh(var_name, layer_idx, temp_path)
            
            if not success:
                QtWidgets.QMessageBox.warning(self, "Export Error", f"Failed to export mesh: {msg}")
                return
            
            layer_name = f"{base_name} - {var_name} (L{layer_idx+1})"
            layer = QgsMeshLayer(temp_path, layer_name, "mdal")
            
            if layer.isValid():
                if not layer.crs().isValid():
                    layer.setCrs(QgsCoordinateReferenceSystem("EPSG:28992"))
                
                # Apply Turbo styling for Mesh
                self.style_mesh_layer(layer)
                
                QgsProject.instance().addMapLayer(layer)
                QgsMessageLog.logMessage(f"NLMOD: Successfully loaded mesh layer for {var_name}", "NlmodInspector", Qgis.Info)
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
                    xmin, xmax, ymin, ymax, y_is_ascending = extent
                    QgsMessageLog.logMessage(f"NLMOD: Using gdal.Translate with bounds: {xmin, ymin, xmax, ymax}", "NlmodInspector", Qgis.Info)
                    
                    from osgeo import gdal
                    # Open the subdataset directly
                    subdataset_uri = f'NETCDF:"{safe_path}":{var_name}'
                    ds = gdal.Open(subdataset_uri)
                    if ds:
                        # Use gdal.Translate to create a corrected VRT
                        # outputBounds is [ulx, uly, lrx, lry]
                        # By specifying [xmin, ymin, xmax, ymax], we force a standard North-Up orientation.
                        # GDAL will automatically handle any necessary flipping of the source data.
                        vrt_ds = gdal.Translate('', ds, format='VRT', 
                                                outputBounds=[xmin, ymin, xmax, ymax], 
                                                bandList=[band_idx])
                        
                        if vrt_ds:
                            vrt_xml = vrt_ds.GetMetadata('xml:VRT')[0]
                            vrt_ds = None # Close
                            
                            # If Y is ascending (South-to-North), we need to flip the source rectangle in the VRT
                            if y_is_ascending:
                                # We need to find <SrcRect xOff="0" yOff="0" xSize="W" ySize="H" />
                                # and change it to <SrcRect xOff="0" yOff="H" xSize="W" ySize="-H" />
                                import re
                                # Find yOff="0" and replace with yOff="{y_size}"
                                # Find ySize="{y_size}" and replace with ySize="-{y_size}"
                                # We can get y_size from the VRT XML itself or use the variable info
                                var_info = self.handler.ds.variables[var_name]
                                y_size = var_info.shape[-2] if var_info.ndim >= 2 else 0
                                if y_size > 0:
                                    vrt_xml = vrt_xml.replace('yOff="0"', f'yOff="{y_size}"')
                                    vrt_xml = vrt_xml.replace(f'ySize="{y_size}"', f'ySize="-{y_size}"')
                                    QgsMessageLog.logMessage(f"NLMOD: Applied VRT flip for ascending Y (size={y_size})", "NlmodInspector", Qgis.Info)
                        else:
                            QgsMessageLog.logMessage("NLMOD: gdal.Translate failed to create VRT.", "NlmodInspector", Qgis.Warning)
                            raise Exception("gdal.Translate failed")
                        ds = None
                    else:
                        QgsMessageLog.logMessage(f"NLMOD: Could not open subdataset {subdataset_uri}", "NlmodInspector", Qgis.Warning)
                        raise Exception("Could not open subdataset")

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
                    self.style_mesh_layer(layer)
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


    def style_mesh_layer(self, layer):
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
            # Using dataProvider is often more robust for metadata in PyQGIS
            provider = layer.dataProvider()
            if provider:
                meta = provider.datasetGroupMetadata(idx)
            else:
                meta = layer.datasetGroupMetadata(idx)
            
            # Robustly try to get min/max from metadata (method names vary by QGIS version)
            min_val = 0.0
            max_val = 1.0
            
            if hasattr(meta, 'minimumValue'):
                min_val = meta.minimumValue()
                max_val = meta.maximumValue()
            elif hasattr(meta, 'statistic'):
                # 0 = Minimum, 1 = Maximum
                try:
                    min_val = meta.statistic(0)
                    max_val = meta.statistic(1)
                except:
                    pass
            elif hasattr(meta, 'minimum'):
                min_val = meta.minimum()
                max_val = meta.maximum()
            
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
            layer.setRendererSettings(settings)
            layer.triggerRepaint()

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
            self.prev_map_tool = canvas.mapTool()
            from .cross_section_tool import CrossSectionMapTool
            self.xs_tool = CrossSectionMapTool(canvas)
            self.xs_tool.line_finished.connect(self.on_cross_section_finished)
            self.xs_tool.points_changed.connect(self.on_cross_section_changed)
            canvas.setMapTool(self.xs_tool)
            self.active_cs_id = None
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Tool Error", f"Failed to start tool: {e}")

    def fetch_cross_section_data(self, var_name, points):
        """Callback for CrossSectionPlotWindow to fetch data."""
        if not self.handler:
            return None
            
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
            
        return self.handler.get_cross_section_data(var_name, points)

    def on_cross_section_finished(self, points):
        """Called when user finishes drawing a line."""
        if not points or len(points) < 2:
            return
            
        # 1. Get selected variable
        selected_items = self.var_list.selectedItems()
        if not selected_items:
            QtWidgets.QMessageBox.information(self, "Info", "Please select a variable first.")
            return
            
        var_name = selected_items[0].data(QtCore.Qt.UserRole)
        
        # 2. Get all 3D variables for the combo box in the plot window
        vars_3d = []
        try:
            all_vars = self.handler.get_variables()
            possible_layer_dims = {'layer', 'lev', 'level', 'z'}
            for v in all_vars:
                if any(d in possible_layer_dims for d in v.get('dimensions', [])):
                    vars_3d.append(v['name'])
        except:
            vars_3d = [var_name]

        # 3. Extract Data (using our new fetcher)
        try:
            data = self.fetch_cross_section_data(var_name, points)
            if not data:
                return
            if "error" in data:
                QtWidgets.QMessageBox.warning(self, "Error", data["error"])
                return
                
            # 4. Calculate cumulative distances for vertices (in model units)
            # We need this for the vertical dashed lines
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

            # 5. Add to List Manager
            import time
            item_id = str(time.time())
            
            # Generate Letter Label (A, B, C...)
            cs_label = self.get_next_cs_label()
            
            from .cross_section_plot import CrossSectionPlotWindow
            
            # Create Window as DockWidget
            win = CrossSectionPlotWindow(
                data, var_name, 
                vertex_distances=v_dists, 
                item_id=item_id,
                all_vars=vars_3d,
                data_fetcher=self.fetch_cross_section_data,
                label=cs_label,
                points=points # Stores original canvas points for future re-transforms
            )
            win.variable_changed.connect(self.update_cs_list_label)
            
            # Restore previous map tool
            if self.prev_map_tool:
                self.iface.mapCanvas().setMapTool(self.prev_map_tool)
                self.prev_map_tool = None
            
            # Create Label for List: A: Head
            display_label = f"{cs_label}: {var_name}"
            
            item = QtWidgets.QListWidgetItem(display_label)
            item.setData(QtCore.Qt.UserRole, item_id)
            self.cs_list.addItem(item)
            
            # Select it
            self.cs_list.setCurrentItem(item)
            
            # Store
            self.plot_windows[item_id] = win
            self.cs_geometries[item_id] = points  # Store original points
            self.active_cs_id = item_id
            
            # Dock it in QGIS
            self.iface.addDockWidget(QtCore.Qt.BottomDockWidgetArea, win)
            win.show()
            
            # Create RubberBand for map visualization
            from qgis.gui import QgsRubberBand
            from qgis.core import QgsWkbTypes
            from qgis.PyQt.QtGui import QColor
            
            rubber_band = QgsRubberBand(self.iface.mapCanvas(), QgsWkbTypes.LineGeometry)
            rubber_band.setColor(QColor(255, 0, 0, 180))  # Red with transparency
            rubber_band.setWidth(3)
            rubber_band.setLineStyle(QtCore.Qt.DashLine)
            
            for point in points:
                rubber_band.addPoint(point)
            
            rubber_band.show()
            self.cs_rubber_bands[item_id] = rubber_band
            
            # Highlight this new one
            self.highlight_cross_section(item)
            
            # Clean up when closed? We could connect a signal, 
            # but for now explicit removal or app exit is fine.
            # Ideally: win.closed.connect(lambda: self.cleanup(item_id))
            
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Plot Error", f"Failed to plot: {e}")

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

        # If the tool is currently active, load these points into it
        if hasattr(self, 'xs_tool') and self.iface.mapCanvas().mapTool() == self.xs_tool:
            try:
                from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform
                canvas_crs = self.iface.mapCanvas().mapSettings().destinationCrs()
                model_crs_def = self.handler.get_crs()
                model_crs = QgsCoordinateReferenceSystem(model_crs_def if model_crs_def else "EPSG:28992")
                
                points = self.cs_geometries[item_id]
                if model_crs.isValid() and canvas_crs != model_crs:
                    xform = QgsCoordinateTransform(model_crs, canvas_crs, QgsProject.instance())
                    points = [xform.transform(p) for p in points]
                
                self.xs_tool.set_points(points)
            except:
                self.xs_tool.set_points(self.cs_geometries.get(item_id, []))

    def raise_cross_section_window(self, item):
        item_id = item.data(QtCore.Qt.UserRole)
        
        # Show window
        if item_id in self.plot_windows:
            win = self.plot_windows[item_id]
            win.show()
            win.raise_()
            win.activateWindow()
            self.highlight_cross_section(item)

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

    def remove_cross_section_by_id(self, item_id):
        """Cleanup when plot window is closed directly or removed from list."""
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
            
        # Also remove from list if it's still there (e.g. if closed via [X] on dock)
        for i in range(self.cs_list.count()):
            item = self.cs_list.item(i)
            if item.data(QtCore.Qt.UserRole) == item_id:
                self.cs_list.takeItem(i)
                break

    def remove_cross_section(self):
        selected_items = self.cs_list.selectedItems()
        if not selected_items:
            return
            
        item = selected_items[0]
        item_id = item.data(QtCore.Qt.UserRole)
        
        self.remove_cross_section_by_id(item_id)

    def get_next_cs_label(self):
        """Finds the next label based on Max(existing_labels) + 1."""
        existing_labels = []
        for win in self.plot_windows.values():
            if hasattr(win, 'cs_label'):
                existing_labels.append(win.cs_label)
        
        if not existing_labels:
            return "A"
            
        def label_to_int(lbl):
            # Very simple A, B, C... Z, A1, B1... converter
            # For now let's just handle A-Z for simplicity as requested
            # If we need more, we can use a proper base-26 system
            if len(lbl) == 1:
                return ord(lbl) - ord('A')
            try:
                # Handle things like 'A1' etc if they exist
                base = ord(lbl[0]) - ord('A')
                suffix = int(lbl[1:])
                return (suffix + 1) * 26 + base
            except:
                return 0

        def int_to_label(val):
            if val < 26:
                return chr(ord('A') + val)
            suffix = (val // 26) - 1
            base = val % 26
            return chr(ord('A') + base) + str(suffix + 1)

        # Get the max integer representation
        max_val = max(label_to_int(lbl) for lbl in existing_labels)
        return int_to_label(max_val + 1)

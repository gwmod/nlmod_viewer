from qgis.PyQt import QtWidgets, QtCore, QtGui
import pyqtgraph as pg
import numpy as np

class TimeSeriesPlotWindow(QtWidgets.QDockWidget):
    variable_changed = QtCore.pyqtSignal(str, str) # item_id, variable_name
    layers_changed = QtCore.pyqtSignal(str, list)   # item_id, layers
    marker_changed = QtCore.pyqtSignal(str, str)    # item_id, marker_type
    closed = QtCore.pyqtSignal(str)                # item_id

    COLORS = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf']

    def __init__(self, data, variable_name, parent=None, item_id=None, 
                 all_vars=None, data_fetcher=None, label="1", point=None,
                 layer_indices=None, marker_type='x'):
        super().__init__(parent)
        self.item_id = item_id
        self.data = data
        self.all_vars = all_vars or [variable_name]
        self.current_var = variable_name
        self.data_fetcher = data_fetcher
        self.label = label
        self.point = point
        self.layer_indices = layer_indices or [0]
        self.marker_type = marker_type
        
        self.setWindowTitle(f"Time Series {label}: {variable_name}")
        self.setAllowedAreas(QtCore.Qt.DockWidgetArea.AllDockWidgetAreas)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose, False)
        
        central = QtWidgets.QWidget()
        self.setWidget(central)
        layout = QtWidgets.QHBoxLayout(central)
        
        # Left side: Controls and Plot
        left_widget = QtWidgets.QWidget()
        left_layout = QtWidgets.QVBoxLayout(left_widget)
        layout.addWidget(left_widget, 4)
        
        # Tools
        tools_layout = QtWidgets.QHBoxLayout()
        tools_layout.addWidget(QtWidgets.QLabel("Variable:"))
        self.var_combo = QtWidgets.QComboBox()
        self.var_combo.addItems(self.all_vars)
        if self.current_var in self.all_vars:
            self.var_combo.setCurrentText(self.current_var)
        self.var_combo.currentTextChanged.connect(self.change_variable)
        tools_layout.addWidget(self.var_combo)
        
        self.btn_toggle_layers = QtWidgets.QPushButton("Layers >>")
        self.btn_toggle_layers.setCheckable(True)
        self.btn_toggle_layers.clicked.connect(self.toggle_layers_panel)
        tools_layout.addWidget(self.btn_toggle_layers)

        self.btn_settings = QtWidgets.QPushButton()
        self.btn_settings.setIcon(self.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_FileDialogDetailedView))
        self.btn_settings.setToolTip("Settings")
        self.btn_settings.clicked.connect(self.show_settings_menu)
        tools_layout.addWidget(self.btn_settings)
        
        tools_layout.addStretch()
        left_layout.addLayout(tools_layout)
        
        # Info
        self.info_label = QtWidgets.QLabel("")
        self.update_info_label()
        self.update_marker_menu_state()
        left_layout.addWidget(self.info_label)
        
        # Plot
        self.plot_widget = pg.PlotWidget(axisItems={'bottom': pg.DateAxisItem()})
        self.plot_widget.setBackground('w')
        self.plot_widget.showGrid(x=True, y=True)
        self.plot_widget.getPlotItem().getAxis('left').setPen('k')
        self.plot_widget.getPlotItem().getAxis('left').setTextPen('k')
        self.plot_widget.getPlotItem().getAxis('left').enableAutoSIPrefix(False)
        self.plot_widget.getPlotItem().getAxis('bottom').setPen('k')
        self.plot_widget.getPlotItem().getAxis('bottom').setTextPen('k')
        left_layout.addWidget(self.plot_widget)
        
        # Right side: Layer Selection
        self.layer_panel = QtWidgets.QWidget()
        right_layout = QtWidgets.QVBoxLayout(self.layer_panel)
        layout.addWidget(self.layer_panel, 1)
        
        right_layout.addWidget(QtWidgets.QLabel("Select Layers:"))
        
        # All/None buttons
        sel_btns_layout = QtWidgets.QHBoxLayout()
        self.btn_select_all = QtWidgets.QPushButton("All")
        self.btn_select_all.setToolTip("Select all layers")
        self.btn_select_all.clicked.connect(self.select_all_layers)
        
        self.btn_select_none = QtWidgets.QPushButton("None")
        self.btn_select_none.setToolTip("Deselect all layers")
        self.btn_select_none.clicked.connect(self.select_none_layers)
        
        sel_btns_layout.addWidget(self.btn_select_all)
        sel_btns_layout.addWidget(self.btn_select_none)
        right_layout.addLayout(sel_btns_layout)
        
        self.layer_list = QtWidgets.QListWidget()
        self.layer_list.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.MultiSelection)
        self.layer_list.itemSelectionChanged.connect(self.on_layer_selection_changed)
        right_layout.addWidget(self.layer_list)
        
        # Initialize
        self.populate_layers()
        self.render_plot()
        
    def populate_layers(self, force_update=False):
        if not self.data:
            return
            
        # Hide layer panel if variable has no layer dimension
        has_layers = self.data.get('has_layers', True)
        if not has_layers:
            self.layer_panel.setVisible(False)
            self.btn_toggle_layers.setVisible(False)
        else:
            self.btn_toggle_layers.setVisible(True)
            self.layer_panel.setVisible(self.btn_toggle_layers.isChecked())
        
        if 'layer_names' not in self.data:
            return
            
        # Select all by default if no selection exists
        if not self.layer_indices:
            self.layer_indices = list(range(len(self.data['layer_names'])))

        self.layer_list.blockSignals(True)
        self.layer_list.clear()
        for i, name in enumerate(self.data['layer_names']):
            item = QtWidgets.QListWidgetItem(name)
            self.layer_list.addItem(item)
            if i in self.layer_indices:
                item.setSelected(True)
        self.layer_list.blockSignals(False)
    
    def select_all_layers(self):
        self.layer_list.blockSignals(True)
        for i in range(self.layer_list.count()):
            self.layer_list.item(i).setSelected(True)
        self.layer_list.blockSignals(False)
        self.on_layer_selection_changed()

    def select_none_layers(self):
        self.layer_list.blockSignals(True)
        self.layer_list.clearSelection()
        self.layer_list.blockSignals(False)
        self.on_layer_selection_changed()
        
    def on_layer_selection_changed(self):
        new_indices = [self.layer_list.row(item) for item in self.layer_list.selectedItems()]
        new_indices.sort()
        
        self.layer_indices = new_indices
        
        if not self.layer_indices and self.data.get('has_layers', True):
            self.plot_widget.clear()
            return

        if self.data_fetcher:
            try:
                new_data = self.data_fetcher(self.current_var, self.point, self.layer_indices)
                if new_data and "error" not in new_data:
                    self.data = new_data
                    self.render_plot()
                    self.layers_changed.emit(self.item_id, self.layer_indices)
            except Exception as e:
                 QtWidgets.QMessageBox.warning(self, "Data Error", f"Failed to fetch data: {e}")

    def change_variable(self, var_name):
        if not self.data_fetcher: return
        try:
            new_data = self.data_fetcher(var_name, self.point, self.layer_indices, force_prompt=True)
            if new_data:
                if "error" in new_data:
                    QtWidgets.QMessageBox.warning(self, "Data Error", new_data['error'])
                    return
                self.data = new_data
                self.current_var = var_name
                self.setWindowTitle(f"Time Series {self.label}: {var_name}")
                self.populate_layers()
                self.render_plot()
                self.variable_changed.emit(self.item_id, var_name)
                self.update_info_label()
                self.update_marker_menu_state()
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Error", f"Failed to fetch data: {e}")

    def update_marker_menu_state(self):
        """Enable marker settings only for spatial time-series that have a map point."""
        has_spatial_point = bool(self.data and self.data.get('point') is not None)
        self.btn_settings.setEnabled(has_spatial_point)
        if has_spatial_point:
            self.btn_settings.setToolTip("Settings")
        else:
            self.btn_settings.setToolTip("Map marker settings are unavailable for non-spatial time series")

    def show_settings_menu(self):
        if not self.btn_settings.isEnabled():
            return
        menu = QtWidgets.QMenu(self)
        
        # Marker Type Submenu
        marker_menu = menu.addMenu("Map Marker")
        
        types = [
            ("X (x)", "x"),
            ("Cross (+)", "cross"),
            ("Box (□)", "box"),
            ("Circle (○)", "circle"),
            ("Triangle (△)", "triangle")
        ]
        
        group = QtWidgets.QActionGroup(self)
        for label, value in types:
            action = marker_menu.addAction(label)
            action.setCheckable(True)
            action.setData(value)
            action.setChecked(self.marker_type == value)
            group.addAction(action)
            action.triggered.connect(lambda _, v=value: self.set_marker_type(v))
            
        menu.exec(self.btn_settings.mapToGlobal(self.btn_settings.rect().bottomLeft()))

    def set_marker_type(self, value):
        self.marker_type = value
        self.marker_changed.emit(self.item_id, value)

    def render_plot(self):
        self.plot_widget.clear()
        if not self.data or 'times' not in self.data:
            return
            
        times = self.data['times']
        time_stamps = self.data.get('time_stamps', [])
        unit = self.data.get('unit', '')
        label_text = f"{self.current_var} ({unit})" if unit else self.current_var
        self.plot_widget.setLabel('left', label_text)
        self.plot_widget.setLabel('bottom', 'Date/Time')
        
        if time_stamps:
            x = np.array(time_stamps)
        else:
            x = np.arange(len(times))
        
        colors = self.COLORS

        has_layers = self.data.get('has_layers', True)
        series = self.data.get('series', [])
        should_show_legend = bool(has_layers or len(series) > 1)
        
        # Reset or remove legend
        if hasattr(self, 'legend') and self.legend:
            self.plot_widget.getPlotItem().legend.items = []
            if not should_show_legend:
                # Completely remove legend if not needed
                self.plot_widget.getPlotItem().removeItem(self.legend)
                self.legend = None
        elif should_show_legend:
            self.legend = self.plot_widget.addLegend()

        if series:
            for i, s in enumerate(series):
                y = np.array(s.get('values', []), dtype=float)
                y[np.isinf(y)] = np.nan
                color = colors[i % len(colors)]
                if should_show_legend:
                    self.plot_widget.plot(x, y, pen=pg.mkPen(color, width=2), name=s.get('name', self.current_var), connect="finite")
                else:
                    self.plot_widget.plot(x, y, pen=pg.mkPen(color, width=2), connect="finite")
        else:
            # Legacy path: plot using layer-indexed values.
            plot_indices = self.layer_indices if has_layers else self.data.get('values', {}).keys()
            for i, lyr in enumerate(plot_indices):
                if lyr in self.data.get('values', {}):
                    y = np.array(self.data['values'][lyr], dtype=float)
                    y[np.isinf(y)] = np.nan

                    color = colors[i % len(colors)]
                    if should_show_legend:
                        name = self.data['layer_names'][lyr] if 'layer_names' in self.data and lyr < len(self.data['layer_names']) else self.current_var
                        self.plot_widget.plot(x, y, pen=pg.mkPen(color, width=2), name=name, connect="finite")
                    else:
                        self.plot_widget.plot(x, y, pen=pg.mkPen(color, width=2), connect="finite")
        
        # DateAxisItem handles ticks automatically

    def refresh(self, all_vars=None):
        """Updates available variables and reloads data."""
        if all_vars is not None:
            self.all_vars = all_vars
            self.var_combo.blockSignals(True)
            self.var_combo.clear()
            self.var_combo.addItems(self.all_vars)
            if self.current_var in self.all_vars:
                self.var_combo.setCurrentText(self.current_var)
            self.var_combo.blockSignals(False)
        
        if self.data_fetcher:
             self.change_variable(self.current_var)
             self.populate_layers()

    def update_info_label(self):
        if not self.point:
            self.info_label.setText("Location: Unknown")
            return
            
        txt = f"X: {self.point.x():.1f} Y: {self.point.y():.1f}"
        
        if self.data and 'cell_info' in self.data:
            ci = self.data['cell_info']
            if isinstance(ci, (list, tuple)):
                txt += f" Row: {ci[0]} Column: {ci[1]}"
            else:
                txt += f" icell2d: {ci}"
        
        self.info_label.setText(txt)

    def toggle_layers_panel(self, checked):
        self.layer_panel.setVisible(checked)
        self.btn_toggle_layers.setText("Layers <<" if checked else "Layers >>")

    def closeEvent(self, event):
        self.closed.emit(self.item_id)
        super().closeEvent(event)

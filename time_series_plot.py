from qgis.PyQt import QtWidgets, QtCore, QtGui
import pyqtgraph as pg
import numpy as np

class TimeSeriesPlotWindow(QtWidgets.QDockWidget):
    variable_changed = QtCore.pyqtSignal(str, str) # item_id, new_var_name
    layers_changed = QtCore.pyqtSignal(str, list) # item_id, layer_indices
    closed = QtCore.pyqtSignal(str) # item_id
    
    def __init__(self, data, variable_name, parent=None, item_id=None, 
                 all_vars=None, data_fetcher=None, label="1", point=None,
                 layer_indices=None):
        super().__init__(parent)
        self.item_id = item_id
        self.data = data
        self.all_vars = all_vars or [variable_name]
        self.current_var = variable_name
        self.data_fetcher = data_fetcher
        self.label = label
        self.point = point
        self.layer_indices = layer_indices or [0]
        
        self.setWindowTitle(f"Time Series {label}: {variable_name}")
        self.setAllowedAreas(QtCore.Qt.AllDockWidgetAreas)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose, False)
        
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
        tools_layout.addStretch()
        left_layout.addLayout(tools_layout)
        
        # Info
        self.info_label = QtWidgets.QLabel("")
        self.update_info_label()
        left_layout.addWidget(self.info_label)
        
        # Plot
        self.plot_widget = pg.PlotWidget()
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
        self.layer_list.setSelectionMode(QtWidgets.QAbstractItemView.MultiSelection)
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
        self.layer_panel.setVisible(has_layers)
        
        if 'layer_names' not in self.data:
            return
            
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
            new_data = self.data_fetcher(var_name, self.point, self.layer_indices)
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
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Error", f"Failed to fetch data: {e}")

    def render_plot(self):
        self.plot_widget.clear()
        if not self.data or 'times' not in self.data:
            return
            
        times = self.data['times']
        unit = self.data.get('unit', '')
        label_text = f"{self.current_var} ({unit})" if unit else self.current_var
        self.plot_widget.setLabel('left', label_text)
        self.plot_widget.setLabel('bottom', 'Time step')
        
        x = np.arange(len(times))
        colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf']

        has_layers = self.data.get('has_layers', True)
        
        # Reset or remove legend
        if hasattr(self, 'legend') and self.legend:
            self.plot_widget.getPlotItem().legend.items = []
            if not has_layers:
                # Completely remove legend if not needed
                self.plot_widget.getPlotItem().removeItem(self.legend)
                self.legend = None
        elif has_layers:
            self.legend = self.plot_widget.addLegend()
        
        # If no layers, plot whatever is available in values (usually index 0)
        plot_indices = self.layer_indices if has_layers else self.data.get('values', {}).keys()
        
        for i, lyr in enumerate(plot_indices):
            if lyr in self.data.get('values', {}):
                # Ensure we have a numerical float array and handle potential Infs
                y = np.array(self.data['values'][lyr], dtype=float)
                y[np.isinf(y)] = np.nan
                
                color = colors[i % len(colors)]
                if has_layers:
                    name = self.data['layer_names'][lyr] if 'layer_names' in self.data and lyr < len(self.data['layer_names']) else self.current_var
                    self.plot_widget.plot(x, y, pen=pg.mkPen(color, width=2), name=name, connect="finite")
                else:
                    self.plot_widget.plot(x, y, pen=pg.mkPen(color, width=2), connect="finite")
        
        if times:
            ax = self.plot_widget.getAxis('bottom')
            # Only show subset of ticks if many
            step = max(1, len(times) // 10)
            ticks = [list(enumerate(times))[::step]]
            ax.setTicks(ticks)

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

    def closeEvent(self, event):
        self.closed.emit(self.item_id)
        super().closeEvent(event)

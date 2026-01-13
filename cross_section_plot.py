from qgis.PyQt import QtWidgets, QtCore, QtGui
import pyqtgraph as pg
import numpy as np

class CrossSectionPlotWindow(QtWidgets.QMainWindow):
    def __init__(self, data, variable_name, parent=None, vertex_distances=None):
        super().__init__(parent)
        self.setWindowTitle(f"Cross Section: {variable_name}")
        self.resize(800, 400)
        
        # Central Widget & Layout
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        layout = QtWidgets.QVBoxLayout(central)
        
        # Tools Layout
        tools_layout = QtWidgets.QHBoxLayout()
        
        tools_layout.addWidget(QtWidgets.QLabel("Z-Range (m):"))
        
        self.z_min_spin = QtWidgets.QDoubleSpinBox()
        self.z_min_spin.setRange(-10000, 10000)
        self.z_min_spin.setDecimals(1)
        self.z_min_spin.valueChanged.connect(self.update_z_range)
        tools_layout.addWidget(self.z_min_spin)
        
        tools_layout.addWidget(QtWidgets.QLabel(" to "))
        
        self.z_max_spin = QtWidgets.QDoubleSpinBox()
        self.z_max_spin.setRange(-10000, 10000)
        self.z_max_spin.setDecimals(1)
        self.z_max_spin.valueChanged.connect(self.update_z_range)
        tools_layout.addWidget(self.z_max_spin)
        
        self.reset_z_btn = QtWidgets.QPushButton("Reset to Data")
        self.reset_z_btn.clicked.connect(self.reset_z_range)
        tools_layout.addWidget(self.reset_z_btn)
        
        # Spacer
        tools_layout.addSpacing(20)
        
        # Data Range
        tools_layout.addWidget(QtWidgets.QLabel("Data Range:"))
        
        self.v_min_spin = QtWidgets.QDoubleSpinBox()
        self.v_min_spin.setRange(-1e6, 1e6)
        self.v_min_spin.setDecimals(2)
        tools_layout.addWidget(self.v_min_spin)
        
        tools_layout.addWidget(QtWidgets.QLabel(" to "))
        
        self.v_max_spin = QtWidgets.QDoubleSpinBox()
        self.v_max_spin.setRange(-1e6, 1e6)
        self.v_max_spin.setDecimals(2)
        tools_layout.addWidget(self.v_max_spin)
        
        self.apply_v_btn = QtWidgets.QPushButton("Apply")
        self.apply_v_btn.clicked.connect(self.apply_data_range)
        tools_layout.addWidget(self.apply_v_btn)
        
        tools_layout.addStretch()
        layout.addLayout(tools_layout)
        
        # Store data for re-rendering
        self.data = data
        self.colorbar = None
        self.vertex_lines = []
        
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
        self.plot_widget.showGrid(x=True, y=True)
        
        # Render Data
        self.render_data(data, vertex_distances=vertex_distances)
        
        # Initialize Range Settings
        self.init_ranges(data)

    def init_ranges(self, data):
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

    def reset_z_range(self):
        if hasattr(self, 'data_z_min'):
            margin = (self.data_z_max - self.data_z_min) * 0.1
            if margin == 0: margin = 1.0
            
            self.z_min_spin.setValue(self.data_z_min - margin)
            self.z_max_spin.setValue(self.data_z_max + margin)

    def apply_data_range(self):
        v_min = self.v_min_spin.value()
        v_max = self.v_max_spin.value()
        if v_max > v_min:
            # Re-render with new limits
            self.render_data(self.data, v_min, v_max)

    def render_data(self, data, v_min=None, v_max=None, vertex_distances=None):
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
            
        # Create Optimized Item
        self.dataset_item = CrossSectionMeshItem(dists, top, botm, vals, cmap, (v_min, v_max))
        self.plot_widget.addItem(self.dataset_item)
        
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

        # Add Vertical Vertex Lines
        if vertex_distances:
            for d in vertex_distances:
                line = pg.InfiniteLine(pos=d, angle=90, pen=pg.mkPen('k', style=QtCore.Qt.DashLine))
                self.plot_widget.addItem(line)
                self.vertex_lines.append(line)

class CrossSectionMeshItem(pg.GraphicsObject):
    def __init__(self, dists, top, botm, vals, cmap, val_range=None):
        super().__init__()
        self.dists = dists
        self.top = top
        self.botm = botm
        self.vals = vals
        self.cmap = cmap
        self.val_range_override = val_range
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
        
        # Optimization: Quantize colors into bins (e.g. 256)
        # Create a QPainterPath for each bin to minimize state changes
        n_bins = 256
        paths = [QtGui.QPainterPath() for _ in range(n_bins)]
        
        # Iterate and assign to paths
        # This python loop is still the heaviest part, but doing it once 
        # to build paths is better than managing objects.
        
        for i in range(num_layers):
            if i == 0: l_top = self.top
            else: l_top = self.botm[i-1]
            l_bot = self.botm[i]
            
            for j in range(num_points - 1):
                 val = float(self.vals[i, j])
                 if np.isnan(val): continue
                 
                 # Skip if geometry is NaN (Out of Domain)
                 if np.isnan(l_top[j]) or np.isnan(l_top[j+1]) or \
                    np.isnan(l_bot[j]) or np.isnan(l_bot[j+1]):
                     continue
                 
                 # Bin index
                 norm = (val - min_val) / val_range
                 bin_idx = int(norm * (n_bins - 1))
                 bin_idx = max(0, min(n_bins-1, bin_idx))
                 
                 # Add rect to path
                 # Top Left, Top Right, Bottom Right, Bottom Left
                 poly = QtGui.QPolygonF([
                     QtCore.QPointF(self.dists[j], l_top[j]),
                     QtCore.QPointF(self.dists[j+1], l_top[j+1]),
                     QtCore.QPointF(self.dists[j+1], l_bot[j+1]),
                     QtCore.QPointF(self.dists[j], l_bot[j])
                 ])
                 paths[bin_idx].addPolygon(poly)
        
        # Draw paths
        # Pre-calculate colors
        colors = [self.cmap.map(i / (n_bins - 1)) for i in range(n_bins)]
        
        for bin_idx, path in enumerate(paths):
            if path.isEmpty(): continue
            p.setBrush(pg.mkBrush(colors[bin_idx]))
            p.drawPath(path)
            
        p.end()
        
    def paint(self, p, *args):
        if self.picture:
            self.picture.play(p)
    
    def boundingRect(self):
        if self.picture:
            return QtCore.QRectF(self.picture.boundingRect())
        return QtCore.QRectF()

from qgis.PyQt import QtWidgets, QtCore, QtGui
import pyqtgraph as pg
import numpy as np

class CrossSectionPlotWindow(QtWidgets.QMainWindow):
    def __init__(self, data, variable_name, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Cross Section: {variable_name}")
        self.resize(800, 400)
        
        # Central Widget & Layout
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        layout = QtWidgets.QVBoxLayout(central)
        
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
        self.render_data(data)

    def render_data(self, data):
        # Unpack
        dists = data['distances']
        top = data['top']
        botm = data['botm']
        vals = data['values']
        
        # Color Map
        cmap = pg.colormap.get('turbo')
        
        # Create Optimized Item
        self.dataset_item = CrossSectionMeshItem(dists, top, botm, vals, cmap)
        self.plot_widget.addItem(self.dataset_item)
        
        # Add Colorbar
        # Get min/max from the data
        valid_vals = vals[~np.isnan(vals)]
        if len(valid_vals) > 0:
            min_val = np.nanmin(valid_vals)
            max_val = np.nanmax(valid_vals)
            
            # Create ColorBarItem
            colorbar = pg.ColorBarItem(
                values=(min_val, max_val),
                colorMap=cmap,
                width=15,
                interactive=False
            )
            
            # Add directly to plot layout (row 2, column 3 = right side)
            self.plot_widget.plotItem.layout.addItem(colorbar, 2, 3)
            
            # Style the colorbar axis
            colorbar.getAxis('right').setPen('k')
            colorbar.getAxis('right').setTextPen('k')

class CrossSectionMeshItem(pg.GraphicsObject):
    def __init__(self, dists, top, botm, vals, cmap):
        super().__init__()
        self.dists = dists
        self.top = top
        self.botm = botm
        self.vals = vals
        self.cmap = cmap
        self.picture = None
        self._generate_picture()
        
    def _generate_picture(self):
        self.picture = QtGui.QPicture()
        p = QtGui.QPainter(self.picture)
        p.setPen(pg.mkPen(None))
        
        # Calculate ranges
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

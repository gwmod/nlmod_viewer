from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction
from .nlmod_dockwidget import NlmodDockWidget
import os

class NlmodInspector:
    def __init__(self, iface):
        """Constructor."""
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.dockwidget = None
        self.action = None

    def initGui(self):
        """Create the menu entries and toolbar icons inside the QGIS GUI."""
        icon_path = os.path.join(self.plugin_dir, 'icons', 'icon.png')
        self.action = QAction(QIcon(icon_path), "NLMOD Inspector", self.iface.mainWindow())
        self.action.setToolTip("Inspect NLMOD groundwater NetCDF files")
        self.action.triggered.connect(self.run)
        
        # Add to the Plugins menu
        self.iface.addPluginToMenu("&NLMOD Inspector", self.action)
        # Add to the Toolbar
        self.iface.addToolBarIcon(self.action)

    def unload(self):
        """Removes the plugin menu item and icon from QGIS GUI."""
        self.iface.removePluginMenu("&NLMOD Inspector", self.action)
        self.iface.removeToolBarIcon(self.action)
        if self.dockwidget:
            self.iface.removeDockWidget(self.dockwidget)

    def run(self):
        """Run method that loads the dock widget."""
        if not self.dockwidget:
            self.dockwidget = NlmodDockWidget(self.iface.mainWindow(), self.iface)
            # Add dock widget to left area (Qt.LeftDockWidgetArea = 0x1)
            self.iface.addDockWidget(Qt.LeftDockWidgetArea, self.dockwidget)
        
        self.dockwidget.show()

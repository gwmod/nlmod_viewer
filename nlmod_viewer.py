from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction
from .nlmod_dockwidget import NlmodDockWidget
import os

class NlmodViewer:
    def __init__(self, iface):
        """Constructor."""
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.dockwidget = None
        self.action = None

    def initGui(self):
        """Create the menu entries and toolbar icons inside the QGIS GUI."""
        icon_path = os.path.join(self.plugin_dir, 'icons', 'icon.png')
        self.action = QAction(QIcon(icon_path), "NLMOD Viewer", self.iface.mainWindow())
        self.action.setToolTip("View NLMOD NetCDF files")
        self.action.triggered.connect(self.run)
        
        # Add to the Plugins menu
        self.iface.addPluginToMenu("&NLMOD Viewer", self.action)
        # Add to the Toolbar
        self.iface.addToolBarIcon(self.action)

        # Connect to project signals for automatic restoration
        from qgis.core import QgsProject
        QgsProject.instance().readProject.connect(self.on_project_read)
        QgsProject.instance().cleared.connect(self.on_project_new)

        # Check if project is already loaded (e.g. plugin reload)
        if QgsProject.instance().fileName():
            self.on_project_read()

    def on_project_read(self):
        """Called when a project is loaded."""
        # Use a small delay because QgsProject entries might not be ready 
        # immediately when the signal fires in some QGIS versions.
        from qgis.PyQt.QtCore import QTimer
        QTimer.singleShot(200, self._deferred_on_project_read)

    def _deferred_on_project_read(self):
        from qgis.core import QgsProject
        
        # 0. Clear any existing state from previous project
        if self.dockwidget:
            self.dockwidget.clear_all_cross_sections()
            
        # 1. Read visibility first before any potential overwrites
        # Try new name first, fallback to old name for backwards compatibility
        is_open_str, ok = QgsProject.instance().readEntry("NlmodViewer", "is_open", "")
        if not ok:
            is_open_str, _ = QgsProject.instance().readEntry("NlmodInspector", "is_open", "false")
        if not is_open_str:
            is_open_str = "false"
        
        # 2. Ensure dock exists and restore its data
        self.create_dock()
        
        # 3. Apply visibility
        if is_open_str == "true":
            self.dockwidget.show()
        else:
            self.dockwidget.hide()

    def on_project_new(self):
        """Called when a new project is created."""
        if self.dockwidget:
            self.dockwidget.clear_all_cross_sections()
            self.dockwidget.close()
            self.dockwidget = None

    def unload(self):
        """Removes the plugin menu item and icon from QGIS GUI."""
        self.iface.removePluginMenu("&NLMOD Viewer", self.action)
        self.iface.removeToolBarIcon(self.action)
        if self.dockwidget:
            self.iface.removeDockWidget(self.dockwidget)

    def create_dock(self):
        """Ensures the dock widget is created and state is restored."""
        if not self.dockwidget:
            self.dockwidget = NlmodDockWidget(self.iface.mainWindow(), self.iface)
            self.iface.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dockwidget)
            # restore_state_from_project is automatically called by DockWidget's __init__
            # but let's be explicit if we changed that to remove the timer
            self.dockwidget.restore_state_from_project()
        return self.dockwidget

    def run(self):
        """Run method that loads the dock widget."""
        self.create_dock()
        self.dockwidget.show()
        self.dockwidget.raise_()
        self.dockwidget.activateWindow()

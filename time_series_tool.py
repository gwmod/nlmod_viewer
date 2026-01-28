from qgis.core import QgsWkbTypes, QgsPointXY, QgsGeometry, Qgis, QgsMessageLog
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor
from qgis.gui import QgsMapTool, QgsRubberBand, QgsVertexMarker

class TimeSeriesMapTool(QgsMapTool):
    point_clicked = pyqtSignal(object) 
    point_moved = pyqtSignal(object)

    def __init__(self, canvas):
        super().__init__(canvas)
        self.canvas = canvas
        self.marker = None
        self.point = None
        self.is_dragging = False

    def set_point(self, point):
        self.point = point
        self.refresh_display()

    def clear_point(self):
        self.point = None
        self.refresh_display()

    def refresh_display(self):
        if self.marker:
            self.canvas.scene().removeItem(self.marker)
            self.marker = None

        if self.point:
            self.marker = QgsVertexMarker(self.canvas)
            self.marker.setCenter(self.point)
            self.marker.setColor(QColor(0, 0, 255))
            self.marker.setIconType(QgsVertexMarker.ICON_X)
            self.marker.setPenWidth(3)
            self.marker.setIconSize(12)

    def canvasPressEvent(self, e):
        point = self.toMapCoordinates(e.pos())
        if e.button() == Qt.LeftButton:
            if self.point and self.is_close(point, self.point):
                self.is_dragging = True
            else:
                self.point = point
                self.refresh_display()
                self.point_clicked.emit(self.point)
        elif e.button() == Qt.RightButton:
            # Maybe cancel?
            pass
                
    def canvasMoveEvent(self, e):
        if self.is_dragging:
            self.point = self.toMapCoordinates(e.pos())
            self.refresh_display()
            self.point_moved.emit(self.point)

    def canvasReleaseEvent(self, e):
        if self.is_dragging:
            self.is_dragging = False
            self.point_moved.emit(self.point)

    def is_close(self, p1, p2):
        dist = self.canvas.mapSettings().mapUnitsPerPixel() * 12
        return p1.distance(p2) < dist

    def deactivate(self):
        if self.marker:
            self.canvas.scene().removeItem(self.marker)
            self.marker = None
        # self.point = None # Don't clear point on deactivation if we want to keep it visible
        super().deactivate()

from qgis.gui import QgsMapToolEmitPoint, QgsRubberBand, QgsVertexMarker
from qgis.core import QgsWkbTypes, QgsPointXY, QgsGeometry
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor

class CrossSectionMapTool(QgsMapToolEmitPoint):
    # Signal emitted when a line is completed: List of QgsPointXY
    line_finished = pyqtSignal(object) 
    # Signal emitted when points are modified (dragged): List of QgsPointXY
    points_changed = pyqtSignal(object)

    def __init__(self, canvas):
        super().__init__(canvas)
        self.canvas = canvas
        self.rubberBand = QgsRubberBand(self.canvas, QgsWkbTypes.LineGeometry)
        self.rubberBand.setColor(QColor(255, 0, 0))
        self.rubberBand.setWidth(2)
        self.rubberBand.setLineStyle(Qt.DashLine)
        
        self.points = []
        self.markers = []
        self.is_drawing = False
        self.is_dragging = False
        self.dragged_vertex_idx = -1
        self.is_moving_all = False
        self.last_mouse_pos = None

    def set_points(self, points):
        """Set existing points for editing."""
        self.points = list(points)
        self.is_drawing = False
        self.is_dragging = False
        self.refresh_display()

    def refresh_display(self):
        """Update rubber band and markers from self.points."""
        self.rubberBand.reset(QgsWkbTypes.LineGeometry)
        for m in self.markers:
            self.canvas.scene().removeItem(m)
        self.markers = []

        if not self.points:
            return

        for p in self.points:
            self.rubberBand.addPoint(p, False)
            marker = QgsVertexMarker(self.canvas)
            marker.setCenter(p)
            marker.setColor(QColor(255, 0, 0))
            marker.setIconType(QgsVertexMarker.ICON_BOX)
            marker.setPenWidth(2)
            self.markers.append(marker)
        
        self.rubberBand.update()
        self.rubberBand.show()

    def canvasPressEvent(self, e):
        point = self.toMapCoordinates(e.pos())
        
        if e.button() == Qt.LeftButton:
            # Check if we are clicking on an existing vertex for dragging
            for i, p in enumerate(self.points):
                if self.is_close(point, p):
                    self.is_dragging = True
                    self.dragged_vertex_idx = i
                    self.is_drawing = False # Stop drawing if we were
                    return

            if not self.is_drawing:
                # Check for line movement if we didn't hit a vertex
                if len(self.points) >= 2:
                    geom = QgsGeometry.fromPolylineXY(self.points)
                    dist_tol = self.canvas.mapSettings().mapUnitsPerPixel() * 10
                    if geom.distance(QgsGeometry.fromPointXY(point)) < dist_tol:
                        self.is_moving_all = True
                        self.last_mouse_pos = point
                        return

                # Start new drawing (replaces existing if any)
                self.points = [point]
                self.is_drawing = True
                self.refresh_display()
            else:
                # Add point to current drawing
                self.points.append(point)
                self.refresh_display()
                
        elif e.button() == Qt.RightButton:
            if self.is_drawing:
                if len(self.points) >= 2:
                    # Finish drawing
                    self.is_drawing = False
                    self.line_finished.emit(self.points)
                    self.refresh_display()
                else:
                    # Cancel drawing
                    self.is_drawing = False
                    self.points = []
                    self.refresh_display()
            else:
                # Edit mode: Check for vertex removal
                for i, p in enumerate(self.points):
                    if self.is_close(point, p):
                        if len(self.points) > 2:
                            self.points.pop(i)
                            self.refresh_display()
                            self.points_changed.emit(self.points)
                        return

    def is_close(self, p1, p2):
        # Pixel-based tolerance for selection
        dist = self.canvas.mapSettings().mapUnitsPerPixel() * 10 # 10 pixels
        return p1.distance(p2) < dist

    def canvasMoveEvent(self, e):
        point = self.toMapCoordinates(e.pos())
        
        if self.is_dragging and self.dragged_vertex_idx != -1:
            self.points[self.dragged_vertex_idx] = point
            self.refresh_display()
        elif self.is_moving_all and self.last_mouse_pos:
            dx = point.x() - self.last_mouse_pos.x()
            dy = point.y() - self.last_mouse_pos.y()
            for i in range(len(self.points)):
                self.points[i] = QgsPointXY(self.points[i].x() + dx, self.points[i].y() + dy)
            self.last_mouse_pos = point
            self.refresh_display()
        elif self.is_drawing and self.points:
            # Temporary "rubber band" to cursor
            self.rubberBand.reset(QgsWkbTypes.LineGeometry)
            for p in self.points:
                self.rubberBand.addPoint(p, False)
            self.rubberBand.addPoint(point, True)

    def canvasReleaseEvent(self, e):
        if self.is_dragging:
            self.is_dragging = False
            self.dragged_vertex_idx = -1
            self.points_changed.emit(self.points)
        elif self.is_moving_all:
            self.is_moving_all = False
            self.last_mouse_pos = None
            self.points_changed.emit(self.points)

    def canvasDoubleClickEvent(self, e):
        if self.is_drawing or not self.points:
            return
            
        point = self.toMapCoordinates(e.pos())
        geom = QgsGeometry.fromPolylineXY(self.points)
        dist_tol = self.canvas.mapSettings().mapUnitsPerPixel() * 10
        
        sq_dist, closest_pt, after_vertex, left_of = geom.closestSegmentWithContext(point)
        
        if sq_dist**0.5 < dist_tol:
            # Insert point into the list
            # after_vertex is the index of the vertex AT THE END of the segment
            self.points.insert(after_vertex, point)
            self.refresh_display()
            self.points_changed.emit(self.points)

    def deactivate(self):
        self.rubberBand.reset(QgsWkbTypes.LineGeometry)
        for m in self.markers:
            self.canvas.scene().removeItem(m)
        self.markers = []
        self.is_drawing = False
        self.is_dragging = False
        self.is_moving_all = False
        self.points = []
        super().deactivate()

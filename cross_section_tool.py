from qgis.core import QgsWkbTypes, QgsPointXY, QgsGeometry
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import QMenu, QAction
from qgis.gui import QgsMapTool, QgsRubberBand, QgsVertexMarker


class CrossSectionMapTool(QgsMapTool):
    # Signal emitted when a line is completed: List of QgsPointXY
    line_finished = pyqtSignal(object) 
    # Signal emitted when points are modified (dragged): List of QgsPointXY
    points_changed = pyqtSignal(object)

    def __init__(self, canvas):
        super().__init__(canvas)
        self.canvas = canvas
        self.rubberBand = QgsRubberBand(self.canvas, QgsWkbTypes.GeometryType.LineGeometry)
        self.rubberBand.setColor(QColor(255, 0, 0))
        self.rubberBand.setWidth(2)
        self.rubberBand.setLineStyle(Qt.PenStyle.DashLine)
        
        self.points = []
        self.markers = []
        self.is_drawing = False
        self.is_dragging = False
        self.dragged_vertex_idx = -1
        self.is_moving_all = False
        self.last_mouse_pos = None
        self.can_draw = False # If false, only edit existing lines

    def set_points(self, points):
        """Set existing points for editing."""
        self.points = list(points)
        self.is_drawing = False
        self.is_dragging = False
        self.refresh_display()

    def refresh_display(self):
        """Update rubber band and markers from self.points."""
        self.rubberBand.reset(QgsWkbTypes.GeometryType.LineGeometry)
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
            marker.setIconType(QgsVertexMarker.IconType.ICON_BOX)
            marker.setPenWidth(2)
            self.markers.append(marker)
        
        self.rubberBand.update()
        self.rubberBand.show()

    def canvasPressEvent(self, e):
        point = self.toMapCoordinates(e.pos())
        
        if e.button() == Qt.MouseButton.LeftButton:
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
                if self.can_draw:
                    self.points = [point]
                    self.is_drawing = True
                    self.refresh_display()
                else:
                    # Not in draw mode, skip
                    pass
            else:
                # Add point to current drawing
                self.points.append(point)
                self.refresh_display()
                
        elif e.button() == Qt.MouseButton.RightButton:
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
                # Edit mode: Context Menu
                # 1. Check if on vertex
                vertex_idx = -1
                for i, p in enumerate(self.points):
                    if self.is_close(point, p):
                        vertex_idx = i
                        break
                
                # 2. Check if on segment
                segment_info = None
                if vertex_idx == -1:
                    geom = QgsGeometry.fromPolylineXY(self.points)
                    dist_tol = self.canvas.mapSettings().mapUnitsPerPixel() * 15
                    res = geom.closestSegmentWithContext(point)
                    if res[0]**0.5 < dist_tol:
                        segment_info = res # (sqDist, closestPoint, afterVertex, leftOf)

                # 3. Build and show Menu
                menu = QMenu(self.canvas)
                
                if vertex_idx != -1:
                    action_remove = QAction("Remove point", menu)
                    action_remove.triggered.connect(lambda: self.remove_vertex(vertex_idx))
                    # Only allow removal if we have more than 2 points
                    action_remove.setEnabled(len(self.points) > 2)
                    menu.addAction(action_remove)
                elif segment_info:
                    action_add = QAction("Add point", menu)
                    # after_vertex is res[2]
                    action_add.triggered.connect(lambda: self.add_vertex(segment_info[2], point))
                    menu.addAction(action_add)
                
                if not menu.isEmpty():
                    menu.exec(e.globalPos())

    def remove_vertex(self, idx):
        if len(self.points) > 2:
            self.points.pop(idx)
            self.refresh_display()
            self.points_changed.emit(self.points)

    def add_vertex(self, idx, point):
        self.points.insert(idx, point)
        self.refresh_display()
        self.points_changed.emit(self.points)

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
            self.rubberBand.reset(QgsWkbTypes.GeometryType.LineGeometry)
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
        # We now use right-click context menu for vertex operations
        pass

    def deactivate(self):
        self.rubberBand.reset(QgsWkbTypes.GeometryType.LineGeometry)
        for m in self.markers:
            self.canvas.scene().removeItem(m)
        self.markers = []
        self.is_drawing = False
        self.is_dragging = False
        self.is_moving_all = False
        self.points = []
        super().deactivate()

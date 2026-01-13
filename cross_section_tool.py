from qgis.gui import QgsMapToolEmitPoint, QgsRubberBand
from qgis.core import QgsWkbTypes, QgsPointXY, QgsGeometry
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor

class CrossSectionMapTool(QgsMapToolEmitPoint):
    # Signal emitted when a line is completed: List of QgsPointXY
    line_finished = pyqtSignal(object) 

    def __init__(self, canvas):
        super().__init__(canvas)
        self.canvas = canvas
        self.rubberBand = QgsRubberBand(self.canvas, QgsWkbTypes.LineGeometry)
        self.rubberBand.setColor(QColor(255, 0, 0))
        self.rubberBand.setWidth(2)
        
        self.points = []
        self.is_drawing = False

    def canvasPressEvent(self, e):
        point = self.toMapCoordinates(e.pos())
        
        if e.button() == Qt.LeftButton:
            if not self.is_drawing:
                # Start drawing
                self.points = [point]
                self.is_drawing = True
                self.rubberBand.reset(QgsWkbTypes.LineGeometry)
                self.rubberBand.addPoint(point, True)
                self.rubberBand.show()
            else:
                # Add point
                self.points.append(point)
                self.rubberBand.addPoint(point, True)
                
        elif e.button() == Qt.RightButton:
            if self.is_drawing and len(self.points) >= 2:
                # Finish drawing
                self.is_drawing = False
                self.line_finished.emit(self.points)
                # Reset
                self.points = []
                self.rubberBand.reset(QgsWkbTypes.LineGeometry) 
            else:
                # Cancel or ignore if not enough points
                self.is_drawing = False
                self.points = []
                self.rubberBand.reset(QgsWkbTypes.LineGeometry)

    def canvasMoveEvent(self, e):
        if self.is_drawing and len(self.points) > 0:
            point = self.toMapCoordinates(e.pos())
            # Update rubber band visual without committing point
            # QgsRubberBand doesn't support transient points well?
            # We can re-add the last point geometry if needed, 
            # or just rely on clicks. Visualizing the "rubber band" to cursor is better.
            
            # Simple approach: Rebuild geometry with temp point
            self.rubberBand.reset(QgsWkbTypes.LineGeometry)
            for p in self.points:
                self.rubberBand.addPoint(p, False)
            self.rubberBand.addPoint(point, True)

    def deactivate(self):
        self.rubberBand.reset(QgsWkbTypes.LineGeometry)
        self.is_drawing = False
        self.points = []
        super().deactivate()

# NLMOD Inspector

A QGIS plugin for inspecting input and output of groundwater models built with [nlmod](https://nlmod.readthedocs.io). This plugin reads NetCDF files containing groundwater model data and visualizes them in QGIS, supporting both structured and vertex (quadtree/unstructured) grids.

## Features

- **NetCDF Support**: Read and visualize NetCDF files from nlmod groundwater models
- **Grid Type Detection**: Automatically detects structured vs. vertex/unstructured grids
- **Layer Selection**: Select specific model layers using actual layer coordinate values
- **Smart Visualization**: 
  - Structured grids: Load as raster layers with automatic pseudocolor styling
  - Vertex grids: Load as mesh layers via MDAL
- **CRS Handling**: Defaults to Dutch coordinate system (EPSG:28992) when CRS is not specified
- **Cross-Section Tool**: Draw lines on the map to plot high-quality cross-sections with interactive cell inspection
- **Time Series Tool**: Place points on the map or cross-sections to generate dynamic time-series plots
- **Variable Inspector**: Browse and select from available model variables (head, conductivity, etc.) with metadata display
- **Project Integrated**: All settings (NetCDF path, cross-sections, time-series) are saved directly in your QGIS project file

## State Persistence

The NLMOD Inspector is designed to be fully integrated with your workflow. **The following information is automatically stored within your QGIS project file (`.qgs` or `.qgz`):**

- The absolute path to the **loaded NetCDF file**.
- All **Cross-Section lines**, their names, and their individual plot settings (Z-ranges, colormaps, etc.).
- All **Time Series points**, their labels, and their selected layer indices.

This means when you save your QGIS project and reopen it later, your entire analysis setup—including all open plot windows and their specific configurations—will be restored exactly as you left it.

## Installation

### From Source

1. Clone or download this repository
2. Copy the `NlmodInspector` folder to your QGIS plugins directory:
   - **Windows**: `C:\Users\<YourUser>\AppData\Roaming\QGIS\QGIS3\profiles\default\python\plugins\`
   - **Linux/Mac**: `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/`
3. Restart QGIS
4. Enable the plugin in **Plugins > Manage and Install Plugins**

### Dependencies

- **QGIS 3.x**
- **Python `netCDF4` library**: Usually included in QGIS (OSGeo4W). If missing, install via OSGeo4W Shell:
  ```bash
  pip install netCDF4
  ```
- **Optional**: `pyqtgraph` for cross-section plotting:
  ```bash
  pip install pyqtgraph
  ```

### Map Layer Visualization

1. Click the **NLMOD Inspector** icon in the toolbar or select it from the Plugins menu.
2. A dock widget will appear on the left side.
3. Click **Browse...** to select your NetCDF file (`.nc`, `.nc4`, or `.hdf5`).
4. The plugin will display file metadata and grid type.
5. **Variables List**:
   - Browse availabe model variables.
   - **Right-click** a variable and select **Show Attributes** to view detailed metadata (dimensions, units, description).
6. Select a variable to plot.
7. If applicable, select a **Layer** and **Time Step** from the dropdowns.
8. Click **Add to Map** to load the layer into QGIS.

### Cross-Section Plotting

Manage cross-sections using the dedicated group at the bottom of the dock widget.

1. **Create**: Click **Add** and click on the map to define the cross-section line. Right-click to finish drawing.
2. **Interact**: Double-click an item in the list to bring its plot window to the front.
3. **Manage**: 
   - **Right-click** an item in the list to **Rename**, **Edit Vertices**, **Move Up**, or **Move Down**.
   - Select an item and click **Remove** to delete it.

#### Cross-Section Window Features
- **Variable Selection**: Switch the plotted variable dynamically using the dropdown at the top.
- **Navigation**: Zoom and pan with the mouse.
- **Interactivity**: Click anywhere in the plot to see the specific cell value, layer, and coordinates.
- **Settings**: Click the **Settings...** button to configure:
  - **Appearance**: Toggle Layer Boundaries, Cell Boundaries, and **Show Layer Names** (labels placed at the thickest part of the layer).
  - **Color Scale**: Set Min/Max values, toggle **Log Scale**, choose a **Colormap** (defaults to Turbo), and **Invert** the colors.

## Grid Type Support

### Structured Grids
- Detected by presence of `x`, `y`, `row`, `column` dimensions
- Loaded as QGIS Raster Layers
- Automatic Turbo color ramp applied
- Layer selection uses actual coordinate values

### Vertex/Unstructured Grids
- Detected by UGRID conventions (`mesh2d_face_nodes`, etc.)
- Loaded as QGIS Mesh Layers via MDAL
- Supports quadtree and other unstructured meshes

## Development

### Project Structure
```
NlmodInspector/
├── __init__.py              # Plugin entry point
├── nlmod_inspector.py       # Main plugin class
├── nlmod_dockwidget.py      # UI dock widget
├── netcdf_handler.py        # NetCDF file parsing
├── cross_section_tool.py    # Map tool for drawing lines
├── cross_section_plot.py    # Plotting window
├── metadata.txt             # QGIS plugin metadata
├── icons/                   # Plugin icons
└── README.md
```

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the GNU General Public License v3.0 - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- Built for use with [nlmod](https://github.com/gwmod/nlmod) - Netherlands MODFLOW toolkit
- Uses QGIS API for geospatial visualization
- NetCDF support via netCDF4-python

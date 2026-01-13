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
- **Cross-Section Tool**: Draw lines on the map to plot cross-sections of model data
- **Variable Inspector**: Browse and select from available model variables (head, conductivity, etc.)

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

## Usage

1. Click the **NLMOD Inspector** icon in the toolbar or select it from the Plugins menu
2. A dock widget will appear on the left side
3. Click **Browse...** to select your NetCDF file (`.nc`, `.nc4`, or `.hdf5`)
4. The plugin will display:
   - File metadata and grid type
   - Available variables (model inputs/outputs)
5. Select a variable from the list
6. If the variable has multiple layers, select the desired layer from the dropdown
7. Click **Add to Map** to load the layer
8. Use QGIS tools to interact with the layer:
   - **Identify Tool**: Click to see values
   - **Layer Properties**: Adjust styling and symbology
   - **Temporal Controller**: Animate time-series data

### Cross-Section Plotting

1. Select a variable with layer data
2. Click **Plot Cross-Section**
3. Draw a line on the map
4. A plot window will show the cross-section through the model layers

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

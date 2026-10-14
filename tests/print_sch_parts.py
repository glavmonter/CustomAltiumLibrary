import sys
import json
import svgwrite
import pyaltiumlib

lib_file = sys.argv[1]
LibFile = pyaltiumlib.read(lib_file)
if LibFile.LibType != 'Schematic':
    print(f'Error: {lib_file} is not a schematic library file.')
    sys.exit(1)

all_parts = LibFile.list_parts()
for component in all_parts:
    print(f'Component: {component}')
    component = LibFile.get_part(component)
    dwg = svgwrite.Drawing(f"img_sch/{component.Name}.svg", size=(400, 400))
    component.draw_svg(dwg, 400, 400)
    dwg.save()

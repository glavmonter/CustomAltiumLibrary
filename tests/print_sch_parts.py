import sys
import json
import svgwrite
import pyaltiumlib
from pyaltiumlib.datatypes import parametercollection

_original_parse = parametercollection.ParameterCollection.parse

def _parse_ansi(self, data):
    if isinstance(data, (bytes, bytearray)):
        data = bytes(data).decode('cp1251', 'replace')
    return _original_parse(self, data)

parametercollection.ParameterCollection.parse = _parse_ansi

lib_file = sys.argv[1]
LibFile = pyaltiumlib.read(lib_file)
if LibFile.LibType != 'Schematic':
    print(f'Error: {lib_file} is not a schematic library file.')
    sys.exit(1)

all_parts = LibFile.list_parts()
for component in all_parts:
    print(f'Component: {component}')
    component = LibFile.get_part(component)
    dwg = svgwrite.Drawing(f"img_sch/{component.Name.replace('/', '_').replace('\\', '_')}.svg", size=(400, 400))
    component.draw_svg(dwg, 400, 400)
    dwg.save()

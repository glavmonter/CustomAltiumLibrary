import sys
import json
import svgwrite
import pyaltiumlib
from pyaltiumlib import PcbLib
from pyaltiumlib.pcblib.footprint import PcbLibFootprint
from pyaltiumlib.datatypes import parametercollection
from pyaltiumlib.datatypes import PCBLayerKind

import logging
logging.basicConfig(level=logging.DEBUG, force=True)

_original_parse = parametercollection.ParameterCollection.parse

def _parse_ansi(self, data):
    if isinstance(data, (bytes, bytearray)):
        data = bytes(data).decode('cp1251', 'replace')
    return _original_parse(self, data)

parametercollection.ParameterCollection.parse = _parse_ansi

PCBLayerKind._map.update({
    0x1e: 'BoardShape',
    0x10: 'TopDimensions',
    0x11: 'BottomDimensions'
})

lib_file = sys.argv[1]
LibFile = pyaltiumlib.read(lib_file)

layers = {
    'BoardShape': 'Mechanical 1',
    'TopAssembly': 'Mechanical 21',
    'BottomAssembly': 'Mechanical 22',
    'TopDesignator': 'Mechanical 23',
    'BottomDesignator': 'Mechanical 24',
    'TopComponentOutline': 'Mechanical 27',
    'BottomComponentOutline': 'Mechanical 28',
    'TopCourtyard': 'Mechanical 15',
    'BottomCourtyard': 'Mechanical 16',
    'Top3DBody': 'Mechanical 13',
    'Bottom3DBody': 'Mechanical 14',
}

required_layers_with_primitives = [
    'TopCourtyard',
    'TopAssembly',
    'TopDesignator',
]

layers_without_primitives = [
    'BoardShape'
]

errors = []

TopCourtyard = LibFile.get_layer(kind='TopCourtyard')

for l in LibFile.Layers:
    print(f'id: {l.id}, name: \'{l.name}\', type: \'{l.layer_type}\'')

def lib_check_layers(lib: PcbLib, errors: []) -> []:
    for k, v in layers.items():
        layer = lib.get_layer(kind=k)
        if layer is None:
            errors.append(f'Layer \'{k}\' not found or invalid')
            continue
        if layer.name != v:
            errors.append(f'Layer \'{k}\' on invalid Mechanical. Required \'{v}\', but found \'{layer.name}\'')

    return errors

def check_component(component: PcbLibFootprint, errors: []) -> []:

    return errors


lib_check_layers(LibFile, errors)
check_component(LibFile.Parts[0], errors)

if len(errors) > 0:
    print('errors:')
    print('\n'.join(errors))
else:
    print('no errors')

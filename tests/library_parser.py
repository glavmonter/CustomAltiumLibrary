import sys
import pyaltiumlib

lib_file = sys.argv[1]

LibFile = pyaltiumlib.read(lib_file)
json = LibFile.read_meta()
all_parts = LibFile.list_parts()

print(f'Json: {json}')
print(f'all_parts: {all_parts}')

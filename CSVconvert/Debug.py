import sarracen
import os

# Read one dump file
# WSL python3; point-mass dumps are no longer on disk (solarsystem/ removed) -- set to a real dump.
dump_file = "/home/mboyle/Honours/solarsystem/solarsystem1_00001"

result = sarracen.read_phantom(dump_file, separate_types='all')
sdf_sinks = result[-1]

# Print available info
print("=== COLUMNS ===")
print(sdf_sinks.columns.tolist())

print("\n=== SHAPE ===")
print(sdf_sinks.shape)

print("\n=== FIRST ROW ===")
print(sdf_sinks.head(1))

print("\n=== DATA TYPES ===")
print(sdf_sinks.dtypes)

print("\n=== PARAMETERS/METADATA ===")
print(sdf_sinks.params)

print("\n=== SAMPLE VALUES (first particle) ===")
print(sdf_sinks.iloc[0])
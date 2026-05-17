import sarracen
import numpy as np
import json

def phantom_to_points(dump_file, output_path):
    sdf = sarracen.read_phantom(dump_file)
    
    positions = sdf[['x', 'y', 'z']].to_numpy()
    
    rho = sdf['rho'].to_numpy()
    rho_norm = (rho - rho.min()) / (rho.max() - rho.min())
    
    vmag = np.sqrt(sdf['vx']**2 + sdf['vy']**2 + sdf['vz']**2)
    vmag_norm = (vmag - vmag.min()) / (vmag.max() - vmag.min())
    
    h = sdf['h'].to_numpy()
    
    points = {
        'positions': positions.tolist(),
        'density':   rho_norm.tolist(),
        'velocity':  vmag_norm.tolist(),
        'smoothing': h.tolist(),
    }
    
    with open(output_path, 'w') as f:
        json.dump(points, f)
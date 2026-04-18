import numpy as np
import cv2 as cv

def spheres_noise(kgrid, base_val, min_val, max_val, min_rad, max_rad, seed, dbg_file=None):
    np.random.seed(seed)
    max_val -= base_val
    min_val -= base_val
    # result = np.ones([kgrid.Nx, kgrid.Ny, kgrid.Nz], dtype=float) * base_val
    # result[10:-10:, 280:, :] = 250
    n_spheres = np.random.randint(3, 16)
    radii = np.random.random(n_spheres) * (max_rad - min_rad) + min_rad
    xs = np.random.random(radii.size) * (radii + kgrid.Nx) - radii / 2
    ys = np.random.random(radii.size) * (radii + kgrid.Ny) - radii / 2
    zs = np.random.random(radii.size) * (radii + kgrid.Nz) - radii / 2
    vals = np.random.random(radii.size) * (max_val - min_val) + min_val
    spheres = []
    for r, v, x, y, z in zip(radii, vals, xs, ys, zs):
        spheres.append({
            'radius': r,
            'value': v,
            'x': x,
            'y': y,
            'z': z,
        })
        
    shape = (kgrid.Nx, kgrid.Ny, kgrid.Nz)
    ix, iy, iz = np.indices(shape)

    cx = np.array([s['x']      for s in spheres]).reshape(-1, 1, 1, 1)
    cy = np.array([s['y']      for s in spheres]).reshape(-1, 1, 1, 1)
    cz = np.array([s['z']      for s in spheres]).reshape(-1, 1, 1, 1)
    r  = np.array([s['radius'] for s in spheres]).reshape(-1, 1, 1, 1)
    v  = np.array([s['value']  for s in spheres]).reshape(-1, 1, 1, 1)

    dist_sq = (ix - cx)**2 + (iy - cy)**2 + (iz - cz)**2
    dist    = np.sqrt(dist_sq)

    # Normalized distance: 0.0 at center, 1.0 at edge, >1.0 outside
    t = np.clip(dist / r, 0.0, 1.0)

    falloff = 'quadratic'

    match falloff:
        case 'none':
            weight = np.where(dist <= r, 1.0, 0.0)
        case 'linear':
            weight = 1.0 - t                          # 1 → 0 linearly
        case 'quadratic':
            weight = 1.0 - t**2                       # faster near edge
        case 'smooth':
            weight = 1.0 - (3 * t**2 - 2 * t**3)     # smooth step, zero derivative at both ends
        case _:
            raise ValueError(f"Unknown falloff: '{falloff}'")
 
    weight = np.where(dist <= r, weight, 0.0)

    # Split positive and negative spheres
    pos_mask = v > 0
    neg_mask = v < 0

    # Positive spheres: push from 0 toward max_val
    decay = 2
    pos_strength = np.where(pos_mask, np.clip(weight * v / max_val, 0.0, 1.0), 0.0)
    pos_remaining = np.prod((1.0 - pos_strength) ** decay, axis=0)
    pos = max_val * (1.0 - pos_remaining)

    # Negative spheres: push from 0 toward min_val
    neg_strength = np.where(neg_mask, np.clip(weight * v / min_val, 0.0, 1.0), 0.0)
    neg_remaining = np.prod((1.0 - neg_strength) ** decay, axis=0)
    neg = min_val * (1.0 - neg_remaining)

    # Combine: outside all spheres both terms are 0, so result is 0
    arr = pos + neg

    arr += base_val
    
    if dbg_file is not None:
        slice = arr[:, :, arr.shape[-1] // 2]
        slice -= slice.min()
        slice /= slice.max()
        slice *= 255
        cv.imwrite(dbg_file, slice.astype(np.uint8))

    return arr
